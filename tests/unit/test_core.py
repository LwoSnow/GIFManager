"""Unit tests for the core layer.

Nothing here imports PySide6, which is the point: the core layer must be
exercisable without a GUI toolkit.

核心层的单元测试。

此处不导入 PySide6，这正是重点：核心层必须能在没有界面工具包的情况下被演练。
"""
import os
import pathlib
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class VersionTests(unittest.TestCase):
    def test_parse_valid(self):
        from gifmanager.core import version

        self.assertEqual(version.parse_version("1.2.3"), (1, 2, 3))
        self.assertEqual(version.parse_version(" 10.0.7 "), (10, 0, 7))

    def test_parse_invalid(self):
        from gifmanager.core import version

        for bad in ("1.2", "1.2.3.4", "a.b.c", "", None, 123):
            self.assertIsNone(version.parse_version(bad), bad)

    def test_compare(self):
        from gifmanager.core import version

        self.assertEqual(version.cmp_version("1.0.6", "1.0.6"), 0)
        self.assertEqual(version.cmp_version("1.0.7", "1.0.6"), 1)
        self.assertEqual(version.cmp_version("1.0.6", "1.2.0"), -1)
        self.assertEqual(version.cmp_version("2.0.0", "1.99.99"), 1)

    def test_compare_rejects_garbage(self):
        from gifmanager.core import version

        with self.assertRaises(ValueError):
            version.cmp_version("nope", "1.0.0")

    def test_is_newer_never_raises(self):
        from gifmanager.core import version

        self.assertTrue(version.is_newer("1.0.7", "1.0.6"))
        self.assertFalse(version.is_newer("junk", "1.0.6"))
        self.assertFalse(version.is_newer("1.0.6", "1.0.6"))

    def test_setup_name_round_trip(self):
        from gifmanager.core import version

        name = version.parse_setup_name("GIFManager-Setup-1.2.3.exe")
        self.assertEqual(name, (1, 2, 3))
        self.assertEqual(version.format_version(name), "1.2.3")
        self.assertIsNone(version.parse_setup_name("other-1.2.3.exe"))


class HotkeyTests(unittest.TestCase):
    def test_parse_and_describe(self):
        from gifmanager.core import hotkeys

        binding = hotkeys.HotkeyBinding.parse("Ctrl+Shift+F10")
        self.assertEqual(binding.modifiers,
                         hotkeys.MOD_CTRL | hotkeys.MOD_SHIFT)
        self.assertEqual(binding.key, "F10")
        self.assertEqual(binding.describe(), "Ctrl+Shift+F10")

    def test_parse_accepts_separators_and_aliases(self):
        from gifmanager.core import hotkeys

        for text in ("Ctrl-Shift-F10", "ctrl shift f10", "Control+Shift+F10"):
            binding = hotkeys.HotkeyBinding.parse(text)
            self.assertEqual(binding.key, "F10", text)
            self.assertEqual(binding.modifiers,
                             hotkeys.MOD_CTRL | hotkeys.MOD_SHIFT, text)

    def test_unset_binding(self):
        from gifmanager.core import hotkeys

        binding = hotkeys.HotkeyBinding.parse("")
        self.assertFalse(binding.is_set)
        self.assertFalse(binding.is_valid)
        self.assertEqual(binding.describe(), "")

    def test_modifier_alone_is_not_a_hotkey(self):
        from gifmanager.core import hotkeys

        self.assertFalse(hotkeys.HotkeyBinding.parse("Ctrl+Alt").is_valid)

    def test_unknown_key_is_rejected(self):
        from gifmanager.core import hotkeys

        self.assertFalse(hotkeys.HotkeyBinding.parse("Ctrl+Banana").is_set)

    def test_meta_label_is_per_platform(self):
        from gifmanager.core import hotkeys

        binding = hotkeys.HotkeyBinding(hotkeys.MOD_META, "K")
        self.assertEqual(binding.describe("win32"), "Win+K")
        self.assertEqual(binding.describe("darwin"), "Cmd+K")
        self.assertEqual(binding.describe("linux"), "Super+K")

    def test_storage_round_trip(self):
        from gifmanager.core import hotkeys

        binding = hotkeys.HotkeyBinding.parse("Ctrl+Alt+J")
        restored = hotkeys.HotkeyBinding.from_storage(binding.to_storage())
        self.assertEqual(restored, binding)

    def test_from_storage_rejects_junk(self):
        from gifmanager.core import hotkeys

        self.assertEqual(hotkeys.HotkeyBinding.from_storage(None).key, "F10")
        self.assertEqual(hotkeys.HotkeyBinding.from_storage({}).key, "F10")
        self.assertEqual(
            hotkeys.HotkeyBinding.from_storage({"key": "nope"}).key, "F10")

    def test_migrate_qt_binding(self):
        from gifmanager.core import hotkeys

        # A Qt key of 0 meant "unset", and the modifiers were reset too.
        # Qt 按键值为 0 表示"未设置"，修饰键也一并重置。
        migrated = hotkeys.migrate_qt_binding(5, 0)
        self.assertEqual(migrated.modifiers, 0)
        self.assertEqual(migrated.key, "F10")
        named = hotkeys.migrate_qt_binding(2, 0x42, portable_key="B")
        self.assertEqual(named.key, "B")
        self.assertEqual(named.modifiers, hotkeys.MOD_ALT)


