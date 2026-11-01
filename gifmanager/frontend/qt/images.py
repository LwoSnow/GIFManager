"""Native image pipeline: bindings to the Rust `gifmanager_native` library.

This module is the ONLY place that knows the native library exists. Everything
above it (the animation engine, the thumbnail loader) asks a question and gets
either a result or `None`, and falls back to the pure-Qt path. That is what makes
the native library an optimisation rather than a requirement: a checkout without
a Rust toolchain still runs, just with GUI-thread decoding.

# Why a C ABI through `ctypes`

The library exports plain C functions rather than a CPython extension module, so
one binary serves every Python 3.10+ interpreter and the boundary is explicit. The
cost is that ownership must be spelled out, which is why every returned buffer is
read into a Python `bytes` and the native allocation is released in the same
function that obtained it.

# Buffer contract

Every buffer is RGBA8, row-major, tightly packed (`stride == width * 4`). The Qt
layer wraps it as `QImage.Format_RGBA8888` with no conversion.

原生图像管线：到 Rust `gifmanager_native` 库的绑定。

本模块是"唯一"知道该原生库存在的地方。它之上的所有代码（动画引擎、缩略图加载器）
提出一个问题并得到结果或 `None`，然后回退到纯 Qt 路径。这正是让原生库成为"优化项"
而非"必需项"的原因：没有 Rust 工具链的源码目录照样能跑，只是解码发生在界面线程。

# 为什么用 C ABI 加 `ctypes`

该库导出普通 C 函数而非 CPython 扩展模块，因此一个二进制服务于任意 Python 3.10+
解释器，且边界是显式的。代价是所有权必须写明，因此每个返回的缓冲都在获取它的同一个
函数里被读入 Python `bytes` 并释放原生分配。

# 缓冲约定

每个缓冲都是 RGBA8、行主序、紧密排列（`stride == width * 4`）。Qt 侧直接以
`QImage.Format_RGBA8888` 包装，不做任何转换。
"""
import ctypes
import dataclasses
import logging
import os
import shutil
import subprocess
import sys
import threading
from ctypes import c_char_p, c_int, c_uint32, c_uint64, c_void_p

from gifmanager.platform.base import native_library_names

log = logging.getLogger("GIFManager")

# Environment variables that control library discovery.
#
# `_ENV_LIBRARY` points at an explicit build. `_ENV_DISABLE` forces the pure-Qt
# path, which is how the fallback is TESTED rather than assumed: pointing the
# library override at a nonexistent file does NOT work, because the search then
# continues through the other candidates and finds the real library.
#
# 控制库发现的环境变量。
#
# `_ENV_LIBRARY` 指向显式构建。`_ENV_DISABLE` 强制走纯 Qt 路径——这正是让回退路径
# 被"测试"而不是被假设的方式：把库覆盖指向一个不存在的文件"并不"管用，因为搜索会
# 继续遍历其余候选并找到真实的库。
ENV_LIBRARY = "GIFMANAGER_NATIVE_LIB"
ENV_DISABLE = "GIFMANAGER_NATIVE_DISABLE"

# Values of `ENV_DISABLE` that mean "off" / `ENV_DISABLE` 中表示"关闭"的取值
_DISABLED_VALUES = frozenset({"1", "true", "yes", "on"})

# Library file name per platform, delegated so the rule lives in one place.
#
# This used to be a flat tuple of all three names, which meant Linux tried
# `gifmanager_native.dll` FIRST - a stale artefact a Windows build had left in
# `native/target/release/` - `dlopen`ed a PE binary and reported "invalid ELF header", then fell
# through to a `.so` that did not exist. See `platform.base.native_library_names` for the full
# account, including why one helper rather than a constant per loader.
# 各平台的库文件名，委托出去，使规则只存在于一处。
#
# 这里过去是三平台名称的平铺元组，意味着 Linux 会"先"尝试 `gifmanager_native.dll`——一个 Windows
# 构建遗留在 `native/target/release/` 的过期产物——`dlopen` 一个 PE 二进制并报告
# "invalid ELF header"，然后落到并不存在的 `.so`。完整说明见
# `platform.base.native_library_names`，包括为什么用一个辅助函数而不是每个加载器一个常量。
LIBRARY_NAMES = native_library_names("gifmanager_native")

