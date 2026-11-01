// A shadcn-style tooltip.
//
// # Why the app palette was not enough
//
// An attached `ToolTip.visible`/`ToolTip.text` creates a `QtQuick.Controls.Basic` tooltip, whose
// background comes from that style. Setting `QPalette.ToolTipBase` did change it
// (`#252525` in dark, verified), but the theme's surface is very close to `ToolTipBase`, so the
// result still read as "a box from another application": the stock style draws its own 1px
// `palette.mid` frame and a rectangular, unscaled surface that matches nothing else in this interface.
//
// A palette can only ever produce "a themed Basic tooltip". This component produces OUR tooltip -
// same radius, same border, same ink and the same entrance as the menus and the combo popup - which is
// what "风格统一" actually requires.
//
// 一个 shadcn 风格提示框。
//
// # 为什么光靠应用调色板不够
//
// 用附加属性 `ToolTip.visible`/`ToolTip.text` 创建的是 `QtQuick.Controls.Basic` 的提示框，背景来自
// 该样式。设置 `QPalette.ToolTipBase` 确实改变了它（深色下 `#252525`，已验证），但主题表面与
// `ToolTipBase` 非常接近，结果仍然读作"来自另一个应用的方块"：原样式会自己画一条 `palette.mid` 的
// 1px 边框，并且是一块不带圆角的矩形表面，与本界面里任何东西都不相配。
//
// 调色板最多只能产出"一个被上色的 Basic 提示框"。本组件产出"我们的"提示框——同样的圆角、边框、文字
// 颜色，以及与菜单和下拉弹出层相同的入场方式——这才是"风格统一"真正要求的。

import QtQuick
import QtQuick.Controls.Basic

ToolTip {
    id: control

    readonly property var ui: theme ? theme.uiColors : ({})
    readonly property var metrics: theme ? theme.uiMetrics : ({})

    // A tooltip is a transient label, not a dialog: no shadow, no scrim, and it must never steal
    // focus from what it describes.
    // 提示框是瞬时标签而非对话框：没有投影、没有遮罩，并且绝不能从它所描述的东西那里抢走焦点。
    padding: control.metrics.uiPaddingX
    topPadding: 5
    bottomPadding: 5
    delay: 420
    timeout: 6000
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    // Scale from 0.96 with opacity, matching the menus: nothing appears from nothing.
    // 从 0.96 缩放加不透明度，与菜单一致：没有东西是从"无"中出现的。
    enter: Transition {
        ParallelAnimation {
            NumberAnimation {
                property: "opacity"
                from: 0.0
                to: 1.0
                duration: control.metrics.uiPressMs
                easing.type: Easing.OutCubic
            }
            NumberAnimation {
                property: "scale"
                from: 0.96
                to: 1.0
                duration: control.metrics.uiPressMs
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

    contentItem: Text {
        text: control.text
        color: control.ui.foreground
        font.pixelSize: control.metrics.uiFontSizeSm
        wrapMode: Text.NoWrap
        verticalAlignment: Text.AlignVCenter
    }

    background: Rectangle {
        radius: control.metrics.uiRadiusSm
        color: theme.surface
        border.color: control.ui.borderStrong
        border.width: 1
    }
}