class GpuTests(unittest.TestCase):
    def test_classify_discrete(self):
        from gifmanager.core import gpu

        for name in ("NVIDIA GeForce RTX 4060 Laptop GPU",
                     "AMD Radeon RX 7900 XTX",
                     "Intel(R) Arc(TM) A770 Graphics"):
            self.assertEqual(gpu.classify_adapter(name), gpu.PREF_HIGH, name)

    def test_classify_integrated(self):
        from gifmanager.core import gpu

        for name in ("Intel(R) UHD Graphics 630",
                     "AMD Radeon 780M",
                     "Radeon(TM) Graphics",
                     "Microsoft Basic Display Adapter"):
            self.assertEqual(gpu.classify_adapter(name), gpu.PREF_POWER, name)

    def test_classify_unknown(self):
        from gifmanager.core import gpu

        self.assertIsNone(gpu.classify_adapter(""))
        self.assertIsNone(gpu.classify_adapter("Some Future Adapter"))

    def test_arc_is_discrete_despite_intel(self):
        # Ordering regression: the integrated hints once swallowed Arc.
        # 顺序回归：集显特征词曾吞掉 Arc。
        from gifmanager.core import gpu

        self.assertEqual(
            gpu.classify_adapter("Intel(R) Arc(TM) A770 Graphics"),
            gpu.PREF_HIGH)

    def test_clamp(self):
        from gifmanager.core import gpu

        self.assertEqual(gpu.clamp_preference("2"), gpu.PREF_HIGH)
        self.assertEqual(gpu.clamp_preference(99), gpu.PREF_SYSTEM)
        self.assertEqual(gpu.clamp_preference(None), gpu.PREF_SYSTEM)

    def test_parse_windows_value(self):
        from gifmanager.core import gpu

        self.assertEqual(gpu.parse_windows_value("GpuPreference=2;"), gpu.PREF_HIGH)
        self.assertEqual(gpu.parse_windows_value("GpuPreference=9;"), None)
        self.assertEqual(gpu.parse_windows_value(""), None)

    def test_should_apply_never_removes_on_startup(self):
        from gifmanager.core import gpu

        # A stored SYSTEM value on the startup path means "never chosen", not
        # "delete whatever the OS has".
        # 启动路径上存储的 SYSTEM 意为"从未选择"，而非"删掉系统里的任何设置"。
        apply, allow_removal = gpu.should_apply(
            gpu.PREF_HIGH, gpu.PREF_SYSTEM, True, explicit=False)
        self.assertFalse(apply)
        self.assertFalse(allow_removal)
        apply, allow_removal = gpu.should_apply(
            gpu.PREF_HIGH, gpu.PREF_SYSTEM, True, explicit=True)
        self.assertTrue(apply)
        self.assertTrue(allow_removal)

    def test_should_apply_skips_unchanged(self):
        from gifmanager.core import gpu

        apply, _ = gpu.should_apply(gpu.PREF_HIGH, gpu.PREF_HIGH, True, False)
        self.assertFalse(apply)

    def test_wants_override_off_when_disabled(self):
        from gifmanager.core import gpu

        self.assertFalse(gpu.wants_override(False, gpu.PREF_HIGH))
        self.assertTrue(gpu.wants_override(True, gpu.PREF_HIGH))


