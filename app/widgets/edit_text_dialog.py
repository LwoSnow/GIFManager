"""Edit text dialog
文字编辑对话框"""
import sys
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QDialogButtonBox,
)
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QMouseEvent

from app.models.lang_manager import tr


class EditTextDialog(QDialog):

    def __init__(self, current_text="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("edit_text_dialog"))
        self.setFixedSize(400, 300)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )
        self._current_text = current_text
        self._dragging = False
        self._drag_start = QPoint()

        self._setup_ui()
        self._apply_rounded()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 14, 20, 16)

        title_bar = QHBoxLayout()
        title = QLabel(tr("edit_text_dialog"))
        title.setStyleSheet("font-size: 15px; font-weight: bold; color: #FFF;")
        title_bar.addWidget(title)
        title_bar.addStretch()
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(26, 26)
        btn_close.setFlat(True)
        btn_close.clicked.connect(self.reject)
        title_bar.addWidget(btn_close)
        layout.addLayout(title_bar)

        prompt = QLabel(tr("edit_text_prompt"))
        prompt.setStyleSheet("color: #999; font-size: 12px;")
        layout.addWidget(prompt)

        self._editor = QPlainTextEdit()
        self._editor.setPlainText(self._current_text)
        self._editor.setStyleSheet(
            "QPlainTextEdit { background:#2B2B2B; border:1px solid #3A3A3A;"
            " border-radius:6px; color:#E0E0E0; padding:8px;"
            " selection-background-color:#1677FF; }"
        )
        layout.addWidget(self._editor, 1)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def text(self):
        return self._editor.toPlainText().strip()

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
