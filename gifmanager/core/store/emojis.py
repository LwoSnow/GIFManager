"""Emoji repository: rows, hashes, counts, movement and text entries.

表情仓储：行、哈希、计数、移动与文字条目。
"""
import logging
import os

from gifmanager.core import fileops as file_ops
from gifmanager.core.store import schema

log = logging.getLogger("GIFManager")

# Import outcomes returned by `import_emoji` /
# `import_emoji` 返回的导入结果
RESULT_OK = "ok"
RESULT_DUPLICATE = "duplicate"
RESULT_ERROR = "error"

# `add_text_emoji` sentinels / `add_text_emoji` 的返回值约定
TEXT_DUPLICATE = 0
TEXT_REJECTED = -1

# Length of the auto-generated display name for a text entry /
# 文字条目自动生成的显示名长度
TEXT_DISPLAY_LENGTH = 20

# Longest side above which a GIF pastes as a file attachment rather than a
# picture in chat applications. / 超过此长度的 GIF 在聊天软件中会被当作文件附件
# 而非图片粘贴。
OVERSIZED_SEND_DIM = 512


def text_display_name(text):
    # First 20 characters of a text entry, with an ellipsis when truncated.
    # 文字条目的前 20 个字符，被截断时加省略号。
    text = text or ""
    return text[:TEXT_DISPLAY_LENGTH] + ("..." if len(text) > TEXT_DISPLAY_LENGTH else "")