class GridLayoutTests(unittest.TestCase):
    def test_row_major_and_flatten_are_inverse(self):
        from gifmanager.core import grid_layout

        ids = list(range(1, 11))
        for columns in (1, 2, 3, 4, 7):
            self.assertEqual(
                grid_layout.flatten_columns(
                    grid_layout.row_major_columns(ids, columns)),
                ids, columns)

    def test_row_major_shape(self):
        from gifmanager.core import grid_layout

        columns = grid_layout.row_major_columns([1, 2, 3, 4, 5], 3)
        self.assertEqual(columns, [[1, 4], [2, 5], [3]])

    def test_row_major_zero_columns_is_one(self):
        from gifmanager.core import grid_layout

        self.assertEqual(grid_layout.row_major_columns([1, 2], 0), [[1, 2]])

    def test_distribute_evenly(self):
        from gifmanager.core import grid_layout

        self.assertEqual(grid_layout.distribute_evenly(7, 3), [3, 3, 1])
        self.assertEqual(grid_layout.distribute_evenly(0, 3), [0, 0, 0])

    def test_uniform_rects_fits_the_width(self):
        from gifmanager.core import grid_layout

        rects, height, per_row = grid_layout.uniform_rects(
            20, 100, 120, 8, 500)
        self.assertEqual(per_row, 4)
        self.assertEqual(len(rects), 20)
        for rect in rects.values():
            self.assertLessEqual(rect[0] + rect[2], 500)
        # 5 rows of 120 plus 4 gaps of 8 / 5 行 120 加 4 个 8 的间隔
        self.assertEqual(height, 5 * 120 + 4 * 8)

    def test_uniform_rects_never_zero_columns(self):
        from gifmanager.core import grid_layout

        _rects, _height, per_row = grid_layout.uniform_rects(
            3, 200, 200, 8, 50)
        self.assertEqual(per_row, 1)

    def test_compact_renumber(self):
        from gifmanager.core import grid_layout

        self.assertEqual(
            grid_layout.compact_renumber([0, 2, 5]), {0: 0, 2: 1, 5: 2})

    def test_visual_order(self):
        from gifmanager.core import grid_layout

        rows = [
            {"id": 1, "col_index": 1, "sort_order": 0},
            {"id": 2, "col_index": 0, "sort_order": 5},
            {"id": 3, "col_index": 0, "sort_order": 1},
        ]
        self.assertEqual([r["id"] for r in grid_layout.visual_order(rows)],
                         [3, 2, 1])

    def test_pack_columns_keeps_user_sorted(self):
        from gifmanager.core import grid_layout

        rows = [
            {"id": 1, "col_index": 2, "user_sorted": 1},
            {"id": 2, "col_index": 0, "user_sorted": 0},
        ]
        columns = grid_layout.pack_columns(rows, 500, 8, lambda _r: 100)
        ids = {index: [row["id"] for row in rows_in_column]
               for index, rows_in_column in columns.items()}
        # A row the user placed stays in its column, and the unplaced row opens
        # a NEW column beside it because the width allows it — `col_index: 0` on
        # an unplaced row is a default, not a placement.
        # 用户已放置的行留在原列；未放置的行因宽度允许而在其旁边"新开"一列——
        # 未放置行上的 `col_index: 0` 是默认值而非放置结果。
        self.assertEqual(ids, {2: [1], 3: [2]})

    def test_pack_columns_opens_a_new_column_when_it_fits(self):
        from gifmanager.core import grid_layout

        rows = [
            {"id": 1, "col_index": 0, "user_sorted": 1},
            {"id": 2, "col_index": 0, "user_sorted": 0},
        ]
        # Two 80 px cards with an 8 px gap fit in 200 px, so the unplaced card
        # gets its own column instead of being stacked on the first.
        # 两张 80px 卡片加 8px 间隔在 200px 内放得下，因此未放置的卡片会另开一列，
        # 而不是叠在第一列上。
        columns = grid_layout.pack_columns(rows, 200, 8, lambda _r: 80)
        self.assertEqual(sorted(columns), [0, 1])

    def test_pack_columns_stacks_when_the_width_is_exhausted(self):
        from gifmanager.core import grid_layout

        rows = [
            {"id": 1, "col_index": 0, "user_sorted": 1},
            {"id": 2, "col_index": 0, "user_sorted": 0},
        ]
        columns = grid_layout.pack_columns(rows, 90, 8, lambda _r: 80)
        self.assertEqual(sorted(columns), [0])
        self.assertEqual(len(columns[0]), 2)

    def test_merge_columns_returns_none_when_nothing_to_merge(self):
        from gifmanager.core import grid_layout

        rows = [{"id": 1, "col_index": 0, "sort_order": 0}]
        self.assertIsNone(
            grid_layout.merge_columns(rows, [9], [0]))

    def test_merge_columns_balances(self):
        from gifmanager.core import grid_layout

        rows = [
            {"id": 1, "col_index": 0, "sort_order": 0},
            {"id": 2, "col_index": 1, "sort_order": 0},
            {"id": 3, "col_index": 1, "sort_order": 1},
            {"id": 4, "col_index": 2, "sort_order": 0},
        ]
        columns = grid_layout.merge_columns(rows, [2], [0, 1])
        self.assertNotIn(2, columns)
        self.assertEqual(sum(len(v) for v in columns.values()), 4)

    def test_hit_test_prefers_last(self):
        from gifmanager.core import grid_layout

        rects = {"a": (0, 0, 10, 10), "b": (0, 0, 10, 10)}
        self.assertEqual(grid_layout.hit_test(rects, 5, 5), "b")
        self.assertIsNone(grid_layout.hit_test(rects, 50, 50))

    def test_total_height_and_width(self):
        from gifmanager.core import grid_layout

        rects = {"a": (0, 0, 10, 10), "b": (20, 30, 10, 10)}
        self.assertEqual(grid_layout.total_height(rects), 40)
        self.assertEqual(grid_layout.total_width(rects), 30)
        self.assertEqual(grid_layout.total_height({}), 0)


