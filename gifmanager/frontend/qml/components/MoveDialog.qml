// Pick a destination group for one or more stickers.
//
// # Why a dialog rather than a menu submenu
//
// This action was a `Menu` submenu filled by a `Repeater`, then by an `Instantiator`. Both
// approaches were unreliable for the same underlying reason: a `Menu` does not build its
// contents until it is shown, and its children only become entries through
// `insertItem`/`addItem`. Three separate failure modes followed, and each one alone made the
// feature look dead:
//
//   * a `Repeater` reparents delegates instead of calling `insertItem`, so the submenu was
//     created EMPTY;
//   * an `Instantiator` works only when `onObjectAdded` calls `insertItem`, and inserting into
//     an already-open menu does not resize it, so the entries could exist yet not be visible;
//   * a nested `Menu` with `popupType: Popup.Item` needs its own usable geometry, which a
//     frameless tool window does not always give it.
//
// A dialog has none of those properties: a `ListView` over a `model` is the most ordinary QML
// there is, it is created once when the dialog opens, and its rows are plain items. The
// destination list is short and known, so a list in a dialog is also simply easier to read and
// to click than a cascade.
//
// 为一个或多个贴纸选择目标分组。
//
// # 为什么用对话框而不是菜单子菜单
//
// 这个操作曾是 `Menu` 子菜单，先由 `Repeater` 填充、后由 `Instantiator` 填充。两种做法都不可靠，
// 根因相同：`Menu` 在被显示之前不会构建内容，而其子项只有经 `insertItem`/`addItem` 才成为条目。
// 由此产生三种各自独立的失败模式，每一种单独就足以让该功能看起来是死的：
//
//   * `Repeater` 重设委托父项而不调用 `insertItem`，因此子菜单被创建为"空"；
//   * `Instantiator` 只有在 `onObjectAdded` 调用 `insertItem` 时才行，而向已打开的菜单插入不会
//     让它重新调整尺寸，因此条目可能存在却不可见；
//   * 带 `popupType: Popup.Item` 的嵌套 `Menu` 需要自己可用的几何尺寸，而无边框工具窗口并不总能
//     给它。
//
// 对话框没有这些性质：`ListView` 加 `model` 是最普通的 QML，它在对话框打开时创建一次，其行是普通
// 元素。目的地列表短而已知，因此对话框里的列表也比级联更容易阅读和点击。

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "./ui"
import "../components/ui"

