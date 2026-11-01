"""The Qt D-Bus transport for the XDG Desktop Portal.

# Why this is not in the platform layer

`gifmanager/platform/linux.py` holds the GlobalShortcuts PROTOCOL — which calls to make
in which order, what the replies mean, when to open and close a session — and it must
stay importable by a process with no GUI toolkit. `QtDBus` comes from PySide6, so the
transport lives here, in the layer allowed to depend on Qt, and is injected into the
backend.

That split is also what makes the protocol testable without D-Bus: the backend takes any
object with `call`/`subscribe`/`close_session`, so a fake drives the state machine on a
machine that has no portal at all.

# 为什么这不在平台层

`gifmanager/platform/linux.py` 持有 GlobalShortcuts 的"协议"——按什么顺序发哪些调用、回复
意味着什么、何时开会话与关会话——而它必须保持可被无界面工具包的进程导入。`QtDBus` 来自
PySide6，因此传输层放在这里、在被允许依赖 Qt 的层，并被注入后端。

这一划分也正是让协议能在没有 D-Bus 时被测试的原因：后端接受任何带
`call`/`subscribe`/`close_session` 的对象，因此伪实现能在完全没有门户的机器上驱动状态机。
"""
import logging

from gifmanager import APP_ID

log = logging.getLogger("GIFManager")

# Bus, object and interface names, fixed by the portal specification rather than by this
# application.
# 总线、对象与接口名，由门户规范固定，而非由本应用决定。
PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
PORTAL_INTERFACE = "org.freedesktop.portal.GlobalShortcuts"
PORTAL_SESSION_INTERFACE = "org.freedesktop.portal.Session"

# The interface a NON-sandboxed client uses to tell the portal who it is.
#
# `Registry.Register(s app_id, a{sv} options)` is the documented route for a client the portal
# cannot identify on its own, and this application is exactly that: a plain Wayland client started
# from a terminal or a `.desktop` entry, not inside a sandbox.
# 非沙箱客户端用来告诉门户"它是谁"的接口。
#
# `Registry.Register(s app_id, a{sv} options)` 是门户自身无法识别的客户端所用的既定途径，而本应用
# 正是如此：一个从终端或 `.desktop` 条目启动的普通 Wayland 客户端，不在沙箱内。
PORTAL_REGISTRY_INTERFACE = "org.freedesktop.host.portal.Registry"

# How long to wait for a reply that requires the user to answer a dialog. A chooser the
# user walks away from must not hang the application, but cutting it off too early loses
# a binding the user did want.
# 等待需要用户回答对话框的回复的时长。用户离开的选择器不应挂住应用，但过早截断会丢失用户
# 确实想要的绑定。
BIND_TIMEOUT_MS = 120_000

# A modest timeout for calls that do NOT involve the user, such as creating a session.
# These should be immediate; a slow one means the portal is broken.
# 不涉及用户的调用的适度超时，例如创建会话。它们应当立即返回；慢就说明门户有问题。
CALL_TIMEOUT_MS = 8_000


