# Version parsing and comparison utilities for the updater.
# 更新器用的版本号解析与比较工具。
import re

# Installer file name pattern: GIFManager-Setup-a.b.c.exe /
# 安装包文件名模式：GIFManager-Setup-a.b.c.exe
_SETUP_NAME_RE = re.compile(
    r"GIFManager-Setup-(\d+)\.(\d+)\.(\d+)\.exe$", re.IGNORECASE)


# Parse "a.b.c" into a tuple (a, b, c); None when invalid.
# 把 "a.b.c" 解析为元组 (a, b, c)；非法时返回 None。
def parse_version(text):
    if not isinstance(text, str):
        return None
    m = re.fullmatch(r"\s*(\d+)\.(\d+)\.(\d+)\s*", text)
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


# Compare two versions. Priority: a > b > c. Returns -1/0/1.
# Accepts tuples or strings. 比较两个版本号，优先级 a>b>c，返回 -1/0/1。
# 接受元组或字符串。
def cmp_version(v1, v2):
    t1 = parse_version(v1) if isinstance(v1, str) else v1
    t2 = parse_version(v2) if isinstance(v2, str) else v2
    if t1 is None or t2 is None:
        raise ValueError(f"invalid version: {v1!r} vs {v2!r}")
    for x, y in zip(t1, t2):
        if x < y:
            return -1
        if x > y:
            return 1
    return 0


# Extract the version tuple from an installer file name like
# GIFManager-Setup-1.0.1.exe; None when the name does not match.
# 从安装包文件名（如 GIFManager-Setup-1.0.1.exe）提取版本元组；
# 不匹配时返回 None。
def parse_setup_name(name):
    if not isinstance(name, str):
        return None
    m = _SETUP_NAME_RE.search(name.strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
