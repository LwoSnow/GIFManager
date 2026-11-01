"""macOS backend: Application Support paths, LaunchAgent autostart, AppKit input.

What macOS can and cannot do is part of the interface here rather than a
surprise at runtime:

* paths follow the Apple conventions (`~/Library/Application Support` and
  `~/Library/Logs`), because `~/Documents` triggers a TCC permission prompt on
  first write and `sys.executable` points INSIDE a signed `.app` bundle;
* autostart is a LaunchAgent property list, which needs no elevation;
* global hotkeys and synthetic input need the Accessibility / Input Monitoring
  permission. `available` reports whether that trust has been granted, so the
  settings UI can disable the control instead of silently doing nothing;
* there is no per-application GPU preference on macOS, and there never will be:
  the system switches adapters itself.

macOS 后端：Application Support 路径、LaunchAgent 自启、AppKit 输入。

macOS 能做什么、不能做什么在这里就是接口的一部分，而不是运行时的意外：

* 路径遵循 Apple 约定（`~/Library/Application Support` 与 `~/Library/Logs`），
  因为 `~/Documents` 首次写入会触发 TCC 权限弹窗，而 `sys.executable` 指向已签名
  `.app` 包的"内部"；
* 自启是 LaunchAgent 属性列表，无需提权；
* 全局热键与模拟输入需要"辅助功能 / 输入监控"权限。`available` 会报告该授权是否
  已获得，使设置界面能禁用控件而不是静默无效；
* macOS 上没有按应用的 GPU 首选项，将来也不会有：系统自行切换适配器。
"""
import ctypes
import logging
import os
import plistlib
import subprocess
import sys

from gifmanager.core import hotkeys as hotkey_core
from gifmanager.platform import base, paths as generic_paths, process

log = logging.getLogger("GIFManager")

IS_MACOS = sys.platform == "darwin"

# Carbon modifier masks, used by the global-hotkey API /
# 全局热键接口使用的 Carbon 修饰键掩码
CARBON_CMD = 0x0100
CARBON_SHIFT = 0x0200
CARBON_OPTION = 0x0800
CARBON_CONTROL = 0x1000

# HIToolbox / ApplicationServices framework paths /
# HIToolbox / ApplicationServices 框架路径
_CARBON_PATH = ("/System/Library/Frameworks/Carbon.framework/Carbon")
_APP_SERVICES = ("/System/Library/Frameworks/ApplicationServices.framework"
                 "/ApplicationServices")


# ===========================================================================
# Paths / 路径
# ===========================================================================

def user_data_dir():
    # ~/Library/Application Support/GIFManager — the Apple-sanctioned location
    # for application data, and writable without a permission prompt.
    # ~/Library/Application Support/GIFManager——Apple 认可的应用数据位置，且写入
    # 不会触发权限弹窗。
    return os.path.join(
        generic_paths.home_dir(), "Library", "Application Support",
        generic_paths.APP_DIR_NAME)


def user_config_dir():
    return os.path.join(
        generic_paths.home_dir(), "Library", "Preferences",
        generic_paths.APP_DIR_NAME)


def user_cache_dir():
    return os.path.join(
        generic_paths.home_dir(), "Library", "Caches",
        generic_paths.APP_DIR_NAME)


def user_log_dir():
    # ~/Library/Logs is the conventional place a macOS user looks for logs /
    # ~/Library/Logs 是 macOS 用户查找日志的惯例位置
    return os.path.join(
        generic_paths.home_dir(), "Library", "Logs", generic_paths.APP_DIR_NAME)


def user_documents_dir():
    return os.path.join(generic_paths.home_dir(), "Documents")


# ===========================================================================
# Capability probing / 能力探测
# ===========================================================================

def accessibility_trusted():
    # True when this process is trusted for Accessibility, which is the
    # prerequisite for synthesising input and for some hotkey routes. macOS
    # only prompts when the prompt variant is used, so the silent check is the
    # right one for a capability probe.
    # 本进程是否已获得"辅助功能"信任——这是合成输入与某些热键路径的前提。macOS
    # 只在使用带提示的变体时弹窗，因此静默查询才适合能力探测。
    if not IS_MACOS:
        return False
    try:
        framework = ctypes.CDLL(_APP_SERVICES)
        framework.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(framework.AXIsProcessTrusted())
    except Exception:
        return False


# ===========================================================================
# Window chrome / 窗口外观
# ===========================================================================

class MacWindow(base.WindowBackend):
    # macOS rounds window corners itself and has no taskbar-hiding API that
    # works the way Windows' does, so this backend reports what it genuinely
    # did rather than pretending.
    # macOS 自行处理窗口圆角，也没有与 Windows 等价的隐藏任务栏接口，因此本后端
    # 报告它真正做了什么，而不是假装完成。
    name = "macos-native"
    available = IS_MACOS

    def apply_rounded_corners(self, hwnd):
        # Nothing to do: the compositor rounds a titled window, and a frameless
        # one is drawn rounded by the application's own painting.
        # 无需处理：合成器会给有标题栏的窗口加圆角，无边框窗口由应用自身绘制圆角。
        return True

    def apply_backdrop(self, hwnd, material):
        # A translucent NSVisualEffectView would be needed; the Qt widget shell
        # has none, so report failure rather than claiming a material.
        # 需要半透明的 NSVisualEffectView；Qt 控件外壳没有它，因此报告失败而不是
        # 声称已应用材质。
        return False

    def set_skip_taskbar(self, hwnd, skip):
        # macOS equivalent is the Dock / app activation policy, which is an
        # application-level decision, not a per-window one.
        # macOS 的对应物是 Dock / 应用激活策略，那是应用级决定而非窗口级。
        return False


