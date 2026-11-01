"""Importing files and folders into a group, with progress and cancellation.

The store already does the work — it filters, converts, copies and de-duplicates, and
`import_emojis_batch` does the whole batch in one transaction. What was missing was
the layer between "the user picked some files" and "the store has them": collecting
paths, refusing a target that cannot hold images, keeping the interface responsive
during a large batch, and reporting what happened.

# Why this runs in CHUNKS on the GUI thread, not on a worker thread

The first version used a `QThread`. It failed immediately and completely:

    sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in
    that same thread.

`DataStore` holds ONE connection, created on the thread that opened it. Python's
sqlite3 refuses to use a connection from another thread, and that is not a setting to
relax: the connection is shared, so two threads using it would interleave statements
on one cursor. Giving each thread its own connection would mean the main thread's
in-flight queries and the worker's writes could not see each other's uncommitted
work, and the interface would show a library that is missing rows the user just
imported.

So the batch is processed in SMALL CHUNKS, one chunk per event-loop turn. The
database work stays on the owning thread; the interface keeps breathing between
chunks. For an import this is the right trade in both directions: the expensive part
is decoding and re-encoding images, which the store already parallelises internally
across its own pool, and the database statements are trivial by comparison.

# Cancellation

Cancellation is checked between chunks, so it stops within one chunk rather than
immediately. That is the honest limit: a conversion already inside the store cannot be
interrupted without leaving a half-written file behind.

存储层已经把活干完了——它负责过滤、转换、复制与去重，而 `import_emojis_batch` 在一个事务
里完成整批。缺的是"用户选了一些文件"与"存储层拥有了它们"之间那一层：收集路径、拒绝无法容纳
图片的目标、在大批量期间保持界面响应，以及报告结果。

# 为什么这里在 GUI 线程上"分块"运行，而不是放在工作线程

第一版用了 `QThread`。它立刻且彻底地失败了：

    sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in
    that same thread.

`DataStore` 持有"一个"连接，创建于打开它的那个线程。Python 的 sqlite3 拒绝从另一个线程
使用该连接，而且这不是一个可以放宽的设置：连接是共享的，两个线程使用它会在同一个游标上交错
执行语句。给每个线程各自一个连接，则主线程正在进行的查询与 worker 的写入彼此看不到对方未
提交的工作，界面会显示一个缺少用户刚导入行的图库。

因此批量以"小块"处理，每个事件循环轮次处理一块。数据库工作留在持有它的线程上；界面在块与块
之间保持呼吸。对导入而言这在两个方向上都是正确的取舍：昂贵部分是图片解码与重编码，而存储层
已经在它自己的池里做了并行；相比之下数据库语句微不足道。

# 取消

取消在块之间检查，因此它会在一个块之内停下，而不是立即停下。这是如实的限制：已经进入存储层的
转换若被打断会留下半写入的文件。
"""
import logging
import os
from collections import deque

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot

from gifmanager.core.imaging import signatures
from gifmanager.core.store import media as media_store

log = logging.getLogger("GIFManager")

# Files per chunk. Small enough that the interface stays responsive on a slow disk,
# large enough that the per-chunk overhead is not the dominant cost.
# 每块的文件数。小到在慢速磁盘上界面仍可响应，大到每块开销不占主导。
CHUNK_SIZE = 4

# The interval between chunks, in milliseconds. Zero would starve the event loop's
# other timers on a fast import; a whole frame keeps painting smooth.
# 块与块之间的间隔（毫秒）。零会在快速导入时饿死事件循环的其他定时器；一整帧则让绘制保持
# 流畅。
CHUNK_INTERVAL_MS = 0


# Extensions offered by the file picker. Built from the signature table so the dialog
# cannot offer a format the importer would then reject.
# 文件选择器提供的扩展名。由签名表构建，使对话框不会提供一个导入器随后会拒绝的格式。
def importable_extensions():
    return sorted(name.lstrip(".").lower() for name in signatures.IMPORT_EXTS)


def file_dialog_filter():
    # A Qt file-dialog filter string: "Images (*.gif *.png);;All files (*)".
    #
    # Derived from the same table as the importer, so a format added to the
    # signatures is offered automatically and a removed one stops appearing.
    # Qt 文件对话框过滤字符串："Images (*.gif *.png);;All files (*)"。
    #
    # 与导入器来自同一张表，因此加入签名表的格式会自动出现，被移除的则不再出现。
    patterns = " ".join(f"*.{ext}" for ext in importable_extensions())
    return f"Images ({patterns});;All files (*)"


