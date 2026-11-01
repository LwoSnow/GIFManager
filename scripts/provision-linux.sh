#!/bin/sh
# Install Python and the project's dependencies inside a Linux environment.
#
# Deliberately a SCRIPT rather than an inline command: the URL and package names differ
# per distribution, and a first attempt that installs `python3` on Arch and fails because
# the package is called `python` reads as "the image is broken" rather than "the name is
# wrong".
#
# 刻意写成"脚本"而非内联命令：URL 与包名随发行版而变，而第一次尝试在 Arch 上安装
# `python3` 却因为包名是 `python` 而失败，读起来像"镜像坏了"而不是"名字错了"。
#
# Usage: provision-linux.sh [--minimal]
#   --minimal  install only Python and pip (no Qt), for the pure-Python layers
#   （默认）   也安装 PySide6 与 Pillow，以便跑完整的冒烟检查
#
# 用法：provision-linux.sh [--minimal]
#   --minimal  只装 Python 与 pip（不装 Qt），用于纯 Python 层
#   （默认）    也安装 PySide6 与 Pillow，以便跑完整的冒烟检查
set -e

MINIMAL=0
if [ "$1" = "--minimal" ]; then
    MINIMAL=1
fi

echo "=== detecting the distribution ==="
if [ -r /etc/os-release ]; then
    . /etc/os-release
    echo "id=$ID version=$VERSION_ID"
else
    echo "no /etc/os-release; cannot detect"
    exit 1
fi

install_qt_libraries() {
    # The NATIVE libraries Qt's Python wheels link against.
    #
    # `pip install PySide6` succeeds without them and then `import PySide6.QtGui` fails
    # with `libGL.so.1: cannot open shared object file`. That is the single most common way
    # a fresh Linux environment looks broken: the Python package is installed, the import
    # still fails, and the message names a library nobody asked for.
    #
    # 首选的 PySide6 wheel 所链接的"原生"库。
    #
    # 没有它们时 `pip install PySide6` 会成功，随后 `import PySide6.QtGui` 会以
    # `libGL.so.1: cannot open shared object file` 失败。这是全新 Linux 环境看起来"坏掉"的
    # 最常见方式：Python 包装好了，导入仍然失败，而消息点名了一个没人要过的库。
    echo "=== installing Qt's native libraries ==="
    case "$ID" in
        arch|manjaro)
            # `mesa` provides libGL; the xcb libraries are what the `xcb` platform plugin
            # needs when a real X display IS used, and `libxkbcommon` is needed by both xcb
            # and wayland.
            # `mesa` 提供 libGL；xcb 系列库是真正使用 X 显示时 `xcb` 平台插件所需的，而
            # `libxkbcommon` 是 xcb 与 wayland 都需要的。
            pacman -S --noconfirm --needed mesa libxkbcommon \
                libxcb libxext libxrender libxi libxfixes libxrandr libxcursor \
                libsm libice fontconfig freetype2 2>&1 | tail -3
            ;;
        debian|ubuntu|linuxmint|pop)
            export DEBIAN_FRONTEND=noninteractive
            apt-get install -y -qq libgl1 libegl1 libxkbcommon0 libxkbcommon-x11-0 \
                libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
                libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 \
                libxcb-xkb1 libdbus-1-3 libfontconfig1
            ;;
        fedora|rhel|centos|rocky|almalinux)
            dnf install -y mesa-libGL mesa-libEGL libxkbcommon libxkbcommon-x11 \
                xcb-util-cursor xcb-util-wm xcb-util-image xcb-util-keysyms fontconfig
            ;;
        alpine)
            apk add --no-cache mesa libxkbcommon fontconfig ttf-dejavu
            ;;
        opensuse*|sles)
            zypper --non-interactive install Mesa-libGL1 libxkbcommon0 \
                libxkbcommon-x11-0 libxcb-cursor0 fontconfig
            ;;
        *)
            echo "unknown distribution; install libGL, libxkbcommon and the xcb libraries"
            ;;
    esac
}


install_packages() {
    # Install the named packages with whichever package manager this is.
    # 用本发行版的包管理器安装指定包。
    case "$ID" in
        arch|manjaro)
            # Arch calls it `python`, not `python3`, and ships pip in a separate package.
            # Arch 里它叫 `python` 而不是 `python3`，且 pip 是单独的包。
            pacman -Sy --noconfirm --needed python python-pip
            ;;
        debian|ubuntu|linuxmint|pop)
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -qq
            apt-get install -y -qq python3 python3-pip python3-venv
            ;;
        fedora|rhel|centos|rocky|almalinux)
            dnf install -y python3 python3-pip
            ;;
        alpine)
            apk add --no-cache python3 py3-pip
            ;;
        opensuse*|sles)
            zypper --non-interactive install python3 python3-pip
            ;;
        *)
            echo "unsupported distribution: $ID"
            echo "install python3 and pip by hand, then re-run this script"
            exit 1
            ;;
    esac
}

echo
echo "=== installing python and pip ==="
install_packages

echo
echo "=== python version ==="
python3 --version

echo
echo "=== ensuring pip works ==="
if ! python3 -m pip --version >/dev/null 2>&1; then
    echo "pip module missing; trying ensurepip"
    python3 -m ensurepip --upgrade 2>/dev/null || true
fi
python3 -m pip --version

if [ "$MINIMAL" = "1" ]; then
    echo
    echo "=== minimal install requested; skipping Qt ==="
    exit 0
fi

echo
echo "=== installing Qt's native libraries ==="
install_qt_libraries

echo
echo "=== installing PySide6 and Pillow ==="
# `--break-system-packages` is needed on distributions that mark the system Python as
# externally managed (Arch, newer Debian). This is a throwaway verification environment,
# which is exactly the case that flag exists for; a real deployment uses a venv.
# 在把系统 Python 标记为"外部管理"的发行版上（Arch、较新的 Debian）需要
# `--break-system-packages`。这是一个一次性验证环境，正是该选项存在的场合；真实部署用 venv。
python3 -m pip install --no-cache-dir --break-system-packages \
    "PySide6==6.11.1" "Pillow==12.3.0" 2>&1 | tail -5

echo
echo "=== verifying the Qt platform plugins ==="
python3 - <<'PY'
import os
import PySide6
from PySide6.QtCore import QLibraryInfo
plugins = QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
platforms = os.path.join(plugins, "platforms")
print("PySide6:", PySide6.__version__)
print("plugins:", plugins)
print("platforms:", sorted(os.listdir(platforms)) if os.path.isdir(platforms) else "<missing>")
needed = {"offscreen", "minimal"}
present = set()
if os.path.isdir(platforms):
    for name in os.listdir(platforms):
        stem = name.split(".")[0].replace("libq", "")
        present.add(stem)
missing = sorted(needed - present)
print("offscreen plugin:", "present" if "offscreen" in present else "MISSING")
if missing:
    print("MISSING:", missing)
PY

echo
echo "=== provisioned ==="
