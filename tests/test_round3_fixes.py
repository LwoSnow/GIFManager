"""Verify the three fixes:
1. English settings: no scrollable control shows a horizontal bar
2. Grid resize triggers lazy creation + visible-GIF refresh
3. At the new minimum width, image columns fill the width without a big
   right-side blank strip
验证三个修复：
1. 英文设置：所有滚动控件无横向滚动条
2. 网格 resize 触发懒加载创建 + 可见 GIF 刷新
3. 新最小宽度下图片列铺满、右侧无大片空白"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_r3_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

from PIL import Image

import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import (QApplication, QAbstractScrollArea, QScrollArea,
                               QWidget)
from PySide6.QtCore import Qt, QSize, QEvent
from app.models.data_manager import DataManager
from app.models.lang_manager import set_language
from app.widgets.emoji_grid import EmojiGridWidget
from app.widgets.settings_dialog import SettingsDialog
from app.models.constants import MIN_WINDOW_WIDTH

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:100]}")


# 1. English settings: no horizontal bars / 英文设置无横向条
set_language("en_US")
dlg = SettingsDialog(parent=None)
dlg.show()
app.processEvents()
bars = []
for w in dlg.findChildren(QAbstractScrollArea):
    h = w.horizontalScrollBar()
    if h.isVisible() and h.maximum() > 0:
        bars.append(f"{w.__class__.__name__}(max={h.maximum()})")
check("A 英文设置无横向滚动条", not bars, f"bars={bars}")
check("A2 窗口加大到 470", dlg.width() == 470, f"w={dlg.width()}")
dlg.deleteLater()

# 2. resize triggers lazy creation + gif refresh / resize 触发懒加载与 GIF 刷新
dm = DataManager()
g = dm.create_group("回归组2", "image")
for i in range(30):
    p = os.path.join(TMP, f"p{i}.png")
    Image.new("RGB", (30, 30), (i % 255, 100, 200)).save(p)
    dm.import_emoji(g, p, auto_convert=False)
# spread columns like a real group / 模拟真实分组已摊列
dm.assign_unassigned_columns(g, 540, 8, lambda e: 100)

host = QWidget()
host.data_manager = dm
host.resize(600, 600)
scroll = QScrollArea(host)
scroll.resize(600, 600)
scroll.setWidgetResizable(True)
grid = EmojiGridWidget()
grid.set_data_manager(dm)
scroll.setWidget(grid)
grid._ensure_scroll_connected()
grid._viewport_width = lambda: 560
grid.current_group_id = g
grid.load_emojis(dm.get_emojis_by_group(g), "image")
app.processEvents()

called = {"ensure": 0, "gif": 0}
orig_ensure = grid._ensure_visible
orig_gif = grid._update_visible_gifs


def spy_ensure():
    called["ensure"] += 1
    return orig_ensure()


def spy_gif():
    called["gif"] += 1
    return orig_gif()


grid._ensure_visible = spy_ensure
grid._update_visible_gifs = spy_gif
# simulate a resize event / 模拟 resize 事件
from PySide6.QtGui import QResizeEvent
grid.resizeEvent(QResizeEvent(QSize(800, 800), QSize(600, 600)))
check("B resize 启动防抖刷新定时器", grid._resize_refresh_timer.isActive())
import time
deadline = time.time() + 1
while (called["ensure"] == 0 or called["gif"] == 0) and time.time() < deadline:
    app.processEvents()
    time.sleep(0.01)
check("B2 防抖后触发懒加载刷新", called["ensure"] >= 1, f"ensure={called['ensure']}")
check("B3 防抖后触发 GIF 刷新", called["gif"] >= 1, f"gif={called['gif']}")

# 3. minimum width fits 3 columns / 最小宽度容纳 3 列
# full grid so the merge path (window shrink -> merge columns) runs
# 完整网格以走融合路径（窗口缩小 -> 列融合）
grid2 = EmojiGridWidget()
grid2.set_data_manager(dm)
grid2.current_group_id = g
host2 = QWidget()
host2.data_manager = dm
scroll2 = QScrollArea(host2)
scroll2.setWidgetResizable(True)
scroll2.setWidget(grid2)
grid2._ensure_scroll_connected()
grid2._viewport_width = lambda: MIN_WINDOW_WIDTH
grid2.load_emojis(dm.get_emojis_by_group(g), "image")
app.processEvents()
# window shrinks to the minimum -> merge overflowing columns / 窗口缩到最小
grid2._check_column_merge()
app.processEvents()
rows = dm.get_emojis_by_group(g)
col_count = len({int(e["col_index"]) for e in rows})
usable = MIN_WINDOW_WIDTH - 20
rects, tw, th, info = grid2._masonry_layout_data(usable)
print(f"  MIN_WINDOW_WIDTH={MIN_WINDOW_WIDTH} usable={usable} "
      f"cols={col_count} total_w={tw}")
check("C 最小宽度融合到 3 列", col_count == 3, f"cols={col_count}")
check("C2 列总宽不超可用宽", tw <= usable + 40, f"total_w={tw} usable={usable}")
check("C3 右侧空白 < 40px", usable - (tw - 20) < 40, f"空白={usable - (tw - 20)}px")

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n本轮验证: {n_pass}/{len(RES)} 通过")
try:
    dm._conn.close()
except Exception:
    pass
import os as _os
_os._exit(0 if n_pass == len(RES) else 1)
