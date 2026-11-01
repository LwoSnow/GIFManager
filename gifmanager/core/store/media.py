"""Import and media-maintenance repository: conversion, dedup and batch import.

The dedup rule has to match BOTH hash columns. The same picture may be stored
as a converted GIF or as its raw source depending on the "auto-convert" setting,
so comparing only the stored hash let the same file be imported twice whenever
that setting changed.

导入与媒体维护仓储：转换、查重与批量导入。

查重规则必须同时匹配两个哈希列。同一张图可能因"自动转换"开关被存为转换后的 GIF
或原始文件，只比对存储哈希会导致同一文件在开关变化时被重复导入。
"""
import logging
import os
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor

from gifmanager.core.imaging import signatures
from gifmanager.core import fileops as file_ops
from gifmanager.core.store import schema
from gifmanager.core.store.emojis import (
    RESULT_DUPLICATE,
    RESULT_ERROR,
    RESULT_OK,
)

log = logging.getLogger("GIFManager")

# Prefix for temporary conversion output / 临时转换输出的前缀
TEMP_PREFIX = "gm_conv_"


def _parallel_map(work, items, workers):
    # Run `work` over `items`, using a thread pool only when it can help. The
    # worker functions do pure file I/O; every database write stays on the
    # calling thread, because one sqlite3 connection is not thread safe.
    # 对 `items` 运行 `work`，仅在有益时使用线程池。worker 只做纯文件 I/O；所有
    # 数据库写入都留在调用线程，因为单个 sqlite3 连接不是线程安全的。
    if workers is None or workers <= 1 or len(items) <= 1:
        return [work(item) for item in items]
    with ThreadPoolExecutor(max_workers=int(workers)) as executor:
        return list(executor.map(work, items))


