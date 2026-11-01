"""Settings: declarative form specification driven by the settings schema.

The previous release's settings dialog was 1780 lines: a ~35-argument
constructor, seven hand-built pages, and ~30 getters, each reading a widget the
page had to remember to create. Adding a setting meant touching four places, and
forgetting one produced a control that read correctly but never saved.

Here a page declares its rows as data, and a builder turns each row into a widget
bound to a `core.settings.AppSettings` field. Adding a setting means adding a
field (already done in `core/settings.py`) and one row here. The label, the
default, the clamp and the platform gate all come from the schema.

设置：由设置 schema 驱动的声明式表单规范。

此前版本的设置对话框有 1780 行：一个约 35 参数的构造函数、七个手写页面、以及约 30 个
getter，各自读取页面"必须记得创建"的控件。新增一项设置要改四处，而漏掉一处就会产生
一个读取正常但从不保存的控件。

在这里，页面以数据声明其行，由构建器把每行变成一个绑定到
`core.settings.AppSettings` 字段的控件。新增一项设置意味着加一个字段（已在
`core/settings.py` 中完成）和这里的一行。标签、默认值、钳制范围与平台门控全部来自
schema。
"""
import dataclasses
import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from gifmanager.core import settings as schema
from gifmanager.frontend.qt.views.base import View
from gifmanager.frontend.qt.widgets.hotkey_capture import HotkeyCapture

log = logging.getLogger("GIFManager")

# Field kinds a row can have / 行可以拥有的字段类型
KIND_BOOL = "bool"
KIND_INT = "int"
KIND_FLOAT = "float"
KIND_TEXT = "text"
KIND_CHOICE = "choice"
KIND_PERCENT = "percent"
KIND_HOTKEY = "hotkey"
KIND_FILE = "file"

# How a percent row converts to and from its stored value. `hover_zoom` and
# `card_scale` are stored as factors but edited as percentages, which is what the
# user thinks in.
# 百分比行的存储值换算方式。`hover_zoom` 与 `card_scale` 以系数存储，但以百分比编辑
# ——那是用户思考的单位。
PERCENT_SCALE = 100.0


# Rows that are editable only while another setting is in a particular state.
#
# Declared as a module-level table rather than inline in `_sync_gates`, because the
# rule is also needed by tests and by the QML front-end, and a rule with two copies
# is a rule that will disagree with itself.
#
# 仅在另一项设置处于特定状态时可编辑的行。
#
# 声明为模块级表而不是内联在 `_sync_gates` 中，因为该规则也被测试与 QML 前端需要，而有两
# 份副本的规则迟早会自相矛盾。
DEPENDENT_ON = {
    "gif_render_count": "gif_render_mode",
    "ffmpeg_path": "ffmpeg_enabled",
    "gpu_pref": "gpu_accel",
    "gpu_viewport": "gpu_accel",
    "hover_zoom": "hover_preview_enabled",
}

# The value the master must hold for the dependent row to be editable. A master
# that is a choice needs a specific value; a master that is a switch needs `True`.
# 主设置必须持有的取值，依赖行才可编辑。主设置是选择项时需要特定取值；是开关时需要
# `True`。
DEPENDENT_VALUE = {
    "gif_render_count": "manual",
}


def dependent_enabled(field, settings):
    # True when a dependent row's master allows editing it /
    # 依赖行的主设置允许编辑它时为 True
    master = DEPENDENT_ON.get(field)
    if master is None:
        return True
    value = getattr(settings, master, None)
    expected = DEPENDENT_VALUE.get(field, True)
    return value == expected


@dataclasses.dataclass(frozen=True)
class Row:
    # One editable setting.
    #
    # `field` is the `AppSettings` attribute name, which is also the storage key
    # and the translation key source, so a row cannot silently point at a setting
    # that does not exist: `build_form` asserts the field is real.
    # 一项可编辑设置。
    #
    # `field` 是 `AppSettings` 的属性名，同时也是存储键与翻译键来源，因此一行不可能
    # 悄悄指向一个不存在的设置：`build_form` 会断言该字段真实存在。
    field: str
    kind: str
    label_key: str
    # Extra translation key for the row's explanatory hint /
    # 行的说明性提示所用的额外翻译键
    hint_key: str = ""
    # Choice rows only: (stored value, label key) pairs /
    # 仅选择行：(存储值, 翻译键) 对
    choices: tuple = ()
    # Minimum and maximum for numeric rows; None means "take the schema's" /
    # 数值行的最小与最大值；None 表示"取 schema 的"
    minimum: object = None
    maximum: object = None
    # Capability that must be supported for this row to be enabled /
    # 该行可用所需支持的能力
    capability: str = ""
    # True when changing this row needs a restart to take effect /
    # 该行改动需要重启才生效时为 True
    restart: bool = False


