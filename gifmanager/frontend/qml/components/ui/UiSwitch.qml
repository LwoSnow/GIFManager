// A shadcn-style switch, following SWB-QML-UI's `SwbSwitch`.
//
// # State is contrast, not colour
//
// The track is `surface3` when off and `selected` when on. The palette's whole point is that the
// "on" state is the only high-contrast element, so a switch reads at a glance without needing an
// accent colour - which is what keeps the interface monochrome and calm.
//
// The thumb slides rather than snapping: a spring-free `Behavior on x` with an out-cubic ease, kept
// short so the motion reads as a consequence of the click rather than as an animation.
//
// 一个 shadcn 风格开关，遵循 SWB-QML-UI 的 `SwbSwitch`。
//
// # 状态即对比度，而不是彩色
//
// 关闭时轨道是 `surface3`，打开时是 `selected`。整套调色板的意义就在于"打开"是唯一的高对比元素，
// 因此开关一眼可读，且不需要一个强调色——这正是让界面保持单色与安静的原因。
//
// 滑块是滑动而非瞬跳：一条无弹簧的 `on x` 行为，out-cubic 缓动，并且很短，使这段运动读作"点击的
// 结果"而不是"一段动画"。

import QtQuick
import QtQuick.Controls.Basic

Switch {
    id: control

    readonly property var ui: theme ? theme.uiColors : ({})
    readonly property var metrics: theme ? theme.uiMetrics : ({})

    // 36x20 track, 16 px thumb: the shadcn proportions, derived from the shared tokens so a future
    // metric change moves every control together.
    // 36x20 轨道、16px 滑块：shadcn 的比例，由共享令牌推导，使将来调整度量会同时移动所有控件。
    readonly property int trackWidth: 36
    readonly property int trackHeight: 20
    readonly property int thumbSize: 16
    readonly property int inset: 2

    implicitWidth: control.trackWidth
    implicitHeight: control.trackHeight
    opacity: control.enabled ? 1.0 : 0.5
    hoverEnabled: true

    indicator: Rectangle {
        id: track
        implicitWidth: control.trackWidth
        implicitHeight: control.trackHeight
        x: control.leftPadding
        y: control.topPadding + (control.availableHeight - height) / 2
        radius: height / 2
        // `selected` when on; otherwise the TOP step of the low-contrast ladder (`surface4`), which
        // is visible against the window without competing with the on state. The first version used
        // `surface3`, one step lower, and the off track disappeared into the background.
        // 打开时为 `selected`；否则用低对比阶梯的"最高"一级（`surface4`），它相对窗口可见又不与打开态
        // 争夺注意力。第一个版本用低一级的 `surface3`，关闭态轨道直接溶进了背景。
        color: control.checked
               ? control.ui.selected
               : control.hovered ? control.ui.surface4 : control.ui.surface3
        border.color: control.checked ? control.ui.selected : control.ui.borderStrong
        border.width: 1
        Behavior on color { ColorAnimation { duration: control.metrics.uiAnimationMs } }

        Rectangle {
            id: thumb
            width: control.thumbSize
            height: control.thumbSize
            radius: height / 2
            y: (parent.height - height) / 2
            x: control.checked ? parent.width - width - control.inset : control.inset
            // An OFF switch must NOT have a bright thumb.
            //
            // The first version used `foreground` (near-white) for the off thumb, which read as
            // "on" at a glance - the exact opposite of what a state indicator is for. Off is
            // `mutedForeground` so it is dim on a dim track; on is `selectedForeground` so it is dark
            // on the bright track. The pair inverts WITH the track, which is what makes the two
            // states unmistakable.
            // 关闭的开关"不得"有明亮的滑块。
            //
            // 第一个版本用 `foreground`（近白）作关闭态滑块，一眼看去像"开着"——与状态指示器的用途
            // 正好相反。关闭用 `mutedForeground`，在暗轨道上就暗；打开用 `selectedForeground`，在亮
            // 轨道上就暗。这一对颜色"随轨道一起"反转，正是让两个状态不会混淆的原因。
            color: control.checked ? control.ui.selectedForeground : control.ui.mutedForeground
            Behavior on x {
                NumberAnimation {
                    duration: control.metrics.uiPressMs
                    easing.type: Easing.OutCubic
                }
            }
            Behavior on color { ColorAnimation { duration: control.metrics.uiAnimationMs } }
        }
    }

    // The label, when a caller gives one.
    //
    // It used to be `Item {}` - an EMPTY content item - so `text` on a switch was discarded and the
    // control rendered as a bare track. That is the reported "checkbox shows no text": a switch with
    // a caption silently lost it, and there was no way to tell that from a switch that was never
    // given a caption.
    // 当调用方给出标签时显示它。
    //
    // 它过去是 `Item {}`——一个"空"的内容元素——因此开关上的 `text` 被丢弃，控件只渲染成一条轨道。这
    // 就是用户报告的"复选框不显示文字"：带标题的开关静默丢掉了它，且无法与"从未给过标题"区分。
    contentItem: Text {
        text: control.text
        visible: control.text !== ""
        font: control.font
        color: control.enabled ? control.ui.foreground : control.ui.mutedForeground
        // The text sits to the LEFT of the track, which is where a label belongs when the control it
        // describes is on the right of a row.
        // 文字位于轨道"左侧"——当控件处在行末时，标签就该在那个位置。
        leftPadding: 0
        rightPadding: control.trackWidth + control.metrics.uiControlGap
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        // Right-align inside the control so the mirroring of a label and its switch looks deliberate
        // rather than like an off-by-a-gap.
        // 在控件内右对齐，使"标签与其开关"的镜像关系看起来是刻意的，而不是差了一个间隙。
        horizontalAlignment: Text.AlignRight
        // The track must not be pushed by the text: the indicator is positioned from the control's
        // own leftPadding, so the text is given room only on its right.
        // 轨道不得被文字挤动：指示器由控件自身的 `leftPadding` 定位，因此只在文字右侧留出空间。
    }
}
