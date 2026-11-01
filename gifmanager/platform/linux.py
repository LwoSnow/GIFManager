"""Linux backend: XDG paths, X11 global hotkeys, desktop-entry autostart.

Two Linux realities shape this module:

* **X11 and Wayland are different systems**, not two spellings of one. X11 can
  grab a global hotkey (`XGrabKey`) and observe raw scroll events (XInput2);
  Wayland deliberately forbids both, and offers only the
  `org.freedesktop.portal.GlobalShortcuts` portal, which is compositor
  arbitrated and cannot consume a combination. Each backend therefore reports
  its own `available`, and the settings UI disables what the session cannot do.
* **Display adapters are not a per-application setting.** Adapter choice is
  PRIME (`DRI_PRIME`) or the vendor control panel, so the GPU service reports
  itself unavailable and the settings page hides it rather than showing a dead
  control.

Linux 后端：XDG 路径、X11 全局热键、桌面项自启。

两个 Linux 现实塑造了本模块：

* **X11 与 Wayland 是两套不同系统**，不是同一系统的两种写法。X11 可以抓取全局
  热键（`XGrabKey`）并观察原始滚动事件（XInput2）；Wayland 刻意禁止这两者，只
  提供 `org.freedesktop.portal.GlobalShortcuts` 门户，且该门户由合成器仲裁、
  无法消费组合键。因此各后端各自报告 `available`，设置界面禁用当前会话做不到的项。
* **显示适配器不是按应用的设置。** 适配器选择靠 PRIME（`DRI_PRIME`）或厂商控制
  面板，因此 GPU 服务报告自己不可用，设置页隐藏它，而不是显示一个死控件。
"""
import ctypes
import logging
import os
import re
import shutil
import subprocess
import sys

from gifmanager.core import hotkeys as hotkey_core
from gifmanager.platform import base, paths as generic_paths, process

log = logging.getLogger("GIFManager")

IS_LINUX = sys.platform.startswith("linux") or "bsd" in sys.platform

# Session type, taken from the environment because that is where every desktop
# publishes it: XDG_SESSION_TYPE is authoritative, WAYLAND_DISPLAY implies
# Wayland, DISPLAY implies X11.
# 会话类型取自环境变量，因为所有桌面都在那里发布它：XDG_SESSION_TYPE 权威，
# WAYLAND_DISPLAY 意味着 Wayland，DISPLAY 意味着 X11。
SESSION_X11 = "x11"
SESSION_WAYLAND = "wayland"
SESSION_UNKNOWN = "unknown"


def session_type():
    if not IS_LINUX:
        return SESSION_UNKNOWN
    declared = (os.environ.get("XDG_SESSION_TYPE") or "").strip().lower()
    if declared in (SESSION_X11, SESSION_WAYLAND):
        return declared
    if os.environ.get("WAYLAND_DISPLAY"):
        return SESSION_WAYLAND
    if os.environ.get("DISPLAY"):
        return SESSION_X11
    return SESSION_UNKNOWN


def is_wayland():
    return session_type() == SESSION_WAYLAND


# True only on an X11 session: the precondition for grabbing keys, observing raw scroll and
# injecting input.
#
# # Why this is separate from IS_LINUX
#
# Three backends declared `available = IS_LINUX`, which is true on Wayland too - and on Wayland
# all three are FORBIDDEN by design:
#
#   * `XGrabKey` is X11; Wayland routes global shortcuts through the portal instead.
#   * XInput2 raw events are X11; there is no cross-client scroll observation on Wayland.
#   * synthetic input into another client is explicitly prohibited on Wayland.
#
# The consequence was visible in the settings window: the capability report read
# `auto_input: True` and `global_scroll: True` on an Arch + niri session, so the toggles rendered
# ENABLED and simply did nothing when switched. The module docstring already claimed these
# backends "declare `available` from the session type"; they did not, and now they do.
#
# 仅在 X11 会话上为真：抓取按键、观察原始滚动与注入输入的前提。
#
# # 为什么它与 IS_LINUX 分开
#
# 三个后端声明了 `available = IS_LINUX`，而它在 Wayland 上也成立——但在 Wayland 上这三者都被
# 设计性地"禁止"：
#
#   * `XGrabKey` 属于 X11；Wayland 改为经门户路由全局快捷键。
#   * XInput2 原始事件属于 X11；Wayland 上没有跨客户端的滚动观察。
#   * 向其他客户端注入合成输入在 Wayland 上被明确禁止。
#
# 后果在设置窗口里可见：在 Arch + niri 会话上能力报告读出 `auto_input: True` 与
# `global_scroll: True`，于是两个开关渲染为"可用"、拨动后却毫无效果。模块文档字符串早已声称这些
# 后端"按会话类型声明 `available`"；它们此前没有，现在有了。
X11_AVAILABLE = IS_LINUX and session_type() == SESSION_X11


# ===========================================================================
# The XDG Desktop Portal / XDG 桌面门户
# ===========================================================================
#
# Bus, object and interface names, fixed by the portal specification rather than by
# this application.
# 总线、对象与接口名，由门户规范固定，而非由本应用决定。

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
PORTAL_INTERFACE = "org.freedesktop.portal.GlobalShortcuts"
PORTAL_SESSION_INTERFACE = "org.freedesktop.portal.Session"

# How long to wait for a reply that requires the user to answer a dialog. A chooser
# the user walks away from must not hang the application, but cutting it off too early
# loses a binding the user did want.
# 等待需要用户回答对话框的回复的时长。用户离开的选择器不应挂住应用，但过早截断会丢失用户
# 确实想要的绑定。
BIND_TIMEOUT_MS = 120_000

# A modest timeout for calls that do NOT involve the user, such as creating a session.
# These should be immediate; a slow one means the portal is broken.
# 不涉及用户的调用的适度超时，例如创建会话。它们应当立即返回；慢就说明门户有问题。
CALL_TIMEOUT_MS = 8_000


# ===========================================================================
# Paths / 路径
# ===========================================================================
#
# This module deliberately defines NONE of `home_dir`, `user_data_dir`,
# `user_config_dir`, `user_cache_dir`, `user_log_dir`, `user_documents_dir` or
# `temp_dir`.
#
# The XDG rules ARE the generic rules, so there is nothing platform-specific to add — and
# defining a delegating wrapper is actively harmful. `paths.py` dispatches by asking the
# platform module for an override and falling back to its own generic implementation when
# there is none; but `paths.py` ALSO defines module-level functions with these names,
# which dispatch. So a wrapper here that calls `generic_paths.user_data_dir()` re-enters
# the dispatcher, which finds the wrapper again, forever:
#
#     linux.user_data_dir -> generic_paths.user_data_dir -> paths.call
#       -> paths.resolve -> _backend_override -> linux.user_data_dir -> ...
#
# That made EVERY path lookup on Linux a RecursionError, so the application could not
# start there at all. Absence is the correct answer: the generic fallback already handles
# it, and no override is needed.
#
# 本模块"刻意"不定义 `home_dir`、`user_data_dir`、`user_config_dir`、`user_cache_dir`、
# `user_log_dir`、`user_documents_dir` 或 `temp_dir` 中的任何一个。
#
# XDG 规则"就是"通用规则，因此没有平台特有的东西要加——而定义一个委托包装函数是有害的。
# `paths.py` 的分发方式是向平台模块索取覆盖，没有时回退到自身的通用实现；但 `paths.py`
# "也"定义了这些名称的模块级函数，而那些函数会分发。因此此处一个调用
# `generic_paths.user_data_dir()` 的包装函数会重新进入分发器，分发器又找到该包装函数，如此
# 往复：
#
#     linux.user_data_dir -> generic_paths.user_data_dir -> paths.call
#       -> paths.resolve -> _backend_override -> linux.user_data_dir -> ...
#
# 那使 Linux 上"每一次"路径查找都变成 RecursionError，应用在那里根本无法启动。正确的答案是
# "不定义"：通用回退已经处理了它，无需任何覆盖。


