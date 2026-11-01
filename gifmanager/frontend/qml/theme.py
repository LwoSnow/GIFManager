"""The theme bridge: the palette QML binds to.

QSS is a Qt Widgets mechanism and does not apply to Qt Quick Controls, so the two
style sheets under `frontend/qt/theme/` cannot be reused. The colours they defined
are carried over here as data, and `Theme.qml` exposes them as a singleton that
every component reads.

Writing the palette once, in Python, and letting QML read it has two advantages
over hard-coding colours in QML: a theme switch is one property write rather than
a walk over every component, and the palette is testable without a scene graph.

主题桥：QML 绑定的调色板。

QSS 是 Qt Widgets 的机制，对 Qt Quick Controls 不生效，因此
`frontend/qt/theme/` 下的两份样式表无法复用。它们定义的颜色在此以数据形式保留，并由
`Theme.qml` 作为单例暴露给每个组件读取。

把调色板在 Python 里写一次、让 QML 读取，比把颜色硬编码进 QML 有两个好处：切换主题是
一次属性写入而不是遍历每个组件；且调色板无需场景图即可测试。
"""
import logging

from PySide6.QtCore import Property, QObject, Signal, Slot

log = logging.getLogger("GIFManager")

# The palettes, transcribed from the QSS the Qt Widgets front-end used. Keeping
# the same values means the QML interface looks like the one it replaces, which
# makes a visual regression obvious rather than a matter of taste.
#
# 调色板，转录自 Qt Widgets 前端使用的 QSS。保持相同取值意味着 QML 界面看起来与被它
# 取代的那个一致，使视觉回归显而易见，而不是品味问题。
PALETTES = {
    "dark": {
        "window": "#1E1E1E",
        "surface": "#252525",
        "surfaceAlt": "#2B2B2B",
        "surfaceHover": "#353535",
        "border": "#3A3A3A",
        "borderStrong": "#333333",
        # The card's hover border. The original dark QSS used #4A4A4A; the light
        # theme switched the hover border to the accent, which is why the two
        # palettes disagree here deliberately.
        # 卡片悬停边框。原深色 QSS 用 #4A4A4A；浅色主题把悬停边框换成强调色，因此
        # 两套调色板在此处刻意不同。
        "borderHover": "#4A4A4A",
        "text": "#E0E0E0",
        "textMuted": "#999999",
        "textStrong": "#FFFFFF",
        "accent": "#383838",
        "accentSoft": "#2A2A2A",
        "accentText": "#E6E6E6",
        "danger": "#E4686C",
        "card": "#2B2B2B",
        "cardHover": "#353535",
        "cardSelected": "#383838",
        "scrollbar": "#3A3A3A",
        "scrollbarHover": "#4A4A4A",
    },
    "light": {
        "window": "#F2F3F5",
        "surface": "#FFFFFF",
        "surfaceAlt": "#FAFAFA",
        "surfaceHover": "#EFEFEF",
        "border": "#D8D8D8",
        "borderStrong": "#CCCCCC",
        "borderHover": "#B4B4B4",
        "text": "#333333",
        "textMuted": "#888888",
        "textStrong": "#222222",
        "accent": "#E9E9E9",
        "accentSoft": "#F2F2F2",
        "accentText": "#1A1A1A",
        "danger": "#D93A3E",
        "card": "#FFFFFF",
        "cardHover": "#F5F5F5",
        "cardSelected": "#E9E9E9",
        "scrollbar": "#C8C8C8",
        "scrollbarHover": "#ABABAB",
    },
}

# Typography and metrics. Kept beside the colours because a component that reads
# one almost always reads the other, and splitting them makes every component
# import two singletons.
# 字体与尺寸。与颜色放在一起，因为读取其一的组件几乎总会读取另一个，拆开会让每个组件
# 都要导入两个单例。
METRICS = {
    "fontSizeSmall": 11,
    "fontSizeBody": 13,
    "fontSizeTitle": 15,
    "fontSizeHeading": 18,
    "radius": 6,
    "radiusLarge": 12,
    "spacingTight": 4,
    "spacing": 8,
    "spacingLoose": 14,
    "navWidth": 168,
    # Card geometry, matching the original project's `emoji_item` /
    # `FlowLayout` so the two interfaces are the same density. The QML views read
    # `cardSizeBase` from here rather than repeating the number.
    # 卡片几何，与原项目的 `emoji_item` / `FlowLayout` 一致，使两个界面密度相同。QML 视图
    # 从这里读 `cardSizeBase` 而不是重复那个数字。
    "cardSizeBase": 100,
    "nameStrip": 22,
    "cardGap": 8,
    "gridMargin": 8,
    "nameArea": 22,
    "statusHeight": 26,
    # Height of a settings control and of a toolbar button. Present because QML already
    # read `theme.controlHeight` and it did NOT exist, so `Layout.preferredHeight` was
    # assigned `undefined` — the control silently took its own implicit height instead of
    # the intended one, which is the kind of bug that looks like a styling choice.
    # 设置控件与工具栏按钮的高度。加上它是因为 QML 已经在读 `theme.controlHeight` 而它"不存在"，
    # 于是 `Layout.preferredHeight` 被赋为 `undefined`——控件静默采用自身隐式高度而不是预期高度，
    # 这正是那种看起来像样式选择的缺陷。
    "controlHeight": 32,
}

