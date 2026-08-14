"""Offscreen smoke test: MainWindow instantiates, loads settings, and a
group switch + import path runs without exceptions. Isolated data dir.
离屏冒烟测试：MainWindow 可实例化、加载设置，分组切换与导入路径无异常。
数据隔离。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_smoke_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

from PIL import Image, ImageDraw

import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication
from app.main_window import MainWindow
from app.utils import gif_player

app = QApplication(sys.argv)
w = MainWindow()
w.show()
app.processEvents()

RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:100]}")


check("A 主窗口实例化", w is not None and w.isVisible())
check("B 数据管理器就绪", w.data_manager is not None)

# create a group + import a gif + a png (auto-convert) / 建组并导入 gif 与 png
gid = w.data_manager.create_group("冒烟组", "image")
check("C 建组", gid is not None)

gifp = os.path.join(TMP, "a.gif")
frames = []
for color in ("red", "blue"):
    im = Image.new("RGBA", (80, 60), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([5, 5, 75, 55], fill=color)
    frames.append(im)
frames[0].save(gifp, save_all=True, append_images=frames[1:],
               duration=100, loop=0, disposal=2)

pngp = os.path.join(TMP, "b.png")
im = Image.new("RGB", (40, 40), (0, 128, 255))
im.save(pngp)

w.group_list.select_group(gid)
app.processEvents()
imported, duplicated = w.data_manager.import_emojis_batch(
    gid, [gifp, pngp], workers=2, auto_convert=True)
check("D 批量导入(转gif)", imported == 2, f"imported={imported} dup={duplicated}")

w._refresh_emoji_grid()
app.processEvents()
check("E 网格加载", len(w.emoji_grid._data) == 2, len(w.emoji_grid._data))

# switch to All and back / 切换到全部再切回
w.group_list.select_all_group()
app.processEvents()
w.group_list.select_group(gid)
app.processEvents()
check("F 分组切换无异常", True)

# copy to clipboard (send) / 复制到剪贴板（发送）
emojis = w.data_manager.get_emojis_by_group(gid)
if emojis:
    ok = w.data_manager.copy_to_clipboard(emojis[0], mode=0)
    check("G 复制到剪贴板", ok)

# layout cache is exercised / 布局缓存被使用
w.emoji_grid._masonry_layout_data(w.emoji_grid._usable_width())
w.emoji_grid._masonry_layout_data(w.emoji_grid._usable_width())
check("H 布局缓存命中", w.emoji_grid._layout_cache is not None)

# settings dialog opens / 设置对话框可打开
from app.widgets.settings_dialog import SettingsDialog
dlg = SettingsDialog(parent=w)
dlg.refresh_translations()
check("I 设置对话框 + 翻译刷新", True)
dlg.deleteLater()

w._real_quit()
app.processEvents()

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n冒烟验证: {n_pass}/{len(RES)} 通过")
gif_player.shutdown()
import os as _os
_os._exit(0 if n_pass == len(RES) else 1)
