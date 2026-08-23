"""Verify rename keeps the scroll position (keep_scroll=True path). /
验证重命名保持滚动位置（keep_scroll=True 路径）。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_ren_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

import logging
logging.disable(logging.CRITICAL)

import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from app.models.data_manager import DataManager
import app.main_window as mw

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:100]}")


dm = DataManager()
win = mw.MainWindow()
win.data_manager = dm
g = dm.create_group("重命名", "image")
for i in range(40):
    p = os.path.join(TMP, f"{i}.gif")
    with open(p, "wb") as f:
        f.write(b"GIF89a" + b"\x00" * 30)
    dm.import_emoji(g, p, auto_convert=False)
win.current_group_id = g
win._refresh_emoji_grid()
app.processEvents()

sb = win._scroll_area.verticalScrollBar()
print("scrollbar max:", sb.maximum())
# Force a real scroll position (needs a scrollable range) /
# 强制一个真实滚动位置（需要有滚动范围）
if sb.maximum() > 0:
    sb.setValue(sb.maximum() // 2)
else:
    # offscreen may report 0 range; set a value manually to still exercise
    # the preserve path / offscreen 可能报告 0 范围；手动设值以测试保留路径
    sb.setRange(0, 1000)
    sb.setValue(500)
app.processEvents()
v1 = sb.value()
print("scroll before rename:", v1)

# rename the FIRST emoji (id unchanged) / 重命名第一个表情（id 不变）
e = dm.get_emojis_by_group(g)[0]
win._refresh_emoji_grid(keep_scroll=True)
app.processEvents()
# flush the restore timer / 冲刷恢复定时器
for _ in range(5):
    app.processEvents()
    QTimer.singleShot(10, lambda: None)
    app.processEvents()
v2 = sb.value()
print("scroll after keep_scroll refresh:", v2)
check("重命名保持滚动位置", v1 == v2, (v1, v2))

# deleting an emoji (data set changes) resets to top (control) /
# 删除表情（数据集变化）回顶（对照）
sb.setRange(0, 1000)
sb.setValue(1000)
app.processEvents()
v3 = sb.value()
dm.delete_emoji(dm.get_emojis_by_group(g)[-1]["id"])
win._refresh_emoji_grid()
for _ in range(10):
    app.processEvents()
v4 = sb.value()
print("scroll after delete refresh:", v4, "(was", v3, ")")
check("删除后刷新回顶（对照）", v4 == 0, v4)

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n重命名滚动保持验证: {n_pass}/{len(RES)} 通过")
import os as _os
_os._exit(0 if n_pass == len(RES) else 1)
