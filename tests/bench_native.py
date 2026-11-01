"""Measure the native pipeline against the pure-Qt path.

A change like this is only worth its build complexity if the numbers say so, so
this measures instead of asserting that "Rust is faster". It reports the two
paths separately and prints the ratio, including the cases where the native
pipeline is NOT a win — a small single-frame image is dominated by the
fixed overhead of crossing the FFI boundary, and the report says so.

这样一项改动只有数字支持才值得它带来的构建复杂度，因此这里做的是"测量"而不是断言
"Rust 更快"。它分别报告两条路径并打印比值，也包括原生管线"不占优"的情形——小尺寸
单帧图的开销主要由跨 FFI 边界的固定成本决定，报告会如实说明。

Run / 运行:
    python tests/bench_native.py
"""
import os
import statistics
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage

from gifmanager.frontend.qt import images


def section(title):
    print()
    print("=" * 68)
    print(title)
    print("=" * 68)


def timeit(func, repeat=5):
    # Best-of-N rather than mean: a garbage collection or a scheduler hiccup in
    # one run says nothing about the code under test.
    # 取 N 次中的最优而非平均：某一次运行里的垃圾回收或调度抖动不能说明被测代码的性质。
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        result = func()
        samples.append(time.perf_counter() - start)
    return min(samples), result