class FileOpsTests(unittest.TestCase):
    def test_md5_matches_hashlib(self):
        import hashlib
        import tempfile

        from gifmanager.core import fileops

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "blob.bin")
            payload = os.urandom(300_000)
            with open(path, "wb") as handle:
                handle.write(payload)
            self.assertEqual(fileops.file_md5(path),
                             hashlib.md5(payload).hexdigest())

    def test_unique_path_avoids_collision(self):
        import tempfile

        from gifmanager.core import fileops

        with tempfile.TemporaryDirectory() as tmp:
            first = os.path.join(tmp, "a.gif")
            open(first, "wb").close()
            resolved = fileops.unique_path(tmp, "a.gif")
            self.assertEqual(os.path.basename(resolved), "a_1.gif")
            open(resolved, "wb").close()
            self.assertEqual(
                os.path.basename(fileops.unique_path(tmp, "a.gif")), "a_2.gif")

    def test_unique_path_passthrough(self):
        import tempfile

        from gifmanager.core import fileops

        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(fileops.unique_path(tmp, "new.gif"),
                             os.path.join(tmp, "new.gif"))

    def test_copy_upgrades_gif87a_header(self):
        import tempfile

        from gifmanager.core import fileops

        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "old.gif")
            dst = os.path.join(tmp, "new.gif")
            with open(src, "wb") as handle:
                handle.write(b"GIF87a" + b"\x00" * 20)
            self.assertTrue(fileops.copy_upgrading_gif(src, dst))
            with open(dst, "rb") as handle:
                self.assertEqual(handle.read(6), b"GIF89a")
            # Only the header changes / 只改写文件头
            self.assertEqual(os.path.getsize(src), os.path.getsize(dst))

    def test_copy_preserves_gif89a(self):
        import tempfile

        from gifmanager.core import fileops

        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "a.gif")
            dst = os.path.join(tmp, "b.gif")
            with open(src, "wb") as handle:
                handle.write(b"GIF89a" + b"\x11" * 10)
            fileops.copy_upgrading_gif(src, dst)
            # `Path.read_bytes()` rather than a bare `open(...).read()`. The bare form leaves the
            # file object
            # to the garbage collector, and CPython reports it as
            #     ResourceWarning: unclosed file <_io.BufferedReader name='.../b.gif'>
            # which puts two warnings in the CI log on every run. A test that leaks handles is also
            # a poor
            # example in a project whose point is careful resource handling.
            # 用 `Path.read_bytes()` 而不是裸的 `open(...).read()`。后者把文件对象交给垃圾回收，CPython 会报
            #     ResourceWarning: unclosed file <_io.BufferedReader name='.../b.gif'>
            # 每跑一次就在 CI 日志里留两条警告。一个泄漏句柄的测试，在一个以谨慎处理资源为宗旨的项目里也是
            # 坏示范。
            self.assertEqual(pathlib.Path(dst).read_bytes(),
                             pathlib.Path(src).read_bytes())

    def test_remove_dir_retry(self):
        import tempfile

        from gifmanager.core import fileops

        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "tree", "nested")
            os.makedirs(target)
            open(os.path.join(target, "f.txt"), "w").close()
            self.assertTrue(fileops.remove_dir_retry(os.path.join(tmp, "tree")))
            self.assertFalse(os.path.isdir(os.path.join(tmp, "tree")))

    def test_remove_dir_retry_on_missing_is_true(self):
        import tempfile

        from gifmanager.core import fileops

        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(
                fileops.remove_dir_retry(os.path.join(tmp, "absent")))

    def test_rename_dir(self):
        import tempfile

        from gifmanager.core import fileops

        with tempfile.TemporaryDirectory() as tmp:
            old = os.path.join(tmp, "old")
            new = os.path.join(tmp, "new")
            os.makedirs(old)
            open(os.path.join(old, "f.txt"), "w").close()
            self.assertTrue(fileops.rename_dir(old, new))
            self.assertTrue(os.path.isfile(os.path.join(new, "f.txt")))
            self.assertFalse(os.path.isdir(old))

    def test_retry_policy_is_per_platform(self):
        from gifmanager.core import fileops

        tries, delay = fileops.retry_policy()
        self.assertGreaterEqual(tries, 1)
        self.assertGreaterEqual(delay, 0.0)


