"""Check bilingual comments at the BLOCK level: a run of consecutive comment
lines must contain both English and Chinese (matching the project's paired
multi-line style). / 按注释块检查双语：连续注释行块须同时包含英文与中文
（与项目成对多行注释风格一致）。"""
import re
import sys

FILES = [
    "app/main_window.py", "app/widgets/emoji_item.py", "app/widgets/emoji_grid.py",
    "app/widgets/settings_dialog.py", "app/models/data_manager.py",
    "app/utils/gif_converter.py", "app/utils/gif_player.py",
    "app/utils/build_gifdec.py",
]

CJK = re.compile(r"[\u4e00-\u9fff]")
ASCII = re.compile(r"[A-Za-z]{2,}")


def has_zh(s):
    return bool(CJK.search(s))


def has_en(s):
    return bool(ASCII.search(s))


bad = 0
for f in FILES:
    lines = open(f, encoding="utf-8").read().split("\n")
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s.startswith("#") or s.startswith("# -*-") or s.startswith("#!"):
            i += 1
            continue
        # collect the comment block / 收集连续注释块
        block = []
        while i < len(lines) and lines[i].strip().startswith("#"):
            block.append(lines[i].strip())
            i += 1
        # strip separator-only lines / 去掉纯分隔线
        block = [b for b in block
                 if not re.fullmatch(r"#[\s\-=*]+", b) and b not in ("#",)]
        if not block:
            continue
        joined = " ".join(block)
        # comments with code identifiers only (like "# noqa") are fine
        if re.search(r"noqa|pragma|type:", joined):
            continue
        # any line containing both languages satisfies the block / 任一行双语即合规
        if any(has_zh(b) and has_en(b) for b in block):
            continue
        if has_zh(joined) and has_en(joined):
            continue
        print(f"{f}:{lines.index(block[0], 0) + 1 if False else None}")
        # find line number of the block start
        start = None
        for idx in range(len(lines)):
            if lines[idx].strip() == block[0]:
                start = idx + 1
                break
        print(f"{f}:{start}: 注释块缺双语: {block[0][:60]} ...")
        bad += 1
print("COMMENT BLOCK ISSUES:", bad)
sys.exit(1 if bad else 0)
