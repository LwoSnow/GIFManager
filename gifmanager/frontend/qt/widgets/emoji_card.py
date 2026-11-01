"""One emoji card: an image or text sticker with a name strip.

The card is deliberately small. The previous release's card carried the hover
zoom overlay, the name marquee, drag-and-drop with a painted preview, multi
select with a long-press range select, and a per-card GIF playback state
machine, which is why it grew past 1600 lines. Those concerns belong to the
grid (which knows what is visible) and to the animation engine; a card that only
paints a sticker and reports clicks stays readable.

单张表情卡片：图片或文字贴纸，带名称条。

卡片刻意做小。上一版本的卡片还背着悬停放大层、名称跑马灯、带手绘预览的拖放、长按
范围多选，以及每卡的 GIF 播放状态机，因此膨胀到 1600 行以上。那些关注点属于网格
（它知道什么可见）与动画引擎；一张只负责绘制贴纸并上报点击的卡片才保持可读。
"""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from gifmanager.core.constants import CARD_SIZE

# Height of the name strip under a sticker / 贴纸下方名称条的高度
NAME_AREA = 22

# Padding between the card border and the sticker / 卡片边框与贴纸之间的内边距
FRAME_INSET = 6

# Corner radius of a card / 卡片圆角半径
CORNER_RADIUS = 8


