// A shadcn-style spin box, following SWB-QML-UI's `SwbSpinBox`.
//
// The default `QtQuick.Controls.Basic` spin box draws its own arrows from the style's palette, which
// this application never themes - in the settings window it showed up as a black bar with two grey
// slabs. This replaces the shell with the same surface + 1px border language as `UiTextField`, and
// the steppers become flat `−`/`+` glyph buttons that sit inside the field, so a row of numeric
// settings reads as a row of fields rather than as a row of widgets from another application.
//
// 一个 shadcn 风格数字输入框，遵循 SWB-QML-UI 的 `SwbSpinBox`。
//
// `QtQuick.Controls.Basic` 的默认 SpinBox 用样式自身的调色板绘制箭头，而本应用从未给它上色——在设置
// 窗口里它表现为一条黑底加两块灰色板。这里用与 `UiTextField` 相同的"表面 + 1px 边框"语言替换外壳，并把
// 步进器变成位于字段内部的扁平 `−`/`+` 字形按钮，使一排数字设置读起来像一排字段，而不是一排来自另一个
// 应用的控件。

import QtQuick
import QtQuick.Controls.Basic

SpinBox {
    id: control

    readonly property var ui: theme ? theme.uiColors : ({})
    readonly property var metrics: theme ? theme.uiMetrics : ({})

    implicitWidth: 140
    implicitHeight: control.metrics.uiControlHeight
    leftPadding: control.metrics.uiControlHeightSm + control.metrics.uiPaddingX
    rightPadding: control.metrics.uiControlHeightSm + control.metrics.uiPaddingX
    font.pixelSize: control.metrics.uiFontSize
    opacity: control.enabled ? 1.0 : 0.5
    editable: true

    contentItem: TextInput {
        text: control.textFromValue(control.value, control.locale)
        font: control.font
        color: control.ui.foreground
        selectionColor: control.ui.selected
        selectedTextColor: control.ui.selectedForeground
        horizontalAlignment: Qt.AlignHCenter
        verticalAlignment: Qt.AlignVCenter
        readOnly: !control.editable
        validator: control.validator
        inputMethodHints: Qt.ImhFormattedNumbersOnly
    }

    up.indicator: Rectangle {
        x: control.width - control.metrics.uiControlHeightSm
        height: parent.height - 8
        y: 4
        width: control.metrics.uiControlHeightSm
        radius: control.metrics.uiRadiusSm - 2
        // A step up the ladder on hover, nothing otherwise: the stepper should never look like a
        // filled button competing with the field it belongs to.
        // 悬停时沿阶梯上抬一级，其余时候什么都没有：步进器不应看起来像一个与所属字段争夺注意力的
        // 实心按钮。
        color: control.up.pressed ? control.ui.surface3
               : control.up.hovered ? control.ui.accent : "transparent"
        Text {
            anchors.centerIn: parent
            text: "+"
            font.pixelSize: control.metrics.uiFontSize
            color: control.up.hovered ? control.ui.foreground : control.ui.mutedForeground
        }
    }

    down.indicator: Rectangle {
        x: 4
        height: parent.height - 8
        y: 4
        width: control.metrics.uiControlHeightSm
        radius: control.metrics.uiRadiusSm - 2
        color: control.down.pressed ? control.ui.surface3
               : control.down.hovered ? control.ui.accent : "transparent"
        Text {
            anchors.centerIn: parent
            text: "\u2212"
            font.pixelSize: control.metrics.uiFontSize
            color: control.down.hovered ? control.ui.foreground : control.ui.mutedForeground
        }
    }

    background: Rectangle {
        implicitHeight: control.metrics.uiControlHeight
        radius: control.metrics.uiRadius
        color: control.ui.surface1
        border.color: control.activeFocus ? control.ui.ring : control.ui.border
        border.width: 1
        Behavior on border.color { ColorAnimation { duration: control.metrics.uiAnimationMs } }
    }
}
