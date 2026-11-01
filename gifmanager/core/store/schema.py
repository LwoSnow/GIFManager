"""SQLite database connection, schema and migrations.

The schema is created idempotently: `CREATE TABLE IF NOT EXISTS` for a fresh
database, then per-column `PRAGMA table_info` probes to add anything a database
from an older release is missing. Both halves are kept deliberately — the
`CREATE` bodies already carry the columns that the `ALTER`s add, so a database
created by either path ends up identical.

SQLite 数据库连接、表结构与迁移。

表结构以幂等方式创建：新库走 `CREATE TABLE IF NOT EXISTS`，随后逐列用
`PRAGMA table_info` 探测，为旧版本遗留的数据库补齐缺失列。两部分都刻意保留——
`CREATE` 语句里已经包含 `ALTER` 要加的列，因此无论经哪条路径创建的库最终都一致。
"""
import logging
import os
import sqlite3

log = logging.getLogger("GIFManager")

# Group types / 分组类型
TYPE_IMAGE = "image"
TYPE_TEXT = "text"

# Builtin group roles. Roles, not names, identify the builtin groups, so a user
# may rename or drag them freely without breaking lookups.
# 内置分组角色。内置分组按"角色"而非名称识别，因此用户可以自由重命名或拖拽，
# 查找依然有效。
ROLE_ALL = "all"
ROLE_DEFAULT = "default"

# Builtin group names assigned when the rows are first created /
# 首次创建这些行时使用的内置分组名
BUILTIN_NAMES = {
    ROLE_ALL: ("全部", TYPE_IMAGE),
    ROLE_DEFAULT: ("默认", TYPE_IMAGE),
}

GROUPS_DDL = """
    CREATE TABLE IF NOT EXISTS groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        type TEXT NOT NULL DEFAULT 'image',
        sort_order INTEGER NOT NULL DEFAULT 0,
        is_builtin INTEGER NOT NULL DEFAULT 0,
        builtin_role TEXT DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    )
"""

EMOJIS_DDL = """
    CREATE TABLE IF NOT EXISTS emojis (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        filename TEXT DEFAULT '',
        text_content TEXT DEFAULT '',
        original_name TEXT DEFAULT '',
        content_hash TEXT DEFAULT '',
        sort_order INTEGER NOT NULL DEFAULT 0,
        col_index INTEGER NOT NULL DEFAULT 0,
        user_sorted INTEGER NOT NULL DEFAULT 0,
        use_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE
    )
"""

# Indexes are created after the migrations so an index never references a column
# that a migration is about to add.
# 索引在迁移之后创建，避免索引引用一个迁移即将添加的列。
INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_emojis_hash ON emojis(content_hash)",
    "CREATE INDEX IF NOT EXISTS idx_emojis_group_hash"
    " ON emojis(group_id, content_hash)",
    "CREATE INDEX IF NOT EXISTS idx_emojis_group_src"
    " ON emojis(group_id, src_hash)",
)


