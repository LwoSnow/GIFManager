"""Emoji grid
表情包网格"""
import math
import time
from PySide6.QtWidgets import (
    QWidget, QLayout, QLayoutItem, QSizePolicy, QLabel, QVBoxLayout, QMenu,
)
from PySide6.QtCore import Qt, QSize, QRect, Signal, QPoint, QTimer
from PySide6.QtGui import QContextMenuEvent, QPainter, QColor, QPixmap, QPixmapCache, QPen

from app.widgets.emoji_item import EmojiItem, _loader, _thumb_key
from app.models.lang_manager import tr
from app.models.logger import get_logger


_GRID_LOG = None


def _grid_log():
    global _GRID_LOG
    if _GRID_LOG is None:
        _GRID_LOG = get_logger()
    return _GRID_LOG


# Transparent overlay that draws the drag-drop indicator on top of the card container,
# because painting on the grid itself is covered by child widgets
# 置顶透明覆盖层：绘制拖放引导条（画在网格自身会被卡片容器子控件遮挡）
class _DropOverlay(QWidget):
    def __init__(self, grid):
        super().__init__(grid)
        self._grid = grid
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setStyleSheet("background: transparent;")
        self.hide()

    def paintEvent(self, event):
        rect = self._grid._drop_indicator_rect()
        if rect is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        if self._grid._drop_mode == "swap":
            # White border around the swap target card / 交换目标卡片白色边框
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
        else:
            # White insert bar (horizontal gap / vertical new column) / 白色插入条（水平间隙 / 垂直新列）
            painter.fillRect(rect, QColor(255, 255, 255))
        painter.end()


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
        grid = self._grid_widget()
        if grid is not None and grid._is_all_view:
            # All view: data-driven lazy grid (fixed-size image cards)
            # All 视图：数据驱动的懒加载网格（固定尺寸图片卡）
            return grid._do_all_grid(rect, test_only)
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
    selection_changed = Signal(int)  # number of selected items / 选中数量
    edit_mode_changed = Signal(bool)  # multi-select mode entered/left / 多选模式进入/退出

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dm = None
        self._items = []
        self._thumb_index = {}  # thumb_key -> list of cards / 缩略图 key 到卡片列表
        self._data = []
        self._preview_limits = (100, 200)
        self._layout_cache = None  # masonry layout cache (width, data id) / masonry 布局缓存
        self._all_cache = None     # All-view grid cache / All 视图网格缓存
        # Multi-select edit mode / 多选编辑模式
        self._selection_mode = False
        self._selection = {}  # emoji id str -> emoji dict / 选中的表情
        # Whether image cards show their name (settings "show_emoji_name") /
        # 图片卡是否显示名称（设置"显示表情包名称"）
        self._show_emoji_name = True
        # Hover zoom factor for image cards (settings "hover_zoom") /
        # 图片卡悬停放大倍数（设置"悬停放大倍数"）
        self._hover_zoom = 1.15
        # Master switch for the hover preview (settings) / 悬停预览总开关（设置）
        self._hover_preview_enabled = True
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
        self._drop_mode = "insert"  # Gap insert / swap with card under cursor / 间隙插入 / 卡片交换
        self._drop_target_id = None  # Swap target card id / 交换目标卡片 id
        self._last_sort_by = None    # Last blank-menu sort kind / 上次空白菜单整理方式
        self._last_sort_time = 0.0   # Last blank-menu sort timestamp / 上次整理时间戳
        self._last_sort_desc = False  # Last blank-menu sort direction / 上次整理方向（True=逆序）
        self._is_text_group = False
        self.setAcceptDrops(True)

        self._merge_timer = QTimer(self)
        self._merge_timer.setSingleShot(True)
        self._merge_timer.setInterval(150)
        self._merge_timer.timeout.connect(self._check_column_merge)

        # Resize refresh (debounced): lazy-create cards and refresh the
        # visible-GIF set after the window size settles
        # resize 后刷新（防抖）：窗口尺寸稳定后懒加载创建卡片并刷新可见 GIF
        self._resize_refresh_timer = QTimer(self)
        self._resize_refresh_timer.setSingleShot(True)
        self._resize_refresh_timer.setInterval(150)
        self._resize_refresh_timer.timeout.connect(self._on_resize_refresh)

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

        # Top-most drop indicator overlay (mouse-transparent) / 置顶拖放引导条覆盖层（鼠标穿透）
        self._drop_overlay = _DropOverlay(self)
        self._drop_overlay.setGeometry(self.rect())
        self._drop_overlay.raise_()

    def release_gif_handles(self):
        # Stop every animation and detach its file handles so Windows
        # allows renaming/deleting the current group folder
        # 停止所有动画并分离文件句柄，使 Windows 允许重命名/删除当前分组目录
        for card in self._items:
            card.stop_animation()

    def _on_thumb_ready(self, key, img):
        if img.isNull():
            return
        pix = QPixmap.fromImage(img)
        QPixmapCache.insert(key, pix)
        # O(1) lookup via the index (key -> list of cards: the All view can
        # show the same file in several folded cards); fall back to a scan
        # when the index is stale / 用索引 O(1) 查找（key -> 卡片列表：
        # All 视图同一文件可能折叠为多张卡）；索引滞后时回退遍历
        cards = self._thumb_index.get(key)
        if cards:
            for card in cards:
                card.apply_thumb(pix)
            return
        for card in self._items:
            if card._thumb_path and _thumb_key(card._thumb_path) == key:
                card.apply_thumb(pix)

    def set_data_manager(self, dm):
        self._dm = dm

    @property
    def _is_all_view(self):
        # True in the "All" aggregation view (lazy grid layout) / "全部"聚合视图
        return self.current_group_id is None and bool(self._data)

    def _all_grid_data(self, usable):
        # Grid layout for the All view: every card is a fixed-size image
        # card (no text cards in All), so positions are pure arithmetic.
        # Returns (rects: {emoji_id: (x,y,w,h)}, total_h, per_row).
        # All 视图网格布局：卡片全部为固定尺寸图片卡（All 视图不含文字卡），
        # 位置为纯算术。返回 (rects: {emoji_id: (x,y,w,h)}, total_h, per_row)。
        key = (usable, id(self._data))
        cached = getattr(self, "_all_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        m = self._flow.contentsMargins()
        spacing = self._flow.spacing()
        cw = EmojiItem.CARD_SIZE
        ch = EmojiItem.card_height(self._show_emoji_name)
        per_row = max(1, (usable + spacing) // (cw + spacing))
        rects = {}
        for i, em in enumerate(self._data):
            rects[em["id"]] = (
                m.left() + (i % per_row) * (cw + spacing),
                m.top() + (i // per_row) * (ch + spacing),
                cw, ch,
            )
        rows = (len(self._data) + per_row - 1) // per_row if self._data else 0
        total_h = m.top() + rows * (ch + spacing) - spacing + m.bottom()
        total_h = max(total_h, 0)
        result = (rects, total_h, per_row)
        self._all_cache = (key, result)
        return result

    def _do_all_grid(self, rect, test_only=False):
        m = self._flow.contentsMargins()
        usable = max(rect.width() - m.left() - m.right(), 10)
        rects, total_h, _per_row = self._all_grid_data(usable)
        if not test_only:
            for card in self._items:
                r = rects.get(card._emoji.get("id"))
                if r is not None:
                    card.setGeometry(r[0], r[1], r[2], r[3])
            pw = self._flow.parentWidget()
            if pw is not None:
                pw.setMinimumWidth(max(usable + m.left() + m.right(), 10))
                gp = pw.parentWidget()
                if gp is not None:
                    gp.updateGeometry()
        return total_h

    def _masonry_layout_data(self, usable):
        # Calculate the masonry layout in full based on self._data and return
        # (rects: {emoji_id: (x,y,w,h)}, total_w, total_h, col_info)
        # 基于 self._data 全量计算 masonry 布局，
        # 返回 (rects: {emoji_id: (x,y,w,h)}, total_w, total_h, col_info)
        # Cache the result: the layout depends only on the usable width and
        # the data set, so per-scroll recomputation is wasted work (this ran
        # on every scrollbar tick with 600+ items, hurting scroll smoothness)
        # 缓存结果：布局只取决于可用宽度与数据集，滚动时逐次重算是浪费
        # （此前每次滚动都会对 600+ 项全量重算，影响滚动流畅度）
        key = (usable, id(self._data))
        cached = getattr(self, "_layout_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
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
                    h = EmojiItem.card_height(self._show_emoji_name)
                rects[em["id"]] = (col_x[ci], cy, w, h)
                cy += h + spacing
            col_h[ci] = cy - spacing
        total_h = max(col_h.values()) + m.bottom()
        result = (rects, total_w, total_h, {
            "col_x": col_x, "col_widths": col_widths, "col_h": col_h,
        })
        self._layout_cache = (key, result)
        return result

    def _do_masonry_data(self, rect, test_only=False):
        m = self._flow.contentsMargins()
        spacing = self._flow.spacing()
        usable = max(rect.width() - m.left() - m.right(), 10)
        rects, total_w, total_h, info = self._masonry_layout_data(usable)
        if not test_only:
            # Position every created card by its DATA rect (absolute layout
            # position). Re-packing the _items list from the top of each
            # column is wrong under lazy loading + recycling: _items only
            # holds the cards near the viewport, so re-packing moved them
            # all to the top and the recycle pass deleted them as "scrolled
            # out" (bottom cards went missing). / 按数据 rect（绝对布局位置）
            # 定位每张已创建的卡。懒加载+回收下 _items 只含视口附近的卡，
            # 从列顶重排会把它们全挪到顶部，回收逻辑误判"滚出"而删除
            # （导致下方卡片大量缺失）。
            for card in self._items:
                r = rects.get(card._emoji.get("id"))
                if r is None:
                    continue
                x, y, w, h = r
                if card._is_text and card.width() != w:
                    card.reflow(w)
                card.setGeometry(x, y, w, h)
            pw = self._flow.parentWidget()
            if pw is not None:
                pw.setMinimumWidth(max(total_w, 10))
                gp = pw.parentWidget()
                if gp is not None:
                    gp.updateGeometry()
        return total_h

    def _usable_width(self):
        return max(self._viewport_width() - 20, 10)

    def _layout_usable(self):
        # Width used by the actual layout: the flow container's real width
        # (at least the viewport; wider when columns overflow), matching
        # _do_masonry_data / _do_all_grid so lazy creation and layout agree.
        # 实际布局使用的宽度：flow 容器的真实宽度（至少与视口等宽，列超宽时
        # 更宽），与 _do_masonry_data / _do_all_grid 一致，保证懒加载创建
        # 与布局计算不产生偏差。
        cw = self._flow_container.width()
        if cw > 0:
            return max(cw - 20, self._usable_width())
        return self._usable_width()

    def _ensure_visible(self):
        # Lazy loading: create only the cards inside the visible band
        # (plus a buffer). Group views use the masonry layout, the All
        # view uses the fixed-size grid. / 懒加载：只为可见区域（含缓冲）
        # 创建卡片。分组视图用 masonry 布局，All 视图用固定尺寸网格。
        if not self._data:
            return
        sc = self._find_scroll()
        if sc is None:
            return
        sb = sc.verticalScrollBar()
        y0 = sb.value() - self._lazy_buffer
        y1 = sb.value() + sc.viewport().height() + self._lazy_buffer
        if self.current_group_id is None:
            rects, _tw, _th = self._all_grid_data(self._layout_usable())
        else:
            rects, _tw, _th, _info = self._masonry_layout_data(self._layout_usable())
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
                             preview_limits=self._preview_limits,
                             show_name=self._show_emoji_name,
                             hover_zoom=self._hover_zoom,
                             # Disable hover zoom while in edit mode: a zoom
                             # overlay hides neighboring cards and fights the
                             # selection badges (previously only cards that
                             # existed when edit mode started had hover
                             # disabled; newly created ones re-enabled it).
                             # 编辑模式下禁用悬停放大：放大浮层会隐藏相邻卡、
                             # 与勾选角标交互冲突（此前只有进入编辑模式时已
                             # 存在的卡被禁用，新建的卡会重新启用）。
                             hover_enabled=(self._hover_preview_enabled
                                            and not self._selection_mode))
            card.clicked.connect(self._on_card_clicked)
            card.selection_toggled.connect(self._on_selection_toggled)
            card.set_selection_mode(self._selection_mode)
            if self._selection_mode and str(em.get("id", "")) in self._selection:
                card.set_checked(True)
            self._items.append(card)
            self._flow.addWidget(card)
            self._index_add(card)
            created = True
        if created:
            self._flow.invalidate()
            self._flow.activate()
            self._flow.relayout()
            self._update_visible_gifs()
        # Recycle cards scrolled far outside the buffer, so a long browsing
        # session does not accumulate every widget ever created (the lazy
        # loader previously only created cards, never removed them)
        # 回收滚出缓冲区的卡片：长时间浏览大库不会累积所有创建过的控件
        # （此前懒加载只创建、从不回收）
        far = [c for c in self._items
               if c.geometry().y() > y1 + 100
               or c.geometry().y() + c.height() < y0 - 100]
        for c in far:
            self._items.remove(c)
            self._index_remove(c)
            c._stop_gif()
            c.deleteLater()

    def _index_add(self, card):
        # A file may appear in multiple cards (All view folds duplicates by
        # content_hash); the index maps key -> list of cards
        # 同一文件可能对应多张卡（All 视图按 content_hash 折叠重复）；
        # 索引为 key -> 卡片列表
        if card._thumb_path:
            self._thumb_index.setdefault(
                _thumb_key(card._thumb_path), []).append(card)

    def _index_remove(self, card):
        if not card._thumb_path:
            return
        key = _thumb_key(card._thumb_path)
        lst = self._thumb_index.get(key)
        if lst and card in lst:
            lst.remove(card)
            if not lst:
                self._thumb_index.pop(key, None)

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
                # All view: lazy grid — keep cards whose id is still
                # present, delete the rest; the visible band is created by
                # _ensure_visible (avoids building 500+ widgets at once,
                # which made switching to All noticeably slow)
                # All 视图：懒加载网格——保留仍存在的卡片，删除其余；
                # 可视区由 _ensure_visible 创建（避免一次性构建 500+ 控件，
                # 这是切换到 All 时卡顿的根源）
                keep_ids = {em.get("id") for em in emojis}
                emap = {em.get("id"): em for em in emojis}
                survivors = []
                for card in self._items:
                    cid = card._emoji.get("id")
                    # Reuse only when the card still matches the current
                    # show-name setting; otherwise rebuild it (e.g. after
                    # toggling "show emoji name" in settings) / 仅在卡片与
                    # 当前"显示名称"设置一致时复用，否则重建（如设置中切换
                    # "显示表情包名称"后需立即生效）
                    if cid in keep_ids and card._show_name == self._show_emoji_name:
                        card._emoji = emap[cid]
                        card.refresh_display()
                        survivors.append(card)
                    else:
                        card._stop_gif()
                        card.deleteLater()
                self._items = survivors
                self._ensure_scroll_connected()
                self._ensure_visible()
            else:
                keep_ids = {em.get("id") for em in emojis}
                emap = {em.get("id"): em for em in emojis}
                survivors = []
                for card in self._items:
                    cid = card._emoji.get("id")
                    # Same reuse rule as the All view / 与 All 视图相同的复用规则
                    if cid in keep_ids and card._show_name == self._show_emoji_name:
                        card._emoji = emap[cid]
                        card.refresh_display()
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
        # Rebuild the thumb lookup index after the card set changes
        # (key -> list of cards, so folded duplicates in the All view all
        # receive the decoded thumbnail) / 卡片集合变化后重建缩略图查找索引
        # （key -> 卡片列表，All 视图折叠的重复卡都能收到解码的缩略图）
        self._thumb_index = {}
        for card in self._items:
            self._index_add(card)
        # Re-apply multi-select mode to recycled/rebuilt cards /
        # 对回收/重建的卡片重新应用多选模式
        self._sync_selection_mode_on_rebuild()

        if self.current_group_id is not None:
            QTimer.singleShot(0, self._check_column_merge)
        QTimer.singleShot(0, self._update_visible_gifs)
        # Reset the vertical scroll to the top when the data set changes:
        # switching to a smaller group used to keep the previous group's
        # bottom scroll position. Runs after the layout settles so the new
        # scroll range is valid. / 数据集变化时垂直滚动回到顶部：此前切换到
        # 更小的分组会停留在上一分组底部位置。在布局稳定后执行，确保
        # 新滚动范围已生效。
        QTimer.singleShot(0, self._reset_scroll_top)

    def _reset_scroll_top(self):
        sc = self._find_scroll()
        if sc is not None:
            sc.verticalScrollBar().setValue(0)

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
            if hasattr(p, "data_manager"):
                return p.data_manager
            p = p.parent()
        return None

    def _on_card_clicked(self, emoji):
        self.emoji_clicked.emit(emoji)

    # --- Multi-select edit mode / 多选编辑模式 ---

    def enter_edit_mode(self):
        # Enter multi-select edit mode: all visible cards show a check
        # badge; clicks toggle selection instead of sending. Hover zoom is
        # disabled so it does not fight the check interactions.
        # 进入多选编辑模式：所有可见卡片显示勾选角标；点击切换选中而非发送。
        # 停用悬停放大，避免与勾选交互冲突。
        if self._selection_mode:
            return
        self._selection_mode = True
        self._selection.clear()
        for card in self._items:
            card.set_selection_mode(True)
            card._hover_enabled = False
            card._hide_hover_zoom()
        self.edit_mode_changed.emit(True)
        self.selection_changed.emit(0)

    def exit_edit_mode(self):
        # Leave multi-select edit mode and clear the selection; restore
        # hover preview / 退出多选编辑模式并清空选择；恢复悬停预览
        if not self._selection_mode:
            return
        self._selection_mode = False
        self._selection.clear()
        for card in self._items:
            card.set_selection_mode(False)
            card._hover_enabled = self._hover_preview_enabled
        self.edit_mode_changed.emit(False)
        self.selection_changed.emit(0)

    def in_edit_mode(self):
        return self._selection_mode

    def selected_emojis(self):
        # List of selected emoji dicts (stable by id) / 选中的表情列表（按 id 稳定排序）
        return [self._selection[k] for k in sorted(self._selection)]

    def selection_count(self):
        return len(self._selection)

    def _on_selection_toggled(self, emoji_id, checked):
        # Update the selection map from a card's toggle signal / 由卡片信号
        # 更新选中集合
        if not self._selection_mode:
            return
        if checked:
            # Store the emoji dict from the current data / 从当前数据取表情
            for em in self._data:
                if str(em.get("id", "")) == emoji_id:
                    self._selection[emoji_id] = em
                    break
        else:
            self._selection.pop(emoji_id, None)
        self.selection_changed.emit(len(self._selection))

    def _sync_selection_mode_on_rebuild(self):
        # Re-apply selection mode to cards after a rebuild (recycled cards
        # are recreated without the flag) / 重建后重新应用多选模式（回收重
        # 建的卡片不带该标志）
        if self._selection_mode:
            for card in self._items:
                card.set_selection_mode(True)
                card._hover_enabled = False
                if str(card._emoji.get("id", "")) in self._selection:
                    card.set_checked(True)

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
        # Right-click on blank space: sort/rearrange menu
        # 空白处右键：整理/排序菜单
        if self.current_group_id is not None and self._data:
            menu = QMenu(self)
            act_rearrange = menu.addAction(tr("rearrange"))
            menu.addSeparator()
            act_name = menu.addAction(tr("sort_by_name"))
            act_time = menu.addAction(tr("sort_by_time"))
            act_freq = menu.addAction(tr("sort_by_freq"))
            chosen = menu.exec(pos)
            if chosen == act_rearrange:
                self._rearrange()
            elif chosen in (act_name, act_time, act_freq):
                if chosen == act_name:
                    by = "name"
                elif chosen == act_time:
                    by = "time"
                else:
                    by = "freq"
                self._sort_group(by)
        event.accept()

    # Sort the group once by name / created time. Clicking the same kind flips direction
    # (ascending ↔ descending) within 10s; clicking again after 10s resets to ascending.
    # 按名称 / 加入时间单次整理组内卡片。10 秒内重复点击同一方式在正序/逆序间切换；超过 10 秒再次点击恢复正序。
    def _sort_group(self, by):
        if self.current_group_id is None or not self._data:
            return
        dm = self._find_data_manager()
        if dm is None:
            return
        now = time.time()
        within = getattr(self, "_last_sort_by", None) == by and \
            now - getattr(self, "_last_sort_time", 0) <= 10
        # Flip direction when clicked again within 10s, otherwise reset to ascending
        # 10 秒内再次点击翻转方向，否则重置为正序
        desc = (not getattr(self, "_last_sort_desc", False)) if within else False
        self._last_sort_by = by
        self._last_sort_time = now
        self._last_sort_desc = desc
        dm.sort_group_emojis(self.current_group_id, by=by, desc=desc)
        _grid_log().info("Sort group -> group=%s by=%s desc=%s cards=%d",
                         self.current_group_id, by, desc, len(self._data))
        self._refresh_cards_after_merge()
        # Re-check column fit: after re-sorting, columns that no longer fit
        # the current width are merged so the bottom stays flush and no
        # column is clipped off-screen / 重排后复查列是否放得下：放不下的列
        # 被融合，保证底部平整、无列被裁出屏幕
        QTimer.singleShot(0, self._check_column_merge)

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
        # Re-check column fit so the rearranged columns always fit the
        # current width (avoids clipped columns and bottom gaps)
        # 复查列是否放得下（避免列被裁切与底部缺口）
        QTimer.singleShot(0, self._check_column_merge)

    # ------------------------------------------------------------------
    # Drag & drop: text groups move across columns / image groups sort within the group
    # 拖拽：文字分组跨列移动 / 图片分组组内排序
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-emoji-id"):
            if self.current_group_id is not None and self._data:
                self._drop_col = 0
                self._drop_order = 0
                self._drop_mode = "insert"
                self._drop_target_id = None
                self._drop_overlay.show()
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat("application/x-emoji-id") and self._data:
            event.acceptProposedAction()
            pos = event.position().toPoint()
            mode, col, order, target_id = self._drop_target(pos)
            if (mode, col, order, target_id) != (self._drop_mode, self._drop_col,
                                                 self._drop_order, self._drop_target_id):
                # Partial repaint: only refresh the old/new indicator regions / 局部重绘：只刷新旧/新指示区域
                old = self._drop_indicator_rect()
                self._drop_mode, self._drop_col, self._drop_order, self._drop_target_id = \
                    mode, col, order, target_id
                new = self._drop_indicator_rect()
                if old is not None:
                    self._drop_overlay.update(old.adjusted(-4, -4, 4, 4))
                if new is not None:
                    self._drop_overlay.update(new.adjusted(-4, -4, 4, 4))
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._drop_index = -1
        self._drop_col = -1
        self._drop_order = 0
        self._drop_mode = "insert"
        self._drop_target_id = None
        self._drop_overlay.hide()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._drop_index = -1
        self._drop_col = -1
        self._drop_order = 0
        self._drop_mode = "insert"
        self._drop_target_id = None
        self._drop_overlay.hide()
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
            mode, col, order, target_id = self._drop_target(
                event.position().toPoint(), exclude=dragged_id)
            if mode == "swap" and target_id is not None and target_id != dragged_id:
                # Swap positions with the card under the cursor / 与光标下的卡片交换位置
                dm.swap_emoji_columns(dragged_id, target_id)
                _grid_log().info("Drag swap -> emoji=%s with=%s", dragged_id, target_id)
            else:
                # Gap insert (move within/across columns) / 间隙插入（列内/列间移动）
                dm.set_emoji_column(dragged_id, col, order)
                dm.compact_text_columns(self.current_group_id)
                _grid_log().info("Drag reorder -> emoji=%s group=%s target_col=%s order=%s",
                                 dragged_id, self.current_group_id, col, order)
            event.acceptProposedAction()
            # Lightweight refresh (update card data + relayout, avoiding full rebuild jank)
            # 轻量刷新（更新卡片数据 + 重排，避免全量重建卡顿）
            self._refresh_cards_after_merge()
        else:
            event.ignore()

    # The drop indicator is drawn on the top-most _DropOverlay (painting on the grid itself
    # is covered by child widgets), so no paintEvent override is needed here
    # 拖放引导条由置顶 _DropOverlay 绘制（画在网格自身会被子控件遮挡），此处无需 paintEvent

    # Unified indicator rect by mode: insert bar (horizontal), blank new-column bar (vertical),
    # swap target highlight border / 按模式统一返回指示矩形：插入条（水平）、新列条（垂直）、交换高亮边框
    def _drop_indicator_rect(self):
        if self._drop_mode == "swap" and self._drop_target_id is not None:
            rects, _tw, _th, _info = self._masonry_layout_data(self._usable_width())
            r = rects.get(self._drop_target_id)
            if r is None:
                return None
            return QRect(r[0], r[1], r[2], r[3])
        return self._drop_line_rect_h()

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

    # Compute (mode, column, order, target_id) from the full data set, since cards may not be
    # created yet under lazy loading. Mode: "insert" = drop into the gap (column/order valid);
    # "swap" = drop onto the middle of a card (target_id valid); "blank" = open a new column.
    # 计算 (模式, 目标列, 列内位置, 目标卡id)——基于全量数据预估（懒加载下卡片可能未创建）。
    # 模式："insert" = 间隙插入（列/位置有效）；"swap" = 卡片中间交换（目标卡id有效）；
    # "blank" = 开新列。
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
            return ("blank", 0, 0, None)
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
            # Blank space on the right (in the viewport, right of the last column) → try
            # opening a new column; otherwise use the nearest column
            # 右侧空白（视口内、最后一列右侧）→ 尝试开新列；否则最近列
            max_col = max(col_xs)
            last_right = col_xs[max_col][1]
            sc = self._find_scroll()
            offset = sc.horizontalScrollBar().value() if sc else 0
            vp_w = self._viewport_width()
            in_view = pos.x() - offset <= vp_w
            if pos.x() > last_right and in_view:
                new_col = self._blank_zone_col(exclude)
                if new_col is not None:
                    return ("blank", new_col, 0, None)  # Open a new column / 开新列
                return ("insert", max_col, len(cols[max_col]), None)  # Last column end / 末列末尾
            best, bd = None, float("inf")
            for ci, (x0, x1) in col_xs.items():
                d = abs(pos.x() - (x0 + x1) // 2)
                if d < bd:
                    bd, best = d, ci
            target_col = best
        col_items = sorted(cols[target_col], key=lambda e: e[1][1])
        # 1) Cursor is inside a card's rect → swap with that card
        #    光标在卡片矩形内 → 与该卡片交换
        for em, r in col_items:
            if r[1] <= pos.y() <= r[1] + r[3]:
                return ("swap", target_col, 0, em["id"])
        # 2) Otherwise insert into the gap: compare pos.y with card centers
        #    否则在间隙处插入：比较 pos.y 与卡片中心
        order = len(col_items)
        for i, (_e, r) in enumerate(col_items):
            if pos.y() < r[1] + r[3] / 2:
                order = i
                break
        return ("insert", target_col, order, None)

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
        # Keep the drop overlay covering the whole grid / 让拖放覆盖层始终覆盖整个网格
        self._drop_overlay.setGeometry(self.rect())
        # Merge overflowing columns when the window shrinks (150ms debounce: a resize storm
        # from dragging the window edge triggers only one pass)
        # 缩小窗口时融合溢出列（150ms 防抖：拖拽窗口边缘的 resize 风暴只触发一次）
        if self.current_group_id is not None and self._data:
            self._merge_timer.start()
        # Resizing changes which cards/GIFs are visible: refresh lazy card
        # creation and the visible-GIF set after the resize settles. Without
        # this, enlarging the window left newly visible GIFs static (they
        # only started playing on the next scroll).
        # 尺寸变化会改变可见卡片/GIF：resize 稳定后刷新懒加载创建与可见 GIF
        # 播放集。此前放大窗口后新进入视野的 GIF 不播放（要等下次滚动）。
        self._resize_refresh_timer.start()

    def _on_resize_refresh(self):
        self._ensure_visible()
        self._update_visible_gifs()

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
