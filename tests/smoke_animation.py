"""Check that an animated GIF actually animates in the grid.

# What this measures

"Animated stickers do not move" has at least five candidate causes, and they are
indistinguishable by reading the QML:

  1. the native decoder returns one frame, so nothing is animatable;
  2. `animationEnabled` (the render-mode cap) is off;
  3. the card never calls `register`;
  4. the card registers but `frameKey` returns "" so `Image.source` never changes;
  5. the frames are served but the timer does not advance the index.

This builds a real animated GIF, registers it, and reports each of those five separately,
so the answer names the broken step instead of the symptom.

# 本脚本检查动画 GIF 在网格中"确实会动"。

# 它测量什么

"动画贴纸不动"至少有五个候选原因，而它们靠阅读 QML 无法区分：

  1. 原生解码器只返回一帧，因此没有可动的东西；
  2. `animationEnabled`（渲染模式上限）是关的；
  3. 卡片从未调用 `register`；
  4. 卡片注册了但 `frameKey` 返回 ""，于是 `Image.source` 从不变化；
  5. 帧被提供了但定时器没有推进序号。

本脚本构建一个真实的动画 GIF、注册它，并分别报告这五项，使答案点名坏掉的那一步而不是症状。
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PYTHONUTF8"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_animated_gif(path, frames=6, size=64, delay_ms=80):
    from PIL import Image

    images = []
    for index in range(frames):
        image = Image.new("RGB", (size, size), (30 + index * 30, 90, 200))
        # A white pixel whose position moves, so a static render is visually obvious.
        # 一个位置会移动的白点，使静态渲染在视觉上一望即知。
        image.putpixel((4 + index * 8, 32), (255, 255, 255))
        images.append(image)
    images[0].save(path, save_all=True, append_images=images[1:],
                   duration=delay_ms, loop=0)
    return path


def main():
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    from gifmanager.backend import MemorySettingsStore, create_backend
    from gifmanager.frontend.qml import animator
    from gifmanager.frontend.qml import app as qml_app
    from gifmanager.frontend.qt import animation
    from gifmanager.frontend.qt.bridge import BackendAdapter

    application = qml_app.build_application([])
    problems = []

    with tempfile.TemporaryDirectory(prefix="gifmanager-anim-") as tmp:
        gif = make_animated_gif(os.path.join(tmp, "animated.gif"))
        print("test GIF          :", os.path.getsize(gif), "bytes, 6 frames")

        # ---- 1. can the decoder produce frames at all? ---------------------
        # ---- 1. 解码器究竟能否产出多帧？ -----------------------------------
        print()
        print("==== 1. the decoder ====")
        print("native available  :", animation.available())
        decoded = animation.decode_all(gif, 48)
        if decoded is None:
            print("decode_all        : None  (no decoder for this platform)")
            # Absent decoder: SKIPPED when the caller accepts that environment, a FAILURE
            # otherwise — the same contract `smoke_playback` uses, for the same reason: on a
            # machine where the decoder IS expected, silently skipping is how a broken build
            # looks green.
            # 缺少解码器：调用方接受该环境时 SKIPPED，否则失败——与 `smoke_playback` 同一契约、
            # 同一原因：在期望有解码器的机器上，静默跳过正是坏掉的构建看起来是绿的方式。
            if "--allow-missing-decoder" in sys.argv:
                print()
                print("ANIMATION CHECK SKIPPED / 动画检查已跳过")
                print("  no GIF decoder is available on this platform")
                print("  本平台没有可用的 GIF 解码器")
                return 0
            print()
            print("ANIMATION CHECK FAILED / 动画检查未通过")
            print("  no GIF decoder; re-run with --allow-missing-decoder to accept this")
            print("  没有 GIF 解码器；用 --allow-missing-decoder 重跑以接受此环境")
            return 1
        else:
            frame_list, delays = decoded
            frames = frame_list
            print("decoded frames    :", len(frame_list))
            print("decoded delays    :", delays)
            if len(frame_list) < 2:
                problems.append(
                    f"the decoder returned {len(frame_list)} frame(s); an animated GIF "
                    f"needs more than one")

        backend = create_backend(data_dir=tmp, settings_store=MemorySettingsStore(),
                                log=False)
        try:
            group_id = backend.store.create_group("Anim", "image")
            backend.store.import_emoji(group_id, gif, auto_convert=False)
            adapter = BackendAdapter(backend)
            engine, bridge, theme, warnings = qml_app.create_engine(adapter,
                                                                   strict=True)

            # ---- 2. is animation enabled by the render-mode cap? -----------
            # ---- 2. 渲染模式上限是否允许动画？ -----------------------------
            print()
            print("==== 2. the render mode ====")
            print("animationEnabled  :", bridge.animationEnabled)
            if not bridge.animationEnabled:
                problems.append(
                    "animationEnabled is False: the render-mode cap is suppressing every "
                    "animation, so no card will ever animate")

            # ---- 3 and 4. register the sticker and read the frame key ------
            # ---- 3 与 4. 注册贴纸并读取帧键 -------------------------------
            #
            # `register` now decodes in the BACKGROUND, so its first call is EXPECTED to report
            # 0 frames — that is the design, not a defect, and it is what keeps a 231 ms decode
            # off the GUI thread. The frames arrive on `framesDecoded`, and a card re-registers
            # itself when they do (`StickerCard.onFramesDecoded`). This check therefore drives
            # the same sequence a card does.
            #
            # `register` 现在在"后台"解码，因此它第一次调用"预期"报告 0 帧——那是设计而不是缺陷，
            # 也正是它让 231 毫秒的解码离开 GUI 线程。帧经 `framesDecoded` 到达，而卡片会在那时自行
            # 重新注册（`StickerCard.onFramesDecoded`）。因此本检查驱动与卡片相同的序列。
            print()
            print("==== 3/4. the animator ====")
            rows = backend.store.get_emojis_by_group(group_id)
            sticker_id = rows[0]["id"]
            path = backend.store.emoji_filepath(rows[0])

            first_call = bridge.animator.register(sticker_id, path)
            print("register (async)  :", first_call)

            # Wait for the background decode, exactly as the event loop does in the application.
            # 等待后台解码，与应用中的事件循环所做的一致。
            landed = []
            bridge.animator.framesDecoded.connect(lambda p: landed.append(p))
            deadline = time.monotonic() + 20.0
            while time.monotonic() < deadline and not landed:
                application.processEvents()
                time.sleep(0.02)
            print("framesDecoded     :", len(landed), "signal(s)")
            if not landed:
                problems.append(
                    "the background decode never reported back, so a card would show its still "
                    "thumbnail forever")

            # Re-register, which is what the card's handler does.
            # 重新注册，这正是卡片的处理函数所做的。
            count = bridge.animator.register(sticker_id, path)
            print("register (again)  :", count)
            if count < 2:
                problems.append(
                    f"after the decode landed, register() reported {count} frame(s); the card "
                    f"would decide this is a still image")

            key = bridge.animator.frameKey(sticker_id)
            print("frameKey          :", repr(key))
            if not key:
                problems.append("frameKey returned an empty string, so Image.source has "
                                "nothing to show")
            # A frame key must be a PROVIDER URL, not a path. The earlier version of this
            # check looked for a path separator and used `/`, which every `image://` URL
            # contains — so it reported a defect on a correct key. The assertions that
            # actually distinguish the two are: the key starts with the provider scheme, and
            # the image id carries no Windows drive letter or backslash.
            # 帧键必须是"提供器 URL"而不是路径。本检查的早期版本查找路径分隔符并用了 `/`，而每个
            # `image://` URL 都含它——于是它在正确的键上报出了缺陷。真正能区分两者的断言是：键以
            # 提供器方案开头，且图像 id 不含 Windows 盘符或反斜杠。
            if key and not key.startswith("image://"):
                problems.append(
                    f"frameKey is not a provider URL ({key!r}); the image provider "
                    f"cannot resolve it")
            if key and "\\" in key:
                problems.append(f"frameKey leaked a filesystem path ({key!r})")
            if key and ":" in key.split("/", 3)[-1] and "\\" not in key:
                # `image://gifframes/<16 hex>:<index>` is the expected shape; a drive letter
                # would put a second colon in a position that is not the frame index.
                # `image://gifframes/<16 位十六进制>:<序号>` 是预期形状；盘符会在帧序号之外
                # 的位置放入第二个冒号。
                image_id = key.split("/", 3)[-1]
                head, _, tail = image_id.partition(":")
                if not tail.isdigit():
                    problems.append(
                        f"frameKey's id is not <prefix>:<index> ({image_id!r})")

            # ---- 5. does the timer advance the index? ---------------------
            # ---- 5. 定时器是否推进序号？ -----------------------------------
            print()
            print("==== 5. advancing ====")
            first = bridge.animator.frameIndex(sticker_id)
            # Drive the animator's own tick handler with a back-dated start rather than
            # sleeping: a wall-clock wait makes this check flaky under load.
            # 用回拨的起始时刻驱动动画器自身的 tick 处理器，而不是睡眠：墙上时钟等待会让本检查在
            # 负载下不稳定。
            animation_module = sys.modules["gifmanager.frontend.qml.animator"]
            deadline = time.monotonic() + 2.0
            seen = {first}
            while time.monotonic() < deadline and len(seen) < min(3, len(frames)):
                bridge.animator._started[sticker_id] = time.monotonic() - 10.0
                bridge.animator._tick()
                application.processEvents()
                seen.add(bridge.animator.frameIndex(sticker_id))
                time.sleep(0.02)
            print("frame indices seen:", sorted(seen))
            if len(seen) < 2:
                problems.append(
                    f"the frame index never advanced past {first}; the timer is not "
                    f"driving the animation")

            # And the URL must CHANGE, which is what the Image element reacts to.
            # 而 URL 必须"变化"，那才是 Image 元素作出反应的东西。
            keys = set()
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and len(keys) < 2:
                bridge.animator._started[sticker_id] = time.monotonic() - 10.0
                bridge.animator._tick()
                application.processEvents()
                keys.add(bridge.animator.frameKey(sticker_id))
                time.sleep(0.02)
            print("frame keys seen   :", len(keys))
            if len(keys) < 2:
                problems.append("frameKey never changed, so the card would show one frame")

            # Unregistering must also release the store PIN.
            #
            # `register` is called again on every delegate re-bind, so an unconditional pin leaked
            # one
            # reference per call while `unregister` released one - the animation count returned to
            # zero
            # while paths stayed pinned forever, which quietly disables the eviction budget.
            # 注销也必须释放存储的固定。
            #
            # 委托每次重新绑定都会再次调用 `register`，因此无条件的 pin 每次调用泄漏一个引用，而
            # `unregister` 只释放一个——动画计数回到零，路径却永久被固定，使淘汰预算悄悄失效。
            # Re-register the SAME card, the way a delegate re-bind does. This is what turned the
            # original pin into a leak: `register` pinned unconditionally while `unregister`
            # released
            # exactly one reference, so N re-binds left N-1 pins behind for ever. A test that
            # registers
            # only once cannot see that, which is why this calls it again deliberately.
            # 重新注册"同一张"卡片，模拟委托重新绑定。这正是把固定变成泄漏的原因：`register` 无条件
            # 固定，而 `unregister` 只释放一个引用，因此 N 次重绑会永久留下 N-1 个固定。只注册一次的
            # 测试看不到这一点，所以这里刻意再调一次。
            bridge.animator.register(sticker_id, path)
            bridge.animator.register(sticker_id, path)
            application.processEvents()
            pinned_while_registered = len(animator.STORE._pin_counts)
            print(f"  pins while registered   : {pinned_while_registered}")
            if pinned_while_registered != 1:
                problems.append(
                    f"{pinned_while_registered} pins for ONE playing card; re-registering must be "
                    f"idempotent or every delegate re-bind leaks a reference that can never be "
                    f"released")
            bridge.animator.unregister(sticker_id)
            settle = time.monotonic() + 0.3
            while time.monotonic() < settle:
                application.processEvents()
                time.sleep(0.01)
            leaked = len(animator.STORE._pin_counts)
            print(f"  pinned after unregister : {leaked}")
            if leaked:
                problems.append(
                    f"{leaked} pin(s) survived unregister, so those paths can never be evicted")
            bridge.detach()
            del engine
        finally:
            backend.close()

    # ---- 5. a PLAYING animation survives eviction pressure -----------------
    # ---- 5. 正在播放的动画在淘汰压力下存活 --------------------------------
    #
    # This is the regression guard for the warning flood reported while scrolling fast:
    #
    #     QML QQuickImage: Failed to get image from provider: image://gifframes/...
    #
    # Eviction is "oldest stored first", but a playing card keeps requesting frame N and never
    # re-`put`s anything, so it was the best eviction candidate precisely while it was still on
    # screen.
    # Once its frames were gone every request returned a null image, one warning per frame per card.
    # 这是"快速滚动时大量警告"的回归保护：
    #
    #     QML QQuickImage: Failed to get image from provider: image://gifframes/...
    #
    # 淘汰策略是"最久未被存入者先出"，但播放中的卡片会一直请求第 N 帧、从不再 `put` 任何东西，因此它
    # 恰好会在仍处于屏幕上时成为最优先的淘汰对象。帧一旦消失，每次请求都返回空图像，每张卡片每帧一条警告。
    print()
    print("==== 5. pinning a playing animation ====")
    store = animator.FrameStore(pixel_budget=2 * 100 * 100)

    def frames_for():
        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        image.fill(0xFF202020)
        return [image]

    playing = os.path.join(tempfile.mkdtemp(), "playing.gif")
    scrolled = os.path.join(tempfile.mkdtemp(), "scrolled.gif")
    arriving = os.path.join(tempfile.mkdtemp(), "arriving.gif")

    store.put(playing, frames_for())
    store.pin(playing)
    store.put(scrolled, frames_for())
    # A third animation arrives while scrolling; the budget holds two, so one is evicted.
    # 滚动期间第三个动画到达；预算只装得下两个，因此有一个被淘汰。
    store.put(arriving, frames_for())

    print(f"  pinned survived    : {store.has(playing)}")
    print(f"  unpinned evicted   : {not store.has(scrolled)}")
    if not store.has(playing):
        problems.append(
            "a PINNED (still playing) animation was evicted under budget pressure, so its card "
            "will request frames the store no longer has - that is the null-image warning flood")
    if store.has(scrolled):
        problems.append(
            "an unpinned animation was kept while a newer one was stored, so eviction stopped "
            "respecting the budget")

    # Reference counting: two cards on one file, one leaving must not unpin it.
    # 引用计数：两张卡片显示同一文件，其中一张离开不得解除固定。
    store.pin(arriving)
    store.pin(arriving)
    store.unpin(arriving)
    print(f"  refcount holds     : {store.pinned(arriving)}")
    if not store.pinned(arriving):
        problems.append(
            "unpinning one of two references made the path evictable while another card still "
            "plays it")
    store.unpin(arriving)

    # ---- 6. the decode queue must drop stale work and prefer the newest ----
    # ---- 6. 解码队列必须丢弃陈旧任务并优先最新 ----------------
    #
    # The pool has two threads, and a fast scroll through a large library queues a decode for every
    # card
    # that passes. Under FIFO the cards that are on screen RIGHT NOW sat behind work for rows the
    # user had
    # already passed, which is the "1000 stickers, nothing animates for a long time" worry. Two
    # properties
    # are asserted here: a job nobody wants any more must not decode at all, and a job that had to
    # wait
    # must run newest-first.
    # 线程池只有两个线程，而在大素材库里快速滚动会为每张经过的卡片排入一次解码。FIFO 下"此刻在屏幕上"
    # 的卡片排在用户早已滚过的那些行之后，这正是"1000 张贴纸时很久都不渲染"的担忧。这里断言两个性质：
    # 已经没有谁需要的任务不得解码，以及排过队的任务必须"最新优先"。
    print()
    print("==== 6. the decode queue ====")
    import threading

    real_decode = animation.decode_all
    lock = threading.Lock()
    calls = []

    def fake_decode(path, pixels):
        with lock:
            calls.append(path)
        time.sleep(0.05)
        return None

    try:
        animation.decode_all = fake_decode

        stale = animator._FrameDecoder()
        drained = []
        stale.ready.connect(lambda path: drained.append(path))
        for name in ("s1.gif", "s2.gif", "s3.gif"):
            stale.submit(name, 64, lambda path: False)
        stale._pool.waitForDone(5000)
        # `ready` is a QUEUED signal, so it only reaches the lambda once the event loop runs.
        # `ready` 是"队列"信号，因此只有在事件循环运行后才会到达 lambda。
        settle = time.monotonic() + 0.4
        while time.monotonic() < settle:
            application.processEvents()
            time.sleep(0.01)
        with lock:
            stale_calls = list(calls)
        print(f"  stale decoded      : {len(stale_calls)}")
        print(f"  stale ready fired  : {len(drained)}")
        if stale_calls:
            problems.append(
                f"stale decode jobs still ran ({stale_calls}), so a scroll-away holds "
                f"the two workers for hundreds of milliseconds each")
        if len(drained) != 3:
            problems.append(
                f"a dropped job fired {len(drained)} ready signals for 3 jobs; the "
                f"pending set would never clear and the path could never be queued again")

        with lock:
            calls.clear()
        order = []

        def ordered_decode(path, pixels):
            with lock:
                order.append(path)
            time.sleep(0.05)
            return None

        animation.decode_all = ordered_decode
        fresh = animator._FrameDecoder()
        fresh._pool.setMaxThreadCount(1)
        for name in ("first.gif", "second.gif", "third.gif", "fourth.gif"):
            fresh.submit(name, 64, lambda path: True)
        fresh._pool.waitForDone(5000)
        print(f"  decode order       : {order}")
        if order[:1] != ["first.gif"]:
            problems.append(f"the first submission should start at once, got {order}")
        if order[1:] != ["fourth.gif", "third.gif", "second.gif"]:
            problems.append(f"queued jobs are not newest-first: {order[1:]}")
    finally:
        animation.decode_all = real_decode

    print()
    if problems:
        print("ANIMATION CHECK FAILED / 动画检查未通过")
        for problem in problems:
            print("  " + problem)
        return 1
    print("ANIMATION CHECK OK / 动画检查通过")
    print("  the decoder produces multiple frames, the animator serves each one by key,")
    print("  the index and key both advance, and a playing animation is not evicted")
    print("  解码器产出多帧、动画器按键提供每一帧、序号与键都会推进，且正在播放的动画不会被淘汰")
    return 0


if __name__ == "__main__":
    import os as _os

    _status = main()
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(_status)
