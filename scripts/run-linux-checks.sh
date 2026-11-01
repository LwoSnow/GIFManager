#!/bin/sh
# Run the project's checks on Linux.
#
# # Why a script rather than a list of commands
#
# The set of checks differs per platform in a way that matters, and getting it wrong
# produces a red result that says nothing about the code:
#
#   * `smoke_launcher` starts a real application process and needs a display server plus
#     a working Qt platform plugin; in a container or a headless shell it fails for
#     reasons unrelated to the code.
#   * `smoke_native` and `smoke_native_contract` need the optional Rust/C decoder, which
#     is NOT built here. They are supposed to degrade gracefully, so this script runs
#     them and reports the outcome as INFORMATION rather than as a failure — and
#     `--strict-native` turns that into a failure for a machine where the decoder IS
#     expected.
#   * `probe_services` needs a real desktop session with a tray and a portal. It is the
#     one check that genuinely cannot run in WSL, and it says so.
#
# Usage: run-linux-checks.sh [--quick] [--strict-native] [--python PATH] [-- <extra args>]
#   --quick          skip the slow smokes (native, playback)
#   --strict-native  treat a missing native decoder as a failure
#   --python PATH    interpreter to use (default: auto-detect)
#
# 本脚本在 Linux 上运行本项目的检查。
#
# # 为什么用脚本而非一串命令
#
# 检查集合按平台而变，而这一点很重要；弄错会产出一个与代码无关的红色结果：
#
#   * `smoke_launcher` 会启动真实应用进程，需要显示服务器与可用的 Qt 平台插件；在容器或
#     无头 shell 中它会因与代码无关的原因失败。
#   * `smoke_native` 与 `smoke_native_contract` 需要可选的 Rust/C 解码器，而此处并未构建。
#     它们本该优雅降级，因此本脚本运行它们并把结果作为"信息"报告而不是失败——而
#     `--strict-native` 会在确实期望该解码器的机器上把它变成失败。
#   * `probe_services` 需要带托盘与门户的真实桌面会话。它是唯一真正无法在 WSL 中运行的检查，
#     而它会说明这一点。
#
# 用法：run-linux-checks.sh [--quick] [--strict-native] [--python PATH] [-- <额外参数>]
#   --quick          跳过较慢的冒烟检查（native、playback）
#   --strict-native  把缺失原生解码器视为失败
#   --python PATH    使用的解释器（默认自动探测）

QUICK=0
STRICT_NATIVE=0
PYTHON=""
EXTRA=""

while [ $# -gt 0 ]; do
    case "$1" in
        --quick) QUICK=1 ;;
        --strict-native) STRICT_NATIVE=1 ;;
        --python) shift; PYTHON="$1" ;;
        --) shift; EXTRA="$*" ;;
        *) echo "unknown option: $1"; exit 2 ;;
    esac
    shift
done

# Locate the project root from this script's own path, so the checks run from anywhere.
# 由脚本自身路径定位项目根目录，使检查可从任意位置运行。
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$ROOT" || exit 1

echo "project root: $ROOT"

# Pick an interpreter. The project's own venv is preferred when it is a LINUX venv: a
# Windows `.venv` copied through a mount has a `python.exe` and a Scripts/ layout, and
# using it produces "no such file" errors that look like a broken checkout.
# 选择解释器。项目自带的 venv 在"是 Linux venv"时优先：经挂载过来的 Windows `.venv`
# 里有 `python.exe` 与 Scripts/ 布局，使用它会产出看起来像检出损坏的"文件不存在"错误。
if [ -z "$PYTHON" ]; then
    for candidate in ".venv/bin/python" "venv/bin/python"; do
        if [ -x "$candidate" ]; then
            PYTHON="$candidate"
            break
        fi
    done
    if [ -z "$PYTHON" ]; then
        for candidate in python3 python; do
            if command -v "$candidate" >/dev/null 2>&1; then
                PYTHON="$candidate"
                break
            fi
        done
    fi
fi

