"""In-place updater: check, download, verify, install.

# The three decisions this module makes

**1. Where the release list comes from.** A single JSON manifest at a fixed URL,
overridable by environment variable so a fork or an internal mirror works without a
code change. Not the GitHub API: that needs a token for rate limits, returns a shape
that changes, and would make this application depend on GitHub specifically.

**2. How the download is verified.** SHA-256 against a digest published IN the
manifest, plus a size check before hashing so a truncated transfer fails fast. This is
integrity, NOT authenticity: an attacker who can rewrite the manifest can rewrite the
digest. Saying so matters, because "we check the hash" is easy to read as "we verify
the publisher". Real authenticity needs a signature whose key ships with the
application, which is a key-management problem rather than a code problem and is
therefore left as a documented gap rather than half-done.

**3. What "install" means per platform.** This is where an in-place updater stops
being portable. Windows can hand an installer to the shell and exit; macOS replaces a
bundle and needs a relaunch; Linux has a package manager the user owns, so the honest
answer is "download and tell the user", not "silently replace files the package
manager will overwrite on the next upgrade".

# 原地更新器：检查、下载、校验、安装。

# 本模块做的三个决定

**1. 发布列表从哪来。** 一个固定在某个 URL 的 JSON 清单，可由环境变量覆盖，使分支或内部
镜像无需改代码即可工作。不用 GitHub API：它需要 token 应付限流、返回的形状会变，还会让本应用
特定依赖 GitHub。

**2. 下载如何校验。** 用清单里"发布"的摘要做 SHA-256，并在哈希前先查大小，使被截断的传输
快速失败。这是"完整性"而非"真实性"：能改写清单的攻击者也能改写摘要。说明这一点很重要，因为
"我们检查了哈希"很容易被读成"我们验证了发布者"。真正的真实性需要一个随应用发布的密钥签名，
那是密钥管理问题而非代码问题，因此作为已记录的缺口保留，而不是做一半。

**3. 各平台上"安装"意味着什么。** 这正是原地更新器不再可移植的地方。Windows 可以把安装包
交给外壳并退出；macOS 替换 bundle 且需要重启；Linux 有属于用户的包管理器，因此诚实的答案是
"下载并告知用户"，而不是"静默替换那些包管理器下次升级会覆盖的文件"。
"""
import hashlib
import json
import logging
import os
import shutil
import ssl
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from gifmanager import __version__
from gifmanager.core import paths, version as version_core

log = logging.getLogger("GIFManager")

# Where the release manifest lives. Overridable because a fork, an internal mirror or
# an air-gapped deployment must not require a code change to point somewhere else.
# 发布清单所在位置。可覆盖，因为分支、内部镜像或隔离部署不应为了指向别处而改代码。
MANIFEST_ENV = "GIFMANAGER_UPDATE_MANIFEST"
DEFAULT_MANIFEST_URL = (
    "https://raw.githubusercontent.com/GIFManager/GIFManager/main/"
    "releases/latest.json")

# Timeouts. A metadata fetch is small and should be fast; an installer is large and
# legwork is expected, so the two are separate rather than one compromise value.
# 超时。元数据获取很小且应当很快；安装包很大且预期要花时间，因此两者分开，而不是取一个折中值。
MANIFEST_TIMEOUT_S = 10
DOWNLOAD_TIMEOUT_S = 120

# Read in chunks so a large download does not sit in memory and progress can be
# reported per chunk rather than only at the end.
# 分块读取，使大文件不会常驻内存，且进度可按块报告而不是只在结束时。
CHUNK_BYTES = 64 * 1024

# How the download ended. Strings rather than an enum because they are compared
# against dict values that cross into QML.
# 下载的结局。用字符串而非枚举，因为它们要与跨入 QML 的字典取值比较。
STATE_OK = "ok"
STATE_NO_UPDATE = "no-update"
STATE_UNREACHABLE = "unreachable"
STATE_INVALID = "invalid"
STATE_CORRUPT = "corrupt"
STATE_DISABLED = "disabled"


def manifest_url():
    return (os.environ.get(MANIFEST_ENV) or "").strip() or DEFAULT_MANIFEST_URL


def current_version():
    return __version__


