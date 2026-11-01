"""Hotkey capture field: record a global hotkey by pressing it.

The captured value is a `core.hotkeys.HotkeyBinding`, not the raw Qt integer
pair the previous release stored (`hotkey_mods` / `hotkey_vk`). The old format
tied the persisted setting to one toolkit's enum values, so the value could not
be interpreted — let alone displayed — on another platform. A binding carries its
own portable name, and the platform layer translates it at registration time.

热键捕获字段：按键即录制一个全局热键。

捕获到的是 `core.hotkeys.HotkeyBinding`，而不是上一版本存储的裸 Qt 整数对
（`hotkey_mods` / `hotkey_vk`）。旧格式把持久化设置绑到了某一个工具包的枚举值上，
因此该取值在别的平台上无法被解释、更无法显示。绑定自带可移植名，由平台层在注册时翻译。
"""
import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget

from gifmanager.core import hotkeys as hotkey_core

log = logging.getLogger("GIFManager")

# Qt modifier bit -> portable modifier bit. The mapping is explicit rather than
# arithmetic because Qt's bit values are an implementation detail that has changed
# between releases, and silently producing a wrong modifier is worse than failing
# to capture.
# Qt 修饰位 -> 可移植修饰位。映射是显式的而非算术推导，因为 Qt 的位值属于实现细节
# 且曾在版本间变化，而静默产出错误的修饰键比捕获失败更糟。
_MODIFIER_MAP = (
    (Qt.KeyboardModifier.ControlModifier, hotkey_core.MOD_CTRL),
    (Qt.KeyboardModifier.AltModifier, hotkey_core.MOD_ALT),
    (Qt.KeyboardModifier.ShiftModifier, hotkey_core.MOD_SHIFT),
    (Qt.KeyboardModifier.MetaModifier, hotkey_core.MOD_META),
)

# Qt key value -> portable key name. Built at import time from the portable name
# lists so the two cannot disagree about which keys exist.
# Qt 按键值 -> 可移植按键名。在导入时由可移植名称列表构建，使两者不会对"存在哪些按键"
# 产生分歧。
_KEY_MAP = {}
for _letter in hotkey_core.LETTER_KEYS:
    _KEY_MAP[getattr(Qt.Key, f"Key_{_letter}", None)] = _letter
for _digit in hotkey_core.DIGIT_KEYS:
    _KEY_MAP[getattr(Qt.Key, f"Key_{_digit}", None)] = _digit
for _number in range(1, 25):
    _KEY_MAP[getattr(Qt.Key, f"Key_F{_number}", None)] = f"F{_number}"

_NAMED_KEYS = {
    "Key_Space": "SPACE",
    "Key_Tab": "TAB",
    "Key_Escape": "ESC",
    "Key_Return": "ENTER",
    "Key_Enter": "ENTER",
    "Key_Backspace": "BACKSPACE",
    "Key_Delete": "DELETE",
    "Key_Insert": "INSERT",
    "Key_Home": "HOME",
    "Key_End": "END",
    "Key_PageUp": "PAGEUP",
    "Key_PageDown": "PAGEDOWN",
    "Key_Up": "UP",
    "Key_Down": "DOWN",
    "Key_Left": "LEFT",
    "Key_Right": "RIGHT",
    "Key_Minus": "MINUS",
    "Key_Equal": "EQUAL",
    "Key_Comma": "COMMA",
    "Key_Period": "PERIOD",
    "Key_Slash": "SLASH",
    "Key_Semicolon": "SEMICOLON",
    "Key_Quote": "QUOTE",
    "Key_BracketLeft": "BRACKETLEFT",
    "Key_BracketRight": "BRACKETRIGHT",
    "Key_Backslash": "BACKSLASH",
    "Key_grave": "GRAVE",
}
for _attribute, _portable in _NAMED_KEYS.items():
    _KEY_MAP[getattr(Qt.Key, _attribute, None)] = _portable
_KEY_MAP.pop(None, None)


def modifiers_from_qt(modifiers):
    # Portable modifier bits for a Qt modifier mask /
    # Qt 修饰掩码对应的可移植修饰位
    result = 0
    for qt_flag, portable in _MODIFIER_MAP:
        if modifiers & qt_flag:
            result |= portable
    return result


def key_from_qt(key):
    # Portable key name for a Qt key value, or None when unmapped.
    #
    # Returning None for an unmapped key is deliberate: the previous release fell
    # back to treating the Qt value as a Win32 virtual-key code, which happened to
    # work for A-Z and 0-9 and silently produced a wrong hotkey for everything
    # else.
    # Qt 按键值对应的可移植按键名，未映射时返回 None。
    #
    # 对未映射按键返回 None 是刻意的：上一版本回退为把 Qt 取值当作 Win32 虚拟键码，
    # 这对 A-Z 与 0-9 恰好可用，对其他一切则静默产出错误的热键。
    return _KEY_MAP.get(key)


