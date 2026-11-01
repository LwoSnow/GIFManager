"""Prove that an animated GIF reaches the SCREEN, by comparing two renders.

# Why a pixel comparison

A Python-side check can report six frames, a live timer, advancing keys and a registered
provider while the user still sees a still image — because every one of those is upstream of
the `Image` element. The only assertion that covers the whole path is: render the grid,
advance the animation, render again, and compare the two images. If they are identical, the
animation never reached the screen regardless of what Python says.

It writes both renders so the difference can also be LOOKED at.

# 通过比较两次渲染，证明动画 GIF 确实到达了"屏幕"。

# 为什么用像素比较

Python 侧的检查可以报告六帧、活跃的定时器、推进的键与已注册的提供器，而用户仍然只看到静态图——
因为那些全都在 `Image` 元素的上游。唯一覆盖整条路径的断言是：渲染网格、推进动画、再次渲染，然后
比较两张图。如果它们完全相同，那么无论 Python 说什么，动画都没有到达屏幕。

它会把两次渲染都写出来，因此差异也可以被"看到"。
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PYTHONUTF8"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_animated_gif(path, frames=8, size=80, delay_ms=90):
    from PIL import Image

    images = []
    for index in range(frames):
        # A large moving block, so a still render differs OBVIOUSLY from a moving one.
        # 一个大幅移动的方块，使静态渲染与运动渲染的差异"一目了然"。
        image = Image.new("RGB", (size, size), (20, 20, 30))
        for x in range(0, 24):
            for y in range(0, 24):
                image.putpixel(((x + index * 7) % size, (y + index * 5) % size),
                               (255, 240, 60))
        images.append(image)
    images[0].save(path, save_all=True, append_images=images[1:],
                   duration=delay_ms, loop=0)
    return path


def bridge_animation_available(animation):
    # Whether a decoder exists at all, asked before building anything.
    # 是否存在解码器，在构建任何东西之前询问。
    return bool(animation.available())


def main(argv):
    from PySide6.QtWidgets import QApplication

    from gifmanager.backend import MemorySettingsStore, create_backend
    from gifmanager.frontend.qml import app as qml_app
    from gifmanager.frontend.qt import animation
    from gifmanager.frontend.qt.bridge import BackendAdapter

    first_out = argv[0] if argv else "anim_frame_a.png"
    second_out = argv[1] if len(argv) > 1 else "anim_frame_b.png"

    application = qml_app.build_application([])
    problems = []

    if not bridge_animation_available(animation):
        # No decoder: SKIPPED when the caller accepts the environment, a failure otherwise.
        # 没有解码器：调用方接受该环境时 SKIPPED，否则失败。
        if "--allow-missing-decoder" in sys.argv:
            print("ANIMATION PIXEL CHECK SKIPPED / 动画像素检查已跳过")
            print("  no GIF decoder is available on this platform")
            print("  本平台没有可用的 GIF 解码器")
            return 0
        print("ANIMATION PIXEL CHECK FAILED / 动画像素检查未通过")
        print("  no GIF decoder; re-run with --allow-missing-decoder to accept this")
        print("  没有 GIF 解码器；用 --allow-missing-decoder 重跑以接受此环境")
        return 1

    with tempfile.TemporaryDirectory(prefix="gifmanager-anim-px-") as tmp:
        gif = make_animated_gif(os.path.join(tmp, "moving.gif"))
        backend = create_backend(data_dir=tmp, settings_store=MemorySettingsStore(),
                                log=False)
        try:
            group_id = backend.store.create_group("Anim", "image")
            backend.store.import_emoji(group_id, gif, auto_convert=False)
            adapter = BackendAdapter(backend)
            engine, bridge, theme, warnings = qml_app.create_engine(adapter,
                                                                   strict=True)
            for warning in warnings:
                print("engine warning:", warning)

            bridge.selectGroup(group_id)
            root = engine.rootObjects()[0]
            root.setWidth(520)
            root.setHeight(420)
            root.setVisible(True)

            def settle(seconds):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    application.processEvents()
                    time.sleep(0.02)

            settle(1.5)

            # Which card, and is it animating at all?
            # 哪张卡片，以及它是否在动画？
            sticker_id = backend.store.get_emojis_by_group(group_id)[0]["id"]
            print("animationEnabled :", bridge.animationEnabled)
            print("frameCount       :", bridge.animator.frameCount(sticker_id))
            print("isAnimating      :", bridge.animator.isAnimating(sticker_id))
            print("frameKey now     :", bridge.animator.frameKey(sticker_id))

            if not bridge.animationEnabled:
                problems.append(
                    "animationEnabled is False: the render-mode cap suppresses animation, "
                    "so this is a SETTING and not a code defect")

            # Render two DELIBERATELY different frames.
            #
            # The first version ticked the animator six times and re-rendered, which is a
            # race: the running timer can advance the index between the render and the
            # comparison, and it did — both captures landed on the same frame and the check
            # reported "the animation never reached the screen" for a correct animation.
            #
            # Setting the index directly removes the race and still tests the thing that
            # matters: does a frame CHANGE reach the pixels? The animator's own timer is
            # covered separately by `smoke_animation`.
            # 渲染"刻意不同的"两帧。
            #
            # 第一个版本 tick 动画器六次后重新渲染，这是一个竞态：运行中的定时器可能在渲染与比较之间
            # 推进序号，而它确实这样做了——两次截取落在同一帧上，于是本检查对一个正确的动画报出"动画
            # 从未到达屏幕"。
            #
            # 直接设置序号消除了竞态，同时仍然测试要紧的那件事：帧的"变化"是否到达像素？动画器自身的
            # 定时器由 `smoke_animation` 单独覆盖。
            from gifmanager.frontend.qml import animator as _animator

            frame_total = bridge.animator.frameCount(sticker_id)

            def show_frame(index):
                # Force this frame and let the `frameChanged` signal reach QML, then render.
                # 强制显示该帧，让 `frameChanged` 信号到达 QML，然后渲染。
                bridge.animator._indices[sticker_id] = index
                bridge.animator._started[sticker_id] = time.monotonic()
                bridge.animator.frameChanged.emit()
                settle(0.5)
                return root.grabWindow()

            first = show_frame(0)
            first.save(first_out, "PNG")
            second = show_frame(max(1, frame_total // 2))
            second.save(second_out, "PNG")
            print(f"compared frame 0 with frame {max(1, frame_total // 2)} "
                  f"of {frame_total}")

            # Compare the two renders pixel by pixel. `grabWindow()` returns a `QImage`
            # already — NOT a pixmap — so there is no `toImage()` step.
            # 逐像素比较两次渲染。`grabWindow()` 返回的"已经"是 `QImage`，不是 pixmap，因此没有
            # `toImage()` 这一步。
            image_a = first
            image_b = second
            if image_a.size() != image_b.size():
                problems.append("the two renders have different sizes")
            else:
                differing = 0
                sampled = 0
                step = 3
                for y in range(0, image_a.height(), step):
                    for x in range(0, image_a.width(), step):
                        sampled += 1
                        if image_a.pixel(x, y) != image_b.pixel(x, y):
                            differing += 1
                print()
                print(f"sampled {sampled} pixel(s), {differing} differ "
                      f"({100.0 * differing / max(1, sampled):.1f}%)")
                if differing == 0:
                    problems.append(
                        "the two renders are IDENTICAL: the animation never reached the "
                        "screen, so the card is showing one frame forever")
                elif differing < sampled * 0.005:
                    problems.append(
                        f"only {differing} of {sampled} sampled pixels changed, which is "
                        f"too few for a visibly moving frame")

            print()
            print("wrote:", first_out)
            print("wrote:", second_out)
            bridge.detach()
            del engine
        finally:
            backend.close()

    print()
    if problems:
        print("ANIMATION PIXEL CHECK FAILED / 动画像素检查未通过")
        for problem in problems:
            print("  " + problem)
        return 1
    print("ANIMATION PIXEL CHECK OK / 动画像素检查通过")
    print("  two renders taken across a frame change DIFFER, so the animation reaches the")
    print("  screen; the two PNGs are written for visual confirmation")
    print("  跨一次帧变化取得的两张渲染是不同的，因此动画到达了屏幕；两张 PNG 已写出以供目视确认")
    return 0


if __name__ == "__main__":
    import os as _os

    _status = main(sys.argv[1:])
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(_status)
