"""Resource and data location resolution.

Every path decision that depends on HOW the application is running (source
checkout vs. a frozen bundle) or on the USER (XDG dirs, per-user config) lives
here, so `gifmanager.core` stays free of `sys.frozen` and `%LOCALAPPDATA%`
style checks. OS-specific directory rules are asked of
`gifmanager.platform.paths`; this module only composes them.

资源与数据位置解析。

所有取决于"程序如何运行"（源码目录 vs 冻结打包）或"用户是谁"（XDG 目录、
用户配置）的路径决策都集中在此，使 `gifmanager.core` 不再出现 `sys.frozen`
与 `%LOCALAPPDATA%` 之类的判断。系统专有的目录规则向
`gifmanager.platform.paths` 查询，本模块只做组合。
"""
import os
import sys

# Environment variable that overrides the data directory. Useful for portable
# installs, tests, and running several profiles side by side.
# 覆盖数据目录的环境变量。便于便携安装、测试，以及并行运行多套配置。
DATA_DIR_ENV = "GIFMANAGER_DATA_DIR"

# Cached platform path functions, keyed by function name. Cached because
# `data_dir()` and `logs_dir()` are called on hot paths and resolving the
# backend module on every call would add import machinery to a path lookup.
# 按函数名缓存的平台路径函数。之所以缓存，是因为 `data_dir()` 与 `logs_dir()`
# 在热路径上被调用，而每次调用都解析后端模块会给一次路径查询加上导入机制开销。
_path_functions = {}

# Per-user directory resolver installed by the application at startup, supplied
# by `gifmanager.platform.paths`. It is injected rather than imported because
# `core` must not depend on the platform layer — the dependency would point
# upwards and make the core untestable without an OS backend.
#
# Until it is installed, the generic POSIX/XDG rules below apply, which is what
# lets `core.paths` work in a unit test that never builds a backend.
# 由应用在启动时安装的按用户目录解析器，来源是 `gifmanager.platform.paths`。以注入
# 方式提供而非导入，因为 `core` 不得依赖平台层——那会让依赖指向"上方"，并使核心层
# 在没有系统后端时无法测试。
#
# 安装之前使用下面通用的 POSIX/XDG 规则，这正是让 `core.paths` 能在从不构建后端的
# 单元测试里工作的原因。
_path_resolver = None


def install_path_resolver(resolver):
    # Adopt a per-user directory resolver and drop the memoised lookups.
    #
    # `resolver(name)` returns the running system's implementation of one of
    # `RESOLVED_NAMES`. Called once from `backend.create_backend`.
    # 采用一个按用户目录解析器并丢弃已记忆的查找结果。
    #
    # `resolver(name)` 返回当前系统对 `RESOLVED_NAMES` 中某一项的实现。由
    # `backend.create_backend` 调用一次。
    global _path_resolver
    _path_resolver = resolver
    _path_functions.clear()


# Names a resolver is asked for / 向解析器请求的名称
RESOLVED_NAMES = ("user_data_dir", "user_log_dir")


def _generic_home_dir():
    return (
        os.environ.get("HOME")
        or os.environ.get("USERPROFILE")
        or os.path.expanduser("~")
    )


def _generic_user_data_dir():
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return os.path.join(xdg, "GIFManager")
    return os.path.join(_generic_home_dir(), ".local", "share", "GIFManager")


def _generic_user_log_dir():
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = xdg or os.path.join(_generic_home_dir(), ".cache")
    return os.path.join(base, "GIFManager", "logs")


_GENERIC_PATHS = {
    "user_data_dir": _generic_user_data_dir,
    "user_log_dir": _generic_user_log_dir,
}


# Resolve one per-user directory function, preferring the installed resolver /
# 解析一个按用户目录函数，优先使用已安装的解析器
def platform_path(name):
    if name in _path_functions:
        return _path_functions[name]()
    function = None
    if _path_resolver is not None:
        try:
            function = _path_resolver(name)
        except Exception:
            function = None
    if function is None:
        function = _GENERIC_PATHS.get(name, _generic_user_data_dir)
    _path_functions[name] = function
    return function()


# True when running from a PyInstaller (or similar) bundle.
# 处于 PyInstaller（或同类）打包运行状态时为 True。
def is_frozen():
    return bool(getattr(sys, "frozen", False))


# Directory holding the running executable (or the interpreter when frozen is
# False). Used as the anchor for portable layouts.
# 运行中可执行文件所在目录（未打包时为解释器所在目录）。便携布局以此为锚点。
def executable_dir():
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Directory holding the importable `gifmanager` package.
# 可导入的 `gifmanager` 包所在目录。
def package_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Project root when running from a source checkout, i.e. the directory that
# contains `gifmanager/`, `resources/` and `apps/`.
# 源码运行时的项目根目录，即包含 `gifmanager/`、`resources/` 与 `apps/` 的目录。
def project_root():
    return os.path.dirname(package_dir())