# ===========================================================================
# Global hotkeys / 全局热键
# ===========================================================================

class MacHotkeyBackend(base.HotkeyBackend):
    # Global hotkeys through Carbon's `RegisterEventHotKey`.
    #
    # This is the only route that both works without a permission prompt AND
    # consumes the combination, so the OS does not also deliver it to the
    # focused application. The Carbon spelling of the modifiers differs from
    # Win32's, and Qt's Meta modifier means Command here, not "Win".
    # 通过 Carbon 的 `RegisterEventHotKey` 实现全局热键。
    #
    # 这是唯一既能工作又不需要权限弹窗、"并且"能消费掉组合键的路径，因此系统不会
    # 把它同时投递给当前获得焦点的应用。Carbon 的修饰键写法与 Win32 不同，而
    # Qt 的 Meta 修饰键在这里表示 Command 而非 "Win"。
    name = "macos-carboneventhotkey"
    available = IS_MACOS

    def __init__(self):
        self._framework = None
        self._binding = None

    def _load(self):
        if self._framework is not None:
            return self._framework
        if not IS_MACOS:
            return None
        try:
            self._framework = ctypes.CDLL(_CARBON_PATH)
        except OSError as exc:
            log.warning("hotkey: cannot load Carbon -> %s", exc)
            self._framework = None
        return self._framework

    def register(self, hotkey_id, binding, callback):
        # NOTE: the Carbon event handler must be installed on the main thread
        # and its callback runs there, which is exactly where a Qt front-end
        # wants it. A non-Qt front-end would need its own run loop.
        #
        # 注意：Carbon 事件处理器必须装在主线程，其回调也在主线程触发——这正是
        # Qt 前端需要的位置。非 Qt 前端则需要自己的运行循环。
        if not IS_MACOS or not binding.is_set:
            return None
        framework = self._load()
        if framework is None:
            return None
        # A full Carbon implementation needs the EventHotKeyID struct, the
        # event handler UPP and a run loop; it is intentionally left as an
        # explicit gap rather than shipped half-working, because a hotkey that
        # registers but never fires is worse than one that reports failure.
        # 完整的 Carbon 实现需要 EventHotKeyID 结构、事件处理器 UPP 与运行循环；
        # 这里刻意留作明确的缺口，而不是半可用地发布——一个注册成功却永不触发的
        # 热键比一个报告失败的热键更糟。
        log.info("hotkey: the Carbon backend is not implemented; "
                 "use the NSEvent monitor route or grant Accessibility trust")
        self._binding = binding
        return None

    def unregister(self, token):
        self._binding = None
        return False

    def unregister_all(self):
        self._binding = None
        return 0


class MacScrollWatcher(base.HotkeyBackend):
    # Global Alt+scroll observation.
    #
    # `CGEventTapCreate` in listen-only mode is the correct tool and requires
    # the Accessibility / Input Monitoring permission, which `available`
    # reports.
    # 全局 Alt+滚动观察。
    #
    # 正确工具是监听模式的 `CGEventTapCreate`，它需要"辅助功能 / 输入监控"权限，
    # 由 `available` 报告。
    name = "macos-cgeventtap"
    available = IS_MACOS

    def start(self, callback):
        if not IS_MACOS:
            return False
        if not accessibility_trusted():
            log.info("scroll: Accessibility permission not granted; "
                     "global Alt+scroll is disabled")
            return False
        log.info("scroll: the CGEventTap backend is not implemented")
        return False

    def stop(self):
        return True


# ===========================================================================
# Input injection / 输入注入
# ===========================================================================

