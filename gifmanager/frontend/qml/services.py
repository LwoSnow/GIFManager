"""System tray icon and global hotkey, as bindable QML services.

Both are things a user expects from this kind of tool and neither existed: there was
no tray, and `hotkey` was a stored setting that nothing ever registered with the
system.

# Why these are separate services rather than methods on the bridge

The tray may not exist (a session without one, a headless run, a platform where
`QSystemTrayIcon` is unavailable) and the global hotkey may not be supported (every
non-Windows backend is a skeleton). Putting them on the bridge would mean every front
-end had to guard every call; a service that reports `available` lets QML bind
visibility to it instead of testing a capability at each call site.

# The tray needs a real icon

`QSystemTrayIcon` with no icon is INVISIBLE on Windows — not an error, just absent,
which is indistinguishable from "the platform has no tray". The icon is therefore
built from the application's own window icon, and a tray that cannot produce an icon
reports itself unavailable rather than silently not appearing.

系统托盘图标与全局热键，作为可绑定的 QML 服务。

两者都是这类工具的用户所期望的，而两者此前都不存在：没有托盘，而 `hotkey` 只是一个存储的
设置，从未被注册到系统。

# 为什么它们是独立服务而不是桥上的方法

托盘可能不存在（无托盘的会话、无头运行、`QSystemTrayIcon` 不可用的平台），而全局热键可能
不受支持（所有非 Windows 后端都是骨架）。把它们放在桥上意味着每个前端都必须在每次调用处
防护；一个报告 `available` 的服务让 QML 把可见性绑定到它，而不是在每个调用点测试能力。

# 托盘需要真实图标

在 Windows 上，没有图标的 `QSystemTrayIcon` 是"不可见"的——不是报错，只是不出现，而这与
"平台没有托盘"无法区分。因此图标由应用自身的窗口图标构建，而无法生成图标的托盘会报告自己
不可用，而不是静默地不出现。
"""
import logging

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtQuick import QQuickImageProvider

log = logging.getLogger("GIFManager")


def register_bundled_fonts():
    # Load every bundled font and return (ok, family names, reason).
    #
    # # Why this must run before any window exists
    #
    # `QFontDatabase.addApplicationFont` only affects fonts resolved AFTERWARDS. QML resolves a
    # `font.family` when the item is created, and the application-wide font is captured when it is
    # set, so loading the files after the engine has loaded the interface means the first frame -
    # and
    # any item already built - keeps the system face. Hence this is called from
    # `build_application`, next to `setDesktopFileName`, not from the theme bridge.
    #
    # # Why the file order matters
    #
    # The six files are one family with six WEIGHTS. Registering them in ascending weight order lets
    # Qt's database attach them as styles of one family, so `font.weight: Font.DemiBold` resolves to
    # the Bold file. Registering them in directory order would still work for the default weight but
    # would make `Font.Bold` land on whichever file Qt saw first.
    #
    # Returns the family names Qt actually registered, because the QML side must name a family that
    # exists: a typo silently falls back to the system face with no error at all.
    # 加载全部随包字体，返回 (是否成功, 字族名列表, 原因)。
    #
    # # 为什么必须在任何窗口存在之前运行
    #
    # `QFontDatabase.addApplicationFont` 只影响其"之后"解析的字体。QML 在元素被创建时解析
    # `font.family`，而应用级字体在被设置时就被捕获，因此在引擎加载界面之后才加载文件意味着首帧——以及
    # 任何已经构建的元素——仍使用系统字面。因此它由 `build_application` 调用，与
    # `setDesktopFileName` 相邻，而不是由主题桥调用。
    #
    # # 为什么文件顺序要紧
    #
    # 这六个文件是"同一字族的六个字重"。按字重升序注册让 Qt 的数据库把它们作为同一字族的样式挂上，
    # 于是 `font.weight: Font.DemiBold` 会解析到 Bold 文件。按目录顺序注册对默认字重仍然可用，但会让
    # `Font.Bold` 落在 Qt 最先看到的那个文件上。
    #
    # 返回 Qt 实际注册的字族名，因为 QML 侧必须命名一个存在的字族：拼错会静默回退到系统字面，且没有
    # 任何错误。
    import os

    from PySide6.QtGui import QFontDatabase

    from gifmanager.core import paths
    from gifmanager.frontend.qml.theme import BUNDLED_FONT_FILE_ORDER

    root = paths.resources_dir()
    if not root:
        return False, [], "no resources directory"
    directory = os.path.join(root, "fonts")
    if not os.path.isdir(directory):
        return False, [], f"no fonts directory at {directory}"

    families = []
    loaded = 0
    for name in BUNDLED_FONT_FILE_ORDER:
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            log.warning("fonts: %s is absent; that weight will fall back", name)
            continue
        identifier = QFontDatabase.addApplicationFont(path)
        if identifier < 0:
            # A negative id means Qt refused the file. Reported rather than swallowed, because a
            # rejected font looks exactly like "the system face is being used", which is the state
            # this function exists to leave.
            # 负值意味着 Qt 拒收该文件。报告而不是吞掉，因为被拒收的字体与"正在使用系统字面"看起来
            # 完全一样，而那正是本函数要摆脱的状态。
            log.warning("fonts: Qt refused %s", path)
            continue
        loaded += 1
        for family in QFontDatabase.applicationFontFamilies(identifier):
            if family not in families:
                families.append(family)
    if not loaded:
        return False, [], "no bundled font could be loaded"
    log.info("fonts: loaded %d file(s), families=%s", loaded, families)
    return True, families, ""



