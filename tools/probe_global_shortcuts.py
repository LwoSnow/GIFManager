"""Ask the running XDG portal what it will actually do about global shortcuts.

`tests/smoke_wayland.py` drives the `GlobalShortcuts` protocol through a fake transport, which is
right for a unit test and means the real QtDBus spelling and the real portal are never exercised.
On a real Arch + niri session the interface is listed on the bus, so "the portal is absent" is not
the explanation - something in the conversation fails, and the application reports only "the
system refused the hotkey".

This prints the whole exchange: who answers for `GlobalShortcuts`, the version, and the exact
error from `CreateSession`.

`tests/smoke_wayland.py` 通过伪传输层驱动 `GlobalShortcuts` 协议，这对单元测试是正确的，也意味着
真实的 QtDBus 写法与真实门户从未被执行。在真实的 Arch + niri 会话上，该接口就列在总线上，因此
"门户不存在"不是解释——对话中的某一步失败了，而应用只报告"系统拒绝了热键"。

本脚本打印整段交互：谁应答 `GlobalShortcuts`、版本、以及 `CreateSession` 的确切错误。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SETTINGS_INTERFACE = "org.freedesktop.portal.Settings"
SHORTCUTS_INTERFACE = "org.freedesktop.portal.GlobalShortcuts"
REGISTRY_PATH = "/org/freedesktop/portal/desktop"


def main():
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtDBus import (QDBus, QDBusConnection, QDBusInterface,
                                QDBusMessage)

    app = QCoreApplication.instance() or QCoreApplication([])

    bus = QDBusConnection.sessionBus()
    print("session bus connected :", bus.isConnected())
    print("bus address           :",
          os.environ.get("DBUS_SESSION_BUS_ADDRESS", "<unset>"))
    print()

    # ---- 1. who owns the desktop object, and what does it advertise? --------
    # ---- 1. 谁拥有该桌面对象，它声称什么？ ---------------------------------
    print("=== 1. the portal's own properties ===")
    message = QDBusMessage.createMethodCall(
        PORTAL_BUS, PORTAL_PATH, "org.freedesktop.DBus.Properties", "Get")
    message << SHORTCUTS_INTERFACE << "version"
    reply = bus.call(message, QDBus.CallMode.Block, 5_000)
    if reply.type() == QDBusMessage.MessageType.ErrorMessage:
        print("  Get(GlobalShortcuts, version) -> error:", reply.errorName(),
              reply.errorMessage())
    else:
        print("  GlobalShortcuts version       :", reply.arguments())

    # ---- 2. does an interface object exist for it? --------------------------
    # ---- 2. 它是否存在接口对象？ -------------------------------------------
    print()
    print("=== 2. the interface object ===")
    interface = QDBusInterface(PORTAL_BUS, PORTAL_PATH, SHORTCUTS_INTERFACE, bus)
    print("  isValid               :", interface.isValid())
    last = interface.lastError()
    if last.isValid():
        print("  lastError             :", last.name(), last.message())

    # ---- 3. CreateSession, and print whatever comes back --------------------
    # ---- 3. CreateSession，并打印回来的任何东西 ----------------------------
    print()
    print("=== 3. CreateSession ===")
    # The portal requires the caller's unique bus name for the request handle.
    # 门户要求调用方的唯一总线名来构造请求句柄。
    unique = bus.baseService()
    print("  unique bus name       :", unique or "<empty>")
    sanitized = (unique or "").lstrip(":").replace(".", "_")
    handle_token = "gifmanager_probe"

    message = QDBusMessage.createMethodCall(
        PORTAL_BUS, PORTAL_PATH, SHORTCUTS_INTERFACE, "CreateSession")
    options = {
        "handle_token": handle_token,
        "session_handle_token": handle_token,
    }
    message << options
    reply = bus.call(message, QDBus.CallMode.Block, 8_000)
    if reply.type() == QDBusMessage.MessageType.ErrorMessage:
        print("  ERROR name            :", reply.errorName())
        print("  ERROR message         :", reply.errorMessage())
        # The two failures that actually happen on a non-GNOME compositor.
        # 在非 GNOME 合成器上真正会发生的两种失败。
        name = reply.errorName() or ""
        if "NotSupported" in name:
            print("  -> the backend does not support global shortcuts at all")
            print("  -> 后端完全不支持全局快捷键")
        elif "Cancelled" in name or "Denied" in name:
            print("  -> a dialog was expected and was not answered")
            print("  -> 预期会弹出对话框，而它没有被应答")
        return 1
    print("  OK, arguments         :", reply.arguments())
    print()
    print("  expected request path :",
          f"{PORTAL_PATH}/session/{sanitized}/{handle_token}")
    _ = app
    _ = REGISTRY_PATH
    _ = SETTINGS_INTERFACE
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