def blocking_call_mode():
    # The `QDBus.CallMode.Block` enum value, wherever this PySide6 keeps it.
    #
    # # The enum is NOT on QDBusConnection
    #
    # The first version wrote `QDBusConnection.CallMode.Block`, which reads correctly and is
    # wrong: in PySide6 6.11.1 `CallMode` lives on the `QDBus` namespace, and `QDBusConnection`
    # exposes only `UnregisterMode`:
    #
    #     AttributeError: type object 'PySide6.QtDBus.QDBusConnection'
    #                     has no attribute 'CallMode'
    #
    # The effect on Linux/Wayland was total: every portal call raised, so `CreateSession` failed,
    # so the XDG `GlobalShortcuts` hotkey could never be registered — and the failure was a
    # `log.exception` inside the call wrapper rather than anything visible in the interface.
    #
    # Nothing caught it before because `tests/smoke_wayland.py` drives the protocol through a
    # FAKE transport, exactly as it should for a unit test: the fake supplies its own call
    # implementation, so the real QtDBus spelling was never executed. It only surfaced on a real
    # Wayland session, which is the point of this check.
    #
    # Resolved once and cached; both spellings are tried so an older or newer PySide6 that moves
    # the enum again keeps working.
    # `QDBus.CallMode.Block` 枚举值，无论本 PySide6 把它放在哪里。
    #
    # # 该枚举"不在" QDBusConnection 上
    #
    # 第一版写的是 `QDBusConnection.CallMode.Block`，读起来正确、实际错误：在 PySide6 6.11.1 中
    # `CallMode` 位于 `QDBus` 命名空间，而 `QDBusConnection` 只暴露 `UnregisterMode`：
    #
    #     AttributeError: type object 'PySide6.QtDBus.QDBusConnection'
    #                     has no attribute 'CallMode'
    #
    # 它对 Linux/Wayland 的影响是彻底的：每次门户调用都抛异常，于是 `CreateSession` 失败，于是
    # XDG `GlobalShortcuts` 热键永远无法注册——而该失败表现为调用包装器内部的一次
    # `log.exception`，界面上什么也看不到。
    #
    # 此前没有任何检查发现它，因为 `tests/smoke_wayland.py` 通过"伪"传输层驱动协议，这对单元测试
    # 而言完全正确：伪传输层提供自己的调用实现，因此真实的 QtDBus 写法从未被执行。它只在真实
    # Wayland 会话上暴露，这正是本检查的意义。
    #
    # 解析一次后缓存；两种写法都尝试，使再次搬迁枚举的旧版或新版 PySide6 仍能工作。
    global _BLOCKING_CALL_MODE
    if _BLOCKING_CALL_MODE is not None:
        return _BLOCKING_CALL_MODE
    from PySide6 import QtDBus

    for holder in (getattr(QtDBus, "QDBus", None),
                   QtDBus.QDBusConnection):
        mode = getattr(holder, "CallMode", None)
        if mode is not None and hasattr(mode, "Block"):
            _BLOCKING_CALL_MODE = mode.Block
            return _BLOCKING_CALL_MODE
    raise RuntimeError("QtDBus exposes no CallMode enum / QtDBus 没有暴露 CallMode 枚举")


# Cached value for `blocking_call_mode`; None until resolved.
# `blocking_call_mode` 的缓存值；未解析前为 None。
_BLOCKING_CALL_MODE = None


def qt_dbus_available():
    # True when PySide6's QtDBus can be imported. /
    # PySide6 的 QtDBus 可被导入时为 True。
    try:
        from PySide6.QtDBus import QDBusConnection  # noqa: F401

        return True, ""
    except ImportError as exc:
        return False, f"QtDBus is unavailable ({exc})"


def session_bus_connected():
    # True when a session bus is both configured and connected. /
    # 会话总线既已配置又已连接时为 True。
    ok, reason = qt_dbus_available()
    if not ok:
        return False, reason
    import os

    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return False, "no D-Bus session bus (DBUS_SESSION_BUS_ADDRESS is unset)"
    from PySide6.QtDBus import QDBusConnection

    if not QDBusConnection.sessionBus().isConnected():
        return False, "the D-Bus session bus is not connected"
    return True, ""


