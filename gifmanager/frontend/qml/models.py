"""List models making the backend directly bindable from QML.

A `ListView` in QML reads a model through roles, so exposing plain Python lists
would mean copying them into QML and re-copying them on every change. A
`QAbstractListModel` reports the change instead, and the view updates the affected
rows only — which is what makes a large library usable without a virtualisation
layer written by hand.

The model exposes no stylesheet, no colour and no pixel size: those belong to the
QML delegate, and keeping them out means the same model can back a different
visual design.

让后端可被 QML 直接绑定的列表模型。

QML 的 `ListView` 通过角色读取模型，因此暴露普通 Python 列表意味着把它们复制进 QML
并在每次变更时重新复制。`QAbstractListModel` 改为上报变更，视图只更新受影响的行——
这正是让大图库无需手写虚拟化层即可使用的原因。

模型不暴露任何样式表、颜色或像素尺寸：那些属于 QML 委托，把它们排除在外意味着同一个
模型可以支撑不同的视觉设计。
"""
import logging

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    Property,
    QSortFilterProxyModel,
    Qt,
    Signal,
    Slot,
)

from gifmanager.core import grid_layout

log = logging.getLogger("GIFManager")

# Text masonry metrics, matching the original project's `EmojiItem`: the card
# font, the fixed maximum card width, and the layout spacing between columns.
# 文字瀑布流的度量，与原项目的 `EmojiItem` 一致：卡片字体、固定的最大卡片宽度，以及
# 列间距。
TEXT_FONT_FAMILY = "Microsoft YaHei"
TEXT_FONT_POINT = 12
TEXT_MAX_WIDTH = 220
TEXT_MASONRY_SPACING = 8
# The width an image card reports to the packer — the theme's base card size,
# repeated here because the model layer cannot import the theme.
# 图片卡向摊列器报告的宽度——即主题的基础卡片尺寸；模型层不能导入主题，故在此重复。
TEXT_IMAGE_CARD_WIDTH = 100


