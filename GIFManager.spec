# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置（onedir 模式）
#
# 用法：pyinstaller --noconfirm --clean GIFManager.spec
# 输出：dist/GIFManager/GIFManager.exe + dist/GIFManager/_internal/...
#
# 说明：
# - onedir 模式：启动快、杀软误报少，便于制作便携 zip。
# - language/ 与 icon.ico 通过 add-data 放进 _internal/，
#   打包后的代码（frozen）会从 _internal 读取这些只读资源。
# - data/（表情数据库与文件）与 logs/ 由代码在运行时创建，
#   打包版会写到 exe 同级目录或用户目录（见 app/models/data_manager.py
#   与 app/models/logger.py 的 frozen 分支），不会打进包内。

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[
        ("app/utils/gifdec.dll", "app/utils"),   # 原生 GIF 解码器 native GIF decoder
    ],
    datas=[
        ("language", "language"),   # 翻译文件 language/*.json -> _internal/language/
        ("icon.ico", "."),          # 应用图标 -> _internal/icon.ico
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    upx=False,
    console=False,          # GUI 应用，不弹出控制台
    icon="icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="GIFManager",
)
