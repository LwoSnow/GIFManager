"""Experimental GPU-backed viewport for the sticker grid.

Qt renders QWidget hierarchies with the CPU raster engine, so the app's own GPU
usage is normally zero. Installing a `QOpenGLWidget` as the scroll area's
viewport makes Qt composite the grid through an OpenGL surface, which genuinely
engages the GPU (and therefore the adapter Windows was asked to prefer).

This is OFF by default and applied ONLY at startup: the surface is created once
and never swapped at runtime. Both restrictions come from field reports about
the earlier attempt — re-creating the viewport while toggling crashed the
renderer, and a freshly created surface could show a black first paint.

`QOpenGLWidget` itself is portable; only the reason the option exists (routing
work to the adapter an OS preference asked for) is Windows-shaped. On a system
with no such preference the switch is hidden rather than shown dead, which is
what the settings page's capability gate does.

实验性 GPU 视口。Qt 用 CPU 光栅引擎绘制 QWidget 层级，因此程序自身的 GPU 占用
通常为零。把 `QOpenGLWidget` 装成滚动区的视口后，Qt 会通过 OpenGL 表面合成网格，
从而真正启用 GPU（进而用上 Windows 被要求优先的那块显卡）。

默认关闭，且仅在启动时安装：表面只创建一次，运行时绝不替换。这两条限制都来自
此前实测的问题——反复切换时重建视口会让渲染器崩溃，而刚创建的表面可能出现首帧
全黑。
"""
from PySide6.QtGui import QColor, QPalette
# QOpenGLWidget lives in its OWN module (QtOpenGLWidgets), not QtWidgets /
# QOpenGLWidget 位于独立模块（QtOpenGLWidgets）而非 QtWidgets
from PySide6.QtOpenGLWidgets import QOpenGLWidget


# GPU viewport: always filled with the theme surface colour.
# GPU 视口：始终以主题表面色填充。
class GridGlViewport(QOpenGLWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        # NoPartialUpdate: Qt clears the framebuffer before each paint, so a
        # stale or uninitialised region can never show through as black — that
        # was the "empty group is pure black until a full repaint" report.
        # NoPartialUpdate：Qt 每次绘制前清空帧缓冲，因此陈旧或尚未初始化的区域
        # 不会透出黑色——那正是"空分组纯黑、需完整重绘才恢复"的报告现象。
        self.setUpdateBehavior(
            QOpenGLWidget.UpdateBehavior.NoPartialUpdate)
        self.setAutoFillBackground(True)

    def set_background(self, color: QColor):
        # Keep the palette in step with the theme so Qt's background fill (and
        # the empty-group surface) uses the theme colour instead of black.
        # 让调色板跟随主题，使 Qt 的背景填充（以及空分组的表面）使用主题色而非黑色。
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, color)
        pal.setColor(QPalette.ColorRole.Base, color)
        self.setPalette(pal)
        self.setAutoFillBackground(True)
        self.update()