# ---------------------------------------------------------------------------
# shadcn-style UI tokens, adapted from SWB-QML-UI
# 从 SWB-QML-UI 适配的 shadcn 风格 UI 令牌
# ---------------------------------------------------------------------------
#
# SWB-QML-UI (https://github.com/xxmzwf/SWB-QML-UI, MIT) restyles all 51
# `QtQuick.Controls.Basic` controls into the shadcn Base UI look, driven by its own
# `SwbTheme` singleton. It is a compiled C++/CMake QML module, and PySide6 does not ship
# Qt's CMake package (`lib/cmake` contains only PySide6's own), so `find_package(Qt6)`
# cannot succeed and the plugin cannot be built here without a full multi-gigabyte Qt SDK.
#
# So the STRUCTURE is ported rather than linked: the token names, the component API (variants,
# sizes, states) and the metric scale follow SWB, and our own QML components reproduce them. The
# SHADES are not SWB's - see the note above `SHADCN_PALETTES` for why the near-white dark button was
# replaced by a low-contrast ladder. So this is "shadcn-style adapted from SWB", not "SWB verbatim",
# and the difference is deliberate rather than drift.
#
# The tokens are separate keys rather than a replacement for the palette above: the existing
# colours are load-bearing across every page, and a rewrite would have been a redesign rather than
# an adaptation. A component opts in by reading the `ui*` keys.
#
# SWB-QML-UI（https://github.com/xxmzwf/SWB-QML-UI，MIT）把全部 51 个
# `QtQuick.Controls.Basic` 控件重塑为 shadcn Base UI 外观，由它自己的 `SwbTheme` 单例驱动。
# 它是一个编译型 C++/CMake QML 模块，而 PySide6 不附带 Qt 的 CMake 包（`lib/cmake` 里只有
# PySide6 自己的），因此 `find_package(Qt6)` 无法成功，不安装完整的数 GB Qt SDK 就无法在此
# 构建该插件。
#
# 因此"移植"的是结构而不是链接：令牌名称、组件 API（变体、尺寸、状态）与度量刻度遵循 SWB，并由我们
# 自己的 QML 组件重现。"明暗值"不是 SWB 的——理由见 `SHADCN_PALETTES` 上方的说明：近白色的深色按钮
# 被一条低对比阶梯取代。因此这里是"从 SWB 适配的 shadcn 风格"，而不是"逐字照搬 SWB"，这个差别是
# 刻意的，不是漂移。
#
# 这些令牌是"额外"的键，而不是替换上面的调色板：既有颜色承载着每个页面的呈现，重写它就成了重新
# 设计而不是适配。组件通过读取 `ui*` 键来选择加入。

