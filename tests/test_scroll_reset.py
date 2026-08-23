"""Verify _reset_scroll_top retries until the range settles: after a group
switch the scrollbar must end at the top even when the range grows lazily
(cards built by the throttled _ensure_visible). / 验证 _reset_scroll_top 在
range 稳定前重试：切换分组后即使懒加载建卡使 range 增长，滚动条最终仍停在
顶部。"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_rs_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

import logging
logging.disable(logging.CRITICAL)

import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication, QScrollArea

from app.models.data_manager import DataManager
from app.widgets.emoji_grid import EmojiGridWidget

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:100]}")


dm = DataManager()
g = dm.create_group("组", "image")
for i in range(50):
    p = os.path.join(TMP, f"{i}.png")
    with open(p, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + bytes(20))
    dm.import_emoji(g, p, auto_convert=False)

grid = EmojiGridWidget()
grid.set_data_manager(dm)
grid.current_group_id = g
sc = QScrollArea()
sc.setWidget(grid)
sc.setWidgetResizable(True)
sc.resize(400, 300)
sc.show()
app.processEvents()
grid.load_emojis(dm.get_emojis_by_group(g), "image")
app.processEvents()
sb = sc.verticalScrollBar()
# force a large range, scroll to the bottom (simulate previous group) /
# 强制大 range 并滚到底（模拟上一个分组）
sb.setRange(0, 5000)
sb.setValue(5000)
app.processEvents()
print("before reset: value =", sb.value(), "(max", sb.maximum(), ")")

# switch (reset scroll) and let the retry run while range settles to small /
# 切换（复位滚动），让重试在 range 收缩到小时运行
sb.setRange(0, 10)  # new group is small / 新分组内容少
grid._reset_scroll_top()
for _ in range(30):
    app.processEvents()
    time.sleep(0.02)
v = sb.value()
print("after reset+settle: value =", v, "(max", sb.maximum(), ")")
check("滑块最终停在顶部", v == 0, v)

# harder: reset, then the range GROWS right after (lazy cards built by the
# throttled ensure_visible) — the retry must still land at the top /
# 更严格：复位后 range 立即增长（节流 ensure_visible 懒加载建卡）——重试
# 仍须停在顶部
sb.setRange(0, 5000)
sb.setValue(5000)
app.processEvents()
grid._scroll_reset_tries = 0
sb.setRange(0, 100)   # first lazy build grows range / 首次懒加载使 range 增长
grid._reset_scroll_top()
sb.setRange(0, 400)   # second build grows it more / 再次增长
for _ in range(30):
    app.processEvents()
    time.sleep(0.02)
v2 = sb.value()
print("after reset+range-grow: value =", v2, "(max", sb.maximum(), ")")
check("range 增长后滑块仍回顶部", v2 == 0, v2)

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n滚动复位重试验证: {n_pass}/{len(RES)} 通过")
import os as _os
_os._exit(0 if n_pass == len(RES) else 1)