@dataclasses.dataclass(frozen=True)
class Page:
    # One settings category / 一个设置分类
    page_id: str
    title_key: str
    sections: tuple


def _choice(value, label):
    return (value, label)


# ---------------------------------------------------------------------------
# The settings pages / 设置页面
# ---------------------------------------------------------------------------
#
# Grouped the way a user thinks about them rather than the way the schema stores
# them, because the schema groups by type (bools, numbers, text) and a user looks
# for "how do I change the card size" rather than "where are the floats".
#
# 按用户思考的方式分组，而不是按 schema 存储的方式——schema 按类型（布尔、数值、文本）
# 分组，而用户找的是"怎么改卡片大小"，不是"浮点数在哪"。
PAGES = (
    Page("appearance", "appearance_group", (
        ("appearance_basic", (
            Row("theme", KIND_CHOICE, "theme_group", choices=(
                _choice("dark", "theme_dark"),
                _choice("light", "theme_light"),
            )),
            Row("language", KIND_CHOICE, "language_group"),
            Row("show_emoji_name", KIND_BOOL, "show_emoji_name"),
            Row("name_font_size", KIND_INT, "name_font_size"),
        )),
        ("appearance_cards", (
            Row("card_scale", KIND_PERCENT, "card_size",
                hint_key="card_size_hint"),
            Row("hover_preview_enabled", KIND_BOOL, "hover_preview_enable"),
            Row("hover_zoom", KIND_PERCENT, "hover_zoom"),
        )),
        ("text_preview_group", (
            Row("text_preview_limit_single", KIND_INT, "text_preview_single"),
            Row("text_preview_limit_multi", KIND_INT, "text_preview_multi"),
        )),
    )),
    Page("sending", "send_group", (
        ("send_mode", (
            Row("send_mode", KIND_CHOICE, "send_mode", choices=(
                _choice(schema.SEND_MODE_FILE, "send_mode_file"),
                _choice(schema.SEND_MODE_IMAGE, "send_mode_image"),
            )),
            Row("auto_input", KIND_BOOL, "auto_input_enable",
                hint_key="auto_input_hint",
                capability=schema.CAPABILITY_AUTO_INPUT),
        )),
        ("gif_conv_group", (
            Row("auto_convert_gif", KIND_BOOL, "gif_auto_convert"),
            Row("ffmpeg_enabled", KIND_BOOL, "ffmpeg_enable"),
            Row("ffmpeg_path", KIND_FILE, "ffmpeg_path",
                hint_key="ffmpeg_path_hint"),
        )),
    )),
    Page("performance", "perf_group", (
        ("perf_threads", (
            Row("thread_count", KIND_INT, "thread_count",
                hint_key="thread_count_hint"),
            Row("gif_render_mode", KIND_CHOICE, "gif_render_group", choices=(
                _choice(schema.RENDER_AUTO, "gif_render_auto"),
                _choice("manual", "gif_render_manual"),
            )),
            Row("gif_render_count", KIND_INT, "gif_render_count"),
        )),
        ("gpu_group", (
            Row("gpu_accel", KIND_BOOL, "gpu_accel_enable",
                hint_key="gpu_accel_hint"),
            Row("gpu_pref", KIND_CHOICE, "gpu_pref", choices=(
                _choice(schema.gpu_pref_system(), "gpu_pref_system"),
                _choice(schema.gpu_pref_high(), "gpu_pref_high"),
                _choice(schema.gpu_pref_power(), "gpu_pref_power"),
            ), capability=schema.CAPABILITY_GPU_PREFERENCE),
            Row("gpu_viewport", KIND_BOOL, "gpu_viewport_enable",
                hint_key="gpu_viewport_hint", restart=True,
                capability=schema.CAPABILITY_GPU_VIEWPORT),
        )),
    )),
    Page("behaviour", "other_group", (
        ("behaviour_window", (
            Row("remember_group", KIND_BOOL, "remember_group"),
            Row("always_on_top", KIND_BOOL, "always_on_top"),
            Row("autostart", KIND_BOOL, "autostart",
                capability=schema.CAPABILITY_AUTOSTART),
            Row("auto_update", KIND_BOOL, "update_auto"),
        )),
        ("hotkey_group", (
            Row("hotkey", KIND_HOTKEY, "hotkey_group",
                hint_key="hotkey_hint",
                capability=schema.CAPABILITY_GLOBAL_HOTKEY),
        )),
        ("global_sort_group", (
            Row("global_sort_enabled", KIND_BOOL, "global_sort_enable"),
            Row("global_sort_by", KIND_CHOICE, "global_sort_by", choices=(
                _choice("time", "sort_by_time"),
                _choice("name", "sort_by_name"),
                _choice("freq", "sort_by_freq"),
            )),
            Row("global_sort_desc", KIND_BOOL, "global_sort_desc"),
        )),
    )),
)


