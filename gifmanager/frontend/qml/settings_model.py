"""Settings as a schema-driven model QML can render generically.

The Qt Widgets settings page had to hand-build a widget per row and bind it by
name. QML can do better: expose the ROWS as a model, and one delegate renders
every kind of control from the row's declared `kind`. Adding a setting then means
adding one row to `core.settings`'s companion list here — no widget, no binding,
no per-page code.

This is the main reason the settings page is cheap in QML and was expensive in
Widgets: a declarative interface is good at "render this list of things", and the
schema already describes the list.

把设置做成 QML 可通用渲染的 schema 驱动模型。

Qt Widgets 设置页必须为每行手工构建控件并按名称绑定。QML 可以做得更好：把"行"暴露为
模型，由一个委托按行声明的 `kind` 渲染每一种控件。于是新增一项设置只需在此处的列表里
加一行——没有控件、没有绑定、也没有每页的代码。

这正是设置页在 QML 中便宜、而在 Widgets 中昂贵的主要原因：声明式界面擅长"渲染这一串
东西"，而 schema 已经把这一串描述好了。
"""
import dataclasses
import json
import logging
import os

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    Property,
    Qt,
    Signal,
    Slot,
)

from gifmanager.core import settings as schema

log = logging.getLogger("GIFManager")

# Control kinds, mirroring the Qt Widgets page so the two front-ends describe the
# same schema the same way.
# 控件类型，与 Qt Widgets 页面一致，使两个前端以相同方式描述同一 schema。
KIND_BOOL = "bool"
KIND_INT = "int"
KIND_PERCENT = "percent"
KIND_CHOICE = "choice"
KIND_TEXT = "text"
KIND_HOTKEY = "hotkey"
KIND_FILE = "file"

PERCENT_SCALE = 100.0


@dataclasses.dataclass(frozen=True)
class SettingRow:
    # One editable setting.
    #
    # `field` is an `AppSettings` attribute name, which is also the storage key,
    # so a row cannot silently point at a setting that does not exist.
    # 一项可编辑设置。
    #
    # `field` 是 `AppSettings` 的属性名，同时也是存储键，因此一行不可能悄悄指向一个
    # 不存在的设置。
    field: str
    kind: str
    label_key: str
    hint_key: str = ""
    choices: tuple = ()
    minimum: object = None
    maximum: object = None
    capability: str = ""
    restart: bool = False


@dataclasses.dataclass(frozen=True)
class SettingsGroup:
    # A titled block of rows inside a category / 分类内一个带标题的行块
    title_key: str
    rows: tuple


@dataclasses.dataclass(frozen=True)
class SettingsCategory:
    # One entry in the settings navigation / 设置导航中的一项
    category_id: str
    title_key: str
    groups: tuple


def _choice(value, label_key):
    return (value, label_key)


