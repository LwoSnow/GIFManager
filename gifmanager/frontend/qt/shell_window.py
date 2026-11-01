"""Application shell: navigation, menu bar, keyboard shortcuts, status bar.

The shell owns everything that is about the APPLICATION rather than about a
particular page: the window frame, the navigation list, the menu bar and its
shortcuts, the status bar, and the ordered shutdown. A page only owns its own
content.

Two consequences worth stating, because they are the reason for the split:

* **Every action is reachable three ways** — menu, keyboard and command palette —
  and all three go through one `CommandRegistry`, so they cannot disagree about
  whether an action is available.
* **A page can be left.** `deactivate()` is called on navigation, which is what
  lets the library page stop its decode pools and timers instead of running them
  behind the settings page.

应用外壳：导航、菜单栏、键盘快捷键、状态栏。

外壳拥有"属于应用"而非"属于某个页面"的一切：窗口框、导航列表、菜单栏及其快捷键、
状态栏，以及有序退出。页面只拥有自己的内容。

有两点值得说明，因为它们正是这一划分的理由：

* **每个操作都有三条到达路径**——菜单、键盘与命令面板——而三者都经同一个
  `CommandRegistry`，因此它们不可能对"某操作是否可用"产生分歧。
* **页面可以被离开。** 导航时会调用 `deactivate()`，这正是让表情库页在设置页背后
  停止其解码池与定时器、而不是继续运行的原因。

Not ported yet, and the interface each will call: the system tray
(`platform.window().set_skip_taskbar`), global hotkeys
(`platform.hotkeys().register` with `core.hotkeys.HotkeyBinding`), auto-input paste
(`platform.input_backend()`), autostart (`platform.autostart().set_enabled`), the
GPU preference editor (`platform.gpu_preference()` plus `core.gpu.classify_adapter`),
the in-place updater (`core.version`), and the file pickers for import
(`store.import_emojis_batch` already implements the pipeline).

尚未移植的功能，以及各自将要调用的接口：系统托盘
（`platform.window().set_skip_taskbar`）、全局热键（`platform.hotkeys().register`
配合 `core.hotkeys.HotkeyBinding`）、自动输入粘贴（`platform.input_backend()`）、
开机自启（`platform.autostart().set_enabled`）、GPU 首选项编辑器
（`platform.gpu_preference()` 配合 `core.gpu.classify_adapter`）、就地更新
（`core.version`），以及导入用的文件选择器
（`store.import_emojis_batch` 已实现流水线）。
"""
import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from gifmanager import APP_NAME, __version__
from gifmanager.core import constants
from gifmanager.frontend.qt import commands as cmd
from gifmanager.frontend.qt.bridge import apply_theme
from gifmanager.frontend.qt.views.base import PlaceholderView
from gifmanager.frontend.qt.views.library import LibraryView
from gifmanager.frontend.qt.views.settings import SettingsView

log = logging.getLogger("GIFManager")

# Width of the navigation column / 导航栏宽度
NAV_WIDTH = 168

# Status messages that carry a timeout / 带超时的状态消息
DEFAULT_STATUS_TIMEOUT_MS = 4000


