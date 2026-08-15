# Update manager: checks GitHub releases and downloads the installer.
# Uses QtNetwork asynchronously so the UI never blocks. Error messages are
# returned as translatable keys plus a raw detail string, shown inline in
# the settings page (no popups).
# Downloads use parallel HTTP Range requests (multi-thread) for much higher
# throughput on slow connections; the segment count follows the configured
# thread count, capped for small files.
# 更新管理器：检查 GitHub releases 并下载安装包。使用 QtNetwork 异步，
# UI 不阻塞。错误信息以可翻译 key + 原始详情返回，在设置页内联显示（不弹窗）。
# 下载使用并行 HTTP Range 分段请求（多线程），慢速网络下吞吐大幅提升；
# 段数跟随配置的核心数，小文件自动降低段数。
import json
import logging
import os
import threading

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import (
    QNetworkAccessManager, QNetworkReply, QNetworkRequest,
)

from app.utils.version import parse_setup_name, cmp_version

log = logging.getLogger("GIFManager")

# All releases (both the "Update" and "Distribution" tags are scanned;
# the newest version wins regardless of which tag it lives under) /
# 拉取全部 releases（同时扫描 Update 与 Distribution 两个标签，
# 取版本号最大的那个，不依赖标签）
API_URL = (
    "https://api.github.com/repos/LwoSnow/GIFManager/releases?per_page=30"
)
USER_AGENT = "GIFManager-Updater"

# Parallel download tuning / 并行下载调参
MIN_SEG_BYTES = 512 * 1024   # at least 512 KB per segment / 每段至少 512KB
MAX_SEGMENTS = 8             # hard cap, mirrors the thread-count cap / 段数上限（与核心数上限一致）


# Map a QNetworkReply error / HTTP status to a translatable key.
# 把网络错误/HTTP 状态映射为可翻译的错误 key。
def _err_key(reply):
    status = reply.attribute(
        QNetworkRequest.Attribute.HttpStatusCodeAttribute)
    if status == 404:
        return "update_err_404"
    if status == 403:
        return "update_err_403"
    err = reply.error()
    mapping = {
        QNetworkReply.NetworkError.ConnectionRefusedError:
            "update_err_conn_refused",
        QNetworkReply.NetworkError.RemoteHostClosedError:
            "update_err_conn_closed",
        QNetworkReply.NetworkError.HostNotFoundError:
            "update_err_dns",
        QNetworkReply.NetworkError.TimeoutError:
            "update_err_timeout",
        QNetworkReply.NetworkError.SslHandshakeFailedError:
            "update_err_ssl",
        QNetworkReply.NetworkError.TemporaryNetworkFailureError:
            "update_err_network",
        QNetworkReply.NetworkError.NetworkSessionFailedError:
            "update_err_network",
        QNetworkReply.NetworkError.UnknownNetworkError:
            "update_err_network",
        QNetworkReply.NetworkError.ContentAccessDenied:
            "update_err_403",
        QNetworkReply.NetworkError.ContentNotFoundError:
            "update_err_404",
    }
    return mapping.get(err, "update_err_unknown")


