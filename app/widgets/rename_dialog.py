"""Rename dialog (frameless, theme-aware): localised OK/Cancel buttons and a
compact size matching the group-rename window. The prompt/input area uses a
transparent background so it is not rendered as a dark box (the default
QLineEdit palette base and QDialog background are too dark in dark theme).
重命名对话框（无边框、主题适配）：本地化的确定/取消按钮，紧凑尺寸与分组重命名一致。
提示/输入区使用透明背景，避免显示为黑框（深色主题下默认 QLineEdit 与 QDialog
背景过暗）。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QApplication,
)

from app.models.lang_manager import tr
from app.widgets.frameless_dialog import FramelessDialog


def _is_light(widget=None):
    # The active theme is stored on the main window's `_theme` attribute; walk
    # up the parent chain to find it (default dark). If no parent exposes
    # `_theme` (e.g. a dialog created from a non-MainWindow parent), fall back
    # to the background colour of the application/effective palette so light
    # mode still renders readable text. QDialog background is set via the app
    # stylesheet, which does NOT update the Qt palette Window role — so read
    # the QSS QDialog background as a last resort.
    # 当前主题存于主窗口的 `_theme` 属性；沿父链向上查找（默认深色）。若父链
    # 无组件暴露 `_theme`（如从非 MainWindow 父组件弹出的对话框），回退到应用/
    # 生效调色板背景色，保证亮色模式文字仍可读。QDialog 背景由应用样式表设置，
    # 不会更新 Qt 调色板 Window 角色——因此最后回退读取 QSS 的 QDialog 背景。
    w = widget
    while w is not None:
        theme = getattr(w, "_theme", None)
        if theme in ("light", "dark"):
            return theme == "light"
        w = w.parent()
    # Fallback 1: the app stylesheet QDialog background is authoritative
    # (the app QSS sets QDialog background via stylesheet, which does NOT
    # update the Qt palette Window role). Light QSS uses #FFFFFF, dark #252525.
    # / 回退 1：应用样式表 QDialog 背景是权威来源（应用 QSS 用样式表设置
    # QDialog 背景，不会更新 Qt 调色板 Window 角色）。亮色用 #FFFFFF，深色 #252525。
    try:
        qss = QApplication.instance().styleSheet() or ""
        idx = qss.find("QDialog {")
        if idx < 0:
            idx = qss.find("QDialog{")
        if idx >= 0:
            # Read only the QDialog block (up to the next closing brace) so a
            # following #FFFFFF (e.g. a titleLabel text colour) is not taken
            # as the dialog background. / 仅读取 QDialog 块（到下一个花括号），
            # 避免把紧随其后的 #FFFFFF（如 titleLabel 文字色）误判为背景色。
            end = qss.find("}", idx)
            if end < 0:
                end = idx + 200
            block = qss[idx:end]
            if "#FFFFFF" in block or "#ffffff" in block:
                return True
            if "#252525" in block or "#1E1E1E" in block or "#1e1e1e" in block:
                return False
    except Exception:
        pass
    # Fallback 2: effective palette window lightness (reflects a plain light
    # background when no styled theme is present) / 回退 2：生效调色板窗口亮度
    try:
        from PySide6.QtGui import QPalette
        target = widget if widget is not None else QApplication.instance()
        lum = target.palette().color(QPalette.ColorRole.Window).lightness()
        if lum > 180:
            return True
        if lum < 100:
            return False
    except Exception:
        pass
    return False


class RenameDialog(FramelessDialog):

    def __init__(self, current_name="", parent=None, title=None):
        super().__init__(parent)
        self.setWindowTitle(title or tr("rename"))
        # Compact size matching the (previous) group-rename QInputDialog window
        # / 紧凑尺寸，与原先分组重命名 QInputDialog 窗口一致
        self.setFixedSize(300, 150)
        self._current_name = current_name
        self._title = title or tr("rename")
        self._light = _is_light(self)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        # Tighter spacing than before: the reclaimed height goes to the input
        # box, whose text was clipped at the bottom when the editor was only
        # 28 px tall (5 px vertical padding left a 16 px content area for an
        # ~18 px line). / 间距比之前紧凑：省下的高度留给输入框——此前编辑框
        # 仅 28px 高，上下 5px 内边距只剩 16px 内容区，而字体行高约 18px，
        # 文字底部被裁切。
        layout.setSpacing(8)
        layout.setContentsMargins(20, 12, 20, 14)

        # Pick readable colours per theme / 按主题选择可读颜色
        if self._light:
            title_color, prompt_color, text_color, border_color = "#222222", "#666666", "#1E1E1E", "#D8D8D8"
        else:
            title_color, prompt_color, text_color, border_color = "#FFFFFF", "#999999", "#E0E0E0", "#3A3A3A"

        title_bar = QHBoxLayout()
        title = QLabel(self._title)
        title.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: %s;" % title_color)
        title_bar.addWidget(title)
        title_bar.addStretch()
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(24, 24)
        btn_close.setFlat(True)
        btn_close.clicked.connect(self.reject)
        title_bar.addWidget(btn_close)
        layout.addLayout(title_bar)

        prompt = QLabel(tr("new_name"))
        prompt.setStyleSheet(
            "background: transparent; color: %s; font-size: 12px;" % prompt_color)
        layout.addWidget(prompt)

        # Transparent background so the input does not appear as a dark/black
        # box. The vertical padding is kept small and an explicit min-height
        # guarantees the content area is taller than the font line, so the
        # glyphs are no longer clipped / shifted downward.
        # 透明背景，避免输入框显示为深色/黑框。上下内边距保持较小，并显式设置
        # min-height 保证内容区高于字体行高，文字不再被裁切或偏下。
        self._editor = QLineEdit(self._current_name)
        self._editor.setMinimumHeight(32)
        self._editor.setStyleSheet(
            "QLineEdit { background: transparent;"
            " border: 1px solid %s; border-radius: 6px;"
            " color: %s; padding: 0 6px; min-height: 30px;"
            " selection-background-color: #1677FF; }" % (border_color, text_color)
        )
        self._editor.setFocus()
        self._editor.selectAll()
        layout.addWidget(self._editor)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_ok = QPushButton(tr("ok"))
        btn_ok.setFixedWidth(80)
        btn_ok.clicked.connect(self.accept)
        btn_row.addWidget(btn_ok)
        btn_cancel = QPushButton(tr("cancel"))
        btn_cancel.setFixedWidth(80)
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        # Enter confirms / Enter 确认
        self._editor.returnPressed.connect(self.accept)

    def new_name(self):
        return self._editor.text().strip()

    def showEvent(self, event):
        # Re-select the whole name once the dialog is actually shown: selecting
        # in the constructor is normally enough, but showing/focusing the
        # dialog can clear the selection on some platforms, and rename is
        # always a full-text edit. / 对话框真正显示后再次全选：构造函数里选中
        # 通常已足够，但某些平台在显示/获取焦点时会清掉选择，而重命名总是对
        # 整段文字修改。
        super().showEvent(event)
        self._editor.setFocus()
        self._editor.selectAll()
