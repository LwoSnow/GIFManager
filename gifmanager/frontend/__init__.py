"""Qt front-end shell.

Everything under this package may import PySide6; nothing outside it may. The
backend it drives is toolkit-free, so a different shell (web, GTK, TUI) can be
added beside this one without touching `core`, `platform` or `backend`.

Qt 前端外壳。

本包内的一切都可以导入 PySide6；包外的一切都不可以。它所驱动的后端与工具包无关，
因此可以在本外壳旁边新增另一种外壳（Web、GTK、TUI），而无需改动 `core`、
`platform` 或 `backend`。
"""

__all__ = []
