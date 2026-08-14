# Compare the native gifdec.dll decoder against Pillow's GIF reader
# frame by frame (pixel-accurate). Generates GIFs with partial frames and
# different disposal methods. / 用 Pillow 作参考，逐帧像素级对比原生解码器
# 的输出（含局部帧与不同处置方式组合）。
import ctypes
import os
import sys
import tempfile
from ctypes import c_void_p, c_int, c_char_p, c_uint8, byref, POINTER

from PIL import Image, ImageDraw

LIB = ctypes.CDLL(os.path.abspath(os.path.join("app", "utils", "gifdec.dll")))
LIB.gif_open.restype = c_void_p
LIB.gif_open.argtypes = [c_char_p, POINTER(c_int), POINTER(c_int), POINTER(c_int)]
LIB.gif_frame.restype = c_int
LIB.gif_frame.argtypes = [c_void_p, c_int, POINTER(c_uint8)]
LIB.gif_close.argtypes = [c_void_p]

TMP = tempfile.mkdtemp(prefix="gifdec_cmp_")


def decode_native(path):
    w, h, n = c_int(), c_int(), c_int()
    hnd = LIB.gif_open(path.encode("utf-8"), byref(w), byref(h), byref(n))
    if not hnd:
        return None
    buf = (c_uint8 * (w.value * h.value * 4))()
    frames = []
    try:
        for i in range(n.value):
            if not LIB.gif_frame(hnd, i, buf):
                return None
            frames.append(bytes(buf))
    finally:
        LIB.gif_close(hnd)
    return w.value, h.value, frames


def pillow_frames(path):
    im = Image.open(path)
    frames = []
    for i in range(im.n_frames):
        im.seek(i)
        rgba = im.convert("RGBA")
        frames.append(rgba.tobytes())
    return frames


def make_gif(path, specs, disposal=2):
    frames = []
    for color, box in specs:
        im = Image.new("RGBA", (60, 40), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rectangle(box, fill=color)
        frames.append(im)
    frames[0].save(
        path, save_all=True, append_images=frames[1:],
        duration=100, loop=0, disposal=disposal,
    )


def compare(path, label):
    nat = decode_native(path)
    ref = pillow_frames(path)
    if nat is None:
        print(f"[FAIL] {label}: native decode failed")
        return False
    w, h, native_frames = nat
    if len(native_frames) != len(ref):
        print(f"[FAIL] {label}: frame count {len(native_frames)} != {len(ref)}")
        return False
    ok = True
    for i, (a, b) in enumerate(zip(native_frames, ref)):
        if len(a) != len(b):
            print(f"[FAIL] {label} f{i}: size mismatch")
            ok = False
            continue
        # Compare the alpha channel exactly and the RGB channels only where
        # the reference pixel is visible (alpha > 0): fully-transparent pixels
        # may carry any invisible RGB, so only their alpha matters.
        # 逐字节对比：alpha 通道严格一致；RGB 仅在参考像素可见（alpha>0）时比较。
        # 全透明像素的不可见 RGB 可能不同（如清除后 (0,0,0,0) vs 调色板色），
        # 只需比较其 alpha。
        diff = 0
        for o in range(0, len(a), 4):
            if a[o + 3] != b[o + 3]:
                diff += 4
            elif b[o + 3] > 0 and (a[o] != b[o] or a[o + 1] != b[o + 1]
                                   or a[o + 2] != b[o + 2]):
                diff += 4
        if diff:
            print(f"[FAIL] {label} f{i}: {diff} visible bytes differ of {len(a)}")
            ok = False
    if ok:
        print(f"[PASS] {label}: {len(ref)} frames match Pillow (visible pixels)")
    return ok


all_ok = True
if __name__ == "__main__":
    # 1. two full frames, disposal 2 / 两帧整幅 + disposal 2
    p1 = os.path.join(TMP, "a.gif")
    make_gif(p1, [("red", (5, 5, 35, 25)), ("blue", (5, 5, 35, 25))], disposal=2)
    all_ok &= compare(p1, "full-2frames-disp2")

    # 2. partial frames at different positions (overlay), disposal 0
    # 不同位置局部帧（叠加），disposal 0
    p2 = os.path.join(TMP, "b.gif")
    make_gif(p2, [("red", (0, 0, 20, 20)), ("blue", (30, 10, 55, 35))], disposal=0)
    all_ok &= compare(p2, "partial-overlay-disp0")

    # 3. three frames, disposal 2 (each frame clears previous)
    # 三帧 + disposal 2（每帧清除上一帧）
    p3 = os.path.join(TMP, "c.gif")
    make_gif(p3, [
        ("red", (0, 0, 25, 39)),
        ("lime", (17, 0, 42, 39)),
        ("blue", (34, 0, 59, 39)),
    ], disposal=2)
    all_ok &= compare(p3, "three-frames-disp2")

    # 4. disposal 1 (keep: frames accumulate)
    # disposal 1（保留：帧叠加）
    p4 = os.path.join(TMP, "d.gif")
    make_gif(p4, [
        ("red", (0, 0, 25, 39)),
        ("lime", (17, 0, 42, 39)),
    ], disposal=1)
    all_ok &= compare(p4, "two-frames-disp1")

    # 5. random noise frames (exercises LZW heavily), disposal 2
    # 随机噪声帧（充分锻炼 LZW），disposal 2
    import random
    random.seed(7)
    frames = []
    for k in range(4):
        im = Image.new("RGBA", (48, 48), (0, 0, 0, 0))
        px = im.load()
        for x in range(48):
            for y in range(48):
                px[x, y] = (random.randrange(256), random.randrange(256),
                            random.randrange(256), 255 if (x + y + k) % 3 else 0)
        frames.append(im)
    p5 = os.path.join(TMP, "e.gif")
    frames[0].save(p5, save_all=True, append_images=frames[1:],
                   duration=100, loop=0, disposal=2)
    all_ok &= compare(p5, "noise-4frames-disp2")

    # 6. disposal 3 (restore to previous frame) / 恢复前一帧
    p6 = os.path.join(TMP, "f.gif")
    frames = []
    for color, box in [("red", (0, 0, 25, 39)), ("lime", (17, 0, 42, 39)),
                       ("blue", (34, 0, 59, 39))]:
        im = Image.new("RGBA", (60, 40), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rectangle(box, fill=color)
        frames.append(im)
    frames[0].save(p6, save_all=True, append_images=frames[1:],
                   duration=100, loop=0, disposal=3)
    all_ok &= compare(p6, "three-frames-disp3")

    # 7. interlaced GIF / 隔行扫描 GIF
    p7 = os.path.join(TMP, "g.gif")
    im = Image.new("P", (48, 48))
    im.putpalette([0, 0, 0, 255, 0, 0, 0, 255, 0, 0, 0, 255] + [0] * 12)
    for x in range(48):
        for y in range(48):
            im.putpixel((x, y), 1 + ((x + y) % 3))
    im.save(p7, interlace=True)
    all_ok &= compare(p7, "single-interlaced")

    print("RESULT:", "ALL PASS" if all_ok else "SOME FAILED")
    sys.exit(0 if all_ok else 1)