def register_app_id(bus, app_id):
    # Tell the portal this client's app id. Returns (ok, reason).
    #
    # # Why this call is required at all
    #
    # The portal refuses every `GlobalShortcuts` call from a client it cannot identify:
    #
    #     org.freedesktop.portal.Error.NotAllowed: An app id is required
    #
    # `QGuiApplication.setDesktopFileName(APP_ID)` is necessary but NOT sufficient. Measured on
    # Arch Linux + niri, where the portal backend is `xdg-desktop-portal-gnome` and there is no
    # GNOME Shell for it to ask about the focused client: the Wayland app id is published, and the
    # portal still answers "An app id is required". `Registry.Register` is the route that works,
    # and it requires a matching `.desktop` file to exist - without one it answers
    #
    #     org.freedesktop.portal.Error.Failed: Could not register app ID:
    #     App info not found for 'gifmanager'
    #
    # Both failures are reported to the caller rather than swallowed, because the difference
    # between "the portal is missing", "the app id is not declared" and "the .desktop file is not
    # installed" is exactly what a user needs to fix it.
    #
    # 把本客户端的 app id 告诉门户。返回 (是否成功, 原因)。
    #
    # # 为什么这个调用是必需的
    #
    # 门户会拒绝来自无法识别客户端的每一次 `GlobalShortcuts` 调用：
    #
    #     org.freedesktop.portal.Error.NotAllowed: An app id is required
    #
    # `QGuiApplication.setDesktopFileName(APP_ID)` 是必要的但"不充分"。在 Arch Linux + niri 上实测，
    # 此后端是 `xdg-desktop-portal-gnome`，而它没有 GNOME Shell 可问"当前客户端是谁"：Wayland app id
    # 已发布，门户仍回答 "An app id is required"。可行的是 `Registry.Register`，而它要求存在匹配的
    # `.desktop` 文件——没有它则回答
    #
    #     org.freedesktop.portal.Error.Failed: Could not register app ID:
    #     App info not found for 'gifmanager'
    #
    # 两种失败都报告给调用方而不是吞掉，因为"门户缺失"、"未声明 app id"与"未安装 .desktop 文件"
    # 这三者的区别正是用户修复它所需要的。
    if not app_id:
        return False, "no application id to register"
    try:
        from PySide6.QtDBus import QDBusMessage

        message = QDBusMessage.createMethodCall(
            PORTAL_BUS, PORTAL_PATH, PORTAL_REGISTRY_INTERFACE, "Register")
        message << str(app_id) << {}
        reply = bus.call(message, blocking_call_mode(), CALL_TIMEOUT_MS)
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            name = reply.errorName() or ""
            detail = reply.errorMessage() or name or "the registry refused the app id"
            # "Already associated" means the portal ALREADY knows this connection's app id, which
            # is the state this function exists to reach. It happens whenever Qt published the
            # id from the Wayland surface before this call - i.e. whenever
            # `setDesktopFileName` ran before the window was created, which is the correct order.
            #
            # Treating it as a failure made the hotkey fail with "the system refused the hotkey"
            # on a machine where the portal was perfectly willing. Measured on Arch + niri.
            # "already associated" 意味着门户"已经"知道本连接的 app id，而这正是本函数要达到的状态。
            # 每当 Qt 先经 Wayland 表面发布了 id（即 `setDesktopFileName` 在窗口创建前运行，也就是
            # 正确顺序）时就会发生。
            #
            # 把它当作失败，会让热键在一台门户完全乐意的机器上以"系统拒绝了热键"告败。在
            # Arch + niri 上实测。
            if "already associated" in detail.lower():
                log.debug("portal: app id %r was already associated", app_id)
                return True, ""
            if "App info not found" in detail:
                # Actionable: the fix is to install the desktop entry.
                # 可操作：修复方法是安装桌面条目。
                return False, ("the portal found no desktop entry for "
                               f"{app_id!r}; install packaging/gifmanager.desktop "
                               f"(scripts/install-desktop-entry.sh) [{detail}]")
            return False, detail
        return True, ""
    except Exception as exc:
        log.exception("portal: registering the app id raised")
        return False, str(exc)


