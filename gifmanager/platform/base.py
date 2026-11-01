"""Platform interface definitions.

A platform backend is a module (`gifmanager.platform.windows`,
`gifmanager.platform.macos`, `gifmanager.platform.linux`) that registers itself
with `REGISTRY` and supplies a set of small service objects. Registration is
explicit and lazy, so a Windows checkout never imports an X11 module and a macOS
checkout never touches `ctypes.windll`.

平台接口定义。

平台后端是一个模块（`gifmanager.platform.windows`、`gifmanager.platform.macos`、
`gifmanager.platform.linux`），它向 `REGISTRY` 注册自己并提供若干小服务对象。
注册是显式且惰性的，因此 Windows 上的代码不会导入 X11 模块，macOS 上的代码也
不会碰 `ctypes.windll`。
"""
import importlib
import sys
import threading

# Candidate backend modules per `sys.platform` value / 各 `sys.platform` 取值对应的
# 候选后端模块
PLATFORM_MODULES = {
    "win32": "gifmanager.platform.windows",
    "cygwin": "gifmanager.platform.windows",
    "darwin": "gifmanager.platform.macos",
    "linux": "gifmanager.platform.linux",
    "freebsd": "gifmanager.platform.linux",
    "openbsd": "gifmanager.platform.linux",
    "netbsd": "gifmanager.platform.linux",
}

# Fallback backend, used when the running system has no dedicated module /
# 运行系统没有专用模块时使用的兜底后端
FALLBACK_MODULE = "gifmanager.platform.linux"


class UnsupportedOperation(Exception):
    # Raised by a service that the current platform genuinely cannot provide.
    # The caller is expected to degrade gracefully rather than crash.
    # 当前平台确实无法提供的服务抛出此异常；调用方应优雅降级而不是崩溃。

    def __init__(self, service, platform=None):
        self.service = service
        self.platform = platform or sys.platform
        super().__init__(
            f"{service} is not available on {self.platform} / "
            f"{self.platform} 上不支持 {service}"
        )


class HotkeyBackend:
    # Global (system-wide) hotkey registration.
    #
    # Implementations differ radically per system: Windows uses
    # `RegisterHotKey` plus a native event filter, macOS uses Carbon
    # `RegisterEventHotKey` or an `NSEvent` global monitor, Linux uses X11
    # `XGrabKey`. Each returns an opaque token per registered hotkey, or None
    # when registration failed because another program already owns the
    # combination.
    # 全局（系统级）热键注册。
    #
    # 各系统实现差异极大：Windows 用 `RegisterHotKey` 加原生事件过滤器，
    # macOS 用 Carbon `RegisterEventHotKey` 或 `NSEvent` 全局监听，Linux 用
    # X11 `XGrabKey`。每个实现为已注册热键返回一个不透明令牌；因组合键已被
    # 其他程序占用而注册失败时返回 None。

    # Human-readable backend name, shown in the settings dialog /
    # 后端名称，显示在设置界面
    name = "unsupported"

    # True when the backend can actually register hotkeys on this system /
    # 本系统上后端确实能注册热键时为 True
    available = False

    def register(self, hotkey_id, sequence, callback):
        # Register `sequence` (a portable string such as "Ctrl+Shift+G") and
        # invoke `callback` when it fires. Returns a token or None.
        # 注册 `sequence`（如 "Ctrl+Shift+G" 的可移植字符串），触发时调用
        # `callback`。返回令牌或 None。
        raise UnsupportedOperation("global hotkeys")

    def unregister(self, token):
        # Release a token returned by `register`; must be safe to call twice.
        # 释放 `register` 返回的令牌；重复调用必须安全。
        return False

    def unregister_all(self):
        # Release every registration made through this backend /
        # 释放经此后端建立的全部注册
        return 0

    def install_event_filter(self):
        # Hook into the host toolkit's native event pump, when the OS delivers
        # hotkeys through window messages. Returns True when installed or when
        # the platform needs no hook (macOS/Linux typically return True).
        # 需要经窗口消息投递热键时，接入宿主工具包的原生事件循环。安装成功，
        # 或平台无需钩子（macOS/Linux 通常返回 True）时返回 True。
        return True

    def remove_event_filter(self):
        # Undo `install_event_filter` / 撤销 `install_event_filter`
        return True

    def scroll_delta(self, native_event):
        # Extract a horizontal/vertical scroll delta from a native event, when
        # the platform offers global scroll capture. Returns None when the
        # event carries no scroll.
        # 平台提供全局滚动捕获时，从原生事件中取出水平/垂直滚动增量；事件不含
        # 滚动时返回 None。
        return None


