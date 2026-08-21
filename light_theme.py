"""Bright theme style sheet
亮色主题样式表"""

QSS = """
/* ========== 全局 ========== */
QWidget {
    background-color: #F2F3F5;
    color: #333333;
    font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
    font-size: 13px;
}

QMainWindow {
    background-color: #F2F3F5;
}

/* ========== 主工具栏 ========== */
QWidget#mainToolbar {
    background-color: #FFFFFF;
    border-bottom: 1px solid #E2E2E2;
}

/* ========== 搜索栏 ========== */
QLineEdit {
    background-color: #FFFFFF;
    border: 1px solid #D8D8D8;
    border-radius: 16px;
    padding: 6px 12px;
    color: #333333;
    selection-background-color: #1677FF;
}
QLineEdit:focus {
    border-color: #1677FF;
}

/* ========== 按钮 ========== */
QPushButton {
    background-color: #FFFFFF;
    border: 1px solid #D8D8D8;
    border-radius: 6px;
    padding: 6px 16px;
    color: #333333;
}
QPushButton:hover {
    background-color: #E8F1FE;
    border-color: #1677FF;
}
QPushButton:pressed {
    background-color: #D6E4F8;
}
QPushButton[flat="true"] {
    background-color: transparent;
    border: none;
    padding: 4px 8px;
}

/* ========== 滚动区域 ========== */
QScrollArea {
    background-color: #F2F3F5;
    border: none;
}
QScrollBar:horizontal {
    background: transparent;
    height: 6px;
}
QScrollBar::handle:horizontal {
    background: #C8C8C8;
    border-radius: 3px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover {
    background: #A8A8A8;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
QScrollBar:vertical {
    background: transparent;
    width: 6px;
}
QScrollBar::handle:vertical {
    background: #C8C8C8;
    border-radius: 3px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #A8A8A8;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* ========== 菜单 ========== */
QMenu {
    background-color: #FFFFFF;
    border: 1px solid #E0E0E0;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item {
    padding: 8px 32px 8px 12px;
    border-radius: 4px;
    color: #333333;
}
QMenu::item:selected {
    background-color: #1677FF;
    color: #FFFFFF;
}
QMenu::separator {
    height: 1px;
    background: #E4E4E4;
    margin: 4px 8px;
}

/* ========== 提示框 ========== */
QToolTip {
    background-color: #FFFFFF;
    color: #333333;
    border: 1px solid #D8D8D8;
    border-radius: 4px;
    padding: 4px 8px;
}

/* ========== 状态栏 ========== */
QStatusBar {
    background-color: #FFFFFF;
    border-top: 1px solid #E2E2E2;
    color: #888888;
}

/* ========== 对话框 ========== */
QDialog {
    background-color: #FFFFFF;
}
QLabel#titleLabel {
    font-size: 15px;
    font-weight: bold;
    color: #222222;
}

/* ========== 表情包卡片 ========== */
QFrame#emojiCard {
    background-color: #FFFFFF;
    border: 1px solid #EAEAEA;
    border-radius: 8px;
    padding: 4px;
}
QFrame#emojiCard:hover {
    border-color: #1677FF;
    background-color: #F0F7FF;
}
QFrame#emojiCard[selected="true"] {
    border-color: #1677FF;
    background-color: #E6F0FF;
}
QLabel#thumbLabel {
    background-color: #EDEDED;
    border-radius: 6px;
}
QLabel#nameLabel {
    color: #888888;
    background: transparent;
}
QLabel#checkBadge {
    color: #FFFFFF;
    font-size: 12px;
    font-weight: bold;
    background-color: #1677FF;
    border: 1px solid #FFFFFF;
    border-radius: 9px;
}
QLabel#editCount {
    color: #666666;
    font-size: 11px;
    background: transparent;
}
QPushButton#editToolBtn {
    color: #333333;
    background-color: #F0F0F0;
    border: 1px solid #CCCCCC;
    border-radius: 4px;
    padding: 3px 10px;
    font-size: 11px;
}
QPushButton#editToolBtn:hover {
    background-color: #E0E0E0;
}
QPushButton#editToolBtn:disabled {
    color: #AAAAAA;
    background-color: #F5F5F5;
}

/* ========== 分组标签按钮 ========== */
QPushButton#groupTab {
    background-color: transparent;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    color: #666666;
    font-size: 12px;
}
QPushButton#groupTab:hover {
    background-color: #E8E8E8;
    color: #333333;
}
QPushButton#groupTab[active="true"] {
    background-color: #1677FF;
    color: #FFFFFF;
}

/* ========== 分割线 ========== */
QFrame#separator {
    background-color: #E2E2E2;
}

/* ========== 设置对话框通用控件 ========== */
QListWidget {
    background-color: #F7F8FA;
    border: 1px solid #E8E8E8;
    border-radius: 8px;
    outline: none;
    padding: 4px;
}
QListWidget::item {
    padding: 9px 12px;
    border-radius: 6px;
    color: #555555;
    margin: 1px 0;
}
QListWidget::item:hover {
    background-color: #E8F1FE;
    color: #333333;
}
QListWidget::item:selected {
    background-color: #1677FF;
    color: #FFFFFF;
}
QListWidget::item:selected:hover {
    background-color: #1677FF;
    color: #FFFFFF;
}
QComboBox {
    background-color: #FFFFFF;
    border: 1px solid #D8D8D8;
    border-radius: 4px;
    padding: 3px 8px;
    color: #333333;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    color: #333333;
    selection-background-color: #1677FF;
    outline: none;
}
QSpinBox {
    background-color: #FFFFFF;
    border: 1px solid #D8D8D8;
    border-radius: 4px;
    color: #333333;
    padding: 2px 6px;
}
QSpinBox::up-button, QSpinBox::down-button {
    width: 0;
    border: none;
}
QGroupBox {
    border: none;
    margin-top: 16px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 2px;
    color: #888888;
    font-size: 11px;
    padding: 0 2px;
}
QCheckBox, QRadioButton {
    color: #333333;
    spacing: 6px;
}
QRadioButton::indicator {
    width: 12px;
    height: 12px;
    border-radius: 6px;
    border: 1px solid #8A8A8A;
    background: transparent;
}
QRadioButton::indicator:hover {
    border-color: #1677FF;
}
QRadioButton::indicator:checked {
    border-color: #1677FF;
    background-color: #1677FF;
}
"""
