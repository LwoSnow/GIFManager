"""View protocol: what a page in the shell must provide.

A "view" is one place the user can be. The shell owns the window, the navigation
and the status bar; a view owns the content. That split is what lets the settings
page, the library page and an about page exist without the window knowing what
any of them contain.

The protocol is deliberately small. A view declares an id, a title key, and the
commands it contributes; it implements `activate`/`deactivate` so work can be
started and — more importantly — stopped when the user navigates away. The
previous release's window had no notion of "not visible", which is why the grid's
timers kept running while the settings dialog was open.

视图协议：外壳中一个页面必须提供什么。

"视图"是用户可以所在的一个位置。外壳拥有窗口、导航与状态栏；视图拥有内容。这一划分
正是让设置页、表情库页与关于页可以共存、而窗口不知道它们各自包含什么的原因。

协议刻意很小。视图声明 id、标题键以及它贡献的命令；它实现
`activate`/`deactivate`，使工作可以开始，更重要的是在用户离开时"停止"。此前版本的
窗口没有"不可见"的概念，这正是设置对话框打开时网格定时器仍在运行的原因。
"""
import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget

log = logging.getLogger("GIFManager")


class View(QWidget):
    # Base class for a shell page.
    #
    # Subclasses set `VIEW_ID` and `TITLE_KEY` and implement `activate`. The
    # default implementations of everything else are intentional no-ops so a
    # simple page only writes the parts it needs.
    # 外壳页面的基类。
    #
    # 子类设置 `VIEW_ID` 与 `TITLE_KEY` 并实现 `activate`。其余方法的默认实现刻意是
    # 空操作，使简单页面只需编写它需要的部分。

    # Stable identifier used by navigation, settings and diagnostics /
    # 供导航、设置与诊断使用的稳定标识
    VIEW_ID = "view"

    # Translation key for the view's title / 视图标题的翻译键
    TITLE_KEY = ""

    # Translation key for the navigation entry, when it differs from the title /
    # 导航条目的翻译键（与标题不同时使用）
    NAV_KEY = ""

    # Emitted when the view wants the shell to show a message /
    # 视图希望外壳显示一条消息时发出
    status_message = Signal(str, int)

    # Emitted when the view's content changed the library, so the shell can
    # refresh anything that mirrors it. Views that never mutate do not emit.
    # 视图内容改动了库时发出，使外壳刷新任何镜像它的部分。从不改动的视图不会发出。
    library_changed = Signal()

    def __init__(self, adapter, parent=None):
        super().__init__(parent)
        self._adapter = adapter
        self._active = False

    # ---- identity / 标识 -------------------------------------------------

    @property
    def adapter(self):
        return self._adapter

    def view_id(self):
        return self.VIEW_ID

    def title_key(self):
        return self.TITLE_KEY or self.VIEW_ID

    def title(self):
        return self._adapter.tr(self.title_key())

    def nav_key(self):
        return self.NAV_KEY or self.title_key()

    # ---- lifecycle / 生命周期 -------------------------------------------

    def activate(self):
        # Called when the view becomes visible. Start timers, begin playback,
        # refresh from the backend — whatever the view needs to be live.
        #
        # The body is `return None` rather than `pass`: an explicit statement
        # documents that doing nothing is the intended default, and a body that
        # holds only a comment is an IndentationError rather than a no-op.
        # 视图变为可见时调用。启动定时器、开始播放、从后端刷新——视图活跃所需的一切。
        #
        # 函数体是 `return None` 而非 `pass`：显式语句说明"什么都不做"就是预期的默认
        # 行为，而只有注释的函数体是 IndentationError 而不是空操作。
        return None

    def deactivate(self):
        # Called when the view stops being visible.
        #
        # This is the hook the previous release lacked: a page must be able to
        # stop its timers and animations, or a background page keeps consuming
        # CPU and holding file handles.
        # 视图不再可见时调用。
        #
        # 这正是此前版本缺失的钩子：页面必须能停止自己的定时器与动画，否则后台页面会
        # 持续消耗 CPU 并占住文件句柄。
        return None

    @property
    def is_active(self):
        return self._active

    def set_active(self, active):
        # Managed by the shell; not meant to be overridden. Subclasses implement
        # `activate`/`deactivate` instead, so the flag and the hook cannot get out
        # of step.
        # 由外壳管理，不应被覆写。子类改为实现 `activate`/`deactivate`，使标志与钩子
        # 不会不同步。
        active = bool(active)
        if active == self._active:
            return
        self._active = active
        try:
            if active:
                self.activate()
            else:
                self.deactivate()
        except Exception:
            log.exception("view %s: lifecycle hook failed", self.view_id())

    # ---- commands / 命令 -------------------------------------------------

    def commands(self):
        # Commands this view contributes to the registry.
        #
        # Returned as a list of `commands.Command`. The shell registers them when
        # the view is created, so every action a page offers is discoverable from
        # one place.
        # 本视图贡献给注册表的命令。
        #
        # 返回 `commands.Command` 列表。外壳在创建视图时注册它们，因此页面提供的每个
        # 操作都能从一处被发现。
        return ()

    def state(self):
        # Snapshot used by command availability predicates. A plain mapping, so a
        # predicate never reaches into widget internals.
        # 供命令可用性谓词使用的快照。使用普通映射，使谓词无需伸手进控件内部。
        return {}

    # ---- presentation / 呈现 ---------------------------------------------

    def retranslate(self):
        # Re-apply translated text after a language change. A view with no
        # translatable text of its own keeps this no-op.
        # 语言变更后重新应用已翻译文本。自身没有可翻译文本的视图保持此空操作。
        return None

    def apply_settings(self, settings, changed):
        # Adopt settings that changed, whether or not this view is visible.
        #
        # Called on EVERY view, not only the active one: a hidden view keeps its
        # widgets alive, so a grid that ignored the change would render stale
        # state the moment the user navigated back to it. `changed` is the set of
        # field names the shell computed, so a view can skip work that does not
        # concern it.
        # 采用已变更的设置，无论本视图是否可见。
        #
        # 对"每个"视图调用，而不只是活跃的那个：隐藏的视图仍持有其控件，因此忽略变更的
        # 网格会在用户导航回来的瞬间渲染过期状态。`changed` 是外壳算出的字段名集合，
        # 使视图可以跳过与己无关的工作。
        return None

    def can_close(self):
        # Asked before the shell closes this view's window, so a view with
        # unsaved work can refuse.
        # 外壳关闭承载本视图的窗口前询问，使有未保存工作的视图可以拒绝。
        return True

    def shutdown(self):
        # Called once at application exit, after `deactivate` /
        # 应用退出时调用一次，在 `deactivate` 之后
        self.deactivate()