class PortalBus:
    # The D-Bus operations the GlobalShortcuts protocol needs, and nothing else.
    #
    # Extracted from the backend so the protocol can be exercised without D-Bus: a fake
    # that implements these three methods drives `CreateSession`, `BindShortcuts` and
    # `Activated` and proves the state machine — session reuse, honouring a substituted
    # binding, dispatch by id, release on close — none of which needs a compositor.
    #
    # What a fake CANNOT prove is that the real portal accepts these arguments in this
    # order. That distinction is stated rather than blurred.
    # GlobalShortcuts 协议所需的 D-Bus 操作，仅此而已。
    #
    # 从后端抽出，使协议能在没有 D-Bus 时被演练：实现这三个方法的伪对象即可驱动
    # `CreateSession`、`BindShortcuts` 与 `Activated` 并证明状态机——会话复用、尊重被替换
    # 的绑定、按 id 分发、关闭时释放——这些都不需要合成器。
    #
    # 伪实现"无法"证明的是真实门户是否接受这些参数、这个顺序。这一区别被明确说明而非含糊带过。

    def __init__(self):
        self._bus = None
        self._interface = None
        # Why the app id could not be registered, when it could not.
        # 无法注册 app id 时的原因。
        self._register_reason = ""

    def connect(self):
        # Return (ok, reason). / 返回 (是否成功, 原因)。
        if self._interface is not None:
            return True, ""
        ok, reason = session_bus_connected()
        if not ok:
            return False, reason
        try:
            from PySide6.QtDBus import QDBusConnection, QDBusInterface
        except ImportError as exc:
            return False, f"QtDBus is unavailable ({exc})"
        self._bus = QDBusConnection.sessionBus()

        # Identify this client BEFORE any portal call, on the SAME connection.
        #
        # The registry keys off the caller's unique bus name, so registering on a different
        # connection would identify a process that then makes no calls. Doing it here also means
        # the reason is surfaced by `connect`, which every caller already handles - rather than
        # being discovered as a mysterious "the system refused the hotkey" later.
        #
        # 在任何门户调用"之前"、在"同一条"连接上标识本客户端。
        #
        # 注册表以调用方的唯一总线名为键，因此在另一条连接上注册会标识一个随后不发任何调用的进程。
        # 放在此处也意味着原因由 `connect` 暴露出来，而每个调用方本就处理它——而不是稍后才发现为
        # 一个莫名的"系统拒绝了热键"。
        registered, register_reason = register_app_id(self._bus, APP_ID)
        if not registered:
            # Not fatal for the UI: the window still opens. It IS fatal for the hotkey, and the
            # reason is what tells the user to install the desktop entry.
            # 对界面不致命：窗口仍会打开。但对热键是致命的，而该原因正是告诉用户去安装桌面条目。
            log.warning("portal: cannot register app id %r -> %s", APP_ID, register_reason)
            self._register_reason = register_reason
        else:
            self._register_reason = ""

        self._interface = QDBusInterface(
            PORTAL_BUS, PORTAL_PATH, PORTAL_INTERFACE, self._bus)
        if not self._interface.isValid():
            self._interface = None
            return False, ("the GlobalShortcuts portal is not provided by this "
                           "session (install xdg-desktop-portal)")
        return True, ""

    def call(self, method, arguments, timeout_ms=CALL_TIMEOUT_MS):
        # Return (arguments, error), with "" as the error on success.
        #
        # A tuple rather than an exception because every caller has to handle failure
        # anyway and the failure carries a message the interface shows.
        # 返回 (参数, 错误)，成功时错误为空字符串。
        #
        # 用元组而非异常，因为每个调用方无论如何都要处理失败，而该失败携带一条界面要显示的消息。
        ok, reason = self.connect()
        if not ok:
            return None, reason
        try:
            from PySide6.QtDBus import QDBusConnection, QDBusMessage

            message = QDBusMessage.createMethodCall(
                PORTAL_BUS, PORTAL_PATH, PORTAL_INTERFACE, method)
            for argument in arguments:
                message << argument
            reply = self._bus.call(message, blocking_call_mode(),
                                   timeout_ms)
            if reply.type() == QDBusMessage.MessageType.ErrorMessage:
                return None, (reply.errorMessage() or reply.errorName()
                              or "the portal refused the call")
            return reply.arguments(), ""
        except Exception as exc:
            log.exception("portal: call %s raised", method)
            return None, str(exc)

    def subscribe(self, signal, handler):
        # Connect one portal signal. Returns True when connected. /
        # 连接一个门户信号。连接成功时返回 True。
        ok, _reason = self.connect()
        if not ok:
            return False
        try:
            return bool(self._bus.connect(PORTAL_BUS, PORTAL_PATH,
                                          PORTAL_INTERFACE, signal, handler))
        except Exception:
            log.exception("portal: subscribing to %s failed", signal)
            return False

    def supports_binding(self):
        # Whether this transport can actually SEND a `BindShortcuts` call. (ok, reason).
        #
        # # Why this probe exists at all
        #
        # `BindShortcuts(session o, shortcuts a(sa{sv}), parent_window s, options a{sv})` needs an
        # ARRAY OF STRUCTS. PySide6 cannot construct that type: there is no
        # `QMetaType.Type.QDBusArgument`, so `QDBusArgument.beginArray` cannot be given a struct
        # element type, and a plain Python list of tuples arrives as `PySide::PyObjectWrapper`
        # which D-Bus refuses to marshal:
        #
        #     QDBusMarshaller: type 'PySide::PyObjectWrapper' is not registered with D-Bus
        #     Marshalling failed: Unregistered type PySide::PyObjectWrapper passed in arguments
        #
        # The damage was not the failure itself but WHERE it happened: `QDBusConnection.call` is
        # BLOCKING, the message never left, so no reply ever came and the call sat on the GUI
        # thread until `BIND_TIMEOUT_MS` (120 s) expired. The window never appeared - the
        # application looked hung on startup, with the last log line being a portal session.
        #
        # So the argument is CONSTRUCTED HERE, in isolation, and its SIGNATURE checked. If the
        # signature is not exactly `a(sa{sv})` the binding is impossible and the caller must not
        # make the call at all.
        # 本传输层是否"真的能发出" `BindShortcuts`。返回 (是否可行, 原因)。
        #
        # # 为什么需要这个探测
        #
        # `BindShortcuts(session o, shortcuts a(sa{sv}), parent_window s, options a{sv})` 需要
        # "结构体数组"。PySide6 无法构造该类型：没有 `QMetaType.Type.QDBusArgument`，因此
        # `QDBusArgument.beginArray` 拿不到结构体元素类型，而普通 Python 元组列表到达时是
        # `PySide::PyObjectWrapper`，D-Bus 拒绝编组它：
        #
        #     QDBusMarshaller: type 'PySide::PyObjectWrapper' is not registered with D-Bus
        #     Marshalling failed: Unregistered type PySide::PyObjectWrapper passed in arguments
        #
        # 危害不在失败本身，而在它"发生的位置"：`QDBusConnection.call` 是阻塞的，消息根本没发出，
        # 因此永远没有回复，调用就在 GUI 线程上一直挂到 `BIND_TIMEOUT_MS`（120 秒）过期。窗口从未
        # 出现——应用看起来在启动时卡死，最后一行日志是一个门户会话。
        #
        # 因此这里"单独"构造该参数并检查其"签名"。若签名不是恰好 `a(sa{sv})`，绑定就不可能完成，
        # 调用方绝不应发出该调用。
        try:
            from PySide6.QtCore import QMetaType
            from PySide6.QtDBus import QDBusArgument

            argument = QDBusArgument()
            argument.beginArray(QMetaType(QMetaType.Type.QVariantMap))
            argument.endArray()
            signature = str(argument.currentSignature())
        except Exception as exc:
            return False, (f"this PySide6 cannot build a D-Bus struct array ({exc}); "
                           f"global shortcuts through the portal are unavailable")
        if signature != "a(sa{sv})":
            return False, (
                "this PySide6 cannot construct the `a(sa{sv})` argument `BindShortcuts` "
                f"requires (it produces {signature!r}), so the portal cannot bind a shortcut; "
                "bind a key in the compositor to `--toggle` instead "
                "/ 本 PySide6 无法构造 `BindShortcuts` 所需的 `a(sa{sv})` 参数，"
                "因此门户无法绑定快捷键；请在合成器中把某个键绑定到 `--toggle`")
        return True, ""

    def sender(self):
        # The backend needs it because `CreateSession` replies with a REQUEST handle, and the
        # session handle has to be derived as
        # `/org/freedesktop/portal/desktop/session/<sender sanitised>/<session_handle_token>`.
        # Exposed as a method rather than a property so a fake transport can supply it, and
        # returning "" when unknown lets the caller report a clear error instead of building a
        # path with an empty component.
        # 本连接的唯一总线名，门户会把它嵌入会话路径。
        #
        # 后端需要它，因为 `CreateSession` 回复的是"请求"句柄，而会话句柄必须推导为
        # `/org/freedesktop/portal/desktop/session/<净化后的 sender>/<session_handle_token>`。
        # 用方法而非属性暴露，使伪传输层也能提供它；未知时返回空字符串，让调用方报告清晰的错误
        # 而不是构造一个含空组件的路径。
        try:
            if self._bus is None:
                from PySide6.QtDBus import QDBusConnection

                self._bus = QDBusConnection.sessionBus()
            return str(self._bus.baseService() or "")
        except Exception:
            log.exception("portal: cannot read the connection's bus name")
            return ""

    def close_session(self, session_path):
        # Call `Close` on a session object, which releases its bindings. /
        # 在会话对象上调用 `Close`，释放其绑定。
        if not session_path:
            return True
        try:
            from PySide6.QtDBus import QDBusConnection, QDBusMessage

            bus = self._bus
            if bus is None:
                bus = QDBusConnection.sessionBus()
            message = QDBusMessage.createMethodCall(
                PORTAL_BUS, session_path, PORTAL_SESSION_INTERFACE, "Close")
            bus.call(message, blocking_call_mode(), CALL_TIMEOUT_MS)
            return True
        except Exception:
            log.exception("portal: closing the session failed")
            return False


