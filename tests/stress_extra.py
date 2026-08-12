"""GIFManager supplementary stress test: complex image load + single-shot SQL/layout timing
GIFManager 补充压力测试：复杂图像负载 + SQL/布局单次耗时
(Solid-color images decode fastest; real stickers (complex GIF/PNG) are heavier,
so noise images are used to simulate them.)
（纯色图解码最快；真实表情包（复杂 GIF/PNG）解码更重，这里用噪声图模拟）
"""
import os
import sys
import time
import json
import shutil
import tempfile
import random

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_extra_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor, QPainter

import app.main_window as mw_mod


def _isolate_qsettings(tmp):
    _Real = mw_mod.QSettings

    class _Iso(_Real):
        def __init__(self, *a, **k):
            super().__init__(os.path.join(tmp, "settings.ini"), _Real.Format.IniFormat)

    return _Iso


mw_mod.QSettings = _isolate_qsettings(TMP)

import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from app.main_window import MainWindow
from app.models.data_manager import DataManager
from app.models.lang_manager import tr
from app.widgets.emoji_item import _loader

app = QApplication(sys.argv)
RES = {}
OUT = os.path.join(ROOT, "tests", "output")
os.makedirs(OUT, exist_ok=True)


def now():
    return time.perf_counter()


def timed(name, fn):
    t0 = now()
    r = fn()
    RES[name] = round(now() - t0, 3)
    print(f"[{now() - t0:8.3f}s] {name}")
    return r


def flush(ms=50):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.003)


def gen_solid(n, outdir, size=512):
    os.makedirs(outdir, exist_ok=True)
    paths = []
    for i in range(n):
        img = QImage(size, size, QImage.Format.Format_RGB32)
        img.fill(QColor((i * 7 + 13) % 256, (i * 13 + 29) % 256, (i * 29 + 7) % 256))
        p = QPainter(img)
        p.fillRect((i * 37) % 380, (i * 53) % 380, 90, 90,
                   QColor(255 - (i * 7) % 256, 255 - (i * 13) % 256, 255 - (i * 29) % 256))
        p.end()
        fp = os.path.join(outdir, f"solid_{i:05d}.png")
        img.save(fp, "PNG")
        paths.append(fp)
    return paths


def gen_noise(n, outdir, size=512):
    # Complex noise images: 800 random color blocks each, simulating the
    # decode load of real stickers / 复杂噪声图：每张 800 个随机色块，模拟真实表情包解码负载
    os.makedirs(outdir, exist_ok=True)
    paths = []
    for i in range(n):
        rng = random.Random(i)
        img = QImage(size, size, QImage.Format.Format_RGB32)
        img.fill(QColor(20, 20, 20))
        p = QPainter(img)
        for _ in range(800):
            c = QColor(rng.randrange(256), rng.randrange(256), rng.randrange(256))
            p.fillRect(rng.randrange(size - 50), rng.randrange(size - 50),
                       rng.randrange(2, 55), rng.randrange(2, 55), c)
        p.end()
        fp = os.path.join(outdir, f"noise_{i:05d}.png")
        img.save(fp, "PNG")
        paths.append(fp)
    return paths


print("== 生成图片：1800 纯色 + 200 复杂噪声（512x512） ==")
solid = timed("gen_solid_1800", lambda: gen_solid(1800, os.path.join(TMP, "imgs")))
noise = timed("gen_noise_200", lambda: gen_noise(200, os.path.join(TMP, "imgs")))
all_paths = solid + noise
sz = sum(os.path.getsize(p) for p in all_paths)
print(f"  总大小: {sz / 1024 / 1024:.1f} MB（噪声图明显更大）")

print("\n== 导入 2000 张 ==")
dm = DataManager()
default_g = dm.get_group_by_name("Default Expression")
okc = 0


def _import():
    global okc
    for fp in all_paths:
        if dm.import_emoji(default_g["id"], fp) == "ok":
            okc += 1


timed("import_2000", _import)
print(f"  导入成功 {okc}/2000")

print("\n== SQL 查询耗时（2000 行库） ==")
timed("sql_get_all_emojis", lambda: dm.get_all_emojis())
timed("sql_get_all_emojis_kw", lambda: dm.get_all_emojis("img_00"))
timed("sql_get_by_group", lambda: dm.get_emojis_by_group(default_g["id"]))
timed("sql_search_kw", lambda: dm.get_emojis_by_group(default_g["id"], "img_00"))

print("\n== 窗口构造（停在「全部」2000 卡） + 缩略图（含噪声负载） ==")
w = timed("window_ctor", MainWindow)
w.show()
flush(200)
t0 = now()
while len(_loader._pending) > 0:
    app.processEvents()
    time.sleep(0.01)
    if now() - t0 > 300:
        break
flush(150)
RES["thumbs_ready_complex"] = round(now() - t0, 3)
print(f"[{RES['thumbs_ready_complex']:8.3f}s] thumbs_ready_complex（1800 纯色 + 200 噪声）")

print("\n== masonry 布局单次计算耗时（图片分组 2000 张） ==")
w.group_list.select_group(default_g["id"])
flush(200)
grid = w.emoji_grid


def _masonry_once():
    grid._masonry_layout_data(grid._usable_width())


timed("masonry_layout_2000_once", _masonry_once)
RES["masonry_est_fps"] = round(1.0 / max(RES["masonry_layout_2000_once"], 1e-6), 1)

print("\n== 拖拽排序单次写库（set_emoji_column） ==")
emojis = dm.get_emojis_by_group(default_g["id"])
e0, e1 = emojis[0], emojis[1]


def _col():
    dm.set_emoji_column(e0["id"], 0, 0)
    dm.set_emoji_column(e1["id"], 0, 1)


timed("set_emoji_column_x2", _col)

print("\n== 清空 2000 张（逐条删除 + 文件删除） ==")


def _clear():
    for e in list(dm.get_emojis_by_group(default_g["id"])):
        dm.delete_emoji(e["id"])


timed("delete_all_2000", _clear)

print(json.dumps(RES, ensure_ascii=False, indent=2))
with open(os.path.join(OUT, "results_extra.json"), "w", encoding="utf-8") as f:
    json.dump(RES, f, ensure_ascii=False, indent=2)

print("\n清理...")
try:
    dm._conn.close()
except Exception:
    pass
QThreadPool = __import__("PySide6.QtCore", fromlist=["QThreadPool"]).QThreadPool
QThreadPool.globalInstance().waitForDone(3000)
app.quit()
shutil.rmtree(TMP, ignore_errors=True)