# The neutral palette, per colour scheme - LOW CONTRAST, with contrast used as the STATE signal.
#
# # Why this is not SWB's palette any more
#
# SWB's dark primary is `#e5e5e5` on a `#0a0a0a` window: a ~19:1 ratio, i.e. a near-white slab in a
# near-black window. As the main call to action in the toolbar it shouts, and in a picker that is
# opened dozens of times a day that shout becomes tiring. The complaint was exactly this, and it is
# the same conclusion Apple reaches with "dim to focus, separate to keep flow" and Emil Kowalski's
# "match the motion and weight to the personality of the component": a tool should feel calm, and
# emphasis should be scarce enough to mean something.
#
# So the base surfaces sit CLOSE together and state is expressed by the DELTA between them:
#
#     dark  background #141416 -> surface1 #1a1a1d -> surface2 #212125
#           -> surface3 #2a2a2f -> surface4 #34343a -> selected #e6e6e9
#     light background #ffffff -> surface1 #f7f7f8 -> surface2 #f0f0f2
#           -> surface3 #e9e9ec -> surface4 #e1e1e5 -> selected #1f1f24
#
# Unselected controls sit on surface1..2 (a few percent away from the window), hover moves up one
# step, press moves up two, and `selected` is the ONLY high-contrast token - reserved for "this is
# the one that is active". `primary` (the call to action) is therefore a raised surface plus bright
# text rather than a white block: the hierarchy comes from the text and the weight, not from area.
#
# `#aarrggbb` is Qt's spelling when a token must be translucent; most are solid so the steps are
# predictable rather than dependent on what is behind them.
#
# 中性调色板，按配色方案——"低对比"，并用对比度作为"状态"信号。
#
# # 为什么不再是 SWB 的调色板
#
# SWB 的深色 primary 是 `#e5e5e5`，窗口是 `#0a0a0a`：约 19:1，也就是近黑窗口里的一块近白板。作为
# 工具栏的主操作它在"喊"，而在一个每天打开几十次的选取器里，这种"喊"会变成疲劳。用户的抱怨正是此，
# 也与 Apple 的"压暗以聚焦、用分离保持流畅"以及 Emil Kowalski 的"让动效与轻重匹配组件的性格"是同一
# 结论：工具应当安静，而强调要稀缺才有意义。
#
# 因此基础表面彼此"接近"，状态由它们之间的"差值"表达：
#
#     dark  background #141416 -> surface1 #1a1a1d -> surface2 #212125
#           -> surface3 #2a2a2f -> surface4 #34343a -> selected #e6e6e9
#     light background #ffffff -> surface1 #f7f7f8 -> surface2 #f0f0f2
#           -> surface3 #e9e9ec -> surface4 #e1e1e5 -> selected #1f1f24
#
# 未选中的控件停在 surface1..2（与窗口相差几个百分点），悬停上一级、按下上两级，而 `selected` 是
# "唯一"的高对比令牌——专留给"当前是它"这一状态。`primary`（主操作）因此是"抬升的表面 + 明亮文字"
# 而不是一块白：层级来自文字与字重，而不是面积。
#
# 需要半透明时用 Qt 的 `#aarrggbb` 写法；大多数是实色，使层级可预测而不依赖背后是什么。
SHADCN_PALETTES = {
    "dark": {
        "background": "#141414",
        # The elevation ladder. Each step is a small, deliberate delta, not a jump.
        # 抬升阶梯。每一级都是小而刻意的差值，不是跳跃。
        "surface1": "#1a1a1a",
        "surface2": "#212121",
        "surface3": "#2a2a2a",
        "surface4": "#343434",
        "foreground": "#ededed",
        "mutedForeground": "#8d8d8d",
        "border": "#2c2c2c",
        "borderStrong": "#3a3a3a",
        # The call to action: a raised surface, NOT a white slab.
        # 主操作：抬升的表面，"不是"一块白。
        "primary": "#3a3a3a",
        "primaryForeground": "#f0f0f0",
        "primaryHover": "#444444",
        "secondary": "#1e1e1e",
        "secondaryForeground": "#d6d6d6",
        "secondaryHover": "#262626",
        # Hover tint for ghost/outline buttons.
        # ghost 与 outline 按钮的悬停底色。
        "accent": "#262626",
        "accentForeground": "#ededed",
        "accentHover": "#2e2e2e",
        # The ONE high-contrast token: reserved for the selected/active state.
        # "唯一"的高对比令牌：专留给选中/激活状态。
        "selected": "#e6e6e6",
        "selectedForeground": "#141414",
        "popover": "#1a1a1a",
        "destructive": "#e4686c",
        "destructiveForeground": "#ffffff",
        "ring": "#555555",
        "focusRing": "#38ffffff",
        # The modal scrim: translucent, so the window behind stays legible as context instead of
        # being blacked out. Apple's "dim to focus, separate to keep flow".
        # 模态遮罩：半透明，使背后的窗口仍可读作上下文而不是被涂黑。Apple 的"压暗以聚焦、用分离保持
        # 流畅"。
        "scrim": "#66000000",
    },
    "light": {
        "background": "#ffffff",
        "surface1": "#f7f7f7",
        "surface2": "#f0f0f0",
        "surface3": "#e9e9e9",
        "surface4": "#e1e1e1",
        "foreground": "#1a1a1a",
        "mutedForeground": "#6e6e6e",
        "border": "#e3e3e3",
        "borderStrong": "#d2d2d2",
        "primary": "#ececec",
        "primaryForeground": "#1a1a1a",
        "primaryHover": "#e4e4e4",
        "secondary": "#f4f4f4",
        "secondaryForeground": "#2a2a2a",
        "secondaryHover": "#ececec",
        "accent": "#f0f0f0",
        "accentForeground": "#1a1a1a",
        "accentHover": "#e8e8e8",
        "selected": "#1f1f1f",
        "selectedForeground": "#fafafa",
        "popover": "#ffffff",
        "destructive": "#d93a3e",
        "destructiveForeground": "#ffffff",
        "ring": "#b4b4b4",
        "focusRing": "#2e000000",
        "scrim": "#40000000",
    },
}

