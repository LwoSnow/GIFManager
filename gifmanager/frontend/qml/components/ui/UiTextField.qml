// A shadcn Base UI text field, adapted from SWB-QML-UI's `SwbTextField`.
//
// Follows `components/SwbTextField.qml`: a transparent fill with a 1px border that switches to the
// ring colour on focus, plus the outer focus ring. The right-click editing menu is deliberately not
// ported — our fields are single-line search and name inputs, and SWB's context menu is a 6.8 KB
// component that would add behaviour nobody asked for.
//
// 一个 shadcn Base UI 风格文本框，适配自 SWB-QML-UI 的 `SwbTextField`。
//
// 遵循 `components/SwbTextField.qml`：透明填充 + 1px 边框，聚焦时边框变为 ring 色，外加外层聚焦环。
// 刻意不移植右键编辑菜单——我们的字段是单行搜索与名称输入，而 SWB 的右键菜单是一个 6.8 KB 的组件，
// 会引入没人要求的行为。

import QtQuick
import QtQuick.Controls.Basic

TextField {
    id: control

    readonly property var ui: theme ? theme.uiColors : ({})
    readonly property var metrics: theme ? theme.uiMetrics : ({})

    implicitWidth: 200
    implicitHeight: control.metrics.uiControlHeight
    leftPadding: control.metrics.uiPaddingX
    rightPadding: control.metrics.uiPaddingX
    topPadding: 0
    bottomPadding: 0
    verticalAlignment: TextInput.AlignVCenter
    font.pixelSize: control.metrics.uiFontSize
    color: control.ui.foreground
    placeholderTextColor: control.ui.mutedForeground
    // Selection uses the PRIMARY colour with its own foreground, which is what keeps the selected
    // text readable in dark mode - the primary is light there and the foreground dark.
    // 选中态用"主色"配它自己的前景色，这正是深色模式下选中文字仍可读的原因——那里主色是浅的、
    // 前景是深的。
    selectionColor: control.ui.primary
    selectedTextColor: control.ui.primaryForeground
    opacity: control.enabled ? 1.0 : 0.5
    selectByMouse: true

    background: Rectangle {
        implicitWidth: 200
        implicitHeight: control.metrics.uiControlHeight
        radius: control.metrics.uiRadius
        color: "transparent"
        border.color: control.activeFocus ? control.ui.ring : control.ui.border
        border.width: 1
        Behavior on border.color { ColorAnimation { duration: control.metrics.uiAnimationMs } }

        // Focus ring, outside the field.
        // 聚焦环，位于字段外部。
        Rectangle {
            anchors.fill: parent
            anchors.margins: -control.metrics.uiFocusRingWidth
            radius: parent.radius + control.metrics.uiFocusRingWidth
            color: "transparent"
            border.color: control.ui.focusRing
            border.width: control.metrics.uiFocusRingWidth
            visible: control.activeFocus
        }
    }

    // No context menu.
    //
    // Qt gives a text field the standard Undo/Redo/Cut/Copy/Paste/Delete/Select All menu on right
    // click. That menu is styled by `QtQuick.Controls.Basic` - it cannot be themed from QML - so it
    // appeared as a black panel with a white frame amid an interface that had just been unified, and
    // it offered nothing this application needs (the fields here hold short names or a hint string,
    // and selection still works through dragging).
    //
    // `acceptedButtons: Qt.RightButton` is the whole trick: the handler takes ONLY right clicks, so
    // left clicks pass straight through to the field and editing, selection and the caret are
    // untouched. Declared last so it sits above the field's own content item, which is what receives
    // the right click and opens the menu.
    // 不显示上下文菜单。
    //
    // Qt 会给文本字段提供标准的撤销/重做/剪切/复制/粘贴/删除/全选右键菜单。该菜单由
    // `QtQuick.Controls.Basic` 绘制——无法从 QML 上色——因此它表现为一块黑底白框的面板，出现在刚刚
    // 统一过风格的界面里，而且它并不提供本应用需要的东西（这里的字段装的是短名称或提示字符串，选择
    // 仍然可以拖动完成）。
    //
    // `acceptedButtons: Qt.RightButton` 就是全部技巧：该处理器"只"接管右键，因此左键直接穿过到字段，
    // 编辑、选择与光标都不受影响。声明在最后，使它位于字段自身的内容元素之上——而正是那个元素接收右键
    // 并打开菜单。
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.RightButton
        onPressed: function (mouse) { mouse.accepted = true }
    }
}
