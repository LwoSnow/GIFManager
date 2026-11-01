"""Measure the REAL GIFs the user maintains, to size the problem honestly.

The synthetic GIFs used by the other checks are 96x96 with 24 frames. The user's library holds
up to 8.6 MB per file, so the decoded footprint is a different order of magnitude and the frame
cache budget has to be judged against THAT.

Reports per file: compressed size, frame count, frame dimensions, and the decoded RGBA bytes,
then the total for a full viewport of cards.

用户维护的"真实"GIF，用于如实衡量问题规模。其他检查使用的合成 GIF 是 96x96、24 帧。用户的素材库
单个文件最大 8.6MB，因此解码后的占用是另一个数量级，而帧缓存预算必须针对"那个"来评估。

按文件报告：压缩后大小、帧数、帧尺寸、解码后 RGBA 字节数，然后是一个完整视口的卡片总量。
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PYTHONUTF8"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The user's own library, which is the realistic input.
# 用户自己的素材库，也就是真实输入。
SOURCE = r"C:\TLWorkStation\GIFManager\data\emojis\大肥鱼"

# How many cards a full viewport holds at the default card size on a 950 px window.
# 950px 窗口、默认卡片尺寸下一个完整视口容纳的卡片数。
VIEWPORT_CARDS = 24


def human(count):
    if count >= 1024 * 1024 * 1024:
        return f"{count / (1024 ** 3):.2f} GB"
    if count >= 1024 * 1024:
        return f"{count / (1024 ** 2):.1f} MB"
    return f"{count / 1024:.0f} KB"


def main():
    from PySide6.QtWidgets import QApplication

    from gifmanager.frontend.qml import animator as animator_module
    from gifmanager.frontend.qt import animation

    application = QApplication.instance() or QApplication([])
    _ = application

    if not os.path.isdir(SOURCE):
        print(f"SKIPPED: {SOURCE} is not present")
        return 0

    files = sorted(
        (os.path.join(SOURCE, name) for name in os.listdir(SOURCE)
         if name.lower().endswith(".gif")),
        key=os.path.getsize, reverse=True)
    print(f"files available        : {len(files)}")

    # The largest few are the worst case; measuring all 157 would take minutes.
    # 最大的几个是最坏情况；测量全部 157 个要花几分钟。
    sample = files[:8]
    total_decoded = 0
    total_frames = 0
    rows = []
    for path in sample:
        compressed = os.path.getsize(path)
        started = time.perf_counter()
        # Decode at the CARD size the animator uses, which is what playback actually pays for.
        # 按动画器使用的"卡片尺寸"解码，那才是播放实际付出的代价。
        decoded = animation.decode_all(path, 100)
        seconds = time.perf_counter() - started
        if not decoded:
            rows.append((os.path.basename(path), compressed, 0, "0x0", 0, seconds))
            continue
        frames, _delays = decoded
        pixels = sum(frame.width() * frame.height() for frame in frames)
        decoded_bytes = pixels * 4
        size = f"{frames[0].width()}x{frames[0].height()}" if frames else "0x0"
        rows.append((os.path.basename(path), compressed, len(frames), size,
                     decoded_bytes, seconds))
        total_decoded += decoded_bytes
        total_frames += len(frames)

    print()
    print(f"{'file':16} {'packed':>9} {'frames':>7} {'frame':>10} "
          f"{'decoded':>9} {'decode':>8}")
    for name, compressed, frames, size, decoded_bytes, seconds in rows:
        print(f"{name:16} {human(compressed):>9} {frames:>7} {size:>10} "
              f"{human(decoded_bytes):>9} {seconds * 1000:>6.0f} ms")
    print()
    print(f"sample decoded total   : {human(total_decoded)} for {len(sample)} file(s)")
    print(f"average per file       : {human(total_decoded // max(1, len(sample)))}")
    print(f"average frames         : {total_frames / max(1, len(sample)):.0f}")
    print()

    # The number that decides whether the design works: a full viewport of these.
    # 决定设计是否可行的数字：一整个视口装下这些。
    per_file = total_decoded // max(1, len(sample))
    viewport = per_file * VIEWPORT_CARDS
    budget_pixels = animator_module.FrameStore.DEFAULT_PIXEL_BUDGET
    budget_bytes = budget_pixels * 4
    print(f"viewport of {VIEWPORT_CARDS} cards : {human(viewport)} decoded")
    print(f"frame cache budget     : {human(budget_bytes)} ({budget_pixels:,} pixels)")
    print(f"cards the budget holds : {budget_bytes // max(1, per_file)}")
    print()

    problems = []
    if viewport > budget_bytes:
        problems.append(
            f"a full viewport of these GIFs needs {human(viewport)} but the frame cache holds "
            f"{human(budget_bytes)}: animations will be evicted and RE-DECODED while "
            f"scrolling, which is a full decode per evicted card per scroll")
    if per_file > 200 * 1024 * 1024:
        problems.append(
            f"{human(per_file)} per file is above any reasonable single-animation budget")

    print()
    if problems:
        print("REAL GIF MEASUREMENT FINDINGS / 真实 GIF 测量发现")
        for problem in problems:
            print("  " + problem)
        return 1
    print("REAL GIF MEASUREMENT OK / 真实 GIF 测量正常")
    print("  the frame cache can hold a full viewport of the user's own GIFs")
    print("  帧缓存可以容纳用户自己 GIF 的完整视口")
    return 0


if __name__ == "__main__":
    import os as _os

    _status = main()
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(_status)
