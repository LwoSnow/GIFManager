"""Verify group management, text-sticker creation, and the updater's parsing.

These three were the last gaps with a complete backend and no interface. Each has a
failure mode worth pinning down:

* **groups**: the store refuses an empty name, a duplicate name, and a name whose
  FOLDER belongs to another group. Those are three different messages to a user, so the
  test checks that each produces its own, and that a built-in group cannot be renamed
  or deleted.
* **text stickers**: a text group accepts them, an image group must REFUSE rather than
  redirect, a duplicate must be reported, and the length limit must be a refusal rather
  than a silent truncation.
* **updater**: a malformed manifest must be refused rather than trusted, the checksum
  must actually be verified, and a truncated download must be caught. No network is
  used: a local HTTP server serves the bytes, so the test measures THIS code rather
  than the internet's availability.

这三项是最后有完整后端却没有界面的缺口。每一项都有值得钉住的失败模式：

* **分组**：存储层会拒绝空名称、重复名称，以及"目录"属于另一个分组的名称。对用户而言这是
  三条不同的消息，因此测试检查每一种都产出自己的消息，并检查内置分组不能被重命名或删除。
* **文字贴纸**：文字分组接受它们，图片分组必须"拒绝"而非改道，重复必须被报告，长度上限必须
  是拒绝而非静默截断。
* **更新器**：畸形清单必须被拒绝而非被信任，校验和必须真的被验证，被截断的下载必须被抓到。
  不使用网络：由本地 HTTP 服务器提供字节，因此测试测量的是"本代码"而不是互联网的可用性。
"""
import hashlib
import http.server
import json
import os
import socket
import sys
import tempfile
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from gifmanager.backend import MemorySettingsStore, create_backend
from gifmanager.core import updater as updater_core
from gifmanager.core import version as version_core


def section(title):
    print()
    print("=" * 4, title)