def platform_key():
    # The active platform's registry key ("win32", "darwin", "linux").
    #
    # Exposed because the QML bootstrap needs it for the font family list and the update
    # installer, and reaching for `platform.current().key` from three places means three
    # places to get the import wrong. It reports "unknown" rather than raising: a missing
    # platform key must not stop the interface from starting.
    # 当前平台的注册键（"win32"、"darwin"、"linux"）。
    #
    # 暴露它是因为 QML 引导需要它来选字体族并决定更新安装器，而从三处去取
    # `platform.current().key` 意味着三处都可能把导入写错。它报告 "unknown" 而不抛错：缺少
    # 平台键不得阻止界面启动。
    try:
        from gifmanager import platform as platform_layer

        return platform_layer.current().key or "unknown"
    except Exception:
        log.exception("platform: cannot resolve the platform key")
        return "unknown"


def tray_available():
    # True when this session can show a tray icon at all.
    #
    # `isSystemTrayAvailable` is a static probe; it is asked BEFORE constructing the
    # icon, because constructing one in a session without a tray produces an object
    # that exists and never appears — the worst kind of "it works on my machine".
    # 本会话能显示托盘图标时为 True。
    #
    # `isSystemTrayAvailable` 是静态探测；它在构造图标"之前"询问，因为在没有托盘的会话里构造
    # 一个会产生一个存在却永不出现的对象——最糟糕的那种"在我机器上是好的"。
    #
    # # The probe is NOT sufficient on its own
    #
    # `QSystemTrayIcon.isSystemTrayAvailable()` answers "does this desktop publish a tray
    # area", and it returns True even in a process whose application object is only a
    # `QGuiApplication`. But the tray is built from `QSystemTrayIcon` and `QMenu`, both of
    # which are QtWidgets, and constructing ANY `QWidget` without a `QApplication` aborts
    # the process outright:
    #
    #     QWidget: Cannot create a QWidget without QApplication
    #
    # That is not a warning — the process dies, with exit code 134 on Linux and a bare
    # abort on Windows. Measured on Arch Linux under niri:
    #
    #     app type          : QGuiApplication
    #     isSystemTrayAvail : True
    #     QApplication.inst : <QGuiApplication object>      <- not a QApplication
    #
    # So the question "can this session show a tray" has a second half: "is this process
    # allowed to build widgets at all". Without this check, `tests/smoke_qml.py` — which
    # builds a `QGuiApplication` on purpose, because the pure-QML checks need no widget
    # stack — died with SIGABRT before it could assert anything.
    #
    # 这个探测本身不充分。
    #
    # `QSystemTrayIcon.isSystemTrayAvailable()` 回答的是"这个桌面是否提供托盘区"，而它在
    # 应用对象只是 `QGuiApplication` 的进程里也返回 True。但托盘由 `QSystemTrayIcon` 与
    # `QMenu` 构建，两者都是 QtWidgets，而在没有 `QApplication` 时构造"任何" `QWidget` 会
    # 直接中止进程：
    #
    #     QWidget: Cannot create a QWidget without QApplication
    #
    # 那不是警告——进程会死，Linux 上退出码 134，Windows 上是一次裸 abort。在 Arch Linux 的
    # niri 下实测：
    #
    #     app 类型          : QGuiApplication
    #     isSystemTrayAvail : True
    #     QApplication.inst : <QGuiApplication 对象>      <- 不是 QApplication
    #
    # 因此"本会话能否显示托盘"这个问题有下半部分："本进程是否有权构建控件"。没有这项检查时，
    # `tests/smoke_qml.py`（它刻意构建 `QGuiApplication`，因为纯 QML 检查不需要控件栈）在断言
    # 任何东西之前就以 SIGABRT 死掉。
    try:
        from PySide6.QtWidgets import QApplication, QSystemTrayIcon

        # `isinstance` rather than `is not None`: a `QGuiApplication` instance satisfies
        # `QApplication.instance()` and is exactly the case that crashes.
        # 用 `isinstance` 而不是 `is not None`：`QGuiApplication` 实例能满足
        # `QApplication.instance()`，而它正是会崩溃的那种情况。
        if not isinstance(QApplication.instance(), QApplication):
            return False
        return bool(QSystemTrayIcon.isSystemTrayAvailable())
    except Exception:
        log.exception("tray: the availability probe failed")
        return False


