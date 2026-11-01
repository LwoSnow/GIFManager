"""Exercise the Wayland GlobalShortcuts PROTOCOL with a fake D-Bus transport.

# What this can and cannot prove

`gifmanager/platform/linux.py` cannot run here: there is no Linux, no Wayland, no
portal. Rather than ship the portal code untested, the D-Bus transport is behind
`PortalBus` and this file substitutes a fake for it — so the STATE MACHINE is
verified even though the wire format is not.

What is genuinely covered:

* a session is opened ONCE and reused, so a single close releases every binding;
* the compositor's reply WINS over the requested combination, because the portal is
  allowed to substitute one and believing the request would display a shortcut that
  does nothing;
* `Activated` dispatches by shortcut id, including the string form the portal sends;
* a bind failure keeps the session so a retry does not pay for a new one;
* `unregister_all` closes the session, which is the only thing that actually releases
  a compositor binding;
* an unreachable portal reports a reason instead of attempting a call.

What is NOT covered, and must be tested on real hardware: that xdg-desktop-portal
accepts these argument types in this order, and that a compositor's
`trigger_description` spelling parses. The parser's handling of the spellings real
desktops emit IS covered by `_binding_from_trigger` cases below.

# 本脚本能证明与不能证明什么

`gifmanager/platform/linux.py` 在此无法运行：没有 Linux、没有 Wayland、没有门户。与其
让门户代码未经验证就发布，D-Bus 传输被放在 `PortalBus` 之后，本文件用伪实现替换它——因此
"状态机"得到验证，尽管线上格式没有。

真正被覆盖的：

* 会话只打开"一次"并复用，使一次关闭即释放每个绑定；
* 合成器的回复"优先于"请求的组合，因为门户被允许替换它，而相信请求会显示一个无效的快捷键；
* `Activated` 按快捷方式 id 分发，包括门户发送的字符串形式；
* 绑定失败时会话保留，使重试无需再开一个；
* `unregister_all` 关闭会话，而那是唯一真正释放合成器绑定的操作；
* 门户不可达时报告原因，而不是尝试调用。

"没有"被覆盖、必须在真机测试的：xdg-desktop-portal 是否按此顺序接受这些参数类型，以及合成器
的 `trigger_description` 写法能否解析。解析器对真实桌面所输出写法的处理"已"由下面的
`_binding_from_trigger` 用例覆盖。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gifmanager.core import hotkeys as hotkey_core
from gifmanager.platform import linux as L


def section(title):
    print()
    print("=" * 4, title)


class FakePortalBus:
    # A stand-in for `PortalBus` that records calls and returns scripted replies.
    # `PortalBus` 的替身，记录调用并返回预设回复。

    def __init__(self):
        self.calls = []
        self.sessions = []
        self.closed = []
        self.subscriptions = []
        self.handlers = {}
        # Scripted behaviour / 预设行为
        self.session_handle = "/org/freedesktop/portal/desktop/session/fake"
        # None means "echo the requested trigger", which is what a permissive
        # compositor does. / None 表示"回显请求的触发器"，这是宽容的合成器会做的事。
        self.bind_reply = None
        # An error string, to make BindShortcuts fail. /
        # 一个错误字符串，使 BindShortcuts 失败。
        self.fail_bind = None
        # An error string, to make CreateSession fail. /
        # 一个错误字符串，使 CreateSession 失败。
        self.fail_create = None
        self.subscribe_ok = True

    def call(self, method, arguments, timeout_ms=None):
        self.calls.append((method, arguments, timeout_ms))
        if method == "CreateSession":
            if self.fail_create:
                return None, self.fail_create
            self.sessions.append(self.session_handle)
            return [{"session_handle": self.session_handle}], ""
        if method == "BindShortcuts":
            if self.fail_bind:
                return None, self.fail_bind
            session, shortcuts = arguments[0], arguments[1]
            if self.bind_reply is not None:
                return [self.bind_reply], ""
            # Echo what was proposed, which is what a permissive compositor does.
            # 回显被建议的内容，这是宽容的合成器会做的事。
            entries = []
            for shortcut_id, properties, _triggers in shortcuts:
                entries.append((shortcut_id, {
                    "trigger_description": properties.get("preferred_trigger", ""),
                }, []))
            return [{"shortcuts": entries}], ""
        return None, f"unexpected method {method}"

    def subscribe(self, signal, handler):
        self.subscriptions.append(signal)
        self.handlers[signal] = handler
        return self.subscribe_ok

    def close_session(self, session_path):
        self.closed.append(session_path)
        return True

    def emit(self, signal, *arguments):
        handler = self.handlers.get(signal)
        if handler is not None:
            handler(*arguments)


class Reachable(L.WaylandHotkeyBackend):
    # The real backend with the capability probe forced on, so the protocol can run
    # without a portal. Only the PROBE is overridden; every protocol path is the real
    # code.
    # 真实后端，但强制打开能力探测，使协议能在没有门户时运行。只覆盖"探测"；每条协议路径
    # 都是真实代码。

    def __init__(self, bus):
        self._bus = bus
        self._session = ""
        self._bindings = {}
        self._callbacks = {}
        self._requested = {}
        self._error = ""
        self._subscribed = False
        self._token_counter = 0
        self._available = True
        self._reason = ""


def main():
    problems = []
    binding = hotkey_core.HotkeyBinding(
        hotkey_core.MOD_CTRL | hotkey_core.MOD_ALT, "F9")
    print("requested binding:", binding.describe())

    section("a session is opened once and reused")
    bus = FakePortalBus()
    backend = Reachable(bus)
    fired = []
    token = backend.register(0, binding, lambda: fired.append("first"))
    print("token            :", token)
    print("CreateSession x  :", sum(1 for c in bus.calls
                                    if c[0] == "CreateSession"))
    if token != bus.session_handle:
        problems.append(f"register returned {token!r}, expected the session path")
    if sum(1 for c in bus.calls if c[0] == "CreateSession") != 1:
        problems.append("the session was created more than once for one register")

    # A second registration must reuse the session, because a single close has to
    # release everything.
    # 第二次注册必须复用会话，因为一次关闭必须释放全部。
    other = hotkey_core.HotkeyBinding(
        hotkey_core.MOD_CTRL | hotkey_core.MOD_SHIFT, "K")
    backend.register(1, other, lambda: fired.append("second"))
    creates = sum(1 for c in bus.calls if c[0] == "CreateSession")
    print("after 2nd register, CreateSession x:", creates)
    if creates != 1:
        problems.append(f"the second register created {creates} sessions")
    if len(bus.sessions) != 1:
        problems.append("two bindings did not share one session")

    section("Activated dispatches by shortcut id")
    bus.emit("Activated", bus.session_handle, "0", 0, {})
    bus.emit("Activated", bus.session_handle, "1", 0, {})
    print("fired            :", fired)
    if fired != ["first", "second"]:
        problems.append(f"dispatch produced {fired}, expected both callbacks")
    # An unknown id must be ignored, not raise: a compositor can send a stale signal.
    # 未知 id 必须被忽略而不是抛错：合成器可能发送过期信号。
    bus.emit("Activated", bus.session_handle, "999", 0, {})
    print("after unknown id :", fired, "(unchanged)")
    if len(fired) != 2:
        problems.append("an unknown shortcut id produced a callback")

    section("the compositor's SUBSTITUTED binding wins")
    bus2 = FakePortalBus()
    # A compositor that binds something else, which is the whole reason the reply is
    # the authority.
    # 一个绑定了别的东西的合成器，这正是回复才是权威的全部理由。
    bus2.bind_reply = {"shortcuts": [("0", {
        "trigger_description": "Super+Q",
    }, [])]}
    backend2 = Reachable(bus2)
    backend2.register(0, binding, lambda: None)
    actual = backend2.last_binding(0)
    print("requested        :", binding.describe())
    print("actually bound   :", actual.describe() if actual else None)
    if actual is None:
        problems.append("the substituted binding was not recorded")
    elif actual.describe() == binding.describe():
        problems.append(
            "the requested binding was kept although the compositor substituted one; "
            "the UI would show a shortcut that does nothing")
    elif "Super" not in actual.describe():
        problems.append(f"the substituted binding parsed as {actual.describe()!r}")

    section("a bind failure keeps the session for a retry")
    bus3 = FakePortalBus()
    bus3.fail_bind = "the user dismissed the dialog"
    backend3 = Reachable(bus3)
    result = backend3.register(0, binding, lambda: None)
    print("register         :", result)
    print("CreateSession x  :", sum(1 for c in bus3.calls
                                    if c[0] == "CreateSession"))
    print("session kept     :", backend3.session_path() not in ("", None))
    print("error            :", backend3.last_error())
    if result is not None:
        problems.append("a failed bind returned a token")
    if backend3.session_path() in ("", None):
        problems.append("a failed bind discarded the session, so a retry would "
                        "pay for a new one")
    if "dismissed" not in backend3.last_error():
        problems.append("the refusal reason was not recorded for the UI")

    section("a create failure reports instead of pretending")
    bus4 = FakePortalBus()
    bus4.fail_create = "no portal on this bus"
    backend4 = Reachable(bus4)
    result = backend4.register(0, binding, lambda: None)
    print("register         :", result)
    print("error            :", backend4.last_error())
    if result is not None:
        problems.append("a failed session creation returned a token")
    if "no portal" not in backend4.last_error():
        problems.append("the session failure was not recorded")

    section("unregister_all closes the session, releasing the binding")
    bus5 = FakePortalBus()
    backend5 = Reachable(bus5)
    backend5.register(0, binding, lambda: None)
    print("session before   :", backend5.session_path())
    backend5.unregister_all()
    print("closed           :", bus5.closed)
    print("session after    :", backend5.session_path() or "(released)")
    if not bus5.closed:
        problems.append("unregister_all did not close the portal session, so the "
                        "compositor binding would stay held")
    if backend5.session_path():
        problems.append("the session path survived unregister_all")

    section("an unreachable portal says why")
    # The REAL class with no transport and an explicit "unavailable" verdict, because the
    # PROBE now lives in the frontend: it needs Qt, and the platform layer may not import
    # a GUI toolkit. So the backend is TOLD, and this checks that being told "no" is
    # honoured rather than ignored.
    #
    # 没有传输层、且显式给出"不可用"判定的"真实"类，因为"探测"现在位于前端：它需要 Qt，而
    # 平台层不得导入界面工具包。因此后端是"被告知"的，而这里检查"被告知否"被遵守而非忽略。
    real = L.WaylandHotkeyBackend(bus=None, available=False,
                                  reason="not Linux")
    print("available        :", real.available)
    print("reason           :", real.unavailable_reason())
    print("register         :", real.register(0, binding, lambda: None))
    if real.available:
        problems.append("the portal reported itself available with no transport")
    if not real.unavailable_reason():
        problems.append("an unavailable portal gave no reason")
    if real.register(0, binding, lambda: None) is not None:
        problems.append("an unavailable backend still returned a token")

    section("a backend with no transport refuses even when told it is available")
    # The transport is what makes the protocol possible, so its absence must be fatal to
    # `available` regardless of what the probe said — otherwise the first `register` would
    # raise AttributeError on `None.call`.
    # 传输层是协议得以进行的前提，因此它的缺失必须使 `available` 为假，无论探测说了什么
    # ——否则第一次 `register` 会在 `None.call` 上抛 AttributeError。
    no_transport = L.WaylandHotkeyBackend(bus=None, available=True)
    print("available        :", no_transport.available)
    print("reason           :", no_transport.unavailable_reason())
    if no_transport.available:
        problems.append("a backend with no transport reported itself available")
    if not no_transport.unavailable_reason():
        problems.append("a missing transport gave no reason")

    section("trigger spellings real desktops emit")
    cases = (
        ("Ctrl+Alt+F9", "Ctrl+Alt+F9"),
        ("Super+Q", "Super+Q"),
        ("Mod4+Q", "Super+Q"),
        ("LOGO+K", "Super+K"),
        ("ALT+Shift+space", "Alt+Shift+Space"),
        ("Control+Mod1+P", "Ctrl+Alt+P"),
    )
    for text, expected in cases:
        parsed = L._binding_from_trigger(text)
        got = parsed.describe() if parsed else None
        flag = "OK " if got == expected else "DIFF"
        print(f"  [{flag}] {text!r:18} -> {got!r} (expected {expected!r})")
        if got != expected:
            problems.append(f"{text!r} parsed as {got!r}, expected {expected!r}")
    # A description with no key must NOT become a binding: storing a guess would
    # display a wrong shortcut as if it worked.
    # 没有按键的描述"不得"变成绑定：存下一个猜测会把错误快捷键显示得像是有效的。
    for text in ("", "   ", "Ctrl+", "Ctrl+Alt"):
        parsed = L._binding_from_trigger(text)
        print(f"  [{'OK ' if parsed is None else 'BAD'}] {text!r:18} -> "
              f"{parsed.describe() if parsed else None}")
        if parsed is not None:
            problems.append(f"{text!r} produced a binding out of nothing")

    print()
    if problems:
        print("WAYLAND PROTOCOL CHECK FAILED / Wayland 协议检查未通过")
        for problem in problems:
            print("  " + problem)
        return 1
    print("WAYLAND PROTOCOL CHECK OK / Wayland 协议检查通过")
    print("  the session is opened once and reused, the compositor's substituted")
    print("  binding wins, Activated dispatches by id, a bind failure keeps the")
    print("  session, unregister_all releases it, and an unreachable portal")
    print("  explains itself")
    print("  会话只开一次并复用、合成器替换的绑定优先、Activated 按 id 分发、绑定失败保留")
    print("  会话、unregister_all 释放它、门户不可达时说明原因")
    print()
    print("  NOT verifiable without hardware / 无硬件无法验证：")
    print("    that xdg-desktop-portal accepts these argument types in this order /")
    print("    xdg-desktop-portal 是否按此顺序接受这些参数类型")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
