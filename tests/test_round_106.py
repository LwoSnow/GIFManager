"""Regression for this round's fixes:
1. the GPU acceleration switch survives OK -> reopen (it was never passed to
   the dialog, so it always came back OFF)
2. the settings icon comes from setting.svg and is tinted per theme
3. wrapping hints are never vertically squeezed (last line cut off)
4. with parallel rendering on, every VISIBLE animated GIF plays (the play cap
   used to leave the topmost cards static)
本轮修复回归：
1. GPU 加速开关在确定→重新打开后保持（此前根本没传给对话框，故总是回到关闭）
2. 设置图标取自 setting.svg 且随主题着色
3. 换行提示不会被上下挤压（最后一行被切掉）
4. 开启并行渲染时，所有"可见"动图都会播放（此前的播放上限会让最上面的卡片静止）
"""
import collections
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import logging
logging.disable(logging.CRITICAL)

TMP = tempfile.mkdtemp(prefix="gifmgr_round_")
import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PIL import Image
from PySide6.QtWidgets import (QApplication, QScrollArea, QLabel)
from PySide6.QtCore import Qt, QSettings

# NOTE: QSettings.setDefaultFormat(IniFormat) + setPath() do NOT isolate
# anything -- QSettings("Org","App") keeps using the native registry format, so
# this test used to write its values straight into the user's real key.
# isolate_all() redirects MainWindow's settings factory; the probe below must
# therefore be built from the SAME throwaway INI, not from the real namespace.
# 注意：QSettings.setDefaultFormat(IniFormat) + setPath() 并不能隔离——
# QSettings("Org","App") 仍然使用原生注册表格式，本测试以前会把取值直接写进
# 用户真实键。isolate_all() 重定向 MainWindow 的设置工厂；下面的 _probe 因此
# 必须基于同一个临时 INI 构造，而不是真实命名空间。
from tests._iso import isolate_settings, isolate_gpu_pref, drain_and_exit  # noqa: E402

_ISO_INI = isolate_settings()
isolate_gpu_pref()

app = QApplication(sys.argv)
# Make the run deterministic: clear the GPU keys / 保证可重复：清掉 GPU 键
_probe = QSettings(_ISO_INI, QSettings.Format.IniFormat)
_probe.setValue("gpu_accel", False)
_probe.setValue("gpu_render", False)
_probe.sync()

RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:110]}")


from app.models.data_manager import DataManager
from app.widgets.emoji_item import EmojiItem
from app.widgets.emoji_grid import EmojiGridWidget
from app.widgets.settings_dialog import SettingsDialog
import app.main_window as mw


def settle(sec=0.35):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


# --- 1. GPU switch round-trip through MainWindow ------------------------
w = mw.MainWindow()
w.data_manager = DataManager()
w.show()
settle(0.2)
check("默认 GPU 加速关闭", w._gpu_accel is False, w._gpu_accel)
# simulate the user enabling it in the dialog and pressing OK
dlg = SettingsDialog(gpu_accel=True, gpu_pref=2,
                     gpu_adapters=["NVIDIA GeForce RTX 3050 Laptop GPU"])
w._settings_dialog = dlg
w._apply_settings(dlg)
w._settings_dialog = None
dlg.deleteLater()
settle(0.1)
check("确定后主窗口记录为开启", w._gpu_accel is True, w._gpu_accel)
check("确定后已写入设置", bool(w._settings.value("gpu_accel", None, type=bool)),
      w._settings.value("gpu_accel"))
# reopening must show it ON (this was the reported bug)
dlg2 = SettingsDialog(gpu_accel=w._gpu_accel, gpu_pref=w._gpu_pref,
                      gpu_adapters=w._gpu_adapters)
check("重新打开显示为开启", dlg2.gpu_accel() is True, dlg2.gpu_accel())
dlg2.close()

# --- 2. settings icon from setting.svg, tinted per theme ---------------
# The icon is rendered at 75% of ICON_PX (16 px) while the button stays 32x32,
# so the coverage-based alpha test must tolerate antialiasing: a downscaled
# line-art SVG never reaches full opacity at 16 px (measured max alpha 192).
# 图标按 ICON_PX 的 75%（16px）渲染，而按钮仍为 32x32，因此基于覆盖率的
# alpha 判定必须容忍抗锯齿：缩小的线条型 SVG 在 16px 下不会达到完全不透明
# （实测最大 alpha 为 192）。
icons = {}
for th in ("dark", "light"):
    w._theme = th
    w._apply_theme()
    settle(0.1)
    pm = w.btn_settings.icon().pixmap(22, 22)
    im = pm.toImage()
    hist = collections.Counter()
    for y in range(im.height()):
        for x in range(im.width()):
            c = im.pixelColor(x, y)
            if c.alpha() > 10:
                hist[(c.red(), c.green(), c.blue())] += 1
    icons[th] = hist.most_common(1)[0][0] if hist else None