class ClipboardBackend:
    # Clipboard access, including the non-standard MIME payloads chat
    # applications need (raw animated GIF bytes alongside a static bitmap).
    # 剪贴板访问，包括聊天软件需要的非标准 MIME 载荷（原始动图 GIF 字节 +
    # 静态位图）。

    name = "unsupported"
    available = False

    def copy_files(self, paths):
        # Put file references on the clipboard / 把文件引用放入剪贴板
        raise UnsupportedOperation("clipboard file copy")

    def copy_image(self, path):
        # Put an image file on the clipboard as a bitmap /
        # 把图片文件作为位图放入剪贴板
        raise UnsupportedOperation("clipboard image copy")

    def copy_rich_image(self, path):
        # Put an image on the clipboard so a chat application keeps the
        # animation where it can and still receives a standard bitmap. Returns
        # True when the payload was written.
        # 把图片放入剪贴板，使聊天软件在能识别动画时保留动画，同时仍收到标准
        # 位图。载荷写入成功返回 True。
        raise UnsupportedOperation("clipboard rich image copy")

    def copy_text(self, text):
        # Put plain text on the clipboard / 把纯文本放入剪贴板
        raise UnsupportedOperation("clipboard text copy")


class InputBackend:
    # Simulated keyboard input into the previously focused application.
    # 向此前获得焦点的应用程序模拟键盘输入。

    name = "unsupported"
    available = False

    def paste_to_foreground(self, delay_ms=50):
        # Send the platform's paste shortcut (Ctrl+V / Cmd+V) to whichever
        # window currently has focus. Returns True on success.
        # 向当前拥有焦点的窗口发送本平台的粘贴快捷键（Ctrl+V / Cmd+V）。
        # 成功返回 True。
        return False

    def foreground_window(self):
        # Opaque identifier of the foreground window, or 0 /
        # 前台窗口的不透明标识，无则 0
        return 0

    def bring_to_front(self, window_id):
        # Restore foreground focus to a window, bypassing the OS's
        # focus-stealing protection where possible. Returns True on success.
        # 把前台焦点还给指定窗口，尽量绕过系统的防抢焦点限制。成功返回 True。
        return False

    def paste_to_window(self, window_id, delay_ms=50):
        # Deliver a paste directly to a window without relying on simulated
        # key events. Returns True when the platform has a direct route.
        # 不依赖模拟按键、直接向窗口投递粘贴。平台存在直投通道时返回 True。
        return False

    def owns_window(self, window_id):
        # True when the identifier belongs to this process (so the focus
        # tracker can ignore our own dialogs).
        # 标识属于本进程时为 True（使焦点跟踪器忽略自己的对话框）。
        return False


class GpuPreferenceBackend:
    # Per-application GPU preference, where the OS exposes one.
    #
    # Windows stores it in the registry, macOS chooses automatically and offers
    # no per-app override, Linux depends on the driver (PRIME/DRI_PRIME or the
    # vendor control panel), so `available` is False on most systems.
    # 按应用的 GPU 首选项（系统提供时）。
    #
    # Windows 存在注册表，macOS 自动选择且不提供按应用覆盖，Linux 取决于驱动
    # （PRIME/DRI_PRIME 或厂商控制面板），因此在多数系统上 `available` 为
    # False。

    name = "unsupported"
    available = False

    # Preference values shared by every backend / 各后端共用的取值
    SYSTEM = 0    # let the OS decide / 由系统决定
    POWER = 1     # power saving / integrated / 省电 / 集显
    HIGH = 2      # high performance / discrete / 高性能 / 独显

    def apply(self, executable, preference):
        # Store `preference` for `executable`; SYSTEM removes any override.
        # Returns True on success.
        # 为 `executable` 写入 `preference`；SYSTEM 表示删除覆盖项。成功返回
        # True。
        return False

    def get(self, executable):
        # Read back the stored preference, or None when unset /
        # 读回已存储的首选项，未设置时返回 None
        return None

    def list_adapters(self):
        # Installed display adapters, for display only /
        # 已安装的显示适配器，仅用于展示
        return []


class AutostartBackend:
    # "Start with the system" registration.
    # "开机自启"注册。

    name = "unsupported"
    available = False

    def is_enabled(self, app_id):
        # True when an autostart entry for `app_id` exists /
        # `app_id` 的自启项存在时为 True
        return False

    def set_enabled(self, app_id, command, enabled):
        # Create or remove the autostart entry. `command` is the full command
        # line to run. Returns True on success.
        # 创建或删除自启项。`command` 为要运行的完整命令行。成功返回 True。
        return False


