"""Measure the preview (still-frame) cost against loading the whole GIF.

A card's placeholder used to be the GIF's own `file://` URL, which makes a QML `Image` decode the
entire animation on the GUI thread once per card. The preview provider asks `QImageReader` for
frame 0 at the card's size instead. This measures both, on the user's own files, so the saving is
a number rather than a claim.

卡片的占位符过去是 GIF 自身的 `file://` URL，这会让 QML 的 `Image` 在 GUI 线程上按每张卡片一次
解码整个动画。预览提供器改为向 `QImageReader` 请求卡片尺寸的第 0 帧。本脚本在用户自己的文件上
测量两者，使节省是一个数字而不是一个说法。
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PYTHONUTF8"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SOURCE = r"C:\TLWorkStation\GIFManager\data\emojis\大肥鱼"
EDGE = 100
SAMPLE = 6


def main():
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QImage, QImageReader
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    _ = application

    if not os.path.isdir(SOURCE):
        print(f"SKIPPED: {SOURCE} is not present")
        return 0

    files = sorted((os.path.join(SOURCE, name) for name in os.listdir(SOURCE)
                    if name.lower().endswith(".gif")),
                   key=os.path.getsize, reverse=True)[:SAMPLE]

    print(f"{'file':16} {'whole GIF':>11} {'preview':>10} {'speedup':>8}")
    full_total = 0.0
    preview_total = 0.0
    for path in files:
        started = time.perf_counter()
        whole = QImage(path)
        full_seconds = time.perf_counter() - started

        reader = QImageReader(path)
        size = reader.size()
        if size.isValid() and size.width() > 0:
            reader.setScaledSize(size.scaled(QSize(EDGE, EDGE),
                                             Qt.AspectRatioMode.KeepAspectRatio))
        started = time.perf_counter()
        preview = reader.read()
        preview_seconds = time.perf_counter() - started

        if whole.isNull() or preview.isNull():
            print(f"{os.path.basename(path):16} {'<failed>':>11}")
            continue
        full_total += full_seconds
        preview_total += preview_seconds
        ratio = full_seconds / max(preview_seconds, 1e-9)
        print(f"{os.path.basename(path):16} {full_seconds * 1000:>9.0f} ms "
              f"{preview_seconds * 1000:>8.1f} ms {ratio:>7.0f}x")

    print()
    print(f"sample of {len(files)} of the largest files")
    print(f"whole-GIF QImage loads : {full_total * 1000:.0f} ms")
    print(f"preview decodes        : {preview_total * 1000:.0f} ms")

    # WHAT THIS MEASURES, and what it does not.
    #
    # `QImage(path)` on a GIF reads frame 0 only (2-8 ms measured), so the preview is NOT faster
    # than that — an earlier version of this file claimed it was, from a ratio computed the wrong
    # way round. The expensive operation on these files is `animation.decode_all`, which expands
    # every frame and costs 231 ms median / 383 ms worst; THAT is what had to leave the GUI
    # thread, and `tests/profile_real_gifs.py` measures that separately.
    #
    # So the preview's value is not speed, it is ORDER: the card shows a real frame immediately
    # (a few ms) while the full decode runs in the background, instead of showing nothing until
    # 231 ms later. This check therefore asserts the PREVIEW IS CHEAP ENOUGH TO RUN ON THE GUI
    # THREAD, not that it beats something it does not beat.
    # 本脚本测量什么、不测量什么。
    #
    # 对 GIF 调用 `QImage(path)` 只读取第 0 帧（实测 2-8 毫秒），因此预览"并不"比它快——本文件
    # 的早期版本声称它快，那是把比值算反了。这些文件上真正昂贵的操作是 `animation.decode_all`，
    # 它展开每一帧、代价中位 231 毫秒、最差 383 毫秒；那才是必须离开 GUI 线程的东西，由
    # `tests/profile_real_gifs.py` 单独测量。
    #
    # 因此预览的价值不是速度，而是"顺序"：卡片立即（几毫秒）显示真实帧，而完整解码在后台运行，
    # 而不是在 231 毫秒之后才显示任何东西。所以本检查断言的是"预览足够便宜、可以在 GUI 线程上运行"，
    # 而不是它击败了一个它并未击败的东西。
    problems = []
    per_preview_ms = preview_total / max(1, len(files)) * 1000
    if per_preview_ms > 50:
        problems.append(
            f"{per_preview_ms:.0f} ms per preview is too slow to run while scrolling")
    if preview_total < 0:
        problems.append("unreachable")

    print()
    if problems:
        print("PREVIEW COST FINDINGS / 预览代价发现")
        for problem in problems:
            print("  " + problem)
        return 1
    print("PREVIEW COST OK / 预览代价正常")
    print(f"  one scaled frame costs {per_preview_ms:.1f} ms on average, cheap enough to")
    print("  render immediately while the full animation decodes in the background")
    print(f"  一张缩放帧平均花费 {per_preview_ms:.1f} 毫秒，足够便宜到可以立即渲染，")
    print("  而完整动画在后台解码")
    return 0


if __name__ == "__main__":
    import os as _os

    _status = main()
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(_status)
