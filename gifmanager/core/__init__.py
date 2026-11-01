"""Core layer — platform-independent domain logic.

Nothing in this package may import Qt, `ctypes`, `winreg`, or any other
OS-specific module. Anything that must touch the operating system is reached
through `gifmanager.platform`, which is injected by the caller.

核心层——与平台无关的领域逻辑。

本包内不得导入 Qt、`ctypes`、`winreg` 等系统专有模块。任何必须接触操作系统的
操作都通过调用方注入的 `gifmanager.platform` 完成。
"""

from gifmanager.core.constants import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
)

__all__ = [
    "DEFAULT_WINDOW_HEIGHT",
    "DEFAULT_WINDOW_WIDTH",
    "MIN_WINDOW_HEIGHT",
    "MIN_WINDOW_WIDTH",
]
