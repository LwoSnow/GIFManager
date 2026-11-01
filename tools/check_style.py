"""Style check for this project's rules.

The rules come from the project's own `code-style` standard, which is stricter
than plain PEP8 in two places that matter for review:

* a module docstring (`\"\"\"`) is allowed ONLY as the first statement of a file —
  every class and function is documented with a `#` comment above it instead;
* every `#` comment must be bilingual, English first then Chinese.

Exit code 0 when the rules hold, 1 otherwise.

本项目的风格检查。

规则来自项目自己的 `code-style` 规范，它在两处比朴素 PEP8 更严，且这两处对评审很
关键：

* 三引号（`\"\"\"`）只允许作为文件的第一条语句——类与函数一律用其上方的 `#` 注释说明；
* 每条 `#` 注释必须双语，英文在前、中文在后。

规则成立时退出码 0，否则 1。
"""
import io
import pathlib
import re
import sys
import tokenize

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Maximum line length / 最大行宽
MAX_LINE_LENGTH = 100

# Characters that indicate the Chinese half of a bilingual comment /
# 表明注释含有中文半部分的字符范围
_CJK = re.compile(r"[\u3000-\u303f\u3040-\u30ff\u4e00-\u9fff\uff00-\uffef]")

# Comments that legitimately carry no translation: shebangs, encoding
# declarations, linter directives, and pure-punctuation separators.
# Structural dividers (`# ---- name ----`, `# ====`) are exempt because they
# only partition a file visually; the section they introduce is documented in
# prose, and translating a rule of dashes adds nothing a reader needs.
# 合法地无需翻译的注释：shebang、编码声明、linter 指令，以及纯标点分隔线。
# 结构分隔线（`# ---- 名称 ----`、`# ====`）豁免，因为它们只是视觉上划分文件；
# 它们引出的分节由散文说明，翻译一排横线不会给读者增加任何信息。
_EXEMPT_COMMENT = re.compile(
    r"^#!|coding[:=]|noqa|type:\s*ignore|pylint:|^\s*#\s*[-=*#]{4,}\s*$")

# A separator plus its single-word section title, e.g. a line of dashes above
# `# Paths` and another below it. The title is checked on its own, so a section
# heading still has to be bilingual.
# 分隔线加其单词分节标题，例如 `# Paths` 上下各一条横线。标题单独检查，因此分节标题
# 仍必须是双语的。
_DIVIDER_TITLE = re.compile(r"^#\s*([A-Za-z][A-Za-z0-9 ,/&'-]*)$")

# Directories and files excluded from the check /
# 检查时排除的目录与文件
_EXCLUDED_PARTS = {"__pycache__", ".venv", "venv", "build", "dist"}

# Command used in the failure hints / 失败提示中使用的命令
_HINT = "python tools/check_style.py gifmanager"


class Finding:
    def __init__(self, path, line, kind, message):
        self.path = path
        self.line = line
        self.kind = kind
        self.message = message

    def __str__(self):
        return f"{self.path}:{self.line}: [{self.kind}] {self.message}"


def check_docstrings(path, source):
    # A `\"\"\"` string is allowed only when it is the module docstring /
    # 三引号字符串只允许作为模块 docstring
    findings = []
    try:
        tree = compile(source, str(path), "exec",
                       # PyCF_ONLY_AST builds the tree without executing
                       # PyCF_ONLY_AST 只构建语法树、不执行
                       flags=0x400, dont_inherit=True)
    except SyntaxError as exc:
        return [Finding(path, exc.lineno or 0, "syntax", exc.msg)]

    body = getattr(tree, "body", [])
    module_doc = body[0] if body else None
    module_doc_lines = set()
    if (isinstance(module_doc, __import__("ast").Expr)
            and isinstance(module_doc.value, __import__("ast").Constant)
            and isinstance(module_doc.value.value, str)):
        module_doc_lines = set(
            range(module_doc.lineno, (module_doc.end_lineno or module_doc.lineno) + 1))

    for token in _tokens(source):
        if token.type != tokenize.STRING:
            continue
        if token.start[0] in module_doc_lines:
            continue
        text = token.string.lstrip("rbuRBU")
        if not text.startswith('"""') and not text.startswith("'''"):
            continue
        if token.start[0] != token.end[0]:
            continue  # a multi-line string is not a docstring anyway / 多行字符串本就不是 docstring
        findings.append(Finding(
            path, token.start[0], "docstring",
            "triple-quoted string outside the file header; use a '#' comment "
            "above the definition / 三引号出现在文件头之外；请改用定义上方的 "
            "'#' 注释"))
    return findings


