"""Verify horizontal scrollbar resets to the left on group switch (the
previous group's horizontal value must not stick the handle to the right
edge). / 验证切换分组后水平滚动条复位到最左（上一分组的水平滚动值不得让
滑块贴到右侧边缘）。"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_hs_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

# Isolate QSettings / the per-app GPU preference from the real user state /
# 隔离 QSettings 与按应用 GPU 首选项，避免影响用户真实状态
from tests._iso import isolate_all, drain_and_exit  # noqa: E402

isolate_all()

import logging
logging.disable(logging.CRITICAL)

import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication

from app.models.data_manager import DataManager
import app.main_window as mw

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:100]}")


dm = DataManager()
t1 = dm.create_group("文字一", "text")
t2 = dm.create_group("文字二", "text")
for i in range(30):
    dm.add_text_emoji(t1, f"很长很长的文字内容第{i}个用于撑宽")
    dm.add_text_emoji(t2, f"短{i}")
img = dm.create_group("图片组", "image")

win = mw.MainWindow()
win.data_manager = dm
win.show()
app.processEvents()

# switch to text group 1, force horizontal scroll to the right / 切文字组1，
# 强制水平滚动到最右
win.group_list.select_group(t1)
for _ in range(20):
    app.processEvents()
    time.sleep(0.01)
hb = win._scroll_area.horizontalScrollBar()
if hb.maximum() > 0:
    hb.setValue(hb.maximum())
    app.processEvents()
    print("text1 h-scroll value:", hb.value())
else:
    print("text1 no h-scroll range")

# switch to image group (horizontal off) then back to text 2 / 切图片组再切
# 回文字组2
win.group_list.select_group(img)
for _ in range(20):
    app.processEvents()
    time.sleep(0.01)
win.group_list.select_group(t2)
for _ in range(20):
    app.processEvents()
    time.sleep(0.01)
hb2 = win._scroll_area.horizontalScrollBar()
print("after switch to text2: h-scroll value =", hb2.value(),
      "(max", hb2.maximum(), ")")
check("切换分组后水平滚动复位最左", hb2.value() == 0, hb2.value())

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n水平滚动复位验证: {n_pass}/{len(RES)} 通过")
import os as _os
drain_and_exit(0 if n_pass == len(RES) else 1)
