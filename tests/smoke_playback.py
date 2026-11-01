"""Verify GIF playback: decoding, the frame provider, and frame advancement.

A GIF is the one sticker format that cannot be tested by checking that an image
appeared: the whole point is that it CHANGES. So this checks the three parts that
together make animation work, and would each fail in a different way:

1. the decoder returns several frames with real delays (a wrong delay unit makes the
   animation play eight times too fast, which a "did it move" test would not notice);
2. the image provider serves each frame by URL, because QML cannot be handed a
   `QImage` — a broken provider means every card blanks;
3. the frame index ADVANCES over time, driven by the animator's single timer, and
   obeys the cap from the render-mode settings.

GIF 是唯一无法靠"图像出现了"来测试的贴纸格式：它的全部意义就在于"会变"。因此本脚本检查
共同构成动画的三个部分，每一部分都会以不同方式失败：

1. 解码器返回多帧且延迟真实（延迟单位错误会让动画快八倍，而"它动了吗"的测试不会发现）；
2. 图像提供器按 URL 提供每一帧，因为 QML 无法被交给一个 `QImage`——提供器坏了等于每张卡片
   全白；
3. 帧序号随时间推进，由动画器的单个定时器驱动，并遵守渲染模式设置给出的上限。
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QSize
from PySide6.QtGui import QGuiApplication

from gifmanager.backend import MemorySettingsStore, create_backend
from gifmanager.core import settings as schema


def section(title):
    print()
    print("=" * 4, title)


def make_animated_gif(path, frames=6, size=(48, 48), delay_ms=80):
    # A real animated GIF with a known frame count and delay, so "the delays are
    # right" is checkable rather than assumed.
    # 一个真实的动画 GIF，帧数与延迟已知，使"延迟是对的"可被检查而非假设。
    from PIL import Image

    images = []
    for index in range(frames):
        # A distinctly different colour per frame, so a test can tell frames apart
        # by pixel value and not only by index.
        # 每帧一个明显不同的颜色，使测试能按像素值而不只按序号区分帧。
        image = Image.new("RGB", size,
                          (20 + index * 30, 200 - index * 25, 60 + index * 20))
        images.append(image)
    images[0].save(path, save_all=True, append_images=images[1:],
                   duration=delay_ms, loop=0, format="GIF")
    return path


def pump(app, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    problems = []

    with tempfile.TemporaryDirectory() as tmp:
        backend = create_backend(data_dir=tmp,
                                settings_store=MemorySettingsStore(), log=False)

        section("a real animated GIF decodes to several frames with real delays")
        from gifmanager.frontend.qt import animation

        # No decoder is a SUPPORTED state, not a failure — but it is also not a pass.
        #
        # Playback cannot be tested without something to decode with, so this reports
        # SKIPPED rather than pretending either way. It is a FAILURE unless
        # `--allow-missing-decoder` is given, because on a machine where the decoder IS
        # expected, silently skipping is exactly how a broken build looks green. The Linux
        # check runner passes the flag, since its environment genuinely cannot build one.
        #
        # 没有解码器是"受支持"的状态而非失败——但也不是通过。
        #
        # 没有任何可解码的东西就无法测试播放，因此这里报告 SKIPPED，而不是朝任何一边假装。除非
        # 给了 `--allow-missing-decoder`，否则它是"失败"，因为在期望有解码器的机器上静默跳过
        # 正是坏掉的构建看起来是绿的方式。Linux 检查运行器会传该标志，因为它的环境确实无法构建
        # 一个。
        if not animation.available():
            print("decoder available : False")
            print()
            reason = ("no GIF decoder is available, so playback cannot be tested "
                      "(the Rust pipeline is unbuilt and this platform has no C "
                      "library)")
            reason_zh = ("没有可用的 GIF 解码器，因此无法测试播放（Rust 管线未构建，"
                         "且本平台没有 C 库）")
            if "--allow-missing-decoder" in sys.argv:
                print("GIF PLAYBACK CHECK SKIPPED / GIF 播放检查已跳过")
                print("  " + reason)
                print("  " + reason_zh)
                backend.close()
                return 0
            print("GIF PLAYBACK CHECK FAILED / GIF 播放检查未通过")
            print("  " + reason)
            print("  " + reason_zh)
            print("  re-run with --allow-missing-decoder to accept this environment")
            print("  用 --allow-missing-decoder 重跑以接受此环境")
            backend.close()
            return 1

        gif = make_animated_gif(os.path.join(tmp, "anim.gif"), frames=6,
                                delay_ms=80)
        print("decoder available :", animation.available())
        decoded = animation.decode_all(gif, 48)
        if not decoded:
            print("DECODING FAILED although the decoder reports itself available")
            backend.close()
            return 1
        frames, delays = decoded
        print("frames            :", len(frames))
        print("delays (ms)       :", delays[:6])
        print("frame size        :", frames[0].width(), "x", frames[0].height())
        if len(frames) != 6:
            problems.append(f"decoded {len(frames)} frames, expected 6")
        # The delay unit is the specific bug this catches: the `gif` crate reports
        # centiseconds, and treating them as milliseconds made every animation play
        # eight to ten times too fast in an earlier pass.
        # 延迟单位正是这里要抓的具体缺陷：`gif` crate 报告的是厘秒，而把它们当毫秒会让每个动画
        # 在早前的一轮中快八到十倍。
        if delays and not all(60 <= int(d) <= 120 for d in delays[:4]):
            problems.append(
                f"delays {delays[:4]} are outside 60-120 ms for an 80 ms GIF; "
                f"the delay unit is probably wrong")
        # Frames must actually differ, or "animation" would be a redraw of one picture.
        # 帧必须真的不同，否则"动画"就是重绘同一张图。
        distinct = len({frames[i].pixel(10, 10) for i in range(len(frames))})
        print("distinct first-pixel colours:", distinct)
        if distinct < 2:
            problems.append("every frame has the same pixel; nothing would animate")

        section("the image provider serves each frame by URL")
        from gifmanager.frontend.qml import animator as anim_mod

        prefix = anim_mod.register_frames(gif, frames)
        print("key prefix        :", prefix)
        provider = anim_mod.StickerFrameProvider()
        for index in (0, 2, len(frames) - 1):
            # Qt's contract: the image is RETURNED and the size is reported
            # through the `size` out-parameter.
            # Qt 的契约：图像由返回值给出，尺寸经 `size` 出参报告。
            size = QSize()
            image = provider.requestImage(f"{prefix}:{index}", size, None)
            print(f"  {prefix}:{index} -> {image.width()}x{image.height()}"
                  f" size={size.width()}x{size.height()}")
            if image.isNull():
                problems.append(f"the provider returned a null image for frame {index}")
            elif image.pixel(10, 10) != frames[index].pixel(10, 10):
                problems.append(
                    f"frame {index} from the provider differs from the decoded frame")
        # A request for an unknown prefix must give a null image, not a stale one from
        # another animation: serving the wrong sticker's frame is worse than a blank.
        # 对未知前缀的请求必须给出空图像，而不是来自另一个动画的过期帧：提供错误贴纸的帧比空白
        # 更糟。
        unknown = provider.requestImage("deadbeef:0", QSize(), None)
        print("unknown prefix null:", unknown.isNull())
        if not unknown.isNull():
            problems.append("the provider served a frame for an unknown prefix")
        # Out-of-range indices wrap, because a card can be one frame behind a restart.
        # 越界序号会回绕，因为卡片可能比一次重新开始晚一帧。
        wrapped = provider.requestImage(f"{prefix}:{len(frames) + 1}",
                                           QSize(), None)
        print("wrapped index null:", wrapped.isNull())
        if wrapped.isNull():
            problems.append("an out-of-range index did not wrap to a real frame")

        section("the animator advances the frame index over time")
        anim = anim_mod.StickerAnimator(backend)
        anim.setMaxAnimated(4)
        count = anim.register(1, gif)
        print("registered frames :", count)
        print("frame count       :", anim.frameCount(1))
        print("animated ids      :", anim.animated)
        if count != 6:
            problems.append(f"register returned {count}, expected 6")
        first = anim.frameIndex(1)
        key_first = anim.frameKey(1)
        print("initial index     :", first, "key:", key_first)
        # The key must name the PROVIDER, not a file: a filesystem path here means the
        # provider cannot resolve it and every animated card is blank. This assertion is
        # what caught exactly that bug.
        # 键必须指向"提供器"而非文件：此处出现文件系统路径意味着提供器无法解析它，而每张动画
        # 卡片都会是空白。正是这条断言抓住了那个缺陷。
        # The URL must be the CANONICAL provider form whose name equals the
        # registered provider id, AND the provider must actually serve it. The
        # first version only checked the string's shape, so a scheme/provider name
        # mismatch ("gifframe" vs "gifframes") passed while every animated card
        # rendered blank.
        # URL 必须是"规范"提供器形式且其名等于注册的提供器 id，并且提供器必须"真的能
        # 服务它"。第一版只检查字符串形状，于是 scheme 与提供器名不匹配
        #（"gifframe" 对 "gifframes"）照样通过，而每张动画卡都是空白。
        expected_prefix = "image://" + anim_mod.PROVIDER_ID + "/"
        if not key_first.startswith(expected_prefix):
            problems.append(
                f"the frame key {key_first!r} is not an 'image://{anim_mod.PROVIDER_ID}/' "
                f"URL, so Qt cannot resolve the provider")
        tail = key_first[len(expected_prefix):]
        prefix_part, _, index_part = tail.partition(":")
        if "\\" in tail or "/" in tail:
            problems.append(
                f"the frame key {key_first!r} contains a path separator, so it is a "
                f"filesystem path rather than a provider key")
        if len(prefix_part) != 16 or not index_part.isdigit():
            problems.append(
                f"the frame key {key_first!r} is not '<16-hex-prefix>:<index>'")
        if anim_mod.path_for_prefix(prefix_part) != gif:
            problems.append(
                f"the provider cannot resolve the prefix {prefix_part!r} back to the "
                f"decoded GIF")

        # Ask the provider for the frame the URL names: a null QImage here means the
        # card would render empty, which is the user-visible failure this guards.
        # 向提供器索取该 URL 所指的帧：空 QImage 意味着卡片会渲染为空白，而这正是本
        # 检查守护的用户可见故障。
        provider = anim_mod.StickerFrameProvider()
        served_size = QSize()
        served = provider.requestImage(
            f"{prefix_part}:{index_part}", served_size, QSize(0, 0))
        print("provider served   :", served.width(), "x", served.height())
        if served.isNull() or served.width() <= 0:
            problems.append(
                "the frame provider served a null image for its own key, so every "
                "animated card would render blank")

        # Drive the animator's own tick handler instead of sleeping a fixed 350 ms.
        #
        # The first version waited 350 ms of wall time and asserted the frame advanced.
        # That is a wall-clock race: under load the timer can miss its window, so the
        # check passed alone and failed about a third of the time when ten runs competed
        # for the CPU. Calling `_tick` with a back-dated start time makes the assertion
        # test the STATE MACHINE, which is the thing that can be wrong, and leaves the
        # timer's accuracy to Qt.
        #
        # 直接驱动动画器自身的 tick 处理器，而不是固定睡 350 毫秒。
        #
        # 第一个版本等待 350 毫秒墙上时间并断言帧已推进。那是一场墙上时钟竞态：负载下定时器可能
        # 错过窗口，因此该检查单独跑能过，而在十次运行争抢 CPU 时约三分之一会失败。把起始时刻
        # 改早再调用 `_tick`，使断言测试的是"状态机"——那才是可能出错的东西——而把定时器精度留给
        # Qt。
        def advance_one_frame(sticker_id):
            # Back-date the current frame's start far enough that the next tick is due.
            # 把当前帧的起始时刻改得足够早，使下一次 tick 到期。
            anim._started[sticker_id] = time.monotonic() - 10.0
            anim._tick()
            app.processEvents()

        pump(app, 0.05)
        advance_one_frame(1)
        later = anim.frameIndex(1)
        key_later = anim.frameKey(1)
        print("after one tick    :", later, "key:", key_later)
        if later == first:
            problems.append(
                f"the frame index did not advance after a due tick (still {later})")
        if key_later == key_first:
            problems.append("the frame key did not change, so the card would be static")

        # And it must keep advancing, wrapping rather than stopping at the last frame.
        # 而且它必须继续推进，回绕而不是在最后一帧停住。
        seen = {later}
        for _ in range(len(frames) * 2):
            advance_one_frame(1)
            seen.add(anim.frameIndex(1))
        print("frames seen       :", sorted(seen), f"(of {len(frames)})")
        if len(seen) < 2:
            problems.append("the frame index stopped advancing after one step")
        if max(seen) >= len(frames) or min(seen) < 0:
            problems.append(
                f"a frame index fell outside 0..{len(frames) - 1}: {sorted(seen)}")

        # The timer must also be RUNNING and armed, which is what makes the animation
        # happen without a test poking it.
        # 定时器还必须"正在运行"且已武装，这正是让动画无需测试去戳它也会发生的原因。
        print("timer armed       :", anim._timer.isActive(),
              "interval:", anim._timer.interval())
        if not anim._timer.isActive():
            problems.append("the animator's timer is not running after a registration")

        section("the render-mode cap is obeyed")
        # A cap of 2 with 5 registrations must animate only the 2 most recent.
        # 上限为 2 而有 5 个注册时，必须只动画最近的 2 个。
        for extra in range(2, 7):
            anim.register(extra, gif)
        anim.setMaxAnimated(2)
        animating = [sid for sid in range(1, 7) if anim.isAnimating(sid)]
        print("registrations     :", len(anim._registrations))
        print("animating         :", animating)
        if len(animating) != 2:
            problems.append(
                f"the cap is 2 but {len(animating)} stickers are animating")
        # Raising the cap must resume the others WITHOUT resetting them, because a
        # user dragging the count upward does not expect every animation to jump back
        # to frame one.
        # 提高上限必须"继续"其余动画而不重置它们，因为把数量往上拖的用户不会期望每个动画都跳回
        # 第一帧。
        anim.setMaxAnimated(0)
        resumed = [sid for sid in range(1, 7) if anim.isAnimating(sid)]
        print("after raising cap :", len(resumed))
        if len(resumed) != 6:
            problems.append(f"uncapping left {len(resumed)} of 6 animating")

        section("unregistering stops the timer when nothing is left")
        for sid in range(1, 7):
            anim.unregister(sid)
        print("animated          :", anim.animated)
        print("timer active      :", anim._timer.isActive())
        if anim.animated != 0:
            problems.append("the animator still reports animated stickers")
        if anim._timer.isActive():
            problems.append("the timer is still running with nothing to animate")

        section("disabling playback stops all timer work")
        anim.register(1, gif)
        anim.setEnabled(False)
        print("enabled           :", anim.enabled)
        print("timer active      :", anim._timer.isActive())
        if anim._timer.isActive():
            problems.append("the timer runs while playback is disabled")

        anim.shutdown()
        backend.close()

    print()
    if problems:
        print("GIF PLAYBACK CHECK FAILED / GIF 播放检查未通过")
        for problem in problems:
            print("  " + problem)
        return 1
    print("GIF PLAYBACK CHECK OK / GIF 播放检查通过")
    print("  a real GIF decodes to the right frame count with correct delays, the")
    print("  provider serves each frame by URL and refuses unknown ones, and the")
    print("  animator advances frames while obeying the render-mode cap")
    print("  真实 GIF 解码出正确的帧数与延迟、提供器按 URL 提供每一帧并拒绝未知前缀、动画器")
    print("  推进帧并遵守渲染模式上限")
    return 0


if __name__ == "__main__":
    import os as _os
    import sys as _sys

    _status = main()

    # Drain the decoder's worker thread BEFORE exiting.
    #
    # `os._exit` bypasses `atexit`, and `frontend/qt/animation.py` registers its thread
    # shutdown there. Killing the interpreter while that thread is mid-decode produced an
    # INTERMITTENT non-zero status — a green check that sometimes reported failure, which
    # is worse than a red one because it trains the reader to ignore it. Draining first
    # makes the exit deterministic.
    # 退出"之前"排空解码器的工作线程。
    #
    # `os._exit` 会绕过 `atexit`，而 `frontend/qt/animation.py` 在那里注册了线程关闭。在该
    # 线程正在解码时杀掉解释器会产生"间歇性"非零状态——一个绿色的检查有时报为失败，这比红色的
    # 更糟，因为它会让读者学会忽略它。先排空使退出成为确定性的。
    try:
        from gifmanager.frontend.qt import animation as _animation

        _animation.shutdown()
    except Exception:
        pass

    if _os.environ.get("GIFMANAGER_SMOKE_DEBUG"):
        _sys.stderr.write(f"[debug] exit status = {_status}\n")
    _sys.stdout.flush()
    _sys.stderr.flush()
    _os._exit(_status)