def application_icon_path():
    # The bundled application icon, or "" when it is not there.
    #
    # Located through `core.paths.resources_dir()`, so a packaged build finds it
    # beside the executable and a source run finds it in `resources/`. The `.ico`
    # is preferred on Windows because it carries the multi-resolution sizes the shell
    # asks for; elsewhere the `.png` is the one that exists.
    # 随包的应用图标，不存在时为空字符串。
    #
    # 经 `core.paths.resources_dir()` 定位，因此打包构建会在可执行文件旁找到它，源码运行会在
    # `resources/` 找到它。Windows 上优先用 `.ico`，因为它带外壳所索取的多分辨率尺寸；其他
    # 平台则是存在的那个 `.png`。
    import os

    try:
        from gifmanager.core import paths

        root = paths.resources_dir()
    except Exception:
        log.exception("tray: cannot resolve the resources directory")
        return ""
    if not root:
        return ""
    for name in ("gifmanager.ico", "gifmanager.png", "icon.ico", "icon.png"):
        candidate = os.path.join(root, "icons", name)
        if os.path.isfile(candidate):
            return candidate
    return ""


def apply_application_icon(target=None):
    # Give the application and, when given, a window the bundled icon.
    #
    # Called before the interface is created, because a window icon set after the
    # window is shown does not update the taskbar entry on Windows.
    # 把随包图标交给应用，并在给出窗口时也交给窗口。
    #
    # 在创建界面之前调用，因为在 Windows 上窗口显示之后再设置图标不会更新任务栏条目。
    path = application_icon_path()
    if not path:
        log.info("icon: no bundled icon found; the window and tray will be plain")
        return False
    try:
        from PySide6.QtGui import QGuiApplication, QIcon

        icon = QIcon(path)
        if icon.isNull():
            log.warning("icon: %s loaded as a null icon", path)
            return False
        app = QGuiApplication.instance()
        if app is not None:
            app.setWindowIcon(icon)
        if target is not None:
            target.setWindowIcon(icon)
        log.info("icon: %s", path)
        return True
    except Exception:
        log.exception("icon: cannot apply %s", path)
        return False