# Where a development build ends up relative to the crate root, and where a
# packaged build is expected to carry it.
# 开发构建产物相对于 crate 根的位置，以及打包版应携带它的位置。
_DEV_PROFILE_DIRS = ("release", "debug")

# Error codes returned by the library / 库返回的错误码
ERR_NONE = 0
ERR_BAD_ARGUMENT = 1
ERR_IO = 2
ERR_DECODE = 3
ERR_UNSUPPORTED = 4

_ERROR_NAMES = {
    ERR_BAD_ARGUMENT: "bad argument",
    ERR_IO: "cannot read the file",
    ERR_DECODE: "cannot decode the image",
    ERR_UNSUPPORTED: "unsupported operation",
}

# Set when the library is absent, so the explanation is logged once instead of
# on every call.
# 库缺失时置位，使说明只记录一次而不是每次调用都记录。
_reported_missing = False

_lock = threading.RLock()


class NativeError(RuntimeError):
    # Raised when the library is present but a call fails /
    # 库存在但调用失败时抛出
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(f"[{_ERROR_NAMES.get(code, code)}] {message}")


@dataclasses.dataclass(frozen=True)
class DecodedAnimation:
    # Every frame of a GIF, already scaled.
    #
    # `frames` holds owned `bytes` objects, so nothing here depends on the native
    # library still being loaded or on a `free` having been called at the right
    # moment.
    # GIF 的全部帧，已完成缩放。
    #
    # `frames` 持有由 Python 拥有的 `bytes` 对象，因此这里没有任何东西依赖原生库仍然
    # 被加载，也不依赖 `free` 在正确时机被调用。
    width: int
    height: int
    frames: tuple
    delays: tuple

    @property
    def frame_bytes(self):
        return self.width * self.height * 4

    @property
    def frame_count(self):
        return len(self.frames)


@dataclasses.dataclass(frozen=True)
class DecodedThumbnail:
    # One still image, already scaled into its box /
    # 一张静态图，已缩放进其范围
    width: int
    height: int
    pixels: bytes

    @property
    def frame_bytes(self):
        return len(self.pixels)


# ---------------------------------------------------------------------------
# Library loading / 库加载
# ---------------------------------------------------------------------------

def is_disabled():
    # True when the pure-Qt path was requested explicitly /
    # 显式请求纯 Qt 路径时为 True
    return str(os.environ.get(ENV_DISABLE, "")).strip().lower() in _DISABLED_VALUES


def _library_candidates():
    # Search order: an explicit environment override, the packaged resources
    # directory, then a development build under `native/target/<profile>`.
    #
    # The development locations are searched so a contributor who has just run
    # `cargo build --release` gets the native path immediately, without a copy
    # step that would silently go stale.
    #
    # Returns an empty sequence when `ENV_DISABLE` is set, so the caller's search
    # loop finds nothing and the fallback runs — which is what makes
    # `tests/smoke_native_contract.py` able to exercise the fallback for real.
    # 搜索顺序：显式环境变量覆盖、随包资源目录，然后是 `native/target/<profile>`
    # 下的开发构建。
    #
    # 之所以搜索开发位置，是为了让刚运行过 `cargo build --release` 的贡献者立刻用上
    # 原生路径，而无需一个会悄悄过期的复制步骤。
    #
    # 设置 `ENV_DISABLE` 时返回空序列，使调用方的搜索循环什么也找不到并走到回退路径
    # ——这正是让 `tests/smoke_native_contract.py` 能真正演练回退的原因。
    if is_disabled():
        return

    override = os.environ.get(ENV_LIBRARY)
    if override:
        yield override

    from gifmanager.core import paths

    for directory in (paths.resources_dir(), paths.package_dir(),
                      paths.executable_dir()):
        for name in LIBRARY_NAMES:
            yield os.path.join(directory, name)

    root = paths.project_root()
    for profile in _DEV_PROFILE_DIRS:
        for name in LIBRARY_NAMES:
            yield os.path.join(root, "native", "target", profile, name)

    # A system-wide install, as a last resort /
    # 系统级安装，作为最后手段
    for name in LIBRARY_NAMES:
        found = shutil.which(name)
        if found:
            yield found


