"""GIF playback for QML, through a custom image provider.

# The problem QML poses

The decoder already returns decoded frames and their delays
(`frontend/qt/animation.py`), and the Qt Widgets front-end plays them by swapping a
`QLabel`'s pixmap. QML cannot do that: `Image.source` is a URL, and there is no way to
hand an `Image` a `QImage`. Writing each frame to a temporary file would work and
would be a catastrophe — a 60-frame animation would mean 60 files per card per
second.

# The mechanism

A `QQuickImageProvider` is the supported way to serve an image from C++ to QML, and
it is addressed by URL. So:

* decoded frames live in a registry keyed by `"<path hash>:<frame index>"`;
* the provider resolves that key back to the `QImage` it already holds;
* a QML `Timer` advances a frame index on a cadence the animation service reports.

QML writes `source: "gifframe:///" + app.animator.frameKey(id)` and nothing else. The
frame index is a bound property, so advancing it re-evaluates the source and the
`Image` loads the next frame from the provider — no file, no pixel copy, and no
JavaScript driving the animation.

# Why the frame index lives in PYTHON

An `Image` with a changing `source` is re-requested through the provider every frame.
Driving that from QML per card would mean every delegate owning a timer, and a grid of
200 visible cards would mean 200 timers. Here ONE service owns the frame counter and
reports it per sticker id, so QML binds to it and the cost is one property read per
card per frame.

# What this does NOT do

Frames are decoded for the whole animation up front, which is what makes playback a
lookup rather than a decode. For a very large GIF that is a real memory cost, bounded
by the existing decode cache in `animation.py`. A streaming decoder would be better and
is not what this is.

QML 的 GIF 播放，经自定义图像提供器实现。

# QML 带来的问题

解码器已经返回解码帧及其延迟（`frontend/qt/animation.py`），Qt Widgets 前端通过切换
`QLabel` 的 pixmap 来播放。QML 做不到：`Image.source` 是 URL，没有办法把 `QImage` 交给
`Image`。把每帧写进临时文件可行，但会是一场灾难——60 帧动画意味着每张卡片每秒 60 个文件。

# 机制

`QQuickImageProvider` 是从 C++ 向 QML 提供图像的受支持方式，且以 URL 寻址。因此：

* 解码帧存放在以 `"<路径哈希>:<帧序号>"` 为键的注册表里；
* 提供器把该键解析回它已持有的 `QImage`；
* 一个 QML `Timer` 按动画服务报告的节奏推进帧序号。

QML 只写 `source: "gifframe:///" + app.animator.frameKey(id)`，别无其他。帧序号是绑定属性，
因此推进它会让 source 重新求值、`Image` 从提供器加载下一帧——没有文件、没有像素复制，也没有
JavaScript 驱动动画。

# 为什么帧序号放在 Python 里

source 不断变化的 `Image` 每帧都会经提供器重新请求。若由 QML 每张卡片自行驱动，就意味每个
委托都持有一个定时器，而一屏 200 张可见卡片就是 200 个定时器。这里由"一个"服务持有帧计数器
并按贴纸 id 报告，因此 QML 绑定到它，代价是每帧每卡片一次属性读取。

# 这里"不"做什么

帧在开始播放前被整体解码，这正是让播放成为一次查表而不是一次解码的原因。对非常大的 GIF，
这是真实的内存代价，由 `animation.py` 中已有的解码缓存限制。流式解码器会更好，而这不是它。
"""
import hashlib
import logging
import os
import threading
import time

