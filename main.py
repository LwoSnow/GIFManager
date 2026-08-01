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


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("GIFManager")
    app.setOrganizationName("GIFManager")

    font = QFont("Microsoft YaHei", 10)
    app.setFont(font)

    window = MainWindow()
    window.show()

    # Enable fillets after window display (requires valid HWND) / 窗口显示后启用圆角（需要有效的 HWND）
    from PySide6.QtCore import QTimer
    QTimer.singleShot(100, _enable_win11_rounded_corners)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
