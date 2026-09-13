"""Verify smooth-scroll direction (wheel UP decreases value, wheel DOWN
increases) and the long-name marquee call chain (hover triggers start,
leave triggers stop). / 验证平滑滚动方向（向上减、向下增）与长名称跑马灯
调用链（悬停触发启动、离开触发停止）。"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_dir_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)
from tests._iso import drain_and_exit  # noqa: E402

import logging
logging.disable(logging.CRITICAL)

import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication, QScrollArea, QWidget, QVBoxLayout

from app.models.data_manager import DataManager
from app.widgets.emoji_item import EmojiItem
from app.main_window import SmoothScroll

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:110]}")


# --- A. smooth-scroll direction / 平滑滚动方向 ---
sa = QScrollArea()
inner = QWidget()
inner.setMinimumHeight(2000)
sa.setWidget(inner)
sa.resize(300, 200)
sa.show()
app.processEvents()
bar = sa.verticalScrollBar()
sm = SmoothScroll(sa)

# DOWN (negative delta) -> value increases / 滚轮向下（负）-> value 增大
bar.setValue(bar.maximum() // 2)
app.processEvents()
start = bar.value()
sm.handle_wheel(-200)
for _ in range(30):
    app.processEvents()
    time.sleep(0.01)
check("A 滚轮向下 value 增大", bar.value() > start, (start, bar.value()))

# UP (positive delta) -> value decreases / 滚轮向上（正）-> value 减小
bar.setValue(bar.maximum() // 2)
app.processEvents()
start = bar.value()
sm.handle_wheel(200)
for _ in range(30):
    app.processEvents()
    time.sleep(0.01)
check("A2 滚轮向上 value 减小", bar.value() < start, (start, bar.value()))

# --- B. long-name marquee call chain / 长名称跑马灯调用链 ---
class _DM:
    def emoji_filepath(self, e):
        return None


dm = DataManager()
g = dm.create_group("图", "image")
p = os.path.join(TMP, "a.gif")
with open(p, "wb") as f:
    f.write(b"GIF89a" + b"\x00" * 40)
dm.import_emoji(g, p, auto_convert=False)
e = dm.get_emojis_by_group(g)[0]
e = dict(e)
e["original_name"] = "非常非常长的测试名称用于跑马灯abcdefghijklmnopqrstuvwxyz0123456789"

calls = {"start": 0, "stop": 0}
card = EmojiItem(e, _DM(), show_name=True, hover_zoom=1.2, hover_enabled=True)
card.resize(100, 120)
card.show()
app.processEvents()
# give the card a thumbnail so _show_hover_zoom does not early-return /
# 给卡片设缩略图，避免 _show_hover_zoom 提前返回
from PySide6.QtGui import QPixmap, QColor
card._thumb_label.setPixmap(QPixmap(60, 40))
card._thumb_label.setPixmap(card._thumb_label.pixmap())
_orig_start = card._start_name_scroll
_orig_stop = card._stop_name_scroll
card._start_name_scroll = lambda: (calls.update(start=calls["start"] + 1),
                                   _orig_start())[1]
card._stop_name_scroll = lambda: (calls.update(stop=calls["stop"] + 1),
                                  _orig_stop())[1]
check("B 名字标签有完整名", card._name_full == e["original_name"])
card._show_hover_zoom()
app.processEvents()
check("B2 悬停触发名字滚动启动", calls["start"] > 0, calls)
card._hide_hover_zoom()
app.processEvents()
check("B3 离开触发名字滚动停止", calls["stop"] > 0, calls)
card.deleteLater()

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n滚动方向+跑马灯验证: {n_pass}/{len(RES)} 通过")
import os as _os
drain_and_exit(0 if n_pass == len(RES) else 1)
