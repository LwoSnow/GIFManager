"""Window and UI constants shared by every front-end.

窗口与界面常量，供所有前端共用。
"""

# Default window size (used before saved geometry is restored) /
# 默认窗口尺寸（恢复保存的几何前使用）
DEFAULT_WINDOW_WIDTH = 620
DEFAULT_WINDOW_HEIGHT = 520

# Minimum window size in logical (device-independent) pixels — Qt sizes are
# DPI-independent, so on a 125% display the physical size is x1.25.
# 344x380 logical == ~433x475 physical at 125% scaling. 344 px is a bit
# wider than the 3-column critical point (427 physical on the user's 125%
# screen): the extra ~6 px of headroom keeps 3 full columns stable against
# font/scrollbar rounding, instead of sitting 1 px above the 2-column cliff.
# 窗口最小尺寸（逻辑像素，与 DPI 无关——125% 缩放下物理尺寸为 x1.25）。
# 344x380 逻辑 == 125% 屏上约 433x475 物理。344px 比 3 列临界点（用户
# 125% 屏上为 427 物理）略宽：多出的约 6px 余量保证 3 整列稳定，不会因
# 字体/滚动条舍入而掉到 2 列。
MIN_WINDOW_WIDTH = 344
MIN_WINDOW_HEIGHT = 380

# Grid geometry: the lazy-load buffer band around the visible viewport, and the
# default card metrics. Kept here (not in the Qt widgets) so a non-Qt front-end
# can reuse the same virtualisation maths. / 网格几何：可视区上下方的懒加载
# 缓冲带，以及默认卡片尺寸。放在此处（而非 Qt 控件内），使非 Qt 前端也能复用
# 同一套虚拟化计算。
GRID_BUFFER_PX = 300

# Card side length in logical pixels / 卡片边长（逻辑像素）
CARD_SIZE = 76

# Horizontal and vertical spacing between cards / 卡片之间的水平与垂直间距
CARD_SPACING = 8

__all__ = [
    "CARD_SIZE",
    "CARD_SPACING",
    "DEFAULT_WINDOW_HEIGHT",
    "DEFAULT_WINDOW_WIDTH",
    "GRID_BUFFER_PX",
    "MIN_WINDOW_HEIGHT",
    "MIN_WINDOW_WIDTH",
]