def binding_from_event(event):
    # Portable binding for a key event, or None when the key is unsupported or is
    # a bare modifier.
    # 按键事件对应的可移植绑定；按键不受支持或仅为修饰键时返回 None。
    key = key_from_qt(event.key())
    if key is None:
        return None
    return hotkey_core.HotkeyBinding(
        modifiers_from_qt(event.modifiers()), key)


class HotkeyCapture(QWidget):
    # Read-only field that shows the current binding and captures a new one.
    #
    # A `QLineEdit` subclass would inherit the text-input machinery it does not
    # want; composing a field plus a clear button keeps the focus behaviour
    # explicit, which is what a capture widget actually needs.
    # 只读字段，显示当前绑定并捕获新的绑定。
    #
    # 继承 `QLineEdit` 会带上它并不需要的文本输入机制；组合"字段 + 清除按钮"使焦点行为
    # 保持显式，而这正是捕获控件真正需要的。
    changed = Signal(object)

    def __init__(self, binding=None, parent=None):
        super().__init__(parent)
        self._binding = binding or hotkey_core.HotkeyBinding(
            0, hotkey_core.DEFAULT_KEY)
        self._capturing = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._field = QLineEdit()
        self._field.setReadOnly(True)
        self._field.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._field.installEventFilter(self)
        layout.addWidget(self._field, 1)

        self._clear = QPushButton(self._unset_text())
        self._clear.setObjectName("hotkeyClear")
        self._clear.clicked.connect(self._on_clear)
        layout.addWidget(self._clear)

        self._refresh()

    # ---- value / 取值 ----------------------------------------------------

    def binding(self):
        return self._binding

    def set_binding(self, binding):
        # Adopt a binding without emitting `changed`, so loading the form does
        # not look like a user edit.
        # 采用一个绑定但不发出 `changed`，使加载表单不会被当成用户编辑。
        self._binding = binding or hotkey_core.HotkeyBinding(0, "")
        self._refresh()

    def _unset_text(self):
        # Translated through the parent chain when possible; falls back to a
        # neutral label so the widget is usable without an adapter.
        # 尽可能经父链翻译；无适配器时回退到中性标签，使该控件仍可使用。
        try:
            from gifmanager.core.lang import tr

            return tr("clear")
        except Exception:
            return "Clear"

    def _refresh(self):
        if self._capturing:
            self._field.setText("...")
            return
        described = self._binding.describe()
        if not described:
            try:
                from gifmanager.core.lang import tr

                described = tr("hotkey_unset")
            except Exception:
                described = ""
        self._field.setText(described)

    # ---- capture / 捕获 --------------------------------------------------

    def eventFilter(self, obj, event):
        if obj is not self._field:
            return super().eventFilter(obj, event)
        event_type = event.type()
        if event_type == event.Type.FocusIn:
            self._begin()
            return False
        if event_type == event.Type.FocusOut:
            self._end()
            return False
        if event_type == event.Type.KeyPress and self._capturing:
            return self._on_key(event)
        return super().eventFilter(obj, event)

    def _begin(self):
        self._capturing = True
        self._refresh()

    def _end(self):
        self._capturing = False
        self._refresh()

    def _on_key(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            # Escape clears the binding, which is how a user removes one without
            # hunting for a delete button. It is also the only key that cannot be
            # bound, which matches every other hotkey field.
            # Escape 清除绑定，使用户无需寻找删除按钮即可移除。它也是唯一无法被绑定的
            # 按键，与其他所有热键字段一致。
            self._apply(hotkey_core.HotkeyBinding(0, ""))
            self._field.clearFocus()
            return True
        if key in (Qt.Key.Key_unknown, 0):
            return True
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt,
                   Qt.Key.Key_Meta):
            # A bare modifier is not a hotkey; waiting for the real key is what
            # makes "Ctrl then Shift then F10" work naturally.
            # 单独的修饰键不是热键；等待真实按键正是让"先 Ctrl 再 Shift 再 F10"自然的
            # 原因。
            return True
        binding = binding_from_event(event)
        if binding is None:
            log.info("hotkey capture: key %s has no portable name", key)
            return True
        self._apply(binding)
        self._field.clearFocus()
        return True

    def _apply(self, binding):
        if binding == self._binding:
            return
        self._binding = binding
        self._refresh()
        self.changed.emit(binding)

    def _on_clear(self):
        self._apply(hotkey_core.HotkeyBinding(0, ""))


__all__ = [
    "HotkeyCapture",
    "binding_from_event",
    "key_from_qt",
    "modifiers_from_qt",
]
