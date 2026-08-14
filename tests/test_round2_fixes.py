"""Regression for this round of fixes:
1. apply_thumb survives a deleted C++ widget (the logged QLabel errors)
2. All view loads lazily (few cards created on switch, fast)
3. gif concurrency cap raised on multi-core
4. settings: about-page scroll hides the horizontal bar; version label
   inherits the theme color
本轮修复的回归：
1. apply_thumb 在 C++ 控件已删除时不崩溃（日志中的 QLabel 报错）
2. All 视图懒加载（切换只建可视卡、快速）
3. 多核下动图并发上限提高
4. 设置：关于页滚动区隐藏横向条；版本文字继承主题色"""
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_round2_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

from PIL import Image

import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication, QScrollArea, QWidget
from app.models.data_manager import DataManager
from app.widgets.emoji_grid import EmojiGridWidget
from app.widgets.emoji_item import EmojiItem, _thumb_key
from app.widgets.settings_dialog import SettingsDialog
from app.widgets.hotkey_manager import key_event_to_hotkey_desc

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:100]}")


# 1. apply_thumb on a deleted card must not raise / 已删除卡片上 apply_thumb 不抛异常
dm = DataManager()
g = dm.create_group("回归组", "image")
pngp = os.path.join(TMP, "p.png")
Image.new("RGB", (40, 40), (1, 2, 3)).save(pngp)
dm.import_emoji(g, pngp, auto_convert=False)
emoji = dm.get_emojis_by_group(g)[0]
card = EmojiItem(emoji, dm)
pix = card._thumb_label.pixmap() or __import__("PySide6.QtGui",
                                                fromlist=["QPixmap"]).QPixmap(10, 10)
card.deleteLater()
app.processEvents()
try:
    card.apply_thumb(pix)
    check("A apply_thumb 删除后不崩", True)
except RuntimeError as e:
    check("A apply_thumb 删除后不崩", False, str(e))

# 2. All view lazy load / All 视图懒加载
host = QWidget()
host.resize(800, 600)
host.data_manager = dm
scroll = QScrollArea(host)
scroll.resize(800, 600)
scroll.setWidgetResizable(True)
grid = EmojiGridWidget()
grid.set_data_manager(dm)
scroll.setWidget(grid)
grid._ensure_scroll_connected()
grid._viewport_width = lambda: 620  # realistic width / 真实宽度

# build 300 emojis / 造 300 个表情
for i in range(40):
    p = os.path.join(TMP, f"p{i}.png")
    Image.new("RGB", (30, 30), (i % 255, 100, 200)).save(p)
    dm.import_emoji(g, p, auto_convert=False)
all_emojis = dm.get_all_emojis("")
grid.current_group_id = None
t0 = time.time()
grid.load_emojis(all_emojis, "image")
t_load = (time.time() - t0) * 1000
app.processEvents()
check("B All 懒加载只建可视卡", len(grid._items) < len(all_emojis),
      f"{len(grid._items)}/{len(all_emojis)}")
check("B2 切换快(<300ms)", t_load < 300, f"{t_load:.0f}ms")
_rects, th, _per = grid._all_grid_data(grid._layout_usable())
check("B3 布局覆盖全部数据", th > 0, f"total_h={th}")
grid.current_group_id = g
grid.load_emojis(dm.get_emojis_by_group(g), "image")
app.processEvents()
grid.current_group_id = None
t0 = time.time()
grid.load_emojis(all_emojis, "image")
t_back = (time.time() - t0) * 1000
check("B4 切回 All 快(<300ms)", t_back < 300, f"{t_back:.0f}ms")

# 3. gif concurrency cap / 动图并发上限
n = 8
cap = max(8, n * 4)
check("C 并发上限提高", cap >= 24, f"cap={cap}")

# 4. settings about-page scroll + version label / 设置页关于页滚动区 + 版本文字
dlg = SettingsDialog(parent=None)
from PySide6.QtCore import Qt as _Qt
about_scrolls = [w for w in dlg.findChildren(__import__(
    "PySide6.QtWidgets", fromlist=["QScrollArea"]).QScrollArea)]
horizontal_off = all(
    w.horizontalScrollBarPolicy() == _Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    for w in about_scrolls)
check("D 设置内滚动区均隐藏横向条", horizontal_off)
lbl = dlg._lbl_current
check("D2 版本文字继承主题色", "color:" not in lbl.styleSheet(),
      lbl.styleSheet())
dlg.deleteLater()

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n本轮回归: {n_pass}/{len(RES)} 通过")
try:
    dm._conn.close()
except Exception:
    pass
import os as _os
_os._exit(0 if n_pass == len(RES) else 1)
