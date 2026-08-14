# Update manager: checks GitHub releases and downloads the installer.
# Uses QtNetwork asynchronously so the UI never blocks. Error messages are
# returned as translatable keys plus a raw detail string, shown inline in
# the settings page (no popups).
# 更新管理器：检查 GitHub releases 并下载安装包。使用 QtNetwork 异步，
# UI 不阻塞。错误信息以可翻译 key + 原始详情返回，在设置页内联显示（不弹窗）。
import json
import os

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import (
    QNetworkAccessManager, QNetworkReply, QNetworkRequest,
)

from app.utils.version import parse_setup_name, cmp_version

# All releases (both the "Update" and "Distribution" tags are scanned;
# the newest version wins regardless of which tag it lives under) /
# 拉取全部 releases（同时扫描 Update 与 Distribution 两个标签，
# 取版本号最大的那个，不依赖标签）
API_URL = (
    "https://api.github.com/repos/LwoSnow/GIFManager/releases?per_page=30"
)
USER_AGENT = "GIFManager-Updater"


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

    def download_update(self, dest_path):
        # Download the newest installer to dest_path (auto-redirect).
        # 下载最新安装包到 dest_path（自动跟随重定向）。
        if self._latest is None:
            self.download_done.emit(False, "update_err_no_release")
            return
        self._dl_dest = dest_path
        try:
            self._dl_file = open(dest_path, "wb")
        except OSError as e:
            self.download_done.emit(False, str(e))
            return
        req = QNetworkRequest(QUrl(self._latest[1]))
        req.setRawHeader(b"User-Agent", USER_AGENT.encode())
        self._dl_reply = self._nam.get(req)
        self._dl_reply.downloadProgress.connect(self._on_dl_progress)
        self._dl_reply.readyRead.connect(self._on_dl_ready)
        self._dl_reply.finished.connect(self._on_dl_finished)
        self._start_timeout(self._dl_reply, self._on_dl_timeout)

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
        if self._dl_reply is not None:
            self._dl_reply.abort()

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
        if reply is not None and reply.isRunning():
            reply.abort()
        self._dl_reply = None
        if self._dl_file is not None:
            try:
                self._dl_file.close()
            except OSError:
                pass
        self.download_done.emit(False, "update_err_timeout|")
