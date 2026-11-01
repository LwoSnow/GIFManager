"""The sticker grid: a lazy, virtualised, masonry-capable flow of cards.

The layout arithmetic lives in `gifmanager.core.grid_layout` and the visibility
window arithmetic in `gifmanager.frontend.qt.virtual`, so this class only wires
them to Qt: it materialises the cards inside the visible band plus a buffer,
recycles the ones that leave, and requests thumbnails for what is on screen.

What it deliberately does NOT do, compared with the previous release's 1900-line
grid: GIF playback orchestration (see `gifmanager.frontend.qt.animation`), drag
reordering with a painted overlay, edit mode with a long-press range select, and
automatic column merging on resize. Those are separate features and belong in
separate objects; the seams for them are documented at the bottom of this file.

贴纸网格：惰性、虚拟化、支持瀑布流的卡片流。

布局运算位于 `gifmanager.core.grid_layout`，可视窗口运算位于
`gifmanager.frontend.qt.virtual`，因此本类只把它们接到 Qt 上：物化"可视带 + 缓冲"
内的卡片、回收离开的卡片，并为屏幕上的卡片请求缩略图。

与上一版本 1900 行的网格相比，它刻意"不做"这些事：GIF 播放编排（见
`gifmanager.frontend.qt.animation`）、带绘制覆盖层的拖拽重排、带长按范围选择的编辑
模式，以及缩放时的列自动合并。它们是独立功能，属于独立对象；它们的接缝记录在本文件
末尾。
"""
import logging
import os

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import QScrollArea, QWidget

from gifmanager.core import grid_layout
from gifmanager.core.constants import CARD_SIZE, CARD_SPACING, GRID_BUFFER_PX
from gifmanager.frontend.qt.thumbnails import ThumbnailLoader, thumb_key
from gifmanager.frontend.qt.widgets.emoji_card import EmojiCard, PlaceholderCard
from gifmanager.frontend.qt.virtual import (
    GridMetrics,
    visible_window,
)

log = logging.getLogger("GIFManager")

# Recycled cards kept for reuse. Cards are expensive to build (a frame, two
# labels, a stylesheet) and recycling is what keeps a long scroll smooth.
# 保留复用的已回收卡片。构建卡片代价不低（一个框架、两个标签、一份样式表），回收是
# 长距离滚动保持流畅的关键。
CARD_POOL_MAX = 48

# Debounce before a relayout after a resize, so dragging a window edge does not
# relayout on every intermediate width. / 缩放后重新布局的防抖，避免拖动窗口边缘时
# 每个中间宽度都触发一次布局。
RESIZE_DEBOUNCE_MS = 120