class PlaceholderView(View):
    # A view that only shows a message and, optionally, what is planned for it.
    #
    # Used for a page that is declared in the navigation but not implemented yet,
    # so the shell is complete and honest instead of hiding the gap: the user sees
    # what is planned and which backend interface it will call.
    #
    # `view_id` and `title_key` are CONSTRUCTOR arguments rather than class
    # attributes, because two placeholder pages must be able to coexist with
    # different ids. Overriding the class attribute on an instance does not work:
    # the shell keys its registry by `view_id()`, so both pages would land on the
    # same key and the second would silently replace the first.
    # 仅显示一条消息、并可选说明其计划的视图。
    #
    # 用于已在导航中声明但尚未实现的页面，使外壳保持完整且诚实，而不是掩盖缺口：用户
    # 能看到计划了什么、以及它将调用哪个后端接口。
    #
    # `view_id` 与 `title_key` 是"构造参数"而非类属性，因为两个占位页必须能以不同的
    # id 共存。在实例上覆盖类属性是行不通的：外壳按 `view_id()` 作注册键，两个页面会
    # 落到同一个键上，后一个会静默替换前一个。
    VIEW_ID = "placeholder"
    TITLE_KEY = "placeholder"

    def __init__(self, adapter, message="", planned="", view_id=None,
                 title_key=None, parent=None):
        super().__init__(adapter, parent)
        self._view_id = view_id or self.VIEW_ID
        self._title_key = title_key or self.TITLE_KEY
        self._message = message
        self._planned = planned
        self._layout = None
        self._title_label = None
        self._detail_label = None
        self._build()

    def _build(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel, QVBoxLayout

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)
        layout.addStretch(1)

        self._title_label = QLabel(self._message)
        self._title_label.setWordWrap(True)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setObjectName("placeholderTitle")
        layout.addWidget(self._title_label)

        if self._planned:
            self._detail_label = QLabel(self._planned)
            self._detail_label.setWordWrap(True)
            self._detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._detail_label.setObjectName("placeholderDetail")
            layout.addWidget(self._detail_label)
        layout.addStretch(1)
        self._layout = layout

    def view_id(self):
        return self._view_id

    def title_key(self):
        return self._title_key

    def nav_key(self):
        return self._title_key


__all__ = ["PlaceholderView", "View"]
