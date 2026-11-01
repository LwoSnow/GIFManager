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
    from PySide6.QtWidgets import QApplication

    from gifmanager.backend import MemorySettingsStore, create_backend
    from gifmanager.frontend.qml import app as qml_app
    from gifmanager.frontend.qt.bridge import BackendAdapter
    from gifmanager.frontend.qt import animation

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

            bridge.animator.unregister(sticker_id)
            bridge.detach()
            del engine
        finally:
            backend.close()

    print()
    if problems:
        print("ANIMATION CHECK FAILED / 动画检查未通过")
        for problem in problems:
            print("  " + problem)
        return 1
    print("ANIMATION CHECK OK / 动画检查通过")
    print("  the decoder produces multiple frames, the animator serves each one by key,")
    print("  and the index and key both advance")
    print("  解码器产出多帧、动画器按键提供每一帧，且序号与键都会推进")
    return 0


if __name__ == "__main__":
    import os as _os

    _status = main()
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(_status)
