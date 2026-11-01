// A shadcn-style combo box, following SWB-QML-UI's `SwbComboBox`.
//
// The trigger is the same shell as `UiTextField` (surface, 1px border, ring on focus) plus a small
// chevron; the popup is a `popover` surface with a 1px border, and the SELECTED row is the only
// high-contrast element - `selected` fill with `selectedForeground` text. That is the same rule the
// rest of the design system follows, so a chosen item reads the same way in a list as a chosen tab
// reads in the tab bar.
//
// The popup is opened with a short scale-and-fade from 0.96 plus opacity, not from zero: an element
// that grows out of nothing looks like it came from nowhere.
//
// 一个 shadcn 风格下拉框，遵循 SWB-QML-UI 的 `SwbComboBox`。
//
// 触发器与 `UiTextField` 同一个外壳（表面、1px 边框、聚焦时 ring）加一个小箭头；弹出层是 `popover`
// 表面加 1px 边框，而"选中行"是唯一的高对比元素——`selected` 填充配 `selectedForeground` 文字。
// 这与设计系统其余部分遵循同一条规则，使"被选中的项"在列表里的读法与"被选中的标签"在标签栏里一致。
//
// 弹出层以 0.96 起的缩放加淡入打开，而不是从 0 起：从"无"中长出来的元素看起来像凭空出现。

import QtQuick
import QtQuick.Controls.Basic

