"""Native GIF playback support: decodes GIF frames off the GUI thread via
the bundled gifdec.dll (plain-C GIF89a decoder), caches the decoded frames,
and plays them back with a QTimer on the GUI thread.

QMovie decodes GIF frames on the GUI thread, which is the main cause of
scroll jank when many animated stickers are visible. With this module the
decode happens once in a background worker thread and playback is just a
pixmap swap. Falls back to QMovie when the DLL is unavailable (e.g. a dev
checkout without a compiled gifdec.dll, or a non-Windows build).
原生 GIF 播放支持：通过内置 gifdec.dll（纯 C GIF89a 解码器）在 GUI 线程
之外解码 GIF 帧、缓存解码结果，并在 GUI 线程用 QTimer 播放。

QMovie 在 GUI 线程解码 GIF 帧，是表情包多时滚动卡顿的主因。本模块在后台
工作线程一次性解码全部帧，播放时只是切换 pixmap。DLL 不可用时回退 QMovie
（例如未编译 gifdec.dll 的开发目录，或非 Windows 构建）。"""
import ctypes
import os
import sys
import time
from ctypes import POINTER, c_char_p, c_int, c_uint8, c_void_p, byref

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QImage

# Decoded-frame cache budget: ~48 MB of RGBA frames / 解码帧缓存预算：约 48MB
_CACHE_PIXEL_LIMIT = 12_000_000


def _dll_path():
    # Source checkout: app/utils/gifdec.dll next to this module. Packaged
    # (PyInstaller onedir): _internal/app/utils/gifdec.dll, then exe dir.
    # 源码目录：本模块同目录 app/utils/gifdec.dll；打包版（PyInstaller
    # onedir）：_internal/app/utils/gifdec.dll，其次 exe 同级目录。
    d = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, "_internal", "app", "utils", "gifdec.dll"))
        candidates.append(os.path.join(exe_dir, "gifdec.dll"))
    candidates.append(os.path.join(d, "gifdec.dll"))
    candidates.append(os.path.join(os.path.dirname(d), "gifdec.dll"))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


_lib = None


def _dll():
    # Load lazily (once); None when the DLL is missing or fails to load
    # 惰性加载（仅一次）；DLL 缺失或加载失败时返回 None
    global _lib
    if _lib is None:
        p = _dll_path()
        if p:
            try:
                lib = ctypes.CDLL(p)
                lib.gif_open.restype = c_void_p
                lib.gif_open.argtypes = [
                    c_char_p, POINTER(c_int), POINTER(c_int), POINTER(c_int)]
                lib.gif_frame_delay_ms.restype = c_int
                lib.gif_frame_delay_ms.argtypes = [c_void_p, c_int]
                lib.gif_frame.restype = c_int
                lib.gif_frame.argtypes = [c_void_p, c_int, POINTER(c_uint8)]
                lib.gif_close.argtypes = [c_void_p]
                _lib = lib
            except Exception:
                _lib = None
    return _lib


def available():
    # True when the native decoder DLL is usable / 原生解码 DLL 是否可用
    return _dll() is not None


# Decode every frame of a GIF into scaled QImages. Returns (frames, delays)
# or None on failure. Runs in the worker thread.
# 把 GIF 的所有帧解码为缩放后的 QImage 列表。返回 (frames, delays) 或 None。
# 在工作线程中执行。
def decode_all(path, target):
    lib = _dll()
    if lib is None:
        return None
    w, h, n = c_int(), c_int(), c_int()
    handle = lib.gif_open(path.encode("utf-8"), byref(w), byref(h), byref(n))
    if not handle:
        return None
    try:
        nf = n.value
        if nf <= 0:
            return None
        delays = [lib.gif_frame_delay_ms(handle, i) for i in range(nf)]
        buf = (c_uint8 * (w.value * h.value * 4))()
        frames = []
        for i in range(nf):
            if not lib.gif_frame(handle, i, buf):
                break
            # QImage wraps the buffer without owning it; .copy() takes an
            # owned copy (the buffer is reused for the next frame).
            # QImage 不拥有缓冲区；.copy() 复制一份（缓冲区会被下一帧复用）。
            img = QImage(buf, w.value, h.value, w.value * 4,
                         QImage.Format.Format_RGBA8888).copy()
            if target and (img.width() > target or img.height() > target):
                img = img.scaled(
                    target, target,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            frames.append(img)
        if not frames:
            return None
        return frames, delays
    finally:
        lib.gif_close(handle)


# ---- decoded-frame cache / 解码帧缓存 -----------------------------------

_frames_cache = {}   # path -> [frames, delays, last_used] / 路径 -> 缓存项
_cache_pixels = 0


def cache_get(path):
    # (frames, delays) or None when not cached / 未缓存时返回 None
    e = _frames_cache.get(path)
    if e:
        e[2] = time.monotonic()
        return e[0], e[1]
    return None


def _cache_put(path, frames, delays):
    global _cache_pixels
    pixels = sum(f.width() * f.height() for f in frames)
    _frames_cache[path] = [frames, delays, time.monotonic()]
    _cache_pixels += pixels
    while _cache_pixels > _CACHE_PIXEL_LIMIT and len(_frames_cache) > 1:
        oldest = min(_frames_cache, key=lambda k: _frames_cache[k][2])
        if oldest == path:
            break  # never evict the freshly inserted entry / 不淘汰刚插入项
        old = _frames_cache.pop(oldest)
        _cache_pixels -= sum(f.width() * f.height() for f in old[0])


# ---- background decode worker / 后台解码工作线程 --------------------------

class _DecodeWorker(QObject):
    request = Signal(str, int)   # path, target size / 路径、目标尺寸
    decoded = Signal(str)        # path (frames are in the cache) / 路径（帧已入缓存）

    def __init__(self):
        super().__init__()
        self._pending = set()
        self.request.connect(self.on_request)

    @Slot(str, int)
    def on_request(self, path, target):
        if path in self._pending:
            return  # one in-flight decode per path / 同一路径只解码一次
        self._pending.add(path)
        try:
            result = decode_all(path, target)
            if result is not None:
                _cache_put(path, result[0], result[1])
        finally:
            self._pending.discard(path)
        self.decoded.emit(path)


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


def request_decode(path, target):
    # Ask the worker to decode a GIF; skip when it is already cached
    # 请求后台解码 GIF；已缓存时直接跳过
    if _dll() is None or _frames_cache.get(path) is not None:
        return
    _ensure_worker().request.emit(path, target)


def connect_decoded(handler):
    # Connect a GUI-thread handler to the decode-done signal
    # 连接解码完成信号（在 GUI 线程回调）
    _ensure_worker().decoded.connect(handler)


def shutdown():
    # Stop the worker thread at app quit / 应用退出时停止工作线程
    global _worker, _thread
    if _thread is not None:
        _thread.quit()
        _thread.wait(2000)
        _thread = None
        _worker = None


# Stop the worker thread on interpreter exit (also covers offscreen tests)
# 解释器退出时停止工作线程（也覆盖离屏测试场景）
import atexit
atexit.register(shutdown)
