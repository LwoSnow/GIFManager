"""Platform layer — the only place that knows which OS the code is running on.

`gifmanager.platform` exposes two things:

* `paths` — a module of per-user directory functions, correct for the running
  system (the Windows and macOS backends override the generic POSIX rules);
* `current()` — a `Platform` object whose `service(...)` accessors hand out the
  native service implementations, falling back to safe no-ops when the running
  system cannot provide one.

Callers never import `gifmanager.platform.windows` directly, and never test
`sys.platform`. That keeps every OS-specific branch in exactly one file per
system, which is what makes a new platform an additive change.

平台层——代码中唯一知道自己运行在哪个系统上的地方。

`gifmanager.platform` 暴露两样东西：

* `paths` —— 按用户目录函数的模块，对当前系统正确（Windows 与 macOS 后端覆盖
  通用的 POSIX 规则）；
* `current()` —— 一个 `Platform` 对象，其 `service(...)` 访问器发放原生服务实现，
  当前系统无法提供时回退到安全的空操作。

调用方绝不直接导入 `gifmanager.platform.windows`，也绝不做 `sys.platform` 判断。
这使每个系统的专有分支都只存在于该系统的一个文件里，新增平台因此是纯增量改动。
"""
from gifmanager.platform import paths
from gifmanager.platform.base import (
    PLATFORM_MODULES,
    AutostartBackend,
    ClipboardBackend,
    GpuPreferenceBackend,
    HotkeyBackend,
    InputBackend,
    Platform,
    SingleInstanceBackend,
    UnsupportedOperation,
    WindowBackend,
    current_key,
)

# Service name -> abstract base class. The order here is also the order used by
# `describe()` and by the diagnostics report.
# 服务名 -> 抽象基类。此处的顺序也是 `describe()` 与诊断报告使用的顺序。
SERVICE_TYPES = {
    "hotkeys": HotkeyBackend,
    # Global scroll capture is a separate service because a platform may
    # provide one and not the other (Wayland offers neither).
    # 全局滚动捕获是独立服务，因为某平台可能提供其一而不提供另一个（Wayland
    # 两者都不提供）。
    "scroll": HotkeyBackend,
    "clipboard": ClipboardBackend,
    "input": InputBackend,
    "gpu_preference": GpuPreferenceBackend,
    "autostart": AutostartBackend,
    "window": WindowBackend,
    "single_instance": SingleInstanceBackend,
}

_platform = None

# Path functions the active backend may override. Resolved through the backend
# module the same way services are, so `gifmanager.platform.paths.user_data_dir()`
# answers with the RUNNING system's convention (`%APPDATA%`, `~/Library/...`,
# `$XDG_DATA_HOME`) rather than the generic POSIX default.
# 当前后端可以覆盖的路径函数。它们与服务一样经后端模块解析，因此
# `gifmanager.platform.paths.user_data_dir()` 回答的是"当前系统"的约定
# （`%APPDATA%`、`~/Library/...`、`$XDG_DATA_HOME`），而不是通用 POSIX 默认值。
PATH_FUNCTIONS = (
    "user_data_dir", "user_config_dir", "user_cache_dir", "user_log_dir",
    "user_documents_dir", "temp_dir", "home_dir",
)


# The active platform backend, created on first use and cached for the process.
# 当前平台后端，首次使用时创建并在进程内缓存。
def current():
    global _platform
    if _platform is None:
        key = current_key()
        # The backend module is imported on first use, not at package import:
        # a Windows checkout must never touch X11 code, and vice versa.
        # 后端模块在首次使用时导入而非包导入时：Windows 上的代码绝不碰 X11，反之
        # 亦然。
        _platform = Platform(key if key in PLATFORM_MODULES else "generic")
        _platform._load()
    return _platform


def path_function(name):
    # The running system's implementation of a per-user directory function,
    # falling back to the generic POSIX rule when the backend does not override
    # it.
    #
    # The backend's OWN module dictionary is consulted, not `getattr` on the
    # backend: `gifmanager.platform.paths` defines a module-level `__getattr__`
    # hook that resolves these same names through this function, so an
    # attribute lookup would return the generic implementation and the hook
    # would silently undo every backend override.
    # 查的是后端"自身"的模块字典，而不是对后端用 `getattr`：
    # `gifmanager.platform.paths` 定义了模块级 `__getattr__` 钩子，它会经本函数
    # 解析这些同名对象，因此属性查找会返回通用实现，钩子会静默抵消每一个后端覆盖。
    module = current()._load()
    override = module.__dict__.get(name)
    if callable(override):
        return override
    return getattr(paths, name)


# True when the running system has a dedicated backend module /
# 当前系统有专用后端模块时为 True
def is_supported():
    return current_key() in PLATFORM_MODULES


# Native module implementing the running system's services /
# 实现当前系统服务的原生模块
def backend_module():
    return current()._load()


def service(name):
    # Resolve a native service by name, creating it once per process /
    # 按名称解析原生服务，每进程只创建一次
    base_class = SERVICE_TYPES[name]
    return current().service(name, base_class)


def hotkeys():
    return service("hotkeys")


def scroll():
    # Global scroll capture. Separate from `hotkeys()` because a platform may
    # support one and not the other (Wayland supports neither).
    # 全局滚动捕获。与 `hotkeys()` 分开，因为某平台可能支持其一而不支持另一个
    # （Wayland 两者都不支持）。
    return service("scroll")


def clipboard():
    return service("clipboard")


def input_backend():
    return service("input")


def gpu_preference():
    return service("gpu_preference")


def autostart():
    return service("autostart")


def window():
    return service("window")


def single_instance():
    return service("single_instance")


def describe():
    # Diagnostics table: which services the running system actually provides.
    # Used by the settings dialog's "system information" section and by tests.
    # 诊断表：当前系统实际提供哪些服务。供设置界面的"系统信息"区块与测试使用。
    active = current()
    rows = []
    for name in SERVICE_TYPES:
        implemented = active.implements(name)
        instance = service(name)
        rows.append({
            "service": name,
            "implemented": implemented,
            "backend": getattr(instance, "name", "unknown"),
            "available": bool(getattr(instance, "available", False)),
        })
    return {
        "platform_key": active.key,
        "backend_module": active._load().__name__,
        "services": rows,
    }


def reset_for_tests():
    # Drop the cached backend so a test can swap `Platform.REGISTRY` entries.
    # 丢弃缓存的后端，使测试可以替换 `Platform.REGISTRY` 中的条目。
    global _platform
    _platform = None


__all__ = [
    "PATH_FUNCTIONS",
    "PLATFORM_MODULES",
    "SERVICE_TYPES",
    "UnsupportedOperation",
    "autostart",
    "backend_module",
    "clipboard",
    "current",
    "describe",
    "gpu_preference",
    "hotkeys",
    "input_backend",
    "is_supported",
    "path_function",
    "paths",
    "reset_for_tests",
    "scroll",
    "service",
    "single_instance",
    "window",
]