class ImagingSignatureTests(unittest.TestCase):
    def test_content_kind_by_magic_bytes(self):
        import tempfile

        from gifmanager.core.imaging import signatures

        cases = (
            (b"GIF89a" + b"\x00" * 8, ".jpg", signatures.KIND_GIF),
            (b"\x89PNG\r\n\x1a\n" + b"\x00" * 4, ".txt", signatures.KIND_PNG),
            (b"\xff\xd8\xff\xe0" + b"\x00" * 8, ".png", signatures.KIND_JPEG),
            (b"RIFF\x00\x00\x00\x00WEBP", ".bmp", signatures.KIND_WEBP),
        )
        with tempfile.TemporaryDirectory() as tmp:
            for payload, extension, expected in cases:
                path = os.path.join(tmp, "probe" + extension)
                with open(path, "wb") as handle:
                    handle.write(payload)
                self.assertEqual(signatures.content_kind(path), expected,
                                 extension)

    def test_content_kind_falls_back_to_extension(self):
        import tempfile

        from gifmanager.core.imaging import signatures

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "unknown.gif")
            with open(path, "wb") as handle:
                handle.write(b"\x00" * 16)
            self.assertEqual(signatures.content_kind(path), signatures.KIND_GIF)

    def test_content_kind_missing_file(self):
        from gifmanager.core.imaging import signatures

        self.assertIsNone(signatures.content_kind("does-not-exist.bin"))

    def test_importable_extensions(self):
        from gifmanager.core.imaging import signatures

        self.assertTrue(signatures.is_importable("a.gif"))
        self.assertTrue(signatures.is_importable("a.JPEG"))
        self.assertFalse(signatures.is_importable("a.txt"))
        self.assertTrue(signatures.needs_conversion("a.png"))
        self.assertFalse(signatures.needs_conversion("a.gif"))

    def test_needs_gif_conversion_uses_content_not_extension(self):
        import tempfile

        from gifmanager.core.imaging import signatures

        with tempfile.TemporaryDirectory() as tmp:
            # GIF content under a .jpg name is already a GIF /
            # 伪装 .jpg 的 GIF 内容本身就是 GIF
            path = os.path.join(tmp, "fake.jpg")
            with open(path, "wb") as handle:
                handle.write(b"GIF89a" + b"\x00" * 8)
            self.assertFalse(signatures.needs_gif_conversion(path))
            # PNG content under a .gif name still needs conversion /
            # 伪装 .gif 的 PNG 内容仍需转换
            other = os.path.join(tmp, "fake.gif")
            with open(other, "wb") as handle:
                handle.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 4)
            self.assertTrue(signatures.needs_gif_conversion(other))

    def test_has_gif_signature(self):
        import tempfile

        from gifmanager.core.imaging import signatures

        with tempfile.TemporaryDirectory() as tmp:
            good = os.path.join(tmp, "a.gif")
            with open(good, "wb") as handle:
                handle.write(b"GIF89a")
            self.assertTrue(signatures.has_gif_signature(good))
            self.assertFalse(signatures.has_gif_signature("missing.gif"))

    def test_is_mjpeg_detects_two_scans(self):
        import tempfile

        from gifmanager.core.imaging import signatures

        # SOI, SOS with a 2-byte header, entropy, then a second SOI /
        # SOI、SOS（2 字节头）、熵数据，随后第二个 SOI
        single = b"\xff\xd8" + b"\xff\xda\x00\x02" + b"\x00" * 4 + b"\xff\xd9"
        double = (b"\xff\xd8" + b"\xff\xda\x00\x02" + b"\x00" * 4
                  + b"\xff\xd8" + b"\xff\xd9")
        with tempfile.TemporaryDirectory() as tmp:
            one = os.path.join(tmp, "one.jpg")
            two = os.path.join(tmp, "two.jpg")
            with open(one, "wb") as handle:
                handle.write(single)
            with open(two, "wb") as handle:
                handle.write(double)
            self.assertFalse(signatures.is_mjpeg(one))
            self.assertTrue(signatures.is_mjpeg(two))

    def test_dimensions_from_probe_when_pillow_absent(self):
        from gifmanager.core.imaging import signatures

        # The probe callback stands in for an ffmpeg invocation, so this passes
        # with or without Pillow installed — it only exercises the fallback when
        # Pillow cannot read the file, which is the case for a nonexistent path.
        # 探测回调代替一次 ffmpeg 调用，因此本测试有无 Pillow 都能通过——只在 Pillow
        # 无法读取文件（路径不存在即如此）时演练兜底路径。
        result = signatures.image_dimensions(
            "missing-input.png",
            probe=lambda _p: "Stream #0:0: Video: png, 640x480, 25 fps")
        self.assertEqual(result, (640, 480))

    def test_dimensions_none_without_probe(self):
        from gifmanager.core.imaging import signatures

        self.assertIsNone(signatures.image_dimensions("missing-input.png"))


