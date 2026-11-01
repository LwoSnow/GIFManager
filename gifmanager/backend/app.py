"""Backend façade: the single object a front-end talks to.

The pre-refactor `MainWindow` reached directly into `DataManager`, six widgets,
`gif_converter`'s module globals, `QSettings` and three platform-specific
modules, and pushed a refresh to the grid from twenty separate call sites. That
made the window a pull-based god object with no way to observe what changed.

Here a front-end receives one `Backend`, calls methods on it, and subscribes to
`library_changed` / `settings_changed`. The Qt shell adapts those callbacks to
Qt signals; a different front-end adapts them to whatever it has.

重构前的 `MainWindow` 直接伸手进 `DataManager`、六个控件、`gif_converter` 的模块
全局量、`QSettings` 与三个平台专有模块，并从二十个调用点分别推送一次网格刷新。
这使窗口变成一个基于拉取的上帝对象，且无法观察"什么变了"。

在这里，前端拿到一个 `Backend`，在它上面调用方法，并订阅 `library_changed` /
`settings_changed`。Qt 外壳把这些回调适配为 Qt 信号；其他前端适配为它们自己的机制。
"""
import logging
import os
import threading

from gifmanager import APP_NAME, __version__
from gifmanager.backend.settings_store import JsonSettingsStore
from gifmanager.core import hotkeys as hotkey_core
from gifmanager.core import lang, logging_setup, paths, settings as settings_model
from gifmanager.core.imaging.converter import MediaConverter
from gifmanager.core.store.repository import Store
from gifmanager.platform import current as current_platform
from gifmanager.platform import describe as describe_platform
from gifmanager.platform import process as platform_process

log = logging.getLogger("GIFManager")


def install_platform_paths():
    # Hand the core layer the running system's per-user directory rules.
    #
    # This is the one place the dependency is inverted: `core.paths` must not
    # import `gifmanager.platform`, so the application pushes the resolver in
    # instead. Called before anything resolves a directory.
    # 把当前系统的按用户目录规则交给核心层。
    #
    # 这是唯一一处依赖反转：`core.paths` 不得导入 `gifmanager.platform`，因此由应用
    # 把解析器推进去。必须在任何目录解析之前调用。
    from gifmanager import platform as platform_layer

    paths.install_path_resolver(platform_layer.path_function)

# Notification kinds delivered to subscribers. A front-end maps these onto its
# own refresh logic; the backend never knows what a widget is.
# 投递给订阅者的通知类型。前端把它们映射到自己的刷新逻辑；后端从不关心什么是控件。
CHANGE_LIBRARY = "library"      # groups or emoji rows changed / 分组或表情行发生变化
CHANGE_SETTINGS = "settings"    # settings changed / 设置发生变化
CHANGE_LANGUAGE = "language"    # the active language changed / 当前语言发生变化