class TrayService(QObject):
    # The tray icon and its menu.
    #
    # Actions are exposed as SIGNALS rather than callbacks into the bridge, so this
    # service does not depend on a front-end: whichever front-end owns it decides what
    # "copy" means.
    # 托盘图标及其菜单。
    #
    # 操作以"信号"而非回调进桥的方式暴露，因此本服务不依赖任何前端：持有它的前端自行决定
    # "复制"意味着什么。
    toggleRequested = Signal()
    copyRequested = Signal()
    settingsRequested = Signal()
    quitRequested = Signal()
    # The trigger reason, for diagnostics / 触发原因，用于诊断
    activated = Signal(str)

    def __init__(self, window=None, parent=None):
        super().__init__(parent)
        self._window = window
        self._tray = None
        self._available = False
        self._reason = ""
        self._title = "GIFManager"
        self._setup()

    def _setup(self):
        if not tray_available():
            self._reason = "no system tray in this session"
            log.info("tray: not available (%s)", self._reason)
            return
        try:
            from PySide6.QtGui import QAction, QKeySequence
            from PySide6.QtWidgets import QMenu, QSystemTrayIcon
        except Exception:
            log.exception("tray: cannot import the tray classes")
            self._reason = "tray classes unavailable"
            return

        icon = self._icon()
        if icon is None or icon.isNull():
            # Without an icon the tray entry exists but is invisible, so reporting
            # available would be a lie the user cannot see through.
            # 没有图标时托盘条目存在但不可见，因此报告可用会是一个用户看不穿的谎言。
            self._reason = "no icon available, so a tray entry would be invisible"
            log.warning("tray: %s", self._reason)
            return

        tray = QSystemTrayIcon(icon, self)
        menu = QMenu()
        self._menu = menu

        # Menu entries get their mnemonics from Qt's STANDARD key sequences rather
        # than from hand-written "(&C)" text. Two reasons: a mnemonic baked into a
        # translated string cannot be re-chosen when the translation changes, and the
        # standard sequence is what makes the shortcut match the platform's
        # convention (Ctrl+Q on Windows, Cmd+Q on macOS) without a platform test here.
        # 菜单条目从 Qt 的"标准"键序列取助记键，而不是手写的 "(&C)" 文本。两个原因：写进
        # 已翻译字符串的助记键无法在翻译变更时重新选择；而标准序列正是让快捷键符合平台惯例
        #（Windows 上 Ctrl+Q、macOS 上 Cmd+Q）而无需在此做平台判断的原因。
        self._action_show = QAction(self._t("toggle_window"), menu)
        self._action_show.triggered.connect(self.toggleRequested)
        menu.addAction(self._action_show)

        menu.addSeparator()

        self._action_settings = QAction(self._t("settings"), menu)
        self._action_settings.triggered.connect(self.settingsRequested)
        menu.addAction(self._action_settings)

        menu.addSeparator()

        self._action_quit = QAction(self._t("quit"), menu)
        self._action_quit.setShortcut(QKeySequence.StandardKey.Quit)
        self._action_quit.triggered.connect(self.quitRequested)
        menu.addAction(self._action_quit)

        tray.setContextMenu(menu)
        tray.setToolTip(self._title)
        # A LEFT-click on the icon is the "show me the window" gesture on Windows and
        # a no-op on macOS, which is why the reason is passed on.
        # 在 Windows 上左键点击图标是"把窗口给我"的手势，在 macOS 上是空操作，因此把原因
        # 一并传出。
        tray.activated.connect(self._on_activated)
        tray.show()

        self._tray = tray
        self._available = True

    def _icon(self):
        # The window's icon, the application's, or the icon file on disk.
        #
        # The disk lookup is the fallback that actually matters: nothing sets a window
        # icon unless the front-end does, and `QGuiApplication.windowIcon()` is empty
        # by default. Without this the tray would report "no icon" on a perfectly
        # healthy session — which is what happened the first time this was tested on
        # real Windows.
        #
        # 窗口图标、应用图标，或磁盘上的图标文件。
        #
        # 磁盘查找才是真正重要的回退：除非前端设置，否则没有东西会设置窗口图标，而
        # `QGuiApplication.windowIcon()` 默认为空。没有它就等于在一个完全健康的会话里报告
        # "没有图标"——这正是第一次在真实 Windows 上测试时发生的事。
        for source in ("window", "application"):
            try:
                if source == "window" and self._window is not None:
                    icon = self._window.windowIcon()
                elif source == "application":
                    from PySide6.QtGui import QGuiApplication

                    app = QGuiApplication.instance()
                    icon = app.windowIcon() if app is not None else None
                else:
                    icon = None
                if icon is not None and not icon.isNull():
                    return icon
            except Exception:
                log.exception("tray: cannot read the %s icon", source)

        path = application_icon_path()
        if path:
            try:
                from PySide6.QtGui import QIcon

                icon = QIcon(path)
                if not icon.isNull():
                    return icon
            except Exception:
                log.exception("tray: cannot load the icon from %s", path)
        return None

    @staticmethod
    def _t(key):
        # Translation without an adapter, because the tray is built before any
        # front-end hands one over. A missing table falls back to the key.
        # Trailing mnemonic parentheses ("复制(&C)") are STRIPPED: a QAction
        # renders them as a dead "(C)" — the tray menu has no mnemonic handling,
        # and the copy shortcut is already on the action via the standard key
        # sequence.
        # 无适配器的翻译，因为托盘在任何前端交出适配器之前就被构建。表缺失时回退到键名。
        # 结尾的助记括号（"复制(&C)"）被剥离：QAction 会把它画成一个无用的 "(C)"
        # ——托盘菜单没有助记键处理，且复制快捷键已由标准键序列设在动作上。
        import re

        try:
            from gifmanager.core.lang import tr

            return re.sub(r"\s*\(&[A-Za-z]\)", "", tr(key))
        except Exception:
            return key

    def _on_activated(self, reason):
        from PySide6.QtWidgets import QSystemTrayIcon

        names = {
            QSystemTrayIcon.ActivationReason.Trigger: "trigger",
            QSystemTrayIcon.ActivationReason.DoubleClick: "double-click",
            QSystemTrayIcon.ActivationReason.Context: "context",
            QSystemTrayIcon.ActivationReason.MiddleClick: "middle-click",
        }
        name = names.get(reason, str(reason))
        self.activated.emit(name)
        # Only the primary gesture toggles: treating a right-click the same way would
        # toggle the window at the same moment the menu opens.
        # 只有主手势触发切换：把右键同等对待会在菜单打开的同时切换窗口。
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggleRequested.emit()

    # ---- state / 状态 ----------------------------------------------------

    @Property(bool, notify=activated)
    def available(self):
        return self._available

    @Property(str, notify=activated)
    def unavailableReason(self):
        return self._reason

    @Property(str, notify=activated)
    def title(self):
        return self._title

    @Slot(str)
    def setTitle(self, title):
        self._title = str(title or "")
        if self._tray is not None:
            self._tray.setToolTip(self._title)

    @Slot(str)
    def showMessage(self, message, timeout_ms=4000):
        # A balloon notification. Ignored when there is no tray, because a
        # notification with nowhere to appear is not an error.
        # 气泡通知。没有托盘时忽略，因为一条无处显示的通知不是错误。
        if self._tray is None:
            return
        from PySide6.QtWidgets import QSystemTrayIcon

        self._tray.showMessage(self._title, str(message),
                               QSystemTrayIcon.MessageIcon.Information,
                               int(timeout_ms))

    @Slot(str)
    def retranslate(self, _language=""):
        # Re-apply the menu labels after a language change.
        #
        # The actions are read with `getattr(..., None)` and skipped when absent, because
        # this list and the construction above are edited independently: the "copy" entry
        # was removed from the menu during a refactor while this method kept setting its
        # text, so a language change raised
        #
        #     AttributeError: 'TrayService' object has no attribute '_action_copy'
        #
        # and took the tray down with it. A missing action means "this entry no longer
        # exists", which is not an error to report — but it IS worth a debug line, because
        # the alternative (a silent skip) would hide a genuinely misnamed action forever.
        #
        # 语言变更后重新应用菜单标签。
        #
        # 用 `getattr(..., None)` 读取动作并在缺失时跳过，因为本列表与上面的构建是分别编辑的：
        # 一次重构把"复制"条目从菜单移除，而本方法仍在设置它的文本，于是语言变更抛出
        #
        #     AttributeError: 'TrayService' object has no attribute '_action_copy'
        #
        # 并把托盘一起搞坏。动作缺失意味着"该条目已不存在"，这不是需要报告的错误——但它"确实"
        # 值得一行 debug 日志，因为另一种做法（静默跳过）会永远掩盖一个真正写错名字的动作。
        if not self._available:
            return
        for attribute, key in (("_action_show", "toggle_window"),
                               ("_action_copy", "copy"),
                               ("_action_settings", "settings"),
                               ("_action_quit", "quit")):
            action = getattr(self, attribute, None)
            if action is None:
                log.debug("tray: no %s action to retranslate", attribute)
                continue
            action.setText(self._t(key))

    def shutdown(self):
        # Hide and detach. Leaving a tray icon behind after the window closes makes a
        # process that looks like it has exited but has not.
        # 隐藏并分离。窗口关闭后留下托盘图标会造出一个看起来已退出其实没有的进程。
        if self._tray is not None:
            self._tray.hide()
            self._tray.setContextMenu(None)
            self._tray.deleteLater()
            self._tray = None
        self._available = False


