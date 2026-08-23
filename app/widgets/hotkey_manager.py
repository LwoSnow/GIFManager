"""Windows global hotkey manager — RegisterHotKey + nativeEvent
Windows 全局快捷键管理器 — RegisterHotKey + nativeEvent"""
import ctypes
from ctypes import wintypes
from PySide6.QtCore import QAbstractNativeEventFilter, Qt
from PySide6.QtGui import QKeySequence

from app.models.lang_manager import tr

# Win32 API constants / Win32 API 常量
user32 = ctypes.windll.user32

# Declare argtypes so pointer-sized handles/pointers are not truncated on
# 64-bit (truncation previously made SetWindowsHookExW/CallNextHookEx throw
# OverflowError, which slowed the system mouse). / 声明 argtypes，避免 64 位
# 下指针尺寸句柄/指针被截断（截断曾让 SetWindowsHookExW/CallNextHookEx 抛
# OverflowError，拖慢系统鼠标）。
if hasattr(user32, "SetWindowsHookExW"):
    user32.SetWindowsHookExW.restype = ctypes.c_void_p
    user32.SetWindowsHookExW.argtypes = [
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
if hasattr(user32, "UnhookWindowsHookEx"):
    user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
if hasattr(user32, "CallNextHookEx"):
    user32.CallNextHookEx.restype = ctypes.c_ssize_t
    user32.CallNextHookEx.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_size_t]
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
        # Same hotkey: just refresh the callback / 相同热键：仅更新回调
        if self._registered and self._mods == mods and self._vk == vk:
            self._callback = callback
            return True
        wm = _qt_mods_to_win(mods)
        win_vk = VK_MAP.get(vk, vk)
        # Probe the new combination with a temporary id first: if it is taken
        # by another app, fail WITHOUT unregistering the currently registered
        # hotkey (the old code unregistered first, silently losing the old
        # hotkey on a busy new one). / 先用临时 id 探测新组合：若被其他程序
        # 占用则失败且不注销当前已注册热键（旧代码先注销，新键被占用时会
        # 静默丢失旧热键）。
        probe_id = self.HOTKEY_ID + 100
        ok = user32.RegisterHotKey(0, probe_id, wm, win_vk)
        if not ok:
            return False
        user32.UnregisterHotKey(0, probe_id)
        # Probe succeeded: replace the old registration / 探测成功：替换旧注册
        self.unregister()
        ok2 = user32.RegisterHotKey(0, self.HOTKEY_ID, wm, win_vk)
        if not ok2:
            # Extremely unlikely: leave a clean unregistered state / 极罕见：
            # 保持干净的未注册状态
            self._registered = False
            self._callback = None
            return False
        self._registered = True
        self._mods = mods
        self._vk = vk
        self._callback = callback
        return True

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


# Win32 constants for Alt+scroll detection /
# Alt+滚轮检测的 Win32 常量
WH_MOUSE_LL = 14
WM_MOUSEWHEEL = 0x020A
VK_MENU = 0x12  # Alt key / Alt 键


