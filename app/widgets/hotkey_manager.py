"""Windows global hotkey manager — RegisterHotKey + nativeEvent
Windows 全局快捷键管理器 — RegisterHotKey + nativeEvent"""
import ctypes
from ctypes import wintypes
from PySide6.QtCore import QAbstractNativeEventFilter, Qt
from PySide6.QtGui import QKeySequence

from app.models.lang_manager import tr

# Win32 API constants / Win32 API 常量
user32 = ctypes.windll.user32
WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

# Virtual key codes / 虚拟键码
VK_MAP = {
    Qt.Key.Key_F1: 0x70, Qt.Key.Key_F2: 0x71, Qt.Key.Key_F3: 0x72,
    Qt.Key.Key_F4: 0x73, Qt.Key.Key_F5: 0x74, Qt.Key.Key_F6: 0x75,
    Qt.Key.Key_F7: 0x76, Qt.Key.Key_F8: 0x77, Qt.Key.Key_F9: 0x78,
    Qt.Key.Key_F10: 0x79, Qt.Key.Key_F11: 0x7A, Qt.Key.Key_F12: 0x7B,
    Qt.Key.Key_A: 0x41, Qt.Key.Key_B: 0x42, Qt.Key.Key_C: 0x43,
    Qt.Key.Key_D: 0x44, Qt.Key.Key_E: 0x45, Qt.Key.Key_F: 0x46,
    Qt.Key.Key_G: 0x47, Qt.Key.Key_H: 0x48, Qt.Key.Key_I: 0x49,
    Qt.Key.Key_J: 0x4A, Qt.Key.Key_K: 0x4B, Qt.Key.Key_L: 0x4C,
    Qt.Key.Key_M: 0x4D, Qt.Key.Key_N: 0x4E, Qt.Key.Key_O: 0x4F,
    Qt.Key.Key_P: 0x50, Qt.Key.Key_Q: 0x51, Qt.Key.Key_R: 0x52,
    Qt.Key.Key_S: 0x53, Qt.Key.Key_T: 0x54, Qt.Key.Key_U: 0x55,
    Qt.Key.Key_V: 0x56, Qt.Key.Key_W: 0x57, Qt.Key.Key_X: 0x58,
    Qt.Key.Key_Y: 0x59, Qt.Key.Key_Z: 0x5A,
    Qt.Key.Key_0: 0x30, Qt.Key.Key_1: 0x31, Qt.Key.Key_2: 0x32,
    Qt.Key.Key_3: 0x33, Qt.Key.Key_4: 0x34, Qt.Key.Key_5: 0x35,
    Qt.Key.Key_6: 0x36, Qt.Key.Key_7: 0x37, Qt.Key.Key_8: 0x38,
    Qt.Key.Key_9: 0x39,
    Qt.Key.Key_Space: 0x20,
    Qt.Key.Key_Tab: 0x09,
    Qt.Key.Key_Escape: 0x1B,
    # Mouse side buttons → virtual key codes / 鼠标侧键 → 虚拟键码
    0x100001: 0x05,  # XButton1 → VK_XBUTTON1 / 鼠标侧键1 → VK_XBUTTON1
    0x100002: 0x06,  # XButton2 → VK_XBUTTON2 / 鼠标侧键2 → VK_XBUTTON2
}


def _qt_mods_to_win(mods):
    wm = 0
    m = int(mods)
    if m & int(Qt.KeyboardModifier.AltModifier.value):
        wm |= MOD_ALT
    if m & int(Qt.KeyboardModifier.ControlModifier.value):
        wm |= MOD_CONTROL
    if m & int(Qt.KeyboardModifier.ShiftModifier.value):
        wm |= MOD_SHIFT
    if m & int(Qt.KeyboardModifier.MetaModifier.value):
        wm |= MOD_WIN
    return wm


# Build a human-readable hotkey description from a QKeyEvent
# 从 QKeyEvent 生成人类可读的快捷键描述
def key_event_to_hotkey_desc(event):
    parts = []
    mods = int(event.modifiers().value)
    if mods & int(Qt.KeyboardModifier.ControlModifier.value):
        parts.append("Ctrl")
    if mods & int(Qt.KeyboardModifier.ShiftModifier.value):
        parts.append("Shift")
    if mods & int(Qt.KeyboardModifier.AltModifier.value):
        parts.append("Alt")
    if mods & int(Qt.KeyboardModifier.MetaModifier.value):
        parts.append("Win")

    key = event.key()
    # Mouse side buttons (raw Qt values) / 鼠标侧键（原始 Qt 键值）
    if key == 0x100001:
        parts.append(tr("mouse_x1"))
    elif key == 0x100002:
        parts.append(tr("mouse_x2"))
    else:
        seq = QKeySequence(key)
        name = seq.toString()
        if name:
            parts.append(name)
        else:
            return ""

    return "+".join(parts) if parts else ""


# Global hotkey manager
# 全局热键管理器
class HotkeyManager(QAbstractNativeEventFilter):
    HOTKEY_ID = 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._registered = False
        self._mods = 0
        self._vk = 0
        self._callback = None

    # Register a global hotkey. mods: Qt modifiers, vk: Qt Key, callback: zero-arg callback
    # 注册全局热键。mods: Qt 修饰键，vk: Qt 键，callback: 无参回调
    def register(self, mods, vk, callback):
        self.unregister()
        wm = _qt_mods_to_win(mods)
        win_vk = VK_MAP.get(vk, vk)
        ok = user32.RegisterHotKey(0, self.HOTKEY_ID, wm, win_vk)
        if ok:
            self._registered = True
            self._mods = mods
            self._vk = vk
            self._callback = callback
        return bool(ok)

    def unregister(self):
        if self._registered:
            user32.UnregisterHotKey(0, self.HOTKEY_ID)
            self._registered = False
            self._callback = None

    @property
    def is_registered(self):
        return self._registered

    def nativeEventFilter(self, eventType, message):
        # In PySide6, eventType is a QByteArray → Python bytes
        # PySide6 中 eventType 是 QByteArray → Python bytes
        et = eventType.data() if hasattr(eventType, "data") else bytes(eventType)
        if b"windows" in et:
            msg = ctypes.cast(
                ctypes.c_void_p(int(message)), ctypes.POINTER(wintypes.MSG)
            ).contents
            if msg.message == WM_HOTKEY and msg.wParam == self.HOTKEY_ID:
                if self._callback:
                    self._callback()
                return True, 0
        return False, 0

    # ------------------------------------------------------------------
    # Serialization / 序列化
    # ------------------------------------------------------------------

    def to_dict(self):
        return {"mods": int(self._mods), "vk": int(self._vk)}

    def from_dict(self, d):
        mods = d.get("mods", 0)
        vk = d.get("vk", 0)
        return int(mods), int(vk)