def collect_paths(paths, recursive=True):
    # Expand the user's selection into a list of files.
    #
    # A directory selection means "everything importable inside it". Directories are
    # walked rather than passed to the store, because the store expects files and a
    # silent zero-import from a folder is the kind of failure that looks like a bug.
    #
    # Results are sorted so a batch reports in a stable order, and de-duplicated
    # because a caller can select both a folder and a file inside it.
    # 把用户的选择展开为文件列表。
    #
    # 选择目录意味着"其中所有可导入的东西"。目录是被遍历的而不是直接交给存储层，因为存储层
    # 期望文件，而目录静默导入零个正是那种看起来像缺陷的失败。
    #
    # 结果被排序使批量报告顺序稳定，并被去重因为调用方可能同时选中一个目录和它里面的文件。
    found = []
    for path in paths:
        if not path:
            continue
        if os.path.isdir(path):
            if not recursive:
                for entry in sorted(os.listdir(path)):
                    candidate = os.path.join(path, entry)
                    if os.path.isfile(candidate):
                        found.append(candidate)
                continue
            for root, _dirs, files in os.walk(path):
                for name in sorted(files):
                    found.append(os.path.join(root, name))
        elif os.path.isfile(path):
            found.append(path)

    unique = []
    seen = set()
    for path in sorted(found):
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def split_importable(paths):
    # (importable, rejected) — the rejection list is what lets the report say WHY
    # something did not arrive, instead of a count that silently is not the number of
    # files the user picked.
    # (可导入, 被拒绝)——被拒列表正是让报告能说明"为什么某个文件没进来"的原因，而不是给出
    # 一个悄悄不等于用户所选文件数的计数。
    importable = []
    rejected = []
    for path in paths:
        if signatures.is_importable(path):
            importable.append(path)
        else:
            rejected.append(path)
    return importable, rejected


class ImportReport:
    # The outcome of one import, as plain data so every front-end can render it.
    # 一次导入的结果，作为纯数据使每个前端都能渲染。
    __slots__ = ("imported", "skipped", "rejected", "cancelled", "group_name",
                 "errors")

    def __init__(self, imported=0, skipped=0, rejected=0, cancelled=False,
                 group_name="", errors=None):
        self.imported = int(imported)
        self.skipped = int(skipped)
        self.rejected = int(rejected)
        self.cancelled = bool(cancelled)
        self.group_name = group_name
        self.errors = list(errors or ())

    @property
    def total(self):
        return self.imported + self.skipped + self.rejected

    def as_dict(self):
        return {
            "imported": self.imported,
            "skipped": self.skipped,
            "rejected": self.rejected,
            "total": self.total,
            "cancelled": self.cancelled,
            "groupName": self.group_name,
            "errors": self.errors,
        }

    def __repr__(self):
        return (f"<ImportReport imported={self.imported} skipped={self.skipped} "
                f"rejected={self.rejected} cancelled={self.cancelled}>")


