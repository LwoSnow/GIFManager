# Keep the manager window from stealing foreground focus, and paste into the
# chat input that owns focus. Design (mirrors search-input / IME panel tools
# like Sogou's character panel): the manager is a Tool window shown without
# activating; a background guard timer tracks "the last non-manager
# foreground window" (the chat input the user clicked) and, whenever the
# manager gets activated by a mouse click, immediately hands focus back to
# that tracked window. Ctrl+V via SendInput therefore always lands in the
# chat input, even while the user is clicking emojis in the manager. Pure
# ctypes -> user32, Windows only.
# 防止管理器窗口抢占前台焦点，并把内容粘贴到持有焦点的聊天输入框。设计
# （参照输入法/字符面板类工具，如搜狗字符大全）：管理器是 Tool 窗口、
# 显示时不激活；后台守卫定时器跟踪"最近一个非管理器的前台窗口"（用户
# 点击的聊天输入框），一旦管理器被鼠标点击激活，立即把焦点归还给该
# 窗口。因此 Ctrl+V（SendInput）总是落在聊天输入框，即使用户正在管理器
# 里点击表情。纯 ctypes 调 user32，仅 Windows。
import ctypes
import ctypes.wintypes as wt
import os
import sys

# Virtual-key codes / 虚拟键码
VK_CONTROL = 0x11
VK_V = 0x56

# SendInput 结构定义 / SendInput structures
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Declare HWND argtypes/restype: without them ctypes converts handles via
# c_int (32-bit), truncating 64-bit window handles above 2^31 and making
# handle comparisons (foreground == manager) fail. / 声明句柄函数的
# argtypes/restype：缺失时 ctypes 按 c_int（32 位）转换，64 位窗口句柄
# 超过 2^31 会被截断，导致句柄比较（前台 == 管理器）失配。
user32.GetForegroundWindow.restype = wt.HWND
user32.SetForegroundWindow.argtypes = (wt.HWND,)
user32.SetForegroundWindow.restype = wt.BOOL
user32.BringWindowToTop.argtypes = (wt.HWND,)
user32.BringWindowToTop.restype = wt.BOOL
user32.GetWindowThreadProcessId.argtypes = (wt.HWND, ctypes.POINTER(wt.DWORD))
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.AttachThreadInput.argtypes = (wt.DWORD, wt.DWORD, wt.BOOL)
user32.AttachThreadInput.restype = wt.BOOL
user32.IsWindow.argtypes = (wt.HWND,)
user32.IsWindow.restype = wt.BOOL
user32.GetClassNameW.argtypes = (wt.HWND, wt.LPWSTR, ctypes.c_int)
user32.GetClassNameW.restype = ctypes.c_int
user32.EnumChildWindows.argtypes = (
    wt.HWND, ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM), wt.LPARAM)
user32.EnumChildWindows.restype = wt.BOOL
user32.GetGUIThreadInfo.argtypes = (wt.DWORD, ctypes.c_void_p)
user32.GetGUIThreadInfo.restype = wt.BOOL
user32.SendMessageW.argtypes = (wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
user32.SendMessageW.restype = ctypes.c_ssize_t


# The Win32 INPUT/KEYBDINPUT layout: the union inside INPUT is as large as
# the biggest member (MOUSEINPUT = 32 bytes), so INPUT is 40 bytes total.
# ctypes must reproduce that, otherwise SendInput returns
# ERROR_INVALID_PARAMETER (87). / Win32 INPUT/KEYBDINPUT 布局：INPUT 内
# union 大小取最大成员（MOUSEINPUT = 32 字节），故 INPUT 总长 40 字节。
# ctypes 必须复现该布局，否则 SendInput 返回 ERROR_INVALID_PARAMETER(87)。
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD),
        ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wt.LONG),
        ("dy", wt.LONG),
        ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wt.DWORD),
        ("wParamL", wt.WORD),
        ("wParamH", wt.WORD),
    ]


class INPUT(ctypes.Structure):
    _pack_ = 8  # SDK: INPUT is 8-aligned / SDK：INPUT 按 8 字节对齐
    class _I(ctypes.Union):
        _fields_ = [
            ("ki", KEYBDINPUT),
            ("mi", _MOUSEINPUT),
            ("hi", _HARDWAREINPUT),
        ]

    _anonymous_ = ("i",)
    _fields_ = [("type", wt.DWORD), ("i", _I)]


def _send_key(vk, up=False, delay_ms=8):
    # One keyboard event (down or up) for the given virtual key. A short
    # delay between events lets the target app (e.g. Qt-based WeChat)
    # process each keystroke separately; without it, Ctrl+V can be
    # misread as a lone "v" character. / 发送单个按键事件（按下或抬起）。
    # 事件间加入短暂延迟，让目标程序（如基于 Qt 的微信）逐个处理按键；
    # 否则 Ctrl+V 可能被误读为孤立的 "v" 字符。
    if delay_ms > 0:
        import time
        time.sleep(delay_ms / 1000.0)
    ki = KEYBDINPUT()
    ki.wVk = vk
    ki.dwFlags = KEYEVENTF_KEYUP if up else 0
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki = ki
    n = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    if n != 1:
        err = ctypes.get_last_error()
        # Log once via the app logger when available / 可用时经应用日志记录一次
        try:
            from app.models.logger import get_logger
            get_logger().warning("input_sender: SendInput failed (vk=%s up=%s err=%s)",
                                 vk, up, err)
        except Exception:
            pass
        return False
    return True


