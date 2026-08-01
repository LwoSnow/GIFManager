"""Application log file management
应用日志文件管理"""
import os
import sys
import logging
from datetime import datetime


def _root_dir():
    d = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return d


def logs_dir():
    candidates = []
    if getattr(sys, "frozen", False):
        # PyInstaller 打包版：优先 %LOCALAPPDATA%（安装到 Program Files 也可写），
        # 其次 exe 同级（便携场景）
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(os.path.join(local, "GIFManager", "logs"))
        candidates.append(os.path.join(os.path.dirname(sys.executable), "logs"))
    else:
        candidates.append(os.path.join(_root_dir(), "logs"))
    for c in candidates:
        try:
            os.makedirs(c, exist_ok=True)
            return c
        except OSError:
            continue  # 无写权限则尝试下一个候选
    return candidates[-1]


_logger = None
_handler = None


def init_logger():
    global _logger, _handler
    if _logger is not None:
        return _logger
    path = os.path.join(logs_dir(), datetime.now().strftime("%Y%m%d_%H%M%S") + ".log")
    _logger = logging.getLogger("GIFManager")
    _logger.setLevel(logging.DEBUG)
    _logger.propagate = False  # 避免重复输出
    _handler = logging.FileHandler(path, encoding="utf-8")
    fmt = logging.Formatter(
        "%(asctime)s.%(msecs)03d [%(levelname)s] [%(threadName)s] "
        "%(name)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    _handler.setFormatter(fmt)
    # FileHandler (StreamHandler) flushes after each emit by default
    # FileHandler（StreamHandler）默认每条 emit 后 flush
    _logger.addHandler(_handler)
    # Console synchronous output (developers can view it in real time, StreamHandler flushes after emit by default)
    # 控制台同步输出（开发者实时查看，StreamHandler 默认 emit 后 flush）
    _console = logging.StreamHandler(sys.stdout)
    _console.setFormatter(fmt)
    _logger.addHandler(_console)
    _logger.info("=== GIFManager session started ===")
    _logger.info("Log file: %s", path)
    return _logger


def get_logger():
    if _logger is None:
        init_logger()
    return _logger


def clear_logs():
    global _logger, _handler
    if _handler is not None:
        try:
            _logger.removeHandler(_handler)
            _handler.close()
        except Exception:
            pass
        _handler = None
        _logger = None
    logs = logs_dir()
    count = 0
    for fn in os.listdir(logs):
        if fn.endswith(".log"):
            try:
                os.remove(os.path.join(logs, fn))
                count += 1
            except OSError:
                pass
    init_logger()  # Rebuild the current session log file / 重建当前会话日志文件
    return count


def install_excepthook():
    import traceback

    def hook(exc_type, exc_value, exc_tb):
        try:
            get_logger().error(
                "Uncaught exception:\n%s",
                "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
            )
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = hook
