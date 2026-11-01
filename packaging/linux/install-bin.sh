#!/bin/sh
# Installer body for the self-extracting `.bin`.
#
# `makeself` wraps this script and its payload into one executable file. It runs from the directory it
# extracted to, with `$1` being the target prefix passed on the command line:
#
#     ./GIFManager-2.0.0-linux-x86_64.bin            # installs into ~/.local
#     ./GIFManager-2.0.0-linux-x86_64.bin /opt/gm     # installs into /opt/gm
#
# # Why `~/.local` and not `/usr`
#
# The application keeps its database and stickers under `$XDG_DATA_HOME`, so it needs no privileges to run;
# asking for `sudo` only to copy files into `/usr` would be a worse trade than following the XDG layout.
# `--system` is still available for anyone who wants it.
#
# `.bin` 自解压安装器的主体脚本。
#
# `makeself` 把本脚本与其负载包成单个可执行文件。它从解压出的目录中运行，`$1` 是命令行传入的目标前缀：
#
#     ./GIFManager-2.0.0-linux-x86_64.bin            # 安装到 ~/.local
#     ./GIFManager-2.0.0-linux-x86_64.bin /opt/gm     # 安装到 /opt/gm
#
# # 为什么用 `~/.local` 而不是 `/usr`
#
# 程序把数据库与贴纸放在 `$XDG_DATA_HOME`，因此运行无需任何特权；仅为把文件拷进 `/usr` 而要求 `sudo`
# 是比遵循 XDG 布局更差的交易。想装到系统位置的人仍可使用 `--system`。

set -eu

VERSION="__VERSION__"
PREFIX="${1:-}"
MODE="user"

for arg in "$@"; do
  case "$arg" in
    --system) MODE="system" ;;
    --prefix=*) PREFIX="${arg#--prefix=}" ;;
    -h|--help)
      echo "GIFManager $VERSION installer"
      echo "Usage: $0 [--system] [--prefix=PATH]"
      exit 0
      ;;
  esac
done

if [ -z "$PREFIX" ]; then
  if [ "$MODE" = "system" ]; then
    PREFIX="/usr/local"
  else
    PREFIX="${XDG_DATA_HOME:-$HOME/.local}"
  fi
fi

# The payload sits beside this script once makeself has extracted it.
# 负载在 makeself 解压后与本脚本并列。
HERE="$(cd "$(dirname "$0")" && pwd)"
PAYLOAD="$HERE/payload"

LIBDIR="$PREFIX/lib/gifmanager"
BINDIR="$PREFIX/bin"
APPDIR="$PREFIX/share/applications"
ICONDIR="$PREFIX/share/icons/hicolor/256x256/apps"

echo "Installing GIFManager $VERSION into $PREFIX"
mkdir -p "$LIBDIR" "$BINDIR" "$APPDIR" "$ICONDIR"
cp -R "$PAYLOAD/." "$LIBDIR/"
chmod +x "$LIBDIR/GIFManager"

# A tiny launcher rather than a symlink: a symlink to the bundle executable makes PyInstaller resolve
# `sys.executable` through it, and the `_internal` directory is then looked for next to the LINK.
# 用小型启动脚本而不是符号链接：指向包内可执行文件的符号链接会让 PyInstaller 经它解析
# `sys.executable`，随后 `_internal` 目录会被到"链接"旁边去找。
cat > "$BINDIR/gifmanager" <<LAUNCHER
#!/bin/sh
exec "$LIBDIR/GIFManager" "\$@"
LAUNCHER
chmod +x "$BINDIR/gifmanager"

# The desktop file is installed under the name Qt registers as its app id, because the XDG portal looks
# the entry up BY THAT NAME before it will register the app id; any other name makes the global-hotkey
# portal answer "app info not found".
# 桌面文件以 Qt 注册的 app id 为名安装，因为 XDG 门户会在注册 app id 之前"按那个名字"查找条目；换成别的
# 名字会让全局热键门户回答 "app info not found"。
sed -e "s|^Exec=.*|Exec=$BINDIR/gifmanager|" "$HERE/gifmanager.desktop" > \
  "$APPDIR/gifmanager.desktop"
if [ -f "$HERE/gifmanager.png" ]; then
  cp "$HERE/gifmanager.png" "$ICONDIR/gifmanager.png"
fi

# Refresh the desktop database when the tools exist; a missing one is not an error.
# 工具存在时刷新桌面数据库；缺失不是错误。
command -v update-desktop-database >/dev/null 2>&1 && \
  update-desktop-database "$APPDIR" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && \
  gtk-update-icon-cache -f -t "$PREFIX/share/icons/hicolor" >/dev/null 2>&1 || true

cat <<DONE

GIFManager $VERSION installed.

  launcher : $BINDIR/gifmanager
  bundle   : $LIBDIR

To uninstall, remove those two paths.
卸载：删除上述两个路径即可。
DONE
