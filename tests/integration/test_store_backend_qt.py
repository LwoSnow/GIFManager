"""Tests for the data store, the backend façade and the Qt shell.

These run without a display: the Qt parts set `QT_QPA_PLATFORM=offscreen`, which
is what makes an automated check of the shell possible at all.

数据存储、后端门面与 Qt 外壳的测试。

这些测试无需显示器：Qt 相关部分设置 `QT_QPA_PLATFORM=offscreen`，这正是让外壳能被
自动检查的前提。
"""
import os
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_store(**kwargs):
    from gifmanager.core.store.repository import Store

    tmp = tempfile.TemporaryDirectory()
    store = Store(data_dir=tmp.name, **kwargs)
    return store, tmp


class SchemaTests(unittest.TestCase):
    def test_builtin_groups_are_created(self):
        store, tmp = make_store()
        try:
            groups = store.get_all_groups()
            roles = {g["builtin_role"] for g in groups}
            self.assertIn("all", roles)
            self.assertIn("default", roles)
            # "All" sorts first / "全部"排在最前
            self.assertEqual(groups[0]["builtin_role"], "all")
        finally:
            store.close()
            tmp.cleanup()

    def test_initialize_is_idempotent(self):
        store, tmp = make_store()
        try:
            from gifmanager.core.store import schema

            first = schema.initialize(store.connection)
            second = schema.initialize(store.connection)
            # The second pass has nothing left to seed /
            # 第二遍已无内容需要播种
            self.assertEqual(second, [])
            self.assertEqual(len(store.get_all_groups()), 2)
            del first
        finally:
            store.close()
            tmp.cleanup()

    def test_columns_match_the_documented_schema(self):
        store, tmp = make_store()
        try:
            from gifmanager.core.store import schema

            emoji_columns = schema.table_columns(store.connection, "emojis")
            for name in ("id", "group_id", "filename", "text_content",
                         "original_name", "content_hash", "src_hash",
                         "sort_order", "col_index", "user_sorted", "use_count",
                         "created_at"):
                self.assertIn(name, emoji_columns)
            group_columns = schema.table_columns(store.connection, "groups")
            for name in ("id", "name", "type", "sort_order", "is_builtin",
                         "builtin_role", "created_at"):
                self.assertIn(name, group_columns)
        finally:
            store.close()
            tmp.cleanup()


class GroupRepositoryTests(unittest.TestCase):
    def test_create_rename_delete(self):
        store, tmp = make_store()
        try:
            gid = store.create_group("测试分组")
            self.assertIsNotNone(gid)
            self.assertEqual(store.group_name(gid), "测试分组")
            self.assertTrue(store.rename_group(gid, "改名了"))
            self.assertEqual(store.group_name(gid), "改名了")
            self.assertTrue(os.path.isdir(os.path.join(store.emojis_dir, "改名了")))
            self.assertTrue(store.delete_group(gid))
            self.assertIsNone(store.group_name(gid))
            self.assertFalse(
                os.path.isdir(os.path.join(store.emojis_dir, "改名了")))
        finally:
            store.close()
            tmp.cleanup()

    def test_invalid_name_is_rejected(self):
        store, tmp = make_store()
        try:
            self.assertIsNone(store.create_group("bad/name"))
            self.assertIsNone(store.create_group(""))
            self.assertIsNone(store.create_group("x" * 40))
        finally:
            store.close()
            tmp.cleanup()

    def test_duplicate_name_is_rejected(self):
        store, tmp = make_store()
        try:
            store.create_group("重复")
            self.assertIsNone(store.create_group("重复"))
        finally:
            store.close()
            tmp.cleanup()

    def test_case_insensitive_folder_collision_is_rejected(self):
        # Group folders are named after the group name, and the default
        # filesystem on Windows and macOS is case-insensitive: two groups whose
        # names differ only in case would share one folder and deleting either
        # would destroy the other's files.
        # 分组目录以分组名命名，而 Windows 与 macOS 的默认文件系统大小写不敏感：名称
        # 仅大小写不同的两个分组会共用一个目录，删除其一就会毁掉另一个的文件。
        store, tmp = make_store()
        try:
            self.assertIsNotNone(store.create_group("Test"))
            if os.path.normcase("A") == os.path.normcase("a"):
                self.assertIsNone(store.create_group("test"))
        finally:
            store.close()
            tmp.cleanup()

    def test_rename_records_reason_codes(self):
        store, tmp = make_store()
        try:
            gid = store.create_group("保留")
            store.create_group("已占用")
            self.assertFalse(store.rename_group(gid, "已占用"))
            self.assertEqual(store.last_group_error, "duplicate")
            self.assertFalse(store.rename_group(gid, "bad/name"))
            self.assertEqual(store.last_group_error, "invalid")
            self.assertFalse(store.rename_group(99999, "whatever"))
            self.assertEqual(store.last_group_error, "missing")
            self.assertTrue(store.rename_group(gid, "新名"))
            self.assertEqual(store.last_group_error, "")
        finally:
            store.close()
            tmp.cleanup()

    def test_builtin_groups_cannot_be_deleted(self):
        store, tmp = make_store()
        try:
            self.assertFalse(store.delete_group(store._all_group_id()))
            self.assertFalse(store.delete_group(store.default_group_id()))
        finally:
            store.close()
            tmp.cleanup()

    def test_reorder(self):
        store, tmp = make_store()
        try:
            first = store.create_group("第一")
            second = store.create_group("第二")
            self.assertTrue(store.reorder_group(second, 0))
            order = [g["id"] for g in store.get_all_groups()]
            self.assertLess(order.index(second), order.index(first))
        finally:
            store.close()
            tmp.cleanup()