class EmojiCard(QFrame):
    # A single sticker. Emits `activated` on a left click and
    # `context_requested` on a right click, with the row it represents.
    # 单张贴纸。左键点击发出 `activated`，右键点击发出
    # `context_requested`，并带上它所代表的行。

    activated = Signal(dict)
    context_requested = Signal(dict, object)
    # Emitted with (row, global rect) when the pointer enters, and with
    # (None, None) when it leaves. The preview window is owned by the view, so the
    # card reports an intention rather than showing anything itself.
    # 指针进入时发出 (行, 全局矩形)，离开时发出 (None, None)。预览窗口由视图持有，
    # 因此卡片只上报意图，不自行显示任何东西。
    hovered = Signal(object, object)

    def __init__(self, parent=None, show_name=True, scale=1.0):
        super().__init__(parent)
        self._emoji = None
        self._filepath = None
        self._show_name = bool(show_name)
        self._scale = float(scale)
        self._pixmap = None
        self._selected = False

        self.setObjectName("emojiCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Hover must be reported even when no button is pressed, which is what
        # `WA_Hover` enables.
        # 即使没有按键按下也必须上报悬停，这正是 `WA_Hover` 提供的能力。
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            FRAME_INSET, FRAME_INSET, FRAME_INSET, 2)
        layout.setSpacing(2)

        self._image = QLabel()
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setObjectName("emojiThumb")
        layout.addWidget(self._image, 1)

        self._name = QLabel()
        self._name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name.setObjectName("emojiName")
        self._name.setVisible(self._show_name)
        layout.addWidget(self._name, 0)

        self._apply_metrics()

    # ---- metrics / 尺寸 --------------------------------------------------

    @property
    def card_size(self):
        return max(24, int(round(CARD_SIZE * self._scale)))

    @property
    def thumb_size(self):
        return max(16, int(round((CARD_SIZE - 2 * FRAME_INSET) * self._scale)))

    def set_scale(self, scale):
        self._scale = float(scale)
        self._apply_metrics()

    def set_show_name(self, show):
        show = bool(show)
        if show == self._show_name:
            return
        self._show_name = show
        self._name.setVisible(show)
        self._apply_metrics()

    def _apply_metrics(self):
        size = self.card_size
        height = size + (NAME_AREA if self._show_name else 0)
        self.setFixedSize(QSize(size, height))
        self._image.setFixedSize(QSize(self.thumb_size, self.thumb_size))
        self._restyle()
        if self._pixmap is not None:
            self._render_pixmap()

    def _restyle(self):
        # Two style variants rather than a property plus `polish()`: a selected
        # card must look selected even while the pointer is elsewhere, and the two
        # states have to compose.
        # 两种样式变体而不是"属性加 polish()"：被选中的卡片即使指针在别处也必须看起来
        # 是选中的，而这两种状态必须能叠加。
        accent = "#1677FF"
        if self._selected:
            background = "rgba(22,119,255,90)"
            border = f"2px solid {accent}"
        else:
            background = "rgba(255,255,255,18)"
            border = "2px solid transparent"
        self.setStyleSheet(
            f"#emojiCard {{ background: {background};"
            f" border: {border};"
            f" border-radius: {CORNER_RADIUS}px; }}"
            f"#emojiCard:hover {{ background: rgba(22,119,255,60); }}"
            f"#emojiName {{ font-size: 11px; }}"
        )

    def set_selected(self, selected):
        selected = bool(selected)
        if selected == self._selected:
            return
        self._selected = selected
        self._restyle()

    @property
    def is_selected(self):
        return self._selected

    # ---- content / 内容 --------------------------------------------------

    def set_emoji(self, emoji, filepath=None):
        # Bind a row (a dict from the store) and its file path /
        # 绑定一行（来自存储的字典）及其文件路径
        self._emoji = emoji
        self._filepath = filepath
        self._pixmap = None
        text = (emoji or {}).get("text_content") or ""
        if text:
            # Text stickers show their content instead of an image, which is
            # the whole point of a text group.
            # 文字贴纸显示其内容而非图片，这正是文字分组的意义。
            self._image.setPixmap(QPixmap())
            self._image.setText(self._shorten(text))
            self._name.setVisible(False)
        else:
            self._image.setText("")
            self._name.setVisible(self._show_name)
            self._name.setText(self._shorten((emoji or {}).get("original_name", "")))
        self.setToolTip(text or (emoji or {}).get("original_name", ""))

    @staticmethod
    def _shorten(text, limit=12):
        text = str(text or "")
        return text if len(text) <= limit else text[:limit] + "\u2026"

    def apply_thumb(self, pixmap):
        # Deliver a decoded thumbnail. `fast=True` skips the resample, which is
        # the hot path during GIF playback where frames already match the box.
        # 交付已解码的缩略图。`fast=True` 跳过重采样，这是 GIF 播放时帧尺寸已匹配
        # 目标框的热路径。
        self._pixmap = pixmap
        self._render_pixmap()

    def _render_pixmap(self):
        pixmap = self._pixmap
        if pixmap is None or pixmap.isNull():
            return
        box = self.thumb_size
        if pixmap.width() > box or pixmap.height() > box:
            pixmap = pixmap.scaled(
                box, box,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._image.setPixmap(pixmap)

    def clear(self):
        # Reset for recycling through the card pool /
        # 重置以便经卡片池回收复用
        self._emoji = None
        self._filepath = None
        self._pixmap = None
        # The selection state must be reset too: a recycled card that kept its
        # badge would show a stale highlight on an unrelated sticker.
        # 选中态也必须重置：保住角标的回收卡片会在无关的贴纸上显示过期的选中样式。
        self._selected = False
        self._restyle()
        self._image.setPixmap(QPixmap())
        self._image.setText("")
        self._name.setText("")

    # ---- queries / 查询 --------------------------------------------------

    @property
    def emoji(self):
        return self._emoji

    @property
    def filepath(self):
        return self._filepath

    @property
    def emoji_id(self):
        return (self._emoji or {}).get("id")

    # ---- events / 事件 ---------------------------------------------------

    def enterEvent(self, event):
        # Report the card's global rectangle so the preview can position itself
        # without the card knowing what a preview is.
        # 上报卡片的全局矩形，使预览能自行定位，而卡片无需知道"预览"是什么。
        if self._emoji:
            self.hovered.emit(self._emoji, self.global_rect())
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered.emit(None, None)
        super().leaveEvent(event)

    def global_rect(self):
        from PySide6.QtCore import QRect

        top_left = self.mapToGlobal(self.rect().topLeft())
        return QRect(top_left, self.size())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._emoji:
            self.activated.emit(self._emoji)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        # A double click opens the edit dialog; a single click copies. Reporting
        # both would copy and then open a dialog, so the double click is consumed.
        # 双击打开编辑对话框；单击为复制。两者同时上报会先复制再弹窗，因此双击被消费。
        if event.button() == Qt.MouseButton.LeftButton and self._emoji:
            self.context_requested.emit(self._emoji, event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        if self._emoji:
            self.context_requested.emit(self._emoji, event.globalPos())
        event.accept()


class PlaceholderCard(QWidget):
    # Shown when a group has no rows, so an empty group never looks like a
    # rendering failure. / 分组没有行时显示，使空分组不会看起来像渲染失败。
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setObjectName("emojiPlaceholder")
        layout = QVBoxLayout(self)
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setObjectName("emojiPlaceholderLabel")
        layout.addWidget(label)

    def set_text(self, text):
        for label in self.findChildren(QLabel):
            label.setText(text)


def paint_drop_indicator(painter, rect, color=None):
    # Shared helper so the grid and any future overlay draw the insertion bar
    # identically. / 共用辅助，使网格与将来可能的覆盖层绘制出完全相同的插入指示条。
    painter.fillRect(rect, color or QColor(22, 119, 255))


def draw_dashed_frame(painter, rect, color=None):
    # Dashed outline used for the drag preview / 拖拽预览使用的虚线轮廓
    pen = painter.pen()
    pen.setStyle(Qt.PenStyle.DashLine)
    pen.setColor(color or QColor(22, 119, 255))
    painter.setPen(pen)
    painter.drawRect(rect)


__all__ = [
    "CORNER_RADIUS",
    "FRAME_INSET",
    "NAME_AREA",
    "EmojiCard",
    "PlaceholderCard",
    "draw_dashed_frame",
    "paint_drop_indicator",
]
