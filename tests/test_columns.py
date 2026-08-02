"""图片分组列堆叠（masonry）+ resize 列融合 + 拖拽列移动 回归测试

运行: python -m unittest tests.test_columns -v
隔离: 临时数据目录 + 内存版 QSettings（不触碰真实 data/ 与注册表配置）
"""
import os
import sys
import tempfile
import shutil
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TMP = tempfile.mkdtemp(prefix="gifmgr_coltest_")

import app.models.data_manager as dm_mod

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QEventLoop

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
    with open(path, "wb") as f:
        f.write(bytes([
            0x47, 0x49, 0x46, 0x38, 0x39, 0x61,
            0x01, 0x00, 0x01, 0x00, 0x80, 0x00, 0x00,
            color, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x2C, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00,
            0x02, 0x02, 0x44, 0x01, 0x00, 0x3B,
        ]))


def _col_distribution(dm, group_id):
    """返回 {col_index: [emojis按sort_order] 的 id 列表}"""
    emos = dm.get_emojis_by_group(group_id)
    cols = {}
    for e in emos:
        cols.setdefault(int(e["col_index"]), []).append(e["id"])
    return cols


def _all_ids(cols):
    ids = []
    for ci in sorted(cols):
        ids.extend(cols[ci])
    return ids


class TestImageColumnLayout(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # 数据目录重定向到本类临时目录（运行时 patch，tearDown 恢复，避免多测试类互相覆盖）
        cls._orig_data_dir = dm_mod._app_data_dir
        dm_mod._app_data_dir = lambda: TMP
        cls.app = QApplication.instance() or QApplication([])
        cls.w = mw_mod.MainWindow()
        cls.w.resize(620, 520)
        cls.w.show()

    @classmethod
    def tearDownClass(cls):
        cls.w.close()
        dm_mod._app_data_dir = cls._orig_data_dir
        shutil.rmtree(TMP, ignore_errors=True)

    def _wait(self, ms=400):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def _overlap(self):
        rects = [c.geometry() for c in self.w.emoji_grid._items]
        return sum(
            1 for i in range(len(rects)) for j in range(i + 1, len(rects))
            if rects[i].intersects(rects[j])
        )

    def test_image_group_columns_merge_drag(self):
        dm = self.w.data_manager
        gid = dm.create_group("图组", "image")
        tmp = tempfile.mkdtemp()
        try:
            for i in range(7):
                p = os.path.join(tmp, f"img{i}.gif")
                _make_gif(p, 0x10 + i)
                self.assertEqual(dm.import_emoji(gid, p), "ok", f"导入 img{i} 失败")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # ---- 1. 切换到图片分组：未分配卡片自动摊列（宽窗口 → 多列） ----
        self.w.group_list._rebuild()
        self.w.group_list.select_group(gid)
        self._wait()
        cols = _col_distribution(dm, gid)
        print("摊列后 col 分布:", {k: len(v) for k, v in cols.items()})
        self.assertGreaterEqual(max(cols), 3, "宽窗口应摊成多列")
        self.assertEqual(len(_all_ids(cols)), 7, "卡片无丢失")
        self.assertEqual(self._overlap(), 0, "masonry 布局卡片不应重叠")
        self.assertEqual(len(self.w.emoji_grid._items), 7)
        # 已分配 → user_sorted=1，再次刷新不再摊列（分布不变）
        before = {k: tuple(v) for k, v in cols.items()}
        self.w._refresh_emoji_grid()
        self._wait()
        after = {k: tuple(v) for k, v in _col_distribution(dm, gid).items()}
        self.assertEqual(before, after, "重复刷新不应改变列分布")

        # ---- 2. 缩小窗口 → 列融合（顺序保持，卡片不丢失） ----
        wide = {k: tuple(v) for k, v in cols.items()}
        self.w.resize(420, 520)
        self._wait(600)  # resizeEvent → 融合 → emojis_reordered → 重载
        merged = _col_distribution(dm, gid)
        print("融合后 col 分布:", {k: len(v) for k, v in merged.items()})
        self.assertLess(max(merged), max(wide), "缩小后列数应减少")
        self.assertEqual(len(_all_ids(merged)), 7, "融合后卡片无丢失")
        self.assertEqual(self._overlap(), 0, "融合后卡片不应重叠")
        # 融合规则：被挤压的卡片逐个放入当前卡片最少的列（动态均衡）
        keep_n = max(merged) + 1
        keep_ids = set()
        for ci in range(keep_n):
            keep_ids.update(wide.get(ci, ()))
        squeezed = [i for ci in range(keep_n, max(wide) + 1) for i in wide.get(ci, ())]
        self.assertEqual(len(_all_ids(merged)), 7, "融合后卡片无丢失")
        self.assertEqual(set(_all_ids(merged)), set(_all_ids(wide)), "融合后卡片集合不变")
        self.assertTrue(set(squeezed) <= set(_all_ids(merged)),
                        "被挤压卡片应全部进入保留列")
        # 最短列分配 → 各列卡片数尽量均衡（max-min ≤ 1）
        counts = [len(merged[ci]) for ci in sorted(merged)]
        self.assertLessEqual(max(counts) - min(counts), 1,
                             f"各列卡片数应尽量均衡: {counts}")

        # ---- 3. 拖拽模拟：跨列移动（移入指定列指定位置） ----
        dragged_id = _all_ids(merged)[0]
        dm.set_emoji_column(dragged_id, 0, 999999)  # 移到第 1 列末尾
        moved = _col_distribution(dm, gid)
        self.assertIn(dragged_id, moved[0], "拖拽后应位于目标列")
        self.assertEqual(moved[0][-1], dragged_id, "拖拽后应位于目标列末尾")
        # 移空列压缩
        empty_cols = [ci for ci in range(max(moved) + 1)
                      if ci not in moved or not moved[ci]]
        self.assertEqual(empty_cols, [], "拖拽后不应有空列（compact 生效）")

        # ---- 4. 文字分组原有功能不回归 ----
        tid = dm.create_group("颜文字", "text")
        dm.add_text_emoji(tid, "ヽ(´ー｀)ノ おはよう")
        dm.add_text_emoji(tid, "(╯°□°)╯︵ ┻━┻")
        dm.add_text_emoji(tid, "略略略")
        self.w.group_list._rebuild()
        self.w.group_list.select_group(tid)
        self._wait()
        tcols = _col_distribution(dm, tid)
        print("文字分组 col 分布:", {k: len(v) for k, v in tcols.items()})
        self.assertEqual(len(_all_ids(tcols)), 3, "文字卡片无丢失")
        self.assertEqual(self._overlap(), 0, "文字分组卡片不应重叠")

        # ---- 5. "全部"聚合视图仍正常（流式） ----
        self.w.group_list.select_all_group()
        self._wait()
        shown = len(self.w.emoji_grid._items)
        self.assertGreaterEqual(shown, 7, "\"全部\"应显示聚合表情")
        self.assertEqual(self._overlap(), 0, "\"全部\"流式布局不应重叠")


if __name__ == "__main__":
    unittest.main()