class MediaRepository:
    # Import pipeline plus library-wide conversion.
    # 导入流水线以及全库转换。

    # ---- duplicate pre-filter / 重复预过滤 -------------------------------

    def filter_already_imported(self, group_id, filepaths, hash_out=None):
        # Split `filepaths` into (new_files, skipped) by hashing the SOURCE file
        # and comparing against the group's known hashes.
        #
        # Hashing reads a file once; conversion decodes and re-encodes it, often
        # through a spawned ffmpeg process, and writes a temporary GIF — orders
        # of magnitude more work. This is what makes re-importing a 400-file QQ
        # pack nearly instant.
        #
        # `hash_out` collects {source path: md5} so the batch importer never
        # hashes the same file twice.
        # 通过计算源文件哈希并与该分组的已知哈希比对，把 `filepaths` 分为
        # （新文件, 跳过数）。
        #
        # 哈希只读一次文件；转换要解码、重编码（通常还要启动 ffmpeg 进程）并写入
        # 临时 GIF——开销高几个数量级。这正是重复导入 400 个 QQ 文件几乎瞬时的
        # 原因。
        #
        # `hash_out` 收集 {源路径: md5}，使批量导入不会对同一文件哈希两次。
        known = self.known_hashes(group_id)
        new_files = []
        skipped = 0
        for path in filepaths:
            try:
                digest = self._file_md5(path)
            except OSError:
                # Unreadable now: let the normal path report it /
                # 当前不可读：交给正常路径处理
                new_files.append(path)
                continue
            if hash_out is not None:
                hash_out[path] = digest
            if known and digest in known:
                skipped += 1
            else:
                new_files.append(path)
        return new_files, skipped

    def _temp_gif_path(self):
        return os.path.join(
            tempfile.gettempdir(), f"{TEMP_PREFIX}{uuid.uuid4().hex}.gif")

    def _prepare_store_file(self, src, auto_convert):
        # Decide what to store and under which extension.
        #
        # Returns (path_to_store, extension, temporary_path_or_None). The caller
        # owns the temporary file and must remove it.
        #
        # 决定存什么、以什么扩展名存。
        #
        # 返回 (要存储的路径, 扩展名, 临时路径或 None)。临时文件由调用方负责删除。
        ext = signatures.extension_of(src)
        store_ext = ext or ".gif"
        if auto_convert and self._converter.needs_gif_conversion(src):
            temp = self._temp_gif_path()
            if self._converter.convert_to_gif(src, temp):
                return temp, ".gif", temp
            log.warning("import: convert_to_gif failed for %s, store original", src)
            file_ops.remove_quietly(temp)
            return src, store_ext, None
        if signatures.content_kind(src) == signatures.KIND_GIF:
            store_ext = ".gif"
            # An oversized GIF pastes as a file attachment, so downscale it on
            # import (animation kept). This follows the auto-convert switch:
            # with it off the file is stored as-is and the send path
            # downscales on the fly.
            # 超大 GIF 会被当作文件附件粘贴，因此导入时降采样（保留动画）。此项
            # 跟随"自动转换"开关：关闭时原样入库，发送路径会即时降采样。
            if auto_convert:
                dimensions = self._converter.image_dimensions(src)
                if dimensions and max(dimensions) > signatures.MAX_GIF_DIM:
                    temp = self._temp_gif_path()
                    if self._converter.downscale_gif_if_needed(src, temp):
                        return temp, ".gif", temp
                    log.warning(
                        "import: downscale oversized gif failed for %s (dims=%s),"
                        " store original", src, dimensions)
                    file_ops.remove_quietly(temp)
                elif dimensions is None:
                    log.warning(
                        "import: cannot read dimensions of %s, store original", src)
        return src, store_ext, None

    @staticmethod
    def _find_duplicate(conn, group_id, hashes):
        for content_hash in hashes:
            row = conn.execute(
                "SELECT id, original_name FROM emojis WHERE group_id=? AND "
                "(content_hash=? OR (src_hash != '' AND src_hash=?)) LIMIT 1",
                (group_id, content_hash, content_hash)).fetchone()
            if row:
                return row
        return None

    # ---- single import / 单个导入 ---------------------------------------

    def import_emoji(self, group_id, filepath, auto_convert=True):
        # Import one file. Returns RESULT_OK, RESULT_DUPLICATE or RESULT_ERROR.
        # 导入一个文件。返回 RESULT_OK、RESULT_DUPLICATE 或 RESULT_ERROR。
        group = self.get_group(group_id)
        if not group or group["type"] != schema.TYPE_IMAGE:
            return RESULT_ERROR
        if not signatures.is_importable(filepath):
            return RESULT_ERROR
        try:
            raw_hash = self._file_md5(filepath)
        except OSError:
            raw_hash = ""
        if raw_hash and raw_hash in self.known_hashes(group_id):
            return RESULT_DUPLICATE

        src, store_ext, temp = self._prepare_store_file(filepath, auto_convert)
        group_dir = os.path.join(self._emojis_dir, group["name"])
        os.makedirs(group_dir, exist_ok=True)
        dest = os.path.join(group_dir, f"{uuid.uuid4().hex[:8]}{store_ext}")
        try:
            if store_ext == ".gif":
                self._converter.copy_as_gif(src, dest)
            else:
                file_ops.copy_file(src, dest)
        except OSError:
            # `temp` is None when no temporary conversion file was produced, so
            # it must be checked before removal: passing None to `os.remove`
            # raises TypeError, which would mask the real OSError.
            # 未产生临时转换文件时 `temp` 为 None，因此删除前必须判空——把 None 传给
            # `os.remove` 会抛 TypeError，从而掩盖真正的 OSError。
            if temp:
                file_ops.remove_quietly(temp)
            return RESULT_ERROR
        try:
            content_hash = self._file_md5(dest)
        except OSError:
            file_ops.remove_quietly(dest)
            if temp:
                file_ops.remove_quietly(temp)
            return RESULT_ERROR

        incoming = {content_hash}
        if raw_hash:
            incoming.add(raw_hash)
        if self._find_duplicate(self._conn, group_id, incoming):
            file_ops.remove_quietly(dest)
            if temp:
                file_ops.remove_quietly(temp)
            return RESULT_DUPLICATE

        original_name = os.path.splitext(os.path.basename(filepath))[0]
        # Record the original source hash only when the stored bytes differ from
        # the source (conversion, downscale, or GIF87a->GIF89a upgrade), so the
        # "already imported" index stays complete without false matches.
        # 仅在存储字节与源文件不同（转换、降采样或 GIF87a→GIF89a 升级）时记录原始
        # 源哈希，使"已导入"索引保持完整且不产生误匹配。
        src_hash = raw_hash if (raw_hash and raw_hash != content_hash) else ""
        self._conn.execute(
            "INSERT INTO emojis (group_id, filename, original_name, content_hash,"
            " src_hash) VALUES (?,?,?,?,?)",
            (group_id, os.path.basename(dest), original_name, content_hash, src_hash))
        self._commit()
        if temp:
            file_ops.remove_quietly(temp)
        return RESULT_OK

    # ---- batch import / 批量导入 ----------------------------------------

    def import_emojis_batch(self, group_id, filepaths, workers=None,
                            auto_convert=True, src_hash_map=None):
        # Import many files. Returns (imported, duplicated + pre_skipped).
        #
        # `src_hash_map` supplies {path being imported: md5 of the ORIGINAL
        # source}. Required when the caller already converted the file elsewhere
        # (the >100-file progress path converts into the temp directory first and
        # then imports with auto_convert=False): hashing the temporary GIF as if
        # it were the source records a hash that can never match the user's file,
        # so the "already imported" pre-skip silently stops working for that
        # whole batch.
        #
        # 导入多个文件。返回 (已导入, 重复 + 预跳过)。
        #
        # `src_hash_map` 提供 {正在导入的路径: 原始源文件 md5}。当调用方已在别处
        # 转换过文件时（>100 文件的进度路径先转到临时目录再以 auto_convert=False
        # 导入）必须提供：把临时 GIF 当源文件哈希会记下一个永远匹配不上用户文件的
        # 哈希，整批的"已导入跳过"于是静默失效。
        src_hash_map = src_hash_map or {}
        group = self.get_group(group_id)
        if not group or group["type"] != schema.TYPE_IMAGE:
            return (0, 0)
        valid = [p for p in filepaths if signatures.is_importable(p)]
        if not valid:
            return (0, 0)
        valid, pre_skipped = self.filter_already_imported(group_id, valid)
        if not valid:
            return (0, pre_skipped)

        group_dir = os.path.join(self._emojis_dir, group["name"])
        os.makedirs(group_dir, exist_ok=True)

        def work(src):
            # Worker thread: convert -> copy (upgrading GIF87a) -> hash. No
            # database access happens here.
            # worker 线程：转换 → 复制（升级 GIF87a）→ 哈希。此处不访问数据库。
            store = src
            temp = None
            try:
                if src in src_hash_map:
                    src_hash = src_hash_map[src]
                else:
                    try:
                        src_hash = self._file_md5(src)
                    except OSError:
                        src_hash = ""
                store, store_ext, temp = self._prepare_store_file(src, auto_convert)
                store_ext = store_ext or ".gif"
                dest = os.path.join(
                    group_dir, f"{uuid.uuid4().hex[:8]}{store_ext}")
                try:
                    if store_ext == ".gif":
                        self._converter.copy_as_gif(store, dest)
                    else:
                        file_ops.copy_file(store, dest)
                    digest = self._file_md5(dest)
                except OSError:
                    file_ops.remove_quietly(dest)
                    return None
            finally:
                # Always clean the temporary GIF, even when the copy or the hash
                # failed: a failed copy otherwise leaves gm_conv_*.gif behind.
                # 复制或哈希失败时也清理临时 GIF：否则失败的复制会在临时目录残留
                # gm_conv_*.gif。
                file_ops.remove_quietly(temp)
            recorded = src_hash if (src_hash and src_hash != digest) else ""
            return {
                "dest": dest,
                "hash": digest,
                "src_hash": recorded,
                "original_name": os.path.splitext(os.path.basename(src))[0],
            }

        results = _parallel_map(work, valid, workers)

        # Calling thread: duplicate check and a single transaction for the
        # batch insert.
        # 调用线程：查重，并用单个事务完成批量插入。
        existing = self._existing_hashes(group_id)
        imported = 0
        duplicated = 0
        with self.transaction() as conn:
            for result in results:
                if result is None:
                    continue
                src_hash = result.get("src_hash", "")
                if result["hash"] in existing or (src_hash and src_hash in existing):
                    duplicated += 1
                    file_ops.remove_quietly(result["dest"])
                    continue
                existing.add(result["hash"])
                if src_hash:
                    existing.add(src_hash)
                conn.execute(
                    "INSERT INTO emojis (group_id, filename, original_name,"
                    " content_hash, src_hash) VALUES (?,?,?,?,?)",
                    (group_id, os.path.basename(result["dest"]),
                     result["original_name"], result["hash"], src_hash))
                imported += 1
        # Pre-skipped files count as duplicates so the caller's "skipped" total
        # reflects everything that was filtered.
        # 预跳过的文件同样计入重复数，使调用方的"跳过"统计完整反映被过滤的文件。
        return (imported, duplicated + pre_skipped)

    # ---- library-wide conversion / 全库转换 ------------------------------

    def convert_library_to_gif(self, progress_cb=None, workers=None):
        # Convert every non-GIF image in every group to GIF, and downscale
        # oversized GIFs. On success the original file is deleted and the row is
        # updated (the content hash becomes the GIF hash, the source hash keeps
        # the original). A converted file that duplicates existing content in
        # the same group removes the redundant row instead.
        #
        # Returns (converted, failed, deduped).
        #
        # `progress_cb(index, total, filename)` is invoked between rows, and once
        # more with an empty filename at the end so a progress dialog can settle
        # at 100%.
        #
        # 把每个分组内的非 GIF 图片转为 GIF，并降采样超大 GIF。成功后删除原文件并
        # 更新行（内容哈希变为 GIF 哈希，源哈希保留原值）。转换结果与同组已有内容
        # 重复时删除冗余行。
        #
        # 返回 (已转换, 失败, 去重)。
        #
        # `progress_cb(index, total, filename)` 在行之间调用，最后再以空文件名调用
        # 一次，使进度对话框能停在 100%。
        rows = self._conn.execute(
            "SELECT e.id, e.group_id, e.filename, e.content_hash, e.src_hash,"
            " g.name AS gname FROM emojis e JOIN groups g ON e.group_id=g.id"
            " WHERE g.type='image' AND e.filename != ''").fetchall()

        pending = []
        for row in rows:
            path = os.path.join(self._emojis_dir, row["gname"], row["filename"])
            if signatures.needs_conversion(path):
                pending.append(dict(row))
            elif signatures.content_kind(path) == signatures.KIND_GIF:
                dimensions = self._converter.image_dimensions(path)
                if dimensions and max(dimensions) > signatures.MAX_GIF_DIM:
                    pending.append(dict(row))
        total = len(pending)

        def convert_one(emoji):
            src = os.path.join(self._emojis_dir, emoji["gname"], emoji["filename"])
            dst = os.path.join(
                self._emojis_dir, emoji["gname"], f"{uuid.uuid4().hex[:8]}.gif")
            if signatures.content_kind(src) == signatures.KIND_GIF:
                ok = self._converter.downscale_gif_if_needed(src, dst)
            else:
                ok = self._converter.convert_to_gif(src, dst)
            if not ok:
                log.warning("convert_library: convert/downscale failed for %s", src)
                file_ops.remove_quietly(dst)
                return (emoji, None)
            try:
                digest = self._file_md5(dst)
            except OSError:
                file_ops.remove_quietly(dst)
                return (emoji, None)
            return (emoji, (src, dst, digest))

        results = _parallel_map(convert_one, pending, workers)

        converted = 0
        failed = 0
        deduped = 0
        for index, (emoji, result) in enumerate(results):
            if progress_cb is not None:
                progress_cb(index, total, emoji["filename"])
            if result is None:
                failed += 1
                continue
            src, dst, new_hash = result
            duplicate = self._conn.execute(
                "SELECT id FROM emojis WHERE group_id=? AND content_hash=? AND id!=?",
                (emoji["group_id"], new_hash, emoji["id"])).fetchone()
            file_ops.remove_quietly(src)
            if duplicate:
                file_ops.remove_quietly(dst)
                self._conn.execute("DELETE FROM emojis WHERE id=?", (emoji["id"],))
                deduped += 1
            else:
                self._conn.execute(
                    "UPDATE emojis SET filename=?, content_hash=?, src_hash=?"
                    " WHERE id=?",
                    (os.path.basename(dst), new_hash,
                     emoji["src_hash"] or emoji["content_hash"], emoji["id"]))
                converted += 1
            self._commit()
        if progress_cb is not None and total:
            progress_cb(total, total, "")
        return (converted, failed, deduped)

    # ---- send-copy maintenance / 发送副本维护 ---------------------------

    def is_oversized_gif(self, filepath):
        # True when the file is a GIF whose longer side exceeds MAX_GIF_DIM,
        # i.e. likely to be pasted as a file attachment by a chat application.
        # 文件是 GIF 且较长边超过 MAX_GIF_DIM（聊天软件大概率将其作为文件附件粘贴）
        # 时为 True。
        if not signatures.has_gif_signature(filepath):
            return False
        dimensions = self._converter.image_dimensions(filepath)
        if dimensions is None:
            log.warning("is_oversized_gif: cannot read dimensions of %s", filepath)
            return False
        return max(dimensions) > signatures.MAX_GIF_DIM

    def make_send_copy(self, filepath):
        # Write a downscaled temporary GIF for the clipboard, or None.
        #
        # The caller owns the returned path and must clean it up; the store
        # tracks it in `_pending_send_temps` so `cleanup_send_temps` can drop
        # everything at shutdown.
        #
        # 为剪贴板生成一份降采样的临时 GIF，失败返回 None。
        #
        # 返回的路径由调用方负责清理；存储把它记入 `_pending_send_temps`，使
        # `cleanup_send_temps` 可以在退出时统一清理。
        try:
            handle, temp = tempfile.mkstemp(suffix=".gif", prefix="gm_send_")
            os.close(handle)
        except OSError as exc:
            log.warning("make_send_copy: mkstemp failed -> %s", exc)
            return None
        if not self._converter.downscale_gif_if_needed(filepath, temp):
            log.warning("make_send_copy: downscale failed for %s", filepath)
            file_ops.remove_quietly(temp)
            return None
        self._pending_send_temps.add(temp)
        return temp

    def cleanup_send_temp(self, path):
        self._pending_send_temps.discard(path)
        return file_ops.remove_quietly(path)

    def cleanup_send_temps(self):
        # Remove every tracked send copy; returns the number removed. Called at
        # shutdown, replacing the previous per-file timer so the core layer needs
        # no event loop.
        # 清理所有已记录的发送副本，返回删除数量。退出时调用，替代此前每个文件一个
        # 定时器的做法，使核心层不需要事件循环。
        removed = 0
        for path in list(self._pending_send_temps):
            if self.cleanup_send_temp(path):
                removed += 1
        return removed

    def pending_send_temps(self):
        return set(self._pending_send_temps)


__all__ = ["MediaRepository", "TEMP_PREFIX"]