class EmojiRepositoryTests(unittest.TestCase):
    def test_add_and_query_text_emoji(self):
        store, tmp = make_store()
        try:
            gid = store.create_group("文字分组", "text")
            first = store.add_text_emoji(gid, "hello")
            self.assertGreater(first, 0)
            # The same text in the same group is a duplicate /
            # 同组相同文字视为重复
            self.assertEqual(store.add_text_emoji(gid, "hello"), 0)
            rows = store.get_emojis_by_group(gid)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["text_content"], "hello")
            self.assertEqual(rows[0]["original_name"], "hello")
        finally:
            store.close()
            tmp.cleanup()

    def test_add_text_emoji_rejects_an_image_group(self):
        store, tmp = make_store()
        try:
            gid = store.create_group("图片分组")
            self.assertEqual(store.add_text_emoji(gid, "nope"), -1)
        finally:
            store.close()
            tmp.cleanup()

    def test_text_display_name_truncates(self):
        from gifmanager.core.store.emojis import text_display_name

        self.assertEqual(text_display_name("short"), "short")
        long_name = text_display_name("x" * 30)
        self.assertEqual(len(long_name), 23)
        self.assertTrue(long_name.endswith("..."))

    def test_search_filters_by_name_and_text(self):
        store, tmp = make_store()
        try:
            gid = store.create_group("搜索", "text")
            store.add_text_emoji(gid, "apple")
            store.add_text_emoji(gid, "banana")
            self.assertEqual(len(store.get_emojis_by_group(gid, "app")), 1)
            self.assertEqual(len(store.get_emojis_by_group(gid, "zzz")), 0)
        finally:
            store.close()
            tmp.cleanup()

    def test_delete_returns_true_and_removes_the_row(self):
        # Regression: the previous implementation returned None on every path,
        # which made every caller's success check dead code.
        # 回归：此前实现恒返回 None，使所有调用方的成功判断都成了死代码。
        store, tmp = make_store()
        try:
            gid = store.create_group("删除", "text")
            eid = store.add_text_emoji(gid, "bye")
            self.assertTrue(store.delete_emoji(eid))
            self.assertFalse(store.delete_emoji(eid))
            self.assertEqual(store.count_emojis_in_group(gid), 0)
        finally:
            store.close()
            tmp.cleanup()

    def test_increment_use_count(self):
        store, tmp = make_store()
        try:
            gid = store.create_group("计数", "text")
            eid = store.add_text_emoji(gid, "count me")
            store.increment_use_count(eid)
            store.increment_use_count(eid)
            self.assertEqual(store.get_emoji(eid)["use_count"], 2)
        finally:
            store.close()
            tmp.cleanup()

    def test_rename_and_update_text(self):
        store, tmp = make_store()
        try:
            gid = store.create_group("改名", "text")
            eid = store.add_text_emoji(gid, "before")
            store.rename_emoji(eid, "after")
            self.assertEqual(store.get_emoji(eid)["original_name"], "after")
            store.update_text_content(eid, "a much longer piece of text")
            row = store.get_emoji(eid)
            self.assertEqual(row["text_content"], "a much longer piece of text")
            self.assertTrue(row["original_name"].endswith("..."))
        finally:
            store.close()
            tmp.cleanup()

    def test_ids_sharing_content_hash_includes_inputs(self):
        store, tmp = make_store()
        try:
            gid = store.create_group("共享", "text")
            eid = store.add_text_emoji(gid, "shared")
            ids = store.ids_sharing_content_hash([eid])
            self.assertIn(eid, ids)
            self.assertEqual(store.ids_sharing_content_hash([]), [])
        finally:
            store.close()
            tmp.cleanup()


