"""Profile with the user's OWN GIFs, which are three orders of magnitude larger than synthetic.

The synthetic GIFs used elsewhere are 96x96 with 24 frames. The user's library holds files up to
8.6 MB with a 130-frame average, and measured decode costs of 231 ms median / 383 ms worst. That
is the input the scroll complaint is about, so this profile uses it directly.

Reports, per phase:

  * decode cost for the largest files (the worst case a scroll can hit);
  * whether `register` BLOCKS on the GUI thread, which is the defect the async decode removes;
  * how much decoded frame data a viewport of these needs against the cache budget.

用用户"自己"的 GIF 剖析，它们比合成文件大三个数量级。其他地方使用的合成 GIF 是 96x96、24 帧。
用户的素材库有最大 8.6MB 的文件、平均 130 帧，实测解码代价中位 231 毫秒、最差 383 毫秒。那正是滚动
投诉所针对的输入，因此本剖析直接使用它。

按阶段报告：

  * 最大文件的解码代价（滚动可能遇到的最坏情况）；
  * `register` 是否在 GUI 线程上"阻塞"，那正是异步解码所消除的缺陷；
  * 一整个视口需要多少解码数据、以及它与缓存预算的对比。
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PYTHONUTF8"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SOURCE = r"C:\TLWorkStation\GIFManager\data\emojis\大肥鱼"

# How many of the largest files to install, and how long to observe playback.
# 安装多少个最大文件，以及观察播放多久。
INSTALL = 12
WINDOW_SECONDS = 3.0

# A `register` that blocks the GUI thread longer than this is a visible stall at 60 fps.
# `register` 阻塞 GUI 线程超过这个时间，就是 60fps 下可见的停顿。
BLOCKING_MS = 50


def main():
    from PySide6.QtWidgets import QApplication

    from gifmanager.backend import MemorySettingsStore, create_backend
    from gifmanager.frontend.qml import animator as animator_module
    from gifmanager.frontend.qml import app as qml_app
    from gifmanager.frontend.qt import animation
    from gifmanager.frontend.qt.bridge import BackendAdapter

    application = qml_app.build_application([])
    if not os.path.isdir(SOURCE):
        print(f"SKIPPED: {SOURCE} is not present")
        return 0

    # The largest files are the worst case a scroll can meet.
    # 最大的文件是滚动可能遇到的最坏情况。
    files = sorted((os.path.join(SOURCE, name) for name in os.listdir(SOURCE)
                    if name.lower().endswith(".gif")),
                   key=os.path.getsize, reverse=True)[:INSTALL]
    print(f"using {len(files)} of the largest files from the user's library")
    print(f"total packed           : "
          f"{sum(os.path.getsize(f) for f in files) / (1024 * 1024):.1f} MB")
    print()

    # ---- how long does one decode take, and does register block? --------------
    # ---- 一次解码要多久，以及 register 是否阻塞？ -----------------------------
    backend = create_backend(data_dir=os.path.dirname(files[0]),
                             settings_store=MemorySettingsStore(), log=False)
    ok = True
    try:
        animator = animator_module.StickerAnimator(backend)

        print("=== register() cost on the GUI thread ===")
        blocking = []
        for index, path in enumerate(files, start=1):
            started = time.perf_counter()
            count = animator.register(index, path)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            blocking.append((os.path.basename(path), count, elapsed_ms))

        for name, count, elapsed_ms in blocking:
            marker = "  <-- BLOCKS" if elapsed_ms > BLOCKING_MS else ""
            print(f"  {name:16} frames={count:>3}  register={elapsed_ms:>6.1f} ms{marker}")
        worst = max(entry[2] for entry in blocking)
        print()
        print(f"worst register()       : {worst:.1f} ms")
        if worst > BLOCKING_MS:
            ok = False
            print(f"  -> the GUI thread is blocked for {worst:.0f} ms, which is a visible")
            print(f"     stall; the decode must not run on the drawing thread")
            print(f"  -> GUI 线程被阻塞 {worst:.0f} 毫秒，那是可见的停顿；解码不得在绘制线程上运行")

        # ---- background decoding: does a queued decode actually land? ---------
        # ---- 后台解码：排队的解码真的会落地吗？ -------------------------------
        print()
        print("=== background decode ===")
        animator.clear()
        pending = []
        for index, path in enumerate(files, start=1):
            count = animator.register(index, path)
            pending.append(count)
        print(f"register() returned immediately, frame counts: {pending[:6]} ...")
        if all(count == 0 for count in pending):
            print("  -> every register reported 'nothing yet', as expected for an async decode")
            print("  -> 每次 register 都报告'暂时没有'，正如异步解码所预期")
        else:
            print("  -> some registers returned frames; those were already in the store")
            print("  -> 有些 register 返回了帧；那些已经在存储中")

        # Wait for the background decodes and confirm the frames arrive.
        # 等待后台解码并确认帧到达。
        decoded_paths = []
        animator.framesDecoded.connect(lambda path: decoded_paths.append(path))
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline and len(decoded_paths) < len(files):
            application.processEvents()
            time.sleep(0.05)
        print(f"framesDecoded signals  : {len(decoded_paths)} of {len(files)}")
        if len(decoded_paths) < len(files):
            ok = False
            print("  -> some decodes never reported back, so those cards would stay static")
            print("  -> 有些解码从未回报，因此那些卡片会一直是静态的")
        print(f"frame store            : "
              f"{animator_module.STORE.used_pixels * 4 / (1024 * 1024):.1f} MB "
              f"of {animator_module.FrameStore.DEFAULT_PIXEL_BUDGET * 4 / (1024 * 1024):.1f} MB")

        # ---- playback over the real files ------------------------------------
        # ---- 真实文件上的播放 -------------------------------------------------
        #
        # RE-REGISTER, because nothing else will. In the application the re-registration comes
        # from `StickerCard.onFramesDecoded` — a card that was told "nothing yet" tries again
        # when the frames land. There is no card here, so this profile must do what the card
        # does, or it measures an animator with nothing registered and reports the async design
        # as a failure.
        # "重新注册"，因为没有别的东西会做。在应用中重新注册来自 `StickerCard.onFramesDecoded`
        # ——被告知"暂时没有"的卡片会在帧落地时再试一次。此处没有卡片，因此本剖析必须做卡片所做的
        # 事，否则它测量的是一个没有任何注册的动画器、并把异步设计报告为失败。
        print()
        print(f"=== playback over {WINDOW_SECONDS:.0f} s (after re-registering) ===")
        for index, path in enumerate(files, start=1):
            animator.register(index, path)
        print(f"re-register frames     : "
              f"{[animator.frameCount(i) for i in range(1, len(files) + 1)][:6]} ...")

        ticks = {"n": 0}
        original_tick = animator_module.StickerAnimator._tick

        def counting_tick(self):
            ticks["n"] += 1
            return original_tick(self)

        animator_module.StickerAnimator._tick = counting_tick
        deadline = time.monotonic() + WINDOW_SECONDS
        while time.monotonic() < deadline:
            application.processEvents()
            time.sleep(0.004)
        animator_module.StickerAnimator._tick = original_tick
        print(f"ticks                  : {ticks['n']}")
        registered = len(animator._paths)
        print(f"cards registered       : {registered}")
        if registered == 0:
            ok = False
            print("  -> nothing registered even after the frames arrived, so no card animates")
            print("  -> 即使帧已到达也没有任何注册，因此没有卡片会动")
        if ticks["n"] == 0 and registered:
            ok = False
            print("  -> registered cards but the timer never ticked")
            print("  -> 已注册卡片但定时器从未滴答")

        animator.clear()
    finally:
        backend.close()
        _ = animation

    print()
    if not ok:
        print("REAL-GIF PROFILE FINDINGS / 真实 GIF 剖析发现")
        return 1
    print("REAL-GIF PROFILE OK / 真实 GIF 剖析正常")
    print("  register() returns immediately on the user's own 5-8 MB GIFs, and every")
    print("  background decode reports back")
    print("  在用户自己 5-8MB 的 GIF 上 register() 立即返回，且每次后台解码都会回报")
    return 0


if __name__ == "__main__":
    import os as _os

    _status = main()
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(_status)