# SWB's sizing and typography tokens, which do not vary with the colour scheme.
# SWB 的尺寸与排版令牌，不随配色方案变化。
SHADCN_METRICS = {
    "uiRadius": 10,
    # 基准圆角减 2，小号控件与列表项使用 / base radius minus 2, for small controls and rows
    "uiRadiusSm": 8,
    # 基准圆角加 4，对话框与卡片等大表面使用 / base radius plus 4, for dialogs and large surfaces
    "uiRadiusLarge": 14,
    "uiFontSize": 14,
    # 基准字号减 1，小号控件使用 / base font size minus 1, for small controls
    "uiFontSizeSm": 13,
    "uiControlHeight": 32,
    # 基准高度减 4，小号控件使用 / base control height minus 4, for small controls
    "uiControlHeightSm": 28,
    # 基准高度加 4，大号控件使用 / base control height plus 4, for large controls
    "uiControlHeightLg": 36,
    "uiIconSize": 16,
    # The gap between a control's box (checkbox, radio, switch) and its label. Named because three
    # components need the same number, and a hardcoded 8 in each would drift.
    # 控件方框（复选框、单选、开关）与它标签之间的间距。命名是因为三个组件需要同一个数字，而在各自
    # 里硬编码 8 会漂移。
    "uiControlGap": 8,
    "uiHandleSize": 12,
    "uiTrackThickness": 4,
    "uiFocusRingWidth": 3,
    "uiAnimationMs": 150,
    # Press feedback is deliberately shorter than a colour transition: the acknowledgement has to
    # land inside the press, and both Apple ("respond on pointer-down") and Kowalski (100-160 ms for
    # button press feedback) put it well under this value.
    # 按压反馈刻意短于颜色过渡：确认必须落在"按下"之内，而 Apple（"在按下时响应"）与 Kowalski
    #（按钮按压反馈 100–160 毫秒）都把它放在这个值以内。
    "uiPressMs": 110,
    # How far a press scales the control down. 0.97 is what Kowalski recommends - perceptible, and
    # small enough that a row of buttons does not visibly wobble.
    # 按压时控件缩小的幅度。0.97 是 Kowalski 建议的值——可感知，且小到一排按钮不会明显抖动。
    "uiPressScale": 0.97,
    "uiPaddingX": 10,
    # Dialog geometry. `uiDialogPadding` is the inset on every side, so the title, the content and
    # the footer share one straight text edge; `uiDialogWidth` is the default before a caller
    # narrows it for a short prompt.
    # 对话框几何。`uiDialogPadding` 是四边的内缩量，使标题、内容与页脚共用一条直的文本边缘；
    # `uiDialogWidth` 是调用方为短提示收窄之前的默认宽度。
    "uiDialogPadding": 18,
    "uiDialogWidth": 380,
    "uiDialogGap": 12,
}

# Fallback family list per platform convention. Qt falls back automatically, but
# naming the right family is what keeps CJK glyph metrics consistent — and those
# metrics feed the card layout.
# 按平台惯例的字体族回退列表。Qt 会自动回退，但指定正确的字体族才能让中日韩字形度量
# 一致——而那些度量会影响卡片布局。
FONT_FAMILIES = {
    "win32": ["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"],
    "darwin": ["PingFang SC", "Hiragino Sans GB", "Helvetica Neue"],
}
FONT_FAMILIES_DEFAULT = [
    "Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Micro Hei", "DejaVu Sans",
]

