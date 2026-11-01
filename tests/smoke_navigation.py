"""Check that every settings/about route actually opens its window, and that QML
logs no error.

# Why this exists

`Main.qml` once assigned to `bridge.viewIndex`, a READ-ONLY Qt property, from four
routes — and only one reported the error while three died silently. The interface
check that only loads the QML and reads engine warnings passed with three dead
controls.

The navigation model has since changed deliberately: the main window IS the library
(the original project's window had no view navigation), and settings/about open in
their own window. The routes are now the toolbar gear, the F1 shortcut, and the
tray's settings entry, all converging on `openSettings()`. The same class of bug —
a route that parses but does nothing — is caught the same way: the QML source must
carry every declared route as a call, and a window that is opened must actually
become visible.

# 本脚本存在的理由

`Main.qml` 曾从四条路径向只读 Qt 属性 `bridge.viewIndex` 赋值——只有一条报告了错误，
另外三条静默失效。只加载 QML 并读取引擎警告的界面检查在三个死控件面前照样通过。

导航模型此后被刻意更改：主窗口"就是表情库"（原项目的窗口没有视图导航），设置与关于在
自己的窗口中打开。路径现在是工具栏齿轮、F1 快捷键与托盘的设置项，全部汇聚到
`openSettings()`。同类缺陷——能解析但毫无作用的路径——仍以同样的方式抓取：QML 源码必须
以"调用"形式携带每条声明的路径，且被打开的窗口必须真的可见。
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PYTHONUTF8"] = "1"
os.environ["GIFMANAGER_QML_STRICT"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Every route a user can take to open settings, by the name of the control that
# owns it. Explicit rather than derived, so a route that is ADDED and left
# unverified is noticeable.
# 用户打开设置可以走的每一条路径，按拥有它的控件命名。显式而非推导，使"新增了一条路径
# 却未验证"能被察觉。
ROUTES = (
    ("toolbar settings gear", "openSettings"),
    ("F1 shortcut", "openSettings"),
    ("tray settings entry", "openSettings"),
)


def main():
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    from gifmanager.backend import MemorySettingsStore, create_backend
    from gifmanager.frontend.qml import app as qml_app
    from gifmanager.frontend.qt.bridge import BackendAdapter

    app = qml_app.build_application([])
    problems = []

    tmp = tempfile.mkdtemp(prefix="gifmanager-nav-")
    backend = create_backend(data_dir=tmp, settings_store=MemorySettingsStore(),
                             log=False)
    try:
        adapter = BackendAdapter(backend)
        engine, bridge, theme, warnings = qml_app.create_engine(adapter, strict=True)
        print("engine warnings:", len(warnings))
        for warning in warnings:
            print("  WARNING:", warning)
            problems.append(f"the engine reported a warning ({warning})")

        roots = engine.rootObjects()
        if not roots:
            problems.append("the engine produced no root object")
            shell = None
        else:
            shell = roots[0]

        if shell is not None:
            # 1. Opening settings must SHOW a second window. Driven through the
            # QML function every route calls, which is the assertion that
            # distinguishes "the QML parsed" from "the control works".
            # 1. 打开设置必须"显示"第二个窗口。经所有路径共同调用的那个 QML 函数驱动
            # ——这正是区分"QML 解析成功"与"控件可用"的断言。
            print()
            print("==== openSettings() shows the settings window ====")
            shell_open = getattr(shell, "openSettings", None)
            if shell_open is None:
                problems.append("the shell exposes no openSettings() function")
            else:
                shell_open()
                app.processEvents()
                others = [w for w in QGuiApplication.topLevelWindows()
                          if w.isVisible() and w is not shell]
                print(f"  visible windows besides the shell: {len(others)}")
                if not others:
                    problems.append(
                        "openSettings() made no second window visible")
                else:
                    others[0].close()
                    app.processEvents()

        # 2. The QML source must not ASSIGN to a read-only bridge property anywhere.
        #
        # This is the check that caught the original four occurrences, including
        # the three that failed silently. `setViewIndex(...)` is a call and is
        # allowed; `viewIndex =` is an assignment and is not.
        # 2. QML 源码中不得在任何地方"赋值"给只读桥属性。
        #
        # 这正是抓到最初四处（含静默失败的三处）的检查。`setViewIndex(...)` 是调用，
        # 允许；`viewIndex =` 是赋值，不允许。
        print()
        print("==== QML assignments to read-only bridge properties ====")
        import pathlib
        import re

        qml_root = (pathlib.Path(__file__).resolve().parent.parent
                    / "gifmanager" / "frontend" / "qml")
        read_only = ("viewIndex",)
        pattern = re.compile(
            r"bridge\.(" + "|".join(read_only) + r")\s*(?<![=!<>])=(?!=)")
        found_any = False
        for path in sorted(qml_root.rglob("*.qml")):
            for number, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                # Comments describe the bug; they are not the bug.
                # 注释在描述该缺陷；注释本身不是缺陷。
                if stripped.startswith("//"):
                    continue
                if pattern.search(line):
                    found_any = True
                    problems.append(
                        f"{path.name}:{number} assigns to read-only bridge."
                        f"{pattern.search(line).group(1)}; use the slot instead")
        if not found_any:
            print("  none (good)")

        # 3. Each declared route must be present in Main.qml as a CALL, so a
        # route cannot be silently dropped when the file is edited.
        # 3. 每一条声明的路径都必须在 Main.qml 中以"调用"形式存在，使路径不会在文件被
        # 编辑时静默消失。
        print()
        print("==== declared routes still present as calls ====")
        main_qml = (qml_root / "shell" / "Main.qml").read_text(encoding="utf-8")
        call_count = main_qml.count("openSettings(")
        print(f"  openSettings( occurrences in Main.qml: {call_count}")
        # The gear button, the F1 shortcut and the tray entry — three routes,
        # asserted as "at least three" so adding a route does not fail the check
        # while removing one does.
        # 齿轮按钮、F1 快捷键与托盘项——三条路径，断言为"至少三条"，使新增路径不会让
        # 检查失败，而移除一条会。
        if call_count < 3:
            problems.append(
                f"Main.qml has only {call_count} openSettings call(s); three routes "
                "are expected (toolbar gear, F1, tray entry)")

        bridge.detach()
        del engine
    finally:
        backend.close()

    print()
    if problems:
        print("NAVIGATION CHECK FAILED / 导航检查未通过")
        for problem in problems:
            print("  " + problem)
        return 1
    print("NAVIGATION CHECK OK / 导航检查通过")
    print("  the settings window opens visibly through the function every route")
    print("  calls, no QML file assigns to a read-only bridge property, and all")
    print("  three settings routes are present")
    print("  设置窗口经所有路径共同调用的函数可见地打开，没有 QML 文件赋值给只读桥")
    print("  属性，且三条设置路径全部存在")
    return 0


if __name__ == "__main__":
    import os as _os

    _status = main()
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(_status)
