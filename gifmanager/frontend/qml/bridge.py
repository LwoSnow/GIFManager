"""The one object QML sees: `BackendBridge`.

QML reaches Python through context properties, and every one of them has to be a
`QObject` with properties and slots — a plain Python object's attributes are not
visible to the QML engine. This module is that boundary, and it is deliberately
the ONLY place that knows both worlds: the rest of the backend stays
toolkit-free, and the QML files never import Python.

# Why this replaces the Qt Widgets adapter

`frontend/qt/bridge.py` existed to re-emit backend callbacks as Qt signals so
widgets could connect to them, and to forward unknown attributes to the store so
ported widget code kept working. QML needs neither: it binds to properties and
calls slots, so this bridge exposes intent ("select this group", "copy this
sticker") rather than proxying an object graph.

QML 看到的唯一对象：`BackendBridge`。

QML 通过上下文属性访问 Python，而其中每一个都必须是带属性与槽的 `QObject`——普通
Python 对象的属性对 QML 引擎不可见。本模块就是这个边界，且刻意是唯一同时了解两个世界的
地方：后端其余部分保持与工具包无关，QML 文件也从不导入 Python。

# 为什么它取代了 Qt Widgets 适配器

`frontend/qt/bridge.py` 的存在是为了把后端回调重新以 Qt 信号发出以供控件连接，并把未知
属性转发给存储使移植来的控件代码继续工作。QML 两者都不需要：它绑定属性、调用槽，因此本
桥暴露的是"意图"（"选中该分组"、"复制这张贴纸"），而不是代理一张对象图。
"""
import logging

from PySide6.QtCore import Property, QObject, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication

from gifmanager import APP_NAME, __version__
from gifmanager.core import settings as schema
from gifmanager.frontend.qml.animator import StickerAnimator
from gifmanager.frontend.qml.importer import ImportService
from gifmanager.frontend.qml.models import GroupListModel, StickerListModel
from gifmanager.frontend.qml.services import HotkeyService, TrayService
from gifmanager.frontend.qml.settings_model import SettingsRowModel

log = logging.getLogger("GIFManager")

# Status message durations, in milliseconds. Named because the difference
# between "a copy succeeded" and "a copy failed" is how long the user needs.
# 状态消息的显示时长（毫秒）。命名是因为"复制成功"与"复制失败"需要的阅读时间不同。
STATUS_BRIEF_MS = 2000
STATUS_NORMAL_MS = 3200
STATUS_LONG_MS = 6000

# The project's home page. Declared once, here, because the About page shows it and clicking it
# opens it — two uses that must not be able to disagree.
# 项目主页。只在此声明一次，因为关于页显示它、点击它打开它——两种用途不允许产生分歧。
REPOSITORY_URL = "https://github.com/LwoSnow/GIFManager"

# Card scale bounds, mirroring the schema's clamps. Alt+wheel moves in steps of
# this fraction, exactly like the original project's grid.
# 卡片缩放边界，与 schema 的钳制一致。Alt+滚轮按该步进调整，与原项目的网格相同。
CARD_SCALE_STEP = 0.02

# QSettings identity for front-end session state (window geometry). The original
# project used the same organization/application pair, so a geometry saved by it
# is restored here rather than lost on migration.
# 前端会话状态（窗口几何）的 QSettings 标识。与原项目使用同一 organization/application
# 组合，因此原项目保存的几何在此被恢复，而不是在迁移中丢失。
SESSION_ORGANIZATION = "GIFManager"
SESSION_APPLICATION = "GIFManager"

# Longest text a sticker may hold.
#
# Bounded because a text sticker is drawn inside a card, not in a text view: a
# thousand-character entry would be unreadable there and would slow every card's
# layout. The limit is stated in the refusal message rather than the input silently
# truncating.
# 贴纸可容纳的最长文本。
#
# 设界限是因为文字贴纸绘制在卡片内而非文本视图里：一千字的条目在那里无法阅读，还会拖慢每张
# 卡片的布局。该上限在拒绝消息中说明，而不是让输入被静默截断。
MAX_TEXT_STICKER_CHARS = 200


def _group_error_key(error):
    # Map the store's `last_group_error` to a translation key.
    #
    # Matched against the store's own constants rather than against substrings of them.
    # The first version searched for words like "duplicate", which happens to work for
    # today's values and would break silently the moment one is reworded — and a silent
    # break here means a wrong message, not a crash, so nothing would catch it.
    # 与存储层自己的常量比较，而不是比较它们的子串。第一个版本搜索 "duplicate" 之类的词，
    # 这对今天的取值恰好可用，而一旦某个取值改写就会静默失效——而这里的静默失效意味着消息
    # 错误而不是崩溃，因此没有任何东西会抓到它。
    from gifmanager.core.store import groups as group_store

    if not error:
        return "group_rename_failed"
    mapping = {
        group_store.ERROR_DUPLICATE: "group_name_taken",
        group_store.ERROR_INVALID: "group_name_unusable",
        group_store.ERROR_DIR: "group_dir_locked",
        group_store.ERROR_MISSING: "group_missing",
    }
    return mapping.get(str(error).strip().lower(), "group_rename_failed")


class _HotkeyCaptureFilter(QObject):
    # The application-wide key sink used while the settings window is recording a shortcut.
    #
    # Lives at module level rather than inside `beginHotkeyCapture` so it is a stable class: a
    # filter
    # defined inside a method is a fresh type on every call, which makes it impossible to compare
    # and
    # therefore impossible to be sure `removeEventFilter` targets the same object that was
    # installed.
    # 设置窗口录制快捷键期间使用的应用级按键接收器。
    #
    # 放在模块级而不是 `beginHotkeyCapture` 内部，是为了得到一个稳定的类：在方法内定义的过滤器每次
    # 调用都是新类型，因而无法比较，也就无法保证 `removeEventFilter` 移除的是当初安装的那个对象。

    def __init__(self, bridge):
        super().__init__()
        self._bridge = bridge

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent

        if event.type() not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return False
        bridge = self._bridge
        if not bridge._hotkey_field:
            # Not armed: let everything through untouched.
            # 未处于待捕获：一切原样通过。
            return False
        try:
            if event.type() == QEvent.Type.KeyPress:
                return bridge._capture_hotkey_event(event)
            # While armed, key RELEASES are swallowed too. Otherwise the release of the very key
            # that
            # was just captured would reach whatever has focus and could activate a button.
            # 待捕获期间，按键"释放"也一并吞掉。否则刚被捕获的那个键的释放事件会到达持有焦点者，
            # 并可能激活某个按钮。
            return True
        except RuntimeError:
            # The bridge was destroyed while the filter was still installed (window closed during a
            # capture). Drop the filter rather than raising into Qt's event loop.
            # 过滤器仍在安装状态时桥被销毁（捕获期间关闭了窗口）。丢弃过滤器，而不是向 Qt 事件循环抛出。
            return False


