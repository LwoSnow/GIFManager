"""Column-ordering repository: text-card containers, sorting and redistribution.

Every method here follows the same shape — read the group's rows, compute a pure
list transformation, write the result in one transaction. The arithmetic itself
lives in `gifmanager.core.grid_layout`, so the same rules can back a non-Qt
front-end.

列排序仓储：文字卡片容器、排序与重分配。

此处每个方法形状一致——读取分组行、做纯列表变换、在一个事务里写回。运算本身位于
`gifmanager.core.grid_layout`，因此同一套规则可以支撑非 Qt 前端。
"""
import logging

from gifmanager.core import grid_layout
from gifmanager.core.store import schema

log = logging.getLogger("GIFManager")

# Sort keys accepted by `sort_group_emojis` / `sort_group_emojis` 接受的排序键
SORT_NAME = "name"
SORT_TIME = "time"
SORT_FREQ = "freq"

# Window within which clicking the same sort key again flips the direction /
# 再次点击同一排序键时切换方向的窗口
SORT_TOGGLE_SECONDS = 10.0


class SortToggle:
    # Decides the direction for a sort click: clicking the same key again
    # within `SORT_TOGGLE_SECONDS` flips the direction, anything else starts
    # ascending. Kept as a tiny stateful object so the rule is testable without
    # a widget — it used to be buried inside the grid's click handler.
    # 决定一次排序点击的方向：在 `SORT_TOGGLE_SECONDS` 内再次点击同一键会切换方向，
    # 其他情况从升序开始。做成一个极小的有状态对象，使该规则无需控件即可测试——
    # 它此前埋在网格的点击处理函数里。
    def __init__(self, window_seconds=SORT_TOGGLE_SECONDS):
        self._window = float(window_seconds)
        self._last_key = None
        self._last_at = 0.0

    def click(self, sort_key, now):
        # Returns the direction to use: True for descending /
        # 返回要使用的方向：True 表示降序
        if sort_key == self._last_key and (now - self._last_at) <= self._window:
            descending = not self._last_descending
        else:
            descending = False
        self._last_key = sort_key
        self._last_at = now
        self._last_descending = descending
        return descending

    def reset(self):
        self._last_key = None
        self._last_at = 0.0
        self._last_descending = False