class GroupListModel(QAbstractListModel):
    # The group bar as a model: one row per group, "All" first.
    # 作为模型的分组栏：每个分组一行，"全部"在最前。

    # Role numbers are explicit because QML reads them by NAME; the enum values are
    # what lets the delegate write `model.name` instead of `model.roleNames()`.
    # 角色编号是显式的，因为 QML 按"名称"读取；枚举值正是让委托能写 `model.name`
    # 而不是 `model.roleNames()` 的原因。
    IdRole = Qt.ItemDataRole.UserRole + 1
    NameRole = Qt.ItemDataRole.UserRole + 2
    TypeRole = Qt.ItemDataRole.UserRole + 3
    CountRole = Qt.ItemDataRole.UserRole + 4
    IsAllRole = Qt.ItemDataRole.UserRole + 5
    IsBuiltinRole = Qt.ItemDataRole.UserRole + 6
    IsCurrentRole = Qt.ItemDataRole.UserRole + 7

    changed = Signal()

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self._backend = backend
        self._groups = []
        self._counts = {}
        self._current_id = None
        self.reload()

    def roleNames(self):
        return {
            self.IdRole: b"groupId",
            self.NameRole: b"name",
            self.TypeRole: b"groupType",
            self.CountRole: b"count",
            self.IsAllRole: b"isAll",
            self.IsBuiltinRole: b"isBuiltin",
            self.IsCurrentRole: b"isCurrent",
        }

    # ---- data / 数据 -----------------------------------------------------

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._groups)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._groups)):
            return None
        group = self._groups[index.row()]
        if role == self.IdRole:
            return group["id"]
        if role == self.NameRole:
            # Built-in names (All, Default) are translated at display time: the
            # STORE keeps a stable key-ish name, and "全部" must follow the UI
            # language the way the original project's `tr("all_group")` did.
            # 内置名（全部、默认）在显示时翻译：存储层保留稳定的名字，而界面上的
            # “全部”须跟随界面语言——与原项目 `tr("all_group")` 的做法一致。
            if group.get("is_builtin"):
                key = ("all_group" if group["id"] == self._all_id()
                       else "default_group")
                translated = self._backend.tr(key)
                if translated:
                    return translated
            return group["name"]
        if role == self.TypeRole:
            return group["type"]
        if role == self.CountRole:
            return self._counts.get(group["id"], 0)
        if role == self.IsAllRole:
            return group["id"] == self._all_id()
        if role == self.IsBuiltinRole:
            return bool(group["is_builtin"])
        if role == self.IsCurrentRole:
            # The All view highlights the All tab: `_current_id` is None there,
            # which compared against the All group's REAL id left "全部" without
            # its selection colour.
            # “全部”视图高亮“全部”标签：此时 `_current_id` 为 None，与“全部”的
            # 真实 id 比较会让“全部”失去选中色。
            if self._current_id is None:
                return group["id"] == self._all_id()
            return group["id"] == self._current_id
        return None

    def _all_id(self):
        return self._backend.store._all_group_id()

    @Slot()
    def reload(self):
        # Rebuild the whole list. Groups are few (tens at most) so a full reset is
        # cheaper than a role-by-role diff, and the counts are re-queried in the
        # same pass rather than lazily per delegate.
        # 重建整个列表。分组很少（至多几十个），因此整体重置比逐角色求差更省，且计数在同
        # 一趟里重新查询，而不是每个委托惰性查询。
        self.beginResetModel()
        self._groups = self._backend.groups()
        self._counts = {}
        for group in self._groups:
            if group["id"] == self._all_id():
                # The All view folds duplicate content hashes, so its count is the
                # image-emoji total rather than the sum of the groups.
                # "全部"视图按内容哈希折叠，因此它的计数是图片表情总数，而不是各分组之和。
                self._counts[group["id"]] = self._backend.store.count_image_emojis()
            else:
                self._counts[group["id"]] = self._backend.store.count_emojis_in_group(
                    group["id"])
        self.endResetModel()
        self.changed.emit()

    # ---- selection / 选择 -----------------------------------------------

    @Property(int, notify=changed)
    def currentId(self):
        # -1 for the All view, because QML cannot carry a Python None through an
        # int property. The sentinel is documented rather than implicit.
        # 全部视图用 -1，因为 QML 无法把 Python 的 None 传过 int 属性。该哨兵值是文档化
        # 的而非隐含的。
        return -1 if self._current_id is None else int(self._current_id)

    @Slot(int)
    def select(self, group_id):
        # The All group's REAL id must normalise to the None sentinel, or every
        # "is this the All view" check downstream (canReorder, the packer, the
        # status line) sees a plain group where there is none.
        # "全部"的真实 id 必须归一化为 None 哨兵，否则下游所有"是否全部视图"的判断
        # （canReorder、摊列器、状态行）都会把全部视图当成普通分组。
        selected = None if group_id < 0 or group_id == self._all_id() \
            else group_id
        if selected == self._current_id:
            return
        self._current_id = selected
        if self._groups:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self._groups) - 1, 0),
                [self.IsCurrentRole])
        self.changed.emit()

    @Slot(str, result=bool)
    def selectByName(self, name):
        # Restoring the remembered group is by NAME, because the id is not stable
        # across a database rebuild. A missing name falls back to All rather than
        # leaving nothing selected.
        # 恢复记住的分组按"名称"，因为 id 在数据库重建后并不稳定。名称缺失时回退到"全部"，
        # 而不是什么都不选。
        if not name:
            self.select(-1)
            return False
        for group in self._groups:
            if group["name"] == name:
                self.select(group["id"])
                return True
        self.select(-1)
        return False

    @Slot(int, result=str)
    def nameOf(self, group_id):
        for group in self._groups:
            if group["id"] == group_id:
                return group["name"]
        return ""

    @Slot(int, result=str)
    def typeOf(self, group_id):
        for group in self._groups:
            if group["id"] == group_id:
                return group["type"]
        return "image"


