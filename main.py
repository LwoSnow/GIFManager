import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from app.main_window import MainWindow


def _enable_win11_rounded_corners():  # Window rounded corners / 窗口圆角 (DWM API)
    if sys.platform != "win32":
        return
    try:
        import ctypes
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_ROUND = 2
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.windll.user32.GetActiveWindow(),
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(ctypes.c_int(DWMWCP_ROUND)),
            ctypes.sizeof(ctypes.c_int),
        )
    except Exception:
        pass  # Win10 or earlier versions are not supported / Win10 或更低版本不支持


# Keep the mutex handle alive for the whole process lifetime.
# 保持互斥句柄存活，覆盖整个进程生命周期。
_INSTANCE_MUTEX = None


# Single-instance guard via a Windows named mutex.
# The mutex name is independent of the .py/.exe file name and does not
# rely on PIDs, so it keeps working after packaging into an exe.
# 用 Windows 命名互斥量做单实例检测：互斥名与 .py/.exe 文件名无关、
# 不依赖 PID，打包成 exe 后依然有效。
def _acquire_single_instance_mutex():
    global _INSTANCE_MUTEX
    if sys.platform != "win32":
        return False
    import ctypes
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Local\\GIFManager_SingleInstance")
    # ERROR_ALREADY_EXISTS (183) -> another instance already owns it / 已有实例持有
    already = kernel32.GetLastError() == 183
    if already:
        kernel32.CloseHandle(handle)
    else:
        _INSTANCE_MUTEX = handle
    return already


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("GIFManager")
    app.setOrganizationName("GIFManager")

    font = QFont("Microsoft YaHei", 10)
    app.setFont(font)

    # Single-instance check: show a notice and exit if already running /
    # 单实例检测：若已有实例在运行，弹窗提示后退出
    if _acquire_single_instance_mutex():
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QMessageBox
        from app.models.lang_manager import set_language, tr
        lang = QSettings().value("language", "")
        if lang:
            set_language(lang)
        QMessageBox.information(
            None, tr("already_running_title"), tr("already_running_msg"))
        sys.exit(0)

    window = MainWindow()
    window.show()

    # Enable fillets after window display (requires valid HWND) / 窗口显示后启用圆角（需要有效的 HWND）
    from PySide6.QtCore import QTimer
    QTimer.singleShot(100, _enable_win11_rounded_corners)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
