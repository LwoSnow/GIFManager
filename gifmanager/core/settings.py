"""Application settings: schema, defaults, validation and migration.

Before the refactor the same 33 keys were spelled out three times — once as
`QSettings` reads with hand-written coercion in `_load_settings`, once as writes
in `_save_settings`, and once as a ~35-argument dialog constructor with its own
clamping — and the three disagreed. Notably `theme`, `language` and
`gpu_adapters` were read without the `type=` argument that the neighbouring keys
used, and floats were wrapped in `try/except` instead of a shared coercion.

Here a setting is declared exactly once, as a dataclass field with its default
and its UI metadata, and everything else is derived from that declaration: the
key list, the validators, the serialisation, the "what changed" diff and the
per-platform capability gate.

应用设置：schema、默认值、校验与迁移。

重构前同样的 33 个键被写了三遍——一遍是 `_load_settings` 里手写强制转换的
`QSettings` 读取，一遍是 `_save_settings` 的写入，一遍是带自己那套钳制逻辑的
约 35 参数对话框构造函数——而且三者互不一致。特别是 `theme`、`language` 与
`gpu_adapters` 没有使用相邻键都用的 `type=` 参数，浮点数则用 `try/except` 而不是
共用的强制转换。

在这里，一项设置只声明一次：一个带默认值与界面元数据的 dataclass 字段，其余一切
都由该声明推导——键清单、校验器、序列化、"改了什么"的差分，以及按平台的能力门控。
"""
import dataclasses
from dataclasses import dataclass, field
from typing import Optional, Tuple

from gifmanager import __version__
from gifmanager.core import hotkeys as hotkey_core
from gifmanager.core import paths

# Default interface language. Kept here rather than in the language layer so a
# settings file with no `language` key still resolves to the shipped default.
# 默认界面语言。放在此处而非语言层，使没有 `language` 键的设置文件仍解析到随包默认值。
DEFAULT_LANGUAGE = "zh_CN"

# ---- enumerations / 枚举 ---------------------------------------------------------

# Theme choices / 主题取值
THEMES = ("dark", "light")
THEME_DARK = "dark"

# Sort keys / 排序键
SORT_KEYS = ("time", "name", "freq")
SORT_TIME = "time"

# GIF render concurrency modes / GIF 渲染并发模式
RENDER_MODES = ("auto", "manual")
RENDER_AUTO = "auto"

# Clipboard send modes: 0 = file path, 1 = image bytes /
# 剪贴板发送模式：0 = 文件路径，1 = 图片字节
SEND_MODE_FILE = 0
SEND_MODE_IMAGE = 1

# ---- bounds / 取值范围 ---------------------------------------------------------------

HOVER_ZOOM_MIN = 1.0
HOVER_ZOOM_MAX = 2.0
CARD_SCALE_MIN = 0.5
CARD_SCALE_MAX = 2.0
NAME_FONT_MIN = 1
NAME_FONT_MAX = 20
TEXT_LIMIT_MIN = 20
TEXT_LIMIT_MAX = 1000
GIF_RENDER_COUNT_MIN = 1
GIF_RENDER_COUNT_MAX = 64
THREAD_COUNT_MIN = 1
THREAD_COUNT_MAX = 64

# ---- platform capabilities / 平台能力 ------------------------------------------------

# Capability names used by `SettingSpec.capability`. A setting whose capability
# the running system does not provide is reported as unavailable so the UI can
# disable it, instead of offering a control that silently does nothing — which
# is exactly what the GPU preference and autostart rows did on non-Windows
# builds.
# `SettingSpec.capability` 使用的能力名。当前系统不提供的能力所对应的设置会被报告
# 为不可用，使界面可以禁用它，而不是提供一个静默无效的控件——这正是此前 GPU 首选项
# 与自启项在非 Windows 构建上的表现。
CAPABILITY_NONE = ""
CAPABILITY_GPU_PREFERENCE = "gpu_preference"
CAPABILITY_GLOBAL_HOTKEY = "global_hotkey"
CAPABILITY_GLOBAL_SCROLL = "global_scroll"
CAPABILITY_AUTOSTART = "autostart"
CAPABILITY_AUTO_INPUT = "auto_input"
CAPABILITY_GPU_VIEWPORT = "gpu_viewport"


