"""Native GIF playback: decode off the GUI thread, play back as pixmap swaps.

`QMovie` decodes GIF frames on the GUI thread, which is the main cause of scroll
jank when many animated stickers are visible. Here the decode happens once on a
worker thread and playback is just a pixmap swap, so a screen full of animated
stickers scrolls smoothly.

The decoder itself is a small C library. Its FILE NAME differs per system
(`gifdec.dll`, `libgifdec.dylib`, `libgifdec.so`), and where a packaged build
puts it differs too, so the search is driven by
`gifmanager.platform.process.find_executable` instead of hard-coded `sys.frozen`
candidates. When the library is absent — a source checkout without a compiled
decoder, or a platform with no build — this module reports `available() == False`
and the widget falls back to `QMovie`, which is correct but decodes on the GUI
thread.

原生 GIF 播放：在界面线程之外解码，播放时只切换 pixmap。

`QMovie` 在界面线程解码 GIF 帧，是表情包多时滚动卡顿的主因。这里解码在后台工作线程
一次性完成，播放只是切换 pixmap，因此满屏动图也能流畅滚动。

解码器本身是一个小型 C 库。其"文件名"随系统不同（`gifdec.dll`、
`libgifdec.dylib`、`libgifdec.so`），打包版放置它的位置也不同，因此搜索由
`gifmanager.platform.process.find_executable` 驱动，而不是硬编码 `sys.frozen`
候选路径。库缺失时——未编译解码器的源码目录，或没有构建产物的平台——本模块报告
`available() == False`，控件回退到 `QMovie`：功能正确，但在界面线程解码。
"""
import atexit
import ctypes
import logging
import os
import time
from ctypes import POINTER, c_char_p, c_int, c_uint8, c_void_p, byref

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QImage

from gifmanager.frontend.qt import images
from gifmanager.platform import process

log = logging.getLogger("GIFManager")

# Decoded-frame cache budget: about 48 MB of RGBA frames /
# 解码帧缓存预算：约 48MB 的 RGBA 帧
CACHE_PIXEL_LIMIT = 12_000_000

# Library file names to try, in order. The bare `gifdec` entry lets the system
# loader apply its own naming rules as a last resort.
# 依次尝试的库文件名。最后的裸 `gifdec` 让系统加载器按自己的命名规则处理。
LIBRARY_NAMES = ("gifdec.dll", "libgifdec.dylib", "libgifdec.so", "gifdec")


def platform_library_names(platform_key=""):
    # The subset of `LIBRARY_NAMES` this platform can actually load.
    #
    # Trying all of them is not harmless: on Linux the list started with `gifdec.dll`, so
    # the loader attempted to `dlopen` a WINDOWS PE binary and reported
    # "invalid ELF header". That is a confusing failure — it names a file that exists and
    # says nothing about the platform mismatch — and it also means a `.dll` sitting in
    # `resources/` (shipped for Windows, or copied by a user) is preferred over a working
    # `.so` beside it. Absence is the correct answer for the other platforms' names.
    #
    # `platform_key` is accepted for a caller that knows the session (a test), and defaults
    # to the running interpreter.
    # 本平台"确实能加载"的 `LIBRARY_NAMES` 子集。
    #
    # 全部尝试并非无害：Linux 上列表以 `gifdec.dll` 开头，于是加载器试图 `dlopen` 一个
    # Windows PE 二进制并报告 "invalid ELF header"。那是个令人困惑的失败——它点名了一个存在
    # 的文件，却对平台不匹配只字不提——而且它还意味着 `resources/` 里的 `.dll`（为 Windows
    # 发布，或用户复制过来的）会优先于它旁边可用的 `.so`。对其他平台的名称而言，正确的答案是
    # "不尝试"。
    #
    # 接受 `platform_key` 是为了让知道会话的调用方（测试）使用，默认用当前解释器。
    import sys

    key = platform_key or sys.platform
    if key.startswith("win") or key == "cygwin":
        allowed = ("gifdec.dll", "gifdec")
    elif key == "darwin":
        allowed = ("libgifdec.dylib", "gifdec")
    else:
        allowed = ("libgifdec.so", "gifdec")
    return tuple(name for name in LIBRARY_NAMES if name in allowed)


