"""Data management SQLite & file management
数据管理 SQLite & 文件管理"""
import hashlib
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import uuid
from PySide6.QtCore import QStandardPaths, QMimeData, QUrl
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication

from app.utils import gif_converter

# Valid characters for group names: Chinese and English, numbers, spaces, short lines /
# 分组名合法字符：中英文、数字、空格、短横线
_GROUP_NAME_RE = re.compile(r'^[\w\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\- ]+$')

def _is_valid_group_name(name):
    return bool(_GROUP_NAME_RE.match(name)) and len(name.strip()) <= 32


def _remove_dir_retry(path, tries=5, delay=0.2):
    # Remove a directory with retries: Windows may briefly hold one of its
    # files open (async thumbnail decode / GIF playback teardown). Never
    # raises, so callers (e.g. delete_group) are never blocked by a
    # transient lock. / 带重试地删除目录：Windows 可能短暂占用其中文件
    # （异步缩略图解码 / GIF 播放收尾）。不抛异常，调用方（如 delete_group）
    # 不会被瞬态锁阻塞。
    for i in range(tries):
        try:
            shutil.rmtree(path)
            return True
        except OSError:
            if i == tries - 1:
                try:
                    shutil.rmtree(path, ignore_errors=True)
                except OSError:
                    pass
                return False
            time.sleep(delay)
    return False


def _app_data_dir():
    # Prioritize using the root directory of the project / 优先使用项目根目录下的 data/
    candidates = []
    if getattr(sys, "frozen", False):
        # PyInstaller 打包版：数据写在 exe 同级（便携场景），
        # 安装版（如 Program Files 不可写）自动回退到用户文档目录
        candidates.append(os.path.join(os.path.dirname(sys.executable), "data"))
    else:
        d = os.path.dirname(os.path.abspath(__file__))  # app/models
        d = os.path.dirname(d)  # app
        d = os.path.dirname(d)  # root
        candidates.append(os.path.join(d, "data"))
    candidates.append(
        os.path.join(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation),
            "GIFManager",
        )
    )
    for c in candidates:
        try:
            os.makedirs(c, exist_ok=True)
        except OSError:
            continue  # 无写权限（如安装到 Program Files）则尝试下一个候选
        if os.path.isdir(c):
            return c
    return candidates[-1]


