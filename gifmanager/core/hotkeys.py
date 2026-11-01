"""Portable global-hotkey bindings.

A binding used to be two raw integers in the settings store — a Qt
`KeyboardModifier` bitmask and a Qt `Qt.Key` value — which tied the persisted
format, the capture widget and the Windows registration code to one toolkit.
Here a binding is a modifier bitmask plus a portable key NAME, and the two
halves of the old format stay available as a migration path.

可移植的全局热键绑定。

绑定此前是设置里的两个裸整数——一个 Qt `KeyboardModifier` 位掩码与一个 Qt
`Qt.Key` 值——把持久化格式、捕获控件与 Windows 注册代码都绑到了一个工具包上。
这里绑定是"修饰键位掩码 + 可移植按键名"，旧格式的两部分则保留为迁移路径。
"""
import re
from dataclasses import dataclass, replace

# Modifier bits. These are this project's own bits (not Qt's, not Win32's), so
# the stored value is meaningful on every platform.
# 修饰键位。这是本项目自己的位（既非 Qt 的也非 Win32 的），因此存储值在所有平台
# 都有意义。
MOD_CTRL = 1 << 0
MOD_ALT = 1 << 1
MOD_SHIFT = 1 << 2
MOD_META = 1 << 3

ALL_MODIFIERS = MOD_CTRL | MOD_ALT | MOD_SHIFT | MOD_META

# Per-platform display names for the Meta modifier, and the separator used
# between a modifier and the key.
#
# The running system's name is supplied by the caller rather than read from
# `sys.platform` here: this module is display logic and must not depend on which
# OS it is compiled on, and the front-end already knows the platform key.
# Meta 修饰键在各平台的显示名，以及修饰键与按键之间的分隔符。
#
# 当前系统的名称由调用方提供，而不是在此读 `sys.platform`：本模块是显示逻辑，不得
# 依赖自己跑在哪个系统上，而前端本来就知道平台标识。
_META_LABELS = {
    "win32": "Win",
    "cygwin": "Win",
    "darwin": "Cmd",
}
_META_LABEL_DEFAULT = "Super"

# Portable key names accepted in a binding string. The set covers what a global
# hotkey is realistically used for; anything else is rejected rather than
# silently persisted as an unusable value.
# 绑定字符串接受的可移植按键名。集合覆盖了全局热键的现实用途；其他按键会被拒绝，
# 而不是静默存成无法使用的值。
LETTER_KEYS = tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
DIGIT_KEYS = tuple("0123456789")
FUNCTION_KEYS = tuple(f"F{n}" for n in range(1, 25))
NAMED_KEYS = (
    "SPACE", "TAB", "ESC", "ENTER", "BACKSPACE", "DELETE", "INSERT",
    "HOME", "END", "PAGEUP", "PAGEDOWN", "UP", "DOWN", "LEFT", "RIGHT",
    "MINUS", "EQUAL", "COMMA", "PERIOD", "SLASH", "SEMICOLON", "QUOTE",
    "BRACKETLEFT", "BRACKETRIGHT", "BACKSLASH", "GRAVE",
)
MOUSE_KEYS = ("MOUSE4", "MOUSE5")

VALID_KEYS = frozenset(
    LETTER_KEYS + DIGIT_KEYS + FUNCTION_KEYS + NAMED_KEYS + MOUSE_KEYS)

# Aliases so a hand-written or migrated string still parses /
# 别名，使手写或迁移来的字符串仍能解析
_KEY_ALIASES = {
    "ESCAPE": "ESC",
    "RETURN": "ENTER",
    "DEL": "DELETE",
    "INS": "INSERT",
    "PGUP": "PAGEUP",
    "PGDN": "PAGEDOWN",
    "X1": "MOUSE4",
    "X2": "MOUSE5",
}

# A key is "unset" when its name is empty /
# 按键名为空时表示"未设置"
UNSET_KEY = ""

