"""表情包网格 — FlowLayout 自适应网格 + 居中占位层"""
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


class FlowLayout(QLayout):
    """自适应列数的流式布局"""

    def __init__(self, parent=None, margin=8, spacing=8):
        super().__init__(parent)
        self._items = []
        self._margin = margin
        self._spacing = spacing
        self._masonry = False  # True = 俄罗斯方块式紧凑堆叠
        self._suppress_invalidate = False  # 批量增删期间抑制 LayoutRequest 事件风暴
        if parent:
            self.setContentsMargins(margin, margin, margin, margin)
            self.setSpacing(spacing)

    def invalidate(self):
        # 批量操作（load_emojis 重建）时抑制逐次 postEvent，最后统一布局一次
        if self._suppress_invalidate:
            return
        super().invalidate()

    def set_masonry(self, enabled):
        """切换 masonry（紧凑堆叠）模式：卡片放入当前最短列，不按行对齐"""
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
        """返回实际布局高度（关键：滚动区域依赖此值判断内容高度；
        minimumSize 只是单卡尺寸并集，会导致滚动范围不足、底部被裁）"""
        pw = self.parentWidget()
        if pw is not None:
            w = max(pw.width(), 10)
            h = self.heightForWidth(w)
            return QSize(w, h)
        return self.minimumSize()

    def relayout(self):
        """强制用父容器当前尺寸重新布局。

        Qt 的 QLayout::activate() 在布局几何与父容器尺寸一致时（增删
        item 但容器大小未变）会短路，不会调用 setGeometry，导致新加入的
        item 不被布局。这里显式用当前尺寸重排所有 item。
        """
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
            # 注意：QLayoutItem.sizeHint() 对 isHidden() 的 widget（新卡片
            # 尚未显示）返回 (0,0)，必须用 widget 自身的尺寸接口。
            # 固定尺寸（min==max）用 minimumSize，可变宽度（文字卡片）
            # 用 sizeHint，保证 hidden 状态下也能得到正确尺寸。
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
                # 直接用 QWidget.setGeometry：QWidgetItem.setGeometry 对
                # isHidden() 的 widget（新卡片尚未显示）会因 isEmpty() 直接
                # 返回而不生效，导致新卡片停留在 (0,0) 造成重叠。
                wid.setGeometry(QRect(x, y, w, h))

            x += w + spacing
            row_height = max(row_height, h)

        return y + row_height + m.bottom()

    def _grid_widget(self):
        """向上找到 EmojiGridWidget（数据驱动布局的宿主）"""
        pw = self.parentWidget()
        if pw is not None:
            gp = pw.parentWidget()
            if gp is not None and gp.__class__.__name__ == "EmojiGridWidget":
                return gp
        return None

    def _do_masonry(self, rect: QRect, test_only=False):
        # 数据驱动布局（懒加载下 _items 只含可见卡，必须由全量数据计算位置）
        grid = self._grid_widget()
        if grid is not None and grid._data:
            return grid._do_masonry_data(rect, test_only)
        return self._do_masonry_legacy(rect, test_only)

    def _do_masonry_legacy(self, rect: QRect, test_only=False):
        """稳定列堆叠（全量 _items 兜底实现，正常情况下由数据驱动版本接管）"""
        m = self.contentsMargins()
        usable = max(rect.width() - m.left() - m.right(), 10)
        spacing = self._spacing

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
        # 列内按 sort_order 排序
        for ci in col_map:
            col_map[ci].sort(key=lambda e: int(e[0].widget()._emoji.get("sort_order", 0)))

        x = m.left()
        y_max = m.top()
        for ci in sorted(col_map):
            col_entries = col_map[ci]
            # 该列独立列宽
            nw_list = []
            for item, wid in col_entries:
                if isinstance(wid, EmojiItem) and wid._is_text:
                    nw_list.append(wid.text_natural_width(wid._emoji.get("text_content", "")))
                else:
                    # 图片卡片固定尺寸；hidden 时 width() 可能不准，用 minimumSize 兜底
                    nw_list.append(max(wid.width(), wid.minimumSize().width(), 10))
            col_w = max(80, min(max(nw_list), usable))
            # 所有列都布局（不跳过），超出可视部分由横向滚动展示
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

        # 设置容器最小宽度 = 全部列总宽，超出可视区时触发横向滚动（稳定列不重排）
        pw = self.parentWidget()
        if pw is not None and not test_only:
            pw.setMinimumWidth(max(0, x - spacing) + m.right())
            # 向上冒泡：让 QScrollArea 感知内容变宽
            gp = pw.parentWidget()
            if gp is not None:
                gp.updateGeometry()

        return y_max + m.bottom()