class Backend:
    # Application services, wired once and shared by the whole process.
    #
    # Construction is deliberately side-effect free apart from opening the data
    # store: nothing touches a window, a tray icon or a global hotkey, so a
    # headless test can build a backend and exercise every service.
    # 应用服务，装配一次并全进程共享。
    #
    # 除了打开数据存储，构造刻意没有副作用：不碰窗口、托盘图标或全局热键，因此
    # 无界面测试可以构建后端并演练每一个服务。
    def __init__(self, data_dir=None, settings_store=None, converter=None,
                 language_manager=None):
        # The platform's directory rules and subprocess policy are installed
        # before anything reads a path or spawns a process.
        # 在读取任何路径或启动任何子进程之前，先安装平台的目录规则与子进程策略。
        install_platform_paths()

        self.data_dir = data_dir or paths.data_dir()

        self.settings_store = settings_store or JsonSettingsStore(
            path=_settings_path(self.data_dir))
        self.settings = settings_model.from_mapping(self.settings_store.read_all())

        # Hand the stored thread count to the native library BEFORE anything decodes.
        #
        # The Rust pipeline sizes its worker pool with rayon, which reads `RAYON_NUM_THREADS` when
        # the global pool is initialised - and there is no exported setter, so an environment
        # variable is the only channel. Setting it here works because the backend is built before
        # the first image is decoded; a CHANGE therefore needs a restart, which is why the
        # `thread_count` row is flagged `restart=True` in the settings schema.
        #
        # Measured before this: the setting was stored and read by nobody, and the library always
        # reported all cores (16 on this machine) whatever the user chose.
        # 在任何解码发生"之前"把存储的线程数交给原生库。
        #
        # Rust 管线用 rayon 决定工作线程池大小，而它在全局池初始化时读取 `RAYON_NUM_THREADS`——并
        # 没有导出的 setter，因此环境变量是唯一通道。放在此处可行，是因为后端在第一次解码之前就被构建；
        # 因此"修改"需要重启，这也是设置 schema 里 `thread_count` 行被标记为 `restart=True` 的原因。
        #
        # 在此之前的实测：该设置被存储、却没有任何东西读它，库总是报告全部核心（本机 16），无论用户
        # 选择什么。
        thread_count = int(self.settings.thread_count or 0)
        if thread_count > 0:
            os.environ["RAYON_NUM_THREADS"] = str(thread_count)

        # `platform_process` implements the interface `MediaConverter` expects
        # (console suppression on Windows, encoding-tolerant output decoding);
        # injecting it keeps the converter's own default OS-free.
        # `platform_process` 实现了 `MediaConverter` 期望的接口（Windows 上抑制控制台、
        # 容忍编码的输出解码）；注入它使转换器自身的默认实现与系统无关。
        self.converter = converter or MediaConverter(
            ffmpeg_path=self.settings.ffmpeg_path,
            ffmpeg_enabled=self.settings.ffmpeg_enabled,
            process_runner=platform_process)
        self.store = Store(data_dir=self.data_dir, converter=self.converter)

        # One language manager for the process. The core module keeps a default
        # singleton for call sites that cannot take an injected one; the backend
        # installs the configured language onto it so both agree.
        # 全进程一个语言管理器。核心模块为无法注入的调用点保留默认单例；后端把配置的
        # 语言装载到它上面，使两者一致。
        self.language = language_manager or lang.LanguageManager()
        self.language.set_language(self.settings.language)
        lang.set_manager(self.language)

        self.platform = current_platform()
        self._platform_report = None

        self._subscribers = []
        self._lock = threading.RLock()
        self._closed = False

        log.info("backend ready: data=%s platform=%s version=%s",
                 self.data_dir, self.platform.key, __version__)

    # ---- notifications / 通知 -------------------------------------------

    def subscribe(self, callback):
        # Register `callback(kind, payload)` and return an unsubscribe callable.
        #
        # Callbacks run on the thread that performed the mutation, so a
        # front-end must marshal to its UI thread. This replaces the twenty
        # direct `_refresh_emoji_grid()` calls scattered through the old window.
        # 注册 `callback(kind, payload)` 并返回取消订阅的可调用对象。
        #
        # 回调在"执行变更的那个线程"上运行，因此前端必须转投到自己的界面线程。这取代
        # 了旧窗口里散落的二十处直接 `_refresh_emoji_grid()` 调用。
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe():
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return unsubscribe

    def notify(self, kind, payload=None):
        with self._lock:
            subscribers = list(self._subscribers)
        for callback in subscribers:
            try:
                callback(kind, payload)
            except Exception:
                log.exception("backend subscriber failed for %s", kind)

    # ---- settings / 设置 -------------------------------------------------

    def load_settings(self):
        # Re-read the store and return the normalised settings /
        # 重新读取存储并返回规范化后的设置
        self.settings = settings_model.from_mapping(
            self.settings_store.read_all())
        return self.settings

    def apply_settings(self, new_settings, persist=True):
        # Adopt `new_settings`, persist it, and push it into the services that
        # depend on it. Returns the fields that actually changed, so a front-end
        # can skip re-applying everything.
        # 采用 `new_settings`、持久化它，并推送到依赖它的服务。返回真正变化的字段，
        # 使前端可以跳过重应用全部设置。
        previous = self.settings
        changed = settings_model.diff(previous, new_settings)
        self.settings = new_settings

        if "ffmpeg_enabled" in changed or "ffmpeg_path" in changed:
            self.apply_converter_settings()
        if "language" in changed:
            self.language.set_language(new_settings.language)
        # Autostart is a PLATFORM action, not a stored preference.
        #
        # The switch used to write `autostart: true` into the settings file and change nothing on
        # disk, so the user was told the application would start with the session and it never did.
        # Measured on Arch + niri: after enabling it, `platform.autostart().is_enabled(...)` still
        # answered False and no `~/.config/autostart/gifmanager.desktop` existed.
        #
        # 自启是一个"平台动作"而不是一个存储的偏好。
        #
        # 这个开关过去只是把 `autostart: true` 写进设置文件、磁盘上什么都没变，于是用户被告知应用
        # 会随会话启动，而它从未如此。在 Arch + niri 上实测：启用之后
        # `platform.autostart().is_enabled(...)` 仍回答 False，且不存在
        # `~/.config/autostart/gifmanager.desktop`。
        if "autostart" in changed:
            self.apply_autostart()

        if persist:
            self.settings_store.write_many(
                settings_model.to_mapping(new_settings))
        self.notify(CHANGE_SETTINGS, changed)
        return changed

    def apply_autostart(self):
        # Create or remove the platform's autostart entry. Returns True when the platform agrees
        # with the stored value afterwards.
        #
        # `platform.autostart()` is a MODULE-level accessor, not an attribute of the `Platform`
        # object - reaching for `current_platform().autostart` raises AttributeError, which is how
        # the first version of this method would have failed on every settings change.
        # 创建或移除平台的自启条目。平台随后与存储值一致时返回 True。
        #
        # `platform.autostart()` 是"模块级"访问器，不是 `Platform` 对象的属性——去取
        # `current_platform().autostart` 会抛 AttributeError，而这正是本方法的第一个版本会在每次
        # 设置变更时失败的方式。
        from gifmanager import APP_ID
        from gifmanager import platform as platform_layer

        service = platform_layer.autostart()
        if not service.available:
            log.info("autostart: the backend is unavailable on this platform")
            return False
        wanted = bool(self.settings.autostart)
        command = self.autostart_command()
        try:
            service.set_enabled(APP_ID, command, wanted)
        except Exception:
            log.exception("autostart: set_enabled(%r) failed", wanted)
            return False
        actual = bool(service.is_enabled(APP_ID))
        if actual != wanted:
            log.warning("autostart: asked for %r but the backend reports %r", wanted, actual)
            return False
        log.info("autostart: %s", "enabled" if wanted else "disabled")
        return True

    @staticmethod
    def autostart_command():
        # The command an autostart entry should run.
        #
        # Built from the RUNNING interpreter rather than from a resolved `gifmanager` script: on a
        # source checkout that script lives in the project's own venv, which is usually not on
        # `PATH` (measured on Arch: `.venv/bin` is not), so a bare `gifmanager` in the entry would
        # fail at login with "command not found" and no visible error.
        # 自启条目应当运行的命令。
        #
        # 用"正在运行的解释器"构造，而不是解析出的 `gifmanager` 脚本：在源码检出里该脚本位于项目
        # 自己的 venv 中，而它通常不在 `PATH` 上（Arch 上实测 `.venv/bin` 不在），因此条目里写一个
        # 裸 `gifmanager` 会在登录时以"找不到命令"失败，且没有任何可见错误。
        import shlex
        import sys

        return f"{shlex.quote(sys.executable)} -m gifmanager"

    def apply_converter_settings(self):
        self.converter.configure(
            path=self.settings.ffmpeg_path,
            enabled=self.settings.ffmpeg_enabled)

    def save_session(self, window_geometry=None, last_group_name=None):
        # Persist session state that only a front-end knows about /
        # 持久化只有前端才知道的会话状态
        payload = {}
        if window_geometry is not None:
            payload["window_geometry"] = window_geometry
            self.settings.window_geometry = window_geometry
        if last_group_name is not None:
            payload["last_group_name"] = last_group_name
            self.settings.last_group_name = last_group_name
        if payload:
            self.settings_store.write_many(payload)
        self.settings_store.sync()
        return payload

    # ---- language / 语言 -------------------------------------------------

    def set_language(self, code):
        self.language.set_language(code)
        self.settings.language = code
        self.settings_store.write_many({"language": code})
        self.notify(CHANGE_LANGUAGE, code)
        return code

    def tr(self, key, **kwargs):
        return self.language.t(key, **kwargs)

    def available_languages(self):
        return self.language.available_languages()

    # ---- platform capabilities / 平台能力 --------------------------------

    def platform_report(self, refresh=False):
        # Cached capability report. Mirrors the platform layer's own table and
        # adds the setting-level capability names, so a settings page can ask
        # "can this system do X" with one call.
        # 带缓存的能力报告。镜像平台层自身的表，并加入设置层的能力名，使设置页一次调用
        # 就能问"本系统能不能做 X"。
        if self._platform_report is None or refresh:
            report = describe_platform()
            provided = {
                row["service"]: bool(row["available"])
                for row in report["services"]
            }
            report["capabilities"] = {
                settings_model.CAPABILITY_GPU_PREFERENCE:
                    provided.get("gpu_preference", False),
                settings_model.CAPABILITY_GLOBAL_HOTKEY:
                    provided.get("hotkeys", False),
                settings_model.CAPABILITY_GLOBAL_SCROLL:
                    provided.get("scroll", False),
                settings_model.CAPABILITY_AUTOSTART:
                    provided.get("autostart", False),
                settings_model.CAPABILITY_AUTO_INPUT:
                    provided.get("input", False),
                # The OpenGL viewport only makes sense where an adapter
                # preference can be expressed at all.
                # 只有在能够表达适配器首选项的地方，OpenGL 视口才有意义。
                settings_model.CAPABILITY_GPU_VIEWPORT:
                    provided.get("gpu_preference", False),
            }
            self._platform_report = report
        return self._platform_report

    def supports(self, capability):
        if not capability:
            return True
        return bool(self.platform_report()["capabilities"].get(capability, False))

    # ---- library convenience / 库便捷方法 --------------------------------

    def groups(self):
        return self.store.get_all_groups()

    def all_group_id(self):
        # Public spelling of the builtin "All" pseudo-group id. The old window
        # called the private `_all_group_id()` from four places, which is how
        # the "All means None" rule leaked out of the store.
        # 内置"全部"伪分组 id 的公开写法。旧窗口从四处调用私有的 `_all_group_id()`，
        # "全部即 None"的规则正是这样从存储里泄漏出去的。
        return self.store._all_group_id()

    def is_all_group(self, group_id):
        return group_id is None or group_id == self.store._all_group_id()

    # ---- sending a sticker to another application / 把贴纸发送到其他应用 ----------
    #
    # This is the operation the application exists for, and it is one SEQUENCE with a
    # defined order. Copying and pasting are not two independent features:
    #
    #   1. put the sticker on the clipboard (text for a text sticker, the file as a URL
    #      for an image so a chat client can paste it as a picture);
    #   2. optionally ask the platform to deliver the paste keystroke.
    #
    # Doing them here rather than in a front-end means both front-ends send identically,
    # and it means the "did the paste land" question has one answer. The step that can
    # fail silently is step 2 — a hotkey may be swallowed, or the input backend may be
    # unavailable on this platform — so the result names which steps ran.
    #
    # 这是本应用存在的意义所在，而它是一个有确定顺序的"序列"。复制与粘贴不是两个独立功能：
    #
    #   1. 把贴纸放上剪贴板（文字贴纸放文本，图片贴纸放文件 URL，使聊天客户端能作为图片粘贴）；
    #   2. 可选地请平台投递粘贴按键。
    #
    # 在此而非在前端完成，意味着两个前端发送行为一致，也意味着"粘贴是否落地"只有一个答案。可能
    # 静默失败的是第 2 步——热键可能被吞掉，或输入后端在本平台不可用——因此结果会指明哪些步骤
    # 执行了。

    def clipboard_payload_for(self, emoji):
        # What should go on the clipboard for this row.
        #
        # Returned as a DESCRIPTION rather than applied here, because the clipboard is a
        # front-end concern: Qt owns it, and `core`/`backend` must not import Qt. The
        # front-end takes this description and performs it, which keeps the decision
        # ("text or file") in the testable layer and the mechanism in the Qt layer.
        # 返回"描述"而非在此应用，因为剪贴板属于前端关注点：Qt 拥有它，而 `core`/`backend`
        # 不得导入 Qt。前端取该描述并执行，使"文本还是文件"的决定留在可测试的层，而机制留在
        # Qt 层。
        if not emoji:
            return {"kind": "none"}
        text = emoji.get("text_content") or ""
        if text:
            return {"kind": "text", "text": text}
        path = self.store.emoji_filepath(emoji)
        if not path:
            return {"kind": "none"}
        return {"kind": "file", "path": path,
                "name": emoji.get("original_name", "")}

    def can_auto_send(self):
        # Whether this platform can deliver the paste keystroke.
        #
        # Asked through the platform layer so a front-end never has to test the OS
        # itself, and so the settings page's capability gate and this answer cannot
        # disagree — they read the same `supports()`.
        # 本平台能否投递粘贴按键。
        #
        # 经平台层询问，使前端无需自行判断操作系统，也使设置页的能力门控与本答案不会矛盾——它们
        # 读的是同一个 `supports()`。
        return bool(self.supports(settings_model.CAPABILITY_AUTO_INPUT))

    def input_backend(self):
        # The platform's input service, or a base instance that reports itself
        # unavailable. Resolved through `platform.service` so an unsupported platform
        # yields the base class rather than an AttributeError.
        # 平台的输入服务，或一个报告自身不可用的基类实例。经 `platform.service` 解析，使不受
        # 支持的平台给出基类而不是 AttributeError。
        from gifmanager import platform as platform_layer
        from gifmanager.platform.base import InputBackend

        return platform_layer.current().service("input", InputBackend)

    def auto_send_after(self, delay_ms=60):
        # Ask the platform to paste, after a short delay so the clipboard write settles.
        #
        # The delay is not superstition: the clipboard is owned by the OS and a paste
        # delivered in the same tick as the write can arrive before the new contents are
        # visible to the target, which pastes the PREVIOUS sticker.
        # 请平台粘贴，延迟一小段时间使剪贴板写入落地。
        #
        # 该延迟不是迷信：剪贴板由操作系统拥有，与写入同一时刻投递的粘贴可能在目标看到新内容之前
        # 到达，于是粘贴出"上一个"贴纸。
        if not self.can_auto_send():
            return {"ok": False, "reason": "this platform cannot send input"}
        backend = self.input_backend()
        if not getattr(backend, "available", False):
            return {"ok": False,
                    "reason": f"the input backend ({backend.name}) is unavailable"}
        try:
            delivered = backend.paste_to_foreground(delay_ms)
        except Exception as exc:
            log.exception("send: the input backend raised")
            return {"ok": False, "reason": str(exc)}
        return {"ok": bool(delivered),
                "reason": "" if delivered else "the paste keystroke was not delivered"}

    def default_group_id(self):
        return self.store.default_group_id()

    def stats(self, group_id=None, keyword=""):
        # Read-only counts for the status bar, so the front-end stops issuing
        # three queries of its own on every refresh.
        # 状态栏用的只读计数，使前端不再每次刷新都自行发三条查询。
        if group_id is None:
            total = self.store.count_image_emojis()
        else:
            total = self.store.count_emojis_in_group(group_id)
        matched = total if keyword else 0
        return {
            "group_id": group_id,
            "total": total,
            "keyword": keyword,
            "matched": matched,
            "all_total": self.store.count_all_emojis(),
        }

    def view(self, group_id=None, keyword=""):
        # The rows a front-end should display for a group (or the All view) /
        # 前端应为某分组（或"全部"视图）显示的行
        if self.is_all_group(group_id):
            return self.store.get_all_emojis(keyword=keyword)
        return self.store.get_emojis_by_group(group_id, keyword=keyword)

    # ---- lifecycle / 生命周期 -------------------------------------------

    def close(self):
        # Ordered teardown. The order matters and is documented here rather
        # than left to a caller: pending send copies reference files the store
        # owns, and the database must be closed after them.
        # 有序退出。顺序很重要，且在此记录而不是留给调用方：待清理的发送副本引用了
        # 存储持有的文件，数据库必须在它们之后关闭。
        if self._closed:
            return
        self._closed = True
        try:
            self.store.cleanup_send_temps()
        except Exception:
            log.exception("backend close: send-copy cleanup failed")
        try:
            self.store.close()
        except Exception:
            log.exception("backend close: store close failed")
        try:
            self.settings_store.sync()
        except Exception:
            log.exception("backend close: settings sync failed")
        with self._lock:
            self._subscribers.clear()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False


