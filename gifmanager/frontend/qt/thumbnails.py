"""Async thumbnail loading for the emoji grid.

Decoding an image on the GUI thread is what makes a grid of stickers stutter, so
thumbnails are decoded and scaled on a private thread pool and delivered back as
a `QImage` through a queued signal. `QImage` is used rather than `QPixmap`
because only `QImage` may be touched off the GUI thread.

The cache is deliberately explicit here rather than Qt's process-global
`QPixmapCache`: the global cache made the pixmap travel worker -> grid ->
global cache -> card by key, which hid the dependency between the grid and the
card behind a string. An injected cache keeps that contract visible and lets a
different front-end supply its own.

表情网格的异步缩略图加载。

在界面线程解码图片正是让满屏表情卡顿的原因，因此缩略图在私有线程池上解码并缩放，
再经队列信号以 `QImage` 送回。用 `QImage` 而非 `QPixmap`，因为只有 `QImage` 可以
在界面线程之外被访问。

此处刻意使用显式缓存而非 Qt 进程级的 `QPixmapCache`：全局缓存让 pixmap 以"工作
线程 → 网格 → 全局缓存 → 卡片"的路径经字符串键传递，把网格与卡片之间的依赖藏在
一个字符串后面。注入式缓存让这份契约保持可见，也允许其他前端提供自己的实现。
"""
import logging
import os

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QImage, QPixmap

from gifmanager.frontend.qt import images

log = logging.getLogger("GIFManager")

# Cache key prefix, kept so a key is recognisable in a debugger /
# 缓存键前缀，使键在调试器中可辨认
KEY_PREFIX = "thumb:"

# Threads used when parallel rendering is switched off. Two is enough to hide
# the decode latency of a small visible band without competing with the UI.
# 关闭并行渲染时使用的线程数。两个足以掩盖小范围可视区的解码延迟，又不会与界面争抢。
SERIAL_THREADS = 2

# Decoded-thumbnail budget, in kilobytes. Reported by
# `QPixmapCache.setCacheLimit` in the previous release; kept as a documented
# number because it is what the grid's memory profile was tuned against.
# 解码缩略图预算，单位千字节。上一版本通过 `QPixmapCache.setCacheLimit` 设置；保留
# 为文档化数值，因为网格的内存表现是针对它调优的。
CACHE_LIMIT_KB = 65536


def thumb_key(filepath):
    # Cache key for a file path. Pure and shared, because the loader and the
    # card must agree on the exact string. / 某文件路径的缓存键。纯函数且共用，
    # 因为加载器与卡片必须对完全相同的字符串达成一致。
    return KEY_PREFIX + str(filepath)


class ThumbnailCache:
    # Bounded least-recently-used cache of decoded pixmaps.
    # 有界、按最近最少使用的已解码 pixmap 缓存。
    def __init__(self, limit=256):
        self._limit = max(8, int(limit))
        self._items = {}

    def get(self, key):
        item = self._items.pop(key, None)
        if item is None:
            return None
        # Re-insert to mark it as most recently used /
        # 重新插入以标记为最近使用
        self._items[key] = item
        return item

    def put(self, key, pixmap):
        self._items.pop(key, None)
        self._items[key] = pixmap
        while len(self._items) > self._limit:
            self._items.pop(next(iter(self._items)))

    def discard(self, key):
        self._items.pop(key, None)

    def clear(self):
        self._items.clear()

    def __len__(self):
        return len(self._items)