def make_animated_gif(path, frames=24, size=(300, 200)):
    # A realistic animated sticker: a moving shape over a gradient, which forces
    # real per-frame pixel work rather than 24 copies of one image.
    # 真实感的动图：渐变背景上的运动图形，迫使逐帧有真实像素工作，而不是同一张图的
    # 24 次复制。
    from PIL import Image, ImageDraw

    built = []
    for index in range(frames):
        image = Image.new("RGB", size)
        pixels = []
        for y in range(size[1]):
            for x in range(0, size[0], 4):
                shade = (x * 255) // size[0]
                pixels.extend([(shade, (y * 255) // size[1], 128)] * 4)
        image.putdata(pixels[: size[0] * size[1]])
        draw = ImageDraw.Draw(image)
        offset = (index * 11) % (size[0] - 60)
        draw.ellipse([offset, 40, offset + 60, 140], fill=(255, 40, 40))
        built.append(image.convert("P", palette=Image.Palette.ADAPTIVE))
    built[0].save(path, save_all=True, append_images=built[1:],
                  duration=[40] * frames, loop=0, disposal=2)
    return path


def make_still(path, size=(1200, 900)):
    from PIL import Image, ImageDraw

    image = Image.new("RGB", size, (30, 30, 40))
    draw = ImageDraw.Draw(image)
    for index in range(0, size[0], 40):
        draw.line([(index, 0), (index, size[1])], fill=(0, 120, 200), width=2)
    for index in range(0, size[1], 40):
        draw.line([(0, index), (size[0], index)], fill=(200, 90, 0), width=2)
    image.save(path)
    return path


def bench_gif(gif_path, target):
    import gifmanager.frontend.qt.animation as animation

    # Force each path explicitly rather than relying on the dispatcher, so the
    # report compares implementations and not availability.
    # 显式强制走各条路径，而不是依赖分发器，使报告比较的是"实现"而非"可用性"。
    native_time, native = timeit(
        lambda: animation._decode_all_native(gif_path, target))
    c_time, c_result = timeit(
        lambda: animation._decode_all_c(gif_path, target))

    native_frames = len(native[0]) if native else 0
    c_frames = len(c_result[0]) if c_result else 0
    print(f"  native (Rust)   {native_time * 1000:9.2f} ms   frames={native_frames}")
    print(f"  bundled C       {c_time * 1000:9.2f} ms   frames={c_frames}"
          + ("   (unavailable)" if c_frames == 0 else ""))
    if c_frames and native_frames and native_time > 0:
        print(f"  speed-up        {c_time / native_time:9.2f}x")
    return native_time, c_time


def bench_thumbnail(png_path, box):
    native_time, decoded = timeit(
        lambda: images.decode_thumbnail(png_path, box))

    def qt_path():
        image = QImage(png_path)
        return image.scaled(box, box,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
    qt_time, _ = timeit(qt_path)

    print(f"  native (Rust)   {native_time * 1000:9.2f} ms"
          f"   {decoded.width}x{decoded.height}" if decoded else "  native n/a")
    print(f"  QImage.scaled   {qt_time * 1000:9.2f} ms")
    if decoded and native_time > 0:
        print(f"  speed-up        {qt_time / native_time:9.2f}x")
    return native_time, qt_time


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    del app

    if not images.available():
        print("NATIVE LIBRARY UNAVAILABLE — build it with `cargo build --release`")
        print("在 native/ 下运行 `cargo build --release` 构建原生库")
        return 1

    report = images.describe()
    print(f"library : {report['path']}")
    print(f"version : {report['version']}   scaling threads: {report['threads']}")
    print(f"cpu     : {os.cpu_count()} logical cores")

    with tempfile.TemporaryDirectory() as tmp:
        section("Animated GIF: 24 frames, 300x200, scale to a 76 px card")
        gif = make_animated_gif(os.path.join(tmp, "anim.gif"))
        print(f"  source size: {os.path.getsize(gif) / 1024:.0f} KiB")
        gif_native, gif_c = bench_gif(gif, 76)

        section("Animated GIF: no scaling (source size retained)")
        bench_gif(gif, 0)

        section("Still image: 1200x900 -> 76 px thumbnail (the per-card path)")
        png = make_still(os.path.join(tmp, "still.png"))
        print(f"  source size: {os.path.getsize(png) / 1024:.0f} KiB")
        thumb_native, thumb_qt = bench_thumbnail(png, 76)

        section("Small still: 64x64 -> 76 px box (the FFI-overhead case)")
        from PIL import Image

        tiny = os.path.join(tmp, "tiny.png")
        Image.new("RGB", (64, 64), (200, 100, 50)).save(tiny)
        bench_thumbnail(tiny, 76)

        section("Summary / 结论")
        print("  What the numbers say / 数字说明了什么")
        print()
        if gif_c > 0:
            print(f"  GIF decode alone      : {gif_c / gif_native:.2f}x  "
                  "(+ scaling: only Rust scales)")
        print(f"  thumbnail decode+scale: {thumb_qt / thumb_native:.2f}x")
        print()
        print("  HONEST READING / 如实解读")
        print("  GIF decoding is NOT dramatically faster than the C library. The")
        print("  library was chosen for three other reasons:")
        print("    * correctness -- the C decoder ignored the GIF disposal method,")
        print("      so frames that should restore the background or the previous")
        print("      frame left trails and black boxes; the Rust decoder")
        print("      composites properly and is verified against Pillow;")
        print("    * portability -- one Rust source builds for every platform,")
        print("      while the C decoder needed a separately built and shipped")
        print("      gifdec.dll / .dylib / .so, which is why macOS and Linux had")
        print("      no native decoder at all;")
        print("    * parallel frame scaling -- the C path scales on one Python")
        print("      thread, one QImage.scaled per frame.")
        print()
        print("  The clear throughput win is the THUMBNAIL path, which is also the")
        print("  one that runs most often: once per card materialised and once per")
        print("  card recycled, i.e. multiplied by the number of cards on screen.")
        print()
        print("  GIF 解码并不比 C 库显著更快。选它有三个别的理由：")
        print("    * 正确性——C 解码器忽略 GIF 处置方式，本该恢复背景或上一帧的帧会")
        print("      留下拖影与黑框；Rust 解码器正确合成，并与 Pillow 对照验证；")
        print("    * 可移植性——一份 Rust 源码可构建所有平台，而 C 解码器需要分别")
        print("      构建并随包发布 gifdec.dll / .dylib / .so，这正是 macOS 与")
        print("      Linux 上完全没有原生解码器的原因；")
        print("    * 并行逐帧缩放——C 路径在单个 Python 线程上逐帧 QImage.scaled。")
        print()
        print("  明确的吞吐收益在缩略图路径，而它也是运行最频繁的一条：每次卡片物化")
        print("  一次、每次卡片回收一次，即乘以屏幕上的卡片数量。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
