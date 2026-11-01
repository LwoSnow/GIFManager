// A shadcn-style menu item, following SWB-QML-UI's `SwbMenuItem`.
//
// Overrides only `background` and the text colour, so Qt keeps handling activation, mnemonics and
// keyboard navigation. Hover is a single step up the elevation ladder — no accent colour, no blue —
// because a menu row highlighted in a different hue from the rest of the interface is the exact
// inconsistency this component exists to remove.
//
// 一个 shadcn 风格菜单条目，遵循 SWB-QML-UI 的 `SwbMenuItem`。
//
// 只覆写 `background` 与文字颜色，使 Qt 继续处理激活、助记键与键盘导航。悬停是抬升阶梯上的一级——
// 没有强调色、没有蓝色——因为一个用与界面其余部分不同色相高亮的菜单行，正是本组件要消除的那种不一致。

import QtQuick
import QtQuick.Controls.Basic

MenuItem {
    id: control

    readonly property var ui: theme ? theme.uiColors : ({})
    readonly property var metrics: theme ? theme.uiMetrics : ({})

    implicitHeight: control.metrics.uiControlHeightSm
    leftPadding: control.metrics.uiPaddingX
    rightPadding: control.metrics.uiPaddingX

    // `palette` rather than a `contentItem`, for the same reason as `UiComboBox`: Qt's own logic
    // resolves the shortcut text and the mnemonic underline, and re-implementing the label loses both.
    //
    // Both roles bind to ONE computed value: assigning `palette.text: palette.windowText` looks
    // natural and produces `QML Palette: Binding loop detected`, because the two roles are
    // independent properties that each re-emit.
    // 用 `palette` 而不是 `contentItem`，理由与 `UiComboBox` 相同：Qt 自身的逻辑负责快捷键文字与助记键
    // 下划线，重写标签会把两者都丢掉。
    //
    // 两个角色都绑定到"同一个"计算值：写成 `palette.text: palette.windowText` 看起来自然，却会产生
    // `QML Palette: Binding loop detected`，因为这两个角色是各自会重新发出的独立属性。
    readonly property color ink: control.enabled ? control.ui.foreground
                                                : control.ui.mutedForeground
    palette.windowText: control.ink
    palette.text: control.ink

    background: Rectangle {
        radius: control.metrics.uiRadiusSm - 2
        color: control.highlighted ? control.ui.accent : "transparent"
    }
}