def library_path():
    # Path of a usable library, or None / 可用库的路径，无则 None
    for candidate in _library_candidates():
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


class _Api:
    # Loaded library plus the prototypes of every function used here.
    #
    # Every prototype declares argtypes and restype. Without them `ctypes`
    # defaults to `c_int` for both, which TRUNCATES 64-bit pointers on 64-bit
    # Windows — the same class of bug that the previous release had to guard
    # against for window handles.
    # 已加载的库，以及此处用到的每个函数的原型。
    #
    # 每个原型都声明 argtypes 与 restype。缺少它们时 `ctypes` 两者都默认为
    # `c_int`，在 64 位 Windows 上会"截断" 64 位指针——正是上一版本不得不为窗口句柄
    # 防范的那一类错误。
    def __init__(self, path):
        self.path = path
        self.lib = ctypes.CDLL(path)
        lib = self.lib

        lib.gifmanager_version.restype = c_char_p
        lib.gifmanager_version.argtypes = ()

        lib.gifmanager_last_error_code.restype = c_int
        lib.gifmanager_last_error_code.argtypes = ()

        lib.gifmanager_last_error_message.restype = c_char_p
        lib.gifmanager_last_error_message.argtypes = ()

        lib.gifmanager_thread_count.restype = c_uint32
        lib.gifmanager_thread_count.argtypes = ()

        lib.gifmanager_probe.restype = c_int
        lib.gifmanager_probe.argtypes = ()

        lib.gifmanager_decode_gif.restype = c_void_p
        lib.gifmanager_decode_gif.argtypes = (c_char_p, c_uint32)

        lib.gifmanager_frames_width.restype = c_uint32
        lib.gifmanager_frames_width.argtypes = (c_void_p,)
        lib.gifmanager_frames_height.restype = c_uint32
        lib.gifmanager_frames_height.argtypes = (c_void_p,)
        lib.gifmanager_frames_count.restype = c_uint32
        lib.gifmanager_frames_count.argtypes = (c_void_p,)
        lib.gifmanager_frames_frame_bytes.restype = c_uint64
        lib.gifmanager_frames_frame_bytes.argtypes = (c_void_p,)
        lib.gifmanager_frames_offset.restype = c_uint64
        lib.gifmanager_frames_offset.argtypes = (c_void_p, c_uint32)
        lib.gifmanager_frames_delay.restype = c_uint32
        lib.gifmanager_frames_delay.argtypes = (c_void_p, c_uint32)
        lib.gifmanager_frames_copy.restype = c_uint64
        lib.gifmanager_frames_copy.argtypes = (c_void_p, c_uint32, c_void_p)
        lib.gifmanager_frames_free.restype = None
        lib.gifmanager_frames_free.argtypes = (c_void_p,)

        lib.gifmanager_decode_thumbnail.restype = c_void_p
        lib.gifmanager_decode_thumbnail.argtypes = (c_char_p, c_uint32)
        lib.gifmanager_thumbnail_width.restype = c_uint32
        lib.gifmanager_thumbnail_width.argtypes = (c_void_p,)
        lib.gifmanager_thumbnail_height.restype = c_uint32
        lib.gifmanager_thumbnail_height.argtypes = (c_void_p,)
        lib.gifmanager_thumbnail_bytes.restype = c_uint64
        lib.gifmanager_thumbnail_bytes.argtypes = (c_void_p,)
        lib.gifmanager_thumbnail_copy.restype = c_uint64
        lib.gifmanager_thumbnail_copy.argtypes = (c_void_p, c_void_p)
        lib.gifmanager_thumbnail_free.restype = None
        lib.gifmanager_thumbnail_free.argtypes = (c_void_p,)

    # ---- error plumbing / 错误传递 ---------------------------------------

    def last_error(self):
        code = self.lib.gifmanager_last_error_code()
        if code == ERR_NONE:
            return None
        raw = self.lib.gifmanager_last_error_message()
        message = raw.decode("utf-8", "replace") if raw else ""
        return NativeError(code, message)

    @property
    def version(self):
        raw = self.lib.gifmanager_version()
        return raw.decode("ascii", "replace") if raw else "unknown"

    def thread_count(self):
        return int(self.lib.gifmanager_thread_count())

    def probe(self):
        # Non-zero means the library linked but something it needs is broken /
        # 非零表示库已链接但它需要的某样东西出了问题
        return int(self.lib.gifmanager_probe()) == ERR_NONE


