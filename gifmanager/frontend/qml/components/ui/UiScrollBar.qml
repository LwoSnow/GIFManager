// A shadcn Base UI scroll bar, adapted from SWB-QML-UI's `SwbScrollBar`.
//
// Follows `components/SwbScrollBar.qml`: a 1px inset track, a thumb whose radius is half its
// thickness so both orientations round correctly, and a colour shift on hover or drag. The thumb
// hides itself when the content already fits, which is what makes an overflowing list visibly
// different from a list that happens to be short.
//
// 一个 shadcn Base UI 风格滚动条，适配自 SWB-QML-UI 的 `SwbScrollBar`。
//
// 遵循 `components/SwbScrollBar.qml`：1px 内缩轨道；滑块圆角取其厚度的一半，使两个方向都能正确圆角；
// 悬停或拖拽时变色。内容装得下时滑块自我隐藏，这正是"溢出的列表"与"恰好很短的列表"看上去不同的原因。

import QtQuick
import QtQuick.Controls.Basic

ScrollBar {
    id: control

    readonly property var ui: theme ? theme.uiColors : ({})
    readonly property var metrics: theme ? theme.uiMetrics : ({})

    // A 1px inset keeps the thumb off the very edge of the view it belongs to.
    // 1px 内缩使滑块不贴住所属视图的最边缘。
    padding: 1
    // A tiny scroll range would otherwise produce an unusable sliver of a thumb.
    // 极小的滚动范围否则会产生一个无法使用的细条滑块。
    minimumSize: 0.1

    contentItem: Rectangle {
        implicitWidth: 8
        implicitHeight: 8
        radius: Math.min(width, height) / 2
        color: (control.hovered || control.pressed)
               ? control.ui.mutedForeground
               : control.ui.border
        // Hidden when everything fits. `size` is the visible fraction of the content.
        // 内容装得下时隐藏。`size` 是内容可见部分的比例。
        visible: control.size < 1.0
        Behavior on color { ColorAnimation { duration: control.metrics.uiAnimationMs } }
    }
}
