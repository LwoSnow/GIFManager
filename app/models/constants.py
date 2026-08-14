# Window / UI constants
# 窗口 / UI 常量

# Default window size (used before saved geometry is restored)
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
