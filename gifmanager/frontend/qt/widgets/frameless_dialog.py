"""Frameless dialog base: drag + rounded corners
无边框对话框基类：拖动 + 圆角"""
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QDialog

from gifmanager.platform import window as window_platform


class FramelessDialog(QDialog):
    # Shared frameless-window behavior for small dialogs: title-bar drag via
    # mouse events, and a rounded-corner request forwarded through the platform
    # layer so this module no longer imports `ctypes` or tests `sys.platform`.
    # 无边框小对话框共用行为：鼠标拖动 + 经平台层转发的圆角请求，因此本模块不再
    # 导入 `ctypes`，也不再判断 `sys.platform`。

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dragging = False
        self._drag_start = QPoint()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )
        self._apply_rounded()

    def _apply_rounded(self):
        # The Windows backend issues the DWM call, macOS reports success (its
        # window server rounds regardless) and every other backend returns
        # False, which simply keeps square corners.
        # Windows 后端发起 DWM 调用，macOS 报告成功（其窗口服务器本就会加圆角），
        # 其他后端返回 False，即保持直角。
        window_platform().apply_rounded_corners(int(self.winId()))

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