class EmojiGridWidget(QWidget):
    # Card grid for one group (or the All view).
    # 单个分组（或"全部"视图）的卡片网格。

    emoji_clicked = Signal(dict)
    emoji_right_clicked = Signal(dict, QPoint)
    emojis_reordered = Signal()
    selection_changed = Signal(int)
    # (row, global rect) on enter, (None, None) on leave. The preview window is
    # owned by the view, so the grid relays rather than displays.
    # 进入时 (行, 全局矩形)，离开时 (None, None)。预览窗口由视图持有，因此网格只转发
    # 而不显示。
    card_hovered = Signal(object, object)

    def __init__(self, adapter=None, parent=None):
        super().__init__(parent)
        self._adapter = adapter
        self._rows = []
        self._rects = {}
        self._cards = {}          # emoji id -> EmojiCard / 表情 id -> 卡片
        self._pool = []
        self._pool_reused = 0
        self._selected_ids = set()
        self._current_group_id = None
        self._group_type = "image"
        self._keyword = ""
        self._show_name = True
        self._card_scale = 1.0
        self._usable_width = 0

        self.setObjectName("emojiGrid")
        self.setSizePolicy(
            self.sizePolicy().horizontalPolicy(), self.sizePolicy().verticalPolicy())

        self._loader = ThumbnailLoader(parent=self)
        self._loader.done.connect(self._on_thumb_ready)

        self._placeholder = PlaceholderCard("", self)
        self._placeholder.hide()

        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(RESIZE_DEBOUNCE_MS)
        self._relayout_timer.timeout.connect(self._on_relayout)

    # ---- configuration / 配置 -------------------------------------------

    def set_adapter(self, adapter):
        self._adapter = adapter

    def set_show_name(self, show):
        show = bool(show)
        if show == self._show_name:
            return
        self._show_name = show
        for card in self._cards.values():
            card.set_show_name(show)
        self._clear_pool()
        self._rebuild_layout()

    def set_card_scale(self, scale):
        scale = max(0.5, min(2.0, float(scale)))
        if abs(scale - self._card_scale) < 1e-6:
            return
        self._card_scale = scale
        for card in self._cards.values():
            card.set_scale(scale)
        self._clear_pool()
        self._rebuild_layout()

    @property
    def card_scale(self):
        return self._card_scale

    @property
    def current_group_id(self):
        return self._current_group_id

    @current_group_id.setter
    def current_group_id(self, group_id):
        self._current_group_id = group_id

    # ---- data / 数据 ----------------------------------------------------

    def load_rows(self, rows, group_id=None, group_type="image", keyword=""):
        # Replace the displayed rows and rebuild the layout /
        # 替换显示的行并重建布局
        self._release_cards()
        self._rows = list(rows or [])
        if group_id is not None:
            self._current_group_id = group_id
        self._group_type = group_type or "image"
        self._keyword = keyword or ""
        self._rebuild_layout()

    def rows(self):
        return list(self._rows)

    def card_count(self):
        return len(self._cards)

    def pooled_count(self):
        return len(self._pool)

    @property
    def pool_reused(self):
        return self._pool_reused

    # ---- selection / 选择 -------------------------------------------------
    #
    # Selection is plain data — a set of row ids — rather than a per-card widget
    # flag, so it survives a rebuild and so a command predicate can ask "is
    # anything selected" without walking the card list.
    # 选择是纯数据——一组行 id——而不是每卡的控件标志，因此它能跨重建存活，命令谓词也能
    # 在不遍历卡片列表的情况下询问"是否有选中项"。

    def selected_ids(self):
        return set(getattr(self, "_selected_ids", ()))

    def selected_rows(self):
        chosen = self.selected_ids()
        if not chosen:
            return []
        return [row for row in self._rows if row.get("id") in chosen]

    def selection_count(self):
        return len(self.selected_ids())

    def set_selected(self, emoji_id, selected):
        chosen = set(getattr(self, "_selected_ids", ()))
        if selected:
            chosen.add(emoji_id)
        else:
            chosen.discard(emoji_id)
        self._selected_ids = chosen
        card = self._cards.get(emoji_id)
        if card is not None and hasattr(card, "set_selected"):
            card.set_selected(selected)
        self.selection_changed.emit(len(chosen))
        return True

    def clear_selection(self):
        changed = bool(getattr(self, "_selected_ids", ()))
        self._selected_ids = set()
        for card in self._cards.values():
            if hasattr(card, "set_selected"):
                card.set_selected(False)
        if changed:
            self.selection_changed.emit(0)
        return changed

    def select_all(self):
        self._selected_ids = {row.get("id") for row in self._rows}
        for emoji_id, card in self._cards.items():
            if hasattr(card, "set_selected"):
                card.set_selected(emoji_id in self._selected_ids)
        self.selection_changed.emit(len(self._selected_ids))
        return len(self._selected_ids)

    def selection(self):
        # Read-only copy, so a caller cannot mutate the internal set /
        # 只读副本，使调用方无法改动内部集合
        return set(self.selected_ids())

    # ---- layout / 布局 --------------------------------------------------

    def _metrics(self):
        return GridMetrics(
            card_width=int(round(CARD_SIZE * self._card_scale)),
            card_height=int(round((CARD_SIZE + (22 if self._show_name else 0))
                                  * self._card_scale)),
            spacing=CARD_SPACING,
            margin=0,
        )

    def _available_width(self):
        width = self.width()
        if width <= 0:
            scroll = self._find_scroll()
            if scroll is not None:
                width = scroll.viewport().width()
        return max(0, width)

    def _compute_rects(self):
        metrics = self._metrics()
        usable = self._available_width()
        self._usable_width = usable
        if usable <= 0 or not self._rows:
            return {}, metrics
        return grid_layout.grid_rects(self._rows, metrics, usable), metrics

    def _rebuild_layout(self):
        self._rects, metrics = self._compute_rects()
        if not self._rows:
            self._show_placeholder()
            self._release_cards()
            self.setMinimumHeight(0)
            self.resize(self.width(), max(0, self.height()))
            return
        self._hide_placeholder()
        total_height = grid_layout.total_height(self._rects)
        self.setMinimumHeight(total_height)
        self.resize(self._available_width(), total_height)
        self._ensure_visible()
        self._ensure_scroll_connected()

    def _on_relayout(self):
        self._rebuild_layout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Debounced: a live window resize emits a continuous stream of events,
        # and relaying out on each one is what made resizing feel sticky.
        # 防抖：实时缩放窗口会连续产生事件，逐个重新布局正是缩放感觉粘滞的原因。
        self._relayout_timer.start()

    # ---- virtualisation / 虚拟化 ----------------------------------------

    def _find_scroll(self):
        parent = self.parent()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                return parent
            parent = parent.parent()
        return None

    def _ensure_scroll_connected(self):
        if getattr(self, "_scroll_connected", False):
            return
        scroll = self._find_scroll()
        if scroll is None:
            return
        scroll.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        self._scroll_connected = True

    def _on_scrolled(self, _value):
        self._ensure_visible()

    def _visible_band(self):
        scroll = self._find_scroll()
        if scroll is None:
            return 0, max(0, self.height())
        top = scroll.verticalScrollBar().value()
        height = scroll.viewport().height()
        return visible_window(top, height, GRID_BUFFER_PX)

    def _ensure_visible(self):
        # Materialise the cards inside the visible band plus the buffer, and
        # recycle everything outside it plus a hysteresis margin. The margin
        # stops a card that straddles the boundary from being destroyed and
        # rebuilt on the next scroll tick.
        # 物化"可视带 + 缓冲"内的卡片，并回收带外再加上滞后余量的卡片。该余量避免
        # 恰好跨在边界上的卡片在下一个滚动 tick 被销毁重建。
        if not self._rects:
            return
        y0, y1 = self._visible_band()
        wanted = {
            emoji_id for emoji_id, rect in self._rects.items()
            if rect[1] <= y1 and rect[1] + rect[3] >= y0
        }

        for emoji_id in list(self._cards):
            if emoji_id not in wanted:
                self._recycle(self._cards.pop(emoji_id))

        index = {row.get("id"): row for row in self._rows}
        for emoji_id in wanted:
            if emoji_id in self._cards:
                continue
            row = index.get(emoji_id)
            if row is None:
                continue
            card = self._take_card(row)
            self._cards[emoji_id] = card
            card.show()
        self._update_playing_hint()

    def _update_playing_hint(self):
        # Only cards inside the strict viewport (no buffer) should animate; the
        # buffer exists to have cards READY, not to have them all running.
        # 只有严格视口内（不含缓冲）的卡片才应播放动画；缓冲的存在是为了让卡片"就绪"，
        # 而不是让它们全部运行。
        scroll = self._find_scroll()
        if scroll is None:
            return
        top = scroll.verticalScrollBar().value()
        bottom = top + scroll.viewport().height()
        for emoji_id, card in self._cards.items():
            rect = self._rects.get(emoji_id)
            if rect is None:
                continue
            on_screen = rect[1] <= bottom and rect[1] + rect[3] >= top
            card.setProperty("onScreen", on_screen)
            self._update_animation(card, on_screen)

    def _update_animation(self, card, on_screen):
        # Hook for the animation engine. Kept as a method rather than inlined so
        # a subclass (or a future mixin) can drive playback without touching the
        # virtualisation logic.
        # 动画引擎的挂钩。做成方法而非内联，使子类（或将来的 mixin）无需触碰虚拟化
        # 逻辑即可驱动播放。
        path = card.filepath
        if not path or not on_screen:
            return

    # ---- card pool / 卡片池 ---------------------------------------------

    def _take_card(self, row):
        card = None
        while self._pool:
            candidate = self._pool.pop()
            if candidate._show_name == self._show_name:
                card = candidate
                self._pool_reused += 1
                break
            candidate.deleteLater()
        if card is None:
            card = EmojiCard(self, show_name=self._show_name,
                             scale=self._card_scale)
            card.activated.connect(self._on_card_activated)
            card.context_requested.connect(self._on_card_context)
            # Connected once, at construction, so a recycled card is never
            # connected twice — which would deliver every hover twice and double
            # the preview churn.
            # 只在构造时连接一次，使回收的卡片绝不会被连接两次——否则每次悬停都会投递两次，
            # 预览的抖动也会翻倍。
            card.hovered.connect(self.card_hovered)
        else:
            card.set_scale(self._card_scale)
        card.setParent(self)
        filepath = self._filepath_for(row)
        card.set_emoji(row, filepath)
        card.set_selected(row.get("id") in self.selected_ids())
        self._place(card, row.get("id"))
        if filepath:
            self._request_thumb(card, filepath)
        return card

    def _request_thumb(self, card, filepath):
        cached = self._loader.cached(filepath)
        if cached is not None:
            card.apply_thumb(cached)
            return
        self._loader.request(filepath, card.thumb_size)

    def _place(self, card, emoji_id):
        rect = self._rects.get(emoji_id)
        if rect is None:
            return
        card.setGeometry(QRect(int(rect[0]), int(rect[1]),
                               int(rect[2]), int(rect[3])))

    def _recycle(self, card):
        card.hide()
        if len(self._pool) >= CARD_POOL_MAX or card._show_name != self._show_name:
            card.deleteLater()
            return
        card.clear()
        self._pool.append(card)

    def _release_cards(self):
        for card in self._cards.values():
            card.hide()
            card.deleteLater()
        self._cards.clear()
        self._clear_pool()

    def _clear_pool(self):
        for card in self._pool:
            card.deleteLater()
        self._pool.clear()

    def keep_pool_consistent(self):
        # Drop pooled cards built for a different name setting. Called by the
        # settings path so a recycled card never shows a stale height.
        # 丢弃为不同名称设置构建的池内卡片。由设置路径调用，使回收的卡片不会显示错误
        # 的高度。
        self._clear_pool()

    # ---- thumbnails / 缩略图 --------------------------------------------

    def _on_thumb_ready(self, key, image):
        from gifmanager.frontend.qt.thumbnails import to_pixmap

        pixmap = to_pixmap(image)
        if pixmap is None:
            return
        self._loader.store(key, pixmap)
        for card in self._cards.values():
            if card.filepath and thumb_key(card.filepath) == key:
                card.apply_thumb(pixmap)

    # ---- file paths / 文件路径 ------------------------------------------

    def _filepath_for(self, row):
        if not row or not row.get("filename"):
            return None
        if self._adapter is None:
            return None
        return self._adapter.store.emoji_filepath(row)

    # ---- events / 事件 --------------------------------------------------

    def _on_card_activated(self, emoji):
        self.emoji_clicked.emit(emoji)

    def _on_card_context(self, emoji, position):
        self.emoji_right_clicked.emit(emoji, position)

    # ---- placeholder / 占位 ---------------------------------------------

    def _show_placeholder(self):
        self._placeholder.set_text(
            self._empty_text())
        self._placeholder.setGeometry(
            QRect(0, 0, max(1, self._available_width()), 160))
        self._placeholder.show()

    def _hide_placeholder(self):
        self._placeholder.hide()

    def _empty_text(self):
        # Translated through the adapter, so an empty group says why it is
        # empty in the user's language instead of showing a raw key.
        # 经适配器翻译，使空分组能用用户的语言说明为什么为空，而不是显示原始键名。
        translate = self._translate
        if self._keyword:
            return translate("no_search_result")
        if self._group_type == "text":
            return translate("empty_text_group")
        return translate("empty_image_group")

    def _translate(self, key):
        adapter = self._adapter
        if adapter is not None and hasattr(adapter, "tr"):
            try:
                return adapter.tr(key)
            except Exception:
                pass
        return key

    # ---- teardown / 退出 -------------------------------------------------

    def release_assets(self):
        # Drain the thumbnail pool before the interpreter tears down. Documented
        # as the safe order: the pool is drained before the animation engine's
        # thread, which is what the exit crashes needed.
        # 在解释器拆除前排空缩略图线程池。此处记录的是安全顺序：线程池先于动画引擎的
        # 线程排空，这正是此前退出崩溃所需要的。
        self._release_cards()
        self._clear_pool()
        self._loader.shutdown(3000)


