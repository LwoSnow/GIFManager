"""UpdateManager parallel (Range) download verification with a local server:
segmented downloads must reassemble the payload byte-for-byte, and small
files fall back to a single stream. Runs offscreen, fully isolated.
用本地服务器验证 UpdateManager 并行（Range）下载：分段下载必须逐字节
重组载荷，小文件回退单流。离屏运行、完全隔离。"""
import hashlib
import http.server
import os
import socketserver
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="gifmgr_dl_")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from app.models.update_manager import UpdateManager

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:100]}")


def run_case(payload, segments=None, expect_ok=True):
    # Serve a payload with Range support on a random port / 在随机端口提供
    # 支持 Range 的载荷
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            rng = self.headers.get("Range")
            body = payload
            if rng and rng.startswith("bytes="):
                s, e = rng[6:].split("-")
                start = int(s)
                end = int(e) if e else len(payload) - 1
                body = payload[start:end + 1]
                self.send_response(206)
                self.send_header(
                    "Content-Range",
                    "bytes {}-{}/{}".format(start, end, len(payload)))
            else:
                self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(body)

    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        um = UpdateManager()
        um._latest = (None, "http://127.0.0.1:{}/setup.exe".format(port),
                      len(payload), "x.exe")
        dest = os.path.join(TMP, "out_{}.exe".format(len(RES)))
        results = {}
        loop = QEventLoop()
        um.download_done.connect(
            lambda ok, p, r=results: (r.update(ok=ok, p=p), loop.quit()))
        um.download_update(dest, segments=segments)
        QTimer.singleShot(30000, loop.quit)
        loop.exec()
        # Let queued signals settle, then abort anything still pending /
        # 让排队信号落地，再中止仍在进行的请求
        um.cancel_download()
        app.processEvents()
        if not results.get("ok"):
            return False, results.get("p", "no result")
        with open(dest, "rb") as fh:
            data = fh.read()
        good = hashlib.md5(data).hexdigest() == hashlib.md5(payload).hexdigest()
        return good, len(data)
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=2)


# 1. Parallel download reassembles exactly / 并行下载逐字节重组
big = b"MZ" + os.urandom(3 * 1024 * 1024 + 12345)
ok, detail = run_case(big, segments=6)
check("A 并行 6 段下载字节一致", ok, detail)

# 2. Small file falls back to single stream / 小文件回退单流
small = b"MZ" + os.urandom(200 * 1024)
ok, detail = run_case(small)  # segments=None -> auto -> 1
check("B 小文件单流下载", ok, detail)

# 3. Segment count formula / 段数计算
um = UpdateManager()
check("C 小文件 1 段", um._segment_count(100_000) == 1)
check("C2 大文件封顶 8 段", um._segment_count(50_000_000) == 8)
check("C3 5MB 用满 8 段", um._segment_count(5_000_000) == 8)

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n更新下载验证: {n_pass}/{len(RES)} 通过")
# Bypass Qt teardown (offscreen crash) / 绕过 Qt 退出清理（offscreen 崩溃）
import shutil
shutil.rmtree(TMP, ignore_errors=True)
import os as _os
_os._exit(0 if n_pass == len(RES) else 1)