class OrderingRepository:
    # "All" grid ordering, text-group column containers and redistribution.
    # "全部"网格排序、文字分组列容器与重分配。

    # ---- single-card placement / 单卡放置 --------------------------------

    def set_emoji_column(self, emoji_id, target_col, target_order):
        # Move one card into a column at a row index, touching only rows the
        # user has placed (`user_sorted=1`) so the automatic packer's results
        # are not disturbed.
        # 把一张卡移入某列的行位置，只影响用户已放置的行（`user_sorted=1`），不干扰
        # 自动摊列的结果。
        row = self._conn.execute(
            "SELECT group_id FROM emojis WHERE id=?", (emoji_id,)).fetchone()
        if not row:
            return False
        group_id = row[0]
        existing = self._conn.execute(
            "SELECT id FROM emojis WHERE group_id=? AND col_index=? AND id!=? "
            "AND user_sorted=1 ORDER BY sort_order",
            (group_id, target_col, emoji_id)).fetchall()
        ids = [r[0] for r in existing]
        target_order = max(0, min(target_order, len(ids)))
        ids.insert(target_order, emoji_id)
        for index, other_id in enumerate(ids):
            self._conn.execute(
                "UPDATE emojis SET col_index=?, sort_order=?, user_sorted=1"
                " WHERE id=?",
                (target_col, index, other_id))
        self._commit()
        return True

    def swap_emoji_columns(self, emoji_a, emoji_b):
        # Swap two cards' column and position (drag onto the middle of a card).
        # Refuses cards in different groups, which would corrupt both layouts.
        # 交换两张卡片的列与列内位置（拖到卡片中间时）。拒绝跨分组的卡片，否则会破坏
        # 两边的布局。
        rows = self._conn.execute(
            "SELECT id, group_id, col_index, sort_order FROM emojis"
            " WHERE id IN (?,?)",
            (emoji_a, emoji_b)).fetchall()
        if len(rows) != 2:
            return False
        info = {r[0]: {"group": r[1], "col": r[2], "order": r[3]} for r in rows}
        if info[emoji_a]["group"] != info[emoji_b]["group"]:
            return False
        a, b = info[emoji_a], info[emoji_b]
        self._conn.execute(
            "UPDATE emojis SET col_index=?, sort_order=?, user_sorted=1 WHERE id=?",
            (b["col"], b["order"], emoji_a))
        self._conn.execute(
            "UPDATE emojis SET col_index=?, sort_order=?, user_sorted=1 WHERE id=?",
            (a["col"], a["order"], emoji_b))
        self._commit()
        return True

    # ---- batch packing / 批量摊列 ---------------------------------------

    def assign_unassigned_columns(self, group_id, usable_w, spacing, width_of):
        # Allocate columns for the cards the user has not placed yet: open a new
        # column while the total width still fits, otherwise append to the
        # currently shortest one. Returns the number of cards allocated.
        # 为用户尚未放置的卡片分配列：总宽仍能容纳时开新列，否则追加到当前最短的列。
        # 返回分配的卡片数。
        emojis = self.get_emojis_by_group(group_id)
        columns = grid_layout.pack_columns(emojis, usable_w, spacing, width_of)
        unassigned = [e for e in emojis if not e.get("user_sorted")]
        if not unassigned:
            return 0
        with self.transaction() as conn:
            for column_index, rows in columns.items():
                for order, emoji in enumerate(rows):
                    conn.execute(
                        "UPDATE emojis SET col_index=?, sort_order=?, user_sorted=1"
                        " WHERE id=?",
                        (column_index, order, emoji["id"]))
        return len(unassigned)

    def assign_new_text_column(self, group_id, usable_w, spacing, width_of,
                               natural_width):
        # Place one more text card in a new column when the viewport still has
        # room, otherwise fall back to the shortest existing column.
        # 视口仍有空间时，把新的文字卡片放入一个新列；否则回退到现有的最短列。
        emojis = self.get_emojis_by_group(group_id)
        columns, counts = self._column_metrics(emojis, width_of)
        widths = list(columns.values())
        total = sum(widths) + spacing * max(0, len(widths) - 1)
        new_width = min(max(natural_width, grid_layout.MIN_CARD_WIDTH), usable_w)
        if not widths or total + spacing + new_width <= usable_w:
            return max(columns) + 1 if columns else 0
        return min(counts, key=counts.get)

    @staticmethod
    def _column_metrics(emojis, width_of):
        columns = {}
        counts = {}
        for emoji in emojis:
            index = int(emoji.get("col_index", 0) or 0)
            columns[index] = max(columns.get(index, 0), width_of(emoji))
            counts[index] = counts.get(index, 0) + 1
        return columns, counts

    # ---- redistribution / 重分配 ----------------------------------------

    def rearrange_columns(self, group_id, col_count):
        # One-click tidy: redistribute every card row-first in its current
        # visual order. Returns the number of cards rewritten.
        # 一键整理：按当前视觉顺序行优先重新分列。返回重写的卡片数。
        emojis = self.get_emojis_by_group(group_id)
        if not emojis:
            return 0
        return self._redistribute(
            [e["id"] for e in emojis], group_id, col_count)

    def sort_group_emojis(self, group_id, by=SORT_NAME, desc=False):
        # Sort a group's cards and redistribute them row-first, keeping the
        # current column count so a sort is a single tidy action rather than a
        # relayout. Returns the number of cards sorted.
        # 排序分组卡片并行优先重分配，保留当前列数，使排序是一次整理而非重新布局。
        # 返回排序的卡片数。
        emojis = self.get_emojis_by_group(group_id)
        if not emojis:
            return 0
        if by == SORT_TIME:
            # created_at has second precision; tie-break by id (insert order) /
            # created_at 秒级精度，同秒用 id（插入顺序）区分
            emojis.sort(key=lambda e: (e.get("created_at", ""), e["id"]), reverse=desc)
        elif by == SORT_FREQ:
            # Ascending = least used first, descending = most used first /
            # 升序 = 低频在前，降序 = 高频在前
            emojis.sort(key=lambda e: e.get("use_count", 0), reverse=desc)
        else:
            # Name sort: case-insensitive, empty names last /
            # 名称排序：忽略大小写，空名排后
            emojis.sort(
                key=lambda e: (e.get("original_name", "") or "").lower(),
                reverse=desc)
        col_count = grid_layout.column_count_of(emojis)
        return self._redistribute([e["id"] for e in emojis], group_id, col_count)

    def prepend_emojis(self, group_id, new_ids):
        # Put freshly added cards at the top-left: prepend them in insertion
        # order to the global order and redistribute, so existing cards shift
        # back. Returns the number of cards redistributed.
        # 把新增卡片放到左上角：按加入顺序插到全局顺序最前并重分配，旧卡整体后移。
        # 返回重分配的卡片数。
        emojis = self.get_emojis_by_group(group_id)
        if not emojis:
            return 0
        ordered = grid_layout.visual_order(emojis)
        new_set = set(new_ids)
        old_ids = [e["id"] for e in ordered if e["id"] not in new_set]
        col_count = grid_layout.column_count_of(emojis)
        return self._redistribute(list(new_ids) + old_ids, group_id, col_count)

    def prepend_latest_imports(self, group_id, count):
        # Prepend the `count` most recently imported cards (one import batch),
        # in insertion order. / 把最近导入的 `count` 张卡片（单次导入批次）按加入
        # 顺序放到最前。
        if count <= 0:
            return 0
        emojis = self.get_emojis_by_group(group_id)
        if not emojis:
            return 0
        emojis.sort(key=lambda e: e["id"], reverse=True)  # newest first / 最新在前
        new_ids = [e["id"] for e in emojis[:count]]
        new_ids.reverse()  # insertion order: earliest first / 按加入顺序：先导入的在前
        return self.prepend_emojis(group_id, new_ids)

    def _redistribute(self, ordered_ids, group_id, col_count):
        # Row-first rewrite of the whole group in one transaction /
        # 在一个事务内行优先重写整个分组
        columns = grid_layout.row_major_columns(ordered_ids, col_count)
        with self.transaction() as conn:
            for column_index, ids in enumerate(columns):
                for order, emoji_id in enumerate(ids):
                    conn.execute(
                        "UPDATE emojis SET col_index=?, sort_order=?, user_sorted=1"
                        " WHERE id=?",
                        (column_index, order, emoji_id))
        return len(ordered_ids)

    # ---- merging / 合并 -------------------------------------------------

    def merge_columns_into(self, group_id, source_cols, target_cols):
        # Merge columns into the target columns, always into the currently
        # shortest one so the result stays balanced. Returns the number of cards
        # moved. / 把列并入目标列，且总是进入当前最短的列以保持均衡。返回移动的
        # 卡片数。
        emojis = self.get_emojis_by_group(group_id)
        columns = grid_layout.merge_columns(emojis, source_cols, target_cols)
        if columns is None:
            return 0
        moved = sum(len(rows) for index, rows in columns.items()
                    if index in set(source_cols))
        # `merge_columns` already moved the cards, so count them from the
        # difference between the original and merged layouts.
        # `merge_columns` 已移动卡片，因此用原始布局与合并后布局的差集计数。
        original = {int(e.get("col_index", 0) or 0) for e in emojis}
        remaining = set(columns.keys())
        moved = sum(1 for e in emojis
                    if int(e.get("col_index", 0) or 0) in original - remaining)
        with self.transaction() as conn:
            for column_index, rows in columns.items():
                for order, emoji in enumerate(rows):
                    conn.execute(
                        "UPDATE emojis SET col_index=?, sort_order=?, user_sorted=1"
                        " WHERE id=?",
                        (column_index, order, emoji["id"]))
        return moved

    # ---- column queries / 列查询 ----------------------------------------

    def text_max_col(self, group_id):
        row = self._conn.execute(
            "SELECT MAX(col_index) FROM emojis WHERE group_id=?", (group_id,)
        ).fetchone()
        return row[0] if row and row[0] is not None else -1

    def text_col_sizes(self, group_id):
        # Rows per column, keyed by column index. (Previously dead code; kept
        # because the merge logic and tests find it useful.)
        # 各列的行数，按列号索引。（此前是死代码；保留，因为合并逻辑与测试都用得上。）
        rows = self._conn.execute(
            "SELECT col_index, COUNT(*) FROM emojis WHERE group_id=? "
            "GROUP BY col_index", (group_id,)).fetchall()
        return {r[0]: r[1] for r in rows}

    def column_widths(self, group_id, width_of):
        # Natural width of each column, i.e. the widest card in it /
        # 各列的自然宽度，即该列最宽的卡片
        emojis = self.get_emojis_by_group(group_id)
        widths = {}
        for emoji in emojis:
            index = int(emoji.get("col_index", 0) or 0)
            widths[index] = max(widths.get(index, 0), width_of(emoji))
        return widths

    def compact_text_columns(self, group_id):
        # Renumber columns 0..N-1 so a deleted column leaves no gap /
        # 把列号重排为 0..N-1，使删除一列后不留下空洞
        rows = self._conn.execute(
            "SELECT col_index FROM emojis WHERE group_id=? "
            "GROUP BY col_index ORDER BY col_index", (group_id,)).fetchall()
        mapping = grid_layout.compact_renumber([r[0] for r in rows])
        with self.transaction() as conn:
            for old, new in mapping.items():
                if old != new:
                    conn.execute(
                        "UPDATE emojis SET col_index=? WHERE group_id=? AND"
                        " col_index=?", (new, group_id, old))
        return len(mapping)


__all__ = [
    "OrderingRepository",
    "SORT_FREQ",
    "SORT_NAME",
    "SORT_TIME",
    "SORT_TOGGLE_SECONDS",
    "SortToggle",
]