class EmojiGridWidget(QWidget):
    """表情包网格容器 — 有内容时 FlowLayout 网格，无内容时居中占位文字"""

    emoji_clicked = Signal(dict)
    emoji_right_clicked = Signal(dict, QPoint)
    emojis_reordered = Signal()  # 内部排序完成，通知重载

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dm = None
        self._items = []
        self._data = []  # 当前视图全量数据（懒加载布局依据）
        self._preview_limits = (100, 200)
        self._lazy_buffer = 300  # 懒加载上下缓冲像素
        self.current_group_id = None  # 当前分组（None = 全部，不参与排序）
        self._gif_limit = 8  # 同时播放的 GIF 数（由多线程核心数设置驱动，核心数×2）
        self._playing_gifs = set()
        self._drop_index = -1  # 图片分组：拖拽插入位置指示（-1 = 不显示）
        self._drop_col = -1    # 文字分组：目标列
        self._drop_order = 0   # 文字分组：列内插入位置
        self._is_text_group = False
        self.setAcceptDrops(True)

        # 融合防抖：resize 风暴（拖拽窗口边缘）期间只触发一次融合检查
        self._merge_timer = QTimer(self)
        self._merge_timer.setSingleShot(True)
        self._merge_timer.setInterval(150)
        self._merge_timer.timeout.connect(self._check_column_merge)

        # 异步缩略图：统一接收完成信号并分发给对应卡片（只连接一次）
        _loader.done.connect(self._on_thumb_ready)

        # 外层垂直布局，包含占位文字层
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # 占位文字（居中）
        self._placeholder = QLabel(self)
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setWordWrap(True)
        self._placeholder.setStyleSheet(
            "color: #666; font-size: 14px; background: transparent; padding: 40px;"
        )
        self._placeholder.hide()
        outer.addWidget(self._placeholder)

        # FlowLayout 区域
        self._flow_container = QWidget(self)
        self._flow = FlowLayout(self._flow_container, margin=10, spacing=8)
        outer.addWidget(self._flow_container, 1)

    def _on_thumb_ready(self, key, img):
        """后台缩略图解码完成：写入缓存并分发给所有等待该图的卡片"""
        if img.isNull():
            return
        pix = QPixmap.fromImage(img)
        QPixmapCache.insert(key, pix)
        for card in self._items:
            if card._thumb_path and _thumb_key(card._thumb_path) == key:
                card.apply_thumb(pix)

    def set_data_manager(self, dm):
        self._dm = dm

    # ------------------------------------------------------------------
    # 数据驱动 masonry 布局（懒加载：_items 只含可见卡，位置由全量数据计算）
    # ------------------------------------------------------------------

    def _masonry_layout_data(self, usable):
        """基于 self._data 全量计算 masonry 布局。
        返回 (rects: {emoji_id: (x,y,w,h)}, total_w, total_h, col_info)"""
        m = self._flow.contentsMargins()
        spacing = self._flow.spacing()
        cols = {}
        for em in self._data:
            cols.setdefault(int(em.get("col_index", 0)), []).append(em)
        for ci in cols:
            cols[ci].sort(key=lambda e: int(e.get("sort_order", 0)))
        if not cols:
            return {}, 0, m.top() + m.bottom(), {}
        # 列宽（内容自然宽，clamp 到可用宽）
        col_widths = {}
        for ci, lst in cols.items():
            nw = max(
                (EmojiItem.text_natural_width(e.get("text_content", ""))
                 if e.get("text_content") else 100)
                for e in lst
            )
            col_widths[ci] = max(80, min(nw, usable))
        # 列 x 位置
        x = m.left()
        col_x = {}
        for ci in sorted(cols):
            col_x[ci] = x
            x += col_widths[ci] + spacing
        total_w = max(0, x - spacing) + m.right()
        # 卡片位置（预估高度）
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
        """数据驱动 masonry：按全量数据计算位置，只对已创建卡片 setGeometry"""
        m = self._flow.contentsMargins()
        spacing = self._flow.spacing()
        usable = max(rect.width() - m.left() - m.right(), 10)
        _rects, total_w, total_h, info = self._masonry_layout_data(usable)
        if not test_only:
            # 已创建卡按列逐张布局（实际高度累加，reflow 文字卡）
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
        """懒加载：创建当前可视区域（含缓冲）内的卡片，滚动时增量创建。
        只增不销毁；已创建卡复用。"""
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
            # 新卡就位后更新可见 GIF 播放集合（懒加载创建的底部卡片）
            self._update_visible_gifs()

    def _ensure_scroll_connected(self):
        """连接滚动条：valueChanged（滚动）与 rangeChanged（内容高度变化后滚动条
        范围更新，懒加载初始 range=0 时 setValue 不会触发 valueChanged）"""
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
        """可见区域 GIF 自动播放：只渲染可视卡片内的动图，最多同时播放
        _gif_limit 个（= 多线程核心数 × 2），其余显示静态首帧缩略图。"""
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
        # 之前播放、现已不可见或超限的卡片停止动画
        for cid in playing - new_playing:
            for card in self._items:
                if id(card) == cid:
                    card.stop_animation()
                    break
        self._playing_gifs = new_playing

    def load_emojis(self, emojis, group_type="image", preview_limits=(100, 200)):
        """加载表情包。空列表时显示占位文字。
        preview_limits: (单行预览上限, 多行预览上限) """
        self._is_text_group = (group_type == "text")
        # 先清空 FlowLayout 的 QWidgetItem 包装（关键：deleteLater 不会自动移除）
        # 批量抑制 invalidate：避免 takeAt/addWidget 逐次 post LayoutRequest 事件风暴
        self._flow._suppress_invalidate = True
        try:
            while self._flow.count() > 0:
                self._flow.takeAt(0)
            # （旧卡片的复用 / 停止动画 / 删除由下方统一处理）

            if not emojis:
                self._flow_container.hide()
                # 清空旧数据/卡片（避免空分组残留旧内容占用内存与误触发融合检查）
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
            # 具体分组（图片/文字）用 masonry 列堆叠（列成员由 col_index 持久化，
            # 窗口 resize 只触发列融合不重排）；"全部"聚合视图保持流式布局
            self._flow.set_masonry(self.current_group_id is not None)
            self._data = list(emojis)
            self._preview_limits = preview_limits

            dm = self._find_data_manager()

            if self.current_group_id is None:
                # "全部"聚合视图：全量创建（流式布局，无懒加载）
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
                # 具体分组：懒加载——只保留仍存在的旧卡（复用），可见区域增量创建
                keep_ids = {em.get("id") for em in emojis}
                emap = {em.get("id"): em for em in emojis}
                survivors = []
                for card in self._items:
                    cid = card._emoji.get("id")
                    if cid in keep_ids:
                        card._emoji = emap[cid]  # 更新列/序等数据
                        survivors.append(card)
                    else:
                        card._stop_gif()
                        card.deleteLater()
                self._items = survivors
                self._ensure_scroll_connected()
                # 创建可视区域内的卡片（懒加载，只增不销毁）
                self._ensure_visible()
        finally:
            self._flow._suppress_invalidate = False

        self._flow.invalidate()
        self._flow.activate()
        # 容器尺寸未变时 Qt 的 activate() 不会重排新 item，显式强制重排
        self._flow.relayout()
        # 强制向上冒泡：更新容器几何 → 触发 QScrollArea 重新布局
        self._flow_container.updateGeometry()
        self.updateGeometry()

        # 初始加载后检查列融合（窗口窄时无法完整显示的列自动并入前列）
        if self.current_group_id is not None:
            QTimer.singleShot(0, self._check_column_merge)
        # 布局完成后更新可见 GIF 播放集合
        QTimer.singleShot(0, self._update_visible_gifs)

    def _check_column_merge(self):
        """加载/调整后检查：无法完整显示的列融合进前列（内部轻量刷新，不重建）"""
        if self.current_group_id is not None and self._data:
            self._merge_overflow_columns()

    def _refresh_cards_after_merge(self):
        """融合/拖拽写库后轻量刷新：更新全量数据与已创建卡片并重新布局，
        避免全量重建（QPixmap 重新解码）造成卡顿。"""
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
        # 位置变化后刷新可见 GIF 播放集合
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
        # 空白处右键：一键整理（按当前窗口宽度重新均匀分列，消除拉伸窗口后的空缺）
        if self.current_group_id is not None and self._data:
            from PySide6.QtWidgets import QMenu
            menu = QMenu(self)
            act = menu.addAction(tr("rearrange"))
            if menu.exec(pos) == act:
                self._rearrange()
        event.accept()

    def _rearrange(self):
        """一键整理：按当前窗口宽度计算列数（图标列数由窗口/屏幕大小决定），
        所有卡片按全局顺序均匀重分配列，消除拉伸窗口后的空白空缺。"""
        if self.current_group_id is None or not self._data:
            return
        dm = self._find_data_manager()
        if dm is None:
            return
        usable = self._usable_width()
        spacing = self._flow.spacing()
        # 列宽基准：组内最大自然宽（图片 100 / 文字自然宽），保证每列完整显示
        base_w = 100
        for em in self._data:
            if em.get("text_content"):
                base_w = max(base_w, EmojiItem.text_natural_width(em.get("text_content", "")))
        # 列数 = 可用宽度能容纳的最大列数
        k = max(1, (usable + spacing) // (base_w + spacing))
        dm.rearrange_columns(self.current_group_id, k)
        _grid_log().info("One-click rearrange -> group=%s cols=%d cards=%d",
                         self.current_group_id, k, len(self._data))
        self._refresh_cards_after_merge()

    # ------------------------------------------------------------------
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
                # 局部重绘：只刷新旧/新插入条区域，避免全量重绘卡顿
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
            # 统一列模式：拖拽到目标列的指定位置（列内/列间移动）
            col, order = self._drop_target(event.position().toPoint(), exclude=dragged_id)
            dm.set_emoji_column(dragged_id, col, order)
            dm.compact_text_columns(self.current_group_id)
            event.acceptProposedAction()
            _grid_log().info("Drag reorder -> emoji=%s group=%s target_col=%s order=%s",
                             dragged_id, self.current_group_id, col, order)
            # 轻量刷新（更新卡片数据 + 重排，避免全量重建卡顿）
            self._refresh_cards_after_merge()
        else:
            event.ignore()

    def paintEvent(self, event):
        """绘制白色插入位置指示条：列内画水平条，新列画垂直条"""
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

    def _drop_line_rect_h(self):
        """列内水平分界条（数据驱动预估位置）；新列时画垂直条在最后一列右侧"""
        if self._drop_col < 0:
            return None
        rects, _tw, _th, _info = self._masonry_layout_data(self._usable_width())
        col_entries = [(em, rects[em["id"]])
                       for em in self._data
                       if int(em.get("col_index", 0)) == self._drop_col
                       and em["id"] in rects]
        if not col_entries:
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

    def _drop_target(self, pos, exclude=None):
        """计算 (目标列, 列内插入位置)——基于全量数据预估位置（懒加载下卡片可能未创建）"""
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
        # 列的 x 范围
        col_xs = {}
        for ci, entries in cols.items():
            xs = [r[0] for _e, r in entries]
            xr = [r[0] + r[2] for _e, r in entries]
            col_xs[ci] = (min(xs), max(xr))
        # 目标列：pos.x 所在列
        target_col = None
        for ci, (x0, x1) in col_xs.items():
            if x0 <= pos.x() <= x1:
                target_col = ci
                break
        if target_col is None:
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
                    return (new_col, 0)  # 开新列
                # 不能开新列 → 最后一列末尾
                return (max_col, len(cols[max_col]))
            best, bd = None, float("inf")
            for ci, (x0, x1) in col_xs.items():
                d = abs(pos.x() - (x0 + x1) // 2)
                if d < bd:
                    bd, best = d, ci
            target_col = best
        # 列内插入位置：比较 pos.y 与卡片中心
        col_items = sorted(cols[target_col], key=lambda e: e[1][1])
        order = len(col_items)
        for i, (_e, r) in enumerate(col_items):
            if pos.y() < r[1] + r[3] / 2:
                order = i
                break
        return (target_col, order)

    def _blank_zone_col(self, exclude=None):
        """右侧空白区：若被拖卡片能单独开一列则返回新列号，否则返回 None"""
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

    def _merge_overflow_columns(self):
        """窗口缩小时，无法完整显示的列按顺序依次并入能完整显示的前列。
        完整显示 = 该列自然宽 ≤ 可视宽，且各列总宽放得下。
        返回 True 表示发生了融合（需要重新加载）。"""
        if self.current_group_id is None or not self._data:
            return False
        dm = self._find_data_manager()
        spacing = self._flow.spacing()
        # 与 _do_masonry 的实际布局宽度保持一致（viewport 宽 - contentsMargins 10*2）
        usable = max(self._viewport_width() - 20, 10)
        # 每列宽度（按内容自然宽，不 clamp）——数据驱动（懒加载下卡片可能未创建）
        col_widths = {}
        for em in self._data:
            ci = int(em.get("col_index", 0))
            if em.get("text_content"):
                nw = EmojiItem.text_natural_width(em.get("text_content", ""))
            else:
                nw = 100  # 图片卡片固定宽
            col_widths[ci] = max(col_widths.get(ci, 0), nw)
        cols = sorted(col_widths)
        if not cols:
            return False
        # 逐列判定"能否完整单开"：
        #   ① 该列自然宽 ≤ 可视宽（否则内容被压缩，显示不全 → 融合）
        #   ② 累加总宽（含该列）≤ 可视宽（否则溢出 → 融合）
        keep = []      # 能完整显示且放得下的列
        overflow = []  # 需要融合的列
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
        # 目标列：能完整显示的列循环（若 keep 为空则全部并入第一列）
        if not keep:
            keep = [cols[0]]
        # 单事务批量融合 + 列号压缩（避免逐条 commit 造成卡顿）
        dm.merge_columns_into(self.current_group_id, overflow, keep)
        # 轻量刷新现有卡片（不重建，避免 QPixmap 重新解码卡顿）
        self._refresh_cards_after_merge()
        return True

    def resizeEvent(self, event):
        super().resizeEvent(event)
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

    def _viewport_width(self):
        """可视视口宽度（横向滚动时网格被拉伸，需用视口而非网格宽度判断空白）"""
        sc = self._find_scroll()
        if sc is not None:
            return max(sc.viewport().width(), 100)
        return max(self.width(), 100)

    # ------------------------------------------------------------------
    # 文字分组：添加时分配列（能开新列就开，否则放行高最小列）
    # ------------------------------------------------------------------

    def _current_col_widths(self):
        """当前各列布局宽度（按 col_index 分组取最大卡片宽）"""
        cols = {}
        for it in self._items:
            ci = int(it._emoji.get("col_index", 0))
            cols[ci] = max(cols.get(ci, 0), it.width())
        return [cols[k] for k in sorted(cols)]

    def assign_new_text_column(self, emoji_id, group_id, text, usable_w):
        """新文字表情列分配：能单独开一列则开新列，否则放入卡片最少的列。"""
        self._assign_to_column(
            emoji_id, group_id, EmojiItem.text_natural_width(text), usable_w
        )

    def assign_unassigned_columns(self, group_id):
        """未分配卡片（user_sorted=0，如新导入/旧数据迁移）按当前窗口宽自动摊列：
        能开新列则开（窗口大 → 多列），否则放卡片最少的列末尾。
        写入 DB 并置 user_sorted=1（从此保持用户/程序分配的列，resize 只融合不重置）。
        返回是否分配了任何卡片。"""
        dm = self._find_data_manager()
        if dm is None:
            return False

        def width_of(e):
            return (EmojiItem.text_natural_width(e.get("text_content", ""))
                    if e.get("text_content") else 100)

        # 与 _do_masonry 布局一致（viewport 宽 - contentsMargins 10*2）
        usable = max(self._viewport_width() - 20, 10)
        return dm.assign_unassigned_columns(
            group_id, usable, self._flow.spacing(), width_of
        ) > 0

    def _assign_to_column(self, emoji_id, group_id, natural_w, usable_w):
        """通用列分配：能开新列则开新列，否则放卡片最少的列末尾。
        列宽/列计数从数据库内容计算（不依赖当前 UI 网格状态）。"""
        dm = self._find_data_manager()
        spacing = self._flow.spacing()
        new_w = min(max(natural_w, 80), usable_w)
        # 从 DB 读当前各列内容算列宽与卡片数（排除新卡自身）
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
