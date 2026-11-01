// A shadcn-style menu separator, following SWB-QML-UI's `SwbMenuSeparator`.
//
// The Basic style draws its separator from `palette.mid`, which this application never themed — so a
// separator either vanished or drew a bright line in the wrong colour once the menu's palette
// overrides were removed. This draws it from the `border` token instead, so it belongs to the same
// material as the menu's own edge.
//
// 一个 shadcn 风格菜单分隔线，遵循 SWB-QML-UI 的 `SwbMenuSeparator`。
//
// Basic 样式用 `palette.mid` 绘制分隔线，而本应用从未给它上色——因此一旦移除菜单的调色板覆写，分隔线
// 要么消失、要么用错误的颜色画出一条亮线。这里改用 `border` 令牌绘制，使它属于与菜单自身边缘同一种材料。

import QtQuick
import QtQuick.Controls.Basic

MenuSeparator {
    id: control

    readonly property var ui: theme ? theme.uiColors : ({})
    readonly property var metrics: theme ? theme.uiMetrics : ({})

    // `padding` on a separator is what gives it vertical breathing room; without it the line touches
    // both neighbouring rows.
    // 分隔线上的 `padding` 就是它上下留白；缺了它，这条线会紧贴相邻两行。
    padding: control.metrics.uiControlGap - 2
    leftPadding: 0
    rightPadding: 0
    implicitHeight: 1 + 2 * control.padding

    contentItem: Rectangle {
        implicitHeight: 1
        color: control.ui.border
    }
}
