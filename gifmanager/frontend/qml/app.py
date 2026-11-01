"""QML application bootstrap: engine, context properties, window.

The Qt Widgets shell did the same job by constructing a `ShellWindow`, but the two
are not interchangeable. A QML front-end needs:

* an engine with a plugin path that can see this package's modules;
* the bridge and the theme installed as context properties, because QML reaches
  Python only through `QObject` properties and slots;
* a `.qml` root object rather than a Python window, so the window's own layout is
  declarative.

Every one of those is a place where a mistake produces the same symptom — a blank
window and a line on stderr — so the engine's warnings are logged rather than
ignored.

QML 应用引导：引擎、上下文属性、窗口。

Qt Widgets 外壳通过构造 `ShellWindow` 做同样的事，但两者不可互换。QML 前端需要：

* 一个插件路径能看到本包模块的引擎；
* 把桥与主题安装为上下文属性，因为 QML 只经 `QObject` 的属性与槽访问 Python；
* 一个 `.qml` 根对象而非 Python 窗口，使窗口自身的布局也是声明式的。

以上每一点出错都会产生同一种症状——空白窗口加一行 stderr——因此引擎的警告被记录而不是
忽略。
"""
import logging
import os
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from gifmanager import APP_ID, APP_NAME, __version__
from gifmanager.backend import create_backend
from gifmanager.core import logging_setup, paths
from gifmanager.frontend.qml.bridge import BackendBridge
from gifmanager.frontend.qml.theme import ThemeBridge
from gifmanager.frontend.qt.bridge import BackendAdapter
from gifmanager.platform import single_instance as single_instance_service

log = logging.getLogger("GIFManager")

# Base point size for the interface font. Matches the Qt Widgets shell so the two
# front-ends render text at the same size.
# 界面字体基准磅值。与 Qt Widgets 外壳一致，使两个前端以相同尺寸渲染文本。
BASE_FONT_POINT_SIZE = 10

# Environment flag that makes QML parse errors fatal to the exit code. Off by
# default so a packaging problem does not turn a warning into a crash.
# 让 QML 解析错误影响退出码的环境开关。默认关闭，使打包问题不会把一条警告变成崩溃。
STRICT_ENV = "GIFMANAGER_QML_STRICT"

# The Qt Quick Controls style this interface requires.
#
# `Basic` is the style DESIGNED to be customized. Every other style on Windows is
# the native one, which refuses customization: each `background` and `contentItem`
# override is reported as "The current style does not support customization of this
# control" and then silently ignored, so the theme ends up half-applied — some
# controls following the palette and others drawing themselves in system colours.
#
# This is set from Python rather than relying only on `qtquickcontrols2.conf`,
# because the conf file is looked up relative to the working directory: launching
# from another directory silently selected the native style, which is exactly how
# those three warnings appeared.
#
# 本界面所要求的 Qt Quick Controls 样式。
#
# `Basic` 是"为可定制而设计"的样式。Windows 上的其他样式都是原生样式，而原生样式拒绝
# 定制：每一处 `background` 与 `contentItem` 覆盖都被报告为"当前样式不支持定制该控件"并被
# 静默忽略，于是主题只被应用一半——一部分控件跟随调色板，另一部分用系统颜色自我绘制。
#
# 这一点从 Python 设置而不是只依赖 `qtquickcontrols2.conf`，因为 conf 文件是按工作目录
# 查找的：从别的目录启动会静默选中原生样式，那三个警告正是这样出现的。
REQUIRED_STYLE = "Basic"


def qml_root():
    # Directory holding the `.qml` sources / 存放 `.qml` 源码的目录
    return os.path.join(os.path.dirname(os.path.abspath(__file__)))


def qml_entry():
    # Absolute path of the root component / 根组件的绝对路径
    return os.path.join(qml_root(), "shell", "Main.qml")


def controls_conf():
    # Absolute path of the style configuration file /
    # 样式配置文件的绝对路径
    return os.path.join(qml_root(), "qtquickcontrols2.conf")


def apply_controls_style():
    # Select the customizable style, and point Qt at the conf file by ABSOLUTE path.
    #
    # Must run before any control is created: `QQuickStyle` reads the style at
    # control-instantiation time, and setting it afterwards has no effect on
    # already-loaded controls. It is safe to call before a `QGuiApplication` exists,
    # and it is idempotent, so both the import-time call below and the explicit call
    # in `create_engine` are harmless together.
    #
    # The environment variable is set in addition to the explicit call because the
    # two cover different failure modes: the call fixes the style, and the variable
    # makes the conf file's other settings (should any be added) reach components
    # that ask Qt for them by path.
    #
    # 选择可定制的样式，并以"绝对路径"告知 Qt conf 文件的位置。
    #
    # 必须在任何控件被创建之前运行：`QQuickStyle` 在控件实例化时读取样式，之后再设置对
    # 已加载的控件无效。在 `QGuiApplication` 存在之前调用是安全的，且它是幂等的，因此下面
    # 导入时的调用与 `create_engine` 中的显式调用同时存在也无害。
    #
    # 除显式调用外还设置环境变量，因为两者覆盖不同的失败模式：调用修正样式，环境变量让
    # conf 文件的其他设置（如果以后添加）能被按路径向 Qt 索取它们的组件看到。
    from PySide6.QtQuickControls2 import QQuickStyle

    if os.path.isfile(controls_conf()):
        os.environ.setdefault("QT_QUICK_CONTROLS_CONF", controls_conf())
    QQuickStyle.setStyle(REQUIRED_STYLE)
    return QQuickStyle.name()


