"""Hover preview: the enlarged card that follows the pointer.

A sticker at card size is often too small to tell apart from its neighbours, so
hovering one shows it larger in a floating window. The previous release built the
overlay inside each card and hid the card's *neighbours* to make room — which is
why the grid and the card ended up with a mutual dependency on each other's
private attributes.

Here the preview is a separate top-level window owned by the view. It knows
nothing about a card beyond "a file path and a size", so the card does not need to
reach up into the grid, and the grid does not need to reach down into the card.

悬停预览：跟随指针的放大卡片。

卡片尺寸下的贴纸常常难以与相邻的区分，因此悬停时会以浮动窗口放大显示。上一版本把该
覆盖层建在每张卡片内部，并隐藏卡片的"邻居"来腾出空间——这正是网格与卡片最终互相依赖
对方私有属性的原因。

在这里，预览是视图持有的独立顶层窗口。它对卡片的了解仅限于"一个文件路径和一个尺寸"，
因此卡片无需向上伸手进网格，网格也无需向下伸手进卡片。
"""
import logging
import os

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

log = logging.getLogger("GIFManager")

# Delay before the preview appears. Showing it instantly makes the grid feel
# twitchy while the pointer crosses the window on the way somewhere else.
# 预览出现前的延迟。立即显示会让指针只是路过窗口时网格显得神经质。
SHOW_DELAY_MS = 220

# Gap between the pointer and the preview window /
# 指针与预览窗口之间的间距
POINTER_GAP_PX = 18

# Extra size beyond the card, as a factor /
# 相对卡片的放大倍数
DEFAULT_ZOOM = 1.15

# Longest side of the source image the preview will decode. Decoding a
# 1920x1920 sticker to show it at 200 px would cost far more than the preview is
# worth.
# 预览会解码的源图最长边。为在 200px 处显示而解码 1920x1920 的贴纸，代价远超预览本身
# 的价值。
MAX_SOURCE_DIM = 512


class HoverPreview(QWidget):
    # A frameless, non-interactive window showing one sticker enlarged.
    #
    # `WA_TransparentForMouseEvents` plus `Tool` keeps it out of the way: the
    # pointer must never land on the preview, or moving the mouse toward the
    # sticker would leave the card and the preview would flicker.
    # 无边框、不接收交互的窗口，放大显示一张贴纸。
    #
    # `WA_TransparentForMouseEvents` 加上 `Tool` 让它不碍事：指针绝不能落在预览上，
    # 否则朝贴纸移动鼠标时会离开卡片，预览就会闪烁。
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setObjectName("hoverPreview")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self._image = QLabel()
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setObjectName("hoverPreviewImage")
        layout.addWidget(self._image)

        self._caption = QLabel()
        self._caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._caption.setObjectName("hoverPreviewCaption")
        layout.addWidget(self._caption)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SHOW_DELAY_MS)
        self._timer.timeout.connect(self._show_now)

        self._pending = None
        self._zoom = DEFAULT_ZOOM
        self._source_dim = 240
        self._pixmap = None
        self._current_path = None
        self.hide()

    # ---- configuration / 配置 -------------------------------------------

    def set_zoom(self, zoom):
        # Clamped to the same range the settings schema allows, so a stored value
        # and a runtime value cannot disagree.
        # 钳制到设置 schema 允许的同一范围，使存储值与运行时值不会不一致。
        self._zoom = max(1.0, min(2.0, float(zoom)))

    def set_source_dim(self, dimension):
        # Size of the card the preview is standing in for /
        # 预览所代表的卡片的尺寸
        self._source_dim = max(24, int(dimension))

    # ---- lifecycle / 生命周期 -------------------------------------------

    def schedule(self, filepath, caption="", card_global_rect=None):
        # Ask for the preview after the delay. Calling it again for the same file
        # is a no-op, so a pointer moving within one card does not restart the
        # timer and make the preview flicker.
        # 延迟后请求预览。对同一文件重复调用是空操作，因此在同一张卡片内移动指针不会重启
        # 定时器而让预览闪烁。
        if not filepath:
            self.cancel()
            return
        if (self._pending is not None and self._pending[0] == filepath
                and self.isVisible()):
            self._move_near(card_global_rect)
            return
        self._pending = (filepath, caption, card_global_rect)
        self._timer.start()

    def cancel(self):
        self._timer.stop()
        self._pending = None
        self.hide()

    def _show_now(self):
        if self._pending is None:
            return
        filepath, caption, rect = self._pending
        self._pending = None
        if not os.path.isfile(filepath):
            return
        if self._pixmap is None or self._current_path != filepath:
            if not self._load(filepath):
                return
        self._caption.setText(caption or "")
        self._caption.setVisible(bool(caption))
        target = self._target_size()
        scaled = self._pixmap.scaled(
            target, target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self._image.setPixmap(scaled)
        self._image.setFixedSize(scaled.size())
        self.adjustSize()
        self._move_near(rect)
        self.show()
        self.raise_()

    def _target_size(self):
        return max(48, int(round(self._source_dim * self._zoom)))

    def _load(self, filepath):
        # Prefer the native decoder, which is a single native call and decodes
        # directly at the target size; fall back to `QImage`, which decodes the
        # whole file first.
        # 优先用原生解码器：一次原生调用并直接按目标尺寸解码；回退到 `QImage`，它先解码
        # 整个文件。
        from gifmanager.frontend.qt import images

        target = min(MAX_SOURCE_DIM, self._target_size())
        decoded = images.decode_thumbnail(filepath, target)
        if decoded is not None:
            from PySide6.QtGui import QImage

            image = QImage(decoded.pixels, decoded.width, decoded.height,
                           decoded.width * 4, QImage.Format.Format_RGBA8888)
            if not image.isNull():
                self._pixmap = QPixmap.fromImage(image)
                self._current_path = filepath
                return True
        pixmap = QPixmap(filepath)
        if pixmap.isNull():
            log.info("hover preview: cannot decode %s", filepath)
            return False
        self._pixmap = pixmap
        self._current_path = filepath
        return True

    def _move_near(self, card_global_rect):
        # Place the preview beside the card, flipping to the other side when it
        # would fall off the screen. A preview that hangs off the edge is worse
        # than one on the "wrong" side.
        # 把预览放在卡片旁，将要超出屏幕时翻到另一侧。挂在屏幕外比放在"错"的一侧更糟。
        if card_global_rect is None:
            return
        rect = card_global_rect
        screen = QGuiApplication.screenAt(rect.center())
        available = screen.availableGeometry() if screen else None

        x = rect.right() + POINTER_GAP_PX
        y = rect.top() - (self.height() - rect.height()) // 2
        if available is not None:
            if x + self.width() > available.right():
                x = rect.left() - POINTER_GAP_PX - self.width()
            if x < available.left():
                x = rect.left()
            y = max(available.top() + 4,
                    min(y, available.bottom() - self.height() - 4))
        self.move(QPoint(int(x), int(y)))

    # ---- teardown / 退出 -------------------------------------------------

    def shutdown(self):
        self.cancel()
        self._pixmap = None
        self._current_path = None


__all__ = [
    "DEFAULT_ZOOM",
    "HoverPreview",
    "MAX_SOURCE_DIM",
    "POINTER_GAP_PX",
    "SHOW_DELAY_MS",
]
