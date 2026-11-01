// A text sticker and the text-sticker editor.
//
// # Why a text sticker is a card and not a label
//
// The grid stores all three kinds of thing in one list, so a text sticker has to
// occupy a cell, be selectable and copy with one click like everything else. Its
// content IS its name, which is what `add_text_emoji` already does — the store sets
// the display name from the text — so there is nothing to keep in sync.
//
// # Why the editor is one dialog for create and edit
//
// Both are "type some text and save it", and the only differences are the title and
// which bridge method runs. Two dialogs would be two places to fix the length limit.
//
// 文字贴纸与文字贴纸编辑器。
//
// # 为什么文字贴纸是卡片而不是标签
//
// 网格把三类东西放在同一个列表里，因此文字贴纸必须占用一个单元格、可被选中、并能像其他一切
// 一样一次点击复制。它的内容"就是"它的名称，这正是 `add_text_emoji` 已经在做的事——存储层
// 从文字设置显示名——因此没有任何东西需要同步。
//
// # 为什么编辑器新建与编辑共用一个对话框
//
// 两者都是"输入一些文字并保存"，唯一的差别是标题与运行哪个桥方法。两个对话框就是两处需要修正
// 同一个长度上限。

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "./ui"
import "../components/ui"

UiDialog {
    // Item 型弹窗：在场景内绘制。无边框工具窗口上 Window 型原生弹窗不显示。
    // Item-type popup: rendered inside the scene, because a Window-type
    // native popup does not show on a frameless tool window.
    id: textDialog

    required property var app

    // "create" | "edit" /
    // "create" | "edit"
    property string mode: "create"

    anchors.centerIn: parent
    modal: true
    width: Math.min(460, parent ? parent.width - 60 : 420)
    standardButtons: Dialog.NoButton

    // Edit mode: the sticker being changed. Create mode: -1.
    // 编辑模式：正在修改的贴纸。新建模式：-1。
    property int targetId: -1
    property string errorMessage: ""

    // The length limit comes from the bridge, so the counter and the refusal cannot
    // disagree about what the limit is.
    // 长度上限来自桥，使计数器与拒绝不会对上限是什么产生分歧。
    readonly property int limit: textDialog.app.textStickerLimit
    readonly property int used: editor.text.length
    readonly property bool tooLong: textDialog.used > textDialog.limit

    readonly property bool creating: textDialog.mode === "create"

    function openCreateFor(groupId) {
        mode = "create"
        targetId = groupId
        errorMessage = ""
        editor.text = ""
        targetLabel.text = textDialog.app.groupNameOf(groupId)
        open()
        editor.forceActiveFocus()
    }

    function openEdit(stickerId) {
        var row = textDialog.app.sticker(stickerId)
        mode = "edit"
        targetId = stickerId
        errorMessage = ""
        editor.text = row.text_content || ""
        var groupId = row.group_id === undefined ? -1 : row.group_id
        targetLabel.text = textDialog.app.groupNameOf(groupId)
        open()
        editor.forceActiveFocus()
        editor.selectAll()
    }

    function submit() {
        if (textDialog.tooLong) {
            // `trArgsE`, not `trArgs`: this form takes a language-epoch argument so the
            // message retranslates when the language changes. Calling `trArgs` with three
            // arguments makes Qt ignore the call entirely ("Too many arguments, ignoring 1")
            // and the property receives `undefined` — so the length-limit refusal showed no
            // message at all.
            // 用 `trArgsE` 而不是 `trArgs`：这种形式接收语言纪元参数，使消息在语言变更时重翻译。
            // 用三个实参调用 `trArgs` 会让 Qt 完全忽略该调用（"Too many arguments, ignoring 1"），
            // 属性收到 `undefined`——于是长度上限的拒绝提示完全不显示。
            textDialog.errorMessage = textDialog.app.trArgsE(
                "text_too_long", JSON.stringify({ limit: textDialog.limit }),
                textDialog.app.languageEpoch)
            return
        }
        var result
        if (textDialog.creating)
            result = textDialog.app.createTextSticker(textDialog.targetId,
                                                      editor.text)
        else
            result = textDialog.app.setStickerTextResult(textDialog.targetId,
                                                         editor.text)
        if (result.ok) {
            textDialog.close()
            textDialog.app.showStatus(result.message, 2500)
            return
        }
        textDialog.errorMessage = result.message
    }

    title: textDialog.creating ? textDialog.app.trE("new_text_sticker", textDialog.app.languageEpoch)
                               : textDialog.app.trE("edit_text_dialog", textDialog.app.languageEpoch)

    contentItem: ColumnLayout {
        spacing: theme.spacing

        Label {
            Layout.fillWidth: true
            text: textDialog.creating ? textDialog.app.trE("text_sticker_prompt", textDialog.app.languageEpoch)
                                      : textDialog.app.trE("edit_text_prompt", textDialog.app.languageEpoch)
            color: theme.textMuted
            font.pixelSize: theme.fontSizeSmall
            wrapMode: Text.WordWrap
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: theme.spacingTight
            visible: textDialog.creating
            Label {
                text: textDialog.app.trE("text_sticker_group", textDialog.app.languageEpoch)
                color: theme.textMuted
                font.pixelSize: theme.fontSizeSmall
            }
            Label {
                id: targetLabel
                Layout.fillWidth: true
                text: ""
                color: theme.text
                font.pixelSize: theme.fontSizeSmall
                elide: Text.ElideRight
            }
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.preferredHeight: 120
            clip: true
            TextArea {

    // No context menu: see `UiTextField` for why. Only right clicks are taken, so editing and
    // selection are untouched.
    // 不显示上下文菜单：理由见 `UiTextField`。只接管右键，因此编辑与选择不受影响。
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.RightButton
        onPressed: function (mouse) { mouse.accepted = true }
    }

                id: editor
                wrapMode: TextArea.Wrap
                selectByMouse: true
                color: theme.text
                font.pixelSize: theme.fontSizeBody
                // Ctrl+Enter saves, Enter inserts a newline: a text sticker may
                // legitimately be several lines, so Enter cannot be the submit key.
                // Ctrl+Enter 保存，Enter 插入换行：文字贴纸合理情况下可能有多行，因此 Enter
                // 不能作为提交键。
                Keys.onPressed: function (event) {
                    if (event.key === Qt.Key_Return
                            && (event.modifiers & Qt.ControlModifier)) {
                        textDialog.submit()
                        event.accepted = true
                    }
                }
            }
        }

        // The counter turns red past the limit instead of the field silently
        // refusing keystrokes, so the user sees why.
        // 计数器在超出上限时变红，而不是让字段静默拒绝按键，使用户能看到原因。
        Label {
            Layout.fillWidth: true
            text: textDialog.used + " / " + textDialog.limit
                  + "  ·  " + textDialog.app.trE("new_text_sticker_hint", textDialog.app.languageEpoch)
            color: textDialog.tooLong ? theme.danger : theme.textMuted
            font.pixelSize: theme.fontSizeSmall
        }

        Label {
            Layout.fillWidth: true
            visible: textDialog.errorMessage !== ""
            text: textDialog.errorMessage
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
                text: textDialog.app.trE("ok", textDialog.app.languageEpoch)
                enabled: editor.text.trim() !== "" && !textDialog.tooLong
                onClicked: textDialog.submit()
            }
            UiButton {
                text: textDialog.app.trE("cancel", textDialog.app.languageEpoch)
                onClicked: textDialog.close()
            }
        }
    }

}
