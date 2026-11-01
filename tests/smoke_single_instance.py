"""Check that Linux enforces a single instance AND can deliver a command to the owner.

Both halves matter on Wayland, and neither existed:

  * the base backend `acquire` returns `(True, None)` — "you are the only instance" — so on Linux
    two copies could run and both open the same SQLite database, which is the failure the check
    exists to prevent;
  * with no working global-hotkey API (X11 grab needs X11; the XDG portal's `BindShortcuts` needs
    an `a(sa{sv})` argument PySide6 cannot build), the documented way to bind a key is a
    compositor binding that RUNS A COMMAND. That command has to reach the running instance rather
    than start a second one, so the single-instance channel doubles as the command channel.

两部分在 Wayland 上都重要，而它们此前都不存在：

  * 基类 `acquire` 返回 `(True, None)`——"你是唯一实例"——因此 Linux 上两份拷贝可以同时运行并同时
    打开同一个 SQLite 数据库，正是该检查要防止的失败；
  * 在没有任何可用全局热键 API 的情况下（X11 抓取需要 X11；XDG 门户的 `BindShortcuts` 需要 PySide6
    无法构造的 `a(sa{sv})` 参数），绑定按键的既定方式是一条"运行命令"的合成器绑定。该命令必须到达
    运行中的实例而不是启动第二个，因此单实例通道同时充当命令通道。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# A name unique to this run, so a real instance of the application cannot interfere and this check
# cannot leave a name behind that blocks a later run.
# 本次运行专属的名字，使真实的应用实例无法干扰，且本检查无法留下一个会阻塞后续运行的名字。
PROBE_NAME = f"GIFManagerTest-{os.getpid()}"

# The commands the channel accepts. Anything else must be refused, because this is an
# inter-process channel and acting on arbitrary text would be a way to drive the application from
# outside.
# 通道接受的命令。其他内容必须被拒，因为这是一条进程间通道，对任意文本采取行动会成为从外部驱动
# 应用的手段。
VALID_COMMANDS = ("toggle", "show", "hide", "quit")


def main():
    from gifmanager import platform as platform_layer

    problems = []
    service = platform_layer.single_instance()
    print("backend        :", type(service).__name__)
    print("available      :", service.available)
    if not service.available:
        print("SINGLE INSTANCE CHECK SKIPPED / 单实例检查已跳过")
        print("  this platform's single-instance backend reports unavailable")
        return 0

    # How many copies of this application a second launch may start.
    # 第二次启动最多可以启动多少份本应用。
    print()
    print("==== 1. only one owner ====")
    acquired, handle = service.acquire(PROBE_NAME)
    print("  first acquire :", acquired)
    if not acquired:
        problems.append(
            "the first acquire failed, so the application could never start")
    second, second_handle = service.acquire(PROBE_NAME)
    print("  second acquire:", second, "(must be False)")
    if second:
        problems.append(
            "a second acquire succeeded, so two copies could run and both open the database")
        service.release(second_handle)

    # ---- 2. a command reaches the owner ------------------------------------
    # ---- 2. 命令能到达持有者 -----------------------------------------------
    #
    # The command channel is a LINUX feature, and only Linux has it: it exists because Wayland
    # gives a client no global-hotkey API and the XDG portal cannot be driven from PySide6, so the
    # documented workaround is a compositor key binding that runs `--toggle`. Windows keeps a named
    # mutex (an `int` handle, no socket, no `drain`), which is a real platform difference rather
    # than a defect - so this section runs only when the backend actually offers a channel, and
    # fails only where the channel is REQUIRED.
    #
    # On Windows the first version of this check called `handle.drain()` on that int and died with
    # `AttributeError: 'int' object has no attribute 'drain'`.
    # 命令通道是"Linux"特性，也只有 Linux 有：它存在是因为 Wayland 不提供全局热键 API，而 XDG 门户
    # 无法从 PySide6 驱动，因此既定的变通做法是一条运行 `--toggle` 的合成器键绑定。Windows 用的是
    # 命名互斥量（`int` 句柄，无套接字、无 `drain`），这是真实的平台差异而非缺陷——因此本节只在后端
    # 确实提供通道时运行，且只在"要求"该通道的平台上失败。
    #
    # 在 Windows 上，本检查的第一个版本对那个 int 调用 `handle.drain()`，以
    # `AttributeError: 'int' object has no attribute 'drain'` 崩掉。
    channel = handle is not None and callable(getattr(handle, "drain", None))
    if not channel:
        from gifmanager.platform import current as current_platform

        key = current_platform().key
        if key.startswith("linux"):
            problems.append(
                "the Linux backend has no command channel, so a compositor key binding could "
                "never reach the running instance")
        else:
            print()
            print("==== 2-6. the command channel ====")
            print(f"  SKIPPED on {key!r}: this platform's single instance keeps a named lock and")
            print("  offers no command channel, which is a documented platform difference")
            print(f"  在 {key!r} 上跳过：该平台的单实例使用命名锁，不提供命令通道，这是已记录的")
            print("  平台差异")
            if handle is not None:
                service.release(handle)
            print()
            if problems:
                print("SINGLE INSTANCE CHECK FAILED / 单实例检查未通过")
                for problem in problems:
                    print("  " + problem)
                return 1
            print("SINGLE INSTANCE CHECK OK / 单实例检查通过")
            print("  one owner; the command channel is not provided on this platform")
            print("  只有一个持有者；本平台不提供命令通道")
            return 0

    print()
    print("==== 2. the command channel ====")
    delivered = service.notify(PROBE_NAME, "toggle")
    print("  notify toggle :", delivered)
    if not delivered:
        problems.append("a compositor key binding could not reach the running instance")
    received = handle.drain()
    print("  drained       :", received)
    if received != ["toggle"]:
        problems.append(
            f"the owner received {received!r} instead of exactly ['toggle']")

    # Draining twice must not repeat a command: a toggle delivered twice would hide the window the
    # user just asked to see.
    # 第二次 drain 不得重复投递：一次被投递两次的 toggle 会隐藏用户刚要求显示的窗口。
    print("  drained again :", handle.drain())
    if handle.drain():
        problems.append("draining twice repeated a command, so the window would toggle twice")

    # ---- 3. an unknown command is refused ----------------------------------
    # ---- 3. 未知命令被拒 ---------------------------------------------------
    print()
    print("==== 3. an unknown command is refused ====")
    refused = service.notify(PROBE_NAME, "rm -rf /")
    print("  notify garbage:", refused)
    if refused:
        problems.append(
            "an arbitrary string was delivered as a command, so anything on the session bus "
            "could drive the application")
    if handle.drain():
        problems.append("a refused command still reached the owner")

    # Every advertised command must be accepted, or the key binding documentation is a lie.
    # 每个对外宣称的命令都必须被接受，否则键绑定文档就是在说谎。
    print()
    print("==== 4. every advertised command is accepted ====")
    for command in VALID_COMMANDS:
        if not service.notify(PROBE_NAME, command):
            problems.append(f"the advertised command {command!r} was refused")
    drained = handle.drain()
    print("  drained       :", drained)
    if sorted(drained) != sorted(VALID_COMMANDS):
        problems.append(
            f"draining gave {drained!r}, expected all of {list(VALID_COMMANDS)!r}")

    # ---- 5. release frees the name -----------------------------------------
    # ---- 5. 释放会腾出名字 -------------------------------------------------
    print()
    print("==== 5. release frees the name ====")
    service.release(handle)
    third, third_handle = service.acquire(PROBE_NAME)
    print("  acquire again :", third)
    if not third:
        problems.append(
            "the name stayed taken after release, so a restart would be refused as 'already "
            "running'")
    service.release(third_handle)

    # ---- 6. a crashed owner does not wedge the name ------------------------
    # ---- 6. 崩溃的持有者不会卡住名字 ---------------------------------------
    #
    # This is the reason the backend uses an ABSTRACT socket rather than a lock file: the kernel
    # drops the name when the process dies, so a crash cannot leave a lock that makes the
    # application refuse to start. Simulated here by closing the handle without releasing it,
    # which is what a crash effectively does.
    # 这正是后端使用"抽象"套接字而非锁文件的原因：进程死亡时内核会丢弃该名字，因此崩溃不会留下一个
    # 让应用拒绝启动的锁。此处通过关闭句柄而不调用 release 来模拟，那正是崩溃的等效行为。
    print()
    print("==== 6. a crashed owner does not wedge the name ====")
    crashed, crashed_handle = service.acquire(PROBE_NAME)
    if crashed and crashed_handle is not None:
        close = getattr(crashed_handle, "close", None)
        if callable(close):
            close()
    after_crash, after_handle = service.acquire(PROBE_NAME)
    print("  acquire after  :", after_crash)
    if not after_crash:
        problems.append(
            "the name stayed taken after the owner's socket closed, so a crashed instance would "
            "block every later start")
    service.release(after_handle)

    print()
    if problems:
        print("SINGLE INSTANCE CHECK FAILED / 单实例检查未通过")
        for problem in problems:
            print("  " + problem)
        return 1
    print("SINGLE INSTANCE CHECK OK / 单实例检查通过")
    print("  one owner, commands reach it exactly once, garbage is refused, and both release and")
    print("  a crash free the name")
    print("  只有一个持有者、命令恰好送达一次、垃圾被拒，且释放与崩溃都会腾出名字")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