# The categories, in navigation order. Mirrors the ORIGINAL project's dialog
# (通用/发送/热键/文字/性能)，so a user of that application finds every setting in the
# same tab as before.
# 分类，按导航顺序。对应原项目对话框（通用/发送/热键/文字/性能），使原项目的用户在同样的
# 标签页里找到同一项设置。
CATEGORIES = (
    SettingsCategory("general", "cat_general", (
        SettingsGroup("theme_group", (
            SettingRow("theme", KIND_CHOICE, "theme_group", choices=(
                _choice("dark", "theme_dark"),
                _choice("light", "theme_light"))),
            SettingRow("language", KIND_CHOICE, "language_group"),
        )),
        SettingsGroup("display_group", (
            SettingRow("show_emoji_name", KIND_BOOL, "show_emoji_name"),
            SettingRow("name_font_size", KIND_INT, "name_font_size"),
        )),
        SettingsGroup("card_size_group", (
            SettingRow("card_scale", KIND_PERCENT, "card_size",
                       hint_key="card_size_hint"),
            SettingRow("hover_preview_enabled", KIND_BOOL,
                       "hover_preview_enable"),
            SettingRow("hover_zoom", KIND_PERCENT, "hover_zoom"),
        )),
        SettingsGroup("other_group", (
            SettingRow("remember_group", KIND_BOOL, "remember_group"),
            SettingRow("always_on_top", KIND_BOOL, "always_on_top"),
            SettingRow("autostart", KIND_BOOL, "autostart",
                       capability=schema.CAPABILITY_AUTOSTART),
            SettingRow("auto_update", KIND_BOOL, "update_auto"),
        )),
        SettingsGroup("global_sort_group", (
            SettingRow("global_sort_enabled", KIND_BOOL, "global_sort_enable"),
            SettingRow("global_sort_by", KIND_CHOICE, "global_sort_by", choices=(
                _choice("time", "sort_by_time"),
                _choice("name", "sort_by_name"),
                _choice("freq", "sort_by_freq"))),
            SettingRow("global_sort_desc", KIND_BOOL, "global_sort_desc"),
        )),
    )),
    SettingsCategory("sending", "cat_send", (
        SettingsGroup("send_mode", (
            SettingRow("send_mode", KIND_CHOICE, "send_mode", choices=(
                _choice(schema.SEND_MODE_FILE, "send_mode_file"),
                _choice(schema.SEND_MODE_IMAGE, "send_mode_image"))),
            SettingRow("auto_input", KIND_BOOL, "auto_input_enable",
                       hint_key="auto_input_hint",
                       capability=schema.CAPABILITY_AUTO_INPUT),
        )),
        SettingsGroup("gif_conv_group", (
            SettingRow("auto_convert_gif", KIND_BOOL, "gif_auto_convert"),
            SettingRow("ffmpeg_enabled", KIND_BOOL, "ffmpeg_enable"),
            SettingRow("ffmpeg_path", KIND_FILE, "ffmpeg_path",
                       hint_key="ffmpeg_path_hint"),
        )),
    )),
    SettingsCategory("hotkey", "cat_hotkey", (
        SettingsGroup("hotkey_group", (
            SettingRow("hotkey", KIND_HOTKEY, "hotkey_group",
                       hint_key="hotkey_hint",
                       capability=schema.CAPABILITY_GLOBAL_HOTKEY),
        )),
    )),
    SettingsCategory("text", "cat_text", (
        SettingsGroup("text_preview_group", (
            SettingRow("text_preview_limit_single", KIND_INT,
                       "text_preview_single"),
            SettingRow("text_preview_limit_multi", KIND_INT,
                       "text_preview_multi"),
        )),
    )),
    SettingsCategory("performance", "cat_perf", (
        SettingsGroup("perf_threads", (
            # `restart=True`: the value reaches the native library as `RAYON_NUM_THREADS`
            # when the backend is built, and rayon sizes its pool once. The row therefore
            # tells the user a restart is needed instead of pretending the change took
            # effect immediately.
            # `restart=True`：该值在后端构建时以 `RAYON_NUM_THREADS` 到达原生库，而 rayon
            # 只决定一次池大小。因此该行告诉用户需要重启，而不是假装改动立即生效。
            SettingRow("thread_count", KIND_INT, "thread_count",
                       hint_key="thread_count_hint", restart=True),
            SettingRow("gif_render_mode", KIND_CHOICE, "gif_render_group",
                       choices=(
                           _choice(schema.RENDER_AUTO, "gif_render_auto"),
                           _choice("manual", "gif_render_manual"))),
            SettingRow("gif_render_count", KIND_INT, "gif_render_count"),
        )),
        SettingsGroup("gpu_group", (
            SettingRow("gpu_accel", KIND_BOOL, "gpu_accel_enable",
                       hint_key="gpu_accel_hint"),
            SettingRow("gpu_pref", KIND_CHOICE, "gpu_pref", choices=(
                _choice(0, "gpu_pref_system"),
                _choice(2, "gpu_pref_high"),
                _choice(1, "gpu_pref_power")),
                capability=schema.CAPABILITY_GPU_PREFERENCE),
            SettingRow("gpu_viewport", KIND_BOOL, "gpu_viewport_enable",
                       hint_key="gpu_viewport_hint", restart=True,
                       capability=schema.CAPABILITY_GPU_VIEWPORT),
        )),
    )),
)

# Fields deliberately absent from the UI, with the reason. Listed so "why is this
# setting not editable" has an answer.
# 刻意不出现在界面上的字段及其原因。列出它们使"为什么这项不可编辑"有答案。
HIDDEN_FIELDS = {
    "window_geometry": "front-end session state",
    "last_group_name": "front-end session state",
    "gpu_adapters": "cached probe result",
}