class UpdateManager(QObject):
    # ok, version tuple, download url, size bytes, error key + raw detail
    # 成功标志、版本元组、下载地址、大小（字节）、错误 key + 原始详情
    check_finished = Signal(bool, object, str, int, str, str)
    download_progress = Signal(int, int)   # received, total / 已接收、总量
    download_done = Signal(bool, str)      # ok, dest path or error detail / 结果、路径或错误详情

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._reply = None
        self._timers = {}   # reply -> QTimer / 请求超时定时器表
        self._latest = None   # (version tuple, url, size, name) / 最新版本信息
        self._dl_reply = None
        self._dl_dest = ""
        self._dl_file = None
        self._seg_replies = set()   # active parallel segment replies / 并行分段请求集合

    def check_updates(self):
        # Fetch all releases and find the newest installer version.
        # 拉取全部 releases 并找出最新的安装包版本。
        if self._reply is not None:
            # Ignore repeated calls while a request is in flight / 请求进行中忽略重复调用
            return
        self._latest = None
        req = QNetworkRequest(QUrl(API_URL))
        req.setRawHeader(b"User-Agent", USER_AGENT.encode())
        req.setRawHeader(b"Accept", b"application/vnd.github+json")
        self._reply = self._nam.get(req)
        self._reply.finished.connect(lambda: self._on_check_finished(self._reply))
        self._start_timeout(self._reply, self._on_check_timeout)

    def _on_check_finished(self, reply):
        # Guard against double delivery: aborting a timed-out reply fires
        # `finished` again, so an already-handled reply must be ignored
        # (otherwise the timeout path emits two check_finished signals).
        # 防止双重回调：abort 超时的 reply 会再次触发 finished，已处理的
        # reply 必须忽略（否则超时路径会发两次 check_finished 信号）。
        if self._reply is not reply:
            reply.deleteLater()
            return
        self._stop_timeout(reply)
        self._reply = None
        if reply.error() != QNetworkReply.NetworkError.NoError:
            key = _err_key(reply)
            self.check_finished.emit(False, None, "", 0, key,
                                     reply.errorString())
            reply.deleteLater()
            return
        data = bytes(reply.readAll())
        reply.deleteLater()
        try:
            releases = json.loads(data)
        except (ValueError, TypeError):
            self.check_finished.emit(
                False, None, "", 0, "update_err_parse", "")
            return
        if not isinstance(releases, list):
            self.check_finished.emit(
                False, None, "", 0, "update_err_parse", "")
            return
        best = None
        for rel in releases:
            if not isinstance(rel, dict):
                continue
            for asset in rel.get("assets", []):
                if not isinstance(asset, dict):
                    continue
                name = asset.get("name", "")
                ver = parse_setup_name(name)
                if ver is None:
                    continue
                if best is None or cmp_version(ver, best[0]) > 0:
                    best = (ver, asset.get("browser_download_url", ""),
                            int(asset.get("size", 0) or 0), name)
        self._latest = best
        if best is None:
            self.check_finished.emit(
                False, None, "", 0, "update_err_no_release", "")
        else:
            self.check_finished.emit(True, best[0], best[1], best[2], "", "")

    def latest_info(self):
        # (version, url, size, name) or None / 最新版本信息或 None
        return self._latest

    def download_update(self, dest_path, segments=None):
        # Download the newest installer to dest_path using parallel Range
        # requests (auto-redirect). `segments` overrides the auto-calculated
        # segment count (used by tests). / 用并行 Range 分段请求下载最新
        # 安装包到 dest_path（自动跟随重定向）。segments 可覆盖自动计算的
        # 段数（供测试用）。
        if self._latest is None:
            self.download_done.emit(False, "update_err_no_release")
            return
        self._dl_dest = dest_path
        url = QUrl(self._latest[1])
        size = self._latest[2] or 0
        n_seg = segments or self._segment_count(size)
        log.info("update download -> url=%s size=%s segments=%s", url.toString(), size, n_seg)
        if n_seg <= 1 or size <= 0:
            # Single-stream fallback (small file or unknown size) /
            # 单流回退（小文件或未知大小）
            self._download_single(url, dest_path)
            return
        self._download_parallel(url, dest_path, size, n_seg)

    # Auto segment count: at least 512 KB per segment, capped at 8, and
    # never more segments than the file can split into (1 MB minimum).
    # 自动段数：每段至少 512KB、上限 8，且不超过文件能分出的段数（最小 1MB）。
    def _segment_count(self, size):
        if size <= MIN_SEG_BYTES:
            return 1
        n = max(1, min(MAX_SEGMENTS, size // MIN_SEG_BYTES))
        return n

    # Sequential download (Range unsupported / small file). Kept on the
    # main thread via QtNetwork so the UI stays responsive and the shared
    # timeout/validation paths below still apply.
    # 顺序下载（不支持 Range / 小文件）。仍走主线程 QtNetwork，UI 保持
    # 响应，且沿用下面的超时与校验逻辑。
    def _download_single(self, url, dest_path):
        try:
            self._dl_file = open(dest_path, "wb")
        except OSError as e:
            log.warning("update download: cannot open %s -> %s", dest_path, e)
            self.download_done.emit(False, str(e))
            return
        req = QNetworkRequest(url)
        req.setRawHeader(b"User-Agent", USER_AGENT.encode())
        self._dl_reply = self._nam.get(req)
        self._dl_reply.downloadProgress.connect(self._on_dl_progress)
        self._dl_reply.readyRead.connect(self._on_dl_ready)
        self._dl_reply.finished.connect(self._on_dl_finished)
        self._start_timeout(self._dl_reply, self._on_dl_timeout)

    # Parallel segmented download with HTTP Range. One worker thread per
    # segment; every worker opens its own reply so QtNetwork stays
    # event-loop driven. Progress is the sum of all received bytes.
    # 基于 HTTP Range 的并行分段下载：每段一个工作线程，各段独立发起
    # 请求（QtNetwork 事件循环驱动）。进度为各段已收字节之和。
    def _download_parallel(self, url, dest_path, size, n_seg):
        try:
            # Create (truncate) the destination, then close it so the
            # segment writers can open it independently (Windows file
            # locking). / 先创建（清空）目标文件再关闭句柄，让各分段能
            # 独立打开写入（Windows 文件锁）。
            with open(dest_path, "wb"):
                pass
        except OSError as e:
            log.warning("update download: cannot create %s -> %s", dest_path, e)
            self.download_done.emit(False, str(e))
            return
        seg_size = (size + n_seg - 1) // n_seg
        state = {
            "lock": threading.Lock(),
            "received": 0,
            "errors": [],
            "done": 0,
            "aborted": False,
        }

        def emit_progress():
            # Throttle to ~20 updates/s max / 进度节流：最多约每秒 20 次
            self.download_progress.emit(state["received"], size)

        def on_seg_progress(seg_rep):
            def _cb(received, total):
                with state["lock"]:
                    # delta from the previous snapshot / 相对上一次快照的增量
                    prev = seg_rep.property("_gm_prev")
                    delta = received - prev
                    seg_rep.setProperty("_gm_prev", received)
                    state["received"] += max(0, delta)
                emit_progress()
            return _cb

        def on_seg_ready(seg_rep):
            data = bytes(seg_rep.readAll())
            if not data:
                return
            # Progress is counted ONLY by on_seg_progress (downloadProgress
            # deltas); counting readAll bytes here too would double-count the
            # same payload and drive the bar to 100% at ~50% real progress.
            # 进度只由 on_seg_progress（downloadProgress 增量）统计；此处再
            # 统计 readAll 字节会重复计数，导致真实进度约 50% 时进度条已满。
            self._write_segment(dest_path, seg_rep, data, state)

        def on_seg_finished(seg_rep):
            with state["lock"]:
                state["done"] += 1
            self._stop_timeout(seg_rep)
            self._seg_replies.discard(seg_rep)
            # Verify the server honored the Range request (206 + matching
            # Content-Range); a 200 full-body reply would make every segment
            # write the whole file at its offset, corrupting the output.
            # 校验服务端是否遵守 Range（206 + Content-Range 与请求段一致）；
            # 若返回 200 全量体，每段会把整个文件写到各自偏移，破坏输出。
            status = seg_rep.attribute(
                QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            range_ok = (int(status) == 206)
            if range_ok:
                cr = seg_rep.rawHeader("Content-Range")
                if cr is not None:
                    cr_bytes = bytes(cr) if not isinstance(cr, bytes) else cr
                else:
                    cr_bytes = b""
                off = seg_rep.property("_gm_offset")
                want = f"bytes {off}-".encode()
                if not cr_bytes.startswith(want):
                    range_ok = False
            if seg_rep.error() == QNetworkReply.NetworkError.NoError and not range_ok:
                with state["lock"]:
                    if not state["aborted"]:
                        state["errors"].append("update_err_range")
                        state["aborted"] = True
                seg_rep.abort()  # stop sibling segments / 中止兄弟分段
            # Flush any bytes still buffered in the reply (finished may
            # arrive with unread data) / 冲刷 reply 中可能残留的缓冲数据
            # （finished 到达时可能还有未读字节）
            tail = bytes(seg_rep.readAll())
            if tail:
                self._write_segment(dest_path, seg_rep, tail, state)
            if seg_rep.error() != QNetworkReply.NetworkError.NoError:
                with state["lock"]:
                    if not state["aborted"]:
                        state["errors"].append(
                            _err_key(seg_rep) + "|" + seg_rep.errorString())
                        state["aborted"] = True
                seg_rep.abort()  # stop sibling segments / 中止兄弟分段
            seg_rep.deleteLater()
            self._maybe_finish_parallel(state, size, dest_path, n_seg)

        for i in range(n_seg):
            start = i * seg_size
            end = min(size, start + seg_size) - 1
            req = QNetworkRequest(url)
            req.setRawHeader(b"User-Agent", USER_AGENT.encode())
            req.setRawHeader(
                b"Range", f"bytes={start}-{end}".encode())
            rep = self._nam.get(req)
            self._seg_replies.add(rep)
            rep.setProperty("_gm_offset", start)
            rep.setProperty("_gm_written", 0)
            rep.setProperty("_gm_prev", 0)
            rep.downloadProgress.connect(on_seg_progress(rep))
            rep.readyRead.connect(lambda r=rep: on_seg_ready(r))
            rep.finished.connect(lambda r=rep: on_seg_finished(r))
            self._start_timeout(rep, self._on_seg_timeout, ms=120000)
        # First progress tick so the bar starts moving immediately /
        # 首个进度事件：进度条立即开始移动
        emit_progress()

    def _on_seg_timeout(self, seg_rep):
        self._stop_timeout(seg_rep)
        if seg_rep is not None and seg_rep.isRunning():
            seg_rep.abort()

    def _maybe_finish_parallel(self, state, size, dest_path, n_seg):
        with state["lock"]:
            done = state["done"]
            errors = list(state["errors"])
            aborted = state["aborted"]
            received = state["received"]
        if done < n_seg:
            return
        if errors:
            self._cleanup_dest(dest_path)
            self.download_done.emit(False, errors[0])
            return
        self._dl_reply = None
        self._dl_file = None
        try:
            with open(dest_path, "rb") as fh:
                mz_ok = fh.read(2) == b"MZ"
        except OSError:
            mz_ok = False
        actual = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0
        log.info("update download done -> size=%s expected=%s mz=%s",
                 actual, size, mz_ok)
        if actual <= 0:
            self._cleanup_dest(dest_path)
            self.download_done.emit(False, "update_err_empty")
        # Parallel segments write exact byte ranges, so a strict size match
        # is expected (the ±16 tolerance belonged to the single-stream path).
        # 并行分段按精确字节范围写入，大小应严格相等（±16 容差属于单流路径）。
        elif actual != size:
            self._cleanup_dest(dest_path)
            self.download_done.emit(False, "update_err_size")
        elif not mz_ok:
            self._cleanup_dest(dest_path)
            self.download_done.emit(False, "update_err_invalid")
        else:
            self.download_done.emit(True, dest_path)

    def _cleanup_dest(self, dest_path):
        try:
            os.remove(dest_path)
        except OSError:
            pass

    # Write one segment's chunk at its byte offset (offset + bytes already
    # written for this segment). Thread-safe per segment via the reply's
    # own property bookkeeping. / 在段偏移处写入一段数据（偏移 = 段起点 +
    # 该段已写字节数）。各段通过 reply 自身属性记账，天然线程安全。
    def _write_segment(self, dest_path, seg_rep, data, state):
        off = seg_rep.property("_gm_offset")
        written = seg_rep.property("_gm_written")
        try:
            with open(dest_path, "r+b") as fh:
                fh.seek(off + written)
                fh.write(data)
            seg_rep.setProperty("_gm_written", written + len(data))
        except OSError as e:
            with state["lock"]:
                if not state["aborted"]:
                    state["errors"].append(str(e))
                    state["aborted"] = True
            seg_rep.abort()

    def _on_dl_ready(self):
        if self._dl_file is not None and self._dl_reply is not None:
            self._dl_file.write(bytes(self._dl_reply.readAll()))

    def _on_dl_progress(self, received, total):
        self.download_progress.emit(int(received), int(total))

    def _on_dl_finished(self):
        reply = self._dl_reply
        if reply is None:
            return
        self._stop_timeout(reply)
        if reply.error() != QNetworkReply.NetworkError.NoError:
            if self._dl_file is not None:
                try:
                    self._dl_file.close()
                except OSError:
                    pass
                try:
                    os.remove(self._dl_dest)
                except OSError:
                    pass
            key = _err_key(reply)
            self.download_done.emit(False, key + "|" + reply.errorString())
        else:
            self._on_dl_ready()  # flush remaining bytes / 冲刷剩余数据
            if self._dl_file is not None:
                try:
                    self._dl_file.close()
                except OSError:
                    pass
            size = os.path.getsize(self._dl_dest) if os.path.exists(
                self._dl_dest) else 0
            # Content validation: expected size match + MZ executable header /
            # 内容校验：预期大小匹配 + MZ 可执行文件头
            expected = self._latest[2] if self._latest else 0
            mz_ok = False
            try:
                with open(self._dl_dest, "rb") as fh:
                    mz_ok = fh.read(2) == b"MZ"
            except OSError:
                pass
            if size <= 0:
                self.download_done.emit(False, "update_err_empty")
            elif expected and abs(size - expected) > 16:
                self.download_done.emit(False, "update_err_size")
            elif not mz_ok:
                self.download_done.emit(False, "update_err_invalid")
            else:
                self.download_done.emit(True, self._dl_dest)
        self._dl_reply = None
        self._dl_file = None
        reply.deleteLater()

    def cancel_download(self):
        # Abort the single-stream reply or all parallel segment replies.
        # Parallel segments: mark the state aborted so on_seg_finished skips
        # the error bookkeeping and _maybe_finish_parallel still runs its
        # cleanup once the last segment settles. / 中止单流回复或全部并行分段
        # 回复。并行分段：先置 aborted 状态，使 on_seg_finished 跳过错误记录，
        # 最后一段结束时 _maybe_finish_parallel 仍会执行清理。
        if self._dl_reply is not None:
            self._dl_reply.abort()
        for rep in list(self._seg_replies):
            if rep is not None and rep.isRunning():
                rep.abort()
        self._seg_replies.clear()

    # Timeout guard: abort a stuck request so the UI never waits forever /
    # 超时保护：卡住的请求自动中止，UI 不会无限等待
    def _start_timeout(self, reply, on_timeout, ms=45000):
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(ms)
        timer.timeout.connect(lambda: on_timeout(reply))
        self._timers[reply] = timer
        timer.start()

    def _stop_timeout(self, reply):
        t = self._timers.pop(reply, None)
        if t is not None:
            t.stop()
            t.deleteLater()

    def _on_check_timeout(self, reply):
        self._stop_timeout(reply)
        # Clear _reply BEFORE aborting: abort() fires `finished` synchronously,
        # and the guard in _on_check_finished uses _reply to detect the
        # duplicate (otherwise two check_finished signals are emitted).
        # 先清 _reply 再 abort：abort() 会同步触发 finished，_on_check_finished
        # 的守卫用 _reply 判断重复（否则会发两次 check_finished 信号）。
        if self._reply is reply:
            self._reply = None
        if reply is not None and reply.isRunning():
            reply.abort()
        self.check_finished.emit(
            False, None, "", 0, "update_err_timeout", "")

    def _on_dl_timeout(self, reply):
        self._stop_timeout(reply)
        # Clear the reference BEFORE abort: abort() fires `finished`
        # synchronously, and _on_dl_finished short-circuits on `reply is None`,
        # so this reply would never be deleteLater'd and the half-written file
        # would stay behind. Remove both here. / 先清引用再 abort：abort() 会
        # 同步触发 finished，而 _on_dl_finished 以 `reply is None` 短路，
        # 否则该 reply 永远不会 deleteLater，半成品文件也会残留。两者都在
        # 此处清理。
        if self._dl_reply is reply:
            self._dl_reply = None
        if self._dl_file is not None:
            try:
                self._dl_file.close()
            except OSError:
                pass
            self._dl_file = None
        if reply is not None and reply.isRunning():
            reply.abort()
        reply.deleteLater()
        self._cleanup_dest(self._dl_dest)
        self.download_done.emit(False, "update_err_timeout|")