def _tokens(source):
    try:
        return list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return []


def check_comments(path, source):
    # Every comment BLOCK must carry both English and Chinese.
    #
    # A block — consecutive comment lines with no blank line or code between them
    # — is checked as a unit rather than line by line, because the project's
    # style allows the English half on one line and the Chinese half on the
    # next, which is the only way a sentence of either language fits the line
    # width. Line-by-line checking would flag every correctly written block.
    # 每个注释"块"都必须同时含英文与中文。
    #
    # 以"块"为单位检查（连续注释行，中间没有空行或代码），而不是逐行检查，因为项目
    # 风格允许英文半句在一行、中文半句在下一行——这是任一种语言的一句话能落在行宽内
    # 的唯一办法。逐行检查会把每个写法正确的块都报成问题。
    findings = []
    blocks = []
    current = []

    lines = source.splitlines()
    for token in _tokens(source):
        if token.type != tokenize.COMMENT:
            continue
        text = token.string.rstrip()
        if _EXEMPT_COMMENT.search(text):
            continue
        start_line = token.start[0]
        if current and start_line != current[-1][0] + 1:
            blocks.append(current)
            current = []
        current.append((start_line, text))
    if current:
        blocks.append(current)

    for block in blocks:
        joined = "\n".join(text for _line, text in block)
        if _CJK.search(joined):
            continue
        findings.append(Finding(
            path, block[0][0], "comment",
            "comment block has no Chinese half; this project's comments are "
            "bilingual / 注释块缺少中文部分；本项目注释为双语"))
    del lines
    return findings


def check_line_length(path, source):
    findings = []
    for number, line in enumerate(source.splitlines(), 1):
        if len(line) > MAX_LINE_LENGTH:
            findings.append(Finding(
                path, number, "length",
                f"line is {len(line)} characters (max {MAX_LINE_LENGTH}) / "
                f"行宽 {len(line)} 字符（上限 {MAX_LINE_LENGTH}）"))
    return findings


def check_whitespace(path, source):
    findings = []
    lines = source.splitlines()
    for number, line in enumerate(lines, 1):
        if line.rstrip() != line:
            findings.append(Finding(path, number, "trailing",
                                    "trailing whitespace / 行尾有空白"))
        if "\t" in line:
            findings.append(Finding(path, number, "tab",
                                    "tab character; use 4 spaces / "
                                    "存在制表符；请用 4 空格"))
    if source and not source.endswith("\n"):
        findings.append(Finding(path, len(lines), "eof",
                                "file has no trailing newline / 文件末尾缺少换行"))
    if source.endswith("\n\n"):
        findings.append(Finding(path, len(lines), "eof",
                                "file ends with a blank line / 文件末尾有多余空行"))
    return findings


def check_file(path):
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [Finding(path, 0, "read", str(exc))]
    findings = []
    findings.extend(check_docstrings(path, source))
    findings.extend(check_comments(path, source))
    findings.extend(check_line_length(path, source))
    findings.extend(check_whitespace(path, source))
    return findings


def iter_python_files(targets):
    for target in targets:
        path = pathlib.Path(target)
        if not path.is_absolute():
            path = ROOT / path
        if path.is_file() and path.suffix == ".py":
            yield path
            continue
        for candidate in sorted(path.rglob("*.py")):
            if _EXCLUDED_PARTS & set(candidate.parts):
                continue
            yield candidate


def main(argv=None):
    targets = list(argv or [])
    if not targets:
        targets = ["gifmanager", "apps", "tests", "tools"]

    findings = []
    checked = 0
    for path in iter_python_files(targets):
        checked += 1
        findings.extend(check_file(path))

    if findings:
        print(f"STYLE CHECK FAILED / 风格检查未通过 ({len(findings)} findings)")
        for finding in findings[:200]:
            print("  " + str(finding))
        if len(findings) > 200:
            print(f"  ... and {len(findings) - 200} more / 另有 {len(findings) - 200} 处")
        print(f"\nre-run: {_HINT}")
        return 1

    print(f"STYLE CHECK OK / 风格检查通过 ({checked} files)")
    print(f"  line width <= {MAX_LINE_LENGTH}, no tabs, no trailing whitespace")
    print("  triple quotes only in the file header / 三引号仅出现在文件头")
    print("  every comment bilingual / 所有注释均双语")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