class ShellWindow(QWidget):
    # The main application window.
    #
    # A plain `QWidget` rather than a `QMainWindow`: the shell composes the menu
    # bar, the navigation and a stacked content area itself, and a `QMainWindow`
    # would impose its own dock/toolbar model on top of that composition.
    # 主应用窗口。
    #
    # 用普通 `QWidget` 而非 `QMainWindow`：外壳自行组合菜单栏、导航与堆叠内容区，而
    # `QMainWindow` 会在这一组合之上强加它自己的停靠/工具栏模型。
    APP_TITLE = APP_NAME

    def __init__(self, adapter, parent=None):
        super().__init__(parent)
        self._adapter = adapter
        self.settings = adapter.settings
        self._views = {}
        self._nav_items = {}
        self._registry = cmd.CommandRegistry()
        self._current_view_id = None
        self._pending_geometry = self.settings.window_geometry

        self.setWindowTitle(f"{self.APP_TITLE} {__version__}")
        self.setMinimumSize(constants.MIN_WINDOW_WIDTH, constants.MIN_WINDOW_HEIGHT)

        self._build_views()
        self._register_shell_commands()
        self._build_ui()
        self._build_shortcuts()
        self._connect_signals()
        self._restore_geometry()
        self.retranslate()
        self.navigate(self._initial_view_id())

    # ---- construction / 构建 --------------------------------------------

    def _build_views(self):
        # Views are constructed eagerly but only the visible one is ACTIVE.
        # Eager construction keeps navigation instant; laziness is not needed
        # because a page's expensive work happens in `activate`, not in `__init__`.
        # 视图及早构建，但只有可见的那个是"活跃"的。及早构建使导航瞬时完成；不需要
        # 惰性，因为页面的昂贵工作在 `activate` 而非 `__init__` 中发生。
        library = LibraryView(self._adapter, self)
        library.attach_registry(self._registry)
        self.add_view(library)

        settings = SettingsView(self._adapter, self)
        self.add_view(settings)
        # The settings page reports edits and the shell owns persistence and
        # re-rendering, so the page never touches application state itself.
        # 设置页上报编辑，而外壳负责持久化与重新渲染，因此该页面本身从不触碰应用状态。
        settings.settings_edited.connect(self.apply_settings)

        self.add_view(PlaceholderView(
            self._adapter,
            message=self._adapter.tr("about_text"),
            planned=f"{self.APP_TITLE} {__version__} — MIT",
            view_id="about", title_key="about",
            parent=self))

        # Register each view's contributed commands /
        # 注册每个视图贡献的命令
        for view in self._views.values():
            self._registry.register_all(view.commands())

    def add_view(self, view):
        # Ordered by insertion, which is the navigation order /
        # 按插入顺序，即导航顺序
        self._views[view.view_id()] = view
        return view

    def _register_shell_commands(self):
        self._registry.register_all([
            cmd.define(
                cmd.CMD_NAV_LIBRARY, "all_group",
                lambda: self.navigate("library"),
                shortcut="Ctrl+1",
                surfaces=(cmd.SURFACE_MENU, cmd.SURFACE_PALETTE)),
            cmd.define(
                cmd.CMD_NAV_SETTINGS, "settings",
                lambda: self.navigate("settings"),
                shortcut="Ctrl+2",
                surfaces=(cmd.SURFACE_MENU, cmd.SURFACE_PALETTE)),
            cmd.define(
                cmd.CMD_NAV_ABOUT, "about",
                lambda: self.navigate("about"),
                surfaces=(cmd.SURFACE_MENU, cmd.SURFACE_PALETTE)),
            cmd.define(
                cmd.CMD_TOGGLE_THEME, "theme_group", self.toggle_theme,
                surfaces=(cmd.SURFACE_MENU, cmd.SURFACE_PALETTE)),
            cmd.define(
                cmd.CMD_SHOW_SHORTCUTS, "shortcuts", self.show_shortcuts,
                shortcut="F1",
                surfaces=(cmd.SURFACE_MENU, cmd.SURFACE_PALETTE)),
            cmd.define(
                cmd.CMD_CLEAR_LOGS, "clear_logs", self.clear_logs,
                surfaces=(cmd.SURFACE_MENU, cmd.SURFACE_PALETTE)),
            cmd.define(
                cmd.CMD_QUIT, "quit", self.close,
                shortcut="Ctrl+Q",
                surfaces=(cmd.SURFACE_MENU, cmd.SURFACE_PALETTE)),
            # A selection-wide select-all lives on the library view but is driven
            # from a shell shortcut, which is exactly the case the registry
            # exists for.
            # 全选作用于表情库视图，但由外壳快捷键驱动——这正是注册表存在的意义。
            cmd.define(
                cmd.CMD_SELECT_ALL, "select_all", self.select_all,
                shortcut="Ctrl+A",
                surfaces=(cmd.SURFACE_MENU, cmd.SURFACE_PALETTE)),
            cmd.define(
                cmd.CMD_TOGGLE_EDIT_MODE, "edit_select_all",
                self.toggle_edit_mode, shortcut="Ctrl+E",
                surfaces=(cmd.SURFACE_MENU, cmd.SURFACE_PALETTE)),
        ])

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_menu_bar())
        outer.addWidget(self._build_body(), 1)

        self.status_bar = QStatusBar(self)
        outer.addWidget(self.status_bar)

    def _build_menu_bar(self):
        # A plain widget holding buttons, not a real QMenuBar: the window is
        # frameless, and a native menu bar would draw outside it.
        # 一个装按钮的普通控件，而非真正的 QMenuBar：窗口是无边框的，原生菜单栏会画到
        # 它外面。
        from PySide6.QtWidgets import QPushButton

        bar = QWidget(self)
        bar.setObjectName("shellMenuBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(6)

        title = QLabel(self.APP_TITLE)
        title.setObjectName("shellTitle")
        layout.addWidget(title)
        layout.addSpacing(10)

        self._menu_buttons = {}
        for name, key, surface in (
                ("file", "file_menu", cmd.SURFACE_MENU),
                ("edit", "edit_menu", cmd.SURFACE_MENU),
                ("view", "view_menu", cmd.SURFACE_MENU),
                ("help", "help_menu", cmd.SURFACE_MENU)):
            button = QPushButton()
            button.setObjectName("shellMenuButton")
            button.setFlat(True)
            button.clicked.connect(
                lambda _checked=False, k=key: self._open_command_menu(
                    self.sender(), k))
            layout.addWidget(button)
            self._menu_buttons[key] = button

        layout.addStretch(1)

        self._palette = QLineEdit()
        self._palette.setObjectName("shellPalette")
        self._palette.setClearButtonEnabled(True)
        self._palette.returnPressed.connect(self._run_palette_command)
        layout.addWidget(self._palette)

        return bar

    def _build_body(self):
        body = QWidget(self)
        layout = QHBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._nav = QListWidget(self)
        self._nav.setObjectName("shellNav")
        self._nav.setFixedWidth(NAV_WIDTH)
        self._nav.currentRowChanged.connect(self._on_nav_row_changed)
        layout.addWidget(self._nav)

        self._stack = QStackedWidget(self)
        for view in self._views.values():
            self._stack.addWidget(view)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, view.view_id())
            self._nav.addItem(item)
            self._nav_items[view.view_id()] = item
        layout.addWidget(self._stack, 1)

        return body

    def _build_shortcuts(self):
        # Shortcuts come from the registry, so a command's documented key and its
        # actual binding cannot drift apart.
        # 快捷键来自注册表，因此命令所记录的按键与实际绑定不会脱节。
        self._shortcut_actions = []
        for command in self._registry.all():
            if not command.shortcut:
                continue
            action = QAction(self)
            action.setShortcut(QKeySequence(command.shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            action.triggered.connect(
                lambda _checked=False, cid=command.id: self._invoke(cid))
            self.addAction(action)
            self._shortcut_actions.append(action)

    def _connect_signals(self):
        self._adapter.language_changed.connect(self._on_language_changed)
        # Settings can be changed by ANY presenter — a menu item, a shortcut, the
        # command palette, a future settings page — so the shell subscribes to the
        # change rather than relying on whichever presenter remembered to call
        # `apply_settings`. Without this, toggling the theme from the command
        # palette changed the stored setting but left the old stylesheet on
        # screen.
        # 设置可以被"任何"呈现方改动——菜单项、快捷键、命令面板、将来的设置页——因此
        # 外壳订阅该变更，而不是依赖某个记得调用 `apply_settings` 的呈现方。缺少它时，
        # 从命令面板切换主题会改掉存储的设置却把旧样式表留在屏幕上。
        self._adapter.settings_changed.connect(self._on_settings_changed)
        for view in self._views.values():
            view.status_message.connect(self.show_status)

    def _on_settings_changed(self, changed):
        self._adapter.load_settings()
        self.settings = self._adapter.settings
        self._reapply_settings(changed or ())

    def _reapply_settings(self, changed):
        # Re-render only what the changed fields affect, so an unrelated setting
        # does not force a stylesheet reparse or a grid rebuild.
        #
        # Every view is told, not only the visible one: a hidden view still owns
        # live widgets, so a grid that ignored a card-scale change would come back
        # showing the old size.
        # 只重新渲染受影响的部分，使无关设置不会强制重新解析样式表或重建网格。
        #
        # 会通知"每个"视图，而不只是可见的那个：隐藏的视图仍持有活动控件，因此忽略卡片
        # 缩放变更的网格在切回来时会显示旧尺寸。
        if not changed or "theme" in changed:
            apply_theme(self._app(), self.settings.theme)
        if not changed or "language" in changed:
            self.retranslate()
        for view in self._views.values():
            try:
                view.apply_settings(self.settings, changed)
            except Exception:
                log.exception("shell: view %s failed to apply settings",
                              view.view_id())
        self._refresh_actions()

    # ---- navigation / 导航 -----------------------------------------------

    def navigate(self, view_id):
        # Switch to a view, deactivating the previous one.
        #
        # The deactivation is the point: a hidden page must stop its timers,
        # animations and file handles rather than keep running behind the visible
        # one.
        # 切换到某视图，并停用前一个。
        #
        # 停用正是关键：隐藏的页面必须停止其定时器、动画与文件句柄，而不是在可见页面
        # 背后继续运行。
        if view_id not in self._views:
            log.warning("shell: no such view %r", view_id)
            return False
        previous = self._views.get(self._current_view_id)
        if previous is not None and previous.view_id() != view_id:
            previous.set_active(False)
        self._current_view_id = view_id
        view = self._views[view_id]
        self._stack.setCurrentWidget(view)
        item = self._nav_items.get(view_id)
        if item is not None:
            row = self._nav.row(item)
            if row != self._nav.currentRow():
                self._nav.blockSignals(True)
                self._nav.setCurrentRow(row)
                self._nav.blockSignals(False)
        view.set_active(True)
        self._refresh_actions()
        return True

    def _on_nav_row_changed(self, row):
        if row < 0:
            return
        item = self._nav.item(row)
        if item is None:
            return
        self.navigate(item.data(Qt.ItemDataRole.UserRole))

    @property
    def current_view(self):
        return self._views.get(self._current_view_id)

    @property
    def library(self):
        # The library view, by name.
        #
        # Named accessors for the views that other code needs are deliberately
        # narrow: anything that reaches through the shell to a view's internals is
        # a sign the operation belongs on the view, and a single obvious accessor
        # makes those reaches countable.
        # 按名称取表情库视图。
        #
        # 其他代码需要的视图有刻意很窄的具名访问器：任何"穿过外壳去够视图内部"的写法
        # 都说明该操作应属于视图，而单一的明显访问器让这类伸手可被计数。
        return self._views.get("library")

    def view(self, view_id):
        return self._views.get(view_id)

    def current_state(self):
        # Merged view state, so a command predicate can be about "the
        # application" without knowing which page is showing.
        # 合并后的视图状态，使命令谓词可以针对"整个应用"而不必知道当前显示哪一页。
        state = {"view": self._current_view_id}
        view = self.current_view
        if view is not None:
            state.update(view.state())
        return state

    def _initial_view_id(self):
        return "library"

    # ---- commands / 命令 -------------------------------------------------

    def _invoke(self, command_id):
        return self._registry.invoke(command_id, self.current_state())

    def _open_command_menu(self, anchor, _key):
        # Menus are generated from the registry. The grouping below is a fixed
        # partition of command ids, which keeps "which menu is this in" explicit
        # instead of implied by the order of `addAction` calls.
        # 菜单由注册表生成。下面的分组是命令 id 的固定划分，使"某命令属于哪个菜单"是
        # 显式的，而不是由 `addAction` 调用顺序隐含。
        groups = {
            "file_menu": (cmd.CMD_IMPORT, cmd.CMD_CONVERT_LIBRARY,
                          cmd.CMD_CLEAR_LOGS, None, cmd.CMD_QUIT),
            "edit_menu": (cmd.CMD_SELECT_ALL, cmd.CMD_TOGGLE_EDIT_MODE,
                          cmd.CMD_DELETE_SELECTED),
            "view_menu": (cmd.CMD_TOGGLE_THEME, cmd.CMD_CARD_SCALE_UP,
                          cmd.CMD_CARD_SCALE_DOWN, cmd.CMD_CARD_SCALE_RESET,
                          cmd.CMD_TOGGLE_NAME, None, cmd.CMD_NAV_LIBRARY,
                          cmd.CMD_NAV_SETTINGS),
            "help_menu": (cmd.CMD_SHOW_SHORTCUTS, cmd.CMD_NAV_ABOUT),
        }
        # Resolve the label through the button that opened the menu, so the
        # partition above and the button list cannot disagree about which key
        # belongs to which menu.
        # 通过打开菜单的按钮解析标签，使上面的划分与按钮列表不会对"哪个键属于哪个菜单"
        # 产生分歧。
        key = None
        for name, button in self._menu_buttons.items():
            if button is anchor:
                key = name
                break
        menu = QMenu(self)
        state = self.current_state()
        for command_id in groups.get(key, ()):
            if command_id is None:
                menu.addSeparator()
                continue
            command = self._registry.get(command_id)
            if command is None:
                continue
            label = self._adapter.tr(command.label_key)
            if command.shortcut:
                label = f"{label}\t{command.shortcut}"
            action = menu.addAction(label)
            action.setEnabled(command.is_enabled(state))
            action.triggered.connect(
                lambda _checked=False, cid=command_id: self._invoke(cid))
        if menu.isEmpty():
            return
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _run_palette_command(self):
        # Run the first palette entry matching the typed text /
        # 运行第一条匹配输入文本的命令面板条目
        text = self._palette.text()
        matches = self._registry.search(text)
        if not matches:
            self.show_status(self._adapter.tr("no_command_match"), 3000)
            return
        self._invoke(matches[0].id)
        self._palette.clear()

    def _refresh_actions(self):
        # Re-evaluate every menu label and enablement after a navigation or a
        # selection change.
        # 导航或选择变化后重新求值每个菜单标签与启用状态。
        view = self.current_view
        if view is not None:
            view.retranslate()

    # ---- shell actions / 外壳操作 ----------------------------------------

    def select_all(self):
        view = self.current_view
        grid = getattr(view, "_grid", None)
        if grid is None:
            return False
        count = grid.select_all()
        self.show_status(
            self._adapter.tr("emoji_count", group=self._adapter.tr("select_all"),
                             count=count, total=count), 2000)
        return count > 0

    def toggle_edit_mode(self):
        view = self.current_view
        grid = getattr(view, "_grid", None)
        if grid is None:
            return False
        if grid.selection_count():
            grid.clear_selection()
            self.show_status(self._adapter.tr("edit_select_all") + " \u2717", 1500)
        else:
            grid.select_all()
        self._refresh_actions()
        return True

    def toggle_theme(self):
        # The whole settings object is re-derived rather than mutated in place, so
        # the coercion and clamping in `core.settings` apply to a runtime change
        # exactly as they do to a stored one.
        # 整体重新派生设置对象而不是就地修改，使 `core.settings` 中的强制转换与钳制对
        # 运行时变更的作用与对已存储取值的作用完全一致。
        from gifmanager.core import settings as settings_model

        target = "light" if self.settings.theme == "dark" else "dark"
        updated = settings_model.from_mapping(
            {**settings_model.to_mapping(self.settings), "theme": target})
        self.apply_settings(updated)
        return True

    def show_shortcuts(self):
        rows = []
        for command in self._registry.all():
            if not command.shortcut:
                continue
            rows.append(f"{self._adapter.tr(command.label_key)}\t"
                        f"{command.shortcut}")
        body = "\n".join(sorted(rows)) or self._adapter.tr("shortcuts_empty")
        QMessageBox.information(self, self._adapter.tr("shortcuts"), body)
        return True

    def clear_logs(self):
        from gifmanager.core import logging_setup

        removed = logging_setup.clear_logs()
        log.info("cleared %s log files", removed)
        QMessageBox.information(
            self, self._adapter.tr("clear_logs"),
            self._adapter.tr("logs_cleared", count=removed))
        return True

    # ---- settings / 设置 -------------------------------------------------

    def apply_settings(self, new_settings):
        # Adopt a settings object supplied by an editor.
        #
        # The re-rendering itself lives in `_reapply_settings`, which is also what
        # the adapter's `settings_changed` notification drives, so a change made
        # through this method and one made through a command both end up in the
        # same place.
        # 采用由编辑器提供的设置对象。
        #
        # 重新渲染本身位于 `_reapply_settings`，它同时也是适配器 `settings_changed`
        # 通知所驱动的逻辑，因此经本方法做的改动与经命令做的改动最终走到同一处。
        changed = self._adapter.apply_settings(new_settings)
        self.settings = self._adapter.settings
        self._reapply_settings(changed)
        return changed

    def _app(self):
        from PySide6.QtWidgets import QApplication

        return QApplication.instance()

    # ---- presentation / 呈现 ---------------------------------------------

    def show_status(self, message, timeout=DEFAULT_STATUS_TIMEOUT_MS):
        if timeout and timeout > 0:
            self.status_bar.showMessage(str(message), int(timeout))
        else:
            self.status_bar.showMessage(str(message))

    def retranslate(self):
        for key, button in self._menu_buttons.items():
            button.setText(self._adapter.tr(key))
        self._palette.setPlaceholderText(self._adapter.tr("command_palette"))
        for view in self._views.values():
            item = self._nav_items.get(view.view_id())
            if item is not None:
                item.setText(self._adapter.tr(view.nav_key()))
            view.retranslate()

    def _on_language_changed(self, _code):
        self.retranslate()

    # ---- geometry / 几何 -------------------------------------------------

    def _restore_geometry(self):
        blob = self._pending_geometry
        if blob:
            try:
                self.restoreGeometry(blob)
                return
            except Exception:
                log.warning("shell: cannot restore the saved geometry")
        self.resize(constants.DEFAULT_WINDOW_WIDTH, constants.DEFAULT_WINDOW_HEIGHT)

    def _save_geometry(self):
        return bytes(self.saveGeometry())

    # ---- lifecycle / 生命周期 -------------------------------------------

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self):
        # Ordered teardown, innermost first:每个视图先停，然后持久化会话状态。
        # 每个视图先停，然后持久化会话状态。
        for view in self._views.values():
            try:
                view.shutdown()
            except Exception:
                log.exception("shell: view %s failed to shut down", view.view_id())
        try:
            self._adapter.save_session(window_geometry=self._save_geometry())
        except Exception:
            log.exception("shell: cannot persist the session")


__all__ = ["DEFAULT_STATUS_TIMEOUT_MS", "NAV_WIDTH", "ShellWindow"]
