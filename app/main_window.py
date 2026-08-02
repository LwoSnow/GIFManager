"""Main window management
主窗口管理"""
import os
import sys
import ctypes
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QMenu, QScrollArea, QFrame, QLabel,
    QFileDialog, QMessageBox, QStatusBar, QApplication, QInputDialog,
    QSystemTrayIcon,
)
from PySide6.QtCore import Qt, QSize, QMimeData, QPoint, QTimer, QSettings, QThreadPool
from PySide6.QtGui import (
    QDragEnterEvent, QDropEvent, QIcon, QAction, QKeyEvent, QKeySequence,
    QMouseEvent,
)

from app.theme.dark_theme import QSS as DARK_QSS
from app.theme.light_theme import QSS as LIGHT_QSS
from app.models.data_manager import DataManager
from app.models.lang_manager import tr, set_language, current_language, available_languages
from app.models.constants import (
    DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT,
)
from app.models.logger import init_logger, get_logger, install_excepthook, clear_logs
from app.widgets.group_list import GroupListWidget
from app.widgets.emoji_grid import EmojiGridWidget
from app.widgets.search_bar import SearchBar
from app.widgets.settings_dialog import SettingsDialog, recommended_thread_count
from app.widgets.hotkey_manager import HotkeyManager


def _root_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _DragToolbar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._dragging = False
        self._drag_start = QPoint()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            delta = event.globalPosition().toPoint() - self._drag_start
            w = self.window()
            if w:
                w.move(w.pos() + delta)
            self._drag_start = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._dragging = False
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    APP_TITLE = "GIFManager"

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.APP_TITLE)
        self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self.setAcceptDrops(True)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        )

        icon_path = os.path.join(_root_dir(), "icon.ico")
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # Logging system / 日志系统
        init_logger()
        install_excepthook()
        self._log = get_logger()
        self._log.info("App version: 1.0.0 | theme: pending | thread_count: pending")

        self._settings = QSettings("GIFManager", "GIFManager")
        self.data_manager = DataManager()
        self.current_group_id = None
        self._send_mode = 0
        self._remember_group = True
        self._hotkey_registered = False
        self._settings_dialog = None

        self._load_settings()
        self._setup_ui()
        self._apply_theme()
        self._connect_signals()
        self._setup_tray()
        self._init_hotkey_mgr()
        self._apply_thread_count()

        self._restore_geometry()

        saved_gid = self._restore_group()
        if saved_gid is not None:
            self.group_list.select_group(saved_gid)
        else:
            self.group_list.select_all_group()

    # QSettings

    def _load_settings(self):
        self._send_mode = int(self._settings.value("send_mode", 0))
        self._remember_group = self._settings.value("remember_group", True, type=bool)
        self._autostart = self._settings.value("autostart", False, type=bool)
        self._always_on_top = self._settings.value("always_on_top", False, type=bool)
        # Number of multi-threaded cores (0 = automatic, use recommended values)
        # 多线程核心数（0 = 自动，使用推荐值）
        self._thread_count = int(self._settings.value("thread_count", 0))
        self._apply_thread_count()
        # Theme (dark light)
        # 主题（暗色/亮色）
        self._theme = self._settings.value("theme", "dark")
        # Text preview restrictions (single line, multiple lines independent)
        # 文字预览限制（单行 / 多行独立）
        self._text_limit_single = int(self._settings.value("text_preview_limit_single", 100))
        self._text_limit_multi = int(self._settings.value("text_preview_limit_multi", 200))
        lang = self._settings.value("language", "zh_CN")
        try:
            set_language(lang)
        except Exception:
            pass
        self._apply_always_on_top()
        self._apply_autostart()

    def _apply_thread_count(self):
        # Multi-threaded core limit setting
        # 多线程核心数限制设置
        from PySide6.QtCore import QThreadPool
        n = self._thread_count if self._thread_count > 0 else recommended_thread_count()
        pool = QThreadPool.globalInstance()
        if pool.maxThreadCount() != n:
            pool.setMaxThreadCount(n)
        if hasattr(self, "emoji_grid"):
            self.emoji_grid._gif_limit = max(2, n * 2)

    def _save_settings(self):
        self._settings.setValue("send_mode", self._send_mode)
        self._settings.setValue("remember_group", self._remember_group)
        self._settings.setValue("autostart", self._autostart)
        self._settings.setValue("always_on_top", self._always_on_top)
        self._settings.setValue("thread_count", self._thread_count)
        self._settings.setValue("theme", self._theme)
        self._settings.setValue("text_preview_limit_single", self._text_limit_single)
        self._settings.setValue("text_preview_limit_multi", self._text_limit_multi)
        self._settings.setValue("language", current_language())

    def _restore_geometry(self):
        geo = self._settings.value("window_geometry")
        if geo:
            self.restoreGeometry(geo)
        else:
            self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
            screen = QApplication.primaryScreen().availableGeometry()
            self.move(
                (screen.width() - self.width()) // 2,
                (screen.height() - self.height()) // 2,
            )

    def _save_geometry(self):
        self._settings.setValue("window_geometry", self.saveGeometry())

    def _apply_always_on_top(self):
        # setWindowFlag implicitly hides the window; record visibility and restore
        # setWindowFlag 会隐式隐藏窗口：先记录可见性再恢复显示
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self._always_on_top)
        if was_visible:
            self.show()

    def _apply_autostart(self):
        # Windows startup entry (registry Run key) / 开机启动项（注册表 Run 键）
        if sys.platform != "win32":
            return
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
            )
            if self._autostart:
                exe_path = sys.executable
                script = os.path.abspath(sys.argv[0]) if sys.argv else ""
                winreg.SetValueEx(key, "GIFManager", 0, winreg.REG_SZ,
                                  f'"{exe_path}" "{script}"')
            else:
                try:
                    winreg.DeleteValue(key, "GIFManager")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception:
            pass

    def _save_current_group(self):
        if self._remember_group and self.current_group_id is not None:
            g = self.data_manager.get_group(self.current_group_id)
            if g:
                self._settings.setValue("last_group_name", g["name"])

    def _restore_group(self):
        if not self._remember_group:
            return None
        name = self._settings.value("last_group_name", "")
        if name:
            g = self.data_manager.get_group_by_name(name)
            if g:
                return g["id"]
        return None

    # showEvent — Register hotkey + rounded corners after window is shown / 窗口显示后注册热键 + 圆角

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_rounded()
        QTimer.singleShot(200, self._register_hotkey_if_needed)

    def _apply_rounded(self):
        if sys.platform != "win32":
            return
        try:
            hwnd = int(self.winId())
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33,  # DWMWA_WINDOW_CORNER_PREFERENCE
                ctypes.byref(ctypes.c_int(2)),  # DWMWCP_ROUND
                ctypes.sizeof(ctypes.c_int),
            )
        except Exception:
            pass

    # UI

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        toolbar = _DragToolbar()
        toolbar.setObjectName("mainToolbar")
        toolbar.setFixedHeight(46)
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 6, 8, 6)
        toolbar_layout.setSpacing(8)

        self.search_bar = SearchBar()
        toolbar_layout.addWidget(self.search_bar, 1)

        self.btn_import = QPushButton(tr("import_gif"))
        self.btn_import.setFixedHeight(32)
        self._build_import_menu()
        toolbar_layout.addWidget(self.btn_import)

        self.btn_add_text = QPushButton(tr("add_text"))
        self.btn_add_text.setFixedHeight(32)
        self.btn_add_text.hide()
        toolbar_layout.addWidget(self.btn_add_text)

        self.btn_settings = QPushButton("⚙")
        self.btn_settings.setFixedSize(32, 32)
        self.btn_settings.setFlat(True)
        toolbar_layout.addWidget(self.btn_settings)

        root.addWidget(toolbar)

        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFixedHeight(1)
        root.addWidget(sep)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.emoji_grid = EmojiGridWidget()
        self._scroll_area.setWidget(self.emoji_grid)
        root.addWidget(self._scroll_area, 1)

        self.group_list = GroupListWidget(self.data_manager)
        root.addWidget(self.group_list)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._refresh_status()

    def _build_import_menu(self):
        menu = QMenu(self)
        self._act_import_folder = menu.addAction(tr("from_folder"))
        self._act_import_files = menu.addAction(tr("from_file"))
        self.btn_import.setMenu(menu)

    def _apply_theme(self):
        self.setStyleSheet(DARK_QSS if self._theme != "light" else LIGHT_QSS)

    # System tray / 系统托盘

    def _setup_tray(self):
        self._tray = QSystemTrayIcon(self)
        icon_path = os.path.join(_root_dir(), "icon.ico")
        if os.path.isfile(icon_path):
            self._tray.setIcon(QIcon(icon_path))
        else:
            self._tray.setIcon(self.style().standardIcon(
                self.style().StandardPixmap.SP_FileDialogContentsView
            ))
        self._tray.setToolTip(self.APP_TITLE)
        tray_menu = QMenu(self)
        act_show = tray_menu.addAction(tr("tray_show"))
        act_show.triggered.connect(self._toggle_visible)
        tray_menu.addSeparator()
        act_quit = tray_menu.addAction(tr("tray_quit"))
        act_quit.triggered.connect(self._real_quit)
        self._tray.setContextMenu(tray_menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_visible()

    def _toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.activateWindow()
            self.raise_()

    def _real_quit(self):
        self._save_geometry()
        self._save_current_group()
        self._save_settings()
        if self._hotkey_mgr:
            self._hotkey_mgr.unregister()
        self._tray.hide()
        QApplication.quit()

    def closeEvent(self, event):
        self._save_geometry()
        self._save_current_group()
        self._save_settings()
        self._log.info("Window closing -> hide to tray")
        event.ignore()
        self.hide()
        self._tray.showMessage(
            self.APP_TITLE, tr("tray_hidden"),
            QSystemTrayIcon.MessageIcon.Information, 1500
        )

    # Signals / 信号

    def _connect_signals(self):
        self.search_bar.textChanged.connect(self._on_search)
        self._act_import_folder.triggered.connect(self._import_from_folder)
        self._act_import_files.triggered.connect(self._import_from_files)
        self.btn_settings.clicked.connect(self._open_settings)
        self.group_list.group_changed.connect(self._on_group_changed)
        self.group_list.groups_updated.connect(self._refresh_emoji_grid)
        self.emoji_grid.emoji_clicked.connect(self._on_emoji_clicked)
        self.emoji_grid.emoji_right_clicked.connect(self._on_emoji_right_clicked)
        self.emoji_grid.emojis_reordered.connect(self._refresh_emoji_grid)
        self.btn_add_text.clicked.connect(self._add_text_emoji)

    # Group / 分组

    def _on_group_changed(self, group_id):
        # "All" is a virtual aggregation group: its database id is
        # equivalent to "No group selected",
        # Otherwise, get_emojis_by_group(all_id) will only find the
        # emoticons under the name "All" (always empty).
        # "All"是虚拟聚合分组：其数据库 id 等价于"未选中任何分组"，
        # 否则会走 get_emojis_by_group(全部_id) 只查到"All"名下（恒为空）的表情。
        # "All"是虚拟聚合分组：按内置标记识别（重命名后仍有效）
        all_id = self.data_manager._all_group_id()
        if all_id is not None and group_id == all_id:
            group_id = None
        self.current_group_id = group_id
        self.emoji_grid.current_group_id = group_id
        self._log.info("Switch group -> id=%s", group_id)
        # Text grouping enables horizontal scrolling (stable columns may
        # exceed the visible width), image grouping is turned off
        # 文字分组启用横向滚动（稳定列可能超出可视宽度），图片分组关闭
        is_text = False
        if group_id is not None:
            g = self.data_manager.get_group(group_id)
            is_text = bool(g and g["type"] == "text")
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if is_text
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        if group_id is not None:
            g = self.data_manager.get_group(group_id)
            if g and g["type"] == "text":
                self.btn_import.hide()
                self.btn_add_text.show()
            else:
                self.btn_import.show()
                self.btn_add_text.hide()
        else:
            self.btn_import.show()
            self.btn_add_text.hide()
        self._save_current_group()
        self._refresh_emoji_grid()
        self._refresh_status()

    def _refresh_emoji_grid(self):
        keyword = self.search_bar.text().strip()
        if self.current_group_id is None:
            emojis = self.data_manager.get_all_emojis(keyword)
            group_type = "image"
        else:
            g = self.data_manager.get_group(self.current_group_id)
            group_type = g["type"] if g else "image"
            if not keyword:
                self.emoji_grid.assign_unassigned_columns(self.current_group_id)
            emojis = self.data_manager.get_emojis_by_group(self.current_group_id, keyword)
        self.emoji_grid.load_emojis(
            emojis, group_type,
            preview_limits=(self._text_limit_single, self._text_limit_multi),
        )

    def _refresh_status(self):
        total = self.data_manager.count_all_emojis()
        gid = self.current_group_id
        if gid is None:
            keyword = self.search_bar.text().strip()
            shown = len(self.data_manager.get_all_emojis(keyword))
            group_name = "All"
            if not keyword:
                image_total = self.data_manager.count_image_emojis()
                folded = image_total - shown
                if folded > 0:
                    folded_msg = tr(
                        "emoji_count_folded", group=group_name,
                        count=shown, total=total, folded=folded,
                    )
                    self.status_bar.showMessage(f"  {folded_msg}")
                    return
            count = shown
        else:
            g = self.data_manager.get_group(gid)
            group_name = g["name"] if g else "All"
            count = self.data_manager.count_emojis_in_group(gid)
        self.status_bar.showMessage(
            f"  {tr('emoji_count', group=group_name, count=count, total=total)}"
        )

    def _on_search(self, _text):
        self._refresh_emoji_grid()

    # Import / 导入

    def _import_from_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, tr("select_files"), "", tr("image_filter")
        )
        if files:
            self._do_import(files)

    def _import_from_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr("select_folder"))
        if not folder:
            return
        exts = {".gif", ".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        files = []
        for root_dir, _dirs, filenames in os.walk(folder):
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() in exts:
                    files.append(os.path.join(root_dir, fn))
        if files:
            self._do_import(files)
        else:
            QMessageBox.information(self, "GIFManager", tr("no_image_found"))

    def _do_import(self, files):
        target_group = self.current_group_id
        if target_group is None:
            # Builtin default group lookup by flag (works after rename)
            # 内置默认分组按标记查找（重命名后仍有效）
            default = self.data_manager.default_group_id()
            if default is None:
                QMessageBox.warning(self, "GIFManager", tr("default_group_missing"))
                return
            target_group = default

        group_info = self.data_manager.get_group(target_group)
        if group_info and group_info["type"] == "text":
            QMessageBox.warning(self, "GIFManager", tr("text_group_warning"))
            return

        imported, duplicated = self.data_manager.import_emojis_batch(
            target_group, files,
            workers=QThreadPool.globalInstance().maxThreadCount(),
        )
        self._log.info(
            "Import -> group=%s files=%d imported=%d duplicated=%d",
            group_info["name"] if group_info else target_group,
            len(files), imported, duplicated,
        )
        # New cards go to the top-left corner / 新导入的卡片放到左上角
        if imported > 0:
            self.data_manager.prepend_latest_imports(target_group, imported)
        self._refresh_emoji_grid()
        self._refresh_status()
        msg = tr("import_success", count=imported, group=group_info["name"])
        if duplicated:
            msg += tr("import_skip_dup", count=duplicated)
        self.status_bar.showMessage(f"  {msg}", 3000)

    def _add_text_emoji(self):
        if self.current_group_id is None:
            return
        g = self.data_manager.get_group(self.current_group_id)
        if not g or g["type"] != "text":
            return
        text, ok = QInputDialog.getMultiLineText(
            self, tr("add_text_dialog"), tr("add_text_prompt")
        )
        if ok and text.strip():
            r = self.data_manager.add_text_emoji(self.current_group_id, text.strip())
            if r == 0:
                QMessageBox.information(self, tr("text_duplicate_title"), tr("text_duplicate_msg"))
                return
            if r > 0:
                # New text emoji goes to the top-left corner / 新文字表情放到左上角
                self.data_manager.prepend_emojis(self.current_group_id, [r])
            self._refresh_emoji_grid()
            self._refresh_status()
            self.status_bar.showMessage(f"  {tr('added_to', group=g['name'])}", 2000)

    def _assign_new_text(self, emoji_id, text):
        usable = self._scroll_usable_width()
        self.emoji_grid.assign_new_text_column(
            emoji_id, self.current_group_id, text, usable
        )

    def _scroll_usable_width(self):
        try:
            vw = self._scroll_area.viewport().width()
            return max(vw - 20, 100)
        except Exception:
            return 600

    # Drag / 拖放

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        exts = {".gif", ".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        files = []
        for url in urls:
            path = url.toLocalFile()
            if os.path.isfile(path) and os.path.splitext(path)[1].lower() in exts:
                files.append(path)
        if files:
            self._do_import(files)

    def keyPressEvent(self, event: QKeyEvent):
        if event.matches(QKeySequence.StandardKey.Paste):
            if self.current_group_id is not None:
                g = self.data_manager.get_group(self.current_group_id)
                if g and g["type"] == "text":
                    text = QApplication.clipboard().text()
                    if text.strip():
                        added = 0
                        skipped = 0
                        new_ids = []
                        for line in text.strip().split("\n"):
                            line = line.strip()
                            if not line:
                                continue
                            r = self.data_manager.add_text_emoji(self.current_group_id, line)
                            if r > 0:
                                new_ids.append(r)
                                added += 1
                            elif r == 0:
                                skipped += 1
                        if new_ids:
                            # Pasted text goes to the top-left corner / 粘贴的文字放到左上角
                            self.data_manager.prepend_emojis(self.current_group_id, new_ids)
                        self._refresh_emoji_grid()
                        self._refresh_status()
                        msg = tr("pasted_to", group=g["name"])
                        if skipped:
                            msg += tr("import_skip_dup", count=skipped)
                        self.status_bar.showMessage(f"  {msg}", 2500)
                    return
        super().keyPressEvent(event)

    # Emoji operation / 表情包操作

    def _on_emoji_clicked(self, emoji):
        self._log.info("Send/copy emoji -> id=%s mode=%s", emoji.get("id"), self._send_mode)
        success = self.data_manager.copy_to_clipboard(emoji, mode=self._send_mode)
        if success:
            name = emoji.get("original_name") or emoji.get("text_content", "emoji")
            mode_label = tr("copied_path") if self._send_mode == 0 else tr("copied_image")
            self.status_bar.showMessage(f"  ✓ {tr('copied_msg', mode=mode_label, name=name)}", 2000)

    def _on_emoji_right_clicked(self, emoji, pos):
        menu = QMenu(self)
        menu.addAction(tr("send_copy")).triggered.connect(lambda: self._on_emoji_clicked(emoji))
        menu.addSeparator()
        if emoji.get("text_content"):
            menu.addAction(tr("edit_text")).triggered.connect(lambda: self._edit_text_emoji(emoji))
        else:
            menu.addAction(tr("rename")).triggered.connect(lambda: self._rename_emoji(emoji))
        self._build_move_submenu(menu, emoji)
        menu.addSeparator()
        menu.addAction(tr("delete")).triggered.connect(lambda: self._delete_emoji(emoji))
        menu.exec(pos)

    def _delete_emoji(self, emoji):
        name = emoji.get("original_name") or emoji.get("text_content", "")
        if self.current_group_id is None and emoji.get("content_hash"):
            copies = self.data_manager.get_emoji_copies(emoji)
            if len(copies) > 1:
                from app.widgets.delete_copies_dialog import DeleteCopiesDialog
                dlg = DeleteCopiesDialog(copies, self)
                if dlg.exec() == DeleteCopiesDialog.DialogCode.Accepted:
                    for cid in dlg.selected_emojis():
                        self.data_manager.delete_emoji(cid)
                    self._refresh_emoji_grid()
                    self._refresh_status()
                return
        reply = QMessageBox.question(
            self, tr("confirm_delete"), tr("confirm_delete_msg", name=name),
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.data_manager.delete_emoji(emoji["id"])
            self._log.info("Delete emoji -> id=%s", emoji["id"])
            self._refresh_emoji_grid()
            self._refresh_status()

    def _rename_emoji(self, emoji):
        old_name = emoji.get("original_name") or emoji.get("text_content", "")
        new_name, ok = QInputDialog.getText(
            self, tr("rename_dialog"), tr("new_name"), text=old_name
        )
        if ok and new_name.strip():
            self.data_manager.rename_emoji(emoji["id"], new_name.strip())
            self._log.info("Rename emoji -> id=%s old=%r new=%r",
                           emoji["id"], old_name, new_name.strip())
            self._refresh_emoji_grid()

    def _edit_text_emoji(self, emoji):
        from app.widgets.edit_text_dialog import EditTextDialog
        dlg = EditTextDialog(emoji.get("text_content", ""), self)
        if dlg.exec() == EditTextDialog.DialogCode.Accepted:
            new_text = dlg.text()
            if not new_text:
                return
            if new_text == emoji.get("text_content", ""):
                return
            cur = self.data_manager.get_emojis_by_group(emoji["group_id"])
            for other in cur:
                if other["id"] != emoji["id"] and other.get("text_content") == new_text:
                    QMessageBox.information(
                        self, tr("text_duplicate_title"), tr("text_duplicate_msg")
                    )
                    return
            self.data_manager.rename_emoji(emoji["id"], new_text[:20])
            self._conn_update_text(emoji["id"], new_text)
            self._refresh_emoji_grid()

    def _conn_update_text(self, emoji_id, text):
        self.data_manager.update_text_content(emoji_id, text)

    def _build_move_submenu(self, menu, emoji):
        is_text = bool(emoji.get("text_content"))
        groups = self.data_manager.get_all_groups()
        all_id = self.data_manager._all_group_id()
        targets = [
            g for g in groups
            if g["id"] != all_id
            and g["id"] != emoji["group_id"]
            and g["type"] == ("text" if is_text else "image")
        ]
        if not targets:
            return
        sub = QMenu(tr("move_to_group"), menu)
        for g in targets:
            sub.addAction(g["name"]).triggered.connect(
                lambda checked, gid=g["id"]: self._do_move(emoji, gid)
            )
        menu.addMenu(sub)

    def _move_emoji(self, emoji):
        groups = self.data_manager.get_all_groups()
        image_groups = [g for g in groups if g["type"] == "image" and g["id"] != emoji["group_id"]]
        if not image_groups:
            QMessageBox.information(self, "GIFManager", tr("no_move_target"))
            return
        menu = QMenu(self)
        for g in image_groups:
            act = menu.addAction(g["name"])
            act.triggered.connect(lambda checked, gid=g["id"]: self._do_move(emoji, gid))
        menu.exec(self.btn_import.mapToGlobal(QPoint(0, 30)))

    def _do_move(self, emoji, target_group_id):
        self.data_manager.move_emoji(emoji["id"], target_group_id)
        self._log.info("Move emoji -> id=%s target_group=%s", emoji["id"], target_group_id)
        self._refresh_emoji_grid()
        self._refresh_status()

    # Settings / 设置

    def _open_settings(self):
        dlg = SettingsDialog(
            self._send_mode, self._remember_group,
            self._autostart, self._always_on_top,
            self._text_limit_single, self._text_limit_multi,
            self._thread_count, self._theme,
            self.data_manager, self._hotkey_desc(), self
        )
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.apply_clicked.connect(self._on_settings_apply)
        dlg.finished.connect(self._on_settings_finished)
        dlg.clear_logs_requested.connect(self._on_clear_logs)
        self._settings_dialog = dlg
        dlg.show()

    def _on_clear_logs(self):
        from PySide6.QtWidgets import QMessageBox
        count = clear_logs()
        self._log = get_logger()  # 清除后重建的新会话日志
        self._log.info("Clear logs -> removed %d file(s)", count)
        QMessageBox.information(
            self, "GIFManager",
            tr("clear_logs_done", count=count),
        )

    def _on_settings_apply(self):
        if self._settings_dialog is not None:
            self._apply_settings(self._settings_dialog)

    def _on_settings_finished(self, result):
        dlg = self._settings_dialog
        self._settings_dialog = None
        if dlg is not None and result == SettingsDialog.DialogCode.Accepted:
            self._apply_settings(dlg)

    def _apply_settings(self, dlg):
        old_lang = current_language()
        new_lang = dlg.language()
        if new_lang != old_lang:
            set_language(new_lang)
        self._send_mode = dlg.send_mode()
        self._remember_group = dlg.remember_group()
        self._autostart = dlg.autostart()
        self._always_on_top = dlg.always_on_top()
        self._text_limit_single = dlg.text_limit_single()
        self._text_limit_multi = dlg.text_limit_multi()
        self._thread_count = dlg.thread_count()
        theme_changed = (dlg.theme() != self._theme)
        self._theme = dlg.theme()
        self._log.info(
            "Settings applied -> send_mode=%s remember=%s autostart=%s top=%s "
            "threads=%s theme=%s",
            dlg.send_mode(), dlg.remember_group(), dlg.autostart(),
            dlg.always_on_top(), dlg.thread_count(), self._theme,
        )
        new_hotkey = dlg.hotkey_info()
        if new_hotkey is not None:
            self._apply_hotkey(*new_hotkey)
        self._save_settings()
        self._apply_theme()
        if theme_changed and self._settings_dialog is not None:
            d = self._settings_dialog
            d.hide()
            d.setStyleSheet(DARK_QSS if self._theme != "light" else LIGHT_QSS)
            d.style().unpolish(d)
            d.style().polish(d)
            for child in d.findChildren(QWidget):
                child.style().unpolish(child)
                child.style().polish(child)
            d.show()
            d.repaint()
        self._apply_always_on_top()
        self._apply_autostart()
        self._apply_thread_count()
        self._refresh_emoji_grid()
        if new_lang != old_lang:
            self._reload_language()
            if self._settings_dialog is not None:
                self._settings_dialog.refresh_translations()

    def _reload_language(self):
        self.btn_import.setText(tr("import_gif"))
        self.btn_add_text.setText(tr("add_text"))
        self._build_import_menu()
        self.search_bar.setPlaceholderText(tr("search_placeholder"))
        tray_menu = self._tray.contextMenu()
        if tray_menu:
            tray_menu.actions()[0].setText(tr("tray_show"))
            tray_menu.actions()[-1].setText(tr("tray_quit"))
        self._refresh_emoji_grid()
        self._refresh_status()

    # Shortcut keys — delayed registration in showEvent
    # 快捷键 — showEvent 中延迟注册

    def _init_hotkey_mgr(self):
        self._hotkey_mgr = HotkeyManager(self)
        self._hotkey_mods = int(self._settings.value("hotkey_mods", 0))
        self._hotkey_vk = int(self._settings.value("hotkey_vk", Qt.Key.Key_F10))
        if self._hotkey_vk == 0:
            self._hotkey_mods = 0
            self._hotkey_vk = Qt.Key.Key_F10
        QApplication.instance().installNativeEventFilter(self._hotkey_mgr)

    def _register_hotkey_if_needed(self):
        if self._hotkey_mods != 0 or self._hotkey_vk != 0:
            self._apply_hotkey(self._hotkey_mods, self._hotkey_vk)

    def _apply_hotkey(self, mods, vk):
        if mods == 0 and vk == 0:
            self._hotkey_mgr.unregister()
            self._hotkey_mods = 0
            self._hotkey_vk = 0
            self._settings.setValue("hotkey_mods", 0)
            self._settings.setValue("hotkey_vk", 0)
            self._hotkey_registered = False
            return

        ok = self._hotkey_mgr.register(mods, vk, self._toggle_visible)
        if not ok:
            self.status_bar.showMessage(f"  ⚠ {tr('hotkey_fail')}", 4000)
            return
        self._hotkey_mods = mods
        self._hotkey_vk = vk
        self._hotkey_registered = True
        self._settings.setValue("hotkey_mods", int(mods))
        self._settings.setValue("hotkey_vk", int(vk))

    def _hotkey_desc(self):
        if self._hotkey_mods == 0 and self._hotkey_vk == 0:
            return tr("hotkey_unset")
        mods_val = int(self._hotkey_mods)
        parts = []
        if mods_val & int(Qt.KeyboardModifier.ControlModifier.value):
            parts.append("Ctrl")
        if mods_val & int(Qt.KeyboardModifier.ShiftModifier.value):
            parts.append("Shift")
        if mods_val & int(Qt.KeyboardModifier.AltModifier.value):
            parts.append("Alt")
        if mods_val & int(Qt.KeyboardModifier.MetaModifier.value):
            parts.append("Win")
        vk = self._hotkey_vk
        if vk == 0x100001:
            parts.append(tr("mouse_x1"))
        elif vk == 0x100002:
            parts.append(tr("mouse_x2"))
        else:
            seq = QKeySequence(vk)
            name = seq.toString()
            if name:
                parts.append(name)
        return "+".join(parts) if parts else tr("hotkey_unset")
