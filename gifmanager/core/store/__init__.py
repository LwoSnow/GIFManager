"""Data store: SQLite schema, migrations and the domain repositories.

The portable filesystem helpers live one level up in `gifmanager.core.fileops`,
because both the imaging layer and the store need them; importing them through
this package would make `imaging -> store -> imaging` a cycle.

数据存储：SQLite 表结构、迁移与领域仓储。

可移植的文件系统辅助函数位于上一层的 `gifmanager.core.fileops`，因为图像层与存储
都需要它们；经本包导入会造成 `imaging -> store -> imaging` 循环。
"""
from gifmanager.core.store.repository import DataStore, Store
from gifmanager.core.store.schema import (
    INDEXES,
    ROLE_ALL,
    ROLE_DEFAULT,
    TYPE_IMAGE,
    TYPE_TEXT,
    cleanup_duplicate_builtins,
    connect,
    ensure_builtin,
    initialize,
    migrate,
    table_columns,
)

__all__ = [
    "INDEXES",
    "ROLE_ALL",
    "ROLE_DEFAULT",
    "TYPE_IMAGE",
    "TYPE_TEXT",
    "DataStore",
    "Store",
    "cleanup_duplicate_builtins",
    "connect",
    "ensure_builtin",
    "initialize",
    "migrate",
    "table_columns",
]