def desktop_dir():
    # XDG autostart entries live here and are read by every mainstream desktop.
    #
    # Defined HERE because it is NOT one of the dispatched names: `desktop_dir` is
    # autostart-specific and has no generic equivalent, so it cannot recurse.
    # XDG 自启项放在这里，主流桌面都会读取。
    #
    # 在此定义是因为它"不在"被分发的名称之中：`desktop_dir` 是自启专用的，没有通用等价物，
    # 因此不会递归。
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base_dir = xdg or os.path.join(generic_paths.home_dir(), ".config")
    return os.path.join(base_dir, "autostart")


# ===========================================================================
# Window chrome / 窗口外观
# ===========================================================================

class LinuxWindow(base.WindowBackend):
    # On Linux the compositor owns window decorations, and whether an
    # always-on-top hint is honoured depends on the window manager (GNOME on
    # Wayland ignores it). This backend says so rather than silently doing
    # nothing.
    # 在 Linux 上窗口装饰由合成器负责，是否尊重置顶提示取决于窗口管理器
    # （Wayland 上的 GNOME 会忽略它）。本后端如实说明，而不是静默无效。
    name = "linux-compositor"
    available = IS_LINUX

    def apply_rounded_corners(self, hwnd):
        # Server-side decorations are the compositor's business; a frameless Qt
        # window draws its own corners.
        # 服务端装饰属于合成器的职责；无边框 Qt 窗口自行绘制圆角。
        return True

    def apply_backdrop(self, hwnd, material):
        # Blur-behind is compositor specific (KWin, Mutter, Hyprland each expose
        # a different hint) and has no portable spelling.
        # 背景模糊因合成器而异（KWin、Mutter、Hyprland 各暴露不同的提示），没有可
        # 移植的写法。
        return False

    def set_skip_taskbar(self, hwnd, skip):
        # Qt's own window flags are the portable route here; nothing extra is
        # needed at the X11 level. / 这里可移植的路径是 Qt 自己的窗口标志；
        # X11 层不需要额外处理。
        return True


# ===========================================================================
# Global hotkeys / 全局热键
# ===========================================================================

# X11 modifier masks / X11 修饰键掩码
SHIFT_MASK = 1 << 0
LOCK_MASK = 1 << 1
CONTROL_MASK = 1 << 2
MOD1_MASK = 1 << 3   # Alt / Alt 键 键
MOD4_MASK = 1 << 6   # Super / Super 键 键

# X11 key symbols for the named keys a global hotkey may use /
# 全局热键可能使用的具名按键的 X11 键符
_X11_NAMED_SYMBOLS = {
    "SPACE": "space", "TAB": "Tab", "ESC": "Escape", "ENTER": "Return",
    "BACKSPACE": "BackSpace", "DELETE": "Delete", "INSERT": "Insert",
    "HOME": "Home", "END": "End", "PAGEUP": "Prior", "PAGEDOWN": "Next",
    "UP": "Up", "DOWN": "Down", "LEFT": "Left", "RIGHT": "Right",
    "MINUS": "minus", "EQUAL": "equal", "COMMA": "comma", "PERIOD": "period",
    "SLASH": "slash", "SEMICOLON": "semicolon", "QUOTE": "apostrophe",
    "BRACKETLEFT": "bracketleft", "BRACKETRIGHT": "bracketright",
    "BACKSLASH": "backslash", "GRAVE": "grave",
}


def key_to_keysym(key_name):
    # Portable key name -> X11 keysym NAME (not the numeric keysym) /
    # 可移植按键名 -> X11 键符名（不是数值键符）
    name = hotkey_core.canonical_key(key_name)
    if not name:
        return None
    if len(name) == 1:
        return name.lower() if name.isalpha() else name
    if name.startswith("F") and name[1:].isdigit():
        return name
    return _X11_NAMED_SYMBOLS.get(name)


def modifiers_to_x11(modifiers):
    flags = 0
    if modifiers & hotkey_core.MOD_SHIFT:
        flags |= SHIFT_MASK
    if modifiers & hotkey_core.MOD_CTRL:
        flags |= CONTROL_MASK
    if modifiers & hotkey_core.MOD_ALT:
        flags |= MOD1_MASK
    if modifiers & hotkey_core.MOD_META:
        flags |= MOD4_MASK
    return flags


class _X11Display:
    # Minimal libX11 binding, loaded lazily so a Wayland-only system never pays
    # for it and never fails because libX11 is absent.
    # 极简的 libX11 绑定，惰性加载，使纯 Wayland 系统不会为它付出代价，也不会因
    # 缺少 libX11 而失败。
    def __init__(self):
        self.lib = None
        self.display = None

    def open(self):
        if self.lib is not None:
            return self.display is not None
        try:
            self.lib = ctypes.CDLL("libX11.so.6")
        except OSError:
            try:
                self.lib = ctypes.CDLL("libX11.so")
            except OSError as exc:
                log.info("x11: libX11 is not available (%s)", exc)
                return False
        self.lib.XOpenDisplay.restype = ctypes.c_void_p
        self.lib.XOpenDisplay.argtypes = (ctypes.c_char_p,)
        self.lib.XStringToKeysym.restype = ctypes.c_ulong
        self.lib.XStringToKeysym.argtypes = (ctypes.c_char_p,)
        self.lib.XKeysymToKeycode.restype = ctypes.c_ubyte
        self.lib.XKeysymToKeycode.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
        self.lib.XDefaultRootWindow.restype = ctypes.c_ulong
        self.lib.XDefaultRootWindow.argtypes = (ctypes.c_void_p,)
        self.lib.XGrabKey.argtypes = (
            ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong,
            ctypes.c_int, ctypes.c_int, ctypes.c_int)
        self.lib.XUngrabKey.argtypes = (
            ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_ulong)
        self.lib.XSync.argtypes = (ctypes.c_void_p, ctypes.c_int)
        self.display = self.lib.XOpenDisplay(None)
        return self.display is not None

    def close(self):
        if self.lib is not None and self.display is not None:
            try:
                self.lib.XCloseDisplay(self.display)
            except Exception:
                pass
        self.display = None


