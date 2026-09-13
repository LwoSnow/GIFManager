"""Verify scroll throttling: many rapid valueChanged signals coalesce into
fewer rebuilds, and decoding stays paused until the scroll settles.
验证滚动节流：大量快速 valueChanged 合并为少数重建，滚动停稳前解码保持
暂停。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_thr_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)
from tests._iso import drain_and_exit  # noqa: E402

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
g = dm.create_group("节流", "image")
for i in range(60):
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
# fire 200 rapid valueChanged signals; the throttle must coalesce them /
# 触发 200 次快速 valueChanged；节流必须合并
calls = []
_orig = grid._on_scroll_throttled
grid._on_scroll_throttled = lambda: (calls.append(1), _orig())[1]
for _ in range(200):
    sb.valueChanged.emit(sb.value())
app.processEvents()
# wait long enough for the 30 ms throttle to fire at most a couple of times
# (each emit restarts the timer, so with 0 interval between them only the
# last one survives) / 等待 30ms 节流触发（每次 emit 都重启定时器，间隔为 0
# 时只有最后一次生效）
import time
time.sleep(0.05)
for _ in range(10):
    app.processEvents()
n_throttled = len(calls)
check("A 200 次 valueChanged 合并执行", n_throttled <= 3, n_throttled)
check("B 拖拽中标记滚动", grid._scrolling is True)
# wait for the 200 ms settle timer / 等待 200ms 停稳定时器
time.sleep(0.25)
for _ in range(10):
    app.processEvents()
check("C 停稳后恢复解码", grid._scrolling is False)

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n滚动节流验证: {n_pass}/{len(RES)} 通过")
import os as _os
drain_and_exit(0 if n_pass == len(RES) else 1)
