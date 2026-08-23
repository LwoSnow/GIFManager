"""Single emoji card — thumbnail (image) / text content (adaptive height)
单个表情包卡片 — 图片缩略图（卡片）/ 文字内容（自适应高度）"""
import os
import math
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy, QApplication
from PySide6.QtCore import (
    Qt, QSize, QTimer, Signal, QMimeData, QUrl, QPoint, QObject, QRunnable,
    QThreadPool, QRect,
)
from PySide6.QtGui import (
    QPixmap, QPixmapCache, QMovie, QFont, QFontMetrics, QDrag, QMouseEvent,
    QPainter, QPen, QColor, QImage, QImageReader,
)

from app.models.lang_manager import tr
from app.utils import gif_player


# Thumbnail cache capped at 64MB (~2500+ 76x76 thumbs); LRU evicts automatically
# 缩略图缓存上限 64MB（约 2500+ 张 76x76 缩略图），LRU 自动淘汰
QPixmapCache.setCacheLimit(65536)


def _thumb_key(filepath):
    return "thumb:" + filepath


# Background thumbnail decode task (QImage is thread-safe)
# 后台缩略图解码任务（QImage 线程安全）
class _LoadTask(QRunnable):

    def __init__(self, loader, filepath, size):
        super().__init__()
        self._loader = loader
        self._filepath = filepath
        self._size = size

    def run(self):
        img = QImage(self._filepath)
        if not img.isNull():
            img = img.scaled(
                self._size, self._size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        # Cross-thread signal: queued connection runs the callback on the main thread
        # 跨线程信号：queued connection 自动回主线程
        self._loader.done.emit(_thumb_key(self._filepath), img)
        self._loader._pending.discard(self._filepath)


# Global async thumbnail loader: QThreadPool decodes, callback runs on the main thread
# 全局缩略图异步加载器：QThreadPool 解码，主线程回调
class _ThumbLoader(QObject):

    # key, scaled image; empty QImage = failure
    # key, scaled image（空 QImage = 失败）
    done = Signal(str, QImage)

    def __init__(self):
        super().__init__()
        self._pool = QThreadPool.globalInstance()
        n = os.cpu_count() or 4
        self._pool.setMaxThreadCount(min(max(n - 1, 2), 8))
        self._pending = set()

    def request(self, filepath, size):
        if filepath in self._pending:
            return  # already loading; dedupe / 已在加载，去重
        self._pending.add(filepath)
        self._pool.start(_LoadTask(self, filepath, size))


_loader = _ThumbLoader()


# Emoji card with GIF animation preview and drag support
# 表情包卡片，支持 GIF 动画预览（悬停时播放）与拖拽
class EmojiItem(QFrame):

    clicked = Signal(dict)  # carries emoji dict / 携带 emoji 字典
    selection_toggled = Signal(str, bool)  # emoji id str, checked / 表情 id、勾选状态

    CARD_SIZE = 100
    THUMB_SIZE = 84
    # Height of the name strip under the thumbnail (image cards)
    # 缩略图下方名称条的高度（图片卡）
    NAME_AREA = 22
    # Global name font size and name-area height (image cards). Set by the
    # settings dialog; the name label uses an inline style so it overrides
    # the global QSS font-size. / 全局名称字号与名称区高度（图片卡）。由设置
    # 对话框设置；名字标签用内联样式，覆盖全局 QSS 的 font-size。
    _name_font_size = 10
    _name_area = NAME_AREA
    # Name chars shown before "…" when the name is long / 名称过长时截断显示的字符数
    NAME_CHAR_LIMIT = 12
    # Text card fixed width (masonry column width)
    # 文字卡片统一宽度（masonry 列宽）
    TEXT_WIDTH = 220
    TEXT_MAX_WIDTH = 220
    # Global card scale factor (set by EmojiGridWidget) /
    # 全局卡片缩放系数（由 EmojiGridWidget 设置）
    _card_scale = 1.0

    # Set the global name font size (1–20); the name-area height adapts.
    # 设置全局名字字号（1–20），名称区高度随之自适应。
    @classmethod
    def set_name_font_size(cls, size):
        size = max(1, min(20, int(size)))
        cls._name_font_size = size
        cls._name_area = max(10, size + 8)  # font + padding / 字号 + 内边距

    @classmethod
    def get_name_font_size(cls):
        return cls._name_font_size

    @classmethod
    def get_name_area(cls):
        return cls._name_area

    # Scaled card size / 缩放后的卡片尺寸
    @classmethod
    def card_size(cls):
        return int(cls.CARD_SIZE * cls._card_scale)

    # Scaled thumbnail size / 缩放后的缩略图尺寸
    @classmethod
    def thumb_size(cls):
        return int(cls.THUMB_SIZE * cls._card_scale)

    def __init__(self, emoji: dict, data_manager, parent=None,
                 preview_limits=(100, 200), width=None, show_name=True,
                 hover_zoom=1.15, hover_enabled=True):
        super().__init__(parent)
        self._emoji = emoji
        self._dm = data_manager
        self._movie = None
        self._is_text = bool(emoji.get("text_content"))
        self._press_pos = None
        self._dragging = False
        self._preview_limits = preview_limits  # (single-line cap, multi-line cap) / (单行上限, 多行上限)
        self._width = width if width else (self.TEXT_WIDTH if self._is_text else self.card_size())
        # Whether the name label under the thumbnail is shown (settings) /
        # 是否在缩略图下方显示名称（设置项）
        self._show_name = show_name
        # Hover zoom factor and master switch (settings) / 悬停放大倍数与总开关（设置）
        self._hover_zoom = max(1.0, float(hover_zoom))
        self._hover_enabled = bool(hover_enabled)
        self._hover_layer = None
        self._hidden_neighbors = []  # sibling cards hidden by the overlay / 被浮层隐藏的相邻卡
        self._hover_timer = None  # debounce before showing the overlay / 浮层显示去抖定时器
        # Native GIF playback state (gifdec.dll) / 原生 GIF 播放状态（gifdec.dll）
        self._frames = None
        self._delays = None
        self._frame_idx = 0
        # Long-name marquee: the full name is scrolled across the label while
        # hovering; otherwise it shows elided text with an ellipsis.
        # 长名称跑马灯：悬停时在标签内横向滚动完整名称；否则显示省略号截断。
        # NOTE: _name_label is created ONLY for image cards with names shown,
        # so newer methods must access it via getattr(self, "_name_label", None).
        # / 注意：_name_label 仅图片卡显示名称时创建，故新方法须用
        # getattr(self, "_name_label", None) 安全访问。
        self._name_full = ""
        self._name_scroll_timer = None
        self._name_scroll_offset = 0
        self._play_timer = None
        self._playing = False
        self._decode_connected = False
        self._decode_req = False

        self.setObjectName("emojiCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._thumb_path = None
        # GIF-flag result cached after first content check
        # 首次判定后缓存（GIF 内容识别）
        self._is_gif_file = None
        # Multi-select edit mode state / 多选编辑模式状态
        self._selection_mode = False
        self._checked = False
        self._check_badge = None  # top-left corner badge / 左上角角标

        if self._is_text:
            self._build_text_ui()
        else:
            self._build_image_ui()

    # Detect GIF by file content (QQ emoji packs often masquerade as .jpg)
    # 按文件内容判断 GIF（QQ 表情包动图常伪装为 .jpg 扩展名）
    @staticmethod
    def is_gif_content(path):
        try:
            with open(path, "rb") as f:
                return f.read(4) == b"GIF8"
        except OSError:
            return False

    # Natural text width (longest line + margins + wrap-guard buffer) for
    # dynamic min-column detection
    # 文本自然宽度（最长一行 + 边距 + 防换行缓冲），用于动态检测最小列宽
    @staticmethod
    def text_natural_width(text, font=None):
        if font is None:
            font = QFont("Microsoft YaHei", 12)
        fm = QFontMetrics(font)
        max_line = 0
        for line in text.split("\n"):
            max_line = max(max_line, fm.horizontalAdvance(line))
        # 24 = margins 12*2, 16 = label padding 8*2, +16 = wrap guard:
        # horizontalAdvance returns rounded ints and the label has 8px horizontal
        # padding (content width = label width - 16), so an exact match would let
        # Qt wordWrap push the last char to a new line, breaking the row height.
        # 24 = 边距 12*2，16 = label padding 8*2，+16 防换行缓冲：horizontalAdvance
        # 是四舍五入的整数，且 label 有 8px 水平 padding（内容宽 = label宽 - 16），
        # 若内容宽恰好等于文本宽度，Qt wordWrap 会把最后一个字符挤到
        # 下一行导致行高异常
        return min(max_line + 24 + 16 + 16, 220)

    # ------------------------------------------------------------------
    # Image-mode UI / 图片模式 UI
    # ------------------------------------------------------------------

    @classmethod
    def card_height(cls, show_name):
        # Image card height: thumbnail area plus the name strip when names
        # are shown (settings "show_emoji_name"). Layout code must use this
        # so cards and scroll range stay consistent when names are hidden.
        # 图片卡高度：缩略图区 + 名称条（设置"显示表情包名称"开启时）。
        # 布局代码必须用此方法，隐藏名称时卡片与滚动范围保持一致。
        return cls.card_size() + (cls._name_area if show_name else 0)

    def _build_image_ui(self):
        cs = self.card_size()
        self.setFixedSize(cs, self.card_height(self._show_name))
        layout = QVBoxLayout(self)
        if self._show_name:
            layout.setContentsMargins(4, 6, 4, 2)
        else:
            # No name strip: equal stretches above and below center the
            # thumbnail vertically (top gap == bottom gap), independent of
            # the exact margins / 无名称条：上下等量 stretch 使缩略图垂直居中
            # （上间距 = 下间距），不依赖具体边距数值
            layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(3)

        self._thumb_label = QLabel()
        self._thumb_label.setObjectName("thumbLabel")
        ts = self.thumb_size()
        self._thumb_label.setFixedSize(ts, ts)
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if self._show_name:
            layout.addWidget(self._thumb_label,
                             alignment=Qt.AlignmentFlag.AlignCenter)
        else:
            # equal stretch on both sides -> top gap == bottom gap /
            # 上下等量 stretch → 上间距 = 下间距
            layout.addStretch(1)
            layout.addWidget(self._thumb_label,
                             alignment=Qt.AlignmentFlag.AlignHCenter)
            layout.addStretch(1)

        if self._show_name:
            full_name = self._emoji.get("original_name", "")
            self._name_full = full_name
            self._name_label = QLabel()
            self._name_label.setObjectName("nameLabel")
            self._name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # Inline style wins over the global QSS font-size (setFont would
            # be overridden by the stylesheet). Height adapts to the font.
            # 内联样式优先级高于全局 QSS font-size（setFont 会被样式表覆盖）。
            # 高度随字号自适应。
            self._name_label.setStyleSheet(
                "font-size: {0}px;".format(max(1, self.get_name_font_size())))
            self._name_label.setFixedHeight(self._name_area)
            self._apply_name_display()
            layout.addWidget(self._name_label)

        self._setup_image()

    def _setup_image(self):
        filepath = self._dm.emoji_filepath(self._emoji)
        if filepath != self._thumb_path:
            # The card switched to a different file: stop native playback
            # state (a stale decode result must not start playing)
            # 卡片换到了不同文件：停止原生播放状态（过期解码结果不得开始播放）
            if self._play_timer is not None:
                self._play_timer.stop()
            self._playing = False
            self._decode_req = False
            self._frames = None
            self._delays = None
        if not filepath or not os.path.isfile(filepath):
            self._thumb_label.setText(tr("no_image"))
            return
        self._thumb_path = filepath
        # 1) Cache hit: show directly (zero decode on group switch / hover restore)
        # 1) 缓存命中：直接显示（切分组/悬停恢复零解码）
        key = _thumb_key(filepath)
        pix = QPixmap()
        if QPixmapCache.find(key, pix):
            self.apply_thumb(pix)
            return
        # 2) Cache miss: blank placeholder + async background decode (dispatched by EmojiGridWidget)
        # 2) 未命中：占位（label 默认空白）+ 后台异步解码（由 EmojiGridWidget 统一接收）
        _loader.request(filepath, self.thumb_size() - 8)

    # Set thumbnail once the async decode is ready (dispatched centrally by EmojiGridWidget).
    # The C++ widget may already be deleted when the decode finishes (the
    # card was recycled/deleted meanwhile), so guard with shiboken isAlive.
    # 异步缩略图就绪后设置（由 EmojiGridWidget 统一分发）。解码完成时卡片
    # 可能已被回收/删除（C++ 对象已销毁），用 shiboken 校验存活。
    def apply_thumb(self, pix):
        if self._is_text or self._thumb_label is None:
            return
        try:
            from shiboken6 import isValid
            if not isValid(self) or not isValid(self._thumb_label):
                return
        except ImportError:
            pass
        try:
            self._set_thumb_pixmap(pix, fast=False)
        except RuntimeError:
            pass  # widget destroyed between the check and the call / 检查与调用间已销毁

    # Display a pixmap in the thumbnail label, scaled to fit the CURRENT
    # thumb size preserving the image's aspect ratio (a 4:3 sticker shows as
    # a 4:3 picture, not as a square with letterboxing). This is the same
    # "fit by aspect ratio" look the hover overlay used, so the emoji inside
    # the card scales together with the card, and hover simply enlarges the
    # already-fitted picture (no duplicated overlay look). The hover layer
    # is kept in sync so the hovered GIF frame matches.
    # 在缩略图 label 中显示 pixmap：按当前缩略图尺寸等比缩放（保持图片宽高
    # 比——4:3 的表情包显示为 4:3 图片，而非带黑边的方形）。这与悬停浮层
    # 的"按宽高比适配"是同一套，因此卡片内表情随卡片一起缩放，悬停只是在
    # 已适配的图上再放大（不再有浮层叠加的视觉问题）。悬停浮层同步更新，
    # 使悬停中的 GIF 帧保持一致。
    def _set_thumb_pixmap(self, pix, fast=True):
        if pix is None or pix.isNull():
            return
        ts = self.thumb_size()
        # Fast path (GIF frames only): frames are decoded slightly smaller
        # than the box (thumb_size()-4). If already inside, show directly —
        # this skips a costly per-frame resample during playback (the main
        # cause of jank with many animated stickers). Static thumbnails pass
        # fast=False and always scale to fill the box.
        # / 快速路径（仅 GIF 帧）：帧比框略小解码（thumb_size()-4）。已适配
        # 框内则直接显示——播放时跳过每帧昂贵重采样（多动图卡顿主因）。
        # 静态缩略图传 fast=False，始终缩放填充框。
        if fast and pix.width() <= ts and pix.height() <= ts:
            self._thumb_label.setPixmap(pix)
            self._update_hover_layer(pix)
            return
        # Fit inside the thumb box preserving aspect ratio; center via the
        # label alignment / 等比适配缩略图框内；由 label 对齐居中
        pix = pix.scaled(
            ts, ts,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._thumb_label.setPixmap(pix)
        self._update_hover_layer(pix)

    def refresh_display(self):
        # Refresh name/text label after rename or text edit
        # (reused cards keep their widgets, so labels must be updated manually)
        # 重命名/编辑后刷新名称/文字（复用卡保留控件，需手动更新标签）
        if self._is_text:
            display, _t = self._display_text()
            self._text_label.setText(display)
        elif self._show_name:
            self._name_full = self._emoji.get("original_name", "")
            # Re-apply the font size/height in case they changed (settings) /
            # 重新套用字号/高度（设置可能已变更）
            self._name_label.setStyleSheet(
                "font-size: {0}px;".format(max(1, self.get_name_font_size())))
            self._name_label.setFixedHeight(self._name_area)
            self._apply_name_display()

    # ------------------------------------------------------------------
    # Text-mode UI (adaptive height + preview limits + dynamic column reflow)
    # 文字模式 UI（自适应高度 + 预览限制 + 动态列宽重排）
    # ------------------------------------------------------------------

    # Returns (display text, truncated?)
    # 返回 (显示文本, 是否截断)
    def _display_text(self):
        text = self._emoji.get("text_content", "")
        has_newline = "\n" in text
        limit = self._preview_limits[1] if has_newline else self._preview_limits[0]
        if len(text) > limit:
            return text[:limit] + "…", True
        return text, False

    # Text emoji: preview-limit truncation + precise height adaptation + centered text block
    # 文字表情 — 预览限制截断 + 高度精确自适应 + 文字块居中
    def _build_text_ui(self):
        display, truncated = self._display_text()
        width = self._width
        v_pad = 10   # card layout vertical margins / 卡片 layout 上下边距
        l_pad = 4    # label vertical padding / label 上下 padding

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, v_pad, 12, v_pad)
        layout.setSpacing(0)

        self._text_label = QLabel(display)
        self._text_label.setFont(QFont("Microsoft YaHei", 12))
        self._text_label.setStyleSheet(
            f"color: #E0E0E0; background: transparent; padding: {l_pad}px 8px;"
            "border-radius: 4px;"
        )
        self._text_label.setWordWrap(True)
        # Text stays left-aligned while two stretches on each side center the block in the card
        # 文本保持左对齐，左右各一个 stretch 使文字块在卡片内水平居中
        self._text_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch(1)
        layout.addWidget(self._text_label)
        layout.addStretch(1)

        self._recalc_size(width)
        # Tooltip shows the full content when truncated / 悬停提示完整内容（截断时）
        self.setToolTip(self._emoji.get("text_content", "") if truncated else "")

    # Recompute wrapped label height for the given width and set the card size
    # 按给定宽度重算 label 换行高度并设置卡片尺寸
    def _recalc_size(self, width):
        v_pad = 10
        l_pad = 4
        self._width = width
        # label_w = card width - margins 12*2 - label padding 8*2;
        # content_w subtracts label padding 8*2 again (actual text area)
        # label_w = 卡片宽 - 边距 12*2 - label padding 8*2；content_w 再减
        # label padding 8*2（文本实际可用宽）
        label_w = max(width - 24 - 16, 20)
        content_w = max(label_w - 16, 12)
        self._text_label.setFixedWidth(label_w)
        display, _t = self._display_text()
        fm = self._text_label.fontMetrics()
        line_spacing = fm.lineSpacing()

        # Fallback line count: estimate by content width (ceil, never underestimates)
        # 参考行数：按内容宽估算（ceil 保守，不低估）
        fallback_lines = 0
        for para in display.split("\n"):
            if para == "":
                fallback_lines += 1
                continue
            fallback_lines += max(1, math.ceil(fm.horizontalAdvance(para) / content_w))
        # Fallback must include the label's vertical padding to be comparable with heightForWidth
        # fallback 需包含 label 上下 padding，才能与 heightForWidth 直接比较
        fallback_lh = fallback_lines * line_spacing + l_pad * 2

        # Prefer the precise height; only fall back when heightForWidth is abnormal
        # (0 or over 2x the reference, i.e. a bad wrap from font rounding). The 2x
        # threshold never hurts normal single lines (hfw includes padding, ~= fallback),
        # catching only genuine doubled wraps.
        # 精确行高优先；仅当 heightForWidth 异常（0 或明显超过参考值 2 倍，
        # 说明发生了字体舍入导致的错误换行）时才回退。阈值 2 倍不会误伤
        # 正常的单行（hfw 含 padding，约 = fallback），只拦截真正的翻倍换行。
        lh = self._text_label.heightForWidth(label_w)
        if lh <= 0 or lh > fallback_lh * 2.0:
            lh = fallback_lh

        height = lh + v_pad * 2 + l_pad * 2
        self.setFixedSize(width, height)

    # Masonry columns have independent widths: recompute height for a new width (text cards only)
    # masonry 每列独立列宽：按新列宽重算高度（仅文字卡片）
    def reflow(self, width):
        if not self._is_text or width == self._width:
            return
        self._recalc_size(width)

    # Estimate card height for a given width (used by masonry layout). Uses the
    # same exact heightForWidth math as _recalc_size so sizeHint matches the real
    # layout height (otherwise the scroll range is too short and the bottom clips).
    # 估算在给定宽度下卡片的高度（用于 masonry 高度计算）。与 _recalc_size 使用
    # 相同的 heightForWidth 精确计算，确保 sizeHint 与实际布局高度一致
    # （否则滚动范围不足底部被裁）
    def estimate_height(self, width):
        v_pad, l_pad = 10, 4
        label_w = max(width - 24 - 16, 20)
        lh = self._text_label.heightForWidth(label_w)
        if lh <= 0:
            display, _t = self._display_text()
            content_w = max(label_w - 16, 12)
            fm = self._text_label.fontMetrics()
            line_spacing = fm.lineSpacing()
            line_count = 0
            for para in display.split("\n"):
                if para == "":
                    line_count += 1
                    continue
                line_count += max(1, math.ceil(fm.horizontalAdvance(para) / content_w))
            lh = line_count * line_spacing + l_pad * 2
        return lh + v_pad * 2 + l_pad * 2

    # Static text-card height estimate (no widget instance needed; for lazy-load layout).
    # Mirrors _recalc_size's fallback line-count algorithm (ceil, never underestimates).
    # 静态估算文字卡高度（不依赖 widget 实例，用于懒加载布局计算）。
    # 与 _recalc_size 的 fallback 行数算法一致（ceil 保守，不低估）。
    @staticmethod
    def estimate_height_static(text, width, font=None):
        v_pad, l_pad = 10, 4
        label_w = max(width - 24 - 16, 20)
        content_w = max(label_w - 16, 12)
        if font is None:
            font = QFont("Microsoft YaHei", 12)
        fm = QFontMetrics(font)
        line_spacing = fm.lineSpacing()
        line_count = 0
        for para in text.split("\n"):
            if para == "":
                line_count += 1
                continue
            line_count += max(1, math.ceil(fm.horizontalAdvance(para) / content_w))
        lh = line_count * line_spacing + l_pad * 2
        return lh + v_pad * 2 + l_pad * 2

    # ------------------------------------------------------------------
    # Overridden events — click + drag / 覆盖的事件 — 点击 + 拖拽
    # ------------------------------------------------------------------

    # Multi-select edit mode / 多选编辑模式
    def set_selection_mode(self, enabled):
        # Toggle multi-select mode. In this mode a click toggles the check
        # badge instead of sending the emoji. / 切换多选模式。该模式下点击
        # 切换勾选角标，而非发送表情。
        self._selection_mode = bool(enabled)
        if enabled and self._check_badge is None:
            self._check_badge = QLabel(self)
            self._check_badge.setObjectName("checkBadge")
            self._check_badge.setFixedSize(18, 18)
            self._check_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._check_badge.move(2, 2)
            self._check_badge.setCursor(Qt.CursorShape.PointingHandCursor)
            self._check_badge.raise_()
        if not enabled:
            self.set_checked(False)
        self._update_badge()

    def set_checked(self, checked):
        # Set the checked state and refresh the corner badge. Emits
        # selection_toggled only on actual changes. / 设置勾选状态并刷新角标。
        # 仅在实际变化时发射 selection_toggled。
        checked = bool(checked)
        if checked == self._checked:
            return
        self._checked = checked
        self._update_badge()
        self.selection_toggled.emit(str(self._emoji.get("id", "")), self._checked)

    def is_checked(self):
        return self._checked

    def _update_badge(self):
        # Refresh the check badge: an empty grey circle when unselected, a
        # solid blue circle when selected (mirrors the send-mode radio
        # buttons). / 刷新勾选角标：未选中为灰色空心圆，选中为蓝色实心圆
        # （与发送模式单选按钮同款样式）。
        if self._check_badge is None:
            return
        if not self._selection_mode:
            self._check_badge.hide()
            return
        if self._checked:
            self._check_badge.setStyleSheet(
                "QLabel { background-color: #1677FF;"
                " border: 2px solid #1677FF; border-radius: 8px; }")
        else:
            self._check_badge.setStyleSheet(
                "QLabel { background-color: transparent;"
                " border: 2px solid #8A8A8A; border-radius: 8px; }")
        self._check_badge.show()

    def mousePressEvent(self, event: QMouseEvent):
        if self._selection_mode:
            # In multi-select mode any click toggles the check state; no
            # drag/send is started. / 多选模式下任意点击切换勾选；不启动拖拽
            # 或发送。
            if event.button() == Qt.MouseButton.LeftButton:
                self.set_checked(not self._checked)
                event.accept()
                return
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._selection_mode:
            # No drag while multi-selecting / 多选模式下不启动拖拽
            event.accept()
            return
        if (event.buttons() & Qt.MouseButton.LeftButton) and self._press_pos is not None:
            if (event.position().toPoint() - self._press_pos).manhattanLength() > (
                QApplication.startDragDistance()
            ):
                self._dragging = True
                self._start_drag()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._selection_mode:
            # Multi-select mode: the press already toggled the check state.
            # / 多选模式：按下时已切换勾选状态，这里不再发送。
            self._dragging = False
            self._press_pos = None
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and not self._dragging:
            self.clicked.emit(self._emoji)
        self._dragging = False
        self._press_pos = None
        super().mouseReleaseEvent(event)

    # Start drag: internal sort id + file/text + same-size dashed preview box
    # (right-click cancel is Qt's default behavior)
    # 启动拖拽：内部排序标识 + 文件/文本 + 同尺寸虚线预览框（右键取消由 Qt 默认支持）
    def _start_drag(self):
        drag = QDrag(self)
        mime = QMimeData()
        # Internal sort id: emoji's DB id / 内部排序标识：emoji 的 DB id
        mime.setData("application/x-emoji-id", str(self._emoji.get("id", -1)).encode())

        if self._is_text:
            mime.setText(self._emoji.get("text_content", ""))
        else:
            fp = self._dm.emoji_filepath(self._emoji)
            if fp:
                mime.setUrls([QUrl.fromLocalFile(fp)])

        # Preview box: same-size white dashed border, no content / 预览框：与卡片同尺寸的白色虚线边框，不显示内容
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            w, h = self.card_size(), self.card_height(self._show_name)
        pix = QPixmap(w, h)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        pen = QPen(QColor(255, 255, 255), 2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(1, 1, w - 2, h - 2)
        painter.end()
        drag.setPixmap(pix)
        drag.setHotSpot(QPoint(w // 2, h // 2))

        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)

    def enterEvent(self, event):
        # GIF animation is visibility-driven (managed by EmojiGridWidget);
        # no separate hover playback
        # GIF 动画由可见性驱动（EmojiGridWidget 统一管理），悬停不再单独播放
        if self._is_text:
            self.setStyleSheet(
                "QFrame#emojiCard { background-color: #353535; border: 1px solid "
                "#4A4A4A; border-radius: 6px; }"
            )
        else:
            # Long-name marquee: start scrolling the name as soon as the mouse
            # enters the card, regardless of whether hover preview is on. /
            # 长名称跑马灯：鼠标进入卡片即开始滚动名称，无论悬停预览是否开启。
            self._start_name_scroll()
            # Debounce hover: show the enlarged overlay only after the mouse
            # rests ~90 ms. Rapidly sweeping across cards no longer toggles
            # the overlay (and its neighbor hide/show) on every card, which
            # used to make mouse movement feel sluggish inside the window.
            # 悬停去抖：鼠标停留约 90ms 后才显示放大浮层。快速划过卡片不再
            # 每张卡都切换浮层（及其邻居显隐），此前这会让窗口内鼠标移动
            # 感觉迟滞。
            self._schedule_hover_zoom()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._cancel_hover_zoom()
        self._hide_hover_zoom()
        if self._is_text:
            self.setStyleSheet("")
        super().leaveEvent(event)

    def _schedule_hover_zoom(self):
        # Near-instant debounce: the overlay appears almost immediately, but
        # an extremely fast sweep across cards still does not toggle it on
        # every single card. / 近即时去抖：浮层几乎立即出现，但极快的划过
        # 仍不会每张卡都切换。
        if self._hover_timer is None:
            self._hover_timer = QTimer(self)
            self._hover_timer.setSingleShot(True)
            self._hover_timer.setInterval(10)
            self._hover_timer.timeout.connect(self._show_hover_zoom)
        self._hover_timer.start()

    def _cancel_hover_zoom(self):
        if self._hover_timer is not None:
            self._hover_timer.stop()

    # ------------------------------------------------------------------
    # Hover zoom: an enlarged overlay shown over the card while hovering /
    # 悬停放大：悬停时在卡片上方显示放大浮层
    # ------------------------------------------------------------------

    # Apply the name label text: elide (scroll text + "…") unless the full
    # name fits; while hovering a long name scrolls across (marquee).
    # 应用名字标签文本：完整名称放不下时截断加省略号；悬停时长名称横向
    # 滚动（跑马灯）。
    def _apply_name_display(self):
        lbl = getattr(self, "_name_label", None)
        if lbl is None:
            return
        if self._name_full:
            # Static (not hovering): elide with "…" when the name is long.
            # Hovering restores the full name for the marquee scroll.
            # 静态（非悬停）：名称过长时截断加省略号；悬停时恢复完整名供跑马灯。
            lbl.setText(self._elide_name(self._name_full))
        else:
            lbl.setText("")

    # Return a name clause: up to NAME_CHAR_LIMIT chars, then "…" when longer.
    # / 返回名称子串：最多 NAME_CHAR_LIMIT 字符，更长则加省略号。
    def _elide_name(self, name):
        if name and len(name) > self.NAME_CHAR_LIMIT:
            return name[:self.NAME_CHAR_LIMIT] + "…"
        return name

    # Start the long-name marquee on hover (if the name overflows the label
    # width). / 悬停时启动长名称跑马灯（若名称超出标签宽度）。
    def _start_name_scroll(self):
        lbl = getattr(self, "_name_label", None)
        if lbl is None or not self._name_full:
            return
        if self._name_scroll_timer is not None:
            return
        try:
            from PySide6.QtGui import QFontMetrics
            from PySide6.QtWidgets import QApplication
        except ImportError:
            return
        w = lbl.width()
        if w <= 0:
            return
        fm = QFontMetrics(lbl.font())
        if fm.horizontalAdvance(self._name_full) <= w:
            return  # fits — no scroll needed / 放得下——无需滚动
        self._name_scroll_offset = 0
        self._name_scroll_timer = QTimer(self)
        # Slower marquee: advance one char every 80 ms (~12.5 chars/s) so it
        # reads comfortably rather than zipping by. / 较慢的跑马灯：每 80ms 前进
        # 一格（约每 12.5 字符/秒），阅读舒适而非快速掠过。
        self._name_scroll_timer.setInterval(80)
        self._name_scroll_timer.timeout.connect(self._tick_name_scroll)
        self._name_scroll_timer.start()

    def _stop_name_scroll(self):
        if self._name_scroll_timer is not None:
            self._name_scroll_timer.stop()
            self._name_scroll_timer.deleteLater()
            self._name_scroll_timer = None
        self._name_scroll_offset = 0
        self._scroll_char_widths = {}
        lbl = getattr(self, "_name_label", None)
        if lbl is not None:
            # Restore the static (non-hover) elided text / 恢复静态截断文本
            lbl.setText(self._elide_name(self._name_full))

    def _tick_name_scroll(self):
        # Marquee: render a looping window of the name. The window advances
        # one character per tick and wraps around, so the text keeps cycling
        # (shows the head, then the tail, then loops back to the head)
        # instead of just truncating. / 跑马灯：渲染循环窗口。窗口每 tick 前进
        # 一格并回绕，文本持续循环（先显示头部、再尾部、再回到头部），而非
        # 仅截断。
        lbl = getattr(self, "_name_label", None)
        if lbl is None or not self._name_full:
            self._stop_name_scroll()
            return
        w = lbl.width()
        try:
            from PySide6.QtGui import QFontMetrics
        except ImportError:
            self._stop_name_scroll()
            return
        fm = QFontMetrics(lbl.font())
        name = self._name_full
        text_w = fm.horizontalAdvance(name)
        if w <= 0:
            return
        if text_w <= w:
            lbl.setText(self._elide_name(name))
            return
        # Feed a doubled name so the window can slide seamlessly and loop.
        # / 使用双倍名称，窗口无缝滑动并循环。
        doubled = name + "  " + name
        # Advance the window by one char each tick; wrap when past the name.
        # / 每 tick 前进一格，超过名称长度后回绕。
        self._name_scroll_offset += 1
        if self._name_scroll_offset > len(name):
            self._name_scroll_offset = 0
        # Count characters that fit the label width, then slice the doubled
        # name from the current offset. Per-char widths are cached on the
        # card (the label width + font are fixed for the hover duration), so
        # the loop does not re-measure the same characters on every tick.
        # / 计算标签宽度能容纳的字符数，从当前偏移截取双倍名称。每字符宽度
        # 缓存在卡片上（标签宽度与字号在悬停期间固定），循环不再每 tick
        # 重复度量同一批字符。
        cache = getattr(self, "_scroll_char_widths", {})
        disp_w = w - 4  # small padding / 少量边距
        chars = 0
        acc = 0
        # advance from the offset into the doubled string's slack so the head
        # also scrolls in when wrapping / 从偏移取足够字符填满 label
        i = 0
        while acc < disp_w and i < len(doubled):
            ch = doubled[i]
            cw = cache.get(ch)
            if cw is None:
                cw = fm.horizontalAdvance(ch)
                cache[ch] = cw
            acc += cw
            chars += 1
            i += 1
        self._scroll_char_widths = cache
        msg = doubled[self._name_scroll_offset:
                      self._name_scroll_offset + chars]
        lbl.setText(msg)

    def _ensure_hover_layer(self):
        if self._hover_layer is None:
            self._hover_layer = QLabel(self)
            self._hover_layer.setObjectName("hoverZoom")
            self._hover_layer.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # Mouse-transparent so the card keeps receiving hover events /
            # 鼠标穿透，卡片继续接收悬停事件
            self._hover_layer.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self._hover_layer.hide()

    def _show_hover_zoom(self):
        if not self._hover_enabled or self._hover_zoom <= 1.0:
            return
        self._ensure_hover_layer()
        pix = self._thumb_label.pixmap()
        if pix is None or pix.isNull():
            return
        # "Zoom in place": keep the original thumbnail occupying its layout
        # cell (so the name label below does NOT shift to the center when the
        # layout collapses), and show an enlarged copy on top of it. The
        # overlay is positioned around the thumbnail area.
        # "原位放大"：保留原缩略图占用布局格子（避免下方名字因布局塌缩而
        # 移到中央），在它上方显示放大副本。浮层以缩略图区域为中心定位。
        z = self._hover_zoom
        # Scale by the IMAGE's aspect ratio, not the card shape (a 4:3
        # sticker grows as a 4:3 rectangle, not as the square card)
        # 按图片自身的宽高比放大（4:3 的表情包放大为 4:3 矩形，而非方形卡片）
        w = max(10, int(round(pix.width() * z)))
        h = max(10, int(round(pix.height() * z)))
        # Do not let the overlay cover the name strip below / 不让浮层盖住下方名称条
        ny = self.height() - self._name_area - 2 if self._show_name else self.height()
        # Fit the scale within the space above the name strip so the emoji
        # stays inside the card (height then re-proportions the width so the
        # image keeps its aspect ratio instead of letterboxing off-centre).
        # / 在名称条以上的空间内适配缩放，使表情保持在卡片内；高度受限时同步
        # 等比调整宽度，避免图片在非等比框内被左右偏移。
        max_h = max(10, ny)
        if h > max_h:
            s = max_h / h
            w = max(10, int(round(w * s)))
            h = max_h
        # Centre the overlay on the CARD's horizontal centre (the thumbnail's
        # own centre is off by the card padding, which made the enlarged
        # emoji lean right), and vertically on the thumb area.
        # 浮层以卡片水平中心为锚点（缩略图自身中心受卡片内边距偏移，导致
        # 放大表情偏右），垂直方向居中于缩略图区域。
        cxp = self.width() // 2
        pg = self._thumb_label.geometry()
        cyp = pg.y() + pg.height() // 2
        x = cxp - w // 2
        y = cyp - h // 2
        self._hover_layer.setGeometry(x, y, w, h)
        self._hover_layer.raise_()
        self._hover_layer.show()
        self._update_hover_layer(pix)
        # Hide sibling cards overlapped by the enlarged overlay so it is not
        # partly covered / 隐藏被放大浮层覆盖的相邻卡片，避免浮层被部分遮挡
        self._hide_neighbor_cards()
        # Start the long-name marquee while hovering / 悬停时启动长名称跑马灯
        self._start_name_scroll()

    def _hide_hover_zoom(self):
        if self._hover_layer is not None:
            self._hover_layer.hide()
        # The original thumbnail stays visible (it keeps its layout cell);
        # no show() needed here. / 原缩略图保持可见（占据布局格子），无需恢复。
        self._restore_neighbor_cards()
        # Stop the long-name marquee when leaving hover / 离开悬停停止跑马灯
        self._stop_name_scroll()

    def _find_grid(self):
        p = self.parent()
        while p is not None:
            if p.__class__.__name__ == "EmojiGridWidget":
                return p
            p = p.parent()
        return None

    def _hide_neighbor_cards(self):
        grid = self._find_grid()
        if grid is None:
            return
        orig = self._hover_layer.geometry()
        top_left = self.mapTo(self.parentWidget(), orig.topLeft())
        overlay = QRect(top_left, orig.size())
        hidden = []
        for other in grid._items:
            if other is self:
                continue
            if other.geometry().intersects(overlay):
                other.hide()
                hidden.append(other)
        self._hidden_neighbors = hidden

    def _restore_neighbor_cards(self):
        for c in self._hidden_neighbors:
            if c is None:
                continue
            # The neighbor may have been deleted by a rebuild while hidden
            # (search/group switch); guard like apply_thumb does
            # 邻居卡可能在隐藏期间被重建删除（搜索/切分组）；与 apply_thumb
            # 一样用 shiboken 校验存活
            try:
                from shiboken6 import isValid
                if not isValid(c):
                    continue
            except ImportError:
                pass
            try:
                c.show()
            except RuntimeError:
                pass
        self._hidden_neighbors = []

    def _update_hover_layer(self, pix):
        # Keep the enlarged overlay in sync with the current frame (GIFs
        # animate while hovered) / 放大浮层跟随当前帧（GIF 悬停时持续动画）
        if self._hover_layer is None or not self._hover_layer.isVisible():
            return
        if pix is None or pix.isNull():
            return
        w = self._hover_layer.width()
        h = self._hover_layer.height()
        scaled = pix.scaled(
            w, h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._hover_layer.setPixmap(scaled)

    # Whether this card is a GIF animation (content-sniffed, result cached)
    # 当前卡片是否为 GIF 动图（内容识别，缓存结果）
    def is_gif(self):
        if self._is_text:
            return False
        if self._is_gif_file is None:
            fp = self._dm.emoji_filepath(self._emoji)
            self._is_gif_file = bool(fp and os.path.isfile(fp) and EmojiItem.is_gif_content(fp))
        return self._is_gif_file

    # Play GIF animation (called by the grid visibility driver; idempotent).
    # Prefers the native gifdec.dll decoder (frames decode off the GUI
    # thread); falls back to QMovie when the DLL is unavailable.
    # priority: lower decodes sooner (the visible band passes ~0-9, so a GIF
    # scrolled into view decodes before older off-screen requests).
    # 播放 GIF 动画（由网格可见性驱动调用，幂等）。优先使用原生 gifdec.dll
    # 解码器（帧在 GUI 线程外解码）；DLL 不可用时回退 QMovie。
    # priority：越小越先解码（视野内传 ~0-9，滚动进视野的 GIF 优先于旧的
    # 视野外请求）。
    def play_animation(self, priority=100, allow_decode=True):
        if self._is_text or self._playing:
            return
        if not self.is_gif():
            return
        fp = self._dm.emoji_filepath(self._emoji)
        if not fp:
            return
        if not gif_player.available():
            self._start_gif(fp)  # QMovie fallback / QMovie 回退
            return
        hit = gif_player.cache_get(fp)
        if hit is not None:
            self._frames, self._delays = hit
            self._playing = True
            self._frame_idx = 0
            self._start_play_timer()
            return
        # Frames not decoded yet: mark playing and start playback when the
        # background decode finishes. While scrolling (allow_decode=False)
        # the decode request is skipped — the static thumbnail stays until
        # the scroll settles, then decoding resumes center-outward. / 帧尚未
        # 解码：标记播放中，后台解码完成后开始播放。滚动中（allow_decode=
        # False）跳过解码请求——保持静态缩略图，停下后再从中心向两边解码。
        if not allow_decode:
            return
        self._playing = True
        if not self._decode_connected:
            gif_player.connect_decoded(self._on_frames_ready)
            self._decode_connected = True
        if not self._decode_req:
            self._decode_req = True
            gif_player.request_decode(fp, self.thumb_size() - 4, priority)

    # Native frames are ready (path only; frames live in the cache)
    # 原生帧已就绪（仅传路径；帧在缓存中）
    def _on_frames_ready(self, path):
        if self._thumb_path != path:
            self._decode_req = False  # stale result / 过期结果
            return
        self._decode_req = False
        if not self._playing:
            return
        hit = gif_player.cache_get(path)
        if hit is None:
            # Decode failed (corrupt file): release the playing slot so the
            # card can retry later and does not keep consuming the GIF limit
            # (previously _playing stayed True forever, blocking retries)
            # 解码失败（文件损坏）：释放播放名额，允许日后重试且不再占用
            # GIF 并发上限（此前 _playing 永远为 True，阻塞重试）
            self._playing = False
            return
        self._frames, self._delays = hit
        self._frame_idx = 0
        self._start_play_timer()

    def _start_play_timer(self):
        if self._play_timer is None:
            self._play_timer = QTimer(self)
            self._play_timer.setSingleShot(True)
            self._play_timer.timeout.connect(self._play_next)
        self._frame_idx = 0
        self._show_frame(0)
        self._play_timer.start(self._delays[0] if self._delays else 30)

    def _play_next(self):
        if not self._frames:
            return
        self._frame_idx = (self._frame_idx + 1) % len(self._frames)
        self._show_frame(self._frame_idx)
        delay = 30
        if self._delays and self._frame_idx < len(self._delays):
            delay = self._delays[self._frame_idx]
        self._play_timer.start(delay)

    def _show_frame(self, idx):
        if self._thumb_label is not None and 0 <= idx < len(self._frames):
            pix = QPixmap.fromImage(self._frames[idx])
            self._set_thumb_pixmap(pix)

    # Stop GIF animation and restore the static thumbnail (idempotent)
    # 停止 GIF 动画并恢复静态缩略图（幂等）
    def stop_animation(self):
        self._playing = False
        if self._play_timer is not None:
            self._play_timer.stop()
        self._frames = None
        self._delays = None
        self._frame_idx = 0
        self._stop_gif()  # stops the QMovie fallback and restores the thumb
        # _stop_gif 停止 QMovie 回退并恢复静态缩略图

    def _start_gif(self, filepath):
        if self._movie:
            return
        self._movie = QMovie(filepath)
        # Scale preserving the aspect ratio: QMovie.setScaledSize stretches to
        # the exact size, which distorts non-square GIFs. Compute an
        # aspect-correct target size from the original frame size first.
        # 等比缩放：QMovie.setScaledSize 会强制拉伸到指定尺寸，非方形 GIF
        # 会被压扁变形。先按原始帧尺寸算出等比的目标尺寸再设置。
        self._movie.setScaledSize(self._gif_scaled_size(filepath))
        self._movie.frameChanged.connect(self._on_frame)
        self._movie.start()

    def _gif_scaled_size(self, filepath):
        target = self.thumb_size() - 4
        reader = QImageReader(filepath)
        size = reader.size()
        if size.isValid() and size.width() > 0 and size.height() > 0:
            return size.scaled(target, target, Qt.AspectRatioMode.KeepAspectRatio)
        return QSize(target, target)

    def _stop_gif(self):
        self._cancel_hover_zoom()
        self._hide_hover_zoom()
        if self._movie:
            self._movie.stop()
            # Release the file handle synchronously: QMovie keeps the file
            # open until its QIODevice is detached, which blocks Windows from
            # renaming/deleting the group folder
            # 同步释放文件句柄：QMovie 会一直持有文件直到分离 QIODevice，
            # 否则 Windows 无法重命名/删除分组目录
            self._movie.setDevice(None)
            self._movie.deleteLater()
            self._movie = None
        # Restore the static thumbnail / 恢复静态缩略图
        if not self._is_text:
            self._setup_image()

    def _on_frame(self, _frame):
        if self._movie and not self._is_text:
            pix = self._movie.currentPixmap()
            self._set_thumb_pixmap(pix)