class EmojiRepository:
    # Emoji rows: queries, hashes, imports, text entries, moves and deletes.
    # 表情行：查询、哈希、导入、文字条目、移动与删除。

    # ---- queries / 查询 -------------------------------------------------

    def get_all_emojis(self, keyword=""):
        # The "All" view: image groups only, folded by content hash so the same
        # picture stored in two groups appears once.
        # "全部"视图：仅图片分组，按内容哈希折叠，使存于两个分组的同一张图只出现一次。
        self._backfill_content_hash()
        where = "g.type='image' AND e.filename != '' AND e.content_hash != ''"
        args = []
        if keyword:
            where += " AND e.original_name LIKE ? ESCAPE '\\'"
            args.append(f"%{self._escape_like(keyword)}%")
        rows = self._conn.execute(
            "SELECT e.* FROM emojis e JOIN groups g ON e.group_id=g.id "
            f"WHERE {where} "
            "GROUP BY e.content_hash "
            "ORDER BY MAX(e.sort_order), MAX(e.created_at) DESC",
            args,
        ).fetchall()
        return [dict(r) for r in rows]

    def get_emojis_by_group(self, group_id, keyword=""):
        if keyword:
            pattern = f"%{self._escape_like(keyword)}%"
            rows = self._conn.execute(
                "SELECT * FROM emojis WHERE group_id=? "
                "AND (original_name LIKE ? ESCAPE '\\'"
                " OR text_content LIKE ? ESCAPE '\\') "
                "ORDER BY sort_order, id",
                (group_id, pattern, pattern),
            ).fetchall()
        else:
            # Column-major, like the original grid: every concrete group laid out
            # as masonry columns (its `set_masonry(current_group_id is not
            # None)`), so a card's place is its (column, position within column)
            # and drag-reorder writes are only visible under this ordering.
            # 列主序，与原网格一致：原项目的所有具体分组都按瀑布流列布局（其
            # `set_masonry(current_group_id is not None)`），因此一张卡的位置就是它的
            # （列, 列内位置），拖拽排序的写入也只有在这个排序下才可见。
            rows = self._conn.execute(
                "SELECT * FROM emojis WHERE group_id=? "
                "ORDER BY col_index, sort_order, id",
                (group_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_all_emojis(self):
        return self._conn.execute("SELECT COUNT(*) FROM emojis").fetchone()[0]

    def count_image_emojis(self):
        return self._conn.execute(
            "SELECT COUNT(*) FROM emojis e JOIN groups g ON e.group_id=g.id "
            "WHERE g.type='image'").fetchone()[0]

    def count_emojis_in_group(self, group_id):
        return self._conn.execute(
            "SELECT COUNT(*) FROM emojis WHERE group_id=?", (group_id,)).fetchone()[0]

    def get_emoji(self, emoji_id):
        row = self._conn.execute(
            "SELECT * FROM emojis WHERE id=?", (emoji_id,)).fetchone()
        return dict(row) if row else None

    def get_emoji_copies(self, emoji):
        # Every stored copy of the same picture, across all groups, with the
        # group name joined in — the duplicate-removal dialog lists these.
        # 同一张图在所有分组中的每个副本，并连接分组名——重复删除对话框用它列出。
        if not emoji.get("content_hash"):
            return [emoji]
        rows = self._conn.execute(
            "SELECT e.*, g.name AS group_name FROM emojis e "
            "JOIN groups g ON e.group_id=g.id "
            "WHERE e.content_hash=? AND e.filename != '' "
            "ORDER BY e.sort_order, e.id",
            (emoji["content_hash"],),
        ).fetchall()
        return [dict(r) for r in rows]

    def ids_sharing_content_hash(self, emoji_ids):
        # Every row (across all groups) whose content hash matches one of the
        # given ids, INCLUDING those ids.
        #
        # The All view folds rows by content hash, so deleting only the folded
        # representative left the other copies in place and the user saw
        # stickers that "would not go away" after select-all + delete.
        # 所有内容哈希与给定 id 之一相同的行（跨分组），并包含这些 id 本身。
        #
        # "全部"视图按内容哈希折叠行，只删除折叠后的代表行会让其余副本残留，用户
        # 看到的是全选删除后"删不干净"。
        if not emoji_ids:
            return []
        ids = []
        seen = set()
        for emoji_id in emoji_ids:
            key = str(emoji_id)
            if key in seen:
                continue
            seen.add(key)
            ids.append(emoji_id)
        placeholders = ",".join("?" for _ in ids)
        hashes = [
            row[0] for row in self._conn.execute(
                f"SELECT DISTINCT content_hash FROM emojis WHERE id IN ({placeholders})",
                tuple(ids)).fetchall() if row[0]
        ]
        for content_hash in hashes:
            for row in self._conn.execute(
                    "SELECT id FROM emojis WHERE content_hash=?", (content_hash,)).fetchall():
                key = str(row[0])
                if key not in seen:
                    seen.add(key)
                    ids.append(row[0])
        return ids

    def known_hashes(self, group_id):
        # Every hash already stored for a group: the stored-file hash AND the
        # original (pre-conversion) source hash. This is the "already imported"
        # index used to skip work before it starts.
        # 某分组已存储的全部哈希：实际存储文件哈希与原始（转换前）源哈希。这是
        # "已导入"索引，用于在工作开始前跳过。
        known = set()
        for row in self._conn.execute(
                "SELECT content_hash, src_hash FROM emojis WHERE group_id=?",
                (group_id,)).fetchall():
            if row[0]:
                known.add(row[0])
            if row[1]:
                known.add(row[1])
        return known

    def _existing_hashes(self, group_id):
        return self.known_hashes(group_id)

    # ---- hash backfill / 哈希回填 ---------------------------------------

    def _backfill_content_hash(self):
        # Fill in hashes for rows that predate the column. Runs on every
        # `get_all_emojis`, so it stays a no-op query when nothing is missing.
        # 为早于该列的行走补齐哈希。每次 `get_all_emojis` 都会运行，因此没有缺失时
        # 它只是一次空查询。
        rows = self._conn.execute(
            "SELECT e.id, e.group_id, e.filename FROM emojis e "
            "WHERE e.filename != '' AND (e.content_hash IS NULL OR e.content_hash = '')"
        ).fetchall()
        if not rows:
            return
        groups = {g["id"]: g for g in self.get_all_groups()}
        for row in rows:
            group = groups.get(row["group_id"])
            if not group:
                continue
            path = os.path.join(self._emojis_dir, group["name"], row["filename"])
            try:
                digest = self._file_md5(path)
            except OSError:
                # File missing: keep the hash empty so the row stays out of the
                # All view instead of colliding with a real hash.
                # 文件缺失：保留空哈希，使该行不出现在"全部"视图，也不会与真实哈希
                # 冲突。
                continue
            self._conn.execute(
                "UPDATE emojis SET content_hash=?,"
                " src_hash=CASE WHEN src_hash='' THEN ? ELSE src_hash END"
                " WHERE id=?",
                (digest, digest, row["id"]),
            )
        self._commit()

    # ---- mutations / 变更 -----------------------------------------------

    def rename_emoji(self, emoji_id, new_name):
        self._conn.execute(
            "UPDATE emojis SET original_name=? WHERE id=?", (new_name, emoji_id))
        self._commit()

    def update_text_content(self, emoji_id, text):
        self._conn.execute(
            "UPDATE emojis SET text_content=?, original_name=? WHERE id=?",
            (text, text_display_name(text), emoji_id))
        self._commit()

    def increment_use_count(self, emoji_id):
        # Bump the usage counter after a successful send or copy /
        # 成功发送或复制后使用次数 +1
        self._conn.execute(
            "UPDATE emojis SET use_count = use_count + 1 WHERE id=?", (emoji_id,))
        self._commit()

    def add_text_emoji(self, group_id, text_content):
        # Returns the new row id, TEXT_DUPLICATE when the same text is already
        # in the group, or TEXT_REJECTED for a wrong group type or empty text.
        # 返回新行 id；同组已有相同文字时返回 TEXT_DUPLICATE；分组类型不符或文字为
        # 空时返回 TEXT_REJECTED。
        group = self.get_group(group_id)
        if not group or group["type"] != schema.TYPE_TEXT:
            return TEXT_REJECTED
        text = (text_content or "").strip()
        if not text:
            return TEXT_REJECTED
        duplicate = self._conn.execute(
            "SELECT id FROM emojis WHERE group_id=? AND text_content=? LIMIT 1",
            (group_id, text)).fetchone()
        if duplicate:
            return TEXT_DUPLICATE
        self._conn.execute(
            "INSERT INTO emojis (group_id, text_content, original_name) VALUES (?,?,?)",
            (group_id, text, text_display_name(text)))
        self._commit()
        return self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def delete_emoji(self, emoji_id):
        # Delete the row and its file. Returns True when a row was removed, so
        # callers can branch on the outcome — the previous implementation
        # returned None unconditionally, which made every success check dead
        # code.
        # 删除行及其文件。删除了行时返回 True，使调用方可以据此分支——此前实现恒返回
        # None，导致所有成功判断都成了死代码。
        row = self._conn.execute(
            "SELECT * FROM emojis WHERE id=?", (emoji_id,)).fetchone()
        if not row:
            return False
        emoji = dict(row)
        self._conn.execute("DELETE FROM emojis WHERE id=?", (emoji_id,))
        self._commit()
        if emoji["filename"]:
            path = self.path_for_group_id(emoji["group_id"], emoji["filename"])
            if path:
                file_ops.remove_quietly(path)
        return True

    def delete_emojis(self, emoji_ids):
        # Delete several rows in one transaction. Returns the number removed.
        # 在一个事务内删除多行。返回删除的行数。
        ids = [int(i) for i in emoji_ids]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        rows = self._conn.execute(
            f"SELECT id, group_id, filename FROM emojis WHERE id IN ({placeholders})",
            tuple(ids)).fetchall()
        if not rows:
            return 0
        with self.transaction() as conn:
            conn.execute(
                f"DELETE FROM emojis WHERE id IN ({placeholders})", tuple(ids))
        for row in rows:
            if not row["filename"]:
                continue
            path = self.path_for_group_id(row["group_id"], row["filename"])
            if path:
                file_ops.remove_quietly(path)
        return len(rows)

    def move_emoji(self, emoji_id, target_group_id):
        # Move a card into another group, renaming the file when the target
        # already holds one of the same name, and resetting the column state so
        # the target's layout logic places it fresh.
        # 把卡片移入另一个分组：目标已有同名文件时改名，并重置列状态，使目标分组的
        # 布局逻辑重新放置它。
        target = self.get_group(target_group_id)
        if not target:
            return False
        emoji = self.get_emoji(emoji_id)
        if not emoji:
            return False
        if emoji["text_content"] and target["type"] != schema.TYPE_TEXT:
            return False
        if emoji["filename"] and target["type"] != schema.TYPE_IMAGE:
            return False

        new_filename = emoji["filename"]
        if emoji["filename"]:
            source_group = self.get_group(emoji["group_id"])
            if source_group:
                source_path = os.path.join(
                    self._emojis_dir, source_group["name"], emoji["filename"])
                target_dir = os.path.join(self._emojis_dir, target["name"])
                os.makedirs(target_dir, exist_ok=True)
                target_path = file_ops.unique_path(target_dir, emoji["filename"])
                if os.path.isfile(source_path):
                    try:
                        import shutil

                        shutil.move(source_path, target_path)
                    except OSError as exc:
                        # The file is locked (a thumbnail decode or playback
                        # teardown still holds it). The reason is recorded so
                        # the UI can tell the user instead of failing silently.
                        # 文件被占用（缩略图解码或播放收尾仍持有它）。记录原因，使
                        # 界面能告知用户而不是静默失败。
                        log.warning("move_emoji: cannot move %s -> %s (%s)",
                                    source_path, target_path, exc)
                        self._last_move_error = "locked"
                        return False
                new_filename = os.path.basename(target_path)
            self._last_move_error = ""

        # Reset the column state: keeping the source group's col_index and
        # sort_order created orphan columns and number gaps in the target.
        # 重置列状态：保留源分组的 col_index 与 sort_order 会在目标分组产生孤列与
        # 列号空洞。
        self._conn.execute(
            "UPDATE emojis SET group_id=?, filename=?, col_index=0, sort_order=0,"
            " user_sorted=0 WHERE id=?",
            (target_group_id, new_filename, emoji_id))
        self._commit()
        if target["type"] == schema.TYPE_TEXT:
            self.compact_text_columns(target_group_id)
        return True

    # ---- bulk conversions / 批量转换 ------------------------------------

    def replace_file(self, emoji_id, new_filename, content_hash, src_hash):
        # Point a row at a new file after an in-place conversion /
        # 就地转换后把某行指向新文件
        self._conn.execute(
            "UPDATE emojis SET filename=?, content_hash=?, src_hash=? WHERE id=?",
            (new_filename, content_hash, src_hash, emoji_id))
        self._commit()

    def delete_emoji_rows(self, emoji_ids):
        # Drop rows without touching their files /
        # 只删除行，不碰其文件
        ids = [int(i) for i in emoji_ids]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self.transaction() as conn:
            cursor = conn.execute(
                f"DELETE FROM emojis WHERE id IN ({placeholders})", tuple(ids))
        return cursor.rowcount


__all__ = [
    "EmojiRepository",
    "OVERSIZED_SEND_DIM",
    "RESULT_DUPLICATE",
    "RESULT_ERROR",
    "RESULT_OK",
    "TEXT_DISPLAY_LENGTH",
    "TEXT_DUPLICATE",
    "TEXT_REJECTED",
    "text_display_name",
]