def parse_manifest(payload):
    # Extract the release information from a manifest, or explain what is wrong.
    #
    # A dict rather than a dataclass because the result crosses into QML, where a
    # mapping is what the bindings read.
    # 从清单中提取发布信息，或说明问题所在。
    #
    # 用字典而非数据类，因为结果要跨入 QML，而那里的绑定读取的是映射。
    if not isinstance(payload, dict):
        return {"ok": False, "reason": "the manifest is not a JSON object"}
    latest = payload.get("version") or payload.get("tag_name") or ""
    parsed = version_core.parse_version(str(latest).lstrip("v"))
    if parsed is None:
        return {"ok": False,
                "reason": f"the manifest has no usable version (got {latest!r})"}
    asset = payload.get("asset") or payload.get("url") or ""
    if not asset:
        return {"ok": False, "reason": "the manifest names no download"}
    return {
        "ok": True,
        "version": version_core.format_version(parsed),
        "versionTuple": parsed,
        "url": str(asset),
        "sha256": str(payload.get("sha256") or "").lower(),
        "size": int(payload.get("size") or 0),
        "notes": str(payload.get("notes") or ""),
        "published": str(payload.get("published") or ""),
        # Absent on purpose in the default manifest, and reported when present so the
        # UI can show that the check is weaker than it looks.
        # 默认清单中刻意没有，存在时会上报，使界面能显示该校验比看上去更弱。
        "signature": str(payload.get("signature") or ""),
    }


