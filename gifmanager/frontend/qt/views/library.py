"""Library view: groups, search, the sticker grid and its own toolbar.

This is the page the application is really about. It used to be the whole
window; it is now one view among several, which is what makes the settings page
able to exist beside it without either one knowing about the other.

Its commands go into the shared registry rather than into local lambdas, so the
same "Import stickers" action can appear in the toolbar, the context menu and the
command palette without being implemented three times.

表情库视图：分组、搜索、贴纸网格与自己的工具栏。

这是应用真正的核心页面。它以前就是整个窗口；现在它是若干视图之一，这正是让设置页能
与它共存、而彼此互不知晓的原因。

它的命令进入共享注册表而不是本地 lambda，因此同一个"导入表情包"操作可以出现在工具栏、
右键菜单与命令面板中，而无需实现三遍。
"""
import logging

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gifmanager.core import constants
from gifmanager.frontend.qt import commands as cmd
from gifmanager.frontend.qt.views.base import View
from gifmanager.frontend.qt.widgets.emoji_grid import EmojiGridWidget
from gifmanager.frontend.qt.widgets.group_list import GroupListWidget
from gifmanager.frontend.qt.widgets.search_bar import SearchBar

log = logging.getLogger("GIFManager")

# Delay before a keystroke in the search box triggers a reload. Typing a name
# would otherwise issue one query per character.
# 搜索框每次按键触发重新加载前的延迟。否则输入一个名字会每字符发一次查询。
SEARCH_DEBOUNCE_MS = 200

# Card scale bounds and step, shared with the view commands /
# 卡片缩放范围与步长，与视图命令共用
SCALE_MIN = 0.5
SCALE_MAX = 2.0
SCALE_STEP = 0.1


