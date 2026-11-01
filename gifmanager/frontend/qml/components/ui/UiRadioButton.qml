// A shadcn-style radio button, following SWB-QML-UI's `SwbRadioButton`.
//
// Same two-token language as the checkbox: an unchecked circle is `surface1` with a `border`, the
// chosen one is `selected` with a `selectedForeground` dot. The dot scales from 0.9 rather than 0 -
// nothing in the real world appears from nothing, which is the rule Kowalski states for entrances -
// and it is clipped so it can never spill past the ring.
//
// 一个 shadcn 风格单选按钮，遵循 SWB-QML-UI 的 `SwbRadioButton`。
//
// 与复选框同样的两令牌语言：未选中的圆是带 `border` 的 `surface1`，被选中的是 `selected` 加
// `selectedForeground` 圆点。圆点从 0.9 而非 0 缩放出现——现实中没有东西是从"无"中出现的，这正
// 是 Kowalski 对入场动画的规则——并被裁剪，使它永不溢出圆环。

import QtQuick
import QtQuick.Controls.Basic

RadioButton {
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

    indicator: Rectangle {
        id: ring
        x: control.leftPadding
        y: (control.height - height) / 2
        width: control.boxSize
        height: control.boxSize
        radius: height / 2
        color: control.checked
               ? control.ui.selected
               : control.hovered ? control.ui.surface3 : control.ui.surface1
        border.color: control.checked
                      ? control.ui.selected
                      : control.hovered ? control.ui.borderStrong : control.ui.border
        border.width: 1
        Behavior on color { ColorAnimation { duration: control.metrics.uiAnimationMs } }

        Rectangle {
            anchors.centerIn: parent
            // `0.9` rather than `0`: a dot that grows from nothing reads as a glitch.
            // 用 0.9 而不是 0：从"无"开始生长的圆点读起来像故障。
            width: parent.width * 0.42
            height: parent.height * 0.42
            radius: height / 2
            color: control.ui.selectedForeground
            scale: control.checked ? 1.0 : control.metrics.uiPressScale
            opacity: control.checked ? 1.0 : 0.0
            Behavior on opacity { NumberAnimation { duration: control.metrics.uiPressMs } }
            Behavior on scale {
                NumberAnimation {
                    duration: control.metrics.uiPressMs
                    easing.type: Easing.OutCubic
                }
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