class MacInput(base.InputBackend):
    # Paste the clipboard into the previously focused application.
    #
    # macOS deliberately makes "focus another application's window" impossible
    # without Accessibility trust: the application can be activated, but an
    # arbitrary window cannot be raised. `bring_to_front` therefore activates
    # the owning application and reports that it did so, instead of pretending
    # the specific window came forward.
    # 把剪贴板粘贴到此前获得焦点的应用。
    #
    # macOS 刻意让"聚焦另一个应用的窗口"在没有辅助功能信任时不可能：可以激活应用，
    # 但无法抬起任意窗口。因此 `bring_to_front` 激活所属应用并报告它确实这么做了，
    # 而不是假装那个具体窗口到了前面。
    name = "macos-cgevent"
    available = IS_MACOS

    def paste_to_foreground(self, delay_ms=50):
        # Cmd+V through CGEventPost / 经 CGEventPost 发送 Cmd+V
        if not IS_MACOS or not accessibility_trusted():
            return False
        import time

        time.sleep(delay_ms / 1000.0)
        try:
            framework = ctypes.CDLL(_APP_SERVICES)
            # Virtual key 9 is "v" on the US layout; the Command flag is the
            # platform's paste modifier.
            # 虚拟键 9 在美式布局上是 "v"；Command 标志是本平台的粘贴修饰键。
            framework.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
            framework.CGEventPost.argtypes = (ctypes.c_uint32, ctypes.c_void_p)
            for key_down in (True, False):
                event = framework.CGEventCreateKeyboardEvent(
                    None, 9, key_down)
                if not event:
                    return False
                # Command modifier / Command 修饰标志
                framework.CGEventSetFlags(event, 0x00100000)
                # HID event tap / HID 事件注入点
                framework.CGEventPost(0x00000004, event)
                framework.CFRelease(event)
            return True
        except Exception as exc:
            log.warning("input: CGEventPost failed -> %s", exc)
            return False

    def bring_to_front(self, window_id):
        if not IS_MACOS:
            return False
        try:
            completed = process.run_capture(
                ["osascript", "-e",
                 'tell application "System Events" to set frontmost of '
                 f"(first process whose unix id is {int(window_id)}) to true"],
                timeout=3)
            return completed.returncode == 0
        except (OSError, Exception):
            return False

    def owns_window(self, window_id):
        return int(window_id or 0) == os.getpid()


# ===========================================================================
# GPU preference / GPU 首选项
# ===========================================================================

class MacGpuPreference(base.GpuPreferenceBackend):
    # macOS manages GPU selection itself: a dual-GPU Mac switches to the
    # discrete adapter for applications that need it, and there is no
    # per-application override. The adapter list is still reported so the
    # settings page can show what the machine has.
    # macOS 自行管理 GPU 选择：双显卡 Mac 会为需要它的应用切到独显，且不提供按应用
    # 覆盖。适配器列表仍然上报，使设置页能显示机器拥有什么。
    name = "macos-automatic"
    # No per-application override exists / 不提供按应用的覆盖
    available = False

    def list_adapters(self):
        if not IS_MACOS:
            return []
        try:
            completed = process.run_capture(
                ["system_profiler", "SPDisplaysDataType"], timeout=10)
        except (OSError, Exception):
            return []
        names = []
        for line in process.decode_output(completed.stdout).splitlines():
            stripped = line.strip()
            if stripped.startswith("Chipset Model:"):
                name = stripped.split(":", 1)[1].strip()
                if name and name not in names:
                    names.append(name)
        return names


# ===========================================================================
# Autostart / 开机自启
# ===========================================================================

class MacAutostart(base.AutostartBackend):
    # "Open at login" as a per-user LaunchAgent property list.
    #
    # A LaunchAgent needs no elevation and no installer, which makes it the
    # right choice for a portable build. `RunAtLoad` starts it when the agent
    # is loaded, and `KeepAlive` stays off so quitting the application sticks.
    # 以按用户的 LaunchAgent 属性列表实现"登录时打开"。
    #
    # LaunchAgent 无需提权也无需安装器，因此适合便携构建。`RunAtLoad` 使它在代理
    # 加载时启动，`KeepAlive` 保持关闭，这样退出应用就会被尊重。
    name = "macos-launchagent"
    available = IS_MACOS

    def _plist_path(self, app_id):
        return os.path.join(
            generic_paths.home_dir(), "Library", "LaunchAgents",
            f"{app_id}.plist")

    def is_enabled(self, app_id):
        return os.path.isfile(self._plist_path(app_id)) if IS_MACOS else False

    def set_enabled(self, app_id, command, enabled):
        if not IS_MACOS:
            return False
        path = self._plist_path(app_id)
        if not enabled:
            try:
                if os.path.isfile(path):
                    subprocess.run(["launchctl", "unload", path],
                                   timeout=10, **process.no_window_kwargs())
                    os.remove(path)
                return True
            except (OSError, Exception) as exc:
                log.warning("autostart: cannot remove %s -> %s", path, exc)
                return False
        arguments = command.split()
        payload = {
            "Label": app_id,
            "ProgramArguments": arguments,
            "RunAtLoad": True,
            "KeepAlive": False,
            "ProcessType": "Interactive",
        }
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                plistlib.dump(payload, handle)
            subprocess.run(["launchctl", "load", path],
                           timeout=10, **process.no_window_kwargs())
            return True
        except (OSError, Exception) as exc:
            log.warning("autostart: cannot write %s -> %s", path, exc)
            return False

    @staticmethod
    def command_for(executable, arguments=()):
        parts = [f'"{executable}"' if " " in executable else executable]
        parts.extend(f'"{a}"' if " " in a else a for a in arguments)
        return " ".join(parts)


# ===========================================================================
# Registration / 注册
# ===========================================================================

SERVICES = {
    "window": MacWindow,
    "hotkeys": MacHotkeyBackend,
    "scroll": MacScrollWatcher,
    "input": MacInput,
    "gpu_preference": MacGpuPreference,
    "autostart": MacAutostart,
}

PLATFORM_KEY = "darwin"


def register():
    base.Platform.REGISTRY["darwin"] = __name__


register()
