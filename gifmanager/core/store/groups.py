"""Group repository: create, rename, reorder and delete groups.

分组仓储：分组的创建、重命名、排序与删除。
"""
import logging
import os
import re
import sqlite3

from gifmanager.core import fileops as file_ops
from gifmanager.core.store import schema

log = logging.getLogger("GIFManager")

# Valid characters for a group name: Chinese, Japanese and English letters,
# digits, spaces and short lines. The name is also used as a directory name, so
# the character set has to stay filesystem-safe on every platform.
# 分组名的合法字符：中英日文字、数字、空格与短横线。名称同时用作目录名，因此字符集
# 在各平台都必须对文件系统安全。
_GROUP_NAME_RE = re.compile(r'^[\w\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\- ]+$')

# Longest accepted group name / 允许的最长分组名
MAX_GROUP_NAME_LENGTH = 32

# rename_group failure reasons, mapped by the UI to translation key suffixes.
# `rename_fail_<reason>` must exist for every value.
# rename_group 的失败原因，界面映射为翻译键后缀。每个取值都必须存在
# `rename_fail_<原因>`。
ERROR_MISSING = "missing"
ERROR_INVALID = "invalid"
ERROR_DUPLICATE = "duplicate"
ERROR_DIR = "dir"


def is_valid_group_name(name):
    # Character-set check plus a length cap. Public because the settings and
    # import paths validate names before calling the store.
    # 字符集检查加长度上限。公开，因为设置与导入路径在调用存储前也会校验名称。
    return bool(_GROUP_NAME_RE.match(name)) and len(name.strip()) <= MAX_GROUP_NAME_LENGTH


