"""Emoji grid
表情包网格"""
from PySide6.QtWidgets import (
    QWidget, QLayout, QLayoutItem, QSizePolicy, QLabel, QVBoxLayout,
)
from PySide6.QtCore import Qt, QSize, QRect, Signal, QPoint, QTimer
from PySide6.QtGui import QContextMenuEvent, QPainter, QColor, QPixmap, QPixmapCache
import math

from app.widgets.emoji_item import EmojiItem, _loader, _thumb_key
from app.models.lang_manager import tr
from app.models.logger import get_logger


_GRID_LOG = None


def _grid_log():
    global _GRID_LOG
    if _GRID_LOG is None:
        _GRID_LOG = get_logger()
    return _GRID_LOG


# Fluid layout with adaptive column number / 自适应列数的流式布局
class FlowLayout(QLayout):

    def __init__(self, parent=None, margin=8, spacing=8):
        super().__init__(parent)
        self._items = []
        self._margin = margin
        self._spacing = spacing
        self._masonry = False  # True = Tetris-style compact stacking / 俄罗斯方块式紧凑堆叠
        # Suppress LayoutRequest events during batch add/remove (load_emojis rebuild)
        # 批量增删（load_emojis 重建）期间抑制 LayoutRequest 事件
        self._suppress_invalidate = False
        if parent:
            self.setContentsMargins(margin, margin, margin, margin)
            self.setSpacing(spacing)

    def invalidate(self):
        # Suppress sequential postEvent during batch operation (load_emojis reconstruction)
        # 批量操作（load_emojis 重建）时抑制逐次 postEvent
        if self._suppress_invalidate:
            return
        super().invalidate()

    def set_masonry(self, enabled):
        # Toggle masonry mode: cards are placed in the current shortest column, not aligned by rows
        # 切换 紧凑堆叠 模式：卡片放入当前最短列，不按行对齐
        if self._masonry != enabled:
            self._masonry = enabled
            self.invalidate()
            pw = self.parentWidget()
            if pw:
                self._do_layout(QRect(0, 0, pw.width(), pw.height()), test_only=False)

    def addItem(self, item: QLayoutItem):
        self._items.append(item)
        self.invalidate()

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            item = self._items.pop(index)
            self.invalidate()
            return item
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        # Returns the actual layout height (the scrolling area relies on this value
        # to determine the content height)
        # 返回实际布局高度（滚动区域依赖此值判断内容高度）
        pw = self.parentWidget()
        if pw is not None:
            w = max(pw.width(), 10)
            h = self.heightForWidth(w)
            return QSize(w, h)
        return self.minimumSize()

    def relayout(self):
        pw = self.parentWidget()
        if pw is None:
            return
        self._do_layout(QRect(0, 0, pw.width(), pw.height()), test_only=False)

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            wid = item.widget()
            if wid:
                size = size.expandedTo(wid.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only=False):
        if self._masonry:
            return self._do_masonry(rect, test_only)
        m = self.contentsMargins()
        usable = max(rect.width() - m.left() - m.right(), 10)
        x = m.left()
        y = m.top()
        row_height = 0
        spacing = self._spacing

        for item in self._items:
            wid = item.widget()
            if not wid:
                continue
            # Note: QLayoutItem.sizeHint() returns (0,0) for the widget of isHidden()
            # (the new card has not yet been displayed)
            # and the widget's own size interface must be used.
            # Use minimumSize for fixed size (min==max)
            # and sizeHint for variable width (text card) to ensure that the correct size
            # can be obtained in the hidden state.
            # 注意：QLayoutItem.sizeHint() 对 isHidden() 的 widget（新卡片尚未显示）返回 (0,0)，必须用 widget 自身的尺寸接口。
            # 固定尺寸（min==max）用 minimumSize，可变宽度（文字卡片）用 sizeHint，保证 hidden 状态下也能得到正确尺寸。
            mn = wid.minimumSize()
            mx = wid.maximumSize()
            hint = mn if mn == mx else wid.sizeHint()
            w = min(hint.width(), usable)
            w = max(w, mn.width())
            h = hint.height()
            h = max(h, mn.height())

            if x + w > m.left() + usable and x > m.left():
                x = m.left()
                y += row_height + spacing
                row_height = 0

            if not test_only:
                wid.setGeometry(QRect(x, y, w, h))

            x += w + spacing
            row_height = max(row_height, h)

        return y + row_height + m.bottom()

    def _grid_widget(self):
        pw = self.parentWidget()
        if pw is not None:
            gp = pw.parentWidget()
            if gp is not None and gp.__class__.__name__ == "EmojiGridWidget":
                return gp
        return None

    def _do_masonry(self, rect: QRect, test_only=False):
        # Data-driven layout (_items under lazy loading only contains visible cards,
        # and the position must be calculated from the full amount of data)
        # 数据驱动布局（懒加载下 _items 只含可见卡，必须由全量数据计算位置）
        grid = self._grid_widget()
        if grid is not None and grid._data:
            return grid._do_masonry_data(rect, test_only)
        return self._do_masonry_legacy(rect, test_only)

    def _do_masonry_legacy(self, rect: QRect, test_only=False):
        m = self.contentsMargins()
        usable = max(rect.width() - m.left() - m.right(), 10)
        spacing = self._spacing
        # Group by col_index (stable column members, no inference from layout)
        # 按 col_index 分组（稳定列成员，不从布局反推）
        col_map = {}
        for item in self._items:
            wid = item.widget()
            if not wid:
                continue
            ci = int(wid._emoji.get("col_index", 0))
            col_map.setdefault(ci, []).append((item, wid))
        if not col_map:
            return m.top() + m.bottom()
        # Sort by sort_order within the column / 列内按 sort_order 排序
        for ci in col_map:
            col_map[ci].sort(key=lambda e: int(e[0].widget()._emoji.get("sort_order", 0)))

        x = m.left()
        y_max = m.top()
        for ci in sorted(col_map):
            col_entries = col_map[ci]
            nw_list = []
            for item, wid in col_entries:
                if isinstance(wid, EmojiItem) and wid._is_text:
                    nw_list.append(wid.text_natural_width(wid._emoji.get("text_content", "")))
                else:
                    nw_list.append(max(wid.width(), wid.minimumSize().width(), 10))
            col_w = max(80, min(max(nw_list), usable))
            cy = m.top()
            for item, wid in col_entries:
                if isinstance(wid, EmojiItem) and wid._is_text:
                    if not test_only:
                        wid.reflow(col_w)
                        h = wid.height()
                    else:
                        h = wid.estimate_height(col_w)
                else:
                    h = max(wid.height(), wid.minimumSize().height())
                if not test_only:
                    wid.setGeometry(x, cy, col_w, h)
                cy += h + spacing
            y_max = max(y_max, cy - spacing)
            x += col_w + spacing
        # Set the minimum width of the container = the total width of all columns
        # and trigger horizontal scrolling when it exceeds the visible area
        # (stable columns will not be rearranged)
        # 设置容器最小宽度 = 全部列总宽，超出可视区时触发横向滚动（稳定列不重排）
        pw = self.parentWidget()
        if pw is not None and not test_only:
            pw.setMinimumWidth(max(0, x - spacing) + m.right())
            gp = pw.parentWidget()
            if gp is not None:
                gp.updateGeometry()

        return y_max + m.bottom()