# The family shipped in `resources/fonts/`, preferred over every system font.
#
# # Why a bundled face instead of the system one
#
# Apple's typography rule is "default to the platform's system font ... override only with a
# reason."
# The reason here is that the interface is CJK-first and the system face is whatever the machine
# happens to have: `Microsoft YaHei` on Windows, `Noto Sans CJK` on a Linux box, `PingFang` on
# macOS -
# three different sets of metrics. The card layout derives the name strip's height from font
# metrics,
# so the same library looked subtly different on every machine and a long name could clip on one and
# not another. One bundled family removes that variable, and HarmonyOS Sans ships real Light/Medium/
# Bold weights, which is what lets weight carry hierarchy without faking it with size.
#
# It is also a *licence* consideration: the font is redistributable under its own licence, and
# shipping
# it beside the application is what the OFL permits; bundling a system font would not be.
#
# 随包在 `resources/fonts/` 的字体族，优先于任何系统字体。
#
# # 为什么用随包字体而不是系统字体
#
# Apple 的排版规则是"默认用平台系统字体……只在有理由时覆盖"。这里的理由是界面以中日韩为先，而系统
# 字体取决于机器恰好装了什么：Windows 上是 `Microsoft YaHei`、Linux 上是 `Noto Sans CJK`、macOS 上
# 是 `PingFang`——三套不同的度量。卡片布局由字体度量推导名称条高度，因此同一个素材库在每台机器上
# 都会略有差异，一个长名字可能在某台机器上被裁切而在另一台上不会。统一的随包字族消除了这个变量，而
# HarmonyOS Sans 提供真实的 Light/Medium/Bold 字重，这正是让字重承载层级、而不必用字号伪装的原因。
#
# 这同时是一个"许可"考量：该字体按其自身许可可再分发，随应用一起发布正是 OFL 所允许的；而打包一个
# 系统字体则不行。
BUNDLED_FONT_FAMILY = "HarmonyOS Sans SC"

# The weights shipped, in ascending weight order. Registered in this order so Qt's font database
# sees
# them as styles of one family rather than as six unrelated faces.
# 随包的字重，按升序。按此顺序注册，使 Qt 的字体数据库把它们视为同一字族的多个样式，而不是六个
# 互不相关的字体。
BUNDLED_FONT_FILE_ORDER = (
    "HarmonyOS_Sans_SC_Thin.ttf",
    "HarmonyOS_Sans_SC_Light.ttf",
    "HarmonyOS_Sans_SC_Regular.ttf",
    "HarmonyOS_Sans_SC_Medium.ttf",
    "HarmonyOS_Sans_SC_Bold.ttf",
    "HarmonyOS_Sans_SC_Black.ttf",
)


def families_for(platform_key):
    # The bundled family first, then the platform's own list as a fallback for any glyph the bundled
    # face lacks (rare, but a missing glyph must not fall back to a box).
    # 随包字族在前，然后是平台自身的列表，作为随包字面所缺字形的回退（少见，但缺字形不能回退成方框）。
    return [BUNDLED_FONT_FAMILY] + list(
        FONT_FAMILIES.get(platform_key, FONT_FAMILIES_DEFAULT))


def _parse_colour(text):
    # "#rrggbb" or "#aarrggbb" -> (r, g, b, a) as 0..1 floats, or None.
    #
    # A tiny parser rather than `QColor`: this module is imported by the theme bridge, which is
    # built before any window exists, and pulling in QtGui to compute six derived colours would
    # add a toolkit dependency to a file that only needs arithmetic.
    # "#rrggbb" 或 "#aarrggbb" -> 0..1 浮点的 (r, g, b, a)，无法解析时返回 None。
    #
    # 用极简解析器而不是 `QColor`：本模块被主题桥导入，而主题桥在存在任何窗口之前就被构建，
    # 为一个只做算术的文件拉入 QtGui 来计算六个推导色会引入工具包依赖。
    value = str(text or "").strip().lstrip("#")
    try:
        if len(value) == 6:
            r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
            a = 255
        elif len(value) == 8:
            # Qt spells "#aarrggbb": alpha first.
            # Qt 的写法是 "#aarrggbb"：alpha 在最前。
            a = int(value[0:2], 16)
            r, g, b = (int(value[i:i + 2], 16) for i in (2, 4, 6))
        else:
            return None
    except ValueError:
        return None
    return (r / 255.0, g / 255.0, b / 255.0, a / 255.0)


def _format_colour(rgba):
    # (r, g, b, a) floats -> "#aarrggbb", the form both QML `color` and SWB use.
    # (r, g, b, a) 浮点 -> "#aarrggbb"，QML 的 `color` 与 SWB 都用这种形式。
    r, g, b, a = (max(0, min(255, round(channel * 255))) for channel in rgba)
    return "#{0:02x}{1:02x}{2:02x}{3:02x}".format(a, r, g, b)