check("图标已加载（非空）", icons["dark"] is not None, icons)
check("深色主题图标为浅色", icons["dark"] == (224, 224, 224), icons["dark"])
check("亮色主题图标为深色", icons["light"] == (51, 51, 51), icons["light"])
check("按钮不再显示齿轮字符", w.btn_settings.text() == "",
      repr(w.btn_settings.text()))
# Icon shrunk to 75% of ICON_PX; button area unchanged / 图标缩小到 ICON_PX
# 的 75%，按钮面积不变
from app.main_window import MainWindow as _MW  # noqa: E402
_want_icon = int(_MW.ICON_PX * 0.75)
check("图标尺寸为 ICON_PX 的 75%",
      w.btn_settings.iconSize().width() == _want_icon
      and w.btn_settings.iconSize().height() == _want_icon,
      f"iconSize={w.btn_settings.iconSize()} want={_want_icon}")
check("按钮面积不变（仍为 32x32）",
      w.btn_settings.width() == 32 and w.btn_settings.height() == 32,
      f"{w.btn_settings.width()}x{w.btn_settings.height()}")
check("图标 pixmap 实际按 75% 渲染",
      pm.width() == _want_icon and pm.height() == _want_icon,
      f"pixmap={pm.size()} want={_want_icon}")

# --- 3. wrapping hints are not vertically squeezed ---------------------
sd = SettingsDialog(gif_render_mode="manual", gif_render_count=11,
                    gpu_accel=True, gpu_pref=2,
                    gpu_adapters=["NVIDIA GeForce RTX 3050 Laptop GPU"])
sd.show()
sd._cat_list.setCurrentRow(4)
settle(0.3)
sc = sd._stack.widget(4)
inner = sc.widget()
squeezed = []
for lab in inner.findChildren(QLabel):
    if not lab.wordWrap() or not lab.text():
        continue
    need = lab.heightForWidth(lab.width()) if lab.width() > 0 else 0
    if need > 0 and lab.height() < need:
        squeezed.append((lab.height(), need, lab.text()[:24]))
check("换行提示未被上下挤压", not squeezed, squeezed[:2])
sd.close()

# --- 4. parallel rendering plays every visible GIF ---------------------
dm = DataManager()
gid = dm.create_group("G", "image")
for i in range(24):
    p = os.path.join(TMP, f"a{i}.gif")
    # Distinct RGB colours: single-colour palette GIFs save to identical bytes
    # and would be de-duplicated into one file.
    # 使用不同的 RGB 颜色：单色调色板 GIF 会存成相同字节，会被去重成一个文件。
    frames = [Image.new("RGB", (48, 48),
                        ((i * 37 + j * 11) % 256, (i * 53) % 256, 180))
              for j in range(3)]
    frames[0].save(p, save_all=True, append_images=frames[1:],
                   duration=80, loop=0)
    dm.import_emoji(gid, p, auto_convert=False)
check("测试用动图数量正确",
      len(dm.get_emojis_by_group(gid)) == 24,
      len(dm.get_emojis_by_group(gid)))
sa = QScrollArea()
sa.resize(420, 300)
sa.setWidgetResizable(True)
grid = EmojiGridWidget()
grid.set_data_manager(dm)
grid.current_group_id = gid
sa.setWidget(grid)
sa.show()
grid.load_emojis(dm.get_emojis_by_group(gid), "image")
settle(0.4)
gifs = [c for c in grid._items if c.is_gif()]
check("有多个可见动图可测", len(gifs) >= 2, len(gifs))
EmojiItem.set_parallel_render(True)
grid._gif_limit = 2            # deliberately tiny cap
# Measured immediately after the call: lazy card churn changes the card set
# shortly afterwards, which would make the count flaky.
# 调用后立即读取：懒加载卡片随后会变动，否则计数不稳定。
grid._update_visible_gifs(allow_decode=True)
playing_parallel = len(grid._playing_gifs)
# Same band filter the grid uses (viewport +/-150 px) / 使用与网格相同的可见带
# 过滤（视口上下各 150px）
_sb = sa.verticalScrollBar()
_y0 = _sb.value() - 150
_y1 = _sb.value() + sa.viewport().height() + 150
_in_band = [c for c in grid._items if c.is_gif()
            and not (c.geometry().y() > _y1
                     or c.geometry().y() + c.geometry().height() < _y0)]
EmojiItem.set_parallel_render(False)
grid._update_visible_gifs(allow_decode=True)
playing_serial = len(grid._playing_gifs)
check("并行模式下所有可见动图都在播放",
      playing_parallel == len(_in_band) and playing_parallel > playing_serial,
      f"in_band={len(_in_band)} parallel={playing_parallel} "
      f"serial={playing_serial}")
EmojiItem.set_parallel_render(False)
w.close()

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n本轮修复验证: {n_pass}/{len(RES)} 通过")
sys.stdout.flush()
drain_and_exit(0 if n_pass == len(RES) else 1)
