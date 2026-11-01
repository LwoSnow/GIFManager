"""Application logging: crash-safe session files plus a console mirror.

The log file is written with a per-record flush, so a hard crash still leaves
every line that was logged before it on disk — that is the whole point of the
crash log the project asks users to attach to issues.

应用日志：崩溃安全的会话日志文件 + 控制台镜像。

日志文件每条记录后立即 flush，因此即使进程硬崩溃，崩溃前写过的每一行都已在
磁盘上——这正是项目要求用户随 issue 附上的崩溃日志的价值所在。
"""
import logging
import os
import sys
import threading
from datetime import datetime

from gifmanager.core import paths

# Logger name shared by the whole application / 全应用共用的日志器名称
LOGGER_NAME = "GIFManager"

# Format: time with milliseconds, level, thread, module:line, message.
# 格式：带毫秒的时间、级别、线程、模块:行号、消息。
LOG_FORMAT = (
    "%(asctime)s.%(msecs)03d [%(levelname)s] [%(threadName)s] "
    "%(name)s:%(lineno)d - %(message)s"
)
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

# Log file name pattern / 日志文件名模式
LOG_FILE_PATTERN = "%Y%m%d_%H%M%S.log"

_logger = None
_handler = None
_lock = threading.RLock()


# Directory holding the log files, created on demand.
# 存放日志文件的目录，按需创建。
def logs_dir():
    return paths.logs_dir()


# Logger for the whole application, initialised on first use.
# 全应用的日志器，首次使用时初始化。
def get_logger():
    with _lock:
        if _logger is None:
            _init()
        return _logger


# Explicit initialisation, called once from the application entry point so the
# session banner and the log path are recorded before anything else runs.
# 显式初始化，由应用入口调用一次，使会话横幅与日志路径在任何其他动作之前记录。
def init_logger():
    with _lock:
        if _logger is None:
            _init()
        return _logger


def _init():
    global _logger, _handler
    directory = logs_dir()
    filename = datetime.now().strftime(LOG_FILE_PATTERN)
    path = os.path.join(directory, filename)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # avoid duplicate output through the root logger / 避免经根日志器重复输出

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)

    try:
        # delay=False plus an explicit flush after every record (StreamHandler
        # flushes on emit) keeps the file crash-safe. / delay=False 且每条记录后
        # flush（StreamHandler 在 emit 时 flush），保证日志文件崩溃安全。
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        _handler = handler
    except OSError:
        # A read-only location must not stop the application from starting;
        # the console handler below still reports what happens. / 位置只读不能
        # 阻止程序启动；下面的控制台处理器仍会报告发生了什么。
        _handler = None

    console = _make_console_handler(formatter)
    if console is not None:
        logger.addHandler(console)

    _logger = logger
    logger.info("=== GIFManager session started ===")
    logger.info("Version: %s", _version())
    logger.info("Log file: %s", path)
    logger.info("Data dir: %s", paths.data_dir())
    return logger


def _make_console_handler(formatter):
    # A windowed (console=False) PyInstaller build has no usable stdout; adding
    # a StreamHandler there raises on the first emit. Probe with a real write
    # before installing one. / 无控制台的（console=False）PyInstaller 构建没有
    # 可用的 stdout，此时装 StreamHandler 会在首次 emit 时报错。装之前先实际
    # 写一次做探测。
    stream = sys.stderr
    try:
        if stream is None or not stream.writable():
            return None
        stream.write("")
        stream.flush()
    except Exception:
        return None
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    return handler


def _version():
    try:
        from gifmanager import __version__

        return __version__
    except Exception:
        return "unknown"


# Re-create the session log file, deleting every previous `.log` in the
# directory. Returns the number of files removed.
# 重建会话日志文件，并删除目录内所有旧的 `.log`。返回删除的文件数。
def clear_logs():
    global _logger, _handler
    with _lock:
        if _handler is not None:
            try:
                _logger.removeHandler(_handler)
                _handler.close()
            except Exception:
                pass
        _handler = None
        _logger = None

        directory = logs_dir()
        removed = 0
        try:
            names = os.listdir(directory)
        except OSError:
            names = []
        for name in names:
            if not name.endswith(".log"):
                continue
            try:
                os.remove(os.path.join(directory, name))
                removed += 1
            except OSError:
                pass
        _init()
        return removed


# Route uncaught exceptions into the log before the default handler prints them.
# 未捕获异常先写入日志，再交给默认处理器打印。
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


# Route uncaught exceptions raised inside worker threads into the same log,
# otherwise they are printed to a console that a GUI build does not have.
# 工作线程内未捕获的异常同样写入日志，否则它们会被打印到 GUI 构建并不存在的
# 控制台上。
def install_thread_excepthook():
    def hook(args):
        try:
            get_logger().error(
                "Uncaught exception in thread %s:\n%s",
                args.thread.name if args.thread else "?",
                "".join(_format_exception(args)),
            )
        except Exception:
            pass

    threading.excepthook = hook


def _format_exception(args):
    import traceback

    return traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)


__all__ = [
    "LOGGER_NAME",
    "clear_logs",
    "get_logger",
    "init_logger",
    "install_excepthook",
    "install_thread_excepthook",
    "logs_dir",
]
