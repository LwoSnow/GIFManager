"""单个表情包卡片 — 图片缩略图（卡片） / 文字内容（自适应高度）"""
import os
import math
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy, QApplication
from PySide6.QtCore import Qt, QSize, QTimer, Signal, QMimeData, QUrl, QPoint, QObject, QRunnable, QThreadPool
from PySide6.QtGui import QPixmap, QPixmapCache, QMovie, QFont, QDrag, QMouseEvent, QPainter, QPen, QColor, QImage


# 缩略图缓存上限 64MB（约 2500+ 张 76x76 缩略图），LRU 自动淘汰
QPixmapCache.setCacheLimit(65536)


def _thumb_key(filepath):
    return "thumb:" + filepath


class _LoadTask(QRunnable):
    """后台缩略图解码任务（QImage 线程安全）"""

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
        # 跨线程信号：queued connection 自动回主线程
        self._loader.done.emit(_thumb_key(self._filepath), img)
        self._loader._pending.discard(self._filepath)


class _ThumbLoader(QObject):
    """全局缩略图异步加载器：QThreadPool 解码，主线程回调"""

    done = Signal(str, QImage)  # key, scaled image（空 QImage = 失败）

    def __init__(self):
        super().__init__()
        self._pool = QThreadPool.globalInstance()
        n = os.cpu_count() or 4
        self._pool.setMaxThreadCount(min(max(n - 1, 2), 8))
        self._pending = set()

    def request(self, filepath, size):
        if filepath in self._pending:
            return  # 已在加载，去重
        self._pending.add(filepath)
        self._pool.start(_LoadTask(self, filepath, size))


_loader = _ThumbLoader()


