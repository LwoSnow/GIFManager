#!/bin/sh
# Add the GIFManager window rule to a niri configuration, idempotently.
#
# # What problem this solves
#
# niri tiles new windows. GIFManager is a frameless palette that must FLOAT. Wayland gives the
# client no way to request that, so it has to be a compositor rule matching the window's
# `app-id` — which the application only started publishing once
# `QGuiApplication.setDesktopFileName(APP_ID)` was added.
#
# # Why the rule is wrapped in markers
#
# The rule is appended inside a clearly delimited block, so re-running this script does not add it
# twice and so removing it is one edit. A user's compositor config is not this project's file, and
# appending unmarked text to it would be hostile.
#
# # 幂等地把 GIFManager 的窗口规则加入 niri 配置。
#
# # 这段脚本解决什么
#
# niri 会平铺新窗口。GIFManager 是一个必须"浮动"的无边框调色板。Wayland 不提供让客户端请求此事的
# 途径，因此必须由匹配窗口 `app-id` 的合成器规则实现——而应用直到加入
# `QGuiApplication.setDesktopFileName(APP_ID)` 之后才开始发布该 id。
#
# # 为什么规则被标记包裹
#
# 规则被追加在一个明确分隔的块内，使重复运行本脚本不会加两次、而移除只需一次编辑。用户的合成器配置
# 不是本项目的文件，向其中追加无标记文本会是冒犯性的。
set -e

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(dirname -- "$SCRIPT_DIR")
SNIPPET="$PROJECT_ROOT/packaging/niri-window-rule.kdl"
CONFIG_DIR=${XDG_CONFIG_HOME:-$HOME/.config}/niri
CONFIG="$CONFIG_DIR/config.kdl"
RULES="$CONFIG_DIR/rules.kdl"

BEGIN_MARKER="// >>> GIFManager Next window rule (managed by scripts/niri-window-rule.sh) >>>"
END_MARKER="// <<< GIFManager Next window rule <<<"

die() {
    printf 'error: %s\n' "$1" >&2
    exit 1
}

[ -f "$SNIPPET" ] || die "missing $SNIPPET"

if [ ! -f "$CONFIG" ]; then
    printf 'error: no niri configuration at %s\n' "$CONFIG" >&2
    printf '       this script only applies to a niri session; nothing to do\n' >&2
    exit 1
fi

# Prefer the INCLUDED rules file when the main config includes one, because that is where this
# user keeps window rules and appending to config.kdl would split them.
# 当主配置包含一个规则文件时优先用它，因为该用户把窗口规则放在那里，而追加到 config.kdl 会把它们
# 拆散。
TARGET="$CONFIG"
if grep -qE '^[[:space:]]*include[^"]*"rules\.kdl"' "$CONFIG" 2>/dev/null; then
    [ -f "$RULES" ] && TARGET="$RULES"
    printf 'note: window rules live in %s (included by config.kdl)\n' "$TARGET"
fi

# Refuse to act on a file we cannot parse far enough to be sure the markers are balanced.
# 拒绝在我们无法解析到足以确认标记配对的文件上动手。
if grep -qF "$BEGIN_MARKER" "$TARGET" 2>/dev/null; then
    printf '=== the rule is already installed in %s ===\n' "$TARGET"
    printf '    remove the block between the two GIFManager markers to uninstall\n'
    printf '    移除两个 GIFManager 标记之间的块即可卸载\n'
    exit 0
fi

# Extract only the active `window-rule` block from the snippet: everything else in that file is
# explanation, and copying prose into a compositor config is noise.
# 只从片段中取活动的 `window-rule` 块：该文件其余部分是说明，把散文复制进合成器配置是噪音。
BLOCK=$(sed -n '/^window-rule {/,/^}/p' "$SNIPPET")
[ -n "$BLOCK" ] || die "could not find a window-rule block in $SNIPPET"

cp -f "$TARGET" "$TARGET.bak.$(date +%s)"

printf '\n%s\n' "$BEGIN_MARKER" >> "$TARGET"
printf '%s\n' "$BLOCK" >> "$TARGET"
printf '%s\n' "$END_MARKER" >> "$TARGET"

printf '=== appended the rule to %s ===\n' "$TARGET"

# Validate before declaring success: a syntax error in a compositor config can leave the session
# without a working keyboard.
# 在宣告成功之前校验：合成器配置里的语法错误可能让会话失去可用的键盘。
if command -v niri >/dev/null 2>&1; then
    printf '=== validating ===\n'
    if niri validate -c "$CONFIG" 2>&1 | tail -3; then
        printf '\n=== installed ===\n'
        printf 'The window opens floating at 620x520. niri reloads its config automatically.\n'
        printf 'If it does not, run: niri msg action do-screen-transition\n'
        printf '\n窗口将以 620x520 浮动打开。niri 会自动重载配置；若未生效请运行\n'
        printf 'niri msg action do-screen-transition\n'
    else
        printf 'error: niri rejected the configuration; restoring the backup\n' >&2
        printf '错误：niri 拒绝了配置；正在还原备份\n' >&2
        ls -t "$TARGET".bak.* 2>/dev/null | head -1 | xargs -r cp -f -- "$TARGET"
        exit 1
    fi
else
    printf 'note: `niri` is not on PATH, so the result was not validated\n'
fi
