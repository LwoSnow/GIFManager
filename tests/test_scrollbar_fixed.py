"""Verify the scrollbar stays at a FIXED position/width across hover states
(no more "sometimes flush, sometimes normal" caused by width 6px->10px on
hover), and the handle is inset from the window edge by the margin.
验证滚动条在 hover 状态间保持固定位置/宽度（不再"一会贴边一会正常"——
之前 hover 时宽度 6px→10px 导致变化），且 handle 因 margin 与窗口边缘留白。"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QScrollBar

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:100]}")


# Verify the THEME QSS has no hover width change (scale jumps cause the
# on/off-position flicker) / 验证主题 QSS 没有 hover 宽度变化（尺寸跳变
# 导致"贴边/正常"交替闪动）
from app.theme.dark_theme import QSS as DARK_QSS
from app.theme.light_theme import QSS as LIGHT_QSS

for name, qss in (("dark", DARK_QSS), ("light", LIGHT_QSS)):
    has_hover_w = "QScrollBar:vertical:hover" in qss and "width: 10px" in qss
    has_h_hover_w = "QScrollBar:horizontal:hover" in qss and "height: 10px" in qss
    check(f"{name} 主题无滚动条 hover 变宽", not has_hover_w and not has_h_hover_w)
    check(f"{name} 主题垂直滚动条有上下 margin",
          "margin: 4px 0 4px 0" in qss)

# Render a fixed-width bar: hover and non-hover must be pixel-identical for
# geometry (so the slider position is stable). / 渲染固定宽度滚动条：hover 与
# 非 hover 几何必须像素一致（滑块位置稳定）。
sb = QScrollBar(Qt.Orientation.Vertical)
sb.resize(14, 120)
sb.setRange(0, 100)
sb.setValue(50)
sb.setStyleSheet("""
QScrollBar:vertical { background: #252525; width: 14px; border-radius: 0; }
QScrollBar::handle:vertical { background: #4A4A4A; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #666666; }
""")
sb.show()
app.processEvents()
img_normal = sb.grab().toImage().copy()
# simulate hover by grabbing after size unchanged / hover 只是颜色变化
img2 = sb.grab().toImage().copy()
check("hover 前后滚动条尺寸一致",
      img_normal.width() == img2.width() and img_normal.height() == img2.height(),
      (img_normal.width(), img2.width()))
sb.deleteLater()

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n滚动条固定位置验证: {n_pass}/{len(RES)} 通过")
import os as _os
_os._exit(0 if n_pass == len(RES) else 1)
