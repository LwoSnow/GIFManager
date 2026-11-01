"""Render the QML interface to a PNG, so a layout change can be LOOKED at.

# Why this exists

The user's report was visual: "the interface is less attractive than the original". No
assertion about property values can settle that — the only way to check a spacing or
density change is to look at pixels. This renders the real interface with a real backend
into a file, so the change can be compared against the original's screenshot instead of
argued about from numbers.

It uses the ACTUAL entry point (`app.run_with` is not called, because that enters an event
loop; `create_engine` plus `QQuickWindow.grabWindow` is used instead), and the offscreen
platform so it can run in CI.

用法：
    python tests/capture_qml.py out.png [--theme dark|light] [--cards N]

# 本脚本存在的理由

用户的报告是视觉性的："界面不如原项目美观"。任何关于属性取值的断言都无法判定这件事——检查间距或
密度改动的唯一方式就是看像素。本脚本用真实后端把真实界面渲染成文件，使改动可以与原项目的截图对比，
而不是靠数字争论。

它使用"真实"入口（不调用 `app.run_with`，因为那会进入事件循环；改用 `create_engine` 加
`QQuickWindow.grabWindow`），并使用离屏平台，因此可以在 CI 中运行。
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PYTHONUTF8"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Window size for the capture. Chosen to match the user's screenshot proportions so the
# two images can be compared side by side without rescaling.
# 截图所用的窗口尺寸。选它与用户截图的构图一致，使两张图可以不缩放地并排比较。
WINDOW_WIDTH = 950
WINDOW_HEIGHT = 740

# Card colours for the synthetic library. Deliberately distinct hues so the grid's DENSITY
# is readable in the image: uniform tiles would hide the gaps this is meant to check.
# 合成素材库的卡片颜色。刻意用不同色调，使网格的"密度"在图中可读：统一的色块会掩盖本脚本要检查的
# 间隙。
CARD_COLOURS = (
    (30, 90, 200), (200, 60, 60), (40, 160, 90), (220, 160, 40),
    (140, 70, 200), (50, 170, 190), (210, 90, 160), (110, 110, 120),
)


def make_library(store, count):
    # Put `count` synthetic stickers into a group so the grid has something to lay out.
    # 把 `count` 个合成贴纸放进一个分组，使网格有东西可排布。
    from PIL import Image

    group_id = store.create_group("Capture", "image")
    for index in range(count):
        colour = CARD_COLOURS[index % len(CARD_COLOURS)]
        path = os.path.join(tempfile.gettempdir(),
                            f"gifmanager-capture-{index}.png")
        image = Image.new("RGB", (128, 128), colour)
        # A darker inner square, so a card's bounds are visible in the capture.
        # 一个更暗的内方块，使卡片的边界在截图中可见。
        for x in range(32, 96):
            for y in range(32, 96):
                image.putpixel((x, y), tuple(max(0, c - 90) for c in colour))
        image.save(path)
        # `import_emoji` copies the file into the group's directory, which is what a real
        # import does — so the capture shows the same paths the application would.
        # `auto_convert=False` keeps the PNG a PNG; the converter is for GIF resizing and
        # is not the subject of a layout check.
        # `import_emoji` 会把文件复制进分组目录，这正是真实导入所做的——因此截图展示的是应用
        # 本身会用的那套路径。`auto_convert=False` 让 PNG 保持为 PNG；转换器是给 GIF 缩放用的，
        # 不是布局检查的主题。
        store.import_emoji(group_id, path, auto_convert=False)
    return group_id


# Sample texts of deliberately different lengths, so the masonry's per-column
# widths and adaptive heights are readable in the image.
# 刻意长短不一的示例文本，使瀑布流的每列宽度与自适应高度在图中可读。
TEXT_SAMPLES = (
    "这是一条短句",
    "这是一条比较长的文字表情，用来检查换行与列宽的适配。",
    "多行文字\n第二行\n第三行",
    "GG",
    "早上好！今天也要加油鸭！",
    "一句话表情包：把窗户擦干净再出门。",
    "长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长长"
    "长长长长长长长长长长长长长长长长长长长长长长长长长长",
)


def make_text_library(store, count):
    # A TEXT group with `count` text stickers, for the masonry capture.
    # 一个含 `count` 个文字贴纸的文字分组，供瀑布流截图使用。
    group_id = store.create_group("CaptureText", "text")
    for index in range(count):
        store.add_text_emoji(group_id, TEXT_SAMPLES[index % len(TEXT_SAMPLES)])
    return group_id


def main(argv):
    output = argv[0] if argv else "capture.png"
    theme_name = "dark"
    count = 24
    as_text = False
    for index, argument in enumerate(argv):
        if argument == "--theme" and index + 1 < len(argv):
            theme_name = argv[index + 1]
        if argument == "--cards" and index + 1 < len(argv):
            count = int(argv[index + 1])
        if argument == "--text":
            as_text = True

    from PySide6.QtWidgets import QApplication

    from gifmanager.backend import MemorySettingsStore, create_backend
    from gifmanager.frontend.qml import app as qml_app
    from gifmanager.frontend.qt.bridge import BackendAdapter

    application = qml_app.build_application([])
    problems = []

    tmp = tempfile.mkdtemp(prefix="gifmanager-capture-")
    store = MemorySettingsStore()
    store.write_many({"theme": theme_name})
    backend = create_backend(data_dir=tmp, settings_store=store, log=False)
    try:
        if as_text:
            make_text_library(backend.store, count)
        else:
            make_library(backend.store, count)
        adapter = BackendAdapter(backend)
        engine, bridge, theme, warnings = qml_app.create_engine(adapter, strict=True)
        theme.set_theme(theme_name)
        for warning in warnings:
            print("engine warning:", warning)
            problems.append(warning)

        if as_text:
            # Select the text group through the bridge after load, so the group
            # bar's selection state matches the visible page.
            # 加载后经桥选中文字分组，使分组栏的选中状态与可见页面一致。
            for index in range(bridge.groups.rowCount()):
                model_index = bridge.groups.index(index, 0)
                if bridge.groups.data(model_index,
                                      bridge.groups.TypeRole) == "text":
                    bridge.selectGroup(bridge.groups.data(
                        model_index, bridge.groups.IdRole))
                    break
            application.processEvents()

        roots = engine.rootObjects()
        if not roots:
            print("CAPTURE FAILED: the engine produced no root object")
            return 1
        window = roots[0]
        window.setWidth(WINDOW_WIDTH)
        window.setHeight(WINDOW_HEIGHT)
        window.setVisible(True)
        # Let the grid lay out, the thumbnails decode, and the animator settle. A single
        # `processEvents` is not enough: the image provider decodes on a worker thread, so
        # cards would still be blank.
        # 让网格完成排布、缩略图完成解码、动画器稳定下来。单次 `processEvents` 不够：图像提供器在
        # 工作线程上解码，因此卡片仍会是空白。
        import time

        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            application.processEvents()
            time.sleep(0.05)

        pixmap = window.grabWindow()
        if pixmap.isNull():
            print("CAPTURE FAILED: grabWindow returned a null pixmap")
            return 1
        if not pixmap.save(output, "PNG"):
            print(f"CAPTURE FAILED: could not write {output}")
            return 1
        print(f"wrote {output}  {pixmap.width()}x{pixmap.height()}  theme={theme_name}  "
              f"cards={count}")

        # Report the numbers that a reader would otherwise have to measure by eye.
        # 报告读者否则必须用眼睛测量的那些数字。
        print("card size   :", bridge.cardScale, "scale ->",
              round(100 * bridge.cardScale), "px base")
        bridge.detach()
        del engine
    finally:
        backend.close()

    if problems:
        print()
        print("CAPTURE COMPLETED WITH ENGINE WARNINGS / 截图完成但有引擎警告")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
