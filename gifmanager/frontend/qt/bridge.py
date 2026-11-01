"""Qt adapter over the toolkit-free backend.

The backend notifies subscribers through plain callbacks, which may arrive on a
worker thread. Qt widgets may only be touched from the GUI thread, so this
adapter re-emits every notification as a queued signal. That single rule is what
lets the backend stay toolkit-free while the shell stays thread-safe.

Compatibility note: the widgets ported from the previous release still call
`data_manager`-style methods (`get_all_emojis`, `reorder_group`, ...). Rather
than rewrite them all at once, `BackendAdapter` forwards unknown attribute
access to the backend's store, so the two naming generations coexist while the
migration is incremental. A front-end written from scratch should call
`backend` directly.

Qt 侧对无工具包后端的适配器。

后端通过普通回调通知订阅者，而回调可能来自工作线程。Qt 控件只能在界面线程被访问，
因此本适配器把每条通知重新以队列信号发出。正是这一条规则让后端保持与工具包无关，
同时让外壳保持线程安全。

兼容说明：从上一版本移植来的控件仍会调用 `data_manager` 风格的方法
（`get_all_emojis`、`reorder_group` 等）。与其一次全部重写，`BackendAdapter` 把
未知属性访问转发给后端的存储，使两代命名在迁移期间共存。全新编写的前端应直接调用
`backend`。
"""
from PySide6.QtCore import QObject, Signal

from gifmanager.core import settings as settings_model

# Notification kinds re-emitted as Qt signals /
# 以 Qt 信号重新发出的通知类型
_KIND_SIGNALS = {}


