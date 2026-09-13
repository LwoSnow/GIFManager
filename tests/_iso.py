"""Shared isolation for tests that build the real MainWindow.

A test must never read or write the user's real preferences. Two things used to
leak out of the test process:

1. `QSettings("GIFManager", "GIFManager")` — the real registry key. Tests that
   pressed OK in the settings dialog (or quit the window) wrote the whole
   default block back into it, which silently reset "窗口置顶", the chosen GPU
   and the window geometry. One test even called `clear()` on it.
2. `HKCU\\Software\\Microsoft\\DirectX\\UserGpuPreferences` — the Windows
   per-app GPU preference. Every MainWindow construction used to rewrite (and,
   with acceleration off, delete) the entry for `python.exe`.

`isolate_settings()` points MainWindow at a throwaway INI file and
`isolate_gpu_pref()` points the GPU helper at a throwaway registry subkey. Call
BOTH before constructing MainWindow.

测试绝不能读写用户真实的偏好设置。曾有两处会从测试进程泄漏出去：
1. `QSettings("GIFManager", "GIFManager")` —— 真实注册表键。在设置对话框中按下
   确定（或退出窗口）的测试会把整块默认值写回去，静默重置"窗口置顶"、已选显卡
   与窗口几何；甚至有一个测试对它调用了 clear()。
2. `HKCU\\Software\\Microsoft\\DirectX\\UserGpuPreferences` —— Windows 的按应用
   GPU 首选项。以前每次构造 MainWindow 都会重写（加速关闭时还会删除）
   python.exe 对应的项。

`isolate_settings()` 让 MainWindow 使用临时 INI 文件，`isolate_gpu_pref()` 让 GPU
辅助指向临时注册表子键。构造 MainWindow 前请同时调用两者。
"""
import atexit
import os
import shutil
import tempfile

from PySide6.QtCore import QSettings

_TMP = None


def _tmp_dir():
    global _TMP
    if _TMP is None:
        _TMP = tempfile.mkdtemp(prefix="gm_iso_")
        # Best-effort cleanup; tests often os._exit(), so this may not run /
        # 尽力清理；测试常用 os._exit()，因此不保证执行
        atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))
    return _TMP


def isolate_settings():
    # Redirect MainWindow's QSettings to a throwaway INI. MainWindow looks the
    # factory up at call time, so patching before construction is enough.
    # 将 MainWindow 的 QSettings 重定向到临时 INI。MainWindow 在调用时查找该
    # 工厂，因此在构造前替换即可。
    import app.main_window as mw
    path = os.path.join(_tmp_dir(), "settings.ini")
    mw._new_settings = lambda: QSettings(path, QSettings.Format.IniFormat)
    return path


def isolate_gpu_pref():
    # Redirect the per-app GPU preference to a throwaway subkey so the round
    # trip can still be exercised without touching the real one.
    # 将按应用 GPU 首选项重定向到临时子键，既能验证读写往返，又不碰真实项。
    from app.utils import gpu_pref
    gpu_pref._REG_PATH = r"Software\GIFManager\TestGpuPreferences"
    return gpu_pref._REG_PATH


def cleanup_gpu_pref():
    # Delete the sandbox subkeys so a test run leaves no trace in HKCU.
    # os._exit() skips atexit, which is why drain_and_exit() calls this.
    # 删除沙箱子键，使测试运行不在 HKCU 留痕。os._exit() 不会执行 atexit，因此由
    # drain_and_exit() 调用本函数。
    try:
        import winreg
    except ImportError:
        return
    for sub in (r"Software\GIFManager\TestGpuPreferences",
                r"Software\GIFManager\AuditGpuPref"):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
        except OSError:
            pass


def isolate_all():
    return isolate_settings(), isolate_gpu_pref()


def drain_and_exit(code=0):
    """Drain Qt's thread pools, flush, then os._exit(code).

    os._exit() skips atexit handlers, so a decode/probe worker still running at
    that instant keeps touching Qt objects while Windows detaches DLLs — the
    intermittent 0xC0000005 / 0xC0000409 crash that shows up AFTER a test's
    summary line. Tests that terminate this way must drain first.
    os._exit() 不会执行 atexit 处理器，因此此刻仍在运行的解码/探测 worker 会在
    Windows 卸载 DLL 时继续触碰 Qt 对象——即测试汇总行之后偶发的
    0xC0000005 / 0xC0000409 崩溃。以此方式结束的测试必须先排空线程池。
    """
    import os
    import sys
    try:
        from PySide6.QtCore import QThreadPool, QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
        try:
            from app.widgets.emoji_item import _loader
            _loader.shutdown(3000)
        except Exception:
            pass
        pool = QThreadPool.globalInstance()
        pool.clear()
        # The budget must exceed the GPU probe's PowerShell timeout (5 s):
        # a run that opened Settings can still be inside that call, and
        # os._exit() while it is reading the pipe is a real crash. Waiting
        # longer costs nothing when the pool is already idle.
        # 该预算必须大于 GPU 探测任务的 PowerShell 超时（5s）：打开过设置的那一轮
        # 可能仍在这次调用里，此时 os._exit() 会在它读管道时崩溃。池已空闲时多等
        # 不会有任何代价。
        pool.waitForDone(7000)
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
    except Exception:
        pass
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    cleanup_gpu_pref()
    os._exit(code)
