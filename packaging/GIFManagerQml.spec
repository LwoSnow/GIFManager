# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for GIFManager Next — the QML front-end (onedir).
#
# Usage / 用法:
#     pyinstaller --noconfirm --clean packaging/GIFManagerQml.spec
# Output / 输出:
#     dist/GIFManager/GIFManager.exe   (or `GIFManager/GIFManager` on Linux/macOS)
#     dist/GIFManager/_internal/...
#
# # Two specs, and this is the one that ships
#
# `GIFManagerNext.spec` builds the OLD QtWidgets interface and therefore EXCLUDES `QtQuick`/`QtQml`.
# Building that one and calling it "the application" would ship a front-end this project no longer uses.
# This spec targets `apps/gifmanager_qml.py`, the entry point `python -m gifmanager` runs, so it keeps
# the Qt Quick stack and packs the `.qml` files themselves.
#
# 两个 spec，而"这个"才是发布用的。
#
# `GIFManagerNext.spec` 构建的是旧的 QtWidgets 界面，因此"排除"了 `QtQuick`/`QtQml`。用那个构建并
# 称之为"本程序"，等于发布一个本项目已不再使用的前端。本 spec 面向 `apps/gifmanager_qml.py`——也就是
# `python -m gifmanager` 运行的入口——因此保留 Qt Quick 栈，并打包 `.qml` 文件本身。
#
# # What has to be listed by hand
#
# PyInstaller's PySide6 hook collects the Qt libraries and plugins, but it knows nothing about this
# project's own data:
#
#   * `gifmanager/frontend/qml/**` — the interface itself. Missing it produces a bundle that starts and
#     then fails to load `Main.qml`.
#   * `resources/language` — translations, read through `core.paths.language_dir()`.
#   * `resources/icons` — the tray and window icons.
#   * `resources/fonts` — the bundled HarmonyOS Sans faces. Without them the application still runs, but
#     it falls back to whatever the machine has, which is the platform-dependent metric drift the bundled
#     family exists to remove.
#
# 必须手工列出的内容。
#
# PyInstaller 的 PySide6 钩子会收集 Qt 库与插件，但它对本项目自身的数据一无所知：
#
#   * `gifmanager/frontend/qml/**`——界面本身。漏掉它会得到一个能启动、随后加载 `Main.qml` 失败的包。
#   * `resources/language`——翻译，经 `core.paths.language_dir()` 读取。
#   * `resources/icons`——托盘与窗口图标。
#   * `resources/fonts`——随包的 HarmonyOS Sans 字面。缺了它程序仍能运行，但会回退到机器上恰好有的
#     字体，而那正是随包字族要消除的依赖平台的度量漂移。

import os
import sys

# The spec lives in `packaging/`, so the project root is one level up. `SPECPATH` rather than the working
# directory keeps the build independent of where it is invoked from.
# 本 spec 位于 `packaging/`，因此项目根在上一级。用 `SPECPATH` 而非工作目录，使构建与调用位置无关。
ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))


def tree(relative):
    # (`source_dir`, `destination_dir`) for a directory that must be present, or None when absent.
    #
    # The OPTIONAL assets go through this and are allowed to be missing, so a checkout without a compiled
    # GIF decoder or a bundled ffmpeg still builds.
    # (源目录, 目标目录)；目录不存在时返回 None。
    #
    # "可选"资源经此处理并允许缺失，使未编译 GIF 解码器或未附 ffmpeg 的检出仍能完成构建。
    source = os.path.join(ROOT, relative)
    if not os.path.isdir(source):
        return None
    return (source, relative)


def file(relative):
    source = os.path.join(ROOT, relative)
    if not os.path.isfile(source):
        return None
    return (source, os.path.dirname(relative) or ".")


datas = []

# The interface. `core.paths.package_dir()` resolves to the directory CONTAINING the `gifmanager`
# package, so the destination keeps the package-relative path.
# 界面。`core.paths.package_dir()` 解析为"包含" `gifmanager` 包的那个目录，因此目标保留包内相对路径。
qml_source = os.path.join(ROOT, "gifmanager", "frontend", "qml")
if not os.path.isdir(qml_source):
    raise SystemExit("GIFManagerQml.spec: gifmanager/frontend/qml is missing; nothing to ship")
datas.append((qml_source, os.path.join("gifmanager", "frontend", "qml")))

# Required resources. `resources_dir()` looks for `_internal/resources` once frozen.
# 必需资源。冻结后 `resources_dir()` 会在 `_internal/resources` 查找。
for name in ("language", "icons", "fonts"):
    entry = tree(os.path.join("resources", name))
    if entry is None:
        raise SystemExit(f"GIFManagerQml.spec: resources/{name} is missing")
    datas.append(entry)

# Optional assets / 可选资源
for name in ("ffmpeg",):
    entry = tree(os.path.join("resources", name))
    if entry is not None:
        datas.append(entry)

binaries = []
for name in ("gifdec.dll", "libgifdec.dylib", "libgifdec.so"):
    source = os.path.join(ROOT, "resources", name)
    if os.path.isfile(source):
        binaries.append((source, "resources"))
for name in ("ffmpeg.exe", "ffmpeg"):
    source = os.path.join(ROOT, "resources", "ffmpeg", name)
    if os.path.isfile(source):
        binaries.append((source, os.path.join("resources", "ffmpeg")))

a = Analysis(
    [os.path.join(ROOT, "apps", "gifmanager_qml.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        # Imported lazily by the platform registry, so static analysis cannot see them; without these the
        # bundle falls back to the generic backend and reports every platform service as unsupported.
        # 由平台注册表惰性导入，静态分析看不到；缺少它们会回退到通用后端并报告所有平台服务不支持。
        "gifmanager.platform.windows",
        "gifmanager.platform.macos",
        "gifmanager.platform.linux",
        # The QML front-end imports these inside functions in places, which PyInstaller can miss.
        # QML 前端在多处于函数内部导入它们，PyInstaller 可能漏掉。
        "gifmanager.frontend.qml.app",
        "gifmanager.frontend.qml.bridge",
        "gifmanager.frontend.qml.animator",
        "gifmanager.frontend.qml.services",
        "gifmanager.frontend.qml.models",
        "gifmanager.frontend.qml.settings_model",
        "gifmanager.frontend.qml.importer",
        "gifmanager.frontend.qml.updates",
        "gifmanager.frontend.qt.widgets.hotkey_capture",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Qt modules this application does not use. Note that `QtQuick`/`QtQml` are deliberately NOT here:
        # they are the front-end.
        # 本程序不使用的 Qt 模块。注意 `QtQuick`/`QtQml` 刻意不在此列：它们就是前端。
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
        "PySide6.QtMultimedia",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtBluetooth",
        "PySide6.QtNfc",
        "PySide6.QtPositioning",
        "PySide6.QtSerialPort",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "tkinter",
        "unittest",
        "pydoc_data",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

# An icon is only meaningful to the Windows bootloader; on the other platforms PyInstaller would warn and
# ignore it. Passing it conditionally keeps the build log honest.
# 图标只对 Windows 引导器有意义；在其他平台上 PyInstaller 会警告并忽略。按条件传入使构建日志保持诚实。
icon_path = os.path.join(ROOT, "resources", "icons", "gifmanager.ico")
icon = icon_path if (sys.platform == "win32" and os.path.isfile(icon_path)) else None

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GIFManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX is a common antivirus trigger / UPX 是常见的杀软误报诱因
    console=False,      # GUI application: no console window / GUI 程序：不弹控制台
    disable_windowed_traceback=False,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="GIFManager",
)
