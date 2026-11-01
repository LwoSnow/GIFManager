"""Update service: check, download and install, with progress QML can bind to.

`core/updater.py` does the work and knows nothing about a toolkit. This exposes it as
properties and slots, and it makes two things explicit that a UI is tempted to hide:

* **the check is not a signature check.** The manifest carries a SHA-256, which proves
  the download arrived intact and proves NOTHING about who published it. The service
  reports `signed` so the interface can say which of the two it is.
* **a source checkout cannot update itself.** There is no installed artefact to
  replace, so `canSelfUpdate` is false and the interface shows why instead of offering
  a button that would fail.

`core/updater.py` 做实际工作且对工具包一无所知。本模块把它暴露为属性与槽，并明确两件界面容易
掩盖的事：

* **检查不是签名校验。** 清单携带一个 SHA-256，它证明下载完好无损，而对"是谁发布的"毫无证明。
  服务报告 `signed`，使界面能说明它属于两者中的哪一个。
* **源码目录无法自我更新。** 没有已安装的产物可替换，因此 `canSelfUpdate` 为 false，界面说明
  原因，而不是提供一个会失败的按钮。
"""
import logging

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from gifmanager.core import updater as updater_core

log = logging.getLogger("GIFManager")

# The timer interval this service uses. Declared here rather than imported from the
# importer: the two are unrelated concerns, and reaching across modules for a constant
# is how a "shared" module grows a dependency on an unrelated one.
# 本服务使用的定时器间隔。在此声明而非从导入器导入：两者是不相关的关注点，而跨模块取一个常量
# 正是"共享"模块长出一个对无关模块的依赖的方式。
TIMER_INTERVAL_MS = 0

# A check on startup is polite; a check on every startup is noise. The result is cached
# for a day, and a manual check ignores the cache.
# 启动时检查一次是礼貌的；每次启动都检查是噪音。结果缓存一天，手动检查忽略缓存。
CHECK_CACHE_SECONDS = 24 * 60 * 60

# The first automatic check is DELAYED, because a startup-time network request competes
# with loading the interface and, on a slow connection, delays the first paint.
# 首次自动检查是"延迟"的，因为启动时的网络请求会与加载界面争抢，并在慢速连接上拖延首帧。
STARTUP_CHECK_DELAY_MS = 8000


