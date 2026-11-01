"""Check the icon tinting and the shadcn design tokens.

Both are things that broke or could break silently:

  * `setting.svg` became a Lucide STROKE icon, and the provider was injecting a `fill` attribute.
    Measured through the provider itself, the glyph rendered pure BLACK on BOTH themes - invisible
    on the dark window. Nothing failed; it just looked wrong.
  * the shadcn/SWB tokens are a second palette beside the original one, so a typo in a key name
    would show up as `undefined` in QML rather than as an error.

两者都是曾经静默出错、且可能再次静默出错的地方：

  * `setting.svg` 变成 Lucide 的"描边型"图标后，提供器仍在注入 `fill` 属性。通过提供器本身实测，
    字形在两个主题下都渲染为"纯黑"——在深色窗口上不可见。没有任何东西失败，只是看起来不对。
  * shadcn/SWB 令牌是原调色板旁边的第二套，因此 key 名打错时在 QML 里表现为 `undefined`，
    而不是一个错误。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PYTHONUTF8"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# A tinted glyph must actually be visible, and must not be near-black on the dark theme.
# 着色后的字形必须真的可见，且在深色主题上不能接近纯黑。
DARK_MAX_INK = 100      # the dark theme needs a LIGHT glyph
LIGHT_MAX_INK = 160     # the light theme needs a DARK glyph


def ink_colour(image):
    # The average colour of the visible pixels, or None when nothing was drawn.
    # 可见像素的平均颜色；什么都没画时返回 None。
    pixels = [image.pixelColor(x, y)
              for y in range(image.height()) for x in range(image.width())
              if image.pixelColor(x, y).alpha() > 40]
    if not pixels:
        return None
    count = len(pixels)
    return tuple(sum(getattr(p, channel)() for p in pixels) // count
                 for channel in ("red", "green", "blue"))


def main():
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QApplication

    from gifmanager.frontend.qml.services import GearIconProvider
    from gifmanager.frontend.qml.theme import ThemeBridge

    application = QApplication.instance() or QApplication([])
    _ = application
    problems = []

    # ---- 1. both bundled icons are tinted to the theme's contrast colour ----
    # ---- 1. 两个随包图标都着色为主题对比色 -------------------------------
    print("==== 1. icon tinting ====")
    for icon in ("setting", "github"):
        for theme_name in ("dark", "light"):
            theme = ThemeBridge()
            theme.set_theme(theme_name)
            provider = GearIconProvider(theme)
            pixmap = provider.requestPixmap(f"{icon}/{theme_name}",
                                            QSize(32, 32), QSize(32, 32))
            ink = ink_colour(pixmap.toImage())
            if ink is None:
                problems.append(f"{icon}/{theme_name} rendered nothing at all")
                print(f"  {icon:8} {theme_name:6} -> NOTHING DRAWN")
                continue
            average = sum(ink) / 3.0
            print(f"  {icon:8} {theme_name:6} ink=rgb{ink} avg={average:.0f}")
            if theme_name == "dark" and average < DARK_MAX_INK:
                problems.append(
                    f"{icon} on the dark theme is nearly black (rgb{ink}); the window is "
                    f"{theme.window}, so the glyph is invisible")
            if theme_name == "light" and average > LIGHT_MAX_INK:
                problems.append(
                    f"{icon} on the light theme is too light (rgb{ink}) against {theme.window}")

    # ---- 2. the shadcn tokens exist and invert between themes --------------
    # ---- 2. shadcn 令牌存在且在主题间反转 ---------------------------------
    print()
    print("==== 2. shadcn tokens ====")
    required_colours = ("primary", "primaryForeground", "secondary", "secondaryForeground",
                        "accent", "accentForeground", "background", "popover", "foreground",
                        "mutedForeground", "border", "destructive", "ring",
                        "primaryHover", "secondaryHover", "accentHover",
                        "destructiveBg", "destructiveBgHover", "focusRing")
    required_metrics = ("uiRadius", "uiRadiusSm", "uiFontSize", "uiFontSizeSm",
                        "uiControlHeight", "uiControlHeightSm", "uiControlHeightLg",
                        "uiIconSize", "uiHandleSize", "uiTrackThickness",
                        "uiFocusRingWidth", "uiAnimationMs", "uiPaddingX")
    dark = ThemeBridge()
    dark.set_theme("dark")
    light = ThemeBridge()
    light.set_theme("light")

    for label, bridge in (("dark", dark), ("light", light)):
        colours = bridge.uiColors
        metrics = bridge.uiMetrics
        missing = [k for k in required_colours if k not in colours]
        missing_metrics = [k for k in required_metrics if k not in metrics]
        print(f"  {label:6} colours={len(colours)} metrics={len(metrics)} "
              f"missing={missing + missing_metrics}")
        for key in missing + missing_metrics:
            problems.append(f"the {label} theme has no {key!r} token")

    # The two schemes must actually differ, or the page would look the same in both.
    # 两套配色必须真的不同，否则页面在两个主题下会长得一样。
    if dark.uiColors.get("background") == light.uiColors.get("background"):
        problems.append(
            "both themes report the same shadcn background, so tokens are not switching")
    else:
        print(f"  background inverts: dark={dark.uiColors['background']} "
              f"light={light.uiColors['background']}")

    # A focus ring must be translucent, because it is drawn OUTSIDE the control and would
    # otherwise add a hard opaque outline.
    # 聚焦环必须是半透明的，因为它画在控件"外部"，否则会加上一条硬实线。
    ring = str(dark.uiColors.get("focusRing", ""))
    if not ring.startswith("#") or len(ring) != 9 or ring[1:3] == "ff":
        problems.append(f"the focus ring is not translucent (#aarrggbb): {ring!r}")
    else:
        print(f"  focusRing is translucent: {ring}")

    # ---- 3. the bundled font is registered AND resolved --------------------
    # ---- 3. 随包字体已注册且被解析到 ---------------------------------------
    #
    # A font that fails to load is INVISIBLE: Qt falls back to the system face and draws perfectly
    # normal-looking text in the wrong typeface. So this asserts the family the application font
    # actually RESOLVES to, not merely that the files were passed to Qt.
    # 加载失败的字体是"不可见"的：Qt 回退到系统字面，画出看起来完全正常但字体不对的文字。因此这里断言
    # 应用字体"实际解析到"的字族，而不只是文件被交给了 Qt。
    print()
    print("==== 3. the bundled font ====")
    from PySide6.QtGui import QFontDatabase, QFontInfo

    from gifmanager import __version__
    from gifmanager.frontend.qml.services import register_bundled_fonts
    from gifmanager.frontend.qml.theme import BUNDLED_FONT_FAMILY, families_for
    from gifmanager.frontend.qml.app import build_application

    ok, families, reason = register_bundled_fonts()
    print(f"  registered    : ok={ok} families={families}")
    if not ok:
        problems.append(f"the bundled font could not be loaded: {reason}")
    else:
        styles = QFontDatabase.styles(families[0])
        print(f"  styles        : {styles}")
        # Fewer than two styles means only one file was accepted, so `Font.Bold` would be
        # synthesised instead of using the real Bold face.
        # 少于两个样式意味着只有一个文件被接受，于是 `Font.Bold` 会被合成，而不是使用真实的 Bold 字面。
        if len(styles) < 2:
            problems.append(
                f"the bundled family registered only {len(styles)} style(s); bold text would be "
                f"synthesised instead of using a real weight")

    # The application font must RESOLVE to the bundled family.
    # 应用字体必须"解析到"随包字族。
    application = build_application([])
    resolved = QFontInfo(application.font()).family()
    print(f"  app font      : {resolved}")
    if resolved != BUNDLED_FONT_FAMILY:
        problems.append(
            f"the application font resolves to {resolved!r}, not the bundled "
            f"{BUNDLED_FONT_FAMILY!r}; the shipped font is not being used")
    # And it must be first in the QML-facing fallback list, or a QML item naming `theme.fontFamily`
    # would pick something else.
    # 并且它必须在 QML 侧的字体族列表里排第一，否则命名 `theme.fontFamily` 的 QML 元素会拿到别的。
    order = families_for("win32")
    print(f"  theme list[0] : {order[0]}")
    if order[0] != BUNDLED_FONT_FAMILY:
        problems.append(
            f"theme.fontFamily is {order[0]!r}, not the bundled family")

    # The version the About page shows. Asserted here because a release that leaves it stale is
    # indistinguishable from one that did not ship.
    # 关于页显示的版本。在此断言，因为"版本号没更新"的发布与"没发布"无法区分。
    print(f"  version       : {__version__}")
    if not __version__.startswith("2."):
        problems.append(
            f"the shipped version is {__version__!r}, but this release is the 2.x line")

    print()
    if problems:
        print("UI TOKEN CHECK FAILED / UI 令牌检查未通过")
        for problem in problems:
            print("  " + problem)
        return 1
    print("UI TOKEN CHECK OK / UI 令牌检查通过")
    print("  both icons are tinted to the theme's contrast colour, every token exists and")
    print("  inverts, and the bundled font is registered AND is what the application resolves to")
    print("  两个图标都着色为主题对比色、每个令牌都存在并反转，且随包字体已注册并确实是应用解析到的那个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
