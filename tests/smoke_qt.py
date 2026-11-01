"""Offscreen smoke test for the Qt shell.

Builds the real application, window and grid against a temporary data directory
and a memory settings store, then exercises loading, group switching, search and
teardown. Runs without a display, so it is usable in CI.

Qt 外壳的离屏冒烟测试。

在临时数据目录与内存设置存储之上构建真实的 Application、窗口与网格，然后演练加载、
切换分组、搜索与退出。无需显示器即可运行，因此可用于 CI。
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from gifmanager.backend import MemorySettingsStore, create_backend
from gifmanager.core import settings as settings_model
from gifmanager.frontend.qt.bridge import BackendAdapter, apply_theme
from gifmanager.frontend.qt.main_window import MainWindow


def section(title):
    print()
    print("=" * 4, title)


def main():
    app = QApplication.instance() or QApplication([])

    with tempfile.TemporaryDirectory() as tmp:
        backend = create_backend(data_dir=tmp, settings_store=MemorySettingsStore())
        adapter = BackendAdapter(backend)

        section("theme")
        print("applied:", apply_theme(app, backend.settings.theme),
              "stylesheet chars:", len(app.styleSheet()))

        section("window")
        window = MainWindow(adapter)
        window.show()
        app.processEvents()
        print("title        :", window.windowTitle())
        print("groups       :", [g["name"] for g in adapter.groups()])
        print("status       :", window.status_bar.currentMessage())
        print("grid cards   :", window.library._grid.card_count(),
              "(no rows yet, so 0 is correct)")
        print("placeholder  :", window.library._grid._placeholder.isVisible())

        section("library change notification")
        # A text group, because `add_text_emoji` refuses an image group — the
        # same rule the UI relies on when it swaps the toolbar buttons.
        # 文字分组，因为 `add_text_emoji` 会拒绝图片分组——界面切换工具栏按钮时依赖
        # 的正是同一条规则。
        group_id = backend.store.create_group("冒烟分组", "text")
        backend.store.add_text_emoji(group_id, "hello world")
        backend.store.add_text_emoji(group_id, "second entry")
        backend.notify("library", None)
        app.processEvents()
        print("groups now   :", [g["name"] for g in adapter.groups()])

        print("group bar buttons:", list(window.library._group_list._buttons.keys()))
        captured = []
        window.library._group_list.group_changed.connect(lambda gid: captured.append(gid))
        window.library._group_list.select_group(group_id)
        app.processEvents()
        print("group_changed emitted:", captured)
        print("group bar current id :", window.library._group_list._current_group_id)
        print("current group:", window.library._current_group_id, "expected", group_id)
        print("rows loaded  :", len(window.library._grid.rows()))
        print("cards built  :", window.library._grid.card_count())
        print("status       :", window.status_bar.currentMessage())
        print("import btn hidden (text group):", not window.library._btn_import.isVisible())

        section("search")
        window.library._search.setText("second")
        window.library._on_search_timeout()
        app.processEvents()
        print("keyword      :", repr(window.library._keyword))
        print("rows matched :", len(window.library._grid.rows()))
        window.library._search.setText("")
        window.library._on_search_timeout()
        app.processEvents()
        print("rows restored:", len(window.library._grid.rows()))

        section("settings round trip")
        changed = window.apply_settings(
            settings_model.AppSettings(theme="light", show_emoji_name=False))
        app.processEvents()
        print("changed keys :", sorted(changed))
        print("show name    :", window.library._grid._show_name, "(expected False)")
        print("session saved:", backend.settings_store.read_all().get("theme"))

        section("virtualisation")
        from gifmanager.frontend.qt import virtual

        rects = window.library._grid._rects
        print("rects        :", len(rects))
        print("total height :", max((r[1] + r[3] for r in rects.values()), default=0))
        print("visible band :", virtual.visible_window(0, 400))
        print("anim window  :", virtual.animation_window(0, 400))
        print("anim limit(8,parallel):", virtual.animation_limit(8, 30, True))
        print("anim limit(8,serial)  :", virtual.animation_limit(8, 30, False))

        section("teardown")
        window.close()
        adapter.detach()
        backend.close()
        app.processEvents()
        print("backend closed")

    print()
    print("OK")


if __name__ == "__main__":
    main()