# Applied at IMPORT time, not only when the interface is created.
#
# A caller that builds its own `QQmlApplicationEngine` — which the smoke test does,
# and a plugin or an embedding host may — would otherwise create its first control
# before `create_engine` ever runs, and every themed control would then be drawn by
# the native style. Doing it here means importing this module is enough.
#
# 在"导入"时应用，而不只在创建界面时。
#
# 自行构建 `QQmlApplicationEngine` 的调用方（冒烟测试就是这样，插件或嵌入宿主也可能如此）
# 否则会在 `create_engine` 运行之前就创建出第一个控件，于是每个带主题的控件都会由原生样式
# 绘制。放在这里意味着只要导入本模块就足够。
apply_controls_style()


def configure_engine(engine, strict=False):
    # Add the import paths, collect engine warnings, and load the root component.
    #
    # Context properties are NOT installed here. They must be installed — and
    # referenced from Python — before `load()`, and keeping that in `create_engine`
    # means the objects that must stay alive are held in the same place they are
    # installed, rather than in a caller that might pass a temporary mapping.
    # 添加导入路径、收集引擎警告，并加载根组件。
    #
    # 上下文属性"不"在此安装。它们必须在 `load()` 之前安装并从 Python 侧被引用，而把这件事
    # 留在 `create_engine` 里意味着必须存活的那些对象与安装它们的位置在一起，而不是在一个
    # 可能传入临时映射的调用方那里。
    for directory in ("shell", "views", "components", ""):
        engine.addImportPath(os.path.join(qml_root(), directory)
                             if directory else qml_root())

    warnings = []

    def collect(messages):
        # PySide6 delivers `QQmlApplicationEngine.warnings` as ONE list argument,
        # not as (mode, message) pairs. Declaring two parameters made every warning
        # raise `TypeError` inside the signal handler, which swallowed the only
        # diagnostic QML gives for a misspelled property or a bad import.
        # PySide6 把 `QQmlApplicationEngine.warnings` 作为"单个列表"参数投递，而不是
        # (mode, message) 对。声明两个参数会让每条警告都在信号处理器内抛 `TypeError`，
        # 从而吞掉 QML 对属性名拼错或错误导入给出的唯一诊断。
        for message in messages or ():
            text = str(message).strip()
            if not text:
                continue
            warnings.append(text)
            # A QML warning is almost always a binding that will evaluate to
            # `undefined`, so it is logged at warning level rather than hidden.
            # QML 警告几乎总是一个将求值为 `undefined` 的绑定，因此以警告级别记录而不是
            # 隐藏。
            log.warning("qml: %s", text)

    engine.warnings.connect(collect)
    engine.load(QUrl.fromLocalFile(qml_entry()))
    return warnings


