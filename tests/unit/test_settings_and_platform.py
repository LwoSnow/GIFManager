"""Unit tests for the settings schema, the store and the platform layer.

设置 schema、存储与平台层的单元测试。
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class SettingsSchemaTests(unittest.TestCase):
    def test_defaults_match_the_documented_values(self):
        from gifmanager.core import settings

        s = settings.defaults()
        self.assertEqual(s.theme, "dark")
        self.assertEqual(s.language, "zh_CN")
        self.assertEqual(s.card_scale, 1.0)
        self.assertAlmostEqual(s.hover_zoom, 1.15)
        self.assertEqual(s.name_font_size, 10)
        self.assertTrue(s.auto_convert_gif)
        self.assertTrue(s.show_emoji_name)
        self.assertEqual(s.send_mode, settings.SEND_MODE_FILE)
        self.assertEqual(s.gif_render_mode, "auto")
        self.assertEqual(s.hotkey.key, "F10")

    def test_every_field_has_a_storage_key(self):
        from gifmanager.core import settings

        keys = settings.all_keys()
        self.assertEqual(len(keys), len(set(keys)))
        self.assertIn("theme", keys)
        self.assertIn("hotkey", keys)
        self.assertIn("window_geometry", keys)

    def test_legacy_gpu_render_migrates(self):
        from gifmanager.core import settings

        migrated = settings.migrate({"gpu_render": True})
        self.assertTrue(migrated["gpu_accel"])
        self.assertTrue(settings.from_mapping({"gpu_render": True}).gpu_accel)

    def test_legacy_hotkey_migrates(self):
        from gifmanager.core import settings

        s = settings.from_mapping({"hotkey_vk": 0, "hotkey_mods": 5})
        # vk == 0 meant unset, and the modifiers were reset too /
        # vk == 0 表示未设置，修饰键也一并重置
        self.assertEqual(s.hotkey.modifiers, 0)
        self.assertEqual(s.hotkey.key, "F10")

    def test_dirty_values_are_coerced_not_fatal(self):
        from gifmanager.core import settings

        s = settings.from_mapping({
            "theme": "neon",
            "card_scale": "not a number",
            "name_font_size": "9999",
            "hover_zoom": "0.1",
            "gpu_pref": "42",
            "send_mode": "9",
            "global_sort_by": "colour",
            "text_preview_limit_single": None,
            "show_emoji_name": "yes",
        })
        self.assertEqual(s.theme, "dark")
        self.assertEqual(s.card_scale, 1.0)
        self.assertEqual(s.name_font_size, settings.NAME_FONT_MAX)
        self.assertEqual(s.hover_zoom, settings.HOVER_ZOOM_MIN)
        self.assertLessEqual(s.gpu_pref, 2)
        self.assertEqual(s.send_mode, settings.SEND_MODE_FILE)
        self.assertEqual(s.global_sort_by, settings.SORT_TIME)
        self.assertEqual(s.text_preview_limit_single, 100)
        self.assertTrue(s.show_emoji_name)

    def test_round_trip_through_storage(self):
        from gifmanager.core import settings

        original = settings.AppSettings(
            theme="light", card_scale=1.5, send_mode=settings.SEND_MODE_IMAGE,
            hotkey=settings.hotkey_core.HotkeyBinding.parse("Ctrl+Alt+D"),
            gpu_adapters=("A", "B"), window_geometry=b"\x01\x02\x03")
        restored = settings.from_mapping(settings.to_mapping(original))
        self.assertEqual(restored.theme, original.theme)
        self.assertEqual(restored.card_scale, original.card_scale)
        self.assertEqual(restored.send_mode, original.send_mode)
        self.assertEqual(restored.hotkey, original.hotkey)
        self.assertEqual(restored.gpu_adapters, original.gpu_adapters)
        self.assertEqual(restored.window_geometry, original.window_geometry)

    def test_diff_reports_only_changes(self):
        from gifmanager.core import settings

        base = settings.defaults()
        changed = settings.diff(base, settings.AppSettings(theme="light"))
        self.assertEqual(changed, frozenset({"theme"}))
        self.assertEqual(settings.diff(base, base), frozenset())

    def test_recommended_thread_count(self):
        from gifmanager.core import settings

        self.assertEqual(settings.recommended_thread_count(4), 3)
        self.assertEqual(settings.recommended_thread_count(1),
                         settings.RECOMMENDED_THREAD_MIN)
        self.assertEqual(settings.recommended_thread_count(64),
                         settings.RECOMMENDED_THREAD_MAX)

    def test_thread_count_auto_round_trip(self):
        from gifmanager.core import settings

        recommended = settings.recommended_thread_count(8)
        # Leaving the recommendation in place stores 0, so another machine with
        # a different core count does not inherit this machine's choice.
        # 保持推荐值即存 0，使核心数不同的另一台机器不会继承本机的选择。
        self.assertEqual(settings.thread_count_to_stored(recommended, 8), 0)
        self.assertEqual(settings.thread_count_to_stored(3, 8), 3)
        self.assertEqual(settings.effective_thread_count(0, 8), recommended)
        self.assertEqual(settings.effective_thread_count(3, 8), 3)

    def test_effective_gif_limit(self):
        from gifmanager.core import settings

        auto = settings.AppSettings(gif_render_mode="auto", thread_count=2)
        self.assertGreaterEqual(settings.effective_gif_limit(auto, 8), 8)
        manual = settings.AppSettings(gif_render_mode="manual",
                                      gif_render_count=3)
        self.assertEqual(settings.effective_gif_limit(manual, 8), 3)

    def test_installer_asset_name(self):
        from gifmanager.core import settings

        self.assertEqual(settings.installer_asset_name((1, 0, 7)),
                         "GIFManager-Setup-1.0.7.exe")

    def test_label_keys(self):
        from gifmanager.core import settings

        self.assertEqual(settings.label_key("theme"), "theme_group")
        self.assertEqual(settings.label_key("window_geometry"), None)
        self.assertEqual(settings.label_key("nope"), None)


class SettingsStoreTests(unittest.TestCase):
    def test_memory_store(self):
        from gifmanager.backend import MemorySettingsStore

        store = MemorySettingsStore({"a": 1})
        self.assertEqual(store.read_all(), {"a": 1})
        store.write_many({"b": 2})
        self.assertEqual(store.read_all(), {"a": 1, "b": 2})

    def test_json_store_round_trip(self):
        from gifmanager.backend.settings_store import JsonSettingsStore

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            store = JsonSettingsStore(path)
            self.assertTrue(store.write_many({"theme": "light", "n": 3}))
            fresh = JsonSettingsStore(path)
            self.assertEqual(fresh.read_all()["theme"], "light")
            self.assertEqual(fresh.read_all()["n"], 3)

    def test_json_store_survives_a_corrupt_file(self):
        from gifmanager.backend.settings_store import JsonSettingsStore

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{ this is not json")
            store = JsonSettingsStore(path)
            # Defaults instead of an exception / 回退默认值而非抛异常
            self.assertEqual(store.read_all(), {})
            self.assertTrue(store.write_many({"theme": "dark"}))
            self.assertEqual(JsonSettingsStore(path).read_all()["theme"], "dark")

    def test_json_store_round_trips_bytes(self):
        from gifmanager.backend.settings_store import JsonSettingsStore

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            store = JsonSettingsStore(path)
            store.write_many({"window_geometry": b"\x00\xff\x10"})
            self.assertEqual(
                JsonSettingsStore(path).read_all()["window_geometry"],
                b"\x00\xff\x10")

    def test_write_is_atomic_no_temp_files_left(self):
        from gifmanager.backend.settings_store import JsonSettingsStore

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            store = JsonSettingsStore(path)
            store.write_many({"theme": "dark"})
            store.write_many({"theme": "light"})
            leftovers = [n for n in os.listdir(tmp) if n.startswith(".settings-")]
            self.assertEqual(leftovers, [])


class PlatformTests(unittest.TestCase):
    def test_a_backend_is_selected(self):
        from gifmanager import platform as platform_layer

        report = platform_layer.describe()
        self.assertTrue(report["backend_module"].startswith("gifmanager.platform."))
        self.assertIn(report["platform_key"], ("win32", "darwin", "linux",
                                               "generic"))

    def test_every_service_resolves(self):
        from gifmanager import platform as platform_layer

        for name in platform_layer.SERVICE_TYPES:
            service = platform_layer.service(name)
            self.assertTrue(hasattr(service, "name"), name)
            self.assertIsInstance(service.available, bool, name)

    def test_no_service_raises_on_a_supported_call(self):
        from gifmanager import platform as platform_layer
        from gifmanager.core import hotkeys

        # A capability query must always answer, whether or not the platform
        # implements the feature. / 无论平台是否实现该功能，能力查询都必须有答案。
        binding = hotkeys.HotkeyBinding.parse("Ctrl+Shift+F10")
        try:
            platform_layer.hotkeys().register("probe", binding, lambda: None)
        finally:
            platform_layer.hotkeys().unregister_all()

    def test_autostart_command_quoting(self):
        from gifmanager import platform as platform_layer

        service = platform_layer.autostart()
        command = service.command_for(r"C:\Program Files\App\app.exe",
                                      ["--flag", "plain"])
        self.assertIn('"C:\\Program Files\\App\\app.exe"', command)
        self.assertIn("plain", command)

    def test_paths_are_absolute(self):
        from gifmanager import platform as platform_layer

        for name in ("user_data_dir", "user_cache_dir", "user_log_dir"):
            value = getattr(platform_layer.paths, name)()
            self.assertTrue(os.path.isabs(value), name)

    def test_process_helpers(self):
        from gifmanager.platform import process

        self.assertIsInstance(process.no_window_kwargs(), dict)
        self.assertIsNone(process.find_executable("definitely-not-a-program"))
        found = process.find_executable("python") or process.find_executable(
            "python3")
        if found:
            completed = process.run_capture([found, "-c", "print(42)"], timeout=30)
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(process.decode_output(completed.stdout).strip(), "42")


if __name__ == "__main__":
    unittest.main(verbosity=2)
