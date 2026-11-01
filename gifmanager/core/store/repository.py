"""Data store facade: connection ownership, path resolution and transactions.

`DataStore` composes the group, emoji, import and layout repositories over one
SQLite connection. It has no Qt dependency and no OS-specific calls, so the same
object backs the Qt desktop window, a headless CLI, and future front-ends.

The public method names match the pre-refactor `DataManager` exactly, including
the ones that are private by spelling but public by use (`_all_group_id`) —
their callers are outside this package.

数据存储门面：连接持有、路径解析与事务。

`DataStore` 在一个 SQLite 连接之上组合分组、表情、导入与布局四个仓储。它不依赖
Qt，也没有系统专有调用，因此同一个对象可以支撑 Qt 桌面窗口、无界面 CLI 以及将来
的前端。

公开方法名与重构前的 `DataManager` 完全一致，包括那些"名义私有、实际公用"的
方法（`_all_group_id`）——它们的调用方在本包之外。
"""
import contextlib
import logging
import os
import sqlite3

from gifmanager.core import paths
from gifmanager.core.imaging.converter import MediaConverter
from gifmanager.core import fileops as file_ops
from gifmanager.core.store import schema

log = logging.getLogger("GIFManager")


class DataStore:
    # SQLite store for groups and emoji rows plus their files on disk.
    #
    # Every path is injected rather than discovered, so a test can point the
    # store at a temporary directory and a portable install can point it at a
    # USB stick without touching this class.
    # 分组与表情行及其磁盘文件的 SQLite 存储。
    #
    # 所有路径都是注入的而非自行探测，因此测试可以把存储指向临时目录，便携安装也
    # 可以把它指向 U 盘，都不需要改动本类。
    def __init__(self, data_dir=None, db_path=None, emojis_dir=None,
                 converter=None, initialize=True):
        self._data_dir = os.path.abspath(data_dir or paths.data_dir())
        self._db_path = os.path.abspath(
            db_path or os.path.join(self._data_dir, "emoji.db"))
        self._emojis_dir = os.path.abspath(
            emojis_dir or os.path.join(self._data_dir, "emojis"))
        os.makedirs(self._emojis_dir, exist_ok=True)

        self._converter = converter or MediaConverter()
        self._conn = schema.connect(self._db_path)

        # Last `rename_group` failure reason; the UI maps it to a translation
        # key such as "rename_fail_dir". / 上次重命名分组失败的原因；界面把它映射
        # 为 "rename_fail_dir" 之类的翻译键。
        self._last_group_error = ""
        # Last `move_emoji` failure reason. Previously assigned but never
        # initialised, so reading it raised AttributeError on a fresh instance;
        # it is now declared here and exposed through `last_move_error`.
        # 上次移动表情失败的原因。此前只赋值未初始化，新实例上读取会抛
        # AttributeError；现在在此声明，并通过 `last_move_error` 暴露。
        self._last_move_error = ""
        # Paths of temporary send copies awaiting delayed cleanup /
        # 等待延迟清理的发送临时副本路径
        self._pending_send_temps = set()

        # group_id -> name. `emoji_filepath()` runs for every card on every lazy
        # load recycle and used to hit SQLite each time (a 40-step scroll
        # profile showed 1531 `get_group()` queries, about 15% of the whole
        # scroll cost). Cleared by every group mutation.
        # group_id -> 名称。懒加载回收时每张卡都会调用 `emoji_filepath()`，而它
        # 以前每次都查 SQLite（40 步滚动剖析显示 1531 次 `get_group()`，约占整体
        # 滚动开销的 15%）。任何分组变更都会清空该缓存。
        self._group_name_cache = {}

        if initialize:
            schema.initialize(self._conn)
            schema.cleanup_duplicate_builtins(
                self._conn, self._emojis_dir, file_ops.rename_dir,
                invalidate_cache=self._invalidate_group_cache)

    # ---- lifecycle / 生命周期 -------------------------------------------

    def close(self):
        # Close the SQLite connection. Safe to call twice /
        # 关闭 SQLite 连接。重复调用安全。
        try:
            self._conn.commit()
        except sqlite3.Error:
            pass
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

    # ---- paths / 路径 ----------------------------------------------------

    @property
    def data_dir(self):
        return self._data_dir

    @property
    def db_path(self):
        return self._db_path

    @property
    def emojis_dir(self):
        return self._emojis_dir

    @property
    def converter(self):
        return self._converter

    @property
    def connection(self):
        return self._conn

    @property
    def last_group_error(self):
        return self._last_group_error

    @property
    def last_move_error(self):
        return self._last_move_error

    def group_dir(self, group):
        # Directory holding a group's files. The directory is named after the
        # group NAME (not its id), which is why renaming a group has to move a
        # folder and why two names differing only in case collide on a
        # case-insensitive filesystem. `path_for_group_id` guards that.
        # 存放某分组文件的目录。目录以内置分组"名称"（而非 id）命名，这正是重命名
        # 分组必须移动目录、以及仅大小写不同的两个名称会在大小写不敏感文件系统上
        # 冲突的原因。`path_for_group_id` 对此做了防护。
        name = group["name"] if isinstance(group, dict) else str(group)
        return os.path.join(self._emojis_dir, name)

    def path_for_group_id(self, group_id, filename):
        name = self.group_name(group_id)
        if not name or not filename:
            return None
        return os.path.join(self._emojis_dir, name, filename)

    def emoji_filepath(self, emoji):
        # Absolute path of an emoji's file, or None for a text row or a group
        # that no longer exists. Hot path: called for every card.
        # 表情文件的绝对路径；文字行或分组已不存在时返回 None。热路径：每张卡都会
        # 调用。
        if not emoji.get("filename"):
            return None
        return self.path_for_group_id(emoji["group_id"], emoji["filename"])

    # ---- transactions / 事务 --------------------------------------------

    @contextlib.contextmanager
    def transaction(self):
        # Explicit transaction that maps to BEGIN / COMMIT / ROLLBACK.
        #
        # sqlite3's default isolation level opens an implicit transaction before
        # DML, and issuing `BEGIN` while one is open raises
        # "cannot start a transaction within a transaction". This helper commits
        # any implicit transaction first, so the batch writes below are always
        # exactly one transaction.
        # 显式事务，映射为 BEGIN / COMMIT / ROLLBACK。
        #
        # sqlite3 默认隔离级别会在 DML 前开启隐式事务，此时再发 `BEGIN` 会抛
        # "cannot start a transaction within a transaction"。本辅助函数先提交
        # 隐式事务，使下面的批量写入始终恰好是一个事务。
        self._conn.commit()
        self._conn.execute("BEGIN")
        try:
            yield self._conn
        except BaseException:
            self._conn.rollback()
            raise
        self._conn.commit()

    def _commit(self):
        self._conn.commit()

    # ---- shared helpers / 共用辅助 --------------------------------------

    @staticmethod
    def _file_md5(path):
        # Kept as a staticmethod on the class because callers patch it to count
        # hashing work (`DataManager._file_md5 = staticmethod(counter)`).
        # 保持为类上的静态方法，因为调用方会替换它以统计哈希次数
        # （`DataManager._file_md5 = staticmethod(counter)`）。
        return file_ops.file_md5(path)

    @staticmethod
    def _escape_like(keyword):
        return keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def _invalidate_group_cache(self):
        # Drop the cached group names after any group mutation /
        # 任何分组变更后清空缓存的分组名
        self._group_name_cache.clear()

    def _begin(self):
        return self.transaction()


# The mixins are imported after `DataStore` is defined so they may refer to the
# shared helpers above without a circular import at module load time.
# 各 mixin 在 `DataStore` 定义之后导入，使其可以引用上面的共用辅助而不在模块加载
# 时形成循环导入。
from gifmanager.core.store.emojis import EmojiRepository  # noqa: E402
from gifmanager.core.store.groups import GroupRepository  # noqa: E402
from gifmanager.core.store.media import MediaRepository  # noqa: E402
from gifmanager.core.store.ordering import OrderingRepository  # noqa: E402


class Store(GroupRepository, EmojiRepository, MediaRepository,
            OrderingRepository, DataStore):
    # Complete store: every repository mixed into the facade. Instantiate this
    # class; `DataStore` alone only provides connection and path handling.
    # 完整存储：所有仓储混入门面。请实例化本类；单独的 `DataStore` 只提供连接与
    # 路径处理。
    pass


__all__ = ["DataStore", "Store"]
