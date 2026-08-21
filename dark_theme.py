"""Dark theme style sheet
暗色主题样式表"""

QSS = """
/* ========== 全局 ========== */
QWidget {
    background-color: #1E1E1E;
    color: #CCCCCC;
    font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
    font-size: 13px;
}

/* ========== 主窗口 ========== */
QMainWindow {
    background-color: #1E1E1E;
}

/* ========== 工具栏 ========== */
QToolBar {
    background-color: #252525;
    border-bottom: 1px solid #333333;
    spacing: 8px;
    padding: 4px 8px;
}

/* ========== 主工具栏 ========== */
QWidget#mainToolbar {
    background-color: #252525;
    border-bottom: 1px solid #333333;
}

/* ========== 搜索栏 ========== */
QLineEdit {
    background-color: #2B2B2B;
    border: 1px solid #3A3A3A;
    border-radius: 16px;
    padding: 6px 12px;
    color: #E0E0E0;
    selection-background-color: #1677FF;
}
QLineEdit:focus {
    border-color: #1677FF;
}

/* ========== 按钮 ========== */
QPushButton {
    background-color: #2B2B2B;
    border: 1px solid #3A3A3A;
    border-radius: 6px;
    padding: 6px 16px;
    color: #E0E0E0;
}
QPushButton:hover {
    background-color: #353535;
    border-color: #4A4A4A;
}
QPushButton:pressed {
    background-color: #1A1A1A;
}
QPushButton[flat="true"] {
    background-color: transparent;
    border: none;
    padding: 4px 8px;
}

/* ========== 分页标签栏 ========== */
QTabBar::tab {
    background-color: #252525;
    border: none;
    border-top: 2px solid transparent;
    padding: 8px 18px;
    color: #999999;
    min-width: 60px;
}
QTabBar::tab:hover {
    background-color: #2B2B2B;
    color: #CCCCCC;
}
QTabBar::tab:selected {
    background-color: #1E1E1E;
    color: #FFFFFF;
    border-top: 2px solid #1677FF;
}

/* ========== 滚动区域 ========== */
QScrollArea {
    background-color: #1E1E1E;
    border: none;
}
QScrollBar:horizontal {
    background: #252525;
    height: 6px;
    border-radius: 3px;
}
QScrollBar:horizontal:hover {
    height: 10px;
}
QScrollBar::handle:horizontal {
    background: #4A4A4A;
    border-radius: 3px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover {
    background: #666666;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

QScrollBar:vertical {
    background: #252525;
    width: 6px;
    border-radius: 3px;
}
QScrollBar:vertical:hover {
    width: 10px;
}
QScrollBar::handle:vertical {
    background: #4A4A4A;
    border-radius: 3px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #666666;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* ========== 菜单 ========== */
QMenu {
    background-color: #2B2B2B;
    border: 1px solid #3A3A3A;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item {
    padding: 8px 32px 8px 12px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: #1677FF;
    color: #FFFFFF;
}
QMenu::separator {
    height: 1px;
    background: #3A3A3A;
    margin: 4px 8px;
}

/* ========== 提示框 ========== */
QToolTip {
    background-color: #333333;
    color: #E0E0E0;
    border: 1px solid #4A4A4A;
    border-radius: 4px;
    padding: 4px 8px;
}

/* ========== 状态栏 ========== */
QStatusBar {
    background-color: #252525;
    border-top: 1px solid #333333;
    color: #888888;
}

/* ========== 对话框 ========== */
QDialog {
    background-color: #252525;
}
QLabel#titleLabel {
    font-size: 15px;
    font-weight: bold;
    color: #FFFFFF;
}

/* ========== 表情包卡片 ========== */
QFrame#emojiCard {
    background-color: #2B2B2B;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 4px;
}
QFrame#emojiCard:hover {
    border-color: #4A4A4A;
    background-color: #353535;
}
QFrame#emojiCard[selected="true"] {
    border-color: #1677FF;
    background-color: #1A3A5C;
}
QLabel#thumbLabel {
    background-color: #1A1A1A;
    border-radius: 6px;
}
QLabel#nameLabel {
    color: #999999;
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
    color: #BBBBBB;
    font-size: 11px;
    background: transparent;
}
QPushButton#editToolBtn {
    color: #DDDDDD;
    background-color: #3A3A3A;
    border: 1px solid #4A4A4A;
    border-radius: 4px;
    padding: 3px 10px;
    font-size: 11px;
}
QPushButton#editToolBtn:hover {
    background-color: #4A4A4A;
}
QPushButton#editToolBtn:disabled {
    color: #666666;
    background-color: #2A2A2A;
}

/* ========== 分组标签按钮 ========== */
QPushButton#groupTab {
    background-color: transparent;
    border: none;
    border-radius: 6px;
    padding: 6px 14px;
    color: #999999;
    font-size: 12px;
}
QPushButton#groupTab:hover {
    background-color: #2B2B2B;
    color: #CCCCCC;
}
QPushButton#groupTab[active="true"] {
    background-color: #1677FF;
    color: #FFFFFF;
}

/* ========== 分割线 ========== */
QFrame#separator {
    background-color: #3A3A3A;
}

/* ========== 设置对话框通用控件 ========== */
QListWidget {
    background-color: #252525;
    border: 1px solid #333333;
    border-radius: 8px;
    outline: none;
    padding: 4px;
}
QListWidget::item {
    padding: 9px 12px;
    border-radius: 6px;
    color: #BBBBBB;
    margin: 1px 0;
}
QListWidget::item:hover {
    background-color: #353535;
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
    background-color: #2B2B2B;
    border: 1px solid #3A3A3A;
    border-radius: 4px;
    padding: 3px 8px;
    color: #CCCCCC;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background-color: #2B2B2B;
    color: #CCCCCC;
    selection-background-color: #1677FF;
    outline: none;
}
QSpinBox {
    background-color: #2B2B2B;
    border: 1px solid #3A3A3A;
    border-radius: 4px;
    color: #CCCCCC;
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
    color: #999999;
    font-size: 11px;
    padding: 0 2px;
}
QCheckBox, QRadioButton {
    color: #DDDDDD;
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