# Fallback numeric bounds when a row does not declare its own, so a control never
# offers a range the schema would then reject.
# 行未声明自身范围时使用的数值兜底，使控件绝不会提供一个 schema 随后会拒绝的范围。
DEFAULT_BOUNDS = {
    "name_font_size": (schema.NAME_FONT_MIN, schema.NAME_FONT_MAX),
    "text_preview_limit_single": (schema.TEXT_LIMIT_MIN, schema.TEXT_LIMIT_MAX),
    "text_preview_limit_multi": (schema.TEXT_LIMIT_MIN, schema.TEXT_LIMIT_MAX),
    "thread_count": (0, schema.THREAD_COUNT_MAX),
    "gif_render_count": (0, schema.GIF_RENDER_COUNT_MAX),
    "card_scale": (schema.CARD_SCALE_MIN, schema.CARD_SCALE_MAX),
    "hover_zoom": (schema.HOVER_ZOOM_MIN, schema.HOVER_ZOOM_MAX),
}

# Rows that are editable only while another setting is in a particular state, so a
# dependent control cannot be edited while its master is off.
#
# Imported from the Qt Widgets page rather than declared again: a rule with two
# copies is a rule that will disagree with itself, and the two front-ends describe
# the same schema.
# 仅在另一项设置处于特定状态时可编辑的行，使主开关关闭时依赖它的控件无法被编辑。
#
# 从 Qt Widgets 页面导入而非再次声明：有两份副本的规则迟早会自相矛盾，而两个前端描述的
# 是同一份 schema。
from gifmanager.frontend.qt.views.settings import (  # noqa: E402
    DEPENDENT_ON,
    dependent_enabled,
)


def rows_of(category_id):
    for category in CATEGORIES:
        if category.category_id == category_id:
            return [row for group in category.groups for row in group.rows]
    return []


def row_for(field):
    for category in CATEGORIES:
        for group in category.groups:
            for row in group.rows:
                if row.field == field:
                    return row
    return None


def bounds_for(row):
    explicit = (row.minimum, row.maximum)
    if explicit[0] is not None and explicit[1] is not None:
        return explicit
    return DEFAULT_BOUNDS.get(row.field, (0, 1_000_000))