def create_engine(adapter, strict=None):
    # Build an engine with the bridge and palette installed, load the interface,
    # and return (engine, bridge, theme, warnings).
    # 构建一个已安装桥与调色板的引擎、加载界面，并返回 (engine, bridge, theme, warnings)。
    from gifmanager import platform as platform_layer

    if strict is None:
        strict = str(os.environ.get(STRICT_ENV, "")).strip().lower() in (
            "1", "true", "yes", "on")

    # Before the engine, so no control is ever created under the native style.
    # 在引擎之前，使任何控件都不会在原生样式下被创建。
    style = apply_controls_style()
    log.info("qml: controls style is %s", style)
    if style != REQUIRED_STYLE:
        log.warning(
            "qml: the %s style could not be selected (got %s); controls that "
            "override background/contentItem will be drawn by the style instead "
            "of the theme / 无法选中 %s 样式（当前为 %s）；覆盖 background/"
            "contentItem 的控件将由样式而非主题绘制",
            REQUIRED_STYLE, style, REQUIRED_STYLE, style)

    # Apply the bundled icon BEFORE the window exists, so the taskbar entry has one
    # from the first paint, and so the tray has an icon to take.
    # 在窗口存在"之前"应用随包图标，使任务栏条目从首帧起就有图标，也让托盘有图标可取。
    from gifmanager.frontend.qml.services import apply_application_icon

    if not apply_application_icon():
        log.warning("qml: no window icon; the tray will report itself unavailable / "
                    "无窗口图标；托盘会报告自身不可用")

    theme = ThemeBridge(adapter.settings,
                        platform_key=platform_layer.current().key)
    bridge = BackendBridge(adapter, theme)

    engine = QQmlApplicationEngine()
    # The GIF frame provider must be installed BEFORE the document loads: an `Image`
    # whose source names an unknown provider resolves to a null image and reports it as a
    # warning, and the first card is created during the load.
    # GIF 帧提供器必须在文档加载"之前"安装：source 指向未知提供器的 `Image` 会解析为
    # 空图像并报为警告，而第一张卡片是在加载过程中被创建的。
    from gifmanager.frontend.qml.animator import (register_preview_provider,
                                                  register_provider)

    register_provider(engine)
    # The still frame a card shows before its animation is ready. Registered here for the same
    # reason: the first card is created during the load, and an unknown provider resolves to a
    # null image.
    # 卡片在动画就绪之前显示的静态帧。理由相同：第一张卡片在加载过程中被创建，而未知提供器会解析为
    # 空图像。
    register_preview_provider(engine)
    # The context property is `app`, and the pages receive it as `app: app`.
    #
    # THE REFERENCES ARE STORED ON THE ENGINE, BEFORE LOADING, and that is not
    # tidiness. Two separate lifetimes have to be satisfied:
    #
    #   * `setContextProperty` does NOT take ownership of a `QObject`, so the
    #     bridge must have a live Python reference for as long as the engine reads
    #     it. A local would be collected when `create_engine` returns, and QML
    #     would then evaluate the name to null — while
    #     `engine.rootContext().contextProperty("app")` still reports the object as
    #     present, because the C++ side keeps a wrapper that no longer wraps
    #     anything.
    #   * `engine.rootContext()` returns a TEMPORARY wrapper around the C++
    #     `QQmlContext`. Letting it be collected can take the property binding with
    #     it, so the wrapper is held as well.
    #
    # Storing both before `load()` matters because the values are read while the
    # document is being created.
    #
    # Measured, not assumed: `tests/probe_qml_ownership.py` keeps the reference in
    # one run and drops it in the next, and only the kept one resolves in the
    # document.
    #
    # 上下文属性名为 `app`，页面以 `app: app` 接收它。
    #
    # 这些引用在"加载之前"存放在引擎上，这不是为了整洁。有两个生命周期必须被满足：
    #
    #   * `setContextProperty` "不"接管 `QObject` 的所有权，因此只要引擎还会读取桥，桥就
    #     必须存活。局部变量会在 `create_engine` 返回时被回收，QML 随后把该名称求值为
    #     null——同时 `engine.rootContext().contextProperty("app")` 仍报告对象存在，因为
    #     C++ 侧保留了一个已不再包装任何东西的包装器。
    #   * `engine.rootContext()` 返回的是 C++ `QQmlContext` 的"临时"包装，让它被回收可能
    #     连带失去属性绑定，因此该包装也一并持有。
    #
    # 在 `load()` 之前存放两者很重要，因为取值是在文档创建过程中被读取的。
    #
    # 这是测出来的而非假设的：`tests/probe_qml_ownership.py` 在一次运行中保住引用、下一次
    # 丢弃它，只有保住的那次能在文档内解析成功。
    engine._dsh_context = engine.rootContext()
    engine._dsh_bridge = bridge
    engine._dsh_theme = theme
    # The bridge is exposed as `bridge`, NOT as `app`, and the pages receive it as
    # `app: bridge`.
    #
    # The reason is a scope trap that costs a lot of time to find by reading:
    # inside `LibraryPage.qml`, the expression `app` resolves to the page's OWN
    # `app` property (an id or property in scope shadows a context property), so a
    # binding written `app: app` is self-referential and evaluates to null. The
    # page then works perfectly and reads `undefined` for everything.
    #
    # Measured: with the context property named `app`, `root.title` resolved
    # correctly while all three pages read null. `tests/probe_qml_real.py` reports
    # both facts side by side.
    #
    # 桥以 `bridge` 暴露，而"不是" `app`，页面以 `app: bridge` 接收它。
    #
    # 原因是一个靠阅读很难发现的作用域陷阱：在 `LibraryPage.qml` 内部，表达式 `app` 会
    # 解析到页面"自身"的 `app` 属性（作用域内的 id 或属性会遮蔽上下文属性），因此写成
    # `app: app` 的绑定是自引用的，求值为 null。页面随后看起来完全正常，但每个取值都是
    # `undefined`。
    #
    # 实测：当上下文属性名为 `app` 时，`root.title` 正确解析，而三个页面都读到 null。
    # `tests/probe_qml_real.py` 把这两件事并列报告。
    for name, value in (("bridge", bridge), ("theme", theme)):
        engine._dsh_context.setContextProperty(name, value)

    # The settings-gear provider must be installed before the document loads, for
    # the same reason the GIF frame provider is: the toolbar's `Image` resolves
    # its source during load.
    # 设置齿轮提供器必须在文档加载前安装，与 GIF 帧提供器同理：工具栏的 `Image` 在
    # 加载过程中解析其 source。
    from gifmanager.frontend.qml.services import AppIconProvider, GearIconProvider

    engine.addImageProvider("gear", GearIconProvider(theme))
    # The About page's app icon. A separate provider because it renders a PNG at the requested
    # size rather than an SVG with an injected fill, and mixing the two in one class would make
    # each branch guess which kind of file it was given.
    # 关于页的应用图标。用单独的提供器，因为它按请求尺寸渲染 PNG，而不是注入填充色渲染 SVG，把两者
    # 混在一个类里会让每个分支都要猜自己拿到的是哪类文件。
    engine.addImageProvider("appicon", AppIconProvider())

    warnings = configure_engine(engine, strict=strict)

    roots = engine.rootObjects()
    if not roots:
        log.error("qml: the root component produced no window; %s", qml_entry())
        raise RuntimeError(
            "the QML interface failed to load / QML 界面加载失败: "
            + (warnings[0] if warnings else "no diagnostic from the engine"))

    log.info("qml: loaded %s root object(s)", len(roots))
    return engine, bridge, theme, warnings


