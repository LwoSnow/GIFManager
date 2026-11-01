// A shadcn Base UI button, adapted from SWB-QML-UI's `SwbButton`.
//
// # Provenance
//
// SWB-QML-UI (MIT) restyles all 51 `QtQuick.Controls.Basic` controls into the shadcn Base UI look
// through a compiled C++/CMake QML module. PySide6 does not ship Qt's CMake package, so
// `find_package(Qt6)` cannot succeed and that plugin cannot be built here without a full Qt SDK.
// This is therefore a PORT of the design, not a link against it: the variant set, the size set, the
// 1px reserved border, the outer focus ring and the 150 ms colour transition all follow
// `components/SwbButton.qml`.
//
// The colours and metrics come from the `ui*` tokens on our theme bridge, which transcribe SWB's
// `SwbPalette` and `SwbTheme` verbatim (see `theme.SHADCN_PALETTES`).
//
// 一个 shadcn Base UI 风格按钮，适配自 SWB-QML-UI 的 `SwbButton`。
//
// # 出处
//
// SWB-QML-UI（MIT）通过一个编译型 C++/CMake QML 模块把全部 51 个 `QtQuick.Controls.Basic` 控件
// 重塑为 shadcn Base UI 外观。PySide6 不附带 Qt 的 CMake 包，因此 `find_package(Qt6)` 无法成功，
// 不安装完整 Qt SDK 就无法在此构建该插件。所以这里是设计的"移植"而非对它链接：变体集合、尺寸
// 集合、预留的 1px 边框、外层聚焦环与 150 毫秒颜色过渡都遵循 `components/SwbButton.qml`。
//
// 颜色与度量来自我们主题桥上的 `ui*` 令牌，它们逐字抄录了 SWB 的 `SwbPalette` 与 `SwbTheme`
//（见 `theme.SHADCN_PALETTES`）。

import QtQuick
import QtQuick.Controls.Basic

