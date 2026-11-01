"""Launcher backend: hand a verified download to the platform's own installer.

# Why this is in the platform layer and not in `core.updater`

The first version of the updater put `os.startfile` and a `sys.platform` test in
`core/updater.py`, and the project's own layer check rejected it — correctly. `core`
must not know which operating system it runs on, and the reason is not tidiness:
`core` is the layer that has to work identically everywhere, and every platform branch
that leaks into it is a place where a third platform's behaviour is unrepresented.

So `core.updater` downloads and VERIFIES, which is portable, and this module performs
the platform-specific ACT of installing, which is not.

# The three answers

* **Windows** — launch the installer and let the user finish. The application may then
  exit, because an installer cannot replace files that are in use.
* **macOS** — the same, through `open`. Replacing files inside a running `.app` bundle
  is what breaks its code signature, so the bundle must not be edited in place.
* **Linux** — do NOT replace anything. The package manager owns those files, and
  replacing them makes the next upgrade either revert the change or fail. The file is
  downloaded, verified, and then reported to the user with its path.

启动器后端：把已校验的下载交给平台自己的安装器。

# 为什么这在平台层而不在 `core.updater`

更新器的第一个版本把 `os.startfile` 与一个 `sys.platform` 判断放进了
`core/updater.py`，而项目自己的分层检查拒绝了它——这是正确的。`core` 不得知道自己跑在哪个
操作系统上，理由不是整洁：`core` 是必须在所有地方表现一致的层，而每一条泄漏进它的平台分支都是
第三个平台行为未被表示的地方。

因此 `core.updater` 负责下载与"校验"（可移植），本模块执行平台相关的"安装"动作（不可移植）。

# 三个答案

* **Windows**——启动安装器并让用户完成。应用随后可以退出，因为安装器无法替换正在被使用的文件。
* **macOS**——同上，经 `open`。在运行中的 `.app` bundle 内替换文件正是破坏其代码签名的方式，
  因此绝不能就地编辑该 bundle。
* **Linux**——"不"替换任何东西。包管理器拥有那些文件，替换它们会让下次升级要么回退该改动、要么
  失败。文件被下载、校验，然后连同其路径一起报告给用户。
"""
import logging
import os
import subprocess
import sys

log = logging.getLogger("GIFManager")

IS_WINDOWS = os.name == "nt"
IS_MACOS = sys.platform == "darwin"


def launch(path, note=""):
    # Start the platform's launcher on a verified file.
    #
    # Started DETACHED so the installer outlives this process: on Windows the
    # application must exit for the installer to replace its files, and an installer
    # that is a child of a process being replaced can be killed with it.
    # 用平台的启动器打开一个已校验文件。
    #
    # 以"分离"方式启动，使安装器比本进程活得更久：Windows 上应用必须退出，安装器才能替换其
    # 文件，而作为被替换进程的子进程的安装器可能随它一起被杀掉。
    if not path or not os.path.isfile(path):
        return {"ok": False, "action": "none", "path": path,
                "reason": "there is nothing to launch"}
    try:
        if IS_WINDOWS:
            # `os.startfile` is the documented Windows route and is a no-op on other
            # platforms, which is why it is guarded rather than called unconditionally.
            # `os.startfile` 是 Windows 的既定途径，在其他平台上是空操作，因此它被防护而不是
            # 无条件调用。
            os.startfile(path)  # noqa: S606
            return {"ok": True, "action": "launched", "path": path, "note": note}
        if IS_MACOS:
            spawn_detached(["open", path])
            return {"ok": True, "action": "launched", "path": path, "note": note}
        spawn_detached(["xdg-open", path])
        return {"ok": True, "action": "launched", "path": path, "note": note}
    except Exception as exc:
        log.exception("installer: launching %s failed", path)
        return {"ok": False, "action": "none", "reason": str(exc), "path": path}


