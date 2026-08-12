"""Layout and "All" aggregation/deduplication regression tests
布局与"全部"聚合/去重 回归测试

Run: python -m unittest tests.test_layout -v
运行: python -m unittest tests.test_layout -v
Isolation: temporary data dir + in-memory QSettings (never touches real data/ or registry)
隔离: 使用临时数据目录 + 内存版 QSettings（不触碰真实 data/ 与注册表配置）
"""
import os
import sys
import tempfile
import shutil
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TMP = tempfile.mkdtemp(prefix="gifmgr_test_")

import app.models.data_manager as dm_mod

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QEventLoop

# Replace QSettings with an in-memory version to avoid touching the user
# registry / 用内存版 QSettings 替换，避免读写用户注册表配置
import app.main_window as mw_mod


class _FakeSettings(dict):
    def __init__(self, *args, **kwargs):
        super().__init__()

    def value(self, key, default=None, type=None):
        if key in self:
            return self[key]
        if type is bool:
            return False
        return default

    def setValue(self, key, val):
        self[key] = val


mw_mod.QSettings = _FakeSettings


def _make_gif(path, color=0xFF):
    # Generates a 1x1 GIF; color decides the content (same color = same content,
    # used for the dedupe test) / 生成 1x1 GIF，color 决定内容（同 color = 同内容，用于去重测试）
    with open(path, "wb") as f:
        f.write(bytes([
            0x47, 0x49, 0x46, 0x38, 0x39, 0x61,
            0x01, 0x00, 0x01, 0x00, 0x80, 0x00, 0x00,
            color, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x2C, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00,
            0x02, 0x02, 0x44, 0x01, 0x00, 0x3B,
        ]))


class TestLayoutAndSync(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Redirect the data dir to this class's temp dir (runtime patch, restored in
        # tearDown so test classes never overwrite each other) / 数据目录重定向到本类临时目录
        # （运行时 patch，tearDown 恢复，避免多测试类互相覆盖）
        cls._orig_data_dir = dm_mod._app_data_dir
        dm_mod._app_data_dir = lambda: TMP
        cls.app = QApplication.instance() or QApplication([])
        cls.w = mw_mod.MainWindow()
        cls.w.show()

    @classmethod
    def tearDownClass(cls):
        cls.w.close()
        dm_mod._app_data_dir = cls._orig_data_dir
        shutil.rmtree(TMP, ignore_errors=True)

    def _overlap(self):
        rects = [c.geometry() for c in self.w.emoji_grid._items]
        return sum(
            1 for i in range(len(rects)) for j in range(i + 1, len(rects))
            if rects[i].intersects(rects[j])
        )

    def _run_chain(self, steps):
        # Runs steps: [(delay_ms, callable)] in order until all complete
        # 依序执行 steps: [(delay_ms, callable)]，事件循环运行直至全部完成
        loop = QEventLoop()
        total = 0
        for delay, fn in steps:
            total += delay
            QTimer.singleShot(total, fn)
        QTimer.singleShot(total + 300, loop.quit)
        loop.exec()

    def test_full_flow_no_overlap_aggregate_dedupe(self):
        # Full flow: cards never overlap; "All" aggregates every image group
        # and dedupes by content / 全流程：卡片无重叠；"全部"聚合所有 image 分组并按内容去重
        dm = self.w.data_manager
        results = {}

        def import4_into_default():
            tmp = tempfile.mkdtemp()
            try:
                files = []
                for i in range(4):
                    p = os.path.join(tmp, f"g{i}.gif")
                    _make_gif(p, 0x10 + i)  # 4 distinct contents / 4 张内容不同
                    files.append(p)
                self.w._do_import(files)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            # Current group is "All" (None path); imports go to Default, so "All"
            # should show 4 right away / 当前分组 = 全部(None 路径)，导入目标 = 默认表情 → "全部"应立即显示 4 张
            results["import_in_all"] = (len(self.w.emoji_grid._items), self._overlap())

        def switch_default():
            d = dm.get_group_by_name("Default Expression")
            self.w.group_list.select_group(d["id"])
            results["default"] = (len(self.w.emoji_grid._items), self._overlap())

        def switch_all_none():
            self.w.group_list.select_all_group()
            results["all_none"] = (len(self.w.emoji_grid._items), self._overlap())

        def text_group():
            tid = dm.create_group("颜文字", "text")
            dm.add_text_emoji(tid, "ヽ(´ー｀)ノ おはよう")
            dm.add_text_emoji(tid, "(╯°□°)╯︵ ┻━┻")
            self.w.group_list._rebuild()
            self.w.group_list.select_group(tid)
            results["text"] = (len(self.w.emoji_grid._items), self._overlap())

        def all_again():
            self.w.group_list.select_all_group()
            # Text emojis stay out of "All"; still 4 images / 文字不混入"全部"，仍为 4 张图
            results["all_again"] = (len(self.w.emoji_grid._items), self._overlap())

        def setup_groups_and_dupe():
            # Group A/B: same content imported once each (should dedupe to 1); uniq only
            # in A / 组A/组B：same 内容各导一份（应去重为 1）；uniq 只进组A
            ga = dm.create_group("组A", "image")
            gb = dm.create_group("组B", "image")
            tmp = tempfile.mkdtemp()
            try:
                same1 = os.path.join(tmp, "same1.gif")
                same2 = os.path.join(tmp, "same2.gif")
                uniq = os.path.join(tmp, "uniq.gif")
                _make_gif(same1, 0x33)
                _make_gif(same2, 0x33)  # Same content as same1 / 与 same1 内容相同
                _make_gif(uniq, 0x77)   # Distinct content / 内容不同
                dm.import_emoji(ga, same1)
                dm.import_emoji(gb, same2)
                dm.import_emoji(ga, uniq)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            self.w.group_list._rebuild()
            # DB dedupe check: 4 (Default) + 2 (A/B after dedupe) = 6 / 数据库层去重校验：
            # 4(默认) + 2(组A/组B 去重后) = 6
            results["db_all_count"] = (len(dm.get_all_emojis()), 0)

        def click_all_button():
            # Main bug coverage: clicking the "All" button (real id path) aggregates all
            # image groups / 主 bug 覆盖：点击"全部"按钮（真实 id 路径）→ 应聚合所有 image 分组
            all_gid = dm.get_group_by_name("All")["id"]
            self.w.group_list.select_group(all_gid)
            results["all_button"] = (len(self.w.emoji_grid._items), self._overlap())

        self._run_chain([
            (200, import4_into_default),
            (300, switch_default),
            (300, switch_all_none),
            (300, text_group),
            (300, all_again),
            (300, setup_groups_and_dupe),
            (300, click_all_button),
        ])

        for key, (count, ov) in results.items():
            self.assertEqual(ov, 0, f"{key}: 卡片重叠 {ov}")
        self.assertEqual(results["import_in_all"][0], 4, "导入后\"全部\"应立即显示 4 张")
        self.assertEqual(results["default"][0], 4)
        self.assertEqual(results["all_none"][0], 4)
        self.assertEqual(results["text"][0], 2, "文字分组应为 2 张文字卡片")
        self.assertEqual(results["all_again"][0], 4, "\"全部\"不应混入文字表情")
        self.assertEqual(results["db_all_count"][0], 6, "去重后应有 4+2=6 个不同内容")
        self.assertEqual(results["all_button"][0], 6,
                         "点击\"全部\"按钮（真实 id）应聚合所有 image 分组并去重")


if __name__ == "__main__":
    unittest.main()
