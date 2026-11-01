// A shadcn-style dialog frame, following SWB-QML-UI's `SwbDialog`.
//
// Every secondary window in this application uses it - new group, rename group, edit text sticker,
// move to group, import, update - so they share one surface, one border, one radius and one entrance.
//
// # The entrance
//
// Scale from 0.96 with a simultaneous opacity fade over 150 ms, out-cubic. Not from 0: nothing in
// the real world appears from nothing, and a modal that inflates from a point reads as a visual
// glitch rather than as a surface arriving. A modal keeps its origin CENTRED (unlike a popover,
// which should scale from its trigger) because it is not anchored to anything - it is presented over
// the whole window.
//
// The 1px `borderStrong` edge plus the popover fill is what separates the surface from the scrim
// without a drop shadow: a shadow would need a `MultiEffect` per dialog and would fight the
// frameless window's own compositing.
//
// 一个 shadcn 风格对话框外框，遵循 SWB-QML-UI 的 `SwbDialog`。
//
// 本应用所有二级窗口都用它——新建分组、重命名分组、编辑文字贴纸、移动到分组、导入、更新——因此它们
// 共用同一个表面、边框、圆角与入场方式。
//
// # 入场
//
// 从 0.96 缩放，同时 150 毫秒 out-cubic 淡入。不从 0 起：现实中没有东西是从"无"中出现的，而从一点
// 膨胀出来的模态读作视觉故障而不是"表面到达"。模态的原点保持"居中"（不同于应从触发器缩放的浮层），
// 因为它不锚定于任何东西——它呈现在整个窗口之上。
//
// 1px 的 `borderStrong` 边加 popover 填充，是不用投影就把表面与遮罩区分开的手段：投影需要每个对话框
// 一个 `MultiEffect`，并且会与无边框窗口自身的合成冲突。

import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Dialog {
    id: control

    readonly property var ui: theme ? theme.uiColors : ({})
    readonly property var metrics: theme ? theme.uiMetrics : ({})

    // Item-type popup, because a Window-type native popup does not show on a frameless tool window.
    // That constraint predates this component and is the reason it is set here rather than per
    // call site: a dialog that silently fails to appear is the worst failure mode.
    // Item 型弹窗，因为 Window 型原生弹窗在无边框工具窗口上不会显示。该约束早于本组件存在，而把它设
    // 在"这里"而不是每个调用点的理由正是：静默不出现的对话框是最糟的失效方式。
    popupType: Popup.Item
    modal: true
    anchors.centerIn: parent
    padding: control.metrics.uiDialogPadding
    closePolicy: Popup.CloseOnEscape
    implicitWidth: control.metrics.uiDialogWidth

    // The scrim: dim to focus, which is Apple's rule for a modal task. It is translucent rather than
    // a flat black overlay so the window behind is still legible as context.
    // 遮罩：压暗以聚焦，正是 Apple 对模态任务的规则。它是半透明而不是一块平黑，使背后的窗口仍可读作
    // 上下文。
    Overlay.modal: Rectangle {
        color: control.ui.scrim
    }

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

    background: Rectangle {
        radius: control.metrics.uiRadiusLarge
        // The MAIN window colour, not the popover token.
        //
        // A secondary window that is a different shade of grey from the window it covers reads as a
        // foreign surface - the eye cannot tell whether the difference is hierarchy or a mistake.
        // Using the window colour makes the dialog a LAYER of the same material, and the 1px
        // `borderStrong` edge plus the scrim is what separates it. This is Apple's "material weight
        // encodes hierarchy" applied with one material instead of two.
        // 用"主窗口"的颜色，而不是 popover 令牌。
        //
        // 一个与它所覆盖的窗口呈不同灰度的二级窗口读起来像一块外来的表面——眼睛分不清那个差别是层级
        // 还是错误。用窗口色让对话框成为"同一种材料的另一层"，而 1px 的 `borderStrong` 边与遮罩正是
        // 把它区分开的东西。这是 Apple 的"材料轻重编码层级"，只用在一种材料上而不是两种。
        color: theme ? theme.window : control.ui.popover
        border.color: control.ui.borderStrong
        border.width: 1
    }

    // The header: a title on its own line, muted, small, with the same left padding as the content
    // so the text column is one straight edge.
    // 页眉：标题独占一行、弱化色、小字号，与内容同样的左内边距，使文字列是一条直边。
    header: Item {
        implicitHeight: control.title === "" ? 0 : 34

        Text {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: control.metrics.uiDialogPadding
            anchors.rightMargin: control.metrics.uiDialogPadding
            text: control.title
            visible: control.title !== ""
            color: control.ui.foreground
            font.pixelSize: control.metrics.uiFontSize
            font.weight: Font.DemiBold
            // Negative tracking on a short heading, which is the one place Apple recommends it.
            // 短标题上用负字距——Apple 推荐使用它的那一种场合。
            font.letterSpacing: -0.2
            elide: Text.ElideRight
        }
    }

    // The footer: right-aligned buttons. `contentItem` is left to the caller; a dialog that needs no
    // buttons simply never sets `footer`.
    // 页脚：右对齐按钮。`contentItem` 留给调用方；不需要按钮的对话框不设 `footer` 即可。
    footer: null
}
