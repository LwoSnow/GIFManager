// The sticker library: card grid (image groups), masonry columns (text groups),
// the group tab bar, the full card menu, and multi-select edit mode.
//
// The grid is a `GridView` over the Python sticker model — Qt Quick virtualises
// it, so no lazy-loading code exists here. Text groups use the original
// project's masonry: the store owns (column, order), the model exposes one
// proxy per column, and each column is a plain `Column` inside one shared
// Flickable, so all columns scroll together exactly like the original grid.
//
// 贴纸库：卡片网格（图片分组）、瀑布流列（文字分组）、分组标签栏、完整卡片菜单，以及
// 多选编辑模式。
//
// 网格是 Python 贴纸模型之上的 `GridView`——Qt Quick 对其虚拟化，因此这里没有懒加载代码。
// 文字分组沿用原项目的瀑布流：存储层拥有（列, 位置），模型为每列暴露一个代理，每列是共享
// Flickable 里的一个普通 `Column`，因此所有列像原版网格一样一起滚动。

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../components/ui"

Item {
    id: page
    // Named so a check can drive the sweep state machine directly.
    //
    // The long-press semantics live entirely in `beginSweep`/`applySweep`/`endSweep` plus a timer, and
    // verifying them through real mouse events would mean crossing the overlay's hit test - a different
    // mechanism from the one under test. An explicit name lets the state machine be exercised on its
    // own: hold -> armed, release before the hold -> toggle.
    // 命名使检查能直接驱动扫选状态机。
    //
    // 长按语义完全住在 `beginSweep`/`applySweep`/`endSweep` 加一个定时器里，而用真实鼠标事件验证它们
    // 还要穿过覆盖层的命中测试——那是与被测机制不同的另一套东西。显式名称让状态机可以被单独驱动：
    // 按住 → 武装，未达按住即释放 → 切换。
    objectName: "libraryPage"
    required property var app

    // ---- metrics ----------------------------------------------------------
    //
    // Read from the theme so they cannot drift from the original project's
    // `emoji_item` / `FlowLayout` values (the first QML version had drifted to a
    // 76px card against the original's 100).
    // 从主题读取，使它们不会与原项目的 `emoji_item` / `FlowLayout` 取值漂移（第一个
    // QML 版本曾漂移到 76px 卡片，而原项目是 100）。
    readonly property int cardSize: theme.cardSizeBase
    readonly property int nameStrip: theme.nameStrip
    readonly property int cardGap: theme.cardGap
    readonly property int gridMargin: theme.gridMargin

    // ---- mode -------------------------------------------------------------
    //
    // Multi-select edit mode. Entry points: the card context menu and the edit
    // bar; exit: the bar's exit button, a group switch, or a library reload.
    // 多选编辑模式。入口：卡片右键菜单与编辑操作栏；出口：操作栏的退出按钮、切换分组
    // 或素材库重载。
    property bool editMode: false
    function exitEditMode() {
        page.editMode = false
        page.sweepActive = false
        if (page.app)
            page.app.stickers.clearSelection()
    }

    // ---- drag-to-select state -------------------------------------------
    //
    // The DIRECTION of a sweep, latched when a card is pressed, plus whether a sweep is running.
    // Both live on the page because the gesture spans cards: the card that took the press is not
    // the card the pointer ends up over (measured in `tests/probe_drag_delivery.py` - the press
    // owner receives 0 releases when the pointer leaves it), so no single card can own the
    // gesture.
    //
    // `sweepLatch` is what each card applies to itself as the pointer enters it, so a drag from
    // an UNSELECTED card selects what it crosses and a drag from a SELECTED card deselects it.
    //
    // 拖拽选择的状态。
    //
    // 扫选的"方向"，在卡片被按下时锁定；以及扫选是否正在进行。两者都在页面上，因为该手势跨越卡片：
    // 接收按下的卡片并不是指针最终所在的卡片（`tests/probe_drag_delivery.py` 实测——指针离开后
    // 按下者收到 0 次释放），因此没有哪一张卡片能拥有该手势。
    //
    // `sweepLatch` 是每张卡片在指针进入自身时应用的值，因此从"未选中"卡片开始的拖拽会选中它掠过的，
    // 而从"已选中"卡片开始的拖拽会取消选中。
    property bool sweepActive: false
    property bool sweepLatch: true
    // The card that started the sweep, so a plain click on it still toggles exactly once instead
    // of toggling on press and again on release.
    // 发起扫选的那张卡片，使对它的普通单击仍只切换一次，而不是按下时切换、释放时又切换一次。
    property int sweepOriginId: -1
    // Whether the pointer ever moved to a DIFFERENT card. A press-and-release on one card with no
    // movement is a plain click, and must toggle; anything else is a sweep, which has already
    // applied the latch to every card it crossed including the origin.
    // 指针是否曾移动到"另一张"卡片。在单张卡片上按下并释放且没有移动，就是普通单击、必须切换；
    // 其他情况都是扫选，而扫选已经把锁定值应用到包括起点在内的每一张掠过的卡片。
    property bool sweepMoved: false


    // Last grid index the sweep painted, so a fast drag can fill the gap.
    // 扫选上次涂抹的网格索引，使快速拖动能填补空洞。
    property int sweepLastIndex: -1

    // Which stickers are ACTUALLY on screen, as an id list the cards test themselves against.
    //
    // Computed from `contentY`, the cell height and the column count - the same arithmetic the sweep's
    // hit test uses - because the view does not expose delegate geometry usefully (every delegate
    // reported `y == 0` in measurement) and does not hide off-screen delegates either (60 of 60 stayed
    // `visible` and stayed registered, which is what starved the animator's cap and froze the top half).
    //
    // One extra row above and below is included so a card is already registered by the time it scrolls
    // in, instead of appearing frozen for a frame.
    // 真正在屏幕上的贴纸，作为 id 列表供卡片自测。
    //
    // 由 `contentY`、单元格高度与列数算出——与扫选命中测试同一套算术——因为视图既没有暴露可用的委托
    // 几何（实测每个委托项的 `y` 都为 0），也不会隐藏离屏委托（60 个全部保持 `visible`、全部保持注册，
    // 这才是饿死动画器上限、冻住上半屏的原因）。
    //
    // 上下各多含一行，使卡片在滚入之前就已注册，而不是入屏后先冻一帧。
    readonly property var activeAnimIds: {
        if (!page.app || page.isTextGroup)
            return []
        var rowsTotal = Math.ceil(page.app.stickers.count
                                  / Math.max(1, page.gridColumns))
        var first = Math.max(0, page.gridFirstVisibleRow - 1)
        var last = Math.min(rowsTotal - 1, page.gridLastVisibleRow + 1)
        if (last < first)
            return []
        var ids = []
        var model = page.app.stickers
        for (var row = first; row <= last; ++row) {
            for (var col = 0; col < page.gridColumns; ++col) {
                var index = row * page.gridColumns + col
                if (index >= model.count)
                    break
                ids.push(model.data(model.index(index, 0), page.app.stickerIdRole))
            }
        }
        return ids
    }

    readonly property int gridColumns: Math.max(1, Math.floor(
        (grid.width - grid.leftMargin - grid.rightMargin + page.cardGap) / grid.cellWidth))
    readonly property int gridFirstVisibleRow: Math.max(0, Math.floor(
        (grid.contentY - grid.topMargin) / grid.cellHeight))
    readonly property int gridLastVisibleRow: Math.floor(
        (grid.contentY + grid.height - grid.topMargin) / grid.cellHeight)

    function beginSweep(stickerId) {
        if (!page.app || !page.editMode)
            return
        page.sweepOriginId = stickerId
        page.sweepLatch = !page.app.stickers.isSelected(stickerId)
        page.sweepActive = true
        page.sweepMoved = false
        page.sweepLastIndex = -1
        // Applied IMMEDIATELY, with no hold delay.
        //
        // A previous version waited 280 ms before arming the sweep, copying the original project's
        // long-press timer. That timer exists there because the original also supports click-and-drag
        // to REORDER in the same grid, so a press had to be disambiguated before it could mean
        // "select". Here the two never compete: edit mode disables reordering, and a press in edit
        // mode can only mean "select". Making the user wait for a gesture that has no alternative
        // reading is pure latency - the press-and-drag IS the selection.
        //
        // Applying here is also what keeps a plain click correct: the latch is the OPPOSITE of the
        // anchor's current state, which is precisely what a toggle does, so `endSweep` needs no
        // separate toggle step.
        // 立即应用，没有按住延迟。
        //
        // 上一版在武装扫选前等待 280 毫秒，照搬了原项目的长按定时器。那个定时器在原项目里存在，是因为原
        // 项目同一网格里还支持"点击拖动排序"，因此按下必须先被消歧才能表示"选择"。这里两者从不竞争：编辑
        // 模式会禁用重排，编辑模式下的按下只可能表示"选择"。让用户为一种没有第二种解释的手势等待，纯粹是
        // 延迟——按下拖动"就是"选择。
        //
        // 在此应用也正是让普通单击保持正确的原因：锁定值是锚点当前状态的反面，那恰好就是切换所做的事，
        // 因此 `endSweep` 不需要额外的切换步骤。
        page.app.stickers.setSelected(stickerId, page.sweepLatch)
    }

    function applySweep(stickerId) {
        if (!page.sweepActive || !page.app)
            return
        if (stickerId !== page.sweepOriginId)
            page.sweepMoved = true
        page.app.stickers.setSelected(stickerId, page.sweepLatch)
    }

    // Apply the sweep from a SCENE position, used by the pressed card's own move events.
    //
    // Converting to grid coordinates here instead of in the card keeps the hit test in one place: the
    // card knows where the pointer is, the page knows which cell that is.
    // 从"场景"坐标应用扫选，供被按下卡片的移动事件调用。
    //
    // 在这里而不是在卡片里换算成网格坐标，使命中测试只在一处：卡片知道指针在哪，页面知道那是哪一格。
    function sweepAt(sceneX, sceneY) {
        if (!page.sweepActive || !page.app || page.isTextGroup)
            return
        var local = grid.mapFromItem(null, sceneX, sceneY)
        // CONTENT coordinates, not viewport coordinates.
        //
        // `GridView.indexAt` expects content coordinates, and passing viewport ones is off by
        // `contentY`: with the grid scrolled 300 px the same point resolved to index 0 where the
        // geometry says 15 - the reported "I drag downwards and the cards ABOVE get selected". It
        // looked correct near the top of the list only because `contentY` is then ~0.
        // 用"内容"坐标，而不是视口坐标。
        //
        // `GridView.indexAt` 期望内容坐标，传视口坐标会差一个 `contentY`：网格滚动 300px 时同一个点被
        // 解析成 index 0，而几何上应为 15——正是用户报告的"我往下拖，选中的却是上面的卡片"。在列表顶部
        // 附近看起来正常，只是因为那时 `contentY` 约为 0。
        var index = grid.indexAt(local.x + grid.contentX, local.y + grid.contentY)
        if (index < 0)
            return
        page.applySweepRange(index)
    }

    // Apply the latch to every index between the previous one and this one.
    //
    // A fast drag reports positions far apart - a move can jump several cells - so painting only the
    // sampled index leaves gaps, which is the "high-frequency drag skips cards" half of the report.
    // Filling the span is what the original's `apply_drag_selection` does with its remembered last
    // position.
    // 把锁定值应用到"上一个"索引与当前索引之间的每一个。
    //
    // 快速拖动上报的位置相距很远——一次移动可能跨过好几格——因此只涂抹采样的那个索引会留下空洞，这正是
    // 用户报告里"高频拖动漏选"的那一半。填满这段区间，正是原版 `apply_drag_selection` 用它记住的上一个
    // 位置所做的事。
    function applySweepRange(index) {
        if (!page.app || !grid.model)
            return
        var last = page.sweepLastIndex
        // Fill the gap ONLY within one column.
        //
        // A contiguous index range looks tempting - a fast drag jumps several cells and painting just
        // the sampled one leaves holes - but indices wrap across ROWS: filling 15..25 paints three
        // whole rows, so dragging down one column would select every card beside it. That is its own
        // version of "cards I never touched got selected".
        //
        // Same column means the indices differ by a whole number of rows, so the span between them is
        // exactly the cells the pointer passed through.
        // 只在"同一列"内填补空隙。
        //
        // 连续索引区间看起来很诱人——快速拖动会跳过好几个格子，只涂抹采样的那个会留下空洞——但索引是
        // 跨"行"回绕的：填 15..25 会涂抹整整三行，于是沿一列向下拖动会选中它旁边的每一张卡片。那本身
        // 就是另一种"我没碰过的卡片被选中"。
        //
        // 同一列意味着两个索引相差整数行，因此它们之间的跨度恰好是指针经过的那些格子。
        var cols = Math.max(1, Math.floor((grid.width - grid.leftMargin - grid.rightMargin)
                                          / grid.cellWidth))
        var sameColumn = last >= 0 && (last % cols) === (index % cols)
        var lo = sameColumn ? Math.min(last, index) : index
        var hi = sameColumn ? Math.max(last, index) : index
        // Step by a ROW (one column count), not by one.
        //
        // Adding one walks into the neighbouring columns - the same over-selection the block comment
        // above warns about, reintroduced by the loop increment. One row is `cols` indices, which
        // stays in the column the pointer is in.
        // 按"一行"（一个列数）步进，而不是按一。
        //
        // 加一会在相邻列之间游走——正是上面块注释警告的那种过度选中，只是由循环增量重新引入。一行等于
        // `cols` 个索引，那才停留在指针所在的那一列。
        var step = sameColumn ? cols : 1
        for (var i = lo; i <= hi; i += step) {
            var id = grid.model.data(grid.model.index(i, 0), page.app.stickerIdRole)
            if (id === undefined || id === null)
                continue
            page.app.stickers.setSelected(id, page.sweepLatch)
        }
        page.sweepLastIndex = index
    }

    function endSweep() {
        // Nothing to undo and nothing to toggle: the press already applied the latch, which for a
        // single card is exactly a toggle. Only the flags are cleared.
        // 无需撤销也无需切换：按下时已经应用了锁定值，而对单张卡片而言那恰好就是切换。只清除标志。
        page.sweepActive = false
        page.sweepOriginId = -1
        page.sweepMoved = false
        page.sweepLastIndex = -1
    }

    // Open the move picker for the edit-mode SELECTION.
    //
    // The toolbar button calls this so the shell does not need to know the dialog's id: the
    // page owns the dialogs, and reaching into another file's object tree by id is exactly how
    // the previous menu-based version became hard to reason about.
    // 为编辑模式的"选择"打开移动选取器。
    //
    // 工具栏按钮调用它，使外壳无需知道对话框的 id：对话框由页面拥有，而靠 id 去伸进另一个文件的
    // 对象树，正是此前基于菜单的版本变得难以推理的原因。
    function openMoveForSelection() {
        moveDialog.openForSelection()
    }

    // Drag-reorder state: which sticker is in flight, and which MODEL ROW the
    // insert indicator sits at (and on which side of it). The page owns the hit
    // test because QML DropArea delivery proved unreliable for a delegate drag
    // whose payload item follows the cursor — the drop events never arrived, on
    // or off screen. `childAt`/cell arithmetic over the same geometry is
    // deterministic and testable.
    // 拖拽排序状态：哪个贴纸正在拖动，插入指示条位于哪个模型行（以及哪一侧）。命中测试
    // 由页面负责：QML DropArea 对"载荷对象跟随光标"的委托拖拽投递不可靠——屏上屏下
    // 放置事件都不到达。基于同一几何的 childAt/单元格算术是确定且可测的。
    property int dragStickerId: -1
    property int dropIndex: -1
    property bool dropAfter: false

    function updateDropTarget(sceneX, sceneY) {
        if (page.dragStickerId < 0)
            return
        if (page.isTextGroup)
            page._hitTestMasonry(sceneX, sceneY)
        else
            page._hitTestGrid(sceneX, sceneY)
    }

    function finishDrag() {
        if (page.dragStickerId >= 0 && page.dropIndex >= 0
                && page.app && page.dropIndex < page.app.stickers.count) {
            var row = page.app.stickers.row(page.dropIndex)
            if (row && row.id !== undefined && row.id !== page.dragStickerId) {
                if (page.dropAfter)
                    page.app.reorderStickerAfter(page.dragStickerId, row.id)
                else
                    page.app.reorderSticker(page.dragStickerId, row.id)
            }
        }
        page.dragStickerId = -1
        page.dropIndex = -1
    }

    function _hitTestGrid(sceneX, sceneY) {
        // Map the cursor into the grid's CONTENT coordinates and read off the
        // cell: uniform cells make this pure arithmetic.
        // 把光标映射到网格"内容"坐标后直接读出单元格：均匀单元格使其成为纯算术。
        var scene = page.Window.window ? page.Window.window.contentItem : null
        if (!scene)
            return
        var p = grid.mapFromItem(scene, sceneX, sceneY)
        var cellW = grid.cellWidth
        var cellH = grid.cellHeight
        var cols = Math.max(1, Math.floor(
                            (grid.width - 2 * page.gridMargin + page.cardGap)
                            / cellW))
        var cx = p.x - page.gridMargin + grid.contentX
        var cy = p.y - page.gridMargin + grid.contentY
        var col = Math.floor(cx / cellW)
        var row = Math.floor(cy / cellH)
        if (col < 0 || row < 0) {
            page.dropIndex = -1
            return
        }
        var index = row * cols + col
        if (index >= page.app.stickers.count)
            index = page.app.stickers.count - 1
        page.dropIndex = index
        // Left/right half of the CARD area (the cell's trailing strip is gap).
        // 卡片区域的左/右半（单元格尾部是间隙）。
        var cardWidth = cellW - page.cardGap
        page.dropAfter = (cx - col * cellW) > cardWidth / 2
    }

    function _hitTestMasonry(sceneX, sceneY) {
        // Masonry columns have per-card heights, so arithmetic is out; `childAt`
        // walks the Row → Column → card chain and the card reports its row.
        // 瀑布流各卡高度不同，算术不可用；用 `childAt` 走 Row → Column → 卡片链，
        // 卡片上报自己的行号。
        var scene = page.Window.window ? page.Window.window.contentItem : null
        if (!scene)
            return
        var p = masonryRow.mapFromItem(scene, sceneX, sceneY)
        var column = masonryRow.childAt(p.x, p.y)
        var index = -1
        var after = false
        if (column) {
            var local = column.mapFromItem(masonryRow, p.x, p.y)
            var card = column.childAt(local.x, local.y)
            if (card) {
                index = card.modelRow
                after = local.y > card.y + card.height / 2
            }
        }
        page.dropIndex = index
        page.dropAfter = after
    }

    // A text group renders as masonry columns; everything else is the grid.
    // 文字分组渲染为瀑布流列；其余都是网格。
    readonly property bool isTextGroup: {
        if (!page.app || page.app.groups.currentId < 0)
            return false
        return page.app.groups.typeOf(page.app.groups.currentId) === "text"
    }

    // Reordering only makes sense inside one group without a search filter, and
    // never while the check badges are active. Written against reactive
    // properties rather than `canReorder()`: a slot call in a binding evaluates
    // once and never re-evaluates, which left the drag dead.
    // 重排只在无搜索过滤的单个分组内有意义，且在勾选角标激活时绝不进行。这里用可响应
    // 属性而非 `canReorder()`：绑定里的槽调用只求值一次、永不重估，曾让拖拽完全失效。
    readonly property bool reorderEnabled: {
        if (!page.app || page.editMode)
            return false
        return page.app.groups.currentId >= 0 && page.app.keyword === ""
    }

    // The viewport width feeds the text packer, debounced: a resize storm from
    // dragging the window edge must trigger one packing pass, like the
    // original's 150 ms debounce.
    // 视口宽度供给文字摊列器，带防抖：拖拽窗口边缘引发的 resize 风暴只应触发一次
    // 摊列，如同原版的 150 ms 防抖。
    onWidthChanged: viewportTimer.restart()
    Component.onCompleted: if (page.app) page.app.setViewportWidth(page.width)

    Timer {
        id: viewportTimer
        interval: 150
        onTriggered: if (page.app) page.app.setViewportWidth(page.width)
    }

    // A group switch drops edit mode and any in-flight drag, matching the
    // original grid's per-group selection.
    // 切换分组会退出编辑模式并丢弃进行中的拖拽，与原版网格按分组的选择一致。
    Connections {
        target: page.app ? page.app.groups : null
        function onChanged() {
            page.exitEditMode()
            page.dragStickerId = -1
            page.dropIndex = -1
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ---- card grid (image groups and the All view) ---------------------
        GridView {
            id: grid
            // Named so a check can map card coordinates and deliver real mouse events to the sweep.
            // 命名使检查能映射卡片坐标并向扫选投递真实鼠标事件。
            objectName: "stickerGrid"
            visible: !page.isTextGroup
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: page.app ? page.app.stickers : null
            // The cell is one gap larger than the card on every side, so the
            // grid's margins come from `gridMargin` and the gaps from `cardGap`.
            // The `app` guards keep the bindings valid while the page is still
            // being constructed.
            // 单元格每侧比卡片大出一个间隙，因此网格边距来自 `gridMargin`，间隙来自
            // `cardGap`。`app` 防护使绑定在页面仍在构建时保持有效。
            cellWidth: (page.app ? page.cardSize * page.app.cardScale
                                 : page.cardSize) + page.cardGap
            cellHeight: (page.app ? page.cardSize * page.app.cardScale
                                  : page.cardSize) + page.nameStrip + page.cardGap
            leftMargin: page.gridMargin
            topMargin: page.gridMargin
            rightMargin: page.gridMargin
            bottomMargin: page.gridMargin
            boundsBehavior: Flickable.StopAtBounds
            // NO FLICKING WHILE EDITING.
            //
            // This is the bug that made drag-selection feel broken in two ways at once. A `GridView` is a
            // `Flickable`, and a `Flickable` steals a press-and-drag once it passes its threshold - so
            // dragging across cards scrolled the PAGE instead of painting the selection, and the few
            // events the sweep did receive arrived after the steal, which reads as "does not follow the
            // pointer".
            //
            // In edit mode a press can only mean "select", and there is no second gesture to
            // disambiguate against, so the flick is simply switched off. The wheel still scrolls
            // (`WheelHandler` below is unaffected by `interactive`), which is how a list this dense is
            // scrolled anyway once a drag belongs to selection.
            // 编辑时不可滑动。
            //
            // 这正是让拖动选择以两种方式同时失效的那个缺陷。`GridView` 是 `Flickable`，而 `Flickable`
            // 一旦超过阈值就会抢走按下拖动——于是跨卡片拖动滚的是"页面"而不是涂抹选择，而扫选真正收到
            // 的那少数事件都在被抢之后才到，读起来就是"不跟手"。
            //
            // 编辑模式下按下只可能表示"选择"，也没有第二种手势需要消歧，因此直接关掉滑动。滚轮仍可滚动
            // （下方的 `WheelHandler` 不受 `interactive` 影响）——而当拖动被划归选择之后，滚轮本来就是
            // 这种密集列表的滚动方式。
            interactive: !page.editMode
            // Plain wheel scrolling follows the hand: one notch moves the content
            // by the delta directly, instead of the Flickable's slow default
            // glide. Alt+wheel is handled by the window filter on the Python
            // side and never reaches here.
            // 普通滚轮"跟手"：一格滚轮按增量直接移动内容，而非 Flickable 缓慢的默认
            // 滑动。Alt+滚轮由 Python 侧的窗口过滤器处理，不会到达这里。
            WheelHandler {
                acceptedModifiers: Qt.NoModifier
                onWheel: function (event) {
                    var max = Math.max(0, grid.contentHeight - grid.height)
                    grid.contentY = Math.max(0, Math.min(
                        max, grid.contentY - event.angleDelta.y))
                    event.accepted = true
                }
            }
            ScrollBar.vertical: UiScrollBar {
                policy: ScrollBar.AsNeeded
                contentItem: Rectangle {
                    implicitWidth: 6
                    radius: 3
                    color: parent.pressed ? theme.scrollbarHover : theme.scrollbar
                }
            }

            // ---- drag to select, in edit mode ---------------------------
            //
            // A press on a card latches that card's state, and every card the cursor then crosses
            // is set TO that state - so a drag starting on an unselected card SELECTS the cards it
            // crosses, and one starting on a selected card DESELECTS them.
            //
            // # Why this is an overlay that only exists DURING the drag
            //
            // `tests/probe_drag_delivery.py` measures what Qt actually does, and both facts matter:
            //
            //     press inside card A, then move across into card B
            //       A received 1 press, 3 moves, and 0 RELEASES
            //       B received 3 moves
            //
            // A card's own `MouseArea` receives position changes only while the cursor is INSIDE
            // that card, so per-card handling cannot continue a sweep across a neighbour. And an
            // overlay that is enabled in edit mode ALWAYS swallows the press, which broke plain
            // single-click selection the first time this was attempted.
            //
            // Enabling it only once a sweep has begun satisfies both: the press and any plain
            // click reach the card (the overlay is disabled), and from then on the overlay - which
            // never loses the gesture - sees every move across every card. The grid cannot steal
            // those moves, because the overlay is above it and holding the grab; that is what
            // stops a drag from scrolling the page.
            //
            // 编辑模式下拖拽选择。
            //
            // 按下一张卡片会锁定该卡片的状态，此后光标掠过的每一张都被设"成"该状态——因此从"未选中"
            // 卡片开始的拖拽会"选中"它掠过的卡片，而从"已选中"卡片开始的拖拽会"取消选中"。
            //
            // # 为什么这是一个"只在拖拽期间存在"的覆盖层
            //
            // `tests/probe_drag_delivery.py` 实测了 Qt 的真实行为，两个事实都要紧：
            //
            //     在卡片 A 内按下，然后向右移动进入卡片 B
            //       A 收到 1 次按下、3 次移动、以及 0 次"释放"
            //       B 收到 3 次移动
            //
            // 卡片自身的 `MouseArea` 只在光标"位于该卡片内"时收到位置变化，因此逐卡片的处理无法越过
            // 邻卡继续扫选。而在编辑模式下"始终启用"的覆盖层会吞掉按下——第一次尝试时它就是这样彻底
            // 破坏了普通单击选中。
            //
            // 只在扫选开始后才启用它同时满足两者：按下与任何普通单击都能到达卡片（此时覆盖层被禁用），
            // 此后覆盖层——它永不丢失手势——能看到跨过每一张卡片的每一次移动。网格无法抢走这些移动，
            // 因为覆盖层在它之上并持有抓取；这正是阻止拖拽滚动页面的原因。
            MouseArea {
                id: sweepArea
                anchors.fill: parent
                // Disabled until a card reports that a sweep has started, so it is transparent to
                // ordinary clicks. See the block comment above for why this cannot simply be
                // `enabled: page.editMode`.
                // 在卡片报告扫选开始之前保持禁用，因此对普通单击透明。为什么不能直接写
                // `enabled: page.editMode`，见上方块注释。
                enabled: page.sweepActive
                acceptedButtons: Qt.LeftButton
                // The cursor must not leave the card while the button is held, or the moves stop
                // arriving here and the sweep dies at the first cell boundary.
                // 按住按钮时鼠标不得离开卡片，否则移动不再到达此处，扫选会在第一个单元格边界处中断。
                preventStealing: true

                // The state to apply to every card the sweep crosses, latched at press time.
                // 应用到每次掠过卡片的状态，在按下时锁定。
                property bool sweepTo: true

                function applyAt(px, py) {
                    if (!page.app || !grid.model)
                        return
                    // Same content-coordinate rule as `page.sweepAt`: these are VIEWPORT coordinates
                    // and `indexAt` wants content ones, so the offsets must be added or a scrolled
                    // grid resolves every point to a row near the top.
                    // 与 `page.sweepAt` 相同的内容坐标规则：这里是"视口"坐标而 `indexAt` 要"内容"坐标，
                    // 因此必须加上偏移，否则滚动后的网格会把每个点都解析成靠近顶部的一行。
                    var index = grid.indexAt(px + grid.contentX, py + grid.contentY)
                    if (index < 0)
                        return
                    page.applySweepRange(index)
                }

                onPositionChanged: function (mouse) {
                    if (page.sweepActive)
                        applyAt(mouse.x, mouse.y)
                }

                onReleased: {
                    page.endSweep()
                }
                onCanceled: {
                    page.endSweep()
                }

                // The wheel belongs to the grid, not to the sweep.
                // 滚轮属于网格，不属于扫选。
                onWheel: function (wheel) {
                    wheel.accepted = false
                }
            }
            // `required property`, then hands them to a `StickerCard` as
            // ordinary bindings. The wrapper is not optional: Qt initialises
            // `required property` only on the delegate itself, and a card with
            // plain properties alone renders blank with no warning.
            // 委托是一个内联 `Item`，把模型角色声明为 `required property`，随后作为
            // 普通绑定交给 `StickerCard`。包装不是可选的：Qt 只对委托"自身"初始化
            // `required property`，而只有普通属性的卡片会以零警告渲染为空白。
            delegate: Item {
                id: cardSlot
                required property int index
                required property int modelRow
                required property int stickerId
                required property string name
                required property string source
                required property bool isText
                required property string textContent
                required property bool isSelected

                width: page.app ? page.cardSize * page.app.cardScale
                                 : page.cardSize
                height: (page.app ? page.cardSize * page.app.cardScale
                                  : page.cardSize)
                        + (page.app && page.app.showNames ? page.nameStrip : 0)

                StickerCard {
                    id: cardBody
                    anchors.top: parent.top
                    anchors.horizontalCenter: parent.horizontalCenter
                    app: page.app
                    // Only the grid feeds a band; a card's y here is in its content space.
                    // 只有网格提供区间；这里的卡片 y 处于其内容空间中。
                    activeIds: page.activeAnimIds
                    stickerId: cardSlot.stickerId
                    name: cardSlot.name
                    source: cardSlot.source
                    isText: cardSlot.isText
                    textContent: cardSlot.textContent
                    isSelected: cardSlot.isSelected
                    cardSize: page.app ? page.cardSize * page.app.cardScale
                                       : page.cardSize
                    nameFontSize: page.app ? page.app.nameFontSize : 11
                    showName: page.app ? page.app.showNames : true
                    textLimitSingle: page.app ? page.app.textLimitSingle : 100
                    textLimitMulti: page.app ? page.app.textLimitMulti : 200
                    editMode: page.editMode
                    reorderEnabled: page.reorderEnabled
                    dragStickerId: page.dragStickerId
                    dragTarget: cardSlot
                    // The animator decodes from a FILESYSTEM path, not from the
                    // `file://` URL the Image shows. Without this binding the
                    // path stays empty and every GIF plays as a still.
                    // 动画器从"文件系统路径"解码，而非 Image 显示的 `file://` URL。
                    // 缺了这条绑定，路径恒为空，每个 GIF 都只会显示静态帧。
                    path: page.app.filePathOf(cardSlot.stickerId)
                    positionRoot: page.Window.window
                                 ? page.Window.window.contentItem : null

                    onActivated: function (id) { page.app.sendSticker(id) }
                    onDragStarted: function (id) { page.dragStickerId = id }
                    onDragMoved: function (id, sx, sy) {
                        page.updateDropTarget(sx, sy)
                    }
                    onDragEnded: function (id, sx, sy) {
                        page.finishDrag()
                    }
                    onContextRequested: function (id, sx, sy) {
                        cardMenu.openFor(id, sx, sy)
                    }
                    onSweepBegin: function (id) { page.beginSweep(id) }
                    onSweepApply: function (id) { page.applySweep(id) }
                    onSweepAt: function (sceneX, sceneY) { page.sweepAt(sceneX, sceneY) }
                    onSweepEnd: { page.endSweep() }
                }

                // The insert indicator: a 3px accent bar on the leading or
                // trailing edge of the drop target, the grid-mode counterpart of
                // the original's separator line.
                // 插入指示条：放置目标前缘或后缘上的 3px 强调色竖条，是原版分界线的
                // 网格模式对应物。
                Rectangle {
                    visible: page.dropIndex === cardSlot.modelRow
                             && page.dragStickerId >= 0
                             && page.dragStickerId !== cardSlot.stickerId
                    width: 3
                    height: parent.height
                    radius: 1
                    color: theme.uiColors.foreground
                    anchors.left: page.dropAfter ? undefined : parent.left
                    anchors.leftMargin: page.dropAfter ? 0 : -page.cardGap / 2 - 1
                    anchors.right: page.dropAfter ? parent.right : undefined
                    anchors.rightMargin: page.dropAfter
                                         ? -page.cardGap / 2 - 1 : 0
                }
            }

            // Placeholder shown when the group is empty, so an empty group never
            // looks like a rendering failure.
            // 分组为空时显示的占位，使空分组不会看起来像渲染失败。
            Label {
                anchors.centerIn: parent
                visible: (page.app === undefined || page.app === null
                          || page.app.stickers === undefined)
                         ? false
                         : page.app.stickers.count === 0
                text: (page.app === undefined || page.app === null)
                      ? ""
                      : (page.app.keyword !== ""
                         ? page.app.trE("no_search_result", page.app.languageEpoch)
                         : page.app.trE("empty_image_group", page.app.languageEpoch))
                color: theme.textMuted
                font.pixelSize: theme.fontSizeBody
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                width: Math.min(page.width - 40, 360)
            }
        }

        // ---- text masonry (text groups) ------------------------------------
        //
        // One shared Flickable over a Row of Columns: all columns scroll
        // together, as the original's masonry did. The per-column models are
        // Python proxies filtering the sticker model by the store's column
        // index.
        // 一个共享 Flickable 覆盖一 Row of Columns：所有列一起滚动，如同原版的瀑布流。
        // 每列模型是按存储层列号过滤贴纸模型的 Python 代理。
        Flickable {
            id: masonry
            visible: page.isTextGroup
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: masonryRow.width + 2 * page.gridMargin
            contentHeight: masonryRow.height + 2 * page.gridMargin
            boundsBehavior: Flickable.StopAtBounds
            // Same rule as the grid: a drag in edit mode belongs to the selection, not to the scroll.
            // 与网格同一条规则：编辑模式下的拖动属于选择，不属于滚动。
            interactive: !page.editMode
            WheelHandler {
                acceptedModifiers: Qt.NoModifier
                onWheel: function (event) {
                    var max = Math.max(0, masonry.contentHeight - masonry.height)
                    masonry.contentY = Math.max(0, Math.min(
                        max, masonry.contentY - event.angleDelta.y))
                    event.accepted = true
                }
            }
            ScrollBar.vertical: UiScrollBar {
                policy: ScrollBar.AsNeeded
                contentItem: Rectangle {
                    implicitWidth: 6
                    radius: 3
                    color: parent.pressed ? theme.scrollbarHover : theme.scrollbar
                }
            }

            Row {
                id: masonryRow
                x: page.gridMargin
                y: page.gridMargin
                spacing: page.cardGap

                Repeater {
                    model: page.isTextGroup && page.app
                           ? page.app.textColumnCount : 0

                    delegate: Column {
                        id: masonryColumn
                        required property int index

                        spacing: page.cardGap

                        Repeater {
                            model: page.app
                                   ? page.app.textColumnModel(masonryColumn.index)
                                   : null

                            delegate: Item {
                                id: textSlot
                                required property int modelRow
                                required property int stickerId
                                required property string name
                                required property string source
                                required property bool isText
                                required property string textContent
                                required property bool isSelected

                                width: page.app
                                       ? page.app.textColumnWidth(
                                           masonryColumn.index) : 220
                                height: textCard.height

                                StickerCard {
                                    id: textCard
                                    anchors.top: parent.top
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    app: page.app
                                    stickerId: textSlot.stickerId
                                    name: textSlot.name
                                    source: textSlot.source
                                    isText: textSlot.isText
                                    textContent: textSlot.textContent
                                    isSelected: textSlot.isSelected
                                    cardWidth: parent.width
                                    textLimitSingle: page.app
                                                     ? page.app.textLimitSingle
                                                     : 100
                                    textLimitMulti: page.app
                                                    ? page.app.textLimitMulti : 200
                                    editMode: page.editMode
                                    reorderEnabled: page.reorderEnabled
                                    dragStickerId: page.dragStickerId
                                    dragTarget: textSlot
                                    path: page.app.filePathOf(textSlot.stickerId)
                                    positionRoot: page.Window.window
                                                 ? page.Window.window.contentItem
                                                 : null

                                    onActivated: function (id) {
                                        page.app.sendSticker(id)
                                    }
                                    onDragStarted: function (id) {
                                        page.dragStickerId = id
                                    }
                                    onDragMoved: function (id, sx, sy) {
                                        page.updateDropTarget(sx, sy)
                                    }
                                    onDragEnded: function (id, sx, sy) {
                                        page.finishDrag()
                                    }
                                    onContextRequested: function (id, sx, sy) {
                                        cardMenu.openFor(id, sx, sy)
                                    }
                                    onSweepBegin: function (id) { page.beginSweep(id) }
                                    onSweepApply: function (id) { page.applySweep(id) }
                                    onSweepAt: function (sceneX, sceneY) { page.sweepAt(sceneX, sceneY) }
                                    onSweepEnd: { page.endSweep() }
                                }

                                Rectangle {
                                    visible: page.dropIndex
                                             === textSlot.modelRow
                                             && page.dragStickerId >= 0
                                             && page.dragStickerId
                                                !== textSlot.stickerId
                                    width: parent.width
                                    height: 3
                                    radius: 1
                                    color: theme.uiColors.foreground
                                    anchors.top: page.dropAfter
                                                 ? undefined : parent.top
                                    anchors.topMargin: page.dropAfter
                                                       ? 0 : -page.cardGap / 2 - 1
                                    anchors.bottom: page.dropAfter
                                                    ? parent.bottom : undefined
                                    anchors.bottomMargin: page.dropAfter
                                                          ? -page.cardGap / 2 - 1
                                                          : 0
                                }
                            }
                        }
                    }
                }
            }

            Label {
                anchors.centerIn: parent
                visible: (page.app === undefined || page.app === null
                          || page.app.stickers === undefined)
                         ? false
                         : page.app.stickers.count === 0
                text: (page.app === undefined || page.app === null)
                      ? ""
                      : page.app.trE("empty_text_group", page.app.languageEpoch)
                color: theme.textMuted
                font.pixelSize: theme.fontSizeBody
            }
        }

        // ---- group bar ----------------------------------------------------
        //
        // The original's bottom tab bar: "全部" first (pinned), then the groups,
        // then a fixed "+" that opens the create menu. Tab style: transparent,
        // hover grey, active accent — the original's `groupTab` QSS.
        // 原版的底部标签栏："全部"在最前（固定），然后是各分组，最后是打开新建菜单的
        // 固定"+"。标签样式：透明、悬停灰、激活强调色——原版的 `groupTab` QSS。
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 44
            color: theme.surface

            Rectangle {
                anchors.top: parent.top
                width: parent.width
                height: 1
                color: theme.borderStrong
            }

            ListView {
                id: groupBar
                anchors.left: parent.left
                anchors.right: addGroupButton.left
                anchors.rightMargin: 4
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 6
                height: 36
                orientation: ListView.Horizontal
                spacing: 4
                model: page.app ? page.app.groups : null
                boundsBehavior: Flickable.StopAtBounds
                clip: true

                delegate: Button {
                    id: groupTab
                    required property int groupId
                    required property string name
                    required property int count
                    required property string groupType
                    required property bool isAll
                    required property bool isBuiltin
                    required property bool isCurrent

                    height: 32
                    text: name
                    onClicked: page.app.selectGroup(groupId)
                    // Group context menu: rename always, delete for every group
                    // the store lets delete (non-builtin) — the original split.
                    // 分组右键菜单：始终可重命名；删除仅限存储层允许的分组（非内置）
                    // ——与原版一致。
                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.RightButton
                        cursorShape: Qt.PointingHandCursor
                        // `popup()` with no arguments opens at the cursor, which
                        // is what the original's context menu did.
                        // 不带实参的 `popup()` 在光标处打开，正是原版右键菜单的行为。
                        onClicked: function (mouse) {
                            groupTabMenu.openFor(groupTab.groupId,
                                                 groupTab.isBuiltin)
                        }
                    }
                    // An explicit `UiToolTip`, not the attached `ToolTip.*` properties.
                    //
                    // The attached form creates a `QtQuick.Controls.Basic` tooltip whose frame
                    // and surface come from that style, and no amount of `QPalette` work made it
                    // belong to this interface. `UiToolTip` draws our own surface, so the hover
                    // preview on a group tab looks like the menus and controls around it.
                    // 显式的 `UiToolTip`，而非附加属性 `ToolTip.*`。
                    //
                    // 附加形式创建的是 `QtQuick.Controls.Basic` 的提示框，其边框与表面来自该
                    // 样式，无论怎么调 `QPalette` 都无法让它属于本界面。`UiToolTip` 自绘表面，
                    // 因此分组标签上的悬停预览与周围的菜单和控件看起来是一套。
                    UiToolTip {
                        text: groupTab.name + "  (" + groupTab.count + ")"
                        visible: groupTab.hovered && groupTab.count > 0
                    }

                    background: Rectangle {
                        // shadcn semantics rather than the original QSS accent: the SELECTED tab is
                        // the solid `primary` pill and hover is the `accent` tint, so the tab bar
                        // shares one monochrome palette with the buttons and fields.
                        //
                        // The original used `theme.accent` (a blue) here, which was the last blue
                        // element left on the screen once the toolbar adopted the shadcn tokens -
                        // it read as an unrelated highlight rather than a selection.
                        // 用 shadcn 语义而不是原 QSS 的强调色：选中的标签是实心 `primary` 胶囊、
                        // 悬停用 `accent` 淡色，使标签栏与按钮、输入框共用同一套单色调色板。
                        //
                        // 原版在此用 `theme.accent`（蓝色），而当工具栏采用 shadcn 令牌后，它是屏幕上
                        // 最后一块蓝色——读起来像一个无关的高亮而不是"选中"。
                        radius: theme.uiMetrics.uiRadiusSm
                        // `selected`, not `primary`: with the low-contrast palette, `primary` is a
                        // calm raised surface, so using it here would have made the ACTIVE tab look
                        // like every other idle control. Selection is the one state allowed to be
                        // high contrast, and that is exactly what makes the tab bar readable at a
                        // glance while the rest of the window stays quiet.
                        // 用 `selected` 而不是 `primary`：在低对比调色板下 `primary` 是安静的抬升表面，
                        // 若用在此处，"当前"标签就会和所有闲置控件长得一样。选中是唯一被允许高对比的
                        // 状态，而这正是让标签栏一眼可读、同时窗口其余部分保持安静的原因。
                        color: groupTab.isCurrent
                               ? theme.uiColors.selected
                               : groupTab.hovered ? theme.uiColors.surface3 : "transparent"
                        Behavior on color {
                            ColorAnimation { duration: theme.uiMetrics.uiAnimationMs }
                        }
                    }
                    contentItem: Label {
                        text: groupTab.text
                        color: groupTab.isCurrent
                               ? theme.uiColors.selectedForeground
                               : theme.uiColors.mutedForeground
                        font.pixelSize: 12
                        font.weight: groupTab.isCurrent ? Font.Medium : Font.Normal
                        verticalAlignment: Text.AlignVCenter
                        horizontalAlignment: Text.AlignHCenter
                        leftPadding: 14
                        rightPadding: 14
                    }
                }
            }

            UiButton {
                id: addGroupButton
                anchors.right: parent.right
                anchors.rightMargin: 6
                anchors.verticalCenter: parent.verticalCenter
                width: 32
                height: 32
                flat: true
                text: "＋"
                // Opens the dialog DIRECTLY. There used to be a two-entry menu here
                // (新建图片分组 / 新建文字分组) whose only job was to answer a question the
                // dialog now answers itself by matching the group the user is looking at.
                // Removing it also removes a click: the menu had no other purpose, and a
                // menu that exists to pick between two items that produce the same dialog is
                // a step the user has to take for nothing.
                // "直接"打开对话框。这里曾有一个两项菜单（新建图片分组 / 新建文字分组），其唯一
                // 作用就是回答一个对话框现在会自行回答的问题——匹配用户正在看的分组。移除它也移除了
                // 一次点击：那个菜单没有别的用途，而一个存在的意义是在两个产生同一对话框的条目之间做
                // 选择的菜单，是让用户白走的一步。
                onClicked: groupDialog.openCreate()

                background: Rectangle {
                    radius: 6
                    color: parent.hovered ? theme.surfaceAlt : "transparent"
                }
                contentItem: Label {
                    text: parent.text
                    color: theme.textMuted
                    font.pixelSize: 16
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
        }
    }

    // ---- menus and dialogs -------------------------------------------------

    UiMenu {
        // Item 型弹窗：在场景内绘制。无边框工具窗口上 Window 型原生弹窗不显示。
        // Item-type popup: rendered inside the scene, because a Window-type
        // native popup does not show on a frameless tool window.
        popupType: Popup.Item
        id: groupTabMenu
        property int targetId: -1
        property bool targetBuiltin: false

        function openFor(groupId, builtin) {
            groupTabMenu.targetId = groupId
            groupTabMenu.targetBuiltin = builtin
            popup()
        }

        UiMenuItem {
            text: page.app ? page.app.trE("rename", page.app.languageEpoch) : ""
            onTriggered: groupDialog.openRename(groupTabMenu.targetId)
        }
        UiMenuSeparator {}
        UiMenuItem {
            text: page.app ? page.app.trE("delete", page.app.languageEpoch) : ""
            enabled: !groupTabMenu.targetBuiltin
            onTriggered: groupDialog.openDelete(groupTabMenu.targetId)
        }

        // 自定义 background 会把菜单宽度折叠为 0（Qt 6.11 Basic 实测），因此用
        // 调色板着色默认背景。
        // A custom background collapses the menu width to 0 (measured on Qt
        // 6.11 Basic), so the default background is themed via the palette.
    }

    // The card menu, the original's: edit-mode entry, send, rename/text-edit,
    // move-to-group, delete.
    // 卡片菜单，即原版菜单：编辑模式入口、发送、重命名/编辑文字、移动到分组、删除。
    UiMenu {
        // Item 型弹窗：在场景内绘制。无边框工具窗口上 Window 型原生弹窗不显示。
        // Item-type popup: rendered inside the scene, because a Window-type
        // native popup does not show on a frameless tool window.
        popupType: Popup.Item
        id: cardMenu
        objectName: "cardMenu"
        property int targetId: -1

        // The move targets and their count, held HERE rather than read from the submenu's
        // Repeater.
        //
        // # Why the Repeater's own `count` cannot be used
        //
        // A `Menu` does not instantiate a submenu's contents until that submenu is open —
        // that is how QML keeps a deep menu cheap. So a `Repeater` living inside the
        // submenu reports `count === 0` for as long as the submenu is closed, and a parent
        // item whose `enabled` reads that count is therefore ALWAYS disabled. It cannot be
        // clicked, so the submenu never opens, so the count never becomes non-zero: the
        // item is greyed out permanently and "移动到分组" was unreachable from the card
        // menu.
        //
        // Measuring the target list here breaks the circularity: Python provides the list
        // when the menu opens, and both the parent's `enabled` and the submenu's contents
        // read that one value.
        //
        // 移动目标及其数量放在"此处"，而不是从子菜单 Repeater 读取。
        //
        // # 为什么不能用 Repeater 自身的 `count`
        //
        // `Menu` 在子菜单打开之前不会实例化其内容——这正是 QML 让深层菜单保持廉价的方式。因此
        // 位于子菜单内的 `Repeater` 在子菜单关闭期间一直报告 `count === 0`，而 `enabled` 读取该
        // 计数的父项因此"永远"是禁用的。它无法被点击，于是子菜单永不打开，于是计数永不非零：该项
        // 被永久置灰，而"移动到分组"从卡片菜单无法到达。
        //
        // 在此测量目标列表打破了这一循环：Python 在菜单打开时提供列表，父项的 `enabled` 与子菜单
        // 的内容读同一个取值。
        property var moveTargets: []

        function openFor(id, gx, gy) {
            targetId = id
            // The move targets are built HERE, at open time. Two reasons, both load-bearing:
            //
            //   * the list is what enables the submenu's parent item, and that item's state
            //     is read while the parent menu is open;
            //   * `groupsForSticker` is a Python call, and a `Menu`'s `aboutToShow` is not a
            //     reliable place for one.
            // 移动目标在"打开时"在此构建。两个原因都是承重的：
            //
            //   * 该列表正是启用子菜单父项的东西，而父项的状态在父菜单打开期间被读取；
            //   * `groupsForSticker` 是一次 Python 调用，而 `Menu` 的 `aboutToShow` 不是
            //     执行它的可靠位置。
            var targets = page.app.groupsForSticker(id)
            moveTargets = targets
            popup(gx, gy)
        }

        UiMenuItem {
            text: page.app.trE("edit_mode", page.app.languageEpoch)
            enabled: !page.editMode
            onTriggered: page.editMode = true
        }
        UiMenuSeparator {}
        UiMenuItem {
            text: page.app.trE("send_copy", page.app.languageEpoch)
            onTriggered: page.app.sendSticker(cardMenu.targetId)
        }
        UiMenuSeparator {}
        UiMenuItem {
            // A text sticker edits its content; an image sticker renames — the
            // same branch the original menu took.
            // 文字贴纸编辑内容；图片贴纸重命名——与原版菜单同一分支。
            text: {
                var row = page.app.sticker(cardMenu.targetId)
                return page.app.tr((row && row.text_content)
                                   ? "edit_text" : "rename")
            }
            onTriggered: editDialog.openFor(cardMenu.targetId)
        }
        // One item that opens the move dialog, instead of a cascade or a flat list.
        //
        // The history here is worth keeping: this was a `Menu` submenu fed by a `Repeater`
        // (which cannot add entries to a `Menu` at all), then by an `Instantiator` (which can,
        // but inserting into an already-open menu does not resize it, so the entries could
        // exist invisibly), and then a flat list of entries in this same menu. The user's
        // report for the flat version was the clearest of all: "什么显示都没有，没有二级菜单
        // 也没有反应" — no submenu, no reaction, and not even a hover highlight.
        //
        // So it does not go through the menu's content pipeline at all now. A dialog with a
        // `ListView` is the most ordinary QML there is, it is built once when it opens, and a
        // short list in a dialog is easier to read and click than any cascade.
        //
        // 一个打开移动对话框的条目，取代级联或扁平列表。
        //
        // 这里的历史值得保留：它曾是 `Menu` 子菜单，由 `Repeater` 提供内容（那根本无法向 `Menu`
        // 添加条目），后来改由 `Instantiator`（可以，但向已打开的菜单插入不会让它重新调整尺寸，
        // 因此条目可能存在却不可见），再后来是本菜单里的扁平条目列表。用户对扁平版本的反馈最为明确：
        // "什么显示都没有，没有二级菜单也没有反应"——没有子菜单、没有反应，连悬停高亮都没有。
        //
        // 因此它现在完全不走菜单的内容管线。带 `ListView` 的对话框是最普通的 QML，在打开时构建一次，
        // 而对话框里的短列表比任何级联都更容易阅读和点击。
        UiMenuItem {
            text: page.app.trE("move_to_group", page.app.languageEpoch)
            enabled: page.app.groupsForSticker(cardMenu.targetId).length > 0
            onTriggered: moveDialog.openFor(cardMenu.targetId)
        }
        UiMenuSeparator {}
        UiMenuItem {
            text: page.app.trE("delete", page.app.languageEpoch)
            onTriggered: deleteDialog.openFor(cardMenu.targetId)
        }

        // 自定义 background 会把菜单宽度折叠为 0（Qt 6.11 Basic 实测），因此用
        // 调色板着色默认背景。
        // A custom background collapses the menu width to 0 (measured on Qt
        // 6.11 Basic), so the default background is themed via the palette.
    }

    // Delete confirmation with the copies count: deleting in the All view may
    // remove every copy of one picture, which is what the prompt discloses.
    // 带副本计数的删除确认：在"全部"视图删除可能移除同一张图的所有副本，提示正是为
    // 此而披露。
    Dialog {
        // Item 型弹窗：在场景内绘制。无边框工具窗口上 Window 型原生弹窗不显示。
        // Item-type popup: rendered inside the scene, because a Window-type
        // native popup does not show on a frameless tool window.
        popupType: Popup.Item
        id: deleteDialog
        anchors.centerIn: parent
        modal: true
        standardButtons: Dialog.Yes | Dialog.Cancel
        title: page.app.trE("confirm_delete", page.app.languageEpoch)
        width: Math.min(380, page.width - 40)

        property int targetId: -1
        readonly property int copies: page.app.copiesOf(deleteDialog.targetId)

        function openFor(id) {
            deleteDialog.targetId = id
            open()
        }

        contentItem: Label {
            text: deleteDialog.copies > 1
                  ? page.app.trArgsE("delete_copies_prompt",
                                     JSON.stringify({count: deleteDialog.copies}),
                                     page.app.languageEpoch)
                  : page.app.trE("confirm_delete_msg", page.app.languageEpoch)
            wrapMode: Text.WordWrap
            color: theme.text
            font.pixelSize: theme.fontSizeBody
        }

        background: Rectangle {
            color: theme.surface
            radius: theme.radiusLarge
            border.color: theme.border
        }

        onAccepted: page.app.deleteSticker(deleteDialog.targetId)
    }

    // The move-to-group picker. A dialog rather than a menu cascade — see MoveDialog.qml for
    // the three separate ways the menu approach failed.
    // 移动分组的选取器。用对话框而不是菜单级联——菜单做法的三种各自独立的失败方式见
    // MoveDialog.qml。
    MoveDialog {
        id: moveDialog
        popupType: Popup.Item
        app: page.app
    }

    // Rename (image) / edit-text (text) dialog — one dialog for both, like the
    // original's pair of dialogs collapsed by the shared backend operation.
    // 重命名（图片）/编辑文字（文字）对话框——两者共用一个对话框，如同原项目的一对
    // 对话框被共享的后端操作合并。
    Dialog {
        // Item 型弹窗：在场景内绘制。无边框工具窗口上 Window 型原生弹窗不显示。
        // Item-type popup: rendered inside the scene, because a Window-type
        // native popup does not show on a frameless tool window.
        popupType: Popup.Item
        id: editDialog
        anchors.centerIn: parent
        modal: true
        standardButtons: Dialog.Ok | Dialog.Cancel
        width: Math.min(380, page.width - 40)

        property int targetId: -1
        property string targetName: ""
        property bool editingText: false

        function openFor(id) {
            var row = page.app.sticker(id)
            targetId = id
            editingText = row.isText === true || (row.text_content || "") !== ""
            targetName = row.original_name || ""
            nameField.text = editingText ? (row.text_content || "") : targetName
            title = page.app.tr(editingText ? "edit_text_dialog" : "rename")
            open()
            nameField.forceActiveFocus()
            nameField.selectAll()
        }

        onAccepted: {
            if (editingText) {
                page.app.setStickerText(targetId, nameField.text)
            } else {
                page.app.renameSticker(targetId, nameField.text)
            }
        }

        contentItem: ColumnLayout {
            spacing: theme.spacing

            Label {
                Layout.fillWidth: true
                text: page.app.tr(editDialog.editingText ? "edit_text_prompt"
                                                          : "new_name")
                color: theme.textMuted
                font.pixelSize: theme.fontSizeSmall
                wrapMode: Text.WordWrap
            }

            UiTextField {
                id: nameField
                Layout.fillWidth: true
                selectByMouse: true
                // NO `background` override: it drew a `theme.surfaceAlt` rectangle with a
                // `theme.accent` focus border, which replaced `UiTextField`'s shell and put the legacy
                // BLUE back on a field the design system had already restyled. Same defect as the one
                // in `GroupDialog`, which is why it looked fixed there and not here.
                // 不覆写 `background`：它自绘 `theme.surfaceAlt` 矩形并用 `theme.accent` 作聚焦边框，
                // 替换了 `UiTextField` 的外壳，并把旧"蓝色"重新加到一个设计系统已经重做过样式的字段上。
                // 与 `GroupDialog` 里的缺陷相同——所以那边看起来修好了，这里却没有。
                onAccepted: editDialog.accept()
            }
        }

        background: Rectangle {
            color: theme.surface
            radius: theme.radiusLarge
            border.color: theme.border
        }
    }
}