class HotkeyService(QObject):
    # Registers the user's global hotkey and reports whether it took.
    #
    # Registration can FAIL for reasons the user controls — another application holds
    # the combination — so the result is a property with a reason rather than a
    # boolean the caller has to interpret.
    # 注册用户的全局热键并报告是否成功。
    #
    # 注册可能因用户可控的原因失败——另一个应用占用了该组合——因此结果是一个带原因的属性，
    # 而不是一个需要调用方自行解读的布尔值。
    changed = Signal()
    pressed = Signal()

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self._backend = backend
        self._registered = False
        self._reason = ""
        self._binding = None
        self._available = self._probe()
        if self._available:
            self.reload()

    def _probe(self):
        try:
            # `Backend.supports` takes a capability NAME from the settings schema,
            # not a service name: the mapping from one to the other lives in
            # `platform_report`, so asking it here is what keeps the tray's idea of
            # "supported" identical to the settings page's.
            # `Backend.supports` 接收的是设置 schema 的能力"名"，而不是服务名：两者之间的
            # 映射在 `platform_report` 里，因此在此问它才能让托盘对"受支持"的判断与设置页
            # 完全一致。
            from gifmanager.core import settings as settings_schema

            return bool(self._backend.supports(
                settings_schema.CAPABILITY_GLOBAL_HOTKEY))
        except Exception:
            log.exception("hotkey: the capability probe failed")
            return False

    def _hotkeys(self):
        # Resolved through `Platform.service`, which is the documented way to reach a
        # platform implementation and returns the BASE class when the platform has no
        # real one — so the call below fails as an unsupported operation rather than as an
        # AttributeError.
        #
        # On Linux the class depends on the SESSION, not on the platform: X11 can grab a
        # key, Wayland can only ask the compositor through the portal. The platform module
        # exposes the choice as a function because a module-level decision would freeze
        # whichever session type was active at import time.
        #
        # 经 `Platform.service` 解析，这是访问平台实现的既定方式；当平台没有真实实现时它返回
        # "基类"——因此下面的调用会作为不支持的操作失败，而不是 AttributeError。
        #
        # Linux 上类取决于"会话"而非平台：X11 能抓取按键，Wayland 只能经门户请求合成器。平台
        # 模块把该选择暴露为函数，因为模块级决定会冻住导入时恰好生效的会话类型。
        from gifmanager import platform as platform_layer
        from gifmanager.platform.base import HotkeyBackend

        platform = platform_layer.current()
        if platform.key == "linux":
            from gifmanager.platform import linux as linux_module

            backend_class = linux_module.session_hotkey_backend()
            if backend_class is linux_module.WaylandHotkeyBackend:
                # The PROBE needs Qt, which the platform layer may not import, so it
                # happens here and its result is passed into the backend. Doing it the
                # other way round is what the layer check rejects, and it is right to:
                # `platform` must stay usable by a headless process.
                #
                # 探测需要 Qt，而平台层不得导入它，因此在此完成并把结果传入后端。反过来做正是
                # 分层检查所拒绝的，而这是对的：`platform` 必须保持可被无头进程使用。
                from gifmanager.frontend.qml.portal import PortalBus, portal_available

                available, reason = portal_available()
                instance = backend_class(bus=PortalBus(), available=available,
                                         reason=reason)
                return platform.service("hotkeys", HotkeyBackend,
                                        override=lambda: instance)
            return platform.service("hotkeys", HotkeyBackend,
                                    override=backend_class)
        return platform.service("hotkeys", HotkeyBackend)

    @Property(bool, notify=changed)
    def available(self):
        return self._available

    @Property(bool, notify=changed)
    def registered(self):
        return self._registered

    @Property(str, notify=changed)
    def reason(self):
        return self._reason

    @Property(str, notify=changed)
    def sequence(self):
        binding = self._binding
        if binding is None:
            return ""
        try:
            return binding.describe()
        except Exception:
            return ""

    @Slot(result=bool)
    def reload(self):
        # Register whatever the settings currently say, replacing any previous
        # registration.
        #
        # Unregistering first is deliberate: registering over a live combination on
        # Windows fails with "already registered", so without the teardown a user
        # could never CHANGE their hotkey — only set one once.
        # 注册设置当前所说的组合，替换任何先前的注册。
        #
        # 先注销是刻意的：在 Windows 上覆盖一个仍然生效的组合会以"已注册"失败，因此没有这一步
        # 用户就永远无法"更改"热键——只能设置一次。
        self.unregister()
        if not self._available:
            self._reason = "this system does not support global hotkeys"
            self.changed.emit()
            return False

        binding = self._backend.settings.hotkey
        self._binding = binding
        if binding is None or not getattr(binding, "key", ""):
            self._reason = "no hotkey is configured"
            self.changed.emit()
            return False

        try:
            token = self._hotkeys().register(0, binding, self._on_pressed)
        except Exception as exc:
            log.warning("hotkey: registration of %s failed: %s", binding, exc)
            self._registered = False
            self._reason = str(exc)
            self.changed.emit()
            return False

        self._registered = token is not None
        # A backend that raises nothing but returns None has not registered, and
        # saying so is the difference between "the hotkey works" and "the setting is
        # saved" — two states the previous release could not distinguish.
        # 一个不抛异常但返回 None 的后端并未注册，说明这一点正是"热键可用"与"设置已保存"的
        # 区别——上一版本无法区分这两种状态。
        #
        # The backend's OWN reason is included when it has one.
        #
        # A bare "the system refused the hotkey" is unactionable: it reads the same whether the
        # combination is taken, the session has no hotkey service, or the client binding cannot
        # marshal a portal argument. The Wayland backend stores the real message (`last_error`)
        # precisely so it can be shown, and on Arch + niri that message is what tells a user that
        # the Python binding cannot construct `a(sa{sv})` - a fact no amount of retrying changes.
        # 后端"自身"的原因在有的时候一并给出。
        #
        # 一句光秃秃的"系统拒绝了热键"无可操作：无论组合键被占用、会话没有热键服务、还是客户端绑定
        # 无法编组门户参数，读起来都一样。Wayland 后端正是把真实消息存进 `last_error` 以便显示，
        # 而在 Arch + niri 上，那条消息才告诉用户 Python 绑定无法构造 `a(sa{sv})`——一个重试多少次
        # 都不会改变的事实。
        self._reason = ("" if self._registered
                        else self._refusal_reason())
        self.changed.emit()
        if self._registered:
            log.info("hotkey: registered %s", self.sequence)
        else:
            log.warning("hotkey: not registered (%s)", self._reason)
        return self._registered

    def _refusal_reason(self):
        # The backend's explanation when it has one, else the generic sentence.
        # 后端有解释时用解释，否则用笼统的句子。
        detail = ""
        try:
            getter = getattr(self._hotkeys(), "last_error", None)
            if callable(getter):
                detail = str(getter() or "").strip()
        except Exception:
            detail = ""
        if detail:
            return f"the system refused the hotkey: {detail}"
        return "the system refused the hotkey"

    @Slot()
    def unregister(self):
        if not self._registered:
            return
        try:
            self._hotkeys().unregister(0)
        except Exception:
            log.exception("hotkey: unregister failed")
        self._registered = False
        self.changed.emit()

    def _on_pressed(self):
        # Runs on whichever thread the platform's hotkey mechanism uses, so it only
        # emits: QML must not be touched from there.
        # 在平台热键机制所用的线程上运行，因此它只发信号：绝不可从那里触碰 QML。
        self.pressed.emit()

    def shutdown(self):
        self.unregister()


