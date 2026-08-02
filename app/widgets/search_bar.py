"""Search bar — QLineEdit with localized context menu
搜索栏 — QLineEdit + 中文右键菜单"""
from PySide6.QtWidgets import QLineEdit, QMenu, QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QContextMenuEvent

from app.models.lang_manager import tr


class SearchBar(QLineEdit):

    def __init__(self):
        super().__init__()
        self.setPlaceholderText(tr("search_placeholder"))
        self.setClearButtonEnabled(True)
        self.setFixedHeight(32)

    def setPlaceholderText(self, text):
        super().setPlaceholderText(text)

    def contextMenuEvent(self, event: QContextMenuEvent):
        menu = self.createStandardContextMenu()
        for action in menu.actions():
            txt = action.text()
            if "Undo" in txt or "&Undo" in txt:
                action.setText(tr("undo"))
            elif "Redo" in txt or "&Redo" in txt:
                action.setText(tr("redo"))
            elif "Cu&t" in txt:
                action.setText(tr("cut"))
            elif "&Copy" in txt:
                action.setText(tr("copy"))
            elif "&Paste" in txt:
                action.setText(tr("paste"))
            elif "Delete" in txt:
                action.setText(tr("delete_text"))
            elif "Select All" in txt or "Select &All" in txt:
                action.setText(tr("select_all"))
        menu.exec(event.globalPos())
