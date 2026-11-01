"""Windows backend: registry, Win32 window/input APIs and DWM chrome.

Everything Windows-specific that used to be scattered across `main.py`,
`main_window.py`, `hotkey_manager.py`, `input_sender.py`, `gpu_pref.py` and
`frameless_dialog.py` now lives behind this one module. It registers itself with
`gifmanager.platform.base.Platform` at import time, so no caller has to test
`sys.platform`.

Windows 后端：注册表、Win32 窗口/输入接口与 DWM 外观。

此前散落在 `main.py`、`main_window.py`、`hotkey_manager.py`、`input_sender.py`、
`gpu_pref.py` 与 `frameless_dialog.py` 中的 Windows 专有代码，现在全部位于这一个
模块之后。它在导入时向 `gifmanager.platform.base.Platform` 注册自己，因此没有
调用方需要判断 `sys.platform`。
"""
import logging
import os
import re
import sys
import threading
import time

from gifmanager.core import gpu as gpu_policy
from gifmanager.core import hotkeys as hotkey_core
from gifmanager.platform import base, paths as generic_paths, process

log = logging.getLogger("GIFManager")

IS_WINDOWS = os.name == "nt"


# ===========================================================================
# Paths / 路径
# ===========================================================================

def user_data_dir():
    # %APPDATA%\GIFManager — roaming, because the settings and the emoji
    # database are user data that should follow a roaming profile.
    # %APPDATA%\GIFManager——漫游目录，因为设置与表情数据库属于应随漫游配置文件
    # 迁移的用户数据。
    root = os.environ.get("APPDATA") or os.path.join(
        generic_paths.home_dir(), "AppData", "Roaming")
    return os.path.join(root, generic_paths.APP_DIR_NAME)


def user_config_dir():
    return user_data_dir()


def user_cache_dir():
    # %LOCALAPPDATA% is machine-local and always writable, which is exactly what
    # a cache needs; the previous code used it as the frozen log location.
    # %LOCALAPPDATA% 是本机目录且始终可写，正是缓存需要的；此前的代码把它作为
    # 打包版的日志位置。
    root = os.environ.get("LOCALAPPDATA") or os.path.join(
        generic_paths.home_dir(), "AppData", "Local")
    return os.path.join(root, generic_paths.APP_DIR_NAME)


def user_log_dir():
    return os.path.join(user_cache_dir(), "logs")


def user_documents_dir():
    profile = os.environ.get("USERPROFILE") or generic_paths.home_dir()
    return os.path.join(profile, "Documents")


# ===========================================================================
# Win32 primitives / Win32 原语
# ===========================================================================

_winreg = None
if IS_WINDOWS:
    try:
        import winreg as _winreg
    except ImportError:
        _winreg = None

_user32 = None
_kernel32 = None
_dwmapi = None
_ctypes = None
_wintypes = None

if IS_WINDOWS:
    import ctypes as _ctypes
    import ctypes.wintypes as _wintypes

    _user32 = _ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = _ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        _dwmapi = _ctypes.WinDLL("dwmapi", use_last_error=True)
    except OSError:
        _dwmapi = None

# Window handle functions must declare argtypes/restype, otherwise ctypes
# converts handles through c_int (32-bit), truncating 64-bit handles above
# 2^31 and making handle comparisons (foreground == manager) fail.
# 窗口句柄函数必须声明 argtypes/restype，否则 ctypes 按 c_int（32 位）转换句柄，
# 64 位句柄超过 2^31 会被截断，导致句柄比较（前台 == 管理器）失配。
if _user32 is not None:
    _user32.GetForegroundWindow.restype = _wintypes.HWND
    for _name, _args in (
        ("SetForegroundWindow", (_wintypes.HWND,)),
        ("BringWindowToTop", (_wintypes.HWND,)),
        ("IsWindow", (_wintypes.HWND,)),
        ("ShowWindow", (_wintypes.HWND, _ctypes.c_int)),
    ):
        _getattr = getattr(_user32, _name)
        _getattr.argtypes = _args
        _getattr.restype = _wintypes.BOOL
    _user32.GetWindowThreadProcessId.argtypes = (
        _wintypes.HWND, _ctypes.POINTER(_wintypes.DWORD))
    _user32.GetWindowThreadProcessId.restype = _wintypes.DWORD
    _user32.AttachThreadInput.argtypes = (
        _wintypes.DWORD, _wintypes.DWORD, _wintypes.BOOL)
    _user32.AttachThreadInput.restype = _wintypes.BOOL
    _user32.GetClassNameW.argtypes = (
        _wintypes.HWND, _wintypes.LPWSTR, _ctypes.c_int)
    _user32.GetClassNameW.restype = _ctypes.c_int
    _user32.SendMessageW.argtypes = (
        _wintypes.HWND, _wintypes.UINT, _wintypes.WPARAM, _wintypes.LPARAM)
    _user32.SendMessageW.restype = _ctypes.c_ssize_t
    _user32.EnumChildWindows.argtypes = (
        _wintypes.HWND,
        _ctypes.WINFUNCTYPE(_ctypes.c_bool, _wintypes.HWND, _wintypes.LPARAM),
        _wintypes.LPARAM)
    _user32.EnumChildWindows.restype = _wintypes.BOOL
    _user32.GetGUIThreadInfo.argtypes = (_wintypes.DWORD, _ctypes.c_void_p)
    _user32.GetGUIThreadInfo.restype = _wintypes.BOOL


# ===========================================================================
# Single instance / 单实例
# ===========================================================================

