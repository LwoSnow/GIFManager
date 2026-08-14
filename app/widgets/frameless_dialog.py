"""Frameless dialog base: drag + rounded corners
无边框对话框基类：拖动 + 圆角"""
import ctypes
import sys
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QDialog


class FramelessDialog(QDialog):
    # Shared frameless-window behavior for small dialogs:
    # title-bar drag via mouse events and Windows DWM rounded corners.
    # 无边框小对话框共用行为：鼠标拖动 + Windows DWM 圆角

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dragging = False
        self._drag_start = QPoint()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )
        self._apply_rounded()

    def _apply_rounded(self):
        if sys.platform != "win32":
            return
        try:
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
