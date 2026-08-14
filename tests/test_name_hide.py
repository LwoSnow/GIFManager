"""Regression for: delete_group tolerates a transiently locked GIF file
(the logged PermissionError), and the "show emoji name" setting hides the
name strip (cards + layout use the shorter height).
回归测试：delete_group 容忍瞬时被占用的 GIF 文件（日志中的
PermissionError）；"显示表情包名称"设置可隐藏名称条（卡片与布局用矮高度）。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_name_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

from PIL import Image

import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication
from app.models.data_manager import DataManager
from app.widgets.emoji_item import EmojiItem
from app.widgets.emoji_grid import EmojiGridWidget
from app.models.lang_manager import tr

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:100]}")


dm = DataManager()

# --- 1. delete_group with a transiently locked file / 文件被瞬时占用时删除分组
g = dm.create_group("占用组", "image")
pngp = os.path.join(TMP, "p.png")
Image.new("RGB", (40, 40), (9, 9, 9)).save(pngp)
dm.import_emoji(g, pngp, auto_convert=False)
rows = dm.get_emojis_by_group(g)
stored = os.path.join(dm.data_dir, "emojis", "占用组", rows[0]["filename"])


class _LockAndRelease:
    # holds the file for ~300 ms, then releases (delete_group retries) /
    # 持住文件约 300ms 后释放（delete_group 会重试）
    def __enter__(self):
        import threading
        self._f = open(stored, "rb")

        def release():
            import time
            time.sleep(0.3)
            self._f.close()
        threading.Thread(target=release, daemon=True).start()

    def __exit__(self, *a):
        pass


with _LockAndRelease():
    ok = dm.delete_group(g)
check("A 文件瞬时占用时删除不抛异常", ok, f"ok={ok}")
check("A2 DB 分组已删", dm.get_group(g) is None)
check("A3 文件夹最终已删除", not os.path.isdir(os.path.join(dm.data_dir, "emojis", "占用组")))

# --- 2. show/hide emoji name / 显示/隐藏表情包名称
g2 = dm.create_group("名称组", "image")
dm.import_emoji(g2, pngp, auto_convert=False)
emoji = dm.get_emojis_by_group(g2)[0]

card_on = EmojiItem(emoji, dm, show_name=True)
check("B 显示名称时创建 name_label", hasattr(card_on, "_name_label"))
check("B2 显示名称时高度 122", card_on.height() == EmojiItem.CARD_SIZE + EmojiItem.NAME_AREA,
      card_on.height())

card_off = EmojiItem(emoji, dm, show_name=False)
check("C 隐藏名称时无 name_label", not hasattr(card_off, "_name_label"),
      hasattr(card_off, "_name_label"))
check("C2 隐藏名称时高度 100", card_off.height() == EmojiItem.CARD_SIZE,
      card_off.height())
check("C3 card_height 静态方法一致",
      EmojiItem.card_height(True) == 122 and EmojiItem.card_height(False) == 100)

# grid passes the setting into created cards and layout heights
grid = EmojiGridWidget()
grid.set_data_manager(dm)
grid.current_group_id = g2
grid._show_emoji_name = False
grid._data = dm.get_emojis_by_group(g2)
rects, _tw, th, _info = grid._masonry_layout_data(400)
# card row height = card_height(False) + spacing / 行高 = 矮卡高 + 间距
card_h = EmojiItem.card_height(False)
check("D 布局使用矮高度", th <= (card_h + 8) * 2, f"th={th}")

# --- applying the setting must rebuild reused cards immediately / 应用设置后复用卡立即重建
from PySide6.QtWidgets import QScrollArea, QWidget

host2 = QWidget()
host2.data_manager = dm
host2.resize(600, 600)
scroll2 = QScrollArea(host2)
scroll2.resize(600, 600)
scroll2.setWidgetResizable(True)
grid2 = EmojiGridWidget()
grid2.set_data_manager(dm)
scroll2.setWidget(grid2)
grid2._ensure_scroll_connected()
grid2.current_group_id = g2
grid2._show_emoji_name = True
grid2.load_emojis(dm.get_emojis_by_group(g2), "image")
app.processEvents()
check("E 初始卡显示名称", len(grid2._items) > 0
      and all(c._show_name for c in grid2._items), len(grid2._items))
# toggle the setting and reload (what settings apply does) / 切换设置并重载
grid2._show_emoji_name = False
grid2.load_emojis(dm.get_emojis_by_group(g2), "image")
app.processEvents()
check("E2 应用后立即重建为无名称", len(grid2._items) > 0
      and all(not c._show_name for c in grid2._items)
      and all(not hasattr(c, "_name_label") for c in grid2._items),
      f"items={len(grid2._items)}")
if grid2._items:
    c = grid2._items[0]
    check("E3 无名称卡高度 100", c.height() == 100, c.height())
    # after activating the layout, top gap == bottom gap (centered) /
    # 布局激活后上间距 == 下间距（居中）
    c.layout().activate()
    app.processEvents()
    tl = c._thumb_label
    top = tl.geometry().y()
    bottom = c.height() - (top + tl.height())
    check("E4 缩略图上下间距相等", abs(top - bottom) <= 2,
          f"top={top} bottom={bottom}")

# translation key exists / 翻译键存在
check("F 翻译键存在", tr("show_emoji_name") != "show_emoji_name")

# settings dialog carries the checkbox / 设置对话框携带复选框
from app.widgets.settings_dialog import SettingsDialog
dlg = SettingsDialog(show_emoji_name=False)
check("F 设置复选框反映配置", dlg.show_emoji_name() is False)
dlg._cb_show_name.setChecked(True)
check("F2 getter 跟随勾选", dlg.show_emoji_name() is True)
dlg.deleteLater()

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n名称隐藏/删除容错验证: {n_pass}/{len(RES)} 通过")
try:
    dm._conn.close()
except Exception:
    pass
import os as _os
_os._exit(0 if n_pass == len(RES) else 1)
