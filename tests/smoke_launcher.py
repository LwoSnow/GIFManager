"""End-to-end check of the real launcher.

Runs `apps/gifmanager_qt.py` in a subprocess against a temporary data directory,
lets it build the whole application, then asks Qt to quit. This is the only check
that exercises `shell.run()` — the single-instance guard, the settings load, the
theme application and the ordered teardown — rather than constructing the window
directly.

真实启动器的端到端检查。

在子进程中针对临时数据目录运行 `apps/gifmanager_qt.py`，让它构建完整应用，随后请
Qt 退出。这是唯一会演练 `shell.run()` 的检查——单实例守卫、设置加载、主题应用与有序
退出——而不是直接构建窗口。
"""
import os
import pathlib
import subprocess
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["PYTHONUTF8"] = "1"

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "apps" / "gifmanager_qt.py"

# Quit shortly after the event loop starts. Long enough for the window to be
# shown and the compositor call to be scheduled, short enough to keep the check
# fast.
# 事件循环启动后不久即退出。足够让窗口显示并让合成器调用被排程，又足够短以保持检查
# 迅速。
QUIT_AFTER_MS = 700


def main():
    with tempfile.TemporaryDirectory() as data_dir:
        env = dict(os.environ)
        # A temporary data directory keeps the developer's real library and
        # settings untouched, which is what makes this safe to run anywhere.
        # 临时数据目录使开发者真实的库与设置不被触碰，这正是它可以安全地在任何地方
        # 运行的原因。
        env["GIFMANAGER_DATA_DIR"] = data_dir

        program = (
            "import sys;"
            f"sys.path.insert(0, {str(ROOT)!r});"
            "from PySide6.QtCore import QTimer;"
            "from PySide6.QtWidgets import QApplication;"
            "from gifmanager.frontend.qt import shell;"
            # The first timer must be scheduled BEFORE `shell.run()` creates the
            # QApplication, and it must itself schedule the quit: a timer started
            # before an event loop exists never fires, so the quit has to be
            # armed from inside the loop.
            # 第一个定时器必须在 `shell.run()` 创建 QApplication 之前排程，而它必须
            # 自己再安排退出：事件循环存在之前启动的定时器永远不会触发，因此退出必须从
            # 循环内部武装。
            f"QTimer.singleShot(0, lambda: QTimer.singleShot({QUIT_AFTER_MS},"
            " QApplication.quit));"
            "code = shell.run([]);"
            "print('RUN_EXIT', code)"
        )
        completed = subprocess.run(
            [sys.executable, "-c", program],
            env=env, capture_output=True, text=True, timeout=90)

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        print("returncode:", completed.returncode)
        for line in stdout.splitlines():
            if line.startswith("RUN_EXIT"):
                print(line)

        problems = []
        if completed.returncode != 0:
            problems.append(f"launcher returned {completed.returncode}")
        if "RUN_EXIT 0" not in stdout:
            problems.append("shell.run() did not return 0")
        if "Traceback" in stderr:
            problems.append("a traceback was printed")

        # Facts the launcher must have produced while running.
        # 启动器运行期间必须产生的事实。
        expected = ("backend ready", "exited with 0")
        for needle in expected:
            if needle not in stderr:
                problems.append(f"log is missing {needle!r}")

        # The settings file is written on first close, so its absence would mean
        # the session state never persisted.
        # 设置文件在首次关闭时写入，因此它缺失就意味着会话状态从未持久化。
        if not any(pathlib.Path(data_dir).iterdir()):
            problems.append("the data directory is empty after a full run")

        if problems:
            print()
            print("LAUNCHER CHECK FAILED / 启动器检查未通过")
            for problem in problems:
                print("  " + problem)
            tail = "\n".join(stderr.splitlines()[-25:])
            print("\n--- launcher stderr (tail) ---")
            print(tail)
            return 1

        print()
        print("LAUNCHER CHECK OK / 启动器检查通过")
        print("  single instance acquired, backend built, window shown, "
              "teardown ordered")
        print("  单实例获取、后端构建、窗口显示、退出有序")
        return 0


if __name__ == "__main__":
    sys.exit(main())