class LangTests(unittest.TestCase):
    def test_fallback_dictionary(self):
        from gifmanager.core.lang import LanguageManager

        manager = LanguageManager()
        # A key present in the shipped files resolves in either language /
        # 随包文件中存在的键在任何语言下都能解析
        self.assertNotEqual(manager.t("settings"), "settings")
        # An unknown key shows itself rather than raising /
        # 未知键显示键名本身而不是抛异常
        self.assertEqual(manager.t("definitely_missing_key"),
                         "definitely_missing_key")

    def test_format_failure_is_not_fatal(self):
        from gifmanager.core.lang import LanguageManager

        manager = LanguageManager()
        # A placeholder the string does not have must not raise /
        # 字符串中不存在的占位符不得抛异常
        self.assertIsInstance(manager.t("settings", unknown="x"), str)

    def test_available_languages(self):
        from gifmanager.core.lang import LanguageManager

        available = LanguageManager().available_languages()
        self.assertIn("zh_CN", available)
        self.assertIn("en_US", available)

    def test_switch_language(self):
        from gifmanager.core.lang import LanguageManager

        manager = LanguageManager()
        english = manager.t("settings")
        manager.set_language("en_US")
        self.assertEqual(manager.current_lang, "en_US")
        self.assertIsInstance(manager.t("settings"), str)
        self.assertIsInstance(english, str)


class PathTests(unittest.TestCase):
    def test_env_override_wins(self):
        from gifmanager.core import paths

        original = os.environ.get(paths.DATA_DIR_ENV)
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            os.environ[paths.DATA_DIR_ENV] = tmp
            try:
                self.assertEqual(os.path.normcase(paths.data_dir()),
                                 os.path.normcase(tmp))
            finally:
                if original is None:
                    os.environ.pop(paths.DATA_DIR_ENV, None)
                else:
                    os.environ[paths.DATA_DIR_ENV] = original

    def test_resource_directories_exist(self):
        from gifmanager.core import paths

        self.assertTrue(os.path.isdir(paths.resources_dir()))
        self.assertTrue(os.path.isdir(paths.language_dir()))

    def test_database_and_emoji_paths_are_under_the_data_dir(self):
        from gifmanager.core import paths

        base = os.path.join(os.sep, "tmp", "gm-base")
        self.assertEqual(os.path.dirname(paths.database_path(base)), base)
        self.assertEqual(os.path.dirname(paths.emojis_dir(base)), base)


if __name__ == "__main__":
    unittest.main(verbosity=2)
