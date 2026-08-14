"""Focused regression for bug 4 (GIF conversion: no console flash, Pillow
first for static images, parallel library conversion) and bug 6 (GIF
playback scaled size preserves the aspect ratio).
Bug4（GIF 转换：无控制台闪烁、静态图优先 Pillow、整库并行转换）与 Bug6
（GIF 播放缩放保持宽高比）的专项回归。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_conv_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

from PIL import Image

import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication
from app.models.data_manager import DataManager
from app.utils import gif_converter
from app.widgets.emoji_item import EmojiItem

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:100]}")


# Bug6: aspect-correct scaled size for a 200x100 GIF -> 80x40
gifp = os.path.join(TMP, "wide.gif")
frames = [Image.new("RGB", (200, 100), (255, 0, 0))]
frames[0].save(gifp, save_all=True, append_images=[Image.new("RGB", (200, 100), (0, 0, 255))],
               duration=100, loop=0, disposal=2)
from PySide6.QtCore import QSize
class _StubDM:
    def emoji_filepath(self, emoji):
        return None

item = EmojiItem({"id": 1, "filename": "x.gif", "group_id": 1}, _StubDM())
size = item._gif_scaled_size(gifp)
check("A 等比缩放尺寸", size == QSize(80, 40), f"{size.width()}x{size.height()}")
check("A2 不超过目标", size.width() <= 80 and size.height() <= 80)

# Bug4a: static PNG converts with Pillow only (no ffmpeg subprocess)
pngp = os.path.join(TMP, "s.png")
Image.new("RGB", (50, 50), (10, 200, 30)).save(pngp)
dst = os.path.join(TMP, "s.gif")
calls = []
orig_run = gif_converter.subprocess.run
gif_converter.subprocess.run = lambda *a, **k: calls.append(a) or None
try:
    ok = gif_converter.convert_to_gif(pngp, dst)
finally:
    gif_converter.subprocess.run = orig_run
check("B 静态图 Pillow 转换成功", ok and os.path.isfile(dst))
check("B2 未启动 ffmpeg", len(calls) == 0, f"calls={len(calls)}")
os.remove(dst)

# Bug4b: animated webp falls back to ffmpeg (subprocess invoked with
# CREATE_NO_WINDOW) / 动画 webp 走 ffmpeg（含 CREATE_NO_WINDOW）
webp = os.path.join(TMP, "a.webp")
frames = [Image.new("RGB", (40, 40), (255, 0, 0)),
          Image.new("RGB", (40, 40), (0, 0, 255))]
frames[0].save(webp, save_all=True, append_images=frames[1:], duration=100)
dst2 = os.path.join(TMP, "a.gif")
calls2 = []
class _FakeProc:
    returncode = 0

orig_ff = gif_converter.ffmpeg_path
gif_converter.ffmpeg_path = lambda: r"C:\fake\ffmpeg.exe"
orig_run = gif_converter.subprocess.run
gif_converter.subprocess.run = (
    lambda *a, **k: calls2.append((a[0], k)) or _FakeProc())
try:
    ok2 = gif_converter.convert_to_gif(webp, dst2)
finally:
    gif_converter.subprocess.run = orig_run
    gif_converter.ffmpeg_path = orig_ff
open(dst2, "wb").write(b"GIF89a-fake")  # pretend ffmpeg produced it
check("C 动画 webp 走 ffmpeg", len(calls2) >= 1, f"calls={len(calls2)}")
if calls2:
    flags = calls2[0][1].get("creationflags", 0)
    check("C2 使用 CREATE_NO_WINDOW", flags == 0x08000000, hex(flags))
    check("C3 ffmpeg 参数含源与目标", calls2[0][0][0].endswith("ffmpeg.exe")
          and calls2[0][0][-1] == dst2)

# Bug4d: a GIF mislabeled as .jpg is copied verbatim (no Pillow/ffmpeg,
# animation preserved) / 伪装成 .jpg 的 GIF 原样复制（不走 Pillow/ffmpeg，
# 动画保留）
misgif = os.path.join(TMP, "fake.jpg")
frames = [Image.new("RGB", (40, 30), (255, 0, 0)),
          Image.new("RGB", (40, 30), (0, 0, 255))]
frames[0].save(misgif, format="GIF", save_all=True,
               append_images=frames[1:], duration=100, loop=0, disposal=2)
calls3 = []
orig_ff3 = gif_converter.ffmpeg_path
gif_converter.ffmpeg_path = lambda: r"C:\fake\ffmpeg.exe"
orig_run3 = gif_converter.subprocess.run
gif_converter.subprocess.run = (
    lambda *a, **k: calls3.append((a[0], k)) or _FakeProc())
try:
    dst3 = os.path.join(TMP, "fake.gif")
    ok3 = gif_converter.convert_to_gif(misgif, dst3)
finally:
    gif_converter.subprocess.run = orig_run3
    gif_converter.ffmpeg_path = orig_ff3
check("E 伪装GIF 转换成功", ok3 and os.path.isfile(dst3))
check("E2 未启动 ffmpeg", len(calls3) == 0, f"calls={len(calls3)}")
if os.path.isfile(dst3):
    import ctypes
    from ctypes import c_void_p, c_int, c_char_p, byref, POINTER
    lib = ctypes.CDLL(os.path.abspath(os.path.join(ROOT, "app", "utils", "gifdec.dll")))
    lib.gif_open.restype = c_void_p
    lib.gif_open.argtypes = [c_char_p, POINTER(c_int), POINTER(c_int), POINTER(c_int)]
    lib.gif_close.argtypes = [c_void_p]
    w, h, n = c_int(), c_int(), c_int()
    hnd = lib.gif_open(dst3.encode("utf-8"), byref(w), byref(h), byref(n))
    frames_n = n.value if hnd else 0
    if hnd:
        lib.gif_close(hnd)
    check("E3 动画保留", frames_n == 2, f"frames={frames_n}")
    # content identical to the source / 与源内容一致
    check("E4 内容字节一致", open(misgif, "rb").read() == open(dst3, "rb").read())

# Bug4c: parallel convert_library_to_gif with workers / 整库并行转换
dm = DataManager()
g = dm.create_group("转换组", "image")
for i in range(4):
    p = os.path.join(TMP, f"p{i}.png")
    Image.new("RGB", (30, 30), (i * 40, 100, 200)).save(p)
    dm.import_emoji(g, p, auto_convert=False)
converted, failed, deduped = dm.convert_library_to_gif(workers=4)
check("D 并行转换 4 张", converted == 4, f"converted={converted} failed={failed}")
rows = dm.get_emojis_by_group(g)
check("D2 全部变为 gif", all(r["filename"].endswith(".gif") for r in rows))

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n转换/缩放验证: {n_pass}/{len(RES)} 通过")
try:
    dm._conn.close()
except Exception:
    pass
import os as _os
_os._exit(0 if n_pass == len(RES) else 1)