Button {
    id: control

    // `default | selected | destructive | outline | secondary | ghost | link`.
    //
    // `selected` is the addition that makes the low-contrast palette work: it is the ONLY variant
    // with a high-contrast fill, so "this one is active" is expressed by contrast while every
    // other control stays a few percent away from the window. Without it a low-contrast design has
    // no way to say which of several buttons is the current one.
    // `default | selected | destructive | outline | secondary | ghost | link`。
    //
    // `selected` 是让低对比调色板成立的那个补充：它是"唯一"带高对比填充的变体，于是"当前是它"
    // 由对比度表达，而其他所有控件都与窗口只差几个百分点。没有它，低对比设计就无法说明多个按钮中
    // 哪一个是当前项。
    property string variant: "default"

    // `sm | default | lg`, exactly SWB's set.
    // 与 SWB 完全相同的尺寸集合。
    property string size: "default"

    readonly property var ui: theme ? theme.uiColors : ({})
    readonly property var metrics: theme ? theme.uiMetrics : ({})

    // Resolved fill per variant: a single step up the elevation ladder per state, so the STATE is
    // read as a contrast delta rather than as a colour change.
    // 按变体解析出的填充色：每个状态在抬升阶梯上走一级，于是状态被读作对比度差值而非颜色变化。
    readonly property color bgColor: {
        var c = control.ui
        switch (variant) {
        // The one high-contrast variant.
        // 唯一的高对比变体。
        case "selected":    return c.selected
        case "destructive": return control.pressed ? c.destructiveBgHover
                              : control.hovered ? c.destructiveBgHover : c.destructiveBg
        case "secondary":   return control.pressed ? c.surface3
                              : control.hovered ? c.secondaryHover : c.secondary
        case "outline":     return control.pressed ? c.surface2
                              : control.hovered ? c.accent : "transparent"
        case "ghost":       return control.pressed ? c.surface2
                              : control.hovered ? c.accent : "transparent"
        case "link":        return "transparent"
        default:            return control.pressed ? c.primaryHover
                              : control.hovered ? c.primaryHover : c.primary
        }
    }

    readonly property color textColor: {
        var c = control.ui
        switch (variant) {
        case "selected":    return c.selectedForeground
        case "destructive": return c.destructive
        case "secondary":   return c.secondaryForeground
        case "outline":
        case "ghost":       return c.foreground
        case "link":        return c.foreground
        default:            return c.primaryForeground
        }
    }

    readonly property int resolvedHeight: size === "sm"
                                          ? control.metrics.uiControlHeightSm
                                          : size === "lg"
                                            ? control.metrics.uiControlHeightLg
                                            : control.metrics.uiControlHeight
    readonly property int resolvedRadius: size === "sm"
                                          ? control.metrics.uiRadiusSm
                                          : control.metrics.uiRadius

    horizontalPadding: control.metrics.uiPaddingX
    verticalPadding: 0
    hoverEnabled: true
    font.pixelSize: size === "sm" ? control.metrics.uiFontSizeSm : control.metrics.uiFontSize
    font.weight: Font.Medium
    font.underline: control.variant === "link" && control.hovered
    // A disabled control is dimmed rather than hidden, so its label still explains what is
    // unavailable - SWB's choice, and the right one for a settings dialog.
    // 禁用的控件是变暗而不是隐藏，使它的文字仍能说明什么不可用——这是 SWB 的选择，对设置对话框
    // 而言也是正确的。
    opacity: control.enabled ? 1.0 : 0.5

    // Press feedback, on the press rather than on the release.
    //
    // Apple's "respond on pointer-down, not on release" and Kowalski's `scale(0.97)` on `:active`
    // are the same rule: the interface must acknowledge the press at the instant it happens, or it
    // feels dead. 0.97 is subtle on purpose - enough to feel, not enough to distract - and only
    // `scale` animates, so nothing here can trigger a layout pass.
    //
    // 按压反馈，作用在"按下"而不是"松开"。
    //
    // Apple 的"在按下时响应而不是松开时"与 Kowalski 在 `:active` 上用 `scale(0.97)` 是同一条规则：
    // 界面必须在按下的瞬间确认这次按压，否则会显得死板。0.97 刻意轻微——足以感觉到，不足以分散注意
    // ——并且只有 `scale` 参与动画，因此这里不可能触发布局。
    scale: control.pressed && control.enabled ? 0.97 : 1.0
    Behavior on scale {
        NumberAnimation {
            duration: control.metrics.uiPressMs
            easing.type: Easing.OutCubic
        }
    }

    contentItem: Text {
        text: control.text
        font: control.font
        color: control.textColor
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        visible: control.text !== ""
        // Colour and opacity only, both of which are cheap and non-layout.
        // 只动颜色与不透明度，两者都廉价且不触发布局。
        Behavior on color { ColorAnimation { duration: control.metrics.uiAnimationMs } }
    }

    background: Rectangle {
        implicitHeight: control.resolvedHeight
        radius: control.resolvedRadius
        color: control.bgColor
        // A 1px border is RESERVED on every variant and only revealed for outline and selected, so
        // switching variants does not change the control's width by two pixels.
        // 每个变体都"预留" 1px 边框，只在 outline 与 selected 上显现，使切换变体不会改变控件宽度
        // 两个像素。
        border.color: control.variant === "outline"
                      ? control.ui.border
                      : control.variant === "selected"
                        ? control.ui.selected : "transparent"
        border.width: 1
        Behavior on color { ColorAnimation { duration: control.metrics.uiAnimationMs } }

        // The focus ring sits OUTSIDE the control, which is why it uses negative margins and a
        // matching radius; drawn inside it would eat the border.
        // 聚焦环位于控件"外部"，因此使用负外边距与匹配的圆角；画在内部会吃掉边框。
        Rectangle {
            anchors.fill: parent
            anchors.margins: -control.metrics.uiFocusRingWidth
            radius: parent.radius + control.metrics.uiFocusRingWidth
            color: "transparent"
            border.color: control.ui.focusRing
            border.width: control.metrics.uiFocusRingWidth
            visible: control.visualFocus
        }
    }
}
