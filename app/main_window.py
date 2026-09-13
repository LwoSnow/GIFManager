"""Main window management
主窗口管理"""
import os
import sys
import tempfile
import ctypes
import warnings
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QMenu, QScrollArea, QFrame, QLabel,
    QFileDialog, QMessageBox, QStatusBar, QApplication, QInputDialog,
    QSystemTrayIcon, QProgressDialog,
)
from PySide6.QtCore import (
    Qt, QSize, QMimeData, QPoint, QTimer, QSettings, QThreadPool, QStandardPaths,
    QEvent, QObject, QRunnable, Signal,
)
from PySide6.QtGui import (
    QDragEnterEvent, QDropEvent, QIcon, QAction, QKeyEvent, QKeySequence,
    QMouseEvent,
)

from app.theme.dark_theme import QSS as DARK_QSS
from app.theme.light_theme import QSS as LIGHT_QSS
from app.models.data_manager import DataManager
from app.models.lang_manager import tr, set_language, current_language, available_languages
from app import __version__
from app.utils.version import cmp_version, parse_version
from app.models.constants import (
    DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT,
)
from app.models.logger import init_logger, get_logger, install_excepthook, clear_logs
from app.widgets.group_list import GroupListWidget
from app.widgets.emoji_grid import EmojiGridWidget
from app.widgets.emoji_item import EmojiItem
from app.widgets.search_bar import SearchBar
from app.widgets.settings_dialog import SettingsDialog, recommended_thread_count
from app.widgets.hotkey_manager import HotkeyManager, GlobalScrollWatcher
from app.utils import gif_converter


def _root_dir():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _DragToolbar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._dragging = False
        self._drag_start = QPoint()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging:
            delta = event.globalPosition().toPoint() - self._drag_start
            w = self.window()
            if w:
                w.move(w.pos() + delta)
            self._drag_start = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._dragging = False
        super().mouseReleaseEvent(event)


# Smooth mouse-wheel scrolling: instead of the scrollbar jumping directly to
# the target, animate it toward the target with an easing QTimer so long
# scrolls feel continuous rather than teleporting. Dragging the slider keeps
# its immediate behavior; only mouse-wheel movement is smoothed.
# 平滑鼠标滚轮滚动：滚动条不再直接跳到目标，而是用缓动 QTimer 向目标动画
# 靠近，长距离滚动显得连贯而非瞬移。拖拽滑块保持即时；仅滚轮滚动平滑。
class SmoothScroll:
    STEPS = 12          # frames per glide / 每次滑动的帧数
    STEP_MS = 16        # ~60 fps / 约 60 帧每秒

    def __init__(self, scroll_area):
        self._sa = scroll_area
        # Parent the timer to the scroll area so it is cleaned up with the
        # widget (an unparented QTimer is only kept alive by this reference;
        # if the window is destroyed first, the timer could outlive it).
        # / 把定时器以滚动区为父对象，随控件一并回收（无父的 QTimer 仅靠本
        # 引用存活；窗口先销毁时定时器可能残留）。
        self._timer = QTimer(scroll_area)
        self._timer.setInterval(self.STEP_MS)
        self._timer.timeout.connect(self._tick)
        self._elapsed = 0      # frames completed in the current glide / 本次滑动已完成帧数
        self._start = 0.0      # value at glide start / 滑动起始值
        self._target = None    # desired final value / 目标终值
        self._installed = False

    def _vbar(self):
        if self._sa is None:
            return None
        return self._sa.verticalScrollBar()

    def reset(self):
        # Stop any in-flight glide (e.g. group/data change) / 停止进行中的
        # 滑动（如分组/数据变化）
        self._timer.stop()
        self._target = None

    def _ease(self, t):
        # Ease-out cubic: fast at the start, decelerating into the target.
        # This matches the "缓动分帧推进" described in the changelog (the old
        # constant-per-frame glide was linear, not eased).
        # / ease-out 三次曲线：起始快、临近目标减速。符合更新日志"缓动分帧推进"
        # （旧实现为等步长匀速，非缓动）。
        return 1.0 - (1.0 - t) ** 3

    def _tick(self):
        bar = self._vbar()
        if bar is None or self._target is None:
            self._timer.stop()
            return
        self._elapsed += 1
        t = min(1.0, self._elapsed / float(self.STEPS))
        value = self._start + (self._target - self._start) * self._ease(t)
        if t >= 1.0:
            bar.setValue(int(self._target))
            self._timer.stop()
            self._target = None
        else:
            bar.setValue(int(value))

    def handle_wheel(self, delta_y):
        # Called on a mouse-wheel event over the scroll area: set/continue a
        # smooth glide. / 在滚动区收到滚轮事件时调用：设置/继续一次平滑滑动。
        bar = self._vbar()
        if bar is None or bar.maximum() <= 0:
            return
        # Re-anchor the glide from the current value (a wheel event mid-glide
        # continues from where the bar actually is, not from the stale start).
        # / 从当前值重新锚定滑动（滑动中途又来滚轮时，从滚动条实际位置继续，
        # 而非过期的起始值）。
        if self._target is None:
            self._elapsed = 0
            self._start = float(bar.value())
            self._target = float(bar.value())
        # Qt angleDelta().y() is POSITIVE when the wheel scrolls UP (content
        # moves down) => scrollbar value must DECREASE. So subtract the delta.
        # / Qt angleDelta().y() 在滚轮向上滚时为正值（内容下移）=> 滚动条
        # value 应减小。故减去 delta（此前加 delta 导致方向反了）。
        self._target = max(0, min(bar.maximum(), self._target - delta_y))
        self._start = float(bar.value())
        self._elapsed = 0
        self._timer.start()


class _GpuProbeSignals(QObject):
    # Signal holder for the adapter probe / 显卡探测的信号载体
    done = Signal(list)


class _GpuProbeTask(QRunnable):
    # Probe the installed display adapters on a pool thread: the underlying
    # Windows query takes ~2 s, so it must never run on the GUI thread (doing
    # that when the settings dialog opened froze it). A pool task is used
    # instead of a raw QThread so Qt waits for it during shutdown (destroying a
    # running QThread aborts the process).
    # 在线程池线程上探测已安装显卡：底层 Windows 查询约需 2 秒，绝不能跑在
    # GUI 线程上（此前在设置对话框打开时执行导致卡顿）。使用线程池任务而非裸
    # QThread，使 Qt 在退出时统一等待（运行中的 QThread 被销毁会中止进程）。
    def __init__(self, signals):
        super().__init__()
        self._signals = signals

    def run(self):
        try:
            from app.utils import gpu_pref
            names = gpu_pref.list_adapters()
        except Exception:
            names = []
        try:
            from shiboken6 import isValid
            if not isValid(self._signals):
                return          # owner gone / 持有者已销毁
        except ImportError:
            pass
        try:
            self._signals.done.emit(names)
        except RuntimeError:
            pass


# QSettings factory. Production always returns the real user key; tests replace
# this function with one that points at a throwaway INI file, so a test run can
# never read or write the user's real preferences. This matters: a test that once
# called clear() on the production key silently wiped every setting, including
# "窗口置顶" and the chosen GPU.
# QSettings 工厂。生产环境始终返回用户真实的注册表键；测试会把这个函数替换为
# 指向临时 INI 文件的实现，使测试永远不会读写用户真实的偏好设置。这一点很
# 重要：曾经有测试对生产键调用 clear()，静默清空了包括"窗口置顶"与已选显卡
# 在内的所有设置。
def _new_settings():
    return QSettings("GIFManager", "GIFManager")


