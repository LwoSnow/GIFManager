#!/bin/sh
# Report what this Linux environment provides for running the GIFManager checks.
#
# Written as a FILE rather than a `bash -lc "..."` one-liner because the one-liner kept
# losing its quoting through PowerShell -> wsl.exe -> bash, which produced empty output
# that looked like "nothing is installed" instead of "the command never ran".
#
# 以"文件"形式而非 `bash -lc "..."` 单行命令，因为该单行命令在
# PowerShell -> wsl.exe -> bash 之间反复丢失引号，产出的空输出看起来像"什么都没装"，而不是
# "命令根本没运行"。
echo "=== identity ==="
cat /etc/os-release 2>/dev/null | head -3
echo "arch: $(uname -m)"
echo "kernel: $(uname -r)"

echo
echo "=== tools ==="
for tool in python3 python pip3 pipx pacman gcc cc make git cargo; do
    path=$(command -v "$tool" 2>/dev/null)
    if [ -n "$path" ]; then
        echo "$tool -> $path"
    else
        echo "$tool -> MISSING"
    fi
done

echo
echo "=== python ==="
if command -v python3 >/dev/null 2>&1; then
    python3 --version
    python3 -c "import sys; print('executable:', sys.executable)"
    for module in PySide6 PIL venv ensurepip; do
        if python3 -c "import $module" >/dev/null 2>&1; then
            echo "$module -> present"
        else
            echo "$module -> absent"
        fi
    done
else
    echo "no python3, so nothing to probe"
fi

echo
echo "=== Qt platform plugins ==="
if command -v python3 >/dev/null 2>&1; then
    python3 - <<'PY' 2>/dev/null || echo "cannot import PySide6"
try:
    import PySide6, os
    from PySide6.QtCore import QLibraryInfo
    plugins = QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
    print("PySide6", PySide6.__version__)
    print("plugin dir:", plugins)
    platforms = os.path.join(plugins, "platforms")
    if os.path.isdir(platforms):
        print("platforms:", sorted(os.listdir(platforms)))
    else:
        print("platforms: <missing>")
except Exception as exc:
    print("probe failed:", exc)
PY
fi

echo
echo "=== display ==="
echo "DISPLAY=${DISPLAY:-<unset>}"
echo "WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-<unset>}"
echo "XDG_SESSION_TYPE=${XDG_SESSION_TYPE:-<unset>}"
echo "DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-<unset>}"
if [ -e /tmp/.X11-unix/X0 ]; then
    echo "X socket X0: present"
else
    echo "X socket X0: absent"
fi
