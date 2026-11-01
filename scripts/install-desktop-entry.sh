#!/bin/sh
# Install the desktop entry and icon so the XDG portal and the compositor can identify this app.
#
# # Why this is required on Wayland, and what breaks without it
#
# Measured on Arch Linux + niri (portal backend `xdg-desktop-portal-gnome`):
#
#   CreateSession                    -> org.freedesktop.portal.Error.NotAllowed:
#                                       An app id is required
#   Registry.Register (no .desktop)  -> org.freedesktop.portal.Error.Failed:
#                                       Could not register app ID:
#                                       App info not found for 'gifmanager'
#   Registry.Register (with .desktop)-> accepted
#   CreateSession (after Register)   -> accepted
#
# The same app id is also the only handle niri can match a `window-rule` against, which is how
# this frameless window is made to FLOAT instead of being tiled.
#
# Installs into the per-user XDG directories, so no root is needed:
#   ~/.local/share/applications/gifmanager.desktop
#   ~/.local/share/icons/hicolor/512x512/apps/gifmanager.png
#
# 安装桌面条目与图标，使 XDG 门户与合成器能识别本应用。
#
# # 为什么在 Wayland 上这是必需的，以及缺少它会坏掉什么
#
# 在 Arch Linux + niri 上实测（门户后端 `xdg-desktop-portal-gnome`）：
#
#   CreateSession                    -> org.freedesktop.portal.Error.NotAllowed:
#                                       An app id is required
#   Registry.Register（无 .desktop） -> org.freedesktop.portal.Error.Failed:
#                                       Could not register app ID:
#                                       App info not found for 'gifmanager'
#   Registry.Register（有 .desktop） -> 接受
#   CreateSession（注册之后）        -> 接受
#
# 同一个 app id 也是 niri 匹配 `window-rule` 的唯一把手，而那正是让这个无边框窗口"悬浮"而不是被
# 平铺的方式。
#
# 安装到按用户的 XDG 目录，因此无需 root：
#   ~/.local/share/applications/gifmanager.desktop
#   ~/.local/share/icons/hicolor/512x512/apps/gifmanager.png
set -e

# Resolve the project root from this script's own location, so it works from any cwd and through
# a symlink.
# 由脚本自身位置解析项目根，使其在任何工作目录下、以及经符号链接调用时都能工作。
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(dirname -- "$SCRIPT_DIR")

VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
ICON_SOURCE="$PROJECT_ROOT/resources/icons/gifmanager.png"
TEMPLATE="$PROJECT_ROOT/packaging/gifmanager.desktop"

DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
APPLICATIONS="$DATA_HOME/applications"
ICONS="$DATA_HOME/icons/hicolor/512x512/apps"

die() {
    printf 'error: %s\n' "$1" >&2
    exit 1
}

[ -f "$TEMPLATE" ] || die "missing $TEMPLATE"
[ -d "$PROJECT_ROOT/gifmanager" ] || die "$PROJECT_ROOT does not look like the project root"

# The venv is the ONLY interpreter this should point at: the system Python on a rolling-release
# distribution is too new for the pinned PySide6, which is the whole reason the project carries
# its own environment.
# venv 是唯一应当指向的解释器：滚动发行版的系统 Python 对锁定的 PySide6 来说太新，而这正是项目自带
# 环境的全部原因。
if [ ! -x "$VENV_PYTHON" ]; then
    die "no virtual environment at $VENV_PYTHON
     create it first:  python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt"
fi

printf '=== installing the desktop entry ===\n'
mkdir -p "$APPLICATIONS"

# `Exec` must be one line of absolute paths. `%U` is deliberately absent: the application takes no
# file arguments.
# `Exec` 必须是一行绝对路径。刻意不加 `%U`：本应用不接受文件参数。
ESCAPED_ROOT=$(printf '%s' "$PROJECT_ROOT" | sed 's/[&/\]/\\&/g')
ESCAPED_PY=$(printf '%s' "$VENV_PYTHON" | sed 's/[&/\]/\\&/g')
sed -e "s|^Exec=.*|Exec=\"$ESCAPED_PY\" -m gifmanager|" \
    -e "s|^Icon=.*|Icon=gifmanager|" \
    "$TEMPLATE" > "$APPLICATIONS/gifmanager.desktop"

# `StartupWMClass` is what some shells use to group the window with this entry. Qt's Wayland app id
# comes from `setDesktopFileName`, which already matches.
# `StartupWMClass` 是部分外壳用来把窗口与本条目归组的属性。Qt 的 Wayland app id 来自
# `setDesktopFileName`，已经与它一致。

printf '=== installing the icon ===\n'
if [ -f "$ICON_SOURCE" ]; then
    mkdir -p "$ICONS"
    cp -f "$ICON_SOURCE" "$ICONS/gifmanager.png"
    printf '  %s\n' "$ICONS/gifmanager.png"
else
    printf '  warning: %s is absent, so the entry will have no icon\n' "$ICON_SOURCE"
fi

# Refresh the caches when the tools exist; their absence is not an error on a minimal system.
# 存在相应工具时刷新缓存；在极简系统上它们缺失不算错误。
command -v update-desktop-database >/dev/null 2>&1 \
    && update-desktop-database "$APPLICATIONS" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null 2>&1 \
    && gtk-update-icon-cache -f -t "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true

printf '\n=== installed ===\n'
printf '  entry : %s/gifmanager.desktop\n' "$APPLICATIONS"
printf '  exec  : %s -m gifmanager\n' "$VENV_PYTHON"
printf '\nThe XDG portal can now register app id "gifmanager", which the global hotkey needs, and\n'
printf 'niri can match the window with a window-rule so it floats.\n'
printf '\n门户现在可以注册 app id "gifmanager"（全局热键所需），而 niri 可以用 window-rule 匹配\n'
printf '该窗口使其悬浮。\n'
