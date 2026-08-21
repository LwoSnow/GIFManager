"""Settings dialog — left category navigation + right option pages
设置对话框 — 左侧分类导航 + 右侧选项分页"""
import os
import sys
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QRadioButton,
    QPushButton, QGroupBox, QButtonGroup, QDialogButtonBox,
    QCheckBox, QComboBox, QLineEdit, QSpinBox, QListWidget,
    QStackedWidget, QWidget, QFrame, QScrollArea, QProgressBar,
    QAbstractSpinBox, QSlider,
)
from PySide6.QtCore import Qt, QPoint, Signal, QStandardPaths
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont
from PySide6.QtGui import QKeyEvent, QKeySequence, QMouseEvent

from app.models.lang_manager import tr, current_language, available_languages
from app.models.update_manager import UpdateManager
from app.widgets.hotkey_manager import key_event_to_hotkey_desc
from app.utils.version import cmp_version, parse_version
from app import __version__


def _download_dir():
    # System Downloads folder, falling back to the home dir /
    # 系统下载目录，失败回退用户主目录
    d = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.DownloadLocation)
    return d if d else os.path.expanduser("~")


# Recommended worker thread count: keep 1 core for the UI, capped at 8
# 推荐多线程核心数：留 1 核给 UI，上限 8
def recommended_thread_count():
    n = os.cpu_count() or 4
    return max(2, min(8, n - 1))


# Hotkey capture widget
# 快捷键捕获控件
class HotkeyCapture(QLineEdit):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.setPlaceholderText(tr("hotkey_capture_hint"))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._capturing = False
        self._mods = 0
        self._vk = 0
        # Previous hotkey/text, restored when capture ends without a key
        # (clicking the box then saving must NOT wipe a registered hotkey)
        # 捕获前的热键与文本：未按键就结束时恢复（点击输入框后保存不得
        # 清空已注册的热键）
        self._prev_mods = 0
        self._prev_vk = 0
        self._prev_text = ""

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if not self._capturing:
                self._start_capture()
            else:
                self._stop_capture()
        super().mousePressEvent(event)

    def _start_capture(self):
        self._capturing = True
        # Remember the current hotkey so "click then save" cannot wipe it /
        # 记住当前热键，避免"点击后直接保存"误清空
        self._prev_mods = self._mods
        self._prev_vk = self._vk
        self._prev_text = self.text()
        self._mods = 0
        self._vk = 0
        self.setText(tr("hotkey_capturing"))
        self.setStyleSheet("QLineEdit { border-color: #1677FF; }")
        self.grabKeyboard()
        self.setFocus()

    def _stop_capture(self):
        self._capturing = False
        self.releaseKeyboard()
        self.setStyleSheet("")
        if self._mods == 0 and self._vk == 0:
            # No key was pressed: restore the previous hotkey instead of
            # clearing it / 未按下任何键：恢复原热键而不是清空
            self._mods = self._prev_mods
            self._vk = self._prev_vk
            self.setText(self._prev_text or tr("hotkey_unset"))

    def keyPressEvent(self, event: QKeyEvent):
        if not self._capturing:
            super().keyPressEvent(event)
            return
        key = event.key()
        if key == Qt.Key.Key_Escape:
            # ESC means "clear": also drop the remembered previous hotkey so
            # _stop_capture does not restore it / ESC 表示"清空"：同时清掉
            # 记忆的旧热键，_stop_capture 才不会恢复它
            self._prev_mods = 0
            self._prev_vk = 0
            self._mods = 0
            self._vk = 0
            self.setText(tr("hotkey_unset"))
            self._stop_capture()
            return
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt,
                    Qt.Key.Key_Meta, Qt.Key.Key_AltGr):
            return
        self._mods = int(event.modifiers().value)
        self._vk = key
        desc = key_event_to_hotkey_desc(event)
        self.setText(desc if desc else tr("hotkey_unknown"))

    def hotkey_info(self):
        return (self._mods, self._vk)


# Clickable word-wrapped label: clicking selects the matching send-mode radio
# 可点击的换行标签（发送选项文字，点击选中对应 radio）
class _ClickableLabel(QLabel):

    clicked = Signal()

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


