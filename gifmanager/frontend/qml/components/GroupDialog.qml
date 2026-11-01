// Group management: create, rename and delete a group.
//
// One dialog for all three because they share everything that matters: a name field,
// a validation message, and a primary button whose label and meaning change. Three
// near-identical dialogs would mean three places to fix a validation rule.
//
// 分组管理：新建、重命名、删除分组。
//
// 三合一，因为它们共享一切要紧的东西：一个名称字段、一条校验消息，以及一个标签与含义会变的
// 主按钮。三个几乎相同的对话框意味着三处需要修正同一条校验规则。

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "./ui"
import "../components/ui"

UiDialog {
    // Item 型弹窗：在场景内绘制。无边框工具窗口上 Window 型原生弹窗不显示。
    // Item-type popup: rendered inside the scene, because a Window-type
    // native popup does not show on a frameless tool window.
    id: groupDialog

    required property var app

    // "create" | "rename" | "delete" /
    // "create" | "rename" | "delete"
    property string mode: "create"

    anchors.centerIn: parent
    modal: true
    width: Math.min(420, parent ? parent.width - 60 : 400)
    standardButtons: Dialog.NoButton
    closePolicy: Popup.CloseOnEscape

    // The group being renamed or deleted. -1 in create mode.
    // 正在重命名或删除的分组。新建模式下为 -1。
    property int targetId: -1
    // Cached so a delete confirmation can say how much is lost without a second call
    // whose answer could differ from the one the dialog was opened with.
    // 缓存起来，使删除确认能说明损失多少，而无需第二次调用——其答案可能与打开对话框时的不同。
    property int targetCount: 0
    property bool targetBuiltin: false
    property string targetName: ""
    // The message from the last refusal, shown under the field.
    // 上次拒绝的消息，显示在字段下方。
    property string errorMessage: ""
    // Whether the chosen group type is text (create mode only).
    // 所选分组类型是否为文字（仅新建模式）。
    property bool textType: false

    readonly property bool deleting: groupDialog.mode === "delete"
    readonly property bool creating: groupDialog.mode === "create"

    function openCreate(forTextType) {
        mode = "create"
        targetId = -1
        targetName = ""
        targetCount = 0
        targetBuiltin = false
        errorMessage = ""
        textType = false
        // The type is INFERRED, not asked. The "+" button opens this dialog directly (the
        // old two-entry menu was removed), so there is no caller to name a type and the
        // in-dialog radio buttons were removed with it.
        //
        // Matching the type of the group the user is LOOKING at is the useful guess: while
        // browsing image stickers, a new group is almost always another image group. With no
        // type showing (the "All" view) it falls back to an image group, which is what the
        // import path needs.
        //
        // `forTextType` is still accepted so an existing caller that passes one keeps
        // working; it is simply no longer how the choice is made.
        // 类型是"推断"的而不是询问的。"+"按钮直接打开本对话框（旧的两项菜单已移除），因此没有调用方
        // 来指定类型，对话框内的单选按钮也随之移除。
        //
        // 匹配用户"正在看"的分组类型是有用的猜测：在浏览图片贴纸时，新建的分组几乎总是另一个图片
        // 分组。没有类型在显示时（"全部"视图）回退到图片分组，那正是导入路径需要的。
        //
        // 仍接受 `forTextType`，使传入它的既有调用方继续可用；它只是不再决定该选择。
        if (forTextType === true || forTextType === false) {
            textType = forTextType
        } else {
            textType = groupDialog.app.currentGroupType() === "text"
        }
        nameField.text = ""
        open()
        nameField.forceActiveFocus()
    }

    function openRename(groupId) {
        var info = groupDialog.app.groupInfo(groupId)
        if (!info.exists)
            return
        mode = "rename"
        targetId = groupId
        targetName = info.name
        targetCount = info.count
        targetBuiltin = info.builtin
        errorMessage = ""
        nameField.text = info.name
        open()
        nameField.forceActiveFocus()
        nameField.selectAll()
    }

    function openDelete(groupId) {
        var info = groupDialog.app.groupInfo(groupId)
        if (!info.exists)
            return
        mode = "delete"
        targetId = groupId
        targetName = info.name
        targetCount = info.count
        targetBuiltin = info.builtin
        errorMessage = ""
        open()
    }

    function submit() {
        var result
        if (deleting)
            result = groupDialog.app.deleteGroup(targetId)
        else if (creating)
            result = groupDialog.app.createGroup(nameField.text,
                                                 textType ? "text" : "image")
        else
            result = groupDialog.app.renameGroup(targetId, nameField.text)

        if (result.ok) {
            groupDialog.close()
            groupDialog.app.showStatus(result.message, 2500)
            return
        }
        // A refusal stays in the dialog so the user can correct the name instead of
        // having to reopen it and retype.
        // 拒绝会留在对话框里，使用户能改正名称，而不必重新打开并重输。
        groupDialog.errorMessage = result.message
    }

    title: deleting ? groupDialog.app.trE("group_delete_title", groupDialog.app.languageEpoch)
                    : (creating ? groupDialog.app.trE("group_new", groupDialog.app.languageEpoch)
                                : groupDialog.app.trE("group_rename", groupDialog.app.languageEpoch))

    contentItem: ColumnLayout {
        spacing: theme.spacing

        // ---- delete confirmation ------------------------------------------
        Label {
            Layout.fillWidth: true
            visible: groupDialog.deleting
            text: groupDialog.targetBuiltin
                  ? groupDialog.app.trE("group_builtin_locked", groupDialog.app.languageEpoch)
                  : groupDialog.app.trArgsE(
                        "group_delete_confirm",
                        JSON.stringify({
                            name: groupDialog.targetName,
                            count: groupDialog.targetCount
                        }), groupDialog.app.languageEpoch)
            color: groupDialog.targetBuiltin ? theme.danger : theme.text
            font.pixelSize: theme.fontSizeBody
            wrapMode: Text.WordWrap
        }

        // ---- type selector (create mode) ----------------------------------
        //
        // The group bar's "+" opens this dialog DIRECTLY, so the type — which the
        // old flow chose in a popup menu — is chosen here, where it belongs.
        // 分组栏的“＋”直接打开本对话框，因此类型——旧流程在弹出菜单里选择——就在
        // 它所属的地方选择。
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.spacing
            visible: groupDialog.creating

            Label {
                text: groupDialog.app.tr("group_type")
                color: theme.text
                font.pixelSize: theme.fontSizeBody
            }

            UiRadioButton {
                id: typeImage
                text: groupDialog.app.tr("new_image_group")
                checked: !groupDialog.textType
                onCheckedChanged: if (checked) groupDialog.textType = false
            }

            UiRadioButton {
                id: typeText
                text: groupDialog.app.tr("new_text_group")
                checked: groupDialog.textType
                onCheckedChanged: if (checked) groupDialog.textType = true
            }
        }

        // ---- name field ---------------------------------------------------
        ColumnLayout {
            Layout.fillWidth: true
            spacing: theme.spacingTight
            visible: !groupDialog.deleting

            Label {
                text: groupDialog.creating
                      ? groupDialog.app.trE("group_name", groupDialog.app.languageEpoch)
                      : groupDialog.app.trE("group_new_name", groupDialog.app.languageEpoch)
                color: theme.textMuted
                font.pixelSize: theme.fontSizeSmall
            }

            UiTextField {
                id: nameField
                // Named so a check can focus it and read the border colour. The blue focus ring this
                // dialog used to draw was invisible to every test because nothing could reach the
                // field: a QML type is not findable by class from Python, so an explicit name is the
                // only handle.
                // 命名使检查能聚焦它并读取边框颜色。本对话框过去绘制的蓝色聚焦环对每个测试都不可见，
                // 因为没有东西能触达该字段：从 Python 无法按类找到 QML 类型，因此显式名称是唯一把手。
                objectName: "groupNameField"
                Layout.fillWidth: true
                enabled: !groupDialog.targetBuiltin
                selectByMouse: true
                placeholderText: groupDialog.app.trE("group_name", groupDialog.app.languageEpoch)
                // NO `background` override.
                //
                // It used to draw a `theme.surfaceAlt` rectangle whose focused border was
                // `theme.accent` — the legacy BLUE. That replaced `UiTextField`'s shell, so this one
                // field in a dialog had a blue focus ring while every other control used the design
                // system's grey `ring`. The reported "blue border" was this override, not the
                // component.
                // 不覆写 `background`。
                //
                // 它过去自绘 `theme.surfaceAlt` 矩形、聚焦边框用 `theme.accent`——也就是旧的"蓝色"。
                // 那替换了 `UiTextField` 的外壳，于是对话框里只有这一个字段用蓝色聚焦环，而所有其他控件
                // 用设计系统的灰色 `ring`。用户报告的"蓝色边框"就是这个覆盖，不是组件本身。
                onAccepted: groupDialog.submit()
            }
        }

        // ---- the refusal, if any ------------------------------------------
        Label {
            Layout.fillWidth: true
            visible: groupDialog.errorMessage !== ""
            text: groupDialog.errorMessage
            color: theme.danger
            font.pixelSize: theme.fontSizeSmall
            wrapMode: Text.WordWrap
        }
    }

    footer: Item {
        implicitHeight: footerRow.implicitHeight + 28

        RowLayout {
            id: footerRow
            anchors.fill: parent
            anchors.margins: 14
            // Right-aligned, so a primary action sits at the trailing edge where
            // the eye expects to confirm. `DialogButtonBox` stretched the buttons
            // to fill the width, which made every dialog's actions look like a
            // toolbar rather than a decision.
            // 右对齐，使主操作位于拖尾边缘——眼睛预期在那里确认。`DialogButtonBox`
            // 会把按钮拉伸到整宽，使每个对话框的操作看起来像工具栏而不是一个决定。
            Layout.fillWidth: true
            // A spacer that absorbs the slack, so the buttons keep their natural widths and
            // sit at the trailing edge. Reversing the layout direction instead also reversed
            // the ORDER, which put the cancel button rightmost.
            // 吸收多余空间的弹簧，使按钮保持自然宽度并停在拖尾边缘。改为反转布局方向会同时反转
            // "顺序"，把取消按钮放到了最右。
            Item { Layout.fillWidth: true }
            spacing: 8
            UiButton {
                text: groupDialog.deleting ? groupDialog.app.trE("delete", groupDialog.app.languageEpoch)
                                           : groupDialog.app.trE("ok", groupDialog.app.languageEpoch)
                enabled: !groupDialog.deleting || !groupDialog.targetBuiltin
                onClicked: groupDialog.submit()
            }
            UiButton {
                text: groupDialog.app.trE("cancel", groupDialog.app.languageEpoch)
                onClicked: groupDialog.close()
            }
        }
    }

}