class WindowBackend:
    # Window chrome effects that the host toolkit cannot express portably:
    # rounded corners, backdrop material, taskbar/dock presence.
    # 宿主工具包无法可移植表达窗口外观效果：圆角、背景材质、任务栏/Dock 存在性。

    name = "noop"
    available = False

    def apply_rounded_corners(self, window_id):
        # Ask the compositor for rounded corners. Returns True when the request
        # was accepted; False means the caller should keep square corners.
        # 向合成器请求圆角。请求被接受返回 True；False 表示调用方应保持直角。
        return False

    def apply_backdrop(self, window_id, material):
        # Apply a translucent/backdrop material such as "mica" or "acrylic"
        # where supported. `material` is a portable name.
        # 在支持的系统上应用"云母""亚克力"等半透明背景材质。`material` 为可移植
        # 名称。
        return False

    def set_skip_taskbar(self, window_id, skip):
        # Hide a window from the taskbar (tray-only mode) /
        # 把窗口从任务栏隐藏（仅托盘模式）
        return False


class SingleInstanceBackend:
    # A system-wide named lock that lets a second launch detect the first.
    # 系统级命名锁，使第二次启动能检测到第一次。

    name = "unsupported"
    available = False

    def acquire(self, name):
        # Try to become the single owner of `name`. Returns (acquired, handle);
        # keep `handle` alive for the process lifetime.
        # 尝试成为 `name` 的唯一持有者。返回 (是否获取成功, 句柄)；句柄需在进程
        # 生命周期内保持存活。
        return True, None

    def release(self, handle):
        # Release a handle returned by `acquire` /
        # 释放 `acquire` 返回的句柄
        return True

    def notify(self, name, message):
        # Deliver one short command to the running owner. True when it was delivered.
        #
        # # Why a second launch is allowed to send anything at all
        #
        # On Wayland there is no global-hotkey API, and the XDG `GlobalShortcuts` portal cannot be
        # driven from PySide6 (`BindShortcuts` needs an `a(sa{sv})` argument and PySide6 has no
        # way to construct one). The route that DOES work on every Wayland compositor - and the
        # one niri documents - is a compositor key binding that runs a command. That command
        # needs to reach the ALREADY RUNNING instance, because starting a second one would fight
        # over the database, so the single-instance channel doubles as the command channel.
        #
        # The default backend cannot do this, and saying so is better than a silent no-op: a
        # caller that gets False knows the key binding will appear to do nothing.
        # 向正在运行的持有者投递一条短命令。投递成功时为 True。
        #
        # # 为什么第二次启动允许发送东西
        #
        # Wayland 没有全局热键 API，而 XDG `GlobalShortcuts` 门户无法从 PySide6 驱动
        #（`BindShortcuts` 需要 `a(sa{sv})` 参数，而 PySide6 无法构造它）。在每种 Wayland 合成器上
        # "确实"可行、且 niri 有文档的做法是：一条运行命令的合成器键绑定。该命令必须到达"已在运行"
        # 的实例，因为再启动一个会争抢数据库，因此单实例通道同时充当命令通道。
        #
        # 默认后端做不到这一点，而如实说明优于静默空操作：得到 False 的调用方知道那条键绑定会看起来
        # 毫无效果。
        return False


class Platform:
    # Bundle of services a backend module registers. Attribute access goes
    # through `service()`, which resolves lazily and falls back to the base
    # (unsupported) implementations.
    # 后端模块注册的服务集合。属性访问经 `service()` 进行，惰性解析并在无实现时
    # 回退到基类（不支持）实现。

    # Registry of module name -> importable backend module path. Backends fill
    # this in when they are imported, so it is a record of what has been loaded
    # rather than the list of what exists — `PLATFORM_MODULES` is that list.
    # 模块名 -> 可导入后端模块路径 的注册表。后端在被导入时写入，因此它是"已加载
    # 过什么"的记录，而非"存在什么"的清单——后者是 `PLATFORM_MODULES`。
    REGISTRY = {}

    def __init__(self, key):
        self.key = key
        self.module = None
        self._services = {}
        self._lock = threading.RLock()

    def _load(self):
        with self._lock:
            if self.module is not None:
                return self.module
            # Resolve through PLATFORM_MODULES, not REGISTRY: the registry is
            # only populated once a backend has been imported, so consulting it
            # here would mean no backend is ever loaded.
            # 经 PLATFORM_MODULES 解析而非 REGISTRY：注册表只在后端被导入后才写入，
            # 在这里查它会导致永远没有后端被加载。
            target = PLATFORM_MODULES.get(self.key) or FALLBACK_MODULE
            try:
                self.module = importlib.import_module(target)
            except (ImportError, OSError) as exc:
                # A backend whose optional native dependency is missing must
                # not take the application down; the base classes below make
                # every call a safe no-op instead.
                # 缺少可选原生依赖的后端不能拖垮程序；下面的基类会让每次调用都
                # 变成安全的空操作。
                try:
                    self.module = importlib.import_module(FALLBACK_MODULE)
                except ImportError:
                    self.module = importlib.import_module(
                        "gifmanager.platform.paths")
                if target != FALLBACK_MODULE:
                    import logging

                    logging.getLogger("GIFManager").warning(
                        "platform: cannot load %s (%s); using %s",
                        target, exc, self.module.__name__)
            return self.module

    def implements(self, service_name):
        # True when the active backend provides a real (not base) service /
        # 当前后端提供了真实（非基类）服务时为 True
        module = self._load()
        provided = getattr(module, "SERVICES", {})
        return service_name in provided

    def service(self, service_name, base_class, override=None):
        # Resolve a service instance, creating it once per process.
        #
        # `override` exists for the one case where the platform layer cannot name the
        # class in its own table: Linux's hotkey backend depends on the SESSION (X11
        # grabs a key, Wayland asks the compositor through the portal), and the session
        # is an environment fact rather than a platform fact. A module-level constant
        # would freeze whichever session was active at import time, so the caller
        # resolves it and passes it here.
        #
        # The cache key includes the override's name, so a caller asking for the
        # session-appropriate backend never receives an instance of the other one.
        # 解析服务实例，每进程只创建一次。
        #
        # `override` 用于平台层无法在自己表里命名类的那一种情形：Linux 的热键后端取决于"会话"
        #（X11 抓取按键，Wayland 经门户请求合成器），而会话是环境事实而非平台事实。模块级常量
        # 会冻住导入时恰好生效的会话，因此由调用方解析并传到这里。
        #
        # 缓存键包含 override 的名称，使索要"会话适配后端"的调用方绝不会拿到另一个的实例。
        cache_key = service_name
        if override is not None:
            cache_key = f"{service_name}:{getattr(override, '__name__', override)}"
        with self._lock:
            if cache_key in self._services:
                return self._services[cache_key]
            if override is not None:
                factory = override
            else:
                module = self._load()
                provided = getattr(module, "SERVICES", {})
                factory = provided.get(service_name)
            if factory is None:
                instance = base_class()
            else:
                instance = factory()
            self._services[cache_key] = instance
            return instance


