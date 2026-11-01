"""End-to-end check of the REAL QML launcher.

Runs `apps/gifmanager_qml.py` in a subprocess against a temporary data directory, lets
it build the whole application, then asks Qt to quit. This is the only check that
exercises `qml.app.run()` — the application object, the single-instance guard, the
backend, the engine and the ordered teardown.

# Why this file exists

The shipped QML launcher could not start at all, and **no test noticed**, because:

* `smoke_qml.py` calls `create_engine()` directly, and
* every other QML check builds its own `QApplication` first.

So the real entry point — the thing a user actually runs — was the one code path with no
coverage. It raised "a QGuiApplication must exist before the QML interface is loaded",
which is a message about a missing object rather than about the launcher forgetting to
build it. A test that runs the launcher the way a user does is the only kind that could
have caught that.

真实 QML 启动器的端到端检查。

在子进程中针对临时数据目录运行 `apps/gifmanager_qml.py`，让它构建完整应用，随后请 Qt 退出。
这是唯一会演练 `qml.app.run()` 的检查——应用对象、单实例守卫、后端、引擎与有序退出。

# 本文件为什么存在

随包的 QML 启动器完全无法启动，而**没有任何测试注意到**，因为：

* `smoke_qml.py` 直接调用 `create_engine()`，且
* 其他每个 QML 检查都先自行构建 `QApplication`。

因此真实入口——用户实际运行的那个东西——是唯一没有覆盖的代码路径。它抛出
"a QGuiApplication must exist before the QML interface is loaded"，那是一条关于"缺少对象"的
消息，而不是关于"启动器忘了构建它"。只有按用户的方式运行启动器的测试才可能抓到它。
"""
import os
import pathlib
import subprocess
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["PYTHONUTF8"] = "1"

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "apps" / "gifmanager_qml.py"

# Quit shortly after the event loop starts: long enough for the engine to load and the
# first paint to happen, short enough to keep the check fast.
# 事件循环启动后不久即退出：足够让引擎加载并发生首次绘制，又足够短以保持检查迅速。
QUIT_AFTER_MS = 900

# The application object the QML front-end must build.
#
# `QApplication`, not `QGuiApplication`. This looks like an unnecessary dependency for a
# QML interface, and it was "corrected" to `QGuiApplication` once — which broke the system
# tray, because `QSystemTrayIcon` is a `QtWidgets` class. The tray is created by the QML
# root on every start, so the failure was immediate and its message
# (`QWidget: Cannot create a QWidget without QApplication`) named neither the tray nor the
# application class.
#
# Asserted here rather than left implicit because the wrong choice is the one that looks
# tidier, so a future reader is likely to reach for it again.
#
# QML 前端必须构建的应用对象。
#
# `QApplication` 而不是 `QGuiApplication`。对一个 QML 界面来说这看起来像不必要的依赖，而它
# 曾被"改正"为 `QGuiApplication`——那弄坏了系统托盘，因为 `QSystemTrayIcon` 是 `QtWidgets`
# 类。托盘由 QML 根对象在每次启动时创建，因此失败是立即的，而它的消息
# （`QWidget: Cannot create a QWidget without QApplication`）既没点名托盘、也没点名应用类。
#
# 在此断言而不是留作隐含，因为错误的选择恰恰是看起来更整洁的那个，未来的读者很可能再次选它。
REQUIRED_APPLICATION = "QApplication"


