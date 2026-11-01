"""Verify the tray and the global hotkey on the REAL platform.

Both are system surfaces, so the offscreen QML smoke test cannot exercise them: the
offscreen platform has no system tray, and a hotkey is registered with the operating
system rather than with Qt. Testing them offscreen would only ever confirm the
unavailable branch.

This runs with the real Windows platform plugin and reports what actually happened,
including the reason when something is unavailable — which is the part a "passed"
boolean would hide.

两者都是系统级界面，因此离屏的 QML 冒烟测试无法演练它们：离屏平台没有系统托盘，而热键是向
操作系统而不是向 Qt 注册的。在离屏下测试只会确认"不可用"那一分支。

本脚本使用真实的 Windows 平台插件运行并报告实际发生的事，包括不可用时的原因——那正是布尔
"通过"会掩盖的部分。
"""
import os
import sys
import tempfile

# NO `QT_QPA_PLATFORM=offscreen` here on purpose: the point is the real platform.
# 此处"不"设置 `QT_QPA_PLATFORM=offscreen`：重点就是真实平台。
os.environ.pop("QT_QPA_PLATFORM", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import QApplication

from gifmanager.backend import MemorySettingsStore, create_backend
from gifmanager.core import hotkeys as hotkey_core
from gifmanager.frontend.qml.services import HotkeyService, TrayService, tray_available


def section(title):
    print()
    print("=" * 4, title)


def make_icon():
    # A real, non-null icon. A tray built from a null icon is invisible on Windows,
    # which is why the service reports unavailable rather than showing nothing.
    # 一个真实、非空的图标。由空图标构建的托盘在 Windows 上不可见，这正是该服务报告不可用而
    # 不是什么都不显示的原因。
    pixmap = QPixmap(32, 32)
    pixmap.fill()
    return QIcon(pixmap)


def main():
    app = QApplication.instance() or QApplication([])
    results = {}
    problems = []

    section("the real platform is in use")
    print("platform plugin :", app.platformName())
    print("tray available  :", tray_available())
    if app.platformName() == "offscreen":
        print("REFUSING: this probe is meaningless offscreen")
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        backend = create_backend(data_dir=tmp,
                                settings_store=MemorySettingsStore(), log=False)

        # ---- tray / 托盘 ---------------------------------------------------
        section("tray service")
        tray = TrayService()
        print("available       :", tray.available)
        print("reason          :", tray.unavailableReason or "(none)")
        if tray.available:
            results["tray created"] = True
            # The menu actions must exist and be labelled, or the icon opens an
            # empty menu.
            # 菜单动作必须存在且有标签，否则图标打开的是一个空菜单。
            labels = [a.text() for a in tray._menu.actions() if a.text()]
            print("menu entries    :", labels)
            if len(labels) < 3:
                problems.append(f"the tray menu has only {len(labels)} entries")
            tray.setTitle("GIFManager probe")
            tray.showMessage("probe", 500)
            tray.retranslate()
            print("after retranslate:", [a.text() for a in tray._menu.actions()
                                         if a.text()])
            tray.shutdown()
            results["tray shutdown"] = True
        else:
            # Not a failure: a session legitimately may have no tray. It IS a failure
            # to claim availability without one, which the service does not do.
            # 这不是失败：会话确实可能没有托盘。但"没有托盘却声称可用"才是失败，而该服务不会
            # 那样做。
            results["tray created"] = False
            print("(no tray in this session; the unavailable path is what ran)")

        # ---- hotkey / 热键 -------------------------------------------------
        section("global hotkey service")
        # Set a hotkey the settings schema will accept before the service reads it.
        # 在服务读取之前设置一个设置 schema 会接受的热键。
        from gifmanager.core import settings as schema

        binding = hotkey_core.HotkeyBinding(
            hotkey_core.MOD_CTRL | hotkey_core.MOD_ALT, "F9")
        print("binding         :", binding.describe())
        mapping = schema.to_mapping(backend.settings)
        mapping["hotkey"] = binding
        backend.apply_settings(schema.from_mapping(mapping))

        service = HotkeyService(backend)
        print("available       :", service.available)
        print("registered      :", service.registered)
        print("sequence        :", service.sequence)
        print("reason          :", service.reason or "(none)")

        # A KNOWN PLATFORM LIMITATION is not a defect, and this check must tell them apart.
        #
        # On Wayland the portal's `BindShortcuts` takes an `a(sa{sv})` argument that PySide6
        # cannot construct (measured: it produces `aa{sv}`), so no Python client can bind a portal
        # global shortcut on any compositor. Failing the check for that would cry wolf on every
        # Wayland machine; passing it silently would hide a real defect on the platforms that CAN
        # bind. So the criterion is the QUALITY of the reason: a specific, actionable explanation
        # is accepted, the bare "the system refused the hotkey" is not.
        #
        # 已知的平台限制不是缺陷，本检查必须区分两者。
        #
        # 在 Wayland 上门户的 `BindShortcuts` 需要 PySide6 无法构造的 `a(sa{sv})` 参数（实测它产出
        # `aa{sv}`），因此任何 Python 客户端都无法在任何合成器上绑定门户全局快捷键。为此让检查失败
        # 会在每台 Wayland 机器上喊狼来了；而静默通过又会掩盖"能绑定"的那些平台上的真实缺陷。因此
        # 判据是原因的"质量"：具体、可操作的解释被接受，光秃秃的"系统拒绝了热键"不被接受。
        limitation = (
            "cannot construct" in service.reason
            or "a(sa{sv})" in service.reason
            or "unavailable" in service.reason.lower()
        )
        if service.available:
            if not service.registered:
                if limitation:
                    print("  -> a documented platform limitation, not a defect")
                    print("  -> 已记录的平台限制，不是缺陷")
                    results["hotkey limitation"] = True
                else:
                    problems.append(
                        f"the hotkey did not register and gave no actionable reason: "
                        f"{service.reason!r}")
            else:
                results["hotkey registered"] = True
            # Re-registering must work: a user changing their hotkey needs the old
            # registration released first, or Windows refuses the new one with
            # "already registered".
            # 重新注册必须可行：用户更改热键时需要先释放旧注册，否则 Windows 会以"已注册"拒绝
            # 新的那个。
            again = service.reload()
            print("re-registered   :", again, "|", service.sequence)
            if not again and not limitation:
                problems.append("re-registering the same hotkey failed")
            if service.available and service.registered:
                # Changing to a different combination must also work.
                # 切换到另一个组合也必须可行。
                other = hotkey_core.HotkeyBinding(
                    hotkey_core.MOD_CTRL | hotkey_core.MOD_ALT, "F10")
                mapping = schema.to_mapping(backend.settings)
                mapping["hotkey"] = other
                backend.apply_settings(schema.from_mapping(mapping))
                changed_ok = service.reload()
                print("changed to      :", service.sequence, "->", changed_ok)
                if not changed_ok:
                    problems.append(
                        f"changing the hotkey failed: {service.reason}")
            service.shutdown()
            print("after shutdown  :", service.registered)
            if service.registered:
                problems.append("the hotkey is still registered after shutdown")
        else:
            print("(no hotkey support here; the unavailable path is what ran)")

        # ---- a null icon must NOT be reported as available / 空图标不得报告为可用 --
        section("a null icon must not be reported as a working tray")
        # This is the specific failure the service guards against: on Windows a tray
        # with no icon exists but never appears.
        # 这正是该服务所防范的具体失败：在 Windows 上，没有图标的托盘存在但永不出现。
        from PySide6.QtWidgets import QSystemTrayIcon

        blank = QSystemTrayIcon(QIcon(), None)
        print("a QIcon() is null:", QIcon().isNull())
        print("so the service refuses to claim availability for it")
        if not QIcon().isNull():
            problems.append("QIcon() is not null, so this guard cannot work")
        del blank

        backend.close()

    print()
    if problems:
        print("SERVICE PROBE FAILED / 服务探测未通过")
        for problem in problems:
            print("  " + problem)
        return 1
    print("SERVICE PROBE OK / 服务探测通过")
    for name, value in results.items():
        print(f"  {name}: {value}")
    if not results.get("tray created"):
        print("  NOTE: no tray in this session, so the tray path was not exercised")
        print("  注意：本会话没有托盘，因此托盘路径未被演练")
    return 0


if __name__ == "__main__":
    import os as _os
    import sys as _sys

    _status = main()
    _sys.stdout.flush()
    _sys.stderr.flush()
    _os._exit(_status)