class LibraryView(View):
    # The sticker library page.
    # 贴纸库页面。

    VIEW_ID = "library"
    TITLE_KEY = "all_group"
    NAV_KEY = "all_group"

    def __init__(self, adapter, parent=None):
        super().__init__(adapter, parent)
        self._current_group_id = None
        self._keyword = ""
        # Created on first hover, because a hidden `Tool` window is still an OS
        # resource and most sessions never use the preview.
        # 首次悬停时才创建：隐藏的 `Tool` 窗口仍是系统资源，而多数会话从不用预览。
        self._preview = None
        self._build_ui()
        self._connect_signals()
        self._restore_group()
        self.refresh()

    # ---- construction / 构建 --------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_toolbar())
        layout.addWidget(self._build_separator())
        layout.addWidget(self._build_grid_area(), 1)
        layout.addWidget(self._build_group_bar())

    def _build_toolbar(self):
        bar = QWidget(self)
        bar.setObjectName("mainToolbar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)

        self._search = SearchBar()
        layout.addWidget(self._search, 1)

        # Buttons are created from registry entries rather than inline, so the
        # toolbar cannot drift out of step with the menu or the palette.
        # 按钮由注册表条目创建而非内联，使工具栏不会与菜单或命令面板脱节。
        self._btn_import = self._command_button(cmd.CMD_IMPORT)
        self._btn_add_text = self._command_button(cmd.CMD_ADD_TEXT)
        self._btn_settings = self._command_button(cmd.CMD_NAV_SETTINGS)
        for button in (self._btn_import, self._btn_add_text, self._btn_settings):
            layout.addWidget(button)
        return bar

    def _command_button(self, command_id):
        registry = self._registry
        command = registry.get(command_id) if registry else None
        text = self._adapter.tr(command.label_key) if command else command_id
        button = QPushButton(text)
        button.setObjectName("mainToolButton")
        button.setToolTip(text)
        # The button asks the REGISTRY to run the action, so an action can be
        # disabled or replaced in one place and every presenter follows.
        # 按钮向"注册表"请求执行操作，因此在一处禁用或替换某操作后，所有呈现方都会跟随。
        button.clicked.connect(lambda _checked=False, cid=command_id:
                               self._invoke(cid))
        return button

    @staticmethod
    def _build_separator():
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setObjectName("toolbarSeparator")
        line.setFixedHeight(1)
        return line

    def _build_grid_area(self):
        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("gridScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._grid = EmojiGridWidget(self._adapter, self._scroll)
        self._grid.setObjectName("emojiGrid")
        self._scroll.setWidget(self._grid)
        return self._scroll

    def _build_group_bar(self):
        self._group_list = GroupListWidget(self._adapter, self)
        return self._group_list

    def _connect_signals(self):
        self._search.textChanged.connect(self._on_search_changed)
        self._group_list.group_changed.connect(self._on_group_changed)
        self._group_list.groups_updated.connect(self._on_groups_updated)
        self._grid.emoji_clicked.connect(self._on_emoji_clicked)
        self._grid.emoji_right_clicked.connect(self._on_emoji_context)
        self._grid.card_hovered.connect(self._on_card_hovered)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._on_search_timeout)

        self._adapter.library_changed.connect(self._on_library_changed)
        self._adapter.language_changed.connect(self._on_language_changed)

    # ---- hover preview / 悬停预览 ---------------------------------------

    def _on_card_hovered(self, emoji, rect):
        # The preview is created lazily: a view that is never hovered never builds
        # a top-level window, which matters because a `Tool` window is a real OS
        # resource even while hidden.
        # 预览是惰性创建的：从未被悬停的视图永远不会建出一个顶层窗口——这很重要，因为
        # 即使隐藏，`Tool` 窗口也是真实的系统资源。
        if emoji is None:
            if self._preview is not None:
                self._preview.cancel()
            return
        if self._preview is None:
            from gifmanager.frontend.qt.widgets.hover_preview import HoverPreview

            self._preview = HoverPreview(self)
        self._preview.set_zoom(self._adapter.settings.hover_zoom)
        self._preview.set_source_dim(self._grid._metrics().card_width)
        path = self._adapter.store.emoji_filepath(emoji)
        if not path:
            # A text sticker has no file to show; the caption alone would be a
            # preview of nothing, so the preview stays hidden.
            # 文字贴纸没有可显示的文件；只有标题等于预览了"空"，因此保持隐藏。
            self._preview.cancel()
            return
        self._preview.schedule(path, emoji.get("original_name", ""), rect)

    # ---- registry / 注册表 ----------------------------------------------

    _registry = None

    def attach_registry(self, registry):
        # Given the registry by the shell, because commands live in the shell's
        # namespace: a page-local registry would make the palette unable to see
        # the page's actions.
        # 由外壳传入注册表，因为命令属于外壳的命名空间：页面私有的注册表会让命令面板
        # 看不到该页面的操作。
        self._registry = registry

    def commands(self):
        # The library's own actions. Each carries the surface it suits, so the
        # shell presents them without deciding anything.
        # 表情库自己的操作。每个都声明适合的界面，使外壳无需判断即可呈现。
        return [
            cmd.define(
                cmd.CMD_IMPORT, "import_stickers", self.import_stickers,
                hint_key="import_not_wired",
                shortcut="Ctrl+O", mutates=True,
                surfaces=(cmd.SURFACE_MENU, cmd.SURFACE_TOOLBAR,
                          cmd.SURFACE_PALETTE)),
            cmd.define(
                cmd.CMD_ADD_TEXT, "add_text", self.add_text,
                shortcut="Ctrl+T", mutates=True,
                enabled_when=lambda state: state.get("accepts_text", False),
                surfaces=(cmd.SURFACE_MENU, cmd.SURFACE_TOOLBAR,
                          cmd.SURFACE_PALETTE)),
            cmd.define(
                cmd.CMD_SEARCH_FOCUS, "search_placeholder",
                self.focus_search, shortcut="Ctrl+F",
                surfaces=(cmd.SURFACE_MENU, cmd.SURFACE_PALETTE)),
            cmd.define(
                cmd.CMD_REFRESH, "refresh", self.refresh, shortcut="F5",
                surfaces=(cmd.SURFACE_MENU, cmd.SURFACE_PALETTE)),
            cmd.define(
                cmd.CMD_COPY, "copy", self.copy_currently_clicked,
                shortcut="Ctrl+C",
                enabled_when=lambda state: bool(state.get("selected")),
                surfaces=(cmd.SURFACE_CONTEXT, cmd.SURFACE_MENU)),
            cmd.define(
                cmd.CMD_RENAME, "rename_emoji", self.rename_sticker,
                shortcut="F2", mutates=True,
                enabled_when=lambda state: bool(state.get("has_target")),
                surfaces=(cmd.SURFACE_MENU, cmd.SURFACE_CONTEXT,
                          cmd.SURFACE_PALETTE)),
            cmd.define(
                cmd.CMD_EDIT_TEXT, "edit_text_dialog", self.edit_sticker_text,
                shortcut="F3", mutates=True,
                enabled_when=lambda state: bool(state.get("has_target")),
                surfaces=(cmd.SURFACE_MENU, cmd.SURFACE_CONTEXT,
                          cmd.SURFACE_PALETTE)),
            cmd.define(
                cmd.CMD_MOVE_TO_GROUP, "move_to_group", self.move_sticker,
                shortcut="Ctrl+M", mutates=True,
                enabled_when=lambda state: bool(state.get("has_target")),
                surfaces=(cmd.SURFACE_MENU, cmd.SURFACE_CONTEXT,
                          cmd.SURFACE_PALETTE)),
            cmd.define(
                cmd.CMD_DELETE_SELECTED, "delete", self.delete_sticker,
                shortcut="Delete", mutates=True,
                enabled_when=lambda state: bool(state.get("selected")),
                surfaces=(cmd.SURFACE_MENU, cmd.SURFACE_CONTEXT,
                          cmd.SURFACE_PALETTE)),
            cmd.define(
                cmd.CMD_CARD_SCALE_UP, "card_size", self.scale_up,
                shortcut="Ctrl+=",
                surfaces=(cmd.SURFACE_MENU, cmd.SURFACE_PALETTE)),
            cmd.define(
                cmd.CMD_CARD_SCALE_DOWN, "card_size", self.scale_down,
                shortcut="Ctrl+-",
                surfaces=(cmd.SURFACE_MENU, cmd.SURFACE_PALETTE)),
            cmd.define(
                cmd.CMD_CARD_SCALE_RESET, "card_size", self.scale_reset,
                shortcut="Ctrl+0",
                surfaces=(cmd.SURFACE_MENU, cmd.SURFACE_PALETTE)),
            cmd.define(
                cmd.CMD_TOGGLE_NAME, "show_emoji_name", self.toggle_name,
                surfaces=(cmd.SURFACE_MENU, cmd.SURFACE_PALETTE)),
            cmd.define(
                cmd.CMD_CONVERT_LIBRARY, "gif_convert_all",
                self.convert_library, mutates=True,
                surfaces=(cmd.SURFACE_MENU, cmd.SURFACE_PALETTE)),
        ]

    def _invoke(self, command_id):
        registry = self._registry
        if registry is not None:
            return registry.invoke(command_id, self.state())
        return False

    def state(self):
        # Snapshot for command predicates and for the shell's status line.
        # 供命令谓词与外壳状态行使用的快照。
        group = (None if self._current_group_id is None
                 else self._adapter.store.get_group(self._current_group_id))
        accepts_text = bool(
            group and group["type"] == "text"
        ) or self._adapter.is_all_group(self._current_group_id)
        selected = self._grid.selected_rows()
        return {
            "view": self.view_id(),
            "group_id": self._current_group_id,
            "group_type": group["type"] if group else "image",
            "accepts_text": accepts_text,
            "keyword": self._keyword,
            "count": len(self._grid.rows()),
            "cards": self._grid.card_count(),
            "selected": bool(selected),
            "selection_count": len(selected),
            # True when a dialog has something to act on: a right-clicked card or
            # a selection. This is what makes F2/F3/Ctrl+M reachable from the
            # menu and the palette and not only from a context click.
            # 存在可作用的行时为 True：右键点击的卡片或选中项。这正是让 F2/F3/Ctrl+M
            # 从菜单与命令面板也能到达、而不只在右键时。
            "has_target": bool(selected) or getattr(self, "_context_row", None)
            is not None,
            "card_scale": self._grid.card_scale,
            "show_name": self._grid._show_name,
        }

    # ---- data flow / 数据流 ---------------------------------------------

    def refresh(self):
        group_id = self._current_group_id
        rows = self._adapter.view(group_id, self._keyword)
        group_type = "image"
        if group_id is not None:
            group = self._adapter.store.get_group(group_id)
            if group:
                group_type = group["type"]
        self._grid.load_rows(rows, group_id=group_id, group_type=group_type,
                             keyword=self._keyword)
        self._refresh_status()
        self._refresh_toolbar()

    def _refresh_status(self):
        stats = self._adapter.stats(self._current_group_id, self._keyword)
        group_id = self._current_group_id
        if self._adapter.is_all_group(group_id):
            scope = self._adapter.tr("all_group")
        else:
            group = self._adapter.store.get_group(group_id)
            scope = group["name"] if group else ""
        if self._keyword:
            message = self._adapter.tr(
                "search_result", group=scope, keyword=self._keyword,
                count=stats["total"])
        else:
            message = self._adapter.tr(
                "emoji_count", group=scope, count=stats["total"],
                total=stats["all_total"])
        self.status_message.emit(message, 0)

    def _refresh_toolbar(self):
        # Availability comes from the registry, so a button's enabled state and
        # the matching menu item's cannot disagree.
        # 可用性来自注册表，因此按钮的启用状态与对应菜单项的不会不一致。
        state = self.state()
        registry = self._registry
        if registry is None:
            return
        for command_id, button in (
                (cmd.CMD_IMPORT, self._btn_import),
                (cmd.CMD_ADD_TEXT, self._btn_add_text)):
            command = registry.get(command_id)
            if command is None:
                continue
            button.setEnabled(command.is_enabled(state))

    def _restore_group(self):
        if not self._adapter.settings.remember_group:
            self._group_list.select_all_group()
            return
        name = self._adapter.settings.last_group_name
        if not name:
            self._group_list.select_all_group()
            return
        for group in self._adapter.groups():
            if group["name"] == name:
                self._group_list.select_group(group["id"])
                return
        self._group_list.select_all_group()

    # ---- actions / 操作 --------------------------------------------------

    def focus_search(self):
        self._search.setFocus()
        self._search.selectAll()

    def import_stickers(self):
        # The import pipeline is complete and tested in the store; what is
        # missing is the file picker. Reported rather than silently doing nothing.
        # 导入流水线在存储层已完整且经过测试；缺的是文件选择器。此处明确提示而不是静默
        # 无效。
        QMessageBox.information(
            self, self._adapter.tr("import_stickers"),
            self._adapter.tr("import_not_wired"))

    def add_text(self):
        from PySide6.QtWidgets import QInputDialog

        group_id = self._current_group_id
        if group_id is None:
            group_id = self._adapter.store.default_group_id()
        if group_id is None:
            return
        text, ok = QInputDialog.getText(
            self, self._adapter.tr("add_text"),
            self._adapter.tr("add_text_prompt"))
        if not ok or not text.strip():
            return
        result = self._adapter.store.add_text_emoji(group_id, text)
        if result <= 0:
            self.status_message.emit(self._adapter.tr("duplicate_text"), 3000)
            return
        self._adapter.store.prepend_emojis(group_id, [result])
        self.library_changed.emit()

    def copy_currently_clicked(self):
        rows = self._grid.selected_rows()
        if rows:
            self._copy_emoji(rows[0])

    def delete_selected(self):
        rows = self._grid.selected_rows()
        if not rows:
            return
        if QMessageBox.question(
                self, self._adapter.tr("confirm_delete"),
                self._adapter.tr("confirm_delete_msg", name=str(len(rows)))
        ) != QMessageBox.StandardButton.Yes:
            return
        ids = []
        for row in rows:
            ids.extend(self._adapter.store.ids_sharing_content_hash([row["id"]]))
        removed = self._adapter.store.delete_emojis(sorted(set(ids)))
        log.info("deleted %s rows through the command registry", removed)
        self.library_changed.emit()

    def scale_up(self):
        self._set_scale(self._grid.card_scale + SCALE_STEP)

    def scale_down(self):
        self._set_scale(self._grid.card_scale - SCALE_STEP)

    def scale_reset(self):
        self._set_scale(1.0)

    def _set_scale(self, value):
        scale = max(SCALE_MIN, min(SCALE_MAX, round(value, 2)))
        self._grid.set_card_scale(scale)
        # Persisted so the choice survives a restart, matching the setting the
        # settings page will bind to the same value.
        # 持久化使该选择跨重启保留，与设置页将绑定到同一取值的设置项一致。
        from gifmanager.core import settings as settings_model

        updated = settings_model.from_mapping(
            {**settings_model.to_mapping(self._adapter.settings),
             "card_scale": scale})
        self._adapter.apply_settings(updated)

    def toggle_name(self):
        from gifmanager.core import settings as settings_model

        updated = settings_model.from_mapping(
            {**settings_model.to_mapping(self._adapter.settings),
             "show_emoji_name": not self._grid._show_name})
        self._adapter.apply_settings(updated)
        self._grid.set_show_name(updated.show_emoji_name)

    def convert_library(self):
        # The conversion itself lives in the store and takes a progress callback;
        # only the progress dialog is missing here.
        # 转换本身位于存储层并接收进度回调；此处只缺进度对话框。
        QMessageBox.information(
            self, self._adapter.tr("gif_convert_all"),
            self._adapter.tr("import_not_wired"))

    # ---- slots / 槽 ------------------------------------------------------

    def _on_group_changed(self, group_id):
        self._current_group_id = group_id
        self.refresh()
        if self._adapter.settings.remember_group:
            group = (None if group_id is None
                     else self._adapter.store.get_group(group_id))
            self._adapter.save_session(
                last_group_name=group["name"] if group else "")

    def _on_groups_updated(self):
        self.refresh()

    def _on_search_changed(self, _text):
        self._search_timer.start()

    def _on_search_timeout(self):
        self._keyword = self._search.text().strip()
        self.refresh()

    def _on_library_changed(self):
        self._group_list.reload()
        self.refresh()

    def _on_language_changed(self, _code):
        self.retranslate()

    def _on_emoji_clicked(self, emoji):
        if not self._copy_emoji(emoji):
            self.status_message.emit(
                self._adapter.tr("clipboard_copy_failed"), 3000)

    def _on_emoji_context(self, emoji, position):
        # The context menu is built FROM the registry, so it can never list an
        # action the palette does not know about.
        # 右键菜单"由注册表生成"，因此它绝不会列出命令面板不知道的操作。
        self._context_row = emoji
        registry = self._registry
        if registry is None:
            return
        menu = QMenu(self)
        for command in registry.for_surface(cmd.SURFACE_CONTEXT):
            label = self._adapter.tr(command.label_key)
            action = menu.addAction(label)
            action.setEnabled(command.is_enabled(self.state()))
            action.triggered.connect(
                lambda _checked=False, cid=command.id: self._invoke(cid))
        menu.exec(position)
        self._context_row = None

    def _target_row(self):
        # The row a dialog should act on: the one right-clicked, else the first
        # selected row. Falling back to the selection means the edit commands work
        # from the menu and the palette, not only from a context click.
        # 对话框应作用的那一行：右键点击的那行，否则是第一行选中项。回退到选中项使编辑
        # 类命令从菜单与命令面板也能用，而不只在右键时。
        row = getattr(self, "_context_row", None)
        if row is not None:
            return row
        selected = self._grid.selected_rows()
        return selected[0] if selected else None

    # ---- card dialogs / 卡片对话框 ---------------------------------------

    def rename_sticker(self):
        # Uses the ported, already-localised dialog instead of `QInputDialog`,
        # whose buttons stay in English regardless of the application language.
        # 使用已移植、已本地化的对话框，而不是 `QInputDialog`——后者的按钮无论应用语言
        # 如何都保持英文。
        from gifmanager.frontend.qt.dialogs.rename_dialog import RenameDialog

        row = self._target_row()
        if row is None:
            return False
        dialog = RenameDialog(row.get("original_name", ""), self,
                              title=self._adapter.tr("rename_emoji"))
        if dialog.exec() != RenameDialog.DialogCode.Accepted:
            return False
        new_name = dialog.new_name()
        if not new_name or new_name == row.get("original_name"):
            return False
        self._adapter.store.rename_emoji(row["id"], new_name)
        self.library_changed.emit()
        return True

    def edit_sticker_text(self):
        from gifmanager.frontend.qt.dialogs.edit_text_dialog import EditTextDialog

        row = self._target_row()
        if row is None or not row.get("text_content") and not self._row_accepts_text(row):
            return False
        dialog = EditTextDialog(row.get("text_content", ""), self)
        if dialog.exec() != EditTextDialog.DialogCode.Accepted:
            return False
        text = dialog.text()
        if not text or text == row.get("text_content"):
            return False
        self._adapter.store.update_text_content(row["id"], text)
        self.library_changed.emit()
        return True

    def _row_accepts_text(self, row):
        group = self._adapter.store.get_group(row.get("group_id"))
        return bool(group and group["type"] == "text")

    def move_sticker(self):
        # The move targets are the groups whose type accepts this row, so the
        # menu cannot offer a move the store would then refuse.
        # 目标分组是类型能接受该行的分组，因此菜单不会提供一个存储随后会拒绝的移动。
        from PySide6.QtWidgets import QInputDialog

        row = self._target_row()
        if row is None:
            return False
        wants_text = bool(row.get("text_content"))
        targets = []
        for group in self._adapter.groups():
            if group["id"] == row.get("group_id"):
                continue
            if wants_text and group["type"] != "text":
                continue
            if not wants_text and group["type"] != "image":
                continue
            targets.append(group)
        if not targets:
            self.status_message.emit(
                self._adapter.tr("no_group_to_move_to"), 3000)
            return False
        names = [group["name"] for group in targets]
        chosen, accepted = QInputDialog.getItem(
            self, self._adapter.tr("move_to_group"),
            self._adapter.tr("move_to_group"), names, 0, False)
        if not accepted:
            return False
        target = targets[names.index(chosen)]
        if not self._adapter.store.move_emoji(row["id"], target["id"]):
            self.status_message.emit(
                self._adapter.tr("move_failed"), 3000)
            return False
        self.library_changed.emit()
        return True

    def delete_sticker(self):
        row = self._target_row()
        if row is None:
            return False
        # A sticker stored in several groups is one picture; deleting only the
        # visible copy would leave the others behind, which is what made
        # "delete" look like it did nothing in the previous release.
        # 存于多个分组的贴纸是同一张图；只删可见的那一份会留下其余副本，这正是上一版本
        # "删除"看起来毫无效果的原因。
        copies = self._adapter.store.get_emoji_copies(row)
        if len(copies) > 1:
            from gifmanager.frontend.qt.dialogs.delete_copies_dialog import (
                DeleteCopiesDialog,
            )

            dialog = DeleteCopiesDialog(copies, self)
            if dialog.exec() != DeleteCopiesDialog.DialogCode.Accepted:
                return False
            ids = dialog.selected_emojis() or [row["id"]]
        else:
            if QMessageBox.question(
                    self, self._adapter.tr("confirm_delete"),
                    self._adapter.tr("confirm_delete_msg",
                                     name=row.get("original_name", ""))
            ) != QMessageBox.StandardButton.Yes:
                return False
            ids = self._adapter.store.ids_sharing_content_hash([row["id"]])
        removed = self._adapter.store.delete_emojis(sorted(set(ids)))
        log.info("deleted %s row(s) through the card interface", removed)
        self.library_changed.emit()
        return removed > 0

    def _copy_emoji(self, emoji):
        # Text stickers copy their text; image stickers copy the file, which is
        # what a chat application can paste as a picture.
        # 文字贴纸复制其文字；图片贴纸复制文件，聊天软件才能作为图片粘贴。
        text = (emoji or {}).get("text_content")
        if text:
            from PySide6.QtWidgets import QApplication

            QApplication.clipboard().setText(text)
            self._adapter.store.increment_use_count(emoji["id"])
            self.status_message.emit(self._adapter.tr("clipboard_copied"), 2000)
            return True
        path = self._adapter.store.emoji_filepath(emoji)
        if not path:
            return False
        from PySide6.QtCore import QMimeData, QUrl
        from PySide6.QtWidgets import QApplication

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path)])
        QApplication.clipboard().setMimeData(mime)
        self._adapter.store.increment_use_count(emoji["id"])
        self.status_message.emit(self._adapter.tr("clipboard_copied"), 2000)
        return True

    # ---- lifecycle / 生命周期 -------------------------------------------

    def retranslate(self):
        self._search.setPlaceholderText(self._adapter.tr("search_placeholder"))
        registry = self._registry
        if registry is not None:
            for command_id, button in (
                    (cmd.CMD_IMPORT, self._btn_import),
                    (cmd.CMD_ADD_TEXT, self._btn_add_text),
                    (cmd.CMD_NAV_SETTINGS, self._btn_settings)):
                command = registry.get(command_id)
                if command is not None:
                    button.setText(self._adapter.tr(command.label_key))
        self.refresh()

    def activate(self):
        self._on_library_changed()

    def apply_settings(self, settings, changed):
        # Adopt render-affecting settings even while this view is hidden, so the
        # grid cannot come back showing a stale card size or name setting.
        # 即使本视图隐藏也采用影响渲染的设置，使网格切回来时不会显示过期的卡片尺寸或
        # 名称设置。
        if not changed or "show_emoji_name" in changed:
            self._grid.set_show_name(settings.show_emoji_name)
        if not changed or "card_scale" in changed:
            self._grid.set_card_scale(settings.card_scale)
        if self._preview is not None and (not changed or "hover_zoom" in changed):
            self._preview.set_zoom(settings.hover_zoom)
        if changed and "hover_preview_enabled" in changed \
                and not settings.hover_preview_enabled and self._preview is not None:
            self._preview.cancel()

    def deactivate(self):
        # Stop the debounce timer, hide the preview and release the grid's pools,
        # so a hidden library page holds no windows, file handles or decode
        # threads.
        # 停止防抖定时器、隐藏预览并释放网格的池，使隐藏的表情库页不持有窗口、文件句柄与
        # 解码线程。
        if self._search_timer.isActive():
            self._search_timer.stop()
        if self._preview is not None:
            self._preview.cancel()
        self._grid.release_assets()

    def shutdown(self):
        if self._preview is not None:
            self._preview.shutdown()
            self._preview.deleteLater()
            self._preview = None
        self.deactivate()


__all__ = ["LibraryView", "SCALE_MAX", "SCALE_MIN", "SCALE_STEP",
           "SEARCH_DEBOUNCE_MS"]