def _settings_path(data_dir):
    import os

    from gifmanager.backend.settings_store import SETTINGS_FILENAME

    return os.path.join(data_dir, SETTINGS_FILENAME)


def create_backend(data_dir=None, settings_store=None, log=True, **kwargs):
    # Build a backend with logging wired up. This is the entry point every
    # front-end (and every test) uses, so the log banner is printed exactly
    # once no matter which shell started.
    # 构建后端并接好日志。这是每个前端（以及每个测试）使用的入口，因此无论哪个外壳
    # 启动，日志横幅都只打印一次。
    if log:
        logging_setup.init_logger()
        logging_setup.install_excepthook()
        logging_setup.install_thread_excepthook()
    backend = Backend(data_dir=data_dir, settings_store=settings_store, **kwargs)
    log_settings(backend)
    return backend


def log_settings(backend):
    logger = logging_setup.get_logger()
    logger.info("=== %s %s ===", APP_NAME, __version__)
    logger.info("Settings file: %s", backend.settings_store.path
                if hasattr(backend.settings_store, "path") else "(memory)")
    logger.info("Data dir: %s", backend.data_dir)


def default_hotkey():
    # Binding a fresh install starts with / 全新安装使用的绑定
    return hotkey_core.HotkeyBinding(
        hotkey_core.DEFAULT_MODIFIERS, hotkey_core.DEFAULT_KEY)


__all__ = [
    "Backend",
    "CHANGE_LANGUAGE",
    "CHANGE_LIBRARY",
    "CHANGE_SETTINGS",
    "create_backend",
    "default_hotkey",
]