def build_application(argv=None):
    # A configured `QApplication`.
    #
    # # Why QApplication and not QGuiApplication
    #
    # A QML interface on its own needs no widget stack, so `QGuiApplication` is the
    # obvious base and was the first choice — but this application has a SYSTEM TRAY, and
    # `QSystemTrayIcon` is a `QtWidgets` class. The tray is created by the QML root when
    # the interface loads, so it runs on every start, and under a `QGuiApplication` it dies
    # with
    #
    #     QWidget: Cannot create a QWidget without QApplication
    #
    # That message names neither the tray nor the application class, which is why the
    # first diagnosis blamed the "already running" notice and only fixed half the problem.
    # The tray is a real feature the user asked for, so the correct resolution is to build
    # the base class the feature requires rather than to remove the feature.
    #
    # High-DPI rounding is PassThrough so fractional scale factors (125%) are honoured
    # instead of rounded to 100% or 200%, which is what keeps a 3-column layout from
    # collapsing to 2.
    #
    # 已配置的 `QApplication`。
    #
    # # 为什么是 QApplication 而不是 QGuiApplication
    #
    # 单独的 QML 界面不需要控件栈，因此 `QGuiApplication` 是显然的基类，也是最初的选择——
    # 但本应用有"系统托盘"，而 `QSystemTrayIcon` 是 `QtWidgets` 类。托盘由 QML 根对象在界面
    # 加载时创建，因此每次启动都会执行，而在 `QGuiApplication` 下它会以
    #
    #     QWidget: Cannot create a QWidget without QApplication
    #
    # 死掉。那条消息既没点名托盘、也没点名应用类，这正是第一次诊断归咎于"已在运行"提示、只修好了
    # 一半问题的原因。托盘是用户要求的真实功能，因此正确的解决方式是构建该功能所要求的基类，而不是
    # 去掉该功能。
    #
    # 高 DPI 舍入设为 PassThrough，使 125% 这类分数缩放被尊重而不是舍入到 100% 或 200%——这
    # 正是 3 列布局不会塌成 2 列的原因。
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    # Declare the application id BEFORE the application object exists, and that ordering is the
    # whole point.
    #
    # `setDesktopFileName` is what makes Qt publish `APP_ID` as the window's Wayland `app_id` and
    # as the identity it gives the XDG portal. Two things fail without it:
    #
    #   * a tiling compositor cannot match the window with a `window-rule`, so this frameless
    #     utility window is TILED and cannot be made to float. niri is such a compositor.
    #   * the XDG portal refuses every call: `CreateSession` for the `GlobalShortcuts` hotkey
    #     answers "An app id is required".
    #
    # # Why it cannot go after `QApplication(...)`
    #
    # Qt's platform plugin registers with the portal DURING application construction. Setting the
    # name afterwards is too late: the plugin has already associated the connection, and the portal
    # then reports the contradictory pair measured on Arch + niri -
    #
    #     Registry.Register -> "Connection already associated with an application ID"
    #     CreateSession     -> "An app id is required"
    #
    # i.e. something is associated, but not an app id the portal accepts. Moving this call before
    # construction makes `CreateSession` succeed outright.
    #
    # The `.desktop` file named after this id must also be installed, or the portal reports
    # "App info not found for 'gifmanager'". `packaging/gifmanager.desktop` is that file and
    # `scripts/install-desktop-entry.sh` installs it.
    #
    # Harmless on Windows and macOS, where the desktop file name is unused.
    # 在应用对象存在"之前"声明应用 id，而这个顺序正是要点。
    #
    # `setDesktopFileName` 让 Qt 把 `APP_ID` 发布为窗口的 Wayland `app_id`，以及它交给 XDG 门户的
    # 身份。没有它会有两处失败：
    #
    #   * 平铺合成器无法用 `window-rule` 匹配该窗口，于是这个无边框工具窗口会被"平铺"而无法悬浮。
    #     niri 就是这样的合成器。
    #   * XDG 门户拒绝每一次调用：为 `GlobalShortcuts` 热键发起的 `CreateSession` 回答
    #     "An app id is required"。
    #
    # # 为什么不能放在 `QApplication(...)` 之后
    #
    # Qt 的平台插件在应用构造"期间"就向门户注册。之后再设置名称已经太晚：插件已经关联了该连接，而
    # 门户随后报告在 Arch + niri 上实测到的那对矛盾——
    #
    #     Registry.Register -> "Connection already associated with an application ID"
    #     CreateSession     -> "An app id is required"
    #
    # 即：有东西被关联了，但不是门户接受的 app id。把本调用移到构造之前，`CreateSession` 直接成功。
    #
    # 还必须安装以该 id 命名的 `.desktop` 文件，否则门户报告
    # "App info not found for 'gifmanager'"。`packaging/gifmanager.desktop` 就是那个文件，而
    # `scripts/install-desktop-entry.sh` 负责安装它。
    #
    # 在 Windows 与 macOS 上无害，那里桌面文件名不被使用。
    QApplication.setDesktopFileName(APP_ID)

    app = QApplication.instance()
    if app is not None:
        # An existing instance is reused rather than replaced, because creating a second
        # one aborts the process — Qt allows exactly one application object per process.
        # 已有实例会被复用而不是替换，因为创建第二个会中止进程——Qt 每进程只允许一个应用对象。
        return app
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setApplicationVersion(__version__)

    # Load the bundled fonts BEFORE the application font is chosen.
    #
    # `addApplicationFont` only affects families resolved afterwards, and `app.setFont` captures the
    # family immediately - so registering after this point would leave the application font pointing
    # at the system face while every QML item that names the family explicitly got the bundled one.
    # The visible symptom is a window whose text is one font and whose controls are another.
    # 在选应用字体"之前"加载随包字体。
    #
    # `addApplicationFont` 只影响之后解析的字族，而 `app.setFont` 会立即捕获字族——因此在这一点之后
    # 注册，会让应用字体仍指向系统字面，而每个显式命名该字族的 QML 元素拿到随包字体。可见的症状是一个
    # 窗口里文字是一种字体、控件是另一种。
    from gifmanager.frontend.qml.services import register_bundled_fonts

    fonts_ok, font_families, fonts_reason = register_bundled_fonts()
    if not fonts_ok:
        # Not fatal: the platform fallback list still names working families. Logged because "the
        # font I shipped is not being used" is otherwise indistinguishable from "it is".
        # 不致命：平台回退列表仍然列出了可用的字族。记录是因为"我随包的字体没被用上"否则无法与
        # "用上了"区分。
        log.warning("fonts: the bundled font is not in use (%s); falling back to the "
                    "system family", fonts_reason)

    families = interface_font_families()
    # Prefer what Qt actually registered over the name this module asked for: if the bundled family
    # registered under a different name, naming the requested one would silently fall back.
    # 优先用 Qt 实际注册的名字而不是本模块请求的名字：若随包字族以别的名字注册，命名请求的那个会静默
    # 回退。
    if font_families:
        families = list(font_families) + [f for f in families if f not in font_families]
    font = QFont()
    font.setFamilies(list(families))
    font.setPointSize(BASE_FONT_POINT_SIZE)
    app.setFont(font)
    log.info("fonts: application font families=%s", list(families)[:3])
    return app