class BackendAdapter(QObject):
    # One Qt object fronting the backend for the whole application.
    # 为整个应用充当后端门面的单个 Qt 对象。

    # (kind, payload) for every backend notification /
    # 每条后端通知的 (类型, 载荷)
    backend_changed = Signal(str, object)
    # Convenience mirrors so a widget can connect without decoding the kind /
    # 便捷镜像信号，使控件无需解析类型即可连接
    library_changed = Signal()
    settings_changed = Signal(object)
    language_changed = Signal(str)

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self._backend = backend
        self._unsubscribe = backend.subscribe(self._on_backend_notification)

    # ---- backend plumbing / 后端接线 -------------------------------------

    @property
    def backend(self):
        return self._backend

    @property
    def store(self):
        # The data store, under the name newer code uses. A property rather than
        # a forwarded attribute, so a misspelling such as `adapter.store.store`
        # reports the mistake against this object instead of recursing into the
        # backend's store and blaming the wrong type.
        # 数据存储，使用较新代码中的名称。做成属性而非转发的属性，使像
        # `adapter.store.store` 这样的笔误会针对本对象报错，而不是递归进后端的存储
        # 并归罪于错误的类型。
        return self._backend.store

    @property
    def data_manager(self):
        # Compatibility alias: the ported widgets took a `data_manager`
        # argument and stored it as `self._dm`. Handing them the store keeps
        # their existing call sites working unchanged.
        # 兼容别名：移植来的控件接收 `data_manager` 参数并保存为 `self._dm`。把存储
        # 交给它们，使既有的调用点无需改动即可工作。
        return self._backend.store

    def _on_backend_notification(self, kind, payload):
        # Runs on whichever thread performed the mutation. The signal
        # connection is automatic, and this object lives on the GUI thread, so
        # Qt queues the emission and the slots run on the GUI thread.
        # 在"执行变更的那个线程"上运行。信号连接为自动，而本对象位于界面线程，因此
        # Qt 会把发射排队，槽在界面线程执行。
        self.backend_changed.emit(kind, payload)
        if kind == "library":
            self.library_changed.emit()
        elif kind == "settings":
            self.settings_changed.emit(payload)
        elif kind == "language":
            self.language_changed.emit(str(payload or ""))

    def detach(self):
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    # ---- settings forwarders / 设置转发 ----------------------------------

    @property
    def settings(self):
        return self._backend.settings

    def apply_settings(self, new_settings, persist=True):
        return self._backend.apply_settings(new_settings, persist=persist)

    def load_settings(self):
        return self._backend.load_settings()

    def save_session(self, window_geometry=None, last_group_name=None):
        return self._backend.save_session(window_geometry, last_group_name)

    def supports(self, capability):
        return self._backend.supports(capability)

    def platform_report(self, refresh=False):
        return self._backend.platform_report(refresh=refresh)

    # ---- library forwarders / 库转发 -------------------------------------

    def groups(self):
        return self._backend.groups()

    def is_all_group(self, group_id):
        return self._backend.is_all_group(group_id)

    def stats(self, group_id=None, keyword=""):
        return self._backend.stats(group_id, keyword)

    def view(self, group_id=None, keyword=""):
        return self._backend.view(group_id, keyword)

    def notify_library_changed(self):
        # Called by a widget after a mutation it performed directly on the
        # store, so other subscribers still hear about it.
        # 控件在直接对存储执行变更后调用，使其他订阅者仍能收到通知。
        self._backend.notify("library", None)

    # ---- translation forwarders / 翻译转发 -------------------------------

    def tr(self, key, **kwargs):
        return self._backend.tr(key, **kwargs)

    def set_language(self, code):
        return self._backend.set_language(code)

    def available_languages(self):
        return self._backend.available_languages()

    # ---- transitional attribute forwarding / 过渡期属性转发 --------------

    def __getattr__(self, name):
        # Forward anything not defined here to the store, which is what the
        # ported widgets expect under the name `data_manager`.
        #
        # `__getattr__` runs solely when normal lookup has already failed, so a
        # partially built adapter raises AttributeError instead of looping.
        # 此处未定义的名称一律转发给存储——移植来的控件期望以 `data_manager`
        # 之名拿到的正是它。
        #
        # 下划线开头的名称同样转发，因为其中一些是事实上的公开接口：
        # `group_list` 与旧主窗口都调用 `_all_group_id()`。
        # `__getattr__` 仅在正常查找失败后运行，因此构建到一半的适配器会抛
        # AttributeError 而不是循环。
        backend = self.__dict__.get("_backend")
        if backend is None:
            raise AttributeError(name)
        return getattr(backend.store, name)

    def __dir__(self):
        return sorted(set(super().__dir__) | set(dir(self._backend.store)))


def current_platform_key():
    # The `sys.platform` value the platform layer resolved for this process.
    #
    # Read from the platform layer rather than from `sys` so exactly one module
    # in the project decides "which system am I on", and so a test can describe
    # a binding for another platform without touching `sys.platform`.
    # 平台层为本进程解析出的 `sys.platform` 取值。
    #
    # 从平台层读取而非从 `sys` 读取，使全项目只有一个模块决定"我在哪个系统上"，也使
    # 测试无需触碰 `sys.platform` 即可描述另一平台的绑定。
    from gifmanager import platform as platform_layer

    return platform_layer.current().key


def describe_hotkey(binding):
    # Human-readable form of a hotkey for the running system /
    # 某热键在当前系统上的人类可读形式
    return binding.describe(current_platform_key())


def theme_stylesheet(theme_name):
    # Stylesheet for a theme name, defaulting to dark /
    # 某主题名对应的样式表，默认深色
    from gifmanager.frontend.qt.theme import STYLESHEETS

    return STYLESHEETS.get(theme_name, STYLESHEETS["dark"])


def apply_theme(app, theme_name):
    # Apply a theme to the QApplication and return the name actually used /
    # 把主题应用到 QApplication 并返回实际使用的名称
    name = theme_name if theme_name in settings_model.THEMES else settings_model.THEME_DARK
    app.setStyleSheet(theme_stylesheet(name))
    return name


__all__ = [
    "BackendAdapter",
    "apply_theme",
    "current_platform_key",
    "describe_hotkey",
    "theme_stylesheet",
]