class StickerListModel(QAbstractListModel):
    # The sticker grid as a model.
    #
    # The delegate decides the visual size, so the model carries the DATA a card
    # needs and the file path the image loader wants — not a pixmap. Loading the
    # image is the delegate's job, which is what keeps decoding off this class and
    # asynchronous in the view.
    # 作为模型的贴纸网格。
    #
    # 委托决定视觉尺寸，因此模型携带卡片所需的"数据"以及图像加载器需要的文件路径，而不
    # 是 pixmap。加载图像是委托的职责，这正是让解码留在这个类之外、并在视图中异步进行的
    # 原因。

    IdRole = Qt.ItemDataRole.UserRole + 1
    NameRole = Qt.ItemDataRole.UserRole + 2
    SourceRole = Qt.ItemDataRole.UserRole + 3
    IsTextRole = Qt.ItemDataRole.UserRole + 4
    TextRole = Qt.ItemDataRole.UserRole + 5
    UseCountRole = Qt.ItemDataRole.UserRole + 6
    SelectedRole = Qt.ItemDataRole.UserRole + 7
    WidthRole = Qt.ItemDataRole.UserRole + 8
    HeightRole = Qt.ItemDataRole.UserRole + 9
    # The stored position, exposed so a drag can name a DESTINATION rather than an offset.
    # Without these a front-end can only say "before/after this row", which the store
    # cannot express: it orders by (column, position within column), and the text-card
    # packer owns the columns.
    # 存储的位置，暴露出来使拖拽能指定"目的地"而不是"偏移量"。没有它们，前端只能说"在这一行的
    # 前/后"，而存储层无法表达这一点：它按（列, 列内位置）排序，而列由文字卡片摊列器拥有。
    ColumnRole = Qt.ItemDataRole.UserRole + 10
    OrderRole = Qt.ItemDataRole.UserRole + 11
    # The row's position in THIS model. A column proxy re-numbers its rows, so a
    # delegate under a proxy needs the original row to name a drag target.
    # 本行在本模型中的位置。列代理会重排行号，因此代理下的委托需要原始行号才能指名
    # 拖拽目标。
    RowRole = Qt.ItemDataRole.UserRole + 12

    countChanged = Signal()

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self._backend = backend
        self._rows = []
        self._selected = set()
        # Per-column pixel widths for a TEXT group's masonry, computed at load.
        # An image group leaves it empty: its cells are uniform.
        # 文字分组瀑布流的每列像素宽度，在加载时计算。图片分组保持为空：其单元格
        # 是均匀的。
        self._column_widths = {}
        self._group_id = None

    def roleNames(self):
        return {
            self.IdRole: b"stickerId",
            self.NameRole: b"name",
            self.SourceRole: b"source",
            self.IsTextRole: b"isText",
            self.TextRole: b"textContent",
            self.UseCountRole: b"useCount",
            self.SelectedRole: b"isSelected",
            self.WidthRole: b"naturalWidth",
            self.HeightRole: b"naturalHeight",
            self.ColumnRole: b"columnIndex",
            self.OrderRole: b"orderIndex",
            self.RowRole: b"modelRow",
        }

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        if role == self.IdRole:
            return row["id"]
        if role == self.NameRole:
            return row.get("original_name", "")
        if role == self.SourceRole:
            # A `file://` URL, which is the form `Image.source` expects. Building
            # it here rather than in QML keeps URL escaping in one place.
            # `file://` URL，即 `Image.source` 期望的形式。在此构建而非在 QML 里，使 URL
            # 转义只有一处。
            return self._source_url(row)
        if role == self.IsTextRole:
            return bool(row.get("text_content"))
        if role == self.TextRole:
            return row.get("text_content", "")
        if role == self.UseCountRole:
            return int(row.get("use_count", 0) or 0)
        if role == self.SelectedRole:
            return row["id"] in self._selected
        if role == self.WidthRole:
            return int(row.get("natural_width", 0) or 0)
        if role == self.HeightRole:
            return int(row.get("natural_height", 0) or 0)
        if role == self.ColumnRole:
            # -1 means "not placed by the user", which is the state the automatic packer
            # owns. A drag onto such a card is still meaningful: it places the dragged card
            # in the same column.
            # -1 表示"用户未放置"，那是自动摊列器拥有的状态。拖到这样一张卡片上仍然有意义：
            # 它把被拖的卡片放进同一列。
            value = row.get("col_index")
            return -1 if value is None else int(value)
        if role == self.OrderRole:
            return int(row.get("sort_order", 0) or 0)
        if role == self.RowRole:
            return index.row()
        return None

    def _source_url(self, row):
        path = self._backend.store.emoji_filepath(row)
        if not path:
            return ""
        from PySide6.QtCore import QUrl

        return QUrl.fromLocalFile(path).toString()

    # ---- content / 内容 --------------------------------------------------

    @Slot(int, str, result=int)
    def load(self, group_id, keyword):
        # Replace the contents for a group (or the All view when group_id < 0) and
        # return the row count, so a caller can branch on emptiness without a
        # second round trip.
        # 替换某分组（或 group_id < 0 时的"全部"视图）的内容并返回行数，使调用方无需
        # 第二次往返即可判断是否为空。
        selected = None if group_id < 0 else group_id
        rows = self._backend.view(selected, keyword or "")
        if selected is not None and not keyword:
            # The store hands a concrete group back COLUMN-major (the original
            # grid's masonry order). A GridView fills ROW-major, so the model
            # transposes once here: the visual order the original showed is what
            # the view then reads, and drag hit tests index the same visual.
            # 存储层按"列主序"交回具体分组（原网格的瀑布流次序）。GridView 按行主序
            # 填充，因此模型在此转置一次：视图读到的正是原项目显示的视觉次序，拖拽
            # 命中测试索引的也是同一个视觉次序。
            rows = self._transpose_to_visual(rows)
        self.beginResetModel()
        self._rows = rows
        self._group_id = group_id
        self._column_widths = self._text_column_widths(rows)
        # Selection is dropped on reload: keeping it would highlight rows by id
        # that may now belong to a different group.
        # 重新加载时丢弃选择：保留它会按 id 高亮可能已属于其他分组的行。
        self._selected = set()
        self.endResetModel()
        self.countChanged.emit()
        return len(self._rows)

    @staticmethod
    def _transpose_to_visual(rows):
        # Column-major in, row-major out: group the rows by their stored column,
        # then interleave the columns row by row, shortest columns exhausting
        # first. Rows without a column keep their relative order at the end.
        # 列主序进，行主序出：按存储列分组，再逐行交错各列，先耗尽短列。没有列的行
        # 保持相对次序排在末尾。
        columns = {}
        unplaced = []
        for row in rows:
            value = row.get("col_index")
            if value is None:
                unplaced.append(row)
            else:
                columns.setdefault(int(value), []).append(row)
        if not columns:
            return rows
        visual = []
        depth = max(len(items) for items in columns.values())
        for level in range(depth):
            for column in sorted(columns):
                items = columns[column]
                if level < len(items):
                    visual.append(items[level])
        visual.extend(unplaced)
        return visual

    @staticmethod
    def _text_column_widths(rows):
        # Masonry column widths for a text group: a column is as wide as its
        # widest card, clamped the way the original project clamped it (its
        # `MIN_CARD_WIDTH` floor; the 220 cap is inside `text_natural_width`).
        # Empty for anything that is not a text group (no text rows at all).
        # 文字分组的瀑布流列宽：一列与其最宽的卡片同宽，钳制方式与原项目一致（下限
        # 是它的 `MIN_CARD_WIDTH`；220 上限在 `text_natural_width` 内）。任何非文字
        # 分组（完全没有文字行）为空。
        by_column = {}
        for row in rows:
            if not row.get("text_content"):
                continue
            column = int(row.get("col_index", 0) or 0)
            width = text_natural_width(row.get("text_content", ""))
            by_column[column] = max(by_column.get(column, 0), width)
        if not by_column:
            return {}
        return {column: max(width, grid_layout.MIN_CARD_WIDTH)
                for column, width in by_column.items()}

    @Slot(int, result="QVariantMap")
    def row(self, index):
        # The whole row as a map, for a dialog that needs several fields at once.
        # 整行作为映射，供一次需要多个字段的对话框使用。
        if 0 <= index < len(self._rows):
            return dict(self._rows[index])
        return {}

    @Slot(int, result="QVariantMap")
    def rowById(self, sticker_id):
        for row in self._rows:
            if row["id"] == sticker_id:
                return dict(row)
        return {}

    @Property(int, notify=countChanged)
    def count(self):
        return len(self._rows)

    @Property(bool, notify=countChanged)
    def isEmpty(self):
        return not self._rows

    # ---- selection / 选择 -----------------------------------------------

    @Property(int, notify=countChanged)
    def selectedCount(self):
        return len(self._selected)

    @Slot(int, bool)
    def setSelected(self, sticker_id, selected):
        changed = False
        if selected:
            if sticker_id not in self._selected:
                self._selected.add(sticker_id)
                changed = True
        elif sticker_id in self._selected:
            self._selected.discard(sticker_id)
            changed = True
        if not changed:
            return
        self._emitForId(sticker_id, [self.SelectedRole])
        self.countChanged.emit()

    @Slot(int, result=bool)
    def isSelected(self, sticker_id):
        return sticker_id in self._selected

    @Slot()
    def selectAll(self):
        self._selected = {row["id"] for row in self._rows}
        if self._rows:
            self.dataChanged.emit(self.index(0, 0),
                                  self.index(len(self._rows) - 1, 0),
                                  [self.SelectedRole])
        self.countChanged.emit()

    @Slot()
    def clearSelection(self):
        self._selected = set()
        if self._rows:
            self.dataChanged.emit(self.index(0, 0),
                                  self.index(len(self._rows) - 1, 0),
                                  [self.SelectedRole])
        self.countChanged.emit()

    @Slot(result="QVariantList")
    def selectedIds(self):
        return sorted(self._selected)

    def _emitForId(self, sticker_id, roles):
        for index, row in enumerate(self._rows):
            if row["id"] == sticker_id:
                model_index = self.index(index, 0)
                self.dataChanged.emit(model_index, model_index, roles)
                return

    # ---- text masonry / 文字瀑布流 ----------------------------------------

    @Property(int, notify=countChanged)
    def columnCount(self):
        # Distinct placed columns in the loaded rows. Zero for image groups and
        # for a text group whose cards are all unplaced (the caller packs first).
        # 已加载行中不同已放置列的数量。图片分组与"卡片全部未放置"的文字分组为零
        # （调用方会先摊列）。
        return len(self._column_widths)

    @Slot(int, result=int)
    def columnWidth(self, column):
        return self._column_widths.get(column, 220)

    @Slot(int, int, result=bool)
    def packTextColumns(self, usable_width, group_id):
        # Give every unplaced card in the current group a (column, order). For a
        # TEXT group this drives the masonry; for an IMAGE group the store's
        # columns only back the drag translation — but without it every card
        # sits unplaced at (0, 0) and every drag is a store-level no-op, exactly
        # why the original grid packed on every group load. Called with the live
        # viewport width before the view reads the rows. Returns whether
        # anything was assigned (the caller reloads when it was).
        # 给当前分组中每张未放置的卡片一个（列, 位置）。对文字分组它驱动瀑布流；对图片
        # 分组，存储层的列只为拖拽翻译服务——但没有它每张卡都未放置在 (0, 0)，任何拖拽
        # 在存储层都是空操作，这正是原网格每次加载分组都摊列的原因。在视图读取行"之前"
        # 以实时视口宽度调用。返回是否有分配（有则调用方重载）。分组 id 由调用方显式
        # 传入：本方法在 load() 之前运行，此刻模型还持着上一个分组的 id。
        # The group id arrives explicitly: this runs BEFORE load(), when the
        # model still holds the previous group's id.
        if group_id is None or group_id < 0:
            return False
        store = self._backend.store

        def width_of(row):
            if row.get("text_content"):
                return text_natural_width(row.get("text_content", ""))
            return TEXT_IMAGE_CARD_WIDTH

        assigned = store.assign_unassigned_columns(
            group_id, usable_width, TEXT_MASONRY_SPACING, width_of)
        return assigned > 0

    @Slot(int, result=int)
    def columnIndexOf(self, sticker_id):
        row = self.rowById(sticker_id)
        value = row.get("col_index")
        return -1 if value is None else int(value)


