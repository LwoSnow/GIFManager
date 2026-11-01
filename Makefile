# GIFManager Next — development entry points
# GIFManager Next——开发入口
#
# Every target is a thin wrapper over a documented command, so a contributor
# without `make` loses nothing by running the command directly.
# 每个目标都是对一条已记录命令的薄封装，因此没有 `make` 的贡献者直接运行那条命令不会
# 失去任何能力。

# `$(OS)` is set to `Windows_NT` by every Windows shell and is unset elsewhere, so
# the two native-build scripts are selected without `&&`/`||` chaining, which would
# run the second recipe on any failure of the first.
# 每个 Windows shell 都会把 `$(OS)` 设为 `Windows_NT`，其他平台则不设，因此无需
# `&&`/`||` 串联即可选择两个原生构建脚本——那种写法会在第一条命令任何失败时误跑第二条。
ifeq ($(OS),Windows_NT)
NATIVE_BUILD = powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build-native.ps1
else
NATIVE_BUILD = sh scripts/build-native.sh
endif

# The interpreter used by the checks. Override for a virtualenv:
#   make test PYTHON=.venv/Scripts/python.exe
# 检查所用的解释器。使用虚拟环境时覆盖：
#   make test PYTHON=.venv/Scripts/python.exe
PYTHON ?= python

# Offscreen Qt is what makes an automated check of the shell possible without a
# display, so the test targets set it rather than requiring a desktop session.
# 离屏 Qt 让外壳无需显示器即可被自动检查，因此测试目标会设置它，而不是要求桌面会话。
QT_OFFSCREEN = QT_QPA_PLATFORM=offscreen

.PHONY: help
help:
	@echo "GIFManager Next - available make targets / 可用的 make 目标"
	@echo ""
	@echo "  make check      Run every check: env, layers, style, language, tests"
	@echo "  make env        Verify the interpreter matches the pinned wheels"
	@echo "  make test       Run the test suite (offscreen Qt)"
	@echo "  make layers     Verify the layering rule"
	@echo "  make style      Verify line width and bilingual comments"
	@echo "  make lang       Verify both language files have the same keys"
	@echo "  make smoke      Run all fifteen smoke checks"
	@echo "  make probe-services"
	@echo "                  Check the system tray and global hotkey on a real desktop"
	@echo "  make run        Launch the Qt Widgets shell from the source tree"
	@echo "  make run-qml    Launch the QML shell from the source tree"
	@echo "  make qml-check  Probe the QML runtime, then smoke-load the interface"
	@echo "  make native     Build the Rust image pipeline (optional)"
	@echo "  make bench      Measure the native pipeline against the Qt path"
	@echo "  make build      Build the retired QtWidgets bundle (GIFManagerNext.spec)"
	@echo "  make build-qml  Build the shipped QML bundle (the one CI packages)"
	@echo "  make clean      Remove bytecode, build output and dist"
	@echo ""
	@echo "  The native pipeline is OPTIONAL: without it the application runs and"
	@echo "  reports the slower path through images.describe()."
	@echo "  原生管线是可选的：没有它程序照常运行，并通过 images.describe()"
	@echo "  报告当前走的是较慢路径。"

.PHONY: check
check: env layers style lang batch test
	@echo "all checks passed / 全部检查通过"

# The batch files, because cmd.exe reads them in the console's ANSI code page and needs
# CRLF: a UTF-8 or LF-only .bat is unrunnable while looking correct in an editor.
# 批处理文件，因为 cmd.exe 以控制台 ANSI 代码页读取它们且需要 CRLF：一个 UTF-8 或只有 LF 的
# .bat 在编辑器里看起来正常却无法运行。
.PHONY: batch
batch:
	$(PYTHON) tools/check_batch_encoding.py --quiet

# The environment FIRST, because a mismatched interpreter breaks every later check with a
# message about a missing submodule rather than about the interpreter.
# 环境检查放在"最前"，因为解释器不匹配会用"缺少子模块"的消息弄坏后面每一项检查，而不是
# 报告解释器本身。
.PHONY: env
env:
	$(PYTHON) tools/check_environment.py

.PHONY: lang
lang:
	$(PYTHON) tools/sync_language_keys.py --quiet

.PHONY: test
test:
	$(QT_OFFSCREEN) $(PYTHON) -m unittest discover -s tests -t . -p "test_*.py"

.PHONY: layers
layers:
	$(PYTHON) tools/check_layers.py

.PHONY: style
style:
	$(PYTHON) tools/check_style.py gifmanager apps tests tools