class EmojiGridWidget(QWidget):

    emoji_clicked = Signal(dict)
    emoji_right_clicked = Signal(dict, QPoint)
    emojis_reordered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dm = None
        self._items = []
        self._data = []
        self._preview_limits = (100, 200)
        self._lazy_buffer = 300  # Lazy loading of upper and lower buffer pixels / 懒加载上下缓冲像素
        # Current group (None = All, not involved in sorting) / 当前分组（None = All，不参与排序）
        self.current_group_id = None
        # Number of GIFs played simultaneously (driven by the multi-threaded core-count
        # setting, core count × 2)
        # 同时播放的 GIF 数（由多线程核心数设置驱动，核心数×2）
        self._gif_limit = 8
        self._playing_gifs = set()
        # Emoji grouping: drag-drop insertion position indicator (-1 = not displayed)
        # 图片分组：拖拽插入位置指示（-1 = 不显示）
        self._drop_index = -1
        self._drop_col = -1    # Text grouping: target column / 文字分组：目标列
        self._drop_order = 0   # Text grouping: insertion position within column / 文字分组：列内插入位置
        self._is_text_group = False
        self.setAcceptDrops(True)

        self._merge_timer = QTimer(self)
        self._merge_timer.setSingleShot(True)
        self._merge_timer.setInterval(150)
        self._merge_timer.timeout.connect(self._check_column_merge)

        # Asynchronous thumbnails / 异步缩略图
        _loader.done.connect(self._on_thumb_ready)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._placeholder = QLabel(self)
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setWordWrap(True)
        self._placeholder.setStyleSheet(
            "color: #666; font-size: 14px; background: transparent; padding: 40px;"
        )
        self._placeholder.hide()
        outer.addWidget(self._placeholder)

        self._flow_container = QWidget(self)
        self._flow = FlowLayout(self._flow_container, margin=10, spacing=8)
        outer.addWidget(self._flow_container, 1)

    def _on_thumb_ready(self, key, img):
        if img.isNull():
            return
        pix = QPixmap.fromImage(img)
        QPixmapCache.insert(key, pix)
        for card in self._items:
            if card._thumb_path and _thumb_key(card._thumb_path) == key:
                card.apply_thumb(pix)

    def set_data_manager(self, dm):
        self._dm = dm

    def _masonry_layout_data(self, usable):
        # Calculate the masonry layout in full based on self._data and return
        # (rects: {emoji_id: (x,y,w,h)}, total_w, total_h, col_info)
        # 基于 self._data 全量计算 masonry 布局，
        # 返回 (rects: {emoji_id: (x,y,w,h)}, total_w, total_h, col_info)
        m = self._flow.contentsMargins()
        spacing = self._flow.spacing()
        cols = {}
        for em in self._data:
            cols.setdefault(int(em.get("col_index", 0)), []).append(em)
        for ci in cols:
            cols[ci].sort(key=lambda e: int(e.get("sort_order", 0)))
        if not cols:
            return {}, 0, m.top() + m.bottom(), {}
        col_widths = {}
        for ci, lst in cols.items():
            nw = max(
                (EmojiItem.text_natural_width(e.get("text_content", ""))
                 if e.get("text_content") else 100)
                for e in lst
            )
            col_widths[ci] = max(80, min(nw, usable))
        x = m.left()
        col_x = {}
        for ci in sorted(cols):
            col_x[ci] = x
            x += col_widths[ci] + spacing
        total_w = max(0, x - spacing) + m.right()
        rects = {}
        col_h = {}
        for ci in sorted(cols):
            w = col_widths[ci]
            cy = m.top()
            for em in cols[ci]:
                if em.get("text_content"):
                    h = EmojiItem.estimate_height_static(em.get("text_content", ""), w)
                else:
                    h = EmojiItem.CARD_SIZE + 22
                rects[em["id"]] = (col_x[ci], cy, w, h)
                cy += h + spacing
            col_h[ci] = cy - spacing
        total_h = max(col_h.values()) + m.bottom()
        return rects, total_w, total_h, {
            "col_x": col_x, "col_widths": col_widths, "col_h": col_h,
        }

    def _do_masonry_data(self, rect, test_only=False):
        m = self._flow.contentsMargins()
        spacing = self._flow.spacing()
        usable = max(rect.width() - m.left() - m.right(), 10)
        _rects, total_w, total_h, info = self._masonry_layout_data(usable)
        if not test_only:
            by_col = {}
            for card in self._items:
                by_col.setdefault(int(card._emoji.get("col_index", 0)), []).append(card)
            for ci, cards in by_col.items():
                if ci not in info["col_x"]:
                    continue
                w = info["col_widths"][ci]
                cx = info["col_x"][ci]
                cy = m.top()
                cards.sort(key=lambda c: int(c._emoji.get("sort_order", 0)))
                for card in cards:
                    if card._is_text and card.width() != w:
                        card.reflow(w)
                    h = card.height()
                    card.setGeometry(cx, cy, w, h)
                    cy += h + spacing
            pw = self._flow.parentWidget()
            if pw is not None:
                pw.setMinimumWidth(max(total_w, 10))
                gp = pw.parentWidget()
                if gp is not None:
                    gp.updateGeometry()
        return total_h

    def _usable_width(self):
        return max(self._viewport_width() - 20, 10)

    def _ensure_visible(self):
        # Lazy loading / 懒加载
        if not self._data or self.current_group_id is None:
            return
        sc = self._find_scroll()
        if sc is None:
            return
        sb = sc.verticalScrollBar()
        y0 = sb.value() - self._lazy_buffer
        y1 = sb.value() + sc.viewport().height() + self._lazy_buffer
        rects, _tw, _th, _info = self._masonry_layout_data(self._usable_width())
        dm = self._find_data_manager()
        existing = {card._emoji.get("id") for card in self._items}
        created = False
        for em in self._data:
            if em["id"] in existing:
                continue
            r = rects.get(em["id"])
            if r is None:
                continue
            if r[1] > y1 or r[1] + r[3] < y0:
                continue
            card = EmojiItem(em, dm, self._flow_container,
                             preview_limits=self._preview_limits)
            card.clicked.connect(self._on_card_clicked)
            self._items.append(card)
            self._flow.addWidget(card)
            created = True
        if created:
            self._flow.invalidate()
            self._flow.activate()
            self._flow.relayout()
            self._update_visible_gifs()

    def _ensure_scroll_connected(self):
        if getattr(self, "_scroll_connected", False):
            return
        sc = self._find_scroll()
        if sc is None:
            return
        sb = sc.verticalScrollBar()
        sb.valueChanged.connect(self._ensure_visible)
        sb.rangeChanged.connect(self._ensure_visible)
        sb.valueChanged.connect(self._update_visible_gifs)
        sb.rangeChanged.connect(self._update_visible_gifs)
        self._scroll_connected = True

    def _update_visible_gifs(self):
        if not self._items:
            return
        sc = self._find_scroll()
        if sc is None:
            return
        sb = sc.verticalScrollBar()
        y0 = sb.value() - 150
        y1 = sb.value() + sc.viewport().height() + 150
        visible = []
        for card in self._items:
            if card._is_text or not card.is_gif():
                continue
            r = card.geometry()
            if r.y() > y1 or r.y() + r.height() < y0:
                continue
            visible.append((r.y(), card))
        visible.sort(key=lambda e: e[0])
        limit = max(1, getattr(self, "_gif_limit", 8))
        wanted = {id(card) for _y, card in visible[:limit]}
        playing = getattr(self, "_playing_gifs", set())
        new_playing = set()
        for _y, card in visible:
            if id(card) in wanted:
                card.play_animation()
                new_playing.add(id(card))
            elif id(card) in playing:
                card.stop_animation()
        for cid in playing - new_playing:
            for card in self._items:
                if id(card) == cid:
                    card.stop_animation()
                    break
        self._playing_gifs = new_playing

    def load_emojis(self, emojis, group_type="image", preview_limits=(100, 200)):
        self._is_text_group = (group_type == "text")
        self._flow._suppress_invalidate = True
        try:
            while self._flow.count() > 0:
                self._flow.takeAt(0)

            if not emojis:
                self._flow_container.hide()
                self._data = []
                for card in self._items:
                    card._stop_gif()
                    card.deleteLater()
                self._items = []
                if group_type == "text":
                    msg = tr("paste_text_placeholder")
                else:
                    msg = tr("drag_placeholder")
                self._placeholder.setText(msg)
                self._placeholder.show()
                return

            self._placeholder.hide()
            self._flow_container.show()
            self._flow.set_masonry(self.current_group_id is not None)
            self._data = list(emojis)
            self._preview_limits = preview_limits

            dm = self._find_data_manager()

            if self.current_group_id is None:
                old_cards = {card._emoji.get("id"): card for card in self._items}
                new_items = []
                for em in emojis:
                    card = old_cards.pop(em.get("id"), None)
                    if card is not None and card._is_text == bool(em.get("text_content")):
                        card._emoji = em
                    else:
                        card = EmojiItem(em, dm, self._flow_container,
                                         preview_limits=preview_limits)
                        card.clicked.connect(self._on_card_clicked)
                    new_items.append(card)
                    self._flow.addWidget(card)
                for card in old_cards.values():
                    card._stop_gif()
                    card.deleteLater()
                self._items = new_items
            else:
                keep_ids = {em.get("id") for em in emojis}
                emap = {em.get("id"): em for em in emojis}
                survivors = []
                for card in self._items:
                    cid = card._emoji.get("id")
                    if cid in keep_ids:
                        card._emoji = emap[cid]
                        survivors.append(card)
                    else:
                        card._stop_gif()
                        card.deleteLater()
                self._items = survivors
                self._ensure_scroll_connected()
                self._ensure_visible()
        finally:
            self._flow._suppress_invalidate = False

        self._flow.invalidate()
        self._flow.activate()
        self._flow.relayout()
        self._flow_container.updateGeometry()
        self.updateGeometry()

        if self.current_group_id is not None:
            QTimer.singleShot(0, self._check_column_merge)
        QTimer.singleShot(0, self._update_visible_gifs)

    # After loading/resizing, check whether columns that cannot be fully shown should be merged
    # into the front ones (lightweight internal refresh, no rebuild)
    # 加载/调整后检查：无法完整显示的列融合进前列（内部轻量刷新，不重建）
    def _check_column_merge(self):
        if self.current_group_id is not None and self._data:
            self._merge_overflow_columns()

    # Lightweight refresh after merge / drag reorder (write-back to DB): update all data and
    # already-created cards, then relayout; avoids jank from a full rebuild (QPixmap re-decoding)
    # 融合/拖拽写库后轻量刷新：更新全量数据与已创建卡片并重新布局，
    # 避免全量重建（QPixmap 重新解码）造成卡顿。
    def _refresh_cards_after_merge(self):
        dm = self._find_data_manager()
        if dm is None:
            return
        fresh = dm.get_emojis_by_group(self.current_group_id)
        emap = {e["id"]: e for e in fresh}
        self._data = fresh
        for card in self._items:
            e = emap.get(card._emoji["id"])
            if e:
                card._emoji = e
        self._flow.invalidate()
        self._flow.activate()
        self._flow.relayout()
        self._flow_container.updateGeometry()
        self.updateGeometry()
        self._ensure_visible()
        # Refresh the visible GIF play set after positions changed / 位置变化后刷新可见 GIF 播放集合
        self._update_visible_gifs()

    def _find_data_manager(self):
        p = self.parent()
        while p:
            if hasattr(p, 'data_manager'):
                return p.data_manager
            p = p.parent()
        return None

    def _on_card_clicked(self, emoji):
        self.emoji_clicked.emit(emoji)

    def contextMenuEvent(self, event):
        pos = event.globalPos()
        local = self.mapFromGlobal(pos)
        child = self.childAt(local)
        while child and not isinstance(child, EmojiItem):
            child = child.parent()
        if isinstance(child, EmojiItem):
            self.emoji_right_clicked.emit(child._emoji, pos)
            event.accept()
            return
        # Right-click on blank space: one-click rearrange (evenly re-distribute columns to the
        # current window width, removing the gaps left after stretching the window)
        # 空白处右键：一键整理（按当前窗口宽度重新均匀分列，消除拉伸窗口后的空缺）
        if self.current_group_id is not None and self._data:
            from PySide6.QtWidgets import QMenu
            menu = QMenu(self)
            act = menu.addAction(tr("rearrange"))
            if menu.exec(pos) == act:
                self._rearrange()
        event.accept()

    # One-click rearrange: compute the column count from the current window width (icon column
    # count is decided by window/screen size), then evenly re-distribute all cards in global
    # order to remove the gaps left after stretching the window
    # 一键整理：按当前窗口宽度计算列数（图标列数由窗口/屏幕大小决定），
    # 所有卡片按全局顺序均匀重分配列，消除拉伸窗口后的空白空缺。
    def _rearrange(self):
        if self.current_group_id is None or not self._data:
            return
        dm = self._find_data_manager()
        if dm is None:
            return
        usable = self._usable_width()
        spacing = self._flow.spacing()
        # Column-width baseline: max natural width in the group (100 for images / text natural
        # width), so every column is fully displayed
        # 列宽基准：组内最大自然宽（图片 100 / 文字自然宽），保证每列完整显示
        base_w = 100
        for em in self._data:
            if em.get("text_content"):
                base_w = max(base_w, EmojiItem.text_natural_width(em.get("text_content", "")))
        # Column count = the max number of columns the usable width can hold
        # 列数 = 可用宽度能容纳的最大列数
        k = max(1, (usable + spacing) // (base_w + spacing))
        dm.rearrange_columns(self.current_group_id, k)
        _grid_log().info("One-click rearrange -> group=%s cols=%d cards=%d",
                         self.current_group_id, k, len(self._data))
        self._refresh_cards_after_merge()

    # ------------------------------------------------------------------
    # Drag & drop: text groups move across columns / image groups sort within the group
    # 拖拽：文字分组跨列移动 / 图片分组组内排序
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-emoji-id"):
            if self.current_group_id is not None and self._data:
                self._drop_col = 0
                self._drop_order = 0
                self.update()
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat("application/x-emoji-id") and self._data:
            event.acceptProposedAction()
            pos = event.position().toPoint()
            col, order = self._drop_target(pos)
            if col != self._drop_col or order != self._drop_order:
                # Partial repaint: only refresh the old/new insert-bar regions to avoid full
                # repaint jank / 局部重绘：只刷新旧/新插入条区域，避免全量重绘卡顿
                old = self._drop_line_rect_h()
                self._drop_col, self._drop_order = col, order
                new = self._drop_line_rect_h()
                if old is not None:
                    self.update(old.adjusted(-4, -4, 4, 4))
                if new is not None:
                    self.update(new.adjusted(-4, -4, 4, 4))
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        old = self._drop_line_rect_h()
        self._drop_index = -1
        self._drop_col = -1
        self._drop_order = 0
        if old is not None:
            self.update(old.adjusted(-4, -4, 4, 4))
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        old = self._drop_line_rect_h()
        self._drop_index = -1
        self._drop_col = -1
        self._drop_order = 0
        if old is not None:
            self.update(old.adjusted(-4, -4, 4, 4))
        if event.mimeData().hasFormat("application/x-emoji-id"):
            try:
                dragged_id = int(bytes(event.mimeData().data("application/x-emoji-id")).decode())
            except (ValueError, TypeError):
                event.ignore()
                return
            if self.current_group_id is None or not self._data:
                event.ignore()
                return
            dm = self._find_data_manager()
            # Unified column mode: drop to the target position in the target column
            # (move within/across columns) / 统一列模式：拖拽到目标列的指定位置（列内/列间移动）
            col, order = self._drop_target(event.position().toPoint(), exclude=dragged_id)
            dm.set_emoji_column(dragged_id, col, order)
            dm.compact_text_columns(self.current_group_id)
            event.acceptProposedAction()
            _grid_log().info("Drag reorder -> emoji=%s group=%s target_col=%s order=%s",
                             dragged_id, self.current_group_id, col, order)
            # Lightweight refresh (update card data + relayout, avoiding full rebuild jank)
            # 轻量刷新（更新卡片数据 + 重排，避免全量重建卡顿）
            self._refresh_cards_after_merge()
        else:
            event.ignore()

    # Draw the white drop-position indicator bar: horizontal inside a column,
    # vertical for a new column / 绘制白色插入位置指示条：列内画水平条，新列画垂直条
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = None
        if self._drop_col < 0 or not self._data:
            return
        rect = self._drop_line_rect_h()
        if rect is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(rect, QColor(255, 255, 255))
        painter.end()

    # Horizontal separator bar inside a column (data-driven estimated position); for a new
    # column, draw a vertical bar on the right of the last column
    # 列内水平分界条（数据驱动预估位置）；新列时画垂直条在最后一列右侧
    def _drop_line_rect_h(self):
        if self._drop_col < 0:
            return None
        rects, _tw, _th, _info = self._masonry_layout_data(self._usable_width())
        col_entries = [(em, rects[em["id"]])
                       for em in self._data
                       if int(em.get("col_index", 0)) == self._drop_col
                       and em["id"] in rects]
        if not col_entries:
            # New column: draw a vertical separator bar on the right of the last column
            # 新列：在最后一列右侧画垂直分界条
            max_col = max((int(e.get("col_index", 0)) for e in self._data), default=-1)
            last_entries = [(em, rects[em["id"]]) for em in self._data
                            if int(em.get("col_index", 0)) == max_col and em["id"] in rects]
            if last_entries:
                last = sorted(last_entries, key=lambda e: e[1][1])[-1][1]
                return QRect(last[0] + last[2], last[1], 3, last[3])
            return None
        col_entries.sort(key=lambda e: e[1][1])
        n = len(col_entries)
        order = max(0, min(self._drop_order, n))
        if order == 0:
            first = col_entries[0][1]
            return QRect(first[0], first[1] - 2, first[2], 3)
        if order >= n:
            last = col_entries[-1][1]
            return QRect(last[0], last[1] + last[3] - 1, last[2], 3)
        prev = col_entries[order - 1][1]
        nxt = col_entries[order][1]
        y = (prev[1] + prev[3] + nxt[1]) // 2 - 1
        return QRect(prev[0], y, prev[2], 3)

    # Compute (target column, insertion order inside the column) from the full data set, since
    # cards may not be created yet under lazy loading
    # 计算 (目标列, 列内插入位置)——基于全量数据预估位置（懒加载下卡片可能未创建）
    def _drop_target(self, pos, exclude=None):
        rects, _tw, _th, _info = self._masonry_layout_data(self._usable_width())
        cols = {}
        for em in self._data:
            if em.get("id") == exclude:
                continue
            r = rects.get(em.get("id"))
            if r is None:
                continue
            cols.setdefault(int(em.get("col_index", 0)), []).append((em, r))
        if not cols:
            return (0, 0)
        # x range of each column / 列的 x 范围
        col_xs = {}
        for ci, entries in cols.items():
            xs = [r[0] for _e, r in entries]
            xr = [r[0] + r[2] for _e, r in entries]
            col_xs[ci] = (min(xs), max(xr))
        # Target column: the column containing pos.x / 目标列：pos.x 所在列
        target_col = None
        for ci, (x0, x1) in col_xs.items():
            if x0 <= pos.x() <= x1:
                target_col = ci
                break
        if target_col is None:
            # Not inside any column: blank space on the right (in the viewport, right of the
            # last column) → try opening a new column; otherwise use the nearest column
            # 不在任何列内：右侧空白（视口内、最后一列右侧）→ 尝试开新列；否则最近列
            max_col = max(col_xs)
            last_right = col_xs[max_col][1]
            sc = self._find_scroll()
            offset = sc.horizontalScrollBar().value() if sc else 0
            vp_w = self._viewport_width()
            in_view = pos.x() - offset <= vp_w
            if pos.x() > last_right and in_view:
                new_col = self._blank_zone_col(exclude)
                if new_col is not None:
                    return (new_col, 0)  # Open a new column / 开新列
                # Cannot open a new column → append to the end of the last column
                # 不能开新列 → 最后一列末尾
                return (max_col, len(cols[max_col]))
            best, bd = None, float("inf")
            for ci, (x0, x1) in col_xs.items():
                d = abs(pos.x() - (x0 + x1) // 2)
                if d < bd:
                    bd, best = d, ci
            target_col = best
        # Insertion order inside the column: compare pos.y with the card centers
        # 列内插入位置：比较 pos.y 与卡片中心
        col_items = sorted(cols[target_col], key=lambda e: e[1][1])
        order = len(col_items)
        for i, (_e, r) in enumerate(col_items):
            if pos.y() < r[1] + r[3] / 2:
                order = i
                break
        return (target_col, order)

    # Right blank zone: if the dragged card can open a new column by itself, return the new
    # column number, otherwise None / 右侧空白区：若被拖卡片能单独开一列则返回新列号，否则返回 None
    def _blank_zone_col(self, exclude=None):
        dragged = None
        for em in self._data:
            if em.get("id") == exclude:
                dragged = em
                break
        if dragged is None:
            return None
        nw = (EmojiItem.text_natural_width(dragged.get("text_content", ""))
              if dragged.get("text_content") else 100)
        usable = self._usable_width()
        spacing = self._flow.spacing()
        new_w = min(max(nw, 80), usable)
        # Current total width of the columns (data-driven, excluding the dragged card)
        # 当前列总宽（数据驱动，排除被拖卡）
        col_widths = {}
        for em in self._data:
            if em.get("id") == exclude:
                continue
            ci = int(em.get("col_index", 0))
            w = (EmojiItem.text_natural_width(em.get("text_content", ""))
                 if em.get("text_content") else 100)
            col_widths[ci] = max(col_widths.get(ci, 0), min(w, usable))
        total = sum(col_widths.values()) + spacing * max(0, len(col_widths) - 1)
        if total + spacing + new_w <= usable:
            return max(col_widths) + 1 if col_widths else 0
        return None

    # When the window shrinks, columns that cannot be fully shown are merged, one by one in
    # order, into the front columns that can be fully shown. "Fully shown" means the column's
    # natural width ≤ visible width and the total width of all columns fits.
    # Returns True when a merge happened (a reload is needed).
    # 窗口缩小时，无法完整显示的列按顺序依次并入能完整显示的前列。
    # 完整显示 = 该列自然宽 ≤ 可视宽，且各列总宽放得下。
    # 返回 True 表示发生了融合（需要重新加载）。
    def _merge_overflow_columns(self):
        if self.current_group_id is None or not self._data:
            return False
        dm = self._find_data_manager()
        spacing = self._flow.spacing()
        # Keep consistent with the real layout width used in _do_masonry (viewport width - 10*2)
        # 与 _do_masonry 的实际布局宽度保持一致（viewport 宽 - contentsMargins 10*2）
        usable = max(self._viewport_width() - 20, 10)
        # Width per column (natural content width, un-clamped) — data-driven since cards may
        # not be created yet under lazy loading
        # 每列宽度（按内容自然宽，不 clamp）——数据驱动（懒加载下卡片可能未创建）
        col_widths = {}
        for em in self._data:
            ci = int(em.get("col_index", 0))
            if em.get("text_content"):
                nw = EmojiItem.text_natural_width(em.get("text_content", ""))
            else:
                nw = 100  # Image cards have a fixed width / 图片卡片固定宽
            col_widths[ci] = max(col_widths.get(ci, 0), nw)
        cols = sorted(col_widths)
        if not cols:
            return False
        # Per column, decide whether it can be opened alone fully:
        #   ① the column's natural width ≤ visible width (otherwise content is compressed → merge)
        #   ② the accumulated total width (including this column) ≤ visible width
        #   (otherwise overflow → merge)
        # 逐列判定"能否完整单开"：
        #   ① 该列自然宽 ≤ 可视宽（否则内容被压缩，显示不全 → 融合）
        #   ② 累加总宽（含该列）≤ 可视宽（否则溢出 → 融合）
        keep = []      # Columns that can be fully shown and fit / 能完整显示且放得下的列
        overflow = []  # Columns that need to be merged / 需要融合的列
        total = 0
        for ci in cols:
            w = max(80, col_widths[ci])
            if w > usable:
                overflow.append(ci)
                continue
            new_total = w if not keep else total + spacing + w
            if keep and new_total > usable:
                overflow.append(ci)
                continue
            keep.append(ci)
            total = new_total
        if not overflow:
            return False
        # Target columns: cycle among the columns that are fully shown
        # (if keep is empty, merge everything into the first column)
        # 目标列：能完整显示的列循环（若 keep 为空则全部并入第一列）
        if not keep:
            keep = [cols[0]]
        # Batch merge in a single transaction + column-number compaction
        # (avoids jank from per-row commits)
        # 单事务批量融合 + 列号压缩（避免逐条 commit 造成卡顿）
        dm.merge_columns_into(self.current_group_id, overflow, keep)
        # Lightweight refresh of existing cards (no rebuild, avoids QPixmap re-decoding jank)
        # 轻量刷新现有卡片（不重建，避免 QPixmap 重新解码卡顿）
        self._refresh_cards_after_merge()
        return True

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Merge overflowing columns when the window shrinks (150ms debounce: a resize storm
        # from dragging the window edge triggers only one pass)
        # 缩小窗口时融合溢出列（150ms 防抖：拖拽窗口边缘的 resize 风暴只触发一次）
        if self.current_group_id is not None and self._data:
            self._merge_timer.start()

    def _find_scroll(self):
        from PySide6.QtWidgets import QScrollArea
        p = self.parent()
        while p:
            if isinstance(p, QScrollArea):
                return p
            p = p.parent()
        return None

    # Visible viewport width; when scrolled horizontally the grid is stretched, so the viewport
    # width, not the grid width, must be used to detect blank space
    # 可视视口宽度（横向滚动时网格被拉伸，需用视口而非网格宽度判断空白）
    def _viewport_width(self):
        sc = self._find_scroll()
        if sc is not None:
            return max(sc.viewport().width(), 100)
        return max(self.width(), 100)

    # ------------------------------------------------------------------
    # Text grouping: on add, assign a column (open a new one if possible, else the shortest column)
    # 文字分组：添加时分配列（能开新列就开，否则放行高最小列）
    # ------------------------------------------------------------------

    # Current layout width of each column (max card width per col_index group)
    # 当前各列布局宽度（按 col_index 分组取最大卡片宽）
    def _current_col_widths(self):
        cols = {}
        for it in self._items:
            ci = int(it._emoji.get("col_index", 0))
            cols[ci] = max(cols.get(ci, 0), it.width())
        return [cols[k] for k in sorted(cols)]

    # New text-emoji column assignment: open a new column when possible, otherwise put the
    # card into the column with the fewest cards / 新文字表情列分配：能单独开一列则开新列，否则放入卡片最少的列。
    def assign_new_text_column(self, emoji_id, group_id, text, usable_w):
        self._assign_to_column(
            emoji_id, group_id, EmojiItem.text_natural_width(text), usable_w
        )

    # Unassigned cards (user_sorted=0, e.g. newly imported / migrated old data) are spread
    # across columns automatically based on the current window width: open a new column when
    # possible (wider window → more columns), otherwise append to the end of the column with
    # the fewest cards. Writes to DB and sets user_sorted=1 (after that, the user/program
    # assignment is kept; resize only merges, never resets). Returns whether any card was assigned.
    # 未分配卡片（user_sorted=0，如新导入/旧数据迁移）按当前窗口宽自动摊列：
    # 能开新列则开（窗口大 → 多列），否则放卡片最少的列末尾。
    # 写入 DB 并置 user_sorted=1（从此保持用户/程序分配的列，resize 只融合不重置）。
    # 返回是否分配了任何卡片。
    def assign_unassigned_columns(self, group_id):
        dm = self._find_data_manager()
        if dm is None:
            return False

        def width_of(e):
            return (EmojiItem.text_natural_width(e.get("text_content", ""))
                    if e.get("text_content") else 100)

        # Consistent with the _do_masonry layout (viewport width - contentsMargins 10*2)
        # 与 _do_masonry 布局一致（viewport 宽 - contentsMargins 10*2）
        usable = max(self._viewport_width() - 20, 10)
        return dm.assign_unassigned_columns(
            group_id, usable, self._flow.spacing(), width_of
        ) > 0

    # Generic column assignment: open a new column when possible, otherwise put the card at the
    # end of the column with the fewest cards. Column widths/counts are computed from the DB
    # contents, not from the current UI grid state.
    # 通用列分配：能开新列则开新列，否则放卡片最少的列末尾。
    # 列宽/列计数从数据库内容计算（不依赖当前 UI 网格状态）。
    def _assign_to_column(self, emoji_id, group_id, natural_w, usable_w):
        dm = self._find_data_manager()
        spacing = self._flow.spacing()
        new_w = min(max(natural_w, 80), usable_w)
        # Compute column widths and card counts from the current DB contents
        # (excluding the new card itself) / 从 DB 读当前各列内容算列宽与卡片数（排除新卡自身）
        emojis = dm.get_emojis_by_group(group_id)
        col_widths = {}
        col_counts = {}
        for e in emojis:
            if e["id"] == emoji_id:
                continue
            ci = int(e.get("col_index", 0))
            nw = (EmojiItem.text_natural_width(e.get("text_content", ""))
                  if e.get("text_content") else 100)
            col_widths[ci] = max(col_widths.get(ci, 0), nw)
            col_counts[ci] = col_counts.get(ci, 0) + 1
        total = sum(col_widths.values()) + spacing * max(0, len(col_widths) - 1)
        if not col_widths or total + spacing + new_w <= usable_w:
            new_col = dm.text_max_col(group_id) + 1
            dm.set_emoji_column(emoji_id, new_col, 0)
        else:
            min_col = min(col_counts, key=col_counts.get)
            dm.set_emoji_column(emoji_id, min_col, col_counts[min_col])
        dm.compact_text_columns(group_id)