def interface_font_families():
    # Font families tried in order, per platform convention.
    #
    # Qt falls back automatically, but naming the right family per system is what keeps
    # CJK glyph metrics consistent — and those metrics feed the text-card height
    # calculation, so a wrong family shows up as clipped names rather than as a missing
    # glyph.
    # 按平台惯例依次尝试的字体族。
    #
    # Qt 会自动回退，但为各系统指定正确的字体族才能保证中日韩字形的度量一致——而那些度量会影响
    # 文字卡片高度计算，因此选错字体族会表现为名称被裁切，而不是缺字形。
    from gifmanager.frontend.qml.theme import families_for
    from gifmanager.frontend.qml.services import platform_key

    return families_for(platform_key())


def run(argv=None):
    # Build everything and enter the Qt event loop. Returns the exit code.
    #
    # This is the whole bootstrap, in the same order the Qt Widgets shell uses, because
    # the ORDER is load-bearing:
    #
    #   1. logging first, so an early failure is recorded;
    #   2. the application object, because the single-instance notice needs one;
    #   3. the single-instance check, BEFORE the database is opened — two processes writing
    #      one SQLite file is the failure this prevents;
    #   4. the backend, then the interface.
    #
    # The first version of this launcher called `run(adapter)` with an adapter it never
    # built, so the shipped `apps/gifmanager_qml.py` could not start at all: it raised
    # "a QGuiApplication must exist". The bug was invisible to every test because the tests
    # build their own `QApplication` and call `create_engine` directly, so nothing
    # exercised the real entry point.
    #
    # 构建一切并进入 Qt 事件循环。返回退出码。
    #
    # 这是完整的引导过程，顺序与 Qt Widgets 外壳一致，因为"顺序"是承重的：
    #
    #   1. 先日志，使早期失败被记录；
    #   2. 应用对象，因为单实例提示需要一个；
    #   3. 单实例检查，在打开数据库"之前"——两个进程写同一个 SQLite 文件正是它要防止的失败；
    #   4. 后端，然后是界面。
    #
    # 本启动器的第一个版本用 `run(adapter)` 调用，却从未构建那个 adapter，因此随包的
    # `apps/gifmanager_qml.py` 完全无法启动：它抛 "a QGuiApplication must exist"。这个缺陷
    # 对每个测试都不可见，因为测试自行构建 `QApplication` 并直接调用 `create_engine`，因此
    # 没有任何东西演练过真实入口。
    logging_setup.init_logger()
    logging_setup.install_excepthook()
    logging_setup.install_thread_excepthook()
    log.info("=== %s %s starting (QML) ===", APP_NAME, __version__)

    app = build_application(argv)

    # A command to forward to the running instance, when this launch is only a messenger.
    #
    # # Why a second launch is a legitimate command channel
    #
    # On Wayland the compositor owns global shortcuts, and the documented way for a user to bind
    # one is a rule that RUNS A COMMAND. The command cannot start a second copy of the application
    # - that would fight over the database, which is what the single-instance check prevents - so
    # it sends a one-word command to the copy that is already running. niri's own key bindings work
    # this way, and this is the only global-shortcut route available here: the X11 grab needs X11,
    # and the XDG `GlobalShortcuts` portal cannot be driven from PySide6 because `BindShortcuts`
    # takes an `a(sa{sv})` argument that PySide6 has no way to construct.
    # 当本次启动只是一个信使时，转发给运行中实例的命令。
    #
    # # 为什么第二次启动是合法的命令通道
    #
    # 在 Wayland 上合成器拥有全局快捷键，而用户绑定一个的既定方式是"运行一条命令"的规则。该命令
    # 不能启动应用的第二份拷贝——那会争抢数据库，而单实例检查正是要防止它——因此它向已在运行的那一份
    # 发送一个单词的命令。niri 自身的键绑定就是这样工作的，而这是此处唯一可用的全局快捷键路径：
    # X11 抓取需要 X11，而 XDG `GlobalShortcuts` 门户无法从 PySide6 驱动，因为 `BindShortcuts`
    # 需要 `as(sa{sv})` 参数而 PySide6 无法构造它。
    forward = _forwarded_command(argv)

    # Before any real work: a second launch must not open the database.
    # 任何实际工作之前：第二次启动不得打开数据库。
    service = single_instance_service()
    acquired, handle = service.acquire(APP_NAME)
    if not acquired:
        log.info("another instance is already running")
        if forward:
            # Ask the running copy to act, then leave without a window or a dialog: this process
            # existed only to deliver one word.
            # 请运行中的那一份行动，然后不留窗口、不弹对话框地退出：本进程只为投递一个单词而存在。
            delivered = service.notify(APP_NAME, forward)
            if delivered:
                log.info("forwarded %r to the running instance", forward)
                return 0
            log.warning("could not reach the running instance to send %r", forward)
            return 1
        # A dialog rather than a log line, because a silent exit looks like a crash to
        # someone who double-clicked the launcher.
        # 用对话框而不是日志行，因为对双击了启动器的人来说，静默退出看起来像崩溃。
        show_already_running()
        return 0

    backend = None
    try:
        backend = create_backend()
        adapter = BackendAdapter(backend)
        exit_code = run_with(adapter, app, command_handle=handle)
    finally:
        # Ordered teardown, innermost first: the interface releases its threads and the
        # platform registrations, the backend closes the database, then the instance handle
        # is released.
        # 有序退出，由内向外：界面释放线程与平台注册，后端关闭数据库，随后释放实例句柄。
        if backend is not None:
            try:
                backend.close()
            except Exception:
                log.exception("shutdown: backend close failed")
        try:
            service.release(handle)
        except Exception:
            log.exception("shutdown: instance release failed")
        log.info("=== %s QML shell exited with %s ===", APP_NAME, exit_code)
    return exit_code