# Open a connection with the pragmas the application relies on: WAL for
# concurrent readers, and foreign keys so the emoji rows follow their group.
# 打开连接并设置程序依赖的 pragma：WAL 支持并发读，外键使表情行跟随其分组。
def connect(db_path):
    directory = os.path.dirname(os.path.abspath(db_path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    # `timeout` lets a second process (or a diagnostic tool) wait for a write
    # lock instead of failing instantly with "database is locked".
    # `timeout` 让第二个进程（或诊断工具）等待写锁，而不是立即以
    # "database is locked" 失败。
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def table_columns(conn, table):
    # Column names of a table; empty when the table does not exist.
    # 表的列名；表不存在时返回空集合。
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.DatabaseError:
        return set()
    return {row[1] for row in rows}


def _add_column(conn, table, name, ddl):
    # Add a column only when it is missing. The caller snapshots the column set
    # once, so a single migration pass adds each column at most once.
    # 仅在列缺失时添加。调用方只快照一次列集合，因此单次迁移最多添加每列一次。
    if name in table_columns(conn, table):
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
    return True


def migrate(conn):
    # Bring a database created by any previous release up to the current schema.
    # Returns the list of applied migration names, which the caller logs.
    # 把任何旧版本创建的数据库升级到当前表结构。返回已应用的迁移名列表，供调用方
    # 记录日志。
    applied = []

    emoji_columns = table_columns(conn, "emojis")
    if "content_hash" not in emoji_columns:
        conn.execute("ALTER TABLE emojis ADD COLUMN content_hash TEXT DEFAULT ''")
        applied.append("emojis.content_hash")
    if "src_hash" not in emoji_columns:
        conn.execute("ALTER TABLE emojis ADD COLUMN src_hash TEXT DEFAULT ''")
        applied.append("emojis.src_hash")
    if "sort_order" not in emoji_columns:
        conn.execute(
            "ALTER TABLE emojis ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
        applied.append("emojis.sort_order")
    if "col_index" not in emoji_columns:
        conn.execute(
            "ALTER TABLE emojis ADD COLUMN col_index INTEGER NOT NULL DEFAULT 0")
        applied.append("emojis.col_index")
    if "user_sorted" not in emoji_columns:
        conn.execute(
            "ALTER TABLE emojis ADD COLUMN user_sorted INTEGER NOT NULL DEFAULT 0")
        # Every existing row predates free column arrangement, so its current
        # position is treated as the user's own layout and is never overwritten
        # by the automatic packer. / 所有既有行都早于自由列布局，因此其当前位置
        # 视为用户自己的布局，自动摊列不会覆盖它。
        conn.execute("UPDATE emojis SET user_sorted=1")
        applied.append("emojis.user_sorted")
    if "use_count" not in emoji_columns:
        conn.execute(
            "ALTER TABLE emojis ADD COLUMN use_count INTEGER NOT NULL DEFAULT 0")
        applied.append("emojis.use_count")

    group_columns = table_columns(conn, "groups")
    if "builtin_role" not in group_columns:
        conn.execute("ALTER TABLE groups ADD COLUMN builtin_role TEXT DEFAULT ''")
        # Recover the roles for databases that only knew `is_builtin` plus the
        # historical ordering (All at sort_order 0, Default at 1).
        # 为只知道 `is_builtin` 与历史顺序（全部在 sort_order 0、默认在 1）的
        # 数据库恢复角色。
        conn.execute(
            "UPDATE groups SET builtin_role=? WHERE is_builtin=1 AND sort_order=0",
            (ROLE_ALL,))
        conn.execute(
            "UPDATE groups SET builtin_role=? WHERE is_builtin=1 AND sort_order=1",
            (ROLE_DEFAULT,))
        applied.append("groups.builtin_role")

    if applied:
        log.info("schema migrations applied: %s", ", ".join(applied))
    return applied


def ensure_builtin(conn, role, name=None, group_type=TYPE_IMAGE):
    # Create a builtin group only when its role is absent; never force-rename an
    # existing one (the user is allowed to rename builtin groups).
    # 仅在角色缺失时创建内置分组；绝不强制重命名既有分组（允许用户重命名内置分组）。
    row = conn.execute(
        "SELECT id FROM groups WHERE builtin_role=?", (role,)).fetchone()
    if row is not None:
        return None
    if name is None:
        name, group_type = BUILTIN_NAMES[role]
    cur = conn.execute(
        "INSERT INTO groups (name, type, is_builtin, builtin_role) VALUES (?,?,1,?)",
        (name, group_type, role))
    conn.commit()
    return cur.lastrowid


def initialize(conn):
    # Create the schema, run migrations, seed the builtin groups and build the
    # indexes. Returns the ordered list of steps that actually did something.
    # 创建表结构、执行迁移、播种内置分组并建立索引。返回真正做了事的步骤列表。
    steps = []
    conn.execute(GROUPS_DDL)
    conn.execute(EMOJIS_DDL)
    conn.commit()
    if migrate(conn):
        steps.append("migrate")
    conn.commit()
    for role in (ROLE_ALL, ROLE_DEFAULT):
        if ensure_builtin(conn, role) is not None:
            steps.append(f"seed:{role}")
    for statement in INDEXES:
        conn.execute(statement)
    conn.commit()
    return steps


def cleanup_duplicate_builtins(conn, emojis_dir, move_file, invalidate_cache=None):
    # Repair databases that ended up with more than one row per builtin role
    # (possible before roles existed). Rows are merged into the lowest id, their
    # files are moved into the surviving group's folder and their `group_id` is
    # rewritten; the duplicate rows are then deleted.
    #
    # `move_file(src, dst)` performs the actual file move, so this module stays
    # free of the filesystem policy (retries, copy fallback).
    # 修复每个内置角色存在多行（角色出现之前可能发生）的数据库。各行合并到 id
    # 最小的那行，文件移动到存活分组的目录，`group_id` 改写；随后删除重复行。
    #
    # `move_file(src, dst)` 负责真正的文件移动，使本模块不涉及文件系统策略
    # （重试、复制兜底）。
    removed = 0
    for role in (ROLE_ALL, ROLE_DEFAULT):
        rows = [dict(r) for r in conn.execute(
            "SELECT id, name, sort_order FROM groups WHERE builtin_role=?",
            (role,)).fetchall()]
        if len(rows) < 2:
            continue
        rows.sort(key=lambda r: (r["sort_order"], r["id"]))
        keep = rows[0]
        keep_dir = os.path.join(emojis_dir, keep["name"])
        for dup in rows[1:]:
            dup_dir = os.path.join(emojis_dir, dup["name"])
            if os.path.isdir(dup_dir) and dup_dir != keep_dir:
                os.makedirs(keep_dir, exist_ok=True)
                for name in os.listdir(dup_dir):
                    src = os.path.join(dup_dir, name)
                    dst = os.path.join(keep_dir, name)
                    if os.path.exists(dst):
                        continue
                    try:
                        move_file(src, dst)
                    except OSError as exc:
                        log.warning(
                            "cleanup_duplicate_builtins: cannot move %s -> %s (%s)",
                            src, dst, exc)
            conn.execute(
                "UPDATE emojis SET group_id=? WHERE group_id=?",
                (keep["id"], dup["id"]))
            conn.execute("DELETE FROM groups WHERE id=?", (dup["id"],))
            removed += 1
        conn.commit()
    if invalidate_cache is not None and removed:
        invalidate_cache()
    return removed


__all__ = [
    "BUILTIN_NAMES",
    "EMOJIS_DDL",
    "GROUPS_DDL",
    "INDEXES",
    "ROLE_ALL",
    "ROLE_DEFAULT",
    "TYPE_IMAGE",
    "TYPE_TEXT",
    "cleanup_duplicate_builtins",
    "connect",
    "ensure_builtin",
    "initialize",
    "migrate",
    "table_columns",
]