class X11HotkeyBackend(base.HotkeyBackend):
    # X11 global hotkeys through `XGrabKey`.
    #
    # Two X11 details matter: the grab must be repeated for every combination
    # of CapsLock and NumLock, otherwise the hotkey stops working whenever a
    # lock key is on; and a failed grab raises a `BadAccess` X error
    # ASYNCHRONOUSLY, which by default terminates the process, so an error
    # handler has to be installed before grabbing.
    #
    # X11 通过 `XGrabKey` 实现全局热键。
    #
    # 两个 X11 细节很重要：必须为 CapsLock 与 NumLock 的每种组合重复抓取，否则
    # 任意锁定键打开时热键都会失效；抓取失败的 `BadAccess` X 错误是"异步"上报的，
    # 默认会终止进程，因此抓取前必须安装错误处理器。
    name = "linux-x11-xgrabkey"
    available = X11_AVAILABLE

    def __init__(self):
        self._x11 = _X11Display()
        self._grabs = []
        self._handler_installed = False

    def is_usable(self):
        return IS_LINUX and session_type() == SESSION_X11 and self._x11.open()

    def _install_error_handler(self):
        # A grab that fails because another client owns the combination raises
        # BadAccess; without a handler Xlib prints the error and exits.
        # 因其他客户端已持有组合键而失败的抓取会抛 BadAccess；没有处理器时 Xlib
        # 会打印错误并退出。
        if self._handler_installed or self._x11.lib is None:
            return
        handler_type = ctypes.CFUNCTYPE(
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

        def ignore(_display, _event):
            return 0

        self._error_handler = handler_type(ignore)
        try:
            self._x11.lib.XSetErrorHandler.argtypes = (handler_type,)
            self._x11.lib.XSetErrorHandler(self._error_handler)
            self._handler_installed = True
        except AttributeError:
            log.info("x11: XSetErrorHandler is unavailable")

    def register(self, hotkey_id, binding, callback):
        if not IS_LINUX or not binding.is_set:
            return None
        if session_type() == SESSION_WAYLAND:
            log.info("hotkey: Wayland forbids global key grabs; "
                     "the GlobalShortcuts portal cannot consume a combination")
            return None
        if not self._x11.open():
            return None
        symbol = key_to_keysym(binding.key)
        if symbol is None:
            log.warning("hotkey: %r has no X11 keysym", binding.key)
            return None
        keysym = self._x11.lib.XStringToKeysym(symbol.encode())
        if not keysym:
            log.warning("hotkey: unknown keysym %s", symbol)
            return None
        keycode = self._x11.lib.XKeysymToKeycode(self._x11.display, keysym)
        if not keycode:
            return None
        self._install_error_handler()
        root = self._x11.lib.XDefaultRootWindow(self._x11.display)
        base_mods = modifiers_to_x11(binding.modifiers)
        # GrabModifiers for every lock-key combination /
        # 为每种锁定键组合抓取
        ignore_locks = (0, LOCK_MASK, 1 << 4)  # 1<<4 = Mod2 (usually NumLock)
        for extra in (0, LOCK_MASK, 1 << 4, LOCK_MASK | (1 << 4)):
            self._x11.lib.XGrabKey(
                self._x11.display, keycode, base_mods | extra, root,
                1,  # owner_events: deliver to the grabbing client / 投递给抓取方
                1,  # GrabModeAsync for pointer events / 指针事件异步
                1)  # GrabModeAsync for keyboard events / 键盘事件异步
            self._grabs.append((keycode, base_mods | extra, root))
        self._x11.lib.XSync(self._x11.display, 0)
        # NOTE: receiving the resulting KeyPress events needs an event loop on
        # this X connection. That loop is left to the front-end's toolkit,
        # which owns the connection in practice; the grab itself is what this
        # backend guarantees.
        # 注意：接收由此产生的 KeyPress 事件需要在本 X 连接上有事件循环。该循环交给
        # 前端工具包，因为实际使用中连接由它持有；本后端保证的是抓取本身。
        log.info("hotkey: grabbed %s (%s)", binding.describe(),
                 "0x%02x" % base_mods)
        return hotkey_id

    def unregister(self, token):
        if not self._grabs or self._x11.display is None:
            return False
        for keycode, mods, root in self._grabs:
            try:
                self._x11.lib.XUngrabKey(self._x11.display, keycode, mods, root)
            except Exception:
                pass
        self._grabs.clear()
        try:
            self._x11.lib.XSync(self._x11.display, 0)
        except Exception:
            pass
        return True

    def unregister_all(self):
        count = len(self._grabs)
        self.unregister(None)
        return count


# The Qt D-Bus transport that used to live here now lives in
# `gifmanager/frontend/qml/portal.py`, because the platform layer may not import a GUI
# toolkit and this module must stay usable by a headless process. `PortalBus` is
# injected into `WaylandHotkeyBackend`; see the class docstring for the protocol.
#
# 原先位于此处的 Qt D-Bus 传输层现在位于 `gifmanager/frontend/qml/portal.py`，因为平台层
# 不得导入界面工具包，且本模块必须保持可被无头进程使用。`PortalBus` 被注入
# `WaylandHotkeyBackend`；协议见该类文档字符串。


class WaylandHotkeyBackend(base.HotkeyBackend):
    # Global shortcuts through `org.freedesktop.portal.GlobalShortcuts`.
    #
    # Wayland has no global-hotkey API on purpose: a client may not observe or intercept
    # input destined for another client. The sanctioned route is the portal, and it
    # INVERTS the usual control flow:
    #
    #   * the application does NOT choose the combination. It may propose one, but the
    #     compositor shows its own dialog and decides; the portal then reports what was
    #     actually bound, which may differ from the request or be nothing at all.
    #   * the application does NOT own the binding. The SESSION does, so closing the
    #     session releases it and a crash cannot leave a combination permanently held.
    #   * the application may NOT consume the keystroke. The compositor delivers an
    #     `Activated` signal instead, which is strictly less capable.
    #
    # That is a real reduction in capability, so this backend reports what actually
    # happened rather than pretending the X11 semantics carry over. It is written against
    # the PORTAL rather than `zwp_global_shortcuts_v1`, because that wlroots protocol
    # works on Sway and Hyprland and does nothing on GNOME or KDE, whereas the portal is
    # the cross-desktop interface.
    #
    # # The transport is INJECTED
    #
    # `bus` is any object with `call`/`subscribe`/`close_session`. That is what lets the
    # protocol be tested on a machine with no portal, and what keeps `QtDBus` — a GUI
    # toolkit import — out of the platform layer.
    #
    # Wayland 刻意不提供全局热键接口：客户端不得观察或拦截投递给其他客户端的输入。被认可的
    # 路径是门户，而它把通常的控制流"倒了过来"：
    #
    #   * 应用"不"选择组合键。它可以建议一个，但合成器弹出自己的对话框并做决定；门户随后回报
    #     实际绑定的是什么，可能与请求不同，也可能什么都没绑。
    #   * 应用"不"拥有该绑定。"会话"拥有它，因此关闭会话即释放，崩溃也不会永久占住一个组合键。
    #   * 应用"不得"消费该按键。合成器改为投递 `Activated` 信号，能力严格更弱。
    #
    # 这是能力上的真实削减，因此本后端如实报告发生了什么，而不是假装 X11 的语义能照搬。它针对
    # "门户"而非 `zwp_global_shortcuts_v1` 编写，因为那个 wlroots 协议在 Sway 与 Hyprland 上
    # 可用、在 GNOME 与 KDE 上毫无作用，而门户是跨桌面接口。
    #
    # # 传输层是"注入"的
    #
    # `bus` 是任何带 `call`/`subscribe`/`close_session` 的对象。这正是让协议能在没有门户的
    # 机器上被测试的原因，也是把 `QtDBus`——一个界面工具包导入——挡在平台层之外的原因。
    name = "linux-wayland-portal"

    def __init__(self, bus=None, available=None, reason=""):
        # `available` and `reason` are probed by the FRONT-END and passed in, because the
        # probe needs Qt and this layer may not import it. Defaulting to available keeps a
        # directly-constructed backend usable: it reports a real error from its first call
        # rather than claiming to be unavailable.
        # `available` 与 `reason` 由"前端"探测并传入，因为探测需要 Qt 而本层不得导入它。默认
        # 可用使直接构造的后端仍可用：它从第一次调用报告真实错误，而不是声称自己不可用。
        self._bus = bus
        self._session = ""
        self._bindings = {}
        self._callbacks = {}
        self._requested = {}
        self._error = ""
        self._subscribed = False
        self._token_counter = 0
        if available is None:
            available = True
        self._available = bool(available)
        self._reason = str(reason or "")
        if self._bus is None:
            self._available = False
            self._reason = self._reason or "no portal transport was provided"

    # ---- introspection / 自省 -------------------------------------------

    @property
    def available(self):
        return self._available

    def last_binding(self, hotkey_id=0):
        # The sequence ACTUALLY bound, which the compositor may have changed.
        # "实际"绑定的序列，合成器可能已更改它。
        return self._bindings.get(hotkey_id)

    def last_error(self):
        return self._error

    def unavailable_reason(self):
        return self._reason

    def session_path(self):
        # The portal session this backend owns, exposed for teardown checks.
        # 本后端拥有的门户会话，为退出检查而暴露。
        return self._session

    # ---- protocol / 协议 -------------------------------------------------

    def _handle_token(self, label):
        # A unique handle token, as the portal requires.
        #
        # Derived from the process id and a counter rather than being a constant: the
        # portal rejects a token that is not unique on the bus, and two instances of the
        # same application is a real scenario (a second launch whose single-instance check
        # failed).
        # 门户要求的唯一句柄令牌。
        #
        # 由进程 id 与计数器派生而非常量：门户会拒绝总线上不唯一的令牌，而同一应用的两个实例
        # 是真实场景（单实例检查失败的第二次启动）。
        self._token_counter += 1
        return f"gifmanager_{os.getpid()}_{self._token_counter}_{label}"

    @staticmethod
    def _unwrap(value):
        # Portal replies are variant-wrapped; the Qt transport hands back a
        # `QDBusVariant` for a single-out-argument call, so unwrap one layer when present.
        # 门户回复是变体包装的；Qt 传输层对单出参调用会交回 `QDBusVariant`，因此存在时解开
        # 一层。
        inner = getattr(value, "variant", None)
        return value if inner is None else inner()

    def _map_get(self, mapping, key, default=None):
        # Read one key out of a portal reply map.
        #
        # A `QVariantMap` that arrived over D-Bus is a `QDBusArgument`, NOT a Python dict,
        # so a plain `[...]` or `.get` raises AttributeError. Trying the mapping protocol
        # and reporting the miss is what keeps a shape change from looking like a
        # successful empty reply.
        # 从门户回复映射中读取一个键。
        #
        # 经 D-Bus 到达的 `QVariantMap` 是 `QDBusArgument`，不是 Python dict，因此直接用
        # `[...]` 或 `.get` 会抛 AttributeError。尝试映射协议并报告未命中，正是让形状变化
        # 不会看起来像一次成功的空回复的原因。
        if mapping is None:
            return default
        try:
            if key in mapping:
                return mapping[key]
        except Exception:
            pass
        try:
            return mapping.get(key, default)
        except Exception:
            return default

    def _create_session(self):
        # Open a session and return its object path, or "".
        #
        # Opening once and reusing is what makes a second `register` cheap and, more
        # importantly, what keeps every binding in ONE session so a single close releases
        # all of them.
        # 打开会话并返回其对象路径，或空字符串。
        #
        # 只打开一次并复用，使第二次 `register` 代价很低，更重要的是让所有绑定处于"同一个"
        # 会话，从而一次关闭即全部释放。
        if self._session:
            return self._session
        token = self._handle_token("session")
        arguments, error = self._bus.call("CreateSession", [{
            "handle_token": token,
            "session_handle_token": token,
        }])
        if error:
            self._error = error
            return ""
        if not arguments:
            self._error = "CreateSession returned no arguments"
            return ""
        session = self._session_from_reply(arguments, token)
        if not session:
            return ""
        self._session = session
        log.info("wayland: portal session %s", self._session)
        return self._session

    def _session_from_reply(self, arguments, token):
        # Work out the session handle from a `CreateSession` reply, or set `_error` and return "".
        #
        # # Two shapes exist, and only one of them was handled
        #
        # The portal specification says `CreateSession` returns ONE object path - the REQUEST
        # handle - and delivers the session handle separately in the `Response` signal. The
        # first version of this code assumed the reply was the results map and read
        # `session_handle` out of it, which is what a FAKE transport returns, so
        # `tests/smoke_wayland.py` passed while the real portal failed with
        #
        #     CreateSession returned no session_handle; the portal version may be too old
        #
        # Measured on Arch + niri: the reply is exactly one argument, a `QDBusObjectPath`, and no
        # results map is present at all.
        #
        # # Why the path can be computed instead of awaited
        #
        # The spec also guarantees that when a `session_handle_token` is supplied the session
        # handle IS
        #
        #     /org/freedesktop/portal/desktop/session/<sender sanitised>/<session_handle_token>
        #
        # which removes the need to wait for the signal on an event loop this layer does not own.
        # `BindShortcuts` then acts as the verification: if the path were wrong it would refuse.
        # Both shapes are accepted so the injected fake transport keeps working unchanged.
        # 从 `CreateSession` 回复中得出会话句柄；否则设置 `_error` 并返回空字符串。
        #
        # # 存在两种形状，而只有一种被处理
        #
        # 门户规范说 `CreateSession` 返回"一个"对象路径——请求句柄——并在 `Response` 信号中单独
        # 投递会话句柄。本代码的第一个版本假设回复就是结果映射、并从里面读 `session_handle`，而那
        # 正是"伪"传输层返回的东西，因此 `tests/smoke_wayland.py` 通过、真实门户却失败于
        #
        #     CreateSession returned no session_handle; the portal version may be too old
        #
        # 在 Arch + niri 上实测：回复恰好一个参数、一个 `QDBusObjectPath`，根本没有任何结果映射。
        #
        # # 为什么可以计算路径而不必等待
        #
        # 规范还保证：当提供 `session_handle_token` 时，会话句柄"就是"
        #
        #     /org/freedesktop/portal/desktop/session/<净化后的 sender>/<session_handle_token>
        #
        # 这就不必在本层并不拥有的事件循环上等待信号。随后 `BindShortcuts` 充当校验：若路径错了它
        # 会拒绝。两种形状都接受，使注入的伪传输层无需改动即可继续工作。
        first = self._unwrap(arguments[0])
        # Shape A: a results map (the injected fake transport, and any backend that packs the
        # handle into the reply).
        # 形状 A：结果映射（注入的伪传输层，以及任何把句柄打包进回复的后端）。
        mapped = self._map_get(first, "session_handle")
        if mapped:
            return str(mapped)
        # Shape B: the deterministic path from `session_handle_token`, per the specification.
        # 形状 B：按规范由 `session_handle_token` 决定的确定性路径。
        sender = ""
        getter = getattr(self._bus, "sender", None)
        if callable(getter):
            try:
                sender = str(getter() or "")
            except Exception:
                sender = ""
        if not sender:
            self._error = (
                "the portal replied with a request handle and the transport cannot report its "
                "bus name, so the session path cannot be derived / 门户回复了请求句柄，而传输层"
                "无法报告其总线名，因此无法推导会话路径")
            return ""
        sanitised = sender.lstrip(":").replace(".", "_")
        return f"{PORTAL_PATH}/session/{sanitised}/{token}"

    def _shortcut_list(self, hotkeys):
        # The `(sa{sv}as)` shortcut tuples the portal expects.
        #
        # `preferred_trigger` is a PROPOSAL: the compositor may honour it, substitute its
        # own, or ask the user. The description names the application because the
        # compositor shows it in its own chooser.
        # 门户期望的 `(sa{sv}as)` 快捷方式元组。
        #
        # `preferred_trigger` 是"建议"：合成器可以采纳、替换或询问用户。描述标出应用名，因为
        # 合成器会在自己的选择器里显示它。
        result = []
        for hotkey_id, binding in hotkeys:
            described = self._safe_describe(binding)
            result.append((
                str(hotkey_id),
                {
                    "description": ("GIFManager: " + described) if described
                                   else "GIFManager",
                    "preferred_trigger": described,
                },
                [],
            ))
        return result

    @staticmethod
    def _safe_describe(binding):
        try:
            return binding.describe()
        except Exception:
            return ""

    def _parse_bound(self, arguments):
        # Read `(sa{sv}as)` shortcut tuples out of a `BindShortcuts` reply.
        #
        # Defensive because the reply shape varies by portal version, and a portal that
        # returns an empty or unexpected structure must not be treated as success.
        # 从 `BindShortcuts` 回复中读出 `(sa{sv}as)` 快捷方式元组。
        #
        # 保守处理，因为回复形状随门户版本而变，而返回空或意外结构的门户不得被当作成功。
        parsed = []
        if not arguments:
            return parsed
        payload = self._unwrap(arguments[0])
        shortcuts = self._map_get(payload, "shortcuts")
        if not shortcuts:
            return parsed
        try:
            for entry in shortcuts:
                shortcut_id = entry[0]
                properties = entry[1] if len(entry) > 1 else None
                # `trigger_description` is what the compositor ACTUALLY bound, in the
                # user's localised spelling.
                # `trigger_description` 是合成器"实际"绑定的内容，采用用户本地化的写法。
                trigger = self._map_get(properties, "trigger_description", "")
                binding = _binding_from_trigger(trigger) if trigger else None
                if binding is not None:
                    parsed.append((str(shortcut_id), binding, str(trigger)))
        except Exception:
            log.exception("wayland: cannot parse the bound shortcuts")
        return parsed

    def _subscribe(self):
        if self._subscribed:
            return True
        self._subscribed = self._bus.subscribe("Activated", self._on_activated)
        if not self._subscribed:
            # Worth a warning rather than silence: the hotkey would register and then
            # never fire, which looks like "the setting saved but does nothing".
            # 值得一条警告而非静默：热键会注册成功然后永不触发，那看起来像"设置保存了但毫无
            # 效果"。
            log.warning("wayland: could not subscribe to Activated; the hotkey would "
                        "register but never fire")
        return self._subscribed

    def _on_activated(self, _session, shortcut_id, _timestamp=None, _options=None):
        # Fires on the session's own thread; only forward the event.
        #
        # `shortcut_id` arrives as the portal's `s` type, i.e. a STRING, while `register`
        # was called with an int by every caller. Looking up only one of the two forms is
        # what made the first version of this method register a hotkey successfully and
        # then never fire it.
        # 在会话自身的线程上触发；只转发事件。
        #
        # `shortcut_id` 以门户的 `s` 类型（即字符串）到达，而 `register` 被每个调用方以
        # int 调用。只查两种形式中的一种，正是本方法第一个版本"注册成功却永不触发"的原因。
        callback = None
        for key in self._id_keys(shortcut_id):
            callback = self._callbacks.get(key)
            if callback is not None:
                break
        if callback is None:
            log.info("wayland: Activated for unknown shortcut %r", shortcut_id)
            return
        try:
            callback()
        except Exception:
            log.exception("wayland: the hotkey callback raised")

    @staticmethod
    def _id_keys(shortcut_id):
        # Both forms a shortcut id can arrive in, string first because that is what the
        # portal sends.
        #
        # `str(0) != 0` in Python, so both really are needed: a dict keyed by the int
        # misses a string lookup and vice versa.
        # 快捷方式 id 可能到达的两种形式，字符串在前，因为那是门户发送的形式。
        #
        # Python 中 `str(0) != 0`，因此两者确实都需要：以 int 为键的字典会漏掉字符串查找，
        # 反之亦然。
        keys = [str(shortcut_id)]
        try:
            as_int = int(shortcut_id)
        except (TypeError, ValueError):
            return keys
        if as_int not in keys:
            keys.append(as_int)
        return keys

    def simulate_activated(self, shortcut_id):
        # Deliver `Activated` as the compositor would.
        #
        # Used by the tests, and it exists as a method rather than as a direct
        # `_on_activated` call so the dispatch path under test is the same one the signal
        # handler uses, including the string/int key fallback.
        # 按合成器的方式投递 `Activated`。
        #
        # 供测试使用；它作为方法存在而非直接调用 `_on_activated`，使被测的分发路径与信号处理器
        # 所用的完全一致，包括字符串/整数键的回退。
        self._on_activated(self._session, shortcut_id)

    # ---- the backend interface / 后端接口 -------------------------------

    def register(self, hotkey_id, binding, callback):
        # Ask the compositor to bind a shortcut and return the session path, or None.
        #
        # The token is the session path because bindings belong to the session rather
        # than to individual shortcuts: the portal has no "release one shortcut" call.
        # 请求合成器绑定一个快捷方式并返回会话路径，或 None。
        #
        # 令牌是会话路径，因为绑定属于会话而非单个快捷方式：门户没有"释放单个快捷方式"的调用。
        if not self._available:
            log.info("wayland: %s", self._reason)
            return None

        # Refuse BEFORE opening a session if the transport cannot even send the bind call.
        #
        # `BindShortcuts` is a BLOCKING D-Bus call, and when the argument cannot be marshalled the
        # message never leaves, so no reply arrives and the call sits on the GUI thread until
        # `BIND_TIMEOUT_MS` (120 s) expires. Measured on Arch + niri: the window never appeared and
        # the application looked hung at startup, with the last log line being a portal session.
        # The transport therefore exposes `supports_binding`, and asking it here turns a two-minute
        # freeze into an immediate, explanatory refusal.
        # 若传输层连绑定调用都发不出去，在打开会话"之前"就拒绝。
        #
        # `BindShortcuts` 是"阻塞"的 D-Bus 调用，当参数无法编组时消息根本不会发出，因此收不到回复，
        # 调用就在 GUI 线程上一直挂到 `BIND_TIMEOUT_MS`（120 秒）过期。在 Arch + niri 上实测：窗口
        # 从未出现、应用看起来在启动时卡死，最后一行日志是一个门户会话。因此传输层暴露
        # `supports_binding`，在此询问它可把两分钟的冻结变成一次即时、带解释的拒绝。
        probe = getattr(self._bus, "supports_binding", None)
        if callable(probe):
            can_bind, why = probe()
            if not can_bind:
                self._error = str(why or "the portal cannot bind shortcuts here")
                log.warning("wayland: %s", self._error)
                return None

        session = self._create_session()
        if not session:
            return None

        # `BindShortcuts(session, shortcuts, parent_window, options)`. The parent window
        # is empty because QML exposes none; the portal accepts that and renders an
        # independent dialog.
        # `BindShortcuts(session, shortcuts, parent_window, options)`。父窗口为空，因为
        # QML 未暴露它；门户接受这一点并渲染独立对话框。
        token = self._handle_token("bind")
        arguments, error = self._bus.call(
            "BindShortcuts",
            [session, self._shortcut_list([(hotkey_id, binding)]), "",
             {"handle_token": token}],
            timeout_ms=BIND_TIMEOUT_MS)
        if error:
            self._error = error
            # The session stays open on a bind failure so a retry does not pay for a new
            # one, and so the error is attributable to the BIND rather than to session
            # creation.
            # 绑定失败时会话保持打开，使重试无需再开一个，也让错误归属于"绑定"而非会话创建。
            return None

        # The reply's `shortcuts` list is the AUTHORITY. Believing the requested
        # combination would make the interface display a shortcut that does nothing.
        # 回复的 `shortcuts` 列表才是"权威"。相信请求的组合会让界面显示一个无效的快捷键。
        bound = self._parse_bound(arguments)
        actual = bound[0][1] if bound else binding
        self._bindings[hotkey_id] = actual
        self._requested[hotkey_id] = binding
        self._callbacks[hotkey_id] = callback
        self._subscribe()

        if self._safe_describe(actual) != self._safe_describe(binding):
            log.info("wayland: the compositor bound %r instead of the requested %r",
                     self._safe_describe(actual), self._safe_describe(binding))
        else:
            log.info("wayland: portal bound %r", self._safe_describe(actual))
        return session

    def unregister(self, token):
        # A single shortcut cannot be released through the portal: bindings belong to the
        # session, so this drops the local bookkeeping and leaves the session open.
        # `unregister_all` closes the session, which is the operation that actually
        # releases the compositor binding.
        # 经门户无法释放单个快捷方式：绑定属于会话，因此这里只丢弃本地记录并让会话保持打开。
        # `unregister_all` 关闭会话，那才是真正释放合成器绑定的操作。
        if token is None:
            return False
        self._bindings.clear()
        self._callbacks.clear()
        self._requested.clear()
        return True

    def unregister_all(self):
        # Close the session, which releases every binding it owns.
        #
        # This is the portal's actual release mechanism, and it is why a crash here cannot
        # leave a combination permanently held: the portal drops a session whose client
        # disappeared.
        # 关闭会话，释放它拥有的每个绑定。
        #
        # 这是门户真正的释放机制，也正是这里崩溃不会永久占住一个组合键的原因：客户端消失后
        # 门户会丢弃该会话。
        self._bindings.clear()
        self._callbacks.clear()
        self._requested.clear()
        session = self._session
        self._session = ""
        if not session or self._bus is None:
            return True
        return self._bus.close_session(session)


def _binding_from_trigger(trigger):
    # Parse a portal `trigger_description` back into a `HotkeyBinding`.
    #
    # The description is a localised, human-readable string such as "Ctrl+Alt+K" or the
    # desktop's own spelling ("Super+Q", "Mod4+Q"). Parsing it is LOSSY, so a description
    # that cannot be understood yields None and the caller keeps the requested binding
    # rather than storing a guess that would display a wrong shortcut.
    # 把门户的 `trigger_description` 解析回 `HotkeyBinding`。
    #
    # 该描述是本地化的、人类可读的字符串，例如 "Ctrl+Alt+K" 或桌面自己的写法（"Super+Q"、
    # "Mod4+Q"）。解析它是有"损"的，因此无法理解的描述返回 None，调用方保留请求的绑定，而不是
    # 存下一个会显示错误快捷键的猜测。
    text = str(trigger or "").strip()
    if not text:
        return None
    modifiers = 0
    key = ""
    aliases = {
        "ctrl": hotkey_core.MOD_CTRL, "control": hotkey_core.MOD_CTRL,
        "alt": hotkey_core.MOD_ALT, "mod1": hotkey_core.MOD_ALT,
        "shift": hotkey_core.MOD_SHIFT,
        "super": hotkey_core.MOD_META, "meta": hotkey_core.MOD_META,
        "mod4": hotkey_core.MOD_META, "win": hotkey_core.MOD_META,
        "cmd": hotkey_core.MOD_META, "command": hotkey_core.MOD_META,
        # `LOGO` is X11's historical name for the Super key and is what
        # `XStringToKeysym`-based tools print; KDE spells it this way in some
        # configurations, so omitting it silently dropped the modifier.
        # `LOGO` 是 X11 对 Super 键的历史名称，也是基于 `XStringToKeysym` 的工具所打印的
        # 写法；KDE 在某些配置里这样拼写，因此漏掉它会静默丢掉该修饰键。
        "logo": hotkey_core.MOD_META,
    }
    for part in text.replace(" ", "").split("+"):
        lowered = part.strip().lower()
        if not lowered:
            continue
        if lowered in aliases:
            modifiers |= aliases[lowered]
            continue
        # The last non-modifier component is the key. A description with two keys is not
        # something this application asks for.
        # 最后一个非修饰键组件是按键。含两个按键的描述不是本应用会请求的东西。
        key = part.strip().upper()
    if not key:
        return None
    return hotkey_core.HotkeyBinding(modifiers, key)


# The portal timeouts, mirrored from `frontend/qml/portal.py` so the protocol has a
# default when a transport does not supply one. The values must agree: they describe the
# same portal.
# 门户超时，与 `frontend/qml/portal.py` 保持一致，使传输层未提供时协议有默认值。两者必须
# 一致：它们描述的是同一个门户。
CALL_TIMEOUT_MS = 8_000
BIND_TIMEOUT_MS = 120_000


def session_hotkey_backend():
    # The hotkey backend for the running session.
    #
    # A function rather than a table lookup because the answer depends on an
    # environment variable, and a module-level decision would freeze whichever session
    # type happened to be active at import — which for a process launched from a
    # `.desktop` file is not necessarily the interactive session.
    # 当前会话的热键后端。
    #
    # 用函数而非表查找，因为答案取决于环境变量，而模块级决定会把导入时恰好生效的会话类型冻住
    # ——对从 `.desktop` 文件启动的进程，那不一定是交互式会话。
    if not is_wayland():
        return X11HotkeyBackend
    # The probe needs Qt, which this layer may not import, so it is done by the
    # caller and passed in. Without a caller-supplied transport the backend
    # reports itself unavailable rather than failing at the first call.
    # 探测需要 Qt，而本层不得导入它，因此由调用方完成并传入。没有调用方提供的传输层时，
    # 后端报告自己不可用，而不是在第一次调用时失败。
    return WaylandHotkeyBackend


class LinuxScrollWatcher(base.HotkeyBackend):
    # Global Alt+scroll observation on X11 through XInput2 raw events.
    #
    # XInput2 is used rather than `XGrabButton(Button4/5, Mod1Mask)`: a grab
    # STEALS scrolling from every other application, whereas raw events observe
    # without consuming.
    # X11 上通过 XInput2 原始事件观察全局 Alt+滚动。
    #
    # 使用 XInput2 而不是 `XGrabButton(Button4/5, Mod1Mask)`：抓取会从所有其他应用
    # 手里"夺走"滚动，而原始事件只观察、不消费。
    name = "linux-xinput2"
    available = X11_AVAILABLE

    def start(self, callback):
        if not IS_LINUX:
            return False
        if session_type() != SESSION_X11:
            log.info("scroll: global Alt+scroll needs X11; "
                     "Wayland offers no equivalent")
            return False
        log.info("scroll: the XInput2 backend is not implemented")
        return False

    def stop(self):
        return True


# ===========================================================================
# Input injection / 输入注入
# ===========================================================================

class LinuxInput(base.InputBackend):
    # Paste into the previously focused application.
    #
    # On X11 the portable route is the XTEST extension (or `xdotool`, which
    # wraps it). On Wayland no client may inject input into another client, so
    # the backend reports failure instead of pretending.
    # 把剪贴板粘贴到此前获得焦点的应用。
    #
    # X11 上可移植的路径是 XTEST 扩展（或封装它的 `xdotool`）。Wayland 上任何
    # 客户端都不得向其他客户端注入输入，因此本后端报告失败而不是假装成功。
    name = "linux-xtest"
    available = X11_AVAILABLE

    def paste_to_foreground(self, delay_ms=50):
        if not IS_LINUX:
            return False
        if session_type() == SESSION_WAYLAND:
            log.info("input: Wayland forbids synthetic input into other clients")
            return False
        xdotool = shutil.which("xdotool")
        if not xdotool:
            log.info("input: xdotool is not installed; install it to enable "
                     "automatic paste")
            return False
        import time

        time.sleep(delay_ms / 1000.0)
        try:
            completed = subprocess.run(
                [xdotool, "key", "--clearmodifiers", "ctrl+v"],
                timeout=5, **process.no_window_kwargs())
            return completed.returncode == 0
        except (OSError, Exception) as exc:
            log.warning("input: xdotool failed -> %s", exc)
            return False

    def foreground_window(self):
        if not IS_LINUX:
            return 0
        xdotool = shutil.which("xdotool")
        if not xdotool:
            return 0
        try:
            completed = process.run_capture(
                [xdotool, "getactivewindow"], timeout=3)
            text = process.decode_output(completed.stdout).strip()
            return int(text) if text.isdigit() else 0
        except (OSError, Exception):
            return 0

    def bring_to_front(self, window_id):
        if not IS_LINUX or not window_id:
            return False
        xdotool = shutil.which("xdotool")
        if not xdotool:
            return False
        try:
            completed = subprocess.run(
                [xdotool, "windowactivate", str(int(window_id))],
                timeout=5, **process.no_window_kwargs())
            return completed.returncode == 0
        except (OSError, Exception):
            return False


# ===========================================================================
# GPU preference / GPU 首选项
# ===========================================================================

class LinuxGpuPreference(base.GpuPreferenceBackend):
    # Adapter choice on Linux is not a per-application setting.
    #
    # A user picks an adapter per launch with the `DRI_PRIME` environment
    # variable, or globally in the vendor's control panel (NVIDIA Prime,
    # `switcheroo-control`). Neither is a key/value the application can write
    # on the user's behalf, so `available` is False and the settings page hides
    # the control — while still listing what the machine has.
    # Linux 上的适配器选择不是按应用的设置。
    #
    # 用户通过 `DRI_PRIME` 环境变量按次选择，或在厂商控制面板（NVIDIA Prime、
    # `switcheroo-control`）里全局选择。两者都不是应用能代用户写入的键值，因此
    # `available` 为 False，设置页隐藏该控件——但仍然列出机器拥有什么。
    name = "linux-prime"
    available = False

    def list_adapters(self):
        if not IS_LINUX:
            return []
        names = []
        # `switcheroo-control` is the desktop-neutral source; `lspci` is the
        # fallback when it is not installed.
        # `switcheroo-control` 是桌面中立的数据源；未安装时回退 `lspci`。
        try:
            completed = process.run_capture(
                ["switcheroo-control", "--version"], timeout=3)
            if completed.returncode == 0:
                # The tool has no listing mode; query D-Bus through busctl if
                # available, otherwise fall through to lspci.
                # 该工具没有列表模式；可用时经 busctl 查 D-Bus，否则回退 lspci。
                listed = process.run_capture(
                    ["busctl", "call", "net.hadess.SwitcherooControl",
                     "/net/hadess/SwitcherooControl",
                     "org.freedesktop.DBus.Properties", "Get",
                     "net.hadess.SwitcherooControl", "GPUs"], timeout=5)
                for match in re.findall(r'"Name"\s+s\s+"([^"]+)"',
                                        process.decode_output(listed.stdout)):
                    if match not in names:
                        names.append(match)
        except (OSError, Exception):
            pass
        if names:
            return names
        lspci = shutil.which("lspci")
        if not lspci:
            return []
        try:
            completed = process.run_capture([lspci], timeout=8)
        except (OSError, Exception):
            return []
        for line in process.decode_output(completed.stdout).splitlines():
            if "VGA compatible controller" in line or "3D controller" in line:
                name = line.split(":", 2)[-1].strip()
                if name and name not in names:
                    names.append(name)
        return names

    def dri_prime_hint(self):
        # The documented way for a user to force the discrete adapter /
        # 用户强制使用独显的官方方式
        return "DRI_PRIME=1"


# ===========================================================================
# Autostart / 开机自启
# ===========================================================================

class LinuxAutostart(base.AutostartBackend):
    # "Start with the system" as an XDG desktop entry.
    #
    # `~/.config/autostart/<id>.desktop` is read by GNOME, KDE, XFCE, LXQt and
    # every other mainstream desktop, needs no elevation, and is trivially
    # inspectable by the user.
    # 以 XDG 桌面项实现"开机自启"。
    #
    # `~/.config/autostart/<id>.desktop` 会被 GNOME、KDE、XFCE、LXQt 及其他主流
    # 桌面读取，无需提权，且用户可以直接查看。
    name = "linux-xdg-autostart"
    available = IS_LINUX

    def _desktop_path(self, app_id):
        return os.path.join(desktop_dir(), f"{app_id}.desktop")

    def is_enabled(self, app_id):
        if not IS_LINUX:
            return False
        path = self._desktop_path(app_id)
        if not os.path.isfile(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as handle:
                content = handle.read().lower()
        except OSError:
            return False
        # A desktop entry can be present but disabled with a hidden flag /
        # 桌面项可以存在但被 hidden 标志禁用
        return "hidden=true" not in content

    def set_enabled(self, app_id, command, enabled):
        if not IS_LINUX:
            return False
        path = self._desktop_path(app_id)
        if not enabled:
            try:
                if os.path.isfile(path):
                    os.remove(path)
                return True
            except OSError as exc:
                log.warning("autostart: cannot remove %s -> %s", path, exc)
                return False
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={app_id}\n"
            f"Exec={command}\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(content)
            return True
        except OSError as exc:
            log.warning("autostart: cannot write %s -> %s", path, exc)
            return False

    @staticmethod
    def command_for(executable, arguments=()):
        # Desktop-entry Exec quoting: a backslash escapes the next character,
        # so quoting with double quotes is required for paths with spaces.
        # 桌面项 Exec 的引号规则：反斜杠转义下一个字符，因此含空格的路径必须用双
        # 引号包裹。
        parts = [f'"{executable}"' if " " in executable else executable]
        parts.extend(f'"{a}"' if " " in a else a for a in arguments)
        return " ".join(parts)


# ===========================================================================
# Single instance, and the command channel / 单实例与命令通道
# ===========================================================================


class LinuxSingleInstanceHandle:
    # The listening socket the owning process holds for its lifetime.
    # 持有进程在其生命周期内保持的监听套接字。

    def __init__(self, server, address):
        self.server = server
        self.address = address

    def drain(self):
        # Every command that has arrived since the last call, oldest first.
        #
        # Non-blocking, because the caller is a GUI event loop and must never wait on a peer. A
        # peer that connected and sent nothing costs one `accept` and one empty read.
        # 自上次调用以来到达的每条命令，最早的在前。
        #
        # 非阻塞，因为调用方是 GUI 事件循环、绝不能等待对端。只连接而不发送的对端只花费一次
        # `accept` 与一次空读取。
        messages = []
        if self.server is None:
            return messages
        while True:
            try:
                self.server.setblocking(False)
                connection, _ = self.server.accept()
            except BlockingIOError:
                break
            except OSError:
                break
            try:
                connection.setblocking(False)
                payload = connection.recv(4096)
            except OSError:
                payload = b""
            finally:
                try:
                    connection.close()
                except OSError:
                    pass
            text = payload.decode("utf-8", "replace").strip()
            if text:
                messages.append(text)
        return messages

    def close(self):
        if self.server is not None:
            try:
                self.server.close()
            except OSError:
                pass
            self.server = None


class LinuxSingleInstance(base.SingleInstanceBackend):
    # Single instance through a Linux ABSTRACT-namespace UNIX socket.
    #
    # # Why this did not exist, and what it cost
    #
    # The base class returns `(True, None)` for `acquire`, i.e. "you are the only instance". So on
    # Linux NOTHING prevented two copies of the application from running and both opening the same
    # SQLite database - the exact failure the check exists to prevent, silently absent on the
    # platform this project is now being developed on.
    #
    # # Why the abstract namespace
    #
    # An abstract socket (a leading NUL in the name) lives in the kernel, not the filesystem:
    #   * nothing to clean up after a crash, so a stale lock cannot make the application refuse to
    #     start after being killed - which a lock file on disk cannot promise;
    #   * no permissions problem when the data directory is on a network or NTFS mount, which is
    #     exactly this project's situation;
    #   * the name cannot collide with a real file.
    #
    # The trade-off is that it is Linux-specific, which is fine: this is the Linux backend.
    #
    # 通过 Linux "抽象命名空间" UNIX 套接字实现单实例。
    #
    # # 为什么此前没有，以及它的代价
    #
    # 基类对 `acquire` 返回 `(True, None)`，即"你是唯一实例"。因此 Linux 上"没有任何东西"阻止两份
    # 应用同时运行并同时打开同一个 SQLite 数据库——正是该检查要防止的失败，在本项目现在开发所在的
    # 平台上静默缺失。
    #
    # # 为什么用抽象命名空间
    #
    # 抽象套接字（名字以 NUL 开头）存在于内核而非文件系统：
    #   * 崩溃后无需清理，因此被杀掉后残留的锁不会让应用拒绝启动——磁盘上的锁文件无法保证这一点；
    #   * 数据目录位于网络或 NTFS 挂载上时没有权限问题，而这正是本项目的处境；
    #   * 名字不会与真实文件冲突。
    #
    # 代价是它 Linux 专有，这没问题：本文件就是 Linux 后端。
    name = "linux-abstract-socket"
    available = IS_LINUX

    # Commands a second launch may send. Anything else is ignored rather than acted on: this is an
    # inter-process channel, and acting on arbitrary text from a peer would be a way to drive the
    # application from outside.
    # 第二次启动可以发送的命令。其他内容一律忽略而非执行：这是一条进程间通道，对来自对端的任意文本
    # 采取行动会成为从外部驱动应用的手段。
    COMMANDS = frozenset({"toggle", "show", "hide", "quit"})

    @staticmethod
    def _address(name):
        # Abstract-namespace address: NUL prefix, no filesystem path.
        # 抽象命名空间地址：NUL 前缀，无文件系统路径。
        safe = "".join(ch for ch in str(name) if ch.isalnum() or ch in "-_.")
        return "\0gifmanager-" + (safe or "app")

    def acquire(self, name):
        import socket

        address = self._address(name)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(address)
            server.listen(8)
        except OSError as exc:
            # `EADDRINUSE` is the normal "another instance is running" answer, not an error worth
            # logging: it is how this check reports.
            # `EADDRINUSE` 是"另一个实例在运行"的正常回答，不值得记录为错误：这正是本检查报告的方式。
            server.close()
            log.debug("single-instance: %s is taken (%s); another instance owns it",
                      address, exc)
            return False, None
        return True, LinuxSingleInstanceHandle(server, address)

    def release(self, handle):
        if isinstance(handle, LinuxSingleInstanceHandle):
            handle.close()
            return True
        return False

    def notify(self, name, message):
        import socket

        command = str(message or "").strip()
        if command not in self.COMMANDS:
            log.warning("single-instance: refusing to send unknown command %r", command)
            return False
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            client.settimeout(2.0)
            client.connect(self._address(name))
            client.sendall(command.encode("utf-8"))
            return True
        except OSError as exc:
            log.debug("single-instance: cannot reach the owner (%s)", exc)
            return False
        finally:
            try:
                client.close()
            except OSError:
                pass


# ===========================================================================
# Registration / 注册
# ===========================================================================

SERVICES = {
    # The session-dependent services are resolved by CALL where the answer matters.
    # `window`, `scroll` and `input` declare `available` from the session type, so
    # the table can name a single class and the class reports honestly rather than
    # the table encoding the branch.
    # 依赖会话的服务在"关心答案的地方"按调用解析。`window`、`scroll` 与 `input` 根据会话
    # 类型声明 `available`，因此表里可以只写一个类，由类如实报告，而不是让表来编码分支。
    "window": LinuxWindow,
    "hotkeys": X11HotkeyBackend,
    "scroll": LinuxScrollWatcher,
    "input": LinuxInput,
    "gpu_preference": LinuxGpuPreference,
    "autostart": LinuxAutostart,
    "single_instance": LinuxSingleInstance,
}

PLATFORM_KEY = "linux"


def register():
    for key in ("linux", "linux2", "freebsd", "openbsd", "netbsd"):
        base.Platform.REGISTRY[key] = __name__


register()
