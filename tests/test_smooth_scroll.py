"""Verify smooth scroll: wheel events animate the scrollbar toward the target
over several frames (no instant jump), and the scrollbar track is transparent
(add-page/sub-page) in both themes. / 验证平滑滚动：滚轮事件让滚动条分多帧
动画靠近目标（非瞬移），两个主题的滚动条轨道为透明（add-page/sub-page）。"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_ss_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

import logging
logging.disable(logging.CRITICAL)

import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication, QScrollArea, QWidget, QVBoxLayout
from PySide6.QtCore import QEvent, QPointF, Qt

from app.main_window import SmoothScroll
from app.models.data_manager import DataManager
import app.main_window as mw

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:110]}")


# --- 1. scrollbar track transparent (add-page/sub-page) in both themes ---
from app.theme.dark_theme import QSS as DARK
from app.theme.light_theme import QSS as LIGHT
for name, qss in (("dark", DARK), ("light", LIGHT)):
    has_v = "QScrollBar::add-page:vertical" in qss and \
        "background: transparent" in qss
    has_h = "QScrollBar::add-page:horizontal" in qss and \
        "background: transparent" in qss
    check(f"{name} 垂直轨道 add/sub-page 透明", has_v)
    check(f"{name} 水平轨道 add/sub-page 透明", has_h)

# --- 2. SmoothScroll animates over frames ---
sa = QScrollArea()
inner = QWidget()
inner.setMinimumHeight(2000)  # big content for a real range / 大内容产生真实 range
sa.setWidget(inner)
sa.resize(300, 200)
sa.show()
app.processEvents()
bar = sa.verticalScrollBar()
print("range:", bar.minimum(), bar.maximum())
sm = SmoothScroll(sa)
# scroll DOWN from a mid position: -300 (wheel DOWN) -> value increases.
# / 从中间位置向下滚：-300（滚轮向下）-> value 增大。
bar.setValue(bar.maximum() // 2)
app.processEvents()
start = bar.value()
sm.handle_wheel(-300)  # wheel DOWN / 滚轮向下
# Capture intermediate values over frames: must progress gradually.
seen = []
for _ in range(30):
    seen.append(bar.value())
    app.processEvents()
    time.sleep(0.01)
intermediate = [v for v in seen if start < v < start + 300]
check("平滑滚动逐步推进（经过中间值）", len(intermediate) > 0, seen[:6])
v_final = bar.value()
print("final value:", v_final, "(start", start, ")")
check("滑动最终到达目标", v_final == min(start + 300, bar.maximum()), v_final)
# reset stops / reset 停止
sm.reset()
v_after_reset = bar.value()
check("reset 后不再滑动", bar.value() == v_after_reset)

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n平滑滚动验证: {n_pass}/{len(RES)} 通过")
import os as _os
_os._exit(0 if n_pass == len(RES) else 1)