def library_path():
    # Absolute path of a usable C decoder library, or None.
    #
    # The search covers the three layouts that actually occur: the source
    # checkout's `resources/`, a PyInstaller onedir bundle's `_internal/resources`
    # (both via `resources_dir()`), and a system-wide install on `PATH`. The
    # packaged layout that puts the library beside the package is checked too,
    # because that is where the old spec put it.
    #
    # NOTE: this deliberately does NOT include the Rust library. The Rust pipeline
    # has its own loader in `images.py` and a different file name, and looking for
    # it here would make `available()` claim the C path when only Rust is present.
    #
    # 可用的 C 解码库的绝对路径，无则 None。
    #
    # 搜索覆盖实际出现的三种布局：源码目录的 `resources/`、PyInstaller onedir 包的
    # `_internal/resources`（两者都经 `resources_dir()`），以及 `PATH` 上的系统级安装。
    # 也检查"把库放在包旁边"的打包布局，因为旧 spec 就是那样放的。
    #
    # 注意：此处刻意"不"包含 Rust 库。Rust 管线在 `images.py` 中有自己的加载器与不同的
    # 文件名，在此查找它会让 `available()` 在只有 Rust 存在时误报 C 路径可用。
    from gifmanager.core import paths

    names = platform_library_names()
    directories = (
        paths.resources_dir(),
        paths.package_dir(),
        paths.executable_dir(),
    )
    for directory in directories:
        for name in names:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate
    for name in names:
        found = process.find_executable(name)
        if found and os.path.isfile(found):
            return found
    return None


_lib = None
_lib_probed = False


def _dll():
    # Load lazily (once). None when the library is missing or fails to load,
    # which is a supported state rather than an error.
    # 惰性加载（仅一次）。库缺失或加载失败时返回 None——这是受支持的状态而非错误。
    global _lib, _lib_probed
    if _lib is not None:
        return _lib
    if _lib_probed:
        return None
    _lib_probed = True
    path = library_path()
    if not path:
        log.info("gif_player: no native decoder library found; "
                 "QMovie will be used instead")
        return None
    try:
        library = ctypes.CDLL(path)
        library.gif_open.restype = c_void_p
        library.gif_open.argtypes = [
            c_char_p, POINTER(c_int), POINTER(c_int), POINTER(c_int)]
        library.gif_frame_delay_ms.restype = c_int
        library.gif_frame_delay_ms.argtypes = [c_void_p, c_int]
        library.gif_frame.restype = c_int
        library.gif_frame.argtypes = [c_void_p, c_int, POINTER(c_uint8)]
        library.gif_close.argtypes = [c_void_p]
        _lib = library
        log.info("gif_player: native decoder loaded from %s", path)
    except (OSError, AttributeError) as exc:
        log.warning("gif_player: cannot load %s -> %s", path, exc)
        _lib = None
    return _lib


def available():
    # True when ANY decoder is usable.
    #
    # The Rust pipeline comes first because it decodes every frame in one native
    # call and scales them in parallel; the bundled C library is the older path;
    # `QMovie` on the GUI thread is the last resort. The caller only needs to know
    # whether playback is possible, not which of the three is doing it.
    # 任一解码器可用时返回 True。
    #
    # Rust 管线优先，因为它一次原生调用解码全部帧并并行缩放；随包的 C 库是较旧路径；
    # 界面线程上的 `QMovie` 是最后手段。调用方只需要知道"能否播放"，不需要知道三者中
    # 哪一个在工作。
    return images.available() or _dll() is not None


def decode_all(path, target):
    # Decode every frame of a GIF into scaled QImages.
    #
    # Returns (frames, delays) or None on failure. Runs on a worker thread.
    # 把 GIF 的全部帧解码为缩放后的 QImage。
    #
    # 返回 (帧列表, 延迟列表)，失败返回 None。在工作线程中执行。
    native = _decode_all_native(path, target)
    if native is not None:
        return native
    return _decode_all_c(path, target)


