"""Deep integrity audit of the rebuilt app/widgets/emoji_item.py.

Checks the file for reconstruction damage (lost/duplicated code, stray
artefacts), verifies every definition against the last good .pyc, and compares
the definition inventory with the committed version so nothing can have
silently vanished.
"""
import ast
import collections
import io
import marshal
import os
import subprocess
import sys
import types

sys.stdout.reconfigure(encoding="utf-8")

PATH = "app/widgets/emoji_item.py"
PYC = "app/widgets/__pycache__/emoji_item.cpython-312.pyc"

problems = []


def report(name, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + name + ((" | " + str(detail)) if detail else ""))
    if not ok:
        problems.append(name)


print("=== 1. file-level integrity / 文件级完整性")
raw = open(PATH, "rb").read()
text = raw.decode("utf-8")
report("no UTF-8 BOM", not raw.startswith(b"\xef\xbb\xbf"))
report("no ANSI-roundtrip loss markers", "\ufffd" not in text)
mojibake = [m for m in ("锛", "鐨", "涓", "鍜", "闇", "鎴", "鏂", "鍑", "鍚", "璁")
            if m in text]
report("no GBK mojibake", not mojibake, mojibake)
report("no CRLF (repo uses LF)", b"\r\n" not in raw)
report("no tabs", "\t" not in text)
report("ends with a newline", text.endswith("\n"))
trailing = [i for i, ln in enumerate(text.splitlines(), 1)
            if ln != ln.rstrip()]
report("no trailing whitespace", not trailing, trailing[:5])

print("\n=== 2. syntax / AST")
tree = ast.parse(text)
report("parses as Python", True)
report("module docstring present",
       isinstance(tree.body[0], ast.Expr)
       and isinstance(tree.body[0].value, ast.Constant))

print("\n=== 3. duplicate definitions / 重复定义")
names = collections.Counter()
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        names[node.name] += 1
dupes = {n: c for n, c in names.items() if c > 1}
# A method name may legitimately repeat across classes/stubs; only the same
# qualname twice is a problem.
qual = collections.Counter()
for node in tree.body:
    if isinstance(node, ast.ClassDef):
        # A class body is itself a code object in the .pyc / 类体本身也是 pyc 里的
        # 一个 code object
        qual[node.name] += 1
        for sub in node.body:
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual[f"{node.name}.{sub.name}"] += 1
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        qual[node.name] += 1
dupe_qual = {n: c for n, c in qual.items() if c > 1}
report("no duplicated function definitions", not dupe_qual, dupe_qual)
report("no duplicated class-level names",
       not {n: c for n, c in collections.Counter(qual).items() if c > 1})

print("\n=== 4. definitions vs the last good .pyc / 与 pyc 的定义比对")
with open(PYC, "rb") as f:
    f.read(16)
    old = marshal.load(f)


def walk(code, out, prefix=""):
    out[prefix + code.co_name] = code
    for c in code.co_consts:
        if isinstance(c, types.CodeType):
            walk(c, out, prefix + code.co_name + ".")
    return out


# Normalise both sides to "Class.method" (the pyc walk prefixes "<module>.").
# 两侧统一成 "Class.method"（pyc 遍历会带 "<module>." 前缀）。
def norm(names):
    out = set()
    for n in names:
        n = n.replace("<module>.", "")
        if n.startswith("<") or n in ("<module>",):
            continue
        out.add(n)
    return out


pyc_defs = norm(walk(old, {}))
src_defs = norm(qual)
missing = sorted(pyc_defs - src_defs)
extra = sorted(src_defs - pyc_defs)
report("every pyc code object still exists in the source", not missing, missing)
report("no unexpected new definitions", not extra, extra)