def _forwarded_command(argv):
    # The single-instance command this launch should deliver, or "" when it is a normal start.
    #
    # Deliberately a tiny hand-written parser rather than `argparse`: Qt also receives `argv`, and
    # an `argparse` pass that consumed or rejected Qt's own switches (`-platform`,
    # `-style`, `--` separators) would break the toolkit's documented options. Only the four
    # switches this application defines are looked for, and everything else is left alone.
    #
    # 本次启动应投递的单实例命令；正常启动时为空字符串。
    #
    # 刻意用手写的小解析器而不是 `argparse`：Qt 也会收到 `argv`，而一次消费或拒绝 Qt 自身开关
    #（`-platform`、`-style`、`--` 分隔符）的 `argparse` 处理会破坏工具包的既定选项。只查找本应用
    # 定义的四个开关，其余一律不动。
    arguments = list(argv if argv is not None else sys.argv[1:])
    for flag, command in (
        ("--toggle", "toggle"),
        ("--show", "show"),
        ("--hide", "hide"),
        ("--quit", "quit"),
    ):
        if flag in arguments:
            return command
    return ""


def show_already_running():
    # Tell the user, in their language, that the application is already running, using a
    # QML window.
    #
    # # Why not a `QMessageBox`
    #
    # The first version used one, and it CRASHED:
    #
    #     QWidget: Cannot create a QWidget without QApplication
    #
    # A `QMessageBox` is a `QWidget`, and a `QWidget` needs a `QApplication` — but this
    # front-end builds a `QGuiApplication`, which is the correct base for a QML interface
    # and deliberately does NOT include the widget stack. So the notice itself aborted the
    # process, which is the worst possible outcome for a message whose entire purpose is to
    # say "already running": launching a second copy killed the second copy instead of
    # explaining anything, and the exit looked like a crash rather than a refusal.
    #
    # # Why QML rather than swapping in a QApplication
    #
    # Building a `QApplication` would pull the whole widget stack into a QML process to
    # serve a path that only runs when the user double-launches. A QML window is already
    # the technology this front-end uses, so it needs no new dependency at all.
    #
    # # Failure is contained
    #
    # If the engine cannot be created the notice is skipped with a log line rather than
    # raised: a second launch must exit cleanly even when nothing can be shown.
    # 用 QML 窗口告诉用户应用已在运行。
    #
    # # 为什么不用 `QMessageBox`
    #
    # 第一个版本用了它，并且"崩溃"了：
    #
    #     QWidget: Cannot create a QWidget without QApplication
    #
    # `QMessageBox` 是 `QWidget`，而 `QWidget` 需要 `QApplication`——但本前端构建的是
    # `QGuiApplication`，那是 QML 界面的正确基类，且刻意"不"包含控件栈。于是这条提示本身
    # 中止了进程，而这对一条全部意义在于说"已在运行"的消息来说是最糟的结果：启动第二份反而
    # 杀掉了第二份，而不是解释任何事，且退出看起来像崩溃而不是一次拒绝。
    #
    # # 为什么用 QML 而不是换成一个 QApplication
    #
    # 构建 `QApplication` 会把整个控件栈拉进一个 QML 进程，只为服务一条仅在用户重复启动时
    # 才跑的路径。QML 窗口本就是本前端使用的技术，因此完全不需要新依赖。
    #
    # # 失败被限制住
    #
    # 若引擎无法创建，提示会被跳过并记一行日志而不是抛出：第二次启动必须干净退出，即使什么都
    # 显示不出来。
    from gifmanager.core import lang

    title = lang.tr("already_running_title")
    message = lang.tr("already_running_msg")
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtQml import QQmlApplicationEngine

        # Inline because it is four lines of interface and a separate `.qml` file would be
        # a file to find, ship and keep translated for one window.
        # 内联，因为它是四行界面，而单独的 `.qml` 文件会变成为了一个窗口而需要寻找、打包并保持
        # 翻译的文件。
        document = f'''
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {{
    width: 380
    height: 150
    visible: true
    title: {title!r}
    color: theme ? theme.surface : "#252525"

    ColumnLayout {{
        anchors.fill: parent
        anchors.margins: 18
        spacing: 14

        Label {{
            Layout.fillWidth: true
            text: {message!r}
            color: theme ? theme.text : "#E0E0E0"
            wrapMode: Text.WordWrap
            font.pixelSize: 13
        }}

        Item {{ Layout.fillHeight: true }}

        Button {{
            Layout.alignment: Qt.AlignRight
            text: {lang.tr("ok")!r}
            onClicked: Qt.quit()
        }}
    }}
}}
'''
        engine = QQmlApplicationEngine()
        # A real `ThemeBridge`, constructed normally: the notice reads `theme.surface`,
        # `theme.text` and so on, and a hand-built stand-in would be a second place for the
        # palette to be wrong. It takes the stored theme when a settings object is
        # available and the built-in dark palette otherwise, which is why it needs no
        # backend to exist.
        # 一个"真实"的 `ThemeBridge`，正常构造：该提示读取 `theme.surface`、`theme.text` 等，
        # 而手工拼凑的替身会成为调色板可能出错的第二个地方。有设置对象时它取已存储的主题，否则用
        # 内置深色调色板，因此它不需要后端存在。
        from gifmanager.frontend.qml.services import platform_key
        from gifmanager.frontend.qml.theme import ThemeBridge

        theme = ThemeBridge(settings=None, platform_key=platform_key())
        engine._dsh_theme = theme
        engine._dsh_context = engine.rootContext()
        engine._dsh_context.setContextProperty("theme", theme)

        engine.loadData(document.encode("utf-8"), QUrl("qrc:/already_running.qml"))
        if not engine.rootObjects():
            log.warning("qml: the already-running notice did not load")
            return
        app = QGuiApplication.instance()
        if app is not None:
            app.exec()
        del engine
    except Exception:
        # A message that cannot be shown must not become a crash.
        # 无法显示的提示不得变成崩溃。
        log.exception("qml: cannot show the already-running notice")