# Default binding offered when the user has never chosen one /
# 用户从未选择时提供的默认绑定
DEFAULT_KEY = "F10"
DEFAULT_MODIFIERS = 0

_MODIFIER_TOKENS = {
    "CTRL": MOD_CTRL,
    "CONTROL": MOD_CTRL,
    "ALT": MOD_ALT,
    "OPTION": MOD_ALT,
    "SHIFT": MOD_SHIFT,
    "META": MOD_META,
    "WIN": MOD_META,
    "SUPER": MOD_META,
    "CMD": MOD_META,
    "COMMAND": MOD_META,
}

_SPLIT_RE = re.compile(r"[+\-\s]+")


def meta_label(platform_key=None):
    # Display name of the Meta modifier on a platform.
    #
    # `platform_key` is required in practice and comes from
    # `gifmanager.platform.current().key`; the fallback exists so a caller that
    # genuinely has no platform context (a unit test rendering a string) still
    # gets a sensible label instead of an exception.
    # Meta 修饰键在某平台上的显示名。
    #
    # `platform_key` 实际使用中是必需的，值来自 `gifmanager.platform.current().key`；
    # 兜底存在是为了让确实没有平台上下文的调用方（渲染字符串的单元测试）得到合理标签
    # 而不是异常。
    return _META_LABELS.get(platform_key, _META_LABEL_DEFAULT)


def canonical_key(name):
    # Uppercase a key name and resolve its alias; returns None when unknown /
    # 把按键名大写并解析别名；未知时返回 None
    if not name:
        return None
    upper = str(name).strip().upper().replace(" ", "")
    upper = _KEY_ALIASES.get(upper, upper)
    return upper if upper in VALID_KEYS else None


@dataclass(frozen=True)
class HotkeyBinding:
    # A global hotkey: modifier bits plus one portable key name.
    #
    # `modifiers == 0` and `key == ""` means "unset", which the UI renders as
    # "not set" instead of a broken combination.
    # 一个全局热键：修饰键位加一个可移植按键名。
    #
    # `modifiers == 0` 且 `key == ""` 表示"未设置"，界面渲染为"未设置"而不是一个
    # 组合键。
    modifiers: int = DEFAULT_MODIFIERS
    key: str = DEFAULT_KEY

    @property
    def is_set(self):
        return bool(self.key)

    @property
    def is_valid(self):
        # A global hotkey needs a real key. A bare modifier is not a hotkey.
        # 全局热键需要一个真实按键；单独的修饰键不是热键。
        return self.is_set and self.key in VALID_KEYS

    def describe(self, platform_key=None):
        # Human-readable form such as "Ctrl+Shift+F10". Uses the platform's
        # name for the Meta modifier so macOS reads "Cmd" rather than "Win".
        # 人类可读形式，如 "Ctrl+Shift+F10"。Meta 修饰键用平台名称，使 macOS 显示
        # "Cmd" 而非 "Win"。
        if not self.is_set:
            return ""
        parts = []
        if self.modifiers & MOD_CTRL:
            parts.append("Ctrl")
        if self.modifiers & MOD_ALT:
            parts.append("Alt")
        if self.modifiers & MOD_SHIFT:
            parts.append("Shift")
        if self.modifiers & MOD_META:
            parts.append(meta_label(platform_key))
        parts.append(_display_key(self.key))
        return "+".join(parts)

    def to_storage(self):
        # Portable persisted form / 可移植的持久化形式
        return {"modifiers": int(self.modifiers), "key": self.key}

    @classmethod
    def from_storage(cls, data):
        # Rebuild from `to_storage()` output, tolerating a missing or malformed
        # mapping by falling back to the default binding.
        # 从 `to_storage()` 的输出重建；映射缺失或畸形时回退到默认绑定。
        if not isinstance(data, dict):
            return cls()
        key = canonical_key(data.get("key"))
        if key is None:
            return cls()
        try:
            modifiers = int(data.get("modifiers", 0)) & ALL_MODIFIERS
        except (TypeError, ValueError):
            modifiers = 0
        return cls(modifiers=modifiers, key=key)

    def with_modifiers(self, modifiers):
        return replace(self, modifiers=int(modifiers) & ALL_MODIFIERS)

    def with_key(self, key):
        canonical = canonical_key(key)
        return replace(self, key=canonical or UNSET_KEY)

    @classmethod
    def parse(cls, text):
        # Parse "Ctrl+Shift+F10" (also accepting "-" and spaces as separators).
        # Returns the unset binding when the text holds no recognisable key.
        # 解析 "Ctrl+Shift+F10"（也接受 "-" 与空格作分隔符）。文本中没有可识别按键
        # 时返回未设置绑定。
        tokens = [t for t in _SPLIT_RE.split(str(text or "").strip()) if t]
        modifiers = 0
        key = ""
        for token in tokens:
            upper = token.upper()
            if upper in _MODIFIER_TOKENS:
                modifiers |= _MODIFIER_TOKENS[upper]
                continue
            canonical = canonical_key(upper)
            if canonical:
                key = canonical
        if not key:
            return cls(modifiers=0, key=UNSET_KEY)
        return cls(modifiers=modifiers, key=key)


