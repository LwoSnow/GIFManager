"""Mechanical check of the layering rule.

The architecture's one hard rule is that `gifmanager/core/` must not know about a
GUI toolkit or an operating system. That is easy to state and easy to violate by
accident, so it is checked by parsing the source rather than by review.

Exit code 0 when the rule holds, 1 otherwise, so it can gate a commit or CI.

分层规则的机械检查。

架构唯一一条硬规则是：`gifmanager/core/` 不得知道界面工具包或操作系统的存在。
这条规则容易陈述、却容易被无意破坏，因此用解析源码来检查，而不是靠人工评审。

规则成立时退出码 0，否则 1，因此可以用它把守提交或 CI。
"""
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "gifmanager"

# Importing the package's own modules requires the repository root on the path;
# the check also runs from a plain `python tools/check_layers.py` invocation.
# 导入本包自己的模块需要仓库根在路径上；本检查也会以
# `python tools/check_layers.py` 这种普通方式运行。
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Rules: directory -> what may not appear in its modules.
# 规则：目录 -> 其中模块不得出现的内容。
FORBIDDEN_IN_CORE = {
    # GUI toolkits / 界面工具包
    "PySide6": "a GUI toolkit",
    "PyQt5": "a GUI toolkit",
    "PyQt6": "a GUI toolkit",
    "shiboken6": "a GUI toolkit binding",
    # OS-specific modules / 系统专有模块
    "ctypes": "an OS-specific native-call module",
    "winreg": "a Windows-only module",
    "msvcrt": "a Windows-only module",
    "winsound": "a Windows-only module",
    "pwd": "a POSIX-only module",
    "grp": "a POSIX-only module",
    "termios": "a POSIX-only module",
}

# Attributes that are effectively platform checks even without `sys.platform`.
# 即使不写 `sys.platform` 也等同于平台判断的属性。
FORBIDDEN_ATTRIBUTES_IN_CORE = {
    "os.startfile": "a Windows-only call",
    "os.uname": "a POSIX-only call",
    "sys.frozen": "a packaging-state check",
}

# Attribute chains that are allowed despite looking like a platform check.
# 看起来像平台判断、但允许出现的属性链。
ALLOWED_ATTRIBUTES_IN_CORE = {
    # The retry policy is per-platform because the FILESYSTEM is: on Windows an
    # open handle blocks unlink, on POSIX it does not. The choice affects
    # performance only, never correctness, so it is the one documented exception.
    # 重试策略按平台区分，是因为"文件系统"如此：Windows 上打开的句柄会阻塞删除，
    # POSIX 上不会。该选择只影响性能、绝不影响正确性，因此是唯一一处记录在案的例外。
    "os.name",
}

# Layer import rules beyond core: module path prefix -> what it may not import.
# 核心之外的分层导入规则：模块路径前缀 -> 不得导入的内容。
LAYER_RULES = (
    # core may not import any other layer of this project /
    # core 不得导入本项目任何其他层
    ("gifmanager/core/", ("gifmanager.platform", "gifmanager.backend",
                          "gifmanager.frontend")),
    # platform may not import backend or the front-end /
    # platform 不得导入 backend 或前端
    ("gifmanager/platform/", ("gifmanager.backend", "gifmanager.frontend")),
    # backend may not import the front-end /
    # backend 不得导入前端
    ("gifmanager/backend/", ("gifmanager.frontend",)),
)


def dotted_name(node):
    # Full dotted name of an Attribute/Name chain, or None /
    # Attribute/Name 链的完整点分名，无法判断时返回 None
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def imported_modules(tree):
    # Every module named by an import statement, plus the module of every
    # `from ... import ...`. / 每个 import 语句涉及的模块，以及每个
    # `from ... import ...` 的来源模块。
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.append((node.module, node.lineno))
    return found


