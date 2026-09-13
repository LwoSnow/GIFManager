"""Verify the long-name marquee renders correctly: static elide with "…",
hovering scrolls the name (text changes across ticks, centered alignment),
and leaving stops. / 验证长名称跑马灯正确渲染：静态截断加省略号，悬停时滚动
名称（文本逐 tick 变化、居中），离开停止。"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_marq_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)
from tests._iso import drain_and_exit  # noqa: E402

import logging
logging.disable(logging.CRITICAL)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.models.data_manager import DataManager
from app.widgets.emoji_item import EmojiItem
import app.main_window as mw

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:110]}")


class _DM:
    def emoji_filepath(self, e):
        return None


# long name > NAME_CHAR_LIMIT / 长名称超出字符阈值
name = "超长表情包名称用于测试滚动显示功能abcdefghijklmno"
card = EmojiItem({"id": 1, "filename": "x.gif", "group_id": 1,
                  "original_name": name, "text_content": ""},
                 _DM(), show_name=True, hover_zoom=1.2, hover_enabled=True)
card.resize(100, 120)
card.show()
app.processEvents()
# give the card a thumbnail so hover zoom proceeds / 给缩略图使悬停进入
from PySide6.QtGui import QPixmap
card._thumb_label.setPixmap(QPixmap(60, 40))

# 1. static (not hovering): elided with "…" / 非悬停：截断加省略号
check("A 非悬停显示省略号", card._name_label.text().endswith("…"),
      card._name_label.text())
check("A2 非悬停长度受限于字符阈值",
      len(card._name_label.text()) <= EmojiItem.NAME_CHAR_LIMIT + 1,
      len(card._name_label.text()))
check("A3 名称居中", card._name_label.alignment() ==
      Qt.AlignmentFlag.AlignCenter, card._name_label.alignment())

# 2. hover: marquee scrolls (text changes across ticks) / 悬停：滚动文本变化
card._show_hover_zoom()
app.processEvents()
check("B 悬停启动跑马灯", card._name_scroll_timer is not None
      and card._name_scroll_timer.isActive())
seen = set()
for _ in range(30):
    card._tick_name_scroll()
    seen.add(card._name_label.text())
check("B2 跑马灯滚动（多帧文本不同）", len(seen) > 1, len(seen))

# 3. leave: stops and restores full elided name / 离开：停止并恢复截断
card._hide_hover_zoom()
app.processEvents()
check("C 离开停止跑马灯", card._name_scroll_timer is None
      or not card._name_scroll_timer.isActive())
check("C2 离开后恢复省略号", card._name_label.text().endswith("…"),
      card._name_label.text())
card.deleteLater()

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n跑马灯渲染验证: {n_pass}/{len(RES)} 通过")
import os as _os
drain_and_exit(0 if n_pass == len(RES) else 1)