_api = None
_api_loaded = False


def api():
    # The loaded library, or None when it is not available.
    #
    # Loaded once and cached: `CDLL` on Windows keeps a handle, and reloading per
    # call would add a file-system lookup to a per-frame path.
    # 已加载的库；不可用时返回 None。
    #
    # 只加载一次并缓存：Windows 上 `CDLL` 会持有句柄，逐次调用重新加载会给逐帧路径
    # 加上一次文件系统查找。
    global _api, _api_loaded, _reported_missing
    with _lock:
        if _api_loaded:
            return _api
        _api_loaded = True
        path = library_path()
        if not path:
            if not _reported_missing:
                _reported_missing = True
                log.info(
                    "native: no gifmanager_native library found; using the "
                    "pure-Qt image path (build it with "
                    "`cargo build --release` in native/) / 未找到原生库，"
                    "使用纯 Qt 图像路径")
            _api = None
            return None
        try:
            candidate = _Api(path)
        except OSError as exc:
            log.warning("native: cannot load %s -> %s", path, exc)
            _api = None
            return None
        if not candidate.probe():
            log.warning("native: %s failed its self-check", path)
            _api = None
            return None
        log.info("native: loaded %s (version %s, %s scaling threads)",
                 path, candidate.version, candidate.thread_count())
        _api = candidate
        return _api


def available():
    # True when the native pipeline can be used / 原生管线可用时为 True
    return api() is not None


def reset():
    # Drop the cached library. For tests that point `GIFMANAGER_NATIVE_LIB` at a
    # different build. / 丢弃已缓存的库。供那些把 `GIFMANAGER_NATIVE_LIB` 指向
    # 另一份构建的测试使用。
    global _api, _api_loaded, _reported_missing
    with _lock:
        _api = None
        _api_loaded = False
        _reported_missing = False


def describe():
    # Diagnostics for the settings page's system-information section /
    # 供设置页系统信息区块使用的诊断信息
    loaded = api()
    return {
        "available": loaded is not None,
        "path": loaded.path if loaded else "",
        "version": loaded.version if loaded else "",
        "threads": loaded.thread_count() if loaded else 0,
        "candidates": [c for c in _library_candidates() if c],
    }


# ---------------------------------------------------------------------------
# Decoding / 解码
# ---------------------------------------------------------------------------

