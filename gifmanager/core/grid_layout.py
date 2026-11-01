"""Pure grid-layout arithmetic: column packing, redistribution and merging.

These functions take lists and return lists. No database, no filesystem, no
toolkit — which is what makes the same layout rules reusable by a future web or
mobile front-end, and what makes them testable without a fixture.

纯网格布局运算：分列、重分配与合并。

这些函数只接收列表并返回列表。没有数据库、没有文件系统、没有界面工具包——正因
如此，同一套布局规则可以被将来的 Web 或移动端前端复用，也无需夹具即可测试。
"""
import math

# Cards narrower than this are unreadable; the packer never allocates a column
# below it. / 窄于此值的卡片无法阅读；摊列器不会分配比它更窄的列。
MIN_CARD_WIDTH = 80


def row_major_columns(ordered_ids, col_count):
    # Row-first assignment: card i goes to column i % K at row i // K. This is
    # the layout the grid renders top-to-bottom then left-to-right.
    # 行优先分配：第 i 张卡进入第 i % K 列第 i // K 行。网格即按此从上到下、再
    # 从左到右渲染。
    k = max(1, int(col_count))
    columns = [[] for _ in range(k)]
    for index, item in enumerate(ordered_ids):
        columns[index % k].append(item)
    return columns


def flatten_columns(columns):
    # Inverse of `row_major_columns`: read the columns back into one sequence in
    # visual order. / `row_major_columns` 的逆运算：按视觉顺序把各列读回一个序列。
    ordered = []
    height = max((len(col) for col in columns), default=0)
    for row in range(height):
        for col in columns:
            if row < len(col):
                ordered.append(col[row])
    return ordered


def column_count_of(rows, key="col_index"):
    # Number of distinct columns present in a group, at least 1. Used to keep a
    # re-sort or a prepend from changing the column count the user sees.
    # 分组中出现的不同列数，至少为 1。用于避免重排或置顶改变用户看到的列数。
    values = {int(row.get(key, 0) or 0) for row in rows}
    return len(values) or 1


def visual_order(rows):
    # Sort rows into the order the grid shows: by column, then by row position.
    # 把行排序为网格显示的顺序：先列、再列内位置。
    return sorted(
        rows,
        key=lambda row: (int(row.get("col_index", 0) or 0),
                         int(row.get("sort_order", 0) or 0)),
    )


def pack_columns(rows, usable_width, spacing, width_of):
    # Greedy column allocation for cards that the user has not placed yet.
    #
    # Cards already marked `user_sorted` keep their column; each remaining card
    # is appended to a new column when the total width plus the gap plus the new
    # card still fits, and is otherwise appended to the currently shortest
    # column. That keeps the visual balance while never overflowing the
    # viewport width.
    #
    # Returns an ordered mapping {column index: [rows]} including the placed rows.
    #
    # 用户尚未放置的卡片的贪心分列。
    #
    # 已标记 `user_sorted` 的卡片保持原列；其余每张卡在"总宽 + 间隔 + 新卡宽"仍能
    # 容纳时开新列，否则追加到当前最短的列。这样既不溢出视口宽度，视觉上也均衡。
    #
    # 返回有序映射 {列号: [行]}，其中包含已放置的行。
    usable_width = max(1, int(usable_width))
    spacing = max(0, int(spacing))
    columns = {}
    for row in rows:
        if row.get("user_sorted"):
            columns.setdefault(int(row.get("col_index", 0) or 0), []).append(row)

    pending = [row for row in rows if not row.get("user_sorted")]
    for row in pending:
        new_width = min(max(width_of(row), MIN_CARD_WIDTH), usable_width)
        widths = {ci: max(width_of(x) for x in lst) for ci, lst in columns.items()}
        counts = {ci: len(lst) for ci, lst in columns.items()}
        total = sum(widths.values()) + spacing * max(0, len(widths) - 1)
        if not columns or total + spacing + new_width <= usable_width:
            next_index = max(columns) + 1 if columns else 0
            columns.setdefault(next_index, []).append(row)
        else:
            shortest = min(counts, key=counts.get)
            columns[shortest].append(row)
    return columns


def merge_columns(rows, source_columns, target_columns):
    # Move every card of `source_columns` into the target columns, always into
    # the currently shortest one so the result stays balanced. Target columns
    # that no longer exist fall back to every remaining column.
    #
    # Returns the new column mapping, or None when there is nothing to merge.
    #
    # 把 `source_columns` 的每张卡移入目标列，且总是进入当前最短的列，使结果保持
    # 均衡。目标列不存在时回退为所有剩余列。
    #
    # 返回新的列映射；无可合并内容时返回 None。
    columns = {}
    for row in rows:
        columns.setdefault(int(row.get("col_index", 0) or 0), []).append(row)
    for lst in columns.values():
        lst.sort(key=lambda row: int(row.get("sort_order", 0) or 0))

    pending = []
    for index in source_columns:
        pending.extend(columns.pop(index, []))
    if not pending or not columns:
        return None

    targets = [t for t in target_columns if t in columns] or list(columns.keys())
    for row in pending:
        shortest = min(targets, key=lambda ci: len(columns[ci]))
        columns[shortest].append(row)
    return columns


def compact_renumber(column_indices):
    # Map a sparse set of column numbers onto 0..N-1, preserving order. Text
    # groups use this so a deleted column leaves no gap in the add-column logic.
    # 把稀疏的列号映射到 0..N-1 且保持顺序。文字分组用它，使删除一列后新增列的
    # 逻辑不会遇到空洞。
    return {old: new for new, old in enumerate(sorted(set(column_indices)))}


