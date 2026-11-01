"""Compatibility shim: the old single-window entry point.

The window that used to live here has been split into `shell_window.ShellWindow`
(the window, navigation, menus and status bar) and `views/library.LibraryView`
(the sticker library page). `MainWindow` survives as an alias so code and tests
written against the earlier name keep working, and so there is exactly one obvious
place to read why the split happened.

此处原本的窗口已拆分：`shell_window.ShellWindow` 负责窗口、导航、菜单与状态栏，
`views/library.LibraryView` 负责贴纸库页面。`MainWindow` 作为别名保留，使针对旧名称
编写的代码与测试继续可用，也让"为什么拆分"只有一个明显的查阅位置。
"""
from gifmanager.frontend.qt.shell_window import ShellWindow

# The previous name for the application window / 应用窗口的旧名称
MainWindow = ShellWindow

__all__ = ["MainWindow", "ShellWindow"]
