"""Portable filesystem helpers used by the data store.

The retry policies here are per-platform by design: a Windows process that holds
a GIF open blocks `unlink` until it lets go, while a POSIX `unlink` of an open
file always succeeds. Rather than sprinkling sleeps everywhere, the policy is a
parameter so the platform layer decides.

数据存储使用的可移植文件系统辅助函数。

这里的重试策略按平台设计：Windows 上持有 GIF 的进程会阻塞 `unlink` 直到释放，
而 POSIX 上删除已打开的文件总是成功。与其到处睡等，不如把策略做成参数，由平台层
决定。
"""
import hashlib
import os
import shutil
import time

# Windows: a thumbnail decode or GIF playback teardown can hold a file for a
# few hundred milliseconds. 5 tries x 0.2 s covers that comfortably.
# Windows：缩略图解码或 GIF 播放收尾可能占用文件数百毫秒。5 次 × 0.2 秒足以覆盖。
WINDOWS_RETRY = (5, 0.2)

# POSIX: `unlink` of an open file succeeds, so a single attempt is enough and
# the sleep would only delay a genuine failure.
# POSIX：删除已打开的文件会成功，因此一次尝试足够，睡等只会拖延真正的失败。
POSIX_RETRY = (1, 0.0)


def retry_policy():
    # (attempts, delay) appropriate for the running system /
    # 适合当前系统的 (尝试次数, 间隔)
    return WINDOWS_RETRY if os.name == "nt" else POSIX_RETRY


def file_md5(path):
    # Chunked MD5 of a file: 1 MiB reads keep memory flat for large stickers.
    # 分块计算文件 MD5：每次读 1MiB，大表情包下内存占用平稳。
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def md5_of_bytes(data):
    return hashlib.md5(data).hexdigest()


def remove_dir_retry(path, tries=None, delay=None):
    # Remove a directory tree, retrying while a transient lock is held. Never
    # raises, so a caller such as "delete group" is not blocked by a lock that
    # is about to be released. Returns True when the directory is gone.
    # 删除目录树，遇到瞬态占用时重试。不抛异常，使"删除分组"之类的调用方不会被
    # 一个即将释放的占用阻塞。目录已消失时返回 True。
    if tries is None or delay is None:
        default_tries, default_delay = retry_policy()
        tries = default_tries if tries is None else tries
        delay = default_delay if delay is None else delay
    for attempt in range(tries):
        try:
            shutil.rmtree(path)
            return True
        except OSError:
            if attempt == tries - 1:
                break
            if delay:
                time.sleep(delay)
    shutil.rmtree(path, ignore_errors=True)
    return not os.path.isdir(path)


def unique_path(directory, filename):
    # Resolve a name collision inside `directory` by appending `_1`, `_2`, ...
    # before the extension. Used when moving a card into a group that already
    # holds a file of the same name — silently overwriting would destroy data.
    # 在 `directory` 内解决重名：在扩展名前追加 `_1`、`_2`…。用于把卡片移入已存在
    # 同名文件的分组——静默覆盖会丢数据。
    candidate = os.path.join(directory, filename)
    if not os.path.exists(candidate):
        return candidate
    base, ext = os.path.splitext(filename)
    index = 1
    while True:
        candidate = os.path.join(directory, f"{base}_{index}{ext}")
        if not os.path.exists(candidate):
            return candidate
        index += 1


def rename_dir(old_dir, new_dir):
    # Rename a directory, degrading gracefully when a file inside is still open.
    #
    # `os.rename` is atomic but fails outright on Windows when any file in the
    # tree is held; `shutil.move` retries through a copy for cross-device moves;
    # a full copy does not need exclusive access at all, so it is the last
    # resort. Returns True on success.
    #
    # 重命名目录，在内部文件仍被占用时优雅降级。
    #
    # `os.rename` 是原子的，但 Windows 上目录树内有文件被占用时直接失败；
    # `shutil.move` 对跨设备移动会退化为复制；整目录复制完全不要求独占访问，
    # 因此作为最后兜底。成功返回 True。
    if not os.path.isdir(old_dir):
        return True
    try:
        os.rename(old_dir, new_dir)
        return True
    except OSError:
        pass
    try:
        shutil.move(old_dir, new_dir)
        return True
    except OSError:
        pass
    try:
        shutil.copytree(old_dir, new_dir, dirs_exist_ok=True)
        shutil.rmtree(old_dir, ignore_errors=True)
        return True
    except OSError:
        return False


def copy_upgrading_gif(src, dst):
    # Copy a file, upgrading a GIF87a header to GIF89a on the way.
    #
    # GIF89a is a strict superset of GIF87a, so rewriting only the 6-byte
    # version header is lossless. Chat applications treat a GIF87a file as a
    # generic attachment, so the upgrade is what makes an old sticker paste as
    # an emoji. Pillow must NOT be used here: it quantises large images and
    # loses most of the pixels.
    # 复制文件，并把 GIF87a 头升级为 GIF89a。
    #
    # GIF89a 是 GIF87a 的严格超集，只改写 6 字节版本头完全无损。聊天软件会把
    # GIF87a 文件当作普通附件，这一升级正是老表情能作为表情包粘贴的原因。这里
    # 绝不能用 Pillow：它会量化大图并丢失大部分像素。
    with open(src, "rb") as source:
        head = source.read(6)
        with open(dst, "wb") as target:
            if head == b"GIF87a":
                target.write(b"GIF89a")
            else:
                target.write(head)
            shutil.copyfileobj(source, target)
    return os.path.isfile(dst) and os.path.getsize(dst) > 0


def copy_file(src, dst):
    # Plain copy preserving the modification time / 保留修改时间的普通复制
    shutil.copy2(src, dst)
    return os.path.isfile(dst) and os.path.getsize(dst) > 0


def remove_quietly(path):
    # Best-effort removal that never raises / 尽力删除，绝不抛异常
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def is_nonempty_file(path):
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


__all__ = [
    "POSIX_RETRY",
    "WINDOWS_RETRY",
    "copy_file",
    "copy_upgrading_gif",
    "file_md5",
    "is_nonempty_file",
    "md5_of_bytes",
    "remove_dir_retry",
    "remove_quietly",
    "rename_dir",
    "retry_policy",
    "unique_path",
]
