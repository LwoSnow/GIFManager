"""底部分组标签栏 — 水平可滚动按钮组，支持拖拽排序"""
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QScrollArea, QMenu, QInputDialog, QMessageBox,
    QApplication,
)
from PySide6.QtCore import Qt, Signal, QMimeData, QEvent, QRect
from PySide6.QtGui import QDrag, QMouseEvent, QPainter, QColor

from app.models.lang_manager import tr


class _DropContainer(QWidget):
    """支持绘制白色插入指示条的按钮容器"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drop_index = -1

    def set_drop_index(self, idx):
        self._drop_index = idx
        self.update()

    def clear_drop_index(self):
        self._drop_index = -1
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._drop_index < 0:
            return
        children = [w for w in self.children() if isinstance(w, GroupTabButton)]
        children.sort(key=lambda w: w.geometry().x())
        n = len(children)
        if n < 2:
            return  # 需要至少"全部"+一个可移动分组
        # children[0] 是固定"全部"，children[1..n-1] 是可移动分组
        # _drop_index 基于"不含全部"的可移动分组索引
        idx = max(0, min(self._drop_index, n - 1))
        if idx <= 0:
            x = children[1].geometry().left()  # 第一个可移动分组左侧
        elif idx >= n - 1:
            x = children[-1].geometry().right()  # 末尾
        else:
            x = (children[idx].geometry().right() + children[idx + 1].geometry().left()) // 2
        rect = QRect(x, 2, 2, self.height() - 4)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(rect, QColor(255, 255, 255))
        painter.end()


class GroupTabButton(QPushButton):
    """可拖拽的分组标签按钮（"全部"固定不可拖）"""

    def __init__(self, group_id, pinned=False, parent=None):
        super().__init__(parent)
        self._group_id = group_id
        self._pinned = pinned
        self._press_pos = None
        self._dragging = False

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if (event.buttons() & Qt.MouseButton.LeftButton and
                self._press_pos is not None and not self._pinned):
            if (event.position().toPoint() - self._press_pos).manhattanLength() > QApplication.startDragDistance():
                self._dragging = True
                drag = QDrag(self)
                mime = QMimeData()
                mime.setData("application/x-group-id", str(self._group_id).encode())
                drag.setMimeData(mime)
                drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._dragging = False
        self._press_pos = None
        super().mouseReleaseEvent(event)


class GroupListWidget(QWidget):
    """水平分组标签栏，包含"全部"、各分组和 + 按钮"""

    group_changed = Signal(object)  # group_id (None = 全部)
    groups_updated = Signal()

    def __init__(self, data_manager, parent=None):
        super().__init__(parent)
        self._dm = data_manager
        self._buttons = {}  # group_id -> GroupTabButton
        self._current_group_id = None
        self._dragging_id = None  # 正在拖拽的分组 id（用于插入点计算）

        self.setFixedHeight(44)
        self._setup_ui()
        self._rebuild()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        self._scroll = QScrollArea()
        self._scroll.setFixedHeight(36)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidgetResizable(True)

        self._btn_container = _DropContainer()
        self._btn_layout = QHBoxLayout(self._btn_container)
        self._btn_layout.setContentsMargins(0, 0, 0, 0)
        self._btn_layout.setSpacing(4)
        self._btn_layout.addStretch()

        # 容器接受拖放，用于分组排序
        self._btn_container.setAcceptDrops(True)
        self._btn_container.installEventFilter(self)

        self._scroll.setWidget(self._btn_container)
        layout.addWidget(self._scroll)

        self._btn_add = QPushButton("＋")
        self._btn_add.setFixedSize(32, 32)
        self._btn_add.setObjectName("groupTab")
        self._btn_add.clicked.connect(self._on_add_clicked)
        layout.addWidget(self._btn_add)

    # ------------------------------------------------------------------
    # 构建按钮
    # ------------------------------------------------------------------

    def _rebuild(self):
        for btn in self._buttons.values():
            btn.deleteLater()
        self._buttons.clear()

        all_id = self._dm._all_group_id()
        groups = self._dm.get_all_groups()
        for g in groups:
            gid = g["id"]
            btn = GroupTabButton(gid, pinned=(gid == all_id))
            btn.setText(g["name"])
            btn.setObjectName("groupTab")
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, _id=gid: self._select(_id))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(lambda pos, _id=gid: self._on_right_click(_id, pos))

            self._btn_layout.insertWidget(self._btn_layout.count() - 1, btn)
            self._buttons[gid] = btn

        self._update_active_style()

    # ------------------------------------------------------------------
    # 拖拽排序（容器事件过滤）
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):
        if obj is self._btn_container:
            t = event.type()
            if t == QEvent.Type.DragEnter:
                if event.mimeData().hasFormat("application/x-group-id"):
                    try:
                        self._dragging_id = int(bytes(event.mimeData().data("application/x-group-id")).decode())
                    except (ValueError, TypeError):
                        self._dragging_id = None
                    event.acceptProposedAction()
                    return True
                return False
            if t == QEvent.Type.DragMove:
                if event.mimeData().hasFormat("application/x-group-id"):
                    event.acceptProposedAction()
                    self._btn_container.set_drop_index(
                        self._index_at_pos(event.position().toPoint(), exclude=self._dragging_id)
                    )
                    return True
                return False
            if t == QEvent.Type.Drop:
                if event.mimeData().hasFormat("application/x-group-id"):
                    self._btn_container.clear_drop_index()
                    self._dragging_id = None
                    self._on_group_drop(event)
                    return True
                return False
            if t == QEvent.Type.DragLeave:
                self._btn_container.clear_drop_index()
                self._dragging_id = None
                return False
        return super().eventFilter(obj, event)

    def _on_group_drop(self, event):
        try:
            dragged_id = int(bytes(event.mimeData().data("application/x-group-id")).decode())
        except (ValueError, TypeError):
            event.ignore()
            return
        # 计算插入点时排除被拖分组本身（避免 remove 后索引偏移）
        idx = self._index_at_pos(event.position().toPoint(), exclude=dragged_id)
        if self._dm.reorder_group(dragged_id, idx):
            event.acceptProposedAction()
            self._rebuild()
            self.groups_updated.emit()

    def _index_at_pos(self, pos, exclude=None):
        """计算插入点索引：基于"排除被拖分组后"的可移动分组序列"""
        all_id = self._dm._all_group_id()
        anchors = [gid for gid in self._buttons if gid != all_id and gid != exclude]
        if not anchors:
            return 0
        best = len(anchors)
        best_dist = float("inf")
        for i, gid in enumerate(anchors):
            btn = self._buttons[gid]
            center = btn.geometry().center()
            dist = (pos - center).manhattanLength()
            if dist < best_dist:
                best_dist = dist
                best = i
        # 在最后一个锚点右侧 → 末尾
        last_btn = self._buttons[anchors[-1]]
        if pos.x() > last_btn.geometry().right():
            best = len(anchors)
        return best

    # ------------------------------------------------------------------
    # 选择
    # ------------------------------------------------------------------

    def select_all_group(self):
        self._select(None)

    def select_group(self, group_id):
        if group_id in self._buttons:
            self._select(group_id)
        else:
            self._select(None)

    def _select(self, group_id):
        self._current_group_id = group_id
        self._update_active_style()
        self.group_changed.emit(group_id)

    def _update_active_style(self):
        for gid, btn in self._buttons.items():
            is_active = (gid == self._current_group_id)
            btn.setProperty("active", is_active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    # ------------------------------------------------------------------
    # 右键菜单
    # ------------------------------------------------------------------

    def _on_right_click(self, group_id, pos):
        g = self._dm.get_group(group_id)
        if not g:
            return
        menu = QMenu(self)
        act_rename = menu.addAction(tr("rename"))
        if not g["is_builtin"]:
            act_delete = menu.addAction(tr("delete"))
        else:
            act_delete = None

        action = menu.exec(self._buttons[group_id].mapToGlobal(pos))
        if action == act_rename:
            self._rename_group(group_id)
        elif act_delete and action == act_delete:
            self._delete_group(group_id)

    def _rename_group(self, group_id):
        g = self._dm.get_group(group_id)
        if not g:
            return
        new_name, ok = QInputDialog.getText(self, tr("rename_group_dialog"), tr("new_name"), text=g["name"])
        if ok and new_name.strip():
            if not self._dm.rename_group(group_id, new_name.strip()):
                QMessageBox.warning(self, tr("rename_failed"), tr("rename_failed_msg"))
                return
            self._rebuild()
            self.groups_updated.emit()

    def _delete_group(self, group_id):
        g = self._dm.get_group(group_id)
        if not g:
            return
        reply = QMessageBox.question(
            self, tr("confirm_delete"),
            tr("confirm_delete_group_msg", name=g["name"]),
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._dm.delete_group(group_id)
            if self._current_group_id == group_id:
                self.select_all_group()
            self._rebuild()
            self.groups_updated.emit()

    # ------------------------------------------------------------------
    # + 按钮 - 新建分组
    # ------------------------------------------------------------------

    def _on_add_clicked(self):
        menu = QMenu(self)
        act_image = menu.addAction(tr("new_image_group"))
        act_text = menu.addAction(tr("new_text_group"))
        action = menu.exec(self._btn_add.mapToGlobal(self._btn_add.rect().bottomLeft()))

        if action is None:
            return

        grp_type = "image" if action == act_image else "text"
        title = tr("new_image_group_title") if grp_type == "image" else tr("new_text_group_title")
        name, ok = QInputDialog.getText(self, title, tr("group_name"))
        if ok and name.strip():
            if self._dm.create_group(name.strip(), grp_type) is None:
                QMessageBox.warning(self, tr("create_group_failed"), tr("create_group_failed_msg"))
                return
            self._rebuild()
            self.groups_updated.emit()
