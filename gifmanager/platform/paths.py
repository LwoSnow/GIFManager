"""Per-user directory resolution.

This is the single entry point for "where does this user's data live". Each
public function asks the ACTIVE platform backend first and only falls back to
the generic POSIX/XDG rule when the backend does not override it, so
`gifmanager.platform.paths.user_data_dir()` answers with the running system's
convention (`%APPDATA%`, `~/Library/Application Support`, `$XDG_DATA_HOME`)
without any caller testing `sys.platform`.

The generic implementations are named `generic_*` on purpose: a module-level
function of the same name as the public one would shadow the dispatch, because
attribute lookup only reaches a module's `__getattr__` when the name is NOT
already in the module namespace.

按用户目录解析。

这是"该用户的数据放在哪里"的唯一入口。每个公开函数先询问"当前"平台后端，仅在后端
未覆盖时才回退到通用 POSIX/XDG 规则，因此
`gifmanager.platform.paths.user_data_dir()` 回答的是当前系统的约定
（`%APPDATA%`、`~/Library/Application Support`、`$XDG_DATA_HOME`），而无需任何
调用方判断 `sys.platform`。

通用实现刻意命名为 `generic_*`：与公开函数同名的模块级函数会遮蔽分发逻辑，因为
属性查找只有在名字"不在"模块命名空间时才会走到模块的 `__getattr__`。
"""
import os
import sys

# Directory name used under the per-user data root / 按用户数据根目录下使用的目录名
APP_DIR_NAME = "GIFManager"

# `sys.platform` value this module targets / 本模块面向的 `sys.platform` 取值
PLATFORM_KEY = sys.platform

# The per-user directory functions a backend may override /
# 后端可以覆盖的按用户目录函数
DISPATCHED_NAMES = (
    "home_dir",
    "user_data_dir",
    "user_config_dir",
    "user_cache_dir",
    "user_log_dir",
    "user_documents_dir",
    "temp_dir",
)


def _backend_override(name):
    # The active backend's own implementation, or None.
    #
    # The backend module's `__dict__` is consulted rather than `getattr`: this module
    # dispatches to the backend, so an attribute lookup that travelled back through the
    # module hook would resolve to the generic function and every override would be
    # silently cancelled.
    #
    # Whether the candidate IS a generic is decided by a MARKER attribute, not by
    # comparing function objects or `__module__` strings. Both of those were tried and
    # both failed on Linux:
    #
    #   * `__module__ != __name__` broke as soon as this module was loaded under a
    #     non-canonical name, because the generic function's `__module__` then did not
    #     equal `__name__` — so the generic function was accepted as its own override and
    #     `linux.user_data_dir` recursed until the interpreter gave up. Every path lookup
    #     on Linux became a RecursionError, so the application could not start there.
    #   * object identity broke when this module ended up in `sys.modules` under TWO
    #     names (a real possibility across `sys.path` entries that overlap), because the
    #     two copies have distinct function objects and the generic in one copy looks
    #     like a genuine override of the other.
    #
    # A marker travels WITH the function, so neither name nor identity matters.
    # 候选者"是否"为通用实现由"标记属性"决定，而不是比较函数对象或 `__module__` 字符串。
    # 两者都试过，且在 Linux 上都失败了：
    #
    #   * `__module__ != __name__` 在本模块以非规范名称加载时立刻失效，因为通用函数的
    #     `__module__` 此时不等于 `__name__`——于是通用函数被当成自己的覆盖接受，
    #     `linux.user_data_dir` 递归到解释器放弃。Linux 上每次路径查找都变成 RecursionError，
    #     应用在那里根本无法启动。
    #   * 对象身份在本模块最终以"两个"名称进入 `sys.modules` 时失效（在 `sys.path` 条目重叠
    #     时确实可能），因为两份拷贝的函数对象不同，一份里的通用函数看起来就像另一份的真实覆盖。
    #
    # 标记随函数本身传递，因此名称与身份都无关紧要。
    try:
        from gifmanager import platform as platform_layer

        module = platform_layer.current()._load()
    except Exception:
        # The platform layer is unavailable (a partial install, or an import cycle during
        # bring-up): the generic rules below are still correct on any POSIX system.
        # 平台层不可用（安装不完整，或初始化期间的导入环）：下面的通用规则在任意 POSIX 系统上
        # 仍然正确。
        return None
    candidate = module.__dict__.get(name)
    if not callable(candidate):
        return None
    if getattr(candidate, "_gifmanager_generic", False):
        return None
    return candidate


# ------------------------------------------------------- generic / 通用 ---

