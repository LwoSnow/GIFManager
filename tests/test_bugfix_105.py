"""Regression for the 1.0.5 bug-fix batch:
1. Rename dialog input box is tall enough (text no longer clipped/offset)
2. Dragging inside a search result keeps the search filter
3. Duplicate import detection also matches the ORIGINAL file hash, so the
   same source cannot be imported twice when the auto-convert setting (and
   therefore the stored bytes) differs
4. Multi-select edit mode keeps the selection consistent with the visible
   data set (select-all / delete cover exactly what is shown)
1.0.5 修复批次回归：
1. 重命名对话框输入框高度足够（文字不再被裁切/偏下）
2. 在搜索结果中拖拽后仍保留搜索过滤
3. 导入查重同时比对原始文件哈希，使同一源文件在"自动转换"开关不同
   （存储字节不同）时也不会被重复导入
4. 多选编辑模式的选中集合与可见数据集保持一致（全选/删除覆盖范围正确）
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

from PIL import Image

from PySide6.QtWidgets import QApplication, QLineEdit

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:110]}")


def fresh_dm(tag):
    # Each case gets its own data dir so DataManager instances never share a
    # SQLite file / 每个用例独占数据目录，避免多个 DataManager 共用同一 SQLite
    tmp = tempfile.mkdtemp(prefix=tag)
    import app.models.data_manager as dm_mod
    dm_mod._app_data_dir = lambda: os.path.join(tmp, "data")
    dm = dm_mod.DataManager()
    return dm, tmp


# ---------------------------------------------------------------- 1. dialog
from app.widgets.rename_dialog import RenameDialog
from app.theme.dark_theme import QSS as DARK_QSS
app.setStyleSheet(DARK_QSS)
_dlg = RenameDialog("abc", None)
_dlg.show()
app.processEvents()
_ed = _dlg.findChildren(QLineEdit)[0]
# Content area must exceed the font line height; 28px with 5px padding left
# only 16px and clipped the glyph bottoms.
from PySide6.QtGui import QFontMetrics
_line = QFontMetrics(_ed.font()).height() + 4
check("输入框高度足够（≥32px）", _ed.height() >= 32, f"h={_ed.height()}")
check("输入框行高足够", _ed.height() - 2 >= _line,
      f"h={_ed.height()} line+pad={_line}")
check("对话框内布局不溢出", _dlg.minimumSizeHint().height() <= _dlg.height(),
      f"hint={_dlg.minimumSizeHint().height()} h={_dlg.height()}")
# no vertical padding that would push text down / 无导致文字偏下的上下内边距
check("输入框无上下大内边距", "padding: 5px" not in _ed.styleSheet(),
      _ed.styleSheet()[:70])
_dlg.close()


# ------------------------------------------------- 2/3. import + dedup cases
def import_twice(first_convert, second_convert, use_batch):
    dm, tmp = fresh_dm("gifmgr_dedup_")
    gid = dm.create_group("G", "image")
    src = os.path.join(tmp, "p.png")
    Image.new("RGB", (80, 60), (30, 120, 200)).save(src)
    if use_batch:
        dm.import_emojis_batch(gid, [src], auto_convert=first_convert)
        dm.import_emojis_batch(gid, [src], auto_convert=second_convert)
    else:
        dm.import_emoji(gid, src, auto_convert=first_convert)
        dm.import_emoji(gid, src, auto_convert=second_convert)
    return len(dm.get_emojis_by_group(gid))


# The core regression: converting stores a gif whose hash differs from the
# raw source, so only comparing stored hashes allowed a second import.
check("单独导入 转换开→关 去重", import_twice(True, False, False) == 1)
check("单独导入 转换关→开 去重", import_twice(False, True, False) == 1)
check("批量导入 转换开→关 去重", import_twice(True, False, True) == 1)
check("批量导入 转换关→开 去重", import_twice(False, True, True) == 1)
check("单独导入 转换开→开 去重", import_twice(True, True, False) == 1)
check("批量导入 转换开→开 去重", import_twice(True, True, True) == 1)

# The original hash must be persisted so the reverse direction can match too.
dm, tmp = fresh_dm("gifmgr_dedup_src_")
gid = dm.create_group("G", "image")
src = os.path.join(tmp, "q.png")
Image.new("RGB", (80, 60), (10, 20, 30)).save(src)
dm.import_emoji(gid, src, auto_convert=True)
row = dm.get_emojis_by_group(gid)[0]
check("转换导入保存原始哈希 src_hash", bool(row.get("src_hash")),
      f"content={row.get('content_hash','')[:8]} src={row.get('src_hash','')[:8]}")


# ------------------------------------------------------ 2. search + drag
import app.widgets.emoji_grid as eg

_gsrc = __import__("inspect").getsource(eg.EmojiGridWidget._refresh_cards_after_merge)
check("拖拽后重载带搜索关键词", "_filter_keyword" in _gsrc)
check("load_emojis 接收关键词", "keyword" in
      __import__("inspect").getsource(eg.EmojiGridWidget.load_emojis)[:200])
_mwsrc = __import__("inspect").getsource(
    __import__("app.main_window", fromlist=["x"]).MainWindow._refresh_emoji_grid)
check("主窗口传递关键词", "keyword=keyword" in _mwsrc)

# functional: grid stores the keyword and reuse reload keeps filtering
dm, tmp = fresh_dm("gifmgr_search_")
gid = dm.create_group("G", "image")
for i in range(3):
    p = os.path.join(tmp, f"a{i}.png")
    Image.new("RGB", (60, 60), (i * 60, 100, 150)).save(p)
    dm.import_emoji(gid, p, auto_convert=False)
from app.widgets.emoji_grid import EmojiGridWidget
grid = EmojiGridWidget()
grid.set_data_manager(dm)
filtered = dm.get_emojis_by_group(gid, "a1")
grid.current_group_id = gid
grid.load_emojis(filtered, "image", keyword="a1")
check("网格保存搜索关键词", grid._filter_keyword == "a1", grid._filter_keyword)
check("网格数据为过滤子集", len(grid._data) == 1, len(grid._data))
# a lightweight refresh must keep the filter (previously reloaded all 3)
grid._refresh_cards_after_merge()
check("轻量刷新后仍为过滤子集", len(grid._data) == 1, len(grid._data))


# ------------------------------------------------------- 4. edit mode sync
dm, tmp = fresh_dm("gifmgr_edit_")
gid = dm.create_group("G", "image")
for i in range(6):
    p = os.path.join(tmp, f"e{i}.png")
    Image.new("RGB", (60, 60), (i * 30, 80, 160)).save(p)
    dm.import_emoji(gid, p, auto_convert=False)
from PySide6.QtWidgets import QScrollArea
from PySide6.QtCore import Qt as _Qt
# The grid materializes cards lazily from the enclosing scroll area's
# viewport, so host it exactly like the app does.
# 网格依赖外层滚动区视口做懒加载建卡，故按应用方式承载。
_win = QScrollArea()
_win.resize(900, 620)
_win.setWidgetResizable(True)
_win.setHorizontalScrollBarPolicy(_Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
grid2 = EmojiGridWidget()
grid2.set_data_manager(dm)
grid2.current_group_id = gid
_win.setWidget(grid2)
_win.show()
grid2.load_emojis(dm.get_emojis_by_group(gid), "image")
app.processEvents()
grid2.enter_edit_mode()
app.processEvents()
check("进入编辑模式", grid2.in_edit_mode() is True)
# simulate selecting everything the way the main window does
for em in grid2._data:
    grid2._selection[str(em["id"])] = em
grid2._sync_selection_mode_on_rebuild()
app.processEvents()
_sel_ids = {str(k) for k in grid2._selection}
_vis_ids = {str(c._emoji.get("id")) for c in grid2._items}
check("选中集合与可见卡一致", _sel_ids == _vis_ids,
      f"sel={len(_sel_ids)} vis={len(_vis_ids)}")
# every visible card that is selected must actually show as checked
_mismatch = [c for c in grid2._items
             if str(c._emoji.get("id")) in _sel_ids and not c.is_checked()]
check("选中卡片角标已勾选", not _mismatch, f"mismatch={len(_mismatch)}")
# clear then re-sync: no stale checked badges may remain
grid2._selection.clear()
grid2._sync_selection_mode_on_rebuild()
app.processEvents()
_stale = [c for c in grid2._items if c.is_checked()]
check("清空后无残留勾选", not _stale, f"stale={len(_stale)}")

# Searching while in edit mode must prune the selection to the visible set,
# otherwise the hidden ids inflate the count and break select-all/delete.
# 编辑模式下搜索必须把选中集合修剪到可见集合，否则隐藏 id 会撑大计数，
# 使全选/删除行为错乱。
for em in grid2._data:
    grid2._selection[str(em["id"])] = em
grid2._sync_selection_mode_on_rebuild()
app.processEvents()
_before = len(grid2._selection)
grid2.load_emojis(dm.get_emojis_by_group(gid, "e1"), "image", keyword="e1")
app.processEvents()
_after = len(grid2._selection)
_vis_after = {str(c._emoji.get("id")) for c in grid2._items}
check("搜索后选中被修剪", _after == 1, f"before={_before} after={_after}")
check("选中集合 ⊆ 可见集合", {str(k) for k in grid2._selection} <= _vis_after
      or not _vis_after, f"sel={_after} vis={len(_vis_after)}")
check("修剪后计数与可见一致",
      grid2.selection_count() <= len(grid2._data),
      f"count={grid2.selection_count()} data={len(grid2._data)}")
grid2.exit_edit_mode()

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n1.0.5 修复验证: {n_pass}/{len(RES)} 通过")
sys.stdout.flush()
drain_and_exit(0 if n_pass == len(RES) else 1)