def portal_available():
    # True when a GlobalShortcuts portal is reachable, with a reason when it is not.
    #
    # Probed rather than assumed: the portal service may be absent (a minimal session),
    # present without the GlobalShortcuts interface (an older xdg-desktop-portal), or
    # present and usable. Each needs a different answer in the interface, so the probe
    # returns the reason alongside the flag.
    # GlobalShortcuts 门户可达时为 True，不可达时给出原因。
    #
    # 是探测而非假定：门户服务可能不存在（极简会话）、存在但没有 GlobalShortcuts 接口
    #（较旧的 xdg-desktop-portal）、或存在且可用。三者所需的界面回答不同，因此探测连同原因
    # 一起返回。
    ok, reason = session_bus_connected()
    if not ok:
        return False, reason
    try:
        from PySide6.QtDBus import QDBusConnection, QDBusInterface

        bus = QDBusConnection.sessionBus()
        interface = QDBusInterface(PORTAL_BUS, PORTAL_PATH, PORTAL_INTERFACE, bus)
        if not interface.isValid():
            return False, ("the GlobalShortcuts portal is not provided by this "
                           "session (install xdg-desktop-portal)")
        return True, ""
    except Exception as exc:
        return False, f"the portal probe failed ({exc})"


__all__ = [
    "BIND_TIMEOUT_MS",
    "CALL_TIMEOUT_MS",
    "PORTAL_BUS",
    "PORTAL_INTERFACE",
    "PORTAL_PATH",
    "PORTAL_SESSION_INTERFACE",
    "PortalBus",
    "portal_available",
    "qt_dbus_available",
    "session_bus_connected",
]