def current_key():
    # The registry key for the running interpreter /
    # 当前解释器对应的注册表键
    return sys.platform


def native_library_names(stem, platform_key=""):
    # The file names a native library called `stem` can have on this platform.
    #
    # # Why this is one function and not a local constant per loader
    #
    # Two loaders search for a native library - `frontend/qt/animation.py` for the C decoder and
    # `frontend/qt/images.py` for the Rust pipeline. The first learned this lesson and filtered by
    # platform; the second kept a flat tuple of all three names and therefore tried
    # `gifmanager_native.dll` FIRST on Linux, `dlopen`ed a Windows PE binary that a Windows build
    # had left in `native/target/release/`, and reported
    #
    #     native: cannot load .../gifmanager_native.dll -> 无效的 ELF 头
    #
    # then fell through to a `.so` that did not exist, so the whole native path was unavailable on
    # Linux while a stale Windows artefact sat in the tree. The message names a file that exists
    # and says nothing about the platform mismatch, which is the worst kind of diagnostic.
    #
    # One helper means the rule cannot drift apart again. `platform_key` is accepted so a test can
    # ask about another platform without pretending to be it.
    #
    # 名为 `stem` 的原生库在本平台可能具有的文件名。
    #
    # # 为什么这是一个函数而不是每个加载器各自的局部常量
    #
    # 有两个加载器在搜索原生库——`frontend/qt/animation.py` 找 C 解码器，`frontend/qt/images.py`
    # 找 Rust 管线。前者学到了这一课并按平台过滤；后者保留了三平台名称的平铺元组，因此在 Linux 上
    # "先"尝试 `gifmanager_native.dll`，`dlopen` 一个 Windows 构建遗留在
    # `native/target/release/` 里的 PE 二进制，并报告
    #
    #     native: cannot load .../gifmanager_native.dll -> 无效的 ELF 头
    #
    # 然后落到并不存在的 `.so` 上，于是整条原生路径在 Linux 上不可用，而一个过期的 Windows 产物
    # 就躺在代码树里。该消息点名了一个存在的文件、却对平台不匹配只字不提，是最糟糕的一类诊断。
    #
    # 用一个辅助函数意味着这条规则无法再次分叉。接受 `platform_key` 是为了让测试可以询问其他平台
    # 而不必假装自己是它。
    key = platform_key or sys.platform
    if key.startswith("win") or key == "cygwin":
        return (f"{stem}.dll", stem)
    if key == "darwin":
        return (f"lib{stem}.dylib", stem)
    return (f"lib{stem}.so", stem)


__all__ = [
    "FALLBACK_MODULE",
    "PLATFORM_MODULES",
    "AutostartBackend",
    "ClipboardBackend",
    "GpuPreferenceBackend",
    "HotkeyBackend",
    "InputBackend",
    "Platform",
    "SingleInstanceBackend",
    "UnsupportedOperation",
    "WindowBackend",
    "current_key",
    "native_library_names",
]