def setting(default, label=None, **_kwargs):
    # Field metadata helper. `label` is the translation key used by the settings
    # page; the remaining metadata is descriptive only.
    # 字段元数据辅助。`label` 是设置页使用的翻译键；其余元数据仅作描述。
    return field(default=default, metadata={"label": label})


@dataclass
class AppSettings:
    # Every user-visible setting, typed, defaulted and normalised.
    #
    # Field order groups settings the way the settings pages present them, so a
    # reader can compare this class against the UI one-to-one.
    # 全部用户可见设置，带类型、默认值与规范化。
    #
    # 字段顺序按设置页的呈现方式分组，使读者可以把本类与界面一一对照。
    #
    # `send_mode` is deliberately `int` with the same 0/1 meaning the store's
    # clipboard path expects, because `copy_to_clipboard(mode=...)` takes it
    # directly.
    # `send_mode` 刻意用 `int` 并保持 0/1 含义与存储层的剪贴板路径一致，因为
    # `copy_to_clipboard(mode=...)` 直接接收它。

    # -- appearance / 外观 -------------------------------------------------
    theme: str = setting(THEME_DARK, "theme_group")
    language: str = setting(DEFAULT_LANGUAGE, "language_group")
    show_emoji_name: bool = setting(True, "show_emoji_name")
    name_font_size: int = setting(10, "name_font_size")
    card_scale: float = setting(1.0, "card_size")
    hover_preview_enabled: bool = setting(True, "hover_preview_enable")
    hover_zoom: float = setting(1.15, "hover_zoom")

    # -- text preview / 文字预览 -------------------------------------------
    text_preview_limit_single: int = setting(100, "text_preview_single")
    text_preview_limit_multi: int = setting(200, "text_preview_multi")

    # -- sorting / 排序 ----------------------------------------------------
    global_sort_enabled: bool = setting(False, "global_sort_enable")
    global_sort_by: str = setting(SORT_TIME, "global_sort_by")
    global_sort_desc: bool = setting(False, "global_sort_dir")

    # -- send / 发送 -------------------------------------------------------
    send_mode: int = setting(SEND_MODE_FILE, "send_mode")
    auto_input: bool = setting(True, "auto_input_enable")
    auto_convert_gif: bool = setting(True, "gif_auto_convert")

    # -- conversion / 转换 -------------------------------------------------
    ffmpeg_enabled: bool = setting(True, "ffmpeg_enable")
    ffmpeg_path: str = setting("", "ffmpeg_path")

    # -- performance / 性能 ------------------------------------------------
    thread_count: int = setting(0, "thread_count")
    gif_render_mode: str = setting(RENDER_AUTO, "gif_render_auto")
    gif_render_count: int = setting(0, "gif_render_count")
    gpu_accel: bool = setting(False, "gpu_accel_enable")
    gpu_viewport: bool = setting(False, "gpu_viewport_enable")
    gpu_pref: int = setting(0, "gpu_pref")
    gpu_adapters: Tuple[str, ...] = setting((), "gpu_adapters")

    # -- behaviour / 行为 --------------------------------------------------
    remember_group: bool = setting(True, "remember_group")
    always_on_top: bool = setting(False, "always_on_top")
    autostart: bool = setting(False, "autostart")
    auto_update: bool = setting(False, "update_auto")

    # -- hotkey / 热键 -----------------------------------------------------
    hotkey: hotkey_core.HotkeyBinding = setting(
        hotkey_core.HotkeyBinding(0, hotkey_core.DEFAULT_KEY), "hotkey_group")

    # -- session state / 会话状态 ------------------------------------------
    # Opaque blobs owned by the front-end: Qt stores widget geometry bytes and
    # a group NAME here. A non-Qt front-end stores whatever it needs.
    # 由前端持有的不透明数据：Qt 在这里存控件几何字节与分组"名称"。非 Qt 前端存它
    # 自己需要的东西。
    window_geometry: Optional[bytes] = setting(None, None)
    last_group_name: str = setting("", None)