class SettingsRowModel(QAbstractListModel):
    # The rows of ONE category, rendered by a single QML delegate that switches on
    # `kind`. The model carries display metadata as well as the value, so the
    # delegate never has to consult the schema.
    # "单个"分类的行，由同一个 QML 委托按 `kind` 分支渲染。模型同时携带值、显示元数据
    # 与可用性，使委托无需查阅 schema。

    FieldRole = Qt.ItemDataRole.UserRole + 1
    KindRole = Qt.ItemDataRole.UserRole + 2
    LabelRole = Qt.ItemDataRole.UserRole + 3
    HintRole = Qt.ItemDataRole.UserRole + 4
    GroupRole = Qt.ItemDataRole.UserRole + 5
    ValueRole = Qt.ItemDataRole.UserRole + 6
    ChoicesRole = Qt.ItemDataRole.UserRole + 7
    MinimumRole = Qt.ItemDataRole.UserRole + 8
    MaximumRole = Qt.ItemDataRole.UserRole + 9
    EnabledRole = Qt.ItemDataRole.UserRole + 10
    RestartRole = Qt.ItemDataRole.UserRole + 11
    ChoicesReadyRole = Qt.ItemDataRole.UserRole + 12

    valueEdited = Signal(str, "QVariant")
    structureChanged = Signal()

    def __init__(self, adapter, parent=None):
        super().__init__(parent)
        self._adapter = adapter
        self._category_id = CATEGORIES[0].category_id
        self._rows = []
        self._values = {}
        self._capabilities = {}
        self._revision = 0
        # Edits held for the dialog's 应用/确认 buttons. A control edit lands
        # here (and in the display) instead of the store, so 取消 can revert and
        # 应用 commits in one pass — the original dialog's exact contract.
        # 为对话框的"应用/确认"按钮暂存的编辑。控件编辑落到这里（与显示）而非存储，
        # 使"取消"可回退、"应用"一次提交——与原对话框的契约完全一致。
        self._pending = {}
        self._effective = schema.AppSettings()

    def roleNames(self):
        return {
            self.FieldRole: b"field",
            self.KindRole: b"kind",
            self.LabelRole: b"label",
            self.HintRole: b"hint",
            self.GroupRole: b"groupTitle",
            self.ValueRole: b"value",
            self.ChoicesRole: b"choices",
            self.MinimumRole: b"minimum",
            self.MaximumRole: b"maximum",
            self.EnabledRole: b"capabilityEnabled",
            self.RestartRole: b"restartRequired",
            self.ChoicesReadyRole: b"hasChoices",
        }

    # ---- structure / 结构 ------------------------------------------------

    @Property(str, notify=structureChanged)
    def categoryId(self):
        # `notify=structureChanged`, not a bare `Property(str)`.
        #
        # A property with no notify signal is NOT BINDABLE, and QML says so once:
        #
        #     QQmlExpression: Expression SettingsPage.qml:79 depends on non-bindable
        #     properties: SettingsRowModel::categoryId
        #
        # The symptom is that the settings navigation does not follow a category change: the
        # expression is evaluated once and never re-evaluated. `setCategory` emits through
        # `reload()`, which emits `structureChanged`, so the signal was already being sent —
        # it simply was not declared as this property's notification.
        # 用 `notify=structureChanged` 而不是裸的 `Property(str)`。
        #
        # 没有 notify 信号的属性"不可绑定"，而 QML 会说明一次：
        #
        #     QQmlExpression: Expression SettingsPage.qml:79 depends on non-bindable
        #     properties: SettingsRowModel::categoryId
        #
        # 症状是设置导航不跟随分类变更：表达式只求值一次，之后不再重新求值。`setCategory` 经
        # `reload()` 发出信号，而后者发出 `structureChanged`，因此信号本就在发——只是没有声明为
        # 本属性的通知信号。
        return self._category_id

    @Property("QStringList", notify=structureChanged)
    def categoryIds(self):
        return [category.category_id for category in CATEGORIES]

    @Property("QStringList", notify=structureChanged)
    def categoryTitles(self):
        # NOT `constant=True`: the titles are translated, and a language change
        # must re-evaluate this property. Declaring it constant would freeze the
        # navigation in whichever language happened to be active at first read.
        # "不是" `constant=True`：标题是翻译过的，语言变更必须让该属性重新求值。声明为
        # constant 会把导航冻结在首次读取时恰好生效的语言上。
        return [self._adapter.tr(category.title_key) for category in CATEGORIES]

    @Slot(str)
    def setCategory(self, category_id):
        if category_id == self._category_id and self._rows:
            return
        self._category_id = category_id
        self.reload()

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._rows)

    @Slot()
    def load(self):
        # Take the values from the backend and the capabilities from the platform,
        # then rebuild. Called on activation so the page shows what is really
        # stored rather than what a previous edit left in memory. Pending edits
        # are discarded: the dialog opening is a fresh read of the store.
        # 从后端取值、从平台取能力，然后重建。激活时调用，使页面显示真正存储的内容，而不是
        # 上次编辑留在内存里的内容。待定编辑被丢弃：对话框打开即是对存储的一次新读取。
        self._pending = {}
        self._values = schema.to_mapping(self._adapter.load_settings())
        report = self._adapter.platform_report()
        self._capabilities = dict(report.get("capabilities", {}))
        self._effective = schema.from_mapping(dict(self._values))
        self.reload()

    @Slot()
    def reload(self):
        self.beginResetModel()
        self._rows = []
        for group in self._groups_for_category():
            for row in group.rows:
                self._rows.append((group.title_key, row))
        self.endResetModel()

    def _groups_for_category(self):
        for category in CATEGORIES:
            if category.category_id == self._category_id:
                return category.groups
        return ()

    # ---- data / 数据 -----------------------------------------------------

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        group_key, row = self._rows[index.row()]
        if role == self.FieldRole:
            return row.field
        if role == self.KindRole:
            return row.kind
        if role == self.LabelRole:
            return self._adapter.tr(row.label_key)
        if role == self.HintRole:
            return self._adapter.tr(row.hint_key) if row.hint_key else ""
        if role == self.GroupRole:
            return self._adapter.tr(group_key)
        if role == self.ValueRole:
            return self._display_value(row)
        if role == self.ChoicesRole:
            return self._choices(row)
        if role == self.MinimumRole:
            low, _high = bounds_for(row)
            if row.kind == KIND_PERCENT:
                return int(float(low) * PERCENT_SCALE)
            return low
        if role == self.MaximumRole:
            _low, high = bounds_for(row)
            if row.kind == KIND_PERCENT:
                return int(float(high) * PERCENT_SCALE)
            return high
        if role == self.EnabledRole:
            return self._enabled(row)
        if role == self.RestartRole:
            return row.restart
        if role == self.ChoicesReadyRole:
            return bool(row.choices)
        return None

    def _display_value(self, row):
        raw = self._current_values().get(row.field)
        if row.kind == KIND_PERCENT:
            # Stored as a factor, edited as a percentage. Converting here rather
            # than in QML keeps the stored unit authoritative in one place.
            # 以系数存储、以百分比编辑。在此转换而非在 QML 里，使"存储单位"只在一处具有
            # 权威性。
            if raw is None:
                raw = 1.0
            return round(float(raw) * PERCENT_SCALE)
        return raw

    def _choices(self, row):
        # (label, stored value) pairs, because QML's ComboBox binds its text and
        # its `currentValue` separately.
        # (标签, 存储值) 对，因为 QML 的 ComboBox 分别绑定其文本与 `currentValue`。
        if row.field == "language":
            # The language list is dynamic (whatever the language manager
            # ships), and a language's name is conventionally shown in its OWN
            # language rather than translated — that is what keeps "简体中文"
            # readable inside the English UI and vice versa.
            # 语言列表是动态的（语言管理器带来什么就有什么），且语言名按惯例以其
            # "自身"语言显示而非翻译——这正是"简体中文"在英文界面里仍可读的原因。
            try:
                from gifmanager.core import lang

                codes = lang.available_languages()
                names = {}
                for code in codes:
                    table_path = os.path.join(
                        lang.manager().lang_dir, f"{code}.json")
                    try:
                        with open(table_path, "r", encoding="utf-8") as handle:
                            table = json.load(handle)
                        names[code] = table.get("name", code)
                    except (OSError, ValueError):
                        names[code] = code
            except Exception:
                log.exception("settings: language list unavailable")
                codes = []
                names = {}
            # The display name comes from EACH LANGUAGE FILE's `name` key, so
            # adding a language needs no code change — the file declares what it
            # calls itself.
            # 显示名来自“各语言文件自己的 name 键”，新增语言无需改代码——文件自己
            # 声明它叫什么。
            return [{"label": names.get(code, code), "value": code}
                    for code in codes]
        return [
            {"label": self._adapter.tr(label_key), "value": value}
            for value, label_key in row.choices
        ]

    def _current_values(self):
        # The values the DIALOG shows: stored values with pending edits merged
        # on top. Dependents (e.g. the render count behind its mode switch) read
        # the same view, so a master's edit un-locks its dependent immediately,
        # before 应用 commits anything.
        # 对话框"显示"的值：存储值之上合并待定编辑。依赖行（如渲染模式之后的渲染数）
        # 读同一视图，使主设置的编辑在"应用"提交之前就立即解锁依赖行。
        merged = dict(self._values)
        merged.update(self._pending)
        return merged

    def _enabled(self, row):
        if row.capability and not self._capabilities.get(row.capability, True):
            return False
        # The dependency rule comes from the shared table, so a change to it cannot
        # leave the two front-ends disagreeing about whether a setting is editable.
        # The check runs against the MERGED view so pending master edits apply live.
        # 依赖规则来自共享表，因此对它的改动不会让两个前端在"某项设置是否可编辑"上产生分歧。
        # 检查针对"合并视图"运行，使待定的主设置编辑实时生效。
        try:
            return dependent_enabled(row.field, self._effective)
        except Exception:
            log.exception("settings: dependency for %s failed", row.field)
            return False

    # ---- editing / 编辑 --------------------------------------------------

    @Slot(str, "QVariant")
    def setValue(self, field, value):
        # Hold one edit for the dialog's 应用/确认 buttons instead of writing the
        # store: the coercion/clamping runs exactly as for a stored value, but the
        # result lands in the pending buffer and the merged view. 取消 drops the
        # buffer; 应用 commits it through `applyPending`.
        # 为对话框的"应用/确认"按钮暂存一次编辑而不写存储：强制转换与钳制与对存储值的
        # 处理完全一致，但结果落入待定缓冲与合并视图。"取消"丢弃缓冲；"应用"经
        # `applyPending` 提交。
        row = row_for(field)
        if row is None:
            log.warning("settings: no row for %r", field)
            return
        if row.kind == KIND_PERCENT:
            try:
                value = round(float(value) / PERCENT_SCALE, 4)
            except (TypeError, ValueError):
                return
        self._pending[field] = value
        mapping = self._current_values()
        self._effective = schema.from_mapping(mapping)
        # Dependent rows (a count behind its mode switch) unlock/unlock live.
        # 依赖行（模式开关之后的数量）实时解锁/锁定。
        self._refresh_enabled()
        # The counter must actually advance: a `notify` signal that fires while
        # the property returns the same value leaves a QML binding cached, which is
        # how a "refresh" button ends up doing nothing.
        # 计数器必须真的自增：若 notify 信号触发时属性仍返回相同值，QML 绑定会保持缓存，
        # 这正是"刷新"按钮毫无效果的原因。
        self._revision += 1
        self.valueEdited.emit(field, value)

    @Slot()
    def applyPending(self):
        # Commit every pending edit to the store in ONE pass, so the backend sees
        # a single settings change (and fires one notification) for 确认/应用.
        # 把所有待定编辑一次提交到存储，使后端对"确认/应用"只见一次设置变更（一次通知）。
        if not self._pending:
            return
        mapping = dict(self._values)
        mapping.update(self._pending)
        updated = schema.from_mapping(mapping)
        self._pending = {}
        self._adapter.apply_settings(updated)
        self._values = schema.to_mapping(self._adapter.settings)
        self._effective = schema.from_mapping(dict(self._values))
        self._revision += 1
        self.valueEdited.emit("", None)
        self._refresh_enabled()

    @Slot()
    def cancelPending(self):
        # Drop every pending edit and show the stored values again — the 取消
        # button's whole contract.
        # 丢弃所有待定编辑并重新显示存储值——这正是"取消"按钮的全部契约。
        if not self._pending:
            return
        self._pending = {}
        self._effective = schema.from_mapping(dict(self._values))
        self._revision += 1
        self.reload()

    def _refresh_enabled(self):
        if not self._rows:
            return
        self.dataChanged.emit(self.index(0, 0),
                              self.index(len(self._rows) - 1, 0),
                              [self.EnabledRole])

    @Slot()
    def resetToDefaults(self):
        # Reset every setting, not only this category's, because the button says
        # "reset defaults" and a partial reset would be a surprise.
        # 重置"全部"设置而非仅本分类的，因为按钮写的是"恢复默认"，部分重置会让人意外。
        self._adapter.apply_settings(schema.defaults())
        self._revision += 1
        self.load()
        self.valueEdited.emit("", None)

    @Slot(str, result="QVariant")
    def valueOf(self, field):
        return self._values.get(field)

    @Property(int, notify=valueEdited)
    def revision(self):
        # Bumped by every edit so QML can re-read derived values without watching
        # each role. Emitting a signal is also what makes a property binding
        # re-evaluate at all.
        # 每次编辑都自增，使 QML 无需监视每个角色即可重读派生值。发出信号本身也正是让属性
        # 绑定重新求值的前提。
        return self._revision

    @Slot()
    def retranslate(self):
        # The labels and hints are computed in `data`, so notifying the structure
        # is enough to make every delegate re-read them.
        # 标签与提示在 `data` 中计算，因此通知结构变化即可让每个委托重新读取它们。
        self.structureChanged.emit()
        self.reload()


__all__ = [
    "CATEGORIES",
    "DEFAULT_BOUNDS",
    "DEPENDENT_ON",
    "HIDDEN_FIELDS",
    "KIND_BOOL",
    "KIND_CHOICE",
    "KIND_FILE",
    "KIND_HOTKEY",
    "KIND_INT",
    "KIND_PERCENT",
    "KIND_TEXT",
    "PERCENT_SCALE",
    "SettingRow",
    "SettingsCategory",
    "SettingsGroup",
    "SettingsRowModel",
    "bounds_for",
    "row_for",
    "rows_of",
]