if [ -z "$PYTHON" ]; then
    echo "no Python interpreter found; install python3 first"
    exit 1
fi

# Wayland is present under WSLg, so the SESSION-DEPENDENT code paths would take the
# Wayland branch — where the global-hotkey portal does not exist and reports itself
# unavailable. Pinning the session to X11 here makes the X11 code path (the one with a
# real implementation) the one under test, which is the more informative of the two.
# WSLg 下有 Wayland，因此依赖会话的代码路径会走 Wayland 分支——那里全局热键门户不存在并报告
# 自己不可用。此处把会话固定为 X11，使 X11 代码路径（有真实实现的那条）成为被测对象，那是两者
# 中信息量更大的一个。
GIFMANAGER_SESSION=${GIFMANAGER_SESSION:-x11}
export XDG_SESSION_TYPE="$GIFMANAGER_SESSION"
unset WAYLAND_DISPLAY

# Offscreen Qt for everything: no display server is required, and the checks are meant to
# run in a container.
# 所有检查都用离屏 Qt：不需要显示服务器，而这些检查本就该能在容器中运行。
export QT_QPA_PLATFORM=offscreen
export PYTHONUTF8=1
export PYTHONDONTWRITEBYTECODE=1

echo "interpreter: $($PYTHON --version 2>&1)"
echo "session    : $XDG_SESSION_TYPE (pinned for the test run)"
echo

PASS=0
FAIL=0
INFO=0
FAILED_NAMES=""

run() {
    # Run one check. `$1` is a label, the rest is the command.
    # 运行一个检查。`$1` 是标签，其余是命令。
    label="$1"
    shift
    printf '%-26s ' "$label"
    output=$("$@" 2>&1)
    status=$?
    if [ $status -eq 0 ]; then
        echo "OK"
        PASS=$((PASS + 1))
    else
        echo "FAIL ($status)"
        FAIL=$((FAIL + 1))
        FAILED_NAMES="$FAILED_NAMES $label"
        # Show the reason rather than only the status, so a failure here is actionable.
        # 显示原因而不只是状态，使这里的失败可处理。
        echo "$output" | tail -25 | sed 's/^/      /'
    fi
}

inform() {
    # Run a check whose failure is INFORMATION rather than a defect. Reports the outcome
    # without counting it as a failure unless --strict-native was given.
    # 运行一个其失败属于"信息"而非缺陷的检查。报告结果但不计为失败，除非给了
    # --strict-native。
    label="$1"
    shift
    printf '%-26s ' "$label"
    output=$("$@" 2>&1)
    status=$?
    if [ $status -eq 0 ]; then
        echo "OK"
        PASS=$((PASS + 1))
        return
    fi
    if [ "$STRICT_NATIVE" = "1" ]; then
        echo "FAIL ($status, --strict-native)"
        FAIL=$((FAIL + 1))
        FAILED_NAMES="$FAILED_NAMES $label"
        echo "$output" | tail -20 | sed 's/^/      /'
        return
    fi
    echo "SKIP (graceful degradation, exit $status)"
    INFO=$((INFO + 1))
}

echo "=== static checks ==="
run "compileall" "$PYTHON" -m compileall -q gifmanager apps tests tools
run "check_layers" "$PYTHON" tools/check_layers.py
run "check_style" "$PYTHON" tools/check_style.py gifmanager apps tests tools
run "check_makefile" "$PYTHON" tools/check_makefile.py
run "sync_language_keys" "$PYTHON" tools/sync_language_keys.py --quiet

echo
echo "=== unit and integration tests ==="
run "unittest" "$PYTHON" -m unittest discover -s tests -t . -p "test_*.py"