class GroupRepository:
    # Group CRUD over the `groups` table, including the folder each group owns.
    # 基于 `groups` 表的分组增删改查，含各分组自己的目录。

    # ---- lookups / 查询 -------------------------------------------------

    def _all_group_id(self):
        # id of the builtin "All" pseudo-group. Private by spelling but part of
        # the public contract: the group bar and the main window call it.
        # 内置"全部"伪分组的 id。名义私有，但属于公开契约：分组栏与主窗口都会调用。
        row = self._conn.execute(
            "SELECT id FROM groups WHERE builtin_role=? LIMIT 1",
            (schema.ROLE_ALL,)).fetchone()
        return row[0] if row else None

    def default_group_id(self):
        # Builtin default group, found by role so renaming or dragging it keeps
        # the lookup working. / 内置默认分组，按角色查找，因此重命名或拖拽后查找
        # 依然有效。
        row = self._conn.execute(
            "SELECT id FROM groups WHERE builtin_role=? LIMIT 1",
            (schema.ROLE_DEFAULT,)).fetchone()
        return row[0] if row else None

    def get_all_groups(self):
        # Every group, "All" first, then by explicit sort order and id.
        # 所有分组，"全部"在最前，其余按显式排序值再按 id。
        all_id = self._all_group_id()
        rows = [dict(r) for r in self._conn.execute("SELECT * FROM groups").fetchall()]
        rows.sort(key=lambda g: (g["id"] != all_id, g["sort_order"], g["id"]))
        return rows

    def get_group(self, group_id):
        row = self._conn.execute(
            "SELECT * FROM groups WHERE id=?", (group_id,)).fetchone()
        return dict(row) if row else None

    def get_group_by_name(self, name):
        row = self._conn.execute(
            "SELECT * FROM groups WHERE name=?", (name,)).fetchone()
        return dict(row) if row else None

    def group_name(self, group_id):
        # Cached name-only lookup — the one field `emoji_filepath()` needs.
        # Returns None when the group does not exist.
        # 带缓存的仅名称查询——`emoji_filepath()` 唯一需要的字段。分组不存在时
        # 返回 None。
        try:
            hit = self._group_name_cache.get(group_id)
        except TypeError:
            # Unhashable id (defensive) falls through to the plain query /
            # 不可哈希的 id（防御性处理）回退到普通查询
            hit = None
        if hit is not None:
            return hit or None
        group = self.get_group(group_id)
        name = group["name"] if group else ""
        self._group_name_cache[group_id] = name
        return name or None

    def _dir_taken_by_other(self, name, group_id=None):
        # True when the folder a group would use is already occupied by a
        # DIFFERENT group's row.
        #
        # Group folders are named after the group name, and the uniqueness check
        # on the name is a case-SENSITIVE SQL comparison, while the default
        # filesystem on macOS and Windows is case-INSENSITIVE. Without this
        # check, creating "test" beside an existing "Test" made both groups
        # share one folder, so deleting either destroyed the other's files.
        # 某分组将要使用的目录是否已被"另一个"分组的行占用时为 True。
        #
        # 分组目录以内置名称命名，而名称唯一性检查是大小写"敏感"的 SQL 比较，但在
        # macOS 与 Windows 上默认文件系统大小写"不敏感"。缺少本检查时，在已有
        # "Test" 的情况下创建 "test" 会让两个分组共用一个目录，删除其一就会毁掉
        # 另一个的文件。
        target = os.path.normcase(os.path.join(self._emojis_dir, name))
        for row in self._conn.execute("SELECT id, name FROM groups").fetchall():
            if group_id is not None and row["id"] == group_id:
                continue
            if os.path.normcase(os.path.join(self._emojis_dir, row["name"])) == target:
                return True
        return False

    # ---- mutations / 变更 -----------------------------------------------

    def create_group(self, name, grp_type=schema.TYPE_IMAGE):
        # Returns the new group id, or None when the name is rejected or already
        # in use. / 返回新分组 id；名称不合法或已被使用时返回 None。
        name = (name or "").strip()
        if not is_valid_group_name(name):
            return None
        if self.get_group_by_name(name):
            return None
        if self._dir_taken_by_other(name):
            log.warning("create_group: folder for %r already belongs to another group", name)
            return None
        row = self._conn.execute("SELECT MAX(sort_order) FROM groups").fetchone()
        max_order = row[0] or 0
        self._conn.execute(
            "INSERT INTO groups (name, type, sort_order) VALUES (?,?,?)",
            (name, grp_type, max_order + 1))
        self._commit()
        self._invalidate_group_cache()
        if grp_type == schema.TYPE_IMAGE:
            os.makedirs(os.path.join(self._emojis_dir, name), exist_ok=True)
        return self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def rename_group(self, group_id, new_name):
        old = self.get_group(group_id)
        if not old:
            self._last_group_error = ERROR_MISSING
            return False
        new_name = (new_name or "").strip()
        if not is_valid_group_name(new_name):
            self._last_group_error = ERROR_INVALID
            return False
        existing = self.get_group_by_name(new_name)
        if existing and existing["id"] != group_id:
            self._last_group_error = ERROR_DUPLICATE
            return False
        if self._dir_taken_by_other(new_name, group_id=group_id):
            self._last_group_error = ERROR_DUPLICATE
            return False
        self._conn.execute(
            "UPDATE groups SET name=? WHERE id=?", (new_name, group_id))
        self._commit()
        self._invalidate_group_cache()

        old_dir = os.path.join(self._emojis_dir, old["name"])
        new_dir = os.path.join(self._emojis_dir, new_name)
        if old["type"] == schema.TYPE_IMAGE and os.path.isdir(old_dir):
            if not file_ops.rename_dir(old_dir, new_dir):
                # Roll the name back so the row and the folder never disagree,
                # otherwise every file of this group becomes unreachable.
                # 回滚名称，使行与目录不会不一致，否则该分组的所有文件都将无法访问。
                self._conn.execute(
                    "UPDATE groups SET name=? WHERE id=?", (old["name"], group_id))
                self._commit()
                self._invalidate_group_cache()
                self._last_group_error = ERROR_DIR
                return False
        self._last_group_error = ""
        return True

    def reorder_group(self, group_id, new_index):
        all_id = self._all_group_id()
        movable = [g["id"] for g in self.get_all_groups() if g["id"] != all_id]
        if group_id not in movable:
            return False
        movable.remove(group_id)
        new_index = max(0, min(new_index, len(movable)))
        movable.insert(new_index, group_id)
        for index, gid in enumerate(movable):
            # sort_order starts at 1, leaving 0 for "All" /
            # sort_order 从 1 开始，0 留给"全部"
            self._conn.execute(
                "UPDATE groups SET sort_order=? WHERE id=?", (index + 1, gid))
        self._commit()
        return True

    def delete_group(self, group_id):
        # Delete a group, its rows and its folder. Refuses builtin groups.
        # 删除分组、其行与目录。内置分组拒绝删除。
        old = self.get_group(group_id)
        if not old or old["is_builtin"]:
            return False
        if old["type"] == schema.TYPE_IMAGE:
            group_dir = os.path.join(self._emojis_dir, old["name"])
            if os.path.isdir(group_dir):
                # Retries because a thumbnail decode or GIF playback teardown
                # may hold a file open for a few hundred milliseconds, which
                # used to leave the group half-deleted.
                # 重试：缩略图解码或 GIF 播放收尾可能占用文件数百毫秒，此前会导致
                # 分组删除到一半。
                file_ops.remove_dir_retry(group_dir)
        self._conn.execute("DELETE FROM emojis WHERE group_id=?", (group_id,))
        self._conn.execute("DELETE FROM groups WHERE id=?", (group_id,))
        self._commit()
        self._invalidate_group_cache()
        return True

    def count_groups(self):
        return self._conn.execute("SELECT COUNT(*) FROM groups").fetchone()[0]

    # ---- builtin maintenance / 内置分组维护 ------------------------------

    def ensure_builtin_groups(self):
        # Create the builtin groups when their roles are missing. Called by the
        # store on open so a database from any release has them.
        # 在角色缺失时创建内置分组。存储打开时调用，使任何版本留下的数据库都有它们。
        created = []
        for role in (schema.ROLE_ALL, schema.ROLE_DEFAULT):
            if schema.ensure_builtin(self._conn, role) is not None:
                created.append(role)
        if created:
            self._invalidate_group_cache()
        return created

    def _existing_group_ids(self):
        try:
            return {row[0] for row in self._conn.execute("SELECT id FROM groups")}
        except sqlite3.Error:
            return set()


__all__ = [
    "ERROR_DIR",
    "ERROR_DUPLICATE",
    "ERROR_INVALID",
    "ERROR_MISSING",
    "GROUP_NAME_RE",
    "MAX_GROUP_NAME_LENGTH",
    "GroupRepository",
    "is_valid_group_name",
]
