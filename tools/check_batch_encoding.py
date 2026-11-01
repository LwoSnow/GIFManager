"""Check that batch files are pure ASCII, because cmd.exe reads them as ANSI.

# The failure this prevents

`cmd.exe` reads a `.bat` file using the console's ANSI code page — 936 (GBK) on a Chinese
Windows — NOT as UTF-8. So a UTF-8 encoded CJK character is parsed as two or three separate
one-byte commands:

    '鈥?so' is not recognized as an internal or external command

The launcher becomes unrunnable while looking perfectly fine in an editor, and the errors
name byte fragments rather than the encoding. That is exactly what happened when `Run.bat`
carried bilingual comments.

# Why a lint rather than a convention

The project's style rules require bilingual comments, so the next person to touch a `.bat`
file will try to add Chinese and hit this again. A mechanical check turns a silent
"cannot run" into a named failure at check time. The Chinese explanation belongs in
`docs/RUNNING.md`, where UTF-8 is correct.

# 本脚本检查批处理文件是否为纯 ASCII，因为 cmd.exe 以 ANSI 读取它们。

# 它防止的失败

`cmd.exe` 用控制台的 ANSI 代码页（中文 Windows 是 936/GBK）读取 `.bat` 文件，"不是" UTF-8。
因此一个 UTF-8 编码的中日韩字符会被解析成两三个独立的单字节命令：

    '鈥?so' 不是内部或外部命令

启动器变得无法运行，而在编辑器里看起来完全正常，且错误信息点名的是字节碎片而不是编码。这正是
`Run.bat` 携带双语注释时发生的事。

# 为什么用检查而不是约定

本项目的风格规则要求注释双语，因此下一个接触 `.bat` 的人会尝试加中文并再次撞上它。一个机械检查
把静默的"无法运行"变成检查期一个有名字的失败。中文说明应放在 `docs/RUNNING.md`，那里 UTF-8 是
正确的。
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Directories never worth scanning: a virtual environment is full of third-party batch files
# we do not own, and failing on one would be a false alarm.
# 不值得扫描的目录：虚拟环境里尽是别人的批处理文件，为其中一个报错会是虚警。
SKIP_PARTS = {".venv", "venv", "__pycache__", "node_modules", "target", ".git"}

SUFFIXES = (".bat", ".cmd")

# `chcp 65001` switches the console to UTF-8, but it does NOT change how cmd.exe reads the
# batch file currently being executed — the parsing of the remaining lines has already
# begun under the old code page. So it is not an escape hatch, and this check does not accept
# it as one.
# `chcp 65001` 把控制台切到 UTF-8，但它"不会"改变 cmd.exe 读取当前正在执行的批处理文件的方式
# ——其余各行的解析已在旧代码页下开始。因此它不是逃生通道，本检查也不接受它作为逃生通道。


def batch_files():
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUFFIXES:
            continue
        if SKIP_PARTS & set(path.parts):
            continue
        yield path


def main():
    findings = []
    checked = 0
    for path in batch_files():
        checked += 1
        try:
            raw = path.read_bytes()
        except OSError as exc:
            findings.append((path, 0, f"cannot read: {exc}"))
            continue
        if raw[:3] == b"\xef\xbb\xbf":
            findings.append((path, 1, "has a UTF-8 BOM; cmd.exe shows it as \u00ef\u00bb\u00bf"))

        # LINE ENDINGS, which matter as much as the bytes.
        #
        # cmd.exe expects CRLF. A file with bare LF is treated as ONE enormous line, so
        # every `REM` swallows the rest of the file and the script produces a barrage of
        # errors naming single letters:
        #
        #     'M' is not recognized as an internal or external command
        #
        # That is more confusing than the encoding failure and has the same cause:
        # the file was written by a tool whose newline is LF. Git can also do it silently
        # via `core.autocrlf=false` plus a text checkout.
        #
        # 行尾与字节同样要紧。
        #
        # cmd.exe 期望 CRLF。只有裸 LF 的文件会被当成"一整行"，于是每条 `REM` 都吞掉文件其余
        # 部分，脚本产出一连串点名单个字母的错误：
        #
        #     'M' is not recognized as an internal or external command
        #
        # 这比编码失败更令人困惑，而原因相同：文件是由换行符为 LF 的工具写出的。Git 也可能通过
        # `core.autocrlf=false` 加文本检出静默造成它。
        crlf = raw.count(b"\r\n")
        bare_lf = raw.count(b"\n") - crlf
        if crlf == 0 and bare_lf > 0:
            findings.append(
                (path, 1,
                 f"has {bare_lf} bare LF line ending(s) and no CRLF; cmd.exe treats the "
                 f"whole file as one line"))
        elif bare_lf > 0:
            findings.append(
                (path, 1, f"has {bare_lf} bare LF line ending(s) mixed with CRLF"))
        for number, line in enumerate(raw.split(b"\r\n"), 1):
            # Split on CRLF because that is what cmd.exe expects; a lone LF can make it
            # mis-parse a line even when the bytes are all ASCII.
            # 按 CRLF 切分，因为那才是 cmd.exe 期望的；即使字节全是 ASCII，单独的 LF 也可能让它
            # 误解析某一行。
            for offset, byte in enumerate(line):
                if byte > 127:
                    fragment = line.decode("latin-1", "replace").strip()
                    findings.append(
                        (path, number,
                         f"non-ASCII byte 0x{byte:02x} at column {offset + 1} "
                         f"(line reads {fragment[:48]!r})"))
                    break

    print(f"batch files checked : {checked}")
    if not findings:
        print()
        print("BATCH ENCODING CHECK OK / 批处理编码检查通过")
        print("  every .bat/.cmd is pure ASCII with CRLF, so cmd.exe cannot mis-parse it")
        print("  每个 .bat/.cmd 都是纯 ASCII 且为 CRLF，因此 cmd.exe 不会误解析")
        print("  note: bilingual comments belong in docs/, not in a .bat")
        print("  提示：双语注释属于 docs/，不属于 .bat")
        return 0

    print()
    print("BATCH ENCODING CHECK FAILED / 批处理编码检查未通过")
    for path, number, problem in findings:
        relative = path.relative_to(ROOT)
        print(f"  {relative}:{number}: {problem}")
    print()
    print("  cmd.exe reads a .bat in the console ANSI code page (936/GBK on Chinese")
    print("  Windows), not as UTF-8, so a CJK character becomes several bogus commands.")
    print("  It also needs CRLF: with bare LF the whole file is one line and every REM")
    print("  swallows the rest. Keep batch files ASCII + CRLF; put the Chinese half of a")
    print("  comment in docs/RUNNING.md, or call a Python script that does the work.")
    print("  Repair one with:  python tools/fix_batch_files.py")
    print()
    print("  cmd.exe 以控制台 ANSI 代码页（中文 Windows 是 936/GBK）读取 .bat 而不是 UTF-8，")
    print("  因此一个中日韩字符会变成若干条伪造命令。它还需要 CRLF：只有裸 LF 时整个文件是一行，")
    print("  每条 REM 都会吞掉其余内容。请让批处理保持 ASCII + CRLF；注释的中文部分放进")
    print("  docs/RUNNING.md，或改为调用一个 Python 脚本去干活。")
    print("  修复方式：  python tools/fix_batch_files.py")
    return 1


if __name__ == "__main__":
    sys.exit(main())