class _Handler(http.server.BaseHTTPRequestHandler):
    # Serves whatever the test put in `payloads`, so the updater's real HTTP path is
    # exercised without touching the network.
    # 提供测试放进 `payloads` 的内容，使更新器真实的 HTTP 路径被演练而不触及网络。
    payloads = {}
    status = 200

    def do_GET(self):
        body = self.payloads.get(self.path.lstrip("/"))
        if body is None:
            self.send_error(404)
            return
        self.send_response(_Handler.status)
        self.send_header("Content-Type", "application/json"
                         if self.path.endswith(".json") else "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        # Silent: the test's own output is the report.
        # 静默：测试自身的输出才是报告。
        pass


def start_server():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def main():
    app = QApplication.instance() or QApplication([])
    problems = []

    with tempfile.TemporaryDirectory() as tmp:
        backend = create_backend(data_dir=tmp,
                                settings_store=MemorySettingsStore(), log=False)
        # The bridge takes an ADAPTER, not the backend: the adapter is the shared
        # convenience layer the Qt Widgets front-end also uses, so passing the backend
        # here would make this test exercise a path no front-end uses.
        # 桥接收的是"适配器"而非后端：适配器是 Qt Widgets 前端也在用的共享便捷层，因此在这里
        # 传后端会让本测试演练一条没有前端使用的路径。
        from gifmanager.frontend.qml.bridge import BackendBridge
        from gifmanager.frontend.qml.theme import ThemeBridge
        from gifmanager.frontend.qt.bridge import BackendAdapter

        adapter = BackendAdapter(backend)
        theme = ThemeBridge(backend.settings)
        bridge = BackendBridge(adapter, theme)

        # ---- group management / 分组管理 ------------------------------------
        section("group management: create")
        created = bridge.createGroup("我的分组", "image")
        print("create image      :", created)
        if not created.get("ok"):
            problems.append(f"creating an image group failed: {created}")
        text_group = bridge.createGroup("文字分组", "text")
        print("create text       :", text_group)
        if not text_group.get("ok"):
            problems.append(f"creating a text group failed: {text_group}")

        section("group management: refusals carry their own reason")
        empty = bridge.createGroup("   ", "image")
        duplicate = bridge.createGroup("我的分组", "image")
        print("empty name        :", empty.get("messageKey"), "|", empty.get("message"))
        print("duplicate name    :", duplicate.get("messageKey"), "|",
              duplicate.get("message"))
        if empty.get("ok"):
            problems.append("an empty group name was accepted")
        if empty.get("messageKey") != "group_name_empty":
            problems.append(f"an empty name gave {empty.get('messageKey')!r}")
        if duplicate.get("ok"):
            problems.append("a duplicate group name was accepted")
        if duplicate.get("messageKey") != "group_name_taken":
            problems.append(f"a duplicate name gave {duplicate.get('messageKey')!r}")
        # The two refusals must be DISTINGUISHABLE: a single "it did not work" would
        # leave the user guessing which rule they broke.
        # 两种拒绝必须"可区分"：单一的"没成功"会让用户猜自己破坏了哪条规则。
        if empty.get("messageKey") == duplicate.get("messageKey"):
            problems.append("an empty name and a duplicate name gave the same message")

        section("group management: a built-in group is protected")
        builtin_id = backend.store._all_group_id()
        info = bridge.groupInfo(builtin_id)
        print("builtin info      :", info)
        if not info.get("builtin"):
            problems.append("the All group does not report itself as built-in")
        renamed = bridge.renameGroup(builtin_id, "Hacked")
        deleted = bridge.deleteGroup(builtin_id)
        print("rename builtin    :", renamed.get("messageKey"))
        print("delete builtin    :", deleted.get("messageKey"))
        if renamed.get("ok") or deleted.get("ok"):
            problems.append("a built-in group could be renamed or deleted")

        section("group management: rename and delete")
        target = created["id"]
        renamed = bridge.renameGroup(target, "改名后")
        print("rename            :", renamed)
        if not renamed.get("ok") or renamed.get("name") != "改名后":
            problems.append(f"renaming failed: {renamed}")
        # Renaming to the SAME name must be reported as unchanged, not as a success that
        # silently did nothing.
        # 重命名为"同一"名称必须被报告为未变化，而不是一次静默无效的成功。
        same = bridge.renameGroup(target, "改名后")
        print("rename to same    :", same.get("messageKey"))
        if same.get("ok"):
            problems.append("renaming to the same name reported success")

        # Deleting the group the library is showing must move the selection off it, or
        # the grid would show an empty view of a group that no longer exists.
        # 删除表情库正在显示的分组必须把选中项移开，否则网格会为一个不再存在的分组显示空视图。
        bridge.selectGroup(target)
        app.processEvents()
        deleted = bridge.deleteGroup(target)
        app.processEvents()
        print("delete            :", deleted)
        print("selection after   :", bridge.groups.currentId, "(expected -1)")
        if not deleted.get("ok"):
            problems.append(f"deleting failed: {deleted}")
        if bridge.groups.currentId != -1:
            problems.append(
                f"the selection stayed on the deleted group "
                f"({bridge.groups.currentId})")

        # ---- text stickers / 文字贴纸 ---------------------------------------
        section("text stickers: creation into a text group")
        text_id = text_group["id"]
        made = bridge.createTextSticker(text_id, "测试文字")
        print("create text       :", made)
        if not made.get("ok"):
            problems.append(f"creating a text sticker failed: {made}")
        # It must be visible in the library afterwards.
        # 之后它必须能在表情库中看到。
        bridge.selectGroup(text_id)
        app.processEvents()
        print("stickers in group :", bridge.stickers.count)
        if bridge.stickers.count != 1:
            problems.append(
                f"the text group shows {bridge.stickers.count} rows, expected 1")
        index0 = bridge.stickers.index(0, 0)
        is_text = bridge.stickers.data(index0, bridge.stickers.IsTextRole)
        content = bridge.stickers.data(index0, bridge.stickers.TextRole)
        print("card isText       :", is_text, "content:", content)
        if not is_text:
            problems.append("the created sticker is not marked as text")
        if content != "测试文字":
            problems.append(f"the sticker's content is {content!r}")

        section("text stickers: refusals")
        image_group = bridge.createGroup("图片组", "image")
        into_image = bridge.createTextSticker(image_group["id"], "nope")
        print("into image group  :", into_image.get("messageKey"))
        if into_image.get("ok"):
            problems.append("a text sticker was created in an IMAGE group")
        if into_image.get("messageKey") != "text_needs_text_group":
            problems.append(
                f"an image group gave {into_image.get('messageKey')!r}, expected "
                f"'text_needs_text_group'")
        blank = bridge.createTextSticker(text_id, "   ")
        print("empty text        :", blank.get("messageKey"))
        if blank.get("ok"):
            problems.append("an empty text sticker was created")
        duplicate = bridge.createTextSticker(text_id, "测试文字")
        print("duplicate text    :", duplicate.get("messageKey"))
        if duplicate.get("ok"):
            problems.append("a duplicate text sticker was created")
        limit = bridge.textStickerLimit
        too_long = bridge.createTextSticker(text_id, "x" * (limit + 1))
        print(f"over the limit    : {too_long.get('messageKey')} (limit {limit})")
        if too_long.get("ok"):
            problems.append("text past the limit was accepted")

        section("text stickers: editing")
        sticker_id = bridge.stickers.data(index0, bridge.stickers.IdRole)
        edited = bridge.setStickerTextResult(sticker_id, "改过的文字")
        print("edit              :", edited)
        if not edited.get("ok"):
            problems.append(f"editing a text sticker failed: {edited}")
        row = bridge.stickers.rowById(sticker_id)
        if row.get("text_content") != "改过的文字":
            problems.append(
                f"after the edit the content is {row.get('text_content')!r}")
        unchanged = bridge.setStickerTextResult(sticker_id, "改过的文字")
        print("edit to same      :", unchanged.get("messageKey"))
        if unchanged.get("ok"):
            problems.append("editing to the same text reported success")

        # ---- updater / 更新器 ----------------------------------------------
        section("updater: version handling")
        for newer, older, expected in ((("2.0.1"), "2.0.0", True),
                                       (("2.0.0"), "2.0.0", False),
                                       (("1.9.9"), "2.0.0", False)):
            got = version_core.is_newer(newer, older)
            flag = "OK " if got == expected else "BAD"
            print(f"  [{flag}] is_newer({newer!r}, {older!r}) = {got}")
            if got != expected:
                problems.append(f"is_newer({newer!r}, {older!r}) returned {got}")

        section("updater: a malformed manifest is refused, not trusted")
        bad_manifests = (
            ("{}", "no version"),
            ('{"version": "nonsense"}', "unparseable version"),
            ('{"version": "2.0.1"}', "no download"),
            ("not json at all", "not JSON"),
            ('[1, 2, 3]', "a list instead of an object"),
        )
        server, base = start_server()
        try:
            for body, label in bad_manifests:
                _Handler.payloads = {"latest.json": body.encode("utf-8")}
                result = updater_core.check_for_update(f"{base}/latest.json")
                refused = not result.get("ok")
                flag = "OK " if refused else "BAD"
                print(f"  [{flag}] {label:28} -> state={result.get('state')!r} "
                      f"reason={result.get('reason', '')[:44]!r}")
                if not refused:
                    problems.append(f"a manifest with {label} was accepted")
                if result.get("state") not in (updater_core.STATE_INVALID,
                                               updater_core.STATE_UNREACHABLE):
                    problems.append(
                        f"a manifest with {label} gave state "
                        f"{result.get('state')!r}")

            section("updater: a reachable manifest is compared")
            _Handler.payloads = {"latest.json": json.dumps({
                "version": "9.9.9",
                "asset": f"{base}/setup.exe",
                "sha256": "0" * 64,
                "size": 4,
                "notes": "a test release",
            }).encode("utf-8")}
            result = updater_core.check_for_update(f"{base}/latest.json")
            print("  state            :", result.get("state"))
            print("  latest           :", result.get("latest"))
            print("  signed           :", result.get("signed"))
            if not result.get("ok"):
                problems.append(f"a valid newer manifest was not accepted: {result}")
            if result.get("latest") != "9.9.9":
                problems.append(f"the latest version parsed as {result.get('latest')!r}")
            if result.get("signed"):
                problems.append("an unsigned manifest reported itself as signed")

            # A manifest claiming the CURRENT version must not offer an update.
            # 声称是"当前"版本的清单不得提供更新。
            _Handler.payloads = {"same.json": json.dumps({
                "version": updater_core.current_version(),
                "asset": f"{base}/setup.exe",
            }).encode("utf-8")}
            same = updater_core.check_for_update(f"{base}/same.json")
            print("  current version  :", same.get("state"))
            if same.get("ok"):
                problems.append("the current version was offered as an update")
            if same.get("state") != updater_core.STATE_NO_UPDATE:
                problems.append(
                    f"the current version gave state {same.get('state')!r}")

            section("updater: the checksum is actually verified")
            payload = b"GIFMANAGER-TEST-PAYLOAD" * 64
            good_sha = hashlib.sha256(payload).hexdigest()
            _Handler.payloads = {"setup.exe": payload}

            target = os.path.join(tmp, "good.bin")
            ok_result = updater_core.download(f"{base}/setup.exe", target,
                                              expected_sha256=good_sha,
                                              expected_size=len(payload))
            print("  correct digest   :", ok_result.get("state"),
                  ok_result.get("bytes"), "bytes")
            if not ok_result.get("ok"):
                problems.append(f"a correct download failed: {ok_result}")

            # A WRONG digest must be caught: this is the one thing the check exists for.
            # "错误"摘要必须被抓到：这正是该校验存在的唯一理由。
            bad_result = updater_core.download(f"{base}/setup.exe",
                                               os.path.join(tmp, "bad.bin"),
                                               expected_sha256="f" * 64)
            print("  wrong digest     :", bad_result.get("state"), "|",
                  str(bad_result.get("reason"))[:56])
            if bad_result.get("ok"):
                problems.append("a download with a wrong digest was accepted")
            if bad_result.get("state") != updater_core.STATE_CORRUPT:
                problems.append(
                    f"a wrong digest gave state {bad_result.get('state')!r}")

            # A TRUNCATED transfer must be caught by the size check before hashing.
            # "被截断"的传输必须被大小检查在哈希前抓到。
            short_result = updater_core.download(f"{base}/setup.exe",
                                                 os.path.join(tmp, "short.bin"),
                                                 expected_size=len(payload) + 100)
            print("  truncated        :", short_result.get("state"), "|",
                  str(short_result.get("reason"))[:56])
            if short_result.get("ok"):
                problems.append("a truncated download was accepted")
            if short_result.get("state") != updater_core.STATE_CORRUPT:
                problems.append(
                    f"a truncated download gave state {short_result.get('state')!r}")

            section("updater: an unreachable server is reported, not raised")
            # A port with nothing listening. `check_for_update` must return, because a
            # check that throws turns a network blip into a startup crash.
            # 一个没有监听的端口。`check_for_update` 必须返回，因为会抛异常的检查会把一次网络
            # 抖动变成启动崩溃。
            dead = _free_port()
            unreachable = updater_core.check_for_update(f"http://127.0.0.1:{dead}/x.json")
            print("  state            :", unreachable.get("state"))
            print("  reason           :", str(unreachable.get("reason"))[:60])
            if unreachable.get("ok"):
                problems.append("an unreachable server reported an update")
            if unreachable.get("state") != updater_core.STATE_UNREACHABLE:
                problems.append(
                    f"an unreachable server gave state "
                    f"{unreachable.get('state')!r}")
        finally:
            server.shutdown()

        section("install strategy: the PLATFORM layer decides, not core")
        # `install` and `can_self_update` live in `gifmanager/platform/installer.py`, not
        # in `core.updater`. That split exists because `core` may not know the operating
        # system: it downloads and VERIFIES (portable), the platform layer performs the
        # platform-specific ACT, and the QML service decides WHEN. A first version of the
        # updater put `os.startfile` in `core` and the project's own layer check rejected
        # it.
        # `install` 与 `can_self_update` 位于 `gifmanager/platform/installer.py` 而非
        # `core.updater`。这一划分存在是因为 `core` 不得知道操作系统：它负责下载与"校验"
        #（可移植），平台层执行平台相关的"动作"，而 QML 服务决定"何时"。更新器的第一个版本把
        # `os.startfile` 放进了 `core`，而本项目自己的分层检查拒绝了它。
        from gifmanager.platform import installer as installer_mod

        staged = os.path.join(tmp, "staged.bin")
        with open(staged, "wb") as handle:
            handle.write(b"x")

        # The Windows strategy is NOT called: it LAUNCHES the file, and a first version of
        # this test did exactly that with a fake `.exe`. The operating system refused it,
        # which was inert, but "the test runs whatever it downloaded" is not a property a
        # test should have.
        #
        # Its DECISION is checked instead, which is the part that can be wrong.
        # "不"调用 Windows 策略：它会"启动"该文件，而本测试的第一个版本确实对一个假的 `.exe`
        # 那样做了。操作系统拒绝了它，那是无害的，但"测试会运行它下载的任何东西"不是测试应有的
        # 性质。
        #
        # 改为检查它的"决策"，那才是可能出错的部分。
        print("IS_WINDOWS       :", installer_mod.IS_WINDOWS)
        print("IS_MACOS         :", installer_mod.IS_MACOS)
        print("sys.platform     :", sys.platform)
        # At most ONE flag may be set, and on Linux BOTH are correctly false.
        #
        # The first version asserted they DIFFER, which holds on Windows and macOS and is
        # FALSE on Linux — so it reported a failure on the very platform this test was
        # being run on for the first time. The claim worth checking is that a flag is only
        # set when `sys.platform` agrees with it.
        # 最多只有一个标志可为真，而 Linux 上两者都"正确地"为假。
        #
        # 第一个版本断言两者"不同"，这在 Windows 与 macOS 上成立、在 Linux 上"不"成立——于是它
        # 在这个测试第一次运行的平台上报出了失败。值得检查的命题是：标志为真时 `sys.platform`
        # 必须与之相符。
        if installer_mod.IS_WINDOWS and not sys.platform.startswith("win"):
            problems.append(f"IS_WINDOWS is set on sys.platform={sys.platform!r}")
        if installer_mod.IS_MACOS and sys.platform != "darwin":
            problems.append(f"IS_MACOS is set on sys.platform={sys.platform!r}")
        if installer_mod.IS_WINDOWS and installer_mod.IS_MACOS:
            problems.append("both IS_WINDOWS and IS_MACOS are set")

        # On Linux the strategy must be `manual`: the package manager owns the files, and
        # replacing them makes the next upgrade revert or fail.
        # Linux 上策略必须是 `manual`：包管理器拥有这些文件，替换会让下次升级回退或失败。
        if sys.platform.startswith("linux"):
            linux = installer_mod.install(staged)
            print("linux action     :", linux.get("action"), "|",
                  str(linux.get("reason"))[:64])
            if linux.get("action") != "manual":
                problems.append(
                    f"the Linux install strategy was {linux.get('action')!r}, expected "
                    f"'manual' so it does not fight the package manager")
            if not linux.get("ok"):
                problems.append(
                    "the Linux strategy reported failure for a staged file")
            linux_cap = installer_mod.can_self_update(frozen=True)
            print("linux self-update:", linux_cap)
            if linux_cap.get("ok"):
                problems.append("a frozen Linux build claimed it could self-update")
        else:
            print("(not Linux, so the package-manager strategy is not exercised)")

        # A staged path that does not exist must be refused BEFORE any launcher runs, on
        # every platform.
        # 不存在的暂存路径必须在任何启动器运行之前被拒绝，在每个平台上都是如此。
        missing = installer_mod.install(os.path.join(tmp, "nope.bin"))
        print("missing file     :", missing.get("reason"))
        if missing.get("ok"):
            problems.append("a missing staged file was accepted")
        if missing.get("action") != "none":
            problems.append(
                f"a missing staged file gave action {missing.get('action')!r}")

        # A source checkout cannot self-update anywhere: there is no installed artefact
        # to replace.
        # 源码目录在任何平台上都无法自我更新：没有已安装的产物可替换。
        source_cap = installer_mod.can_self_update(frozen=False)
        print("source checkout  :", source_cap.get("reason", "")[:64])
        if source_cap.get("ok"):
            problems.append("a source checkout claimed it could self-update")
        # A frozen build on a packaging platform CAN, which is the case the button exists
        # for; reporting False would hide it from every real user.
        # 打包平台上的冻结构建"可以"，那正是该按钮存在的理由；报告 False 会让每个真实用户都
        # 看不到它。
        if installer_mod.IS_WINDOWS or installer_mod.IS_MACOS:
            frozen_cap = installer_mod.can_self_update(frozen=True)
            print("frozen build     :", frozen_cap)
            if not frozen_cap.get("ok"):
                problems.append(
                    "a frozen Windows/macOS build reported that it cannot "
                    "self-update, so the install button would never appear")

        section("the updater service exposes state to QML")
        service = bridge.updater
        print("phase            :", service.phase)
        print("currentVersion   :", service.currentVersion)
        print("canSelfUpdate    :", service.canSelfUpdate)
        print("manifestUrl      :", service.manifestUrl)
        print("fraction (idle)  :", service.fraction)
        if service.fraction != 0.0:
            problems.append(f"an idle updater reports fraction {service.fraction}")
        if service.busy:
            problems.append("a fresh updater reports itself as busy")
        # Downloading with no known update must be refused rather than fetching a stale
        # URL from a previous check.
        # 在没有已知更新时下载必须被拒绝，而不是取回上次检查留下的过期 URL。
        no_update = service.download()
        print("download w/o info:", no_update.get("reason"))
        if no_update.get("ok"):
            problems.append("a download started with no known update")

        section("shutdown")
        bridge.detach()
        adapter.detach()
        backend.close()
        print("torn down cleanly")

    print()
    if problems:
        print("FEATURES CHECK FAILED / 功能检查未通过")
        for problem in problems:
            print("  " + problem)
        return 1
    print("FEATURES CHECK OK / 功能检查通过")
    print("  groups are created, renamed and deleted with distinguishable refusals and")
    print("  built-in protection; text stickers are created, refused where they do not")
    print("  belong and bounded; the updater refuses malformed manifests, verifies the")
    print("  checksum, catches truncation and reports an unreachable server")
    print("  分组可新建/重命名/删除且拒绝原因可区分、内置受保护；文字贴纸可创建、在不该去的")
    print("  地方被拒绝且有长度界限；更新器拒绝畸形清单、校验校验和、抓截断并报告不可达")
    return 0


def _free_port():
    # A port nothing is listening on, so the connection is refused rather than refused
    # by a firewall rule that might behave differently.
    # 一个没有监听的端口，使连接被拒绝，而不是被一条行为可能不同的防火墙规则拒绝。
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


if __name__ == "__main__":
    import os as _os
    import sys as _sys

    _status = main()
    _sys.stdout.flush()
    _sys.stderr.flush()
    _os._exit(_status)
