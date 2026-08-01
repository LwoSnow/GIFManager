"""删除重复表情对话框 — 多选分组 + 全选（仅"全部"视图使用）"""
import sys
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QCheckBox, QDialogButtonBox,
)
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QMouseEvent

from app.models.lang_manager import tr


class DeleteCopiesDialog(QDialog):
    """列出同一表情的所有分组副本，多选要删除的项"""

    def __init__(self, copies, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("delete_copies_title"))
        self.setFixedSize(380, 420)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )
        self._copies = copies
        self._items = []  # (QListWidgetItem, emoji_id)
        self._dragging = False
        self._drag_start = QPoint()

        self._setup_ui()
        self._apply_rounded()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 14, 20, 16)

        # 标题栏
        title_bar = QHBoxLayout()
        title = QLabel(tr("delete_copies_title"))
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #FFF;")
        title_bar.addWidget(title)
        title_bar.addStretch()
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(26, 26)
        btn_close.setFlat(True)
        btn_close.clicked.connect(self.reject)
        title_bar.addWidget(btn_close)
        layout.addLayout(title_bar)

        # 提示文字
        prompt = QLabel(tr("delete_copies_prompt", count=len(self._copies)))
        prompt.setStyleSheet("color: #999; font-size: 12px;")
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        # 全选/取消全选
        select_row = QHBoxLayout()
        self._btn_all = QPushButton(tr("select_all_btn"))
        self._btn_all.setFixedHeight(26)
        self._btn_all.setStyleSheet(
            "QPushButton { background:#2B2B2B; border:1px solid #3A3A3A;"
            " border-radius:4px; color:#CCC; padding:2px 12px; }"
            "QPushButton:hover { background:#353535; }"
        )
        self._btn_all.clicked.connect(lambda: self._set_all_checked(True))
        self._btn_none = QPushButton(tr("select_none_btn"))
        self._btn_none.setFixedHeight(26)
        self._btn_none.setStyleSheet(self._btn_all.styleSheet())
        self._btn_none.clicked.connect(lambda: self._set_all_checked(False))
        select_row.addWidget(self._btn_all)
        select_row.addWidget(self._btn_none)
        select_row.addStretch()
        layout.addLayout(select_row)

        # 分组复选列表
        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget { background:#2B2B2B; border:1px solid #3A3A3A;"
            " border-radius:6px; color:#CCC; }"
            "QListWidget::item { padding:6px 8px; }"
            "QListWidget::item:selected { background:#1A3A5C; }"
        )
        for c in self._copies:
            item = QListWidgetItem()
            cb = QCheckBox(f"{c.get('group_name','?')}（{c.get('original_name','')}）")
            cb.setStyleSheet("color:#E0E0E0; background:transparent;")
            item.setSizeHint(cb.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, cb)
            self._items.append((item, c["id"], cb))
        layout.addWidget(self._list, 1)

        # 按钮
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.button(QDialogButtonBox.StandardButton.Ok).setText(tr("delete"))
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _set_all_checked(self, checked):
        for _item, _eid, cb in self._items:
            cb.setChecked(checked)

    def selected_emojis(self):
        """返回用户勾选要删除的 emoji id 列表"""
        return [eid for _item, eid, cb in self._items if cb.isChecked()]

    def _apply_rounded(self):
        if sys.platform != "win32":
            return
        try:
            import ctypes
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                int(self.winId()), 33,
                ctypes.byref(ctypes.c_int(2)),
                ctypes.sizeof(ctypes.c_int),
            )
        except Exception:
            pass

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            delta = event.globalPosition().toPoint() - self._drag_start
            self.move(self.pos() + delta)
            self._drag_start = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._dragging = False
        super().mouseReleaseEvent(event)
