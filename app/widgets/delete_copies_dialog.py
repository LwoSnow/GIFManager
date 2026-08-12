"""Duplicate emoji removal (All)
重复表情删除（All）"""
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QCheckBox, QDialogButtonBox,
)
from PySide6.QtCore import Qt

from app.models.lang_manager import tr
from app.widgets.frameless_dialog import FramelessDialog


class DeleteCopiesDialog(FramelessDialog):

    def __init__(self, copies, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("delete_copies_title"))
        self.setFixedSize(380, 420)
        self._copies = copies
        self._items = []  # (QListWidgetItem, emoji_id)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 14, 20, 16)

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

        prompt = QLabel(tr("delete_copies_prompt", count=len(self._copies)))
        prompt.setStyleSheet("color: #999; font-size: 12px;")
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

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

        # Group check list
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
            gname = c.get("group_name", "?")
            oname = c.get("original_name", "")
            cb = QCheckBox(f"{gname}（{oname}）")
            cb.setStyleSheet("color:#E0E0E0; background:transparent;")
            item.setSizeHint(cb.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, cb)
            self._items.append((item, c["id"], cb))
        layout.addWidget(self._list, 1)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.button(QDialogButtonBox.StandardButton.Ok).setText(tr("delete"))
        btn_box.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("cancel"))
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _set_all_checked(self, checked):
        for _item, _eid, cb in self._items:
            cb.setChecked(checked)

    def selected_emojis(self):
        # Returns the list of emoji ids that the user checked to delete
        # 返回用户勾选要删除的 emoji id 列表
        return [eid for _item, eid, cb in self._items if cb.isChecked()]
