// The settings window: a separate always-on-top tool window, like the original
// project's settings dialog.
//
// The main window is the library only — that is what the original project's main
// window was — so settings and about live here instead of in a navigation page.
// The categories mirror the original dialog (通用/发送/热键/文字/性能 + 关于)，and
// the hotkey tab carries the application's shortcut list as its footer.
//
// 设置窗口：一个独立的置顶工具窗口，如同原项目的设置对话框。
//
// 主窗口只承载表情库——原项目的主窗口就是如此——因此设置与关于住这里而非导航页。分类对应
// 原对话框（通用/发送/热键/文字/性能 + 关于），快捷键标签页把应用的快捷键表作为页脚。

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."
import "../components/ui"

Window {
    id: settingsWindow

    required property var app

    // The categories: the schema-driven ones from the settings model, plus
    // About — the original dialog carried an about page in the same list, and
    // that structure is kept.
    // 分类：来自设置模型的 schema 驱动分类，加上"关于"——原对话框把关于页放在同一
    // 个列表里，此处沿用该结构。
    readonly property var categoryIds: {
        if (!settingsWindow.app || !settingsWindow.app.settings)
            return ["about"]
        return settingsWindow.app.settings.categoryIds.concat(["about"])
    }
    readonly property var categoryTitles: {
        if (!settingsWindow.app || !settingsWindow.app.settings)
            return [settingsWindow.app ? settingsWindow.app.trE("about", settingsWindow.app.languageEpoch) : "About"]
        return settingsWindow.app.settings.categoryTitles.concat(
            [settingsWindow.app.trE("about", settingsWindow.app.languageEpoch)])
    }
    // The index is the single navigation source; the schema model is driven
    // THROUGH it, so a click and a programmatic entry always agree.
    // 本索引是导航的唯一来源；schema 模型经它驱动，使点击与程序化进入永远一致。
    property int categoryIndex: 0
    readonly property bool showingAbout:
        categoryIndex >= app.settings.categoryIds.length
    readonly property bool showingHotkey: !showingAbout && categoryIndex >= 0
        && categoryIds[categoryIndex] === "hotkey"

    width: 680
    height: 500
    minimumWidth: 520
    minimumHeight: 380
    visible: false
    title: app ? app.trE("settings", app.languageEpoch) : "GIFManager"
    // TRANSPARENT, so the rounded frame below can show through at the corners. A solid window colour
    // here would paint square corners over the rounded ones.
    // 透明，使下方带圆角的外框能在四角透出。此处若给实色，会在圆角之上画出方角。
    color: "transparent"
    // A frameless always-on-top tool window — the original dialog's exact
    // flags. WITHOUT the frameless hint Qt draws a native title bar above the
    // custom one, which showed as a black strip that matched nothing.
    // 无边框置顶工具窗口——与原对话框的窗口标志完全一致。缺了无边框标志 Qt 会在自
    // 定义标题栏之上再画一条原生标题栏，即那条与任何颜色都不相配的黑条。
    flags: Qt.Tool | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint

    function openWindow() {
        // Re-read the stored values on entry, so an edit made elsewhere shows up
        // without a manual reload. The same side effect the in-page view's
        // `onVisibleChanged` used to carry.
        // 进入时重读已存储的取值，使在别处做的编辑无需手动重载即可显示。与原先页内
        // 视图的 `onVisibleChanged` 承担的副作用相同。
        if (settingsWindow.app && settingsWindow.app.settings)
            settingsWindow.app.settings.load()
        show()
        raise()
        requestActivate()
    }

    Component.onCompleted: if (app) app.applyWindowEffects(settingsWindow)

    // The visible frame, so the window can have ROUNDED corners.
    //
    // # Why the rounding is drawn here and not left to the compositor
    //
    // `applyWindowEffects` asks DWM to round the window, which works on Windows 11 and does nothing on
    // Windows 10 - and there is no portable request for it on X11 or Wayland either. So the rounding
    // is drawn in QML: the window itself is TRANSPARENT, and this rectangle supplies both the fill and
    // the corners. That works on every platform, and it also gives the 1px edge that separates the
    // window from whatever is behind it.
    //
    // The 1px `anchors.margins` is not decoration: without it the frame's own border is clipped by the
    // window bounds and the top and left edges disappear.
    // 可见的外框，使窗口能有"圆角"。
    //
    // # 为什么圆角画在这里而不是交给合成器
    //
    // `applyWindowEffects` 请 DWM 给窗口加圆角，它在 Windows 11 上有效、在 Windows 10 上什么也不做
    // ——而在 X11 或 Wayland 上也没有可移植的请求方式。因此圆角在 QML 里绘制：窗口自身是"透明"的，
    // 这个矩形同时提供填充与圆角。这在每个平台上都有效，并且顺带给出把窗口与背后内容区分开的 1px 边。
    //
    // 1px 的 `anchors.margins` 不是装饰：没有它，外框自己的边框会被窗口边界裁掉，上边与左边会消失。
    Rectangle {
        id: frame
        anchors.fill: parent
        anchors.margins: 1
        radius: theme.uiMetrics.uiRadiusLarge
        color: theme.window
        border.color: theme.uiColors.borderStrong
        border.width: 1

        // Everything visible lives inside the frame, clipped to it so no child paints over the
        // rounded corners.
        // 所有可见内容都在外框内，并被裁剪到它，使任何子元素都不会盖住圆角。
        clip: true

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

        // ---- title bar -----------------------------------------------------
        //
        // Frameless, so the bar both titles the window and drags it — the same
        // trick the original dialog's title bar used.
        // 无边框，因此标题栏既标示窗口又负责拖动——与原对话框标题栏的手法相同。
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 38
            color: theme.window

            MouseArea {
                anchors.fill: parent
                onPressed: settingsWindow.startSystemMove()
            }

            Label {
                anchors.left: parent.left
                anchors.leftMargin: theme.spacingLoose
                anchors.verticalCenter: parent.verticalCenter
                text: settingsWindow.title
                color: theme.textStrong
                font.pixelSize: theme.fontSizeTitle
                font.bold: true
            }

            UiButton {
                anchors.right: parent.right
                anchors.rightMargin: theme.spacing
                anchors.verticalCenter: parent.verticalCenter
                width: 26
                height: 26
                flat: true
                text: "✕"
                onClicked: settingsWindow.close()

                background: Rectangle {
                    radius: theme.radius
                    color: parent.hovered ? theme.surfaceHover : "transparent"
                }
                contentItem: Label {
                    text: parent.text
                    color: theme.text
                    font.pixelSize: theme.fontSizeSmall
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Rectangle {
                anchors.bottom: parent.bottom
                width: parent.width
                height: 1
                color: theme.borderStrong
            }
        }

        // ---- body: category list + rows ------------------------------------
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            Rectangle {
                Layout.preferredWidth: 132
                Layout.fillHeight: true
                color: theme.window

                // A right-hand separator replaces the fill contrast the sidebar used to carry.
                // 一条右侧分隔线取代了侧栏过去依靠的填充对比。
                Rectangle {
                    anchors.right: parent.right
                    width: 1
                    height: parent.height
                    color: theme.borderStrong
                }

                ListView {
                    id: categories
                    anchors.fill: parent
                    anchors.margins: theme.spacing
                    spacing: theme.spacingTight
                    model: settingsWindow.categoryTitles
                    currentIndex: settingsWindow.categoryIndex
                    boundsBehavior: Flickable.StopAtBounds

                    delegate: ItemDelegate {
                        required property int index
                        required property string modelData

                        width: categories.width
                        height: 32
                        text: modelData
                        highlighted: index === settingsWindow.categoryIndex
                        // The CLICK drives the schema model (`setCategory`), and
                        // the local index follows. The first version only wrote
                        // the local index, so the rows ListView — which reads
                        // the model's category — never changed, and every tab
                        // showed the first category's rows.
                        // 点击驱动 schema 模型（`setCategory`），本地索引随之更新。
                        // 第一版只写本地索引，而行视图读的是模型分类——于是每个标签
                        // 都显示第一分类的行。
                        onClicked: {
                            if (index >= settingsWindow.app.settings.categoryIds.length) {
                                settingsWindow.categoryIndex = index
                                return
                            }
                            settingsWindow.app.settings.setCategory(
                                settingsWindow.categoryIds[index])
                            settingsWindow.categoryIndex = index
                        }

                        contentItem: Label {
                            text: parent.text
                            // The selected category is the one place in this sidebar allowed to be
                            // high contrast - the same `selected` token the tab bar uses, so
                            // "current" looks the same in both navigations.
                            // 选中的分类是这个侧栏里唯一被允许高对比的地方——与标签栏同一个 `selected`
                            // 令牌，使"当前"在两种导航里长得一样。
                            color: parent.highlighted ? theme.uiColors.selectedForeground
                                                      : theme.uiColors.mutedForeground
                            font.pixelSize: theme.fontSizeBody
                            font.weight: parent.highlighted ? Font.Medium : Font.Normal
                            verticalAlignment: Text.AlignVCenter
                            leftPadding: theme.spacing
                        }
                        background: Rectangle {
                            radius: theme.uiMetrics.uiRadiusSm
                            color: parent.highlighted ? theme.uiColors.selected
                                   : parent.hovered ? theme.uiColors.surface3
                                   : "transparent"
                            Behavior on color {
                                ColorAnimation {
                                    duration: theme.uiMetrics.uiAnimationMs
                                }
                            }
                        }
                    }
                }

                Rectangle {
                    anchors.right: parent.right
                    width: 1
                    height: parent.height
                    color: theme.borderStrong
                }
            }

            // The rows view for schema categories; the about page for the last
            // entry. `StackLayout` keeps both alive so switching never rebuilds.
            // schema 分类显示行视图；最后一项显示关于页。`StackLayout` 让两者保持
            // 存活，切换永不重建。
            StackLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: settingsWindow.showingAbout ? 1 : 0

                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    contentWidth: availableWidth

                    ListView {
                        id: rows
                        // Named so a check can reach it. The hotkey row is far enough down that
                        // its delegate is not created until the list is scrolled, and a
                        // `ListView` cannot be identified by class from Python (every visual item
                        // reports `QQuickItem`), so without a name the hotkey field cannot be
                        // tested without scrolling a real window.
                        // 命名使检查能到达它。热键行位置较靠下，其委托在列表滚动之前不会被创建，而
                        // 从 Python 无法按类识别 `ListView`（每个可视元素都报告为 `QQuickItem`），
                        // 因此没有名称就无法在不滚动真实窗口的情况下测试热键字段。
                        objectName: "settingsRows"
                        model: settingsWindow.app ? settingsWindow.app.settings
                                                  : null
                        spacing: 2
                        boundsBehavior: Flickable.StopAtBounds

                        // The hotkey tab's footer: the application shortcut
                        // list, read-only, from the same source the About page
                        // used to show — moved here so the tab is the one place
                        // that answers "what does what".
                        // 热键标签的页脚：应用快捷键表（只读），来源与关于页相同
                        // ——挪到这里，使该标签成为回答"什么键干什么"的唯一地方。
                        footer: settingsWindow.showingHotkey
                                ? shortcutsFooter : null

                        Component {
                            id: shortcutsFooter

                            ColumnLayout {
                                width: rows.width
                                spacing: theme.spacingTight

                                Label {
                                    Layout.fillWidth: true
                                    Layout.topMargin: 14
                                    Layout.leftMargin: theme.spacingLoose
                                    text: settingsWindow.app
                                          ? settingsWindow.app.trE("shortcuts", settingsWindow.app.languageEpoch)
                                          : ""
                                    color: theme.textStrong
                                    font.pixelSize: theme.fontSizeTitle
                                    font.bold: true
                                }

                                Repeater {
                                    // `shortcutList`, not `shortcuts()`.
                                    //
                                    // A binding that CALLS a method has no dependency to re-evaluate
                                    // on, so this table was computed once and never refreshed - the
                                    // global hotkey row kept showing the old sequence after a change.
                                    // The property form carries `notify=settingsChanged`, and committing
                                    // the hotkey emits exactly that.
                                    // 用 `shortcutList` 而不是 `shortcuts()`。
                                    //
                                    // 调用方法的绑定没有可依赖的求值依据，因此该表只算一次、永不刷新——改掉
                                    // 全局热键后该行仍显示旧序列。属性形式带有 `notify=settingsChanged`，
                                    // 而提交热键正好发出该信号。
                                    model: settingsWindow.app
                                           ? settingsWindow.app.shortcutList : []

                                    delegate: RowLayout {
                                        required property var modelData
                                        Layout.fillWidth: true
                                        Layout.leftMargin: theme.spacingLoose
                                        Layout.rightMargin: theme.spacingLoose

                                        Label {
                                            Layout.preferredWidth: 130
                                            text: modelData.keys
                                            color: theme.text
                                            font.family: "Consolas, Menlo, monospace"
                                            font.pixelSize: theme.fontSizeBody
                                        }

                                        Label {
                                            Layout.fillWidth: true
                                            // 去掉 Widgets 时代遗留的助记键括号（如
                                            // "复制 (&C)"→"复制"）。
                                            // Strip the Widgets-era mnemonic
                                            // parentheses ("复制 (&C)"→"复制").
                                            text: modelData.label.replace(
                                                / ?\(&[A-Za-z]\)/, "")
                                            color: theme.text
                                            font.pixelSize: theme.fontSizeBody
                                        }
                                    }
                                }

                                Item { Layout.preferredHeight: theme.spacing }
                            }
                        }

                        delegate: ColumnLayout {
                            id: rowRoot
                            required property int index
                            required property string field
                            required property string kind
                            required property string label
                            required property string hint
                            required property string groupTitle
                            required property var value
                            required property var choices
                            required property int minimum
                            required property int maximum
                            required property bool capabilityEnabled
                            required property bool restartRequired

                            width: rows.width
                            spacing: 2

                            Label {
                                Layout.fillWidth: true
                                Layout.topMargin: rowRoot.index === 0 ? 8 : 14
                                visible: rowRoot.index === 0
                                        || rowRoot.groupTitle !== previousGroup()
                                text: rowRoot.groupTitle
                                color: theme.textStrong
                                font.pixelSize: theme.fontSizeTitle
                                font.bold: true
                                leftPadding: theme.spacingLoose

                                function previousGroup() {
                                    if (rowRoot.index === 0)
                                        return ""
                                    var prior = settingsWindow.app.settings.data(
                                        settingsWindow.app.settings.index(
                                            rowRoot.index - 1, 0),
                                        Qt.UserRole + 5)
                                    return prior
                                }
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                Layout.leftMargin: theme.spacingLoose
                                Layout.rightMargin: theme.spacingLoose
                                spacing: theme.spacing

                                Label {
                                    Layout.preferredWidth: 170
                                    text: rowRoot.label
                                         + (rowRoot.restartRequired ? " *" : "")
                                    color: rowRoot.capabilityEnabled ? theme.text
                                                           : theme.textMuted
                                    font.pixelSize: theme.fontSizeBody
                                    wrapMode: Text.WordWrap
                                    // An explicit `UiToolTip`, not the attached `ToolTip.*` form:
                                    // the attached one is drawn by `QtQuick.Controls.Basic` and kept
                                    // its own frame no matter how the application palette was set.
                                    // 显式的 `UiToolTip`，而非附加属性 `ToolTip.*`：附加形式由
                                    // `QtQuick.Controls.Basic` 绘制，无论应用调色板怎么设都保留着它自己的边框。
                                    UiToolTip {
                                        text: rowRoot.hint
                                        visible: rowHover.hovered && rowRoot.hint !== ""
                                    }
                                }

                                Loader {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: theme.controlHeight
                                    sourceComponent: {
                                        switch (rowRoot.kind) {
                                        case "bool": return boolControl
                                        case "int": return intControl
                                        case "percent": return percentControl
                                        case "choice": return choiceControl
                                        case "hotkey": return hotkeyControl
                                        case "file": return fileControl
                                        default: return textControl
                                        }
                                    }
                                    enabled: rowRoot.capabilityEnabled
                                    opacity: rowRoot.capabilityEnabled ? 1.0 : 0.5

                                    onLoaded: {
                                        if (item === null)
                                            return
                                        // controlChoices is assigned BEFORE
                                        // controlValue: a combo that receives its
                                        // value first has an empty model to look
                                        // up and lands on index 0.
                                        // controlChoices 在 controlValue "之前"赋值：
                                        // 先拿到值的下拉框面对的是空模型，查找会落到
                                        // 第 0 项。
                                        if (item.hasOwnProperty("controlChoices"))
                                            item.controlChoices = rowRoot.choices
                                        if (item.hasOwnProperty("controlMinimum"))
                                            item.controlMinimum = rowRoot.minimum
                                        if (item.hasOwnProperty("controlMaximum"))
                                            item.controlMaximum = rowRoot.maximum
                                        if (item.hasOwnProperty("controlValue"))
                                            item.controlValue = rowRoot.value
                                        if (item.hasOwnProperty("controlField"))
                                            item.controlField = rowRoot.field
                                        if (item.hasOwnProperty("controlLabel"))
                                            item.controlLabel = rowRoot.label
                                    }
                                }
                            }

                            HoverHandler { id: rowHover }
                        }

                        Component {
                            id: boolControl
                            // Every control reads the Loader-assigned inputs, never
                            // the delegate's `rowRoot`: a Component is instantiated
                            // in its own scope and the delegate id is unreachable
                            // from there (the historical "rowRoot is not defined"
                            // warnings).
                            // 每个控件读取 Loader 赋予的输入，绝不读委托的 `rowRoot`：
                            // Component 在自身作用域实例化，从那里无法触及委托 id（即
                            // 历史上的 "rowRoot is not defined" 警告）。
                            // `UiSwitch`: the track is `surface3` off and `selected` on, so the state
                            // is read as contrast rather than as an accent colour.
                            // `UiSwitch`：关闭时轨道是 `surface3`、打开时是 `selected`，因此状态被
                            // 读作对比度而不是强调色。
                            UiSwitch {
                                property var controlValue: undefined
                                property string controlField: ""

                                checked: controlValue === true
                                onToggled: settingsWindow.app.settings.setValue(
                                               controlField, checked)
                            }
                        }

                        Component {
                            id: intControl
                            UiSpinBox {
                                property var controlValue: undefined
                                property string controlField: ""
                                property int controlMinimum: 0
                                property int controlMaximum: 100

                                from: controlMinimum
                                to: controlMaximum
                                value: controlValue === undefined
                                       ? controlMinimum : controlValue
                                editable: true
                                onValueModified: settingsWindow.app.settings.setValue(
                                                     controlField, value)
                            }
                        }

                        Component {
                            id: percentControl
                            UiSpinBox {
                                property var controlValue: undefined
                                property string controlField: ""
                                property int controlMinimum: 0
                                property int controlMaximum: 100

                                from: controlMinimum
                                to: controlMaximum
                                value: controlValue === undefined
                                       ? controlMinimum : controlValue
                                editable: true
                                textFromValue: function (v) { return v + " %" }
                                valueFromText: function (t) {
                                    return parseInt(t.replace(/[^0-9]/g, ""), 10) || 0
                                }
                                onValueModified: settingsWindow.app.settings.setValue(
                                                     controlField, value)
                            }
                        }

                        Component {
                            id: choiceControl
                            // `UiComboBox`: the chosen row in the popup is the only high-contrast
                            // element, so a selected option reads the same way as a selected tab.
                            // `UiComboBox`：弹出层中"被选中的行"是唯一的高对比元素，使"已选项"的
                            // 读法与"已选标签"一致。
                            UiComboBox {
                                property var controlChoices: []
                                property var controlValue: undefined
                                property string controlField: ""

                                model: controlChoices
                                textRole: "label"
                                valueRole: "value"
                                // The Loader assigns `controlValue` AFTER this
                                // control's `Component.onCompleted`, so the
                                // initial selection must also react to the value
                                // arriving — otherwise the combo shows the first
                                // choice while the stored one is another, and
                                // picking the stored one "does nothing".
                                // Loader 在本控件的 `Component.onCompleted` "之后"
                                // 才赋 `controlValue`，因此初始选中必须响应值的到达
                                // ——否则下拉框显示第一项而存储的是另一项，选中原值
                                // 会看起来"选不上"。
                                onControlValueChanged: currentIndex = indexOfValue(
                                                           controlValue)
                                // The model can land after the value (Loader
                                // order changes elsewhere); re-select then too.
                                // 模型也可能晚于值到达（别处调整 Loader 顺序时）；
                                // 那时同样重选。
                                onControlChoicesChanged: currentIndex = indexOfValue(
                                                             controlValue)
                                Component.onCompleted: currentIndex = Math.max(
                                    0, indexOfValue(controlValue))
                                onActivated: {
                                    // 外观 applies AT ONCE; every other choice stays a draft.
                                    //
                                    // A colour scheme is not a value the user needs to confirm: picking
                                    // it and seeing nothing change reads as a broken control, not as
                                    // "press 应用". Fixing the theme needs no restart and no revert
                                    // strategy, so the honest treatment is to show the result
                                    // immediately.
                                    //
                                    // Everything else keeps the dialog's draft contract, because those
                                    // values (send mode, sorting) are not visible while the dialog is
                                    // open and a stray change is better left cancellable.
                                    // 外观"立即"生效；其他选项仍留作草稿。
                                    //
                                    // 配色方案不是需要用户确认的值：选中它却看不出任何变化，读起来是控件坏了，
                                    // 而不是"请按应用"。修复主题既不需要重启也不需要回退策略，因此诚实的处理
                                    // 就是立刻显示结果。
                                    //
                                    // 其余选项保留对话框的草稿契约，因为那些值（发送模式、排序）在对话框打开
                                    // 时并不可见，而一次误改更好留作可取消。
                                    if (controlField === "theme")
                                        settingsWindow.app.setSettingNow(controlField,
                                                                         currentValue)
                                    else
                                        settingsWindow.app.settings.setValue(controlField,
                                                                             currentValue)
                                }
                            }
                        }

                        Component {
                            id: textControl
                            UiTextField {
                                property var controlValue: undefined
                                property string controlField: ""

                                text: controlValue === undefined ? "" : String(controlValue)
                                selectByMouse: true
                                onEditingFinished: settingsWindow.app.settings.setValue(
                                                       controlField, text)
                            }
                        }

                        Component {
                            id: fileControl
                            RowLayout {
                                property var controlValue: undefined
                                property string controlField: ""

                                spacing: theme.spacingTight

                                UiTextField {
                                    id: fileField
                                    Layout.fillWidth: true
                                    text: parent.controlValue === undefined
                                          ? "" : String(parent.controlValue)
                                    placeholderText: settingsWindow.app.trE("automatic", settingsWindow.app.languageEpoch)
                                    selectByMouse: true
                                    onEditingFinished: settingsWindow.app.settings.setValue(
                                                           parent.controlField, text)
                                }

                                UiButton {
                                    text: settingsWindow.app.trE("browse", settingsWindow.app.languageEpoch)
                                    onClicked: settingsWindow.app.browseForFile(
                                                   parent.controlField,
                                                   parent.controlValue || "")
                                }
                            }
                        }

                        Component {
                            id: hotkeyControl
                            // A Rectangle + Label, NOT a `TextField`.
                            //
                            // # Why the text input had to go
                            //
                            // A `TextField` - even a `readOnly` one - brings Qt's whole text-editing
                            // machinery with it, and that machinery competes with the capture:
                            //
                            //   * Shift+F10 is the standard "open the context menu" key, so it opened
                            //     the field's own Undo/Redo/Cut/Copy/Paste/Delete/Select All menu
                            //     instead of being captured. That menu is the dialog the user reported.
                            //   * Alt combinations are menu-accelerator traffic, and the field consumed
                            //     them before the capture filter could see a complete combination.
                            //   * Focus produced a white ring that never went away, because the field
                            //     kept focus after the capture finished - which reads as "still
                            //     waiting for input".
                            //
                            // None of that is needed: the capture is process-wide (see
                            // `BackendBridge.beginHotkeyCapture`), so the control only has to LOOK like
                            // a field and react to a click. A plain item has no text editing, no context
                            // menu, no shortcut table and no focus requirement, which removes all three
                            // failures at once instead of working around each.
                            // 一个 Rectangle + Label，而不是 `TextField`。
                            //
                            // # 为什么必须去掉文本输入
                            //
                            // `TextField`——即便设了 `readOnly`——会带来 Qt 的整套文本编辑机制，而那套机制
                            // 与捕获相互竞争：
                            //
                            //   * Shift+F10 是标准的"打开上下文菜单"键，于是它打开的是字段自己的
                            //     撤销/重做/剪切/复制/粘贴/删除/全选菜单，而不是被捕获。那个菜单就是用户
                            //     报告的对话框。
                            //   * Alt 组合属于菜单加速键流量，字段会在捕获过滤器看到完整组合之前把它们消费掉。
                            //   * 焦点会产生一个不会消失的白色聚焦环，因为捕获结束后字段仍持有焦点——那读起来
                            //     就像"还在等待输入"。
                            //
                            // 这些都不需要：捕获是进程级的（见 `BackendBridge.beginHotkeyCapture`），
                            // 因此控件只需要"看起来像"字段并对点击作出反应。一个普通元素没有文本编辑、
                            // 没有上下文菜单、没有快捷键表、也不需要焦点，于是一次性消除全部三个失效点，
                            // 而不是逐个绕开。
                            Rectangle {
                                id: hotkeyField
                                // Named so a check can find it / 命名使检查能找到它
                                objectName: "hotkeyField"
                                property var controlValue: undefined
                                property string controlField: ""

                                // What the field shows: what was just captured, else the stored value.
                                //
                                // The captured text is kept locally because it must be visible the
                                // instant the key is pressed; waiting for the settings model to
                                // re-evaluate would make a correct capture look like nothing happened.
                                // 字段显示的内容：刚捕获的值，否则是已存储的值。
                                //
                                // 捕获到的文本保存在本地，因为它必须在按键那一刻就可见；等待设置模型重新
                                // 求值会让一次成功的捕获看起来像什么都没发生。
                                property string capturedText: ""

                                // `armed` drives the visual state and is CLEARED when the capture ends.
                                //
                                // This is the guidance that was missing: the highlighted border means "I
                                // am listening", and it drops back the instant a shortcut is recorded, so
                                // nothing suggests the field is still waiting for input.
                                // `armed` 驱动视觉状态，并在捕获结束时"清除"。
                                //
                                // 这正是此前缺失的引导：高亮边框表示"正在监听"，而它在快捷键被记录的那一刻
                                // 恢复常态，因此没有任何东西暗示字段仍在等待输入。
                                property bool armed: false

                                Layout.fillWidth: true
                                implicitHeight: theme.uiMetrics.uiControlHeight
                                radius: theme.uiMetrics.uiRadius
                                color: theme.uiColors.surface1
                                border.width: armed ? 2 : 1
                                border.color: armed ? theme.uiColors.selected
                                                    : hoverArea.containsMouse
                                                      ? theme.uiColors.borderStrong
                                                      : theme.uiColors.border

                                Behavior on border.color {
                                    ColorAnimation { duration: theme.uiMetrics.uiAnimationMs }
                                }

                                Label {
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.verticalCenter: parent.verticalCenter
                                    anchors.leftMargin: theme.uiMetrics.uiPaddingX
                                    anchors.rightMargin: theme.uiMetrics.uiPaddingX
                                    text: hotkeyField.capturedText !== ""
                                          ? hotkeyField.capturedText
                                          : hotkeyField.hotkeyText(hotkeyField.controlValue)
                                    color: hotkeyField.capturedText !== ""
                                           || hotkeyField.controlValue !== undefined
                                           ? theme.uiColors.foreground
                                           : theme.uiColors.mutedForeground
                                    font.pixelSize: theme.uiMetrics.uiFontSize
                                    elide: Text.ElideRight
                                }

                                MouseArea {
                                    id: hoverArea
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        hotkeyField.armed = true
                                        hotkeyField.capturedText = ""
                                        settingsWindow.app.beginHotkeyCapture(
                                            hotkeyField.controlField)
                                    }
                                }

                                // The capture must not survive the control it belongs to.
                                //
                                // The filter is PROCESS-WIDE, so an armed capture that outlives its
                                // field keeps swallowing every keystroke in the application: the user
                                // switches category or closes the window and the rest of the interface
                                // stops responding to the keyboard. Disarming on destruction covers the
                                // category switch (it destroys the Loader's item) and the window close.
                                // 捕获不得比它所归属的控件活得更久。
                                //
                                // 过滤器是"进程级"的，因此一个比自己字段活得更久的待捕获状态会持续吞掉应用里
                                // 的每一次击键：用户切换分类或关闭窗口后，界面其余部分就不再响应键盘。销毁时
                                // 解除覆盖了切换分类（它会销毁 Loader 的元素）与关闭窗口两种情况。
                                Component.onDestruction: if (armed)
                                                             settingsWindow.app.endHotkeyCapture()

                                Connections {
                                    target: settingsWindow.app
                                    function onHotkeyCaptured(field, text) {
                                        if (field !== hotkeyField.controlField)
                                            return
                                        hotkeyField.capturedText = text
                                        // Disarm, so the border returns to normal and the user can see
                                        // the shortcut is configured.
                                        // 解除待捕获，使边框恢复常态、用户能看到快捷键已配置完成。
                                        hotkeyField.armed = false
                                    }
                                    function onHotkeyCaptureEnded() {
                                        hotkeyField.armed = false
                                    }
                                }

                                // The stored value arrives in either shape: a portable string
                                // ("Ctrl+Alt+F10") or the parsed {modifiers, key} map the schema keeps.
                                // Both render as one canonical string.
                                // 存储值有两种形态：可移植字符串（"Ctrl+Alt+F10"）或 schema 解析出的
                                // {modifiers, key} 映射。两者都渲染成同一个规范字符串。
                                function hotkeyText(value) {
                                    if (value === undefined || value === null
                                            || value === "")
                                        return settingsWindow.app.trE("hotkey_unset", settingsWindow.app.languageEpoch)
                                    if (typeof value === "object") {
                                        var parts = []
                                        var mask = value.modifiers | 0
                                        if (mask & Qt.ControlModifier)
                                            parts.push("Ctrl")
                                        if (mask & Qt.AltModifier)
                                            parts.push("Alt")
                                        if (mask & Qt.ShiftModifier)
                                            parts.push("Shift")
                                        if (mask & Qt.MetaModifier)
                                            parts.push("Meta")
                                        if (value.key)
                                            parts.push(String(value.key))
                                        return parts.join("+")
                                    }
                                    return String(value)
                                }
                            }
                        }
                    }
                }

                AboutPage { app: settingsWindow.app }
            }
        }

        // ---- footer ---------------------------------------------------
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 44
            color: theme.window

            Rectangle {
                anchors.top: parent.top
                width: parent.width
                height: 1
                color: theme.borderStrong
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: theme.spacingLoose
                anchors.rightMargin: theme.spacingLoose
                spacing: theme.spacing

                // A spacer pushes the buttons to the RIGHT edge. Without it the row is
                // left-packed by default, and the buttons appeared to float mid-bar because
                // the bar is wide and the three buttons together are narrow.
                //
                // The action order is unchanged (应用 / 取消 / 确定) — only the group's
                // position. Both facts matter: a right-aligned group that also reordered its
                // buttons would be two changes where the user asked for one.
                // 一个弹簧把按钮推到"右"边缘。没有它时该行默认靠左堆叠，而由于这一条很宽、三个按钮
                // 合起来很窄，按钮看起来像浮在条的中间。
                //
                // 动作顺序不变（应用 / 取消 / 确定）——只是整组的位置。两件事都要紧：一个既右对齐
                // 又重新排列了按钮的组，会在用户只要求一件事的地方做两处改动。
                Item { Layout.fillWidth: true }

                // The original dialog's footer contract: 应用 commits and stays,
                // 确认 commits and closes, 取消 reverts and closes. Edits sit in
                // the model's pending buffer until one of them runs.
                // 原对话框的页脚契约：应用提交并留窗，确认提交并关窗，取消回退并关窗。
                // 控件编辑落入模型的待定缓冲，直到其中之一执行。
                UiButton {
                    text: settingsWindow.app
                          ? settingsWindow.app.trE("apply", settingsWindow.app.languageEpoch) : ""
                    // `applySettings` instead of `settings.applyPending`: the bridge slot never raises,
                    // so a failed coercion cannot abort the QML statement. See the OK button below for
                    // why that matters.
                    // 用 `applySettings` 而不是 `settings.applyPending`：桥的槽绝不抛出，因此一次失败的
                    // 强制转换无法中断 QML 语句。原因见下方的"确定"按钮。
                    onClicked: settingsWindow.app.applySettings()
                }

                UiButton {
                    text: settingsWindow.app
                          ? settingsWindow.app.trE("cancel", settingsWindow.app.languageEpoch) : ""
                    onClicked: {
                        settingsWindow.app.settings.cancelPending()
                        settingsWindow.close()
                    }
                }

                UiButton {
                    text: settingsWindow.app
                          ? settingsWindow.app.trE("ok", settingsWindow.app.languageEpoch) : ""
                    // Apply, THEN close, with the apply unable to throw.
                    //
                    // The previous form was `settings.app.applyPending(); settingsWindow.close()`. A
                    // Python exception in `applyPending` (a rejected coercion, an unavailable platform
                    // service, a failed registry write) propagated out of the QML handler, so `close()`
                    // was skipped: the window stayed open and nothing was saved. That is the reported
                    // "clicking save does not close the settings window", and wrapping the apply is what
                    // makes the close unconditional.
                    // 先应用、再关闭，并且应用不会抛出。
                    //
                    // 旧写法是 `settings.app.applyPending(); settingsWindow.close()`。`applyPending` 中的
                    // Python 异常（被拒绝的强制转换、不可用的平台服务、失败的注册表写入）会从 QML 处理函数
                    // 中传播出去，于是 `close()` 被跳过：窗口留在原地且什么都没保存。这正是用户报告的
                    // "点击保存后不会关闭设置窗口"——包住应用步骤，才让关闭成为无条件行为。
                    onClicked: {
                        settingsWindow.app.applySettings()
                        settingsWindow.close()
                    }
                }
            }
        }
    }
    }
}
