"""Settings-dialog layout regressions: clipped checkboxes / clipped text.

Two reported defects and the general invariant behind them:
  * every QCheckBox row must be taller than its indicator (the row used to be
    exactly the indicator's height, so the box was clipped under DPI scaling),
    while `QCheckBox::indicator` must stay UNSTYLED so the native tick survives;
  * every word-wrapped label must be given its real wrapped height (the About
    page was not wrapped in a scroll area, so the fit pass skipped it and the
    MIT licence was cut off top and bottom);
  * every page must be scrollable.
设置界面的排版回归：复选框被裁 / 文字被裁，以及它们背后的通用不变量。
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import logging
import re
logging.disable(logging.CRITICAL)

TMP = tempfile.mkdtemp(prefix="setlayout106_")
import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QScrollArea, \
    QStyle, QStyleOptionButton
from tests._iso import isolate_all, drain_and_exit

isolate_all()
app = QApplication.instance() or QApplication(sys.argv)

from app.main_window import MainWindow
from app.theme.dark_theme import QSS as DARK_QSS
from app.theme.light_theme import QSS as LIGHT_QSS

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name
          + ((" | " + str(detail)) if detail else ""))


def settle(ms=320):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.005)


win = MainWindow()
win.show()
settle()
win._open_settings()
dlg = win._settings_dialog
settle()

PAGES = 7

# ------------------------------------------------ 1. page structure / 页面结构
print("\n[1] every page scrolls / 每页都可滚动")
bare = [i for i in range(dlg._stack.count())
        if not isinstance(dlg._stack.widget(i), QScrollArea)]
check("all settings pages are wrapped in a scroll area", not bare,
      f"bare page indexes={bare}")

# ------------------------------------------------ 2. checkbox indicator room
print("\n[2] checkbox rows leave room for the indicator / 复选框行高留有余量")
for theme_name, qss in (("dark", DARK_QSS), ("light", LIGHT_QSS)):
    app.setStyleSheet(qss)
    dlg.setStyleSheet(qss)
    for i in range(PAGES):
        dlg._cat_list.setCurrentRow(i)
        settle(200)
        page = dlg._stack.widget(i)
        inner = page.widget() if isinstance(page, QScrollArea) else page
        for cb in inner.findChildren(QCheckBox):
            opt = QStyleOptionButton()
            cb.initStyleOption(opt)
            ind = cb.style().subElementRect(
                QStyle.SubElement.SE_CheckBoxIndicator, opt, cb)
            cnt = cb.style().subElementRect(
                QStyle.SubElement.SE_CheckBoxContents, opt, cb)
            ok = (cb.height() >= ind.height() + 2 and cnt.left() >= ind.right())
            check(f"[{theme_name}] p{i} {cb.text()[:18]}: row {cb.height()} >= "
                  f"indicator {ind.height()}+2, text starts at {cnt.x()} "
                  f"(indicator ends {ind.right()})", ok)
def _strip_css_comments(qss):
    # The theme files explain WHY the indicator is left native, so the words
    # "QCheckBox::indicator" do appear in comments; only real rules count.
    # 主题文件里解释了"为什么把指示器交回原生"，因此注释里会出现
    # "QCheckBox::indicator" 字样；这里只看真正的规则。
    return re.sub(r"/\*.*?\*/", "", qss, flags=re.S)


check("QCheckBox::indicator is left to the native style, so the tick survives",
      "QCheckBox::indicator" not in _strip_css_comments(DARK_QSS)
      and "QCheckBox::indicator" not in _strip_css_comments(LIGHT_QSS))
check("the DPI-safe row height is still pinned in both themes",
      "min-height: 18px" in DARK_QSS and "min-height: 18px" in LIGHT_QSS)


def _indicator_image(widget, checked):
    # Draw ONLY the indicator primitive into an offscreen image. This needs no
    # visible window (QWidget.grab() on the offscreen platform crashed at
    # teardown) and it targets the box itself rather than the whole row.
    # 只把"指示器"这一原件画进离屏图像：既不需要可见窗口（离屏平台下
    # QWidget.grab() 会在退出阶段崩溃），也只看方框本身而不是整行。
    img = QImage(20, 20, QImage.Format.Format_ARGB32)
    img.fill(0)
    painter = QPainter(img)
    opt = QStyleOptionButton()
    opt.rect = QRect(1, 1, 18, 18)
    opt.state = (QStyle.StateFlag.State_Enabled
                 | (QStyle.StateFlag.State_On if checked
                    else QStyle.StateFlag.State_Off))
    widget.style().drawPrimitive(
        QStyle.PrimitiveElement.PE_IndicatorCheckBox, opt, painter, widget)
    painter.end()
    return img


for theme_name, qss in (("dark", DARK_QSS), ("light", LIGHT_QSS)):
    app.setStyleSheet(qss)
    dlg.setStyleSheet(qss)
    settle(200)
    probe = dlg.findChildren(QCheckBox)[0]
    on = _indicator_image(probe, True)
    off = _indicator_image(probe, False)
    check(f"[{theme_name}] a checked box paints differently from an empty one "
          f"(i.e. the tick is drawn)", on != off)

app.setStyleSheet(DARK_QSS)
dlg.setStyleSheet(DARK_QSS)
settle(200)

# ------------------------------------------------ 3. wrapped labels get height
print("\n[3] wrapped labels are given their real height / 换行标签获得真实高度")
for i in range(PAGES):
    dlg._cat_list.setCurrentRow(i)
    settle(320)
    page = dlg._stack.widget(i)
    inner = page.widget() if isinstance(page, QScrollArea) else page
    clipped = []
    for lab in inner.findChildren(QLabel):
        if not lab.wordWrap() or not lab.text() or lab.width() <= 0:
            continue
        needed = lab.heightForWidth(lab.width())
        if needed > lab.height() + 1:
            clipped.append((lab.text()[:24].replace("\n", "\\n"),
                            lab.height(), needed))
    check(f"page {i}: no vertically clipped wrapped label", not clipped,
          clipped[:3])

# ------------------------------------------------ 4. the MIT licence in full
print("\n[4] MIT licence is fully visible / MIT 许可完整可见")
dlg._cat_list.setCurrentRow(6)
settle(400)
mit = [w for w in dlg.findChildren(QLabel) if "MIT License" in (w.text() or "")]
check("the licence label exists", len(mit) == 1, len(mit))
if mit:
    lab = mit[0]
    need = lab.heightForWidth(lab.width())
    check("the licence label shows every line",
          lab.height() >= need, f"height={lab.height()} needed={need}")
    check("its minimum height is pinned to the wrapped height",
          lab.minimumHeight() >= need, lab.minimumHeight())
    check("it is left/top aligned (a centred licence reads badly)",
          bool(lab.alignment() & 0x0001), lab.alignment())
    sa = lab.parentWidget()
    while sa is not None and not isinstance(sa, QScrollArea):
        sa = sa.parentWidget()
    check("the licence sits in a scrollable page", sa is not None)
    if sa is not None:
        check("the page can scroll far enough to reach the end",
              sa.verticalScrollBar().maximum() > 0,
              f"vsb max={sa.verticalScrollBar().maximum()} "
              f"content={sa.widget().height()} viewport={sa.viewport().height()}")

# ------------------------------------------------ 5. update page checkbox
print("\n[5] the reported checkbox / 被报告的复选框")
dlg._cat_list.setCurrentRow(5)
settle(300)
cb = dlg._cb_auto_update
opt = QStyleOptionButton()
cb.initStyleOption(opt)
ind = cb.style().subElementRect(
    QStyle.SubElement.SE_CheckBoxIndicator, opt, cb)
check("the update-page checkbox row is taller than its box",
      cb.height() >= ind.height() + 2, f"row={cb.height()} box={ind.height()}")
check("its text does not start over the box",
      cb.style().subElementRect(
          QStyle.SubElement.SE_CheckBoxContents, opt, cb).left()
      >= ind.right())

print("\n" + "=" * 62)
print(f"PASS {len(PASS)} | FAIL {len(FAIL)}")
for f in FAIL:
    print("  FAILED: " + f)
print("RESULT", "OK" if not FAIL else "NG")
drain_and_exit(0 if not FAIL else 1)