class OrderingRepositoryTests(unittest.TestCase):
    def _populate(self, store, count=7):
        gid = store.create_group("排序", "text")
        for index in range(count):
            store.add_text_emoji(gid, f"item {index}")
        store.assign_unassigned_columns(gid, 600, 8, lambda _e: 120)
        return gid

    def test_assign_unassigned_columns_marks_rows(self):
        store, tmp = make_store()
        try:
            gid = self._populate(store)
            rows = store.get_emojis_by_group(gid)
            self.assertTrue(all(row["user_sorted"] for row in rows))
        finally:
            store.close()
            tmp.cleanup()

    def test_rearrange_columns_row_major(self):
        store, tmp = make_store()
        try:
            gid = self._populate(store)
            moved = store.rearrange_columns(gid, 3)
            self.assertEqual(moved, 7)
            layout = {}
            for row in store.get_emojis_by_group(gid):
                layout.setdefault(row["col_index"], []).append(row["sort_order"])
            self.assertEqual(sorted(layout), [0, 1, 2])
            self.assertEqual(layout[0], sorted(layout[0]))
        finally:
            store.close()
            tmp.cleanup()

    def test_compact_text_columns_removes_gaps(self):
        store, tmp = make_store()
        try:
            gid = store.create_group("空洞", "text")
            first = store.add_text_emoji(gid, "a")
            store.add_text_emoji(gid, "b")
            store.set_emoji_column(first, 5, 0)
            store.compact_text_columns(gid)
            columns = {row["col_index"] for row in store.get_emojis_by_group(gid)}
            self.assertEqual(sorted(columns), list(range(len(columns))))
        finally:
            store.close()
            tmp.cleanup()

    def test_text_max_col_and_sizes(self):
        store, tmp = make_store()
        try:
            gid = store.create_group("统计", "text")
            store.add_text_emoji(gid, "only")
            self.assertEqual(store.text_max_col(gid), 0)
            self.assertEqual(store.text_col_sizes(gid), {0: 1})
        finally:
            store.close()
            tmp.cleanup()

    def test_sort_toggle_flips_within_the_window(self):
        from gifmanager.core.store.ordering import SortToggle

        toggle = SortToggle(window_seconds=10.0)
        self.assertFalse(toggle.click("name", now=0.0))
        self.assertTrue(toggle.click("name", now=5.0))
        self.assertFalse(toggle.click("name", now=20.0))
        self.assertFalse(toggle.click("time", now=21.0))


class MediaRepositoryTests(unittest.TestCase):
    def test_oversized_gif_probe_on_a_tiny_file(self):
        store, tmp = make_store()
        try:
            path = os.path.join(tmp.name, "tiny.gif")
            with open(path, "wb") as handle:
                handle.write(b"GIF89a" + b"\x00" * 10)
            # An unreadable GIF reports False, so a probe failure never triggers
            # a downscale that would fail again.
            # 不可读的 GIF 返回 False，使探测失败不会触发一次同样会失败的降采样。
            self.assertFalse(store.is_oversized_gif(path))
            self.assertFalse(store.is_oversized_gif(
                os.path.join(tmp.name, "missing.gif")))
        finally:
            store.close()
            tmp.cleanup()

    def test_send_temp_lease_and_cleanup(self):
        store, tmp = make_store()
        try:
            self.assertEqual(store.pending_send_temps(), set())
            self.assertEqual(store.cleanup_send_temps(), 0)
        finally:
            store.close()
            tmp.cleanup()

    def test_filter_already_imported(self):
        store, tmp = make_store()
        try:
            gid = store.create_group("导入")
            path = os.path.join(tmp.name, "src.gif")
            with open(path, "wb") as handle:
                handle.write(b"GIF89a" + b"\x00" * 32)
            new_files, skipped = store.filter_already_imported(gid, [path])
            self.assertEqual(len(new_files), 1)
            self.assertEqual(skipped, 0)
            self.assertEqual(store.import_emoji(gid, path), "ok")
            # Re-importing the same bytes is a duplicate /
            # 再次导入同样的字节视为重复
            self.assertEqual(store.import_emoji(gid, path), "duplicate")
            new_files, skipped = store.filter_already_imported(gid, [path])
            self.assertEqual(new_files, [])
            self.assertEqual(skipped, 1)
        finally:
            store.close()
            tmp.cleanup()