def _decode_all_native(path, target):
    # Decode through the Rust pipeline.
    #
    # The frames arrive as one contiguous RGBA buffer plus an offset table, and
    # each frame is wrapped as a `QImage` over the Python `bytes` it came in
    # without another pixel copy: `QImage` can reference a `bytes` object as long
    # as the caller keeps it alive, and `DecodedAnimation` holds every frame for
    # as long as the decoded list exists.
    #
    # Scaling happens inside the library, in parallel, which is the part that
    # replaces one `QImage.scaled` per frame on a single Python thread.
    # 经 Rust 管线解码。
    #
    # 帧以一整块连续 RGBA 缓冲加偏移表到达，每帧被包装为引用其 Python `bytes` 的
    # `QImage`，不再多做一次像素复制：只要调用方保持 `bytes` 存活，`QImage` 就可以
    # 引用它，而 `DecodedAnimation` 在解码列表存在期间持有每一帧。
    #
    # 缩放发生在库内部且并行，正是这一步取代了单个 Python 线程上每帧一次
    # `QImage.scaled`。
    decoded = images.decode_gif(path, target or 0)
    if decoded is None or not decoded.frames:
        return None
    stride = decoded.width * 4
    frames = []
    for payload in decoded.frames:
        image = QImage(payload, decoded.width, decoded.height, stride,
                       QImage.Format.Format_RGBA8888)
        if image.isNull():
            return None
        frames.append(image)
    return frames, list(decoded.delays)


def _decode_all_c(path, target):
    # Decode through the bundled C library, the path used before the Rust
    # pipeline existed and still used when it is unavailable.
    # 经随包的 C 库解码——Rust 管线出现之前使用的路径，在其不可用时仍然使用。
    library = _dll()
    if library is None:
        return None
    width, height, count = c_int(), c_int(), c_int()
    handle = library.gif_open(
        path.encode("utf-8"), byref(width), byref(height), byref(count))
    if not handle:
        return None
    try:
        frame_count = count.value
        if frame_count <= 0:
            return None
        delays = [library.gif_frame_delay_ms(handle, i) for i in range(frame_count)]
        buffer = (c_uint8 * (width.value * height.value * 4))()
        frames = []
        for index in range(frame_count):
            if not library.gif_frame(handle, index, buffer):
                break
            # QImage wraps the buffer without owning it; `.copy()` takes an
            # owned copy, because the buffer is reused for the next frame.
            # QImage 不拥有缓冲区；`.copy()` 复制一份，因为缓冲区会被下一帧复用。
            image = QImage(
                buffer, width.value, height.value, width.value * 4,
                QImage.Format.Format_RGBA8888).copy()
            if target and (image.width() > target or image.height() > target):
                image = image.scaled(
                    target, target,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            frames.append(image)
        if not frames:
            return None
        return frames, delays
    finally:
        library.gif_close(handle)


# ---- decoded-frame cache / 解码帧缓存 ------------------------------------

_frames_cache = {}   # path -> [frames, delays, last_used] / 路径 -> 缓存项
_cache_pixels = 0


def cache_get(path):
    # (frames, delays) or None when not cached / 未缓存时返回 None
    entry = _frames_cache.get(path)
    if entry:
        entry[2] = time.monotonic()
        return entry[0], entry[1]
    return None


def _cache_put(path, frames, delays):
    # Least-recently-used eviction under a pixel budget. The freshly inserted
    # entry is never evicted, so a GIF larger than the whole budget still plays.
    # 在像素预算下按最近最少使用淘汰。刚插入的项绝不被淘汰，因此比整个预算还大的
    # GIF 仍能播放。
    global _cache_pixels
    pixels = sum(frame.width() * frame.height() for frame in frames)
    _frames_cache[path] = [frames, delays, time.monotonic()]
    _cache_pixels += pixels
    while _cache_pixels > CACHE_PIXEL_LIMIT and len(_frames_cache) > 1:
        oldest = min(_frames_cache, key=lambda key: _frames_cache[key][2])
        if oldest == path:
            break
        evicted = _frames_cache.pop(oldest)
        _cache_pixels -= sum(f.width() * f.height() for f in evicted[0])


def clear_cache():
    # Drop every cached frame set / 清空全部缓存帧
    global _cache_pixels
    _frames_cache.clear()
    _cache_pixels = 0


# ---- background decode worker / 后台解码工作线程 --------------------------

class _DecodeWorker(QObject):
    # Priority decoding: requests carry a priority (lower = sooner) and the
    # worker takes the highest-priority pending request first, so a GIF scrolled
    # into view decodes before older off-screen ones.
    #
    # Without this, a long scroll through an all-animated group queued every
    # newly visible GIF behind every previously requested one and playback
    # lagged badly.
    # 优先级解码：请求带优先级（越小越先处理），worker 每次取最高优先级的待处理请求，
    # 因此滚动进视野的 GIF 会排在旧的视野外请求之前。
    #
    # 缺少这项时，长跨度滚动全动图分组会让每个新可见 GIF 都排在所有旧请求之后，
    # 播放严重滞后。
    request = Signal(str, int, int)   # path, target size, priority / 路径、目标尺寸、优先级
    decoded = Signal(str)             # path (frames are in the cache) / 路径（帧已入缓存）

    def __init__(self):
        super().__init__()
        # pending: path -> (priority, target). A zero-delay timer pumps one
        # decode per tick so the worker never blocks new requests.
        # pending：路径 -> (优先级, 目标尺寸)。零延迟定时器每 tick 解码一个，
        # worker 不会阻塞新请求。
        self._pending = {}
        self._processing = False
        self.request.connect(self.on_request)

    @Slot(str, int, int)
    def on_request(self, path, target, priority):
        self._pending[path] = (int(priority), int(target))
        if not self._processing:
            self._processing = True
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, self._pump_once)

    def _pump_once(self):
        if not self._pending:
            self._processing = False
            return
        path = min(self._pending, key=lambda key: self._pending[key][0])
        _priority, target = self._pending.pop(path)
        try:
            result = decode_all(path, target)
            if result is not None:
                _cache_put(path, result[0], result[1])
        finally:
            self.decoded.emit(path)
        if self._pending:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, self._pump_once)
        else:
            self._processing = False


