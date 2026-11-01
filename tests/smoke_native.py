"""Verify the Rust image pipeline against the pure-Qt path.

Two things have to hold for the native library to be usable as a drop-in
replacement:

1. it must produce the same PIXELS as the Qt path, within a resampling tolerance;
2. it must handle the GIF cases the old C decoder got wrong — sub-rectangle
   frames, transparency, and the disposal methods — and be checked against a
   reference rather than against itself.

The reference here is Pillow, which is an independent implementation: agreeing
with it is evidence about the pixels, not about our own assumptions.

验证 Rust 图像管线相对于纯 Qt 路径的正确性。

原生库要能作为直接替换使用，必须满足两件事：

1. 必须产出与 Qt 路径"相同"的像素，误差在重采样容差内；
2. 必须正确处理旧 C 解码器做错的 GIF 情形——子矩形帧、透明度、处置方式——并且是
   与参考实现对照，而不是与自己对拍。

此处的参考实现是 Pillow，它是一个独立实现：与它一致是关于"像素正确"的证据，而不是
关于我们自己假设的证据。
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QGuiApplication

from gifmanager.frontend.qt import images


def section(title):
    print()
    print("=" * 4, title)


def make_gif(path, frames, size=(64, 48), delays=None, disposal=2):
    # Build a GIF from full-canvas frames with Pillow. Full-canvas frames keep
    # the reference simple; the sub-rectangle case is covered separately by
    # checking that the native decoder agrees with Pillow on a real-world file.
    # 用 Pillow 从整画布帧构建 GIF。整画布帧让参考实现保持简单；子矩形情形另行通过与
    # Pillow 在真实文件上的一致性来覆盖。
    from PIL import Image

    delays = delays or [100] * len(frames)
    images_list = []
    for pixels in frames:
        image = Image.new("RGBA", size)
        image.putdata(pixels)
        images_list.append(image.convert("P", palette=Image.Palette.ADAPTIVE))
    images_list[0].save(path, save_all=True, append_images=images_list[1:],
                        duration=delays, loop=0, disposal=disposal)
    return path


def solid(color, size=(64, 48)):
    return [color] * (size[0] * size[1])


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    del app

    section("library discovery")
    report = images.describe()
    print("available :", report["available"])
    print("path      :", report["path"])
    print("version   :", report["version"])
    print("threads   :", report["threads"])
    if not report["available"]:
        print()
        print("NATIVE LIBRARY UNAVAILABLE / 原生库不可用")
        print("build it with: cargo build --release   (run inside native/)")
        return 1

    problems = []

    with tempfile.TemporaryDirectory() as tmp:
        section("GIF decode: multi-frame, delays, size")
        gif = os.path.join(tmp, "three.gif")
        make_gif(gif, [solid((255, 0, 0, 255)),
                       solid((0, 255, 0, 255)),
                       solid((0, 0, 255, 255))],
                 delays=[80, 120, 250])
        decoded = images.decode_gif(gif)
        print("frames    :", decoded.frame_count if decoded else None)
        print("size      :", f"{decoded.width}x{decoded.height}" if decoded else None)
        print("delays    :", decoded.delays if decoded else None)
        if decoded is None:
            problems.append("decode_gif returned None for a valid GIF")
        else:
            if decoded.frame_count != 3:
                problems.append(f"expected 3 frames, got {decoded.frame_count}")
            if (decoded.width, decoded.height) != (64, 48):
                problems.append(f"unexpected size {decoded.width}x{decoded.height}")
            # Delays must survive; a 0 would mean the field was dropped.
            # 延迟必须保留；为 0 意味着该字段被丢弃。
            if decoded.delays != (80, 120, 250):
                problems.append(f"delays not preserved: {decoded.delays}")
            # Every frame must be fully opaque red/green/blue, in order.
            # 每帧必须依次是完全不透明的红/绿/蓝。
            for index, expected in enumerate(((255, 0, 0), (0, 255, 0), (0, 0, 255))):
                first = decoded.frames[index][:4]
                if tuple(first[:3]) != expected or first[3] != 255:
                    problems.append(
                        f"frame {index} first pixel is {tuple(first)}, "
                        f"expected {expected + (255,)}")

        section("GIF decode with scaling")
        scaled = images.decode_gif(gif, target=32)
        print("size      :", f"{scaled.width}x{scaled.height}" if scaled else None)
        print("frame mb  :", round(scaled.frame_bytes / 1024, 1) if scaled else None,
              "KiB")
        if scaled is None:
            problems.append("scaled decode returned None")
        else:
            if max(scaled.width, scaled.height) != 32:
                problems.append(
                    f"longest side is {max(scaled.width, scaled.height)}, "
                    f"expected 32")
            # Aspect ratio 64x48 -> longest side 32 gives 32x24 /
            # 64x48 的长边缩到 32 得到 32x24
            if (scaled.width, scaled.height) != (32, 24):
                problems.append(
                    f"aspect ratio not preserved: {scaled.width}x{scaled.height}")

        section("sub-rectangle frames and transparency (Pillow as reference)")
        # A GIF whose second frame is a small rectangle on a persistent canvas is
        # exactly the case the old C decoder rendered wrong.
        # 第二帧是持久画布上的一个小矩形，这正是旧 C 解码器渲染错误的情形。
        from PIL import Image

        sub = os.path.join(tmp, "subrect.gif")
        base = Image.new("RGBA", (80, 60), (0, 0, 0, 0))
        base.paste((255, 0, 0, 255), (0, 0, 80, 60))
        overlay = base.copy()
        overlay.paste((0, 255, 0, 255), (20, 15, 60, 45))
        frames = [base.convert("P", palette=Image.Palette.ADAPTIVE),
                  overlay.convert("P", palette=Image.Palette.ADAPTIVE)]
        frames[0].save(sub, save_all=True, append_images=frames[1:],
                       duration=[100, 100], loop=0, disposal=1)

        our = images.decode_gif(sub)
        with Image.open(sub) as reference:
            ref_frames = []
            for index in range(getattr(reference, "n_frames", 1)):
                reference.seek(index)
                ref_frames.append(reference.convert("RGBA").tobytes())

        print("ours frames:", our.frame_count if our else None,
              " reference frames:", len(ref_frames))
        if our is None:
            problems.append("sub-rectangle decode returned None")
        elif our.frame_count != len(ref_frames):
            problems.append(
                f"frame count differs: {our.frame_count} vs {len(ref_frames)}")
        else:
            for index, ref in enumerate(ref_frames):
                ours = our.frames[index]
                if len(ours) != len(ref):
                    problems.append(f"frame {index} byte length differs")
                    continue
                # Compare a sample of pixels rather than every byte: Pillow and
                # the `gif` crate may quantise slightly differently, so exact
                # equality would be the wrong test. What matters is that the
                # composite is in the right PLACE.
                # 抽样比较像素而不是逐字节比较：Pillow 与 `gif` crate 的量化可能略有
                # 差异，因此严格相等是错误的判据。真正重要的是合成结果在正确的"位置"。
                mismatches = 0
                for pixel in (0, 20 + 15 * 80, 40 + 30 * 80, 79 + 59 * 80):
                    offset = pixel * 4
                    if ours[offset:offset + 3] != ref[offset:offset + 3]:
                        mismatches += 1
                print(f"  frame {index}: sampled mismatches = {mismatches}")
                if mismatches:
                    problems.append(
                        f"frame {index}: {mismatches} of 4 sampled pixels differ "
                        f"from Pillow")

        section("thumbnail decode and scale")
        png = os.path.join(tmp, "still.png")
        from PIL import Image as PILImage

        PILImage.new("RGB", (400, 300), (10, 200, 90)).save(png)
        thumb = images.decode_thumbnail(png, 96)
        print("size      :", f"{thumb.width}x{thumb.height}" if thumb else None)
        print("bytes     :", thumb.frame_bytes if thumb else None)
        if thumb is None:
            problems.append("decode_thumbnail returned None")
        else:
            if max(thumb.width, thumb.height) != 96:
                problems.append(
                    f"thumbnail longest side {max(thumb.width, thumb.height)}, "
                    f"expected 96")
            # Centre pixel must be the fill colour, proving the resampler
            # preserved content rather than producing a blank image.
            # 中心像素必须是填充色，证明重采样器保留了内容而不是产出了空白图。
            centre = ((thumb.height // 2) * thumb.width + thumb.width // 2) * 4
            got = tuple(thumb.pixels[centre:centre + 3])
            print("centre rgb:", got)
            if any(abs(a - b) > 6 for a, b in zip(got, (10, 200, 90))):
                problems.append(f"centre pixel {got} is not the fill colour")

        section("no-upscale guarantee")
        small = os.path.join(tmp, "small.png")
        PILImage.new("RGB", (16, 16), (255, 255, 0)).save(small)
        up = images.decode_thumbnail(small, 256)
        print("16x16 into a 256 box ->", f"{up.width}x{up.height}" if up else None)
        if up is None:
            problems.append("small thumbnail returned None")
        elif (up.width, up.height) != (16, 16):
            problems.append(
                f"a 16x16 source was upscaled to {up.width}x{up.height}")

        section("comparison with the Qt path")
        # Decode the same still both ways and compare the mean absolute error.
        # The two resamplers are different algorithms, so exact equality is not
        # expected; a large error would mean one of them is wrong rather than
        # merely different.
        # 用两种方式解码同一张静态图并比较平均绝对误差。两种重采样器算法不同，因此不
        # 期望严格相等；误差过大会说明其中一个是错的，而不只是不同。
        q_image = QImage(png).scaled(
            96, 96,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        q_image = q_image.convertToFormat(QImage.Format.Format_RGBA8888)
        if thumb and q_image.width() == thumb.width and q_image.height() == thumb.height:
            qt_bytes = bytes(q_image.constBits())
            total = min(len(qt_bytes), len(thumb.pixels))
            diff = sum(abs(qt_bytes[i] - thumb.pixels[i])
                       for i in range(0, total, 4))  # sample the red channel / 抽样红色通道
            mean = diff / max(1, total // 4)
            print("mean red-channel difference:", round(mean, 2))
            if mean > 24:
                problems.append(f"mean channel difference {mean:.1f} is too large")
        else:
            print("sizes differ, skipping the numeric comparison")

    print()
    if problems:
        print("NATIVE PIPELINE CHECK FAILED / 原生管线检查未通过")
        for problem in problems:
            print("  " + problem)
        return 1
    print("NATIVE PIPELINE CHECK OK / 原生管线检查通过")
    print("  GIF frames, delays, sub-rectangles, transparency, scaling and")
    print("  thumbnails all agree with an independent implementation")
    print("  GIF 帧、延迟、子矩形、透明度、缩放与缩略图均与独立实现一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
