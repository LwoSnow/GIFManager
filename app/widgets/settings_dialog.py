"""Settings dialog — left category navigation + right option pages
设置对话框 — 左侧分类导航 + 右侧选项分页"""
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QRadioButton,
    QPushButton, QGroupBox, QButtonGroup, QDialogButtonBox,
    QCheckBox, QComboBox, QLineEdit, QSpinBox, QListWidget,
    QStackedWidget, QWidget, QFrame, QScrollArea,
)
from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtGui import QKeyEvent, QKeySequence, QMouseEvent

from app.models.lang_manager import tr, current_language, available_languages
from app.widgets.hotkey_manager import key_event_to_hotkey_desc


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

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if not self._capturing:
                self._start_capture()
            else:
                self._stop_capture()
        super().mousePressEvent(event)

    def _start_capture(self):
        self._capturing = True
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
            self.setText(tr("hotkey_unset"))

    def keyPressEvent(self, event: QKeyEvent):
        if not self._capturing:
            super().keyPressEvent(event)
            return
        key = event.key()
        if key == Qt.Key.Key_Escape:
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

    def __init__(self, current_mode=0, remember_group=True, autostart=False,
                 always_on_top=False, text_limit_single=100, text_limit_multi=200,
                 thread_count=0, theme="dark", data_manager=None, hotkey_desc="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("settings"))
        self.setFixedSize(440, 480)
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

    def _apply_rounded(self):
        import sys
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
        title_label = QLabel(tr("settings"))
        # Color is inherited from the active theme
        # 颜色继承主题
        title_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        title_bar.addWidget(title_label)
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
        for key in ("cat_general", "cat_send", "cat_hotkey", "cat_text", "cat_perf"):
            self._cat_list.addItem(tr(key))
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
        self._page_layout.addWidget(self._other_group)

        # Clear logs / 清除日志
        self._log_group = QGroupBox(tr("logs_group"))
        log_layout = QVBoxLayout(self._log_group)
        self._btn_clear_logs = QPushButton(tr("clear_logs"))
        self._btn_clear_logs.clicked.connect(self.clear_logs_requested.emit)
        log_layout.addWidget(self._btn_clear_logs)
        self._page_layout.addWidget(self._log_group)
        self._page_layout.addStretch()
        return w

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
        self._page_layout.addStretch()
        return w

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
        return w

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
        return w

    # About page: logo / name / version / developer / MIT license
    # 信息页：Logo / 名称 / 版本 / 开发者 / MIT 许可。
    # Hardcoded English only, not routed through the language file
    # 纯英文硬编码，不经过语言文件。
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

        ver = QLabel("Version 1.0.1")
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
        return w

    def _on_ok(self):
        self._mode = 0 if self._rb_file.isChecked() else 1
        self._remember_group = self._cb_remember.isChecked()
        self._autostart = self._cb_autostart.isChecked()
        self._always_on_top = self._cb_top.isChecked()
        self._text_limit_single = self._spin_single.value()
        self._text_limit_multi = self._spin_multi.value()
        self._thread_count = self._spin_threads.value()
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
        keys = ("cat_general", "cat_send", "cat_hotkey", "cat_text", "cat_perf", "cat_about")
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
        self._lang_group.setTitle(tr("language_group"))
        self._other_group.setTitle(tr("other_group"))
        self._cb_remember.setText(tr("remember_group"))
        self._cb_autostart.setText(tr("autostart"))
        self._cb_top.setText(tr("always_on_top"))
        self._log_group.setTitle(tr("logs_group"))
        self._btn_clear_logs.setText(tr("clear_logs"))
        # Send page / 发送页
        self._send_group.setTitle(tr("send_mode"))
        self._label_file.setText(tr("send_mode_file"))
        self._label_image.setText(tr("send_mode_image"))
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

    def autostart(self):
        return self._cb_autostart.isChecked()

    def always_on_top(self):
        return self._cb_top.isChecked()

    def text_limit_single(self):
        return self._spin_single.value()

    def text_limit_multi(self):
        return self._spin_multi.value()

    def thread_count(self):
        return self._spin_threads.value()