class DataManager:
    def __init__(self):
        self._data_dir = _app_data_dir()
        self._db_path = os.path.join(self._data_dir, "emoji.db")
        self._emojis_dir = os.path.join(self._data_dir, "emojis")
        os.makedirs(self._emojis_dir, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._last_group_error = ""  # last rename_group failure reason / 上次重命名失败原因
        self._init_tables()
        # Speed up GROUP BY content_hash in get_all_emojis for large libraries
        # 为 get_all_emojis 的 GROUP BY content_hash 建索引（大图库提速）
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_emojis_hash ON emojis(content_hash)"
        )

    # Initialization / 初始化

    def _init_tables(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'image',
                sort_order INTEGER NOT NULL DEFAULT 0,
                is_builtin INTEGER NOT NULL DEFAULT 0,
                builtin_role TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            )
        """)
        self._conn.execute("""
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
        """)
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(emojis)")]
        if "content_hash" not in cols:
            self._conn.execute("ALTER TABLE emojis ADD COLUMN content_hash TEXT DEFAULT ''")
        if "src_hash" not in cols:
            # Original (pre-conversion) file hash, kept for dedup compatibility /
            # 转换前原始文件哈希，用于去重兼容
            self._conn.execute("ALTER TABLE emojis ADD COLUMN src_hash TEXT DEFAULT ''")
        if "sort_order" not in cols:
            self._conn.execute(
                "ALTER TABLE emojis ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"
            )
        if "col_index" not in cols:
            self._conn.execute("ALTER TABLE emojis ADD COLUMN col_index INTEGER NOT NULL DEFAULT 0")
        if "user_sorted" not in cols:
            self._conn.execute(
                "ALTER TABLE emojis ADD COLUMN user_sorted INTEGER NOT NULL DEFAULT 0"
            )
            self._conn.execute("UPDATE emojis SET user_sorted=1")
        if "use_count" not in cols:
            self._conn.execute(
                "ALTER TABLE emojis ADD COLUMN use_count INTEGER NOT NULL DEFAULT 0"
            )
        # Builtin groups are identified by an explicit role column ('all' /
        # 'default'), NOT by their sort_order position: the user may drag the
        # builtin default group to another position, and the old
        # sort_order-based lookup then returned None and re-created a
        # duplicate builtin on restart (which merged away the user's rename).
        # 内置分组用显式角色列（'all'/'default'）识别，不依赖 sort_order
        # 位置：用户可拖拽内置默认分组到其他位置，旧版按 sort_order 查找
        # 会返回 None 并在重启时重建重复内置组（进而吞掉用户重命名）。
        gcols = [r[1] for r in self._conn.execute("PRAGMA table_info(groups)")]
        if "builtin_role" not in gcols:
            self._conn.execute("ALTER TABLE groups ADD COLUMN builtin_role TEXT DEFAULT ''")
            self._conn.execute(
                "UPDATE groups SET builtin_role='all' WHERE is_builtin=1 AND sort_order=0")
            self._conn.execute(
                "UPDATE groups SET builtin_role='default' WHERE is_builtin=1 AND sort_order=1")
        self._conn.commit()
        self._ensure_builtin("All", "image", "all")
        self._ensure_builtin("Default Expression", "image", "default")
        self._cleanup_duplicate_builtins()

    def _cleanup_duplicate_builtins(self):
        # An older buggy version matched builtin groups by name, so renaming
        # the default group created duplicate builtin groups. Merge every
        # duplicate per role into the canonical one and re-normalize its
        # columns. / 旧版按名字匹配内置分组，重命名默认分组会产生重复的内置
        # 分组。按角色把重复分组合并到正统分组并重排其列。
        for role in ("all", "default"):
            rows = [dict(r) for r in self._conn.execute(
                "SELECT * FROM groups WHERE builtin_role=?", (role,)).fetchall()]
            if len(rows) <= 1:
                continue
            keep = min(rows, key=lambda g: (g["sort_order"], g["id"]))
            keep_dir = os.path.join(self._emojis_dir, keep["name"])
            for dup in rows:
                if dup["id"] == keep["id"]:
                    continue
                dup_dir = os.path.join(self._emojis_dir, dup["name"])
                for e in self._conn.execute(
                    "SELECT * FROM emojis WHERE group_id=?", (dup["id"],)
                ).fetchall():
                    em = dict(e)
                    # Move the file only when the directories differ / 目录不同才移动文件
                    if em["filename"] and dup_dir != keep_dir:
                        src = os.path.join(dup_dir, em["filename"])
                        dst = os.path.join(keep_dir, em["filename"])
                        if os.path.isfile(src):
                            os.makedirs(keep_dir, exist_ok=True)
                            try:
                                shutil.move(src, dst)
                            except OSError:
                                pass
                    self._conn.execute(
                        "UPDATE emojis SET group_id=? WHERE id=?",
                        (keep["id"], em["id"]),
                    )
                self._conn.execute("DELETE FROM groups WHERE id=?", (dup["id"],))
            self._conn.commit()
            self._renormalize_columns(keep["id"])

    def _renormalize_columns(self, group_id):
        # Re-distribute all cards of a group row-first keeping their relative global order
        # 保持全局相对顺序，将该组所有卡片行优先重新分列
        emojis = self.get_emojis_by_group(group_id)
        if not emojis:
            return
        emojis.sort(key=lambda e: (int(e.get("col_index", 0)), int(e.get("sort_order", 0))))
        col_count = len({int(e.get("col_index", 0)) for e in emojis}) or 1
        self._redistribute([e["id"] for e in emojis], group_id, col_count)

    def _ensure_builtin(self, name, grp_type, role):
        # Create builtin groups only when missing; never force-rename them
        # (users may rename builtin groups freely, keep their choice).
        # Identification is by role, so dragging the default group to another
        # position cannot break the lookup. / 仅在缺失时创建内置分组；不强制
        # 改名（允许用户自由重命名内置分组）。按角色识别，拖拽默认分组到
        # 其他位置不会破坏查找。
        cur = self._conn.execute(
            "SELECT id FROM groups WHERE builtin_role=?", (role,),
        )
        if cur.fetchone() is None:
            self._conn.execute(
                "INSERT INTO groups (name, type, is_builtin, builtin_role)"
                " VALUES (?,?,1,?)",
                (name, grp_type, role)
            )
            self._conn.commit()

    @property
    def data_dir(self):
        return self._data_dir

    # Clustered CRUD / 分组 CRUD

    def _all_group_id(self):
        r = self._conn.execute(
            "SELECT id FROM groups WHERE builtin_role='all' LIMIT 1"
        ).fetchone()
        return r[0] if r else None

    def default_group_id(self):
        # Builtin default group identified by role, so renaming OR dragging it
        # to another position keeps the lookup working / 内置默认分组按角色
        # 识别，重命名或拖拽到其他位置后查找依然有效
        r = self._conn.execute(
            "SELECT id FROM groups WHERE builtin_role='default' LIMIT 1"
        ).fetchone()
        return r[0] if r else None

    def get_all_groups(self):
        all_id = self._all_group_id()
        cur = self._conn.execute("SELECT * FROM groups")
        groups = [dict(r) for r in cur.fetchall()]
        groups.sort(key=lambda g: (g["id"] != all_id, g["sort_order"], g["id"]))
        return groups

    def reorder_group(self, group_id, new_index):
        all_id = self._all_group_id()
        movable = [g["id"] for g in self.get_all_groups() if g["id"] != all_id]
        if group_id not in movable:
            return False
        movable.remove(group_id)
        new_index = max(0, min(new_index, len(movable)))
        movable.insert(new_index, group_id)
        for idx, gid in enumerate(movable):
            # sort_order Starting from 1, leaving 0 for "All" / sort_order 从 1 开始，0 留给"All"
            self._conn.execute(
                "UPDATE groups SET sort_order=? WHERE id=?", (idx + 1, gid)
            )
        self._conn.commit()
        return True

    def get_group(self, group_id):
        cur = self._conn.execute("SELECT * FROM groups WHERE id=?", (group_id,))
        r = cur.fetchone()
        return dict(r) if r else None

    def get_group_by_name(self, name):
        cur = self._conn.execute("SELECT * FROM groups WHERE name=?", (name,))
        r = cur.fetchone()
        return dict(r) if r else None

    def create_group(self, name, grp_type="image"):
        # Duplicate name inspection + security verification / 重名检查 + 安全性校验
        name = name.strip()
        if not _is_valid_group_name(name):
            return None
        if self.get_group_by_name(name):
            return None
        cur = self._conn.execute("SELECT MAX(sort_order) FROM groups")
        max_ord = cur.fetchone()[0] or 0
        self._conn.execute(
            "INSERT INTO groups (name, type, sort_order) VALUES (?,?,?)",
            (name, grp_type, max_ord + 1)
        )
        self._conn.commit()
        if grp_type == "image":
            os.makedirs(os.path.join(self._emojis_dir, name), exist_ok=True)
        return self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def rename_group(self, group_id, new_name):
        old = self.get_group(group_id)
        if not old:
            self._last_group_error = "missing"
            return False
        new_name = new_name.strip()
        # Security verification / 安全性校验
        if not _is_valid_group_name(new_name):
            self._last_group_error = "invalid"
            return False
        # Duplicate name inspection / 重名检查
        existing = self.get_group_by_name(new_name)
        if existing and existing["id"] != group_id:
            self._last_group_error = "duplicate"
            return False
        self._conn.execute("UPDATE groups SET name=? WHERE id=?", (new_name, group_id))
        self._conn.commit()
        old_dir = os.path.join(self._emojis_dir, old["name"])
        new_dir = os.path.join(self._emojis_dir, new_name)
        if old["type"] == "image" and os.path.isdir(old_dir):
            try:
                os.rename(old_dir, new_dir)
            except OSError:
                # Windows occasionally fails with os.rename; fall back to
                # shutil.move before rolling back (Windows 下 os.rename 偶发失败，
                # 回滚前先尝试 shutil.move 兜底迁移)
                try:
                    shutil.move(old_dir, new_dir)
                except OSError:
                    # Last resort: copy the whole folder, then remove the old
                    # one. Copying does not need exclusive access, so it still
                    # works while a file handle is open
                    # 最后兜底：整目录复制后删除旧目录；复制不要求独占访问
                    try:
                        shutil.copytree(old_dir, new_dir, dirs_exist_ok=True)
                        shutil.rmtree(old_dir, ignore_errors=True)
                    except OSError:
                        self._conn.execute(
                            "UPDATE groups SET name=? WHERE id=?",
                            (old["name"], group_id),
                        )
                        self._conn.commit()
                        self._last_group_error = "dir"
                        return False
        self._last_group_error = ""
        return True

    def delete_group(self, group_id):
        old = self.get_group(group_id)
        if not old or old["is_builtin"]:
            return False
        # Delete the emoji pack file (with retries: Windows may briefly
        # hold a GIF open during async thumbnail decode / playback teardown,
        # which used to raise PermissionError and leave the group half-deleted)
        # 删除表情包文件（带重试：Windows 可能在异步缩略图解码 / 播放收尾时
        # 短暂占用 GIF，此前会抛 PermissionError 导致分组删除到一半）
        if old["type"] == "image":
            gdir = os.path.join(self._emojis_dir, old["name"])
            if os.path.isdir(gdir):
                _remove_dir_retry(gdir)
        self._conn.execute("DELETE FROM emojis WHERE group_id=?", (group_id,))
        self._conn.execute("DELETE FROM groups WHERE id=?", (group_id,))
        self._conn.commit()
        return True

    # Emoji CRUD / 表情包 CRUD

    @staticmethod
    def _file_md5(path):  # "All" Remove duplicates / 去重
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def _backfill_content_hash(self):
        rows = self._conn.execute(
            "SELECT e.id, e.group_id, e.filename FROM emojis e "
            "WHERE e.filename != '' AND (e.content_hash IS NULL OR e.content_hash = '')"
        ).fetchall()
        if not rows:
            return
        groups = {g["id"]: g for g in self.get_all_groups()}
        for r in rows:
            g = groups.get(r["group_id"])
            if not g:
                continue
            fp = os.path.join(self._emojis_dir, g["name"], r["filename"])
            try:
                h = self._file_md5(fp)
            except OSError:
                # File is missing, leaving empty hash (does not appear in "All" view) /
                # 文件缺失，保留空哈希（不会出现在"全部"视图）
                continue
            self._conn.execute(
                "UPDATE emojis SET content_hash=?,"
                " src_hash=CASE WHEN src_hash='' THEN ? ELSE src_hash END"
                " WHERE id=?",
                (h, h, r["id"])
            )
        self._conn.commit()

    @staticmethod
    def _escape_like(kw):  # Wildcard escaping / 通配符转义
        return kw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def get_all_emojis(self, keyword=""):
        self._backfill_content_hash()
        where = "g.type='image' AND e.filename != '' AND e.content_hash != ''"
        args = []
        if keyword:
            kw = self._escape_like(keyword)
            where += " AND e.original_name LIKE ? ESCAPE '\\'"
            args.append(f"%{kw}%")
        cur = self._conn.execute(
            "SELECT e.* FROM emojis e JOIN groups g ON e.group_id=g.id "
            f"WHERE {where} "
            "GROUP BY e.content_hash "
            "ORDER BY MAX(e.sort_order), MAX(e.created_at) DESC",
            args,
        )
        return [dict(r) for r in cur.fetchall()]

    def get_emojis_by_group(self, group_id, keyword=""):
        if keyword:
            kw = self._escape_like(keyword)
            cur = self._conn.execute(
                "SELECT * FROM emojis WHERE group_id=? "
                "AND (original_name LIKE ? ESCAPE '\\' OR text_content LIKE ? ESCAPE '\\') "
                "ORDER BY sort_order, id",
                (group_id, f"%{kw}%", f"%{kw}%")
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM emojis WHERE group_id=? ORDER BY sort_order, id",
                (group_id,)
            )
        return [dict(r) for r in cur.fetchall()]

    def reorder_emoji(self, emoji_id, group_id, new_index):
        emojis = self.get_emojis_by_group(group_id)
        ids = [e["id"] for e in emojis]
        if emoji_id not in ids:
            return False
        ids.remove(emoji_id)
        new_index = max(0, min(new_index, len(ids)))
        ids.insert(new_index, emoji_id)
        for idx, eid in enumerate(ids):
            self._conn.execute(
                "UPDATE emojis SET sort_order=? WHERE id=?", (idx, eid)
            )
        self._conn.commit()
        return True

    def count_all_emojis(self):
        return self._conn.execute("SELECT COUNT(*) FROM emojis").fetchone()[0]

    # image Total number of grouped expression records / image 分组表情总数记录
    def count_image_emojis(self):
        return self._conn.execute(
            "SELECT COUNT(*) FROM emojis e JOIN groups g ON e.group_id=g.id "
            "WHERE g.type='image'"
        ).fetchone()[0]

    def count_emojis_in_group(self, group_id):
        return self._conn.execute(
            "SELECT COUNT(*) FROM emojis WHERE group_id=?",
            (group_id,),
        ).fetchone()[0]

    def import_emoji(self, group_id, filepath, auto_convert=True):
        group = self.get_group(group_id)
        if not group or group["type"] != "image":
            return "error"

        ext = os.path.splitext(filepath)[1].lower()
        if ext not in gif_converter.IMPORT_EXTS:
            return "error"
        # Convert non-gif images to gif first (keeps size/ratio unchanged) /
        # 先把非 gif 图片转为 gif（尺寸比例不变）
        src_hash = ""
        src = filepath
        if auto_convert and gif_converter.needs_conversion(filepath):
            src_hash = self._file_md5(filepath)
            tmp_gif = os.path.join(
                tempfile.gettempdir(), f"gm_conv_{uuid.uuid4().hex}.gif")
            if gif_converter.convert_to_gif(filepath, tmp_gif):
                src = tmp_gif
        # Calculate the stored-file hash for dedup: after conversion the gif
        # hash matches other gifs of the same picture, so png and gif of the
        # same image de-duplicate each other.
        # 以实际存储文件哈希查重：转换后 gif 哈希与同图其他 gif 一致，
        # 因此同一张图的 png 与 gif 可以互相去重。
        try:
            content_hash = self._file_md5(src)
        except OSError:
            return "error"
        dup = self._conn.execute(
            "SELECT id, original_name FROM emojis "
            "WHERE content_hash=? AND group_id=? LIMIT 1",
            (content_hash, group_id),
        ).fetchone()
        if dup:
            if src != filepath:
                try:
                    os.remove(src)  # clean temp gif / 清理临时 gif
                except OSError:
                    pass
            return "duplicate"

        gdir = os.path.join(self._emojis_dir, group["name"])
        os.makedirs(gdir, exist_ok=True)

        unique_id = uuid.uuid4().hex[:8]
        store_ext = os.path.splitext(src)[1].lower() or ".gif"
        new_name = f"{unique_id}{store_ext}"
        dest = os.path.join(gdir, new_name)
        shutil.copy2(src, dest)

        original_name = os.path.splitext(os.path.basename(filepath))[0]
        self._conn.execute(
            "INSERT INTO emojis (group_id, filename, original_name, content_hash, src_hash)"
            " VALUES (?,?,?,?,?)",
            (group_id, new_name, original_name, content_hash, src_hash)
        )
        self._conn.commit()
        if src != filepath:
            try:
                os.remove(src)  # remove temp gif / 删除临时 gif
            except OSError:
                pass
        return "ok"

    def import_emojis_batch(self, group_id, filepaths, workers=None, auto_convert=True):
        # Multi-threaded import / 多线程导入
        group = self.get_group(group_id)
        if not group or group["type"] != "image":
            return (0, 0)
        valid = [p for p in filepaths
                 if os.path.splitext(p)[1].lower() in gif_converter.IMPORT_EXTS]
        if not valid:
            return (0, 0)
        gdir = os.path.join(self._emojis_dir, group["name"])
        os.makedirs(gdir, exist_ok=True)

        def work(src):
            # worker Thread: convert -> hash -> copy to target (uuid named)
            # worker 线程：转换 → 哈希 → 复制到目标（uuid 命名）
            try:
                src_hash = ""
                store = src
                if auto_convert and gif_converter.needs_conversion(src):
                    src_hash = self._file_md5(src)
                    tmp_gif = os.path.join(
                        tempfile.gettempdir(), f"gm_conv_{uuid.uuid4().hex}.gif")
                    if gif_converter.convert_to_gif(src, tmp_gif):
                        store = tmp_gif
                h = self._file_md5(store)
                store_ext = os.path.splitext(store)[1].lower() or ".gif"
                dest = os.path.join(gdir, f"{uuid.uuid4().hex[:8]}{store_ext}")
                shutil.copy2(store, dest)
                if store != src:
                    try:
                        os.remove(store)  # remove temp gif / 删除临时 gif
                    except OSError:
                        pass
            except OSError:
                return None
            return {"dest": dest, "hash": h, "src_hash": src_hash,
                    "original_name": os.path.splitext(os.path.basename(src))[0]}

        if workers is None or workers <= 1 or len(valid) <= 1:
            results = [work(p) for p in valid]
        else:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=workers) as ex:
                results = list(ex.map(work, valid))

        # Main thread: duplicate check + single transaction batch INSERT
        # 主线程：查重 + 单事务批量 INSERT
        imported = 0
        duplicated = 0
        existing = set(
            r[0] for r in self._conn.execute(
                "SELECT content_hash FROM emojis WHERE group_id=? AND content_hash != ''",
                (group_id,),
            ).fetchall()
        )
        self._conn.execute("BEGIN")
        try:
            for r in results:
                if r is None:
                    continue
                if r["hash"] in existing:
                    duplicated += 1
                    try:
                        os.remove(r["dest"])
                    except OSError:
                        pass
                    continue
                existing.add(r["hash"])
                self._conn.execute(
                    "INSERT INTO emojis (group_id, filename, original_name,"
                    " content_hash, src_hash)"
                    " VALUES (?,?,?,?,?)",
                    (group_id, os.path.basename(r["dest"]), r["original_name"],
                     r["hash"], r.get("src_hash", "")),
                )
                imported += 1
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return (imported, duplicated)

    # Convert every non-gif image in all groups to gif. On success the
    # original file is deleted and the DB record is updated (content_hash
    # becomes the gif hash, src_hash keeps the original hash). If the
    # converted gif already exists in the same group the redundant record is
    # removed. Returns (converted, failed, deduped).
    # 把所有分组内非 gif 图片转为 gif：成功后删除原文件并更新记录
    # （content_hash 变为 gif 哈希，src_hash 保留原始哈希）。同组已有相同
    # 内容的 gif 时删除冗余记录。返回 (converted, failed, deduped)。
    def convert_library_to_gif(self, progress_cb=None, workers=None):
        rows = self._conn.execute(
            "SELECT e.id, e.group_id, e.filename, e.content_hash, e.src_hash,"
            " g.name AS gname FROM emojis e JOIN groups g ON e.group_id=g.id"
            " WHERE g.type='image' AND e.filename != ''"
        ).fetchall()
        pending = [dict(r) for r in rows
                   if gif_converter.needs_conversion(os.path.join(
                       self._emojis_dir, r["gname"], r["filename"]))]
        total = len(pending)

        # Convert in worker threads (ffmpeg/Pillow are pure file IO); the DB
        # writes stay on the main thread because the sqlite3 connection is
        # not thread-safe. Returns (em, (src, dst, new_hash)) or (em, None).
        # 转换在 worker 线程执行（ffmpeg/Pillow 是纯文件 IO）；数据库写入
        # 留在主线程（sqlite3 连接非线程安全）。返回 (em, (src, dst, hash))
        # 或 (em, None)。
        def convert_one(em):
            src = os.path.join(self._emojis_dir, em["gname"], em["filename"])
            dst = os.path.join(self._emojis_dir, em["gname"],
                               f"{uuid.uuid4().hex[:8]}.gif")
            if not gif_converter.convert_to_gif(src, dst):
                return (em, None)
            try:
                h = self._file_md5(dst)
            except OSError:
                try:
                    os.remove(dst)
                except OSError:
                    pass
                return (em, None)
            return (em, (src, dst, h))

        if workers is None or workers <= 1 or len(pending) <= 1:
            results = [convert_one(em) for em in pending]
        else:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=workers) as ex:
                results = list(ex.map(convert_one, pending))

        converted = 0
        failed = 0
        deduped = 0
        for i, (em, r) in enumerate(results):
            if progress_cb is not None:
                progress_cb(i, total, em["filename"])
            if r is None:
                failed += 1
                continue
            src, dst, new_hash = r
            # Same content already in this group -> drop the redundant record /
            # 同组已有相同内容 → 删除冗余记录
            dup = self._conn.execute(
                "SELECT id FROM emojis WHERE group_id=? AND content_hash=? AND id!=?",
                (em["group_id"], new_hash, em["id"]),
            ).fetchone()
            try:
                os.remove(src)
            except OSError:
                pass
            if dup:
                try:
                    os.remove(dst)
                except OSError:
                    pass
                self._conn.execute(
                    "DELETE FROM emojis WHERE id=?", (em["id"],))
                deduped += 1
            else:
                old_hash = em["content_hash"]
                self._conn.execute(
                    "UPDATE emojis SET filename=?, content_hash=?, src_hash=?"
                    " WHERE id=?",
                    (os.path.basename(dst), new_hash,
                     em["src_hash"] or old_hash, em["id"]),
                )
                converted += 1
            self._conn.commit()
        if progress_cb is not None and total:
            progress_cb(total, total, "")
        return (converted, failed, deduped)

    def add_text_emoji(self, group_id, text_content):
        group = self.get_group(group_id)
        if not group or group["type"] != "text":
            return -1
        text = text_content.strip()
        if not text:
            return -1
        # Duplicate checking in the same group: the same text is not saved repeatedly
        # 同组查重：相同文字不重复保存
        dup = self._conn.execute(
            "SELECT id FROM emojis WHERE group_id=? AND text_content=? LIMIT 1",
            (group_id, text),
        ).fetchone()
        if dup:
            return 0
        display = text[:20] + ("..." if len(text) > 20 else "")
        self._conn.execute(
            "INSERT INTO emojis (group_id, text_content, original_name) VALUES (?,?,?)",
            (group_id, text, display)
        )
        self._conn.commit()
        return self._conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def delete_emoji(self, emoji_id):
        cur = self._conn.execute("SELECT * FROM emojis WHERE id=?", (emoji_id,))
        row = cur.fetchone()
        if row:
            em = dict(row)
            self._conn.execute("DELETE FROM emojis WHERE id=?", (emoji_id,))
            self._conn.commit()
            if em["filename"]:
                group = self.get_group(em["group_id"])
                if group:
                    fp = os.path.join(self._emojis_dir, group["name"], em["filename"])
                    if os.path.isfile(fp):
                        try:
                            os.remove(fp)
                        except OSError:
                            pass

    def get_emoji_copies(self, emoji):
        if not emoji.get("content_hash"):
            return [emoji]
        cur = self._conn.execute(
            "SELECT e.*, g.name AS group_name FROM emojis e "
            "JOIN groups g ON e.group_id=g.id "
            "WHERE e.content_hash=? AND e.filename != '' "
            "ORDER BY e.sort_order, e.id",
            (emoji["content_hash"],)
        )
        return [dict(r) for r in cur.fetchall()]

    def rename_emoji(self, emoji_id, new_name):
        self._conn.execute("UPDATE emojis SET original_name=? WHERE id=?", (new_name, emoji_id))
        self._conn.commit()

    def update_text_content(self, emoji_id, text):
        display = text[:20] + ("..." if len(text) > 20 else "")
        self._conn.execute(
            "UPDATE emojis SET text_content=?, original_name=? WHERE id=?",
            (text, display, emoji_id),
        )
        self._conn.commit()

    def move_emoji(self, emoji_id, target_group_id):
        target = self.get_group(target_group_id)
        if not target:
            return False
        cur = self._conn.execute("SELECT * FROM emojis WHERE id=?", (emoji_id,))
        row = cur.fetchone()
        if not row:
            return False
        em = dict(row)
        if em["text_content"] and target["type"] != "text":
            return False
        if em["filename"] and target["type"] != "image":
            return False
        if em["filename"]:
            src_group = self.get_group(em["group_id"])
            if src_group:
                src_path = os.path.join(self._emojis_dir, src_group["name"], em["filename"])
                dst_dir = os.path.join(self._emojis_dir, target["name"])
                os.makedirs(dst_dir, exist_ok=True)
                dst_path = os.path.join(dst_dir, em["filename"])
                if os.path.isfile(src_path):
                    shutil.move(src_path, dst_path)
        # Reset the column state: the moved card must not keep the source
        # group's col_index/sort_order (that created orphan columns / number
        # gaps in the target group). Mark it unassigned so the target group's
        # assign_unassigned_columns / _redistribute places it fresh.
        # 重置列状态：被移动的卡不得保留源组的 col_index/sort_order
        # （否则目标组会出现孤列/列号空洞）。标记为未分配，由目标组的
        # assign_unassigned_columns / _redistribute 重新分配。
        self._conn.execute(
            "UPDATE emojis SET group_id=?, col_index=0, sort_order=0,"
            " user_sorted=0 WHERE id=?",
            (target_group_id, emoji_id),
        )
        self._conn.commit()
        # Text groups: compact column numbers so no hole remains / 文字分组：
        # 压缩列号，避免空洞
        if target["type"] == "text":
            self.compact_text_columns(target_group_id)
        return True

    # Text Grouping: Stable Column Containers / 文字分组：稳定单列排序

    def set_emoji_column(self, emoji_id, target_col, target_order):
        cur = self._conn.execute("SELECT group_id FROM emojis WHERE id=?", (emoji_id,))
        row = cur.fetchone()
        if not row:
            return False
        group_id = row[0]
        existing = self._conn.execute(
            "SELECT id FROM emojis WHERE group_id=? AND col_index=? AND id!=? "
            "AND user_sorted=1 ORDER BY sort_order",
            (group_id, target_col, emoji_id),
        ).fetchall()
        ids = [r[0] for r in existing]
        target_order = max(0, min(target_order, len(ids)))
        ids.insert(target_order, emoji_id)
        for idx, eid in enumerate(ids):
            self._conn.execute(
                "UPDATE emojis SET col_index=?, sort_order=?, user_sorted=1 WHERE id=?",
                (target_col, idx, eid),
            )
        self._conn.commit()
        return True

    def swap_emoji_columns(self, emoji_a, emoji_b):
        # Swap the column/order of two cards (drag onto the middle of a card).
        # Returns True on success / 交换两张卡片的列与列内位置（拖到卡片中间时）。成功返回 True
        rows = self._conn.execute(
            "SELECT id, group_id, col_index, sort_order FROM emojis WHERE id IN (?,?)",
            (emoji_a, emoji_b),
        ).fetchall()
        if len(rows) != 2:
            return False
        info = {r[0]: {"group": r[1], "col": r[2], "order": r[3]} for r in rows}
        if info[emoji_a]["group"] != info[emoji_b]["group"]:
            return False
        a, b = info[emoji_a], info[emoji_b]
        self._conn.execute(
            "UPDATE emojis SET col_index=?, sort_order=?, user_sorted=1 WHERE id=?",
            (b["col"], b["order"], emoji_a),
        )
        self._conn.execute(
            "UPDATE emojis SET col_index=?, sort_order=?, user_sorted=1 WHERE id=?",
            (a["col"], a["order"], emoji_b),
        )
        self._conn.commit()
        return True

    def assign_unassigned_columns(self, group_id, usable_w, spacing, width_of):
        # Batch column allocation: Cards with user_sorted=0 in the group (newly
        # imported old data) are allocated one by one according to the column container rules
        # (open new columns if they can be opened, otherwise the cards are placed in the
        # minimum number of columns), and are written in a single transaction.
        # width_of: Callback for the natural width of the card (pictures have a fixed
        # width and text has a natural width). Returns the number of allocated cards.
        # 批量摊列：组内 user_sorted=0 的卡片（新导入/旧数据）按列容器规则逐张分配（能开新列则开，否则放卡片最少列），单事务写入。
        # width_of: 卡片自然宽回调（图片固定宽 / 文字自然宽）。返回分配卡片数。
        emojis = self.get_emojis_by_group(group_id)
        unsorted = [e for e in emojis if not e.get("user_sorted")]
        if not unsorted:
            return 0
        cols = {}
        for e in emojis:
            if e.get("user_sorted"):
                cols.setdefault(int(e["col_index"]), []).append(e)
        for em in unsorted:
            new_w = min(max(width_of(em), 80), usable_w)
            col_widths = {}
            counts = {}
            for ci, lst in cols.items():
                col_widths[ci] = max(width_of(x) for x in lst)
                counts[ci] = len(lst)
            total = sum(col_widths.values()) + spacing * max(0, len(col_widths) - 1)
            if not cols or total + spacing + new_w <= usable_w:
                ncol = max(cols) + 1 if cols else 0
                cols.setdefault(ncol, []).append(em)
            else:
                mc = min(counts, key=counts.get)
                cols[mc].append(em)
        self._conn.execute("BEGIN")
        try:
            for ci, lst in cols.items():
                for idx, e in enumerate(lst):
                    self._conn.execute(
                        "UPDATE emojis SET col_index=?, sort_order=?, user_sorted=1 WHERE id=?",
                        (ci, idx, e["id"]),
                    )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return len(unsorted)

    def rearrange_columns(self, group_id, col_count):
        # One-click sorting redistributes columns evenly in global order (col_index, sort_order),
        # rows are filled first (card i → column i%K, intra-column order iK), and
        # single transaction writes
        # 一键整理按全局顺序（col_index, sort_order）重新均匀分配列，行优先填充（卡 i → 列 i%K，列内序 i//K），单事务写入
        emojis = self.get_emojis_by_group(group_id)
        if not emojis:
            return 0
        ordered = [e["id"] for e in emojis]
        return self._redistribute(ordered, group_id, col_count)

    def sort_group_emojis(self, group_id, by="name", desc=False):
        # Sort all cards in the group by name / created time and re-distribute columns
        # (row-first fill). Returns the number of sorted cards.
        # 按名称 / 加入时间排序组内所有卡片并重新分配列（行优先填充）。返回排序卡片数。
        emojis = self.get_emojis_by_group(group_id)
        if not emojis:
            return 0
        if by == "time":
            # created_at has second precision; tie-break by id (insert order)
            # created_at 秒级精度，同秒用 id（插入顺序）区分
            emojis.sort(
                key=lambda e: (e.get("created_at", ""), e["id"]),
                reverse=desc,
            )
        elif by == "freq":
            # Usage frequency: ascending = least used first, descending = most used first
            # 使用频率：升序 = 低频在前，逆序 = 高频在前
            emojis.sort(key=lambda e: e.get("use_count", 0), reverse=desc)
        else:
            # Name sort: case-insensitive, empty names go last / 名称排序：忽略大小写，空名排后
            emojis.sort(
                key=lambda e: (e.get("original_name", "") or "").lower(),
                reverse=desc,
            )
        # Keep the current column count so the sort is a one-time action / 保留当前列数（单次整理）
        col_count = len({int(e.get("col_index", 0)) for e in emojis}) or 1
        return self._redistribute([e["id"] for e in emojis], group_id, col_count)

    def prepend_emojis(self, group_id, new_ids):
        # Place the newly added cards at the top-left corner: prepend them (in insert order) to
        # the global order and re-distribute columns row-first, so existing cards shift back.
        # Returns the number of cards re-distributed.
        # 将本次新增的卡片放到左上角：新卡（按加入顺序）插到全局顺序最前并重新行优先分列，
        # 旧卡整体后移。返回重分配卡片数。
        emojis = self.get_emojis_by_group(group_id)
        if not emojis:
            return 0
        # Existing order / 现有全局顺序（列主序即视觉顺序）
        emojis.sort(key=lambda e: (int(e.get("col_index", 0)), int(e.get("sort_order", 0))))
        old_ids = [e["id"] for e in emojis if e["id"] not in new_ids]
        ordered = list(new_ids) + old_ids
        col_count = len({int(e.get("col_index", 0)) for e in emojis}) or 1
        return self._redistribute(ordered, group_id, col_count)

    def prepend_latest_imports(self, group_id, count):
        # Prepend the `count` most recently imported cards to the top-left corner (newest batch
        # from a single import). Insert order = ascending id (earliest first).
        # 将最近导入的 count 张卡片放到左上角（单次批量导入的最新一批）。顺序按 id 升序（先导入的在前）。
        if count <= 0:
            return 0
        emojis = self.get_emojis_by_group(group_id)
        if not emojis:
            return 0
        emojis.sort(key=lambda e: e["id"], reverse=True)  # Newest first / 最新在前
        new_ids = [e["id"] for e in emojis[:count]]
        new_ids.reverse()  # Insert order: earliest first / 按加入顺序：先导入的在前
        return self.prepend_emojis(group_id, new_ids)

    def _redistribute(self, ordered_ids, group_id, col_count):
        # Row-first redistribution: card i → column i%K, intra-column order i//K
        # 行优先重分配：卡 i → 列 i%K，列内序 i//K
        k = max(1, int(col_count))
        cols = [[] for _ in range(k)]
        for i, eid in enumerate(ordered_ids):
            cols[i % k].append(eid)
        self._conn.execute("BEGIN")
        try:
            for ci, lst in enumerate(cols):
                for idx, eid in enumerate(lst):
                    self._conn.execute(
                        "UPDATE emojis SET col_index=?, sort_order=?, user_sorted=1 WHERE id=?",
                        (ci, idx, eid),
                    )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return len(ordered_ids)

    def merge_columns_into(self, group_id, source_cols, target_cols):
        emojis = self.get_emojis_by_group(group_id)
        cols = {}
        for e in emojis:
            cols.setdefault(int(e["col_index"]), []).append(e)
        for lst in cols.values():
            lst.sort(key=lambda e: e["sort_order"])
        pending = []
        for ci in source_cols:
            pending.extend(cols.pop(ci, []))
        if not pending or not cols:
            return 0
        # Distribute the pending cards across the target columns, always
        # into the currently shortest one, so merged columns stay balanced
        # (target_cols is the caller's list of columns that fit; it was
        # previously ignored) / 把待并入的卡片分配到 target_cols 中当前最短
        # 的列，保持并入后各列均衡（target_cols 是调用方指定的"能完整显示"
        # 的列，此前被忽略）
        targets = [t for t in target_cols if t in cols] or list(cols.keys())
        for e in pending:
            t = min(targets, key=lambda ci: len(cols[ci]))
            cols[t].append(e)
        self._conn.execute("BEGIN")
        try:
            for ci, lst in cols.items():
                for idx, e in enumerate(lst):
                    self._conn.execute(
                        "UPDATE emojis SET col_index=?, sort_order=?, user_sorted=1 WHERE id=?",
                        (ci, idx, e["id"]),
                    )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return len(pending)

    def text_max_col(self, group_id):
        r = self._conn.execute(
            "SELECT MAX(col_index) FROM emojis WHERE group_id=?", (group_id,)
        ).fetchone()
        return r[0] if r and r[0] is not None else -1

    def text_col_sizes(self, group_id):
        rows = self._conn.execute(
            "SELECT col_index, COUNT(*) FROM emojis WHERE group_id=? "
            "GROUP BY col_index",
            (group_id,),
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def compact_text_columns(self, group_id):
        rows = self._conn.execute(
            "SELECT col_index FROM emojis WHERE group_id=? "
            "GROUP BY col_index ORDER BY col_index",
            (group_id,),
        ).fetchall()
        for new, (old,) in enumerate(rows):
            if old != new:
                self._conn.execute(
                    "UPDATE emojis SET col_index=? WHERE group_id=? AND col_index=?",
                    (new, group_id, old),
                )
        self._conn.commit()

    # Emoji package file path / 表情包文件路径

    def emoji_filepath(self, emoji):
        if not emoji.get("filename"):
            return None
        group = self.get_group(emoji["group_id"])
        if not group:
            return None
        return os.path.join(self._emojis_dir, group["name"], emoji["filename"])

    def increment_use_count(self, emoji_id):
        # Bump the usage counter when an emoji is sent/copied / 发送/复制表情包时使用次数 +1
        self._conn.execute(
            "UPDATE emojis SET use_count = use_count + 1 WHERE id=?", (emoji_id,)
        )
        self._conn.commit()

    # Clipboard / 剪贴板

    def copy_to_clipboard(self, emoji, mode=0):
        clipboard = QApplication.clipboard()

        if emoji.get("text_content"):
            clipboard.setText(emoji["text_content"])
            return True

        filepath = self.emoji_filepath(emoji)
        if not filepath or not os.path.isfile(filepath):
            return False

        if mode == 0:
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(filepath)])
            clipboard.setMimeData(mime)
        else:
            # GIF must keep animation: QImage decodes only the first frame,
            # so put the raw bytes into image/gif mime for WeChat/QQ to
            # recognize it as an animated image. Also attach the file URL
            # for extra compatibility.
            # GIF 需保留动画：QImage 只解码首帧，故将原始字节放入 image/gif
            # mime，供微信/QQ 识别为动图；同时附带文件路径增强兼容。
            is_gif = False
            try:
                with open(filepath, "rb") as f:
                    is_gif = f.read(4) == b"GIF8"
            except OSError:
                pass
            if is_gif:
                mime = QMimeData()
                try:
                    with open(filepath, "rb") as f:
                        mime.setData("image/gif", f.read())
                except OSError:
                    return False
                mime.setUrls([QUrl.fromLocalFile(filepath)])
                clipboard.setMimeData(mime)
            else:
                img = QImage(filepath)
                if img.isNull():
                    return False
                clipboard.setImage(img)

        return True