def distribute_evenly(row_count, col_count):
    # Height of each column when `row_count` cards are spread over `col_count`
    # columns row-first. A non-Qt front-end can size its container from this.
    # 行优先把 `row_count` 张卡摊到 `col_count` 列时，每列的高度。非 Qt 前端可用它
    # 计算容器尺寸。
    k = max(1, int(col_count))
    if row_count <= 0:
        return [0] * k
    rows = math.ceil(row_count / k)
    return [min(rows, max(0, row_count - index * rows)) for index in range(k)]


def uniform_rects(count, card_width, card_height, spacing, usable_width,
                  margin=0):
    # Rectangles for a grid of equal-sized cards, filled left to right and then
    # top to bottom.
    #
    # `usable_width` is the space actually available for cards; the column count
    # is derived from it, so the caller never has to compute "how many fit" and
    # the layout cannot overflow the viewport.
    #
    # Returns (rects, total_height, per_row). `rects` maps the card's index to
    # `(x, y, width, height)`.
    # 等尺寸卡片网格的矩形，从左到右、再从上到下填充。
    #
    # `usable_width` 是真正可用于卡片的空间；列数由它推导，因此调用方无需自己算
    # "能放几个"，布局也不会溢出视口。
    #
    # 返回 (矩形表, 总高度, 每行列数)。`rects` 把卡片下标映射到
    # `(x, y, 宽, 高)`。
    count = max(0, int(count))
    if count == 0:
        return {}, 0, 0
    card_width = max(1, int(card_width))
    card_height = max(1, int(card_height))
    spacing = max(0, int(spacing))
    usable = max(1, int(usable_width)) - 2 * max(0, int(margin))

    # At least one column, even when the window is narrower than a single card:
    # a horizontally scrolling grid is worse than a slightly overflowing one.
    # 至少一列，即使窗口比单张卡片还窄：横向滚动的网格比略微溢出更糟。
    per_row = max(1, (usable + spacing) // (card_width + spacing))
    # Centre the row so the leftover space is split evenly; an odd remainder
    # leaves the extra pixel on the right.
    # 整行居中，使剩余空间均分；奇数余量把多出的那一像素留在右侧。
    row_width = per_row * card_width + (per_row - 1) * spacing
    left = max(0, int(margin)) + max(0, (usable - row_width) // 2)

    rects = {}
    for index in range(count):
        row = index // per_row
        column = index % per_row
        rects[index] = (
            left + column * (card_width + spacing),
            max(0, int(margin)) + row * (card_height + spacing),
            card_width,
            card_height,
        )
    rows = (count + per_row - 1) // per_row
    total_height = (2 * max(0, int(margin)) + rows * card_height
                    + max(0, rows - 1) * spacing)
    return rects, total_height, per_row


def grid_rects(rows, metrics, usable_width):
    # Rectangles for a grid of cards keyed by their row id.
    #
    # `rows` is a sequence of mappings (each with an `id`), and `metrics`
    # supplies the card box and spacing. Returns `{row id: (x, y, w, h)}`, which
    # is the shape both the Qt grid and a web front-end can consume unchanged.
    # 以行的 id 为键的卡片矩形。
    #
    # `rows` 是一组映射（各含 `id`），`metrics` 提供卡片尺寸与间距。返回
    # `{行 id: (x, y, 宽, 高)}`——Qt 网格与 Web 前端都能原样消费这个形状。
    ids = [row.get("id") for row in rows]
    boxes, total_height, per_row = uniform_rects(
        len(ids),
        metrics.card_width,
        metrics.card_height,
        metrics.spacing,
        usable_width,
        metrics.margin,
    )
    rects = {}
    for index, emoji_id in enumerate(ids):
        box = boxes.get(index)
        if box is not None:
            rects[emoji_id] = box
    rects_height = total_height
    return rects


def total_height(rects):
    # Lowest bottom edge across a rectangle table /
    # 矩形表中最下方的底边
    if not rects:
        return 0
    return max(int(rect[1]) + int(rect[3]) for rect in rects.values())


def total_width(rects):
    if not rects:
        return 0
    return max(int(rect[0]) + int(rect[2]) for rect in rects.values())


def rect_contains(rect, x, y):
    # Point-in-rectangle test with the same tuple shape `uniform_rects` emits /
    # 与 `uniform_rects` 产出相同元组形状的"点在矩形内"判断
    if rect is None:
        return False
    return (rect[0] <= x <= rect[0] + rect[2]
            and rect[1] <= y <= rect[1] + rect[3])


def hit_test(rects, x, y):
    # Id of the rectangle containing a point, or None. Scans from the end so the
    # topmost (last drawn) card wins when rectangles overlap.
    # 包含该点的矩形 id，无则 None。从末尾开始扫描，使矩形重叠时最上层（最后绘制）
    # 的卡片胜出。
    for emoji_id in reversed(list(rects.keys())):
        if rect_contains(rects[emoji_id], x, y):
            return emoji_id
    return None


__all__ = [
    "MIN_CARD_WIDTH",
    "column_count_of",
    "compact_renumber",
    "distribute_evenly",
    "flatten_columns",
    "grid_rects",
    "hit_test",
    "merge_columns",
    "pack_columns",
    "rect_contains",
    "row_major_columns",
    "total_height",
    "total_width",
    "uniform_rects",
    "visual_order",
]