class GearIconProvider(QQuickImageProvider):
    # A BUNDLED SVG rendered with the theme's text colour injected as the fill — the same trick
    # the original toolbar's `_apply_settings_icon` used, because these files ship with no fill
    # and would draw black on the dark toolbar. A provider (rather than a QML MultiEffect) keeps
    # the tint authoritative in one place and lets the URL carry the name, so a theme switch
    # reloads the image naturally.
    #
    # # The URL carries the icon NAME as well as the theme
    #
    # It was hardcoded to `setting.svg`, which meant a second icon could only be added by
    # copying the class. The id is now `<name>/<theme>` — so `image://gear/github/dark` — and
    # the name is validated against a whitelist rather than pasted into a path, because the URL
    # is reachable from QML and `../..` in an id would otherwise escape the icons directory.
    #
    # 用主题文字色作为填充渲染"随包的" SVG——与原项目工具栏 `_apply_settings_icon` 同一手法，
    # 因为这些文件不带填充、在深色工具栏上会画成黑色。用提供器（而非 QML 的 MultiEffect）使着色
    # 只在一处具有权威性，并让 URL 携带名称——主题切换时图像自然重载。
    #
    # # URL 同时携带图标"名称"与主题
    #
    # 它过去写死为 `setting.svg`，意味着加第二个图标只能靠复制这个类。现在 id 是
    # `<名称>/<主题>`——即 `image://gear/github/dark`——而名称会经白名单校验而不是直接拼进路径，
    # 因为该 URL 可从 QML 到达，否则 id 里的 `../..` 会逃出 icons 目录。

    # The SVGs this provider will render. A whitelist, not a path join.
    # 本提供器会渲染的 SVG。用白名单，而不是拼接路径。
    ALLOWED = ("setting", "github")

    def __init__(self, theme, parent=None):
        super().__init__(QQuickImageProvider.Pixmap)
        self._theme = theme

    def _svg_path(self, image_id):
        import os

        from gifmanager.core import paths

        root = paths.resources_dir()
        if not root:
            return ""
        # `image_id` is "<name>" or "<name>/<theme>"; the theme half is only there to force a
        # reload on a theme switch and carries no information the provider needs.
        # `image_id` 是 "<名称>" 或 "<名称>/<主题>"；主题那一半只是用来在主题切换时强制重载，
        # 不携带提供器需要的信息。
        name = str(image_id or "setting").split("/", 1)[0].strip().lower()
        if name not in self.ALLOWED:
            log.warning("icon: %r is not a bundled icon; refusing", name)
            return ""
        candidate = os.path.join(root, "icons", f"{name}.svg")
        return candidate if os.path.isfile(candidate) else ""

    def _tint(self, svg):
        # Give a bundled SVG the theme's CONTRAST colour, whether it is stroke- or fill-based.
        #
        # # The bug this fixes, measured
        #
        # The provider injected a `fill` attribute onto the root `<svg>` element. That worked for a
        # FILL-based icon, and silently did nothing once `setting.svg` became a Lucide
        # STROKE-based icon:
        #
        #     <svg ... fill="none" stroke="currentColor" stroke-width="2" ...>
        #
        # Two things then went wrong at once. Injecting `fill` on an element that already declares
        # `fill="none"` produces a duplicate attribute, and the declared `none` wins; and
        # `stroke="currentColor"` has no CSS context inside a standalone `QSvgRenderer`, so it
        # resolves to its initial value, BLACK.
        #
        # Measured by rendering through this very provider and averaging the visible pixels:
        #
        #     dark   window=#1E1E1E text=#E0E0E0  ink=rgb(0, 0, 0)
        #     light  window=#F2F3F5 text=#333333  ink=rgb(0, 0, 0)
        #
        # So the gear was pure black on BOTH themes: invisible against the dark window, and only
        # accidentally acceptable on the light one. That is the reported "not the inverse colour of
        # the theme".
        #
        # # The fix, in order of preference
        #
        # 1. `currentColor` is the icon author SAYING "use the current text colour", so replacing
        #    it is the most faithful reading and works for both `stroke` and `fill`.
        # 2. Otherwise inject `fill` only when the root declares no fill of its own, so a
        #    multi-colour icon keeps its colours instead of being flattened to one.
        #
        # The colour is `theme.text`, which IS the contrast colour: `#E0E0E0` on a `#1E1E1E`
        # window, `#333333` on a `#F2F3F5` one - light-on-dark and dark-on-light respectively.
        # 给随包 SVG 上主题的"对比色"，无论它是描边型还是填充型。
        #
        # # 本修复针对的缺陷（已实测）
        #
        # 提供器把 `fill` 属性注入到根 `<svg>` 元素上。这对"填充型"图标有效，而当 `setting.svg`
        # 变成 Lucide 的"描边型"图标后它就静默失效了：
        #
        #     <svg ... fill="none" stroke="currentColor" stroke-width="2" ...>
        #
        # 于是两件事同时出错：向已声明 `fill="none"` 的元素再注入 `fill` 会产生重复属性，而声明的
        # `none` 胜出；并且 `stroke="currentColor"` 在独立的 `QSvgRenderer` 里没有 CSS 上下文，
        # 会解析为其初始值——"黑色"。
        #
        # 通过本提供器渲染并平均可见像素后实测：
        #
        #     dark   window=#1E1E1E text=#E0E0E0  ink=rgb(0, 0, 0)
        #     light  window=#F2F3F5 text=#333333  ink=rgb(0, 0, 0)
        #
        # 因此齿轮在两个主题下都是纯黑：在深色窗口上不可见，在浅色窗口上只是碰巧能看。这正是用户
        # 报告的"不是当前主题的反向色"。
        #
        # # 修法，按优先级
        #
        # 1. `currentColor` 是图标作者在"说"用当前文字色，因此替换它是最忠实的解读，且对 `stroke`
        #    与 `fill` 都有效。
        # 2. 否则仅在根元素自身没有声明 fill 时注入 `fill`，使多色图标保留自己的颜色而不被压成单色。
        #
        # 颜色用 `theme.text`，它"就是"对比色：`#1E1E1E` 窗口上用 `#E0E0E0`、`#F2F3F5` 窗口上用
        # `#333333`——分别是深底浅字与浅底深字。
        colour = str(self._theme.text or "#FFFFFF")
        if "currentColor" in svg:
            return svg.replace("currentColor", colour)
        if "fill=" not in svg.split(">", 1)[0]:
            return svg.replace("<svg ", f'<svg fill="{colour}" ', 1)
        return svg

    def requestPixmap(self, image_id, size, requested_size):
        from PySide6.QtCore import QByteArray, Qt
        from PySide6.QtGui import QPainter, QPixmap
        from PySide6.QtSvg import QSvgRenderer

        side = max(1, int(requested_size.width() or 48))
        height = max(1, int(requested_size.height() or side))
        pixmap = QPixmap(side, height)
        pixmap.fill(Qt.GlobalColor.transparent)

        path = self._svg_path(image_id)
        if not path:
            return pixmap
        try:
            with open(path, "r", encoding="utf-8") as handle:
                svg = handle.read()
            svg = self._tint(svg)
            renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
        except Exception:
            log.exception("icon: rendering %s failed", path)
        return pixmap