UiDialog {
    id: moveDialog

    required property var app

    // The sticker being moved. A single id for the card menu; for edit mode the bridge moves
    // whatever is selected, so this is only used to compute the target list.
    // 正在被移动的贴纸。卡片菜单用单个 id；编辑模式下桥会移动被选中的那些，因此这里只用它计算
    // 目标列表。
    property int targetId: -1
    // True when the caller is the edit-mode toolbar, which moves the whole selection.
    // 调用方是编辑模式工具栏时为真，那会移动整个选择。
    property bool movingSelection: false
    // The destination groups, from the bridge.
    // 目的分组，来自桥。
    property var targets: []

    title: app ? app.trE("move_to_group", app.languageEpoch) : ""
    modal: true
    // Sized from the number of destinations, with a FLOOR.
    //
    // The floor is the important part: without one, a dialog opened from a small item (the
    // card menu lives inside the library page, which can be shorter than the window) computed
    // its height from its parent and came out too short to show more than a couple of rows,
    // with no obvious way to reach the rest.
    //
    // A destination picker should show its options, so this prefers height over compactness.
    // 按目的地数量定尺寸，但设"下限"。
    //
    // 下限是要紧的部分：没有它时，从一个小元素打开的对话框（卡片菜单位于素材库页面内，而该页面可能
    // 比窗口矮）会按其父级算出高度，结果矮到只能显示两三行，且没有明显方式够到其余部分。
    //
    // 目的地选取器应该把选项显示出来，因此它宁取高度而不取紧凑。
    readonly property int minimumHeight: 320
    readonly property int maximumHeight: 620
    width: Math.min(400, parent ? parent.width - 40 : 360)
    height: {
        var wanted = 150 + Math.max(1, Math.min(targets.length, 14)) * rowHeight
        var available = parent ? parent.height - 40 : maximumHeight
        return Math.max(minimumHeight, Math.min(maximumHeight, Math.min(wanted, available)))
    }
    anchors.centerIn: parent
    closePolicy: Popup.CloseOnEscape
    padding: 0

    // Row height, named so the height calculation above and the delegate agree on one number.
    // 行高，命名使上面的高度计算与委托对同一个数字达成一致。
    readonly property int rowHeight: 38

    // Open for ONE sticker. `id` supplies the move targets.
    // 为"单个"贴纸打开。`id` 提供移动目标。
    function openFor(id) {
        targetId = id
        movingSelection = false
        targets = app ? app.groupsForSticker(id) : []
        open()
    }

    // Open for the EDIT-MODE selection: the targets are every group the selection can move to.
    // 为"编辑模式"的选择打开：目标是该选择可以移入的每个分组。
    function openForSelection() {
        targetId = -1
        movingSelection = true
        targets = app ? app.moveTargetsForSelection() : []
        open()
    }

    contentItem: ColumnLayout {
        spacing: 0

        Label {
            Layout.fillWidth: true
            Layout.margins: 14
            // A count so a multi-select move says how many are going, which is the one fact a
            // user needs before committing.
            // 显示数量，使多选移动说明有多少个将被移动——那是用户在确认前唯一需要的事实。
            text: moveDialog.movingSelection && moveDialog.app
                  ? moveDialog.app.trE("move_count_hint",
                                       moveDialog.app.languageEpoch)
                    .replace("{count}",
                             String(moveDialog.app.stickers.selectedCount))
                  : ""
            visible: moveDialog.movingSelection
            color: theme.textMuted
            font.pixelSize: theme.fontSizeSmall
            wrapMode: Text.WordWrap
        }

        ListView {
            id: targetList
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: 6
            Layout.rightMargin: 6
            Layout.bottomMargin: 8
            clip: true
            model: moveDialog.targets
            boundsBehavior: Flickable.StopAtBounds
            // `AlwaysOn` when the list overflows, not `AsNeeded`. An overlay scroll bar that
            // fades in on hover is invisible on a touchpad-free setup until the user happens to
            // scroll, so a list longer than the dialog looked like the complete list rather
            // than like something to scroll.
            // 列表溢出时用 `AlwaysOn` 而不是 `AsNeeded`。悬停才淡入的浮层滚动条在未触摸的环境下
            // 直到用户恰好滚动才可见，因此比对话框更长的列表看起来像完整列表，而不像可以滚动的东西。
            ScrollBar.vertical: UiScrollBar {
                policy: targetList.contentHeight > targetList.height
                        ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
            }

            delegate: ItemDelegate {
                required property var modelData
                width: targetList.width
                height: moveDialog.rowHeight
                onClicked: {
                    if (moveDialog.movingSelection)
                        moveDialog.app.moveSelection(modelData.id)
                    else
                        moveDialog.app.moveSticker(moveDialog.targetId, modelData.id)
                    moveDialog.close()
                }

                contentItem: Label {
                    text: modelData.name
                    color: theme.text
                    font.pixelSize: theme.fontSizeBody
                    verticalAlignment: Text.AlignVCenter
                    leftPadding: theme.spacing
                }
                background: Rectangle {
                    radius: theme.radius
                    color: parent.hovered ? theme.surfaceHover : "transparent"
                }
            }
        }

        // An empty list is a real state — every other group may be a text group — so it says so
        // rather than presenting a blank box.
        // 列表为空是一个真实状态——其他分组可能都是文字分组——因此它说明这一点，而不是呈现一个空框。
        Label {
            Layout.fillWidth: true
            Layout.margins: 14
            visible: moveDialog.targets.length === 0
            text: moveDialog.app ? moveDialog.app.trE("no_move_target",
                                                      moveDialog.app.languageEpoch) : ""
            color: theme.textMuted
            font.pixelSize: theme.fontSizeSmall
            wrapMode: Text.WordWrap
        }
    }

    footer: Item {
        implicitHeight: footerRow.implicitHeight + 28

        RowLayout {
            id: footerRow
            anchors.fill: parent
            anchors.margins: 14
            // Right-aligned, so a primary action sits at the trailing edge where
            // the eye expects to confirm. `DialogButtonBox` stretched the buttons
            // to fill the width, which made every dialog's actions look like a
            // toolbar rather than a decision.
            // 右对齐，使主操作位于拖尾边缘——眼睛预期在那里确认。`DialogButtonBox`
            // 会把按钮拉伸到整宽，使每个对话框的操作看起来像工具栏而不是一个决定。
            Layout.fillWidth: true
            // A spacer that absorbs the slack, so the buttons keep their natural widths and
            // sit at the trailing edge. Reversing the layout direction instead also reversed
            // the ORDER, which put the cancel button rightmost.
            // 吸收多余空间的弹簧，使按钮保持自然宽度并停在拖尾边缘。改为反转布局方向会同时反转
            // "顺序"，把取消按钮放到了最右。
            Item { Layout.fillWidth: true }
            spacing: 8
            UiButton {
                text: moveDialog.app ? moveDialog.app.trE("cancel",
                                                          moveDialog.app.languageEpoch) : ""
                onClicked: moveDialog.close()
            }
        }
    }

}
