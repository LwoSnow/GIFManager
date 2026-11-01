"""Qt application shell: process setup, single instance, theme, main window.

This is the nearest thing to the old `main.py`. It is deliberately thin: it
builds a `QApplication`, asks the platform layer whether another instance is
already running, builds the backend, and shows the window. Everything the old
entry point did inline — a Windows named mutex, a DWM call, a `QSettings`
language read, a `Microsoft YaHei` font — is now a call into a layer.

Qt 应用外壳：进程设置、单实例、主题、主窗口。

这是与旧 `main.py` 最接近的东西。它刻意很薄：构建 `QApplication`、向平台层询问是否
已有实例在运行、构建后端、显示窗口。旧入口内联做的每件事——Windows 命名互斥量、DWM
调用、`QSettings` 语言读取、`Microsoft YaHei` 字体——现在都是一次层调用。
"""
import logging
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from gifmanager import APP_NAME, __version__
from gifmanager.backend import create_backend
from gifmanager.core import lang, logging_setup, paths
from gifmanager.frontend.qt.bridge import BackendAdapter, apply_theme
from gifmanager.frontend.qt.shell_window import ShellWindow
from gifmanager.platform import single_instance as single_instance_service
from gifmanager.platform import window as window_platform

log = logging.getLogger("GIFManager")

# Font families tried in order, per platform convention. The first available one
# is used; Qt falls back automatically, but naming the right family per system is
# what keeps CJK glyph metrics consistent — and those metrics feed the text-card
# height calculation.
# 按平台惯例依次尝试的字体族。使用第一个可用的；Qt 会自动回退，但为各系统指定正确的
# 字体族才能保证中日韩字形的度量一致——而那些度量会影响文字卡片高度计算。
FONT_FAMILIES = {
    "win32": ("Microsoft YaHei UI", "Microsoft YaHei"),
    "darwin": ("PingFang SC", "Hiragino Sans GB"),
}
FONT_FAMILIES_DEFAULT = (
    "Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Micro Hei",
    "DejaVu Sans",
)

# Base point size for the interface font / 界面字体基准磅值
BASE_FONT_POINT_SIZE = 10

# Delay before asking the compositor for rounded corners: the call needs a valid
# window handle, which does not exist until the window has been shown.
# 向合成器请求圆角前的延迟：该调用需要有效的窗口句柄，而窗口显示前它并不存在。
ROUNDED_CORNERS_DELAY_MS = 100


def interface_font():
    # The interface font, with a per-platform family list /
    # 界面字体，带按平台的字体族列表
    families = FONT_FAMILIES.get(sys.platform, FONT_FAMILIES_DEFAULT)
    font = QFont()
    font.setFamilies(list(families))
    font.setPointSize(BASE_FONT_POINT_SIZE)
    return font


def acquire_single_instance(name=APP_NAME):
    # (acquired, handle). The handle must stay alive for the whole process, so
    # it is returned rather than stored in a module global that a garbage
    # collector could drop.
    # 返回 (是否获取成功, 句柄)。句柄必须在整个进程存活，因此以返回值传递，而不是存进
    # 可能被垃圾回收的模块全局量。
    service = single_instance_service()
    return service.acquire(name)


def build_application(argv=None):
    # A configured QApplication. High-DPI rounding is set to PassThrough so
    # fractional scale factors (125%) are honoured instead of rounded to 100% or
    # 200%, which is what keeps a 3-column layout from collapsing to 2 columns.
    # 已配置的 QApplication。高 DPI 舍入设为 PassThrough，使 125% 这类分数缩放被
    # 尊重而不是舍入到 100% 或 200%——这正是 3 列布局不会塌成 2 列的原因。
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setFont(interface_font())
    return app


def message_box(title_key, message_key, backend=None):
    # Show a translated notice. `backend` supplies the language when one has
    # already been built; otherwise the core default applies.
    # 显示一条已翻译的提示。`backend` 提供语言（若已构建）；否则用核心层默认值。
    translate = backend.tr if backend is not None else lang.tr
    QMessageBox.information(None, translate(title_key), translate(message_key))


def run(argv=None):
    # Build everything and enter the Qt event loop. Returns the exit code.
    # 构建一切并进入 Qt 事件循环。返回退出码。
    logging_setup.init_logger()
    logging_setup.install_excepthook()
    logging_setup.install_thread_excepthook()
    log.info("=== %s %s starting ===", APP_NAME, __version__)

    app = build_application(argv)

    # Single-instance check before any real work: a second launch must not open
    # the database, or two processes would write the same SQLite file.
    # 任何实际工作之前先做单实例检查：第二次启动不得打开数据库，否则两个进程会写同一个
    # SQLite 文件。
    acquired, handle = acquire_single_instance()
    if not acquired:
        # Read the configured language without a backend so the notice is
        # already in the user's language.
        # 不借助后端读取配置的语言，使提示已经是用户的语言。
        logging_setup.get_logger().info("another instance is already running")
        message_box("already_running_title", "already_running_msg")
        return 0

    backend = None
    try:
        backend = create_backend()
        apply_theme(app, backend.settings.theme)

        adapter = BackendAdapter(backend)
        window = ShellWindow(adapter)
        window.show()

        # Rounded corners need a valid window handle, which only exists after
        # the window has been shown.
        # 圆角需要有效的窗口句柄，而它只在窗口显示后才存在。
        QTimer.singleShot(
            ROUNDED_CORNERS_DELAY_MS,
            lambda: window_platform().apply_rounded_corners(int(window.winId())))

        exit_code = app.exec()
    finally:
        # Ordered teardown, innermost first: the backend drops its temporary
        # files and closes the database, then the instance handle is released.
        # 有序退出，由内向外：后端先清理临时文件并关闭数据库，随后释放实例句柄。
        if backend is not None:
            try:
                backend.close()
            except Exception:
                log.exception("shutdown: backend close failed")
        try:
            single_instance_service().release(handle)
        except Exception:
            log.exception("shutdown: instance release failed")
        log.info("=== %s exited with %s ===", APP_NAME, exit_code)
    return exit_code


def main():
    return run()


__all__ = [
    "BASE_FONT_POINT_SIZE",
    "FONT_FAMILIES",
    "acquire_single_instance",
    "build_application",
    "interface_font",
    "main",
    "run",
]