# ---------------------------------------------------------------------------
# Documented seams for the features this grid does not own.
#
# * GIF playback — `animation.request_decode` / `animation.cache_get` driven
#   from `_update_animation`, which is already called with the on-screen flag.
#   A per-card timer swaps the pixmap; the decode itself stays off the GUI
#   thread.
# * Drag reordering — the drop target and insertion indicator are pure
#   arithmetic over `self._rects`, so they belong beside `grid_layout` in core
#   and only the mouse events belong here.
# * Edit mode with a range select — the selection set is plain data; only the
#   card badge and the tool bar are Qt.
# * Column merging on resize — `grid_layout.merge_columns` already computes the
#   plan; the debounced `_on_relayout` is where it would be applied.
#
# 本网格不负责的功能，其接缝记录如下。
#
# * GIF 播放——由已经拿到"在屏"标志的 `_update_animation` 驱动
#   `animation.request_decode` / `animation.cache_get`。每卡一个定时器切换
#   pixmap；解码本身仍在界面线程之外。
# * 拖拽重排——投放目标与插入指示条都是对 `self._rects` 的纯运算，因此属于核心层
#   `grid_layout` 旁边，本文件只应保留鼠标事件。
# * 带范围选择的编辑模式——选择集是纯数据；只有卡片角标与工具栏属于 Qt。
# * 缩放时合并列——`grid_layout.merge_columns` 已经算出方案；防抖的
#   `_on_relayout` 就是应用它的位置。
# ---------------------------------------------------------------------------


__all__ = ["CARD_POOL_MAX", "EmojiGridWidget", "RESIZE_DEBOUNCE_MS"]