class ColumnProxy(QSortFilterProxyModel):
    # One masonry column's view of the sticker model: only the rows whose stored
    # `col_index` matches. Per-column ListViews keep Qt Quick's virtualisation,
    # which a hand-rolled Flow over the whole model would give up.
    # 贴纸模型的单个瀑布流列视图：仅保留存储 `col_index` 匹配的行。每列一个 ListView
    # 保住了 Qt Quick 的虚拟化，而全模型手写 Flow 会放弃它。

    def __init__(self, model, column, parent=None):
        super().__init__(parent)
        self._column = int(column)
        self.setSourceModel(model)

    def filterAcceptsRow(self, source_row, source_parent):
        source = self.sourceModel()
        index = source.index(source_row, 0)
        return source.data(index, source.ColumnRole) == self._column


def text_natural_width(text, font=None):
    # The width a text card needs so its longest line does not wrap, mirroring
    # the original project's `EmojiItem.text_natural_width`: longest line plus
    # card margins (24), label padding (16) and a wrap guard (16), capped at
    # TEXT_MAX_WIDTH. The guard exists because horizontalAdvance rounds and the
    # label has its own padding — an exact fit would push the last char to a new
    # line.
    # 文字卡片让其最长一行不换行所需的宽度，镜像原项目的
    # `EmojiItem.text_natural_width`：最长一行加卡片边距（24）、标签内边距（16）与
    # 防换行缓冲（16），上限 TEXT_MAX_WIDTH。缓冲存在的原因是 horizontalAdvance 会
    # 舍入且标签自带内边距——恰好放满会把最后一个字符挤到新行。
    from PySide6.QtGui import QFont, QFontMetrics

    if font is None:
        font = QFont(TEXT_FONT_FAMILY, TEXT_FONT_POINT)
    metrics = QFontMetrics(font)
    longest = 0
    for line in str(text or "").split("\n"):
        longest = max(longest, metrics.horizontalAdvance(line))
    return min(longest + 24 + 16 + 16, TEXT_MAX_WIDTH)


__all__ = ["ColumnProxy", "GroupListModel", "StickerListModel",
           "text_natural_width"]