class ImportService(QObject):
    # Collects the selection, feeds the store in chunks, and reports progress as
    # bindable properties.
    #
    # Progress is a PROPERTY rather than only a signal because QML binds to it: a
    # signal-only design would need a handler writing the value into a local property,
    # which is the hand-rolled refresh this whole design avoids.
    # 收集选择、分块喂给存储层，并以可绑定属性报告进度。
    #
    # 进度是"属性"而不只是信号，因为 QML 绑定到它：纯信号设计需要一个处理器把取值写进本地
    # 属性，而这正是整套设计所避免的手工刷新。
    progressChanged = Signal()
    finished = Signal("QVariantMap")
    # Emitted once per completed chunk, so a front-end can refresh the sticker list
    # while the import is still running instead of only at the end.
    # 每完成一块发出一次，使前端能在导入仍在进行时就刷新贴纸列表，而不只在结束时。
    chunkImported = Signal(int)

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self._backend = backend
        self._queue = deque()
        self._total = 0
        self._done = 0
        self._running = False
        self._cancel = False
        self._report = None
        self._group_id = -1
        self._auto_convert = True
        self._timer = QTimer(self)
        self._timer.setInterval(CHUNK_INTERVAL_MS)
        self._timer.timeout.connect(self._process_chunk)

    # ---- state / 状态 ----------------------------------------------------

    @Property(bool, notify=progressChanged)
    def running(self):
        return self._running

    @Property(int, notify=progressChanged)
    def done(self):
        return self._done

    @Property(int, notify=progressChanged)
    def total(self):
        return self._total

    @Property(float, notify=progressChanged)
    def fraction(self):
        # 0.0 when nothing is running, so a progress bar bound to this shows empty
        # rather than inheriting the last import's value.
        # 未运行时为 0.0，使绑定到它的进度条显示为空，而不是继承上次导入的取值。
        if not self._total:
            return 0.0
        return min(1.0, self._done / self._total)

    @Property(str, constant=True)
    def filter(self):
        return file_dialog_filter()

    # ---- operations / 操作 ----------------------------------------------

    @Slot("QStringList", int, bool, result=bool)
    def start(self, paths, group_id, auto_convert=True):
        # Begin importing. Returns False when the request cannot start, so the caller
        # can report why instead of watching a progress bar that never moves.
        # 开始导入。无法开始时返回 False，使调用方能报告原因，而不是盯着一个永不移动的
        # 进度条。
        if self._running:
            return False
        group = self._backend.store.get_group(group_id)
        if not group:
            log.warning("import: no such group %s", group_id)
            return False
        # A text group cannot hold images, and the store would return zero rather
        # than saying so.
        # 文字分组放不下图片，而存储层会返回零而不是说明这一点。
        if group["type"] != "image":
            log.warning("import: group %r is a text group", group["name"])
            return False

        collected = collect_paths(list(paths))
        if not collected:
            log.info("import: the selection contained no files")
            return False

        importable, rejected = split_importable(collected)
        self._report = ImportReport(rejected=len(rejected),
                                    group_name=group["name"])
        self._queue = deque(importable)
        self._total = len(importable) + len(rejected)
        self._done = len(rejected)
        self._group_id = int(group_id)
        self._auto_convert = bool(auto_convert)
        self._cancel = False
        self._running = True
        self.progressChanged.emit()

        if not self._queue:
            # Everything was rejected, so there is nothing to chunk. Reporting
            # immediately is what keeps the dialog from waiting forever.
            # 全部被拒，因此没有可分块的东西。立即报告正是让对话框不会永远等待的原因。
            self._finish()
            return True
        self._timer.start()
        return True

    @Slot()
    def cancel(self):
        if self._running:
            self._cancel = True

    @Slot(result=bool)
    def isRunning(self):
        return self._running

    def shutdown(self, timeout_ms=5000):
        # Stop at teardown. There is no thread to join any more, so this only has to
        # stop the timer; the parameter is kept because callers pass a timeout and
        # because a future implementation may need to wait for a chunk.
        # 退出时停止。现在没有线程需要 join，因此只需停掉定时器；保留该参数是因为调用方会传
        # 超时，也因为未来的实现可能需要等待一块完成。
        self._timer.stop()
        if self._running:
            self._cancel = True
            log.info("import: cancelled at shutdown")
        self._running = False
        return True

    # ---- chunking / 分块 -------------------------------------------------

    def _process_chunk(self):
        if not self._running:
            self._timer.stop()
            return
        if self._cancel:
            self._report.cancelled = True
            self._finish()
            return

        imported_this_chunk = 0
        for _ in range(CHUNK_SIZE):
            if not self._queue:
                break
            path = self._queue.popleft()
            try:
                result = self._backend.store.import_emoji(
                    self._group_id, path, auto_convert=self._auto_convert)
            except Exception as exc:
                # One bad file must not abort the batch: the remaining files are
                # still worth importing, and the error belongs in the report.
                # 一个坏文件不得中止整批：其余文件仍值得导入，而错误应进入报告。
                log.exception("import: %s failed", path)
                self._report.errors.append(f"{os.path.basename(path)}: {exc}")
                result = media_store.RESULT_ERROR
            if result == media_store.RESULT_OK:
                self._report.imported += 1
                imported_this_chunk += 1
            elif result == media_store.RESULT_DUPLICATE:
                self._report.skipped += 1
            else:
                self._report.rejected += 1
            self._done += 1

        self.progressChanged.emit()
        if imported_this_chunk:
            self.chunkImported.emit(imported_this_chunk)

        if not self._queue:
            self._finish()

    def _finish(self):
        self._timer.stop()
        self._running = False
        self._done = self._total
        self.progressChanged.emit()
        report = self._report or ImportReport()
        self._report = None
        self.finished.emit(report.as_dict())


__all__ = [
    "CHUNK_INTERVAL_MS",
    "CHUNK_SIZE",
    "ImportReport",
    "ImportService",
    "collect_paths",
    "file_dialog_filter",
    "importable_extensions",
    "split_importable",
]