# Global Alt+scroll watcher: low-level mouse hook + QTimer fallback /
# 全局 Alt+滚轮监听器：低级鼠标钩子 + QTimer 兜底
class GlobalScrollWatcher:
    # Uses a Win32 WH_MOUSE_LL hook to capture scroll wheel events globally.
    # Alt state is checked via GetAsyncKeyState. A QTimer polls as fallback
    # in case the hook is not installed (e.g. restricted environment).
    # 使用 Win32 WH_MOUSE_LL 钩子全局捕获滚轮事件。
    # 通过 GetAsyncKeyState 检查 Alt 状态。QTimer 作为兜底轮询。

    def __init__(self):
        self._callback = None
        self._hook = None
        self._last_delta = 0
        # Keep the C callback alive. LPARAM carries a POINTER-sized value
        # (MSLLHOOKSTRUCT*) — on 64-bit it is 8 bytes, so the callback must
        # use c_ssize_t, not wintypes.LPARAM (which is 32-bit c_ulong).
        # Passing a truncated 32-bit LPARAM made every mouse event throw an
        # OverflowError inside the hook (silently caught), which slowed the
        # system mouse (felt like DPI dropping to 1/4 inside the window).
        # 保持 C 回调存活。LPARAM 携带指针宽度值（MSLLHOOKSTRUCT*）——64 位
        # 下为 8 字节，回调必须用 c_ssize_t，而非 wintypes.LPARAM（32 位
        # c_ulong）。传截断的 32 位 LPARAM 会让每次鼠标事件在钩子内抛
        # OverflowError（被静默捕获），拖慢系统鼠标（感觉像窗口内 DPI 降
        # 到 1/4）。
        self._hook_proc = ctypes.WINFUNCTYPE(
            ctypes.c_int, ctypes.c_int, ctypes.c_size_t, ctypes.c_size_t
        )(self._mouse_proc)
        # QTimer fallback: poll every 50 ms when hook is unavailable /
        # QTimer 兜底：钩子不可用时每 50ms 轮询
        self._timer = None

    # Install the hook and start the timer fallback /
    # 安装钩子并启动定时器兜底
    def start(self, callback):
        self._callback = callback
        if self._hook is None:
            try:
                # WH_MOUSE_LL is a low-level hook: the callback runs in THIS
                # process, so hMod must be NULL. Passing GetModuleHandleW(None)
                # made SetWindowsHookExW fail with ERROR_MOD_NOT_FOUND (126).
                # / WH_MOUSE_LL 是低级钩子：回调在本进程内执行，hMod 必须传
                # NULL。此前传 GetModuleHandleW(None) 会让 SetWindowsHookExW
                # 以 ERROR_MOD_NOT_FOUND(126) 失败。
                self._hook = user32.SetWindowsHookExW(
                    WH_MOUSE_LL, self._hook_proc, None, 0,
                )
            except Exception:
                self._hook = None
            if not self._hook:
                try:
                    from app.models.logger import get_logger
                    get_logger().warning(
                        "GlobalScrollWatcher: mouse hook failed (err=%s), "
                        "fall back to timer only",
                        ctypes.get_last_error())
                except Exception:
                    pass
        # Always start timer as fallback (or primary if hook failed) /
        # 始终启动定时器作为兜底（钩子失败时作为主方案）
        if self._timer is None:
            from PySide6.QtCore import QTimer
            self._timer = QTimer()
            self._timer.setInterval(50)
            self._timer.timeout.connect(self._poll)
        self._timer.start()

    # Remove hook and timer / 移除钩子和定时器
    def stop(self):
        if self._hook is not None:
            try:
                user32.UnhookWindowsHookEx(self._hook)
            except Exception:
                pass
            self._hook = None
        if self._timer is not None:
            self._timer.stop()
        self._callback = None

    # Timer fallback: check Alt state + accumulated scroll delta /
    # 定时器兜底：检查 Alt 状态 + 累积的滚轮增量
    def _poll(self):
        if self._callback is None:
            return
        if user32.GetAsyncKeyState(VK_MENU) & 0x8000:
            if self._last_delta != 0:
                d = self._last_delta
                self._last_delta = 0
                self._callback(d)

    # Hook callback: capture WM_MOUSEWHEEL and store delta /
    # 钩子回调：捕获 WM_MOUSEWHEEL 并存储增量
    def _mouse_proc(self, nCode, wParam, lParam):
        if nCode >= 0 and wParam == WM_MOUSEWHEEL:
            try:
                class _MSLLHOOKSTRUCT(ctypes.Structure):
                    _fields_ = [
                        ("pt", wintypes.POINT),
                        ("mouseData", wintypes.DWORD),
                        ("flags", wintypes.DWORD),
                        ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_void_p),
                    ]
                data = ctypes.cast(
                    ctypes.c_void_p(lParam),
                    ctypes.POINTER(_MSLLHOOKSTRUCT),
                ).contents
                delta = ctypes.c_short(data.mouseData >> 16).value
                if delta != 0:
                    self._last_delta = delta
                    # If Alt is held, fire immediately via hook /
                    # Alt 按住时通过钩子立即触发
                    if (user32.GetAsyncKeyState(VK_MENU) & 0x8000
                            and self._callback):
                        self._callback(delta)
                        self._last_delta = 0
            except Exception:
                pass
        return user32.CallNextHookEx(self._hook, nCode, wParam, lParam)