_worker = None
_thread = None


def _ensure_worker():
    global _worker, _thread
    if _worker is None:
        _worker = _DecodeWorker()
        _thread = QThread()
        _thread.setObjectName("GifDecodeThread")
        _worker.moveToThread(_thread)
        _thread.start()
    return _worker


def request_decode(path, target, priority=100):
    # Ask the worker to decode a GIF; skipped when it is already cached.
    # Lower priority numbers decode first (the visible band uses roughly 0-9,
    # older requests fall back to 100).
    # 请求后台解码 GIF；已缓存时直接跳过。优先级数字越小越先解码（视野内大致用
    # 0-9，旧请求默认 100）。
    if _dll() is None or _frames_cache.get(path) is not None:
        return
    _ensure_worker().request.emit(path, int(target), int(priority))


def is_pending(path):
    return _worker is not None and path in _worker._pending


def connect_decoded(handler):
    # Connect a GUI-thread handler to the decode-done signal /
    # 连接解码完成信号（在界面线程回调）
    _ensure_worker().decoded.connect(handler)


def shutdown():
    # Stop the worker thread at application exit /
    # 应用退出时停止工作线程
    global _worker, _thread
    if _thread is not None:
        _thread.quit()
        _thread.wait(2000)
        _thread = None
        _worker = None


# Stop the worker thread on interpreter exit (also covers offscreen tests).
# Ordering matters: this module is imported by the emoji widgets, whose own
# atexit hooks drain the thumbnail pool — LIFO means the widget pools stop
# first, which is the safe order.
# 解释器退出时停止工作线程（也覆盖离屏测试）。顺序很重要：本模块被表情控件导入，
# 而控件自己的 atexit 钩子会排空缩略图线程池——后进先出意味着控件线程池先停，这是
# 安全的顺序。
atexit.register(shutdown)


__all__ = [
    "CACHE_PIXEL_LIMIT",
    "LIBRARY_NAMES",
    "available",
    "cache_get",
    "clear_cache",
    "connect_decoded",
    "decode_all",
    "is_pending",
    "library_path",
    "request_decode",
    "shutdown",
]