def main():
    problems = []

    if not LAUNCHER.is_file():
        print("QML LAUNCHER MISSING / QML 启动器缺失:", LAUNCHER)
        return 1

    with tempfile.TemporaryDirectory() as data_dir:
        env = dict(os.environ)
        # A temporary data directory keeps the developer's real library and settings
        # untouched, which is what makes this safe to run anywhere.
        # 临时数据目录使开发者真实的库与设置不被触碰，这正是它可以安全地在任何地方运行的原因。
        env["GIFMANAGER_DATA_DIR"] = data_dir

        # `run()` owns the application object, so the quit must be armed from INSIDE the
        # event loop: a timer started before a loop exists never fires. Arming it from the
        # first timer is the standard trick, and it is why `run` cannot be given a
        # "quit after N" argument.
        # `run()` 拥有应用对象，因此退出必须从事件循环"内部"武装：在循环存在之前启动的定时器
        # 永远不会触发。用第一个定时器武装它是标准做法，也正是 `run` 不能接收"N 毫秒后退出"参数
        # 的原因。
        program = (
            "import sys;"
            f"sys.path.insert(0, {str(ROOT)!r});"
            "from PySide6.QtCore import QTimer;"
            "from PySide6.QtGui import QGuiApplication;"
            "from gifmanager.frontend.qml import app as qml_app;"
            # Report the application class BEFORE the loop runs, so a wrong choice is named
            # as such rather than surfacing as a widgets abort deep inside the interface.
            # 在循环运行"之前"报告应用类，使错误的选择被如实点名，而不是在界面深处表现为控件中止。
            "built = qml_app.build_application([]);"
            "print('APPLICATION_CLASS', type(built).__name__);"
            f"QTimer.singleShot(0, lambda: QTimer.singleShot({QUIT_AFTER_MS},"
            " QGuiApplication.quit));"
            "code = qml_app.run([]);"
            "print('RUN_EXIT', code)"
        )
        completed = subprocess.run(
            [sys.executable, "-c", program],
            env=env, capture_output=True, text=True, timeout=120)

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        print("returncode:", completed.returncode)
        for line in stdout.splitlines():
            if line.startswith(("RUN_EXIT", "APPLICATION_CLASS")):
                print(line)

        # The application class, asserted explicitly. See REQUIRED_APPLICATION above for why
        # this is worth a line of its own.
        # 应用类被明确断言。理由见上方 REQUIRED_APPLICATION。
        reported = ""
        for line in stdout.splitlines():
            if line.startswith("APPLICATION_CLASS"):
                reported = line.split()[-1]
        if reported != REQUIRED_APPLICATION:
            problems.append(
                f"the launcher built {reported or 'nothing'} but the QML front-end needs "
                f"{REQUIRED_APPLICATION} — its system tray is a QtWidgets object")

        if completed.returncode != 0:
            problems.append(f"the launcher returned {completed.returncode}")
        if "RUN_EXIT 0" not in stdout:
            problems.append("qml_app.run() did not return 0")
        if "Traceback" in stderr:
            problems.append("a traceback was printed")
        # The specific failure this file was written for.
        # 本文件正是为了这一个失败而写的。
        if "QGuiApplication must exist" in stderr:
            problems.append(
                "the launcher did not build the application object; `run()` is supposed "
                "to own the whole bootstrap")

        # Facts the launcher must have produced while running. Each names a step of the
        # bootstrap, so a missing one says WHICH step was skipped rather than only that
        # something went wrong.
        # 启动器运行期间必须产生的事实。每一条都点名引导过程中的一步，因此缺失某条会说明"哪一步"
        # 被跳过，而不只是"出了问题"。
        expected = (
            ("starting (QML)", "the bootstrap log line"),
            ("controls style is Basic", "the Qt Quick Controls style selection"),
            ("interface loaded", "the engine load"),
            ("QML shell exited", "the ordered teardown"),
        )
        for needle, label in expected:
            if needle not in stderr:
                problems.append(f"the log is missing {label} ({needle!r})")

        # RUNTIME QML DIAGNOSTICS, which only a child process can reveal.
        #
        # Qt writes its QML errors to stderr and never to this application's logger, and
        # `QQmlApplicationEngine.warnings()` holds only LOAD-time diagnostics. So
        # `Main.qml` printed "ReferenceError: parent is not defined" on every theme switch while
        # `smoke_qml` reported zero warnings and passed — the handler was dead and the resize
        # grip kept the first theme's colour.
        #
        # This check captures a real process's stderr, so it is the one that can see them.
        # 运行时 QML 诊断，只有子进程能揭示。
        #
        # Qt 把 QML 错误写到 stderr、从不写入本应用的日志器，而
        # `QQmlApplicationEngine.warnings()` 只保留"加载期"诊断。因此 `Main.qml` 在每次主题切换时
        # 打印 "ReferenceError: parent is not defined"，而 `smoke_qml` 报告零警告并通过——那个处理
        # 函数是死的，尺寸抓手一直保留首个主题的颜色。
        #
        # 本检查捕获真实进程的 stderr，因此它是能看到这些的那一个。
        for marker in ("ReferenceError", "TypeError: Cannot read property",
                       "is not defined", "Unable to assign"):
            if marker in stderr:
                for line in stderr.splitlines():
                    if marker in line:
                        problems.append(
                            f"a runtime QML diagnostic the engine's warning list does not "
                            f"carry: {line.strip()[:140]}")
                        break

        # The backend must really have been built: a window with no backend would still
        # print "interface loaded" but show nothing.
        # 后端必须真的被构建：没有后端的窗口仍会打印 "interface loaded"，但什么都不显示。
        if "backend ready" not in stderr:
            problems.append("the backend was never built")

        # And it must have been closed, or the database handle leaks past the process.
        # 而且它必须被关闭，否则数据库句柄会泄漏到进程之外。
        if "backend close" in stderr or "backend: closed" in stderr:
            pass
        elif "exited with 0" not in stderr and "shell exited with 0" not in stderr:
            problems.append("the launcher did not report a clean exit")

    # ---- the SECOND launch, which is a different code path ------------------
    #
    # A second launch is refused by the single-instance guard and shows a notice instead of
    # opening the database. That notice is the only window this front-end shows before a
    # backend exists, and the first version of it used a `QMessageBox` — which requires a
    # `QApplication`, while this front-end builds a `QGuiApplication`. The result was
    #
    #     QWidget: Cannot create a QWidget without QApplication
    #
    # and the process ABORTED. So launching twice killed the second copy with no message at
    # all, which is the worst possible outcome for a notice whose purpose is to explain the
    # refusal.
    #
    # It is checked here, in the same file, because both numbers are about the same entry
    # point and a reader looking at "does the launcher work" should see both answers.
    # 第二次启动，那是一条不同的代码路径。
    #
    # 第二次启动会被单实例守卫拒绝并显示一条提示，而不是打开数据库。那条提示是本前端在后端存在
    # 之前显示的唯一窗口，而它的第一个版本用了 `QMessageBox`——它需要 `QApplication`，而本前端
    # 构建的是 `QGuiApplication`。结果是
    #
    #     QWidget: Cannot create a QWidget without QApplication
    #
    # 且进程"中止"。因此启动两次会杀掉第二份且毫无提示，而这对一条目的在于解释拒绝的消息来说是最
    # 糟的结果。
    #
    # 它在同一个文件里检查，因为两个数字都是关于同一个入口的，而看"启动器是否可用"的读者应该同时
    # 看到两个答案。
    with tempfile.TemporaryDirectory() as data_dir:
        env = dict(os.environ)
        env["GIFMANAGER_DATA_DIR"] = data_dir
        program = (
            "import sys;"
            f"sys.path.insert(0, {str(ROOT)!r});"
            "from PySide6.QtCore import QTimer;"
            "from PySide6.QtGui import QGuiApplication;"
            "from gifmanager.frontend.qml import app as qml_app;"
            "import gifmanager.platform as pl;"
            # The application object comes FIRST. `QTimer.singleShot` before one exists
            # fails with "QObject::startTimer: current thread's event dispatcher has
            # already been destroyed", and `show_already_running` then loads a QML engine
            # with no application behind it. In production `run()` has already called
            # `build_application` by this point, so putting it here reproduces that order
            # rather than inventing a new one.
            # 应用对象放在"最前"。在它存在之前 `QTimer.singleShot` 会以
            # "QObject::startTimer: current thread's event dispatcher has already been
            # destroyed" 失败，随后 `show_already_running` 会在没有应用支撑的情况下加载 QML
            # 引擎。生产中 `run()` 此时已调用过 `build_application`，因此把它放在这里复现的是
            # 那个顺序，而不是发明一个新顺序。
            "qml_app.build_application([]);"
            "svc = pl.single_instance();"
            # Hold the first instance's handle for the whole run, so the second acquire
            # genuinely fails instead of racing.
            # 全程持有第一个实例的句柄，使第二次 acquire 真的失败而不是竞态。
            "got, handle = svc.acquire('GIFManager');"
            "print('FIRST_ACQUIRE', got);"
            # The notice runs its own event loop, so arm the quit before calling it.
            # 提示运行自己的事件循环，因此在调用它之前武装退出。
            "QTimer.singleShot(600, QGuiApplication.quit);"
            "qml_app.show_already_running();"
            "print('NOTICE_RETURNED')"
        )
        completed = subprocess.run(
            [sys.executable, "-c", program],
            env=env, capture_output=True, text=True, timeout=120)
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        print("second-launch returncode:", completed.returncode)
        for line in stdout.splitlines():
            if line.startswith(("FIRST_ACQUIRE", "NOTICE_RETURNED")):
                print(line)

        if "QWidget: Cannot create a QWidget without QApplication" in stderr:
            problems.append(
                "the already-running notice created a QWidget; a QML front-end has no "
                "QApplication, so the notice must be QML")
        if completed.returncode != 0:
            problems.append(
                f"the second launch exited with {completed.returncode}; a refusal must be "
                "clean")
        if "NOTICE_RETURNED" not in stdout:
            problems.append("show_already_running() did not return")
        if "RuntimeError" in stderr or "Traceback" in stderr:
            problems.append("the second launch printed a traceback")

    print()
    if problems:
        print("QML LAUNCHER CHECK FAILED / QML 启动器检查未通过")
        for problem in problems:
            print("  " + problem)
        print()
        print("--- stderr (last 20 lines) ---")
        for line in (stderr or "").splitlines()[-20:]:
            print("  " + line)
        return 1
    print("QML LAUNCHER CHECK OK / QML 启动器检查通过")
    print("  the real entry point builds the application object, the single-instance")
    print("  guard, the backend and the engine, then tears down in order — and a second")
    print("  launch is refused cleanly with a QML notice instead of a widgets crash")
    print("  真实入口构建了应用对象、单实例守卫、后端与引擎，随后按序退出——而第二次启动")
    print("  会被干净拒绝并显示 QML 提示，而不是控件崩溃")
    return 0


if __name__ == "__main__":
    import os as _os
    import sys as _sys

    _status = main()
    _sys.stdout.flush()
    _sys.stderr.flush()
    _os._exit(_status)