def run_with(adapter, app=None, strict=None, command_handle=None):
    # Load the QML interface into an EXISTING application and enter the event loop.
    #
    # Split from `run` because the two have different contracts: `run` owns the process
    # (logging, single instance, teardown) while this owns only the interface. A test that
    # has already built an application calls this one.
    #
    # `command_handle` is the single-instance handle, and supplying it turns the process into a
    # command server: "toggle", "show", "hide" and "quit" sent by a later launch are dispatched to
    # the interface. That is how a Wayland compositor key binding reaches a running instance, and
    # it exists because neither the X11 grab nor the XDG `GlobalShortcuts` portal works on
    # Wayland.
    # 把 QML 界面加载进"已有"应用并进入事件循环。
    #
    # 与 `run` 分开是因为两者契约不同：`run` 拥有进程（日志、单实例、退出清理），而本函数只拥有
    # 界面。已经构建了应用的测试调用这一个。
    #
    # `command_handle` 是单实例句柄，传入它会把本进程变成命令服务器：后一次启动发送的 "toggle"、
    # "show"、"hide" 与 "quit" 会被分发给界面。这正是 Wayland 合成器键绑定到达运行中实例的方式，
    # 它存在的原因是 X11 抓取与 XDG `GlobalShortcuts` 门户在 Wayland 上都不可用。
    app = app or QGuiApplication.instance()
    if app is None:
        raise RuntimeError(
            "run_with requires a QGuiApplication; call `run` for the full bootstrap / "
            "run_with 需要 QGuiApplication；完整引导请调用 `run`")

    if strict is None:
        strict = str(os.environ.get(STRICT_ENV, "")).strip().lower() in (
            "1", "true", "yes", "on")

    engine, bridge, theme, warnings = create_engine(adapter, strict=strict)
    # The palette and the window title depend on the stored theme, so they are applied once
    # the engine exists rather than before it.
    # 调色板与窗口标题依赖已存储的主题，因此在引擎存在之后而非之前应用。
    theme.set_theme(adapter.settings.theme)

    log.info("qml: interface loaded (%s warning(s), %s root object(s))",
             len(warnings), len(engine.rootObjects()))

    poller = None
    if command_handle is not None:
        poller = _start_command_poller(bridge, command_handle)

    try:
        return app.exec()
    finally:
        if poller is not None:
            poller.stop()
        bridge.detach()
        del engine


