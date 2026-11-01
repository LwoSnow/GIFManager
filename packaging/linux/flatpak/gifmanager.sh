#!/bin/sh
# Launcher installed into /app/bin by the Flatpak manifest.
#
# # Why this is a FILE in the repository
#
# The manifest used to write it inline with
#
#     cat > /app/bin/gifmanager <<'EOF'
#     ...
#     EOF
#
# inside a YAML block, and `flatpak-builder` runs each `build-commands` entry as its own shell invocation
# with a build directory that has no `/app/bin` yet. The result was
#
#     Running: cat > /app/bin/gifmanager <<'EOF'
#     /bin/sh: line 1: /app/bin/gifmanager: No such file or directory
#     chmod: cannot access '/app/bin/gifmanager': No such file or directory
#
# - the directory did not exist, and the heredoc did not survive the round trip through YAML. A real file
# installed with `install -Dm755` avoids both problems, and it can be checked by eye.
# 由 Flatpak 清单安装到 /app/bin 的启动器。
#
# # 为什么它是一个"文件"
#
# 清单过去用 `cat > /app/bin/gifmanager <<'EOF'` 内联写入，而 `flatpak-builder` 会把每条 `build-commands`
# 当作独立的一次 shell 调用来执行，其构建目录里还没有 `/app/bin`。结果就是
#
#     Running: cat > /app/bin/gifmanager <<'EOF'
#     /bin/sh: line 1: /app/bin/gifmanager: No such file or directory
#     chmod: cannot access '/app/bin/gifmanager': No such file or directory
#
# ——目录不存在，而 heredoc 也没能完整穿过 YAML。改用真实文件并以 `install -Dm755` 安装，两个问题都没有了，
# 而且可以直接用眼睛核对。
#
# `exec` so the process the desktop sees is the application itself, not a wrapper shell.
# 用 `exec`，使桌面看到的进程就是程序本身，而不是一层包装 shell。

set -eu
exec /app/lib/gifmanager/GIFManager "$@"
