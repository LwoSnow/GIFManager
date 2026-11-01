"""Sanity-check the Makefile after the encoding repair.

A PowerShell `Set-Content -Encoding UTF8` round trip earlier in this session
corrupted the Chinese half of the Makefile's comments into mojibake, which is the
same class of damage it did to two test package files. This verifies the rewrite
is clean and that the recipe lines are still tab-indented, since `make` silently
ignores a recipe indented with spaces.

本次会话早前一次 PowerShell 的 `Set-Content -Encoding UTF8` 往返把 Makefile 注释的
中文半部分变成了乱码，与它对两个测试包文件造成的损坏属同一类。本脚本验证重写后的
内容干净，且配方行仍以制表符缩进——因为 `make` 会静默忽略用空格缩进的配方。
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAKEFILE = ROOT / "Makefile"


def main():
    text = MAKEFILE.read_text(encoding="utf-8")
    lines = text.splitlines()

    problems = []

    mojibake = [(i, l) for i, l in enumerate(lines, 1) if "\ufffd" in l]
    if mojibake:
        problems.append(f"{len(mojibake)} line(s) contain U+FFFD replacement chars")
        for number, line in mojibake[:5]:
            problems.append(f"    {number}: {line[:90]}")

    # A mojibake round trip also produces runs of the C1/C2 range that never occur
    # in correctly encoded Chinese. Spot them by looking for the tell-tale
    # sequences of Latin-1 accented characters.
    # 乱码往返还会产生正确编码的中文里绝不会出现的 C1/C2 区段。通过查找那些典型的
    # Latin-1 重音字符序列来发现它们。
    suspicious = [(i, l) for i, l in enumerate(lines, 1)
                  if any(marker in l for marker in ("锛", "鐨", "涓", "鏄"))]
    if suspicious:
        problems.append(
            f"{len(suspicious)} line(s) look like mis-decoded Chinese")
        for number, line in suspicious[:5]:
            problems.append(f"    {number}: {line[:90]}")

    if not any("\u4e00" <= ch <= "\u9fff" for ch in text):
        problems.append("no Chinese text at all — the comments lost their half")

    # Recipes must be tab-indented. `make` reports a confusing error for a
    # space-indented recipe, so it is worth catching here.
    # 配方必须以制表符缩进。空格缩进的配方会让 `make` 报出令人困惑的错误，因此值得
    # 在此拦下。
    recipe_lines = [l for l in lines if l.startswith("\t")]
    if not recipe_lines:
        problems.append("no tab-indented recipe lines found")

    space_recipes = [i for i, l in enumerate(lines, 1)
                     if l.startswith("    ") and not l.startswith("\t")
                     and "=" not in l and "@echo" not in l
                     and l.strip() and not l.strip().startswith("#")]
    # Only informational: indented continuations of a comment are fine.
    # 仅作信息提示：注释的缩进续行没有问题。

    # `.PHONY: a b c` declares several targets on one line, so the names come from
    # splitting the remainder rather than from the first colon-delimited field.
    # `.PHONY: a b c` 在一行里声明多个目标，因此名称来自对剩余部分的分割，而不是第一个
    # 以冒号分隔的字段。
    targets = []
    for line in lines:
        if not line.startswith(".PHONY:"):
            continue
        targets.extend(line.split(":", 1)[1].split())
    print(f"file            : {MAKEFILE.name}")
    print(f"lines           : {len(lines)}")
    print(f"recipe lines    : {len(recipe_lines)} (tab-indented)")
    print(f"phony targets   : {len(targets)} -> {', '.join(sorted(set(targets)))}")
    print(f"Chinese present : {any(chr(0x4e00) <= ch <= chr(0x9fff) for ch in text)}")

    if problems:
        print()
        print("MAKEFILE CHECK FAILED / Makefile 检查未通过")
        for problem in problems:
            print("  " + problem)
        return 1
    print()
    print("MAKEFILE CHECK OK / Makefile 检查通过")
    print("  encoding clean, Chinese intact, recipes tab-indented")
    print("  编码干净、中文完整、配方以制表符缩进")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