class _LoadTask(QRunnable):
    # One decode job: read a file into a `QImage` and scale it into a square
    # box, preserving the aspect ratio.
    #
    # The Rust pipeline is tried first: it decodes and resamples with a SIMD
    # resampler and hands back one RGBA buffer, so the whole job is one native
    # call plus one `QImage` wrapper with no extra pixel copy. `QImage` remains
    # the fallback, and is also what handles any format the Rust decoders do not
    # know.
    # 单个解码任务：把文件读入 `QImage` 并等比缩放进方形范围。
    #
    # 先尝试 Rust 管线：它用 SIMD 重采样器解码并缩放，返回一整块 RGBA 缓冲，因此整个
    # 任务是一次原生调用加一次 `QImage` 包装，没有额外的像素复制。`QImage` 仍是回退
    # 路径，也负责处理 Rust 解码器不认识的格式。
    def __init__(self, loader, filepath, size):
        super().__init__()
        self._loader = loader
        self._filepath = filepath
        self._size = max(1, int(size))
        self.setAutoDelete(True)

    @Slot()
    def run(self):
        try:
            # The loader may already be gone when the application is quitting;
            # `isValid` is shiboken's liveness check.
            # 应用退出时加载器可能已销毁；`isValid` 是 shiboken 的存活检查。
            try:
                from shiboken6 import isValid

                if not isValid(self._loader):
                    return
            except ImportError:
                pass

            image = self._decode_native()
            if image is None:
                image = self._decode_qt()
            if image is None or image.isNull():
                self._loader.emit_done(self._filepath, None)
                return
            self._loader.emit_done(self._filepath, image)
        except RuntimeError:
            # The C++ object was destroyed mid-flight; nothing to report /
            # C++ 对象在飞行途中被销毁；无需上报
            pass

    def _decode_native(self):
        decoded = images.decode_thumbnail(self._filepath, self._size)
        if decoded is None:
            return None
        # `QImage` references the Python `bytes` rather than copying it, so the
        # buffer stays alive only because the returned image holds a reference to
        # it. Detaching with `.copy()` here would reintroduce exactly the pixel
        # copy this path exists to avoid, so the reference is relied upon.
        # `QImage` 引用该 Python `bytes` 而不是复制它，缓冲区之所以存活只因为返回的
        # image 持有对它的引用。在此用 `.copy()` 分离会重新引入这条路径正是要避免的
        # 像素复制，因此这里依赖该引用。
        return QImage(decoded.pixels, decoded.width, decoded.height,
                      decoded.width * 4, QImage.Format.Format_RGBA8888)

    def _decode_qt(self):
        image = QImage(self._filepath)
        if image.isNull():
            return None
        if image.width() > self._size or image.height() > self._size:
            image = image.scaled(
                self._size, self._size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        return image


class ThumbnailLoader(QObject):
    # Decodes thumbnails on a private pool and reports them on the GUI thread.
    #
    # The pool is private on purpose: an earlier version changed the thread
    # count of `QThreadPool.globalInstance()` at import time, which silently
    # resized every other Qt user's pool in the process.
    # 在私有线程池上解码缩略图，并在界面线程上报结果。
    #
    # 线程池刻意私有：此前版本在导入时修改 `QThreadPool.globalInstance()` 的线程数，
    # 静默改变了同进程内所有其他 Qt 使用者的线程池。
    done = Signal(str, object)   # cache key, QImage or None / 缓存键, QImage 或 None

    def __init__(self, cache=None, parent=None):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(SERIAL_THREADS)
        self._pending = set()
        self._parallel = False
        self.cache = cache if cache is not None else ThumbnailCache()

    # ---- configuration / 配置 -------------------------------------------

    def set_parallel(self, enabled):
        enabled = bool(enabled)
        if enabled == self._parallel:
            return
        self._parallel = enabled
        count = max(2, os.cpu_count() or 4) if enabled else SERIAL_THREADS
        self._pool.setMaxThreadCount(count)

    def is_parallel(self):
        return self._parallel

    @property
    def pending_count(self):
        return len(self._pending)

    # ---- requests / 请求 ------------------------------------------------

    def request(self, filepath, size):
        # Ask for a thumbnail. Requests are de-duplicated, so a card that is
        # recycled while its decode is still in flight does not queue a second
        # job for the same file.
        # 请求缩略图。请求会去重，因此解码仍在进行时被回收的卡片不会为同一文件再排
        # 一个任务。
        if not filepath:
            return
        key = thumb_key(filepath)
        if self.cache.get(key) is not None:
            return
        if filepath in self._pending:
            return
        self._pending.add(filepath)
        self._pool.start(_LoadTask(self, filepath, size))

    def cached(self, filepath):
        return self.cache.get(thumb_key(filepath))

    def emit_done(self, filepath, image):
        # Called from a worker thread. The signal is queued onto the GUI thread
        # because this object lives there.
        # 由工作线程调用。由于本对象位于界面线程，信号会排队到界面线程。
        self._pending.discard(filepath)
        self.done.emit(thumb_key(filepath), image)

    def store(self, key, pixmap):
        self.cache.put(key, pixmap)

    def shutdown(self, timeout_ms=3000):
        # Drain the pool. Called on quit, because a decode still running while
        # the interpreter tears down is how the exit crashes were produced.
        # 排空线程池。退出时调用，因为解释器拆除时仍在运行的解码正是此前退出崩溃的
        # 来源。
        try:
            self._pool.clear()
            self._pool.waitForDone(int(timeout_ms))
        except RuntimeError:
            pass
        self._pending.clear()

    def take_pending(self):
        # Snapshot and clear the in-flight set. Kept public so a test can
        # assert de-duplication without reaching into a private attribute.
        # 对进行中的集合取快照并清空。保持公开，使测试无需伸手进私有属性即可断言去重。
        pending = set(self._pending)
        self._pending.clear()
        return pending


def to_pixmap(image):
    # `QPixmap.fromImage` may only run on the GUI thread, so conversion is a
    # deliberate step at the delivery boundary rather than inside the worker.
    # `QPixmap.fromImage` 只能在界面线程运行，因此转换是交付边界上的一个刻意步骤，
    # 而不是放在工作线程内部。
    if image is None or image.isNull():
        return None
    return QPixmap.fromImage(image)


__all__ = [
    "CACHE_LIMIT_KB",
    "KEY_PREFIX",
    "SERIAL_THREADS",
    "ThumbnailCache",
    "ThumbnailLoader",
    "thumb_key",
    "to_pixmap",
]
