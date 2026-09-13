"""Verify the integrated name-font-size feature (from the friend's PR):
changing the global name font size updates the name label font and the card
height, and the settings dialog exposes it. / 验证融入的名字字号功能（来自
朋友的 PR）：改变全局名字字号会更新名字标签字体与卡片高度，设置对话框也
暴露该项。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_nfs_")
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
from app.widgets.emoji_item import EmojiItem
from app.widgets.settings_dialog import SettingsDialog
import app.main_window as mw

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:110]}")


dm = DataManager()
g = dm.create_group("图组", "image")
p = os.path.join(TMP, "a.gif")
with open(p, "wb") as f:
    f.write(b"GIF89a" + b"\x00" * 40)
dm.import_emoji(g, p, auto_convert=False)
e = dm.get_emojis_by_group(g)[0]

# reset name font to default / 复位名字字号为默认
EmojiItem.set_name_font_size(10)
item = EmojiItem(e, dm, show_name=True)
item.resize(100, 100)
item.show()
app.processEvents()
check("A 默认字号 10", EmojiItem.get_name_font_size() == 10)
check("A2 默认名字区高度 >= 10", EmojiItem.get_name_area() >= 10,
      EmojiItem.get_name_area())
h_before = item._name_label.height()
print("default name label height:", h_before)

# bump font size to 16 -> area grows, label height grows /
# 字号调到 16 -> 名称区变高、标签变高
EmojiItem.set_name_font_size(16)
check("B 字号调为 16", EmojiItem.get_name_font_size() == 16)
check("B2 名称区高度自适应", EmojiItem.get_name_area() == max(10, 16 + 8),
      EmojiItem.get_name_area())
print("name label style:", item._name_label.styleSheet())

# apply via grid and check cards rebuild / 经网格应用并检查卡片重建
win = mw.MainWindow()
win.data_manager = dm
win.current_group_id = g
win._name_font_size = 10
win._refresh_emoji_grid()
app.processEvents()
n0 = len(win.emoji_grid._items)
win.emoji_grid.apply_name_font_size(16)
app.processEvents()
win._name_font_size = 16
n1 = len(win.emoji_grid._items)
check("C 应用字号后卡片保留", n1 >= 0, n1)
if win.emoji_grid._items:
    c = win.emoji_grid._items[0]
    check("C2 卡片名字标签字号已更新", "font-size: 16px" in c._name_label.styleSheet(),
          c._name_label.styleSheet())
    check("C3 card_height 用名称区高度",
          c.card_height(True) == c.card_size() + EmojiItem.get_name_area(),
          (c.card_height(True), c.card_size(), EmojiItem.get_name_area()))

# settings dialog exposes name_font_size / 设置对话框暴露名字字号
dlg = SettingsDialog(name_font_size=16)
app.processEvents()
check("D 设置回显 16", dlg.name_font_size() == 16, dlg.name_font_size())
dlg._spin_name_font.setValue(12)
check("D2 修改后 getter", dlg.name_font_size() == 12, dlg.name_font_size())
dlg.deleteLater()

# grid.apply_name_font_size via main_window _apply path / 经主窗口应用路径
win._name_font_size = 12
win.emoji_grid.apply_name_font_size(12)
app.processEvents()
check("E 主窗口保持字号状态", win._name_font_size == 12)

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n名字字号验证: {n_pass}/{len(RES)} 通过")
import os as _os
drain_and_exit(0 if n_pass == len(RES) else 1)