def check_module(path):
    problems = []
    relative = path.relative_to(ROOT).as_posix()
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{relative}: cannot read ({exc})"]
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [f"{relative}:{exc.lineno}: syntax error ({exc.msg})"]

    in_core = relative.startswith("gifmanager/core/")

    # Import rules / 导入规则
    for module, lineno in imported_modules(tree):
        top = module.split(".")[0]
        if in_core and top in FORBIDDEN_IN_CORE:
            problems.append(
                f"{relative}:{lineno}: core imports {module!r}, which is "
                f"{FORBIDDEN_IN_CORE[top]} / core 导入了 {module!r}，它是"
                f"{FORBIDDEN_IN_CORE[top]}")
        for prefix, forbidden in LAYER_RULES:
            if not relative.startswith(prefix):
                continue
            for banned in forbidden:
                if module == banned or module.startswith(banned + "."):
                    problems.append(
                        f"{relative}:{lineno}: {prefix.rstrip('/')} must not "
                        f"import {module!r} / {prefix.rstrip('/')} 不得导入 "
                        f"{module!r}")

    # Attribute rules and `sys.platform` checks / 属性规则与 `sys.platform` 判断
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            name = dotted_name(node)
            if name is None:
                continue
            if in_core:
                if name == "sys.platform":
                    problems.append(
                        f"{relative}:{node.lineno}: core tests sys.platform; "
                        f"ask gifmanager.platform instead / core 判断了 "
                        f"sys.platform；应改问 gifmanager.platform")
                elif name in FORBIDDEN_ATTRIBUTES_IN_CORE:
                    problems.append(
                        f"{relative}:{node.lineno}: core uses {name}, which is "
                        f"{FORBIDDEN_ATTRIBUTES_IN_CORE[name]} / core 使用了 "
                        f"{name}，它是{FORBIDDEN_ATTRIBUTES_IN_CORE[name]}")
                elif name == "os.name" and name not in ALLOWED_ATTRIBUTES_IN_CORE:
                    problems.append(
                        f"{relative}:{node.lineno}: core uses os.name")
    return problems


def check_platform_backends():
    # Every registered backend module must exist and expose SERVICES.
    # 每个已注册的后端模块都必须存在并暴露 SERVICES。
    problems = []
    from gifmanager.platform.base import PLATFORM_MODULES

    for key, module in PLATFORM_MODULES.items():
        parts = module.split(".")
        path = ROOT.joinpath(*parts).with_suffix(".py")
        if not path.is_file():
            problems.append(
                f"platform: {key} maps to {module}, but {path.name} is missing "
                f"/ platform：{key} 映射到 {module}，但文件缺失")
            continue
        source = path.read_text(encoding="utf-8")
        if "SERVICES = {" not in source:
            problems.append(
                f"{path.relative_to(ROOT).as_posix()}: does not define SERVICES "
                f"/ 未定义 SERVICES")
    return problems


def check_no_toolkit_outside_frontend():
    # Only the front-end may import a GUI toolkit /
    # 只有前端可以导入界面工具包
    problems = []
    for path in sorted(PACKAGE.rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith("gifmanager/frontend/"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        for module, lineno in imported_modules(tree):
            if module.split(".")[0] in ("PySide6", "PyQt5", "PyQt6"):
                problems.append(
                    f"{relative}:{lineno}: only gifmanager/frontend may import "
                    f"a GUI toolkit / 只有 gifmanager/frontend 可以导入界面工具包")
    return problems


def main(argv=None):
    problems = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        problems.extend(check_module(path))
    problems.extend(check_platform_backends())
    problems.extend(check_no_toolkit_outside_frontend())

    if problems:
        print("LAYER CHECK FAILED / 分层检查未通过")
        for problem in problems:
            print("  " + problem)
        print(f"\n{len(problems)} problem(s) / {len(problems)} 处问题")
        return 1

    print("LAYER CHECK OK / 分层检查通过")
    print("  core: no GUI toolkit, no OS-specific module, no sys.platform "
          "/ core：无界面工具包、无系统专有模块、无 sys.platform 判断")
    print("  platform: no backend or front-end import "
          "/ platform：不导入 backend 或前端")
    print("  backend: no front-end import / backend：不导入前端")
    print("  GUI toolkit confined to gifmanager/frontend "
          "/ 界面工具包仅出现在 gifmanager/frontend")
    return 0


if __name__ == "__main__":
    sys.exit(main())