# Storage keys that differ from the field name, kept so a settings file written
# by an earlier release still loads. / 与字段名不同的存储键，保留它们使旧版本写的
# 设置文件仍能加载。
STORAGE_KEY_OVERRIDES = {
    "hover_preview_enabled": "hover_preview_enabled",
}

# Keys an earlier release wrote that no longer exist. They are read during
# migration and then ignored. / 旧版本写过、现已不存在的键。迁移时读取一次，之后
# 忽略。
LEGACY_KEYS = ("gpu_render", "hotkey_mods", "hotkey_vk")

_FIELDS = {f.name: f for f in dataclasses.fields(AppSettings)}


def defaults():
    # Fresh settings with every default applied / 应用了全部默认值的新设置对象
    return AppSettings()


def storage_key(field_name):
    return STORAGE_KEY_OVERRIDES.get(field_name, field_name)


def all_keys():
    # Every persisted key / 全部持久化键
    return tuple(storage_key(name) for name in _FIELDS)


def label_key(field_name):
    # Translation key for a setting, or None when the setting has no UI row /
    # 某项设置的翻译键；该设置没有界面行时返回 None
    spec = _FIELDS.get(field_name)
    return (spec.metadata.get("label") if spec else None) or None


# ---- coercion / 强制转换 -------------------------------------------------------------

def coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "on"):
        return True
    if text in ("false", "0", "no", "off", ""):
        return False
    return default


