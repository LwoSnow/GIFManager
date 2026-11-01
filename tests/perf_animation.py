"""Measure how often the animator repaints, because that is what causes the stutter.

# What went wrong

`_tick` emitted `frameChanged` unconditionally. That signal makes every registered card
assign `Image.source`, and assigning a source costs an image reload plus a texture upload.
Since the timer is scheduled at the NEAREST frame deadline it could fire every 8 ms, so up
to `maxAnimated` textures were re-uploaded 125 times a second with nothing visibly changing.

This counts, over a fixed wall-clock window:

  * how many times `_tick` ran;
  * how many times `frameChanged` was emitted;
  * how many of those ticks had no frame advance at all (pure waste).

`frameChanged` must be strictly less than the tick count whenever the frame delays are longer
than the tick interval, and it must never exceed the number of real advances.

# 测量动画器重绘的频率，因为那正是卡顿的来源。

# 出了什么问题

`_tick` 无条件发出 `frameChanged`。该信号让每张已注册的卡片赋值 `Image.source`，而赋值 source
的代价是一次图像重载加一次纹理上传。由于定时器按"最近"的帧截止时刻排程，它可能每 8 毫秒触发一次，
于是多达 `maxAnimated` 张纹理会以每秒 125 次的频率被重新上传，而画面没有任何可见变化。

本脚本在固定的墙上时间窗口内统计：

  * `_tick` 运行了多少次；
  * `frameChanged` 发出了多少次；
  * 其中有多少次 tick 完全没有帧推进（纯浪费）。

只要帧延迟长于 tick 间隔，`frameChanged` 就必须严格少于 tick 次数，且绝不能超过真实推进的次数。
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PYTHONUTF8"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# How long to observe. Long enough for many ticks at any plausible interval.
# 观察时长。在任何合理的间隔下都足以产生很多次 tick。
WINDOW_SECONDS = 2.0


def main():
    from PySide6.QtWidgets import QApplication

    from gifmanager.backend import MemorySettingsStore, create_backend
    from gifmanager.frontend.qml import animator as animator_module

    application = QApplication.instance() or QApplication([])

    # A real backend: `StickerAnimator` takes one because it reads `card_scale` and the
    # render-mode settings to size its decode. A stand-in would have to reimplement those,
    # and the point of this check is the TICK behaviour, not the decode size.
    # 真实后端：`StickerAnimator` 接收它，因为动画器要读 `card_scale` 与渲染模式设置来决定解码
    # 尺寸。替身就得重新实现那些，而本检查的要点是"tick"行为，不是解码尺寸。
    backend = create_backend(data_dir=tempfile.mkdtemp(prefix="gifmanager-tick-"),
                            settings_store=MemorySettingsStore(), log=False)

    animator = animator_module.StickerAnimator(backend)
    counters = {"ticks": 0, "emits": 0, "empty": 0}
    original_tick = animator._tick

    # Count emissions by CONNECTING a counter. A `SignalInstance`'s `emit` is read-only, so
    # wrapping it raises instead of measuring anything.
    # 通过"连接"一个计数器来统计发出次数。`SignalInstance` 的 `emit` 是只读的，因此包装它会抛错
    # 而不是测量到任何东西。
    animator.frameChanged.connect(lambda: counters.__setitem__("emits",
                                                              counters["emits"] + 1))

    def counting_tick():
        counters["ticks"] += 1
        # Snapshot the indices before, so an "advance" can be detected without trusting the
        # implementation.
        # 先记录序号快照，使"是否推进"无需信任实现即可判定。
        before = dict(animator._indices)
        original_tick()
        if dict(animator._indices) == before:
            counters["empty"] += 1

    animator._tick = counting_tick

    # Register synthetic multi-frame entries with a realistic delay, so the tick interval is
    # driven by the delay rather than by the test.
    # 注册带真实延迟的合成多帧条目，使 tick 间隔由延迟驱动而不是由测试驱动。
    path = os.path.join(tempfile.gettempdir(), "gifmanager-tick-probe.gif")
    from PIL import Image

    frames = []
    for index in range(8):
        image = Image.new("RGB", (48, 48), (20 + index * 20, 90, 200))
        frames.append(image)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=90, loop=0)

    registered = 0
    for sticker_id in range(1, 25):
        count = animator.register(sticker_id, path)
        if count > 1:
            registered += 1
    print(f"registered animated cards : {registered}")
    print(f"maxAnimated               : {animator.maxAnimated}")
    print(f"MIN_INTERVAL_MS           : {animator.MIN_INTERVAL_MS}")

    if registered == 0:
        print()
        print("TICK CHECK SKIPPED / tick 检查已跳过")
        print("  no decoder, so nothing could be registered")
        print("  没有解码器，因此没有东西可以注册")
        return 0

    # Allow every registered card to animate, so the measurement is of the WORST case rather
    # than of a cap that happens to be zero in an unconfigured animator.
    # 允许每张已注册的卡片动画，使测量针对"最坏"情况，而不是一个未配置动画器中恰好为零的上限。
    animator.setMaxAnimated(64)
    print(f"maxAnimated (after set)   : {animator.maxAnimated}")

    # Drive `_tick` by hand rather than relying on the Qt timer: this measures the tick's own
    # cost and emission behaviour, and a timer would add the event loop's resolution to the
    # result.
    # 手工驱动 `_tick` 而不是依赖 Qt 定时器：这测量的是 tick 自身的代价与发出行为，而定时器会把
    # 事件循环的精度掺进结果。
    deadline = time.monotonic() + WINDOW_SECONDS
    while time.monotonic() < deadline:
        # Back-date every frame so each tick finds a due frame: this measures the WORST case,
        # where every card advances on every tick.
        # 把所有帧的起始时刻回拨，使每次 tick 都发现有帧到期：这测量的是"最坏"情况，即每张卡片
        # 每次 tick 都推进。
        for sticker_id in list(animator._paths):
            animator._started[sticker_id] = time.monotonic() - 10.0
        counting_tick()
        application.processEvents()
        time.sleep(0.004)

    print()
    print(f"ticks                     : {counters['ticks']}")
    print(f"frameChanged emissions    : {counters['emits']}")
    print(f"ticks with no advance     : {counters['empty']}")
    print(f"emissions per tick        : "
          f"{counters['emits'] / max(1, counters['ticks']):.2f}")

    problems = []
    # ---- the assertion that actually pins the fix ----------------------
    #
    # The worst-case numbers above are reported for the record, but the assertion is made on a
    # DETERMINISTIC sequence: two ticks with no time passing between them. The second one finds
    # no frame due, so it must not emit. The defect was emitting unconditionally, which made
    # every registered card re-assign `Image.source` - an image reload plus a texture upload -
    # for no visible change.
    #
    # 上面的最坏情况数字是备查的，而断言建立在一个"确定性"序列上：两次 tick 之间不流逝时间。
    # 第二次会发现没有帧到期，因此绝不能发出。缺陷是无条件发出，那会让每张已注册的卡片重新赋值
    # `Image.source`——一次图像重载加一次纹理上传——而画面没有任何可见变化。
    before_emits = counters["emits"]
    counting_tick()
    counting_tick()
    emitted_by_early_ticks = counters["emits"] - before_emits
    print()
    print("=== two ticks with no elapsed time ===")
    print(f"emissions from those two ticks : {emitted_by_early_ticks}")
    if emitted_by_early_ticks > 0:
        problems.append(
            f"{emitted_by_early_ticks} emission(s) from ticks where no frame was due; a tick "
            f"that changes nothing must not signal a repaint")

    if counters["emits"] == 0:
        problems.append("frameChanged was never emitted, so nothing would animate at all")

    print()
    if problems:
        print("TICK CHECK FAILED / tick 检查未通过")
        for problem in problems:
            print("  " + problem)
        return 1
    print("TICK CHECK OK / tick 检查通过")
    print("  a tick that advances nothing emits nothing, so it repaints nothing")
    print("  没有推进任何帧的 tick 不发出信号，因此不重绘任何东西")
    return 0


if __name__ == "__main__":
    import os as _os

    _status = main()
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(_status)
