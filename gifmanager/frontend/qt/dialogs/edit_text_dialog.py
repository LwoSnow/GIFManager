"""Edit text dialog (frameless, theme-aware, localised buttons)
文字编辑对话框（无边框、主题适配、本地化按钮）"""
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit,
)

from gifmanager.core.lang import tr
from gifmanager.frontend.qt.widgets.frameless_dialog import FramelessDialog
from gifmanager.frontend.qt.dialogs.rename_dialog import _is_light


class EditTextDialog(FramelessDialog):

    def __init__(self, current_text="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("edit_text_dialog"))
        self.setFixedSize(400, 300)
        self._current_text = current_text
        self._light = _is_light(self)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 14, 20, 16)

        # Readable colours per theme (the title was hard-coded white, which was
        # invisible in light mode). / 按主题取可读颜色（标题曾硬编码白色，
        # 在亮色模式下看不见）。
        title_color = "#222222" if self._light else "#FFFFFF"
        prompt_color = "#666666" if self._light else "#999999"
        edit_bg = "#FFFFFF" if self._light else "#2B2B2B"
        edit_border = "#D8D8D8" if self._light else "#3A3A3A"
        edit_fg = "#1E1E1E" if self._light else "#E0E0E0"

        title_bar = QHBoxLayout()
        title = QLabel(tr("edit_text_dialog"))
        title.setStyleSheet(
            "font-size: 15px; font-weight: bold; color: %s;" % title_color)
        title_bar.addWidget(title)
        title_bar.addStretch()
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(26, 26)
        btn_close.setFlat(True)
        btn_close.clicked.connect(self.reject)
        title_bar.addWidget(btn_close)
        layout.addLayout(title_bar)

        prompt = QLabel(tr("edit_text_prompt"))
        prompt.setStyleSheet(
            "background: transparent; color: %s; font-size: 12px;"
            % prompt_color)
        layout.addWidget(prompt)

        self._editor = QPlainTextEdit()
        self._editor.setPlainText(self._current_text)
        self._editor.setStyleSheet(
            "QPlainTextEdit { background:%s; border:1px solid %s;"
            " border-radius:6px; color:%s; padding:8px;"
            " selection-background-color:#1677FF; }"
            % (edit_bg, edit_border, edit_fg)
        )
        layout.addWidget(self._editor, 1)

        # Localised OK/Cancel. The stock QDialogButtonBox rendered English
        # "OK"/"Cancel" even in the Chinese UI. / 本地化确定/取消。此前使用
        # 标准 QDialogButtonBox，中文界面下仍显示英文 "OK"/"Cancel"。
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_ok = QPushButton(tr("ok"))
        btn_ok.setFixedWidth(88)
        btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(btn_ok)
        btn_cancel = QPushButton(tr("cancel"))
        btn_cancel.setFixedWidth(88)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        self._editor.setFocus()

    def text(self):
        return self._editor.toPlainText().strip()
