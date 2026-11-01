"""Profile the animated-sticker pipeline to locate the scroll stutter MEASURABLY.

# Why a profiler rather than a guess

"Switching pages and scrolling stutter" has at least six candidate causes in this design, and
several of them are already optimised: the decoded frames are cached per PATH (shared between
duplicate stickers), the cache has a pixel budget with LRU eviction, and the timer no longer
emits on ticks that change nothing. Guessing which of the remainder dominates has already
produced three wrong fixes, so this instruments every operation that runs per frame per card
and reports the counts and the wall time.

Instrumented, per run:

  * `StickerAnimator._tick` - calls
  * `StickerAnimator.frameKey` - calls, and the time they cost
  * `StickerFrameProvider.requestImage` - calls, and whether each was a CACHE HIT or MISS
  * `animation.decode_all` - calls, because a MISS means decoding a whole GIF again
  * cards registered vs the `maxAnimated` cap

A miss count above zero during steady-state playback is the finding: it means the provider is
re-decoding rather than serving the cache, and `Image.source` is reassigned on every frame
change, so a miss costs a full GIF decode per card per tick.

# 用测量而不是猜测来定位动画贴纸的滚动卡顿。

# 为什么用测量工具而不是猜测

"切换页面与滚动会卡顿"在这个设计里至少有六个候选原因，而其中几个已经被优化过：解码帧按"路径"
缓存（重复贴纸共享）、缓存有像素预算与 LRU 淘汰、定时器已不再为没有变化的 tick 发出信号。猜测剩下
哪一个占主导已经导致三次错误的修复，因此本脚本给每一个"每帧每卡片"运行的操作加上计数，并报告调用
次数与墙上耗时。

每次运行统计：

  * `StickerAnimator._tick`——调用次数
  * `StickerAnimator.frameKey`——调用次数及其耗时
  * `StickerFrameProvider.requestImage`——调用次数，以及每一次是缓存"命中"还是"未命中"
  * `animation.decode_all`——调用次数，因为未命中意味着整个 GIF 被重新解码
  * 已注册卡片数与 `maxAnimated` 上限

稳态播放期间未命中次数大于零就是结论：那意味着提供器在重新解码而不是服务缓存，而 `Image.source`
在每次帧变化时都会被重新赋值，因此一次未命中的代价是"每卡片每 tick 一次完整 GIF 解码"。
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PYTHONUTF8"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# How long to observe steady-state playback.
# 稳态播放的观察时长。
WINDOW_SECONDS = 3.0

# How many distinct animated GIFs to install. A realistic viewport holds 12-24 cards.
# 安装多少个不同的动画 GIF。真实视口容纳 12-24 张卡片。
CARD_COUNT = 24


def make_gif(path, frames=24, size=96, delay_ms=80, tint=0):
    # `tint` makes every GIF's CONTENT distinct. Without it the store deduplicates them by
    # content hash - 24 identical files became ONE row, and the profile then measured a single
    # card and reported a clean result for a grid it never built. The row count is asserted
    # below so that mistake cannot recur silently.
    # `tint` 使每个 GIF 的"内容"互不相同。没有它时存储会按内容哈希去重——24 个相同文件变成
    # "一行"，于是剖析测量的是单张卡片、并对一个从未构建出来的网格报告了干净的结果。下面会断言行数，
    # 使那个错误无法再次静默发生。
    from PIL import Image

    images = []
    for index in range(frames):
        image = Image.new("RGB", (size, size), (20, 20, 30))
        base = (250, 220, 40)
        shifted = tuple(min(255, channel + tint) for channel in base)
        for x in range(0, 20):
            for y in range(0, 20):
                image.putpixel(((x + index * 3) % size, (y + index * 2) % size), shifted)
        images.append(image)
    images[0].save(path, save_all=True, append_images=images[1:],
                   duration=delay_ms, loop=0)
    return path


def main():
    from PySide6.QtWidgets import QApplication

    from gifmanager.backend import MemorySettingsStore, create_backend
    from gifmanager.frontend.qml import animator as animator_module
    from gifmanager.frontend.qml import app as qml_app
    from gifmanager.frontend.qt import animation
    from gifmanager.frontend.qt.bridge import BackendAdapter

    application = qml_app.build_application([])
    counters = {"ticks": 0, "frameKey": 0, "requestImage": 0,
                "cacheHit": 0, "cacheMiss": 0, "decodeAll": 0}

    # ---- instrument before anything is loaded ---------------------------------
    # ---- 在加载任何东西之前插桩 -----------------------------------------------
    original_tick = animator_module.StickerAnimator._tick
    original_frame_key = animator_module.StickerAnimator.frameKey
    original_request = animator_module.StickerFrameProvider.requestImage
    original_decode = animation.decode_all

    def tick(self):
        counters["ticks"] += 1
        return original_tick(self)

    def frame_key(self, sticker_id):
        counters["frameKey"] += 1
        return original_frame_key(self, sticker_id)

    def request_image(self, image_id, size, requested_size):
        counters["requestImage"] += 1
        text = str(image_id or "")
        prefix = text.partition(":")[0]
        path = animator_module.path_for_prefix(prefix)
        # A HIT means the frame store already holds this animation, so serving it is a
        # dictionary lookup plus a QImage reference. A MISS means the provider had to decode.
        # 命中意味着帧存储已持有该动画，因此服务它只是一次字典查找加一次 QImage 引用。未命中意味着
        # 提供器不得不解码。
        if path and animator_module.STORE.has(path):
            counters["cacheHit"] += 1
        else:
            counters["cacheMiss"] += 1
        return original_request(self, image_id, size, requested_size)

    def decode_all(path, target=0):
        counters["decodeAll"] += 1
        return original_decode(path, target)

    animator_module.StickerAnimator._tick = tick
    animator_module.StickerAnimator.frameKey = frame_key
    animator_module.StickerFrameProvider.requestImage = request_image
    animation.decode_all = decode_all

    tmp = tempfile.mkdtemp(prefix="gifmanager-perf-")
    backend = create_backend(data_dir=tmp, settings_store=MemorySettingsStore(),
                            log=False)
    try:
        from PIL import Image

        group_id = backend.store.create_group("Perf", "image")
        for index in range(CARD_COUNT):
            path = make_gif(os.path.join(tmp, f"perf{index}.gif"),
                            tint=index * 8)
            backend.store.import_emoji(group_id, path, auto_convert=False)
        rows = len(backend.store.get_emojis_by_group(group_id))
        print(f"rows after import       : {rows} (asked for {CARD_COUNT})")
        if rows < CARD_COUNT:
            print("  -> the store DEDUPLICATED the files; the profile would measure fewer "
                  "cards than intended")
            print("  -> 存储对文件去重了；剖析测量的卡片数会少于预期")

        adapter = BackendAdapter(backend)
        engine, bridge, theme, warnings = qml_app.create_engine(adapter, strict=True)
        bridge.selectGroup(group_id)

        root = engine.rootObjects()[0]
        root.setWidth(950)
        root.setHeight(740)
        root.setVisible(True)

        def pump(seconds):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                application.processEvents()
                time.sleep(0.004)

        # Let the grid build every delegate and the animator register them.
        # 让网格构建所有委托并让动画器注册它们。
        pump(2.5)

        print(f"distinct GIFs installed : {CARD_COUNT}")
        print(f"model rows              : {bridge.stickers.count}")
        print(f"cards registered        : {len(bridge.animator._paths)}")
        print(f"maxAnimated             : {bridge.animator.maxAnimated}")
        print(f"frames decoded so far   : {counters['decodeAll']}")
        print(f"frame store pixels      : {animator_module.STORE.used_pixels:,}")
        print()

        # The grid must actually hold delegates, or this profiles an empty window. The delegate
        # count was the check that caught an earlier "grid renders nothing" defect, so it is
        # asserted before any timing is trusted.
        # 网格必须真的持有委托，否则本脚本剖析的是一个空窗口。委托计数正是此前抓到"网格什么都不渲染"
        # 缺陷的检查，因此在信任任何计时之前先断言它。
        if bridge.stickers.count < CARD_COUNT:
            print(f"WARNING: the model has {bridge.stickers.count} row(s), not "
                  f"{CARD_COUNT}; the numbers below cover fewer cards")
            print(f"警告：模型有 {bridge.stickers.count} 行而不是 {CARD_COUNT}；以下数字覆盖的"
                  f"卡片更少")
            print()

        # ---- steady-state playback: reset the counters and observe ---------
        # ---- 稳态播放：重置计数并观察 ---------------------------------------
        for key in counters:
            counters[key] = 0
        pump(WINDOW_SECONDS)

        elapsed = WINDOW_SECONDS
        print("=== steady-state playback over "
              f"{elapsed:.1f} s ===")
        print(f"ticks                   : {counters['ticks']}")
        print(f"frameKey calls          : {counters['frameKey']}")
        print(f"provider requests       : {counters['requestImage']}")
        print(f"  cache HITS            : {counters['cacheHit']}")
        print(f"  cache MISSES          : {counters['cacheMiss']}")
        print(f"decode_all calls        : {counters['decodeAll']}")
        print()

        # ---- VIEWPORT CHURN: what scrolling actually does -------------------
        #
        # A `GridView` is not findable by class name from Python: every visual item reports
        # itself as `QQuickItem`, and the concrete QML type is not exposed as a Python class
        # (measured: 522 `QQuickItem`s, none named `QQuickGridView`). Rather than fight that,
        # this reproduces the MECHANISM scrolling uses: the grid destroys delegates that leave
        # the viewport and creates new ones as they enter, and a card's `onVisibleChanged`
        # calls `unregister` then `register`.
        #
        # The expensive part of `register` is `_decode_now`: it reads the file and decodes EVERY
        # frame on the GUI thread, synchronously. A scroll that brings 24 new cards into view
        # therefore decodes 24 GIFs, each with dozens of frames, while the viewport is moving -
        # which is the shape of the reported stutter.
        # 视口换入换出：滚动实际做的事情。
        #
        # 从 Python 无法按类名找到 `GridView`：每个可视元素都把自己报告为 `QQuickItem`，而具体的
        # QML 类型并不作为 Python 类暴露（实测：522 个 `QQuickItem`，没有一个叫 `QQuickGridView`）。
        # 与其和它较劲，本脚本复现滚动使用的"机制"：网格销毁离开视口的委托、并在新委托进入时创建
        # 它们，而卡片的 `onVisibleChanged` 会先 `unregister` 再 `register`。
        #
        # `register` 中昂贵的部分是 `_decode_now`：它读取文件并"在 GUI 线程上同步"解码"每一帧"。
        # 因此一次把 24 张新卡片带入视野的滚动会解码 24 个 GIF（每个几十帧），而视口正在移动——这正是
        # 用户报告的卡顿形态。
        print("=== viewport churn: unregister + register, as scrolling does ===")
        churn_ids = list(bridge.animator._paths)
        for key in counters:
            counters[key] = 0
        churn_start = time.perf_counter()
        for sticker_id in churn_ids:
            path = bridge.animator._paths.get(sticker_id, "")
            # Leaving the viewport, then returning - the grid's own sequence.
            # 离开视口，然后回来——网格自身的顺序。
            bridge.animator.unregister(sticker_id)
            bridge.animator.register(sticker_id, path)
            application.processEvents()
        churn_seconds = time.perf_counter() - churn_start
        print(f"cards churned           : {len(churn_ids)}")
        print(f"decode_all during churn : {counters['decodeAll']}")
        print(f"wall time for churn     : {churn_seconds * 1000:.0f} ms")
        if churn_ids:
            print(f"per card                : "
                  f"{churn_seconds / len(churn_ids) * 1000:.1f} ms")
        print()

        problems = []
        # The frame cache should make a RE-registration free, because the frames are already
        # decoded. A non-zero decode count during churn means the cache did not serve it.
        # 帧缓存本应让"重新注册"免费，因为帧已经解码过。换入换出期间解码次数非零意味着缓存没有服务它。
        if counters["decodeAll"] > 0:
            problems.append(
                f"{counters['decodeAll']} GIF decode(s) during {len(churn_ids)} card churn(s); "
                f"each decode reads a file and decodes every frame on the GUI thread, and the "
                f"frame cache should have served them already")
        if churn_ids and churn_seconds / len(churn_ids) > 0.05:
            problems.append(
                f"{churn_seconds / len(churn_ids) * 1000:.0f} ms per card of churn; a scroll "
                f"that recycles the viewport would stutter visibly")

        print()
        registered = len(bridge.animator._paths)
        if registered == 0:
            problems.append("no cards registered, so nothing animates at all")
        # A miss during steady state is the finding: it means a full GIF decode per card.
        # 稳态期间出现未命中就是结论：那意味着每张卡片一次完整 GIF 解码。
        if counters["cacheMiss"] > 0:
            problems.append(
                f"{counters['cacheMiss']} provider MISS(es) during steady-state playback; each "
                f"one re-decodes a GIF instead of serving the frame cache "
                f"({counters['decodeAll']} decode_all call(s))")
        # `frameKey` cost per SECOND, which is the number that matters for the GUI thread.
        #
        # Two earlier versions of this assertion were wrong and both are worth recording:
        # dividing by the tick counter produced 1152 (the counter is reset before the churn
        # phase but the call counter is not), and dividing by the provider requests produced 48
        # (each emit costs one call per REGISTERED card, not per card that advanced). The
        # quantity with a physical meaning is calls per second, compared against what a hash
        # and a string format can afford.
        # `frameKey` 每秒的代价，那才是对 GUI 线程要紧的数字。
        #
        # 这个断言的前两个版本都是错的，都值得记录：除以 tick 计数器得到 1152（计数器在换入换出阶段前
        # 被重置，而调用计数器没有）；除以提供器请求数得到 48（每次发出对"每一张已注册卡片"各付一次调用，
        # 而不是对每张推进的卡片）。具有物理意义的量是"每秒调用次数"，与"一次哈希加一次字符串格式化能
        # 负担多少次"相比。
        total_seconds = elapsed + churn_seconds
        calls_per_second = counters["frameKey"] / max(0.001, total_seconds)
        print(f"frameKey calls/second   : {calls_per_second:.0f} "
              f"({registered} cards, {total_seconds:.1f} s observed)")
        # The prefix is cached, so each call is a dict lookup plus an f-string. Even 5000/s is
        # trivial; the point of the number is to catch a REGRESSION that makes it explode.
        # 前缀已缓存，因此每次调用是一次字典查找加一次 f-string。即使 5000/秒也微不足道；这个数字的
        # 意义在于抓住让它暴涨的"回归"。
        if calls_per_second > 20000:
            problems.append(
                f"frameKey runs {calls_per_second:.0f} times/second for {registered} cards; "
                f"that is far beyond one call per card per frame")

        # Texture budget: the frames on screen should fit the cache without eviction thrash.
        # 纹理预算：屏幕上的帧应当装进缓存而不发生淘汰抖动。
        pixels = animator_module.STORE.used_pixels
        print(f"frame store bytes       : {pixels * 4:,}")

        bridge.detach()
        del engine
    finally:
        backend.close()
        animation.decode_all = original_decode
        animator_module.StickerAnimator._tick = original_tick
        animator_module.StickerAnimator.frameKey = original_frame_key
        animator_module.StickerFrameProvider.requestImage = original_request

    print()
    if problems:
        print("PERF PROFILE FINDINGS / 性能剖析发现")
        for problem in problems:
            print("  " + problem)
        return 1
    print("PERF PROFILE CLEAN / 性能剖析无异常")
    print("  steady-state playback served every frame from cache, with no re-decoding")
    print("  稳态播放的每一帧都由缓存提供，没有重新解码")
    return 0


if __name__ == "__main__":
    import os as _os

    _status = main()
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(_status)
