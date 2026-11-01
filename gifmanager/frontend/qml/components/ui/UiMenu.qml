// A shadcn-style menu, following SWB-QML-UI's `SwbMenu`.
//
// # Why a component rather than `palette` overrides
//
// The context menus used to be themed by assigning `palette.window`, `palette.windowText`,
// `palette.highlight` and `palette.highlightedText` — with `highlight` set to `theme.accent`, the
// legacy BLUE. That is why the right-click menu looked like it belonged to a different application
// than the buttons around it: a custom `background` collapses the menu width to zero on Qt 6.11
// Basic (measured earlier in this file's history), so the only lever was the palette, and the palette
// is exactly where the old colours were.
//
// This component draws its own surface instead, so the menu shares the token language with every
// other control: `popover` fill, `borderStrong` edge, `uiRadius`, and a `selected`-free hover step.
//
// 一个 shadcn 风格菜单，遵循 SWB-QML-UI 的 `SwbMenu`。
//
// # 为什么用组件而不是覆写 `palette`
//
// 右键菜单过去靠设置 `palette.window`、`palette.windowText`、`palette.highlight` 与
// `palette.highlightedText` 着色——其中 `highlight` 用的是 `theme.accent`，也就是旧的"蓝色"。这正是
// 右键菜单看起来像另一个应用的原因：自定义 `background` 会在 Qt 6.11 Basic 上把菜单宽度压成 0
// （本文件历史中实测过），因此唯一的杠杆就是调色板，而调色板恰恰装着旧颜色。
//
// 本组件改为自绘表面，使菜单与其他所有控件共用同一套令牌语言：`popover` 填充、`borderStrong` 边、
// `uiRadius`，以及不带 `selected` 的悬停台阶。

import QtQuick
import QtQuick.Controls.Basic

Menu {
    id: control

    readonly property var ui: theme ? theme.uiColors : ({})
    readonly property var metrics: theme ? theme.uiMetrics : ({})

    // `padding` and `spacing` are what keep items off the menu's own edge; without them the first
    // row sits flush against the border and the surface reads as a list rather than a panel.
    // `padding` 与 `spacing` 让条目离开菜单自身的边缘；缺了它们，第一行会紧贴边框，表面读起来像
    // 一个列表而不是一块面板。
    padding: 4
    spacing: 1
    implicitWidth: 180

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
        radius: control.metrics.uiRadius
        color: theme.surface
        border.color: control.ui.borderStrong
        border.width: 1
    }
}
