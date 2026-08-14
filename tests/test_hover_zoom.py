"""Regression for hover-zoom refinements:
1. the overlay scales by the IMAGE aspect ratio, not the card shape
2. a master switch (settings) can disable the hover preview entirely
3. the zoom spinbox is compact (no arrows, percent sign outside)
悬停放大改进的回归：
1. 浮层按图片宽高比缩放（而非卡片形状）
2. 设置总开关可完全关闭悬停预览
3. 倍数输入框紧凑（无箭头、百分号在框外）"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_zoom2_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

from PIL import Image

import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication, QAbstractSpinBox
from PySide6.QtGui import QPixmap, QImage, QColor
from app.models.data_manager import DataManager
from app.widgets.emoji_item import EmojiItem
from app.widgets.settings_dialog import SettingsDialog
from app.models.lang_manager import tr

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:100]}")


class _DM:
    def emoji_filepath(self, e):
        return None


emoji = {"id": 1, "filename": "x.gif", "group_id": 1,
         "original_name": "名字", "text_content": ""}

# --- 1. scale by image aspect ratio / 按图片宽高比缩放
card = EmojiItem(emoji, _DM(), show_name=False, hover_zoom=1.15,
                 hover_enabled=True)
card.show()
app.processEvents()
# a 80x60 (4:3) image / 80x60（4:3）图片
img = QImage(80, 60, QImage.Format.Format_RGB32)
img.fill(QColor(10, 200, 30))
pix = QPixmap.fromImage(img)
card._thumb_label.setPixmap(pix)
card._show_hover_zoom()
check("A 浮层可见", card._hover_layer is not None and card._hover_layer.isVisible())
w, h = card._hover_layer.width(), card._hover_layer.height()
# 80*1.15=92, 60*1.15=69 -> 4:3 preserved / 保持 4:3 宽高比
check("A2 尺寸按图片比例 (92x69)", w == 92 and h == 69, f"{w}x{h}")
check("A3 宽高比保持", abs(w / h - 80 / 60) < 0.05, f"{w}/{h}")
card._hide_hover_zoom()

# --- 2. master switch disables the preview / 总开关关闭预览
card_off = EmojiItem(emoji, _DM(), hover_zoom=1.3, hover_enabled=False)
card_off._thumb_label.setPixmap(QPixmap(40, 40))
card_off._show_hover_zoom()
check("B 关闭总开关不显示浮层", card_off._hover_layer is None
      or not card_off._hover_layer.isVisible())

# --- 3. settings UI / 设置界面
dlg = SettingsDialog(hover_zoom=1.2, hover_preview_enabled=True)
check("C 倍数回显 120%", dlg._spin_zoom.value() == 120, dlg._spin_zoom.value())
check("C2 无上下箭头按钮", dlg._spin_zoom.buttonSymbols() ==
      QAbstractSpinBox.ButtonSymbols.NoButtons)
check("C3 无内嵌百分号", "%" not in dlg._spin_zoom.suffix(),
      repr(dlg._spin_zoom.suffix()))
check("C4 百分号在框外", dlg._label_zoom_pct.text() == "%")
check("C5 倍数框较窄", dlg._spin_zoom.width() <= 80, dlg._spin_zoom.width())
# toggle the master switch -> spinbox disabled / 关总开关 → 倍数框禁用
dlg._cb_hover_preview.setChecked(False)
check("C6 关闭总开关禁用倍数框", not dlg._spin_zoom.isEnabled())
dlg._cb_hover_preview.setChecked(True)
check("C7 重新开启启用倍数框", dlg._spin_zoom.isEnabled())
# getters / 取值器
dlg._spin_zoom.setValue(150)
check("C8 getter zoom=1.5", abs(dlg.hover_zoom() - 1.5) < 1e-6)
check("C9 getter enabled", dlg.hover_preview_enabled() is True)
check("D 翻译键存在", tr("hover_preview_enable") != "hover_preview_enable")
dlg.deleteLater()

# --- 4. neighbor cards hidden while the overlay overlaps them / 悬停时隐藏被浮层覆盖的相邻卡
from app.widgets.emoji_grid import EmojiGridWidget

host = EmojiGridWidget()
host.resize(600, 400)
host.show()
host._items = []
cardA = EmojiItem(emoji, _DM(), show_name=False, hover_zoom=1.5)
cardB = EmojiItem(emoji, _DM(), show_name=False, hover_zoom=1.5)
cardC = EmojiItem(emoji, _DM(), show_name=False, hover_zoom=1.5)
for c in (cardA, cardB, cardC):
    c.setParent(host)
    host._items.append(c)
    c.show()
cardA.setGeometry(10, 10, 100, 100)
cardB.setGeometry(30, 30, 100, 100)  # overlapping the enlarged A / 与放大后的 A 相交
cardC.setGeometry(400, 10, 100, 100)  # far away / 远处
app.processEvents()
img = QImage(80, 80, QImage.Format.Format_RGB32)
img.fill(QColor(255, 0, 0))
pix = QPixmap.fromImage(img)
cardA._thumb_label.setPixmap(pix)
cardA._show_hover_zoom()
app.processEvents()
# enlarged A is 120x120 centered at (10,10) -> covers card B / 放大后覆盖 B
check("E 覆盖相邻卡时隐藏 B", not cardB.isVisible())
check("E3 远处卡不隐藏", cardC.isVisible())
cardA._hide_hover_zoom()
app.processEvents()
check("E2 离开后恢复 B", cardB.isVisible())

# --- 5. toggling the master switch applies to existing cards immediately /
# 切换总开关立即作用于已有卡片（无需切换分组）
cardA._hover_enabled = True
cardA._show_hover_zoom()
app.processEvents()
check("F 初始悬停可见", cardA._hover_layer is not None
      and cardA._hover_layer.isVisible())
# what settings-apply does: update the existing card and hide its overlay /
# 模拟设置应用：更新已有卡并隐藏浮层
cardA._hover_enabled = False
cardA._hide_hover_zoom()
cardA._show_hover_zoom()
check("F2 关闭后立即不显示", cardA._hover_layer is None
      or not cardA._hover_layer.isVisible())

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n悬停放大改进验证: {n_pass}/{len(RES)} 通过")
import os as _os
_os._exit(0 if n_pass == len(RES) else 1)