class EmojiItem(QFrame):
    """表情包卡片，支持 GIF 动画预览（悬停时播放）与拖拽"""

    clicked = Signal(dict)  # 携带 emoji 字典

    CARD_SIZE = 100
    THUMB_SIZE = 84
    TEXT_WIDTH = 220    # 文字卡片统一宽度（masonry 列宽）
    TEXT_MAX_WIDTH = 220

    def __init__(self, emoji: dict, data_manager, parent=None, preview_limits=(100, 200), width=None):
        super().__init__(parent)
        self._emoji = emoji
        self._dm = data_manager
        self._movie = None
        self._is_text = bool(emoji.get("text_content"))
        self._press_pos = None
        self._dragging = False
        self._preview_limits = preview_limits  # (单行上限, 多行上限)
        self._width = width if width else (self.TEXT_WIDTH if self._is_text else self.CARD_SIZE)

        self.setObjectName("emojiCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._thumb_path = None
        self._is_gif_file = None  # 首次判定后缓存（GIF 内容识别）

        if self._is_text:
            self._build_text_ui()
        else:
            self._build_image_ui()

    @staticmethod
    def is_gif_content(path):
        """按文件内容判断 GIF（QQ 表情包动图常伪装为 .jpg 扩展名）"""
        try:
            with open(path, "rb") as f:
                return f.read(4) == b"GIF8"
        except OSError:
            return False

    @staticmethod
    def text_natural_width(text, font=None):
        """文本自然宽度（最长一行 + 边距 + 防换行缓冲），用于动态检测最小列宽"""
        if font is None:
            font = QFont("Microsoft YaHei", 12)
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(font)
        max_line = 0
        for line in text.split("\n"):
            max_line = max(max_line, fm.horizontalAdvance(line))
        # +16 缓冲：horizontalAdvance 是四舍五入的整数，且 label 有 8px 水平
        # padding（内容宽 = label宽 - 16），若内容宽恰好等于文本宽度，
        # Qt wordWrap 会把最后一个字符挤到下一行导致行高异常
        return min(max_line + 24 + 16 + 16, 220)  # margins 12*2 + padding 8*2 + 缓冲

    # ------------------------------------------------------------------
    # 图片模式 UI
    # ------------------------------------------------------------------

    def _build_image_ui(self):
        self.setFixedSize(self.CARD_SIZE, self.CARD_SIZE + 22)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 6, 4, 2)
        layout.setSpacing(3)

        self._thumb_label = QLabel()
        self._thumb_label.setObjectName("thumbLabel")
        self._thumb_label.setFixedSize(self.THUMB_SIZE, self.THUMB_SIZE)
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._thumb_label, alignment=Qt.AlignmentFlag.AlignCenter)

        name = self._emoji.get("original_name", "")[:10]
        self._name_label = QLabel(name[:10])
        self._name_label.setObjectName("nameLabel")
        self._name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name_label.setFixedHeight(16)
        layout.addWidget(self._name_label)

        self._setup_image()

    def _setup_image(self):
        filepath = self._dm.emoji_filepath(self._emoji)
        if not filepath or not os.path.isfile(filepath):
            self._thumb_label.setText("无图片")
            return
        self._thumb_path = filepath
        # 1) 缓存命中：直接显示（切分组/悬停恢复零解码）
        key = _thumb_key(filepath)
        pix = QPixmap()
        if QPixmapCache.find(key, pix):
            self._thumb_label.setPixmap(pix)
            return
        # 2) 未命中：占位（label 默认空白）+ 后台异步解码（由 EmojiGridWidget 统一接收）
        _loader.request(filepath, self.THUMB_SIZE - 8)

    def apply_thumb(self, pix):
        """异步缩略图就绪后设置（由 EmojiGridWidget 统一分发）"""
        if self._thumb_label is not None and not self._is_text:
            self._thumb_label.setPixmap(pix)

    # ------------------------------------------------------------------
    # 文字模式 UI（自适应高度 + 预览限制 + 动态列宽重排）
    # ------------------------------------------------------------------

    def _display_text(self):
        """返回 (显示文本, 是否截断)"""
        text = self._emoji.get("text_content", "")
        has_newline = "\n" in text
        limit = self._preview_limits[1] if has_newline else self._preview_limits[0]
        if len(text) > limit:
            return text[:limit] + "…", True
        return text, False

    def _build_text_ui(self):
        """文字表情 — 预览限制截断 + 高度精确自适应 + 文字块居中"""
        display, truncated = self._display_text()
        width = self._width
        v_pad = 10   # 卡片 layout 上下边距
        l_pad = 4    # label 上下 padding

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
        # 文本内容左对齐，但文字块在卡片内水平居中
        self._text_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        # 左右各一个 stretch → 文字块居中，文本保持左对齐
        layout.addStretch(1)
        layout.addWidget(self._text_label)
        layout.addStretch(1)

        self._recalc_size(width)
        # 悬停提示完整内容
        self.setToolTip(self._emoji.get("text_content", "") if truncated else "")

    def _recalc_size(self, width):
        """按给定宽度重算 label 换行高度并设置卡片尺寸"""
        v_pad = 10
        l_pad = 4
        self._width = width
        label_w = max(width - 24 - 16, 20)  # margins 12*2 + label padding 8*2
        content_w = max(label_w - 16, 12)   # 文本实际可用宽（label padding 8*2）
        self._text_label.setFixedWidth(label_w)
        display, _t = self._display_text()
        fm = self._text_label.fontMetrics()
        line_spacing = fm.lineSpacing()

        # 参考行数：按内容宽估算（ceil 保守，不低估）
        fallback_lines = 0
        for para in display.split("\n"):
            if para == "":
                fallback_lines += 1
                continue
            fallback_lines += max(1, math.ceil(fm.horizontalAdvance(para) / content_w))
        # fallback 需包含 label 上下 padding，才能与 heightForWidth 直接比较
        fallback_lh = fallback_lines * line_spacing + l_pad * 2

        # 精确行高优先；仅当 heightForWidth 异常（0 或明显超过参考值 2 倍，
        # 说明发生了字体舍入导致的错误换行）时才回退。阈值 2 倍不会误伤
        # 正常的单行（hfw 含 padding，约 = fallback），只拦截真正的翻倍换行。
        lh = self._text_label.heightForWidth(label_w)
        if lh <= 0 or lh > fallback_lh * 2.0:
            lh = fallback_lh

        height = lh + v_pad * 2 + l_pad * 2
        self.setFixedSize(width, height)

    def reflow(self, width):
        """masonry 每列独立列宽：按新列宽重算高度（仅文字卡片）"""
        if not self._is_text or width == self._width:
            return
        self._recalc_size(width)

    def estimate_height(self, width):
        """估算在给定宽度下卡片的高度（用于 masonry 高度计算）。
        与 _recalc_size 使用相同的 heightForWidth 精确计算，确保
        sizeHint 与实际布局高度一致（否则滚动范围不足底部被裁）"""
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

    @staticmethod
    def estimate_height_static(text, width, font=None):
        """静态估算文字卡高度（不依赖 widget 实例，用于懒加载布局计算）。
        与 _recalc_size 的 fallback 行数算法一致（ceil 保守，不低估）。"""
        v_pad, l_pad = 10, 4
        label_w = max(width - 24 - 16, 20)
        content_w = max(label_w - 16, 12)
        if font is None:
            font = QFont("Microsoft YaHei", 12)
        from PySide6.QtGui import QFontMetrics
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
    # 覆盖的事件 — 点击 + 拖拽
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if (event.buttons() & Qt.MouseButton.LeftButton) and self._press_pos is not None:
            if (event.position().toPoint() - self._press_pos).manhattanLength() > QApplication.startDragDistance():
                self._dragging = True
                self._start_drag()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and not self._dragging:
            self.clicked.emit(self._emoji)
        self._dragging = False
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def _start_drag(self):
        """启动拖拽：内部排序标识 + 文件/文本 + 同尺寸虚线预览框（右键取消由 Qt 默认支持）"""
        drag = QDrag(self)
        mime = QMimeData()
        # 内部排序标识：emoji 的 DB id
        mime.setData("application/x-emoji-id", str(self._emoji.get("id", -1)).encode())

        if self._is_text:
            mime.setText(self._emoji.get("text_content", ""))
        else:
            fp = self._dm.emoji_filepath(self._emoji)
            if fp:
                mime.setUrls([QUrl.fromLocalFile(fp)])

        # 预览框：与卡片同尺寸的白色虚线边框，不显示内容
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            w, h = self.CARD_SIZE, self.CARD_SIZE + 22
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
        # GIF 动画由可见性驱动（EmojiGridWidget 统一管理），悬停不再单独播放
        if self._is_text:
            self.setStyleSheet(
                "QFrame#emojiCard { background-color: #353535; border: 1px solid #4A4A4A; border-radius: 6px; }"
            )
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self._is_text:
            self.setStyleSheet("")
        super().leaveEvent(event)

    def is_gif(self):
        """当前卡片是否为 GIF 动图（内容识别，缓存结果）"""
        if self._is_text:
            return False
        if self._is_gif_file is None:
            fp = self._dm.emoji_filepath(self._emoji)
            self._is_gif_file = bool(fp and os.path.isfile(fp) and EmojiItem.is_gif_content(fp))
        return self._is_gif_file

    def play_animation(self):
        """播放 GIF 动画（由网格可见性驱动调用，幂等）"""
        if self._is_text or self._movie or not self.is_gif():
            return
        fp = self._dm.emoji_filepath(self._emoji)
        if fp:
            self._start_gif(fp)

    def stop_animation(self):
        """停止 GIF 动画并恢复静态缩略图（幂等）"""
        self._stop_gif()

    def _start_gif(self, filepath):
        if self._movie:
            return
        self._movie = QMovie(filepath)
        self._movie.setScaledSize(QSize(self.THUMB_SIZE - 4, self.THUMB_SIZE - 4))
        self._movie.frameChanged.connect(self._on_frame)
        self._movie.start()

    def _stop_gif(self):
        if self._movie:
            self._movie.stop()
            self._movie = None
        # 恢复静态缩略图
        if not self._is_text:
            self._setup_image()

    def _on_frame(self, _frame):
        if self._movie and not self._is_text:
            self._thumb_label.setPixmap(self._movie.currentPixmap())
