"""Quick format check per code-style: line width, trailing whitespace, tabs,
triple quotes only at file head, trailing newline.
按 code-style 做快速格式检查：行宽、尾随空格、tab、三引号位置、结尾换行。"""
import re
import sys

FILES = [
    "app/main_window.py", "app/widgets/emoji_item.py", "app/widgets/emoji_grid.py",
    "app/widgets/settings_dialog.py", "app/models/data_manager.py",
    "app/utils/gif_converter.py", "app/utils/gif_player.py", "app/utils/build_gifdec.py",
    "tests/test_gifdec_compare.py", "tests/test_gif_player.py",
    "tests/test_emoji_gif_play.py",
]

problems = 0
for f in FILES:
    try:
        with open(f, encoding="utf-8") as fh:
            lines = fh.readlines()
    except UnicodeDecodeError:
        print(f"{f}: NOT UTF-8")
        problems += 1
        continue
    for i, ln in enumerate(lines, 1):
        if len(ln.rstrip("\n")) > 100:
            print(f"{f}:{i}: LONG {len(ln.rstrip())}")
            problems += 1
        if ln.endswith((" \n", "\t\n")) or ln.endswith(" "):
            print(f"{f}:{i}: TRAILING")
            problems += 1
        if "\t" in ln:
            print(f"{f}:{i}: TAB")
            problems += 1
    body = "".join(lines)
    # Strip the file-head docstring (opening triple-quote within the first
    # 3 lines); whatever remains must not contain triple quotes, except
    # data_manager.py whose SQL strings legitimately use triple quotes.
    # 剥掉文件头 docstring（开头三引号在前 3 行内）；其余部分不得再有三引号，
    # 例外：data_manager.py 的 SQL 多行字符串（既有规范已豁免）。
    head = body
    m = re.search(r'"""', body)
    if m and body[: m.start()].count("\n") <= 2:
        rest = body[m.end():]
        c = rest.find('"""')
        if c >= 0:
            head = rest[c + 3:]
    for m in re.finditer(r'"""', head):
        line = body[: m.start()].count("\n") + 1
        if f != "app/models/data_manager.py":
            print(f"{f}: triple-quote at line {line}")
            problems += 1
    if lines and not lines[-1].endswith("\n"):
        print(f"{f}: NO TRAILING NEWLINE")
        problems += 1
print("PROBLEMS:", problems)
sys.exit(1 if problems else 0)