def check_for_update(url=None):
    # Fetch the manifest and compare. Never raises: an update check that throws turns a
    # network blip into a crash on startup.
    # 获取清单并比较。绝不抛错：会抛异常的更新检查会把一次网络抖动变成启动崩溃。
    target = url or manifest_url()
    request = urllib.request.Request(
        target, headers={"User-Agent": f"GIFManager/{current_version()}",
                         "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request,
                                    timeout=MANIFEST_TIMEOUT_S) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        return {"state": STATE_UNREACHABLE, "ok": False, "current": current_version(),
                "reason": f"the server answered {exc.code}"}
    except urllib.error.URLError as exc:
        return {"state": STATE_UNREACHABLE, "ok": False, "current": current_version(),
                "reason": f"could not reach the server ({exc.reason})"}
    except (ssl.SSLError, OSError) as exc:
        return {"state": STATE_UNREACHABLE, "ok": False, "current": current_version(),
                "reason": str(exc)}

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return {"state": STATE_INVALID, "ok": False, "current": current_version(),
                "reason": f"the manifest is not valid JSON ({exc})"}

    parsed = parse_manifest(payload)
    if not parsed["ok"]:
        return {"state": STATE_INVALID, "ok": False, "current": current_version(),
                "reason": parsed["reason"]}

    newer = version_core.is_newer(parsed["version"], current_version())
    result = {
        "state": STATE_OK if newer else STATE_NO_UPDATE,
        "ok": newer,
        "current": current_version(),
        "latest": parsed["version"],
        "url": parsed["url"],
        "sha256": parsed["sha256"],
        "size": parsed["size"],
        "notes": parsed["notes"],
        "published": parsed["published"],
        "signed": bool(parsed["signature"]),
        "reason": "" if newer else "this is the newest version",
    }
    log.info("updater: current %s, latest %s, update available: %s",
             result["current"], result["latest"], newer)
    return result


def download(url, destination, expected_sha256="", expected_size=0,
             on_progress=None, timeout=DOWNLOAD_TIMEOUT_S):
    # Download to `destination`, hashing as it goes.
    #
    # The digest is computed DURING the transfer rather than by re-reading the file:
    # a second pass over a 200 MB installer is wasted work, and the size check before
    # hashing catches truncation sooner.
    # 下载到 `destination`，边下边哈希。
    #
    # 摘要"在传输过程中"计算，而不是重新读取文件：对 200 MB 的安装包再走一遍是白费功夫，而
    # 哈希前的大小检查能更早发现截断。
    digest = hashlib.sha256()
    written = 0
    request = urllib.request.Request(
        url, headers={"User-Agent": f"GIFManager/{current_version()}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            declared = int(response.headers.get("Content-Length") or 0)
            total = expected_size or declared
            with open(destination, "wb") as handle:
                while True:
                    chunk = response.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    handle.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
                    if on_progress is not None:
                        on_progress(written, total)
    except (urllib.error.URLError, OSError, ssl.SSLError) as exc:
        return {"state": STATE_UNREACHABLE, "ok": False,
                "reason": f"the download failed ({exc})", "path": ""}

    if expected_size and written != expected_size:
        return {"state": STATE_CORRUPT, "ok": False, "path": destination,
                "reason": (f"the download is {written} bytes but the manifest says "
                           f"{expected_size}")}

    actual = digest.hexdigest().lower()
    if expected_sha256 and actual != expected_sha256:
        return {"state": STATE_CORRUPT, "ok": False, "path": destination,
                "reason": (f"the download's SHA-256 is {actual[:16]}... but the "
                           f"manifest says {expected_sha256[:16]}..."),
                "actualSha256": actual}
    return {"state": STATE_OK, "ok": True, "path": destination,
            "bytes": written, "sha256": actual, "reason": ""}


def download_dir():
    # A staging directory that is NOT the application's data directory: an installer or
    # a bundle is not user data, and mixing them means a data backup carries a 200 MB
    # installer around forever.
    # 一个"不是"应用数据目录的暂存目录：安装包或 bundle 不是用户数据，混在一起会让数据备份
    # 永远带着一个 200 MB 的安装包。
    base = os.environ.get("TEMP") or os.environ.get("TMPDIR") or tempfile.gettempdir()
    target = os.path.join(base, "GIFManager", "updates")
    try:
        os.makedirs(target, exist_ok=True)
    except OSError:
        log.exception("updater: cannot create %s", target)
        return tempfile.gettempdir()
    return target


def staged_path(version_text, url=""):
    # Where a given version will be staged.
    #
    # Named after the VERSION and the URL's basename so a second download of a different
    # release cannot silently overwrite the first while it is being installed.
    # 指定版本将被暂存的位置。
    #
    # 以"版本号"与 URL 的基名命名，使对另一个发布的第二次下载不会在第一个正在安装时静默覆盖它。
    suffix = os.path.splitext(urllib.parse.urlparse(url).path)[1] or ".bin"
    safe = version_core.format_version(version_text).replace("/", "_")
    return os.path.join(download_dir(), f"GIFManager-{safe}{suffix}")


# NOTE ON WHAT IS DELIBERATELY ABSENT / 关于刻意缺失部分的说明
#
# There is no `install()` here. Installing cannot be portable — Windows hands a file to
# an installer, macOS opens a package, and Linux must not replace files its package
# manager owns — so it lives in `gifmanager/platform/installer.py`. `core` may not
# import the platform layer, so the DECISION of when to install belongs to the service
# that orchestrates the update (`frontend/qml/updates.py`).
#
# 此处没有 `install()`。安装无法可移植——Windows 把文件交给安装器，macOS 打开包，而 Linux
# 不得替换其包管理器拥有的文件——因此它位于 `gifmanager/platform/installer.py`。`core`
# 不得导入平台层，因此"何时安装"的决定属于编排更新的服务（`frontend/qml/updates.py`）。


def purge_staged(keep=""):
    # Delete staged downloads, optionally keeping one.
    #
    # A verified installer is worth caching between checks, but an old one is 200 MB of
    # nothing, so this is called after a successful install and on demand.
    # 删除已暂存的下载，可选择保留一个。
    #
    # 已校验的安装包值得在两次检查之间缓存，但旧的那份是 200 MB 的废物，因此在成功安装后与按需
    # 调用本函数。
    removed = 0
    directory = download_dir()
    keep_name = os.path.basename(keep) if keep else ""
    try:
        for name in os.listdir(directory):
            if name == keep_name:
                continue
            path = os.path.join(directory, name)
            try:
                if os.path.isfile(path):
                    os.remove(path)
                    removed += 1
                elif os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                    removed += 1
            except OSError:
                log.exception("updater: cannot remove %s", path)
    except OSError:
        log.exception("updater: cannot list %s", directory)
    return removed


__all__ = [
    "CHUNK_BYTES",
    "DEFAULT_MANIFEST_URL",
    "DOWNLOAD_TIMEOUT_S",
    "MANIFEST_ENV",
    "MANIFEST_TIMEOUT_S",
    "STATE_CORRUPT",
    "STATE_DISABLED",
    "STATE_INVALID",
    "STATE_NO_UPDATE",
    "STATE_OK",
    "STATE_UNREACHABLE",
    "check_for_update",
    "current_version",
    "download",
    "download_dir",
    "manifest_url",
    "parse_manifest",
    "purge_staged",
    "staged_path",
]