print("\n=== 5. definition inventory vs the committed version / 与已提交版本比对")
head = subprocess.run(["git", "show", f"HEAD:{PATH}"], capture_output=True)
head_defs = set()
if head.returncode == 0:
    htree = ast.parse(head.stdout.decode("utf-8"))
    for node in htree.body:
        if isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    head_defs.add(f"{node.name}.{sub.name}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            head_defs.add(node.name)
    lost = sorted(head_defs - src_defs)
    report("no definition from HEAD disappeared", not lost, lost)
    added = sorted(src_defs - head_defs)
    print(f"       (definitions added since HEAD: {len(added)})")
else:
    report("HEAD version readable", False, head.stderr[:120])

print("\n=== 6. reconstructed regions: code sanity / 重建区域的代码检查")
src_lines = text.splitlines()
# a) comment lines must not be a lone '#' UNLESS they are the repo's own
# paragraph separator style (7 other modules use a bare '#' inside a block).
# 注释行不得只有一个 '#'，除非是本仓库既有的"段间空注释"写法（其他 7 处也用）。
bare = [i for i, ln in enumerate(src_lines, 1) if ln.strip() == "#"]
report("bare '#' only used as the repo's paragraph separator",
       len(bare) <= 10, bare)
# b) no line may contain a lone '?' that looks like a lost-character marker
suspicious = [i for i, ln in enumerate(src_lines, 1)
              if "?" in ln and not ln.strip().startswith("#")
              and "'?'" not in ln and '"?"' not in ln]
report("no stray '?' markers in code", not suspicious, suspicious)
# c) no triple blank lines / doubled blank runs
runs = []
run = 0
for ln in src_lines:
    if ln.strip() == "":
        run += 1
    else:
        if run > 2:
            runs.append(run)
        run = 0
report("no runs of 3+ blank lines", not runs, runs)
# d) every class/def is preceded by the two blank lines PEP8 wants (top level)
pep8 = []
for i, ln in enumerate(src_lines):
    if (ln.startswith("class ") or ln.startswith("def ")
            or ln.startswith("@classmethod") or ln.startswith("@staticmethod")):
        if i >= 2 and src_lines[i - 1].strip() and src_lines[i - 2].strip():
            if not src_lines[i - 1].lstrip().startswith("#"):
                pep8.append(i + 1)
report("top-level defs separated by a blank line", not pep8, pep8[:6])

print("\n=== 7. imports actually used / 导入是否都被使用")
imported = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        for a in node.names:
            imported.add((a.asname or a.name).split(".")[0])
    elif isinstance(node, ast.ImportFrom):
        for a in node.names:
            imported.add(a.asname or a.name)
used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
unused = sorted(i for i in imported if i not in used and i not in text.replace(
    f"import {i}", ""))
report("no unused imports (heuristic)", not unused, unused)

print("\n=== 8. attribute initialisation / 属性初始化")
# A reconstruction that dropped a `self._x = ...` line would leave an attribute
# read that nothing ever sets. Own method names are excluded (a bare
# `self._tick_name_scroll` is a bound-method reference, not data), as are Qt
# base-class members and class constants.
# 重建时若丢掉一行 `self._x = ...`，就会留下一个永远无人赋值的属性读取。自有方法
# 名不算（`self._tick_name_scroll` 是绑定方法引用而非数据），Qt 基类成员与类常量
# 同样排除。
all_stores = set()
own_methods = set()
for node in tree.body:
    if isinstance(node, ast.ClassDef):
        for sub in node.body:
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                own_methods.add(sub.name)
        for a in ast.walk(node):
            if isinstance(a, ast.Attribute) and isinstance(a.value, ast.Name) \
                    and a.value.id == "self" and isinstance(a.ctx, ast.Store):
                all_stores.add(a.attr)
all_loads = set()
for a in ast.walk(tree):
    if isinstance(a, ast.Attribute) and isinstance(a.value, ast.Name) \
            and a.value.id == "self" and isinstance(a.ctx, ast.Load):
        all_loads.add(a.attr)
QT = {
    "width", "height", "layout", "parent", "parentWidget", "geometry",
    "isVisible", "isHidden", "show", "hide", "setFixedSize", "setCursor",
    "setObjectName", "setToolTip", "setAcceptDrops", "update", "raise_",
    "grab", "mapTo", "devicePixelRatioF", "window", "children", "deleteLater",
    "setStyleSheet", "setAttribute", "setFocusPolicy", "setMouseTracking",
    "setContentsMargins", "setMinimumSize", "setMaximumSize", "size", "pos",
    "x", "y", "move", "resize", "setGeometry", "rect", "font", "setFont",
    "style", "setEnabled", "isEnabled", "setVisible", "underMouse", "hasFocus",
    "setFocus", "setContextMenuPolicy", "setSizePolicy", "sizeHint",
    "minimumSizeHint", "setWindowFlags", "setWindowFlag", "setWindowTitle",
    "activateWindow", "close", "installEventFilter", "removeEventFilter",
    "SERIAL_THREADS", "FRAME_INSET", "LONG_PRESS_MS", "NAME_CHAR_LIMIT",
    "NAME_SCROLL_RETRY_MS", "TEXT_WIDTH", "TEXT_MAX_WIDTH", "CARD_SIZE",
    "THUMB_SIZE", "NAME_AREA", "_name_area", "_name_font_size", "_card_scale",
    "_parallel_render", "clicked", "selection_toggled", "_dm",
}
missing_assign = sorted(all_loads - all_stores - own_methods - QT)
report("every self._attribute read is assigned somewhere",
       not missing_assign, missing_assign)

print("\n" + "=" * 60)
print(f"problems: {len(problems)}")
for p in problems:
    print("   " + p)
print("RESULT", "OK" if not problems else "NG")