def _start_command_poller(bridge, handle):
    # Poll the single-instance socket and dispatch what arrives. Returns the running timer.
    #
    # # Why polling rather than a notifier
    #
    # `QSocketNotifier` would be the event-driven answer, but the handle belongs to the PLATFORM
    # layer, which must not import Qt - so the front-end cannot wrap its descriptor in a Qt
    # object without either leaking a raw fd through the layer boundary or duplicating the socket
    # code. A 250 ms poll of a non-blocking `accept` loop is cheap (one failed `accept` when idle)
    # and keeps the layers intact.
    #
    # 轮询单实例套接字并分发到达的内容。返回运行中的定时器。
    #
    # # 为什么用轮询而不是通知器
    #
    # `QSocketNotifier` 才是事件驱动的答案，但句柄属于"平台"层，而该层不得导入 Qt——因此前端
    # 无法把它的描述符包进 Qt 对象，除非要么让裸 fd 穿过层边界、要么复制套接字代码。对非阻塞
    # `accept` 循环做 250 毫秒轮询很便宜（空闲时只有一次失败的 `accept`），且保持分层完整。
    from PySide6.QtCore import QTimer

    drain = getattr(handle, "drain", None)
    if not callable(drain):
        log.warning("single-instance: the handle cannot deliver commands; "
                    "a compositor key binding will not reach this instance")
        return None

    def poll():
        for command in drain():
            if command == "toggle":
                bridge.toggleWindowRequested.emit()
            elif command == "show":
                bridge.showWindowRequested.emit()
            elif command == "hide":
                bridge.hideWindowRequested.emit()
            elif command == "quit":
                bridge.quit()
            else:
                log.warning("single-instance: ignoring unknown command %r", command)

    timer = QTimer()
    timer.setInterval(250)
    timer.timeout.connect(poll)
    timer.start()
    log.info("single-instance: listening for commands (toggle show hide quit)")
    return timer


__all__ = [
    "BASE_FONT_POINT_SIZE",
    "REQUIRED_STYLE",
    "STRICT_ENV",
    "apply_controls_style",
    "build_application",
    "configure_engine",
    "controls_conf",
    "create_engine",
    "interface_font_families",
    "qml_entry",
    "qml_root",
    "run",
    "run_with",
    "show_already_running",
]
