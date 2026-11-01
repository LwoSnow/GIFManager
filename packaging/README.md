# The native GIF decoder: build it, or run without it.
# 本地 GIF 解码器：构建它，或者不带它运行。
#
# WHY IT IS OPTIONAL / 为什么它是可选的
#
# `frontend/qt/animation.py` decodes GIF frames on a worker thread so playback is
# only a pixmap swap. Without this library the widget falls back to `QMovie`,
# which decodes on the GUI thread: correct, but a screen full of animated
# stickers scrolls badly. Nothing breaks — the feature is a performance one.
#
# `frontend/qt/animation.py` 在工作线程解码 GIF 帧，使播放只是切换 pixmap。缺少
# 本库时控件回退到 `QMovie`，它在界面线程解码：功能正确，但满屏动图滚动会卡。
# 什么都不会坏——这项功能属于性能优化。
#
# THE C ABI / C 接口
#
# The library must export exactly these four symbols; `animation.py` binds them and
# `resources/gifdec.c` already implements them:
# 本库必须恰好导出下面四个符号；`animation.py` 绑定它们，而 `resources/gifdec.c`
# 已实现它们：
#
#     void *gif_open(const char *path, int *w, int *h, int *frames);
#     int   gif_frame_delay_ms(void *handle, int index);
#     int   gif_frame(void *handle, int index, uint8_t *rgba_out);
#     void  gif_close(void *handle);
#
# BUILD / 构建
#
#   Windows (MinGW-w64):  scripts/build-gifdec.ps1
#   Windows (MSVC):       scripts/build-gifdec.ps1 -Toolchain msvc
#   macOS:                scripts/build-gifdec.sh
#   Linux:                scripts/build-gifdec.sh
#
# The output lands in `resources/`, which the PyInstaller spec and
# `animation.library_path()` both search.
# 产物落在 `resources/`，PyInstaller spec 与 `animation.library_path()` 都会搜索
# 该目录。
#
# The C source itself is NOT copied into this repository yet: it lived at
# `app/utils/gifdec.c` in the previous release and is plain portable C with no
# Windows dependency, so porting it is a copy plus a build script. Until then,
# macOS and Linux run the `QMovie` fallback.
# C 源码尚未复制进本仓库：它在上一版本位于 `app/utils/gifdec.c`，是不依赖 Windows
# 的普通可移植 C，因此移植它只需复制加一个构建脚本。在那之前，macOS 与 Linux 运行
# `QMovie` 回退路径。