class MainWindow(QMainWindow):
    APP_TITLE = "GIFManager"
    # Nominal size of the settings icon (drawn at 75% of this) /
    # 设置图标的标称尺寸（实际按此的 75% 绘制）
    ICON_PX = 22

    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.APP_TITLE)
        self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self.setAcceptDrops(True)
        # Tool flag keeps the window out of the taskbar (tray-only UI);
        # StaysOnTopHint keeps it visible above the chat window; combined
        # with WA_ShowWithoutActivating it never steals focus on show.
        # Tool 标志使窗口不显示在任务栏（仅托盘图标）；StaysOnTopHint 保持
        # 窗口在聊天窗口之上；配合 WA_ShowWithoutActivating，显示时不抢焦点。
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(
            Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        icon_path = os.path.join(_root_dir(), "icon.ico")
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # Logging system / 日志系统
        init_logger()
        install_excepthook()
        self._log = get_logger()
        self._log.info(
            "App version: %s | theme: pending | thread_count: pending",
            __version__,
        )

        self._settings = _new_settings()
        self.data_manager = DataManager()
        self.current_group_id = None
        self._send_mode = 0
        self._remember_group = True
        self._hotkey_registered = False
        self._settings_dialog = None

        self._load_settings()
        self._setup_ui()
        self._apply_theme()
        self._connect_signals()
        self._setup_tray()
        self._init_hotkey_mgr()
        self._apply_thread_count()
        self._install_no_activate_filter()

        self._restore_geometry()

        saved_gid = self._restore_group()
        if saved_gid is not None:
            self.group_list.select_group(saved_gid)
        else:
            self.group_list.select_all_group()

    # QSettings / QSettings 设置持久化

    def _load_settings(self):
        # All numeric reads use QSettings' type= keyword (returns the default
        # on corrupt/typed-mismatch values); direct int()/float() casts used
        # to crash startup on dirty registry data / 所有数值读取都用 QSettings
        # 的 type= 关键字（类型不符/脏数据时返回默认值）；此前直接用
        # int()/float() 强转，注册表脏数据会导致启动崩溃
        self._send_mode = self._settings.value("send_mode", 0, type=int)
        self._remember_group = self._settings.value("remember_group", True, type=bool)
        self._autostart = self._settings.value("autostart", False, type=bool)
        self._always_on_top = self._settings.value("always_on_top", False, type=bool)
        # Number of multi-threaded cores (0 = automatic, use recommended values)
        # 多线程核心数（0 = 自动，使用推荐值）
        self._thread_count = self._settings.value("thread_count", 0, type=int)
        self._apply_thread_count()
        # Theme (dark light)
        # 主题（暗色/亮色）
        self._theme = self._settings.value("theme", "dark")
        # Text preview restrictions (single line, multiple lines independent)
        # 文字预览限制（单行 / 多行独立）
        self._text_limit_single = self._settings.value(
            "text_preview_limit_single", 100, type=int)
        self._text_limit_multi = self._settings.value(
            "text_preview_limit_multi", 200, type=int)
        # Global sorting mode (time/name/freq, asc/desc) / 全局排序模式（时间/名称/频率，正/逆序）
        self._gs_enabled = self._settings.value("global_sort_enabled", False, type=bool)
        by = self._settings.value("global_sort_by", "time")
        self._gs_by = by if by in ("time", "name", "freq") else "time"
        self._gs_desc = self._settings.value("global_sort_desc", False, type=bool)
        # Auto-convert imported non-gif images to gif / 导入时自动把非 gif 图片转为 gif
        self._auto_convert_gif = self._settings.value("auto_convert_gif", True, type=bool)
        # Auto-update check on startup / 启动时自动检查更新
        self._auto_update = self._settings.value("auto_update", False, type=bool)
        # Show the emoji name under the thumbnail / 缩略图下方显示表情包名称
        self._show_emoji_name = self._settings.value("show_emoji_name", True, type=bool)
        # Hover zoom factor for image cards / 图片卡悬停放大倍数
        try:
            self._hover_zoom = max(
                1.0, float(self._settings.value("hover_zoom", 1.15)))
        except (TypeError, ValueError):
            self._hover_zoom = 1.15
        # Master switch for the hover preview / 悬停预览总开关
        self._hover_preview_enabled = self._settings.value(
            "hover_preview_enabled", True, type=bool)
        # Card scale factor / 卡片缩放系数
        try:
            self._card_scale = max(
                0.5, min(2.0, float(self._settings.value("card_scale", 1.0))))
        except (TypeError, ValueError):
            self._card_scale = 1.0
        # Name font size for image cards / 图片卡名字字号
        try:
            self._name_font_size = max(
                1, min(20, int(self._settings.value("name_font_size", 10))))
        except (TypeError, ValueError):
            self._name_font_size = 10
        EmojiItem.set_name_font_size(self._name_font_size)
        # Click an emoji -> auto-type (Ctrl+V) into the focused chat input /
        # 点击表情 → 自动输入（Ctrl+V）到焦点聊天输入框
        self._auto_input = self._settings.value("auto_input", True, type=bool)
        # FFmpeg: master switch + optional user-chosen binary path /
        # FFmpeg：总开关 + 可选的用户自定义可执行文件路径
        self._ffmpeg_enabled = self._settings.value(
            "ffmpeg_enabled", True, type=bool)
        self._ffmpeg_path = self._settings.value("ffmpeg_path", "")
        from app.utils import gif_converter as _gc
        _gc.set_ffmpeg_config(path=self._ffmpeg_path,
                              enabled=self._ffmpeg_enabled)
        # Animated-GIF render concurrency (auto by cores / manual count) and
        # the experimental GPU rendering switch / 动态 GIF 渲染并发（按核心数
        # 自动 / 自定义数量）与实验性 GPU 渲染开关
        mode = self._settings.value("gif_render_mode", "auto")
        self._gif_render_mode = mode if mode in ("auto", "manual") else "auto"
        self._gif_render_count = self._settings.value(
            "gif_render_count", 0, type=int)
        self._gpu_render = self._settings.value("gpu_render", False, type=bool)
        # Master switch for GPU/accelerated rendering: ON renders thumbnails in
        # parallel and applies the chosen adapter preference; OFF clears it.
        # GPU/加速渲染总开关：开启时并行渲染缩略图并写入所选显卡偏好；关闭时清除。
        self._gpu_accel = self._settings.value(
            "gpu_accel", self._gpu_render, type=bool)
        # Experimental GPU (OpenGL) viewport. Opt-in and applied at STARTUP only
        # (see _apply_gpu_viewport), so changing it needs a restart.
        # 实验性 GPU（OpenGL）视口。可选，且仅在启动时安装（见
        # _apply_gpu_viewport），因此修改后需重启生效。
        self._gpu_viewport = self._settings.value(
            "gpu_viewport", False, type=bool)
        self._gpu_viewport_installed = False
        self._gpu_viewport_widget = None
        # Windows per-app GPU preference (0 system / 1 power / 2 high perf) /
        # Windows 按应用 GPU 首选项（0 系统 / 1 省电 / 2 高性能）
        self._gpu_pref = self._settings.value("gpu_pref", 0, type=int)
        if self._gpu_pref not in (0, 1, 2):
            self._gpu_pref = 0
        # GPU acceleration: parallel thumbnail rendering (every CPU core) /
        # GPU 加速：并行缩略图渲染（使用全部 CPU 核心）
        EmojiItem.set_parallel_render(self._gpu_accel)
        # Cached GPU adapter names (so the settings dialog lists them by name
        # without running the ~2 s detection). / 缓存的显卡名称（使设置对话框
        # 直接按名称列出，无需执行约 2 秒的检测）。
        cached = self._settings.value("gpu_adapters", "")
        self._gpu_adapters = [n for n in str(cached).split("|") if n.strip()]
        self._gpu_probe_signals = None
        lang = self._settings.value("language", "zh_CN")
        try:
            set_language(lang)
        except Exception:
            pass
        self._apply_always_on_top()
        self._apply_autostart()

    def _apply_thread_count(self):
        # Multi-threaded core limit setting
        # 多线程核心数限制设置
        n = self._thread_count if self._thread_count > 0 else recommended_thread_count()
        pool = QThreadPool.globalInstance()
        if pool.maxThreadCount() != n:
            pool.setMaxThreadCount(n)
        if hasattr(self, "emoji_grid"):
            # GIF frames are decoded off the GUI thread (gifdec.dll) and
            # cached, so playback is just a pixmap swap; raise the
            # concurrent-playback cap accordingly (was core*2, too low on
            # multi-core machines). The user can instead pin an explicit
            # number of simultaneously rendered GIFs in Settings -> Performance.
            # GIF 帧已在后台（gifdec.dll）解码并缓存，播放只是切换 pixmap，
            # 故提高同时播放上限（原为核心数×2，多核机器上偏少）。用户也可在
            # 设置 → 性能 中指定同时渲染的动态 GIF 数量。
            mode = getattr(self, "_gif_render_mode", "auto")
            count = getattr(self, "_gif_render_count", 0)
            if mode == "manual" and count > 0:
                self.emoji_grid._gif_limit = max(1, count)
            else:
                self.emoji_grid._gif_limit = max(8, n * 4)

    def _apply_gpu_preference(self, explicit=False):
        # Windows' per-application GPU preference (HKCU DirectX
        # UserGpuPreferences). Qt cannot bind a process to an adapter, so this
        # is the only real mechanism; it takes effect on the next launch.
        #
        # `explicit` is True only when the user pressed OK in Settings. A
        # non-explicit (startup) call must NOT delete an existing entry: the
        # app would otherwise silently erase a Windows-level, app-wide setting
        # that the user may have made in Windows Settings — and any run with
        # acceleration off (including every test run) wiped it. Startup only
        # writes (or refreshes) a real choice (acceleration on AND a specific
        # adapter); removal happens on the explicit user action alone. It also
        # must not DELETE when acceleration is on but the adapter is "system
        # default" (pref 0) — that is not a request to clear anything.
        # `explicit` 仅在用户于设置中按下确定时为 True。非显式（启动）调用绝不
        # 删除已有项：否则程序会静默抹掉用户在 Windows 设置里做过的、系统级的
        # 按应用设置——而且任何"加速关闭"的运行（包括每次测试）都会清掉它。
        # 启动时只写入（刷新）真正的选择（加速开启"且"指定了显卡）；删除只由用户
        # 的显式操作触发。加速开启但显卡为"系统默认"（pref 0）时同样不得删除——
        # 那并不表示要清除任何东西。
        try:
            from app.utils import gpu_pref
            accel = bool(getattr(self, "_gpu_accel", False))
            pref = int(getattr(self, "_gpu_pref", 0) or 0)
            if not accel:
                if not explicit:
                    self._log.info(
                        "GPU preference -> startup, left untouched / 未改动")
                    return
                # The user turned the switch OFF: clear our request /
                # 用户关闭了开关：清除本程序的请求
                pref = 0
            elif not pref:
                # Acceleration is ON but the adapter is "system default": the
                # user asked for NO specific GPU. Deleting the entry here would
                # be exactly backwards — it used to REMOVE the discrete-GPU
                # request the moment the switch was turned on, which is why
                # enabling "GPU acceleration" appeared to STOP using the GPU.
                # 加速开启但显卡为"系统默认"：用户并未指定任何显卡。此时删除该项
                # 恰好相反——此前正是在打开开关的一刻把独显请求删掉，于是"开启
                # GPU 加速"看起来反而不用独显了。
                self._log.info(
                    "GPU preference -> accel on, adapter unset, left "
                    "untouched / 未指定显卡，未改动")
                return
            exe = gpu_pref.current_exe()
            ok = gpu_pref.apply_preference(exe, pref)
            self._log.info(
                "GPU preference -> explicit=%s accel=%s pref=%s exe=%s "
                "applied=%s", explicit, accel, pref, exe, ok)
        except Exception:
            self._log.exception("Apply GPU preference failed")

    def _start_gpu_adapter_probe(self):
        # Run the ~2 s adapter detection on a pool thread once, then cache the
        # result so later launches list the GPUs instantly. The pool is OWNED by
        # the window (not the global instance) so _stop_gpu_adapter_probe() can
        # really drain it: Qt only awaits the global pool at shutdown, and a
        # task that outlived the window used to signal a destroyed receiver
        # while the process was exiting.
        # 在线程池上执行一次约 2 秒的显卡检测并缓存结果，使后续启动可立即列显卡。
        # 该池由窗口自己持有（不用全局池），这样 _stop_gpu_adapter_probe() 才能真
        # 正排空它：Qt 只在退出时等待全局池，而比窗口活得更久的任务会在进程退出时
        # 向已销毁的接收者发信号。
        if self._gpu_adapters:
            return
        try:
            if getattr(self, "_gpu_pool", None) is None:
                self._gpu_pool = QThreadPool()
                self._gpu_pool.setMaxThreadCount(1)
            self._gpu_probe_signals = _GpuProbeSignals()
            self._gpu_probe_signals.done.connect(self._on_gpu_probe_done)
            self._gpu_pool.start(_GpuProbeTask(self._gpu_probe_signals))
        except Exception:
            self._log.exception("Start GPU adapter probe failed")

    def _on_gpu_probe_done(self, names):
        # Cache the detected adapters for the settings dialog / 缓存检测到的
        # 显卡供设置对话框使用
        self._gpu_adapters = [str(n) for n in (names or []) if str(n).strip()]
        if self._gpu_adapters:
            self._settings.setValue("gpu_adapters", "|".join(self._gpu_adapters))
            self._log.info("GPU adapters cached -> %s", self._gpu_adapters)

    def _apply_gpu_render(self, at_startup=True):
        # GPU handling is now ONLY the Windows per-application GPU preference
        # (see _apply_gpu_preference). The earlier experimental OpenGL viewport
        # swap was removed because field reports showed it is not a usable
        # control:
        #   - its first paint could be black (an empty group showed a pure black
        #     page until a full repaint happened),
        #   - re-creating it while toggling crashed the renderer and left the
        #     sticker page completely black,
        #   - and it never determined which GPU the app actually used, so turning
        #     it "off" left the GPU preference in place.
        # Qt also cannot bind a process to an adapter; the OS-level preference is
        # the supported mechanism.
        # GPU 处理现在只依赖 Windows 的按应用 GPU 首选项（见
        # _apply_gpu_preference）。此前的实验性 OpenGL 视口切换已移除，因为实际
        # 反馈表明它并不是一个可用的控件：
        #   - 首次绘制可能是黑的（空分组显示整页纯黑，直到一次完整重绘才恢复），
        #   - 反复创建/销毁它会导致渲染崩溃、表情包页面整片变黑，
        #   - 而且它并不决定程序实际使用哪块显卡，所以"关闭"后 GPU 偏好依然
        #     生效（独显仍被调用）。
        # Qt 也无法把进程绑定到指定显卡；操作系统级首选项才是受支持的机制。
        # NOTE: the OpenGL viewport is back as an OPT-IN experiment
        # (_apply_gpu_viewport, default off, startup only) because users asked for
        # the process to really touch the GPU — see that method for how the two
        # field problems (black first paint, crashes on toggling) are avoided.
        # 注意：OpenGL 视口已作为"可选实验"重新加入（_apply_gpu_viewport，默认
        # 关闭、仅启动时安装），因为用户希望进程真正用到 GPU——两个实测问题
        # （首帧全黑、切换崩溃）的规避方式见该方法。
        self._apply_viewport_background()

    def _apply_gpu_viewport(self):
        # Install the experimental GPU (OpenGL) viewport — STARTUP ONLY.
        #
        # Qt paints widget hierarchies with the CPU raster engine, so the app's
        # own GPU usage is zero and the Windows per-app preference has nothing to
        # route. Compositing the grid through an OpenGL surface makes the process
        # really use the GPU. It stays opt-in (default off) and is applied once
        # at startup, because the two problems reported for the earlier attempt
        # both came from runtime swapping:
        #   * re-creating the viewport while toggling crashed the renderer,
        #   * a freshly created surface could present one black frame (an empty
        #     group looked pure black) — mitigated by keeping the theme colour in
        #     the viewport's palette and by NoPartialUpdate (see gl_viewport.py),
        #     plus a queued update so the colour lands immediately.
        # It also does not pick an adapter — that is what the Windows preference
        # is for. / 安装实验性 GPU（OpenGL）视口——仅在启动时。
        # Qt 用 CPU 光栅引擎绘制控件层级，因此程序自身 GPU 占用为零，Windows 的
        # 按应用偏好没有可调度的任务。把网格通过 OpenGL 表面合成可让进程真正使用
        # GPU。它保持可选（默认关闭）且只在启动时应用一次，因为此前那次尝试的两个
        # 问题都源于运行时替换：切换时重建视口会让渲染器崩溃；刚创建的表面会出现
        # 一帧全黑（空分组看起来纯黑）——后者通过把主题色放进视口调色板、使用
        # NoPartialUpdate（见 gl_viewport.py）以及排队一次 update 立即铺色来规避。
        # 它同样不决定使用哪块显卡——那是 Windows 首选项的职责。
        if not getattr(self, "_gpu_viewport", False):
            return
        # The master switch is authoritative: no GPU acceleration, no GPU surface /
        # 总开关优先：未开启加速就不安装 GPU 表面
        if not getattr(self, "_gpu_accel", False):
            self._log.info(
                "GPU viewport requested but acceleration is off / 已请求 GPU 视口"
                "但加速未开启，跳过")
            return
        if getattr(self, "_gpu_viewport_installed", False):
            return
        if not self._gpu_viewport_supported():
            self._log.info(
                "Platform has no OpenGL (%s); keeping the CPU viewport / "
                "当前平台无 OpenGL，继续使用 CPU 视口", self._platform_name())
            return
        try:
            from app.widgets.gl_viewport import GridGlViewport
            # IMPORTANT: setViewport() takes ownership of the new widget and
            # DELETES the old viewport — and the scroll area's widget (our grid)
            # is a child of that viewport, so a naive swap destroys the grid
            # (symptom: "Signal source has been deleted" on the next line).
            # takeWidget() first detaches the grid so it survives the swap.
            # 关键：setViewport() 会接管新控件并**删除旧视口**——而滚动区的
            # widget（我们的网格）正是旧视口的子控件，因此直接替换会把网格一起
            # 销毁（症状：下一行就报 "Signal source has been deleted"）。先
            # takeWidget() 把网格摘出来，它才能挺过这次替换。
            grid = self._scroll_area.takeWidget()
            gl = GridGlViewport(self._scroll_area)
            self._scroll_area.setViewport(gl)
            if grid is not None:
                self._scroll_area.setWidget(grid)
            self._gpu_viewport_installed = True
            self._gpu_viewport_widget = gl
            # Re-apply the theme palette to the NEW viewport /
            # 给新视口重新套用主题调色板
            self._apply_viewport_background()
            QTimer.singleShot(0, gl.update)
            # Verify the context really came up; if it did not (driver refuses,
            # remote session, ...) fall back so the grid stays usable.
            # 核实上下文是否真的建立；若没有（驱动拒绝、远程会话等）则回退，
            # 保证网格仍可用。
            QTimer.singleShot(1200, self._verify_gpu_viewport)
            self._log.info(
                "Experimental GPU viewport installed / 实验性 GPU 视口已安装")
        except Exception:
            self._gpu_viewport_installed = False
            self._gpu_viewport_widget = None
            self._log.exception(
                "GPU viewport install failed; keeping the CPU viewport / "
                "GPU 视口安装失败，继续使用 CPU 视口")

    @staticmethod
    def _platform_name():
        try:
            from PySide6.QtGui import QGuiApplication
            return (QGuiApplication.platformName() or "").lower()
        except Exception:
            return ""

    def _gpu_viewport_supported(self):
        # Qt's offscreen/minimal platforms have no OpenGL at all: QOpenGLWidget
        # there logs "not supported on this platform" and never obtains a
        # context, so installing one would only cost a repaint path.
        # Qt 的 offscreen/minimal 平台完全没有 OpenGL：那里的 QOpenGLWidget 会打印
        # "not supported on this platform" 且永远拿不到上下文，装上去只会白搭一条
        # 绘制路径。
        return self._platform_name() not in ("offscreen", "minimal", "minimalegl")

    def _verify_gpu_viewport(self):
        # Deferred check: a QOpenGLWidget is only valid once it has been shown
        # and initialised. If it still is not, swap back to a plain viewport.
        # 延迟核实：QOpenGLWidget 只有在显示并初始化后才有效。若仍无效，则换回
        # 普通视口。
        if not getattr(self, "_gpu_viewport_installed", False):
            return
        gl = getattr(self, "_gpu_viewport_widget", None)
        try:
            valid = gl is not None and gl.isValid()
        except RuntimeError:
            valid = False
        if valid:
            self._log.info("GPU viewport context is valid / GPU 视口上下文有效")
            return
        self._log.warning(
            "GPU viewport has no usable context; falling back to the CPU "
            "viewport / GPU 视口没有可用上下文，回退到 CPU 视口")
        try:
            grid = self._scroll_area.takeWidget()
            self._scroll_area.setViewport(QWidget())
            if grid is not None:
                self._scroll_area.setWidget(grid)
        except Exception:
            self._log.exception("GPU viewport rollback failed / GPU 视口回退失败")
        self._gpu_viewport_installed = False
        self._gpu_viewport_widget = None
        self._apply_viewport_background()

    def _gpu_viewport_valid(self):
        # True once the GL context really exists (None until the widget has been
        # shown and initialised, and on platforms without OpenGL).
        # GL 上下文真正存在时为 True（控件显示并初始化前为 None；无 OpenGL 的平台
        # 同样为 None）。
        gl = getattr(self, "_gpu_viewport_widget", None)
        if gl is None:
            return None
        try:
            return gl.context() is not None
        except RuntimeError:
            return None

    def _apply_viewport_background(self):
        # Paint the scroll viewport (and the grid) with the theme surface colour
        # so the empty area can never fall through to an unthemed/black
        # viewport. / 用主题表面色绘制滚动视口（与网格），使空白区域绝不会
        # 透出未上主题/纯黑的视口。
        try:
            from PySide6.QtGui import QPalette, QColor
        except ImportError:
            return
        dark = (getattr(self, "_theme", "dark") != "light")
        color = QColor("#1E1E1E") if dark else QColor("#F2F3F5")
        for wdg in (self._scroll_area.viewport(), getattr(self, "emoji_grid", None)):
            if wdg is None:
                continue
            try:
                wdg.setAutoFillBackground(True)
                pal = wdg.palette()
                pal.setColor(QPalette.ColorRole.Window, color)
                pal.setColor(QPalette.ColorRole.Base, color)
                wdg.setPalette(pal)
            except RuntimeError:
                continue

    def _install_no_activate_filter(self):
        # Start the focus guard: clicking this window must never steal focus
        # from the chat input — the auto-input feature pastes (Ctrl+V) into
        # the window that still owns focus. The guard tracks "the last
        # non-manager foreground window" and hands focus back whenever the
        # manager gets activated by a click.
        # 启动焦点守卫：点击本窗口不得夺走聊天输入框焦点——自动输入功能向
        # 仍持有焦点的窗口粘贴（Ctrl+V）。守卫跟踪"最近一个非管理器的前台
        # 窗口"，管理器被点击激活时立即归还焦点。
        try:
            from app.utils.input_sender import FocusGuard
            self._focus_guard = FocusGuard(int(self.winId()))
            self._focus_guard.start()
        except Exception:
            self._log.exception("Install focus guard failed")

    def _save_settings(self):
        self._settings.setValue("send_mode", self._send_mode)
        self._settings.setValue("remember_group", self._remember_group)
        self._settings.setValue("autostart", self._autostart)
        self._settings.setValue("always_on_top", self._always_on_top)
        self._settings.setValue("thread_count", self._thread_count)
        self._settings.setValue("theme", self._theme)
        self._settings.setValue("ffmpeg_enabled", self._ffmpeg_enabled)
        self._settings.setValue("ffmpeg_path", self._ffmpeg_path)
        self._settings.setValue("gif_render_mode", self._gif_render_mode)
        self._settings.setValue("gif_render_count", self._gif_render_count)
        self._settings.setValue("gpu_render", self._gpu_render)
        self._settings.setValue("gpu_accel", self._gpu_accel)
        self._settings.setValue("gpu_viewport", self._gpu_viewport)
        self._settings.setValue("gpu_pref", self._gpu_pref)
        self._settings.setValue("gpu_adapters", "|".join(self._gpu_adapters))
        self._settings.setValue("text_preview_limit_single", self._text_limit_single)
        self._settings.setValue("text_preview_limit_multi", self._text_limit_multi)
        self._settings.setValue("global_sort_enabled", self._gs_enabled)
        self._settings.setValue("global_sort_by", self._gs_by)
        self._settings.setValue("global_sort_desc", self._gs_desc)
        self._settings.setValue("auto_convert_gif", self._auto_convert_gif)
        self._settings.setValue("auto_update", self._auto_update)
        self._settings.setValue("show_emoji_name", self._show_emoji_name)
        self._settings.setValue("hover_zoom", self._hover_zoom)
        self._settings.setValue("hover_preview_enabled", self._hover_preview_enabled)
        self._settings.setValue("card_scale", self._card_scale)
        self._settings.setValue("name_font_size", self._name_font_size)
        self._settings.setValue("auto_input", self._auto_input)
        self._settings.setValue("language", current_language())

    def _restore_geometry(self):
        geo = self._settings.value("window_geometry")
        if geo:
            self.restoreGeometry(geo)
        else:
            self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
            screen = QApplication.primaryScreen().availableGeometry()
            self.move(
                (screen.width() - self.width()) // 2,
                (screen.height() - self.height()) // 2,
            )

    def _save_geometry(self):
        self._settings.setValue("window_geometry", self.saveGeometry())

    def _apply_always_on_top(self):
        # setWindowFlag implicitly hides the window; record visibility and restore
        # setWindowFlag 会隐式隐藏窗口：先记录可见性再恢复显示
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self._always_on_top)
        if was_visible:
            self.show()

    def _apply_autostart(self):
        # Windows startup entry (registry Run key) / 开机启动项（注册表 Run 键）
        if sys.platform != "win32":
            return
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
            )
            if self._autostart:
                exe_path = sys.executable
                script = os.path.abspath(sys.argv[0]) if sys.argv else ""
                winreg.SetValueEx(key, "GIFManager", 0, winreg.REG_SZ,
                                  f"\"{exe_path}\" \"{script}\"")
            else:
                try:
                    winreg.DeleteValue(key, "GIFManager")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception:
            pass

    def _save_current_group(self):
        if self._remember_group and self.current_group_id is not None:
            g = self.data_manager.get_group(self.current_group_id)
            if g:
                self._settings.setValue("last_group_name", g["name"])

    def _restore_group(self):
        if not self._remember_group:
            return None
        name = self._settings.value("last_group_name", "")
        if name:
            g = self.data_manager.get_group_by_name(name)
            if g:
                return g["id"]
        return None

    # showEvent — Register hotkey + rounded corners after window is shown / 窗口显示后注册热键 + 圆角

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_rounded()
        QTimer.singleShot(200, self._register_hotkey_if_needed)
        # Start global Alt+scroll watcher for card scaling /
        # 启动全局 Alt+滚轮监听器（卡片缩放）
        if hasattr(self, "_scroll_watcher"):
            self._scroll_watcher.start(self._on_global_scroll)
        # Keep the focus guard's manager handle in sync / 同步焦点守卫的
        # 管理器句柄
        try:
            if getattr(self, "_focus_guard", None) is not None:
                self._focus_guard.set_manager(int(self.winId()))
        except Exception:
            pass

    def hideEvent(self, event):
        super().hideEvent(event)
        if hasattr(self, "_scroll_watcher"):
            self._scroll_watcher.stop()

    def _apply_rounded(self):
        if sys.platform != "win32":
            return
        try:
            hwnd = int(self.winId())
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33,  # DWMWA_WINDOW_CORNER_PREFERENCE
                ctypes.byref(ctypes.c_int(2)),  # DWMWCP_ROUND
                ctypes.sizeof(ctypes.c_int),
            )
        except Exception:
            pass

    # UI / 界面构建

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        toolbar = _DragToolbar()
        toolbar.setObjectName("mainToolbar")
        toolbar.setFixedHeight(46)
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 6, 8, 6)
        toolbar_layout.setSpacing(8)

        self.search_bar = SearchBar()
        toolbar_layout.addWidget(self.search_bar, 1)

        self.btn_import = QPushButton(tr("import_gif"))
        self.btn_import.setFixedHeight(32)
        self._build_import_menu()
        toolbar_layout.addWidget(self.btn_import)

        self.btn_add_text = QPushButton(tr("add_text"))
        self.btn_add_text.setFixedHeight(32)
        self.btn_add_text.hide()
        toolbar_layout.addWidget(self.btn_add_text)

        self.btn_settings = QPushButton()
        self.btn_settings.setFixedSize(32, 32)
        self.btn_settings.setFlat(True)
        self.btn_settings.setToolTip(tr("settings"))
        self._apply_settings_icon()
        toolbar_layout.addWidget(self.btn_settings)

        root.addWidget(toolbar)

        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFixedHeight(1)
        root.addWidget(sep)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.emoji_grid = EmojiGridWidget()
        # Explicit surface background so the empty area can never fall through
        # to an unthemed (e.g. black) viewport — an empty group used to look
        # pure black, which was the GL viewport showing through.
        # 显式设置表面背景，使空白区域不会透出未上主题的（如纯黑）视口——
        # 空分组曾显示为纯黑，正是 GL 视口透出所致。
        self.emoji_grid.setObjectName("emojiGrid")
        self.emoji_grid._show_emoji_name = self._show_emoji_name
        self.emoji_grid._card_scale = self._card_scale
        EmojiItem._card_scale = self._card_scale
        self.emoji_grid._hover_zoom = self._hover_zoom
        self.emoji_grid._hover_preview_enabled = self._hover_preview_enabled
        # Global sort only picks the ordering kind (name/time/frequency); the
        # resize auto-fill is independent of it now.
        # 全局排序只决定排序依据（名称/时间/频率）；拉伸自动铺满已与它无关。
        self.emoji_grid._global_sort_enabled = self._gs_enabled
        # Concurrent animated-GIF render cap (Settings -> Performance) /
        # 动态 GIF 同时渲染上限（设置 → 性能）
        self._apply_thread_count()
        # Experimental GPU rendering of the grid viewport / 实验性 GPU 渲染网格视口
        self._apply_gpu_render()
        # Keep the Windows per-app GPU preference in sync with the setting
        # (also re-applies if the executable path changed). /
        # 保持 Windows 按应用 GPU 首选项与设置一致（可执行文件路径变化时也会重写）。
        self._apply_gpu_preference()
        # Probe the installed adapters in the background (only when nothing is
        # cached) so the settings dialog can list them by name without ever
        # blocking. / 后台探测已安装显卡（仅在无缓存时），使设置对话框能按名称
        # 列出而绝不阻塞。
        self._start_gpu_adapter_probe()
        self._scroll_area.setWidget(self.emoji_grid)
        root.addWidget(self._scroll_area, 1)
        # Experimental GPU viewport: install it HERE, before anything captures a
        # reference to the current (CPU) viewport — the event filter below is
        # installed on the viewport, and setViewport() replaces and destroys the
        # old one. Startup only: the surface is never swapped at runtime, which
        # is what used to crash the renderer when the switch was toggled.
        # 实验性 GPU 视口：必须在"任何地方持有当前（CPU）视口引用"之前安装——
        # 下面的事件过滤器装在视口上，而 setViewport() 会替换并销毁旧视口。仅启动
        # 时安装：运行时绝不替换表面，此前反复切换正是因此让渲染器崩溃。
        self._apply_gpu_viewport()

        self.group_list = GroupListWidget(self.data_manager)
        root.addWidget(self.group_list)

        # Smooth scroll controller: intercept mouse-wheel over the scroll
        # area and animate the scrollbar toward the target instead of
        # jumping instantly. Dragging the slider stays immediate.
        # 平滑滚动控制器：拦截滚动区内的鼠标滚轮，向目标值动画滚动而非瞬移。
        # 拖拽滑块仍保持即时。
        self._smooth_scroll = SmoothScroll(self._scroll_area)
        self._scroll_area.viewport().installEventFilter(self)
        self.group_list.groups_updated.connect(self._on_smooth_scroll_reset)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._build_edit_toolbar()
        self._refresh_status()

    def _build_edit_toolbar(self):
        # Multi-select edit toolbar, shown in the status bar while edit mode
        # is active: delete selected, move selected to another group of the
        # same type, exit. / 多选编辑操作栏：多选模式下显示在状态栏：删除
        # 所选、移动到同类型分组、退出。
        from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget
        bar = QWidget(self)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(6)
        self._edit_count_label = QLabel("0")
        self._edit_count_label.setObjectName("editCount")
        lay.addWidget(self._edit_count_label)
        self._btn_edit_select_all = QPushButton(tr("edit_select_all"))
        self._btn_edit_select_all.setObjectName("editToolBtn")
        self._btn_edit_select_all.clicked.connect(self._edit_select_all)
        lay.addWidget(self._btn_edit_select_all)
        self._btn_edit_delete = QPushButton(tr("edit_delete"))
        self._btn_edit_delete.setObjectName("editToolBtn")
        self._btn_edit_delete.clicked.connect(self._edit_delete_selected)
        lay.addWidget(self._btn_edit_delete)
        self._edit_move_btn = QPushButton(tr("edit_move"))
        self._edit_move_btn.setObjectName("editToolBtn")
        # Connected ONCE; the menu is built lazily on click /
        # 只连接一次；菜单在点击时惰性构建
        self._edit_move_btn.clicked.connect(self._on_edit_move_clicked)
        lay.addWidget(self._edit_move_btn)
        self._btn_edit_exit = QPushButton(tr("edit_exit"))
        self._btn_edit_exit.setObjectName("editToolBtn")
        self._btn_edit_exit.clicked.connect(self._exit_edit_mode)
        lay.addWidget(self._btn_edit_exit)
        bar.hide()
        self._edit_bar = bar
        self.status_bar.addPermanentWidget(bar)
        # Cached move-target menu: built lazily and reused while the selection
        # signature is unchanged (it used to be rebuilt — and leaked — once per
        # check-state change). / 缓存的移动目标菜单：惰性构建，选中特征不变时
        # 复用（此前每次勾选变化都重建一次并泄漏）。
        self._edit_move_menu = None
        self._edit_move_sig = None

    def _enter_edit_mode(self):
        # Enter multi-select edit mode on the grid / 让网格进入多选编辑模式
        self.emoji_grid.enter_edit_mode()

    def _exit_edit_mode(self):
        self.emoji_grid.exit_edit_mode()

    def _on_edit_mode_changed(self, enabled):
        # Show/hide the edit toolbar and stop hover previews while editing /
        # 显示/隐藏编辑操作栏；编辑期间停用悬停预览
        self._edit_bar.setVisible(bool(enabled))
        if not enabled:
            self._refresh_status()
        else:
            self._update_edit_count(0)

    def _on_selection_count_changed(self, count):
        self._update_edit_count(count)

    def _update_edit_count(self, count):
        self._edit_count_label.setText(tr("edit_selected", count=count))
        # Only enable the move submenu when at least one item is selected /
        # 至少选中一项时才允许移动
        has = count > 0
        self._btn_edit_delete.setEnabled(has)
        self._edit_move_btn.setEnabled(has)
        # The move menu itself is built lazily on click (see
        # _ensure_edit_move_menu). Building it here ran a get_all_groups()
        # query and created a fresh QMenu for EVERY card whose check state
        # changed — during "select all" on a large library that was one query
        # plus one leaked menu per card.
        # 移动菜单改为点击时惰性构建（见 _ensure_edit_move_menu）。此前在这里构建
        # 会对"每一张勾选状态变化的卡片"执行一次 get_all_groups() 查询并新建一个
        # QMenu——大图库全选时就是每张卡一次查询加一个泄漏的菜单。
        self._edit_move_sig = None

    def _ensure_edit_move_menu(self):
        # Build (or reuse) the move-target menu for the current selection.
        # Targets must match the type of the selected items (image groups only
        # for images, text groups only for text) so the two kinds never mix.
        # 构建（或复用）当前选中的移动目标菜单。目标必须与所选内容类型一致
        # （图片只能进图片分组、文字只能进文字分组），两类互不串组。
        selected = self.emoji_grid.selected_emojis()
        if not selected:
            return None
        is_text = all(bool(e.get("text_content")) for e in selected)
        groups = self.data_manager.get_all_groups()
        all_id = self.data_manager._all_group_id()
        cur_gid = self.current_group_id
        targets = [
            (g["id"], g["name"]) for g in groups
            if g["id"] != all_id
            and g["id"] != cur_gid
            and g["type"] == ("text" if is_text else "image")
        ]
        if not targets:
            return None
        signature = (is_text, cur_gid, tuple(targets))
        if signature == self._edit_move_sig and self._edit_move_menu is not None:
            return self._edit_move_menu
        if self._edit_move_menu is None:
            self._edit_move_menu = QMenu(self)
        menu = self._edit_move_menu
        menu.clear()
        for gid, name in targets:
            menu.addAction(name).triggered.connect(
                lambda checked=False, _gid=gid: self._edit_move_selected(_gid)
            )
        self._edit_move_sig = signature
        return menu

    def _on_edit_move_clicked(self):
        # Show the (cached) move menu / 弹出（已缓存的）移动菜单
        menu = self._ensure_edit_move_menu()
        if menu is None:
            return
        menu.exec(self._edit_move_btn.mapToGlobal(
            self._edit_move_btn.rect().bottomLeft()))

    def _noop_move(self):
        pass

    def _edit_select_all(self):
        # Select (or clear) every item in the current DATA set, not just the
        # lazily-created visible cards: _items is only the visible band, so
        # selecting by _items would silently select a subset on large
        # libraries, and the toggle check would misbehave after cards were
        # recycled. The grid does the whole pass in one shot (signals batched).
        # / 按当前数据集全选（或清空），而非仅懒加载可见卡：_items 只是可视区
        # 子集，按 _items 全选在大图库下会静默只选子集，且卡片被回收后切换判定会
        # 失效。整趟操作由网格一次性完成（信号合并）。
        grid = self.emoji_grid
        if not grid.in_edit_mode():
            return
        data = grid._data
        if not data:
            return
        # Already fully selected -> clear; otherwise select everything /
        # 已全选 → 清空；否则全选
        target = grid.selection_count() < len(data)
        grid.set_all_selection(target)
    def _edit_move_selected(self, target_group_id):
        # Move all selected emojis to a same-type group / 把所选表情全部
        # 移到同类型分组
        selected = self.emoji_grid.selected_emojis()
        if not selected:
            return
        # Detach QMovie file handles first: Windows cannot move a GIF while
        # it is being played (same requirement as group rename/delete).
        # 先分离 QMovie 文件句柄：GIF 播放中 Windows 无法移动文件
        # （与分组改名/删除的要求一致）。
        self.emoji_grid.release_gif_handles()
        moved = 0
        failed = 0
        for em in selected:
            try:
                if self.data_manager.move_emoji(em["id"], target_group_id):
                    moved += 1
                else:
                    failed += 1
            except OSError:
                failed += 1
                self._log.exception("Edit move failed for id=%s", em.get("id"))
        self._log.info("Edit move -> count=%s target=%s", moved, target_group_id)
        self._exit_edit_mode()
        self._refresh_emoji_grid()
        self._refresh_status()
        if moved:
            self.status_bar.showMessage(
                f"  ✓ {tr('edit_moved', count=moved)}", 2500)
        if failed:
            self.status_bar.showMessage(
                f"  ⚠ {tr('edit_move_failed', count=failed)}", 4000)

    def _edit_delete_selected(self):
        # Delete all selected emojis after confirmation / 确认后删除全部所选
        selected = self.emoji_grid.selected_emojis()
        if not selected:
            return
        reply = QMessageBox.question(
            self, tr("confirm_delete"),
            tr("edit_delete_confirm", count=len(selected)),
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        # Detach QMovie file handles first: Windows cannot delete a GIF
        # while it is being played (same requirement as group delete).
        # 先分离 QMovie 文件句柄：GIF 播放中 Windows 无法删除文件
        # （与分组删除的要求一致）。
        self.emoji_grid.release_gif_handles()
        # In the All view a card represents several rows folded by content_hash,
        # so deleting only the representative left the other copies behind and
        # the stickers "would not go away". Expand the selection to every row
        # sharing a selected content hash before deleting.
        # 在"全部"视图中一张卡代表按 content_hash 折叠的多行，只删代表行会留下其余
        # 副本，表现为"删不干净"。删除前把选中项扩展为共享同一内容哈希的所有行。
        ids = [em["id"] for em in selected]
        if self.current_group_id is None:
            expanded = self.data_manager.ids_sharing_content_hash(ids)
            if expanded:
                ids = expanded
        failed = 0
        deleted = 0
        for emo_id in ids:
            try:
                if self.data_manager.delete_emoji(emo_id):
                    deleted += 1
            except Exception:
                failed += 1
                self._log.exception("Edit delete failed for id=%s", emo_id)
        self._log.info("Edit delete -> selected=%s deleted=%s failed=%s",
                       len(selected), deleted, failed)
        self._exit_edit_mode()
        self._refresh_emoji_grid()
        self._refresh_status()
        if failed:
            self.status_bar.showMessage(
                f"  ⚠ {tr('edit_delete_failed', count=failed)}", 4000)
        else:
            self.status_bar.showMessage(
                f"  ✓ {tr('edit_deleted', count=max(deleted, len(selected)))}",
                2500)

    def _build_import_menu(self):
        menu = QMenu(self)
        self._act_import_folder = menu.addAction(tr("from_folder"))
        self._act_import_files = menu.addAction(tr("from_file"))
        # Connect here (not only in _connect_signals): _reload_language
        # rebuilds the menu on a language switch, and the old actions would
        # otherwise lose their connections, making the import menu dead.
        # 在此处连接（而非仅在 _connect_signals）：切换语言时 _reload_language
        # 会重建菜单，否则旧 action 的连接丢失，导入菜单会失效。
        self._act_import_folder.triggered.connect(self._import_from_folder)
        self._act_import_files.triggered.connect(self._import_from_files)
        # QQ emoji one-click import (multi-account) / QQ 表情一键导入（多账号）
        self._qq_sub = QMenu(tr("import_qq"), menu)
        # Re-scan the QQ accounts every time the submenu opens, so newly
        # saved stickers show up without restarting
        # 每次打开子菜单时重新扫描账号，新保存的表情无需重启即可出现
        self._qq_sub.aboutToShow.connect(self._refresh_qq_submenu)
        menu.addMenu(self._qq_sub)
        self.btn_import.setMenu(menu)

    def _qq_emoji_base(self):
        # Documents\Tencent Files under the current user's documents folder
        # (honours the OneDrive Documents redirection) / 当前用户文档目录下的
        # Documents\Tencent Files（跟随 OneDrive 文档重定向）
        docs = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DocumentsLocation)
        if not docs:
            docs = os.path.join(os.path.expanduser("~"), "Documents")
        return os.path.join(docs, "Tencent Files")

    def _scan_qq_accounts(self):
        # Scan Tencent Files for QQ accounts (pure-digit folders) that have
        # a personal emoji Ori folder; returns [{qq, path, count}]
        # 扫描 Tencent Files 下的 QQ 号（纯数字文件夹）及其个人表情 Ori 目录
        base = self._qq_emoji_base()
        accounts = []
        if not os.path.isdir(base):
            return accounts
        for name in sorted(os.listdir(base)):
            if not name.isdigit():
                continue  # QQ account folders are pure digits / QQ 号是纯数字目录
            emoji_dir = os.path.join(
                base, name, "nt_qq", "nt_data", "Emoji", "personal_emoji", "Ori")
            if not os.path.isdir(emoji_dir):
                continue
            files = [f for f in os.listdir(emoji_dir)
                     if os.path.splitext(f)[1].lower() in gif_converter.IMPORT_EXTS]
            if files:
                accounts.append({
                    "qq": name, "path": emoji_dir, "count": len(files)})
        return accounts

    def _refresh_qq_submenu(self):
        self._qq_sub.clear()
        accounts = self._scan_qq_accounts()
        if not accounts:
            act = self._qq_sub.addAction(tr("import_qq_none"))
            act.setEnabled(False)
            return
        for acc in accounts:
            label = f"{acc['qq']}（{acc['count']} 个）"
            act = self._qq_sub.addAction(label)
            act.triggered.connect(
                lambda checked, p=acc["path"]: self._import_from_qq(p))

    def _import_from_qq(self, emoji_dir):
        # Import every supported image in one QQ account's personal emoji
        # folder (mislabeled GIFs/PNGs are handled by content detection)
        # 导入单个 QQ 号个人表情目录下的全部支持图片（伪装 GIF/PNG 由内容检测处理）
        files = []
        for fn in os.listdir(emoji_dir):
            if os.path.splitext(fn)[1].lower() in gif_converter.IMPORT_EXTS:
                files.append(os.path.join(emoji_dir, fn))
        if not files:
            QMessageBox.information(self, "GIFManager", tr("import_qq_none"))
            return
        self._log.info("Import from QQ -> dir=%s files=%d", emoji_dir, len(files))
        self._do_import(files)

    def _apply_settings_icon(self):
        # Settings button icon from setting.svg, tinted for the active theme
        # (the SVG has no fill, so it would render black — invisible on the
        # dark toolbar). Falls back to the gear glyph when the file is missing.
        # 设置按钮图标取自 setting.svg，并按当前主题着色（该 SVG 没有 fill，
        # 默认渲染为黑色——在深色工具栏上看不见）。文件缺失时回退为齿轮字符。
        try:
            path = os.path.join(_root_dir(), "setting.svg")
            if not os.path.isfile(path):
                self.btn_settings.setText("⚙")
                return
            color = "#333333" if self._theme == "light" else "#E0E0E0"
            with open(path, "r", encoding="utf-8") as f:
                svg = f.read()
            # Give the fill-less paths an explicit theme colour /
            # 给未指定 fill 的路径加上主题颜色
            if "<svg " in svg:
                svg = svg.replace("<svg ", '<svg fill="%s" ' % color, 1)
            from PySide6.QtSvg import QSvgRenderer
            from PySide6.QtGui import QPainter, QPixmap
            from PySide6.QtCore import QByteArray
            renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
            dpr = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0
            # 75% of the original 22 px glyph; the button itself stays 32x32 /
            # 原 22px 的 75%，按钮本身仍为 32x32
            icon_px = int(self.ICON_PX * 0.75)
            side = max(1, int(icon_px * dpr))
            pix = QPixmap(side, side)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            try:
                renderer.render(p)
            finally:
                p.end()
            pix.setDevicePixelRatio(dpr)
            self.btn_settings.setText("")
            self.btn_settings.setIcon(QIcon(pix))
            self.btn_settings.setIconSize(QSize(icon_px, icon_px))
        except Exception:
            self._log.exception("Load settings icon failed")
            self.btn_settings.setText("⚙")

    def _apply_theme(self):
        self.setStyleSheet(DARK_QSS if self._theme != "light" else LIGHT_QSS)
        # Re-tint the settings icon for the new theme / 按新主题重新着色设置图标
        if hasattr(self, "btn_settings"):
            self._apply_settings_icon()
        # Keep the viewport/grid surface in step with the theme so an empty
        # group always shows the theme background. / 视口/网格表面随主题同步，
        # 使空分组始终显示主题背景。
        self._apply_viewport_background()

    # System tray / 系统托盘

    def _setup_tray(self):
        self._tray = QSystemTrayIcon(self)
        icon_path = os.path.join(_root_dir(), "icon.ico")
        if os.path.isfile(icon_path):
            self._tray.setIcon(QIcon(icon_path))
        else:
            self._tray.setIcon(self.style().standardIcon(
                self.style().StandardPixmap.SP_FileDialogContentsView
            ))
        self._tray.setToolTip(self.APP_TITLE)
        tray_menu = QMenu(self)
        act_show = tray_menu.addAction(tr("tray_show"))
        act_show.triggered.connect(self._toggle_visible)
        tray_menu.addSeparator()
        act_quit = tray_menu.addAction(tr("tray_quit"))
        act_quit.triggered.connect(self._real_quit)
        self._tray.setContextMenu(tray_menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_visible()

    def _toggle_visible(self):
        if self.isVisible():
            self.hide()
            self._scroll_watcher.stop()
        else:
            self.show()
            self.activateWindow()
            self.raise_()
            self._scroll_watcher.start(self._on_global_scroll)

    def _real_quit(self):
        self._save_geometry()
        self._save_current_group()
        self._save_settings()
        self._stop_gpu_adapter_probe()
        if self._hotkey_mgr:
            self._hotkey_mgr.unregister()
        self._scroll_watcher.stop()
        # Stop the GIF decode worker thread before the interpreter exits
        # 解释器退出前停止 GIF 解码工作线程
        from app.utils import gif_player
        gif_player.shutdown()
        # Drain the private thumbnail pool as well. Qt only awaits its GLOBAL
        # pool at QApplication destruction, so an owned pool left with in-flight
        # tasks could still signal a half-destroyed loader during exit (the
        # suspected 0xC0000005 / 0xC0000409 crash on quit).
        # 同样要排空私有缩略图线程池。Qt 只在 QApplication 析构时等待"全局"池，
        # 自建池若仍有任务在飞，退出时还会向半销毁的加载器发信号（退出阶段偶发
        # 0xC0000005 / 0xC0000409 崩溃的嫌疑原因）。
        self._shutdown_thumb_loader()
        self._tray.hide()
        QApplication.quit()

    def _shutdown_thumb_loader(self):
        # Idempotent: _real_quit and aboutToQuit can both reach here /
        # 幂等：_real_quit 与 aboutToQuit 都可能走到这里
        if getattr(self, "_thumb_loader_drained", False):
            return
        self._thumb_loader_drained = True
        try:
            from app.widgets.emoji_item import _loader
            _loader.shutdown(3000)
        except Exception:
            self._log.exception("Shutdown thumbnail loader failed")

    def _stop_gpu_adapter_probe(self):
        # Drain the adapter probe's OWN pool. The old comment claimed Qt waits
        # for pool tasks at shutdown, which is only true of the global pool — a
        # pooled task that outlives the window then emits into a destroyed
        # receiver while the interpreter is tearing down.
        # 排空显卡探测自己的线程池。旧注释称 Qt 会在退出时等待线程池任务，但那只对
        # 全局池成立——比窗口活得更久的池任务会在解释器收尾时向已销毁的接收者发信号。
        pool = getattr(self, "_gpu_pool", None)
        if pool is None:
            return
        try:
            pool.clear()
            pool.waitForDone(2000)
        except RuntimeError:
            pass  # already destroyed / 已销毁

    def _on_smooth_scroll_reset(self):
        # Stop any in-flight smooth scroll when data/group changes /
        # 数据/分组变化时停止进行中的平滑滚动
        if getattr(self, "_smooth_scroll", None) is not None:
            self._smooth_scroll.reset()

    # Global Alt+scroll callback: adjust card scale /
    # 全局 Alt+滚轮回调：调节卡片缩放
    def _on_global_scroll(self, delta):
        step = 0.02  # 2% per step / 每步 2%
        if delta > 0:
            new_scale = min(2.0, self._card_scale + step)
        else:
            new_scale = max(0.5, self._card_scale - step)
        if new_scale != self._card_scale:
            self._card_scale = new_scale
            self.emoji_grid._set_card_scale(self._card_scale)
            # Persist the change (Alt+wheel is a live control, not the settings
            # dialog) and keep an open settings dialog's spin in sync.
            # / 持久化该变化（Alt+滚轮是实时控件，非设置对话框），并保持打开的
            # 设置界面输入框同步。
            self._save_settings()
            if self._settings_dialog is not None:
                try:
                    self._settings_dialog.set_card_scale(self._card_scale)
                except RuntimeError:
                    pass  # dialog closed concurrently / 对话框已同时关闭

    def closeEvent(self, event):
        self._stop_gpu_adapter_probe()
        self._save_geometry()
        self._save_current_group()
        self._save_settings()
        # Without a system tray there is no way to bring the window back
        # (Qt.Tool windows have no taskbar entry), so close for real /
        # 无系统托盘时窗口无法再找回（Qt.Tool 窗口无任务栏入口），真正退出
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._log.info("No system tray -> quit on close")
            self._real_quit()
            event.accept()
            return
        self._log.info("Window closing -> hide to tray")
        event.ignore()
        self.hide()
        self._scroll_watcher.stop()
        self._tray.showMessage(
            self.APP_TITLE, tr("tray_hidden"),
            QSystemTrayIcon.MessageIcon.Information, 1500
        )

    # Signals / 信号

    def _connect_signals(self):
        # Drain the private thumbnail pool whenever Qt is about to quit —
        # _real_quit() is not the only exit path (WM_QUIT, qApp.quit(), and the
        # test harness all skip it). / 只要 Qt 即将退出就排空私有缩略图线程池：
        # _real_quit() 并非唯一退出路径（WM_QUIT、qApp.quit()、测试脚本都会绕过它）。
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._shutdown_thumb_loader)
        self.search_bar.textChanged.connect(self._on_search)
        # Import menu actions are connected inside _build_import_menu because
        # the menu is rebuilt on language switches / 导入菜单 action 在
        # _build_import_menu 内连接（菜单会在语言切换时重建）
        self.btn_settings.clicked.connect(self._open_settings)
        self.group_list.group_changed.connect(self._on_group_changed)
        self.group_list.groups_updated.connect(self._refresh_emoji_grid)
        self.emoji_grid.emoji_clicked.connect(self._on_emoji_clicked)
        self.emoji_grid.emoji_right_clicked.connect(self._on_emoji_right_clicked)
        self.emoji_grid.emojis_reordered.connect(self._refresh_emoji_grid)
        self.emoji_grid.edit_mode_changed.connect(self._on_edit_mode_changed)
        self.emoji_grid.selection_changed.connect(self._on_selection_count_changed)
        self.btn_add_text.clicked.connect(self._add_text_emoji)
        # Debounce timer for global freq sort (merge rapid usage) / 频率全局排序防抖定时器
        self._gs_timer = QTimer(self)
        self._gs_timer.setSingleShot(True)
        self._gs_timer.setInterval(400)
        self._gs_timer.timeout.connect(self._on_gs_freq_timeout)
        self._gs_pending_group = None
        # Search debounce timer / 搜索防抖定时器
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._on_search_timeout)
        # Silent update check on startup (tray bubble when a new version
        # exists; failures are logged only). / 启动静默检查更新（发现新版本
        # 用托盘气泡提示；失败仅记录日志）
        from app.models.update_manager import UpdateManager
        self._update_mgr = UpdateManager(self)
        self._update_mgr.check_finished.connect(self._on_auto_update_result)
        if self._auto_update:
            QTimer.singleShot(5000, self._update_mgr.check_updates)

    # Group / 分组

    def _on_group_changed(self, group_id):
        # Leave multi-select edit mode when switching groups (selection is
        # per-group) / 切换分组时退出多选编辑模式（选择是按分组的）
        self.emoji_grid.exit_edit_mode()
        # "All" is a virtual aggregation group: its database id is
        # equivalent to "No group selected" (identified by the builtin flag,
        # so it keeps working after renaming).
        # "All"是虚拟聚合分组：其数据库 id 等价于"未选中任何分组"
        # （按内置标记识别，重命名后仍有效）。
        all_id = self.data_manager._all_group_id()
        if all_id is not None and group_id == all_id:
            group_id = None
        self.current_group_id = group_id
        self.emoji_grid.current_group_id = group_id
        self._log.info("Switch group -> id=%s", group_id)
        # Text grouping enables horizontal scrolling (stable columns may
        # exceed the visible width), image grouping is turned off
        # 文字分组启用横向滚动（稳定列可能超出可视宽度），图片分组关闭
        is_text = False
        if group_id is not None:
            g = self.data_manager.get_group(group_id)
            is_text = bool(g and g["type"] == "text")
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if is_text
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        # Reset the horizontal scroll position on group switch: the previous
        # group's horizontal value would otherwise carry over, and in a
        # narrower/new group the handle sticks to the right edge until the
        # user drags it. / 切换分组时复位水平滚动位置：否则上一分组的水平
        # 滚动值会保留，在更窄/新分组中滑块会贴到右侧边缘，直到用户拖拽。
        self._scroll_area.horizontalScrollBar().setValue(0)
        if group_id is not None:
            g = self.data_manager.get_group(group_id)
            if g and g["type"] == "text":
                self.btn_import.hide()
                self.btn_add_text.show()
            else:
                self.btn_import.show()
                self.btn_add_text.hide()
        else:
            self.btn_import.show()
            self.btn_add_text.hide()
        self._save_current_group()
        self._refresh_emoji_grid()
        self._refresh_status()

    def _refresh_emoji_grid(self, keep_scroll=False):
        # keep_scroll=True preserves the vertical scroll position across the
        # refresh (used by rename — the grid would otherwise jump to the
        # top). / keep_scroll=True 在刷新后保留垂直滚动位置（重命名使用——
        # 否则网格会跳回顶部）。
        scroll_val = None
        if keep_scroll:
            sb = self._scroll_area.verticalScrollBar()
            scroll_val = sb.value()
        keyword = self.search_bar.text().strip()
        if self.current_group_id is None:
            emojis = self.data_manager.get_all_emojis(keyword)
            group_type = "image"
        else:
            g = self.data_manager.get_group(self.current_group_id)
            group_type = g["type"] if g else "image"
            if not keyword:
                self.emoji_grid.assign_unassigned_columns(self.current_group_id)
            emojis = self.data_manager.get_emojis_by_group(self.current_group_id, keyword)
        self.emoji_grid.load_emojis(
            emojis, group_type,
            preview_limits=(self._text_limit_single, self._text_limit_multi),
            keyword=keyword,
        )
        if scroll_val is not None:
            # Restore the previous position once the new layout is ready /
            # 新布局就绪后恢复原位置
            sb = self._scroll_area.verticalScrollBar()
            QTimer.singleShot(0, lambda s=sb, v=scroll_val: s.setValue(v))

    def _refresh_status(self):
        total = self.data_manager.count_all_emojis()
        gid = self.current_group_id
        if gid is None:
            keyword = self.search_bar.text().strip()
            shown = len(self.data_manager.get_all_emojis(keyword))
            group_name = "All"
            if not keyword:
                image_total = self.data_manager.count_image_emojis()
                folded = image_total - shown
                if folded > 0:
                    folded_msg = tr(
                        "emoji_count_folded", group=group_name,
                        count=shown, total=total, folded=folded,
                    )
                    self.status_bar.showMessage(f"  {folded_msg}")
                    return
            count = shown
        else:
            g = self.data_manager.get_group(gid)
            group_name = g["name"] if g else "All"
            count = self.data_manager.count_emojis_in_group(gid)
        self.status_bar.showMessage(
            f"  {tr('emoji_count', group=group_name, count=count, total=total)}"
        )

    def _on_search(self, _text):
        # Debounce: rebuilding the grid on every keystroke is expensive with
        # a large library; refresh 200 ms after typing pauses / 防抖：大图库
        # 下逐键重建网格开销大；停止输入 200ms 后再刷新
        self._search_timer.start()

    def _on_search_timeout(self):
        self._refresh_emoji_grid()

    # Import / 导入

    def _import_from_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, tr("select_files"), "", tr("image_filter")
        )
        if files:
            self._do_import(files)

    def _import_from_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr("select_folder"))
        if not folder:
            return
        exts = {".gif", ".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        files = []
        for root_dir, _dirs, filenames in os.walk(folder):
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() in exts:
                    files.append(os.path.join(root_dir, fn))
        if files:
            self._do_import(files)
        else:
            QMessageBox.information(self, "GIFManager", tr("no_image_found"))

    def _do_import(self, files):
        target_group = self.current_group_id
        if target_group is None:
            # Builtin default group lookup by flag (works after rename)
            # 内置默认分组按标记查找（重命名后仍有效）
            default = self.data_manager.default_group_id()
            if default is None:
                QMessageBox.warning(self, "GIFManager", tr("default_group_missing"))
                return
            target_group = default

        group_info = self.data_manager.get_group(target_group)
        if group_info and group_info["type"] == "text":
            QMessageBox.warning(self, "GIFManager", tr("text_group_warning"))
            return

        valid = [f for f in files
                 if os.path.splitext(f)[1].lower() in gif_converter.IMPORT_EXTS]
        if not valid:
            self.status_bar.showMessage(f"  {tr('import_no_valid')}", 3000)
            return
        # Auto-convert works with Pillow by default (ffmpeg optional) /
        # 自动转换默认用 Pillow（ffmpeg 为可选增强）
        auto = self._auto_convert_gif
        if auto and len(valid) > 100:
            # Large batch: show a conversion progress dialog / 大批量：显示转换进度条
            imported, duplicated, converted_n, fail_n = \
                self._import_with_progress(target_group, valid)
        else:
            imported, duplicated = self.data_manager.import_emojis_batch(
                target_group, valid,
                workers=QThreadPool.globalInstance().maxThreadCount(),
                auto_convert=auto,
            )
            converted_n = 0
            fail_n = 0
        self._log.info(
            "Import -> group=%s files=%d imported=%d duplicated=%d",
            group_info["name"] if group_info else target_group,
            len(valid), imported, duplicated,
        )
        # New cards go to the top-left corner / 新导入的卡片放到左上角
        if imported > 0:
            self.data_manager.prepend_latest_imports(target_group, imported)
            # Global time/name sort runs once after adding / 全局时间/名称排序在新增后执行一次
            self._apply_global_sort(target_group)
        self._refresh_emoji_grid()
        self._refresh_status()
        msg = tr("import_success", count=imported, group=group_info["name"])
        if duplicated:
            msg += tr("import_skip_dup", count=duplicated)
        if converted_n:
            msg += tr("import_converted", count=converted_n)
        if fail_n:
            msg += tr("import_conv_fail", count=fail_n)
        self.status_bar.showMessage(f"  {msg}", 4000)

    def _import_with_progress(self, group_id, files):
        # Convert non-gif files one by one on the main thread while showing
        # a progress dialog, then batch-insert everything.
        # 主线程逐张转换非 gif 文件并显示进度条，随后批量入库。
        # Skip files already in the group BEFORE converting them: hashing the
        # source is cheap, while converting every file again (decode +
        # re-encode + temp write, often spawning ffmpeg) is what made a
        # repeated 400+ QQ import slow and heavy. / 转换之前先跳过本组已有
        # 文件：哈希源文件很便宜，而反复转换每个文件（解码+重编码+写临时文件，
        # 常需启动 ffmpeg）才是重复导入 400+ QQ 表情包时又慢又耗资源的原因。
        # hash_map: {source path: md5} filled by the pre-filter so the original
        # file is never hashed twice (it used to be summed up to 3x per file,
        # cancelling out much of the "skip early" win).
        # hash_map：由预过滤填入 {源路径: md5}，使同一文件不会被哈希两次
        # （此前每个文件最多哈希 3 次，把"提前跳过"的收益抵消了大半）。
        hash_map = {}
        files, pre_skipped = self.data_manager.filter_already_imported(
            group_id, files, hash_out=hash_map)
        dlg = QProgressDialog(
            tr("converting_gif"), tr("cancel"), 0, max(1, len(files)), self)
        dlg.setWindowTitle(tr("importing"))
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        ready = []
        # ONLY the temp files THIS method created may be deleted afterwards.
        # The old cleanup filtered `ready` by "lives in %TEMP% and ends in .gif",
        # which deleted a user's own source file when they imported one from
        # %TEMP%. / 之后只能删除本方法创建的临时文件。旧清理按"位于 %TEMP% 且
        # 以 .gif 结尾"过滤 ready，会把用户从 %TEMP% 导入的源文件一起删掉。
        temps = []
        # {path handed to the batch importer: md5 of the user's original file} /
        # {交给批量导入的路径: 用户原文件 md5}
        src_hash_map = {}
        imported = duplicated = converted_n = fail_n = 0
        try:
            for i, f in enumerate(files):
                if dlg.wasCanceled():
                    break
                dlg.setValue(i)
                dlg.setLabelText(tr("converting_file", name=os.path.basename(f)))
                QApplication.processEvents()
                original_hash = hash_map.get(f, "")
                picked = f
                if gif_converter.needs_gif_conversion(f):
                    # Non-GIF content (animated or static) -> convert to gif;
                    # oversized results are downscaled inside the converter
                    # so chat apps still recognize them as pictures.
                    # 非 GIF 内容（动画或静态）→ 转 gif；超大结果在转换器内
                    # 降采样，聊天软件仍能识别为图片。
                    tmp = os.path.join(
                        tempfile.gettempdir(), f"gm_conv_{os.urandom(4).hex()}.gif")
                    if gif_converter.convert_to_gif(f, tmp):
                        picked = tmp
                        temps.append(tmp)
                        converted_n += 1
                    else:
                        # failed -> keep original format / 失败保持原格式
                        self._log.warning(
                            "import_progress: convert_to_gif failed for %s, "
                            "store original", f)
                        fail_n += 1
                else:
                    # Genuine GIF: copy as-is unless oversized — downscale it
                    # here so chat apps paste it as a picture, not a file
                    # attachment (animation kept). / 真 GIF：除非超大否则原样
                    # 复制——超大则在此降采样，聊天软件才能粘贴为图片而非
                    # 文件附件（保留动画）。
                    dims = gif_converter._image_dimensions(f)
                    if dims and max(dims) > gif_converter.MAX_GIF_DIM:
                        tmp = os.path.join(
                            tempfile.gettempdir(),
                            f"gm_conv_{os.urandom(4).hex()}.gif")
                        if gif_converter.downscale_gif_if_needed(f, tmp):
                            picked = tmp
                            temps.append(tmp)
                        else:
                            self._log.warning(
                                "import_progress: downscale oversized gif failed "
                                "for %s (dims=%s), store original", f, dims)
                    elif dims is None:
                        self._log.warning(
                            "import_progress: cannot read dimensions of %s, "
                            "store original", f)
                ready.append(picked)
                if original_hash:
                    # Record the USER's file hash against whatever path the
                    # batch importer receives, so the pre-skip keeps working
                    # for this batch. / 把"用户文件"的哈希登记到批量导入实际收到
                    # 的路径上，使本批的预跳过继续有效。
                    src_hash_map[picked] = original_hash
            dlg.setValue(len(files))
            if ready:
                imported, duplicated = self.data_manager.import_emojis_batch(
                    group_id, ready,
                    workers=QThreadPool.globalInstance().maxThreadCount(),
                    auto_convert=False,
                    src_hash_map=src_hash_map,
                )
        finally:
            dlg.close()
            # Clean up ONLY the temp gif files this method created (already
            # copied into the library) / 只清理本方法创建的临时 gif（已复制入库）
            for p in temps:
                try:
                    os.remove(p)
                except OSError:
                    pass
        # Files skipped before conversion count as duplicates, so the summary
        # reports everything that was filtered out. / 转换前跳过的文件计入
        # 重复数，使汇总反映全部被过滤的文件。
        return imported, duplicated + pre_skipped, converted_n, fail_n

    def _on_convert_library(self):
        # One-click convert: all non-gif images in every group -> gif /
        # 一键转换：把所有分组非 gif 图片转为 gif
        ret = QMessageBox.question(
            self, tr("gif_convert_all"),
            tr("gif_convert_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        dlg = QProgressDialog(tr("converting_gif"), "", 0, 1, self)
        dlg.setWindowTitle(tr("gif_convert_all"))
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setCancelButton(None)

        def cb(i, total, name):
            if total:
                dlg.setMaximum(total)
                dlg.setValue(i)
                if name:
                    dlg.setLabelText(tr("converting_file", name=name))
                QApplication.processEvents()

        try:
            converted, failed, deduped = \
                self.data_manager.convert_library_to_gif(
                    progress_cb=cb,
                    workers=QThreadPool.globalInstance().maxThreadCount(),
                )
        finally:
            dlg.close()
        self._refresh_emoji_grid()
        self._refresh_status()
        if converted or failed or deduped:
            QMessageBox.information(
                self, tr("gif_convert_all"),
                tr("gif_convert_done",
                   converted=converted, failed=failed, deduped=deduped),
            )
        else:
            QMessageBox.information(
                self, tr("gif_convert_all"), tr("gif_convert_none"))

    def _add_text_emoji(self):
        if self.current_group_id is None:
            return
        g = self.data_manager.get_group(self.current_group_id)
        if not g or g["type"] != "text":
            return
        text, ok = QInputDialog.getMultiLineText(
            self, tr("add_text_dialog"), tr("add_text_prompt")
        )
        if ok and text.strip():
            r = self.data_manager.add_text_emoji(self.current_group_id, text.strip())
            if r == 0:
                QMessageBox.information(self, tr("text_duplicate_title"), tr("text_duplicate_msg"))
                return
            if r > 0:
                # New text emoji goes to the top-left corner / 新文字表情放到左上角
                self.data_manager.prepend_emojis(self.current_group_id, [r])
                # Global time/name sort runs once after adding / 全局时间/名称排序在新增后执行一次
                self._apply_global_sort(self.current_group_id)
            self._refresh_emoji_grid()
            self._refresh_status()
            self.status_bar.showMessage(f"  {tr('added_to', group=g['name'])}", 2000)

    def _assign_new_text(self, emoji_id, text):
        usable = self._scroll_usable_width()
        self.emoji_grid.assign_new_text_column(
            emoji_id, self.current_group_id, text, usable
        )

    def _scroll_usable_width(self):
        try:
            vw = self._scroll_area.viewport().width()
            return max(vw - 20, 100)
        except Exception:
            return 600

    # Drag / 拖放

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        exts = {".gif", ".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        files = []
        for url in urls:
            path = url.toLocalFile()
            if os.path.isfile(path) and os.path.splitext(path)[1].lower() in exts:
                files.append(path)
        if files:
            self._do_import(files)

    def eventFilter(self, obj, event):
        # Route mouse-wheel over the scroll area into the smooth-glide
        # controller (so long scrolls are continuous, not a jump). Normal
        # wheel without a scrollable range, and Alt+wheel (card zoom), are
        # left alone. / 把滚动区内的鼠标滚轮交给平滑滚动控制器（长距离滚动
        # 连贯而非瞬移）。无可滚动范围或 Alt+滚轮（缩放卡片）不拦截。
        if obj is getattr(self, "_scroll_area", None).viewport() \
                and event.type() == QEvent.Type.Wheel:
            me = event
            delta_y = me.angleDelta().y()
            if delta_y != 0 and not (me.modifiers()
                                     & Qt.KeyboardModifier.AltModifier):
                self._smooth_scroll.handle_wheel(delta_y)
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent):
        # Ctrl+A in multi-select edit mode selects all / clears selection /
        # 多选编辑模式下 Ctrl+A 全选/取消全选
        if self.emoji_grid.in_edit_mode() and event.key() == Qt.Key.Key_A \
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._edit_select_all()
            event.accept()
            return
        if event.matches(QKeySequence.StandardKey.Paste):
            if self.current_group_id is not None:
                g = self.data_manager.get_group(self.current_group_id)
                if g and g["type"] == "text":
                    text = QApplication.clipboard().text()
                    if text.strip():
                        added = 0
                        skipped = 0
                        new_ids = []
                        for line in text.strip().split("\n"):
                            line = line.strip()
                            if not line:
                                continue
                            r = self.data_manager.add_text_emoji(self.current_group_id, line)
                            if r > 0:
                                new_ids.append(r)
                                added += 1
                            elif r == 0:
                                skipped += 1
                        if new_ids:
                            # Pasted text goes to the top-left corner / 粘贴的文字放到左上角
                            self.data_manager.prepend_emojis(self.current_group_id, new_ids)
                            # Global time/name sort runs once after adding / 全局时间/名称排序在新增后执行一次
                            self._apply_global_sort(self.current_group_id)
                        self._refresh_emoji_grid()
                        self._refresh_status()
                        msg = tr("pasted_to", group=g["name"])
                        if skipped:
                            msg += tr("import_skip_dup", count=skipped)
                        self.status_bar.showMessage(f"  {msg}", 2500)
                    return
        super().keyPressEvent(event)

    # Emoji operation / 表情包操作

    def _on_emoji_clicked(self, emoji):
        self._log.info("Send/copy emoji -> id=%s mode=%s", emoji.get("id"), self._send_mode)
        success = self.data_manager.copy_to_clipboard(emoji, mode=self._send_mode)
        if success:
            # Bump usage frequency for the freq sort / 记录使用次数供频率排序
            if emoji.get("id") is not None:
                self.data_manager.increment_use_count(emoji["id"])
            name = emoji.get("original_name") or emoji.get("text_content", "emoji")
            mode_label = tr("copied_path") if self._send_mode == 0 else tr("copied_image")
            self.status_bar.showMessage(f"  ✓ {tr('copied_msg', mode=mode_label, name=name)}", 2000)
            # Auto-type into the chat input. The focus guard keeps focus on
            # the chat window even while clicking emojis here, so Ctrl+V
            # pastes straight into the still-focused input. / 自动输入到聊天
            # 输入框。焦点守卫保证点击表情时焦点仍在聊天窗口，Ctrl+V 直接
            # 粘贴进仍持有焦点的输入框。
            if self._auto_input:
                self._auto_input_paste(emoji)
        # Global freq sort: debounced re-sort on usage / 全局频率排序：使用时防抖重排
        if self._gs_enabled and self._gs_by == "freq":
            gid = emoji.get("group_id")
            if gid is not None and success:
                self._gs_pending_group = gid
                self._gs_timer.start()

    def _auto_input_paste(self, emoji):
        guard = getattr(self, "_focus_guard", None)
        try:
            from app.utils.input_sender import (
                paste_to_window, paste_to_foreground, foreground_window,
                bring_to_front,
            )
            import time
            # The tracker remembered the chat window (the last foreground
            # window that was not the manager). Hand focus back to it once
            # and paste. This happens only on an emoji click, so normal
            # interaction (search, settings, right-click) is never disturbed.
            # 跟踪器记住了聊天窗口（最近一个非管理器的前台窗口）。点击表情
            # 时一次性把焦点归还给它并粘贴。仅在点击表情时发生，因此正常
            # 交互（搜索、设置、右键）不受干扰。
            target = guard.target() if guard is not None else 0
            me = int(self.winId()) if self.winId() else 0
            ok = False
            if target and target != me:
                # Bring the chat window to the front, then paste into it /
                # 把聊天窗口带回前台，然后粘贴进去
                for _ in range(10):  # up to ~0.3 s / 最多约 0.3 秒
                    if foreground_window() == target:
                        break
                    bring_to_front(target)
                    time.sleep(0.03)
                    try:
                        from PySide6.QtCore import QCoreApplication
                        QCoreApplication.processEvents()
                    except Exception:
                        pass
                time.sleep(0.1)  # let the target restore its input focus / 让目标恢复输入焦点
                ok = paste_to_window(target, delay_ms=30)
            if not ok:
                # Foreground Ctrl+V via SendInput (Qt WeChat needs keyboard
                # input) / 向前台 SendInput Ctrl+V（Qt 微信需要键盘输入）
                ok = paste_to_foreground(delay_ms=60)
            if ok:
                self._log.info("Auto-input pasted emoji id=%s target=%s",
                               emoji.get("id"), target)
            else:
                self._log.warning(
                    "Auto-input failed to send keys for emoji id=%s",
                    emoji.get("id"))
        except Exception:
            self._log.exception("Auto-input paste failed")

    # Global sorting mode / 全局排序模式
    def _apply_global_sort(self, group_id):
        # Time/name sorts run once when emojis are added; freq runs on use.
        # 时间/名称排序在新增表情时执行一次；频率排序在使用时执行。
        if not self._gs_enabled or group_id is None:
            return
        if self._gs_by == "freq":
            return
        try:
            self.data_manager.sort_group_emojis(
                group_id, by=self._gs_by, desc=self._gs_desc)
        except Exception:
            self._log.exception("Global sort failed")
            return
        if self.current_group_id == group_id:
            self._refresh_emoji_grid()

    def _apply_global_sort_all(self):
        if not self._gs_enabled:
            return
        all_id = self.data_manager._all_group_id()
        for g in self.data_manager.get_all_groups():
            gid = g["id"]
            if gid is None or gid == all_id:
                # Skip the virtual "All" aggregation group / 跳过"全部"虚拟聚合分组
                continue
            try:
                self.data_manager.sort_group_emojis(
                    gid, by=self._gs_by, desc=self._gs_desc)
            except Exception:
                self._log.exception("Global sort failed for group %s", gid)
        self._refresh_emoji_grid()
        self._refresh_status()

    def _on_gs_freq_timeout(self):
        gid = self._gs_pending_group
        self._gs_pending_group = None
        if not self._gs_enabled or self._gs_by != "freq" or gid is None:
            return
        try:
            self.data_manager.sort_group_emojis(
                gid, by="freq", desc=self._gs_desc)
        except Exception:
            self._log.exception("Global freq sort failed")
            return
        if self.current_group_id == gid:
            self._refresh_emoji_grid()

    # Silent auto-update result: tray bubble for a newer version; failures
    # are logged only (details stay visible in the settings update page).
    # 静默更新结果：发现新版本用托盘气泡提示；失败仅记录日志
    # （详细信息可在设置更新页查看）
    def _on_auto_update_result(self, ok, version, url, size, err_key, detail):
        if not ok:
            self._log.info("Auto-update check failed: %s %s", err_key, detail)
            return
        if version is None or cmp_version(version, parse_version(__version__)) <= 0:
            self._log.info("Auto-update: already up to date")
            return
        ver_str = ".".join(str(x) for x in version)
        self._log.info("Auto-update: new version %s available", ver_str)
        if self._tray.isVisible():
            self._tray.showMessage(
                tr("update_bubble_title"),
                tr("update_bubble_msg", version=ver_str),
                QSystemTrayIcon.MessageIcon.Information,
                8000,
            )
            try:
                self._tray.messageClicked.connect(self._open_settings)
            except RuntimeError:
                pass

    def _on_emoji_right_clicked(self, emoji, pos):
        menu = QMenu(self)
        # Multi-select edit mode entry: edit several emojis/text at once /
        # 多选编辑入口：同时对多个表情包/文字操作
        menu.addAction(tr("edit_mode")).triggered.connect(self._enter_edit_mode)
        menu.addSeparator()
        menu.addAction(tr("send_copy")).triggered.connect(lambda: self._on_emoji_clicked(emoji))
        menu.addSeparator()
        if emoji.get("text_content"):
            menu.addAction(tr("edit_text")).triggered.connect(lambda: self._edit_text_emoji(emoji))
        else:
            menu.addAction(tr("rename")).triggered.connect(lambda: self._rename_emoji(emoji))
        self._build_move_submenu(menu, emoji)
        menu.addSeparator()
        menu.addAction(tr("delete")).triggered.connect(lambda: self._delete_emoji(emoji))
        menu.exec(pos)

    def _delete_emoji(self, emoji):
        name = emoji.get("original_name") or emoji.get("text_content", "")
        if self.current_group_id is None and emoji.get("content_hash"):
            copies = self.data_manager.get_emoji_copies(emoji)
            if len(copies) > 1:
                from app.widgets.delete_copies_dialog import DeleteCopiesDialog
                dlg = DeleteCopiesDialog(copies, self)
                if dlg.exec() == DeleteCopiesDialog.DialogCode.Accepted:
                    for cid in dlg.selected_emojis():
                        self.data_manager.delete_emoji(cid)
                    self._refresh_emoji_grid()
                    self._refresh_status()
                return
        reply = QMessageBox.question(
            self, tr("confirm_delete"), tr("confirm_delete_msg", name=name),
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.data_manager.delete_emoji(emoji["id"])
            self._log.info("Delete emoji -> id=%s", emoji["id"])
            self._refresh_emoji_grid()
            self._refresh_status()

    def _rename_emoji(self, emoji):
        old_name = emoji.get("original_name") or emoji.get("text_content", "")
        from app.widgets.rename_dialog import RenameDialog
        dlg = RenameDialog(old_name, self)
        if dlg.exec() == RenameDialog.DialogCode.Accepted:
            new_name = dlg.new_name()
            if new_name:
                self.data_manager.rename_emoji(emoji["id"], new_name)
                self._log.info("Rename emoji -> id=%s old=%r new=%r",
                               emoji["id"], old_name, new_name)
                # Preserve the scroll position: renaming must not jump back to
                # the top of the page. / 保留滚动位置：重命名不应跳回页面顶部。
                self._refresh_emoji_grid(keep_scroll=True)

    def _edit_text_emoji(self, emoji):
        from app.widgets.edit_text_dialog import EditTextDialog
        dlg = EditTextDialog(emoji.get("text_content", ""), self)
        if dlg.exec() == EditTextDialog.DialogCode.Accepted:
            new_text = dlg.text()
            if not new_text:
                return
            if new_text == emoji.get("text_content", ""):
                return
            cur = self.data_manager.get_emojis_by_group(emoji["group_id"])
            for other in cur:
                if other["id"] != emoji["id"] and other.get("text_content") == new_text:
                    QMessageBox.information(
                        self, tr("text_duplicate_title"), tr("text_duplicate_msg")
                    )
                    return
            self.data_manager.rename_emoji(emoji["id"], new_text[:20])
            self._conn_update_text(emoji["id"], new_text)
            # Keep the scroll position after editing text / 编辑文字后保持滚动位置
            self._refresh_emoji_grid(keep_scroll=True)

    def _conn_update_text(self, emoji_id, text):
        self.data_manager.update_text_content(emoji_id, text)

    def _build_move_submenu(self, menu, emoji):
        is_text = bool(emoji.get("text_content"))
        groups = self.data_manager.get_all_groups()
        all_id = self.data_manager._all_group_id()
        targets = [
            g for g in groups
            if g["id"] != all_id
            and g["id"] != emoji["group_id"]
            and g["type"] == ("text" if is_text else "image")
        ]
        if not targets:
            return
        sub = QMenu(tr("move_to_group"), menu)
        for g in targets:
            sub.addAction(g["name"]).triggered.connect(
                lambda checked, gid=g["id"]: self._do_move(emoji, gid)
            )
        menu.addMenu(sub)

    def _do_move(self, emoji, target_group_id):
        self.data_manager.move_emoji(emoji["id"], target_group_id)
        self._log.info("Move emoji -> id=%s target_group=%s", emoji["id"], target_group_id)
        self._refresh_emoji_grid()
        self._refresh_status()

    # Settings / 设置

    def _open_settings(self):
        # Settings is always-on-top; when it is already open, ignore the
        # repeated click silently (no popup needed) / 设置窗口置顶，已打开时
        # 静默忽略重复点击（无需提示框）
        if self._settings_dialog is not None:
            return
        dlg = SettingsDialog(
            self._send_mode, self._remember_group,
            self._autostart, self._always_on_top,
            self._text_limit_single, self._text_limit_multi,
            self._thread_count, self._theme,
            self._gs_enabled, self._gs_by, self._gs_desc,
            self._auto_convert_gif, self._auto_update,
            show_emoji_name=self._show_emoji_name,
            hover_zoom=self._hover_zoom,
            hover_preview_enabled=self._hover_preview_enabled,
            auto_input=self._auto_input,
            card_scale=self._card_scale,
            name_font_size=self._name_font_size,
            ffmpeg_enabled=self._ffmpeg_enabled,
            ffmpeg_path=self._ffmpeg_path,
            gif_render_mode=self._gif_render_mode,
            gif_render_count=self._gif_render_count,
            gpu_render=self._gpu_render,
            gpu_accel=self._gpu_accel,
            gpu_viewport=self._gpu_viewport,
            gpu_pref=self._gpu_pref,
            gpu_adapters=self._gpu_adapters,
            data_manager=self.data_manager,
            hotkey_desc=self._hotkey_desc(),
            parent=self,
        )
        dlg.convert_library_requested.connect(self._on_convert_library)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.apply_clicked.connect(self._on_settings_apply)
        dlg.finished.connect(self._on_settings_finished)
        dlg.clear_logs_requested.connect(self._on_clear_logs)
        self._settings_dialog = dlg
        dlg.show()

    def _on_clear_logs(self):
        count = clear_logs()
        self._log = get_logger()  # 清除后重建的新会话日志
        self._log.info("Clear logs -> removed %d file(s)", count)
        QMessageBox.information(
            self, "GIFManager",
            tr("clear_logs_done", count=count),
        )

    def _on_settings_apply(self):
        if self._settings_dialog is not None:
            self._apply_settings(self._settings_dialog)

    def _on_settings_finished(self, result):
        dlg = self._settings_dialog
        self._settings_dialog = None
        if dlg is not None and result == SettingsDialog.DialogCode.Accepted:
            self._apply_settings(dlg)

    def _apply_settings(self, dlg):
        old_lang = current_language()
        new_lang = dlg.language()
        if new_lang != old_lang:
            set_language(new_lang)
        self._send_mode = dlg.send_mode()
        self._remember_group = dlg.remember_group()
        self._autostart = dlg.autostart()
        self._always_on_top = dlg.always_on_top()
        self._text_limit_single = dlg.text_limit_single()
        self._text_limit_multi = dlg.text_limit_multi()
        self._thread_count = dlg.thread_count()
        # Global sorting mode changed -> re-sort all groups once / 全局排序变化 → 全分组重排一次
        gs_changed = (
            dlg.global_sort_enabled() != self._gs_enabled
            or dlg.global_sort_by() != self._gs_by
            or dlg.global_sort_desc() != self._gs_desc
        )
        self._gs_enabled = dlg.global_sort_enabled()
        self._gs_by = dlg.global_sort_by()
        self._gs_desc = dlg.global_sort_desc()
        # Keep the grid's copy in step; the resize auto-fill no longer depends
        # on it / 同步网格里的副本；拉伸自动铺满已不再依赖它
        self.emoji_grid._global_sort_enabled = self._gs_enabled
        if gs_changed and self._gs_enabled:
            self._apply_global_sort_all()
        # Auto-convert setting may change without closing the dialog / 自动转换开关可能在对话框内直接变化
        self._auto_convert_gif = dlg.auto_convert_gif()
        self._auto_update = dlg.auto_update()
        # Click-emoji auto-input switch / 点击表情自动输入开关
        self._auto_input = dlg.auto_input()
        if getattr(self, "_focus_guard", None) is not None:
            self._focus_guard.set_enabled(self._auto_input)
        # Show/hide the emoji name: pass it to the grid so rebuilt cards
        # (and the layout heights) use the new setting / 显示/隐藏表情包名称：
        # 传给网格，重建的卡片与布局高度使用新设置
        self._show_emoji_name = dlg.show_emoji_name()
        # Route through the setter: it also drops the card pool and rebuilds,
        # which a plain attribute write did not do — pooled cards kept the old
        # fixed height and overlapped the rebuilt ones.
        # 经由 setter 设置：它同时清空卡片池并重建，而单纯改属性不会——池卡会保留
        # 旧固定高度并与重建的卡片重叠。
        self.emoji_grid.set_show_emoji_name(self._show_emoji_name)
        # Hover zoom factor / 悬停放大倍数（新建卡片时使用）
        self._hover_zoom = dlg.hover_zoom()
        self.emoji_grid._hover_zoom = self._hover_zoom
        # Hover preview master switch / 悬停预览总开关
        self._hover_preview_enabled = dlg.hover_preview_enabled()
        self.emoji_grid._hover_preview_enabled = self._hover_preview_enabled
        # Apply to already-created cards immediately (no need to switch
        # groups) / 立即应用到已创建的卡片（无需切换分组）
        for card in self.emoji_grid._items:
            card._hover_enabled = self._hover_preview_enabled
            card._hover_zoom = self._hover_zoom
            if not self._hover_preview_enabled:
                card._hide_hover_zoom()
        # Card scale factor / 卡片缩放系数
        new_scale = dlg.card_scale()
        if new_scale != self._card_scale:
            self._card_scale = new_scale
            self.emoji_grid._set_card_scale(self._card_scale)
        # Name font size / 名字字号
        new_nf = dlg.name_font_size()
        if new_nf != self._name_font_size:
            self._name_font_size = new_nf
            self.emoji_grid.apply_name_font_size(self._name_font_size)
        # FFmpeg usage + optional custom binary / FFmpeg 使用与自定义路径
        self._ffmpeg_enabled = dlg.ffmpeg_enabled()
        self._ffmpeg_path = dlg.ffmpeg_path()
        from app.utils import gif_converter
        gif_converter.set_ffmpeg_config(path=self._ffmpeg_path,
                                       enabled=self._ffmpeg_enabled)
        # Animated-GIF render concurrency / 动态 GIF 渲染并发
        self._gif_render_mode = dlg.gif_render_mode()
        self._gif_render_count = dlg.gif_render_count()
        self._apply_thread_count()
        # GPU acceleration master switch: turns parallel thumbnail rendering on
        # and applies/clears the Windows GPU preference accordingly.
        # GPU 加速总开关：开启并行缩略图渲染，并写入/清除 Windows 的 GPU 偏好。
        new_accel = dlg.gpu_accel()
        new_pref = dlg.gpu_preference()
        if new_accel != self._gpu_accel or new_pref != self._gpu_pref:
            self._gpu_accel = new_accel
            self._gpu_pref = new_pref
            self._gpu_render = new_accel
            EmojiItem.set_parallel_render(self._gpu_accel)
        # Pressing OK always re-synchronises the Windows preference, even when
        # neither value changed: the gate that used to guard this call left the
        # registry stale whenever it had drifted (e.g. reset outside the app, or
        # a previous "off" that never got cleared), so the UI and the actual
        # Windows setting could disagree. The write is idempotent.
        # 按下确定时总是重新同步 Windows 首选项，即使两个值都没变：此前包裹该调用
        # 的判定会在注册表已经跑偏时（例如被程序外部重置、或上一次"关闭"没能清除）
        # 留下过期状态，使界面与实际 Windows 设置不一致。该写入是幂等的。
        self._apply_gpu_preference(explicit=True)
        # Experimental GPU viewport: stored here, APPLIED at the next launch —
        # the surface is deliberately never swapped at runtime (doing that used
        # to crash the renderer), so tell the user a restart is needed.
        # 实验性 GPU 视口：此处只保存，下次启动时安装——表面刻意不在运行时替换
        # （那样做此前会让渲染器崩溃），因此提示用户需重启。
        vp_needs_restart = False
        new_vp = dlg.gpu_viewport()
        if new_vp != self._gpu_viewport:
            self._gpu_viewport = new_vp
            vp_needs_restart = True
        theme_changed = (dlg.theme() != self._theme)
        self._theme = dlg.theme()
        self._log.info(
            "Settings applied -> send_mode=%s remember=%s autostart=%s top=%s "
            "threads=%s theme=%s",
            dlg.send_mode(), dlg.remember_group(), dlg.autostart(),
            dlg.always_on_top(), dlg.thread_count(), self._theme,
        )
        new_hotkey = dlg.hotkey_info()
        if new_hotkey is not None:
            self._apply_hotkey(*new_hotkey)
        self._save_settings()
        self._apply_theme()
        if theme_changed and self._settings_dialog is not None:
            d = self._settings_dialog
            d.hide()
            d.setStyleSheet(DARK_QSS if self._theme != "light" else LIGHT_QSS)
            d.style().unpolish(d)
            d.style().polish(d)
            for child in d.findChildren(QWidget):
                child.style().unpolish(child)
                child.style().polish(child)
            d.show()
            d.repaint()
        self._apply_always_on_top()
        self._apply_autostart()
        self._apply_thread_count()
        self._refresh_emoji_grid()
        if vp_needs_restart:
            # Say it explicitly: the GPU surface is created at startup only /
            # 明确提示：GPU 表面只在启动时创建
            self.status_bar.showMessage(
                f"  {tr('settings_restart_required')}", 5000)
        if new_lang != old_lang:
            self._reload_language()
            if self._settings_dialog is not None:
                self._settings_dialog.refresh_translations()

    def _reload_language(self):
        self.btn_import.setText(tr("import_gif"))
        self.btn_add_text.setText(tr("add_text"))
        self._build_import_menu()
        self.search_bar.setPlaceholderText(tr("search_placeholder"))
        tray_menu = self._tray.contextMenu()
        if tray_menu:
            tray_menu.actions()[0].setText(tr("tray_show"))
            tray_menu.actions()[-1].setText(tr("tray_quit"))
        self._refresh_emoji_grid()
        self._refresh_status()

    # Shortcut keys — delayed registration in showEvent
    # 快捷键 — showEvent 中延迟注册

    def _init_hotkey_mgr(self):
        self._hotkey_mgr = HotkeyManager(self)
        # Global Alt+scroll watcher for card scaling /
        # 全局 Alt+滚轮监听器（卡片缩放）
        self._scroll_watcher = GlobalScrollWatcher()
        # type=int guards against dirty registry values (startup crash fix) /
        # type=int 防止注册表脏数据导致启动崩溃
        self._hotkey_mods = self._settings.value("hotkey_mods", 0, type=int)
        self._hotkey_vk = self._settings.value(
            "hotkey_vk", Qt.Key.Key_F10, type=int)
        if self._hotkey_vk == 0:
            self._hotkey_mods = 0
            self._hotkey_vk = Qt.Key.Key_F10
        QApplication.instance().installNativeEventFilter(self._hotkey_mgr)

    def _register_hotkey_if_needed(self):
        if self._hotkey_mods != 0 or self._hotkey_vk != 0:
            self._apply_hotkey(self._hotkey_mods, self._hotkey_vk)

    def _apply_hotkey(self, mods, vk):
        if mods == 0 and vk == 0:
            self._hotkey_mgr.unregister()
            self._hotkey_mods = 0
            self._hotkey_vk = 0
            self._settings.setValue("hotkey_mods", 0)
            self._settings.setValue("hotkey_vk", 0)
            self._hotkey_registered = False
            return

        ok = self._hotkey_mgr.register(mods, vk, self._toggle_visible)
        if not ok:
            self.status_bar.showMessage(f"  ⚠ {tr('hotkey_fail')}", 4000)
            return
        self._hotkey_mods = mods
        self._hotkey_vk = vk
        self._hotkey_registered = True
        self._settings.setValue("hotkey_mods", int(mods))
        self._settings.setValue("hotkey_vk", int(vk))

    def _hotkey_desc(self):
        if self._hotkey_mods == 0 and self._hotkey_vk == 0:
            return tr("hotkey_unset")
        mods_val = int(self._hotkey_mods)
        parts = []
        if mods_val & int(Qt.KeyboardModifier.ControlModifier.value):
            parts.append("Ctrl")
        if mods_val & int(Qt.KeyboardModifier.ShiftModifier.value):
            parts.append("Shift")
        if mods_val & int(Qt.KeyboardModifier.AltModifier.value):
            parts.append("Alt")
        if mods_val & int(Qt.KeyboardModifier.MetaModifier.value):
            parts.append("Win")
        vk = self._hotkey_vk
        if vk == 0x100001:
            parts.append(tr("mouse_x1"))
        elif vk == 0x100002:
            parts.append(tr("mouse_x2"))
        else:
            seq = QKeySequence(vk)
            name = seq.toString()
            if name:
                parts.append(name)
        return "+".join(parts) if parts else tr("hotkey_unset")