def generic_home_dir():
    # Home directory, resolved without `expanduser` (which ignores a `HOME`
    # override on Windows). / 主目录；不用 `expanduser`（它在 Windows 上会忽略
    # `HOME` 覆盖）。
    return (
        os.environ.get("HOME")
        or os.environ.get("USERPROFILE")
        or os.path.expanduser("~")
    )


def generic_user_data_dir():
    # Root for per-user configuration and data / 按用户配置与数据的根目录
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return os.path.join(xdg, APP_DIR_NAME)
    return os.path.join(generic_home_dir(), ".local", "share", APP_DIR_NAME)


def generic_user_config_dir():
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return os.path.join(xdg, APP_DIR_NAME)
    return os.path.join(generic_home_dir(), ".config", APP_DIR_NAME)


def generic_user_cache_dir():
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return os.path.join(xdg, APP_DIR_NAME)
    return os.path.join(generic_home_dir(), ".cache", APP_DIR_NAME)


def generic_user_log_dir():
    return os.path.join(generic_user_cache_dir(), "logs")


def generic_user_documents_dir():
    # XDG user directories are configured in `user-dirs.dirs`; the value of the
    # `XDG_DOCUMENTS_DIR` line is the answer.
    # XDG 用户目录配置在 `user-dirs.dirs` 中；`XDG_DOCUMENTS_DIR` 行的取值即为答案。
    config = os.path.normpath(
        os.path.join(generic_home_dir(), ".config", "user-dirs.dirs"))
    try:
        with open(config, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line.startswith("XDG_DOCUMENTS_DIR"):
                    continue
                _, _, value = line.partition("=")
                value = value.strip().strip('"').replace(
                    "$HOME", generic_home_dir())
                if value:
                    return value
    except OSError:
        pass
    return generic_home_dir()


def generic_temp_dir():
    # Temporary directory reserved for this application, kept separate from the
    # shared temp root so cleanup can be wholesale.
    # 本应用专用的临时目录。与共享临时根分离，便于整体清理。
    import tempfile

    return os.path.join(tempfile.gettempdir(), APP_DIR_NAME)


_GENERIC = {
    "home_dir": generic_home_dir,
    "user_data_dir": generic_user_data_dir,
    "user_config_dir": generic_user_config_dir,
    "user_cache_dir": generic_user_cache_dir,
    "user_log_dir": generic_user_log_dir,
    "user_documents_dir": generic_user_documents_dir,
    "temp_dir": generic_temp_dir,
}

# Tag every generic implementation so `_backend_override` can recognise one by looking at
# the FUNCTION rather than by comparing names or identities. A platform module that
# re-exports a generic (Linux does, for the paths that are plain XDG rules) therefore
# cannot be mistaken for providing a real override.
#
# 给每个通用实现打标记，使 `_backend_override` 能通过查看"函数本身"来识别它，而不是比较名称或
# 身份。因此一个重新导出通用实现的平台模块（Linux 就是这样，那些路径本就是纯 XDG 规则）不会被
# 误认为提供了真实覆盖。
for _generic_function in _GENERIC.values():
    _generic_function._gifmanager_generic = True
del _generic_function


# ------------------------------------------------------ dispatch / 分发 ---

def resolve(name):
    # Implementation of `name` for the running system: the backend's when it
    # provides one, otherwise the generic rule. / `name` 在当前系统上的实现：
    # 后端提供了就用它，否则用通用规则。
    if name not in _GENERIC:
        raise KeyError(name)
    return _backend_override(name) or _GENERIC[name]


def call(name):
    return resolve(name)()


def home_dir():
    return call("home_dir")


def user_data_dir():
    return call("user_data_dir")


def user_config_dir():
    return call("user_config_dir")


def user_cache_dir():
    return call("user_cache_dir")


def user_log_dir():
    return call("user_log_dir")


def user_documents_dir():
    return call("user_documents_dir")


def temp_dir():
    return call("temp_dir")


def backend_name():
    # Name of the backend providing these directories, for diagnostics /
    # 提供这些目录的后端名称，供诊断使用
    try:
        from gifmanager import platform as platform_layer

        return platform_layer.current()._load().__name__
    except Exception:
        return __name__ + " (generic)"


register = None  # backends register services, not paths / 后端注册服务而非路径


__all__ = [
    "APP_DIR_NAME",
    "DISPATCHED_NAMES",
    "PLATFORM_KEY",
    "backend_name",
    "call",
    "generic_home_dir",
    "generic_temp_dir",
    "generic_user_cache_dir",
    "generic_user_config_dir",
    "generic_user_data_dir",
    "generic_user_documents_dir",
    "generic_user_log_dir",
    "home_dir",
    "resolve",
    "temp_dir",
    "user_cache_dir",
    "user_config_dir",
    "user_data_dir",
    "user_documents_dir",
    "user_log_dir",
]