.PHONY: smoke
smoke:
	$(PYTHON) tests/smoke_core.py
	$(QT_OFFSCREEN) $(PYTHON) tests/smoke_qt.py
	$(QT_OFFSCREEN) $(PYTHON) tests/smoke_launcher.py
	$(QT_OFFSCREEN) $(PYTHON) tests/smoke_qml_launcher.py
	$(QT_OFFSCREEN) $(PYTHON) tests/smoke_shell.py
	$(QT_OFFSCREEN) $(PYTHON) tests/smoke_native.py
	$(QT_OFFSCREEN) $(PYTHON) tests/smoke_native_contract.py
	$(QT_OFFSCREEN) $(PYTHON) tests/smoke_settings_cards.py
	$(QT_OFFSCREEN) $(PYTHON) tests/smoke_qml.py
	$(QT_OFFSCREEN) $(PYTHON) tests/smoke_navigation.py
	$(QT_OFFSCREEN) $(PYTHON) tests/smoke_import.py
	$(QT_OFFSCREEN) $(PYTHON) tests/smoke_import_target.py
	$(QT_OFFSCREEN) $(PYTHON) tests/profile_animation.py
	$(QT_OFFSCREEN) $(PYTHON) tests/smoke_playback.py
	$(QT_OFFSCREEN) $(PYTHON) tests/smoke_animation.py
	$(QT_OFFSCREEN) $(PYTHON) tests/smoke_animation_pixels.py
	$(QT_OFFSCREEN) $(PYTHON) tests/smoke_wayland.py
	$(QT_OFFSCREEN) $(PYTHON) tests/smoke_single_instance.py
	$(QT_OFFSCREEN) $(PYTHON) tests/smoke_ui_tokens.py
	$(QT_OFFSCREEN) $(PYTHON) tests/smoke_features.py

# Platform surfaces that only exist on a real desktop session: the system tray and
# the global hotkey. Deliberately NOT part of `smoke`, because the offscreen platform
# has no tray and this probe would be meaningless — it must run where a tray can
# exist, and it reports the reason rather than a bare pass when one does not.
# 只存在于真实桌面会话的平台界面：系统托盘与全局热键。刻意"不"属于 `smoke`，因为离屏平台
# 没有托盘、该探测将毫无意义——它必须在托盘可能存在的地方运行，而在没有托盘时报告原因而不是
# 一个光秃秃的通过。
.PHONY: probe-services
probe-services:
	$(PYTHON) tests/probe_services.py

# Build the Rust image pipeline. Optional: the application runs without it, and
# `images.describe()` always reports which path is live.
# 构建 Rust 图像管线。可选：没有它程序照常运行，`images.describe()` 始终报告当前
# 生效的是哪条路径。
.PHONY: native
native:
	$(NATIVE_BUILD)

# Measure the native pipeline against the pure-Qt path. Prints the ratio, and says
# plainly where the native path is NOT a win.
# 测量原生管线相对于纯 Qt 路径的表现。打印比值，并如实说明原生路径不占优之处。
.PHONY: bench
bench:
	$(QT_OFFSCREEN) $(PYTHON) tests/bench_native.py

.PHONY: run
run:
	$(PYTHON) apps/gifmanager_qt.py

# Launch the QML interface. Kept separate from `run` so the two front-ends can be
# compared against the same data directory without editing anything between runs.
# 启动 QML 界面。与 `run` 分开，使两个前端能在同一数据目录上对比，运行之间无需改动任何
# 东西。
.PHONY: run-qml
run-qml:
	$(PYTHON) apps/gifmanager_qml.py

# Report what the QML engine and the packed-in Qt build actually provide, before
# blaming the interface for a blank window.
# 报告 QML 引擎与所装 Qt 构建实际提供的能力，避免为一个空白窗口错怪界面。
.PHONY: qml-check
qml-check:
	$(QT_OFFSCREEN) $(PYTHON) tests/probe_qml.py
	$(QT_OFFSCREEN) $(PYTHON) tests/smoke_qml.py

.PHONY: build
build:
	$(PYTHON) -m PyInstaller --noconfirm --clean packaging/GIFManagerNext.spec

# The QML front-end — the interface this project ships, and the one the release workflow packages.
#
# `build` above still builds the retired QtWidgets interface with `GIFManagerNext.spec`, which EXCLUDES
# Qt Quick; running that one and expecting the QML window is the mistake this target exists to avoid.
# QML 前端——本项目发布的界面，也是发布 workflow 打包的那个。
#
# 上面的 `build` 仍用 `GIFManagerNext.spec` 构建已退役的 QtWidgets 界面，而该 spec "排除"了 Qt Quick；
# 跑那个却期待 QML 窗口，正是本目标要避免的混淆。
.PHONY: build-qml
build-qml:
	$(PYTHON) -m PyInstaller --noconfirm --clean packaging/GIFManagerQml.spec

.PHONY: clean
clean:
	$(PYTHON) -c "import pathlib, shutil; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]"
	$(PYTHON) -c "import shutil; shutil.rmtree('build', ignore_errors=True); shutil.rmtree('dist', ignore_errors=True)"
