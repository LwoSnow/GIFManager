"""Native process launching, isolated from the rest of the application.

Every subprocess the application starts (ffmpeg, PowerShell fallbacks, opening
a downloaded installer) has an OS-specific quirk: Windows needs
`CREATE_NO_WINDOW` or a black console flashes on every launch, macOS needs the
binary located rather than assumed on `PATH`, Linux needs a `$DISPLAY` check
before anything can open a window. This module funnels all of that through one
small surface.

原生进程启动，与程序其余部分隔离。

程序启动的每个子进程（ffmpeg、PowerShell 兜底、打开下载好的安装包）都有各自的
系统特性：Windows 需要 `CREATE_NO_WINDOW`，否则每次启动都闪出黑色控制台；
macOS 需要定位二进制而不是假定它在 `PATH` 上；Linux 在打开任何窗口前需要检查
`$DISPLAY`。本模块把这一切收敛到一个很小的接口上。
"""
import os
import shutil
import subprocess
import sys

from gifmanager.core import logging_setup, paths

log = logging_setup.get_logger()

# Bundled ffmpeg file name per platform / 各平台内置 ffmpeg 的文件名
_FFMPEG_NAMES = ("ffmpeg.exe", "ffmpeg")

# Candidates for the bundled ffmpeg, relative to the resources directory and
# the project root. / 内置 ffmpeg 的候选位置，相对于资源目录与项目根目录。
_FFMPEG_SUBDIRS = ("ffmpeg", "bin", "")


# Extra `subprocess` keyword arguments that suppress a console window on
# Windows; empty elsewhere. Returns a fresh dict each call so callers may
# mutate it.
# 在 Windows 上抑制控制台窗口的 `subprocess` 额外参数；其他平台为空。
# 每次调用返回新字典，调用方可自由修改。
def no_window_kwargs():
    if os.name != "nt":
        return {}
    kwargs = {}
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = startupinfo
    except AttributeError:
        pass
    # CREATE_NO_WINDOW (0x08000000) hides the console of a console subsystem
    # child; STARTF_USESHOWWINDOW alone is not enough for ffmpeg, which is a
    # console application. / CREATE_NO_WINDOW（0x08000000）隐藏控制台子系统
    # 子进程的窗口；仅靠 STARTF_USESHOWWINDOW 对 ffmpeg 这类控制台程序不够。
    kwargs["creationflags"] = 0x08000000
    return kwargs


# Locate an executable: an explicit path first, then the bundled copy, then
# `PATH`. Returns None when nothing usable is found.
# 定位可执行文件：先显式路径，再内置副本，最后 `PATH`。找不到可用项时返回 None。
def find_executable(name, explicit=None):
    if explicit:
        # On Windows `os.access(path, X_OK)` is always True, so existence is
        # the only meaningful test there; elsewhere the executable bit is.
        # 在 Windows 上 `os.access(path, X_OK)` 恒为 True，那里只判断存在性；
        # 其他平台额外判断可执行位。
        explicit = os.path.abspath(explicit)
        if os.path.isfile(explicit):
            if os.name == "nt" or os.access(explicit, os.X_OK):
                return explicit
        return None

    for directory in (paths.resources_dir(), paths.project_root()):
        for sub in _FFMPEG_SUBDIRS:
            base = os.path.join(directory, sub) if sub else directory
            for filename in _FFMPEG_NAMES:
                candidate = os.path.join(base, filename)
                if os.path.isfile(candidate):
                    return candidate

    return shutil.which(name)


# Run a command and capture its output. `timeout` is in seconds.
# Returns a `subprocess.CompletedProcess`; raises OSError when the binary
# cannot be started and `subprocess.TimeoutExpired` on timeout, so callers can
# tell "not installed" apart from "hung".
# 运行命令并捕获输出，`timeout` 单位为秒。
# 返回 `subprocess.CompletedProcess`；二进制无法启动时抛 OSError，超时抛
# `subprocess.TimeoutExpired`，使调用方能区分"未安装"与"卡住"。
def run_capture(argv, timeout=30, cwd=None, extra_kwargs=None):
    kwargs = no_window_kwargs()
    if extra_kwargs:
        kwargs.update(extra_kwargs)
    return subprocess.run(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        cwd=cwd,
        **kwargs,
    )


# Run a command, discarding its output — used for long conversions where only
# the exit status matters.
# 运行命令并丢弃输出——用于只关心退出状态的长耗时转换。
def run_quiet(argv, timeout=120, cwd=None):
    kwargs = no_window_kwargs()
    return subprocess.run(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
        cwd=cwd,
        **kwargs,
    )


# Decode captured bytes using the platform's preferred text encoding, replacing
# undecodable bytes instead of raising. On Windows the console encoding is
# frequently the OEM code page, which cannot represent every adapter name.
# 按平台偏好的文本编码解码捕获到的字节，无法解码时替换而非抛异常。Windows 上
# 控制台编码常为 OEM 代码页，无法表示所有显卡名称。
def decode_output(data, preferred="utf-8"):
    if not data:
        return ""
    for encoding in (preferred, "utf-8", "mbcs" if os.name == "nt" else "utf-8"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")


# Open a file or URL with the desktop's default handler.
# Returns True when the request was handed to the OS successfully.
# 用桌面默认程序打开文件或 URL。请求成功交给系统时返回 True。
def open_path(target):
    if not target:
        return False
    try:
        if sys.platform == "win32":
            os.startfile(target)  # noqa: S606 - documented Windows shell open / Windows 外壳打开
            return True
        if sys.platform == "darwin":
            subprocess.Popen(["open", target], **no_window_kwargs())
            return True
        subprocess.Popen(["xdg-open", target], **no_window_kwargs())
        return True
    except OSError as exc:
        log.warning("open_path: cannot open %s -> %s", target, exc)
        return False


# Reveal a file in the desktop's file manager. Returns True on success.
# 在桌面文件管理器中定位文件。成功返回 True。
def reveal_in_file_manager(target):
    if not target or not os.path.exists(target):
        return False
    try:
        if sys.platform == "win32":
            # `explorer /select,` always exits non-zero, so the result is not
            # checked. / `explorer /select,` 总是返回非零退出码，故不检查结果。
            subprocess.Popen(["explorer", "/select,", os.path.normpath(target)])
            return True
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", target])
            return True
        parent = target if os.path.isdir(target) else os.path.dirname(target)
        subprocess.Popen(["xdg-open", parent])
        return True
    except OSError as exc:
        log.warning("reveal_in_file_manager: cannot reveal %s -> %s", target, exc)
        return False


__all__ = [
    "decode_output",
    "find_executable",
    "no_window_kwargs",
    "open_path",
    "reveal_in_file_manager",
    "run_capture",
    "run_quiet",
]