def _with_alpha(text, alpha):
    # SWB's `withAlpha`: keep rgb, replace alpha.
    # SWB 的 `withAlpha`：保留 rgb，替换 alpha。
    rgba = _parse_colour(text)
    if rgba is None:
        return text
    return _format_colour((rgba[0], rgba[1], rgba[2], alpha))


def _darken(text, factor):
    # SWB's `Qt.darker(colour, factor)`: divide each channel, leave alpha alone.
    #
    # `Qt.darker` divides by the factor (so 1.05 makes it 5% darker), which is worth stating
    # because "darker by 1.05" reads like "multiply" to anyone who has not checked.
    # SWB 的 `Qt.darker(colour, factor)`：每个通道除以该因子，alpha 不变。
    #
    # `Qt.darker` 是把通道"除以"因子（因此 1.05 表示暗 5%），这点值得说明，因为"深 1.05 倍"对没
    # 核实过的人来说读起来像是"相乘"。
    rgba = _parse_colour(text)
    if rgba is None or factor <= 0:
        return text
    return _format_colour((rgba[0] / factor, rgba[1] / factor, rgba[2] / factor, rgba[3]))


def palette_for(theme_name):
    return PALETTES.get(theme_name, PALETTES["dark"])


class ThemeBridge(QObject):
    # The palette QML reads. One instance is installed as the `theme` context
    # property.
    # QML 读取的调色板。一个实例被安装为 `theme` 上下文属性。

    changed = Signal()

    def __init__(self, settings=None, platform_key="", parent=None):
        # `settings` is read only for the stored theme name, and only by `refresh()`. It is
        # OPTIONAL because a bridge is needed by windows that exist BEFORE any backend
        # does — the "already running" notice is the case that proved it: that window is
        # shown by `run()` before `create_backend()`, so there is no settings object to
        # pass, and requiring one made the notice unable to read the palette at all.
        #
        # `settings` 只用于读取已存储的主题名，且只有 `refresh()` 读它。它是"可选"的，因为
        # 存在先于任何后端的窗口需要该桥——"已在运行"提示正是证明这一点的情况：那个窗口由
        # `run()` 在 `create_backend()` 之前显示，因此没有设置对象可传，而要求一个会令该提示
        # 完全无法读取调色板。
        #
        # `settings` is only read for the theme name; the palette itself is constant per
        # theme, so a settings change needs nothing more than `refresh()`. The language is
        # deliberately NOT held here: it affects text, and text comes from the bridge, not
        # from a colour provider.
        # `settings` 只用于读取主题名；调色板本身按主题是常量，因此设置变更只需 `refresh()`。
        # 语言刻意"不"在此持有：它影响文本，而文本来自桥，不来自颜色提供方。
        super().__init__(parent)
        self._settings = settings
        self._platform_key = platform_key
        self._theme = "dark"

    # ---- theme / 主题 ----------------------------------------------------

    def theme_name(self):
        return self._theme

    def set_theme(self, name):
        name = name if name in PALETTES else "dark"
        if name == self._theme:
            return False
        self._theme = name
        self.changed.emit()
        return True

    @Property(str, notify=changed)
    def name(self):
        return self._theme

    @Property(bool, notify=changed)
    def isDark(self):
        return self._theme == "dark"

    # ---- colours / 颜色 --------------------------------------------------
    #
    # One property per palette entry rather than a `color(name)` function: a
    # function call does not create a binding, so a component reading
    # `theme.color("accent")` would NOT repaint on a theme switch. A property with
    # a notify signal does.
    # 每个调色板条目一个属性，而不是 `color(name)` 函数：函数调用不会建立绑定，因此读取
    # `theme.color("accent")` 的组件在切换主题时"不会"重绘。带 notify 信号的属性会。

    def _value(self, key):
        return palette_for(self._theme)[key]

    @Property(str, notify=changed)
    def window(self):
        return self._value("window")

    @Property(str, notify=changed)
    def surface(self):
        return self._value("surface")

    @Property(str, notify=changed)
    def surfaceAlt(self):
        return self._value("surfaceAlt")

    @Property(str, notify=changed)
    def surfaceHover(self):
        return self._value("surfaceHover")

    @Property(str, notify=changed)
    def border(self):
        return self._value("border")

    @Property(str, notify=changed)
    def borderStrong(self):
        return self._value("borderStrong")

    @Property(str, notify=changed)
    def borderHover(self):
        return self._value("borderHover")

    @Property(str, notify=changed)
    def text(self):
        return self._value("text")

    @Property(str, notify=changed)
    def textMuted(self):
        return self._value("textMuted")

    @Property(str, notify=changed)
    def textStrong(self):
        return self._value("textStrong")

    @Property(str, notify=changed)
    def accent(self):
        return self._value("accent")

    @Property(str, notify=changed)
    def accentSoft(self):
        return self._value("accentSoft")

    @Property(str, notify=changed)
    def accentText(self):
        return self._value("accentText")

    @Property(str, notify=changed)
    def danger(self):
        return self._value("danger")

    @Property(str, notify=changed)
    def card(self):
        return self._value("card")

    @Property(str, notify=changed)
    def cardHover(self):
        return self._value("cardHover")

    @Property(str, notify=changed)
    def cardSelected(self):
        return self._value("cardSelected")

    @Property(str, notify=changed)
    def scrollbar(self):
        return self._value("scrollbar")

    @Property(str, notify=changed)
    def scrollbarHover(self):
        return self._value("scrollbarHover")

    # ---- metrics and typography / 尺寸与字体 -----------------------------

    @Property(int, notify=changed)
    def fontSizeSmall(self):
        return METRICS["fontSizeSmall"]

    @Property(int, notify=changed)
    def fontSizeBody(self):
        return METRICS["fontSizeBody"]

    @Property(int, notify=changed)
    def fontSizeTitle(self):
        return METRICS["fontSizeTitle"]

    @Property(int, notify=changed)
    def fontSizeHeading(self):
        return METRICS["fontSizeHeading"]

    @Property(int, notify=changed)
    def radius(self):
        return METRICS["radius"]

    @Property(int, notify=changed)
    def radiusLarge(self):
        return METRICS["radiusLarge"]

    @Property(int, notify=changed)
    def spacingTight(self):
        return METRICS["spacingTight"]

    @Property(int, notify=changed)
    def spacing(self):
        return METRICS["spacing"]

    @Property(int, notify=changed)
    def spacingLoose(self):
        return METRICS["spacingLoose"]

    @Property(int, notify=changed)
    def navWidth(self):
        return METRICS["navWidth"]

    @Property(int, notify=changed)
    def statusHeight(self):
        return METRICS["statusHeight"]

    @Property(int, notify=changed)
    def controlHeight(self):
        return METRICS["controlHeight"]

    # Card geometry. Exposed so the QML views do not repeat the numbers the original project
    # defined, which is what let the first QML version drift to a 76px card.
    # 卡片几何。暴露出来使 QML 视图不重复原项目定义过的数字，那正是第一个 QML 版本漂移到 76px
    # 卡片的原因。
    @Property(int, notify=changed)
    def cardSizeBase(self):
        return METRICS["cardSizeBase"]

    @Property(int, notify=changed)
    def nameStrip(self):
        return METRICS["nameStrip"]

    @Property(int, notify=changed)
    def cardGap(self):
        return METRICS["cardGap"]

    @Property(int, notify=changed)
    def gridMargin(self):
        return METRICS["gridMargin"]

    @Property("QStringList", notify=changed)
    def fontFamilies(self):
        return families_for(self._platform_key)

    @Property(str, notify=changed)
    def fontFamily(self):
        families = families_for(self._platform_key)
        return families[0] if families else ""

    # ---- shadcn / SWB design tokens / shadcn 与 SWB 设计令牌 ---------------
    #
    # Two MAP properties rather than 27 explicit ones.
    #
    # The colours section above explains why each palette entry is its own property: a plain
    # function call creates no binding, so a component reading `theme.color("accent")` would not
    # repaint on a theme switch. A MAP property with `notify=changed` has the same guarantee for a
    # different reason: the notify signal fires, the property is re-read, and every binding that
    # touched the map is re-evaluated. What it does not give is per-key granularity, which is
    # irrelevant here because a theme switch changes every shadcn token at once.
    #
    # The alternative was 27 nearly identical `@Property` accessors, which is a lot of noise for
    # no additional safety - and the components that read these tokens are opt-in, so a mistake
    # shows up as one missing key rather than a wrong colour everywhere.
    #
    # QML reads them as `theme.uiColors.primary` and `theme.uiMetrics.uiRadius`. A missing key
    # evaluates to `undefined`, which Qt reports when it reaches a typed property - an honest
    # failure rather than a silent black rectangle.
    #
    # 用两个"映射"属性而不是 27 个显式属性。
    #
    # 上面的颜色部分解释了为何每个调色板条目都是独立属性：普通函数调用不建立绑定，因此读取
    # `theme.color("accent")` 的组件在主题切换时不会重绘。带 `notify=changed` 的"映射"属性以另一
    # 种理由提供同样的保证：notify 信号触发、属性被重读、所有触及该映射的绑定重新求值。它不提供的
    # 是按 key 的粒度，而这在此处无关紧要，因为一次主题切换会同时改变所有 shadcn 令牌。
    #
    # 另一种做法是 27 个几乎相同的 `@Property` 访问器，那是大量噪音而无额外安全性——而且读取这些
    # 令牌的组件是"选择加入"的，因此一个错误表现为缺少某个 key，而不是到处颜色出错。
    #
    # QML 以 `theme.uiColors.primary` 与 `theme.uiMetrics.uiRadius` 读取。缺失的 key 求值为
    # `undefined`，当它到达有类型的属性时 Qt 会报告——这是诚实的失败，而不是静默的黑色矩形。
    @Property("QVariantMap", notify=changed)
    def uiColors(self):
        # The palette for the CURRENT theme, plus the few tokens that are computed rather than
        # chosen.
        #
        # The hover steps are now DECLARED in the palette, not derived, because state is expressed
        # by the size of the step: a derived `Qt.darker(accent, 1.08)` produced whatever delta the
        # base colour happened to allow, which is precisely the unpredictability the ladder exists
        # to remove. Only the alpha-based feedback tints are computed, and `setdefault` keeps a
        # declared value when one exists so the two can never disagree.
        # 当前主题的调色板，加上少数"计算得出而非挑选"的令牌。
        #
        # 悬停层级现在在调色板里"声明"，不再推导：状态由台阶的大小表达，而推导出来的
        # `Qt.darker(accent, 1.08)` 得到的是基础色偶然允许的差值——正是这条阶梯要消除的不可预测性。
        # 只有基于 alpha 的反馈色被计算，且 `setdefault` 在已声明时保留声明值，使两者不可能不一致。
        base = dict(SHADCN_PALETTES.get(self._theme, SHADCN_PALETTES["dark"]))
        base.setdefault("destructiveBg", _with_alpha(base["destructive"], 0.12))
        base.setdefault("destructiveBgHover", _with_alpha(base["destructive"], 0.22))
        base.setdefault("focusRing", _with_alpha(base["ring"], 0.5))
        # `selected` doubles as the "high contrast" state; expose it under both names so a component
        # can read whichever reads better in its context.
        # `selected` 同时就是"高对比"状态；以两个名称暴露，使组件可按上下文选择更贴切的写法。
        base.setdefault("emphasis", base.get("selected", base.get("primary")))
        base.setdefault("emphasisForeground",
                        base.get("selectedForeground", base.get("primaryForeground")))
        return base

    @Property("QVariantMap", constant=True)
    def uiMetrics(self):
        # Sizing and typography tokens. Constant because they do not vary with the colour scheme;
        # declaring that lets QML skip re-evaluating every geometric binding on a theme switch.
        # 尺寸与排版令牌。声明为常量，因为它们不随配色方案变化；这样 QML 在主题切换时可跳过重新
        # 求值每个几何绑定。
        return dict(SHADCN_METRICS)

    # ---- notifications / 通知 -------------------------------------------

    @Slot()
    def refresh(self):
        # Re-read the theme from settings and notify. Called when the settings page changes
        # the theme, so the palette and the stored setting cannot disagree.
        #
        # A bridge built without a settings object has nothing to re-read, so this is a no-op
        # rather than an AttributeError: the notice window calls nothing, but a future caller
        # should not have to know which kind of bridge it holds.
        # 从设置重新读取主题并发出通知。设置页改动主题时调用，使调色板与已存储设置不会不一致。
        #
        # 没有设置对象而构建的桥没有东西可重读，因此这是一个空操作而不是 AttributeError：提示
        # 窗口不调用它，但未来的调用方不应需要知道自己持有的是哪种桥。
        if self._settings is None:
            return
        self.set_theme(self._settings.theme)


__all__ = [
    "FONT_FAMILIES",
    "FONT_FAMILIES_DEFAULT",
    "METRICS",
    "PALETTES",
    "ThemeBridge",
    "families_for",
    "palette_for",
]