class WindowsSingleInstance(base.SingleInstanceBackend):
    # Named-mutex single-instance guard.
    #
    # The mutex name is independent of the .py/.exe file name and does not rely
    # on PIDs, so it keeps working after packaging into an exe and across
    # different launch paths.
    # 命名互斥量的单实例守卫。
    #
    # 互斥名与 .py/.exe 文件名无关、不依赖 PID，因此打包成 exe 后依然有效，不同的
    # 启动路径也能互相识别。
    name = "windows-mutex"
    available = IS_WINDOWS

    # ERROR_ALREADY_EXISTS / 已存在
    ERROR_ALREADY_EXISTS = 183

    def __init__(self):
        self._handles = {}

    def acquire(self, name):
        if not IS_WINDOWS:
            return True, None
        mutex_name = f"Local\\{name}_SingleInstance"
        handle = _kernel32.CreateMutexW(None, False, mutex_name)
        already = _kernel32.GetLastError() == self.ERROR_ALREADY_EXISTS
        if already:
            _kernel32.CloseHandle(handle)
            return False, None
        self._handles[mutex_name] = handle
        return True, handle

    def release(self, handle):
        if handle is None:
            return True
        try:
            _kernel32.CloseHandle(handle)
        except Exception:
            return False
        for key, value in list(self._handles.items()):
            if value == handle:
                del self._handles[key]
        return True


# ===========================================================================
# Window chrome / 窗口外观
# ===========================================================================

class WindowsWindow(base.WindowBackend):
    # DWM corner preference and taskbar visibility.
    # DWM 圆角首选项与任务栏可见性。
    name = "windows-dwm"
    available = IS_WINDOWS

    # DWMWA_WINDOW_CORNER_PREFERENCE / 圆角首选项属性
    DWMWA_WINDOW_CORNER_PREFERENCE = 33
    # DWMWCP_ROUND / 圆角
    DWMWCP_ROUND = 2
    # DWMWA_SYSTEMBACKDROP_TYPE / 系统背景材质属性
    DWMWA_SYSTEMBACKDROP_TYPE = 38
    # DWMWA_USE_IMMERSIVE_DARK_MODE / 沉浸式深色模式属性
    DWMWA_USE_IMMERSIVE_DARK_MODE = 20

    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_APPWINDOW = 0x00040000
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_NOZORDER = 0x0004
    SWP_FRAMECHANGED = 0x0020

    def _set_attribute(self, hwnd, attribute, value):
        if not IS_WINDOWS or _dwmapi is None or not hwnd:
            return False
        try:
            _dwmapi.DwmSetWindowAttribute(
                int(hwnd), attribute,
                _ctypes.byref(_ctypes.c_int(value)),
                _ctypes.sizeof(_ctypes.c_int))
            return True
        except Exception:
            # Windows 10 and earlier do not implement these attributes; the
            # square corners are simply kept.
            # Windows 10 及更早版本不实现这些属性；保持直角即可。
            return False

    def apply_rounded_corners(self, hwnd):
        return self._set_attribute(
            hwnd, self.DWMWA_WINDOW_CORNER_PREFERENCE, self.DWMWCP_ROUND)

    def apply_backdrop(self, hwnd, material):
        # 2 = Mica, 3 = Acrylic (Windows 11 22H2+). Unknown names are ignored.
        # 2 = 云母，3 = 亚克力（Windows 11 22H2+）。未知名称忽略。
        kinds = {"mica": 2, "acrylic": 3, "tabbed": 4}
        kind = kinds.get(str(material).lower())
        if kind is None:
            return False
        return self._set_attribute(
            hwnd, self.DWMWA_SYSTEMBACKDROP_TYPE, kind)

    def set_dark_mode(self, hwnd, dark):
        return self._set_attribute(
            hwnd, self.DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if dark else 0)

    def set_skip_taskbar(self, hwnd, skip):
        if not IS_WINDOWS or not hwnd:
            return False
        try:
            style = _user32.GetWindowLongW(int(hwnd), self.GWL_EXSTYLE)
            if skip:
                style = (style | self.WS_EX_TOOLWINDOW) & ~self.WS_EX_APPWINDOW
            else:
                style = (style | self.WS_EX_APPWINDOW) & ~self.WS_EX_TOOLWINDOW
            _user32.SetWindowLongW(int(hwnd), self.GWL_EXSTYLE, style)
            _user32.SetWindowPos(
                int(hwnd), 0, 0, 0, 0, 0,
                self.SWP_NOMOVE | self.SWP_NOSIZE | self.SWP_NOZORDER
                | self.SWP_FRAMECHANGED)
            return True
        except Exception as exc:
            log.warning("set_skip_taskbar: failed for %s -> %s", hwnd, exc)
            return False


# ===========================================================================
# Global hotkeys / 全局热键
# ===========================================================================

# Win32 modifier flags / Win32 修饰键标志
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

# WM_APP-range commands that marshal registration onto the hotkey thread.
# `RegisterHotKey` with a NULL window posts WM_HOTKEY to the REGISTERING
# thread, so every registration/unregistration MUST happen on the same
# dedicated thread that runs the message pump — a registration from any other
# thread would queue WM_HOTKEY where nobody ever reads it.
# WM_APP 区段命令：把注册编组到热键线程。`RegisterHotKey` 在窗口为 NULL 时把
# WM_HOTKEY 投递给"注册线程"，因此一切注册/注销都必须与消息泵同线程——在其他线程
# 注册会让 WM_HOTKEY 排进一个永远无人读取的队列。
WM_APP_REREGISTER = 0x8100
WM_APP_UNREGISTER = 0x8101

# Window messages for the clipboard and focus handling /
# 剪贴板与焦点处理所用的窗口消息
WM_PASTE = 0x0302

# Virtual-key codes for the named keys a global hotkey may use /
# 全局热键可能使用的具名按键的虚拟键码
_VK_NAMED = {
    "SPACE": 0x20, "TAB": 0x09, "ESC": 0x1B, "ENTER": 0x0D,
    "BACKSPACE": 0x08, "DELETE": 0x2E, "INSERT": 0x2D,
    "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21, "PAGEDOWN": 0x22,
    "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
    "MINUS": 0xBD, "EQUAL": 0xBB, "COMMA": 0xBC, "PERIOD": 0xBE,
    "SLASH": 0xBF, "SEMICOLON": 0xBA, "QUOTE": 0xDE,
    "BRACKETLEFT": 0xDB, "BRACKETRIGHT": 0xDD, "BACKSLASH": 0xDC,
    "GRAVE": 0xC0,
    # RegisterHotKey takes KEYBOARD virtual keys, so the mouse markers only
    # map to something syntactically valid; a mouse-button hotkey is not
    # reliable on Windows and the UI should say so.
    # RegisterHotKey 取的是"键盘"虚拟键，因此鼠标标记只映射到语法上合法的值；
    # Windows 上鼠标键热键并不可靠，界面应说明这一点。
    "MOUSE4": 0x05, "MOUSE5": 0x06,
}