class SettingsView(View):
    # The settings page. Edits a draft and reports changes to the shell.
    # 设置页。编辑一份草稿并把变更上报给外壳。
    VIEW_ID = "settings"
    TITLE_KEY = "settings"
    NAV_KEY = "settings"

    # Emitted with a complete, normalised settings object whenever a control
    # changes. The shell persists it and re-renders whatever it affects, so this
    # view never touches application state itself.
    # 控件变更时发出一个完整、规范化后的设置对象。外壳负责持久化并重新渲染受影响的部分，
    # 因此本视图本身从不触碰应用状态。
    settings_edited = Signal(object)

    def __init__(self, adapter, parent=None):
        super().__init__(adapter, parent)
        self._draft = adapter.settings
        self._controls = {}
        self._rows = {}
        self._page_list = []
        self._page_stack = None
        self._capabilities = {}
        self._build_ui()

    # ---- construction / 构建 --------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QWidget(self)
        layout = QHBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        from PySide6.QtWidgets import QListWidget, QListWidgetItem, QStackedWidget

        self._page_list = QListWidget(self)
        self._page_list.setObjectName("settingsCategories")
        self._page_list.setFixedWidth(150)
        self._page_list.currentRowChanged.connect(self._on_page_changed)
        layout.addWidget(self._page_list)

        self._page_stack = QStackedWidget(self)
        for page in PAGES:
            scroll = QScrollArea(self)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            container = QWidget()
            inner = QVBoxLayout(container)
            inner.setContentsMargins(16, 14, 16, 14)
            inner.setSpacing(12)
            for section_key, rows in page.sections:
                inner.addWidget(self._build_section(section_key, rows))
            inner.addStretch(1)
            scroll.setWidget(container)
            self._page_stack.addWidget(scroll)

            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, page.page_id)
            self._page_list.addItem(item)
        layout.addWidget(self._page_stack, 1)

        outer.addWidget(body, 1)
        outer.addWidget(self._build_footer())

        self._page_list.setCurrentRow(0)

    def _build_footer(self):
        footer = QWidget(self)
        footer.setObjectName("settingsFooter")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        self._status = QLabel("")
        self._status.setObjectName("settingsStatus")
        layout.addWidget(self._status, 1)

        self._btn_reset = QPushButton(self._adapter.tr("reset_defaults"))
        self._btn_reset.clicked.connect(self._on_reset)
        layout.addWidget(self._btn_reset)

        self._btn_reload = QPushButton(self._adapter.tr("reload_settings"))
        self._btn_reload.clicked.connect(self.reload)
        layout.addWidget(self._btn_reload)
        return footer

    def _build_section(self, title_key, rows):
        box = QGroupBox(self._adapter.tr(title_key))
        box.setObjectName("settingsSection")
        form = QFormLayout(box)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight
                               | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        for row in rows:
            if row.field not in {f.name for f in dataclasses.fields(schema.AppSettings)}:
                # A row pointing at a missing field is a programming error, and
                # silently rendering nothing would make it invisible.
                # 指向不存在字段的行是编程错误，而静默不渲染会让它彻底不可见。
                raise KeyError(
                    f"settings row {row.field!r} does not exist in "
                    f"AppSettings / 设置行 {row.field!r} 在 AppSettings 中不存在")
            widget = self._build_control(row)
            self._rows[row.field] = row
            self._controls[row.field] = widget

            label = QLabel(self._adapter.tr(row.label_key))
            label.setObjectName("settingsLabel")
            if row.restart:
                label.setText(label.text() + " *")
                label.setToolTip(self._adapter.tr("restart_required"))
            if row.hint_key:
                label.setToolTip(self._adapter.tr(row.hint_key))
            form.addRow(label, widget)
        return box

    # ---- controls / 控件 -------------------------------------------------

    def _build_control(self, row):
        value = getattr(self._draft, row.field)
        if row.kind == KIND_BOOL:
            widget = QCheckBox()
            widget.setChecked(bool(value))
            widget.toggled.connect(
                lambda checked, f=row.field: self._on_edited(f, bool(checked)))
            return widget

        if row.kind == KIND_INT:
            widget = QSpinBox()
            widget.setRange(self._bound(row, "minimum", 0),
                            self._bound(row, "maximum", 1_000_000))
            widget.setValue(int(value))
            widget.setKeyboardTracking(False)
            widget.valueChanged.connect(
                lambda number, f=row.field: self._on_edited(f, int(number)))
            return widget

        if row.kind == KIND_FLOAT:
            widget = QDoubleSpinBox()
            widget.setDecimals(2)
            widget.setRange(float(self._bound(row, "minimum", 0.0)),
                            float(self._bound(row, "maximum", 1_000_000.0)))
            widget.setValue(float(value))
            widget.setKeyboardTracking(False)
            widget.valueChanged.connect(
                lambda number, f=row.field: self._on_edited(f, float(number)))
            return widget

        if row.kind == KIND_PERCENT:
            return self._build_percent(row, float(value))

        if row.kind == KIND_CHOICE:
            widget = QComboBox()
            for stored, label_key in row.choices:
                widget.addItem(self._adapter.tr(label_key), stored)
            index = widget.findData(value)
            widget.setCurrentIndex(index if index >= 0 else 0)
            widget.currentIndexChanged.connect(
                lambda _index, f=row.field, w=widget:
                self._on_edited(f, w.currentData()))
            return widget

        if row.kind == KIND_HOTKEY:
            widget = HotkeyCapture(value)
            widget.changed.connect(
                lambda binding, f=row.field: self._on_edited(f, binding))
            return widget

        if row.kind == KIND_FILE:
            return self._build_file(row, str(value or ""))

        widget = QLineEdit(str(value or ""))
        widget.textEdited.connect(
            lambda text, f=row.field: self._on_edited(f, text))
        return widget

    def _build_percent(self, row, factor):
        # Stored as a factor, edited as a percentage. The conversion lives in the
        # two lambdas so the draft always holds the STORED unit, which is what
        # keeps the persistence round trip honest.
        # 以系数存储、以百分比编辑。换算放在两个 lambda 里，使草稿始终持有"存储单位"，
        # 这正是持久化往返可信的原因。
        widget = QSpinBox()
        widget.setRange(int(float(self._bound(row, "minimum", 0.5))
                            * PERCENT_SCALE),
                        int(float(self._bound(row, "maximum", 2.0))
                            * PERCENT_SCALE))
        widget.setSingleStep(5)
        widget.setSuffix(" %")
        widget.setValue(int(round(factor * PERCENT_SCALE)))
        widget.setKeyboardTracking(False)
        widget.valueChanged.connect(
            lambda percent, f=row.field:
            self._on_edited(f, round(int(percent) / PERCENT_SCALE, 4)))
        return widget

    def _build_file(self, row, current):
        # A container widget holding the field and a browse button. The row is
        # registered as the CONTAINER, and `_apply_value` reaches the inner
        # `QLineEdit`, so the control stays a single object from the caller's
        # point of view.
        # 一个包含字段与浏览按钮的容器控件。注册的行就是该"容器"，而 `_apply_value`
        # 会取到内部的 `QLineEdit`，因此从调用方看该控件仍是单一对象。
        container = QWidget()
        container.setObjectName("settingsFileRow")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        edit = QLineEdit(current)
        edit.setPlaceholderText(self._adapter.tr("automatic"))
        edit.textEdited.connect(
            lambda text, f=row.field: self._on_edited(f, text))
        layout.addWidget(edit, 1)

        browse = QPushButton(self._adapter.tr("browse"))
        browse.setObjectName("settingsBrowse")
        browse.clicked.connect(
            lambda _checked=False, e=edit: self._browse_file(e))
        layout.addWidget(browse)
        return container

    def _browse_file(self, edit):
        from PySide6.QtWidgets import QFileDialog

        # The filter lists both spellings so a Unix build sees a bare `ffmpeg`
        # rather than only `ffmpeg.exe`, which is what the previous release's
        # Windows-only filter did.
        # 过滤器同时列出两种写法，使 Unix 构建看到裸的 `ffmpeg` 而不只是 `ffmpeg.exe`
        # ——上一版本只列 Windows 写法。
        selected, _filter = QFileDialog.getOpenFileName(
            self, self._adapter.tr("ffmpeg_path"), edit.text(),
            "ffmpeg (ffmpeg ffmpeg.exe);;All files (*)")
        if selected:
            edit.setText(selected)
            self._on_edited("ffmpeg_path", selected)

    @staticmethod
    def _bound(row, which, fallback):
        explicit = getattr(row, which)
        if explicit is not None:
            return explicit
        # Fall back to the schema's own clamp so a row cannot offer a range the
        # schema would then reject, which would look like the control silently
        # refusing input.
        # 回退到 schema 自身的钳制范围，使一行不会提供一个 schema 随后会拒绝的范围——那
        # 会让控件看起来在静默拒绝输入。
        bounds = {
            "name_font_size": (schema.NAME_FONT_MIN, schema.NAME_FONT_MAX),
            "text_preview_limit_single": (schema.TEXT_LIMIT_MIN,
                                          schema.TEXT_LIMIT_MAX),
            "text_preview_limit_multi": (schema.TEXT_LIMIT_MIN,
                                         schema.TEXT_LIMIT_MAX),
            "thread_count": (0, schema.THREAD_COUNT_MAX),
            "gif_render_count": (0, schema.GIF_RENDER_COUNT_MAX),
            "card_scale": (schema.CARD_SCALE_MIN, schema.CARD_SCALE_MAX),
            "hover_zoom": (schema.HOVER_ZOOM_MIN, schema.HOVER_ZOOM_MAX),
        }
        low, high = bounds.get(row.field, (0, 1_000_000))
        return low if which == "minimum" else high

    # ---- draft handling / 草稿处理 ---------------------------------------

    def _on_edited(self, field, value):
        # Rebuild the settings object from its stored mapping rather than mutating
        # it, so every change goes through the schema's coercion and clamping —
        # exactly as a value read from disk would.
        # 从存储映射重建设置对象而不是就地修改，使每次变更都经过 schema 的强制转换与
        # 钳制——与从磁盘读到的取值完全一致。
        mapping = schema.to_mapping(self._draft)
        mapping[field] = value
        self._draft = schema.from_mapping(mapping)
        self._sync_gates()
        self.settings_edited.emit(self._draft)

    def _on_page_changed(self, row):
        if row < 0 or self._page_stack is None:
            return
        self._page_stack.setCurrentIndex(row)

    def _on_reset(self):
        from PySide6.QtWidgets import QMessageBox

        if QMessageBox.question(
                self, self._adapter.tr("reset_defaults"),
                self._adapter.tr("reset_defaults_confirm")
        ) != QMessageBox.StandardButton.Yes:
            return
        self._draft = schema.defaults()
        self._load_into_controls()
        self.settings_edited.emit(self._draft)

    def reload(self):
        # Adopt the persisted settings, discarding unsaved edits /
        # 采用已持久化的设置，丢弃未保存的编辑
        self._draft = self._adapter.load_settings()
        self._load_into_controls()
        self._set_status(self._adapter.tr("settings_reloaded"))

    def _load_into_controls(self):
        # Push the draft into every control, blocking signals so this does not
        # look like a burst of user edits.
        # 把草稿推入每个控件，同时屏蔽信号，使这看起来不像一串用户编辑。
        for field, widget in self._controls.items():
            row = self._rows[field]
            value = getattr(self._draft, field)
            widget.blockSignals(True)
            try:
                self._apply_value(row, widget, value)
            finally:
                widget.blockSignals(False)
        self._sync_gates()

    def _apply_value(self, row, widget, value):
        if row.kind == KIND_BOOL:
            widget.setChecked(bool(value))
        elif row.kind == KIND_INT:
            widget.setValue(int(value))
        elif row.kind == KIND_FLOAT:
            widget.setValue(float(value))
        elif row.kind == KIND_PERCENT:
            widget.setValue(int(round(float(value) * PERCENT_SCALE)))
        elif row.kind == KIND_CHOICE:
            index = widget.findData(value)
            widget.setCurrentIndex(index if index >= 0 else 0)
        elif row.kind == KIND_HOTKEY:
            widget.set_binding(value)
        elif row.kind == KIND_FILE:
            for child in widget.findChildren(QLineEdit):
                child.setText(str(value or ""))
                break
        else:
            widget.setText(str(value or ""))

    # ---- capability gating / 能力门控 ------------------------------------

    def refresh_capabilities(self):
        # Ask the backend what this system can do, once per activation.
        #
        # The point is that a control the platform cannot honour is DISABLED with
        # a reason, rather than present and silently inert — which is what the GPU
        # preference and autostart switches used to be on a non-Windows build.
        # 每次激活时问一次后端本系统能做什么。
        #
        # 要点在于：平台无法兑现的控件会被"禁用"并给出原因，而不是存在却静默无效——
        # 这正是此前 GPU 首选项与开机自启开关在非 Windows 构建上的表现。
        report = self._adapter.platform_report()
        self._capabilities = dict(report.get("capabilities", {}))
        self._sync_gates()

    def _sync_gates(self):
        # A row is enabled when its capability is supported AND its master toggle
        # allows it, so a dependent control cannot be edited while its master is off.
        # 当行的能力受支持"且"其主开关允许时该行可用，因此主开关关闭时依赖它的控件无法被
        # 编辑。
        for field, widget in self._controls.items():
            row = self._rows[field]
            enabled = True
            if row.capability and not self._capabilities.get(row.capability, True):
                enabled = False
            if not dependent_enabled(field, self._draft):
                enabled = False
            widget.setEnabled(enabled)
            if not enabled and row.capability:
                widget.setToolTip(self._adapter.tr("not_supported_here"))

    def _set_status(self, text):
        if hasattr(self, "_status"):
            self._status.setText(text)

    # ---- view protocol / 视图协议 ----------------------------------------

    def activate(self):
        self._draft = self._adapter.load_settings()
        self._load_into_controls()
        self.refresh_capabilities()

    def commands(self):
        from gifmanager.frontend.qt import commands as cmd

        return [
            cmd.define(
                cmd.CMD_SETTINGS, "reset_defaults", self._on_reset,
                surfaces=(cmd.SURFACE_MENU, cmd.SURFACE_PALETTE)),
        ]

    def retranslate(self):
        for index, page in enumerate(PAGES):
            item = self._page_list.item(index)
            if item is not None:
                item.setText(self._adapter.tr(page.title_key))
        # Section titles and row labels are set at build time, so a language
        # change rebuilds the form rather than walking every widget.
        # 分节标题与行标签在构建时设置，因此语言变更通过重建表单完成，而不是遍历每个控件。
        self._rebuild_form()

    def _rebuild_form(self):
        # Keep the current draft and rebuild every page with translated text.
        # Rebuilding is cheap (a few dozen widgets) and removes a whole class of
        # bug where a retranslation path forgets one label.
        # 保留当前草稿并重建每个页面以应用已翻译文本。重建代价很低（几十个控件），且消除
        # 了"重翻译路径漏掉某个标签"这一整类错误。
        draft = self._draft
        current = self._page_list.currentRow()
        self._controls.clear()
        self._rows.clear()
        while self._page_stack.count():
            widget = self._page_stack.widget(0)
            self._page_stack.removeWidget(widget)
            widget.deleteLater()
        self._page_list.clear()
        for page in PAGES:
            scroll = QScrollArea(self)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            container = QWidget()
            inner = QVBoxLayout(container)
            inner.setContentsMargins(16, 14, 16, 14)
            inner.setSpacing(12)
            for section_key, rows in page.sections:
                inner.addWidget(self._build_section(section_key, rows))
            inner.addStretch(1)
            scroll.setWidget(container)
            self._page_stack.addWidget(scroll)
            from PySide6.QtWidgets import QListWidgetItem

            item = QListWidgetItem(self._adapter.tr(page.title_key))
            item.setData(Qt.ItemDataRole.UserRole, page.page_id)
            self._page_list.addItem(item)
        self._draft = draft
        self._load_into_controls()
        self._page_list.setCurrentRow(max(0, current))


__all__ = [
    "KIND_BOOL",
    "KIND_CHOICE",
    "KIND_FILE",
    "KIND_FLOAT",
    "KIND_HOTKEY",
    "KIND_INT",
    "KIND_PERCENT",
    "KIND_TEXT",
    "PAGES",
    "PERCENT_SCALE",
    "Page",
    "Row",
    "SettingsView",
]