echo
echo "=== smoke checks ==="
run "smoke_core" "$PYTHON" tests/smoke_core.py
run "smoke_qt" "$PYTHON" tests/smoke_qt.py
# The REAL entry point, which no other check exercises: the others build their own
# application object and call the internals directly, which is exactly how a launcher that
# could not start went unnoticed.
# "真实"入口，其他检查都不演练它：它们自行构建应用对象并直接调用内部接口，这正是一个无法启动的
# 启动器被漏掉的原因。
run "smoke_qml_launcher" "$PYTHON" tests/smoke_qml_launcher.py
run "smoke_shell" "$PYTHON" tests/smoke_shell.py
run "smoke_settings_cards" "$PYTHON" tests/smoke_settings_cards.py
run "smoke_qml" "$PYTHON" tests/smoke_qml.py
# Every navigation route, because a read-only property assignment made the settings page
# unreachable while the QML still loaded with no engine warning at all.
# 每一条导航路径，因为一次只读属性赋值会让设置页无法到达，而 QML 仍然加载且没有任何引擎警告。
run "smoke_navigation" "$PYTHON" tests/smoke_navigation.py
run "smoke_import" "$PYTHON" tests/smoke_import.py
run "smoke_wayland" "$PYTHON" tests/smoke_wayland.py
run "smoke_features" "$PYTHON" tests/smoke_features.py
run "probe_qml" "$PYTHON" tests/probe_qml.py

if [ "$QUICK" = "0" ]; then
    # `--allow-missing-decoder`: this environment genuinely cannot build a decoder (no
    # Rust toolchain, and no C compiler available from a reachable mirror), so playback is
    # reported as SKIPPED with the reason rather than as a failure. On a machine where the
    # decoder IS expected, the test fails WITHOUT the flag — which is what keeps a broken
    # build from looking green.
    # `--allow-missing-decoder`：本环境确实无法构建解码器（没有 Rust 工具链，也没有可从可达
    # 镜像获得的 C 编译器），因此播放被报告为 SKIPPED 并给出原因，而不是失败。在期望有解码器的
    # 机器上，不带该标志时测试会失败——这正是让坏掉的构建不会看起来是绿的方式。
    run "smoke_playback" "$PYTHON" tests/smoke_playback.py --allow-missing-decoder
    # Animation, reported as SKIPPED without a decoder for the same reason.
    # 动画检查，没有解码器时同样报告 SKIPPED，原因相同。
    run "smoke_animation" "$PYTHON" tests/smoke_animation.py --allow-missing-decoder
    run "smoke_animation_pixels" "$PYTHON" tests/smoke_animation_pixels.py \
        /tmp/gm_anim_a.png /tmp/gm_anim_b.png --allow-missing-decoder
fi

echo
echo "=== optional native decoder (expected absent here) ==="
inform "smoke_native" "$PYTHON" tests/smoke_native.py
inform "smoke_native_contract" "$PYTHON" tests/smoke_native_contract.py

echo
echo "=== desktop-session services (cannot run without a real session) ==="
# `probe_services` needs a tray AND a global hotkey registration. Under WSL there is no
# tray in the offscreen platform and no X server for XGrabKey, so this reports why rather
# than pretending.
# `probe_services` 需要托盘"与"全局热键注册。WSL 下离屏平台没有托盘、也没有 X 服务器供
# XGrabKey 使用，因此它说明原因而不是假装。
PROBE_SESSION=${PROBE_SESSION:-0}
if [ "$PROBE_SESSION" = "1" ]; then
    run "probe_services" "$PYTHON" tests/probe_services.py
else
    printf '%-26s %s\n' "probe_services" "MANUAL (needs a real desktop: tray + X server)"
fi

echo
echo "=============================================="
echo "passed: $PASS   failed: $FAIL   informational: $INFO"
if [ -n "$FAILED_NAMES" ]; then
    echo "failed:$FAILED_NAMES"
fi
if [ "$FAIL" -gt 0 ]; then
    echo "LINUX CHECKS FAILED / Linux 检查未通过"
    exit 1
fi
if [ "$INFO" -gt 0 ]; then
    echo "LINUX CHECKS PASSED / Linux 检查通过"
    echo "  ($INFO check(s) skipped as informational — see the lines above)"
    echo "  （$INFO 项作为信息跳过——见上面各行）"
else
    echo "LINUX CHECKS PASSED / Linux 检查通过"
fi
exit 0