# Non-modal settings dialog: Apply applies live, OK applies and closes
# 设置对话框（非模态）：Apply 按钮实时应用，OK 应用并关闭
class SettingsDialog(QDialog):

    apply_clicked = Signal()  # Apply clicked (does not close) / 点击"应用"（不关闭）
    clear_logs_requested = Signal()  # Clear-all-logs requested / 点击"清除所有日志"
    convert_library_requested = Signal()  # One-click convert all / 一键转换所有图片

    def __init__(self, current_mode=0, remember_group=True, autostart=False,
                 always_on_top=False, text_limit_single=100, text_limit_multi=200,
                 thread_count=0, theme="dark",
                 global_sort_enabled=False, global_sort_by="time", global_sort_desc=False,
                 auto_convert_gif=True, auto_update=False, show_emoji_name=True,
                 hover_zoom=1.15, hover_preview_enabled=True, auto_input=True,
                 emoji_size=100, name_font_size=10,
                 data_manager=None, hotkey_desc="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("settings"))
        # 470x510: slightly larger than before so English texts (longer than
        # Chinese) do not squeeze the option pages / 470x510：比原来略大，
        # 英文文案比中文长，避免挤压右侧选项页
        self.setFixedSize(470, 510)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog
        )

        self._mode = current_mode
        self._remember_group = remember_group
        self._autostart = autostart
        self._always_on_top = always_on_top
        self._text_limit_single = text_limit_single
        self._text_limit_multi = text_limit_multi
        # 0 = auto (use recommended value) / 0 = 自动（使用推荐值）
        self._thread_count = thread_count if thread_count > 0 else recommended_thread_count()
        self._theme = theme if theme in ("dark", "light") else "dark"
        # Global sorting mode (time/name/freq, asc/desc) / 全局排序模式（时间/名称/频率，正/逆序）
        self._gs_enabled = global_sort_enabled
        self._gs_by = global_sort_by if global_sort_by in ("time", "name", "freq") else "time"
        self._gs_desc = global_sort_desc
        # Auto-convert imported images to gif / 导入时自动转 gif
        self._auto_convert_gif = auto_convert_gif
        # Auto-update check on startup / 启动时自动检查更新
        self._auto_update = auto_update
        # Show the emoji name under the thumbnail / 缩略图下方显示表情包名称
        self._show_emoji_name = show_emoji_name
        # Hover zoom factor for image cards / 图片卡悬停放大倍数
        self._hover_zoom = max(1.0, float(hover_zoom))
        # Master switch for the hover preview / 悬停预览总开关
        self._hover_preview_enabled = hover_preview_enabled
        # Click emoji -> auto-type into the focused chat input / 点击表情自动输入
        self._auto_input = auto_input
        self._emoji_size = max(60, min(200, int(emoji_size)))
        self._name_font_size = max(1, min(20, int(name_font_size)))
        self._slider_size = None  # will be set in _build_general_page
        self._spin_name_font = None  # will be set in _build_general_page
        self._dm = data_manager
        self._hotkey_mods = 0
        self._hotkey_vk = 0
        self._hotkey_changed = False
        self._lang = current_language()

        self._setup_ui(hotkey_desc)
        self._dragging = False
        self._drag_start = QPoint()

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_rounded()
        if self.parent():
            pg = self.parent().geometry()
            self.move(
                pg.x() + (pg.width() - self.width()) // 2,
                pg.y() + (pg.height() - self.height()) // 2,
            )

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

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
            # While capturing, clicking blank space saves / 快捷键捕获中，点击空白处保存
            hc = self._hotkey_capture
            if hc._capturing:
                child = self.childAt(event.position().toPoint())
                if child is not hc and not hc.isAncestorOf(child):
                    hc._stop_capture()
                    return
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

    def _setup_ui(self, hotkey_desc):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 12, 16, 12)

        title_bar = QHBoxLayout()
        self._title_label = QLabel(tr("settings"))
        # Color is inherited from the active theme
        # 颜色继承主题
        self._title_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        title_bar.addWidget(self._title_label)
        title_bar.addStretch()
        btn_close = QPushButton("✕")
        btn_close.setFixedSize(26, 26)
        btn_close.setFlat(True)
        btn_close.clicked.connect(self.reject)
        title_bar.addWidget(btn_close)
        layout.addLayout(title_bar)

        # Body: left category navigation + right option pages / 主体：左侧分类导航 + 右侧选项分页
        body = QHBoxLayout()
        body.setSpacing(10)

        self._cat_list = QListWidget()
        self._cat_list.setFixedWidth(118)
        # Hide the horizontal scrollbar and elide long English category
        # names (e.g. "Performance") instead of showing a scrollbar
        # 隐藏横向滚动条，超长的英文分类名（如 Performance）用省略号截断
        self._cat_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._cat_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        for key in ("cat_general", "cat_send", "cat_hotkey", "cat_text", "cat_perf"):
            self._cat_list.addItem(tr(key))
        self._cat_list.addItem(tr("cat_update"))
        # Category name comes from the language file, not hardcoded "About"
        # 分类名走语言文件（可替换为"关于"），页面内容保持纯英文
        self._cat_list.addItem(tr("cat_about"))
        self._cat_list.setCurrentRow(0)
        body.addWidget(self._cat_list)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_general_page())
        self._stack.addWidget(self._build_send_page())
        self._stack.addWidget(self._build_hotkey_page(hotkey_desc))
        self._stack.addWidget(self._build_text_page())
        self._stack.addWidget(self._build_perf_page())
        self._stack.addWidget(self._build_update_page())
        self._stack.addWidget(self._build_about_page())
        self._cat_list.currentRowChanged.connect(self._stack.setCurrentIndex)
        body.addWidget(self._stack, 1)
        layout.addLayout(body, 1)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        # Button texts come from the language file (zh_CN.json) / 按钮文本走语言文件（zh_CN.json 可修改）
        self._btn_apply = btn_box.button(QDialogButtonBox.StandardButton.Apply)
        self._btn_ok = btn_box.button(QDialogButtonBox.StandardButton.Ok)
        self._btn_cancel = btn_box.button(QDialogButtonBox.StandardButton.Cancel)
        self._btn_ok.setText(tr("ok"))
        self._btn_cancel.setText(tr("cancel"))
        self._btn_apply.setText(tr("apply"))
        btn_box.accepted.connect(self._on_ok)
        btn_box.rejected.connect(self.reject)
        btn_box.clicked.connect(self._on_box_clicked)
        layout.addWidget(btn_box)

    # Apply button: applies settings live without closing the dialog
    # Apply 按钮：实时应用设置但不关闭对话框
    def _on_box_clicked(self, button):
        if button is self._btn_apply:
            self.apply_clicked.emit()

    # ------------------------------------------------------------------
    # Category pages / 各分类页面
    # ------------------------------------------------------------------

    def _page_widget(self):
        w = QWidget()
        self._page_layout = QVBoxLayout(w)
        self._page_layout.setContentsMargins(4, 4, 4, 4)
        self._page_layout.setSpacing(10)
        return w

    # General page: theme + language + other options
    # 通用：主题 + 语言 + 其他
    # Wrap a settings page in a scroll area so long pages scroll instead
    # of squeezing together. / 用滚动区包裹设置页，页面过长时滚动显示而不是挤在一起。
    def _wrap_scroll(self, page):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget { background:transparent; }"
        )
        scroll.setWidget(page)
        return scroll

    # Draw a blue circle with a white "?" via QPainter. Using a bitmap
    # instead of QSS avoids stylesheet merge conflicts on the real window.
    # 用 QPainter 绘制蓝底白问号位图，绕开 QSS 合并冲突。
    @staticmethod
    def _make_question_pixmap(size=18):
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1677FF"))
        p.drawEllipse(0, 0, size, size)
        p.setPen(QColor("#FFFFFF"))
        f = QFont()
        f.setBold(True)
        f.setPixelSize(int(size * 0.62))
        p.setFont(f)
        p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "?")
        p.end()
        return pix

    def _build_general_page(self):
        w = self._page_widget()
        # Theme switching / 主题切换
        self._theme_group = QGroupBox(tr("theme_group"))
        theme_layout = QHBoxLayout(self._theme_group)
        self._theme_combo = QComboBox()
        self._theme_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        self._theme_combo.addItem(tr("theme_dark"), "dark")
        self._theme_combo.addItem(tr("theme_light"), "light")
        idx = self._theme_combo.findData(self._theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)
        theme_layout.addWidget(self._theme_combo)
        theme_layout.addStretch()
        self._page_layout.addWidget(self._theme_group)

        # Hover zoom factor / 悬停放大倍数
        self._zoom_group = QGroupBox(tr("hover_zoom_group"))
        zoom_layout = QVBoxLayout(self._zoom_group)
        self._cb_hover_preview = QCheckBox(tr("hover_preview_enable"))
        self._cb_hover_preview.setChecked(self._hover_preview_enabled)
        zoom_layout.addWidget(self._cb_hover_preview)
        zoom_row = QHBoxLayout()
        self._label_zoom = QLabel(tr("hover_zoom"))
        zoom_row.addWidget(self._label_zoom)
        # Compact spinbox: no arrow buttons, wheel-scroll to adjust, the
        # percent sign sits OUTSIDE the box / 紧凑数字框：无上下箭头按钮、
        # 鼠标滚轮调节、百分号在框外
        self._spin_zoom = QSpinBox()
        self._spin_zoom.setRange(100, 200)
        self._spin_zoom.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._spin_zoom.setFixedWidth(64)
        self._spin_zoom.setValue(int(round(self._hover_zoom * 100)))
        zoom_row.addWidget(self._spin_zoom)
        self._label_zoom_pct = QLabel("%")
        zoom_row.addWidget(self._label_zoom_pct)
        zoom_row.addStretch()
        zoom_layout.addLayout(zoom_row)
        # master switch disables the zoom box when off / 总开关关闭时禁用倍数框
        self._cb_hover_preview.toggled.connect(self._spin_zoom.setEnabled)
        self._spin_zoom.setEnabled(self._hover_preview_enabled)
        self._page_layout.addWidget(self._zoom_group)

        # Emoji size slider / 表情大小滑块
        try:
            self._size_group = QGroupBox("表情大小 / Emoji Size")
            size_layout = QVBoxLayout(self._size_group)
            size_row = QHBoxLayout()
            self._label_size = QLabel("卡片尺寸")
            size_row.addWidget(self._label_size)
            self._slider_size = QSlider(Qt.Orientation.Horizontal)
            self._slider_size.setRange(60, 200)
            self._slider_size.setValue(self._emoji_size)
            size_row.addWidget(self._slider_size, 1)
            self._label_size_val = QLabel(str(self._emoji_size) + "px")
            self._label_size_val.setFixedWidth(40)
            size_row.addWidget(self._label_size_val)
            size_layout.addLayout(size_row)
            self._slider_size.valueChanged.connect(
                lambda v: self._label_size_val.setText(str(v) + "px"))
            self._page_layout.addWidget(self._size_group)
        except Exception:
            self._slider_size = None

        # Name font size / 名字字号
        try:
            self._name_font_group = QGroupBox("名字字号 / Name Font Size")
            nf_layout = QHBoxLayout(self._name_font_group)
            nf_layout.addWidget(QLabel("字号"))
            self._spin_name_font = QSpinBox()
            self._spin_name_font.setRange(1, 20)
            self._spin_name_font.setValue(self._name_font_size)
            self._spin_name_font.setFixedWidth(64)
            nf_layout.addWidget(self._spin_name_font)
            nf_layout.addWidget(QLabel("pt"))
            nf_layout.addStretch()
            self._page_layout.addWidget(self._name_font_group)
        except Exception:
            self._spin_name_font = None

        self._lang_group = QGroupBox(tr("language_group"))
        lang_layout = QHBoxLayout(self._lang_group)
        self._lang_combo = QComboBox()
        langs = available_languages()
        for code in langs:
            self._lang_combo.addItem(code, code)
        cur = current_language()
        if cur in langs:
            self._lang_combo.setCurrentIndex(langs.index(cur))
        lang_layout.addWidget(self._lang_combo)
        lang_layout.addStretch()
        self._page_layout.addWidget(self._lang_group)

        self._other_group = QGroupBox(tr("other_group"))
        other_layout = QVBoxLayout(self._other_group)
        self._cb_remember = QCheckBox(tr("remember_group"))
        self._cb_remember.setChecked(self._remember_group)
        other_layout.addWidget(self._cb_remember)
        self._cb_autostart = QCheckBox(tr("autostart"))
        self._cb_autostart.setChecked(self._autostart)
        other_layout.addWidget(self._cb_autostart)
        self._cb_top = QCheckBox(tr("always_on_top"))
        self._cb_top.setChecked(self._always_on_top)
        other_layout.addWidget(self._cb_top)
        self._cb_show_name = QCheckBox(tr("show_emoji_name"))
        self._cb_show_name.setChecked(self._show_emoji_name)
        other_layout.addWidget(self._cb_show_name)
        self._page_layout.addWidget(self._other_group)

        # Global sorting mode / 全局排序模式
        # The group title is drawn as a custom title row so the hint icon
        # can sit right after the title text. / 分组标题用自定义标题行绘制，
        # 让问号图标紧跟在标题文字后面。
        self._gs_group = QGroupBox()
        gs_layout = QVBoxLayout(self._gs_group)
        gs_layout.setContentsMargins(4, 2, 4, 4)
        row_title = QHBoxLayout()
        self._gs_title = QLabel(tr("global_sort_group"))
        self._gs_title.setStyleSheet(
            "QLabel { color:#999999; font-size:11px; padding:0 2px;"
            " background:transparent; }"
        )
        row_title.addWidget(self._gs_title)
        self._gs_hint = QLabel()
        self._gs_hint.setPixmap(self._make_question_pixmap(18))
        self._gs_hint.setFixedSize(18, 18)
        self._gs_hint.setToolTip(tr("global_sort_hint"))
        self._gs_hint.setCursor(Qt.CursorShape.WhatsThisCursor)
        row_title.addWidget(self._gs_hint)
        row_title.addStretch()
        gs_layout.addLayout(row_title)
        # Enable row: checkbox only / 启用行：仅复选框
        row_enable = QHBoxLayout()
        self._cb_gs = QCheckBox(tr("global_sort_enable"))
        self._cb_gs.setChecked(self._gs_enabled)
        row_enable.addWidget(self._cb_gs)
        row_enable.addStretch()
        gs_layout.addLayout(row_enable)
        # The sort combos have no inline stylesheet so they follow the active
        # theme (hardcoded dark QSS here used to stay dark in light mode).
        # 排序下拉框不设内联样式，跟随当前主题（此前硬编码的暗色 QSS 在亮色模式下不换色）
        row_by = QHBoxLayout()
        self._label_gs_by = QLabel(tr("global_sort_by"))
        row_by.addWidget(self._label_gs_by)
        self._combo_gs_by = QComboBox()
        self._combo_gs_by.addItem(tr("sort_by_time"), "time")
        self._combo_gs_by.addItem(tr("sort_by_name"), "name")
        self._combo_gs_by.addItem(tr("sort_by_freq"), "freq")
        self._combo_gs_by.setCurrentIndex(
            max(0, ["time", "name", "freq"].index(self._gs_by)))
        row_by.addWidget(self._combo_gs_by)
        row_by.addStretch()
        gs_layout.addLayout(row_by)
        row_dir = QHBoxLayout()
        self._label_gs_dir = QLabel(tr("global_sort_dir"))
        row_dir.addWidget(self._label_gs_dir)
        self._combo_gs_dir = QComboBox()
        self._combo_gs_dir.addItem(tr("sort_dir_asc"), False)
        self._combo_gs_dir.addItem(tr("sort_dir_desc"), True)
        self._combo_gs_dir.setCurrentIndex(1 if self._gs_desc else 0)
        row_dir.addWidget(self._combo_gs_dir)
        row_dir.addStretch()
        gs_layout.addLayout(row_dir)
        # Enable/disable sub-controls with the master checkbox / 随总开关启用/禁用子控件
        self._cb_gs.toggled.connect(self._combo_gs_by.setEnabled)
        self._cb_gs.toggled.connect(self._combo_gs_dir.setEnabled)
        self._combo_gs_by.setEnabled(self._gs_enabled)
        self._combo_gs_dir.setEnabled(self._gs_enabled)
        self._page_layout.addWidget(self._gs_group)

        # Clear logs / 清除日志
        self._log_group = QGroupBox(tr("logs_group"))
        log_layout = QVBoxLayout(self._log_group)
        self._btn_clear_logs = QPushButton(tr("clear_logs"))
        self._btn_clear_logs.clicked.connect(self.clear_logs_requested.emit)
        log_layout.addWidget(self._btn_clear_logs)
        self._page_layout.addWidget(self._log_group)
        self._page_layout.addStretch()
        return self._wrap_scroll(w)

    # Send mode: radio dots (filled when selected) + word-wrapped text labels
    # 发送模式：radio 圆点选择框（选中实心）+ 可换行文字标签
    def _build_send_page(self):
        w = self._page_widget()

        self._send_group = QGroupBox(tr("send_mode"))
        send_layout = QVBoxLayout(self._send_group)

        self._rb_file = QRadioButton()
        self._rb_image = QRadioButton()
        self._label_file = _ClickableLabel(tr("send_mode_file"))
        self._label_image = _ClickableLabel(tr("send_mode_image"))
        for label in (self._label_file, self._label_image):
            label.setWordWrap(True)  # Wraps long text so it is not clipped / 长文字自动换行，不被窗口截断
            label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label_file.clicked.connect(self._rb_file.click)
        self._label_image.clicked.connect(self._rb_image.click)

        if self._mode == 0:
            self._rb_file.setChecked(True)
        else:
            self._rb_image.setChecked(True)

        def _row(radio, label):
            row = QHBoxLayout()
            row.setSpacing(2)  # Radio dot and text stay close, same visual row / 圆点与文字紧贴，视觉同一行
            # Align radio dot center with the first text line (radio is shorter, nudge down)
            # 圆点中心对齐第一行文字中心（radio 比文字行矮，微调下移）
            radio.setStyleSheet("QRadioButton { margin-top: 2px; }")
            row.addWidget(radio, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(label, 1)
            return row

        send_layout.addLayout(_row(self._rb_file, self._label_file))
        send_layout.addLayout(_row(self._rb_image, self._label_image))
        self._page_layout.addWidget(self._send_group)

        # Auto-input group: click emoji -> paste into the focused input /
        # 自动输入分组：点击表情 → 粘贴到焦点输入框
        self._auto_input_group = QGroupBox(tr("auto_input_group"))
        ai_layout = QVBoxLayout(self._auto_input_group)
        self._cb_auto_input = QCheckBox(tr("auto_input_enable"))
        self._cb_auto_input.setChecked(self._auto_input)
        ai_layout.addWidget(self._cb_auto_input)
        self._ai_hint = QLabel(tr("auto_input_hint"))
        self._ai_hint.setStyleSheet("color: #888; font-size: 11px;")
        self._ai_hint.setWordWrap(True)
        ai_layout.addWidget(self._ai_hint)
        self._page_layout.addWidget(self._auto_input_group)

        # GIF conversion group / GIF 转换分组
        self._conv_group = QGroupBox(tr("gif_conv_group"))
        conv_layout = QVBoxLayout(self._conv_group)
        self._cb_auto_convert = QCheckBox(tr("gif_auto_convert"))
        self._cb_auto_convert.setChecked(self._auto_convert_gif)
        conv_layout.addWidget(self._cb_auto_convert)
        self._conv_hint = QLabel(tr("gif_auto_convert_hint"))
        self._conv_hint.setStyleSheet("color: #888; font-size: 11px;")
        self._conv_hint.setWordWrap(True)
        conv_layout.addWidget(self._conv_hint)
        self._btn_convert_library = QPushButton(tr("gif_convert_all"))
        self._btn_convert_library.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_convert_library.clicked.connect(self._on_convert_all)
        conv_layout.addWidget(self._btn_convert_library)
        self._page_layout.addWidget(self._conv_group)
        self._page_layout.addStretch()
        return self._wrap_scroll(w)

    # Hotkey page
    # 快捷键
    def _build_hotkey_page(self, hotkey_desc):
        w = self._page_widget()
        self._hotkey_group = QGroupBox(tr("hotkey_group"))
        hotkey_layout = QVBoxLayout(self._hotkey_group)
        self._hotkey_hint = QLabel(tr("hotkey_hint"))
        self._hotkey_hint.setStyleSheet("color: #888; font-size: 11px;")
        self._hotkey_hint.setWordWrap(True)
        hotkey_layout.addWidget(self._hotkey_hint)
        self._hotkey_capture = HotkeyCapture()
        self._hotkey_capture.setText(hotkey_desc)
        hotkey_layout.addWidget(self._hotkey_capture)
        self._page_layout.addWidget(self._hotkey_group)
        self._page_layout.addStretch()
        return self._wrap_scroll(w)

    # Text preview limits (single-line and multi-line configured independently)
    # 文字预览限制（单行 / 多行独立）
    def _build_text_page(self):
        w = self._page_widget()
        self._text_group = QGroupBox(tr("text_preview_group"))
        text_layout = QVBoxLayout(self._text_group)
        # Labels wrap so longer English text is not hidden; inputs align to the top
        # 标签可换行（英文文案更长时不被输入框盖住），输入框顶部对齐
        row1 = QHBoxLayout()
        row1.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._label_single = QLabel(tr("text_preview_single"))
        self._label_single.setWordWrap(True)
        row1.addWidget(self._label_single, 1)
        self._spin_single = QSpinBox()
        self._spin_single.setRange(20, 1000)
        self._spin_single.setValue(self._text_limit_single)
        self._spin_single.setFixedWidth(72)
        row1.addWidget(self._spin_single, 0, Qt.AlignmentFlag.AlignTop)
        text_layout.addLayout(row1)
        row2 = QHBoxLayout()
        row2.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._label_multi = QLabel(tr("text_preview_multi"))
        self._label_multi.setWordWrap(True)
        row2.addWidget(self._label_multi, 1)
        self._spin_multi = QSpinBox()
        self._spin_multi.setRange(20, 1000)
        self._spin_multi.setValue(self._text_limit_multi)
        self._spin_multi.setFixedWidth(72)
        row2.addWidget(self._spin_multi, 0, Qt.AlignmentFlag.AlignTop)
        text_layout.addLayout(row2)
        self._page_layout.addWidget(self._text_group)
        self._page_layout.addStretch()
        return self._wrap_scroll(w)

    # About page: logo / name / version / developer / MIT license
    # 信息页：Logo / 名称 / 版本 / 开发者 / MIT 许可。
    # Hardcoded English only, not routed through the language file
    # 纯英文硬编码，不经过语言文件。
    def _build_update_page(self):
        w = self._page_widget()
        layout = self._page_layout

        # Current version / 当前版本
        # No hardcoded foreground color: inherit the active theme (the old
        # #DDDDDD was nearly invisible on the light theme)
        # 不硬编码前景色：继承当前主题（旧 #DDDDDD 在亮色主题下几乎不可见）
        self._lbl_current = QLabel(tr("update_current", version=__version__))
        self._lbl_current.setStyleSheet("font-size: 13px;")
        layout.addWidget(self._lbl_current)

        # Auto-update switch / 自动更新开关
        self._cb_auto_update = QCheckBox(tr("update_auto"))
        self._cb_auto_update.setChecked(self._auto_update)
        layout.addWidget(self._cb_auto_update)

        # Check button / 检查更新按钮
        self._btn_check = QPushButton(tr("update_check"))
        self._btn_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_check.clicked.connect(self._on_check_update)
        layout.addWidget(self._btn_check)

        # Info area (inline, errors shown in red, no popups) /
        # 信息区（页内联显示，错误红色，不弹窗）
        self._lbl_update_info = QLabel("")
        self._lbl_update_info.setWordWrap(True)
        self._lbl_update_info.setStyleSheet("font-size: 12px;")
        layout.addWidget(self._lbl_update_info)

        # Download row: button + progress bar + cancel button / 下载行：
        # 按钮 + 进度条 + 取消按钮
        self._btn_download = QPushButton(tr("update_download"))
        self._btn_download.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_download.setEnabled(False)
        # Only show the button when an update is actually available /
        # 仅在确实有更新时显示下载按钮
        self._btn_download.setVisible(False)
        self._btn_download.clicked.connect(self._on_download_update)
        dl_row = QHBoxLayout()
        dl_row.addWidget(self._btn_download)
        self._btn_dl_cancel = QPushButton(tr("update_cancel"))
        self._btn_dl_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_dl_cancel.setVisible(False)
        self._btn_dl_cancel.clicked.connect(self._on_cancel_download)
        dl_row.addWidget(self._btn_dl_cancel)
        dl_row.addStretch()
        layout.addLayout(dl_row)
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._update_mgr = UpdateManager(self)
        self._update_mgr.check_finished.connect(self._on_check_finished)
        self._update_mgr.download_progress.connect(self._on_dl_progress)
        self._update_mgr.download_done.connect(self._on_dl_done)

        layout.addStretch()
        return self._wrap_scroll(w)

    # Update page handlers / 更新页处理
    def _on_check_update(self):
        self._btn_check.setEnabled(False)
        self._btn_download.setVisible(False)
        self._info_normal(tr("update_checking"))
        self._update_mgr.check_updates()

    def _info_normal(self, text):
        # Inherit the theme foreground color; the old #BBBBBB was hard to
        # read on the light theme / 继承主题前景色（旧 #BBBBBB 亮色下难读）
        self._lbl_update_info.setStyleSheet("font-size: 12px;")
        self._lbl_update_info.setText(text)

    def _info_error(self, text):
        self._lbl_update_info.setStyleSheet(
            "color: #E5533D; font-size: 12px;")
        self._lbl_update_info.setText(text)

    def _on_check_finished(self, ok, version, url, size, err_key, detail):
        self._btn_check.setEnabled(True)
        if not ok:
            # No download button when the check failed or there is no update /
            # 检查失败或没有更新时不显示下载按钮
            self._btn_download.setVisible(False)
            msg = tr(err_key)
            if detail:
                msg += f"\n({detail})"
            self._info_error(msg)
            return
        self._latest_version = version
        self._latest_size = size
        if version is not None and cmp_version(version, parse_version(__version__)) > 0:
            size_mb = size / 1024 / 1024 if size else 0
            self._btn_download.setVisible(True)
            self._btn_download.setEnabled(True)
            self._info_normal(tr(
                "update_found", version=".".join(str(x) for x in version),
                size=f"{size_mb:.1f} MB"))
        else:
            # Already the newest version: hide the download button /
            # 已是最新版本：隐藏下载按钮
            self._btn_download.setVisible(False)
            self._info_normal(tr("update_latest"))

    def _on_download_update(self):
        if self._update_mgr.latest_info() is None:
            return
        name = f"GIFManager-Setup-{self._latest_version[0]}." \
               f"{self._latest_version[1]}.{self._latest_version[2]}.exe"
        dest = os.path.join(_download_dir(), name)
        self._btn_download.setEnabled(False)
        self._btn_dl_cancel.setVisible(True)
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._info_normal(tr("update_downloading", name=name))
        self._update_mgr.download_update(dest)

    def _on_cancel_download(self):
        # Abort the in-flight download (single-stream or parallel segments).
        # The manager cleans up the half-written file via its own paths.
        # 中止进行中的下载（单流或并行分段）。管理器自身清理半成品文件。
        self._btn_dl_cancel.setVisible(False)
        self._btn_dl_cancel.setEnabled(False)
        self._update_mgr.cancel_download()

    def _on_dl_progress(self, received, total):
        if total > 0:
            # Clamp to 100: a single progress signal may report slightly
            # above total on the final chunk. / 钳制到 100：最后一块的单个
            # 进度信号可能略超总量。
            self._progress.setValue(min(100, int(received * 100 / total)))

    def _on_dl_done(self, ok, path_or_err):
        self._btn_download.setEnabled(True)
        self._btn_dl_cancel.setVisible(False)
        self._btn_dl_cancel.setEnabled(True)
        self._progress.setVisible(False)
        if not ok:
            key, _, detail = path_or_err.partition("|")
            msg = tr(key)
            if detail:
                msg += f"\n({detail})"
            self._info_error(msg)
            return
        self._info_normal(tr("update_downloaded", path=path_or_err))
        # Confirm before launching the installer: the file came from the
        # network, so auto-executing it without a prompt is a code-injection
        # surface. / 启动安装程序前确认：文件来自网络，未经确认自动执行是
        # 代码注入面。
        from PySide6.QtWidgets import QMessageBox
        ret = QMessageBox.question(
            self, tr("update_launch_title"),
            tr("update_launch_confirm", path=path_or_err),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        from PySide6.QtCore import QProcess
        if not QProcess.startDetached(path_or_err, []):
            self._info_error(tr("update_launch_fail", path=path_or_err))

    def _build_about_page(self):
        w = self._page_widget()
        layout = self._page_layout
        layout.setSpacing(8)

        # Logo (from the app icon icon.ico) / Logo（程序图标 icon.ico）
        logo = QLabel()
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "icon.ico",
        )
        pix = QPixmap(icon_path)
        if not pix.isNull():
            logo.setPixmap(pix.scaled(
                72, 72,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo)

        name = QLabel("GIFManager")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setStyleSheet("font-size: 20px; font-weight: bold; color: #1677FF;")
        layout.addWidget(name)

        ver = QLabel(f"Version {__version__}")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver.setStyleSheet("color: #888888; font-size: 12px;")
        layout.addWidget(ver)

        dev = QLabel("Developer: LwoSnow")
        dev.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(dev)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #555555;")
        layout.addWidget(line)

        # MIT license text (full, scrollable) / MIT 许可声明（完整文本，可滚动查看）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # Hide the horizontal scrollbar: long English words must wrap, not
        # stretch the page sideways (the bar appears in the English UI)
        # 隐藏横向滚动条：长英文应换行而非横向撑开页面（英文界面下会出现横条）
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        mit_container = QWidget()
        mit_layout = QVBoxLayout(mit_container)
        mit_layout.setContentsMargins(4, 4, 4, 4)
        mit = QLabel(
            "MIT License\n"
            "Copyright (c) 2026 LwoSnow\n\n"
            "Permission is hereby granted, free of charge, to any person "
            "obtaining a copy of this software and associated documentation "
            "files (the \"Software\"), to deal in the Software without "
            "restriction, including without limitation the rights to use, "
            "copy, modify, merge, publish, distribute, sublicense, and/or "
            "sell copies of the Software, and to permit persons to whom the "
            "Software is furnished to do so, subject to the following "
            "conditions:\n\n"
            "The above copyright notice and this permission notice shall be "
            "included in all copies or substantial portions of the "
            "Software.\n\n"
            "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY "
            "KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE "
            "WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE "
            "AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT "
            "HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, "
            "WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING "
            "FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR "
            "OTHER DEALINGS IN THE SOFTWARE."
        )
        mit.setWordWrap(True)
        mit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mit.setStyleSheet("color: #888888; font-size: 11px;")
        mit_layout.addWidget(mit)
        mit_layout.addStretch()
        scroll.setWidget(mit_container)
        layout.addWidget(scroll, 1)
        return w

    # Performance page: worker thread count
    # 性能：多线程核心数
    def _build_perf_page(self):
        w = self._page_widget()
        self._perf_group = QGroupBox(tr("perf_group"))
        perf_layout = QVBoxLayout(self._perf_group)
        self._perf_hint = QLabel(tr("perf_hint"))
        self._perf_hint.setStyleSheet("color: #888; font-size: 11px;")
        self._perf_hint.setWordWrap(True)
        perf_layout.addWidget(self._perf_hint)
        row = QHBoxLayout()
        self._label_threads = QLabel(tr("thread_count"))
        row.addWidget(self._label_threads)
        self._spin_threads = QSpinBox()
        max_cores = max(1, (os.cpu_count() or 4))
        self._spin_threads.setRange(1, max_cores)
        self._spin_threads.setValue(self._thread_count)
        self._spin_threads.setFixedWidth(72)
        row.addWidget(self._spin_threads)
        self._label_threads_unit = QLabel(tr("thread_count_unit"))
        row.addWidget(self._label_threads_unit)
        row.addStretch()
        perf_layout.addLayout(row)
        self._page_layout.addWidget(self._perf_group)
        self._page_layout.addStretch()
        return self._wrap_scroll(w)

    def _on_ok(self):
        self._mode = 0 if self._rb_file.isChecked() else 1
        self._remember_group = self._cb_remember.isChecked()
        self._autostart = self._cb_autostart.isChecked()
        self._always_on_top = self._cb_top.isChecked()
        self._text_limit_single = self._spin_single.value()
        self._text_limit_multi = self._spin_multi.value()
        self._thread_count = self._spin_threads.value()
        self._gs_enabled = self._cb_gs.isChecked()
        self._gs_by = self._combo_gs_by.currentData()
        self._gs_desc = bool(self._combo_gs_dir.currentData())
        self._auto_convert_gif = self._cb_auto_convert.isChecked()
        self._auto_update = self._cb_auto_update.isChecked()
        if self._slider_size is not None:
            self._emoji_size = self._slider_size.value()
        if self._spin_name_font is not None:
            self._name_font_size = self._spin_name_font.value()
        self._lang = self._lang_combo.currentData()
        txt = self._hotkey_capture.text()
        mods, vk = self._hotkey_capture.hotkey_info()
        if txt == tr("hotkey_unset"):
            self._hotkey_mods = 0
            self._hotkey_vk = 0
            self._hotkey_changed = True
        elif mods != 0 or vk != 0:
            self._hotkey_mods = mods
            self._hotkey_vk = vk
            self._hotkey_changed = True
        else:
            self._hotkey_changed = False
        self.accept()

    # Refresh all UI texts after a language switch (keeps current control values)
    # 语言切换后刷新全部界面文本（保留当前控件值）
    def refresh_translations(self):
        self.setWindowTitle(tr("settings"))
        self._title_label.setText(tr("settings"))
        # The list has 7 items (general/send/hotkey/text/perf/update/about);
        # a mismatched key list used to set "Update" to the "About" text and
        # left "About" stale / 列表共 7 项（通用/发送/快捷键/文字/性能/更新/关于）；
        # 此前键列表与列表错位，导致"更新"被写成"关于"且"关于"不刷新
        keys = ("cat_general", "cat_send", "cat_hotkey", "cat_text",
                "cat_perf", "cat_update", "cat_about")
        for i, key in enumerate(keys):
            item = self._cat_list.item(i)
            if item is not None:
                item.setText(tr(key))
        # General page / 通用页
        self._theme_group.setTitle(tr("theme_group"))
        # Theme combo option texts / 主题下拉选项文本
        for i in range(self._theme_combo.count()):
            key = "theme_dark" if self._theme_combo.itemData(i) == "dark" else "theme_light"
            self._theme_combo.setItemText(i, tr(key))
        self._zoom_group.setTitle(tr("hover_zoom_group"))
        self._cb_hover_preview.setText(tr("hover_preview_enable"))
        self._label_zoom.setText(tr("hover_zoom"))
        self._lang_group.setTitle(tr("language_group"))
        self._other_group.setTitle(tr("other_group"))
        self._cb_remember.setText(tr("remember_group"))
        self._cb_autostart.setText(tr("autostart"))
        self._cb_top.setText(tr("always_on_top"))
        self._cb_show_name.setText(tr("show_emoji_name"))
        self._gs_title.setText(tr("global_sort_group"))
        self._cb_gs.setText(tr("global_sort_enable"))
        self._gs_hint.setToolTip(tr("global_sort_hint"))
        self._label_gs_by.setText(tr("global_sort_by"))
        self._label_gs_dir.setText(tr("global_sort_dir"))
        for i in range(self._combo_gs_by.count()):
            key = {"time": "sort_by_time", "name": "sort_by_name",
                   "freq": "sort_by_freq"}[self._combo_gs_by.itemData(i)]
            self._combo_gs_by.setItemText(i, tr(key))
        for i in range(self._combo_gs_dir.count()):
            key = "sort_dir_asc" if self._combo_gs_dir.itemData(i) is False \
                else "sort_dir_desc"
            self._combo_gs_dir.setItemText(i, tr(key))
        self._log_group.setTitle(tr("logs_group"))
        self._btn_clear_logs.setText(tr("clear_logs"))
        # Send page / 发送页
        self._send_group.setTitle(tr("send_mode"))
        self._label_file.setText(tr("send_mode_file"))
        self._label_image.setText(tr("send_mode_image"))
        self._auto_input_group.setTitle(tr("auto_input_group"))
        self._cb_auto_input.setText(tr("auto_input_enable"))
        self._ai_hint.setText(tr("auto_input_hint"))
        self._conv_group.setTitle(tr("gif_conv_group"))
        self._cb_auto_convert.setText(tr("gif_auto_convert"))
        self._conv_hint.setText(tr("gif_auto_convert_hint"))
        self._btn_convert_library.setText(tr("gif_convert_all"))
        self._lbl_current.setText(tr("update_current", version=__version__))
        self._cb_auto_update.setText(tr("update_auto"))
        self._btn_check.setText(tr("update_check"))
        self._btn_download.setText(tr("update_download"))
        # Hotkey page / 快捷键页
        self._hotkey_group.setTitle(tr("hotkey_group"))
        self._hotkey_hint.setText(tr("hotkey_hint"))
        self._hotkey_capture.setPlaceholderText(tr("hotkey_capture_hint"))
        if self._hotkey_capture.text() in (tr("hotkey_unset"), tr("hotkey_capturing"),
                                           tr("hotkey_capture_hint")):
            self._hotkey_capture.setText(tr("hotkey_unset"))
        # Text page / 文字页
        self._text_group.setTitle(tr("text_preview_group"))
        self._label_single.setText(tr("text_preview_single"))
        self._label_multi.setText(tr("text_preview_multi"))
        # Performance page / 性能页
        self._perf_group.setTitle(tr("perf_group"))
        self._perf_hint.setText(tr("perf_hint"))
        self._label_threads.setText(tr("thread_count"))
        self._label_threads_unit.setText(tr("thread_count_unit"))
        # Buttons / 按钮
        self._btn_ok.setText(tr("ok"))
        self._btn_cancel.setText(tr("cancel"))
        self._btn_apply.setText(tr("apply"))
        # Relayout so longer English texts get full width (avoids truncation
        # like "Dark mo" when switching language without reopening)
        # 强制重新布局：更长的英文文本获得完整宽度（避免如 "Dark mo" 截断）
        self._theme_combo.updateGeometry()
        self.layout().invalidate()
        self.layout().activate()

    def send_mode(self):
        return 0 if self._rb_file.isChecked() else 1

    def remember_group(self):
        return self._cb_remember.isChecked()

    # Read current hotkey live (also effective on Apply)
    # 实时读取当前快捷键（Apply 时也生效）
    def hotkey_info(self):
        txt = self._hotkey_capture.text()
        mods, vk = self._hotkey_capture.hotkey_info()
        if txt == tr("hotkey_unset"):
            return (0, 0)
        if mods != 0 or vk != 0:
            return (mods, vk)
        return None

    def language(self):
        return self._lang_combo.currentData()

    def theme(self):
        return self._theme_combo.currentData()

    # Global sorting mode getters / 全局排序模式取值器
    def global_sort_enabled(self):
        return self._gs_enabled

    def global_sort_by(self):
        return self._gs_by

    def global_sort_desc(self):
        return self._gs_desc

    def auto_convert_gif(self):
        return self._auto_convert_gif

    def auto_input(self):
        return self._cb_auto_input.isChecked()

    def auto_update(self):
        return self._auto_update

    def _on_convert_all(self):
        # Emit a signal so MainWindow runs the conversion (it owns the progress
        # dialog and the data manager). / 发出信号由主窗口执行转换（进度条与数据管理在主窗口）
        self.convert_library_requested.emit()

    def autostart(self):
        return self._cb_autostart.isChecked()

    def always_on_top(self):
        return self._cb_top.isChecked()

    def show_emoji_name(self):
        return self._cb_show_name.isChecked()

    def hover_zoom(self):
        return self._spin_zoom.value() / 100.0

    def hover_preview_enabled(self):
        return self._cb_hover_preview.isChecked()

    def emoji_size(self):
        if self._slider_size is not None:
            return self._slider_size.value()
        return self._emoji_size

    def name_font_size(self):
        if self._spin_name_font is not None:
            return self._spin_name_font.value()
        return self._name_font_size

    def text_limit_single(self):
        return self._spin_single.value()

    def text_limit_multi(self):
        return self._spin_multi.value()

    def thread_count(self):
        # Keep the "0 = automatic" semantics: when the shown value equals the
        # recommended default, persist 0 instead of freezing the recommendation
        # as an explicit fixed core count / 保留"0 = 自动"语义：当显示值等于
        # 推荐值时持久化 0，而不是把推荐值固化为显式核数
        v = self._spin_threads.value()
        return 0 if v == recommended_thread_count() else v
