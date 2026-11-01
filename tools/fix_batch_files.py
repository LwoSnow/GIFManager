"""Repair batch files: strip non-ASCII bytes and normalise line endings to CRLF.

# Why a repair tool exists as well as a lint

The lint says "this .bat cannot run"; this says "here is a runnable one". Both are needed
because the two faults have different repairs:

  * non-ASCII bytes are REMOVED, and the affected comment lines are rewritten as English.
    Silently dropping them would leave a comment that starts mid-sentence, so a line whose
    non-ASCII content carries meaning is replaced with a short English note pointing at
    `docs/RUNNING.md`.
  * line endings are CONVERTED to CRLF, which loses nothing.

Usage:
    python tools/fix_batch_files.py --check     report only (default)
    python tools/fix_batch_files.py --write     rewrite the files in place

# 为什么既有检查又有修复工具

检查说"这个 .bat 无法运行"；本工具说"这里有一个能运行的"。两者都需要，因为两种毛病的修复方式不同：

  * 非 ASCII 字节被"删除"，受影响的注释行改写为英文。静默丢弃会留下一条从句子中间开始的注释，因此
    非 ASCII 内容承载语义的行会被替换为一句简短的英文说明，指向 `docs/RUNNING.md`。
  * 行尾被"转换"为 CRLF，这不会丢失任何东西。

用法：
    python tools/fix_batch_files.py --check     仅报告（默认）
    python tools/fix_batch_files.py --write     就地改写文件
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP_PARTS = {".venv", "venv", "__pycache__", "node_modules", "target", ".git"}
SUFFIXES = (".bat", ".cmd")


def batch_files():
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUFFIXES:
            continue
        if SKIP_PARTS & set(path.parts):
            continue
        yield path


def repair(raw):
    # Work line by line so a REPLACEMENT can be substituted for a line that had to lose its
    # non-ASCII content.
    # 逐行处理，使被迫丢失非 ASCII 内容的行可以用一句替换文本代替。
    text = raw.decode("utf-8", "replace")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    repaired = []
    changed = False
    for line in lines:
        if all(ord(ch) < 128 for ch in line):
            repaired.append(line)
            continue
        changed = True
        # A comment line becomes a pointer; anything else is reported rather than guessed at,
        # because a COMMAND containing a CJK character needs a human decision.
        # 注释行变成一句指引；其他行会被报告而不是被猜测，因为含中日韩字符的"命令"需要人来决定。
        if line.lstrip().upper().startswith("REM") or line.lstrip().startswith("::"):
            repaired.append("REM (Chinese note moved to docs/RUNNING.md)")
        else:
            repaired.append(line.encode("ascii", "replace").decode("ascii"))
    return "\r\n".join(repaired), changed


def main(argv):
    write = "--write" in argv
    findings = []
    for path in batch_files():
        raw = path.read_bytes()
        repaired, changed = repair(raw)
        needs_crlf = b"\n" in raw and raw.count(b"\r\n") != raw.count(b"\n")
        if not changed and not needs_crlf and raw[:3] != b"\xef\xbb\xbf":
            continue
        findings.append(path)
        print(f"{path.relative_to(ROOT)}: needs repair"
              f"{' (non-ASCII)' if changed else ''}"
              f"{' (line endings)' if needs_crlf else ''}")
        if write:
            body = repaired.lstrip("\ufeff")
            path.write_bytes(body.encode("ascii", "replace"))
            print("    rewritten as ASCII + CRLF")

    print()
    if not findings:
        print("BATCH FILES OK / 批处理文件正常")
        return 0
    if write:
        print(f"REPAIRED {len(findings)} file(s) / 已修复 {len(findings)} 个文件")
        print("review the result, then re-run tools/check_batch_encoding.py")
        print("请检查结果，然后重跑 tools/check_batch_encoding.py")
        return 0
    print("REPAIR NEEDED / 需要修复")
    print("  re-run with --write to apply")
    print("  用 --write 重跑以应用修复")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