ComboBox {
    id: control

    readonly property var ui: theme ? theme.uiColors : ({})
    readonly property var metrics: theme ? theme.uiMetrics : ({})

    implicitWidth: 180
    implicitHeight: control.metrics.uiControlHeight
    leftPadding: control.metrics.uiPaddingX
    rightPadding: control.metrics.uiPaddingX + 18
    font.pixelSize: control.metrics.uiFontSize
    opacity: control.enabled ? 1.0 : 0.5
    hoverEnabled: true

    // Press feedback on the trigger, like a button.
    // 触发器上的按压反馈，与按钮一致。
    scale: control.pressed && control.enabled ? control.metrics.uiPressScale : 1.0
    Behavior on scale {
        NumberAnimation {
            duration: control.metrics.uiPressMs
            easing.type: Easing.OutCubic
        }
    }

    contentItem: Text {
        leftPadding: 0
        rightPadding: control.indicator.width + 2
        text: control.displayText
        font: control.font
        color: control.ui.foreground
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    indicator: Text {
        x: control.width - control.rightPadding + 4
        y: (control.height - height) / 2
        text: "\u25be"
        font.pixelSize: control.metrics.uiFontSizeSm
        color: control.ui.mutedForeground
        visible: control.enabled
    }

    background: Rectangle {
        implicitWidth: 180
        implicitHeight: control.metrics.uiControlHeight
        radius: control.metrics.uiRadius
        color: control.hovered ? control.ui.surface2 : control.ui.surface1
        border.color: control.activeFocus || control.popup.visible
                      ? control.ui.ring : control.ui.border
        border.width: 1
        Behavior on color { ColorAnimation { duration: control.metrics.uiAnimationMs } }
        Behavior on border.color { ColorAnimation { duration: control.metrics.uiAnimationMs } }

        Rectangle {
            anchors.fill: parent
            anchors.margins: -control.metrics.uiFocusRingWidth
            radius: parent.radius + control.metrics.uiFocusRingWidth
            color: "transparent"
            border.color: control.ui.focusRing
            border.width: control.metrics.uiFocusRingWidth
            visible: control.activeFocus || control.popup.visible
        }
    }

    // The popup rows. Deliberately an `ItemDelegate` with ONLY `palette` and `background` overridden,
    // never `contentItem`.
    //
    // # The bug this replaces
    //
    // The first version wrote `contentItem: Text { text: String(row.modelData) }`. The settings model
    // supplies choices as `[{label: "深色模式", value: "dark"}, ...]`, so `String(object)` produced
    // `[object Object]` in every popup row - the reported "shows the value instead of the name".
    // Re-implementing the text also threw away `textRole`, which is what maps a row to its label.
    //
    // Leaving `contentItem` alone means Qt's own `ComboBox` delegate logic resolves `textRole`, so the
    // label is correct by construction; the design only supplies colours.
    // 弹出层行。刻意只是 `ItemDelegate`，且只覆写 `palette` 与 `background`，绝不覆写 `contentItem`。
    //
    // # 本修复针对的缺陷
    //
    // 第一个版本写了 `contentItem: Text { text: String(row.modelData) }`。设置模型提供的选项是
    // `[{label: "深色模式", value: "dark"}, ...]`，因此 `String(object)` 在每一行都产生
    // `[object Object]`——也就是用户报告的"显示的是值而不是名称"。重写文字同时丢掉了 `textRole`，而
    // 它正是把一行映射到其标签的东西。
    //
    // 不碰 `contentItem` 意味着 Qt 自身的 `ComboBox` 委托逻辑会解析 `textRole`，因此标签在构造上就是
    // 正确的；设计只提供颜色。
    delegate: ItemDelegate {
        id: row
        required property int index
        required property var modelData
        width: control.width - 8
        height: control.metrics.uiControlHeightSm
        highlighted: control.highlightedIndex === index
        leftPadding: control.metrics.uiPaddingX
        rightPadding: control.metrics.uiPaddingX

        // `text` MUST be set here, and this is the whole reason the first fix did not work.
        //
        // Removing the `contentItem` override let Qt draw the row, but `ItemDelegate`'s default
        // content item renders `text` - and a custom `delegate` does NOT inherit ComboBox's
        // `textRole` resolution, so `text` stayed empty and the popup showed blank rows (the reported
        // "选项无法显示文字"). Qt's own delegate sets this line itself; overriding the delegate means
        // taking that responsibility over.
        //
        // The `textRole` half is guarded because `modelData` is not always an object: a plain list of
        // strings has no key to index.
        // 这里"必须"设置 `text`，而这正是第一次修复没有奏效的原因。
        //
        // 移除 `contentItem` 覆写让 Qt 去画这一行，但 `ItemDelegate` 的默认内容项渲染的是 `text`
        // ——而自定义 `delegate` "不会"继承 ComboBox 的 `textRole` 解析，于是 `text` 保持为空、弹出层
        // 显示空白行（即用户报告的"选项无法显示文字"）。Qt 自己的委托本来就会设这一行；覆写委托就意味着
        // 接管那份责任。
        //
        // `textRole` 那一半加了防护，因为 `modelData` 不总是对象：纯字符串列表没有可索引的键。
        text: control.textRole && row.modelData !== undefined && row.modelData !== null
              && typeof row.modelData === "object"
              ? String(row.modelData[control.textRole])
              : (row.modelData !== undefined && row.modelData !== null
                 ? String(row.modelData) : "")

        readonly property bool chosen: control.currentIndex === row.index

        // The ink colour, computed ONCE.
        //
        // `palette.text: palette.windowText` looked harmless and produced
        //     QML Palette: Binding loop detected for property "text"
        // because the two palette roles are independent properties that both re-emit: assigning one
        // from the other makes each depend on the other. Two bindings to the same source value is the
        // way that avoids it.
        // 一次算好的文字颜色。
        //
        // `palette.text: palette.windowText` 看起来无害，却产生了
        //     QML Palette: Binding loop detected for property "text"
        // 因为这两个调色板角色是各自会重新发出的独立属性：用其中一个赋值另一个会让两者互相依赖。让两者
        // 绑定到同一个来源值才是避免它的做法。
        readonly property color ink: row.chosen ? control.ui.selectedForeground
                                                : control.ui.foreground

        // The chosen row is high contrast and everything else is muted; hover is a step up rather
        // than the accent, so no new colour enters the system.
        //
        // ALL FOUR roles are set, and that is not redundant. Basic's `ItemDelegate` swaps to
        // `highlightedText` while `highlighted` is true, and `highlight` would paint a second
        // highlight rectangle over our own `background`. Setting only `windowText`/`text` left the
        // chosen row as light text on the light `selected` fill - legible in the capture only as a
        // smudge, which is how it reached the user.
        // 被选中的行高对比，其余为弱化色；悬停是上抬一级而不是强调色，因此系统里不引入新颜色。
        //
        // 四个角色"都"要设，这并非冗余。Basic 的 `ItemDelegate` 在 `highlighted` 为真时会改用
        // `highlightedText`，而 `highlight` 会在我们自己的 `background` 之上再画一个高亮矩形。只设
        // `windowText`/`text` 会让选中行成为"浅色文字压在浅色 `selected` 填充上"——在截图里只是一团
        // 糊影，这正是它到达用户眼前的样子。
        palette.windowText: row.ink
        palette.text: row.ink
        palette.highlightedText: row.ink
        palette.highlight: "transparent"

        background: Rectangle {
            radius: control.metrics.uiRadiusSm - 2
            color: row.chosen
                   ? control.ui.selected
                   : row.highlighted ? control.ui.accent : "transparent"
        }
    }

    popup: Popup {
        y: control.height + 4
        width: control.width
        implicitHeight: Math.min(contentItem.implicitHeight + 8, 260)
        padding: 4

        // Scale from 0.96 with opacity, not from zero: an element that grows out of nothing looks
        // like it came from nowhere.
        // 以 0.96 缩放加不透明度，而不是从 0 起：从"无"中长出来的元素看起来像凭空出现。
        enter: Transition {
            ParallelAnimation {
                NumberAnimation {
                    property: "opacity"
                    from: 0.0
                    to: 1.0
                    duration: control.metrics.uiAnimationMs
                    easing.type: Easing.OutCubic
                }
                NumberAnimation {
                    property: "scale"
                    from: 0.96
                    to: 1.0
                    duration: control.metrics.uiAnimationMs
                    easing.type: Easing.OutCubic
                }
            }
        }
        exit: Transition {
            NumberAnimation {
                property: "opacity"
                from: 1.0
                to: 0.0
                duration: control.metrics.uiPressMs
                easing.type: Easing.OutCubic
            }
        }

        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.delegateModel
            currentIndex: control.highlightedIndex
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        }

        background: Rectangle {
            radius: control.metrics.uiRadius
            color: theme.surface
            border.color: control.ui.borderStrong
            border.width: 1
        }
    }
}