def open_url(url, note=""):
    # Open a URL in the user's browser.
    #
    # Deliberately NOT `launch()`: that function requires an existing FILE (it starts an
    # installer, and launching a nonexistent path is a bug worth refusing), so a URL fails its
    # `os.path.isfile` guard and is silently reported as "there is nothing to launch". A URL is
    # a different kind of thing with a different launcher per platform.
    #
    # The scheme is checked rather than trusted: this is reachable from QML, and a `file://` URL
    # would turn "open the repository page" into "run something on this machine".
    # 在用户浏览器中打开 URL。
    #
    # 刻意"不"用 `launch()`：那个函数要求文件"存在"（它用来启动安装器，而启动一个不存在的路径是
    # 值得拒绝的缺陷），因此 URL 会失败在它的 `os.path.isfile` 防护上，并被静默报告为"没有东西可
    # 启动"。URL 是另一类东西，每个平台有自己的启动方式。
    #
    # 方案会被校验而非被信任：这可以从 QML 到达，而 `file://` URL 会把"打开仓库页面"变成"在这台
    # 机器上运行某些东西"。
    allowed = ("http://", "https://", "mailto:")
    text = str(url or "").strip()
    if not text.lower().startswith(allowed):
        log.warning("installer: refusing to open a non-web URL: %r", text[:60])
        return {"ok": False, "action": "none", "url": text,
                "reason": "only http, https and mailto URLs may be opened"}
    try:
        if IS_WINDOWS:
            os.startfile(text)  # noqa: S606
            return {"ok": True, "action": "opened", "url": text, "note": note}
        if IS_MACOS:
            spawn_detached(["open", text])
            return {"ok": True, "action": "opened", "url": text, "note": note}
        spawn_detached(["xdg-open", text])
        return {"ok": True, "action": "opened", "url": text, "note": note}
    except Exception as exc:
        log.exception("installer: opening %s failed", text)
        return {"ok": False, "action": "none", "url": text, "reason": str(exc)}


def spawn_detached(argv):
    # Start a process that outlives this one.
    #
    # `start_new_session` on POSIX and `DETACHED_PROCESS` on Windows, because a child
    # that shares the parent's console is killed when the console closes — and the whole
    # point of launching an installer is that this application may exit next.
    # 启动一个比本进程活得更久的进程。
    #
    # POSIX 上用 `start_new_session`，Windows 上用 `DETACHED_PROCESS`，因为与父进程共享控制台
    # 的子进程会在控制台关闭时被杀——而启动安装器的全部意义就在于本应用接下来可能退出。
    flags = 0
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
              "stdin": subprocess.DEVNULL}
    if IS_WINDOWS:
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP / 分离进程 | 新进程组
        flags = 0x00000008 | 0x00000200
        kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(argv, **kwargs)


def install(installer_path, note=""):
    # Install a verified download, or explain why not.
    #
    # The Linux answer is deliberately the weakest in the set, and it is the one that
    # needs saying out loud: an application that replaces files its package manager
    # owns creates an installation that the next upgrade silently reverts.
    # 安装一个已校验的下载，或说明为什么不行。
    #
    # Linux 的答案在这组里刻意是最弱的，而它正是需要明说的那一个：替换包管理器所拥有文件的
    # 应用，会造出一个下次升级会静默回退的安装。
    if not installer_path or not os.path.isfile(installer_path):
        return {"ok": False, "action": "none", "path": installer_path,
                "reason": "there is nothing staged to install"}
    if sys.platform.startswith("linux") or "bsd" in sys.platform:
        return {
            "ok": True,
            "action": "manual",
            "path": installer_path,
            "reason": ("your package manager owns this installation, so the update "
                       "was downloaded and verified but not applied automatically"),
        }
    if IS_WINDOWS or IS_MACOS:
        return launch(installer_path, note=note)
    return {"ok": False, "action": "none", "path": installer_path,
            "reason": f"no installer strategy for {sys.platform!r}"}


def can_self_update(frozen=None):
    # Whether this build can replace itself.
    #
    # A source checkout cannot: there is no installed artefact to replace, and the files
    # belong to whatever tool put them there (git, an editor, a user's own copy).
    # Reporting that is what keeps the interface from offering a button that would fail.
    # 本构建能否替换自身。
    #
    # 源码目录不能：没有已安装的产物可替换，而那些文件属于把它们放在那里的任何工具（git、
    # 编辑器、用户自己的副本）。报告这一点正是让界面不会提供一个会失败的按钮的原因。
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if not frozen:
        return {"ok": False,
                "reason": ("this is a source checkout, so there is nothing to "
                           "replace; use git to update")}
    if sys.platform.startswith("linux") or "bsd" in sys.platform:
        return {"ok": False,
                "reason": "your package manager owns this installation"}
    return {"ok": True, "reason": ""}


__all__ = [
    "IS_MACOS",
    "IS_WINDOWS",
    "can_self_update",
    "install",
    "launch",
    "open_url",
    "spawn_detached",
]
