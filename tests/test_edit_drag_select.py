"""Verify long-press drag range-selection in multi-select edit mode:
- a long press followed by a move paints ONE state over the swept cards
- the state is decided from the anchor (unselected -> select, selected ->
  deselect) and never toggles individual cards back and forth
- a plain click (no long press) still toggles a single card
验证多选编辑模式下的长按拖动范围选择：
- 长按后移动会把"同一种状态"涂抹到扫过的卡片
- 状态由锚点决定（未选中→选中，已选中→取消），不会逐项反复翻转
- 普通点击（未长按）仍是单卡切换
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

TMP = tempfile.mkdtemp(prefix="gifmgr_dragsel_")
import app.models.data_manager as dm_mod
dm_mod._app_data_dir = lambda: os.path.join(TMP, "data")

from PySide6.QtWidgets import QApplication, QScrollArea
from PySide6.QtCore import Qt, QEvent, QPointF, QRect
from PySide6.QtGui import QMouseEvent, QContextMenuEvent

from app.models.data_manager import DataManager
from app.widgets.emoji_item import EmojiItem
from app.widgets.emoji_grid import EmojiGridWidget

app = QApplication(sys.argv)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {str(detail)[:110]}")


def make_event(kind, local_pt, global_pt, buttons=Qt.MouseButton.LeftButton):
    return QMouseEvent(kind, QPointF(local_pt), QPointF(global_pt),
                       Qt.MouseButton.LeftButton, buttons,
                       Qt.KeyboardModifier.NoModifier)


dm = DataManager()
gid = dm.create_group("G", "image")
for i in range(6):
    p = os.path.join(TMP, f"a{i}.gif")
    with open(p, "wb") as f:
        f.write(b"GIF89a" + b"\x00" * (20 + i))
    dm.import_emoji(gid, p, auto_convert=False)

sa = QScrollArea()
sa.resize(1000, 700)
sa.setWidgetResizable(True)
grid = EmojiGridWidget()
grid.set_data_manager(dm)
grid.current_group_id = gid
sa.setWidget(grid)
sa.show()
grid.load_emojis(dm.get_emojis_by_group(gid), "image")
app.processEvents()
# Spread the cards over 3 columns so the "path vs rectangle" behaviour is
# actually exercised (a single column has no off-path card).
# 把卡片铺成 3 列，使"路径 vs 矩形"的行为真正可测（单列没有路径外的卡片）。
dm.rearrange_columns(gid, 3)
grid._refresh_cards_after_merge()
app.processEvents()
grid.enter_edit_mode()
app.processEvents()
cards = list(grid._items)
check("进入编辑模式且有卡片", grid.in_edit_mode() and len(cards) >= 2,
      f"cards={len(cards)}")
_cols = len({int(e.get("col_index", 0)) for e in dm.get_emojis_by_group(gid)})
check("测试布局为多列", _cols >= 2, f"cols={_cols}")


def card_global_center(card):
    return card.mapToGlobal(card.rect().center())


# --- 1. long press on an UNSELECTED anchor -> sweep SELECTS ---------------
anchor = cards[0]
targets = cards[1:4]
anchor.set_checked(False)
# arm the gesture the way the long-press timer would / 按长按定时器的方式武装
anchor._arm_range_select()
anchor._on_long_press()
# move onto the targets one by one / 依次移动到目标卡片
for t in targets:
    gp = card_global_center(t)
    anchor.mouseMoveEvent(make_event(QEvent.Type.MouseMove,
                                     anchor.rect().center(), gp))
app.processEvents()
sel = [c.is_checked() for c in [anchor] + targets]
check("长按未选中卡片后扫过 -> 全部选中", all(sel), sel)

# --- 2. sweeping an already-selected card in SELECT state keeps it selected
# (no per-item toggling) / 选中态下扫过已选卡片不会把它取消
gp_again = card_global_center(targets[0])
anchor.mouseMoveEvent(make_event(QEvent.Type.MouseMove,
                                 anchor.rect().center(), gp_again))
check("选中态重复扫过仍为选中", targets[0].is_checked())

# release ends the gesture / 松开结束手势
anchor.mouseReleaseEvent(make_event(QEvent.Type.MouseButtonRelease,
                                    anchor.rect().center(),
                                    card_global_center(anchor)))
check("松开后手势结束", not anchor._range_select_active)

# --- 3. long press on a SELECTED anchor -> sweep DESELECTS ---------------
anchor2 = cards[4]
anchor2.set_checked(True)
victim = cards[5]
victim.set_checked(True)
anchor2._arm_range_select()
anchor2._on_long_press()
anchor2.mouseMoveEvent(make_event(QEvent.Type.MouseMove,
                                  anchor2.rect().center(),
                                  card_global_center(victim)))
app.processEvents()
check("长按已选卡片后扫过 -> 全部取消",
      not anchor2.is_checked() and not victim.is_checked(),
      f"anchor={anchor2.is_checked()} victim={victim.is_checked()}")

# sweeping an UNSELECTED card in DESELECT state keeps it unselected /
# 取消态下扫过未选卡片不会把它选中
cards[1].set_checked(False)
anchor2.mouseMoveEvent(make_event(QEvent.Type.MouseMove,
                                  anchor2.rect().center(),
                                  card_global_center(cards[1])))
check("取消态扫过未选卡片仍为未选", not cards[1].is_checked())
anchor2.mouseReleaseEvent(make_event(QEvent.Type.MouseButtonRelease,
                                     anchor2.rect().center(),
                                     card_global_center(anchor2)))

# --- 4. plain click (no long press) still toggles one card ---------------
plain = cards[2]
before = plain.is_checked()
plain._arm_range_select()           # press, but the timer never fires
plain.mouseReleaseEvent(make_event(QEvent.Type.MouseButtonRelease,
                                   plain.rect().center(),
                                   card_global_center(plain)))
check("普通点击切换单卡", plain.is_checked() != before,
      f"{before} -> {plain.is_checked()}")

# --- 5. selection set matches the cards that show as checked --------------
mismatch = [c for c in grid._items
            if c.is_checked() != (str(c._emoji.get("id", "")) in grid._selection)]
check("勾选状态与选中集合一致", not mismatch, f"mismatch={len(mismatch)}")
check("计数等于选中数量", grid.selection_count() == len(grid._selection))

# --- 6. deleting deletes exactly the selected ones ------------------------
selected_ids = {e["id"] for e in grid.selected_emojis()}
check("选中集合可删除（id 齐全）", len(selected_ids) == grid.selection_count(),
      f"ids={len(selected_ids)} count={grid.selection_count()}")

# --- 7. a SHORT sweep must not select far-away cards (coordinate bug) -----
# The old code mixed the container's coordinates with card-local ones, which
# misplaced the rectangle origin and swept a much larger area than dragged.
# 短距离拖动不得选中远处卡片（旧实现混用坐标系，矩形起点错位会框住一大片）。
for c in grid._items:
    c.set_checked(False)
grid._selection.clear()
anchor3 = cards[0]
# nearest neighbour by centre distance / 取中心距离最近的邻居
ac = anchor3.geometry().center()
others = sorted(cards[1:],
                key=lambda c: (c.geometry().center() - ac).manhattanLength())
near = others[0]
far = others[-1]
anchor3._arm_range_select()
anchor3._on_long_press()
anchor3.mouseMoveEvent(make_event(QEvent.Type.MouseMove,
                                  anchor3.rect().center(),
                                  card_global_center(near)))
app.processEvents()
check("短距离扫过只选中锚点与邻居",
      anchor3.is_checked() and near.is_checked(), 
      f"anchor={anchor3.is_checked()} near={near.is_checked()}")
check("远处卡片未被选中（无坐标错位）", not far.is_checked(),
      f"far_selected={far.is_checked()} ids={[c._emoji['id'] for c in cards]}")
anchor3.mouseReleaseEvent(make_event(QEvent.Type.MouseButtonRelease,
                                     anchor3.rect().center(),
                                     card_global_center(anchor3)))

# --- 8. RIGHT click must not change the selection ------------------------
rc = cards[2]
rc.set_checked(False)
before = rc.is_checked()
# right press + right release in selection mode / 右键按下与松开
arm_ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(rc.rect().center()),
                     QPointF(card_global_center(rc)), Qt.MouseButton.RightButton,
                     Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier)
rc.mousePressEvent(arm_ev)
rel_ev = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(rc.rect().center()),
                     QPointF(card_global_center(rc)), Qt.MouseButton.RightButton,
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
rc.mouseReleaseEvent(rel_ev)
app.processEvents()
check("右键不改变选中状态", rc.is_checked() == before,
      f"{before} -> {rc.is_checked()}")
# and a LEFT click still toggles / 左键仍可切换
lc = cards[3]
before_l = lc.is_checked()
lc._arm_range_select()
lc.mouseReleaseEvent(make_event(QEvent.Type.MouseButtonRelease,
                                lc.rect().center(), card_global_center(lc)))
check("左键仍可切换选中", lc.is_checked() != before_l,
      f"{before_l} -> {lc.is_checked()}")

# --- 9. right-click still reaches the grid's context menu ---------------
_seen = []
grid.emoji_right_clicked.connect(lambda em, pos: _seen.append(em.get("id")))
cm = QContextMenuEvent(QContextMenuEvent.Reason.Mouse,
                       rc.rect().center(), card_global_center(rc))
app.sendEvent(rc, cm)
app.processEvents()
check("右键仍可弹出上下文菜单", len(_seen) > 0, f"emitted={len(_seen)}")

# --- 10. the sweep is PATH-based, not a start-to-end rectangle ----------
# Dragging diagonally must paint only the cards the cursor passed over, not
# every card inside the bounding rectangle.
# 扫过是"路径式"而非起止矩形：对角拖动只应涂到鼠标经过的卡片，
# 而不是外接矩形内的全部卡片。
for c in grid._items:
    c.set_checked(False)
grid._selection.clear()
grid.reset_drag_selection()
anchor4 = cards[0]
a_ctr = anchor4.geometry().center()
farthest = max(cards[1:],
               key=lambda c: (c.geometry().center() - a_ctr).manhattanLength())
f_ctr = farthest.geometry().center()
# bounding rectangle of the drag / 拖动路径的外接矩形
bbox = QRect(a_ctr, f_ctr).normalized()
# candidates inside the bbox but off the straight path / 在矩形内但不在直线路径上的卡
inside = [c for c in cards
          if c is not anchor4 and c is not farthest
          and bbox.intersects(c.geometry())]
anchor4._arm_range_select()
anchor4._on_long_press()
anchor4.mouseMoveEvent(make_event(QEvent.Type.MouseMove,
                                  anchor4.rect().center(),
                                  card_global_center(farthest)))
app.processEvents()
check("路径端点已选中",
      anchor4.is_checked() and farthest.is_checked(),
      f"anchor={anchor4.is_checked()} far={farthest.is_checked()}")
# The straight path passes through the bbox corners; any card inside the bbox
# whose centre is far from the path must stay unselected.
def _dist_to_segment(p, a, b):
    ax, ay, bx, by = a.x(), a.y(), b.x(), b.y()
    px, py = p.x(), p.y()
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) /
                      float(dx * dx + dy * dy)))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5


off_path = [c for c in inside
            if _dist_to_segment(c.geometry().center(), a_ctr, f_ctr) >
            max(c.width(), c.height())]
if off_path:
    wrong = [c for c in off_path if c.is_checked()]
    check("矩形内但不在路径上的卡片未被选中", not wrong,
          f"wrongly_selected={len(wrong)} of {len(off_path)}")
else:
    check("矩形内但不在路径上的卡片未被选中", True, "no off-path card to test")
anchor4.mouseReleaseEvent(make_event(QEvent.Type.MouseButtonRelease,
                                     anchor4.rect().center(),
                                     card_global_center(anchor4)))

# --- 11. sweeping back and forth must not re-toggle (state is fixed) ----
grid.reset_drag_selection()
anchor5 = cards[0]
anchor5.set_checked(False)
anchor5._arm_range_select()
anchor5._on_long_press()
for _ in range(3):
    anchor5.mouseMoveEvent(make_event(QEvent.Type.MouseMove,
                                      anchor5.rect().center(),
                                      card_global_center(cards[1])))
    anchor5.mouseMoveEvent(make_event(QEvent.Type.MouseMove,
                                      anchor5.rect().center(),
                                      card_global_center(anchor5)))
app.processEvents()
check("来回扫过仍保持选中（不反弹）",
      anchor5.is_checked() and cards[1].is_checked(),
      f"a={anchor5.is_checked()} b={cards[1].is_checked()}")
anchor5.mouseReleaseEvent(make_event(QEvent.Type.MouseButtonRelease,
                                     anchor5.rect().center(),
                                     card_global_center(anchor5)))

n_pass = sum(1 for _, ok in RES if ok)
print(f"\n长按拖动批量选择验证: {n_pass}/{len(RES)} 通过")
sys.stdout.flush()
drain_and_exit(0 if n_pass == len(RES) else 1)
