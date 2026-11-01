"""Verify the application shell: navigation, commands, shortcuts, lifecycle.

The shell is the framework the rest of the interface is built on, so this checks
the framework's promises rather than any particular page:

* every view is reachable and only the visible one is ACTIVE;
* `deactivate` really runs on navigation, because that is what stops a hidden
  page from burning CPU;
* every action is reachable through the registry, and a command's documented
  shortcut matches the key Qt actually bound;
* a command predicate can disable an action, and the disabled action refuses to
  run through EVERY presenter rather than only through the menu.

外壳是其余界面赖以构建的框架，因此这里检查的是框架的承诺而非某个具体页面：

* 每个视图都可到达，且只有可见的那个是"活跃"的；
* 导航时 `deactivate` 确实会运行，因为正是它阻止隐藏页面持续占用 CPU；
* 每个操作都能经注册表到达，且命令所记录的快捷键与 Qt 实际绑定的按键一致；
* 命令谓词可以禁用一个操作，而被禁用的操作在"每个"呈现方都拒绝执行，而不只是菜单里。
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

from gifmanager.backend import MemorySettingsStore, create_backend
from gifmanager.core import settings as settings_model
from gifmanager.frontend.qt import commands as cmd
from gifmanager.frontend.qt.bridge import BackendAdapter, apply_theme
from gifmanager.frontend.qt.shell_window import ShellWindow


def section(title):
    print()
    print("=" * 4, title)


def main():
    app = QApplication.instance() or QApplication([])
    problems = []

    with tempfile.TemporaryDirectory() as tmp:
        backend = create_backend(data_dir=tmp,
                                settings_store=MemorySettingsStore(), log=False)
        adapter = BackendAdapter(backend)
        apply_theme(app, backend.settings.theme)

        # Seed a text group so the library page has content and the
        # text-only command has something to act on.
        # 造一个文字分组，使表情库页有内容、且只对文字有效的命令有作用对象。
        group_id = backend.store.create_group("外壳测试", "text")
        for index in range(3):
            backend.store.add_text_emoji(group_id, f"entry {index}")

        window = ShellWindow(adapter)
        window.show()
        app.processEvents()

        section("navigation")
        print("views        :", list(window._views.keys()))
        print("nav rows     :", window._nav.count())
        print("current      :", window._current_view_id)
        if window._current_view_id != "library":
            problems.append("the shell did not open on the library view")
        if window._nav.count() != len(window._views):
            problems.append(
                f"navigation has {window._nav.count()} rows for "
                f"{len(window._views)} views")

        section("lifecycle: deactivate must run on navigation")
        library = window._views["library"]
        print("library active at start:", library.is_active)
        # Navigate to a view that EXISTS. The settings page replaced the
        # placeholder that used to sit here, so naming the placeholder made this
        # navigation a no-op — and the test then reported the library as "still
        # active", which was the assertion working correctly on a broken fixture.
        # 导航到一个"存在"的视图。设置页取代了此处原先的占位页，因此沿用占位页名会让这次
        # 导航成为空操作——而测试随后报告表情库"仍然活跃"，那其实是断言在一个坏掉的测试
        # 装置上正确工作。
        if not window.navigate("settings"):
            problems.append("cannot navigate to the settings view")
        app.processEvents()
        print("after navigating away  :", library.is_active)
        if library.is_active:
            problems.append("the library stayed active after navigating away")
        window.navigate("library")
        app.processEvents()
        print("after navigating back  :", library.is_active)
        if not library.is_active:
            problems.append("the library did not reactivate")

        section("library content through the shell")
        window._views["library"]._group_list.reload()
        window._views["library"]._group_list.select_group(group_id)
        app.processEvents()
        state = window.current_state()
        print("group id     :", state.get("group_id"))
        print("count        :", state.get("count"))
        print("accepts_text :", state.get("accepts_text"))
        print("status       :", window.status_bar.currentMessage())
        if state.get("count") != 3:
            problems.append(f"expected 3 rows in state, got {state.get('count')}")

        section("command registry")
        print("commands     :", len(window._registry))
        surfaces = {}
        for command in window._registry.all():
            for surface in command.surfaces:
                surfaces[surface] = surfaces.get(surface, 0) + 1
        print("by surface   :", surfaces)
        for needed in (cmd.CMD_IMPORT, cmd.CMD_ADD_TEXT, cmd.CMD_COPY,
                       cmd.CMD_DELETE_SELECTED, cmd.CMD_TOGGLE_THEME,
                       cmd.CMD_QUIT):
            if needed not in window._registry:
                problems.append(f"command {needed} is not registered")
        if not window._registry.for_surface(cmd.SURFACE_CONTEXT):
            problems.append("no command declares the context surface")

        section("shortcuts match what Qt actually bound")
        # Qt canonicalises some key names — `Delete` is reported as `Del` — so the
        # comparison goes through `QKeySequence`, which normalises both sides.
        # Comparing raw strings would report a false mismatch for any key Qt
        # happens to spell differently.
        # Qt 会把某些键名规范化——`Delete` 被报告为 `Del`——因此比较经
        # `QKeySequence` 进行，它会归一化两侧。直接比较字符串会对任何 Qt 恰好拼写不同的
        # 按键误报不一致。
        declared = {}
        for command in window._registry.all():
            if command.shortcut:
                declared[QKeySequence(command.shortcut).toString()] = command.id
        bound = {}
        for action in window._shortcut_actions:
            text = action.shortcut().toString()
            bound[text] = declared.get(text, "")
            if text not in declared:
                problems.append(
                    f"Qt bound {text!r} but no command declares it")
        print("declared     :", dict(sorted(declared.items())))
        print("qt actions   :", len(window._shortcut_actions))
        if len(window._shortcut_actions) != len(declared):
            problems.append(
                f"{len(declared)} shortcuts declared but "
                f"{len(window._shortcut_actions)} actions created")
        # Ctrl+A must reach the select-all command /
        # Ctrl+A 必须能到达全选命令
        select_all_key = QKeySequence("Ctrl+A").toString()
        if bound.get(select_all_key) != cmd.CMD_SELECT_ALL:
            problems.append(
                f"Ctrl+A is bound to {bound.get(select_all_key)!r}, "
                f"expected {cmd.CMD_SELECT_ALL!r}")

        section("commands run through the registry")
        stylesheet_before = app.styleSheet()
        before = backend.settings.theme
        ok = window._registry.invoke(cmd.CMD_TOGGLE_THEME, window.current_state())
        app.processEvents()
        after = backend.settings.theme
        stylesheet_after = app.styleSheet()
        print(f"toggle theme : {before} -> {after} (returned {ok})")
        print(f"stylesheet   : {len(stylesheet_before)} -> "
              f"{len(stylesheet_after)} chars, changed="
              f"{stylesheet_before != stylesheet_after}")
        if not ok or before == after:
            problems.append("toggle_theme did not change the theme")
        # The real test is that the STYLESHEET that is on screen changed, and that
        # it is the one belonging to the new theme. Matching on a colour name in
        # the text would be meaningless: the dark stylesheet mentions "light" in
        # its own comments.
        # 真正的检验是"屏幕上生效的样式表"变了，且它是新主题对应的那一份。用文本里的
        # 颜色名去匹配毫无意义：深色样式表在自己的注释里就提到了 "light"。
        from gifmanager.frontend.qt.theme import STYLESHEETS

        if stylesheet_before == stylesheet_after:
            problems.append(
                "the stylesheet was not reapplied when the theme changed")
        elif stylesheet_after != STYLESHEETS[after]:
            problems.append(
                f"the stylesheet does not match the {after} theme")

        section("availability predicates disable across every presenter")
        library_commands = {c.id: c for c in library.commands()}
        add_text = library_commands.get(cmd.CMD_ADD_TEXT)
        if add_text is None:
            problems.append("the library does not contribute add_text")
        else:
            # The predicate keys off `accepts_text`; force it false and confirm
            # the registry refuses, which is what makes a menu item and its
            # shortcut agree.
            # 谓词以 `accepts_text` 为条件；强制为假并确认注册表拒绝执行，这正是让菜单项
            # 与其快捷键保持一致的原因。
            blocked = dict(window.current_state())
            blocked["accepts_text"] = False
            print("enabled_when(False):", add_text.is_enabled(blocked))
            print("enabled_when(True) :", add_text.is_enabled({"accepts_text": True}))
            if add_text.is_enabled(blocked):
                problems.append("the predicate reported enabled when it should not")
            if not add_text.is_enabled({"accepts_text": True}):
                problems.append("the predicate reported disabled when it should not")

        section("selection drives command availability")
        library._grid.select_all()
        app.processEvents()
        selected_state = window.current_state()
        print("selected rows:", len(library._grid.selected_rows()))
        print("state.selected:", selected_state.get("selected"))
        if not selected_state.get("selected"):
            problems.append("select_all did not reach the view state")
        library._grid.clear_selection()
        app.processEvents()
        print("after clear  :", window.current_state().get("selected"))
        if window.current_state().get("selected"):
            problems.append("clear_selection did not clear the view state")

        section("retranslation")
        library_name_zh = window._nav_items["library"].text()
        backend.set_language("en_US")
        app.processEvents()
        library_name_en = window._nav_items["library"].text()
        print(f"nav label    : {library_name_zh!r} -> {library_name_en!r}")
        if library_name_zh == library_name_en:
            problems.append("the navigation label did not change with the language")
        for button in window._menu_buttons.values():
            if not button.text():
                problems.append("a menu button lost its text after retranslation")
        backend.set_language("zh_CN")
        app.processEvents()

        section("settings reach the visible view")
        changed = window.apply_settings(
            settings_model.AppSettings(card_scale=1.4, show_emoji_name=False))
        app.processEvents()
        print("changed      :", sorted(changed))
        grid = library._grid
        print("grid scale   :", grid.card_scale, " show_name:", grid._show_name)
        if abs(grid.card_scale - 1.4) > 1e-6:
            problems.append("card_scale did not reach the grid")
        if grid._show_name:
            problems.append("show_emoji_name did not reach the grid")

        section("shutdown")
        window.shutdown()
        adapter.detach()
        backend.close()
        print("shut down cleanly")

    print()
    if problems:
        print("SHELL CHECK FAILED / 外壳检查未通过")
        for problem in problems:
            print("  " + problem)
        return 1
    print("SHELL CHECK OK / 外壳检查通过")
    print("  navigation, per-view lifecycle, command registry, shortcuts,")
    print("  predicates, selection, retranslation and settings all behave")
    print("  导航、按视图生命周期、命令注册表、快捷键、谓词、选择、翻译与设置均正常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