def paste_to_foreground(delay_ms=50):
    # Paste the clipboard into the current foreground window with Ctrl+V.
    # A small delay lets the target window process its activation before the
    # keystrokes arrive. Keystrokes are spaced so the target app (Qt-based
    # WeChat in particular) reliably sees Ctrl held while V is pressed —
    # otherwise a stray "v" character can appear. Returns True on success.
    # 用 Ctrl+V 把剪贴板内容粘贴到当前前台窗口。短暂延迟让目标窗口处理
    # 激活后再发送按键。按键之间拉开间隔，确保目标程序（尤其基于 Qt 的
    # 微信）能识别"Ctrl 按住时按 V"——否则可能出现孤立的 "v" 字符。
    # 成功返回 True。
    if sys.platform != "win32":
        return False
    import time
    time.sleep(delay_ms / 1000.0)
    ok = True
    try:
        ok &= _send_key(VK_CONTROL, delay_ms=0)    # Ctrl down / 按下 Ctrl
        time.sleep(0.02)                           # hold Ctrl before V / 先稳住 Ctrl
        ok &= _send_key(VK_V, delay_ms=0)          # V down / 按下 V
        time.sleep(0.02)                           # brief press duration / 短暂按压
        ok &= _send_key(VK_V, up=True, delay_ms=0)  # V up / 松开 V
        time.sleep(0.02)                           # release V before Ctrl / 先松 V 再松 Ctrl
    finally:
        # Always release Ctrl, even when a SendInput call failed: leaving it
        # held would prefix every later keystroke with Ctrl.
        # 无论是否失败都释放 Ctrl：残留按下会让后续所有按键都带 Ctrl 前缀。
        _send_key(VK_CONTROL, up=True, delay_ms=0)  # Ctrl up / 松开 Ctrl
    return ok


def foreground_window():
    # Current foreground window handle, or 0 / 当前前台窗口句柄，无则 0
    if sys.platform != "win32":
        return 0
    return int(user32.GetForegroundWindow() or 0)


def bring_to_front(hwnd):
    # Restore foreground focus to a window. AttachThreadInput bypasses the
    # Windows foreground-lock so SetForegroundWindow works even though our
    # process was just activated. Returns True on success.
    # 把前台焦点还给指定窗口。AttachThreadInput 绕过 Windows 前台锁，
    # 使 SetForegroundWindow 即使在本进程刚被激活时也有效。
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        cur = kernel32.GetCurrentThreadId()
        tgt = user32.GetWindowThreadProcessId(hwnd, None)
        attached = False
        if tgt:
            attached = bool(user32.AttachThreadInput(cur, tgt, True))
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        if attached:
            user32.AttachThreadInput(cur, tgt, False)
        return True
    except Exception:
        return False


# Win32 message ids / Win32 消息号
WM_PASTE = 0x0302
WM_GETTEXT = 0x000D


def _find_edit_children(hwnd, depth=0):
    # Recursively find Edit/RichEdit child controls (WeChat/QQ input boxes
    # are standard edit controls). Returns a list of handles.
    # 递归查找 Edit/RichEdit 子控件（微信/QQ 输入框是标准编辑控件）。
    # 返回句柄列表。
    if not hwnd or depth > 4:
        return []
    found = []

    def cb(h, l):
        try:
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(h, cls, 64)
            name = cls.value
            if name in ("Edit", "RichEdit20W", "RichEdit20A", "RICHEDIT",
                        "RICHEDIT50W", "RichEditD2DPT", "ATL:Edit", "EditW"):
                found.append(int(h))
        except Exception:
            pass
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    user32.EnumChildWindows(hwnd, WNDENUMPROC(cb), 0)
    if found:
        return found
    # descend one more level / 再深入一层
    for child in _children_of(hwnd):
        found.extend(_find_edit_children(child, depth + 1))
    return found


def _children_of(hwnd):
    kids = []

    def cb(h, l):
        kids.append(int(h))
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    user32.EnumChildWindows(hwnd, WNDENUMPROC(cb), 0)
    return kids


def _thread_focus_window(hwnd):
    # The window that currently owns keyboard focus in hwnd's thread (may be
    # 0 if the thread has no focus window). / hwnd 所在线程当前持有键盘焦点的
    # 窗口（线程无焦点窗口时可能为 0）。
    if sys.platform != "win32" or not hwnd:
        return 0
    try:
        class _GUITHREADINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wt.DWORD),
                ("flags", wt.DWORD),
                ("hwndActive", wt.HWND),
                ("hwndFocus", wt.HWND),
                ("hwndCapture", wt.HWND),
                ("hwndMenuOwner", wt.HWND),
                ("hwndMoveSize", wt.HWND),
                ("hwndCaret", wt.HWND),
                ("rcCaret", wt.RECT),
            ]
        tid = user32.GetWindowThreadProcessId(hwnd, None)
        info = _GUITHREADINFO()
        info.cbSize = ctypes.sizeof(_GUITHREADINFO)
        if not user32.GetGUIThreadInfo(tid, ctypes.byref(info)):
            return 0
        return int(info.hwndFocus or 0)
    except Exception:
        return 0