def decode_gif(path, target=0):
    # Decode every frame of a GIF, scaled so its longest side is at most
    # `target` (0 keeps the source size).
    #
    # Returns a `DecodedAnimation`, or None when the native library is
    # unavailable or the file cannot be decoded — never raises for a bad file,
    # because the caller's fallback path handles exactly that case.
    # 解码 GIF 的全部帧，并缩放使最长边不超过 `target`（0 表示保持源尺寸）。
    #
    # 返回 `DecodedAnimation`；原生库不可用或文件无法解码时返回 None——绝不因文件有
    # 问题而抛异常，因为调用方的回退路径处理的正是这种情况。
    loaded = api()
    if loaded is None or not path:
        return None

    encoded = os.fsencode(path)
    handle = loaded.lib.gifmanager_decode_gif(encoded, int(target))
    if not handle:
        error = loaded.last_error()
        if error is not None:
            log.warning("native: cannot decode %s -> %s", path, error)
        return None

    try:
        width = int(loaded.lib.gifmanager_frames_width(handle))
        height = int(loaded.lib.gifmanager_frames_height(handle))
        count = int(loaded.lib.gifmanager_frames_count(handle))
        frame_bytes = int(loaded.lib.gifmanager_frames_frame_bytes(handle))
        if width <= 0 or height <= 0 or count <= 0 or frame_bytes <= 0:
            log.warning("native: %s decoded to an empty animation", path)
            return None

        # One reusable destination buffer: `ctypes` cannot expose a Python
        # `bytes` as writable, so the copy goes through a `bytearray` and is
        # frozen per frame. Reusing the buffer keeps allocation off the per-frame
        # path.
        # 一个可复用的目标缓冲：`ctypes` 无法把 Python `bytes` 暴露为可写，因此复制
        # 经 `bytearray` 进行、逐帧冻结。复用缓冲使分配不落在逐帧路径上。
        destination = (ctypes.c_ubyte * frame_bytes)()
        frames = []
        delays = []
        for index in range(count):
            copied = int(loaded.lib.gifmanager_frames_copy(
                handle, index, destination))
            if copied != frame_bytes:
                log.warning("native: frame %s of %s copied %s of %s bytes",
                            index, path, copied, frame_bytes)
                return None
            frames.append(bytes(destination))
            delays.append(int(loaded.lib.gifmanager_frames_delay(handle, index)))
        return DecodedAnimation(
            width=width, height=height,
            frames=tuple(frames), delays=tuple(delays))
    finally:
        # Released in the same function that acquired it, on every path.
        # 在获取它的同一个函数内、在每条路径上释放。
        loaded.lib.gifmanager_frames_free(handle)


def decode_thumbnail(path, box):
    # Decode a still image and scale it into a `box` x `box` area, preserving the
    # aspect ratio (never upscaling).
    #
    # Returns a `DecodedThumbnail`, or None on any failure so the caller can fall
    # back to `QImage`.
    # 解码静态图并等比缩放进 `box` x `box` 区域（绝不放大）。
    #
    # 返回 `DecodedThumbnail`；任何失败都返回 None，使调用方回退到 `QImage`。
    loaded = api()
    if loaded is None or not path:
        return None

    handle = loaded.lib.gifmanager_decode_thumbnail(
        os.fsencode(path), int(box))
    if not handle:
        error = loaded.last_error()
        if error is not None:
            log.warning("native: cannot decode thumbnail %s -> %s", path, error)
        return None

    try:
        width = int(loaded.lib.gifmanager_thumbnail_width(handle))
        height = int(loaded.lib.gifmanager_thumbnail_height(handle))
        total = int(loaded.lib.gifmanager_thumbnail_bytes(handle))
        if width <= 0 or height <= 0 or total <= 0:
            return None
        destination = (ctypes.c_ubyte * total)()
        copied = int(loaded.lib.gifmanager_thumbnail_copy(handle, destination))
        if copied != total:
            return None
        return DecodedThumbnail(width=width, height=height,
                                pixels=bytes(destination))
    finally:
        loaded.lib.gifmanager_thumbnail_free(handle)


__all__ = [
    "ENV_DISABLE",
    "ENV_LIBRARY",
    "ERR_BAD_ARGUMENT",
    "ERR_DECODE",
    "ERR_IO",
    "ERR_NONE",
    "ERR_UNSUPPORTED",
    "LIBRARY_NAMES",
    "DecodedAnimation",
    "DecodedThumbnail",
    "NativeError",
    "api",
    "available",
    "decode_gif",
    "decode_thumbnail",
    "describe",
    "is_disabled",
    "library_path",
    "reset",
]
