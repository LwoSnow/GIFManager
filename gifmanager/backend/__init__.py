"""Backend layer — application services and the contract a front-end consumes.

This is the layer between the pure core and a user interface. It owns the
service objects, their lifecycle, and the notification a front-end subscribes
to when the library changes. It contains no widgets, so the same backend can
drive the Qt desktop shell, a headless command line tool, and a future
non-Qt front-end.

后端层——应用服务与前端消费的契约。

这是纯核心与用户界面之间的一层。它持有各服务对象、它们的生命周期，以及库发生变更时
前端订阅的通知。它不含控件，因此同一后端可以驱动 Qt 桌面外壳、无界面命令行工具以及
将来的非 Qt 前端。
"""
from gifmanager.backend.app import (
    CHANGE_LANGUAGE,
    CHANGE_LIBRARY,
    CHANGE_SETTINGS,
    Backend,
    create_backend,
    default_hotkey,
)
from gifmanager.backend.settings_store import (
    JsonSettingsStore,
    MemorySettingsStore,
    SettingsStore,
)

__all__ = [
    "Backend",
    "CHANGE_LANGUAGE",
    "CHANGE_LIBRARY",
    "CHANGE_SETTINGS",
    "JsonSettingsStore",
    "MemorySettingsStore",
    "SettingsStore",
    "create_backend",
    "default_hotkey",
]
