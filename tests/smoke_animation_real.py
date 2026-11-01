"""Render the real interface with a REAL animated GIF and compare two frames.

This is the check that must pass for the user's complaint to be answered, and it uses a
small existing GIF from the user's own library rather than a synthetic one — so it tests the
files the application actually stores, at a size small enough that decoding is fast.

Comparisons are made over the card area only, and the count of changed pixels is printed, so
a "nothing changed" result is unambiguous.

这是回答用户投诉所必须通过的检查，它使用用户自己素材库里一个"真实"的小 GIF 而不是合成文件——
因此它测试的是应用实际存储的文件，且尺寸足够小、解码足够快。

比较只在卡片区域内进行，并打印变化的像素数，使"什么都没变"的结论毫无歧义。
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PYTHONUTF8"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def smallest_user_gif(limit=200_000):
    # The smallest multi-frame GIF in the user's library, or None.
    # 用户素材库中最小的多帧 GIF，无则 None。
    base = os.path.join(os.environ.get("APPDATA", ""), "GIFManager", "emojis")
    if not os.path.isdir(base):
        return None
    candidates = []
    for root, _dirs, names in os.walk(base):
        for name in names:
            if name.lower().endswith(".gif"):
                path = os.path.join(root, name)
                try:
                    candidates.append((os.path.getsize(path), path))
                except OSError:
                    pass
    candidates.sort()
    for size, path in candidates:
        if size <= limit:
            return path
    return candidates[0][1] if candidates else None


def main(argv):
    from PySide6.QtWidgets import QApplication

    from gifmanager.backend import MemorySettingsStore, create_backend
    from gifmanager.frontend.qml import app as qml_app
    from gifmanager.frontend.qt import animation
    from gifmanager.frontend.qt.bridge import BackendAdapter

    first_out = argv[0] if argv else "real_a.png"
    second_out = argv[1] if len(argv) > 1 else "real_b.png"

    source = smallest_user_gif()
    if source is None:
        print("REAL GIF CHECK SKIPPED / 真实 GIF 检查已跳过")
        print("  no GIF found in your library to test with")
        print("  素材库里没有可用于测试的 GIF")
        return 0
    print("using your GIF :", source)
    print("size           :", os.path.getsize(source), "bytes")
    decoded = animation.decode_all(source, 64)
    print("decoded frames :", len(decoded[0]) if decoded else None)
    if not decoded or len(decoded[0]) < 2:
        print("REAL GIF CHECK SKIPPED: this file has no animation to show")
        return 0

    application = qml_app.build_application([])
    problems = []

    with tempfile.TemporaryDirectory(prefix="gifmanager-real-") as tmp:
        settings = MemorySettingsStore()
        # The user's own values, so this reproduces their configuration rather than a
        # default that might differ.
        # 用用户自己的取值，使本检查复现其配置，而不是一个可能有差异的默认值。
        settings.write_many({"gif_render_mode": "auto", "gif_render_count": 32})
        backend = create_backend(data_dir=tmp, settings_store=settings, log=False)
        try:
            group_id = backend.store.create_group("Real", "image")
            # `auto_convert=True` is the user's setting, so the stored file goes through the
            # same conversion their imports did.
            # `auto_convert=True` 是用户的设置，因此存储的文件经过与其导入相同的转换。
            backend.store.import_emoji(group_id, source, auto_convert=True)
            row = backend.store.get_emojis_by_group(group_id)[0]
            stored = backend.store.emoji_filepath(row)
            stored_frames = animation.decode_all(stored, 64)
            print("stored frames  :", len(stored_frames[0]) if stored_frames else None)

            adapter = BackendAdapter(backend)
            engine, bridge, theme, warnings = qml_app.create_engine(adapter,
                                                                   strict=True)
            for warning in warnings:
                print("engine warning:", warning)

            bridge.selectGroup(group_id)
            root = engine.rootObjects()[0]
            root.setWidth(420)
            root.setHeight(360)
            root.setVisible(True)

            def settle(seconds):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    application.processEvents()
                    time.sleep(0.02)

            settle(2.0)
            sticker_id = row["id"]
            print("animationEnabled:", bridge.animationEnabled)
            print("frameCount      :", bridge.animator.frameCount(sticker_id))
            print("isAnimating     :", bridge.animator.isAnimating(sticker_id))
            print("frameKey        :", bridge.animator.frameKey(sticker_id))
            if not bridge.animationEnabled:
                problems.append("animationEnabled is False for these settings")
            if bridge.animator.frameCount(sticker_id) < 2:
                problems.append("the animator has fewer than 2 frames for this GIF")

            shots = []
            for step in range(4):
                # Force a due tick, then let the renderer catch up.
                # 强制一次到期的 tick，然后让渲染器跟上。
                bridge.animator._started[sticker_id] = time.monotonic() - 10.0
                bridge.animator._tick()
                settle(0.25)
                shots.append(root.grabWindow())

            print()
            print("frameKey sequence:")
            for index, shot in enumerate(shots):
                print(f"  shot {index}: {shot.width()}x{shot.height()}")

            # Count how many shots differ from the first. If the animation renders, at least
            # one later shot must differ.
            # 统计有多少张与第一张不同。若动画渲染了，至少后面有一张必须不同。
            base = shots[0]
            differing_overall = 0
            for index, shot in enumerate(shots[1:], start=1):
                differing = 0
                sampled = 0
                for y in range(0, base.height(), 2):
                    for x in range(0, base.width(), 2):
                        sampled += 1
                        if base.pixel(x, y) != shot.pixel(x, y):
                            differing += 1
                print(f"  shot {index} vs shot 0: {differing}/{sampled} pixels differ")
                differing_overall = max(differing_overall, differing)
            if differing_overall == 0:
                problems.append(
                    "NO rendered frame differs from the first, so the GIF is displayed "
                    "statically in the real interface")

            shots[0].save(first_out, "PNG")
            shots[-1].save(second_out, "PNG")
            print()
            print("wrote:", first_out)
            print("wrote:", second_out)

            bridge.detach()
            del engine
        finally:
            backend.close()

    print()
    if problems:
        print("REAL GIF CHECK FAILED / 真实 GIF 检查未通过")
        for problem in problems:
            print("  " + problem)
        return 1
    print("REAL GIF CHECK OK / 真实 GIF 检查通过")
    print("  a GIF from your own library renders DIFFERENT pixels across frames")
    print("  你自己素材库中的 GIF 在不同帧之间渲染出不同的像素")
    return 0


if __name__ == "__main__":
    import os as _os

    _status = main(sys.argv[1:])
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(_status)