def key_to_vk(key_name):
    # Portable key name -> Win32 virtual-key code, or None /
    # 可移植按键名 -> Win32 虚拟键码，未知返回 None
    name = hotkey_core.canonical_key(key_name)
    if not name:
        return None
    if len(name) == 1 and name.isalpha():
        return ord(name)
    if len(name) == 1 and name.isdigit():
        return ord(name)
    if name.startswith("F") and name[1:].isdigit():
        number = int(name[1:])
        if 1 <= number <= 24:
            return 0x70 + (number - 1)
    return _VK_NAMED.get(name)


def modifiers_to_win(modifiers):
    flags = 0
    if modifiers & hotkey_core.MOD_CTRL:
        flags |= MOD_CONTROL
    if modifiers & hotkey_core.MOD_ALT:
        flags |= MOD_ALT
    if modifiers & hotkey_core.MOD_SHIFT:
        flags |= MOD_SHIFT
    if modifiers & hotkey_core.MOD_META:
        flags |= MOD_WIN
    return flags


class WindowsHotkeyBackend(base.HotkeyBackend):
    # Registers global hotkeys with `RegisterHotKey` and reports presses
    # through a callback.
    #
    # `RegisterHotKey` posts `WM_HOTKEY` to the CALLING THREAD's message queue,
    # so registration and the message pump must share one dedicated thread.
    # Running that thread here — instead of relying on the host toolkit's native
    # event filter — means the Qt layer needs no Windows-specific code at all,
    # and a message Qt happened to consume can never swallow a hotkey.
    # The callback is therefore invoked on this thread and must marshal to the
    # UI thread itself (the Qt front-end uses a queued signal).
    #
    # 用 `RegisterHotKey` 注册全局热键，并通过回调上报按键。
    #
    # `RegisterHotKey` 把 `WM_HOTKEY` 投递到"调用线程"的消息队列，因此注册与消息
    # 循环必须共用同一个专用线程。把该线程放在这里——而不是依赖宿主工具包的原生
    # 事件过滤器——使 Qt 层完全不需要 Windows 专有代码，且被 Qt 消费掉的消息也
    # 不可能吞掉热键。因此回调在本线程上触发，需自行转投到界面线程（Qt 前端用
    # 队列信号完成）。
    name = "windows-registerhotkey"
    available = IS_WINDOWS

    # Ids: 1 is the live hotkey, 101 a probe used to test a combination without
    # dropping the currently registered one.
    # id：1 为生效热键，101 为探测用，用于在不丢弃当前注册的情况下测试组合键。
    HOTKEY_ID = 1
    PROBE_ID = 101

    def __init__(self):
        self._lock = threading.RLock()
        self._binding = None
        self._callback = None
        self._thread = None
        self._thread_id = None
        self._ready = threading.Event()
        # Completed by the pump thread after a marshalled re-register/unregister,
        # so `register()` can return the real outcome synchronously.
        # 由泵线程在编组后的重注册/注销完成后置位，使 `register()` 能同步拿到真实结果。
        self._register_done = threading.Event()
        self._registered = False

    # ---- thread management / 线程管理 ----------------------------------

    def _ensure_thread(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._ready.clear()
            self._thread = threading.Thread(
                target=self._message_loop, name="WinHotkeyThread", daemon=True)
            self._thread.start()
            # Wait for the thread to own a message queue before any
            # registration happens on it.
            # 在它上面执行任何注册前，先等该线程拥有消息队列。
            self._ready.wait(timeout=3.0)

    def _message_loop(self):
        self._thread_id = _kernel32.GetCurrentThreadId()
        # Force the queue into existence so `RegisterHotKey` from this thread
        # works immediately.
        # 强制创建消息队列，使本线程上的 `RegisterHotKey` 立即可用。
        msg = _wintypes.MSG()
        _user32.PeekMessageW(_ctypes.byref(msg), 0, 0, 0, 0)
        # Register the pending binding BEFORE announcing readiness: the caller
        # of `register()` returns the result it finds after `_ready`, and a
        # binding registered by the CALLER's thread would never receive its
        # WM_HOTKEY (this thread owns the pump).
        # 在宣布就绪"之前"注册待注册的绑定：`register()` 的调用方在 `_ready` 之后
        # 读取结果，而由调用方线程完成的注册永远收不到自己的 WM_HOTKEY（消息泵在本
        # 线程）。
        with self._lock:
            if self._binding is not None:
                self._register_locked(self._binding)
        self._ready.set()
        # The startup registration is also an outcome `register()` waits for:
        # thread scheduling can starve it well past `_ready`, and a caller that
        # reads `_registered` before this line would report a live hotkey as
        # refused.
        # 启动注册同样是 `register()` 要等的"结果"：线程调度可能让它远晚于 `_ready`
        # 才运行，而在此行之前读取 `_registered` 的调用方会把活着的热键报成被拒绝。
        self._register_done.set()
        while True:
            result = _user32.GetMessageW(_ctypes.byref(msg), 0, 0, 0)
            if result in (0, -1):  # WM_QUIT or error / 退出或出错
                break
            if msg.message == WM_HOTKEY:
                with self._lock:
                    callback = self._callback
                if callback is not None:
                    try:
                        callback()
                    except Exception:
                        log.exception("hotkey callback failed")
            elif msg.message == WM_APP_REREGISTER:
                with self._lock:
                    if self._binding is not None:
                        self._register_locked(self._binding)
                self._register_done.set()
            elif msg.message == WM_APP_UNREGISTER:
                with self._lock:
                    self._unregister_locked()
                self._register_done.set()
            _user32.TranslateMessage(_ctypes.byref(msg))
            _user32.DispatchMessageW(_ctypes.byref(msg))
        with self._lock:
            self._unregister_locked()
        self._thread_id = None

    def _stop_thread(self):
        with self._lock:
            thread = self._thread
            thread_id = self._thread_id
        if thread is None:
            return
        if thread_id:
            _user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
        thread.join(timeout=2.0)
        with self._lock:
            self._thread = None

    # ---- registration / 注册 -------------------------------------------

    def _vk_and_mods(self, binding):
        vk = key_to_vk(binding.key)
        if vk is None:
            return None, None
        return vk, modifiers_to_win(binding.modifiers) | MOD_NOREPEAT

    def _register_locked(self, binding):
        vk, mods = self._vk_and_mods(binding)
        if vk is None:
            log.warning("hotkey: %r has no Windows key code", binding.key)
            return False
        # Probe first: registering the live id directly would drop a working
        # hotkey when the new combination is already taken by another program.
        # 先探测：直接注册生效 id 会在新组合键已被其他程序占用时丢掉正在工作的热键。
        if not _user32.RegisterHotKey(0, self.PROBE_ID, mods, vk):
            error = _ctypes.get_last_error()
            log.info("hotkey: combination already in use (err=%s)", error)
            return False
        _user32.UnregisterHotKey(0, self.PROBE_ID)
        if self._registered:
            _user32.UnregisterHotKey(0, self.HOTKEY_ID)
            self._registered = False
        if not _user32.RegisterHotKey(0, self.HOTKEY_ID, mods, vk):
            log.warning("hotkey: registration failed for %s", binding.describe())
            return False
        self._registered = True
        return True

    def _unregister_locked(self):
        if self._registered:
            _user32.UnregisterHotKey(0, self.HOTKEY_ID)
            self._registered = False

    def register(self, hotkey_id, binding, callback):
        if not IS_WINDOWS:
            return None
        if not binding.is_set:
            self.unregister_all()
            return None
        with self._lock:
            self._binding = binding
            self._callback = callback
            fresh = self._thread is None
            self._register_done.clear()
        if fresh:
            # A fresh thread registers the binding itself before it reports
            # readiness (see `_message_loop`); the wait below is what makes the
            # OUTCOME (not just the queue) observable.
            # 新线程在报告就绪前自行注册绑定（见 `_message_loop`）；下面的等待让
            # "结果"（而不只是队列）可被观察。
            self._ensure_thread()
        else:
            # The pump already runs: marshal the registration onto it. Doing it
            # on the caller's thread would put WM_HOTKEY in a queue nobody
            # pumps.
            # 泵已在跑：把注册编组过去。在调用方线程注册会让 WM_HOTKEY 排进无人
            # 泵送的队列。
            _user32.PostThreadMessageW(self._thread_id, WM_APP_REREGISTER,
                                       0, 0)
        # Both paths converge here: the pump sets `_register_done` after the
        # registration attempt, so this read sees the final state.
        # 两条路径在此汇合：泵在注册尝试后置位 `_register_done`，因此这次读取看到的
        # 是最终状态。
        self._register_done.wait(timeout=2.0)
        with self._lock:
            return hotkey_id if self._registered else None

    def unregister(self, token):
        with self._lock:
            thread_id = self._thread_id
            self._binding = None
            self._callback = None
            if not self._registered:
                return True
            self._register_done.clear()
        if thread_id:
            # Unregistration must run on the thread that owns the registration.
            # 注销必须在持有注册的线程上执行。
            _user32.PostThreadMessageW(thread_id, WM_APP_UNREGISTER, 0, 0)
            self._register_done.wait(timeout=2.0)
        else:
            with self._lock:
                self._unregister_locked()
        return True

    def unregister_all(self):
        with self._lock:
            self._unregister_locked()
            self._binding = None
            self._callback = None
        self._stop_thread()
        return 1

    @property
    def is_registered(self):
        with self._lock:
            return self._registered

    def shutdown(self):
        return self.unregister_all()


# Low-level mouse hook constants for the global scroll watcher /
# 全局滚动监视所用的低级鼠标钩子常量
WH_MOUSE_LL = 14
WM_MOUSEWHEEL = 0x020A
WM_MOUSEHWHEEL = 0x020E
VK_MENU = 0x12


class WindowsScrollWatcher(base.HotkeyBackend):
    # Reports global Alt+wheel events through a low-level mouse hook.
    #
    # A `WH_MOUSE_LL` hook requires a running message loop on the installing
    # thread, so the hook lives on its own thread here. `GetAsyncKeyState` is
    # polled as a fallback when the hook cannot be installed (locked-down
    # environments), which is why the poll interval exists.
    # 通过低级鼠标钩子上报全局 Alt+滚轮事件。
    #
    # `WH_MOUSE_LL` 钩子要求安装线程运行消息循环，因此钩子放在自己的线程上。钩子
    # 无法安装时（受限环境）回退为轮询 `GetAsyncKeyState`，这就是轮询间隔存在的
    # 原因。
    name = "windows-mousehook"
    available = IS_WINDOWS

    POLL_MS = 50

    def __init__(self):
        self._hook = None
        self._thread = None
        self._thread_id = None
        self._callback = None
        self._lock = threading.RLock()
        self._running = False

    def _mouse_proc(self, n_code, w_param, l_param):
        if n_code >= 0 and w_param in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
            try:
                if _user32.GetAsyncKeyState(VK_MENU) & 0x8000:
                    data = _ctypes.cast(
                        l_param,
                        _ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
                    delta = _ctypes.c_short(data.mouseData >> 16).value
                    horizontal = w_param == WM_MOUSEHWHEEL
                    with self._lock:
                        callback = self._callback
                    if callback is not None and delta:
                        try:
                            callback(delta, horizontal)
                        except Exception:
                            log.exception("scroll callback failed")
            except Exception:
                log.exception("scroll hook failed to decode the event")
        return _user32.CallNextHookEx(self._hook, n_code, w_param, l_param)

    def _hook_thread(self):
        self._thread_id = _kernel32.GetCurrentThreadId()
        proc_type = _ctypes.WINFUNCTYPE(
            _ctypes.c_int, _ctypes.c_int, _ctypes.c_size_t, _ctypes.c_size_t)
        self._proc = proc_type(self._mouse_proc)
        self._hook = _user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, None, 0)
        message = _wintypes.MSG()
        # Pump messages so the hook callback is delivered; the hook is removed
        # when the loop exits.
        # 泵送消息以投递钩子回调；循环退出时移除钩子。
        while self._running:
            if _user32.PeekMessageW(
                    _ctypes.byref(message), 0, 0, 0, 1):  # PM_REMOVE / 移除取出的消息
                _user32.TranslateMessage(_ctypes.byref(message))
                _user32.DispatchMessageW(_ctypes.byref(message))
            else:
                time.sleep(self.POLL_MS / 1000.0)
        if self._hook:
            try:
                _user32.UnhookWindowsHookEx(self._hook)
            except Exception:
                pass
        self._hook = None
        self._thread_id = None

    def start(self, callback):
        if not IS_WINDOWS or self._running:
            return False
        with self._lock:
            self._callback = callback
            self._running = True
        self._thread = threading.Thread(
            target=self._hook_thread, name="WinScrollHook", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        if not self._running:
            return True
        self._running = False
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None
        with self._lock:
            self._callback = None
        return True


class _MSLLHOOKSTRUCT(_ctypes.Structure if _ctypes else object):
    # Declared once at module level rather than re-created on every wheel event
    # (the previous implementation built a new Structure subclass per message).
    # 在模块级声明一次，而不是每次滚轮事件都重建（此前实现每条消息都新建一个
    # Structure 子类）。
    if _ctypes:
        _fields_ = [
            ("pt", _wintypes.POINT),
            ("mouseData", _wintypes.DWORD),
            ("flags", _wintypes.DWORD),
            ("time", _wintypes.DWORD),
            ("dwExtraInfo", _ctypes.c_void_p),
        ]


# ===========================================================================
# Input injection / 输入注入
# ===========================================================================

# Win32 INPUT/KEYBDINPUT layout.
#
# The union inside INPUT is as large as its biggest member (MOUSEINPUT = 32
# bytes), so INPUT is 40 bytes total. ctypes must reproduce that layout,
# otherwise SendInput returns ERROR_INVALID_PARAMETER (87).
# Win32 INPUT/KEYBDINPUT 布局。
#
# INPUT 内 union 的大小取最大成员（MOUSEINPUT = 32 字节），故 INPUT 总长 40 字节。
# ctypes 必须复现该布局，否则 SendInput 返回 ERROR_INVALID_PARAMETER(87)。
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

VK_CONTROL = 0x11
VK_V = 0x56


if _ctypes:
    class _KEYBDINPUT(_ctypes.Structure):
        _fields_ = [
            ("wVk", _wintypes.WORD),
            ("wScan", _wintypes.WORD),
            ("dwFlags", _wintypes.DWORD),
            ("time", _wintypes.DWORD),
            ("dwExtraInfo", _ctypes.c_size_t),
        ]

    class _MOUSEINPUT(_ctypes.Structure):
        _fields_ = [
            ("dx", _wintypes.LONG),
            ("dy", _wintypes.LONG),
            ("mouseData", _wintypes.DWORD),
            ("dwFlags", _wintypes.DWORD),
            ("time", _wintypes.DWORD),
            ("dwExtraInfo", _ctypes.c_size_t),
        ]

    class _HARDWAREINPUT(_ctypes.Structure):
        _fields_ = [
            ("uMsg", _wintypes.DWORD),
            ("wParamL", _wintypes.WORD),
            ("wParamH", _wintypes.WORD),
        ]

    class _INPUT(_ctypes.Structure):
        _pack_ = 8  # SDK: INPUT is 8-aligned / SDK：INPUT 按 8 字节对齐

        class _UNION(_ctypes.Union):
            _fields_ = [
                ("ki", _KEYBDINPUT),
                ("mi", _MOUSEINPUT),
                ("hi", _HARDWAREINPUT),
            ]

        _anonymous_ = ("i",)
        _fields_ = [("type", _wintypes.DWORD), ("i", _UNION)]


class WindowsInput(base.InputBackend):
    # Paste into whichever window owned focus, without stealing it.
    #
    # The manager window is a Tool window shown without activating, and a
    # background guard records the last non-manager foreground window. Ctrl+V
    # sent through `SendInput` therefore lands in the chat input even while the
    # user is clicking stickers in the manager.
    # 向此前持有焦点的窗口粘贴，且不抢焦点。
    #
    # 管理器是 Tool 窗口、显示时不激活，后台守卫记录最近一个非管理器的前台窗口。
    # 因此经 `SendInput` 发送的 Ctrl+V 总是落在聊天输入框，即使用户正在管理器里点击
    # 表情。
    name = "windows-sendinput"
    available = IS_WINDOWS

    # One keyboard event (down or up) for a virtual key.
    #
    # The short delay between events lets the target application (a Qt-based
    # chat client in particular) process each keystroke separately; without it,
    # Ctrl+V can be misread as a lone "v" character.
    # 为某个虚拟键发送单个按键事件（按下或抬起）。
    #
    # 事件间的短暂延迟让目标程序（尤其基于 Qt 的聊天客户端）逐个处理按键；否则
    # Ctrl+V 可能被误读为孤立的 "v" 字符。
    def _send_key(self, vk, up=False, delay_ms=8):
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)
        key_input = _KEYBDINPUT()
        key_input.wVk = vk
        key_input.dwFlags = KEYEVENTF_KEYUP if up else 0
        payload = _INPUT()
        payload.type = INPUT_KEYBOARD
        payload.ki = key_input
        sent = _user32.SendInput(
            1, _ctypes.byref(payload), _ctypes.sizeof(_INPUT))
        if sent != 1:
            log.warning("input: SendInput failed (vk=%s up=%s err=%s)",
                        vk, up, _ctypes.get_last_error())
            return False
        return True

    def paste_to_foreground(self, delay_ms=50):
        if not IS_WINDOWS:
            return False
        time.sleep(delay_ms / 1000.0)
        ok = True
        try:
            ok &= self._send_key(VK_CONTROL, delay_ms=0)
            time.sleep(0.02)   # hold Ctrl before V / 先稳住 Ctrl
            ok &= self._send_key(VK_V, delay_ms=0)
            time.sleep(0.02)   # brief press duration / 短暂按压
            ok &= self._send_key(VK_V, up=True, delay_ms=0)
            time.sleep(0.02)   # release V before Ctrl / 先松 V 再松 Ctrl
        finally:
            # Always release Ctrl, even when a SendInput call failed: leaving it
            # held would prefix every later keystroke with Ctrl.
            # 无论是否失败都释放 Ctrl：残留按下会让后续所有按键都带 Ctrl 前缀。
            self._send_key(VK_CONTROL, up=True, delay_ms=0)
        return ok

    def foreground_window(self):
        if not IS_WINDOWS:
            return 0
        return int(_user32.GetForegroundWindow() or 0)

    def bring_to_front(self, window_id):
        # AttachThreadInput bypasses the Windows foreground lock so
        # SetForegroundWindow works even though our process was just activated.
        # AttachThreadInput 绕过 Windows 前台锁，使 SetForegroundWindow 即使在本
        # 进程刚被激活时也有效。
        if not IS_WINDOWS or not window_id:
            return False
        try:
            current = _kernel32.GetCurrentThreadId()
            target = _user32.GetWindowThreadProcessId(window_id, None)
            attached = False
            if target:
                attached = bool(_user32.AttachThreadInput(current, target, True))
            _user32.SetForegroundWindow(window_id)
            _user32.BringWindowToTop(window_id)
            if attached:
                _user32.AttachThreadInput(current, target, False)
            return True
        except Exception as exc:
            log.warning("bring_to_front: failed for %s -> %s", window_id, exc)
            return False

    def paste_to_window(self, window_id, delay_ms=50):
        # Deliver WM_PASTE straight to a standard Edit/RichEdit control. Newer
        # chat clients are Qt applications whose input is not a standard edit
        # control, so this returns False and the caller falls back to SendInput.
        # 向标准 Edit/RichEdit 控件直接投递 WM_PASTE。较新的聊天客户端是 Qt 应用，
        # 其输入框不是标准编辑控件，因此返回 False，由调用方回退到 SendInput。
        if not IS_WINDOWS or not window_id:
            return False
        time.sleep(delay_ms / 1000.0)
        edits = self._find_edit_children(window_id)
        if not edits:
            return False
        try:
            _user32.SendMessageW(edits[0], WM_PASTE, 0, 0)
            return True
        except Exception:
            return False

    # Class names of standard text controls across QQ/WeChat builds /
    # QQ/微信各版本中标准文本控件的类名
    _EDIT_CLASSES = frozenset((
        "Edit", "RichEdit20W", "RichEdit20A", "RICHEDIT", "RICHEDIT50W",
        "RichEditD2DPT", "ATL:Edit", "EditW",
    ))

    def _find_edit_children(self, hwnd, depth=0):
        if not hwnd or depth > 4:
            return []
        found = []

        def collect(handle, _param):
            try:
                buffer = _ctypes.create_unicode_buffer(64)
                _user32.GetClassNameW(handle, buffer, 64)
                if buffer.value in self._EDIT_CLASSES:
                    found.append(int(handle))
            except Exception:
                pass
            return True

        callback_type = _ctypes.WINFUNCTYPE(
            _ctypes.c_bool, _wintypes.HWND, _wintypes.LPARAM)
        _user32.EnumChildWindows(hwnd, callback_type(collect), 0)
        if found:
            return found
        for child in self._children_of(hwnd):
            found.extend(self._find_edit_children(child, depth + 1))
        return found

    def _children_of(self, hwnd):
        children = []

        def collect(handle, _param):
            children.append(int(handle))
            return True

        callback_type = _ctypes.WINFUNCTYPE(
            _ctypes.c_bool, _wintypes.HWND, _wintypes.LPARAM)
        _user32.EnumChildWindows(hwnd, callback_type(collect), 0)
        return children

    def focused_child(self, window_id):
        # The window that currently owns keyboard focus in `window_id`'s thread,
        # or 0. / `window_id` 所在线程当前持有键盘焦点的窗口，无则 0。
        if not IS_WINDOWS or not window_id:
            return 0
        try:
            class _GUITHREADINFO(_ctypes.Structure):
                _fields_ = [
                    ("cbSize", _wintypes.DWORD),
                    ("flags", _wintypes.DWORD),
                    ("hwndActive", _wintypes.HWND),
                    ("hwndFocus", _wintypes.HWND),
                    ("hwndCapture", _wintypes.HWND),
                    ("hwndMenuOwner", _wintypes.HWND),
                    ("hwndMoveSize", _wintypes.HWND),
                    ("hwndCaret", _wintypes.HWND),
                    ("rcCaret", _wintypes.RECT),
                ]

            thread_id = _user32.GetWindowThreadProcessId(window_id, None)
            info = _GUITHREADINFO()
            info.cbSize = _ctypes.sizeof(_GUITHREADINFO)
            if not _user32.GetGUIThreadInfo(thread_id, _ctypes.byref(info)):
                return 0
            return int(info.hwndFocus or 0)
        except Exception:
            return 0

    def owns_window(self, window_id):
        # True when the window belongs to this process, so the focus tracker can
        # ignore our own dialogs, settings page and file pickers.
        # 窗口属于本进程时为 True，使焦点跟踪器能忽略自己的对话框、设置页与文件
        # 选择器。
        if not IS_WINDOWS or not window_id:
            return False
        try:
            pid = _wintypes.DWORD()
            _user32.GetWindowThreadProcessId(window_id, _ctypes.byref(pid))
            return pid.value == os.getpid()
        except Exception:
            return False


# ===========================================================================
# GPU preference / GPU 首选项
# ===========================================================================

class WindowsGpuPreference(base.GpuPreferenceBackend):
    # Windows per-application GPU preference.
    #
    # Stored at HKCU\Software\Microsoft\DirectX\UserGpuPreferences, keyed by the
    # FULL PATH of the process image, with the value "GpuPreference=<n>;".
    # Windows keys on the executable that is actually running — `python.exe`
    # when started from source, the packaged exe when frozen — so the script
    # path must never be used as the key.
    # Windows 按应用的 GPU 首选项。
    #
    # 存于 HKCU\Software\Microsoft\DirectX\UserGpuPreferences，以"进程映像"的完整
    # 路径为键，值为 "GpuPreference=<n>;"。Windows 以真正运行的可执行文件为键——
    # 源码运行时是 python.exe，打包后是应用 exe——因此绝不能拿脚本路径当键。
    name = "windows-registry"
    available = IS_WINDOWS

    REG_PATH = r"Software\Microsoft\DirectX\UserGpuPreferences"
    DISPLAY_CLASS = (r"SYSTEM\CurrentControlSet\Control\Class"
                     r"\{4d36e968-e325-11ce-bfc1-08002be10318}")

    SYSTEM = gpu_policy.PREF_SYSTEM
    POWER = gpu_policy.PREF_POWER
    HIGH = gpu_policy.PREF_HIGH

    def current_executable(self):
        # The process image, which is what Windows keys the preference on.
        # 进程映像，即 Windows 用作首选项键的对象。
        try:
            executable = sys.executable
        except Exception:
            executable = ""
        return os.path.abspath(executable) if executable else ""

    def legacy_executable(self):
        # The script path an older release wrongly used as the registry key.
        #
        # ONLY this application's own launcher qualifies: `sys.argv[0]` is
        # whatever script the interpreter was started with — a test file, or any
        # script the user runs — and deleting its GPU entry would silently
        # discard a preference the user created for that program.
        # 旧版本误用作注册表键的脚本路径。
        #
        # 只有本程序自己的启动脚本才算：`sys.argv[0]` 是解释器启动时使用的任意脚本
        # （测试文件、用户自己的脚本），删除它的 GPU 项会静默丢弃用户为那个程序建立
        # 的偏好。
        if getattr(sys, "frozen", False) or not _winreg:
            return ""
        script = (sys.argv[0] if sys.argv else "") or ""
        if not script:
            return ""
        script = os.path.abspath(script)
        if os.path.basename(script).lower() not in (
                "main.py", "main.pyw", "gifmanager.py", "gifmanager.pyw"):
            return ""
        from gifmanager.core import paths

        if os.path.dirname(script) != paths.project_root():
            return ""
        return script

    def apply(self, executable, preference):
        if not IS_WINDOWS or not _winreg or not executable:
            return False
        preference = gpu_policy.clamp_preference(preference)
        try:
            key = _winreg.CreateKeyEx(
                _winreg.HKEY_CURRENT_USER, self.REG_PATH, 0, _winreg.KEY_SET_VALUE)
        except OSError as exc:
            log.warning("gpu_preference: cannot open the registry key -> %s", exc)
            return False
        try:
            # Drop the legacy entry that used the script path as the key: it
            # never matched, so it only confused things.
            # 删除旧版用脚本路径作为键的残留项：它永远不会被匹配，只会造成误解。
            legacy = self.legacy_executable()
            if legacy and legacy != executable:
                try:
                    _winreg.DeleteValue(key, legacy)
                except FileNotFoundError:
                    pass
            if preference == gpu_policy.PREF_SYSTEM:
                # Remove the override so Windows decides again /
                # 删除覆盖项，交回 Windows 决定
                try:
                    _winreg.DeleteValue(key, executable)
                except FileNotFoundError:
                    pass
            else:
                _winreg.SetValueEx(
                    key, executable, 0, _winreg.REG_SZ,
                    gpu_policy.WINDOWS_VALUE_TEMPLATE.format(preference))
            return True
        except OSError as exc:
            log.warning("gpu_preference: write failed -> %s", exc)
            return False
        finally:
            _winreg.CloseKey(key)

    def get(self, executable):
        if not IS_WINDOWS or not _winreg or not executable:
            return None
        try:
            key = _winreg.OpenKey(
                _winreg.HKEY_CURRENT_USER, self.REG_PATH, 0, _winreg.KEY_READ)
        except OSError:
            return None
        try:
            value, _type = _winreg.QueryValueEx(key, executable)
        except OSError:
            return None
        finally:
            _winreg.CloseKey(key)
        return gpu_policy.parse_windows_value(value)

    def list_adapters(self):
        # Installed display adapters, REGISTRY FIRST.
        #
        # The registry read gives exactly the names Device Manager shows and
        # costs microseconds. The PowerShell route it used to take cost about
        # two seconds, mangled non-ASCII names on a Chinese system (CP936 pipe
        # decoded as UTF-8) and was the first thing to break in a frozen build,
        # where it left the adapter list empty.
        # 已安装的显示适配器，优先读注册表。
        #
        # 注册表读到的名字与设备管理器完全一致且耗时微秒级。此前走的 PowerShell
        # 路线约需两秒、在中文系统上还会把非 ASCII 名称弄乱（CP936 管道按 UTF-8
        # 解码），并且在打包后最先失效，那时适配器列表为空。
        if not IS_WINDOWS:
            return []
        names = self._adapters_from_registry()
        if names:
            return names
        return self._adapters_from_powershell()

    def _adapters_from_registry(self):
        if not _winreg:
            return []
        names = []
        try:
            key = _winreg.OpenKey(
                _winreg.HKEY_LOCAL_MACHINE, self.DISPLAY_CLASS, 0, _winreg.KEY_READ)
        except OSError:
            return []
        try:
            index = 0
            while True:
                try:
                    sub = _winreg.EnumKey(key, index)
                except OSError:
                    break
                index += 1
                # Adapter subkeys are exactly four digits /
                # 适配器子键恰好是四位数字
                if len(sub) != 4 or not sub.isdigit():
                    continue
                try:
                    with _winreg.OpenKey(key, sub, 0, _winreg.KEY_READ) as subkey:
                        name = _winreg.QueryValueEx(subkey, "DriverDesc")[0]
                except OSError:
                    continue
                name = str(name).strip()
                if name and name not in names:
                    names.append(name)
        finally:
            _winreg.CloseKey(key)
        return names

    def _adapters_from_powershell(self):
        # Fallback only, for the unlikely case where the class key is
        # unreadable. UTF-8 is forced on the PowerShell side: a Chinese Windows
        # otherwise encodes the pipe as CP936, so a non-ASCII adapter name
        # decoded as UTF-8 became U+FFFD and was dropped as unclassifiable.
        # 仅作回退，用于类键不可读（很少见）的情况。PowerShell 侧强制 UTF-8：否则
        # 中文 Windows 会用 CP936 编码管道，非 ASCII 的显卡名按 UTF-8 解码变成
        # U+FFFD，随后因无法分类而被丢弃。
        try:
            completed = process.run_capture(
                ["powershell", "-NoProfile", "-Command",
                 "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
                 "(Get-CimInstance Win32_VideoController).Name"],
                timeout=5)
        except (OSError, Exception):
            return []
        text = process.decode_output(completed.stdout)
        if not text.strip():
            text = process.decode_output(completed.stdout, preferred="mbcs")
        return [
            line.strip().replace("\ufffd", "").strip()
            for line in text.splitlines()
            if line.strip().replace("\ufffd", "").strip()
        ]

    def process_adapters(self):
        # Which GPU adapters THIS process has used, from the per-process GPU
        # performance counters. An empty result is the honest answer for a
        # Qt-Widgets application: its interface is painted by the CPU raster
        # engine, so a per-app preference has no GPU work of ours to route.
        # 本进程实际用过的显卡，取自按进程的 GPU 性能计数器。对 Qt Widgets 程序
        # 而言"空"就是诚实答案：界面由 CPU 光栅引擎绘制，按应用首选项没有属于本
        # 进程的 GPU 工作可分派。
        if not IS_WINDOWS:
            return []
        try:
            script = (
                "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
                "Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_"
                "GPUEngine | Where-Object { $_.Name -like 'pid_%d_*' } | "
                "ForEach-Object { $_.Name }" % os.getpid())
            completed = process.run_capture(
                ["powershell", "-NoProfile", "-Command", script], timeout=8)
        except (OSError, Exception):
            return []
        luids = []
        for line in process.decode_output(completed.stdout).splitlines():
            match = re.search(r"luid_0x[0-9a-fA-F]+_0x([0-9a-fA-F]+)", line)
            if match:
                luid = "0x" + match.group(1).upper()
                if luid not in luids:
                    luids.append(luid)
        return luids


# ===========================================================================
# Autostart / 开机自启
# ===========================================================================

class WindowsAutostart(base.AutostartBackend):
    # "Start with Windows" through the per-user Run key.
    #
    # The user-level key needs no elevation, which is why the machine-level
    # equivalent is never touched.
    # 通过按用户的 Run 键实现"开机自启"。
    #
    # 用户级键不需要提权，因此绝不触碰机器级对应项。
    name = "windows-run-key"
    available = IS_WINDOWS

    REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def is_enabled(self, app_id):
        if not IS_WINDOWS or not _winreg:
            return False
        try:
            key = _winreg.OpenKey(
                _winreg.HKEY_CURRENT_USER, self.REG_PATH, 0, _winreg.KEY_READ)
        except OSError:
            return False
        try:
            value, _type = _winreg.QueryValueEx(key, app_id)
            return bool(value)
        except OSError:
            return False
        finally:
            _winreg.CloseKey(key)

    def set_enabled(self, app_id, command, enabled):
        if not IS_WINDOWS or not _winreg:
            return False
        try:
            key = _winreg.OpenKey(
                _winreg.HKEY_CURRENT_USER, self.REG_PATH, 0,
                _winreg.KEY_SET_VALUE | _winreg.KEY_QUERY_VALUE)
        except OSError as exc:
            log.warning("autostart: cannot open the Run key -> %s", exc)
            return False
        try:
            if enabled:
                _winreg.SetValueEx(key, app_id, 0, _winreg.REG_SZ, command)
            else:
                try:
                    _winreg.DeleteValue(key, app_id)
                except FileNotFoundError:
                    pass
            return True
        except OSError as exc:
            log.warning("autostart: write failed -> %s", exc)
            return False
        finally:
            _winreg.CloseKey(key)

    @staticmethod
    def command_for(executable, arguments=()):
        # Quote both parts: a path with spaces is otherwise split by the shell
        # that runs the Run entry.
        # 两部分都加引号：否则含空格的路径会被执行 Run 项的外壳拆开。
        parts = [f'"{executable}"' if " " in executable else executable]
        parts.extend(f'"{a}"' if " " in a else a for a in arguments)
        return " ".join(parts)


# ===========================================================================
# Registration / 注册
# ===========================================================================

SERVICES = {
    "single_instance": WindowsSingleInstance,
    "window": WindowsWindow,
    "hotkeys": WindowsHotkeyBackend,
    "scroll": WindowsScrollWatcher,
    "input": WindowsInput,
    "gpu_preference": WindowsGpuPreference,
    "autostart": WindowsAutostart,
}

PLATFORM_KEY = "win32"


def register():
    base.Platform.REGISTRY["win32"] = __name__
    base.Platform.REGISTRY["cygwin"] = __name__


register()
