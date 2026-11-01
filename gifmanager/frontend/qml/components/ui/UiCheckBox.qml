// A shadcn-style checkbox, following SWB-QML-UI's `SwbCheckBox`.
//
// Checked state uses `selected` (the palette's only high-contrast fill) with `selectedForeground`
// for the tick, and an unchecked box is a `surface1` square with a `border`. The tick is drawn with
// two rectangles rotated inside a clipped item rather than a bundled glyph, so it needs no font and
// scales with the control.
//
// 一个 shadcn 风格复选框，遵循 SWB-QML-UI 的 `SwbCheckBox`。
//
// 选中态用 `selected`（调色板唯一的高对比填充），勾为 `selectedForeground`；未选中是带 `border`
// 的 `surface1` 方块。勾由两个矩形在裁剪元素内旋转绘制而不是内置字形，因此不依赖字体并随控件缩放。

import QtQuick
import QtQuick.Controls.Basic

CheckBox {
    id: control

    readonly property var ui: theme ? theme.uiColors : ({})
    readonly property var metrics: theme ? theme.uiMetrics : ({})

    readonly property int boxSize: control.metrics.uiIconSize
    readonly property int gap: control.metrics.uiControlGap

    implicitHeight: control.metrics.uiControlHeightSm
    leftPadding: control.boxSize + control.gap
    opacity: control.enabled ? 1.0 : 0.5
    hoverEnabled: true
    font.pixelSize: control.metrics.uiFontSizeSm
    palette.windowText: control.ui.foreground

    indicator: Rectangle {
        id: box
        x: control.leftPadding
        y: (control.height - height) / 2
        width: control.boxSize
        height: control.boxSize
        radius: control.metrics.uiRadiusSm - 2
        color: control.checked
               ? control.ui.selected
               : control.hovered ? control.ui.surface3 : control.ui.surface1
        border.color: control.checked
                      ? control.ui.selected
                      : control.hovered ? control.ui.borderStrong : control.ui.border
        border.width: 1
        Behavior on color { ColorAnimation { duration: control.metrics.uiAnimationMs } }

        // The tick: two bars, the long one rotated 45 degrees and the short one -45, clipped to the
        // box so nothing spills. Visible only when checked, and it fades in with the fill rather
        // than popping, because a tick that appears from nothing reads as a glitch.
        // 勾：两条短杠，长杠旋转 45 度、短杠 -45 度，裁剪在方框内使任何东西都不外溢。仅在选中时可见，
        // 并且随填充一起淡入而不是突然出现，因为"从无到有"的勾读起来像故障。
        Item {
            anchors.fill: parent
            anchors.margins: 3
            clip: true
            opacity: control.checked ? 1.0 : 0.0
            Behavior on opacity { NumberAnimation { duration: control.metrics.uiPressMs } }

            Rectangle {
                width: parent.width * 0.62
                height: 2
                radius: 1
                color: control.ui.selectedForeground
                anchors.verticalCenter: parent.verticalCenter
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.verticalCenterOffset: 1
                rotation: -45
            }
            Rectangle {
                width: parent.width * 0.34
                height: 2
                radius: 1
                color: control.ui.selectedForeground
                x: parent.width * 0.14
                y: parent.height * 0.52
                rotation: 45
            }
        }
    }

    contentItem: Text {
        text: control.text
        font: control.font
        color: control.enabled ? control.ui.foreground : control.ui.mutedForeground
        leftPadding: control.indicator.width + (control.text ? control.gap : 0)
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
}
