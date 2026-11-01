// One sticker card, drawn to the original project's `EmojiItem` spec.
//
// The card is one component serving three visual modes the original had:
// an image card (square thumbnail + name strip), a text card (variable width,
// content-fitted height, masonry columns), and multi-select mode (a check badge
// instead of sending). The hover zoom is the original's "zoom in place": an
// enlarged copy shown OVER the thumbnail, not a popup beside the card.
//
// 单张贴纸卡片，按原项目 `EmojiItem` 的规格绘制。
//
// 本组件以一个组件承担原项目的三种视觉模式：图片卡（方形缩略图 + 名称条）、文字卡（可变
// 宽度、内容适配高度、瀑布流列）、多选模式（勾选角标而非发送）。悬停放大是原版的"原位
// 放大"：在缩略图"上方"显示放大的副本，而不是卡片旁的弹窗。

import QtQuick
import QtQuick.Controls

Item {
    id: card

    // The card's inputs. Deliberately PLAIN properties with defaults, NOT
    // `required` — a GridView delegate that names a component resolves that
    // component's required properties in its own scope, and the model roles never
    // reach them (the empty-library bug this file once shipped with).
    // 卡片的输入。刻意是带默认值的"普通"属性，而非 `required`——点名组件的 GridView
    // 委托会在组件自身作用域解析 required 属性，模型角色永远到不了那里（本文件曾因
    // 此带着"空素材库"缺陷发布）。
    property var app: null
    property int stickerId: -1
    property string name: ""
    property string source: ""
    property bool isText: false
    property string textContent: ""
    property bool isSelected: false

    // Image-card edge length, scaled by the setting. Declared as a property so
    // the grid and the card agree on one number rather than each computing it.
    // 图片卡边长，按设置缩放。声明为属性，使网格与卡片对同一个数字达成一致。
    property int cardSize: 100
    // Text-card width: the masonry column's width, not the grid cell's.
    // 文字卡宽度：瀑布流列宽，而非网格单元格宽。
    property int cardWidth: 220
    property int nameFontSize: 11
    property bool showName: true

    // Multi-select edit mode: clicks toggle the badge instead of sending, and
    // hover zoom stands down.
    // 多选编辑模式：点击切换角标而非发送，悬停放大退场。
    property bool editMode: false

    // Drag-reorder input: the card is a drop target only while a reorder makes
    // sense for the current view (a group, no search filter), and never for the
    // card being dragged itself.
    // 拖拽排序输入：仅当当前视图允许重排（某个分组、无搜索过滤）时，卡片才是放置
    // 目标；被拖拽的卡片自身绝不是。
    property bool reorderEnabled: false
    property int dragStickerId: -1
    // The delegate item this card moves while dragging (handed over by the
    // delegate so the drag follows the cursor).
    // 拖拽时本卡片移动的委托项（由委托交出，使拖拽跟随光标）。
    property Item dragTarget: null

    // The text preview limits, handed over once by the page.
    // 文字预览截断上限，由页面一次性交入。
    property int textLimitSingle: 100
    property int textLimitMulti: 200

    signal activated(int stickerId)
    signal contextRequested(int stickerId, real sceneX, real sceneY)
    signal editRequested(int stickerId)
    // Drag lifecycle: start, a stream of cursor positions (the page does its own
    // hit-testing — QML DropArea delivery proved unreliable, see the page), and
    // the release.
    // 拖拽生命周期：开始、一串光标位置（页面自行命中测试——QML DropArea 的投递不可
    // 靠，原因记录在页面）、以及松开。
    signal dragStarted(int stickerId)
    signal dragMoved(int stickerId, real sceneX, real sceneY)
    signal dragEnded(int stickerId, real sceneX, real sceneY)

    // Drag-to-select in edit mode, forwarded to the page because the gesture spans cards.
    //
    // `sweepBegin` latches the direction from the card that was pressed; `sweepApply` applies
    // that direction to whichever card the pointer is over; `sweepEnd` clears the page's state.
    // They are separate signals rather than one because the page must distinguish "this card
    // decides the direction" from "this card obeys it".
    //
    // 编辑模式下的拖拽选择，转发给页面，因为该手势跨越卡片。
    //
    // `sweepBegin` 从被按下的卡片锁定方向；`sweepApply` 把该方向应用到指针所在的卡片；`sweepEnd`
    // 清除页面状态。它们是分开的信号而不是一个，因为页面必须区分"这张卡片决定方向"与"这张卡片服从
    // 方向"。
    signal sweepBegin(int stickerId)
    signal sweepApply(int stickerId)
    signal sweepEnd()

    // Scene position of the pointer while a sweep is running. The page converts it into grid
    // coordinates and hit-tests, which is what makes the sweep follow the pointer 1:1 across cells.
    // 扫选运行时指针的场景坐标。页面把它换算成网格坐标并做命中测试——这正是让扫选跨单元格"跟手"的原因。
    signal sweepAt(real sceneX, real sceneY)

    // The item scene coordinates are expressed in. Set by the page to its window.
    // 场景坐标所基于的元素。由页面设为其窗口。
    property Item positionRoot: null

    // True when this card is playing an animation rather than showing a still.
    // Set by `registerAnimation`, which asks the animator whether this sticker
    // has frames.
    // 本卡片是否在播放动画而非显示静态图。由 `registerAnimation` 设置，它向动画器询问
    // 该贴纸是否有帧。
    property bool animated: false

    // The stickers the PAGE says are on screen, as an id list.
    //
    // # Why a list rather than a geometric test
    //
    // Registration used to follow this item's `visible` property, assuming `GridView` hides delegates
    // that scroll out of sight. Measured with 60 GIF stickers and about 32 on screen: ALL 60 stayed
    // registered. Once the registry exceeds the animator's cap ("the last N registrations advance"),
    // the winners are the most recently bound cards - and while scrolling down those are the ones
    // entering at the BOTTOM, so the cards above the fold froze. That is the report: "at two thirds
    // down, only the lower half animates".
    //
    // A geometric test from the card side could not replace it: the view positions delegates through an
    // internal wrapper, so every delegate item reported `y == 0` in measurement. The page, however, can
    // compute the visible index range arithmetically from `contentY`, `cellHeight` and its column count
    // - which is the same arithmetic its hit test already relies on.
    //
    // 页面认为在屏幕上的贴纸，以 id 列表给出。
    //
    // # 为什么用列表而不是几何判断
    //
    // 注册过去跟随本元素的 `visible` 属性，假设 `GridView` 会隐藏滚出视野的委托。用 60 个 GIF、屏幕内
    // 约 32 个实测：全部 60 个保持注册。一旦注册数超过动画器上限（"最后 N 个注册允许推进"），胜出的是
    // 最近绑定的卡片——而向下滚动时那正是从"底部"进入的，于是折线以上的卡片被冻住。这正是用户报告：
    // "滚到三分之二处，只有下半部分在动"。
    //
    // 从卡片一侧做几何判断替代不了它：视图通过内部包装器定位委托，实测每个委托项的 `y` 都报告为 0。
    // 而页面可以按 `contentY`、`cellHeight` 与列数用算术算出可见索引区间——那正是它的命中测试已经在用的
    // 同一套算术。
    property var activeIds: []

    readonly property bool inViewport: card.activeIds === undefined
                                       || card.activeIds === null
                                       ? card.visible
                                       : card.activeIds.indexOf(card.stickerId) >= 0

    // Managed by the MouseArea's enter/exit; a binding to containsMouse would be
    // re-evaluated at moments the overlay cannot track.
    // 由 MouseArea 的进入/离开管理；绑定到 containsMouse 会在浮层无法跟踪的时刻重新
    // 求值。
    property bool hoveredNow: false

    // The animator's current frame URL for this sticker.
    //
    // A PLAIN property refreshed from the animator's `frameChanged` signal — NOT
    // a `frameKey()` call inside the `Image.source` binding. A slot call in a
    // binding evaluates once: the source stayed on the still file and the frames
    // that followed never reached the screen, which is exactly the "animated
    // sticker never animates" symptom.
    // 动画器为该贴纸的当前帧 URL。
    //
    // 是一个普通属性，由动画器的 `frameChanged` 信号刷新——而非在
    // `Image.source` 绑定里调用 `frameKey()`。绑定里的槽调用只求值一次：source 会
    // 停在静态文件上，之后推进的帧永远到不了屏幕，这正是“动画贴纸不动”的症状。
    property string frameUrl: ""

    function refreshFrame() {
        card.frameUrl = (card.animated && card.app)
                        ? card.app.animator.frameKey(card.stickerId) : ""
    }

    Connections {
        target: card.app ? card.app.animator : null
        function onFrameChanged() { card.refreshFrame() }
        // A decode finished in the background. Retry registration, because this card may have
        // asked to animate while its GIF was still decoding and been told "nothing yet" — it
        // showed its still thumbnail and was never registered, so without this the animation
        // would simply never start.
        //
        // Guarded on the path so a card does not re-register for an unrelated decode: the signal
        // carries the path that finished.
        // 后台解码完成。重试注册，因为本卡片可能在 GIF 仍在解码时请求过动画并被告知"暂时没有"
        // ——它显示了静态缩略图且从未注册，因此没有这一步动画就永远不会开始。
        //
        // 按路径防护，使卡片不会为一次无关的解码重新注册：该信号携带完成的那个路径。
        function onFramesDecoded(path) {
            if (!card.animated && path === card.path)
                card.registerAnimation()
        }
    }

    function registerAnimation() {
        if (!card.app || !card.app.animationEnabled || card.isText || !card.source)
            return
        var count = card.app.animator.register(card.stickerId, card.path)
        // `count > 1` is the real test for "this animates": one frame is a still,
        // and treating it as an animation would leave a timer running to redraw
        // the same picture.
        // `count > 1` 才是"这个会动"的真正判据：一帧就是静态图，把它当动画会让一个
        // 定时器一直运行去重绘同一张图。
        card.animated = count > 1
        card.refreshFrame()
    }

    function releaseAnimation() {
        if (card.app && card.app.animator)
            card.app.animator.unregister(card.stickerId)
        card.animated = false
        card.frameUrl = ""
    }

    // The filesystem path, alongside the `file://` URL: the animator decodes from
    // a path, and converting a URL back to one on every card would be wasteful
    // and error-prone.
    // 文件系统路径，与 `file://` URL 并列：动画器从路径解码，而每张卡片都把 URL 转回
    // 路径既浪费又易错。
    property string path: ""

    // The provider URL for this sticker's still frame, from a DEDICATED provider that decodes
    // one frame at the card's size. Empty until `path` is known, so the first paint falls back
    // to `source` for the moment before the bridge supplies the path.
    // 本贴纸静态帧的提供器 URL，来自一个"专用"提供器，它按卡片尺寸解码一帧。在 `path` 已知之前
    // 为空，因此首次绘制在桥提供路径之前的那一瞬回退到 `source`。
    readonly property string previewUrl: card.path !== "" && card.app
                                         ? card.app.previewUrlFor(card.path, card.cardSize)
                                         : ""

    onInViewportChanged: {
        if (inViewport)
            registerAnimation()
        else
            releaseAnimation()
    }

    onStickerIdChanged: {
        releaseAnimation()
        if (inViewport)
            registerAnimation()
    }

    Component.onDestruction: releaseAnimation()
    Component.onCompleted: if (inViewport) registerAnimation()

    // Image mode: square cell. Text mode: the column's width, and the height
    // follows the content (the label below measures itself).
    // 图片模式：方形单元格。文字模式：列宽，高度随内容（由下方标签自测）。
    width: card.isText ? card.cardWidth : card.cardSize
    height: card.isText ? (textContentLabel.height + 20)
                        : card.cardSize + (card.showName ? nameArea.height : 0)

    function scenePoint(x, y) {
        if (!card.positionRoot)
            return { "x": x, "y": y }
        var point = card.mapToItem(card.positionRoot, x, y)
        return { "x": point.x, "y": point.y }
    }

    // The preview text with the original project's limits: single-line and
    // multi-line stickers truncate at their own caps.
    // 带原项目上限的预览文本：单行与多行贴纸按各自上限截断。
    readonly property string displayText: {
        var text = card.textContent
        var limit = text.indexOf("\n") >= 0 ? card.textLimitMulti
                                            : card.textLimitSingle
        if (text.length > limit)
            return text.substring(0, limit) + "…"
        return text
    }

    // ---- card body --------------------------------------------------------
    Rectangle {
        id: body
        width: parent.width
        height: card.isText ? parent.height : card.cardSize
        radius: 8
        color: card.isSelected ? theme.cardSelected
               : hoverArea.containsMouse ? theme.cardHover
               : theme.card
        border.width: card.isSelected ? 2 : 1
        border.color: card.isSelected ? theme.textMuted
                      : hoverArea.containsMouse ? theme.borderHover
                      : (card.isText ? theme.border : "transparent")
        // Clips the scaled thumbnail to the card, so the hover zoom enlarges
        // within the card instead of spilling over the neighbours.
        // 把缩放后的缩略图裁剪在卡片内，使悬停放大在卡片内进行而不外溢到邻居。
        clip: !card.isText

        // Text stickers show their content, left-aligned like the original's
        // text label, inside the padded box.
        // 文字贴纸显示其内容，像原版的文字标签一样左对齐，位于带内边距的盒内。
        Text {
            id: textContentLabel
            anchors.centerIn: parent
            width: parent.width - 24
            visible: card.isText
            text: card.displayText
            wrapMode: Text.Wrap
            // Text stays left-aligned; the anchors center the block.
            // 文本保持左对齐；锚点使文字块居中。
            horizontalAlignment: Text.AlignLeft
            color: theme.text
            // The BUNDLED family, not a hardcoded `Microsoft YaHei`.
            //
            // This was the last place in the interface that named a system font. On Windows the
            // difference is invisible; on Linux the name does not exist, so the text card silently
            // fell back to whatever Qt picked, which is exactly the kind of platform-dependent
            // metric drift the bundled family exists to remove.
            // 用"随包"字族，而不是硬编码的 `Microsoft YaHei`。
            //
            // 这是界面里最后一处命名系统字体的地方。在 Windows 上看不出差别；在 Linux 上该名字不存在，
            // 于是文字卡片静默回退到 Qt 挑的字体——正是随包字族要消除的那种依赖平台的度量漂移。
            font.family: theme.fontFamily
            font.pixelSize: 16
        }

        Image {
            id: thumb
            anchors.fill: parent
            anchors.margins: 4
            visible: !card.isText
            // PREVIEW FIRST, animation second.
            //
            // The placeholder used to be `card.source` — the `file://` URL of the GIF — which
            // makes this `Image` decode the WHOLE animated file with a default `QImageReader` on
            // the GUI thread, once per card. For the user's own library that is the same
            // 231-383 ms the animator pays, charged a second time per card.
            //
            // `previewUrl` goes through the preview provider, which asks `QImageReader` for frame
            // 0 at the card's size, so only one frame is decoded and only at the size needed.
            // The animation then replaces it when the background decode lands.
            //
            // 预览优先，动画其次。
            //
            // 占位符过去是 `card.source`——GIF 的 `file://` URL——那会让这个 `Image` 在 GUI 线程上
            // 用默认的 `QImageReader` 解码"整个"动画文件，且每张卡片一次。对用户自己的素材库来说，
            // 那与动画器付出的 231-383 毫秒相同，而每张卡片还要再收一次。
            //
            // `previewUrl` 走预览提供器，它向 `QImageReader` 请求卡片尺寸的第 0 帧，因此只解码一帧、
            // 且只按所需尺寸解码。后台解码落地后，动画会取代它。
            source: card.isText ? ""
                    : (card.animated && card.frameUrl !== ""
                       ? card.frameUrl
                       : (card.previewUrl !== "" ? card.previewUrl : card.source))
            fillMode: Image.PreserveAspectFit
            asynchronous: !card.animated
            sourceSize.width: card.animated ? 0 : card.width
            sourceSize.height: card.animated ? 0 : card.height
            cache: !card.animated
            smooth: true
            // The hover zoom scales THIS image — the one already rendering (a
            // still or the animator's current frame) — instead of stacking a
            // second, enlarged copy over it. A transform never touches layout,
            // so the name strip and neighbours stay put; the body clips the
            // result to the card, like the original's zoom-in-place.
            // 悬停放大缩放"当前正在渲染"的这张图（静态帧或动画器的当前帧），而不是
            // 在其上再叠一层放大副本。transform 不触碰布局，名称条与邻居位置不变；
            // 卡体把结果裁剪在卡片内，即原版的"原位放大"。
            scale: hoveredNow && !card.editMode && !card.isText
                   && card.app && card.app.hoverPreviewEnabled
                   && card.app.hoverZoom > 1.0 && status === Image.Ready
                   ? Math.max(1.0, card.app.hoverZoom) : 1.0
            transformOrigin: Item.Center
        }

        BusyIndicator {
            anchors.centerIn: parent
            visible: !card.isText && thumb.status === Image.Loading
            running: visible
            width: 22
            height: 22
        }

        // The check badge: a grey ring when unselected, a solid disc when
        // selected — the original's 18x18 corner badge at (2, 2).
        // 勾选角标：未选中为灰环，选中为实心圆——原版 (2, 2) 处的 18x18 角标。
        Rectangle {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.margins: 2
            width: 18
            height: 18
            radius: 9
            visible: card.editMode
            color: card.isSelected ? theme.uiColors.selected : "transparent"
            border.width: 2
            border.color: card.isSelected ? theme.uiColors.selected : theme.borderStrong
        }
    }

    // ---- name strip -------------------------------------------------------
    Label {
        id: nameArea
        anchors.top: body.bottom
        width: parent.width
        height: card.nameFontSize + 10
        visible: card.showName && !card.isText
        text: card.name
        elide: Text.ElideRight
        horizontalAlignment: Text.AlignHCenter
        color: theme.textMuted
        font.pixelSize: card.nameFontSize
    }

    // ---- interaction ------------------------------------------------------
    MouseArea {
        id: hoverArea
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: Qt.PointingHandCursor

        // Hold the gesture for its whole duration while editing.
        //
        // Without this the press was implicitly released to whatever sat under the
        // pointer as soon as it left the card, so a sweep died at the first cell boundary
        // - and the moves it lost arrived nowhere, which is why the selection lagged and
        // eventually stopped. Off in normal mode so the grid can still be dragged to
        // scroll.
        // 编辑时在整个手势期间持有事件。
        //
        // 缺了它，指针一离开卡片，按下就被隐式交还给指针下的其他元素，于是扫选在第一个
        // 单元格边界就断掉——而它丢失的那些移动没有到达任何地方，这就是选择会迟滞并最终停住的
        // 原因。普通模式下关闭，使网格仍能通过拖拽滚动。
        preventStealing: card.editMode

        // Named so a check can find the interactive area of a card and deliver real mouse events
        // to it. Without a name there is no way to test selection at all: `findChildren(QObject)`
        // cannot identify a `MouseArea` by class (every visual item reports `QQuickItem`), and the
        // number of them in a grid is large enough that "the first one" is not an identity.
        // 命名使检查能找到卡片的交互区域并向它投递真实鼠标事件。没有名称就根本无法测试选择：
        // `findChildren(QObject)` 无法按类识别 `MouseArea`（每个可视元素都报告为 `QQuickItem`），
        // 而网格里它们的数量多到"第一个"并不构成身份。
        objectName: "cardMouseArea"

        // Drag threshold bookkeeping. Past the threshold the DELEGATE item
        // (`dragTarget`) follows the cursor for the visual, and the cursor's
        // scene position streams to the page, which owns the hit test.
        // 拖拽阈值记账。超过阈值后委托项（`dragTarget`）跟随光标作视觉反馈，而光标的
        // 场景坐标流式发给页面——命中测试由页面负责。
        property point pressPoint
        property point slotOrigin
        property bool dragging: false

        // The delegate hands itself over, so the card can move it while dragging
        // and snap it back afterwards.
        // 委托把自身交出，使卡片能在拖拽时移动它、结束后让它弹回。
        drag.target: card.reorderEnabled ? card.dragTarget : null
        drag.axis: Drag.XAndYAxis
        drag.threshold: 10


        onPressed: function (mouse) {
            pressPoint = Qt.point(mouse.x, mouse.y)
            slotOrigin = card.dragTarget
                         ? Qt.point(card.dragTarget.x, card.dragTarget.y)
                         : Qt.point(0, 0)
            dragging = false
            // In edit mode the press LATCHES the sweep direction, so the page knows which way
            // every card the pointer crosses should go. Doing it here rather than on release is
            // what makes a click and a sweep the same code path: a click is simply a sweep that
            // never crossed another card.
            // 编辑模式下按下会"锁定"扫选方向，使页面知道指针掠过的每张卡片应被设成什么。在这里而不是
            // 释放时做，正是让单击与扫选成为同一条代码路径的原因：单击只是一次从未跨到另一张卡片的扫选。
            if (card.editMode && mouse.button === Qt.LeftButton && card.sweepBegin)
                card.sweepBegin(card.stickerId)
        }

        onPositionChanged: function (mouse) {
            // In edit mode the pointer belongs to the sweep, and this card OWNS the gesture (see
            // `preventStealing`), so every move is reported to the page as a scene position. The page
            // hit-tests the grid, which is what makes a sweep cross cells without this item ever
            // knowing which card it is over.
            // 编辑模式下指针属于扫选，而本卡片"持有"该手势（见 `preventStealing`），因此每一次移动都以
            // 场景坐标报给页面。页面负责在网格上命中测试——这正是让扫选能跨单元格、而本元素无需知道
            // 自己正压在哪个卡片上的原因。
            if (card.editMode && pressed) {
                var sweepPoint = card.scenePoint(mouse.x, mouse.y)
                card.sweepAt(sweepPoint.x, sweepPoint.y)
                return
            }
            if (!pressed || !card.reorderEnabled)
                return
            var dx = mouse.x - pressPoint.x
            var dy = mouse.y - pressPoint.y
            if (!dragging) {
                if (Math.abs(dx) + Math.abs(dy) <= 10)
                    return
                dragging = true
                card.dragStarted(card.stickerId)
            }
            var point = card.scenePoint(mouse.x, mouse.y)
            card.dragMoved(card.stickerId, point.x, point.y)
        }

        onReleased: function (mouse) {
            if (dragging) {
                var point = card.scenePoint(mouse.x, mouse.y)
                card.dragEnded(card.stickerId, point.x, point.y)
                // Snap the delegate back to its cell; a successful drop reloads
                // the model anyway, a failed one must not leave the card
                // floating.
                // 把委托弹回其单元格；成功的放置会重载模型，失败的放置也不能让卡片
                // 悬在半空。
                if (card.dragTarget) {
                    card.dragTarget.x = slotOrigin.x
                    card.dragTarget.y = slotOrigin.y
                }
            } else if (mouse.button === Qt.RightButton) {
                var point = card.scenePoint(mouse.x, mouse.y)
                card.contextRequested(card.stickerId, point.x, point.y)
            } else if (card.editMode) {
                // The press already applied the latch, which for a single card IS the toggle.
                // Toggling again here would undo the click. `sweepEnd` only clears the page's
                // sweep state.
                // 按下时已经应用了锁定值，对单张卡片而言那就是切换。此处再次切换会撤销这次点击。
                // `sweepEnd` 只清除页面的扫选状态。
                if (card.sweepEnd)
                    card.sweepEnd()
            } else {
                card.activated(card.stickerId)
            }
            dragging = false
        }

        // Only the hover flag here. The sweep is driven by the page's overlay from the moment
        // `onPressed` reports the latch, so a card does nothing when the cursor merely crosses
        // it - see the comment in `onPositionChanged` for why there must be exactly one driver.
        // 此处只设悬停标志。扫选自 `onPressed` 报告锁定值起就由页面的覆盖层驱动，因此光标仅仅
        // 掠过一张卡片时它什么也不做——为什么必须恰好有一个驱动，见 `onPositionChanged` 中的注释。
        onEntered: card.hoveredNow = true
        onExited: card.hoveredNow = false
    }
}