def paste_to_window(hwnd, delay_ms=50):
    # Paste the clipboard into a specific chat window by sending WM_PASTE to
    # its Edit/RichEdit input control. Works for apps with standard edit
    # controls (old QQ/WeChat builds). New WeChat is a Qt app whose input is
    # NOT a standard edit control, so this returns False and the caller
    # falls back to SendInput Ctrl+V (Qt apps process keyboard input).
    # 把剪贴板内容粘贴进指定聊天窗口：向它的 Edit/RichEdit 输入控件发送
    # WM_PASTE。适用于带标准编辑控件的程序（旧版 QQ/微信）。新版微信是
    # Qt 应用，其输入框不是标准编辑控件，本函数返回 False，由调用方回退
    # 到 SendInput 模拟 Ctrl+V（Qt 应用处理键盘输入）。
    if sys.platform != "win32" or not hwnd:
        return False
    import time
    time.sleep(delay_ms / 1000.0)
    edits = _find_edit_children(hwnd)
    if not edits:
        # No standard edit control — cannot deliver WM_PASTE reliably /
        # 无标准编辑控件——无法可靠投递 WM_PASTE
        return False
    try:
        user32.SendMessageW(edits[0], WM_PASTE, 0, 0)
        return True
    except Exception:
        return False


class FocusGuard:
    """Background tracker: every tick, remember the current foreground
    window as the paste target ONLY when it is not the manager (i.e. the
    user clicked the chat input or any other window). It NEVER steals or
    restores focus itself — that would fight normal interaction (search,
    settings, right-click) inside the manager. The recorded target is used
    by the caller exactly once, when an emoji is clicked, to hand focus
    back to the chat input and paste.
    后台跟踪器：每个 tick，仅当当前前台不是管理器时（即用户点击了聊天
    输入框或其他窗口），把它记为粘贴目标。它本身绝不抢夺或归还焦点——
    那会干扰管理器内的正常操作（搜索、设置、右键）。记录的目标由调用方
    在点击表情时使用一次：把焦点还给聊天输入框并粘贴。"""

    # Read-only poll interval: frequent enough to track the chat window,
    # cheap enough to never disturb interaction. / 只读轮询间隔：足够频繁
    # 地跟踪聊天窗口，又足够轻量不干扰交互。
    IDLE_MS = 300

    def __init__(self, manager_hwnd, enabled=True):
        self._manager = int(manager_hwnd or 0)
        self._target = 0
        self._enabled = bool(enabled)
        self._tick = None  # QTimer / Qt 定时器

    def set_manager(self, manager_hwnd):
        self._manager = int(manager_hwnd or 0)

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)
        if not self._enabled:
            if self._tick is not None:
                self._tick.stop()
        else:
            # Restart the tracker when re-enabled: a previous
            # set_enabled(False) stopped the timer, so turning it back on
            # must start it again (otherwise the guard goes dead and the
            # paste target stays stale forever).
            # 重新启用时重启定时器：此前 set_enabled(False) 已停止定时器，
            # 再次开启必须重新 start（否则守卫失效、粘贴目标永久陈旧）。
            if self._tick is not None:
                self._tick.start(self.IDLE_MS)

    def start(self):
        # Start the tracker loop (must be called from the GUI thread) /
        # 启动跟踪循环（须在 GUI 线程调用）
        if self._tick is None:
            from PySide6.QtCore import QTimer
            self._tick = QTimer()
            self._tick.timeout.connect(self.tick)
        self._tick.start(self.IDLE_MS)

    def stop(self):
        if self._tick is not None:
            self._tick.stop()

    def target(self):
        return self._target

    def tick(self):
        # Read-only: remember the foreground window unless it is the manager
        # itself or a window owned by this process (dialogs, settings,
        # file pickers). Never steals or restores focus.
        # 只读：记住前台窗口，除非它就是管理器或本进程所属窗口（对话框、
        # 设置、文件选择器）。绝不抢焦点或归还焦点。
        if not self._enabled or not self._manager:
            return
        fg = foreground_window()
        if not fg or fg == self._manager:
            return
        # Skip windows owned by our own process: a QMessageBox, the settings
        # dialog, or a file picker is a top-level HWND of this process and
        # would otherwise be recorded as the paste target, later pasting
        # into the manager itself after the dialog closes.
        # 跳过本进程所属窗口：QMessageBox、设置对话框、文件选择器都是本进程
        # 的顶层 HWND，若不排除会被记为粘贴目标，对话框关闭后把内容粘贴进
        # 管理器自身。
        try:
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
            if pid.value == os.getpid():
                return
        except Exception:
            return
        self._target = fg