class UpdateService(QObject):
    # Check, download and install an update.
    #
    # Progress and the last result are PROPERTIES so QML binds to them: a signal-only
    # design would need a handler writing each value into a local property, which is the
    # hand-rolled refresh this whole front-end avoids.
    # 检查、下载并安装更新。
    #
    # 进度与最后一次结果是"属性"，使 QML 绑定到它们：纯信号设计需要一个处理器把每个取值写进
    # 本地属性，而这正是整个前端所避免的手工刷新。
    stateChanged = Signal()
    checkFinished = Signal("QVariantMap")
    installFinished = Signal("QVariantMap")

    def __init__(self, backend, platform_key="", parent=None):
        super().__init__(parent)
        self._backend = backend
        self._platform_key = platform_key
        # idle | checking | downloading | ready / 空闲 | 检查中 | 下载中 | 就绪
        self._phase = "idle"
        self._received = 0
        self._total = 0
        self._error = ""
        self._info = {}
        self._checked_at = 0.0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(TIMER_INTERVAL_MS)

    # ---- state / 状态 ----------------------------------------------------

    @Property(str, notify=stateChanged)
    def phase(self):
        return self._phase

    @Property(bool, notify=stateChanged)
    def busy(self):
        return self._phase in ("checking", "downloading")

    @Property(int, notify=stateChanged)
    def received(self):
        return self._received

    @Property(int, notify=stateChanged)
    def total(self):
        return self._total

    @Property(float, notify=stateChanged)
    def fraction(self):
        if not self._total:
            return 0.0
        return min(1.0, self._received / self._total)

    @Property(str, notify=stateChanged)
    def error(self):
        return self._error

    @Property(str, notify=stateChanged)
    def currentVersion(self):
        return updater_core.current_version()

    @Property(str, notify=stateChanged)
    def latestVersion(self):
        return str(self._info.get("latest") or "")

    @Property(str, notify=stateChanged)
    def notes(self):
        return str(self._info.get("notes") or "")

    @Property(str, notify=stateChanged)
    def published(self):
        return str(self._info.get("published") or "")

    @Property(bool, notify=stateChanged)
    def updateAvailable(self):
        return bool(self._info.get("ok"))

    @Property(bool, notify=stateChanged)
    def checked(self):
        return bool(self._info)

    @Property(bool, notify=stateChanged)
    def signed(self):
        # True when the manifest carried a signature.
        #
        # Exposed rather than assumed so the interface can distinguish "verified intact"
        # from "verified authentic" — a distinction the previous phrasing ("we check the
        # hash") quietly erased.
        # 清单携带签名时为 True。
        #
        # 暴露而非假定，使界面能区分"已验证完好"与"已验证真实"——此前的措辞（"我们检查了
        # 哈希"）悄悄抹掉了这一区别。
        return bool(self._info.get("signed"))

    @Property(bool, notify=stateChanged)
    def canSelfUpdate(self):
        return bool(self._can_self_update().get("ok"))

    @Property(str, notify=stateChanged)
    def selfUpdateReason(self):
        return str(self._can_self_update().get("reason") or "")

    @Property(str, notify=stateChanged)
    def manifestUrl(self):
        return updater_core.manifest_url()

    @Property(bool, notify=stateChanged)
    def staged(self):
        return bool(self._staged_path) if hasattr(self, "_staged_path") else False

    def _can_self_update(self):
        # Asked of the PLATFORM layer, because whether this build can replace itself is a
        # platform fact: a source checkout cannot anywhere, and Linux cannot even when
        # frozen because the package manager owns the files.
        # 向"平台层"询问，因为本构建能否替换自身是平台事实：源码目录在任何平台上都不能，而
        # Linux 即使冻结也不能，因为包管理器拥有那些文件。
        cached = getattr(self, "_self_update", None)
        if cached is None:
            from gifmanager.platform import installer

            cached = installer.can_self_update()
            self._self_update = cached
        return cached

    def _set_phase(self, phase, error=""):
        self._phase = phase
        self._error = error
        self.stateChanged.emit()

    # ---- checking / 检查 -------------------------------------------------

    @Slot()
    def start(self):
        # Schedule the delayed automatic check, once.
        # 安排延迟的自动检查，只一次。
        if getattr(self, "_started", False):
            return
        self._started = True
        self._timer.timeout.connect(self._auto_check)
        self._timer.start(STARTUP_CHECK_DELAY_MS)

    def _auto_check(self):
        # Skip when the cache is fresh, so restarting the application five times does
        # not mean five network requests.
        # 缓存在有效期内时跳过，使重启应用五次不意味着五次网络请求。
        import time

        if time.monotonic() - self._checked_at < CHECK_CACHE_SECONDS:
            return
        self.check(force=False)

    @Slot(bool)
    def check(self, force=True):
        # Check the manifest. Synchronous: the request is small, it happens off the
        # startup path, and a QML `BusyIndicator` bound to `busy` covers the wait.
        # 检查清单。同步执行：请求很小、发生在启动路径之外，而绑定到 `busy` 的 QML
        # `BusyIndicator` 覆盖了等待。
        import time

        if self.busy:
            return
        self._set_phase("checking")
        try:
            result = updater_core.check_for_update()
        except Exception as exc:
            # The core is written not to raise, so reaching here means a bug rather
            # than a network problem — which is exactly why it must not take the
            # application down.
            # 核心层被写成不抛异常，因此到这里意味着一个缺陷而非网络问题——这正是它绝不能拖垮
            # 应用的原因。
            log.exception("update: the check raised")
            result = {"state": updater_core.STATE_UNREACHABLE, "ok": False,
                      "reason": str(exc)}
        self._checked_at = time.monotonic()
        self._info = dict(result)
        state = result.get("state", "")
        if result.get("ok"):
            self._set_phase("ready")
        elif state == updater_core.STATE_NO_UPDATE:
            self._set_phase("idle")
        else:
            self._set_phase("idle", str(result.get("reason") or "the check failed"))
        self.checkFinished.emit(dict(result))

    # ---- downloading / 下载 ----------------------------------------------

    @Slot(result="QVariantMap")
    def download(self):
        # Download the update the last check found.
        #
        # Refused when no update is known, because downloading "whatever the manifest
        # last said" without a check is how a stale URL gets fetched.
        # 下载上次检查发现的更新。
        #
        # 未知更新时拒绝，因为未检查就下载"清单上次说的东西"正是取回过期 URL 的方式。
        if not self._info.get("ok"):
            return {"ok": False, "reason": "there is no update to download"}
        if self.busy:
            return {"ok": False, "reason": "an update operation is already running"}

        path = updater_core.staged_path(self._info.get("latest", ""),
                                        self._info.get("url", ""))
        self._received = 0
        self._total = int(self._info.get("size") or 0)
        self._set_phase("downloading")

        def progress(received, total):
            self._received = int(received)
            if total:
                self._total = int(total)
            self.stateChanged.emit()

        result = updater_core.download(
            self._info.get("url", ""), path,
            expected_sha256=self._info.get("sha256", ""),
            expected_size=int(self._info.get("size") or 0),
            on_progress=progress)
        if not result.get("ok"):
            self._set_phase("ready", str(result.get("reason") or "the download failed"))
            return {"ok": False, "reason": self._error}
        self._staged_path = result.get("path", "")
        self._set_phase("ready")
        return {"ok": True, "path": self._staged_path,
                "bytes": result.get("bytes", 0)}

    # ---- installing / 安装 -----------------------------------------------

    @Slot(result="QVariantMap")
    def install(self):
        # Hand the verified download to the PLATFORM layer.
        #
        # On Linux this deliberately does NOT replace files: the package manager owns them,
        # and replacing them makes the next upgrade either revert the change or fail. The
        # result says `action: "manual"` so the interface can explain.
        #
        # The orchestration lives here rather than in `core` because `core` may not import
        # the platform layer: `core` downloads and VERIFIES (portable), `platform`
        # performs the platform-specific ACT, and this service decides WHEN.
        # 把已校验的下载交给"平台层"。
        #
        # Linux 上刻意"不"替换文件：包管理器拥有它们，替换会让下次升级要么回退该改动、要么
        # 失败。结果的 `action` 为 "manual"，使界面能作出说明。
        #
        # 编排在此而非在 `core`，因为 `core` 不得导入平台层：`core` 负责下载与"校验"
        #（可移植），`platform` 执行平台相关的"动作"，而本服务决定"何时"。
        path = getattr(self, "_staged_path", "")
        if not path:
            return {"ok": False, "reason": "nothing has been downloaded yet"}
        from gifmanager.platform import installer

        result = installer.install(path)
        self._set_phase("ready", "" if result.get("ok") else str(result.get("reason")))
        self.installFinished.emit(dict(result))
        return result

    @Slot(result=int)
    def purgeStaged(self):
        # Delete staged installers, keeping the one just downloaded.
        # 删除已暂存的安装包，保留刚下载的那个。
        return updater_core.purge_staged(getattr(self, "_staged_path", ""))


__all__ = ["CHECK_CACHE_SECONDS", "STARTUP_CHECK_DELAY_MS", "UpdateService"]