# Read-only bundled resources (translations, icons, ffmpeg).
# Order: an explicit override, then the frozen bundle's `_internal`, then the
# source checkout's `resources/`, finally the executable's own directory.
# 只读的随包资源（翻译、图标、ffmpeg）。
# 顺序：显式覆盖 → 冻结包的 `_internal` → 源码目录的 `resources/` →
# 可执行文件同级目录。
def resources_dir():
    override = os.environ.get("GIFMANAGER_RESOURCES_DIR")
    if override:
        return os.path.abspath(override)
    candidates = []
    if is_frozen():
        exe_dir = executable_dir()
        candidates.append(os.path.join(exe_dir, "_internal", "resources"))
        candidates.append(os.path.join(exe_dir, "resources"))
    root = project_root()
    candidates.append(os.path.join(root, "resources"))
    for candidate in candidates:
        if os.path.isdir(candidate):
            return candidate
    return candidates[-1]


# Translation files directory / 翻译文件目录
def language_dir():
    return os.path.join(resources_dir(), "language")


# Icons directory / 图标目录
def icons_dir():
    return os.path.join(resources_dir(), "icons")


# Writable application data directory (database + emoji files).
#
# Resolution order:
#   1. `GIFMANAGER_DATA_DIR`, when set (portable installs and tests);
#   2. `<executable dir>/data` when frozen — a portable bundle keeps its data
#      beside the executable;
#   3. the per-user application data directory reported by the platform layer;
#   4. the current working directory, as a last resort.
# The first candidate that can actually be created wins, so an install under
# Program Files (not writable) silently falls back instead of crashing.
#
# 可写的应用数据目录（数据库 + 表情文件）。
#
# 解析顺序：
#   1. 设置了 `GIFMANAGER_DATA_DIR` 时用它（便携安装与测试）；
#   2. 冻结运行时用 `<可执行文件目录>/data`——便携包把数据放在程序旁边；
#   3. 平台层给出的按用户应用数据目录；
#   4. 兜底用当前工作目录。
# 取第一个真正能创建的候选目录，因此安装在 Program Files（不可写）时会静默
# 回退而不是崩溃。
def data_dir():
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        override = os.path.abspath(override)
        os.makedirs(override, exist_ok=True)
        return override

    candidates = []
    if is_frozen():
        candidates.append(os.path.join(executable_dir(), "data"))

    # Imported lazily: `core.paths` is also used by the platform layer's own
    # tests, where a platform backend may not be selectable yet.
    # 延迟导入：平台层自身的测试也会用到 `core.paths`，那时可能还没选定后端。
    candidates.append(platform_path("user_data_dir"))

    candidates.append(os.path.join(os.getcwd(), "data"))

    for candidate in candidates:
        try:
            os.makedirs(candidate, exist_ok=True)
        except OSError:
            continue
        if os.path.isdir(candidate):
            return candidate
    return candidates[-1]


# Emoji files directory (one sub-directory per group) /
# 表情文件目录（每个分组一个子目录）
def emojis_dir(base=None):
    return os.path.join(base or data_dir(), "emojis")


# SQLite database path / SQLite 数据库路径
def database_path(base=None):
    return os.path.join(base or data_dir(), "emoji.db")


# Writable log directory.
#
# The per-user log location comes FIRST, not `<data dir>/logs`: on Windows the
# data directory is `%APPDATA%` (roaming), and roaming a few hundred megabytes
# of scroll logs is exactly what roaming profiles are not for. The platform
# layer answers `%LOCALAPPDATA%`, `~/Library/Logs` or `$XDG_CACHE_HOME`
# respectively. The data directory and the system temp directory remain as
# fallbacks, so logging never becomes the reason the application fails to start.
# 可写日志目录。
#
# 按用户的日志位置放在"最前"，而不是 `<数据目录>/logs`：Windows 上数据目录是
# `%APPDATA%`（漫游），让几百兆滚动日志参与漫游恰是漫游配置文件不该做的事。平台层
# 分别回答 `%LOCALAPPDATA%`、`~/Library/Logs` 或 `$XDG_CACHE_HOME`。数据目录与
# 系统临时目录保留为兜底，使日志永远不会成为程序启动失败的原因。
def logs_dir():
    candidates = [platform_path("user_log_dir")]
    candidates.append(os.path.join(data_dir(), "logs"))

    import tempfile

    candidates.append(os.path.join(tempfile.gettempdir(), "GIFManager", "logs"))

    for candidate in candidates:
        try:
            os.makedirs(candidate, exist_ok=True)
        except OSError:
            continue
        if os.path.isdir(candidate):
            return candidate
    return candidates[-1]


__all__ = [
    "DATA_DIR_ENV",
    "RESOLVED_NAMES",
    "data_dir",
    "database_path",
    "emojis_dir",
    "executable_dir",
    "icons_dir",
    "install_path_resolver",
    "is_frozen",
    "language_dir",
    "logs_dir",
    "package_dir",
    "platform_path",
    "project_root",
    "resources_dir",
]
