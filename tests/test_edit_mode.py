"""Multi-select edit mode smoke test (offscreen): enter edit mode, toggle
selections, verify selection set, delete, and type-isolated moves.
多选编辑模式冒烟测试（离屏）：进入编辑模式、勾选、验证选择集、删除、
以及类型隔离的移动。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_edit_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

import logging
logging.disable(logging.CRITICAL)

import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication

from app.models.data_manager import DataManager
from app.widgets.emoji_item import EmojiItem
from app.widgets.emoji_grid import EmojiGridWidget
import app.main_window as mw

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:100]}")


dm = DataManager()
# image group with 3 gifs / 图片分组 3 个 gif
g1 = dm.create_group("图组", "image")
for i in range(3):
    p = os.path.join(TMP, f"i{i}.gif")
    with open(p, "wb") as f:
        f.write(b"GIF89a" + b"\x00" * (20 + i))
    dm.import_emoji(g1, p, auto_convert=False)
# text group with 2 text emojis / 文字分组 2 个文字
g2 = dm.create_group("文组", "text")
t1 = dm.add_text_emoji(g2, "hello")
t2 = dm.add_text_emoji(g2, "world")

# EmojiItem selection behavior / EmojiItem 勾选行为
img = dm.get_emojis_by_group(g1)
item = EmojiItem(img[0], dm)
item.set_selection_mode(True)
toggled = []
item.selection_toggled.connect(lambda eid, chk: toggled.append((eid, chk)))
item.set_checked(True)
item.set_checked(True)  # same state -> no second signal / 同状态不发第二次
check("A 勾选角标与信号", item.is_checked() and len(toggled) == 1
      and toggled[0][1] is True, toggled)
item.set_selection_mode(False)
check("A2 退出模式清空勾选", not item.is_checked())
item.deleteLater()

# Grid edit mode / 网格编辑模式
win = mw.MainWindow()
win.data_manager = dm
win.current_group_id = g1
grid = win.emoji_grid
win._refresh_emoji_grid()
app.processEvents()
grid.enter_edit_mode()
check("B 进入编辑模式", grid.in_edit_mode())
# hover preview disabled while editing / 编辑期间停用悬停预览
cards = [c for c in grid._items]
check("B2 编辑模式停用悬停", all(not c._hover_enabled for c in cards))
# toggle two via the grid's signal handler / 经网格信号处理器勾选两个
imgs = dm.get_emojis_by_group(g1)
grid._on_selection_toggled(str(imgs[0]["id"]), True)
grid._on_selection_toggled(str(imgs[1]["id"]), True)
check("C 选择两个", grid.selection_count() == 2, grid.selection_count())
check("C2 选择集内容", {e["id"] for e in grid.selected_emojis()} ==
      {imgs[0]["id"], imgs[1]["id"]})
# selection contains the emoji dict with filename / 选择集含文件信息
sel = grid.selected_emojis()
check("C3 选择集带文件", all(e.get("filename") for e in sel))

# Select-all: toggles every visible card / 全选：切换所有可见卡片
win._edit_select_all()
check("C4 全选后选择数=卡片数",
      grid.selection_count() == len(grid._items), grid.selection_count())
win._edit_select_all()  # all selected -> clears / 全部已选 → 清空
check("C5 再次全选清空", grid.selection_count() == 0, grid.selection_count())
# select one, then select-all picks the rest / 选一个，再全选补足其余
grid._on_selection_toggled(str(imgs[0]["id"]), True)
win._edit_select_all()
check("C6 部分选中后全选补足", grid.selection_count() == len(grid._items),
      grid.selection_count())

grid.exit_edit_mode()
check("D 退出清空选择", not grid.in_edit_mode() and grid.selection_count() == 0)
# hover restored after leaving edit mode / 退出后恢复悬停
check("D2 退出后恢复悬停",
      all(c._hover_enabled == grid._hover_preview_enabled for c in grid._items))

# Type isolation for moves / 移动的类型隔离
grid.current_group_id = g1
grid.enter_edit_mode()
grid._on_selection_toggled(str(imgs[0]["id"]), True)
ok_move = dm.move_emoji(imgs[0]["id"], g2)  # image -> text group must fail
check("E 图片不能移入文字组", ok_move is False)
# after failed move the emoji stays in g1 / 移动失败后仍留在 g1
check("E2 图片仍在原组", dm.get_group(g1) is not None
      and any(e["id"] == imgs[0]["id"] for e in dm.get_emojis_by_group(g1)))
# text -> image group must fail too / 文字移入图片组也失败
te = dm.get_emojis_by_group(g2)[0]
check("E3 文字不能移入图片组", dm.move_emoji(te["id"], g1) is False)

# Batch delete via data manager / 经数据管理器批量删除
grid._on_selection_toggled(str(imgs[1]["id"]), True)
sel2 = grid.selected_emojis()
for em in sel2:
    dm.delete_emoji(em["id"])
remaining = dm.get_emojis_by_group(g1)
check("F 批量删除生效", len(remaining) == 1, len(remaining))
grid.exit_edit_mode()

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n多选编辑验证: {n_pass}/{len(RES)} 通过")
import os as _os
_os._exit(0 if n_pass == len(RES) else 1)
