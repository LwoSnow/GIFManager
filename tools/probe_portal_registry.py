"""Try the documented way for a non-sandboxed app to name itself to the portal.

`org.freedesktop.host.portal.Registry.Register(s app_id, a{sv} options)` exists on this bus and is
the interface xdg-desktop-portal provides exactly for a client it cannot identify on its own. The
`setDesktopFileName` route failed because the backend here is `xdg-desktop-portal-gnome`, which in
a niri session has no host to ask for the client's app id.

This registers and then retries `CreateSession` on the SAME bus connection, which is required: the
registry is keyed by the caller's unique bus name.

同一条总线上，`org.freedesktop.host.portal.Registry.Register(s app_id, a{sv} options)` 存在，
正是 xdg-desktop-portal 为"它自己无法识别的客户端"提供的接口。`setDesktopFileName` 路线失败，
是因为此后端是 `xdg-desktop-portal-gnome`，在 niri 会话里它没有宿主可问客户端的 app id。

本脚本在同一条总线连接上注册后重试 `CreateSession`，这是必需的：注册表以调用方的唯一总线名为键。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
REGISTRY = "org.freedesktop.host.portal.Registry"
SHORTCUTS = "org.freedesktop.portal.GlobalShortcuts"


def main():
    from PySide6.QtDBus import QDBus, QDBusConnection, QDBusMessage

    app_id = sys.argv[1] if len(sys.argv) > 1 else "gifmanager"
    bus = QDBusConnection.sessionBus()
    print("bus connected         :", bus.isConnected())
    print("unique name           :", bus.baseService())
    print("app id to register    :", app_id)
    print()

    # ---- 1. register -------------------------------------------------------
    # ---- 1. 注册 -----------------------------------------------------------
    print("=== 1. Registry.Register ===")
    message = QDBusMessage.createMethodCall(PORTAL_BUS, PORTAL_PATH, REGISTRY, "Register")
    message << app_id << {}
    reply = bus.call(message, QDBus.CallMode.Block, 8_000)
    if reply.type() == QDBusMessage.MessageType.ErrorMessage:
        print("  REFUSED:", reply.errorName(), "-", reply.errorMessage())
        registered = False
    else:
        print("  accepted, arguments:", reply.arguments())
        registered = True

    # ---- 2. retry CreateSession on the same connection ---------------------
    # ---- 2. 在同一连接上重试 CreateSession ---------------------------------
    print()
    print("=== 2. CreateSession after registering ===")
    message = QDBusMessage.createMethodCall(
        PORTAL_BUS, PORTAL_PATH, SHORTCUTS, "CreateSession")
    message << {"handle_token": "regprobe", "session_handle_token": "regprobe"}
    reply = bus.call(message, QDBus.CallMode.Block, 8_000)
    if reply.type() == QDBusMessage.MessageType.ErrorMessage:
        print("  REFUSED:", reply.errorName(), "-", reply.errorMessage())
        session_ok = False
    else:
        print("  accepted, arguments:", reply.arguments())
        session_ok = True

    print()
    print("VERDICT / 判定")
    if registered and session_ok:
        print("  registering the app id is what this portal needs; the global hotkey can be")
        print("  implemented through the portal after a single Registry.Register call")
        print("  注册 app id 正是此后端门户所需的；一次 Registry.Register 之后即可经门户实现全局热键")
        return 0
    if not registered:
        print("  the registry refused the app id outright, so the portal route is unavailable")
        print("  here and the hotkey must fall back to a compositor binding")
        print("  注册表直接拒绝了该 app id，因此此门户路线不可用，热键必须回退到合成器绑定")
        return 0
    print("  registration succeeded but the session is still refused: the backend has no")
    print("  global-shortcut provider, so the hotkey must fall back to a compositor binding")
    print("  注册成功但会话仍被拒：后端没有全局快捷键提供者，因此热键必须回退到合成器绑定")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