class AppIconProvider(QQuickImageProvider):
    # The application icon, scaled to whatever size an `Image` asks for.
    #
    # `resources/icons/gifmanager.png` is the same artwork the window, the taskbar and the tray
    # use, but it is a 498 KB bitmap at one fixed size. Going through a provider lets the About
    # page ask for exactly the pixels it needs (72 px) instead of loading the full bitmap into
    # memory and letting Qt scale it, and it keeps the file's location out of the QML — QML can
    # only reach a file through a URL, and this application's resources directory is not
    # necessarily beside the QML.
    #
    # 应用图标，缩放到 `Image` 请求的任意尺寸。
    #
    # `resources/icons/gifmanager.png` 与窗口、任务栏和托盘用的是同一份图案，但它是一张固定尺寸的
    # 498 KB 位图。经提供器可以让关于页只请求它真正需要的像素（72px），而不是把整张位图加载进内存
    # 再让 Qt 缩放；同时它把文件位置挡在 QML 之外——QML 只能经 URL 到达文件，而本应用的资源目录未
    # 必与 QML 相邻。

    def __init__(self, parent=None):
        super().__init__(QQuickImageProvider.Image)

    def _png_path(self):
        import os

        from gifmanager.core import paths

        root = paths.resources_dir()
        if not root:
            return ""
        candidate = os.path.join(root, "icons", "gifmanager.png")
        return candidate if os.path.isfile(candidate) else ""

    def requestImage(self, image_id, size, requested_size):
        # Returns a `QImage` and reports the size through the out-parameter, which is Qt's
        # contract for an `Image`-type provider. Returning a tuple makes Qt treat every request
        # as a failure while a Python-side call unpacks it happily — the trap documented in
        # `animator.StickerFrameProvider`.
        # 返回 `QImage` 并经出参报告尺寸，这是 `Image` 型提供器的 Qt 契约。返回元组会让 Qt 把每次
        # 请求判为失败，而 Python 侧调用却能顺利解包——那个陷阱记录在
        # `animator.StickerFrameProvider` 中。
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage

        side = max(1, int(requested_size.width() or 72))
        height = max(1, int(requested_size.height() or side))
        path = self._png_path()
        if not path:
            return QImage()
        image = QImage(path)
        if image.isNull():
            return QImage()
        scaled = image.scaled(side, height, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        if size is not None:
            size.setWidth(scaled.width())
            size.setHeight(scaled.height())
        return scaled


class FocusTracker(QObject):
    # Remember the last foreground window that is not ours, ported from the
    # original project's FocusGuard: clicking a sticker must paste into the chat
    # window the user was typing in, and the manager never knows that window
    # except by watching. Read-only — it never moves focus itself, which is what
    # keeps it from fighting normal interaction inside the manager.
    # 记住最近一个不属于本进程的前台窗口，自原项目的 FocusGuard 移植：点击贴纸必须
    # 把表情粘贴进用户正在输入的聊天窗口，而除观察之外管理器无从得知那个窗口。只读
    # ——它自身绝不移动焦点，这正是它不干扰管理器内正常交互的原因。

    # Poll interval. Frequent enough to follow the chat window, cheap enough to
    # never disturb interaction.
    # 轮询间隔。足够频繁地跟随聊天窗口，又足够轻量不干扰交互。
    INTERVAL_MS = 300

    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self._bridge = bridge
        self._target = 0
        self._tick = None

    def start(self):
        from PySide6.QtCore import QTimer

        if self._tick is None:
            self._tick = QTimer(self)
            self._tick.timeout.connect(self._poll)
        self._tick.start(self.INTERVAL_MS)

    def stop(self):
        if self._tick is not None:
            self._tick.stop()

    def target(self):
        return self._target

    def _poll(self):
        input_backend = self._bridge._adapter.backend.input_backend()
        if not getattr(input_backend, "available", False):
            return
        try:
            foreground = int(input_backend.foreground_window() or 0)
        except Exception:
            return
        if not foreground or input_backend.owns_window(foreground):
            return
        self._target = foreground


__all__ = [
    "AppIconProvider",
    "FocusTracker",
    "GearIconProvider",
    "HotkeyService",
    "TrayService",
    "application_icon_path",
    "apply_application_icon",
    "platform_key",
    "tray_available",
]