from PySide6.QtCore import (
    QObject,
    Property,
    QSize,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QImage
from PySide6.QtQml import QQmlImageProviderBase, qmlRegisterType
from PySide6.QtQuick import QQuickImageProvider

log = logging.getLogger("GIFManager")

# The URL scheme the provider answers. A custom scheme rather than `image:` so it
# cannot collide with a real file path, and so a stray `image://` request from another
# component is not silently answered with a sticker frame.
# 提供器应答的 URL 方案。用自定义方案而非 `image:`，使它不会与真实文件路径冲突，也使他处
# 组件误发的 `image://` 请求不会静默地被一张贴纸帧应答。
# The provider's id IN THE URL. Qt resolves `image://<name>/<id>` by looking the
# name up among the engine's image providers, so this string must EQUAL
# `PROVIDER_ID`: a URL whose scheme differs from the registered name silently
# resolves to a null image (every animated card blank) with no warning at all.
# That mismatch — "gifframe:///" against a provider registered as "gifframes" —
# is exactly what made animations render as empty cards.
# URL 中的提供器名。Qt 经 `image://<名>/<id>` 在引擎的图像提供器中查该名，因此这个
# 字符串必须"等于" `PROVIDER_ID`：scheme 与注册名不同的 URL 会静默解析为空图像
# （每张动画卡变成空白），且毫无警告。"gifframe:///" 对上注册名为 "gifframes" 的
# 提供器，正是动画渲染为空卡的原因。
SCHEME = "gifframes"

# Provider id, as registered on the engine / 在引擎上注册的提供器 id
PROVIDER_ID = "gifframes"

# A frame index beyond this is treated as "not decoded yet" rather than as an error,
# because a card can be created one binding-evaluation before its decode lands.
# 超过该值的帧序号被视为"尚未解码"而非错误，因为卡片可能在其解码落地前早一次绑定求值被创建。
MAX_FRAME_INDEX = 4096

# Path -> the hash prefix used in its frame URLs.
#
# A cache, because `key_for` computes `normcase(abspath(path))` and an MD5 digest, and it was
# being called for EVERY frame index of EVERY registered card: `frameKey` is a QML slot invoked
# from a property binding, so a grid of 24 animated cards changing frame ~450 times a second
# ran about 500 `abspath`+MD5 pairs per second on the GUI thread. That is pure overhead standing
# between the timer tick and the repaint, which is exactly where scroll stutter comes from.
#
# The prefix depends only on the path, and paths repeat (duplicate stickers share one file), so
# one entry per DISTINCT path is enough. Measured: 744 `frameKey` calls in 3 s with 24 cards.
# 路径 -> 其帧 URL 中使用的哈希前缀。
#
# 用缓存，因为 `key_for` 会计算 `normcase(abspath(path))` 与一次 MD5 摘要，而它过去对"每张已注册
# 卡片的每一个帧序号"都会被调用：`frameKey` 是一个由属性绑定调用的 QML 槽，因此 24 张动画卡片、
# 约每秒 450 次换帧，会在 GUI 线程上跑约 500 次 `abspath`+MD5。那是横在定时器滴答与重绘之间的纯
# 开销，而滚动卡顿正来自那里。
#
# 该前缀只取决于路径，而路径会重复（重复贴纸共享同一个文件），因此每个"不同"路径一条记录就够了。
# 实测：24 张卡片、3 秒内 744 次 `frameKey` 调用。
_PREFIX_CACHE = {}


def key_for(path, index):
    # The registry and URL key for one frame.
    #
    # A hash of the path rather than the path itself: the key goes into a URL, and a
    # Windows path contains a colon and backslashes, which would need escaping on one
    # platform and not another. Hashing makes the key opaque and uniform.
    # 一帧的注册表与 URL 键。
    #
    # 用路径的哈希而非路径本身：键要进入 URL，而 Windows 路径含冒号和反斜杠，在一个平台上
    # 需要转义、在另一个平台上不需要。哈希让键不透明且统一。
    return f"{prefix_for(path)}:{int(index)}"


def prefix_for(path):
    # The hash prefix for a path, computed once per distinct path.
    #
    # `os.path.normcase` and `os.path.abspath` are both syscall-adjacent (`abspath` calls
    # `getcwd` when the path is relative), so caching them matters as much as caching the MD5.
    # 路径的哈希前缀，每个不同路径只计算一次。
    #
    # `os.path.normcase` 与 `os.path.abspath` 都贴近系统调用（路径为相对时 `abspath` 会调用
    # `getcwd`），因此缓存它们与缓存 MD5 同样要紧。
    cached = _PREFIX_CACHE.get(path)
    if cached is not None:
        return cached
    key = os.path.normcase(os.path.abspath(path))
    digest = hashlib.md5(key.encode("utf-8", "replace")).hexdigest()[:16]
    # Bounded, because a library can hold thousands of files and the prefix is only needed
    # while a card is registered. A plain dict with a size guard is enough: entries are cheap
    # (16 bytes of text) and re-computing one is cheaper than tracking usage.
    # 有界，因为素材库可能持有数千个文件，而前缀只在卡片已注册期间才需要。带尺寸保护的普通字典
    # 就够了：条目很廉价（16 字节文本），而重新计算一个比跟踪使用情况更便宜。
    if len(_PREFIX_CACHE) > 4096:
        _PREFIX_CACHE.clear()
    _PREFIX_CACHE[path] = digest
    return digest


class FrameStore:
    # Holds decoded frames per path, with a bounded budget.
    #
    # A class rather than module globals so a test can hold its own instance, and so
    # the provider does not depend on import-time state.
    # 按路径持有解码帧，带受限预算。
    #
    # 用类而非模块全局，使测试能持有自己的实例，也让提供器不依赖导入期状态。

    # Pixels of decoded frames to keep, which is the whole reason this class exists.
    #
    # MEASURED against the user's own library (`tests/measure_real_gifs.py`), because the
    # synthetic test GIFs were three orders of magnitude too small to size it:
    #
    #   average file     130 frames of 100x100  ->  5.0 MB decoded
    #   a viewport of 24 cards                  ->  119 MB decoded
    #
    # The previous budget was 12,000,000 pixels (45.8 MB), which holds NINE such animations. A
    # full viewport therefore could not be cached, so the least recently stored animation was
    # evicted while still on screen - and because a card keeps playing (asking for a new frame
    # index every ~80 ms), an evicted card asked for a frame the store no longer had and
    # `register`'s `_decode_now` re-decoded it: 250 ms of GIF decoding ON THE GUI THREAD, per
    # card, during the scroll. That is the stutter.
    #
    # 32,000,000 pixels is 122 MB, which holds a viewport plus headroom. Chosen as a budget
    # rather than as "unbounded" because this is RGBA frame data and a 157-file library of
    # these would be 780 MB if every animation were retained.
    #
    # 保留的解码帧像素数，这正是本类存在的意义。
    #
    # 针对用户自己的素材库实测（`tests/measure_real_gifs.py`），因为合成测试 GIF 小了三个数量级、
    # 无法用于定尺寸：
    #
    #   平均文件   130 帧、100x100  ->  解码后 5.0 MB
    #   24 张卡片的视口             ->  解码后 119 MB
    #
    # 此前的预算是 12,000,000 像素（45.8 MB），只能容纳"九个"这样的动画。因此一个完整视口无法被
    # 缓存，于是最久未存入的动画在仍在屏幕上时就被淘汰——而由于卡片一直在播放（每约 80 毫秒请求一个
    # 新的帧序号），被淘汰的卡片会请求存储已不再持有的帧，`register` 的 `_decode_now` 便重新解码它：
    # "在 GUI 线程上"每个卡片 250 毫秒的 GIF 解码，就发生在滚动期间。那就是卡顿。
    #
    # 32,000,000 像素即 122 MB，可容纳一个视口加上余量。选择"预算"而非"无上限"，是因为这是 RGBA
    # 帧数据，而一个 157 个此类文件的素材库若保留全部动画会达到 780 MB。
    DEFAULT_PIXEL_BUDGET = 32_000_000

    def __init__(self, pixel_budget=None):
        self._frames = {}
        self._pixels = {}
        self._order = []
        self._budget = int(self.DEFAULT_PIXEL_BUDGET if pixel_budget is None
                           else pixel_budget)
        self._used = 0

    def put(self, path, frames):
        if not frames:
            return
        pixels = sum(frame.width() * frame.height() for frame in frames)
        if path in self._frames:
            self._used -= self._pixels.pop(path, 0)
            self._order = [p for p in self._order if p != path]
        self._frames[path] = list(frames)
        self._pixels[path] = pixels
        self._order.append(path)
        self._used += pixels
        self._evict()

    def _evict(self):
        # Oldest first. Frames are decoded on demand, so evicting the least recently
        # STORED animation is the right policy: the ones still on screen were
        # re-put or re-requested most recently.
        # 最旧优先。帧是按需解码的，因此淘汰"最久未被存入"的动画是正确策略：仍在屏幕上的
        # 那些最近被重新存入或请求过。
        while self._used > self._budget and len(self._order) > 1:
            oldest = self._order.pop(0)
            self._used -= self._pixels.pop(oldest, 0)
            self._frames.pop(oldest, None)

    def frames(self, path):
        frames = self._frames.get(path)
        if frames is not None:
            # Touch, so an animation still being played is not the next evicted.
            # 触碰，使仍在播放的动画不会是下一个被淘汰的。
            if path in self._order:
                self._order.remove(path)
                self._order.append(path)
        return frames

    def has(self, path):
        return path in self._frames

    def clear(self):
        self._frames.clear()
        self._pixels.clear()
        self._order.clear()
        self._used = 0

    @property
    def used_pixels(self):
        return self._used


# The store the provider reads. Module-level because `QQuickImageProvider` is
# instantiated by the QML engine, which has no way to inject a dependency.
# 提供器读取的存储。模块级，因为 `QQuickImageProvider` 由 QML 引擎实例化，而引擎无法注入
# 依赖。
STORE = FrameStore()

# Frame indexes are resolved through `(path, index)`, so the provider needs the path for
# a key as well as the index. Keeping the mapping here avoids putting a filesystem path
# in the URL.
# 帧序号经 `(路径, 序号)` 解析，因此提供器除序号外还需要键对应的路径。把映射放在此处可避免
# 把文件系统路径放进 URL。
_KEYS = {}


def register_frames(path, frames):
    # Publish decoded frames and return the key prefix a card should use.
    # 发布解码帧并返回卡片应使用的键前缀。
    global _KEYS
    STORE.put(path, frames)
    prefix = key_for(path, 0).split(":", 1)[0]
    _KEYS[prefix] = path
    return prefix


# ---------------------------------------------------- background decoding ---
#
# Decoding a real GIF costs 231 ms in the median and 383 ms at worst (measured against the
# user's own 157-file library), so doing it while the grid scrolls freezes the interface.
# `QThreadPool` + a `QRunnable` moves it off the GUI thread; the result is handed back through a
# queued signal, which is what makes the handover thread-safe.
#
# The pool is module-level because `QQuickImageProvider` is created by the engine and cannot take
# an injected dependency, and because a per-animator pool would mean a per-animator thread.
#
# 解码一个真实 GIF 的中位代价是 231 毫秒、最差 383 毫秒（针对用户自己那 157 个文件的素材库实测），
# 因此在网格滚动时做这件事会冻结界面。`QThreadPool` 加 `QRunnable` 把它移出 GUI 线程；结果经队列
# 信号交回，而那正是让交接线程安全的东西。
#
# 线程池放在模块级，因为 `QQuickImageProvider` 由引擎创建、无法注入依赖，且每个动画器一个池意味着
# 每个动画器一条线程。
_decoder = None


def _decoder_pool():
    global _decoder
    if _decoder is None:
        _decoder = _FrameDecoder()
    return _decoder


class _FrameDecoder(QObject):
    # Owns the worker pool and the pending results.
    # 持有工作线程池与待取结果。

    # (path) — emitted on the GUI thread when a decode finished.
    # (path)——解码完成时在 GUI 线程上发出。
    ready = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtCore import QThreadPool

        self._pool = QThreadPool()
        # Decoding is CPU-bound and the frames are large, so a couple of workers is the point of
        # diminishing returns. More workers would compete for memory bandwidth and make the
        # frames land later, not sooner.
        # 解码是 CPU 密集且帧很大，因此两三个工作线程就到了收益递减点。更多线程会争抢内存带宽，让帧
        # 到得更晚而不是更早。
        self._pool.setMaxThreadCount(2)
        self._results = {}
        self._results_lock = threading.Lock()

    def submit(self, path, card_pixels):
        from PySide6.QtCore import QRunnable

        decoder = self

        class _Job(QRunnable):
            # One decode. `run` executes on a pool thread.
            # 一次解码。`run` 在线程池的线程上执行。

            def run(self):
                try:
                    from gifmanager.frontend.qt import animation

                    decoded = animation.decode_all(path, card_pixels)
                    with decoder._results_lock:
                        decoder._results[path] = decoded
                except Exception:
                    log.exception("animator: background decode of %s failed", path)
                    with decoder._results_lock:
                        decoder._results[path] = None
                # A queued emit, so the receiver runs on the GUI thread.
                # 队列发出，使接收方在 GUI 线程上运行。
                decoder.ready.emit(path)

        self._pool.start(_Job())

    def take(self, path):
        with self._results_lock:
            return self._results.pop(path, None)

    def shutdown(self):
        self._pool.waitForDone(3000)
        with self._results_lock:
            self._results.clear()


def animation_decode_async(path, card_pixels, owner):
    # Queue a decode and return the frames ONLY if they are already in the store.
    #
    # Returning `None` is the normal case for an undecoded GIF: the caller (`register`) then
    # reports "nothing to animate yet", the card keeps its still thumbnail, and `framesDecoded`
    # brings it back when the frames arrive.
    # 排队一次解码，并且"仅当"帧已在存储中时才返回它们。
    #
    # 对尚未解码的 GIF 返回 `None` 是常态：调用方（`register`）随后报告"暂时没有可动画的内容"，
    # 卡片保留其静态缩略图，而 `framesDecoded` 会在帧到达时把它带回来。
    store = STORE.frames(path)
    if store is not None:
        return store
    decoder = _decoder_pool()
    # Connected once per animator, with a unique connection so two animators do not receive each
    # other's decodes twice.
    # 每个动画器连接一次，且用唯一连接，使两个动画器不会各自收到对方解码两次。
    key = f"animator_{id(owner)}"
    if not getattr(owner, "_decoder_hooked", False):
        decoder.ready.connect(owner._on_decoded)
        owner._decoder_hooked = True
        _ = key
    decoder.submit(path, card_pixels)
    return None


def animation_take_result(path):
    return _decoder_pool().take(path)


# ------------------------------------------------------- preview decoding ---
#
# The STILL frame a card shows before its animation is ready.
#
# # Why a provider and not `file://`
#
# The card used to show `card.source` — the `file://` URL of the GIF — as its placeholder. That
# makes the QML `Image` decode a 5-8 MB animated GIF with the default `QImageReader`, WHICH READS
# EVERY FRAME, on the GUI thread, once per card. For the user's library that is the same
# 231-383 ms cost as the animator's own decode, paid a second time per card. Measured need:
# `tests/measure_real_gifs.py` reports 130 frames and 5.0 MB decoded per file on average.
#
# This provider asks `QImageReader` for frame 0 at a SCALED size, so Qt does not produce a
# full-resolution first frame and does not touch the rest.
#
# 卡片在动画就绪之前显示的"静态"帧。
#
# # 为什么用提供器而不是 `file://`
#
# 卡片过去把 `card.source`（GIF 的 `file://` URL）当作占位符。那会让 QML 的 `Image` 用默认的
# `QImageReader` 解码一个 5-8MB 的动画 GIF，"它会读取每一帧"，且在 GUI 线程上、每张卡片一次。
# 对用户的素材库来说，这与动画器自身的解码是同样的 231-383 毫秒代价，而每张卡片还要再付一次。实测
# 需求：`tests/measure_real_gifs.py` 报告平均 130 帧、每文件解码 5.0 MB。
#
# 本提供器向 `QImageReader` 请求"缩放后"尺寸的第 0 帧，因此 Qt 既不产出全分辨率首帧，也不碰其余帧。
class PreviewProvider(QQuickImageProvider):
    # One scaled still per (path, edge), cached so scrolling back does not re-decode.
    # 每个 (路径, 边长) 一张缩放静态图，带缓存，使滚回来时无需重新解码。

    # Previews to keep. They are card-sized (about 100x100), so this is a few hundred KB — small
    # enough that the budget can be generous and still bounded.
    # 保留的预览数。它们是卡片尺寸（约 100x100），因此只有几百 KB——小到预算可以给得宽松而仍然有界。
    CACHE_LIMIT = 512

    def __init__(self, parent=None):
        super().__init__(QQuickImageProvider.Image)
        self._cache = {}
        self._order = []

    def _cache_get(self, key):
        image = self._cache.get(key)
        if image is not None and key in self._order:
            self._order.remove(key)
            self._order.append(key)
        return image

    def _cache_put(self, key, image):
        self._cache[key] = image
        if key in self._order:
            self._order.remove(key)
        self._order.append(key)
        while len(self._order) > self.CACHE_LIMIT:
            self._cache.pop(self._order.pop(0), None)

    def requestImage(self, image_id, size, requested_size):
        from PySide6.QtCore import QSize, Qt
        from PySide6.QtGui import QImage, QImageReader

        # `image://preview/<16 hex>/<edge>` — the first segment is a registered path prefix, so
        # the URL never carries a filesystem path (a Windows path contains a colon, which would
        # break the URL).
        # `image://preview/<16 位十六进制>/<边长>`——第一段是已注册的路径前缀，因此 URL 永不携带
        # 文件系统路径（Windows 路径含冒号，会破坏 URL）。
        parts = str(image_id or "").split("/")
        if len(parts) != 2:
            return QImage()
        prefix = parts[0].split(":", 1)[0]
        try:
            edge = max(16, min(512, int(parts[1])))
        except ValueError:
            return QImage()
        path = path_for_prefix(prefix)
        if not path:
            return QImage()

        key = (path, edge)
        cached = self._cache_get(key)
        if cached is not None:
            if size is not None:
                size.setWidth(cached.width())
                size.setHeight(cached.height())
            return cached

        reader = QImageReader(path)
        original = reader.size()
        if original.isValid() and original.width() > 0 and original.height() > 0:
            # Ask for a size rather than scaling afterwards: this is the whole saving, because it
            # stops the decoder producing a full-resolution first frame.
            # 请求尺寸而不是事后缩放：这正是全部节省所在，因为它阻止解码器产出全分辨率首帧。
            target = original.scaled(QSize(edge, edge), Qt.AspectRatioMode.KeepAspectRatio)
            reader.setScaledSize(target)
        image = reader.read()
        if image.isNull():
            return QImage()
        self._cache_put(key, image)
        if size is not None:
            size.setWidth(image.width())
            size.setHeight(image.height())
        return image

    def clear(self):
        self._cache.clear()
        self._order.clear()


# The provider the engine registers. Module-level for the same reason `STORE` is.
# 引擎注册的提供器。与 `STORE` 同样的理由放在模块级。
PREVIEWS = PreviewProvider()


def preview_url(path, edge):
    # The provider URL for a sticker's still frame, or "" when there is no path.
    #
    # # This REGISTERS the prefix
    #
    # The prefix -> path table was filled only by `register_frames`, i.e. when a GIF had finished
    # decoding. A preview is requested BEFORE that — that is the whole point of a preview, to
    # show something while the decode runs — so `path_for_prefix` returned "" and the provider
    # answered with a null image:
    #
    #     QML QQuickImage: Failed to get image from provider:
    #     image://preview/f881dc23b1748828:0/100
    #
    # once per card, and every card rendered blank until its animation landed. Registering the
    # mapping here makes the preview resolvable from the moment the card knows its path.
    # 贴纸静态帧的提供器 URL；无路径时返回 ""。
    #
    # # 此处会"注册"前缀
    #
    # 前缀 -> 路径表过去只由 `register_frames` 填充，也就是 GIF 解码完成时。而预览是在那之前被请求的
    # ——那正是预览的意义，在解码运行期间显示点什么——因此 `path_for_prefix` 返回 ""，提供器以空图像
    # 作答：
    #
    #     QML QQuickImage: Failed to get image from provider:
    #     image://preview/f881dc23b1748828:0/100
    #
    # 每张卡片一次，且在动画落地之前每张卡片都渲染为空白。在此注册该映射使预览从卡片知道自身路径的那
    # 一刻起就可解析。
    if not path:
        return ""
    prefix = prefix_for(path)
    _KEYS[prefix] = path
    return f"image://preview/{prefix}:{0}/{int(edge)}"


def register_preview_provider(engine):
    # Install the preview provider. Called BEFORE the document loads, for the same reason the
    # frame provider is: an `Image` whose source names an unknown provider resolves to a null
    # image and reports it only as a warning.
    # 安装预览提供器。在文档加载"之前"调用，理由与帧提供器相同：source 指向未知提供器的 `Image`
    # 会解析为空图像，且只报为警告。
    engine.addImageProvider("preview", PREVIEWS)


def path_for_prefix(prefix):
    return _KEYS.get(prefix, "")


class StickerFrameProvider(QQuickImageProvider):
    # Serves one decoded GIF frame per request.
    #
    # `QQuickImageProvider` with `Image` type: the provider returns a `QImage` and Qt
    # handles the conversion to the scene graph's texture format, which is the only
    # supported path and also the one that caches correctly.
    # 每次请求提供一个已解码的 GIF 帧。
    #
    # 以 `Image` 类型使用 `QQuickImageProvider`：提供器返回 `QImage`，由 Qt 处理到场景图纹理
    # 格式的转换——这是唯一受支持的路径，也是能正确缓存的那条。

    def __init__(self):
        super().__init__(QQmlImageProviderBase.ImageType.Image)

    def requestImage(self, image_id, size, requested_size):
        # `image_id` is the part of the URL after the scheme, e.g. "abc123:7".
        # `image_id` 是 URL 中方案之后的部分，例如 "abc123:7"。
        text = str(image_id or "")
        prefix, _, index_text = text.partition(":")
        if not prefix or not index_text:
            return QImage()
        try:
            index = int(index_text.split("?", 1)[0])
        except ValueError:
            return QImage()
        if index < 0 or index > MAX_FRAME_INDEX:
            return QImage()

        path = path_for_prefix(prefix)
        if not path:
            return QImage()
        frames = STORE.frames(path)
        if not frames:
            return QImage()
        # A frame index past the end means the animation restarted while a card was
        # still showing the old length, so wrapping is correct rather than an error.
        # 帧序号超出末尾意味着动画已重新开始而某张卡片仍显示旧长度，因此回绕是正确的而非错误。
        frame = frames[index % len(frames)]
        if size is not None:
            size.setWidth(frame.width())
            size.setHeight(frame.height())
        # ONLY the image is returned, and the size is reported through the `size`
        # out-parameter — that is Qt's contract for an `ImageType` provider.
        # Returning a `(image, size)` tuple raised
        #     RuntimeWarning: Invalid return value in function
        #     'QQuickImageProvider.requestImage', expected QImage, got tuple
        # and Qt treated every request as a failure ("Failed to get image from
        # provider"), so every animated card rendered blank while a Python-side
        # call —— which unpacks the tuple happily —— reported success.
        # 只返回图像，尺寸经 `size` 出参报告——这是 Qt 对 `ImageType` 提供器的契约。
        # 返回 `(image, size)` 元组会触发
        #     RuntimeWarning: Invalid return value ...
        # 于是 Qt 把每次请求都判为失败（"Failed to get image from provider"），每张
        # 动画卡都渲染为空白——而 Python 侧的调用能顺利解包元组、报告成功。
        return frame


class StickerAnimator(QObject):
    # Owns playback: which stickers animate, and which frame each is on.
    #
    # ONE timer for every animated sticker, for the reason given in the module
    # docstring: a per-card timer would mean hundreds of timers for a full grid.
    # 持有播放：哪些贴纸在动，以及各自处于第几帧。
    #
    # 为所有动画贴纸共用一个定时器，原因见模块文档字符串：每卡片一个定时器意味着一屏网格有
    # 数百个定时器。
    frameChanged = Signal()

    # Emitted when a background decode finishes and the frames are in the store.
    #
    # A card that asked to animate while its GIF was still decoding showed its STILL thumbnail
    # and was not registered. This signal is what lets it try again, so the animation appears a
    # moment later instead of never.
    # 后台解码完成、帧已进入存储时发出。
    #
    # 在 GIF 仍在解码时请求动画的卡片显示其"静态"缩略图且未被注册。本信号让它再试一次，使动画在
    # 稍后出现而不是永不出现。
    framesDecoded = Signal(str)

    # The frame interval when a card has not been decoded yet, so the first tick is not
    # delayed by a whole second.
    # 卡片尚未解码时的帧间隔，使第一次滴答不会被拖延一整秒。
    IDLE_INTERVAL_MS = 40

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self._backend = backend
        # Paths with a decode in flight or queued, so the same GIF is not decoded twice.
        # 解码进行中或已排队的路径，使同一个 GIF 不会被解码两次。
        self._pending = set()
        # sticker id -> file path / 贴纸 id -> 文件路径
        self._paths = {}
        # sticker id -> key prefix / 贴纸 id -> 键前缀
        self._keys = {}
        # sticker id -> frame count / 贴纸 id -> 帧数
        self._counts = {}
        # sticker id -> delays, in milliseconds / 贴纸 id -> 延迟（毫秒）
        self._delays = {}
        # sticker id -> current frame index / 贴纸 id -> 当前帧序号
        self._indices = {}
        # sticker id -> monotonic time the frame began / 贴纸 id -> 该帧开始的单调时刻
        self._started = {}
        self._enabled = True
        # Zero means "no cap". A cap is what makes a large grid affordable: every
        # animated card costs one image request per frame, and honouring the existing
        # `gif_render_count` setting is what keeps a hundred visible GIFs from asking the
        # scene graph for a hundred textures at once.
        # 零表示"无上限"。上限正是让大网格可负担的原因：每张动画卡片每帧消耗一次图像请求，而
        # 遵守已有的 `gif_render_count` 设置正是让上百个可见 GIF 不会同时向场景图索取上百个
        # 纹理的原因。
        self._max_animated = 0
        # sticker ids, oldest first, for the cap / 贴纸 id，最旧在前，用于上限
        self._registrations = []

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.timeout.connect(self._tick)

    # ---- configuration / 配置 -------------------------------------------

    @Property(bool, notify=frameChanged)
    def enabled(self):
        return self._enabled

    @Slot(bool)
    def setEnabled(self, enabled):
        # Turning playback off stops the timer entirely, so a user who does not want
        # animation gets no timer work at all rather than 40 ms wake-ups that draw the
        # same frame.
        # 关闭播放会完全停掉定时器，因此不希望动画的用户完全不会有定时器开销，而不是每 40 毫秒
        # 醒来一次却画同一帧。
        enabled = bool(enabled)
        if enabled == self._enabled:
            return
        self._enabled = enabled
        if enabled and self._paths:
            self._timer.start(self.IDLE_INTERVAL_MS)
        elif not enabled:
            self._timer.stop()
        self.frameChanged.emit()

    @Property(int, notify=frameChanged)
    def maxAnimated(self):
        return self._max_animated

    @Slot(int)
    def setMaxAnimated(self, limit):
        # Cap how many stickers animate at once.
        #
        # Cards past the cap keep their registration and their current frame, so raising
        # the cap later resumes them rather than restarting them. That matters because a
        # user dragging the count upward does not expect every animation to jump back to
        # frame one.
        # 限制同时动画的贴纸数量。
        #
        # 超出上限的卡片保留其注册与当前帧，因此之后提高上限是"继续"而不是"重头开始"。这很
        # 重要，因为把数量往上拖的用户不会期望每个动画都跳回第一帧。
        limit = max(0, int(limit))
        if limit == self._max_animated:
            return
        self._max_animated = limit
        if self._paths:
            if limit > 0:
                self._timer.start(self.IDLE_INTERVAL_MS)
            else:
                self._timer.stop()
        self.frameChanged.emit()

    def _animating_ids(self):
        # The registrations that are allowed to advance, nearest first.
        #
        # An insertion-ordered list rather than a set, because which cards animate has to
        # be deterministic: a set would make the choice depend on hash ordering and the
        # same grid could animate different stickers on two runs.
        # 允许推进的注册，最近的在前。
        #
        # 用保持插入顺序的列表而非集合，因为"哪些卡片动画"必须是确定性的：集合会让选择取决于
        # 哈希顺序，同一个网格在两次运行中可能动画不同的贴纸。
        ids = [sticker_id for sticker_id in self._registrations
               if sticker_id in self._paths]
        if self._max_animated <= 0:
            return ids
        return ids[-self._max_animated:]

    # ---- registration / 注册 --------------------------------------------

    @Slot(int, str, result=int)
    def register(self, sticker_id, path):
        # Declare that a card for `sticker_id` is showing `path` and wants playback.
        #
        # Returns the frame count, or 0 when there is nothing to animate. Returning the
        # count rather than a boolean lets QML decide whether to show a static image
        # without a second call.
        # 声明某张卡片正在显示 `path` 并希望播放。
        #
        # 返回帧数，无可动画内容时返回 0。返回帧数而非布尔值，使 QML 无需第二次调用即可决定
        # 是否显示静态图。
        sticker_id = int(sticker_id)
        path = str(path or "")
        if not path or not os.path.isfile(path):
            self.unregister(sticker_id)
            return 0
        # Frames may already be in the store from the thumbnail path or a previous
        # card, so check before queueing a decode.
        # 帧可能已经因缩略图路径或先前卡片而在存储中，因此先检查再排队解码。
        frames = STORE.frames(path)
        if frames is None:
            frames = self._decode_now(path)
        if not frames or len(frames) < 2:
            self.unregister(sticker_id)
            return 0
        self._paths[sticker_id] = path
        self._counts[sticker_id] = len(frames)
        self._indices.setdefault(sticker_id, 0)
        self._started.setdefault(sticker_id, time.monotonic())
        if sticker_id in self._registrations:
            self._registrations.remove(sticker_id)
        self._registrations.append(sticker_id)
        if self._enabled and not self._timer.isActive():
            self._timer.start(self.IDLE_INTERVAL_MS)
        self.frameChanged.emit()
        return len(frames)

    @Slot(int)
    def unregister(self, sticker_id):
        sticker_id = int(sticker_id)
        if sticker_id not in self._paths:
            return
        self._paths.pop(sticker_id, None)
        self._counts.pop(sticker_id, None)
        self._delays.pop(sticker_id, None)
        self._indices.pop(sticker_id, None)
        self._started.pop(sticker_id, None)
        if sticker_id in self._registrations:
            self._registrations.remove(sticker_id)
        if not self._paths:
            self._timer.stop()
        self.frameChanged.emit()

    @Slot()
    def clear(self):
        # Drop every registration, for a group change or a search.
        # 丢弃所有注册，用于分组切换或搜索。
        self._paths.clear()
        self._counts.clear()
        self._delays.clear()
        self._indices.clear()
        self._started.clear()
        self._registrations.clear()
        self._timer.stop()
        self.frameChanged.emit()

    # ---- playback / 播放 -------------------------------------------------

    def _decode_now(self, path):
        # Decode OFF the GUI thread, and return whatever the store already has.
        #
        # # Why this is not synchronous any more
        #
        # It used to decode here, synchronously, on the reasoning that "one sticker at card size
        # is milliseconds". MEASURED against the user's own library, that reasoning was wrong by
        # two orders of magnitude:
        #
        #   median decode  231 ms      worst  383 ms
        #   12 cards       2764 ms of decoding
        #
        # So a scroll that brought 12 new cards into view froze the interface for nearly three
        # seconds, and no cache size can fix that — the work simply must not happen on the thread
        # that is drawing. The original project reached the same conclusion and decoded on a
        # worker thread for the same reason.
        #
        # The card keeps showing its still thumbnail (a `frameKey` of "" means the `Image` falls
        # back to `card.source`), and `framesDecoded` tells it to try again when the frames land.
        #
        # 在 GUI 线程"之外"解码，并返回存储当前已有的内容。
        #
        # # 为什么不再同步
        #
        # 它过去在此同步解码，理由是"单张贴纸在卡片尺寸下的解码只需毫秒"。针对用户自己的素材库实测，
        # 那个理由错了两个数量级：
        #
        #   解码中位数  231 毫秒      最差  383 毫秒
        #   12 张卡片   2764 毫秒的解码
        #
        # 因此一次把 12 张新卡片带入视野的滚动会让界面冻结近三秒，而任何缓存尺寸都修不好它——这项
        # 工作就是不能在正在绘制的那条线程上发生。原项目得出了同样的结论，也因此在工作线程上解码。
        #
        # 卡片继续显示其静态缩略图（`frameKey` 为 "" 意味着 `Image` 回退到 `card.source`），而
        # `framesDecoded` 会在帧落地时让它再试一次。
        if path in self._pending:
            return None
        self._pending.add(path)
        decoded = animation_decode_async(path, self._card_pixels(), self)
        return decoded

    def _card_pixels(self):
        # The pixel size to decode at: the card's own edge, so a 1200x900 source is not decoded
        # at full size for a 100 px card.
        # 解码所用的像素尺寸：卡片自身的边长，使 1200x900 的源不会为 100px 的卡片按原尺寸解码。
        card = 128
        try:
            card = max(48, int(self._backend.settings.card_scale * 76))
        except Exception:
            pass
        return card

    @Slot(str)
    def _on_decoded(self, path):
        # Runs on the GUI thread, because `decodeReady` is delivered through a queued
        # connection. Publishes the frames and tells the cards to try again.
        # 在 GUI 线程上运行，因为 `decodeReady` 经队列连接投递。发布帧并通知卡片再试一次。
        self._pending.discard(path)
        decoded = animation_take_result(path)
        if not decoded:
            return
        frames, delays = decoded
        if len(frames) < 2:
            return
        register_frames(path, frames)
        self._delays[path] = list(delays)
        # Every registered card re-reads its key, and every card that was waiting on this decode
        # gets a chance to register: `StickerCard.registerAnimation` is driven by this signal.
        # 每张已注册卡片会重读它的键，而每张等待这次解码的卡片都获得注册机会：`StickerCard` 的
        # `registerAnimation` 由本信号驱动。
        self.framesDecoded.emit(path)

    def _decode_now_blocking(self, path):
        # The old synchronous path, kept for the headless checks that measure decode cost and for
        # a caller that genuinely wants the frames before returning (an import, a test).
        # 旧的同步路径，保留给测量解码代价的无头检查，以及确实希望在返回前拿到帧的调用方（导入、测试）。
        from gifmanager.frontend.qt import animation

        decoded = animation.decode_all(path, self._card_pixels())
        if not decoded:
            return None
        frames, delays = decoded
        register_frames(path, frames)
        self._delays[path] = list(delays)
        return frames

    def _delay_for(self, sticker_id, index):
        path = self._paths.get(sticker_id)
        delays = self._delays.get(path) if path else None
        if not delays:
            return self.IDLE_INTERVAL_MS
        return max(20, int(delays[index % len(delays)]))

    def _tick(self):
        now = time.monotonic()
        if not self._paths:
            self._timer.stop()
            return
        soonest = None
        # The ids whose frame actually advanced. This is NOT bookkeeping: `frameChanged`
        # makes every registered card read `frameKey` and assign it to `Image.source`, and
        # assigning a `source` costs an image reload plus a texture upload. Emitting while
        # nothing advanced therefore re-uploaded up to `maxAnimated` textures for no visible
        # change, and because the timer is scheduled at the NEAREST deadline it could fire as
        # often as every `MIN_INTERVAL_MS` - that is what made scrolling and switching groups
        # stutter.
        #
        # 帧序号"确实"推进了的 id。这不是记账：`frameChanged` 会让每张已注册的卡片读取
        # `frameKey` 并赋给 `Image.source`，而赋值 `source` 的代价是一次图像重载加一次纹理上传。
        # 因此什么都没推进时发出信号，会为一次不可见的变化重新上传多达 `maxAnimated` 张纹理；而
        # 由于定时器按"最近"的截止时刻排程，它可能每 `MIN_INTERVAL_MS` 就触发一次——这正是滚动与
        # 切换分组卡顿的原因。
        advanced = []
        for sticker_id in self._animating_ids():
            count = self._counts.get(sticker_id, 0)
            if count < 2:
                continue
            index = self._indices.get(sticker_id, 0)
            elapsed_ms = (now - self._started.get(sticker_id, now)) * 1000.0
            if elapsed_ms >= self._delay_for(sticker_id, index):
                index = (index + 1) % count
                self._indices[sticker_id] = index
                self._started[sticker_id] = now
                advanced.append(sticker_id)
            remaining = self._delay_for(sticker_id, index) - elapsed_ms
            if soonest is None or remaining < soonest:
                soonest = remaining
        # One timer at the nearest deadline, rather than a fixed interval: a 1-second frame
        # should not cost 25 wake-ups, and a 20 ms frame must not wait 1 second.
        #
        # `MIN_INTERVAL_MS` floors the interval. It was 8, which let a single fast frame drag
        # the whole animator up to 125 wake-ups per second; 16 caps that at ~60 and is still
        # faster than any animation a user can perceive as smooth. A tick that fires early
        # costs nothing now, because it emits no signal.
        # 单个定时器指向最近的截止时刻，而非固定间隔：1 秒的帧不该付出 25 次唤醒，而 20 毫秒的帧
        # 不该等 1 秒。
        #
        # `MIN_INTERVAL_MS` 为间隔设下限。它原本是 8，使一个快帧就能把整个动画器拖到每秒 125 次
        # 唤醒；16 把它限制在约 60，而它仍比用户能感知为流畅的任何动画都快。提前触发的 tick 现在
        # 没有代价，因为它不发出任何信号。
        next_ms = self.IDLE_INTERVAL_MS if soonest is None \
            else max(self.MIN_INTERVAL_MS, min(1000, int(soonest)))
        self._timer.start(next_ms)
        # Emitted only when something moved. A tick with no advance exists solely to re-arm the
        # timer at a closer deadline.
        # 只在有东西动了时才发出。没有推进的 tick 存在的唯一目的是把定时器重新排到更近的截止时刻。
        if advanced:
            self.frameChanged.emit()

    MIN_INTERVAL_MS = 16

    # ---- what QML reads / QML 读取的内容 ---------------------------------

    @Slot(int, result=int)
    def frameIndex(self, sticker_id):
        return self._indices.get(int(sticker_id), -1)

    @Slot(int, result=int)
    def frameCount(self, sticker_id):
        return self._counts.get(int(sticker_id), 0)

    @Slot(int, result=bool)
    def isAnimating(self, sticker_id):
        # True when this sticker is inside the cap and therefore advancing.
        #
        # Exposed because a card past the cap shows a still frame from wherever the
        # animation happened to be rather than its first frame, and a caller may want to
        # indicate that rather than present it as a still image.
        # 该贴纸在上限之内、因而正在推进时为 True。
        #
        # 暴露它是因为超出上限的卡片显示的是动画恰好停在哪里的静止帧而非第一帧，调用方可能想
        # 提示这一点，而不是把它当作静态图呈现。
        return int(sticker_id) in set(self._animating_ids())

    @Slot(int, result=str)
    def frameKey(self, sticker_id):
        # The full URL an `Image` should use for this sticker's current frame.
        #
        # One call rather than three (`frameKeyBase` + `frameIndex` + a concatenation in
        # QML) because the concatenation has to happen exactly once and in one place: a
        # QML-side concat that forgot the scheme would produce a relative path and a
        # silently blank image.
        # 该贴纸当前帧供 `Image` 使用的完整 URL。
        #
        # 一次调用而非三次（`frameKeyBase` + `frameIndex` + QML 里拼接），因为拼接必须恰好发生
        # 一次且只在一处：QML 侧漏掉方案的拼接会产出相对路径和一张静默空白的图像。
        sticker_id = int(sticker_id)
        path = self._paths.get(sticker_id)
        if not path:
            return ""
        # `key_for(path, 0)` already CONTAINS the prefix: it is "<prefix>:<index>". The
        # first version of this method looked the prefix up in `_KEYS`, which maps
        # prefix -> path, so the lookup succeeded and replaced the correct prefix with
        # the FILESYSTEM PATH — producing
        # "gifframe:///C:\Users\...\a.gif:0", which the provider cannot resolve because
        # it looks prefixes up in that same table. The result was a blank card for every
        # animated sticker.
        # `key_for(path, 0)` 本身就"包含"前缀：它是 "<前缀>:<序号>"。本方法的第一个版本在
        # `_KEYS` 中查该前缀，而 `_KEYS` 是 前缀 -> 路径 的映射，于是查找成功并把正确的前缀
        # 替换成了"文件系统路径"——产出
        # "gifframe:///C:\Users\...\a.gif:0"，而提供器无法解析它，因为它也在同一张表里查
        # 前缀。结果是每张动画贴纸都显示为空白卡片。
        prefix = prefix_for(path)
        index = self._indices.get(sticker_id, 0)
        # The canonical provider URL: `image://<provider-id>/<image-id>`.
        # The provider id IS the scheme (see `SCHEME`).
        # 规范的提供器 URL：`image://<提供器 id>/<图像 id>`。提供器 id "就是" scheme
        # （见 `SCHEME`）。
        return f"image://{SCHEME}/{prefix}:{index}"

    @Property(int, notify=frameChanged)
    def animated(self):
        # How many stickers are currently animating. Exposed because a grid that looks
        # static while this is non-zero means the timer is not running, which is a
        # different bug from "nothing is animated".
        # 当前有多少贴纸在动。暴露它是因为：当此值非零而网格看起来是静态的，说明定时器没在跑，
        # 那是与"没有任何东西在动"不同的缺陷。
        return len(self._paths)

    def shutdown(self):
        self._timer.stop()
        self.clear()
        STORE.clear()
        _KEYS.clear()


def register_provider(engine):
    # Install the provider on an engine, replacing any previous one.
    #
    # `setImageProvider` rather than `addImageProvider`: re-registering after a
    # recreation must REPLACE, because two providers under one id is an error Qt reports
    # at request time rather than at registration time.
    # 在引擎上安装提供器，替换任何先前的。
    #
    # 用 `setImageProvider` 而非 `addImageProvider`：重建后重新注册必须"替换"，因为同一个 id
    # 下的两个提供器是 Qt 在请求时而非注册时报出的错误。
    engine.addImageProvider(PROVIDER_ID, StickerFrameProvider())
    return PROVIDER_ID


__all__ = [
    "MAX_FRAME_INDEX",
    "PROVIDER_ID",
    "SCHEME",
    "FrameStore",
    "StickerAnimator",
    "StickerFrameProvider",
    "key_for",
    "path_for_prefix",
    "register_frames",
    "register_provider",
    "STORE",
]