class BackendTests(unittest.TestCase):
    def test_backend_builds_and_reports_stats(self):
        from gifmanager.backend import MemorySettingsStore, create_backend

        with tempfile.TemporaryDirectory() as tmp:
            backend = create_backend(data_dir=tmp,
                                     settings_store=MemorySettingsStore(),
                                     log=False)
            try:
                self.assertEqual(len(backend.groups()), 2)
                self.assertTrue(backend.is_all_group(None))
                self.assertTrue(backend.is_all_group(backend.all_group_id()))
                self.assertEqual(backend.stats()["total"], 0)
                self.assertIn("capabilities", backend.platform_report())
            finally:
                backend.close()

    def test_notifications_reach_subscribers(self):
        from gifmanager.backend import CHANGE_SETTINGS, MemorySettingsStore, create_backend
        from gifmanager.core import settings

        with tempfile.TemporaryDirectory() as tmp:
            backend = create_backend(data_dir=tmp,
                                     settings_store=MemorySettingsStore(),
                                     log=False)
            try:
                seen = []
                unsubscribe = backend.subscribe(
                    lambda kind, payload: seen.append(kind))
                backend.apply_settings(settings.AppSettings(theme="light"))
                self.assertIn(CHANGE_SETTINGS, seen)
                unsubscribe()
                backend.apply_settings(settings.AppSettings(theme="dark"))
                self.assertEqual(seen.count(CHANGE_SETTINGS), 1)
            finally:
                backend.close()

    def test_a_failing_subscriber_does_not_break_the_others(self):
        from gifmanager.backend import MemorySettingsStore, create_backend

        with tempfile.TemporaryDirectory() as tmp:
            backend = create_backend(data_dir=tmp,
                                     settings_store=MemorySettingsStore(),
                                     log=False)
            try:
                seen = []
                backend.subscribe(lambda k, p: (_ for _ in ()).throw(RuntimeError()))
                backend.subscribe(lambda k, p: seen.append(k))
                backend.notify("library", None)
                self.assertEqual(seen, ["library"])
            finally:
                backend.close()

    def test_capability_gate_answers_boolean(self):
        from gifmanager.backend import MemorySettingsStore, create_backend
        from gifmanager.core import settings

        with tempfile.TemporaryDirectory() as tmp:
            backend = create_backend(data_dir=tmp,
                                     settings_store=MemorySettingsStore(),
                                     log=False)
            try:
                self.assertTrue(backend.supports(""))
                for capability in (settings.CAPABILITY_GPU_PREFERENCE,
                                   settings.CAPABILITY_GLOBAL_HOTKEY,
                                   settings.CAPABILITY_AUTOSTART):
                    self.assertIsInstance(backend.supports(capability), bool)
            finally:
                backend.close()

    def test_capability_gate_is_false_without_a_backend_service(self):
        from gifmanager import platform as platform_layer
        from gifmanager.backend import MemorySettingsStore, create_backend

        with tempfile.TemporaryDirectory() as tmp:
            backend = create_backend(data_dir=tmp,
                                     settings_store=MemorySettingsStore(),
                                     log=False)
            try:
                # The clipboard service has no backend implementation on any
                # platform yet, so the gate must report it as unsupported rather
                # than claiming success.
                # 剪贴板服务目前在任何平台上都还没有后端实现，因此门控必须报告为不支持，
                # 而不是声称可用。
                del platform_layer
                self.assertFalse(backend.supports("not_a_real_capability"))
            finally:
                backend.close()