def _display_key(key):
    # Presentation form of a key name: single characters stay as-is, named keys
    # get their first letter capitalised, mouse buttons become "Mouse4".
    # 按键名的展示形式：单字符原样，具名键首字母大写，鼠标键显示为 "Mouse4"。
    if len(key) == 1:
        return key
    if key.startswith("MOUSE"):
        return "Mouse" + key[5:]
    return key.capitalize()


def migrate_qt_binding(modifiers, qt_key, qt_key_names=None, portable_key=None):
    # Migration helper for the pre-refactor format: a Qt `KeyboardModifier`
    # bitmask plus a Qt `Qt.Key` value.
    #
    # `qt_key_names` maps a Qt key value onto a portable key name and
    # `portable_key` overrides the result directly; both are injected so this
    # module needs no Qt import.
    #
    # 重构前格式的迁移辅助：一个 Qt `KeyboardModifier` 位掩码加一个 Qt `Qt.Key`
    # 值。
    #
    # `qt_key_names` 把 Qt 按键值映射到可移植按键名，`portable_key` 直接覆盖结果；
    # 两者都是注入的，使本模块无需导入 Qt。
    if portable_key:
        canonical = canonical_key(portable_key)
        if canonical:
            return HotkeyBinding(int(modifiers) & ALL_MODIFIERS, canonical)
    if qt_key_names and qt_key in qt_key_names:
        return HotkeyBinding(int(modifiers) & ALL_MODIFIERS, qt_key_names[qt_key])
    # A Qt key of 0 means "unset" in the old format, and the old code then reset
    # the modifiers too; reproduce that so an unset hotkey does not come back as
    # a modifier-only binding.
    # 旧格式中 Qt 按键值为 0 表示"未设置"，且旧代码会一并重置修饰键；这里复现该
    # 行为，使未设置的热键不会变成只有修饰键的绑定。
    if not qt_key:
        return HotkeyBinding(0, DEFAULT_KEY)
    return HotkeyBinding(0, UNSET_KEY)


__all__ = [
    "ALL_MODIFIERS",
    "DEFAULT_KEY",
    "DEFAULT_MODIFIERS",
    "DIGIT_KEYS",
    "FUNCTION_KEYS",
    "HotkeyBinding",
    "LETTER_KEYS",
    "MOD_ALT",
    "MOD_CTRL",
    "MOD_META",
    "MOD_SHIFT",
    "MOUSE_KEYS",
    "NAMED_KEYS",
    "UNSET_KEY",
    "VALID_KEYS",
    "canonical_key",
    "meta_label",
    "migrate_qt_binding",
]