def coerce_int(value, default=0, minimum=None, maximum=None):
    # Numeric coercion that survives a dirty settings store.
    #
    # When QSettings reads an integer key whose stored type is a string (a
    # corrupted registry value, or a value written by a different release), Qt
    # returns the raw string; an unguarded `int()` over it used to abort startup.
    # 能在脏设置存储下存活的数值强制转换。
    #
    # 当 QSettings 读取一个存储类型为字符串的整数键时（注册表值损坏，或由其他版本
    # 写入），Qt 返回原始字符串；未加保护的 `int()` 曾因此中断启动。
    try:
        number = int(value)
    except (TypeError, ValueError):
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            number = int(default)
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def coerce_float(value, default=0.0, minimum=None, maximum=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(default)
    if number != number:  # NaN / 非数
        number = float(default)
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def coerce_choice(value, choices, default):
    # Pick a member of `choices`, comparing loosely so a numeric choice stored
    # as a string ("1") still matches its integer member (1). A value outside
    # the set falls back to the default rather than being clamped, because
    # clamping would silently turn an out-of-range enum into a valid-looking
    # one: a corrupt (or future) value would become whatever sits at the edge.
    # 从 `choices` 中选取成员，比较时放宽，使以字符串存储的数字选项（"1"）仍能匹配
    # 其整数成员（1）。集合外的值回退到默认值而不是钳制，因为钳制会把越界的枚举静默
    # 变成一个看似合法的值：一个损坏（或来自未来版本）的值会变成边界上的那一项。
    for choice in choices:
        if value == choice:
            return choice
    for choice in choices:
        if str(value) == str(choice):
            return choice
    return default


def coerce_text(value, default=""):
    return default if value is None else str(value)


def coerce_bytes(value):
    # QSettings returns a QByteArray for the geometry key; accept the portable
    # spellings too so a migrated settings file keeps its geometry.
    # QSettings 为几何键返回 QByteArray；同时接受可移植的写法，使迁移来的设置文件
    # 保留几何信息。
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    data = getattr(value, "data", None)
    if callable(data):
        try:
            return bytes(data())
        except Exception:
            return None
    return None


def coerce_adapters(value):
    # Accept the historical pipe-joined string, a list, or a tuple /
    # 接受历史上以竖线连接的字符串、列表或元组
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        return tuple(part for part in value.split("|") if part)
    try:
        return tuple(str(part) for part in value if str(part))
    except TypeError:
        return ()


def split_label(label):
    # Translation keys are stored as "key" or "key|default" so a language file
    # that has not been updated still shows something readable.
    # 翻译键以 "key" 或 "key|默认文本" 存储，使尚未更新的语言文件也能显示可读内容。
    text = str(label or "")
    if "|" in text:
        key, _, fallback = text.partition("|")
        return key, fallback
    return text, text


# ---- migration / 迁移 ------------------------------------------------------------

def migrate(mapping):
    # Bring a settings mapping written by an earlier release up to date.
    #
    # Two migrations are needed:
    #   * `gpu_render` was the pre-1.0.6 name of the acceleration switch; it is
    #     still written as a mirror so a downgrade keeps working;
    #   * `hotkey_mods` / `hotkey_vk` held Qt-space integers. A `vk` of 0 meant
    #     "unset", and leaving the modifiers behind turned that into a
    #     modifier-only binding, so both are reset together.
    # 把旧版本写入的设置映射升级到当前格式。
    #
    # 需要两个迁移：
    #   * `gpu_render` 是加速开关在 1.0.6 之前的名字；仍然把它作为镜像写出，使降级
    #     也能工作；
    #   * `hotkey_mods` / `hotkey_vk` 存的是 Qt 空间的整数。`vk` 为 0 表示"未设置"，
    #     留着修饰键会把它变成只有修饰键的绑定，因此两者一并重置。
    result = dict(mapping or {})

    if "gpu_accel" not in result and "gpu_render" in result:
        result["gpu_accel"] = result["gpu_render"]

    if "hotkey" not in result and ("hotkey_mods" in result or "hotkey_vk" in result):
        result["hotkey"] = {
            "modifiers": coerce_int(result.get("hotkey_mods"), 0),
            "key": "" if coerce_int(result.get("hotkey_vk"), 0) == 0
            else hotkey_core.DEFAULT_KEY,
        }
    return result


# ---- serialisation / 序列化 --------------------------------------------------------

def from_mapping(mapping):
    # Build settings from a raw key/value mapping, coercing and clamping every
    # field. Unknown keys are ignored; missing keys take their default.
    # 从原始键值映射构建设置，对每个字段做强制转换与钳制。未知键忽略，缺失键取默认值。
    data = migrate(mapping)
    base = AppSettings()
    values = {}

    def raw(field_name):
        return data.get(storage_key(field_name), getattr(base, field_name))

    values["theme"] = coerce_choice(raw("theme"), THEMES, THEME_DARK)
    values["language"] = coerce_text(raw("language"), base.language)
    values["show_emoji_name"] = coerce_bool(raw("show_emoji_name"), True)
    values["name_font_size"] = coerce_int(
        raw("name_font_size"), 10, NAME_FONT_MIN, NAME_FONT_MAX)
    values["card_scale"] = coerce_float(
        raw("card_scale"), 1.0, CARD_SCALE_MIN, CARD_SCALE_MAX)
    values["hover_preview_enabled"] = coerce_bool(
        raw("hover_preview_enabled"), True)
    values["hover_zoom"] = coerce_float(
        raw("hover_zoom"), 1.15, HOVER_ZOOM_MIN, HOVER_ZOOM_MAX)

    values["text_preview_limit_single"] = coerce_int(
        raw("text_preview_limit_single"), 100, TEXT_LIMIT_MIN, TEXT_LIMIT_MAX)
    values["text_preview_limit_multi"] = coerce_int(
        raw("text_preview_limit_multi"), 200, TEXT_LIMIT_MIN, TEXT_LIMIT_MAX)

    values["global_sort_enabled"] = coerce_bool(raw("global_sort_enabled"), False)
    values["global_sort_by"] = coerce_choice(raw("global_sort_by"), SORT_KEYS, SORT_TIME)
    values["global_sort_desc"] = coerce_bool(raw("global_sort_desc"), False)

    values["send_mode"] = coerce_choice(
        raw("send_mode"), (SEND_MODE_FILE, SEND_MODE_IMAGE), SEND_MODE_FILE)
    values["auto_input"] = coerce_bool(raw("auto_input"), True)
    values["auto_convert_gif"] = coerce_bool(raw("auto_convert_gif"), True)

    values["ffmpeg_enabled"] = coerce_bool(raw("ffmpeg_enabled"), True)
    values["ffmpeg_path"] = coerce_text(raw("ffmpeg_path"), "").strip()

    values["thread_count"] = coerce_int(
        raw("thread_count"), 0, 0, THREAD_COUNT_MAX)
    mode = coerce_choice(raw("gif_render_mode"), RENDER_MODES, RENDER_AUTO)
    values["gif_render_mode"] = mode
    count = coerce_int(raw("gif_render_count"), 0, 0, GIF_RENDER_COUNT_MAX)
    values["gif_render_count"] = count
    values["gpu_accel"] = coerce_bool(raw("gpu_accel"), False)
    values["gpu_viewport"] = coerce_bool(raw("gpu_viewport"), False)
    values["gpu_pref"] = coerce_int(raw("gpu_pref"), 0, 0, 2)
    values["gpu_adapters"] = coerce_adapters(raw("gpu_adapters"))

    values["remember_group"] = coerce_bool(raw("remember_group"), True)
    values["always_on_top"] = coerce_bool(raw("always_on_top"), False)
    values["autostart"] = coerce_bool(raw("autostart"), False)
    values["auto_update"] = coerce_bool(raw("auto_update"), False)

    # The hotkey arrives in one of THREE shapes, and all three must work:
    #
    #   * a mapping {"modifiers": int, "key": str} - what `to_storage()` writes, and what older
    #     settings files contain;
    # * a portable string "Ctrl+Alt+F8" - what the QML capture produces, because the platform
    # layer's
    # `register(sequence)` takes exactly this form, so storing it verbatim keeps ONE representation
    #     on the wire instead of translating between two;
    #   * anything else (missing, empty, garbage) - the default binding.
    #
    # Only the mapping used to be accepted. A string fell through to `from_storage(None)`, i.e. the
    # DEFAULT, so capturing a new shortcut appeared to do nothing at all: the value was written,
    # then
    # silently replaced by F10 on the way back in. That is why "changing the global hotkey has no
    # effect" survived even after the capture itself was fixed.
    # 热键有三种到达形态，且三种都必须可用：
    #
    #   * 映射 {"modifiers": int, "key": str}——`to_storage()` 写出的形态，也是旧设置文件里的形态；
    #   * 可移植字符串 "Ctrl+Alt+F8"——QML 捕获产生的形态，因为平台层的 `register(sequence)` 恰好接受
    #     这一形式，逐字存储它就使链路上只有"一种"表示，而不必在两种之间翻译；
    #   * 其他任何情况（缺失、空、垃圾）——默认绑定。
    #
    # 过去只接受映射。字符串会落到 `from_storage(None)`，也就是"默认值"，因此捕获一个新快捷键看起来
    # 毫无作用：值被写入，然后在读回时被静默替换成 F10。这就是为什么即使修好了捕获，
    # "改全局快捷键没有效果"依然存在。
    raw_hotkey = raw("hotkey")
    if isinstance(raw_hotkey, dict):
        values["hotkey"] = hotkey_core.HotkeyBinding.from_storage(raw_hotkey)
    elif isinstance(raw_hotkey, str):
        values["hotkey"] = hotkey_core.HotkeyBinding.parse(raw_hotkey)
    else:
        values["hotkey"] = hotkey_core.HotkeyBinding.from_storage(None)

    values["window_geometry"] = coerce_bytes(data.get("window_geometry"))
    values["last_group_name"] = coerce_text(data.get("last_group_name"), "")

    settings = AppSettings(**values)
    return settings


def to_mapping(settings):
    # Persisted form. The legacy mirrors are written as well, so a downgrade to
    # an older release still sees a consistent configuration.
    # 持久化形式。同时写出历史镜像键，使降级到旧版本时看到的配置仍然一致。
    result = {
        "theme": settings.theme,
        "language": settings.language,
        "show_emoji_name": settings.show_emoji_name,
        "name_font_size": settings.name_font_size,
        "card_scale": settings.card_scale,
        "hover_preview_enabled": settings.hover_preview_enabled,
        "hover_zoom": settings.hover_zoom,
        "text_preview_limit_single": settings.text_preview_limit_single,
        "text_preview_limit_multi": settings.text_preview_limit_multi,
        "global_sort_enabled": settings.global_sort_enabled,
        "global_sort_by": settings.global_sort_by,
        "global_sort_desc": settings.global_sort_desc,
        "send_mode": settings.send_mode,
        "auto_input": settings.auto_input,
        "auto_convert_gif": settings.auto_convert_gif,
        "ffmpeg_enabled": settings.ffmpeg_enabled,
        "ffmpeg_path": settings.ffmpeg_path,
        "thread_count": settings.thread_count,
        "gif_render_mode": settings.gif_render_mode,
        "gif_render_count": settings.gif_render_count,
        "gpu_accel": settings.gpu_accel,
        "gpu_viewport": settings.gpu_viewport,
        "gpu_pref": settings.gpu_pref,
        "gpu_adapters": "|".join(settings.gpu_adapters),
        "remember_group": settings.remember_group,
        "always_on_top": settings.always_on_top,
        "autostart": settings.autostart,
        "auto_update": settings.auto_update,
        "hotkey": settings.hotkey.to_storage(),
        "last_group_name": settings.last_group_name,
        # Downgrade mirrors / 降级镜像
        "gpu_render": settings.gpu_accel,
        "hotkey_mods": settings.hotkey.modifiers,
    }
    if settings.window_geometry is not None:
        result["window_geometry"] = settings.window_geometry
    return result


def diff(previous, current):
    # Names of the fields that differ, so the controller can apply only what
    # changed instead of re-applying all 30 settings on every OK press.
    # 发生变化的字段名，使控制器只应用变化项，而不是每次按确定都重新应用全部 30 项。
    changed = set()
    for spec in dataclasses.fields(AppSettings):
        name = spec.name
        if getattr(previous, name) != getattr(current, name):
            changed.add(name)
    return frozenset(changed)


# ---- derived values / 派生值 -------------------------------------------------------

# Cap on the recommended worker count, matching what the settings page offers /
# 推荐工作线程数的上限，与设置页提供的一致
RECOMMENDED_THREAD_MIN = 2
RECOMMENDED_THREAD_MAX = 8


def recommended_thread_count(cpu_count=None):
    # Worker threads to suggest when the user leaves the count on "auto".
    #
    # One core is reserved for the UI thread, which keeps the window responsive
    # while a large import runs. `cpu_count` is injectable so the rule is
    # testable without depending on the host.
    # 用户把线程数留在"自动"时建议的工作线程数。
    #
    # 保留一个核心给界面线程，使大批量导入时窗口仍然响应。`cpu_count` 可注入，使该
    # 规则无需依赖宿主即可测试。
    import os

    total = cpu_count if cpu_count is not None else (os.cpu_count() or 4)
    return max(RECOMMENDED_THREAD_MIN, min(RECOMMENDED_THREAD_MAX, int(total) - 1))


def thread_count_to_stored(shown, cpu_count=None):
    # The settings store keeps 0 for "auto". The spin box always shows a
    # concrete number, so a shown value equal to the recommendation means the
    # user never picked one and 0 must be stored again — otherwise a machine
    # with a different core count inherits this machine's explicit choice.
    # 设置存储用 0 表示"自动"。微调框总是显示具体数字，因此显示值等于推荐值即意味着
    # 用户从未选择，必须重新存 0——否则核心数不同的另一台机器会继承本机的显式选择。
    shown = coerce_int(shown, recommended_thread_count(cpu_count), THREAD_COUNT_MIN,
                       THREAD_COUNT_MAX)
    if shown == recommended_thread_count(cpu_count):
        return 0
    return shown


def effective_thread_count(stored, cpu_count=None):
    # Concrete worker count for a stored value (0 = auto) /
    # 存储值（0 = 自动）对应的具体工作线程数
    stored = coerce_int(stored, 0, 0, THREAD_COUNT_MAX)
    return stored if stored > 0 else recommended_thread_count(cpu_count)


def effective_gif_limit(settings, cpu_count=None):
    # How many animated stickers may play at once.
    #
    # "auto" scales with the machine (at least 8, four per core) so a fast
    # desktop does not look artificially limited; "manual" honours the user's
    # number exactly, floored at 1 so the feature never switches itself off.
    # 同时可播放的动图数量。
    #
    # "auto" 随机器规模变化（至少 8，每核 4 个），使高性能桌面不被虚假限制；
    # "manual" 严格按用户给的数字，下限 1，使该功能永不自动关闭。
    workers = effective_thread_count(settings.thread_count, cpu_count)
    if settings.gif_render_mode == RENDER_AUTO:
        return max(8, workers * 4)
    return max(1, coerce_int(settings.gif_render_count, 8,
                             GIF_RENDER_COUNT_MIN, GIF_RENDER_COUNT_MAX))


def installer_asset_name(version_tuple):
    # Name the updater looks for. Built here rather than in the UI because it
    # must match the release asset exactly.
    # 更新器查找的文件名。在此构建而非在界面里，因为它必须与发布资源完全一致。
    from gifmanager.core.version import format_version

    return f"GIFManager-Setup-{format_version(version_tuple)}.exe"


def data_directory():
    return paths.data_dir()


def version():
    return __version__


# GPU preference values, re-exported so a settings page can build its choice list
# without importing `core.gpu` itself. Reading them from one place is what keeps
# the stored integers and their labels from drifting apart.
# GPU 首选项取值，重新导出使设置页无需自行导入 `core.gpu` 即可构建选项列表。从一处
# 读取是让存储整数与标签不脱节的原因。
def gpu_pref_system():
    from gifmanager.core import gpu

    return gpu.PREF_SYSTEM


def gpu_pref_power():
    from gifmanager.core import gpu

    return gpu.PREF_POWER


def gpu_pref_high():
    from gifmanager.core import gpu

    return gpu.PREF_HIGH


__all__ = [
    "CAPABILITY_AUTO_INPUT",
    "CAPABILITY_AUTOSTART",
    "CAPABILITY_GLOBAL_HOTKEY",
    "CAPABILITY_GLOBAL_SCROLL",
    "CAPABILITY_GPU_PREFERENCE",
    "CAPABILITY_GPU_VIEWPORT",
    "CAPABILITY_NONE",
    "CARD_SCALE_MAX",
    "CARD_SCALE_MIN",
    "GIF_RENDER_COUNT_MAX",
    "GIF_RENDER_COUNT_MIN",
    "HOVER_ZOOM_MAX",
    "HOVER_ZOOM_MIN",
    "LEGACY_KEYS",
    "NAME_FONT_MAX",
    "NAME_FONT_MIN",
    "RENDER_AUTO",
    "RENDER_MODES",
    "SEND_MODE_FILE",
    "SEND_MODE_IMAGE",
    "SORT_KEYS",
    "SORT_TIME",
    "STORAGE_KEY_OVERRIDES",
    "THEMES",
    "THEME_DARK",
    "AppSettings",
    "all_keys",
    "coerce_bool",
    "coerce_bytes",
    "coerce_choice",
    "coerce_float",
    "coerce_int",
    "coerce_text",
    "data_directory",
    "defaults",
    "diff",
    "effective_gif_limit",
    "effective_thread_count",
    "from_mapping",
    "gpu_pref_high",
    "gpu_pref_power",
    "gpu_pref_system",
    "installer_asset_name",
    "label_key",
    "migrate",
    "recommended_thread_count",
    "split_label",
    "storage_key",
    "thread_count_to_stored",
    "to_mapping",
    "version",
]
