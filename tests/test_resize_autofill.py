"""Verify resize auto-fill in a NORMAL group (not just the All view).

Widening a group opens as many columns as fit and re-distributes the cards
row-first; narrowing merges the overflowing columns back. The behaviour must NOT
depend on the "global sort" setting (it used to, which made the feature look
broken in every group), but it must still be skipped while a search filter is
active.
验证普通分组（而非仅"全部"视图）的拉伸自动铺满：拉宽按可容纳列数增列并
行优先重排，拉窄融合溢出列。该行为不得依赖"全局排序"设置（此前依赖，导致
所有普通分组看起来该功能失效），但搜索过滤生效时仍必须跳过。
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ROOT)
from tests._iso import drain_and_exit  # noqa: E402
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import logging
logging.disable(logging.CRITICAL)

TMP = tempfile.mkdtemp(prefix="gifmgr_fill_")
import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PIL import Image
from PySide6.QtWidgets import QApplication, QScrollArea
from PySide6.QtCore import Qt

from app.models.data_manager import DataManager
from app.widgets.emoji_grid import EmojiGridWidget
from app.widgets.emoji_item import EmojiItem

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}  {str(detail)[:110]}")


dm = DataManager()
gid = dm.create_group("G", "image")
for i in range(24):
    p = os.path.join(TMP, f"a{i}.png")
    Image.new("RGB", (64, 64), (i * 10 % 256, 120, 180)).save(p)
    dm.import_emoji(gid, p, auto_convert=False)

sa = QScrollArea()
sa.setWidgetResizable(True)
sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
grid = EmojiGridWidget()
grid.set_data_manager(dm)
grid.current_group_id = gid
sa.setWidget(grid)
sa.resize(260, 500)          # narrow: only ~1-2 columns fit / 窄：仅约 1-2 列
sa.show()
grid.load_emojis(dm.get_emojis_by_group(gid), "image")
app.processEvents()


def col_count():
    return len({int(e.get("col_index", 0))
                for e in dm.get_emojis_by_group(gid)}) or 1


def flat_order():
    # (sort_order, id) is the row-major reading order / 行优先阅读顺序
    return [e["id"] for e in dm.get_emojis_by_group(gid)]


def usable():
    return grid._usable_width()


narrow_cols = col_count()
card_w = EmojiItem.card_size()
sp = grid._flow.spacing()
order_before = flat_order()
print(f"card_w={card_w} spacing={sp} usable={usable()} cols={narrow_cols}")

# --- 1. widening auto-fills even with global sort OFF --------------------
grid._global_sort_enabled = False
sa.resize(900, 500)
app.processEvents()
expect = max(1, (usable() + sp) // (card_w + sp))
changed = grid.auto_fill_columns()
app.processEvents()
check("未启用全局排序时也会自动铺满", changed is True, f"changed={changed}")
check("列数等于可容纳列数", col_count() == expect,
      f"cols={col_count()} expected={expect}")
check("列数确实增加", col_count() > narrow_cols,
      f"{narrow_cols} -> {col_count()}")
check("铺满不影响卡片全局顺序", flat_order() == order_before,
      f"{len(flat_order())} vs {len(order_before)}")

# --- 2. row-first distribution fills the window (no blank column) -------
widths = {}
for e in dm.get_emojis_by_group(gid):
    ci = int(e.get("col_index", 0))
    widths[ci] = max(widths.get(ci, 0), card_w)
total = sum(widths.values()) + sp * max(0, len(widths) - 1)
check("各列总宽不超过可用宽度", total <= usable() + 1,
      f"total={total} usable={usable()}")
check("至少两列（铺满而非单列）", col_count() >= 2, col_count())
per_col = {}
for e in dm.get_emojis_by_group(gid):
    ci = int(e.get("col_index", 0))
    per_col[ci] = per_col.get(ci, 0) + 1
check("所有列都非空", all(v > 0 for v in per_col.values()), per_col)

# --- 3. re-running with the same width is a no-op ------------------------
again = grid.auto_fill_columns()
check("同宽度重复调用不再改动", again is False, again)

# --- 4. a search filter still blocks the layout write-back (B10) --------
grid._filter_keyword = "zzz"
sa.resize(1400, 500)
app.processEvents()
blocked = grid.auto_fill_columns()
check("过滤态下不自动铺满", blocked is False, blocked)
check("过滤态下列数不变", col_count() == expect, col_count())
grid._filter_keyword = ""

# --- 5. widening again opens even more columns --------------------------
sa.resize(1400, 500)
app.processEvents()
more = grid.auto_fill_columns()
app.processEvents()
check("继续拉宽会继续增列", more is True and col_count() > expect,
      f"{expect} -> {col_count()}")

# --- 6. narrowing shrinks again (merge path still works) ----------------
keep = col_count()
sa.resize(260, 500)
app.processEvents()
grid._check_column_merge()
app.processEvents()
check("缩窄窗口后列数减少", col_count() < keep, f"cols={col_count()} was {keep}")

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n拉伸自动铺满验证: {n_pass}/{len(RES)} 通过")
sys.stdout.flush()
drain_and_exit(0 if n_pass == len(RES) else 1)