class BackendBridge(QObject):
    # Application state exposed to QML: navigation, the current view's data, the
    # status line, and the commands a menu or a palette can invoke.
    # 暴露给 QML 的应用状态：导航、当前视图数据、状态行，以及菜单或命令面板可调用的命令。

    # Emitted with (message, timeout_ms). QML shows it in the status bar, so the
    # bridge does not need to know a status bar exists.
    # 发出 (消息, 超时毫秒)。QML 在状态栏显示它，因此本桥无需知道状态栏的存在。
    statusMessage = Signal(str, int)
    # Emitted after any change that affects the visible sticker list /
    # 任何影响可见贴纸列表的变更之后发出
    libraryChanged = Signal()
    # Emitted after a settings change, with the changed field names /
    # 设置变更后发出，带发生变化的字段名
    settingsChanged = Signal("QVariantList")
    # Emitted when the active language changed /
    # 当前语言变更时发出
    languageChanged = Signal(str)
    # Emitted with a message key QML should present in a dialog /
    # 发出一个消息键，QML 应将其呈现在对话框中
    dialogRequested = Signal(str, str, str)
    # Emitted when the active navigation entry changed. Declared here with the
    # other signals: a `Signal` assigned inside a method body would create an
    # attribute on the INSTANCE, which the QML engine never sees as a signal.
    # 导航项变更时发出。在此与其他信号一起声明：在方法体内赋值的 `Signal` 会在"实例"上
    # 创建属性，而 QML 引擎绝不会把它当作信号。
    viewChanged = Signal()
    # Emitted when the tray became available, which can change after `attach_window`
    # supplies an icon.
    # 托盘变为可用时发出；在 `attach_window` 提供图标之后这一点可能改变。
    trayChanged = Signal()
    # Re-emission of the sticker model's count changes, so properties derived from
    # the loaded rows (the masonry column count) have a notify signal that fires
    # on a group switch — `libraryChanged` does not fire there.
    # 转发贴纸模型的计数变更，使由已加载行导出的属性（瀑布流列数）拥有会在切换分组时
    # 触发的 notify 信号——`libraryChanged` 在那里不触发。
    stickerCountChanged = Signal()

    def __init__(self, adapter, theme, parent=None):
        super().__init__(parent)
        self._adapter = adapter
        self._theme = theme
        self.apply_theme_palette()
        self._view_index = 0
        self._keyword = ""
        self._status = ""
        # The QML root window (set by `attach_window`) and the focus tracker it
        # starts. Both back the auto-paste send path.
        # QML 根窗口（由 `attach_window` 设置）与它启动的焦点跟踪器。两者支撑自动
        # 粘贴发送路径。
        self._window = None
        self._focus_tracker = None
        # The Alt+wheel window filter, installed once with the root window.
        # 随根窗口安装一次的 Alt+滚轮过滤器。
        self._alt_wheel_filter = None
        # Hotkey capture state: the armed field name and the installed event filter.
        # 热键捕获状态：处于待捕获的字段名与已安装的事件过滤器。
        self._hotkey_field = ""
        self._hotkey_filter = None
        # Bumped on every language change; QML `trE` bindings read it as their
        # retranslation dependency.
        # 每次语言变更自增；QML 的 `trE` 绑定将其读取为重翻译依赖。
        self._language_epoch = 0
        # The viewport width the page reported (for text masonry packing) and the
        # per-column proxy cache built from it.
        # 页面报告的视口宽度（供文字瀑布流摊列）与由其构建的每列代理缓存。
        self._viewport_width = 0
        self._column_proxies = {}

        self._groups = GroupListModel(adapter.backend, self)
        self._stickers = StickerListModel(adapter.backend, self)
        self._stickers.countChanged.connect(self.stickerCountChanged)
        self._settings_model = SettingsRowModel(adapter, self)
        # The importer owns its worker thread and reports progress as properties, so
        # QML binds to it rather than watching for refreshes.
        # 导入器持有其工作线程并以属性报告进度，因此 QML 绑定到它而不是等待刷新。
        self._importer = ImportService(adapter.backend, self)
        self._importer.finished.connect(self._on_import_finished)
        # Refresh the list as each chunk lands, so a large import fills the grid
        # while it runs instead of appearing to do nothing until the end.
        # 每完成一块就刷新列表，使大批量导入在进行中就把网格填满，而不是看起来一直没动静直到
        # 结束。
        self._importer.chunkImported.connect(self._on_import_chunk)

        # The tray and the global hotkey are created WITHOUT a window: the tray needs
        # one only for its icon, and `attach_window` supplies it once the QML root
        # object exists. Both report `available`, so a session without a tray or a
        # platform without hotkey support simply leaves the corresponding QML surface
        # hidden.
        # 托盘与全局热键在"没有窗口"的情况下创建：托盘只为了图标才需要窗口，而
        # `attach_window` 会在 QML 根对象存在后提供它。两者都报告 `available`，因此在没有
        # 托盘的会话或没有热键支持的平台上，对应的 QML 界面会直接隐藏。
        self._tray = TrayService(parent=self)
        self._tray.toggleRequested.connect(self.toggleWindowRequested)
        self._tray.settingsRequested.connect(self.openSettingsRequested)
        self._tray.quitRequested.connect(self.quit)
        self._tray.copyRequested.connect(self.copySelectionRequested)
        self.hotkey = HotkeyService(adapter.backend, parent=self)
        self.hotkey.pressed.connect(self.toggleWindowRequested)

        # GIF playback. ONE animator for the whole interface, because a timer per card
        # would mean hundreds of timers for a full grid.
        #
        # It honours the EXISTING render-mode settings rather than adding new ones:
        # `gif_render_mode` already means "auto or a manual cap", and `gif_render_count`
        # already means how many, so playback obeys the switch the settings page already
        # shows instead of introducing a second, conflicting control.
        # GIF 播放。整个界面一个动画器，因为每卡片一个定时器意味着一屏网格有数百个定时器。
        #
        # 它遵循"已有"的渲染模式设置，而不是新增设置：`gif_render_mode` 已经表示"自动或手动
        # 上限"，`gif_render_count` 已经表示多少个，因此播放遵守设置页已经显示的那个开关，
        # 而不是引入第二个相互冲突的控件。
        self._animator = StickerAnimator(adapter.backend, parent=self)
        self._apply_animation_settings()

        # The updater. It schedules its own delayed first check, so nothing here has to
        # remember to start it.
        # 更新器。它自行安排延迟的首次检查，因此这里无需记得启动它。
        from gifmanager.frontend.qml.updates import UpdateService

        platform_key = ""
        try:
            from gifmanager import platform as platform_layer

            platform_key = platform_layer.current().key
        except Exception:
            log.exception("bridge: cannot resolve the platform key")
        self.updater = UpdateService(adapter.backend, platform_key, parent=self)
        self.updater.start()

        # The settings model applies edits itself, so a change it made must not be
        # announced a second time through the backend subscription.
        # 设置模型自行应用编辑，因此它做出的变更不得经后端订阅被第二次宣告。
        self._unsubscribe = adapter.backend.subscribe(self._on_backend_change)
        adapter.library_changed.connect(self._on_library_changed)
        adapter.language_changed.connect(self._on_language_changed)

        # Load the settings rows once, now, instead of relying on the page's
        # `Component.onCompleted` to do it. The page's handler races the parent's
        # assignment of the `app` property, and losing that race leaves the settings
        # list empty until the user navigates away and back — a bug that only shows
        # up in a freshly created window, which is exactly where a smoke test looks.
        #
        # 在此立即加载一次设置行，而不是依赖页面的 `Component.onCompleted`。页面的处理器
        # 与父级对 `app` 属性的赋值存在竞态，输掉竞态会让设置列表保持为空，直到用户切走再
        # 切回——这个缺陷只在新创建的窗口中显现，而那正是冒烟测试观察的地方。
        self._settings_model.load()

        self._restore_group()

    def detach(self):
        # Stop the import job and the platform services before anything else. The
        # import feeds the store, and closing the store under a running chunk would
        # fail inside a timer callback; the hotkey holds an OS registration that must
        # be released, or the combination stays taken after this process exits.
        # 在一切之前停掉导入任务与平台服务。导入在喂存储层，而在块运行中关闭存储层会在定时器
        # 回调里失败；热键持有必须释放的系统注册，否则该组合在本进程退出后仍被占用。
        importer = getattr(self, "importer", None)
        if importer is not None:
            importer.shutdown()
        for name in ("hotkey", "tray"):
            service = getattr(self, name, None)
            if service is not None:
                try:
                    service.shutdown()
                except Exception:
                    log.exception("bridge: %s shutdown failed", name)
        animator = getattr(self, "_animator", None)
        if animator is not None:
            animator.shutdown()
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    @Slot("QVariant")
    def attach_window(self, window):
        # Give the tray a window, for its icon and for the toggle.
        #
        # Called by the QML root once it exists, because a `QSystemTrayIcon` built
        # from the application's icon alone is invisible on some platforms and the
        # window's icon is the one that is actually set.
        # 把窗口交给托盘，用于其图标与切换。
        #
        # 由 QML 根对象在存在后调用，因为仅由应用图标构建的 `QSystemTrayIcon` 在某些平台上
        # 不可见，而窗口的图标才是真正被设置的那个。
        tray = getattr(self, "tray", None)
        if tray is None:
            return
        tray._window = window
        if not tray.available:
            # Rebuild now that an icon may be available. The first attempt reported
            # unavailable precisely because there was no window to take one from.
            # 既然可能已有可用图标就重建。第一次尝试报告不可用，正是因为没有窗口可以取图标。
            tray._setup()
        tray.setTitle(self.tr("app_name") if hasattr(self, "tr") else "GIFManager")
        self._window = window
        self._install_alt_wheel_filter(window)
        self._start_focus_tracker()
        self.trayChanged.emit()

    def _install_alt_wheel_filter(self, window):
        # Alt + wheel scales the cards, like the original grid's wheelEvent. It is
        # a WINDOW event filter rather than a QML WheelHandler because a handler
        # on a Flickable never saw a wheel event in practice; the filter sees
        # every wheel before the scene routes it, accepts only the Alt-modified
        # ones, and leaves ordinary scrolling untouched.
        # Alt + 滚轮缩放卡片，对应原版网格的 wheelEvent。用"窗口事件过滤器"而非 QML
        # 的 WheelHandler：实测 Flickable 上的处理器收不到滚轮事件；过滤器在场景路由
        # 之前看到每一次滚轮，只接受带 Alt 的，普通滚动不受影响。
        if window is None or self._alt_wheel_filter is not None:
            return
        from PySide6.QtCore import QEvent, QObject, Qt

        bridge = self

        class _Filter(QObject):
            def eventFilter(self, obj, event):
                if event.type() != QEvent.Type.Wheel:
                    return False
                # 只认本窗口的滚轮（设置窗口自己的滚轮不归网格管）。接收者可能是项
                # （有 window()）或窗口本身（window() 是场景根，不在本集内——用
                # `is not None` 兜底）。
                # Only wheels for OUR window. The receiver may be an item (which
                # has window()) or the window itself.
                receiver_window = getattr(obj, "window", None)
                if receiver_window is not None:
                    try:
                        owner = receiver_window()
                        if owner is not None and owner is not bridge._window:
                            return False
                    except RuntimeError:
                        return False
                # Ctrl OR Alt. `Ctrl` first, because that is the gesture people try: the report was
                # "按住 ctrl+滚轮可以调节卡片大小未生效", and the filter only accepted `AltModifier`,
                # so Ctrl returned False and the wheel went to the grid as an ordinary scroll.
                #
                # Alt is kept because it was the documented gesture before this; accepting both
                # costs
                # nothing and means the feature cannot silently die for a user who learned either
                # one.
                # Ctrl "或" Alt。优先 Ctrl，因为那是人们会先试的手势：用户报告"按住 ctrl+滚轮可以调节
                # 卡片大小未生效"，而过滤器只接受 `AltModifier`，于是 Ctrl 会返回 False、滚轮作为普通
                # 滚动交给网格。保留 Alt 是因为它此前是文档里的手势；两者都接受没有代价，且意味着学会了
                # 任一种的用户都不会遇到功能静默失效。
                modifiers = event.modifiers()
                if not (modifiers & Qt.ControlModifier) and not (modifiers & Qt.AltModifier):
                    return False
                delta = event.angleDelta().y()
                if delta:
                    bridge.adjustCardScale(1 if delta > 0 else -1)
                event.accept()
                return True

        self._alt_wheel_filter = _Filter(window)
        # Application-level, not window-level: Qt delivers wheel events to the
        # ITEM under the cursor, so a filter on the window never sees them. The
        # filter checks the receiver's window instead.
        # 装在应用级而非窗口级：Qt 把滚轮事件投递给光标下的"项"，窗口上的过滤器永远
        # 看不到；过滤器改为核对接收者所属的窗口。
        from PySide6.QtCore import QCoreApplication

        application = QCoreApplication.instance()
        if application is not None:
            application.installEventFilter(self._alt_wheel_filter)

    def apply_theme_palette(self):
        # Push the theme's colours into the Qt application PALETTE.
        #
        # # Why a palette when every control is already styled in QML
        #
        # Two kinds of control are drawn by `QtQuick.Controls.Basic` itself and cannot be styled
        # without replacing the whole style: `ToolTip` (only reachable through attached properties,
        # which offer no way to swap its background) and anything else created internally, such as
        # the popups of a `Dialog`. Both read `QPalette`, so setting the application palette is the
        # only lever that reaches them.
        #
        # The reported symptom was a tooltip with a WHITE border and black-looking text that matched
        # neither theme: the controls fell back to the default palette, whose `Light`/`Mid` roles
        # are
        # near-white.
        #
        # `ToolTipBase`/`ToolTipText` are set explicitly because those are the roles Basic's tooltip
        # actually reads; setting only the generic roles left its border untinted.
        #
        # 把主题颜色推入 Qt 的"应用调色板"。
        #
        # # 既然所有控件都在 QML 里着色了，为什么还要调色板
        #
        # 有两类控件由 `QtQuick.Controls.Basic` 自身绘制、且不替换整个样式就无法着色：`ToolTip`
        #（只能通过附加属性触达，而附加属性没有替换其背景的入口）以及内部创建的部件，例如 `Dialog` 的
        # 弹出层。两者都读 `QPalette`，因此设置应用调色板是唯一能触达它们的杠杆。
        #
        # 用户报告的症状是提示框有"白色边框"、文字发黑，与两套主题都不匹配：控件回退到了默认调色板，
        # 而它的 `Light`/`Mid` 角色接近白色。
        #
        # 显式设置 `ToolTipBase`/`ToolTipText`，因为那才是 Basic 的提示框真正读取的角色；只设通用角色
        # 会留下一条未着色的边框。
        try:
            from PySide6.QtGui import QColor, QGuiApplication, QPalette

            app = QGuiApplication.instance()
            if app is None:
                return
            theme = getattr(self, "_theme", None)
            if theme is None:
                return
            colours = theme.uiColors
            window = QColor(theme.window)
            surface = QColor(theme.surface)
            text = QColor(theme.text)
            muted = QColor(theme.textMuted)
            border = QColor(colours.get("borderStrong", theme.border))
            border_soft = QColor(colours.get("border", theme.border))
            accent = QColor(colours.get("selected", theme.accent))
            accent_text = QColor(colours.get("selectedForeground", theme.accentText))

            palette = QPalette()
            for role, colour in (
                (QPalette.ColorRole.Window, window),
                (QPalette.ColorRole.Button, surface),
                (QPalette.ColorRole.Base, surface),
                (QPalette.ColorRole.AlternateBase, QColor(theme.surfaceAlt)),
                (QPalette.ColorRole.WindowText, text),
                (QPalette.ColorRole.ButtonText, text),
                (QPalette.ColorRole.Text, text),
                (QPalette.ColorRole.PlaceholderText, muted),
                (QPalette.ColorRole.ToolTipBase, surface),
                (QPalette.ColorRole.ToolTipText, text),
                (QPalette.ColorRole.Highlight, accent),
                (QPalette.ColorRole.HighlightedText, accent_text),
                (QPalette.ColorRole.Light, border_soft),
                (QPalette.ColorRole.Midlight, border_soft),
                (QPalette.ColorRole.Mid, border),
                (QPalette.ColorRole.Dark, border),
                (QPalette.ColorRole.Shadow, border),
            ):
                palette.setColor(role, colour)
            app.setPalette(palette)
            log.debug("theme: application palette applied")
        except Exception:
            log.exception("theme: applying the application palette failed")

    @Slot("QVariant")
    def applyWindowEffects(self, window):
        # Platform window dressing: DWM rounded corners on Windows. The original
        # project applied this from `showEvent`; here the QML root calls it once the
        # window exists. A platform without the service is a no-op, not an error.
        # 平台窗口修饰：Windows 上的 DWM 圆角。原项目在 `showEvent` 中应用；这里由 QML
        # 根对象在窗口存在后调用。没有该服务的平台是空操作，不是错误。
        if window is None:
            return
        try:
            from gifmanager import platform as platform_layer

            service = platform_layer.window()
            window_id = int(window.winId())
            if window_id:
                service.apply_rounded_corners(window_id)
        except Exception:
            log.exception("bridge: apply window effects failed")

    # ---- window geometry / 窗口几何 --------------------------------------
    #
    # Front-end session state: it lives in QSettings, not in the settings schema,
    # because the schema is user preference while a geometry is a per-session
    # fact. The original project used the same QSettings identity, so its saved
    # geometry is honoured.
    # 前端会话状态：存于 QSettings 而非设置 schema，因为 schema 是用户偏好而几何是
    # 会话事实。原项目使用同一 QSettings 标识，因此它保存的几何会被尊重。

    @Slot(result="QVariantMap")
    def loadWindowGeometry(self):
        from PySide6.QtCore import QSettings

        settings = QSettings(SESSION_ORGANIZATION, SESSION_APPLICATION)
        geometry = settings.value("window_geometry_qml", {})
        if not isinstance(geometry, dict):
            return {}
        return geometry

    @Slot("QVariantMap")
    def saveWindowGeometry(self, geometry):
        from PySide6.QtCore import QSettings

        settings = QSettings(SESSION_ORGANIZATION, SESSION_APPLICATION)
        settings.setValue("window_geometry_qml", dict(geometry or {}))

    @Property(bool, notify=settingsChanged)
    def alwaysOnTop(self):
        # The window-stays-on-top state, live: the shell watches this property's
        # notify and re-applies its flags the moment the row changes, so the
        # toggle acts on the running window rather than the next launch.
        # 窗口置顶状态，实时生效：外壳监视此属性的 notify，行变更即刻重设标志，
        # 开关作用于运行中的窗口而非下次启动。
        return bool(getattr(self._adapter.settings, "always_on_top", False))

    # ---- focus tracking for auto-paste / 自动粘贴的焦点跟踪 ---------------

    def _start_focus_tracker(self):
        # Poll the foreground window and remember the last one that is NOT ours.
        # Ported from the original project's FocusGuard: a click on a sticker must
        # paste into the chat window the user was typing in, which means handing
        # focus back to it once, on send.
        # 轮询前台窗口并记住最近一个"不属于本进程"的窗口。自原项目的 FocusGuard 移植：
        # 点击贴纸必须把表情粘贴进用户正在输入的聊天窗口，这要求发送时一次性把焦点
        # 还给它。
        if self._focus_tracker is not None or not self.canAutoSend():
            return
        from gifmanager.frontend.qml.services import FocusTracker

        self._focus_tracker = FocusTracker(self, parent=self)
        self._focus_tracker.start()

    @Slot(result=bool)
    def canAutoSend(self):
        return bool(self._adapter.backend.can_auto_send())

    def _focus_target(self):
        # The remembered chat window, or 0 when none was seen yet.
        # 被记住的聊天窗口；尚未观测到时为 0。
        if self._focus_tracker is None:
            return 0
        return self._focus_tracker.target()

    def _paste_into_chat(self):
        # Deliver Ctrl+V to the remembered chat window, bringing it forward once.
        # Falls back to a foreground paste when no target was ever seen. Returns
        # the delivery result map from the backend.
        # 向被记住的聊天窗口投递 Ctrl+V，先把它带回前台一次。从未观测到目标时回退为
        # 向前台粘贴。返回后端的投递结果映射。
        target = self._focus_target()
        manager = 0
        if self._window is not None:
            try:
                manager = int(self._window.winId())
            except Exception:
                manager = 0
        if target and target != manager:
            input_backend = self._adapter.backend.input_backend()
            if getattr(input_backend, "available", False):
                input_backend.bring_to_front(target)
        return self._adapter.backend.auto_send_after(60)


    @Slot(result=bool)
    def trayAvailable(self):
        tray = getattr(self, "tray", None)
        return bool(tray is not None and tray.available)

    @Slot(result=str)
    def trayUnavailableReason(self):
        tray = getattr(self, "tray", None)
        return "" if tray is None else tray.unavailableReason

    @Slot(result=bool)
    def hotkeyAvailable(self):
        hotkey = getattr(self, "hotkey", None)
        return bool(hotkey is not None and hotkey.available)

    @Slot(result=bool)
    def hotkeyRegistered(self):
        hotkey = getattr(self, "hotkey", None)
        return bool(hotkey is not None and hotkey.registered)

    @Slot(result=str)
    def hotkeyReason(self):
        hotkey = getattr(self, "hotkey", None)
        return "" if hotkey is None else hotkey.reason

    @Slot(result=bool)
    def reapplyHotkey(self):
        # Re-register after the hotkey setting changed.
        #
        # Called from the settings path rather than read on every change, because
        # registration touches the operating system and a failed registration must be
        # reportable.
        # 热键设置变更后重新注册。
        #
        # 从设置路径调用而不是在每次变更时读取，因为注册会触碰操作系统，而失败的注册必须可被
        # 报告。
        hotkey = getattr(self, "hotkey", None)
        if hotkey is None:
            return False
        ok = hotkey.reload()
        if not ok and hotkey.available and hotkey.sequence:
            self._emit_status(
                self._t("hotkey_register_failed", sequence=hotkey.sequence,
                        reason=hotkey.reason),
                STATUS_LONG_MS)
        elif ok:
            self._emit_status(
                self._t("hotkey_registered", sequence=hotkey.sequence),
                STATUS_BRIEF_MS)
        return ok

    # ---- backend notifications / 后端通知 --------------------------------

    # ---- window and tray plumbing / 窗口与托盘接线 -----------------------
    #
    # These are what the tray and the global hotkey ask for. Emitting a signal rather
    # than reaching into the window keeps this bridge free of any knowledge about the
    # QML scene — the same reason the shell gets a `View` protocol instead of the
    # window.
    # 这些是托盘与全局热键所请求的动作。发出信号而不是伸手进窗口，使本桥不持有任何关于 QML
    # 场景的知识——与外壳得到 `View` 协议而非窗口本身是同一个理由。
    toggleWindowRequested = Signal()
    # Separate from the toggle, because a compositor key binding that says "show" must
    # work while the window is already visible; a toggle would hide it instead.
    # 与切换分开，因为一条写着"显示"的合成器键绑定必须在窗口已可见时也有效；切换会改为隐藏它。
    showWindowRequested = Signal()
    hideWindowRequested = Signal()
    openSettingsRequested = Signal()

    # Hotkey capture, for the settings window's shortcut field.
    #
    # `hotkeyCaptured(field, text)` carries the STORED value so the field can display exactly what
    # was
    # recorded instead of re-deriving it; `hotkeyCaptureEnded` lets the field drop its armed styling
    # whether the capture succeeded, was cancelled with Escape, or ended because the window was
    # closed
    # mid-capture.
    # 热键捕获，供设置窗口的快捷键字段使用。
    #
    # `hotkeyCaptured(field, text)` 携带"已存储"的值，使字段显示实际记录的内容而不是重新推导；
    # `hotkeyCaptureEnded` 让字段撤掉"已就绪"样式——无论捕获成功、被 Escape 取消，还是因为窗口在
    # 捕获中途关闭而结束。
    hotkeyCaptured = Signal(str, str)
    hotkeyCaptureEnded = Signal()

    @Slot()
    def copySelectionRequested(self):
        # The tray's "copy" entry.
        #
        # It copies the FIRST selected sticker, or the first in the visible list when
        # nothing is selected. Falling back to the list rather than doing nothing is
        # deliberate: the tray is used while the window is hidden, so "nothing is
        # selected" is the normal state, and a menu entry that silently does nothing
        # is worse than one that copies the obvious candidate.
        # 托盘的"复制"条目。
        #
        # 它复制第一个被选中的贴纸；没有选中项时复制可见列表的第一张。回退到列表而不是什么都不做
        # 是刻意的：托盘是在窗口隐藏时使用的，因此"没有选中项"是常态，而一个静默无效的菜单条目
        # 比一个复制显而易见的候选者更糟。
        ids = self._stickers.selectedIds()
        if not ids:
            index = self._stickers.index(0, 0)
            if not index.isValid():
                self._emit_status(self.tr("nothing_to_copy"), STATUS_NORMAL_MS)
                return
            ids = [self._stickers.data(index, self._stickers.IdRole)]
        self.copySticker(int(ids[0]))

    def _on_backend_change(self, kind, payload):
        # Runs on whichever thread mutated the backend. QML must not be touched
        # from a worker thread, so the signal is emitted and Qt queues it to the
        # thread the bridge lives on.
        # 在改动后端的那个线程上运行。绝不可从工作线程触碰 QML，因此这里发出信号，由 Qt
        # 把它排队到本桥所在的线程。
        if kind == "library":
            self.libraryChanged.emit()
        elif kind == "settings":
            fields = list(payload or ())
            self.settingsChanged.emit(fields)
            # Side effects that used to need a restart, applied the moment the
            # committed settings carry them:
            # 曾需重启才生效的副作用，在提交的设置携带它们的那一刻应用：
            if "theme" in fields:
                # Read the theme from the ADAPTER, not from the bridge's captured settings object.
                #
                # `Backend.apply_settings` REPLACES `self.settings` with a new `AppSettings` built
                # from the merged mapping. `ThemeBridge` was constructed with `adapter.settings`,
                # i.e.
                # the instance that existed at startup, so `refresh()` kept reading the OLD object
                # and
                # saw the old theme - the settings window's 外观 switch therefore appeared to do
                # nothing at all, and only a restart applied it.
                #
                # `set_theme` with the CURRENT value is the fix: it is the same call `run_with`
                # makes
                # at startup, so the two paths cannot diverge again.
                # 从"适配器"读取主题，而不是从本桥构造时捕获的设置对象。
                #
                # `Backend.apply_settings` 会用由合并映射构建的"新" `AppSettings` 替换
                # `self.settings`。而 `ThemeBridge` 是用 `adapter.settings`（也就是启动时存在的那个
                # 实例）构造的，因此 `refresh()` 一直在读"旧"对象、看到旧主题——设置窗口的"外观"
                # 开关看起来毫无作用，只有重启才生效。
                #
                # 用"当前"值调用 `set_theme` 就是修复：它与 `run_with` 在启动时做的是同一个调用，
                # 因此两条路径不会再分叉。
                self._theme.set_theme(self._adapter.settings.theme)
                # The palette must follow the theme, or Basic-drawn controls
                # (tooltips, dialog internals) keep the previous one.
                # 调色板必须跟随主题，否则 Basic 绘制的控件（提示框、对话框内部件）
                # 会保留上一套。
                self.apply_theme_palette()
            if "hotkey" in fields:
                # Re-register the global shortcut the moment it is committed.
                #
                # `reapplyHotkey` existed but NOTHING called it, so a changed shortcut was written
                # to
                # the settings file and then ignored for the rest of the session: the old key kept
                # working (it was still the one registered) and the new one never did, which reads
                # as
                # "changing the hotkey has no effect". Applying it here is the missing link.
                # 在提交的那一刻重新注册全局快捷键。
                #
                # `reapplyHotkey` 存在，却"没有任何地方"调用它，因此改动后的快捷键被写进设置文件后在本
                # 次会话里被忽略：旧键继续有效（注册的仍是它），新键永不生效，读起来就是"改快捷键没用"。
                # 在此应用它就是缺失的那一环。
                self.reapplyHotkey()
            if "language" in fields:
                self._adapter.set_language(self._adapter.settings.language)
            # `_apply_animation_settings` pushes the render-mode cap into the animator.
            #
            # It was called ONLY from `__init__`, so `gif_render_mode` and
            # `gif_render_count` were read once at startup and never again: the animator kept
            # the cap it was born with, and the settings page's "同时渲染表情数" control
            # therefore had no effect at all — including a value of 0, which is supposed to
            # turn every animation into a still.
            #
            # Applied on ANY settings change rather than only when those two fields are named,
            # because the field list is assembled by a different layer and a missed name would
            # silently restore this bug. The call is cheap: it reads two values and assigns
            # two attributes.
            # `_apply_animation_settings` 把渲染模式上限推入动画器。
            #
            # 它"只"在 `__init__` 中被调用，因此 `gif_render_mode` 与 `gif_render_count` 在启动时
            # 被读取一次、之后再也不读：动画器一直持有它出生时那个上限，于是设置页的"同时渲染表情数"
            # 控件完全无效——包括取值为 0 的情况，那本应把所有动画变成静态图。
            #
            # 在"任何"设置变更时应用，而不是只在点名那两个字段时，因为字段列表由另一个层组装，
            # 漏掉一个名字会静默恢复这个缺陷。该调用很廉价：读两个取值、赋两个属性。
            self._apply_animation_settings()
        elif kind == "language":
            self._apply_language_change(str(payload or ""))

    def _on_library_changed(self):
        self._groups.reload()
        self._reload_stickers()

    def _on_import_chunk(self, _count):
        # Reload after each chunk, but only the group COUNTS and the visible list.
        #
        # `groups.reload()` rebuilds every row, which is cheap (tens of rows) and is
        # what makes a group's badge count climb during the import.
        # 每块之后重新加载，但只重载分组"计数"与可见列表。
        #
        # `groups.reload()` 会重建每一行，代价很低（几十行），而它正是让分组角标在导入过程中
        # 递增的原因。
        self._groups.reload()
        self._reload_stickers()

    def _on_import_finished(self, report):
        # Report the outcome through the status line, then reload.
        #
        # The reload is what makes the new stickers appear: an import mutates the
        # store without going through the bridge, so nothing else would notice.
        # 把结果经状态行报告，然后重新加载。
        #
        # 重新加载才是让新贴纸出现的原因：导入直接改动存储层而不经过桥，因此没有别的机制会
        # 注意到它。
        self._groups.reload()
        self._reload_stickers()
        parts = []
        if report.get("imported"):
            parts.append(self._t("import_imported", count=report["imported"]))
        if report.get("skipped"):
            parts.append(self._t("import_skipped", count=report["skipped"]))
        if report.get("rejected"):
            parts.append(self._t("import_rejected", count=report["rejected"]))
        if report.get("cancelled"):
            parts.append(self.tr("import_cancelled"))
        for error in report.get("errors", ()):
            parts.append(error)
        message = self.tr("import_nothing_new") if not parts else "; ".join(parts)
        self._emit_status(message, STATUS_LONG_MS)

    def _on_language_changed(self, code):
        self._apply_language_change(code)

    def _apply_language_change(self, code):
        # One language change retranslates EVERYTHING bound through the epoch:
        # the settings model's labels, the navigation titles, the group bar's
        # builtin names, the status line, and every `trE` binding in QML.
        # 一次语言变更重翻译所有经 epoch 绑定的内容：设置模型标签、导航标题、分组栏
        # 的内置名、状态行，以及 QML 中每个 `trE` 绑定。
        self._language_epoch += 1
        self._settings_model.retranslate()
        self._groups.reload()
        self._emit_status(self._compose_status(), 0)
        self.viewChanged.emit()
        self.languageChanged.emit(code)

    @Property(int, notify=languageChanged)
    def languageEpoch(self):
        # A counter QML `trE` bindings pass back as their second argument: reading
        # it inside a binding makes the binding depend on `languageChanged`, which
        # is what retranslates every static label the moment the language flips.
        # QML 的 `trE` 绑定把它作为第二实参回传：在绑定内读取它使该绑定依赖
        # `languageChanged`——这正是语言翻转时每个静态标签立即重翻译的机制。
        return self._language_epoch

    @Slot(str, int, result=str)
    def trE(self, key, epoch):
        # `tr` with a language-epoch argument. The epoch is ignored; its READ is
        # the retranslation dependency.
        # 带语言纪元参数的 `tr`。纪元被忽略；对它的"读取"才是重翻译依赖。
        return self._adapter.tr(key)

    @Slot(str, str, int, result=str)
    def trArgsE(self, key, arguments, epoch):
        # `trArgs` with a language-epoch argument, same mechanism.
        # 带语言纪元参数的 `trArgs`，同一机制。
        import json

        try:
            kwargs = json.loads(arguments) if arguments else {}
        except (TypeError, ValueError):
            kwargs = {}
        if not isinstance(kwargs, dict):
            kwargs = {}
        try:
            return self._adapter.tr(key, **kwargs)
        except Exception:
            return self._adapter.tr(key)

    # ---- navigation / 导航 -----------------------------------------------

    # The views, in navigation order. Titles are translation keys, resolved in
    # `viewTitles` so a language change re-evaluates them.
    # 视图，按导航顺序。标题是翻译键，在 `viewTitles` 中解析，使语言变更能重新求值。
    VIEW_IDS = ("library", "settings", "about")

    @Property(int, notify=libraryChanged)
    def viewIndex(self):
        return self._view_index

    @Slot(int)
    def setViewIndex(self, index):
        index = max(0, min(int(index), len(self.VIEW_IDS) - 1))
        if index == self._view_index:
            return
        self._view_index = index
        # The settings page re-reads the stored values on entry, so an edit made
        # elsewhere is visible without a manual reload.
        # 设置页在进入时重读已存储的取值，因此在别处做的编辑无需手动重载即可见。
        if self.VIEW_IDS[index] == "settings":
            self._settings_model.load()
        self.viewChanged.emit()

    @Property("QStringList", notify=viewChanged)
    def viewIds(self):
        return list(self.VIEW_IDS)

    @Property("QStringList", notify=viewChanged)
    def viewTitles(self):
        return [self.tr(key) for key in ("all_group", "settings", "about")]

    @Property(str, notify=viewChanged)
    def currentView(self):
        return self.VIEW_IDS[self._view_index]

    # ---- models QML binds to / QML 绑定的模型 ----------------------------
    #
    # These were plain instance attributes assigned in `__init__`, which Python code can
    # read but QML CANNOT use as a model: the engine receives an opaque PyObject rather
    # than a `QAbstractItemModel`, so a `GridView { model: page.app.stickers }` bound to
    # nothing. The visible symptom was an EMPTY library — `model` was `None`, `count` was
    # 0, no delegate was ever created, and Qt reported not one warning, because from the
    # engine's point of view a null model is simply a model with no rows.
    #
    # `Property` with `constant=True` is right here: the model OBJECT never changes, only
    # its contents, and those announce themselves through the model's own signals. That is
    # the opposite of `viewIndex` above, which must NOT be writable from QML.
    #
    # 这些原本是在 `__init__` 中赋值的普通实例属性，Python 代码能读，但 QML "无法"把它当模型
    # 使用：引擎收到的是一个不透明的 PyObject 而不是 `QAbstractItemModel`，因此
    # `GridView { model: page.app.stickers }` 绑定到了空。可见症状是"素材库为空"——`model`
    # 为 `None`、`count` 为 0、从未创建任何委托，而 Qt 一条警告都没有，因为在引擎看来空模型就是
    # 没有行的模型。
    #
    # 这里用带 `constant=True` 的 `Property` 是正确的：模型"对象"永不变，变的只是内容，而内容
    # 通过模型自身的信号宣告自己。这与上面的 `viewIndex` 正好相反，后者绝不允许从 QML 写入。

    @Property(QObject, constant=True)
    def stickers(self):
        return self._stickers

    @Property(QObject, constant=True)
    def groups(self):
        return self._groups

    @Property(QObject, constant=True)
    def settings(self):
        return self._settings_model

    @Property(QObject, constant=True)
    def importer(self):
        return self._importer

    @Property(QObject, constant=True)
    def tray(self):
        return self._tray

    @Property(QObject, constant=True)
    def animator(self):
        # GIF 播放器必须以 Qt 属性暴露：普通属性对 QML 是不透明的 PyObject（与当年
        # `stickers` 的陷阱相同）。
        # The animator must be a Qt property: a plain attribute is an opaque
        # PyObject to QML (the same trap `stickers` once had).
        return self._animator

    # ---- stickers / 贴纸 -------------------------------------------------

    @Property(str, notify=libraryChanged)
    def keyword(self):
        return self._keyword

    @Slot(str)
    def setKeyword(self, text):
        text = (text or "").strip()
        if text == self._keyword:
            return
        self._keyword = text
        self._reload_stickers()

    def _reload_stickers(self):
        group_id = self._groups.currentId
        # A text group owns a column layout, and entering one assigns columns to
        # the cards the packer has not placed yet — the same thing the original
        # grid did in `assign_unassigned_columns` before its reload.
        # 文字分组拥有列布局，进入时给摊列器尚未放置的卡片分列——与原网格在重载前的
        # `assign_unassigned_columns` 相同。
        self._pack_text_columns()
        self._stickers.load(group_id, self._keyword)
        self._emit_status(self._compose_status())

    def _compose_status(self):
        # Built here rather than in QML because it needs translated strings with
        # placeholders, and QML string formatting of translated text is exactly
        # where a translator's placeholders get lost.
        # 在此构建而非在 QML 里，因为它需要带占位符的已翻译字符串，而 QML 对已翻译文本的
        # 字符串格式化恰恰是译者占位符容易丢失的地方。
        group_id = self._groups.currentId
        if group_id < 0:
            scope = self.tr("all_group")
        else:
            scope = self.groupDisplayName(group_id) or self.tr("all_group")
        stats = self._adapter.backend.stats(
            None if group_id < 0 else group_id, self._keyword)
        if self._keyword:
            return self._t("search_result", group=scope,
                           keyword=self._keyword, count=stats["total"])
        return self._t("emoji_count", group=scope, count=stats["total"],
                       total=stats["all_total"])

    @Slot(int, result=str)
    def groupDisplayName(self, group_id):
        # A group's name as the INTERFACE should show it: the built-in groups
        # (All, Default) follow the language, a user's own group keeps the name
        # the user typed. The store keeps stable names; only the display is
        # translated, so remembering/restoring a group still works across a
        # language change.
        # 界面应显示的分组名：内置分组（全部/默认）跟随语言，用户自建分组保持用户输入的
        # 名字。存储层保留稳定的名字，只翻译显示——因此跨语言变更记忆/恢复分组仍然有效。
        name = self._groups.nameOf(group_id) or ""
        group = self._adapter.store.get_group(group_id)
        if group is None or not group.get("is_builtin"):
            return name
        all_id = self._adapter.backend.store._all_group_id()
        key = "all_group" if group_id == all_id else "default_group"
        translated = self._adapter.tr(key)
        return translated or name

    @Slot(int)
    def selectGroup(self, group_id):
        self._groups.select(group_id)
        self._reload_stickers()
        if self._adapter.settings.remember_group:
            name = "" if group_id < 0 else self._groups.nameOf(group_id)
            self._adapter.save_session(last_group_name=name)

    def _restore_group(self):
        if not self._adapter.settings.remember_group:
            self._groups.select(-1)
        else:
            self._groups.selectByName(self._adapter.settings.last_group_name
                                     or "")
        self._reload_stickers()

    # ---- group management / 分组管理 --------------------------------------
    #
    # The store has had `create_group`/`rename_group`/`delete_group` all along; what
    # was missing was an interface. Each operation returns a RESULT DICTIONARY rather
    # than a bare boolean, because the three failure modes a user can cause — an empty
    # name, a duplicate name, and a name the filesystem rejects — need three different
    # messages, and a boolean would collapse them into "it did not work".
    # 存储层一直有 `create_group`/`rename_group`/`delete_group`；缺的是界面。每个操作返回
    # "结果字典"而非裸布尔，因为用户能造成的三种失败——空名称、重复名称、文件系统拒绝的名称
    # ——需要三条不同消息，而布尔会把它们压成"没成功"。

    @Slot(str, str, result="QVariantMap")
    def createGroup(self, name, group_type):
        name = (name or "").strip()
        kind = str(group_type or "").strip().lower()
        if kind not in ("image", "text"):
            kind = "image"
        if not name:
            return self._group_result(False, "group_name_empty")
        existing = self._adapter.backend.store.get_group_by_name(name)
        if existing is not None:
            return self._group_result(False, "group_name_taken", existing)
        created = self._adapter.backend.store.create_group(name, kind)
        if created is None:
            # The store refuses a name whose FOLDER is already taken by another group,
            # which is a different problem from a duplicate row and is the case that
            # would otherwise leave two groups sharing one directory.
            # 存储层会拒绝"目录已被另一个分组占用"的名称，这与行重复是不同的问 题，也正是否则
            # 会让两个分组共用一个目录的情形。
            return self._group_result(False, "group_name_unusable")
        self._on_library_changed()
        self._adapter.notify_library_changed()
        return self._group_result(True, "group_created", {"name": name, "id": created})

    @Slot(int, str, result="QVariantMap")
    def renameGroup(self, group_id, new_name):
        new_name = (new_name or "").strip()
        group = self._adapter.backend.store.get_group(group_id)
        if group is None:
            return self._group_result(False, "group_missing")
        if not new_name or new_name == group["name"]:
            return self._group_result(False, "group_name_unchanged", group)
        if group["is_builtin"]:
            # A builtin group's name is the one the schema's roles resolve to, so
            # renaming it would break `ensure_builtin_groups` on the next open.
            # 内置分组的名称是 schema 角色所解析到的那个，重命名它会让下次打开时的
            # `ensure_builtin_groups` 失效。
            return self._group_result(False, "group_builtin_locked", group)
        if not self._adapter.backend.store.rename_group(group_id, new_name):
            error = self._adapter.backend.store.last_group_error
            return self._group_result(False, _group_error_key(error), group)
        self._on_library_changed()
        self._adapter.notify_library_changed()
        return self._group_result(True, "group_renamed",
                                 {"name": new_name, "id": group_id})

    @Slot(int, result="QVariantMap")
    def deleteGroup(self, group_id):
        group = self._adapter.backend.store.get_group(group_id)
        if group is None:
            return self._group_result(False, "group_missing")
        if group["is_builtin"]:
            return self._group_result(False, "group_builtin_locked", group)
        # How many stickers go with it, so the confirmation can say so. A user
        # deleting a group with 200 stickers deserves to know before, not after.
        # 会一并删除多少贴纸，使确认对话框能说明。删除含 200 张贴纸的分组的用户有权在"之前"
        # 知道，而不是之后。
        count = self._adapter.backend.store.count_emojis_in_group(group_id)
        was_current = self._groups.currentId == group_id
        if not self._adapter.backend.store.delete_group(group_id):
            return self._group_result(False, "group_delete_failed", group)
        self._on_library_changed()
        self._adapter.notify_library_changed()
        if was_current:
            # Leaving the deleted group selected would show an empty grid for a group
            # that no longer exists.
            # 让已删除的分组保持选中，会为一个不再存在的分组显示空网格。
            self._groups.select(-1)
            self._reload_stickers()
        return self._group_result(True, "group_deleted",
                                 {"name": group["name"], "count": count})

    @Slot(int, result="QVariantMap")
    def groupInfo(self, group_id):
        # What a rename/delete dialog needs: the name, whether it is protected, and how
        # much would be lost. One call rather than three round trips and three chances
        # to read inconsistent state.
        # 重命名/删除对话框所需的信息：名称、是否受保护、会损失多少。一次调用而不是三次往返和
        # 三次读到不一致状态的机会。
        group = self._adapter.backend.store.get_group(group_id)
        if group is None:
            return {"exists": False}
        return {
            "exists": True,
            "id": group["id"],
            "name": group["name"],
            "type": group["type"],
            "builtin": bool(group["is_builtin"]),
            "count": self._adapter.backend.store.count_emojis_in_group(group["id"]),
        }

    @Slot(int, result="QVariantList")
    def textGroups(self):
        # Text groups, for the "where does this text sticker go" chooser.
        # 文字分组，供"这张文字贴纸放哪"的选择器使用。
        return [{"id": group["id"], "name": group["name"]}
                for group in self._adapter.groups()
                if group["type"] == "text"]

    def _group_result(self, ok, message_key, extra=None):
        result = {"ok": bool(ok), "messageKey": message_key,
                  "message": self.tr(message_key)}
        if isinstance(extra, dict):
            result.update(extra)
        elif extra is not None:
            result.update({"id": extra.get("id"), "name": extra.get("name")})
        return result

    # ---- text stickers / 文字贴纸 ----------------------------------------

    @Slot(int, str, result="QVariantMap")
    def createTextSticker(self, group_id, text):
        # Create a text sticker in a text group.
        #
        # Refused for an image group rather than silently redirected, for the same reason
        # the importer refuses one: the store would create the row and the card would
        # have no file to show, which reads as a broken sticker rather than as a rejected
        # action.
        # 在文字分组中创建文字贴纸。
        #
        # 对图片分组明确拒绝而不是静默改道，原因与导入器拒绝时相同：存储层会建出行，而卡片没有
        # 文件可显示，读起来像一个坏掉的贴纸而不是一次被拒绝的操作。
        text = (text or "").strip()
        if not text:
            return {"ok": False, "messageKey": "text_empty",
                    "message": self.tr("text_empty")}
        if len(text) > MAX_TEXT_STICKER_CHARS:
            return {"ok": False, "messageKey": "text_too_long",
                    "message": self._t("text_too_long",
                                       limit=MAX_TEXT_STICKER_CHARS)}
        group = self._adapter.backend.store.get_group(group_id)
        if group is None:
            return {"ok": False, "messageKey": "group_missing",
                    "message": self.tr("group_missing")}
        if group["type"] != "text":
            return {"ok": False, "messageKey": "text_needs_text_group",
                    "message": self.tr("text_needs_text_group")}

        # The store de-duplicates text within a group, so a repeat is reported as such
        # instead of appearing to succeed and adding nothing.
        # 存储层会在分组内对文字去重，因此重复会被如实报告，而不是看起来成功却什么都没加。
        before = self._adapter.backend.store.count_emojis_in_group(group_id)
        created = self._adapter.backend.store.add_text_emoji(group_id, text)
        after = self._adapter.backend.store.count_emojis_in_group(group_id)
        if created is None:
            return {"ok": False, "messageKey": "text_create_failed",
                    "message": self.tr("text_create_failed")}
        if after == before:
            return {"ok": False, "messageKey": "text_duplicate",
                    "message": self.tr("text_duplicate")}
        self._on_library_changed()
        self._adapter.notify_library_changed()
        return {"ok": True, "messageKey": "text_created",
                "message": self.tr("text_created"),
                "id": created, "groupId": group_id, "groupName": group["name"]}

    @Slot(result="QVariantMap")
    def textStickerTarget(self):
        # Where a new text sticker would go, so the dialog can preselect and the button
        # can be enabled only when there is somewhere to put it.
        # 新建文字贴纸会去哪里，使对话框能预选，并只在有地方可放时才启用按钮。
        group_id = self._groups.currentId
        if group_id >= 0:
            group = self._adapter.backend.store.get_group(group_id)
            if group is not None and group["type"] == "text":
                return {"ok": True, "id": group["id"], "name": group["name"]}
        for group in self._adapter.groups():
            if group["type"] == "text":
                return {"ok": True, "id": group["id"], "name": group["name"]}
        return {"ok": False}

    @Slot(int, str, result="QVariantMap")
    def setStickerTextResult(self, sticker_id, text):
        # The editing half of `createTextSticker`, as a result map.
        #
        # `setStickerText` already exists and returns a boolean for the card menu; this
        # is the same operation reported the way a DIALOG needs it, because a dialog has
        # to say WHY it refused and a boolean cannot.
        # `createTextSticker` 的编辑一半，以结果映射返回。
        #
        # `setStickerText` 已存在并为卡片菜单返回布尔值；这是同一操作以"对话框需要的方式"报告，
        # 因为对话框必须说明"为什么"拒绝，而布尔做不到。
        text = (text or "").strip()
        if not text:
            return {"ok": False, "messageKey": "text_empty",
                    "message": self.tr("text_empty")}
        if len(text) > MAX_TEXT_STICKER_CHARS:
            return {"ok": False, "messageKey": "text_too_long",
                    "message": self._t("text_too_long",
                                       limit=MAX_TEXT_STICKER_CHARS)}
        row = self._stickers.rowById(sticker_id)
        if not row:
            return {"ok": False, "messageKey": "sticker_missing",
                    "message": self.tr("sticker_missing")}
        if text == row.get("text_content"):
            return {"ok": False, "messageKey": "text_unchanged",
                    "message": self.tr("text_unchanged")}
        if not self.setStickerText(sticker_id, text):
            return {"ok": False, "messageKey": "text_create_failed",
                    "message": self.tr("text_create_failed")}
        return {"ok": True, "messageKey": "text_updated",
                "message": self.tr("text_updated")}

    @Property(int, constant=True)
    def textStickerLimit(self):
        # The limit, read by the dialog's counter so the counter and the refusal cannot
        # disagree.
        # 上限，由对话框的计数器读取，使计数器与拒绝不会产生分歧。
        return MAX_TEXT_STICKER_CHARS

    @Slot(int, result=str)
    def groupNameOf(self, group_id):
        group = self._adapter.backend.store.get_group(group_id)
        return "" if group is None else group["name"]

    @Slot(result=str)
    def currentGroupType(self):
        # The type of the selected group, or "" for the All view. Used by the new-group
        # dialog to preselect the type the user is most likely to want.
        # 选中分组的类型，"全部"视图时为空。供新建分组对话框预选用户最可能想要的类型。
        group_id = self._groups.currentId
        if group_id < 0:
            return ""
        group = self._adapter.backend.store.get_group(group_id)
        return "" if group is None else group["type"]

    @Slot(int, result="QVariantMap")
    def sticker(self, sticker_id):
        return self._stickers.rowById(sticker_id)

    # ---- card operations / 卡片操作 --------------------------------------

    @Slot(int)
    def copySticker(self, sticker_id):
        # Text stickers copy their text; image stickers copy the file, which is
        # what a chat application can paste as a picture.
        # 文字贴纸复制其文字；图片贴纸复制文件，聊天软件才能作为图片粘贴。
        row = self._stickers.rowById(sticker_id)
        if not row:
            return
        text = row.get("text_content")
        if text:
            QGuiApplication.clipboard().setText(text)
            self._adapter.backend.store.increment_use_count(sticker_id)
            self._emit_status(self.tr("clipboard_copied"), STATUS_BRIEF_MS)
            return
        path = self._adapter.backend.store.emoji_filepath(row)
        if not path:
            self._emit_status(self.tr("clipboard_copy_failed"), STATUS_NORMAL_MS)
            return
        from PySide6.QtCore import QMimeData, QUrl

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path)])
        QGuiApplication.clipboard().setMimeData(mime)
        self._adapter.backend.store.increment_use_count(sticker_id)
        self._emit_status(self.tr("clipboard_copied"), STATUS_BRIEF_MS)

    @Slot(int)
    def sendSticker(self, sticker_id):
        # The full send sequence on one card click: clipboard payload, usage
        # count, status line, then — when `auto_input` is on — one paste into
        # the chat window the focus tracker remembered. This is the click path
        # of the original project; `copySticker` stays the clipboard-only form
        # the tray and the context menu use.
        # 一次卡片点击的完整发送序列：剪贴板载荷、使用计数、状态行，然后——当
        # `auto_input` 开启时——向焦点跟踪器记住的聊天窗口粘贴一次。这是原项目的
        # 点击路径；`copySticker` 保留为托盘与右键菜单使用的纯复制形式。
        row = self._stickers.rowById(sticker_id)
        if not row:
            return
        self.copySticker(sticker_id)
        if not self._adapter.settings.auto_input:
            return
        result = self._paste_into_chat()
        if not result.get("ok"):
            reason = result.get("reason") or ""
            if reason:
                log.info("send: paste not delivered: %s", reason)

    @Slot(float)
    def adjustCardScale(self, delta):
        # Alt+wheel card zoom: apply one step to the stored `card_scale` through
        # the same settings path the settings page uses, so the change is
        # persisted, announced, and picked up by the open settings window.
        # Alt+滚轮卡片缩放：对已存储的 `card_scale` 应用一步，走设置页所用的同一条
        # 设置路径，因此变更被持久化、宣告，并被打开的设置窗口读取。
        current = float(self._adapter.settings.card_scale or 1.0)
        minimum, maximum = schema.CARD_SCALE_MIN, schema.CARD_SCALE_MAX
        scaled = max(minimum, min(maximum, current + float(delta) * CARD_SCALE_STEP))
        if scaled == current:
            return
        # Commit the step IMMEDIATELY, not just buffer it.
        #
        # `setValue` only stages a draft for the settings dialog's 应用 button, so the old code
        # adjusted a value that nothing ever applied: the grid reads the APPLIED setting, saw no
        # change, and the gesture looked completely dead. `commitValue` coerces and applies this one
        # field without disturbing any other draft.
        # 立即提交这一步，而不只是暂存。
        #
        # `setValue` 只为设置对话框的"应用"按钮暂存草稿，因此旧代码调整了一个从未被应用的值：网格读的
        # 是"已应用"的设置，看不到变化，手势看起来完全失效。`commitValue` 只强制转换并应用这一个字段，
        # 不打扰任何其他草稿。
        self._settings_model.commitValue("card_scale", round(scaled * 100))

    @Slot(int, str, result=bool)
    def renameSticker(self, sticker_id, new_name):
        new_name = (new_name or "").strip()
        row = self._stickers.rowById(sticker_id)
        if not row or not new_name or new_name == row.get("original_name"):
            return False
        self._adapter.backend.store.rename_emoji(sticker_id, new_name)
        self._adapter.notify_library_changed()
        return True

    @Slot(int, str, result=bool)
    def setStickerText(self, sticker_id, text):
        text = (text or "").strip()
        row = self._stickers.rowById(sticker_id)
        if not row or not text or text == row.get("text_content"):
            return False
        self._adapter.backend.store.update_text_content(sticker_id, text)
        self._adapter.notify_library_changed()
        return True

    @Slot(int, result=bool)
    def deleteSticker(self, sticker_id):
        # A sticker stored in several groups is one picture, so every copy goes:
        # deleting only the visible one is what made "delete" look like it did
        # nothing in an earlier release.
        # 存于多个分组的贴纸是同一张图，因此所有副本一起删除：只删可见的那一份正是早前版本
        # "删除"看起来毫无效果的原因。
        row = self._stickers.rowById(sticker_id)
        if not row:
            return False
        ids = self._adapter.backend.store.ids_sharing_content_hash([sticker_id])
        removed = self._adapter.backend.store.delete_emojis(sorted(set(ids)))
        self._adapter.notify_library_changed()
        return removed > 0

    @Slot(result=bool)
    def deleteSelection(self):
        ids = self._stickers.selectedIds()
        if not ids:
            return False
        expanded = self._adapter.backend.store.ids_sharing_content_hash(ids)
        removed = self._adapter.backend.store.delete_emojis(
            sorted(set(expanded)))
        self._adapter.notify_library_changed()
        return removed > 0

    @Slot(int, result="QVariantList")
    def groupsForSticker(self, sticker_id):
        # Candidate targets for a move, filtered by type so the menu cannot offer
        # a move the store would then refuse.
        # 移动的候选目标，按类型过滤，使菜单不会提供一个存储随后会拒绝的移动。
        row = self._stickers.rowById(sticker_id)
        if not row:
            return []
        wants_text = bool(row.get("text_content"))
        all_id = self._adapter.backend.store._all_group_id()
        result = []
        for group in self._adapter.groups():
            # The All view is never a target: it is an aggregation, not a place.
            # “全部”绝不是目标：它是聚合视图而非存放地。
            if group["id"] == all_id or group["id"] == row.get("group_id"):
                continue
            if wants_text and group["type"] != "text":
                continue
            if not wants_text and group["type"] != "image":
                continue
            result.append({"id": group["id"], "name": group["name"]})
        return result

    @Slot(int, int, result=bool)
    def moveSticker(self, sticker_id, target_group_id):
        if self._adapter.backend.store._all_group_id() == target_group_id:
            self._emit_status(self.tr("move_failed"), STATUS_NORMAL_MS)
            return False
        if not self._adapter.backend.store.move_emoji(sticker_id,
                                                      target_group_id):
            self._emit_status(self.tr("move_failed"), STATUS_NORMAL_MS)
            return False
        self._adapter.notify_library_changed()
        return True

    @Slot(result="QVariantList")
    def moveTargetsForSelection(self):
        # Candidate move targets for the whole selection: image stickers may only enter image
        # groups and text stickers text groups, so a mixed selection gets an empty list rather
        # than a list that half-fails.
        #
        # The ALL view is excluded BY ID, not by comparing against the current group.
        #
        # The previous version skipped whichever group was current, which reads as equivalent
        # and is not: the All view is not a real group, so `currentId` is -1 while it is
        # selected, and the comparison therefore never matched the stored "全部" row. The
        # result was that "全部" appeared as a destination in the edit-mode move dialog - the
        # one place a user could pick it - even though `moveSticker` refuses it and nothing can
        # be stored into an aggregation.
        # 整个选择的候选移动目标：图片只能进图片分组、文字只能进文字分组，因此混合选择得到空列表，
        # 而不是一个会失败一半的列表。
        #
        # "全部"视图按 id 排除，而不是通过比较"当前分组"排除。
        #
        # 上一版跳过的是当前所在的那个分组，读起来等价、其实不等价："全部"不是真实分组，因此在它被
        # 选中时 `currentId` 是 -1，那个比较于是永远匹配不上存储里的"全部"行。结果是"全部"出现在
        # 编辑模式移动对话框的目的地列表里——那是用户唯一能选中它的地方——尽管 `moveSticker` 拒绝
        # 它，而且没有任何东西能存进一个聚合。
        ids = self._stickers.selectedIds()
        if not ids:
            return []
        all_id = self._adapter.backend.store._all_group_id()
        rows = [self._stickers.rowById(sticker_id) for sticker_id in ids]
        wants_text = all(bool(row.get("text_content")) for row in rows if row)
        current_group = self._groups.currentId
        result = []
        for group in self._adapter.groups():
            if group["id"] == all_id or group["id"] == current_group:
                continue
            if group["type"] != ("text" if wants_text else "image"):
                continue
            result.append({"id": group["id"], "name": group["name"]})
        return result

    @Slot(int, result=bool)
    def moveSelection(self, target_group_id):
        # Move every selected sticker into one group. Reports the outcome rather
        # than per-item failures: a batch move either happened or it did not.
        # 把所有选中的贴纸移入一个分组。报告整体结果而非逐项失败：批量移动要么发生
        # 了，要么没有。
        ids = self._stickers.selectedIds()
        if not ids:
            return False
        store = self._adapter.backend.store
        moved = sum(1 for sticker_id in ids
                    if store.move_emoji(sticker_id, target_group_id))
        self._adapter.notify_library_changed()
        if moved:
            self._emit_status(
                self._t("edit_moved", count=moved), STATUS_BRIEF_MS)
            return True
        self._emit_status(self.tr("move_failed"), STATUS_NORMAL_MS)
        return False

    # ---- drag reordering / 拖拽排序 ---------------------------------------
    #
    # Reordering a sticker within its group. The store expresses position as
    # (column, index within column) and the TEXT-card packer owns the columns, so a drag
    # names a DESTINATION CARD and this translates that into the store's coordinates.
    #
    # # Why a destination card rather than an offset
    #
    # "Move one later" is ambiguous in a grid: later within the column, or later in the
    # visual flow? Naming the card the user dropped onto is what a user actually means,
    # and it is expressible in the store's terms. The first design took a numeric offset
    # and could not be implemented without inventing an ordering the store does not have.
    #
    # 在分组内重排贴纸。存储层把位置表达为（列, 列内序号），而列由文字卡片摊列器拥有，因此一次
    # 拖拽指定"目标卡片"，由此翻译成存储层的坐标。
    #
    # # 为什么用目标卡片而不是偏移量
    #
    # 在网格里"往后移一位"是有歧义的：列内往后，还是视觉流往后？点名用户拖放到的卡片才是用户
    # 真正的意思，而且可以用存储层的术语表达。最初的设计接收数值偏移量，而不发明一种存储层并不
    # 存在的排序就无法实现它。

    @Slot(int, int, result="QVariantMap")
    def reorderSticker(self, sticker_id, target_sticker_id):
        # Move `sticker_id` to sit where `target_sticker_id` is.
        #
        # The target's stored position is READ and the dragged card is placed there,
        # which shifts the target down. Reading rather than recomputing is deliberate: the
        # front-end's idea of order and the store's must not be able to disagree, and the
        # only authority on where a card currently sits is the store.
        # 把 `sticker_id` 移到 `target_sticker_id` 所在的位置。
        #
        # "读取"目标已存储的位置并把被拖的卡片放在那里，这会把目标往下推。刻意读取而非重新计算：
        # 前端的顺序概念与存储层的不得产生分歧，而一张卡片当前位置的唯一权威是存储层。
        return self._reorder_sticker(sticker_id, target_sticker_id, 0)

    @Slot(int, int, result="QVariantMap")
    def reorderStickerAfter(self, sticker_id, target_sticker_id):
        # The after-target variant: the dragged card lands one row later, which is
        # what a drop on the target's trailing half means. The store inserts at a
        # row index, so "after" is the target's own index plus one.
        # "放到目标之后"的变体：被拖卡片落在目标后一行，这正是拖到目标后半的含义。存储层
        # 按行号插入，因此"之后"即目标行号加一。
        return self._reorder_sticker(sticker_id, target_sticker_id, 1)

    def _reorder_sticker(self, sticker_id, target_sticker_id, offset):
        # The shared reorder body: read the target's stored (column, order),
        # refuse the no-ops, insert with the requested offset.
        # 重排的公共主体：读取目标已存储的（列, 位置），拒绝无意义的操作，按请求的偏移
        # 插入。
        if sticker_id == target_sticker_id:
            return {"ok": False, "messageKey": "reorder_same",
                    "message": self.tr("reorder_same")}
        dragged = self._stickers.rowById(sticker_id)
        target = self._stickers.rowById(target_sticker_id)
        if not dragged or not target:
            return {"ok": False, "messageKey": "sticker_missing",
                    "message": self.tr("sticker_missing")}
        if dragged.get("group_id") != target.get("group_id"):
            # Reordering ACROSS groups is a move, which is a different operation with a
            # different effect on the filesystem. Refused rather than silently treated as
            # one, because "I dragged it next to that card" does not mean "move it to
            # another group".
            # 跨分组重排是"移动"，那是一个对文件系统效果不同的操作。明确拒绝而不是静默当作移动
            # 处理，因为"我把它拖到那张卡旁边"并不意味着"把它移到另一个分组"。
            return {"ok": False, "messageKey": "reorder_cross_group",
                    "message": self.tr("reorder_cross_group")}

        target_col = target.get("col_index")
        if target_col is None:
            # The target is unplaced (the packer owns it). Destination = its own column is
            # the only meaningful reading, and the packer will re-run on the next load.
            # 目标是未放置的（由摊列器拥有）。目的地 = 它自己的列是唯一有意义的解读，而摊列器会
            # 在下次加载时重跑。
            target_col = 0
        target_order = int(target.get("sort_order") or 0) + offset
        moved = self._adapter.backend.store.set_emoji_column(
            sticker_id, int(target_col), target_order)
        if not moved:
            return {"ok": False, "messageKey": "reorder_failed",
                    "message": self.tr("reorder_failed")}
        self._on_library_changed()
        self._adapter.notify_library_changed()
        return {"ok": True, "messageKey": "reorder_done",
                "message": self.tr("reorder_done"),
                "column": int(target_col), "order": target_order}

    @Slot(result=bool)
    def canReorder(self):
        # Whether reordering makes sense for what is currently shown.
        #
        # The All view folds several groups together, so a "position" there does not
        # exist; a search result is a filtered list whose positions are the unfiltered
        # ones. Both are refused rather than silently reordering something the user
        # cannot see.
        # 当前显示的内容是否适合重排。
        #
        # "全部"视图把多个分组折叠在一起，因此那里不存在"位置"；搜索结果是一个筛选后的列表，
        # 其位置属于未筛选的列表。两者都拒绝，而不是静默重排用户看不到的东西。
        return self._groups.currentId >= 0 and not self._keyword

    @Slot(result=str)
    def reorderBlockedReason(self):
        if self._groups.currentId < 0:
            return self.tr("reorder_needs_group")
        if self._keyword:
            return self.tr("reorder_needs_no_search")
        return ""

    # ---- text masonry / 文字瀑布流 ----------------------------------------
    #
    # A TEXT group lays out as columns (the original project's masonry), and the
    # column structure lives in the store. The page reports its viewport width;
    # the packer assigns unplaced cards against that width; per-column proxies
    # let each column be its own virtualised ListView.
    # 文字分组按列布局（原项目的瀑布流），列结构存于存储层。页面报告其视口宽度；摊列器
    # 按该宽度为未放置的卡片分列；每列一个代理使每一列都是独立的虚拟化 ListView。

    @Slot(int)
    def setViewportWidth(self, width):
        width = max(0, int(width))
        if width == self._viewport_width:
            return
        self._viewport_width = width
        self._reload_stickers()

    def _pack_text_columns(self):
        # Assign unplaced cards against the reported viewport width. Called from
        # the reload path BEFORE the rows are read, so the fresh (column, order)
        # lands in the same load. The All view and searches never pack; a text
        # group packs for its masonry and an image group packs so its drags have
        # placed cards to work with.
        # 按报告的视口宽度为未放置的卡片分列。在读取行"之前"由重载路径调用，使新的
        # （列, 位置）落入同一次加载。"全部"视图与搜索从不摊列；文字分组为瀑布流而摊列，
        # 图片分组摊列是让拖拽有已放置的卡片可用。
        if self._viewport_width <= 0 or self._groups.currentId < 0:
            return False
        if self._keyword:
            return False
        # The pack's usable width must match the grid's own margins (theme
        # `gridMargin` on each side), or the packer's column count drifts from
        # the view's and a drop lands one column off.
        # 摊列的可用宽度必须与网格自身的边距（两侧的 theme `gridMargin`）一致，否则
        # 摊列器的列数会与视图漂移，放置会偏一列。
        from gifmanager.frontend.qml.theme import METRICS

        margin = METRICS["gridMargin"]
        return bool(self._stickers.packTextColumns(
            self._viewport_width - 2 * margin, self._groups.currentId))

    @Property(int, notify=stickerCountChanged)
    def textColumnCount(self):
        return self._stickers.columnCount

    @Slot(int, result=QObject)
    def textColumnModel(self, column):
        # One proxy per column, cached: the proxy object identity must stay stable
        # or a ListView would rebuild its delegates on every binding re-read.
        # 每列一个代理并缓存：代理对象标识必须稳定，否则 ListView 会在每次绑定重读时
        # 重建委托。
        proxy = self._column_proxies.get(column)
        if proxy is None:
            from gifmanager.frontend.qml.models import ColumnProxy

            proxy = ColumnProxy(self._stickers, column)
            self._column_proxies[column] = proxy
        return proxy

    @Slot(int, result=int)
    def textColumnWidth(self, column):
        return self._stickers.columnWidth(column)

    @Slot(int, result=str)
    def stickerFileUrl(self, sticker_id):
        # The `file://` URL an `Image` element can load. Exposed so the hover
        # preview can show the same source the card shows.
        # `Image` 元素可加载的 `file://` URL。暴露它是为了让悬停预览显示与卡片相同的源。
        row = self._stickers.rowById(sticker_id)
        if not row:
            return ""
        path = self._adapter.backend.store.emoji_filepath(row)
        if not path:
            return ""
        from PySide6.QtCore import QUrl

        return QUrl.fromLocalFile(path).toString()

    @Slot(int, result=str)
    def filePathOf(self, sticker_id):
        # A separate call from `stickerFileUrl` because the two are genuinely different
        # things: `Image` needs a URL and the decoder needs a path, and having the bridge
        # hand out the right one to each caller is cheaper and less error-prone than
        # converting in QML or in the card.
        # 贴纸背后的文件系统路径，供动画器使用。
        #
        # 与 `stickerFileUrl` 分开是因为两者确实是不同的东西：`Image` 需要 URL，解码器需要
        # 路径，而由桥向每个调用方交出正确的那个，比在 QML 或卡片里转换更省也更不易错。
        row = self._stickers.rowById(sticker_id)
        if not row:
            return ""
        return self._adapter.backend.store.emoji_filepath(row) or ""

    @Slot(str, int, result=str)
    def previewUrlFor(self, path, edge):
        # A provider rather than the file's own `file://` URL, because loading a 5-8 MB animated
        # GIF through a QML `Image` decodes EVERY frame at full size on the GUI thread. The
        # provider asks `QImageReader` for frame 0 at the target size instead.
        #
        # Exposed through the bridge rather than computed in QML because the URL needs the path's
        # hash prefix, which lives in the animator's registry — a QML-side concatenation would
        # have to duplicate that hashing and would silently produce a URL the provider cannot
        # resolve.
        # `path` 的静态帧在 `edge` 像素下的提供器 URL。
        #
        # 用提供器而不是文件自身的 `file://` URL，因为经 QML 的 `Image` 加载一个 5-8MB 的动画 GIF
        # 会在 GUI 线程上按原尺寸解码"每一帧"。提供器改为向 `QImageReader` 请求目标尺寸的第 0 帧。
        #
        # 经桥暴露而不是在 QML 里计算，因为该 URL 需要路径的哈希前缀，而它住在动画器的注册表里——QML
        # 侧拼接就得重复那套哈希，并会静默产出提供器无法解析的 URL。
        from gifmanager.frontend.qml.animator import preview_url

        return preview_url(str(path or ""), int(edge))

    @Property(int, constant=True)
    def stickerIdRole(self):
        # The integer Qt role for a sticker's id, so QML can read an id out of the model.
        #
        # Needed by the drag-sweep, which asks the grid `indexAt(x, y)` for a row index and then
        # must turn that index back into an id to call `setSelected`. QML cannot name the role
        # itself: the roles are Python class attributes on the model and are not exposed as QML
        # properties, so `grid.model.IdRole` resolves to `undefined` and every selection call
        # would pass `undefined` - a silent no-op.
        # 贴纸 id 对应的整数 Qt 角色，使 QML 能从模型里读出一个 id。
        #
        # 拖拽扫选需要它：它用 `indexAt(x, y)` 向网格要一个行索引，随后必须把该索引换回 id 才能调用
        # `setSelected`。QML 无法自己命名该角色：角色是模型上的 Python 类属性、并未作为 QML 属性暴露，
        # 因此 `grid.model.IdRole` 会解析为 `undefined`，每次选择调用都会传入 `undefined`——一个静默的
        # 空操作。
        from gifmanager.frontend.qml.models import StickerListModel

        return int(StickerListModel.IdRole)

    @Slot(int, result=int)
    def copiesOf(self, sticker_id):
        # How many stored copies the sticker has, so a dialog can warn before one
        # delete removes several rows.
        # 该贴纸存储了多少份副本，使对话框能在一次删除会移除多行之前给出提示。
        row = self._stickers.rowById(sticker_id)
        if not row:
            return 0
        return len(self._adapter.backend.store.get_emoji_copies(row))

    # ---- selection / 选择 ------------------------------------------------

    @Slot()
    def selectAll(self):
        # A TOGGLE, exactly like the original's `_edit_select_all`.
        #
        # `target = selection_count() < len(data)`: if everything is already selected, clear;
        # otherwise select everything. Selecting unconditionally made the button one-way - pressing
        # it
        # twice left the user fully selected with no way back through the same control.
        #
        # The comparison is against the WHOLE current data set, not the visible cards, for the
        # reason
        # the original documents: a lazily-built grid only materialises the visible band, so
        # counting
        # cards would clear the selection while the user is looking at a partially-scrolled list and
        # believe they had selected everything.
        # 与原版 `_edit_select_all` 完全一致的"切换"。
        #
        # `target = selection_count() < len(data)`：若已全选则清空，否则全选。无条件全选会让按钮变成
        # 单向的——按两次之后用户处于全选状态，却无法通过同一个控件回去。
        #
        # 比较的是"整个"当前数据集而不是可见卡片，理由与原版所述相同：懒构建的网格只物化可见区间，按卡片
        # 计数会在用户看着滚动到一半的列表时清空选择，而用户以为自己已全选。
        total = self._stickers.count
        if total and self._stickers.selectedCount < total:
            self._stickers.selectAll()
        else:
            self._stickers.clearSelection()

    @Slot(result=bool)
    def allSelected(self):
        # Whether every item in the current set is selected, so the button can label itself.
        # 当前集合是否已全部选中，使按钮能自我标注。
        total = self._stickers.count
        return bool(total) and self._stickers.selectedCount >= total

    @Slot()
    def clearSelection(self):
        self._stickers.clearSelection()

    # ---- display settings the pages read directly / 页面直接读取的显示设置 ----
    #
    # Exposed as their own properties rather than making QML index into a settings
    # map: a `notify` signal on a property re-evaluates the binding, whereas a map
    # lookup does not, so `app.settings["card_scale"]` would silently not update.
    # 作为独立属性暴露，而不是让 QML 去索引设置映射：属性的 `notify` 信号会让绑定重新
    # 求值，而映射查找不会，因此 `app.settings["card_scale"]` 会静默不更新。

    @Property(float, notify=settingsChanged)
    def cardScale(self):
        return float(self._adapter.settings.card_scale)

    @Property(float, notify=settingsChanged)
    def hoverZoom(self):
        return float(self._adapter.settings.hover_zoom)

    @Property(int, notify=settingsChanged)
    def nameFontSize(self):
        return int(self._adapter.settings.name_font_size)

    @Property(bool, notify=settingsChanged)
    def showNames(self):
        return bool(self._adapter.settings.show_emoji_name)

    @Property(bool, notify=settingsChanged)
    def hoverPreviewEnabled(self):
        return bool(self._adapter.settings.hover_preview_enabled)

    @Property(int, notify=settingsChanged)
    def textLimitSingle(self):
        # Text preview truncation for single-line stickers, the same limits the
        # original project applied (`text_preview_limit_single`).
        # 单行文字贴纸的预览截断上限，与原项目应用的限制相同。
        return int(getattr(self._adapter.settings,
                           "text_preview_limit_single", 100))

    @Property(int, notify=settingsChanged)
    def textLimitMulti(self):
        # The multi-line variant of the same limit.
        # 同一限制的多行版本。
        return int(getattr(self._adapter.settings,
                           "text_preview_limit_multi", 200))

    def _apply_animation_settings(self):
        # Push the render-mode settings into the animator.
        #
        # Called at construction and on every settings change, so the animator cannot hold a
        # cap the user has since changed.
        #
        # # The cap is the COUNT in both modes
        #
        # This used to set the cap to 0 whenever the mode was not `auto`, which made every GIF
        # static in `manual` mode no matter what the count said. That is what happened to a
        # configuration of `gif_render_mode='manual', gif_render_count=18`: the count was
        # present and non-zero, and the check that reads it lived only in the `auto` branch, so
        # the number was ignored and the whole library froze. "Pick the number of animated
        # stickers yourself" cannot reasonably mean "animate none of them".
        #
        # A count of 0 is the real "show stills" signal, because 0 is the value a user reaches
        # by turning the count all the way down. `GIF_RENDER_COUNT_MIN` is 1, so 0 is
        # unambiguous and does not collide with any selectable value.
        #
        # 把渲染模式设置推入动画器。
        #
        # 在构造时与每次设置变更时调用，使动画器不会持有用户已经改过的上限。
        #
        # # 两种模式下上限都是"数量"
        #
        # 这里过去在模式不是 `auto` 时把上限设为 0，使 `manual` 模式下所有 GIF 都变成静态，
        # 无论数量写的是什么。`gif_render_mode='manual', gif_render_count=18` 的配置正是如此：
        # 数量存在且非零，而读取它的判断只写在 `auto` 分支里，于是那个数字被忽略、整个素材库冻结。
        # "自己挑选动画贴纸的数量"不可能合理地意味着"一个都不动"。
        #
        # 数量为 0 才是真正的"显示静态图"信号，因为 0 是用户把数量调到最低时会得到的值。
        # `GIF_RENDER_COUNT_MIN` 是 1，因此 0 不含歧义、也不与任何可选值冲突。
        animator = getattr(self, "_animator", None)
        if animator is None:
            return
        from gifmanager.core import settings as settings_schema

        animator.setEnabled(True)
        count = int(self._adapter.settings.gif_render_count)
        mode = self._adapter.settings.gif_render_mode
        if mode == settings_schema.RENDER_AUTO:
            # `auto` with a count of 0 means "you pick", so it becomes the maximum. `auto` with
            # an explicit count honours it.
            # `auto` 且数量为 0 意味着"你来定"，因此取最大值；`auto` 且有显式数量时尊重它。
            animator.setMaxAnimated(
                count if count > 0 else settings_schema.GIF_RENDER_COUNT_MAX)
            return
        # `manual`: a count of 0 is the "show stills" signal, and any other value IS the cap.
        # Setting the cap to 0 for EVERY value was the bug: a stored
        # `gif_render_count=18` was ignored and the whole library froze.
        # `manual`：数量为 0 是"显示静态图"的信号，其他任何取值"就是"上限。对"每一个"取值都把
        # 上限设为 0 才是那个缺陷：已存的 `gif_render_count=18` 被忽略，整个素材库冻结。
        animator.setMaxAnimated(count)

    @Property(bool, notify=settingsChanged)
    def animationEnabled(self):
        # True when playback should be offered at all. A manual render mode with a cap of
        # zero means "show stills", which QML expresses by not registering frames.
        # 是否应提供播放。上限为零的手动渲染模式意味着"显示静态图"，QML 通过不注册帧来表达。
        return self.maxAnimated > 0

    @Property(int, notify=settingsChanged)
    def maxAnimated(self):
        animator = getattr(self, "_animator", None)
        if animator is None:
            return 0
        return animator.maxAnimated

    @Property(str, notify=settingsChanged)
    def themeName(self):
        return self._adapter.settings.theme

    @Property(str, notify=languageChanged)
    def language(self):
        return self._adapter.settings.language

    @Property("QStringList", notify=languageChanged)
    def languages(self):
        return list(self._adapter.available_languages())

    # ---- settings / 设置 -------------------------------------------------

    @Property(str, notify=settingsChanged)
    def settingsTheme(self):
        return self._adapter.settings.theme

    @Slot(str)
    def setLanguage(self, code):
        self._adapter.set_language(code)

    @Slot()
    def resetSettings(self):
        self._settings_model.resetToDefaults()

    @Slot()
    def reloadSettings(self):
        # Discard unsaved edits by re-reading the store, then tell the models, so
        # the page and the rest of the interface cannot disagree.
        # 通过重读存储丢弃未保存的编辑，随后通知模型，使页面与界面其余部分不会不一致。
        self._adapter.load_settings()
        self.settingsChanged.emit([])

    @Slot(int, result=str)
    def keyName(self, qt_key):
        # Portable key name for a Qt key code, so the QML hotkey field stores the
        # same string the platform layer registers and the settings file keeps.
        # Qt 键码对应的可移植按键名，使 QML 热键字段存储的字符串与平台层注册、设置文件
        # 保存的完全一致。
        from gifmanager.frontend.qt.widgets.hotkey_capture import key_from_qt

        return key_from_qt(qt_key) or ""

    # ---- hotkey capture / 热键捕获 --------------------------------------
    #
    # # Why the capture lives in Python instead of in `Keys.onPressed`
    #
    # The QML version required the `TextField` to hold ACTIVE focus. Inside a `Loader` inside a
    # `Repeater`, a field that is `readOnly` and only gets focus from an overlay `MouseArea`
    # frequently
    # does not have it at the moment a key arrives - the click focuses the overlay, the window loses
    # activation, or focus moves on the next repaint. The result was the reported symptom: pressing
    # a
    # key changed nothing, with no error anywhere.
    #
    # An application-wide event filter has no such dependency: while the field is armed, EVERY key
    # press in the process is seen, which is also what makes modifier combinations reliable - the
    # filter reads `event.modifiers()` from the same event that carries the key, so Ctrl+Shift+F9 is
    # one atom rather than three key presses racing each other.
    #
    # The extra keys are swallowed (returning True) only while armed, so arming cannot leak
    # keystrokes
    # into the rest of the interface.
    #
    # 捕获放在 Python 而不是 `Keys.onPressed` 里。
    #
    # # 为什么捕获放在 Python 而不是 `Keys.onPressed`
    #
    # QML 版本要求 `TextField` 持有"活动焦点"。在 `Repeater` 内的 `Loader` 里，一个 `readOnly` 且只能
    # 通过覆盖的 `MouseArea` 获得焦点的字段，在按键到达时经常并没有焦点——点击把焦点给了覆盖层、窗口
    # 失去激活、或焦点在下一次重绘时移走。结果就是用户报告的症状：按键毫无变化，且任何地方都没有报错。
    #
    # 应用级事件过滤器没有这个依赖：字段处于"待捕获"状态时，进程里的"每一次"按键都会被看到，这也正是
    # 修饰键组合可靠的原因——过滤器从携带按键的"同一个事件"读取 `event.modifiers()`，因此 Ctrl+Shift+F9
    # 是一个原子操作，而不是三次互相竞争的按键。
    #
    # 只有在待捕获期间才吞掉按键（返回 True），因此"待捕获"不会把击键泄漏到界面其余部分。

    @Slot(str)
    def beginHotkeyCapture(self, field):
        # Arm the capture for one settings field.
        # 为一个设置字段进入待捕获状态。
        if not field:
            return
        self._hotkey_field = field
        if self._hotkey_filter is None:
            from PySide6.QtCore import QCoreApplication

            application = QCoreApplication.instance()
            if application is None:
                return
            self._hotkey_filter = _HotkeyCaptureFilter(self)
            application.installEventFilter(self._hotkey_filter)

    @Slot()
    def endHotkeyCapture(self):
        # Disarm, and say so, so the field can drop its "armed" styling.
        # 解除待捕获并通知，使字段可以撤掉"已就绪"的样式。
        self._end_hotkey_capture()
        self.hotkeyCaptureEnded.emit()

    def _end_hotkey_capture(self):
        if self._hotkey_filter is not None:
            from PySide6.QtCore import QCoreApplication

            application = QCoreApplication.instance()
            if application is not None:
                application.removeEventFilter(self._hotkey_filter)
            self._hotkey_filter = None
        self._hotkey_field = ""

    def _capture_hotkey_event(self, event):
        # Handle one key event while armed. Returns True when the event was consumed.
        # 待捕获期间处理一个按键事件。被消费时返回 True。
        from PySide6.QtCore import Qt

        from gifmanager.frontend.qt.widgets.hotkey_capture import key_from_qt

        key = event.key()
        # A bare modifier is not a hotkey: the user is on the way to a combination, so the event is
        # swallowed (it must not reach the interface) but nothing is stored.
        # 单独的修饰键不是热键：用户正在前往一个组合键，因此事件被吞掉（不能传到界面）但不存储任何东西。
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt,
                   Qt.Key.Key_Meta, Qt.Key.Key_AltGr):
            return True
        field = self._hotkey_field
        if key == Qt.Key.Key_Escape:
            # ESC clears, exactly as the original dialog did.
            # ESC 清空，与原对话框完全一致。
            self._settings_model.commitValue(field, "")
            self.hotkeyCaptured.emit(field, "")
            self._end_hotkey_capture()
            self.hotkeyCaptureEnded.emit()
            return True
        name = key_from_qt(key)
        if not name:
            # An unmapped key is left alone: swallowing it would make the field feel broken while
            # storing nothing, and letting it through means Escape still works.
            # 未映射的按键不做处理：吞掉它会让字段"看起来坏了"却什么都没存，放它过去则意味着 ESC 仍然有效。
            return True
        parts = []
        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            parts.append("Ctrl")
        if modifiers & Qt.KeyboardModifier.AltModifier:
            parts.append("Alt")
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            parts.append("Shift")
        if modifiers & Qt.KeyboardModifier.MetaModifier:
            parts.append("Meta")
        parts.append(name)
        text = "+".join(parts)
        # A SINGLE key is a valid shortcut, and it is the default one.
        #
        # The previous version refused a bare letter, digit or F-key on the theory that registering
        # one
        # would steal it from every application. That theory is wrong for this feature: the shipped
        # default is F10 with `modifiers == 0`, the original project's dialog accepted a lone key,
        # and
        # `RegisterHotKey` is happy with one - so the extra rule rejected exactly the values the
        # rest of
        # the system already produces. Combinations remain fully supported; they are simply not
        # required.
        # "单个"按键是合法快捷键，而且它就是默认值。
        #
        # 上一版以"注册裸键会从系统上每个应用手里抢走它"为由，拒绝裸字母、数字与 F 键。对这个功能而言
        # 那个理由不成立：随包默认值就是 `modifiers == 0` 的 F10，原项目的对话框接受单键，而
        # `RegisterHotKey` 也完全接受单键——因此那条额外规则恰好拒绝了系统其余部分一直在产生的值。
        # 组合键仍然被完整支持，只是不再"强制"要求。
        # COMMIT, not draft.
        #
        # `setValue` only stages an edit for the settings dialog's 应用 button, so with it the new
        # sequence sat in a buffer: the preview table kept the old one, the registered key kept the
        # old
        # one, and nothing changed until the user pressed a button they had no reason to press. The
        # capture already knows the value is final, so it applies it.
        #
        # 提交，而不是草稿。
        #
        # `setValue` 只为设置对话框的"应用"按钮暂存编辑，因此用它时新序列停在缓冲里：预览表仍显示旧的、
        # 已注册的键仍是旧的，直到用户按下一个他毫无理由去按的按钮。捕获本身已经知道该值就是最终值，
        # 因此它直接应用。
        self._settings_model.commitValue(field, text)
        self.hotkeyCaptured.emit(field, text)
        self._end_hotkey_capture()
        self.hotkeyCaptureEnded.emit()
        return True


    # ---- settings apply / 设置应用 ---------------------------------------

    @Slot()
    def applySettings(self):
        # Commit the settings dialog's pending edits, and NEVER raise.
        #
        # The QML 确定 button is `applyPending(); close()`. If `applyPending` raises - a coercion the
        # schema rejects, a platform service that is unavailable, a registry write that fails - the
        # exception propagates out of the QML statement and `close()` never runs, so the window
        # stays
        # open and NOTHING is saved. That is exactly the reported "clicking save does not close the
        # settings window": the failure was in the apply step, and the close was its silent victim.
        #
        # Returning a bool instead of raising keeps the two operations independent at the call site.
        # 提设置对话框的待定编辑，并且"绝不抛出"。
        #
        # QML 的"确定"按钮是 `applyPending(); close()`。如果 `applyPending` 抛异常——schema 拒绝的
        # 强制转换、不可用的平台服务、失败的注册表写入——异常会从 QML 语句中传播出去，`close()` 永远
        # 不会执行，于是窗口留在原地且"什么都没保存"。这正是用户报告的"点击保存后不会关闭设置窗口"：
        # 失败发生在应用步骤，而关闭是它无声的受害者。
        #
        # 返回布尔值而不是抛出，使两个操作在调用点彼此独立。
        try:
            self._settings_model.applyPending()
            return True
        except Exception:
            log.exception("settings: applying pending edits failed")
            return False


    @Slot(str, result=bool)
    def supports(self, capability):
        return self._adapter.supports(capability)

    @Property("QVariantMap", notify=settingsChanged)
    def capabilities(self):
        return dict(self._adapter.platform_report().get("capabilities", {}))

    # ---- application / 应用 ---------------------------------------------

    def _t(self, key, **kwargs):
        # Internal translation with placeholders.
        #
        # The QML-facing `tr` slot cannot accept keyword arguments — a PySide6
        # `Slot` cannot declare them — so Python-side callers that need
        # placeholders use this instead of overloading the slot's signature, which
        # would silently stop it registering.
        # 带占位符的内部翻译。
        #
        # 面向 QML 的 `tr` 槽无法接收关键字参数——PySide6 的 `Slot` 无法声明它们——因此
        # 需要占位符的 Python 侧调用方使用本方法，而不是去重载槽的签名（那会让它静默注册
        # 失败）。
        try:
            return self._adapter.tr(key, **kwargs)
        except Exception:
            log.exception("bridge: translation failed for %r", key)
            return key

    @Property(str, constant=True)
    def appName(self):
        return APP_NAME

    @Property(str, constant=True)
    def licenseText(self):
        # The MIT licence, read from the bundled LICENSE file so the About page
        # cannot drift from what the repository ships. A packaged build without
        # the file still shows the licence's substance rather than nothing.
        # MIT 许可，读自随包的 LICENSE 文件，使关于页不会与仓库发布的内容漂移。
        # 没有该文件的打包构建仍显示许可的实质内容而不是空白。
        import os

        candidates = []
        try:
            from gifmanager.core import paths

            root = paths.resources_dir()
            if root:
                # Source layout: <repo>/resources → <repo>/LICENSE.
                # 源码布局：<repo>/resources → <repo>/LICENSE。
                candidates.append(os.path.join(os.path.dirname(root),
                                               "LICENSE"))
                candidates.append(os.path.join(root, "LICENSE"))
        except Exception:
            pass
        for candidate in candidates:
            try:
                if os.path.isfile(candidate):
                    with open(candidate, "r", encoding="utf-8") as handle:
                        text = handle.read().strip()
                    if text:
                        return text
            except OSError:
                continue
        return ("MIT License\n\nCopyright (c) 2026 LwoSnow\n\n"
                "本软件按 MIT 许可发布 / "
                "This software is released under the MIT License.")

    @Property(str, constant=True)
    def version(self):
        return __version__

    # The project's home page, shown on the About page and opened on click.
    #
    # A property rather than a literal in the QML so there is ONE place to change it, and so the
    # packaging metadata can disagree with it in only one spot rather than two.
    # 项目主页，显示在关于页并可点击打开。
    #
    # 用属性而不是 QML 里的字面量，使改动只有"一处"，也让打包元数据即便不一致也只会在一个地方而非
    # 两个地方出现分歧。
    @Property(str, constant=True)
    def repositoryUrl(self):
        return REPOSITORY_URL

    @Slot(str, result=bool)
    def openUrl(self, url):
        # Open a URL in the browser, through the platform layer.
        #
        # The platform layer rather than `QDesktopServices`: opening a URL is an OS action, and
        # `platform/installer.py` is already the one place that knows how each system does it
        # (plus the scheme check that keeps a `file://` URL from turning a link into code
        # execution).
        # 经平台层在浏览器中打开 URL。
        #
        # 用平台层而不是 `QDesktopServices`：打开 URL 是系统动作，而 `platform/installer.py`
        # 已经是唯一知道各系统怎么做的地方（外加方案校验，它防止 `file://` URL 把一次链接点击变成
        # 代码执行）。
        from gifmanager.platform import installer

        result = installer.open_url(str(url or ""))
        if not result.get("ok"):
            self._emit_status(
                self.tr("open_link_failed") + ": " + str(result.get("reason", "")),
                STATUS_NORMAL_MS)
        return bool(result.get("ok"))

    @Property(str, constant=True)
    def platformName(self):
        from gifmanager import platform as platform_layer

        return platform_layer.current().key

    @Property(str, notify=libraryChanged)
    def status(self):
        return self._status

    def _emit_status(self, message, timeout=0):
        self._status = str(message)
        # The property change and the signal both matter: QML reads `status` to render it and
        # listens to `statusMessage` to arm a timeout.
        #
        # `libraryChanged` is emitted here because THAT is the notify signal `status`
        # declares. Without it the value changed in Python while QML kept rendering the old
        # string: a `Property` with `notify=X` re-evaluates its bindings only when X fires,
        # and `statusMessage` is a different signal that QML uses for the timeout only. The
        # symptom was a status bar frozen on whatever it said first — including a count of 0
        # after switching to a group that has stickers.
        #
        # 属性变更与信号都重要：QML 读取 `status` 来渲染，并监听 `statusMessage` 来武装超时。
        #
        # 在此发出 `libraryChanged`，因为那才是 `status` 声明的 notify 信号。没有它时该取值在
        # Python 侧变了而 QML 继续渲染旧字符串：带 `notify=X` 的 `Property` 只在 X 触发时重新
        # 求值其绑定，而 `statusMessage` 是 QML 仅用于超时的另一个信号。症状是状态栏冻结在它最初
        # 显示的内容上——包括切到有贴纸的分组后仍显示 0 个。
        self.libraryChanged.emit()
        self.statusMessage.emit(self._status, int(timeout))

    @Slot(str, int)
    def showStatus(self, message, timeout=STATUS_NORMAL_MS):
        self._emit_status(message, timeout)

    @Slot(str, str, result=str)
    def browseForFile(self, field, current):
        # Open the platform's file chooser for a settings field, and store the result.
        #
        # # Why the dialog lives here and the storage does not
        #
        # `QFileDialog` is a `QtWidgets` class, so it can only be reached from a front-end
        # layer. Returning the chosen path and writing it to the setting keeps the
        # decision ("which field") in QML and the mechanism here, and it means the QML side
        # needs no knowledge of Qt Widgets.
        #
        # # An empty result is not an error
        #
        # Cancelling returns "" and writes NOTHING. Writing "" would silently clear a
        # configured path — a cancel must not be destructive.
        #
        # 为某个设置字段打开平台的文件选择器并存储结果。
        #
        # # 为什么对话框在这里而存储不在
        #
        # `QFileDialog` 是 `QtWidgets` 类，因此只能从前端层到达。返回所选路径并把写入设置留给
        # 调用方，使"选择哪个字段"的决定留在 QML、机制留在此处，也意味着 QML 侧无需了解
        # Qt Widgets。
        #
        # # 空结果不是错误
        #
        # 取消返回 "" 并且"什么都不写"。写 "" 会静默清空一个已配置的路径——取消绝不能有破坏性。
        from PySide6.QtWidgets import QFileDialog

        # The filter is built from the field so a future field with a different file type
        # does not need a new slot. `All files` is always last, because a chooser that
        # hides an executable the user knows exists reads as broken.
        # 过滤器按字段构建，使未来类型不同的字段无需新槽。`All files` 总在最后，因为一个隐藏了
        # 用户明知存在的可执行文件的选择器读起来像坏了。
        if field == "ffmpeg_path":
            filters = self.tr("filter_executables") + ";;" + self.tr("filter_all_files")
        else:
            filters = self.tr("filter_all_files")

        chosen, _selected = QFileDialog.getOpenFileName(
            None, self.tr("choose_file"), current or "", filters)
        chosen = (chosen or "").strip()
        if not chosen:
            self._emit_status(self.tr("no_file_chosen"))
            return ""
        self._settings_model.setValue(field, chosen)
        self._emit_status(self.tr("file_chosen") + ": " + chosen)
        return chosen

    @Slot(str, str, str)
    def requestDialog(self, kind, title, body):
        # Asks QML to present a dialog rather than creating one here: a Qt Widgets
        # dialog would be styled by QSS and would not match the QML interface.
        # 请求 QML 呈现对话框，而不是在此创建：Qt Widgets 对话框会由 QSS 定样式，与 QML
        # 界面不匹配。
        self.dialogRequested.emit(str(kind), str(title), str(body))

    @Slot()
    def importStickers(self):
        # Begin an import into the CURRENT group.
        #
        # Refused rather than attempted when the current group cannot hold images,
        # because the store would return zero imported files and the user would see a
        # silent no-op. QML calls `canImportHere` first to offer a target group
        # instead of a dead button.
        # 向"当前"分组导入。
        #
        # 当前分组放不下图片时明确拒绝而不是尝试，因为存储层会返回导入零个文件，用户会看到
        # 静默的空操作。QML 先调用 `canImportHere` 以提供目标分组选择，而不是一个死按钮。
        if not self.canImportHere():
            self.requestDialog("info", self.tr("import_stickers"),
                               self.tr("import_needs_image_group"))
            return
        self.requestDialog("import", self.tr("import_stickers"), "")

    @Slot(result=bool)
    def canImportHere(self):
        # True when the current view can receive image files.
        #
        # The All view maps to a real group when the library has one, so importing
        # while "All" is selected targets that group rather than being disabled for
        # the most common state a user is in.
        # 当前视图能接收图片文件时为 True。
        #
        # 当图库中存在真实分组时，"全部"视图会映射到那个分组，因此在选中"全部"时导入会
        # 以该分组为目标，而不会因为这是用户最常见的状态而被禁用。
        return self._import_target_group() is not None

    @Slot(result="QVariantList")
    def importTargets(self):
        # Image groups the import can go to. The ALL view is EXCLUDED: it
        # aggregates the other groups and is not a place anything can be stored
        # into — offering it here is what made imports seem to "land in 全部".
        # 导入可去的图片分组。“全部”被排除：它聚合其余分组，不是任何东西的存放地
        # ——把它列在这里正是导入看起来“落进全部”的原因。
        all_id = self._adapter.backend.store._all_group_id()
        return [{"id": group["id"], "name": group["name"]}
                for group in self._adapter.groups()
                if group["type"] == "image" and group["id"] != all_id]

    def _import_target_group(self):
        # The group an import should use.
        #
        # The selected group wins when it can hold images. A selected group that
        # CANNOT hold images is a REFUSAL, not a redirect: the first version fell
        # back to the first image group, so importing while a text group was selected
        # silently wrote the files into an unrelated group. The test caught it —
        # `canImportHere` was true for a text group and the import landed in "全部".
        #
        # The All view is the one case that resolves to another group, because it is
        # not a real group at all: it has no type, and a user sitting in "All" means
        # "the library", so the first image group is the reasonable target.
        #
        # 导入应使用的分组。
        #
        # 选中的分组能放图片时以它为准。选中了"不能"放图片的分组是"拒绝"而非改道：第一版
        # 回退到第一个图片分组，于是在选中文字分组时导入会把文件静默写进一个无关的分组。测试
        # 抓到了它——`canImportHere` 对文字分组返回 true，而导入落进了"全部"。
        #
        # "全部"视图是唯一会解析到其他分组的情形，因为它根本不是真实分组：它没有类型，而用户
        # 停在"全部"意味着"整个图库"，因此第一个图片分组是合理的目标。
        group_id = self._groups.currentId
        if group_id >= 0:
            group = self._adapter.store.get_group(group_id)
            if group is None:
                return None
            return group if group["type"] == "image" else None
        # The All view resolves to the DEFAULT group, not to "the first image group".
        #
        # "All" is an aggregation rather than a place, so an import made while it is selected
        # has to land somewhere real - and the place a user means is the default group, which
        # is the one the library treats as its home. Taking the first group in whatever order
        # the store returns happened to work only while "默认" was also first; renaming or
        # reordering groups silently redirected imports into an unrelated one.
        # "全部"视图解析到"默认"分组，而不是"第一个图片分组"。
        #
        # "全部"是聚合而非存放地，因此在它被选中时发起的导入必须落到某个真实分组——而用户所指的
        # 地方就是默认分组，那是素材库视为归宿的那一个。按存储返回的顺序取第一个分组只在"默认"恰好
        # 也排在第一个时才有效；重命名或重排分组会静默地把导入改道到一个无关分组。
        default_id = self._adapter.store.default_group_id()
        if default_id is not None:
            group = self._adapter.store.get_group(default_id)
            if group is not None and group["type"] == "image":
                return group
        # If the default group is unusable (deleted, or a text group), fall back to the first
        # image group rather than refusing: the user asked to import and there IS a place.
        # 若默认分组不可用（已删除，或是文字分组），回退到第一个图片分组而不是拒绝：用户要求导入，
        # 而确实有地方可放。
        for group in self._adapter.groups():
            if group["type"] == "image":
                return group
        return None

    @Slot("QStringList", result="QVariantMap")
    def importFiles(self, paths):
        return self.importFilesInto(paths, -1)

    @Slot("QStringList", int, result="QVariantMap")
    def importFilesInto(self, paths, group_id):
        # Start an import of the given paths INTO a chosen group. The dialog's
        # picker decides the target; `group_id < 0` falls back to the previous
        # behaviour (the selected group, or the first image group from All).
        # Returns a small report so the caller can tell "refused" from "started".
        # 把给定路径导入"所选分组"。对话框的选择器决定目标；`group_id < 0` 回退为旧
        # 行为（当前分组，或"全部"视图下的第一个图片分组）。返回一份小报告，使调用
        # 方能区分"被拒绝"与"已开始"。
        if group_id is not None and group_id >= 0:
            group = self._adapter.store.get_group(int(group_id))
            if group is None or group["type"] != "image":
                self._emit_status(self.tr("import_needs_image_group"),
                                  STATUS_NORMAL_MS)
                return {"started": False, "reason": "no-group"}
        else:
            group = self._import_target_group()
        if group is None:
            self._emit_status(self.tr("import_needs_image_group"), STATUS_NORMAL_MS)
            return {"started": False, "reason": "no-group"}
        if not paths:
            return {"started": False, "reason": "empty"}
        started = self._importer.start(list(paths), group["id"],
                                      self._adapter.settings.auto_convert_gif)
        if started:
            self._emit_status(
                self._t("import_started",
                        group=self.groupDisplayName(group["id"]),
                        count=len(paths)),
                STATUS_NORMAL_MS)
        return {"started": bool(started), "reason": "" if started else "refused",
                "groupId": group["id"], "groupName": group["name"]}

    @Slot(result=str)
    def importFileFilter(self):
        # The file-dialog filter string, from the same table the importer uses.
        # 文件对话框过滤字符串，来自导入器所用的同一张表。
        return self._importer.filter

    @Slot(int, result=int)
    def currentImportGroupId(self):
        # The group the import dialog should preselect: the one the library is
        # showing when it holds images, otherwise the first image group.
        # 导入对话框应预选的分组：表情库正在显示且能放图片的那个，否则是第一个图片分组。
        group = self._import_target_group()
        return -1 if group is None else int(group["id"])

    @Slot("QUrl", result=str)
    def urlToPath(self, url):
        # A `file://` URL as a filesystem path.
        #
        # QML's dialogs hand back URLs, and passing one straight to the store would
        # make every path look un-importable — the failure mode is "zero files
        # imported", not an error, which is why this conversion is explicit.
        # 把 `file://` URL 转为文件系统路径。
        #
        # QML 的对话框交回 URL，把它直接交给存储层会让每个路径看起来都不可导入——失败形态是
        # "导入零个文件"而不是报错，因此这个转换是显式的。
        if hasattr(url, "toLocalFile"):
            path = url.toLocalFile()
            if path:
                return path
            # A `file://` URL Qt will not map is usually a UNC or a path with a
            # host component; trimming the scheme is the best remaining guess and
            # beats returning an empty string the store would silently skip.
            # 一个 Qt 无法映射的 `file://` URL 通常是 UNC 或带主机名的路径；去掉 scheme 是
            # 余下最好的猜测，也强过返回一个存储层会静默跳过的空字符串。
            text = url.toString()
            return text[7:] if text.startswith("file://") else text
        return str(url or "")

    @Slot(str, result=str)
    def fileNameOf(self, path):
        # The basename, for a compact "you selected this" label.
        # 基名，用于紧凑的"你选择了这个"标签。
        import os

        return os.path.basename(str(path or "").rstrip("/\\")) or str(path or "")

    @Slot(int, result=str)
    def selectedCountLabel(self, count):
        # "N selected", through `_t` rather than `trArgs`.
        #
        # A dedicated slot with a plain `int` argument replaces passing a JSON object
        # to `trArgs` from QML: that call raised "Insufficient arguments" at the call
        # site, and a typed slot cannot fail that way.
        # "已选择 N 项"，经 `_t` 而非 `trArgs`。
        #
        # 用一个参数为普通 `int` 的专用槽，取代从 QML 向 `trArgs` 传 JSON 对象：后者在调用
        # 处抛了 "Insufficient arguments"，而带类型的槽不会以那种方式失败。
        return self._t("import_selected_count", count=int(count))

    @Slot(result="QVariantList")
    def shortcuts(self):
        # Documented key bindings, so the help page and the actual bindings cannot
        # disagree: both read this list. The list names exactly what the QML shell
        # binds — plus the GLOBAL hotkey, whose sequence follows the setting.
        # 已记录的按键绑定，使帮助页与实际绑定不会不一致：两者读取同一列表。列表列出的
        # 恰是 QML 外壳的绑定——外加跟随设置的全局热键。
        rows = [
            {"keys": "Ctrl+F", "label": self.tr("search_placeholder")},
            {"keys": "Ctrl+C", "label": self.tr("copy")},
            {"keys": "Ctrl+A", "label": self.tr("select_all_cards")},
            {"keys": "Delete", "label": self.tr("edit_delete")},
            {"keys": "F1", "label": self.tr("settings")},
            {"keys": "Ctrl+Q", "label": self.tr("quit")},
        ]
        hotkey = getattr(getattr(self, "hotkey", None), "sequence", "") or ""
        if hotkey:
            rows.insert(0, {"keys": hotkey,
                            "label": self.tr("hotkey_group")})
        return rows

    @Property("QVariantList", notify=settingsChanged)
    def shortcutList(self):
        # The same rows as `shortcuts()`, exposed as a NOTIFYING property.
        #
        # The settings window's preview table bound `model: app.shortcuts()`, i.e. a method CALL. A
        # binding that calls a method has no dependency to re-evaluate on, so the table was computed
        # once when the row was built and never updated: changing the global hotkey left the preview
        # showing the old sequence, which is the reported bug.
        #
        # A property with `notify=settingsChanged` gives the binding something to react to, and
        # committing the hotkey already emits that signal.
        # 与 `shortcuts()` 相同的行，但以"带通知"的属性暴露。
        #
        # 设置窗口的预览表绑定的是 `model: app.shortcuts()`，也就是一次"方法调用"。调用方法的绑定没有
        # 可依赖的求值依据，因此该表在行构建时算过一次就再没更新：改掉全局热键后预览仍显示旧序列，
        # 这正是用户报告的缺陷。
        #
        # 带 `notify=settingsChanged` 的属性给了绑定一个可响应的事件，而提交热键本身就会发出该信号。
        return self.shortcuts()

    @Slot(str, "QVariant", result=bool)
    def setSettingNow(self, field, value):
        # Write one setting and apply it IMMEDIATELY, without waiting for 应用/确定.
        #
        # Used by controls whose change has a visible, immediate consequence: the global hotkey (the
        # preview list and the registered key should follow at once) and the colour scheme (the
        # whole
        # window should repaint at once). Drafting those and waiting for a button press means the
        # user
        # sees no feedback and assumes the change was ignored.
        #
        # It goes through `SettingsModel.commitValue`, which applies this single field while leaving
        # any
        # other pending edit untouched.
        # 写入一个设置并"立即"应用，不等"应用/确定"。
        #
        # 供那些改动有可见即时后果的控件使用：全局热键（预览列表与已注册的键都该立刻跟随）与配色方案
        # （整个窗口该立刻重绘）。把它们做成草稿等待按钮，会让用户看不到任何反馈、以为改动被忽略了。
        #
        # 它走 `SettingsModel.commitValue`，只应用这一个字段，不触碰任何其他待定编辑。
        try:
            self._settings_model.commitValue(field, value)
            return True
        except Exception:
            log.exception("settings: applying %r immediately failed", field)
            return False

    # ---- translation / 翻译 ----------------------------------------------

    @Slot(str, result=str)
    def tr(self, key):
        # No `**kwargs`: a PySide6 `Slot` cannot accept keyword arguments from
        # QML, and declaring one would make the slot fail to register. Placeholder
        # substitution goes through `trArgs`.
        # 不接受 `**kwargs`：PySide6 的 `Slot` 无法从 QML 接收关键字参数，声明它会导致
        # 槽注册失败。占位符替换走 `trArgs`。
        return self._adapter.tr(key)

    @Slot(str, str, result=str)
    def trArgs(self, key, arguments):
        # `arguments` is a JSON object of placeholders, which is the portable way to
        # pass a variable set of named arguments through a QML slot.
        # `arguments` 是占位符的 JSON 对象，这是经 QML 槽传递可变具名参数的可移植方式。
        import json

        try:
            kwargs = json.loads(arguments) if arguments else {}
        except (TypeError, ValueError):
            kwargs = {}
        if not isinstance(kwargs, dict):
            kwargs = {}
        try:
            return self._adapter.tr(key, **kwargs)
        except Exception:
            return self._adapter.tr(key)

    @Slot(result=int)
    def currentGroupId(self):
        # The selected group's id, or -1 for the All view.
        #
        # Exposed because QML's `groups.currentId` is the model's own property and the
        # dialogs ask the BRIDGE which group a group operation should target — keeping
        # one answer to that question instead of two that can disagree.
        # 选中分组的 id，"全部"视图时为 -1。
        #
        # 暴露它是因为 QML 的 `groups.currentId` 是模型自身的属性，而对话框向"桥"询问分组操作
        # 应对准哪个分组——让这个问题只有一个答案，而不是两个可能不一致的。
        return int(self._groups.currentId)

    # ---- teardown / 退出 -------------------------------------------------

    @Slot()
    def quit(self):
        app = QGuiApplication.instance()
        if app is not None:
            app.quit()


__all__ = ["BackendBridge", "STATUS_BRIEF_MS", "STATUS_LONG_MS",
           "STATUS_NORMAL_MS"]