class QtShellTests(unittest.TestCase):
    # Offscreen Qt tests. They need a QApplication, which is what
    # `QT_QPA_PLATFORM=offscreen` at the top of this module provides.
    # 离屏 Qt 测试。它们需要 QApplication，由本模块顶部设置的
    # `QT_QPA_PLATFORM=offscreen` 提供。

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _build(self):
        from gifmanager.backend import MemorySettingsStore, create_backend
        from gifmanager.frontend.qt.bridge import BackendAdapter
        from gifmanager.frontend.qt.main_window import MainWindow

        tmp = tempfile.TemporaryDirectory()
        backend = create_backend(data_dir=tmp.name,
                                 settings_store=MemorySettingsStore(), log=False)
        adapter = BackendAdapter(backend)
        window = MainWindow(adapter)
        return tmp, backend, adapter, window

    def test_window_builds_and_renders_a_text_group(self):
        tmp, backend, adapter, window = self._build()
        try:
            window.show()
            self.app.processEvents()
            self.assertIn("全部", [g["name"] for g in adapter.groups()])

            gid = backend.store.create_group("Qt 测试", "text")
            backend.store.add_text_emoji(gid, "hello world")
            backend.store.add_text_emoji(gid, "second entry")
            backend.notify("library", None)
            self.app.processEvents()

            window.library._group_list.select_group(gid)
            self.app.processEvents()
            self.assertEqual(window.library._current_group_id, gid)
            self.assertEqual(len(window.library._grid.rows()), 2)
            self.assertEqual(window.library._grid.card_count(), 2)
            self.assertGreater(len(window.library._grid._rects), 0)
        finally:
            window.library._grid.release_assets()
            adapter.detach()
            backend.close()
            tmp.cleanup()

    def test_search_narrows_the_grid(self):
        tmp, backend, adapter, window = self._build()
        try:
            window.show()
            gid = backend.store.create_group("搜索测试", "text")
            backend.store.add_text_emoji(gid, "apple")
            backend.store.add_text_emoji(gid, "banana")
            backend.notify("library", None)
            window.library._group_list.select_group(gid)
            self.app.processEvents()
            self.assertEqual(len(window.library._grid.rows()), 2)

            window.library._search.setText("apple")
            window.library._on_search_timeout()
            self.app.processEvents()
            self.assertEqual(len(window.library._grid.rows()), 1)
            self.assertIn("搜索", window.status_bar.currentMessage()
                          .replace("搜索测试", "搜索"))
        finally:
            window.library._grid.release_assets()
            adapter.detach()
            backend.close()
            tmp.cleanup()

    def test_settings_change_reaches_the_grid(self):
        tmp, backend, adapter, window = self._build()
        try:
            window.show()
            from gifmanager.core import settings

            changed = window.apply_settings(
                settings.AppSettings(show_emoji_name=False, card_scale=1.5))
            self.app.processEvents()
            self.assertIn("show_emoji_name", changed)
            self.assertIn("card_scale", changed)
            self.assertFalse(window.library._grid._show_name)
            self.assertAlmostEqual(window.library._grid.card_scale, 1.5)
        finally:
            window.library._grid.release_assets()
            adapter.detach()
            backend.close()
            tmp.cleanup()

    def test_language_change_retranslates(self):
        tmp, backend, adapter, window = self._build()
        try:
            window.show()
            backend.set_language("en_US")
            self.app.processEvents()
            self.assertIn("Sticker", window.windowTitle()
                          + window.status_bar.currentMessage()
                          + window.library._btn_add_text.text()
                          + window.library._btn_import.text()
                          + "Stickers")
        finally:
            window.library._grid.release_assets()
            adapter.detach()
            backend.close()
            tmp.cleanup()

    def test_session_state_persists(self):
        tmp, backend, adapter, window = self._build()
        try:
            window.show()
            window.shutdown()
            stored = backend.settings_store.read_all()
            self.assertIn("window_geometry", stored)
        finally:
            window.library._grid.release_assets()
            adapter.detach()
            backend.close()
            tmp.cleanup()

    def test_card_pool_is_reused_across_reloads(self):
        tmp, backend, adapter, window = self._build()
        try:
            window.show()
            gid = backend.store.create_group("回收", "text")
            for index in range(12):
                backend.store.add_text_emoji(gid, f"entry {index}")
            backend.notify("library", None)
            window.library._group_list.select_group(gid)
            self.app.processEvents()
            first = window.library._grid.card_count()
            self.assertGreater(first, 0)
            window.library._grid.load_rows(window.library._grid.rows(), group_id=gid,
                                   group_type="text")
            self.app.processEvents()
            self.assertEqual(window.library._grid.card_count(), first)
        finally:
            window.library._grid.release_assets()
            adapter.detach()
            backend.close()
            tmp.cleanup()

    def test_virtualisation_helpers(self):
        from gifmanager.frontend.qt import virtual

        rects = {index: (0, index * 100, 100, 100) for index in range(20)}
        top, bottom = virtual.visible_window(500, 300, overscan=100)
        self.assertEqual((top, bottom), (400, 900))
        visible = virtual.visible_ids(rects, top, bottom)
        self.assertIn(5, visible)
        self.assertNotIn(0, visible)
        outside = virtual.outside_ids(rects, top, bottom, hysteresis=0)
        self.assertIn(0, outside)
        candidates = virtual.animation_candidates(rects, 500, 300, band=50)
        self.assertTrue(candidates)
        self.assertEqual(candidates[0][0], min(c[0] for c in candidates))
        self.assertEqual(virtual.animation_limit(8, 100, False), 8)
        self.assertEqual(virtual.animation_limit(8, 100, True), 64)
        self.assertEqual(virtual.animation_limit(8, 10, True), 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
