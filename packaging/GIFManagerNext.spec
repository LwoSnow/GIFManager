# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for GIFManager Next (onedir).
#
# Usage / 用法:
#     pyinstaller --noconfirm --clean packaging/GIFManagerNext.spec
# Output / 输出:
#     dist/GIFManager/GIFManager.exe  (or the platform equivalent)
#     dist/GIFManager/_internal/...
#
# Why onedir and not onefile / 为什么用 onedir 而非 onefile:
#   * onefile unpacks the whole bundle into a temp directory on every launch, so
#     startup is slower exactly where it matters most (a tray utility launched at
#     login);
#   * a onefile bundle rewrites itself on disk, which is a common antivirus
#     false-positive trigger.
#   * onefile 每次启动都把整个包解压到临时目录，因此启动更慢——而这对登录时启动的
#     托盘工具恰恰最要命；
#   * onefile 包会在磁盘上重写自身，这是杀软误报的常见诱因。
#
# What goes where / 各部分去向:
#   * `resources/` holds read-only assets (translations, icons, an optional
#     ffmpeg and an optional native GIF decoder). Packaged code reads them
#     through `core.paths.resources_dir()`, which knows the `_internal` layout.
#   * the DATA directory (SQLite database + emoji files) and the log directory
#     are created at runtime by `core.paths`, never packed: they are user data.
#   * `resources/` 存放只读资源（翻译、图标、可选的 ffmpeg 与可选的本地 GIF
#     解码器）。打包后的代码经 `core.paths.resources_dir()` 读取，它知道
#     `_internal` 布局。
#   * 数据目录（SQLite 数据库 + 表情文件）与日志目录由 `core.paths` 在运行时创建，
#     绝不打包：它们属于用户数据。

import os

# The spec lives in `packaging/`, so the project root is one level up. Using
# `SPECPATH` rather than the working directory makes the build independent of
# where it is invoked from.
# 本 spec 位于 `packaging/`，因此项目根在上一级。用 `SPECPATH` 而非工作目录，使
# 构建与调用位置无关。
ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))


def resource_file(relative):
    # (`source`, `destination`) pair, or None when the asset is absent.
    #
    # Every optional asset goes through this helper so a checkout without a
    # compiled GIF decoder or a bundled ffmpeg still builds, instead of failing
    # with a missing-file error that looks like a packaging bug.
    # (`源`, `目标`) 二元组；资源不存在时返回 None。
    #
    # 每个可选资源都经此辅助处理，使未编译 GIF 解码器或未附 ffmpeg 的源码目录仍能
    # 完成构建，而不是以一个看起来像打包 bug 的"文件缺失"错误失败。
    source = os.path.join(ROOT, relative)
    if not os.path.exists(source):
        return None
    return (source, os.path.dirname(relative) or ".")


def optional_resources():
    # Assets that are packaged only when present /
    # 仅在存在时才打包的资源
    candidates = [
        "resources/language",
        "resources/icons",
        # A native decoder for the current platform, whichever name it has.
        # 当前平台的本地解码器，无论叫什么名字。
        "resources/gifdec.dll",
        "resources/libgifdec.dylib",
        "resources/libgifdec.so",
        # ffmpeg is large and licensed separately, so it is never assumed.
        # ffmpeg 体积大且许可独立，因此从不假定其存在。
        "resources/ffmpeg/ffmpeg.exe",
        "resources/ffmpeg/ffmpeg",
    ]
    datas = []
    for relative in candidates:
        entry = resource_file(relative)
        if entry is not None:
            datas.append(entry)
    return datas


# `--add-data` equivalents. `resources` keeps its name so
# `core.paths.resources_dir()` finds it under `_internal`.
# `--add-data` 的等价写法。`resources` 保留其名称，使 `core.paths.resources_dir()`
# 能在 `_internal` 下找到它。
datas = [("resources/language", "resources/language")] if os.path.isdir(
    os.path.join(ROOT, "resources", "language")) else []
datas += optional_resources()

# Deduplicate, keeping the first occurrence, because a directory entry and a
# file inside it can both be listed above.
# 去重并保留首次出现，因为上面可能同时列出一个目录与其中的某个文件。
seen = set()
unique_datas = []
for entry in datas:
    if entry[0] in seen:
        continue
    seen.add(entry[0])
    unique_datas.append(entry)

binaries = []
for name in ("gifdec.dll", "libgifdec.dylib", "libgifdec.so"):
    source = os.path.join(ROOT, "resources", name)
    if os.path.exists(source):
        binaries.append((source, "resources"))

a = Analysis(
    [os.path.join(ROOT, "apps", "gifmanager_qt.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=unique_datas,
    hiddenimports=[
        # Imported lazily by the platform registry, so static analysis cannot
        # see them; without this the bundle would fall back to the generic
        # backend and report every platform service as unsupported.
        # 由平台注册表惰性导入，静态分析看不到它们；缺少这些声明时，打包结果会回退到
        # 通用后端，并把每个平台服务都报告为不支持。
        "gifmanager.platform.windows",
        "gifmanager.platform.macos",
        "gifmanager.platform.linux",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Qt modules this application does not use; excluding them keeps the
        # bundle several hundred megabytes smaller.
        # 本程序不使用的 Qt 模块；排除它们可让包小几百兆。
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQuick",
        "PySide6.QtQml",
        "PySide6.Qt3DCore",
        "PySide6.QtMultimedia",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "tkinter",
        "unittest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GIFManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX compression is a common antivirus trigger / UPX 压缩是常见的杀软误报诱因
    console=False,      # GUI application: no console window / GUI 程序：不弹控制台
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="GIFManager",
)
