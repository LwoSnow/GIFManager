// The application shell: the library window, the toolbar, the status bar.
//
// The main window is the LIBRARY — that is what the original project's window
// was. A frameless tool window with a drag-anywhere toolbar, a search field, the
// import and add-text actions, and a settings gear; no navigation column,
// because settings and about live in their own window (`SettingsWindow.qml`).
//
// Everything binds to `app` (the Python `BackendBridge`) and `theme`. No page
// ever calls a refresh method: a backend change emits a signal, the signal
// invalidates the binding, and QML re-evaluates what depends on it.
//
// 应用外壳：表情库窗口、工具栏、状态栏。
//
// 主窗口"就是表情库"——原项目的窗口即是如此。一个无边框工具窗口、可全栏拖动的工具栏、
// 搜索框、导入与新建文字操作，以及设置齿轮；没有导航列，因为设置与关于住在自己的窗口
// （`SettingsWindow.qml`）里。
//
// 此处一切都绑定到 `app`（Python 的 `BackendBridge`）与 `theme`。页面从不调用刷新方法：
// 后端变更发出信号，信号使绑定失效，QML 重新求值依赖它的部分。

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
// The pages live in a sibling directory, and QML resolves an unqualified type only
// in the file's OWN directory. A relative import is what makes `LibraryPage` and
// `SettingsWindow` resolvable here.
// 页面位于同级目录，而 QML 只在文件"自身"目录中解析未限定的类型。相对导入才是让
// `LibraryPage` 与 `SettingsWindow` 在此可解析的原因。
import "../views"
import "../components"
import "../components/ui"

ApplicationWindow {
    id: shell

    // `app` is NOT declared here, and that is the point.
    //
    // A QML `property` shadows a context property of the same name. Declaring
    // `property var app: null` therefore HID the `app` context property that
    // `bridge.py` installs, so every binding read null. Leaving `app` undeclared
    // solves it, because a context property satisfies the reference without an
    // initialiser.
    //
    // 此处"不"声明 `app`，这正是要点。
    //
    // QML 的 `property` 会遮蔽同名的上下文属性。因此声明 `property var app: null` 会
    // "隐藏" `bridge.py` 安装的 `app` 上下文属性，使每个绑定都读到 null。完全不声明
    // `app` 则解决该问题，因为上下文属性无需初始化值即可满足引用。

    // The original project's window geometry: default 620x520, minimum 344x380
    // (its `models/constants.py`). Same numbers so the two interfaces open at the
    // same size.
    // 原项目的窗口几何：默认 620x520，最小 344x380（其 `models/constants.py`）。相同
    // 数值使两个界面以相同尺寸打开。
    width: 620
    height: 520
    minimumWidth: 344
    minimumHeight: 380
    visible: false
    title: bridge ? (bridge.appName + " " + bridge.version) : "GIFManager"
    color: theme.window

    // Frameless tool window, exactly the original project's flags: no title bar
    // (the toolbar drags the window), no taskbar entry (the tray icon owns
    // visibility), optionally always-on-top. `visible` starts false: the flags
    // and the restored geometry must land BEFORE the first show, so
    // `Component.onCompleted` applies them and then shows.
    // 无边框工具窗口，与原项目的窗口标志完全一致：无标题栏（工具栏负责拖动窗口）、
    // 无任务栏条目（可见性由托盘图标拥有）、可选置顶。`visible` 初始为 false：窗口
    // 标志与恢复的几何必须在首次显示"之前"落地，因此 `Component.onCompleted` 先应用
    // 再显示。
    readonly property int baseFlags: Qt.Tool | Qt.FramelessWindowHint

    onClosing: function (close) {
        // Hide to the tray when there is one — the original behaviour: a tool
        // window has no taskbar entry, so closing it for real would lose it.
        // Without a tray there is no way back, so the window really closes.
        // 有托盘时隐藏到托盘——原版行为：工具窗口没有任务栏条目，真正关闭会找不到
        // 它。没有托盘则无路可回，窗口真正关闭。
        shell.saveGeometry()
        if (bridge.trayAvailable()) {
            close.accepted = false
            shell.hide()
            bridge.tray.showMessage(bridge.appName, bridge.trE("tray_hidden", bridge.languageEpoch))
        } else {
            close.accepted = true
        }
    }

    function saveGeometry() {
        bridge.saveWindowGeometry({
            "x": shell.x, "y": shell.y,
            "width": shell.width, "height": shell.height
        })
    }

    function openSettings() {
        settingsWindow.openWindow()
    }

    // ---- keyboard shortcuts ------------------------------------------------

    Shortcut { sequence: "Ctrl+F"; onActivated: searchField.forceActiveFocus() }
    Shortcut { sequence: "Ctrl+Q"; onActivated: bridge.quit() }
    Shortcut { sequence: "F1"; onActivated: shell.openSettings() }
    // 复制选中（或首张可见）贴纸——与托盘"复制"同一条路径。
    // Copy the selected (or first visible) sticker — the tray's copy route.
    Shortcut { sequence: "Ctrl+C"; onActivated: bridge.copySelectionRequested() }
    Shortcut {
        sequence: "Delete"
        onActivated: {
            // 编辑模式下删除所选；普通模式不响应，防止误删。
            // Delete the selection in edit mode; inert otherwise, so a stray
            // keypress cannot delete anything.
            if (libraryPage.editMode && bridge.stickers.selectedCount > 0)
                bridge.deleteSelection()
        }
    }
    Shortcut {
        sequence: "Ctrl+A"
        onActivated: {
            // Select all/clear in edit mode, mirroring the original grid.
            // 编辑模式下全选/取消全选，镜像原版网格。
            if (!libraryPage.editMode)
                return
            if (bridge.stickers.selectedCount > 0)
                bridge.stickers.clearSelection()
            else
                bridge.stickers.selectAll()
        }
    }

    // ---- frameless window chrome ------------------------------------------
    //
    // Four invisible edge strips give a frameless window native edge-resizing
    // through `startSystemResize`. The original project had no resize route at
    // all (its frameless window could only be moved); these keep the same look
    // while restoring the resize its layout code assumed.
    // 四条不可见的边缘条让无边框窗口经 `startSystemResize` 获得原生边缘缩放。原项目
    // 完全没有缩放通道（其无边框窗口只能移动）；它们保持相同外观，同时恢复其布局代
    // 码一直假定的缩放能力。
    component ResizeEdge: MouseArea {
        id: edge

        property int edges: 0
        z: 20
        acceptedButtons: Qt.LeftButton
        onPressed: shell.startSystemResize(edge.edges)
    }

    ResizeEdge {
        edges: Qt.LeftEdge
        width: 5
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        cursorShape: Qt.SizeHorCursor
    }
    ResizeEdge {
        edges: Qt.RightEdge
        width: 5
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        cursorShape: Qt.SizeHorCursor
    }
    ResizeEdge {
        edges: Qt.TopEdge
        height: 5
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        cursorShape: Qt.SizeVerCursor
    }
    ResizeEdge {
        edges: Qt.BottomEdge
        height: 5
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        cursorShape: Qt.SizeVerCursor
    }

    // The corner grip resizes BOTH axes at once, and shows the two diagonal
    // slashes the user asked for.
    // 右下角角标同时调节两个轴向，并显示所要求的两道斜杠。
    Item {
        width: 18
        height: 18
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        z: 21

        Canvas {
            id: resizeGrip
            anchors.fill: parent
            onPaint: {
                var ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)
                ctx.strokeStyle = theme.textMuted
                ctx.lineWidth = 1.5
                ctx.beginPath()
                ctx.moveTo(width - 4, 4)
                ctx.lineTo(4, width - 4)
                ctx.moveTo(width - 4, 10)
                ctx.lineTo(10, width - 4)
                ctx.stroke()
            }
            // 重画以跟随主题切换 / repaint on theme switches
            Connections {
                target: theme
                // `resizeGrip.requestPaint()`, NOT `parent.requestPaint()`: a function inside a
                // `Connections` block does not inherit the enclosing item's dynamic scope, so
                // `parent` is undefined there and the grip never repainted on a theme switch —
                // it kept the colour of whichever theme was active when it was first drawn.
                // 用 `resizeGrip.requestPaint()`，而不是 `parent.requestPaint()`：`Connections`
                // 块内的函数不继承外层元素的动态作用域，因此那里的 `parent` 是未定义的，抓手在主题
                // 切换时从不重绘——它一直保留首次绘制时那个主题的颜色。
                function onChanged() { resizeGrip.requestPaint() }
            }
        }

        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.SizeFDiagCursor
            acceptedButtons: Qt.LeftButton
            onPressed: shell.startSystemResize(Qt.RightEdge | Qt.BottomEdge)
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ---- toolbar -------------------------------------------------------
        //
        // 46px, like the original's `_DragToolbar`: search stretches, then the
        // library actions, then the settings gear. The MouseArea under the
        // controls is what makes the empty areas drag the frameless window.
        // 46px，如同原项目的 `_DragToolbar`：搜索框拉伸，然后是表情库操作，最后是
        // 设置齿轮。控件下方的 MouseArea 使空白区域可以拖动无边框窗口。
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 46
            color: theme.surface

            MouseArea {
                anchors.fill: parent
                onPressed: shell.startSystemMove()
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 8
                anchors.rightMargin: 8
                anchors.topMargin: 6
                anchors.bottomMargin: 6
                spacing: 8

                // The search field, stretched like the original's `SearchBar`
                // (rounded, clear button, focus accent).
                // 搜索框，与原项目的 `SearchBar` 一样拉伸（圆角、清除按钮、聚焦描边）。
                UiTextField {
                    id: searchField
                    Layout.fillWidth: true
                    Layout.preferredHeight: 32
                    placeholderText: bridge.trE("search_placeholder", bridge.languageEpoch)
                    selectByMouse: true
                    // The border, focus ring, radius and text colour now come from `UiTextField`,
                    // which follows SWB's `SwbTextField`. The previous version reimplemented a
                    // 16px-radius pill here, which fought the design tokens.
                    // 边框、聚焦环、圆角与文字色现在来自 `UiTextField`（遵循 SWB 的
                    // `SwbTextField`）。此前的版本在此重画了一个 16px 圆角的胶囊，与设计令牌冲突。
                    onTextEdited: searchTimer.restart()
                    onAccepted: searchTimer.trigger()

                    Timer {
                        id: searchTimer
                        interval: 200
                        onTriggered: bridge.setKeyword(searchField.text)
                    }

                    UiButton {
                        visible: searchField.text !== ""
                        anchors.right: parent.right
                        anchors.rightMargin: 6
                        anchors.verticalCenter: parent.verticalCenter
                        width: 22
                        height: 22
                        // A ghost icon button rather than a hand-drawn circle: the variant IS the
                        // design decision, so a later restyle reaches it automatically.
                        // 用 ghost 图标按钮而不是手画圆形：变体"就是"那个设计决定，因此后续改版会
                        // 自动覆盖到它。
                        variant: "ghost"
                        size: "sm"
                        text: "\u2715"
                        onClicked: {
                            searchField.text = ""
                            bridge.setKeyword("")
                        }
                    }
                }

                // Text-group-only action, shown/hidden by group type exactly
                // like the original toolbar did.
                // 仅文字分组可用的操作，按分组类型显示/隐藏，与原工具栏一致。
                UiButton {
                    id: addTextButton
                    Layout.preferredHeight: 32
                    visible: bridge.groups.currentId >= 0
                             && bridge.groups.typeOf(bridge.groups.currentId)
                                === "text"
                    // Secondary, because importing is the primary action of this screen.
                    // 次要样式，因为"导入"才是本屏的主操作。
                    variant: "outline"
                    text: bridge.trE("new_text_sticker", bridge.languageEpoch)
                    onClicked: bridge.requestDialog("textSticker", "", "")
                }

                UiButton {
                    id: importButton
                    Layout.preferredHeight: 32
                    visible: !(bridge.groups.currentId >= 0
                               && bridge.groups.typeOf(bridge.groups.currentId)
                                  === "text")
                    // The screen's primary action, so it takes the solid `default` variant.
                    // 本屏主操作，因此使用实心的 `default` 变体。
                    variant: "default"
                    text: bridge.trE("import_gif", bridge.languageEpoch)
                    onClicked: importDialog.open()
                }

                // The settings gear: the SAME `setting.svg` the original
                // toolbar used (bundled in `resources/icons/`), 75% of the
                // button like the original's `ICON_PX * 0.75`. The SVG carries
                // no fill, so a `MultiEffect` colorizes it to the theme text
                // colour — the QML counterpart of the original's fill injection.
                // 设置齿轮：与原工具栏同一个 `setting.svg`（随包于
                // `resources/icons/`），取按钮的 75%，同原项目的 `ICON_PX * 0.75`。
                // 该 SVG 不带填充，因此用 `MultiEffect` 着色为主题文字色——等价于
                // 原项目注入 fill 的做法。
                UiButton {
                    id: settingsButton
                    width: 32
                    height: 32
                    // Ghost, so the hover tint comes from the design token instead of a hand-mixed
                    // `theme.surfaceHover`.
                    // 用 ghost，使悬停底色来自设计令牌，而不是手工混出的 `theme.surfaceHover`。
                    variant: "ghost"
                    ToolTip.visible: hovered
                    ToolTip.text: bridge.trE("settings", bridge.languageEpoch)
                    onClicked: shell.openSettings()

                    contentItem: Item {
                        // The provider renders the bundled `setting.svg` with the
                        // theme's text colour injected as the fill (the original
                        // toolbar's approach), so the glyph is always legible on
                        // both themes; the URL carries the theme name, which is
                        // what makes a theme switch reload the image.
                        // 提供器以主题文字色作为填充渲染随包的 `setting.svg`（原工
                        // 具栏的手法），字形在两套主题下都清晰；URL 携带主题名，这
                        // 正是主题切换时图像重载的原因。
                        Image {
                            anchors.centerIn: parent
                            width: 24
                            height: 24
                            // `image://gear/setting/<theme>` — the icon NAME is part of the id.
                            //
                            // This read `image://gear/<theme>` and worked only while the provider
                            // was hardcoded to `setting.svg`. Generalising the provider to take a
                            // name broke this call site silently: the provider read the first
                            // segment as the name, got `dark`, logged
                            //     icon: 'dark' is not a bundled icon; refusing
                            // and returned a TRANSPARENT pixmap, so the settings gear disappeared
                            // with no QML warning at all.
                            // `image://gear/setting/<主题>`——图标"名称"是 id 的一部分。
                            //
                            // 这里过去是 `image://gear/<主题>`，只在提供器写死为 `setting.svg` 时
                            // 有效。把提供器泛化为接受名称后，这个调用点静默失效：提供器把第一段当作
                            // 名称、读到 `dark`，记录
                            //     icon: 'dark' is not a bundled icon; refusing
                            // 并返回"透明"位图，于是设置齿轮消失了，且没有任何 QML 警告。
                            source: "image://gear/setting/" + theme.name
                            sourceSize.width: 48
                            sourceSize.height: 48
                            fillMode: Image.PreserveAspectFit
                            asynchronous: false
                            smooth: true
                        }
                    }
                }
            }

            Rectangle {
                anchors.bottom: parent.bottom
                width: parent.width
                height: 1
                color: theme.borderStrong
            }
        }

        // ---- body: the library --------------------------------------------
        LibraryPage {
            id: libraryPage
            Layout.fillWidth: true
            Layout.fillHeight: true
            app: bridge
        }

        // ---- status bar ---------------------------------------------------
        //
        // The count message on the left; while edit mode is active the multi-
        // select toolbar takes the right side, like the original's status-bar
        // edit bar.
        // 左侧为计数消息；编辑模式激活时多选操作栏占据右侧，如同原项目的状态栏编辑栏。
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: theme.statusHeight
            color: theme.surface

            Rectangle {
                anchors.top: parent.top
                width: parent.width
                height: 1
                color: theme.borderStrong
            }

            Label {
                id: statusLabel
                anchors.left: parent.left
                anchors.leftMargin: theme.spacingLoose
                anchors.verticalCenter: parent.verticalCenter
                // While an import runs, the count message is replaced by the import's progress.
                //
                // The import used to open its own window purely to show a progress bar, which
                // takes the focus away from the library and covers the very grid the stickers
                // are appearing in. The status bar already sits at the bottom of the same
                // window and already displays a summary, so it is the natural place: no extra
                // surface, no focus change, and the user sees both the stickers arriving and
                // the numbers moving.
                //
                // `app.importer` is guarded because this binding is evaluated while the page is
                // still being built, when `app` may not be assigned yet.
                // 导入进行时，计数消息被导入进度取代。
                //
                // 导入曾单开一个窗口，只为显示一个进度条，那会把焦点从素材库夺走、并遮住贴纸正在出现
                // 的那个网格。状态栏本就在同一个窗口底部、本就在显示一条摘要，因此它是自然的位置：
                // 没有额外界面、不改变焦点，用户同时看到贴纸到达与数字变化。
                //
                // `app.importer` 带防护，因为该绑定在页面仍在构建时就会被求值，此时 `app` 可能还未赋值。
                text: {
                    var importer = bridge.importer
                    if (importer && importer.running) {
                        return bridge.trE("importing_short", bridge.languageEpoch)
                               + " " + importer.done + " / " + importer.total
                    }
                    return bridge.status
                }
                color: theme.textMuted
                font.pixelSize: theme.fontSizeSmall
                elide: Text.ElideRight
                width: parent.width - 2 * theme.spacingLoose
                       - (editBar.visible ? editBar.width : 0)
                       - (importBar.visible ? importBar.width : 0)
            }

            // The bar itself, drawn UNDER the label's text so the numbers stay readable on top
            // of the fill rather than beside it.
            // 进度条本身绘制在标签文字"下方"，使数字在填充之上仍可读，而不是被挤到旁边。
            Rectangle {
                id: importBar
                anchors.left: parent.left
                anchors.leftMargin: theme.spacingLoose
                anchors.verticalCenter: parent.verticalCenter
                height: 3
                width: (statusLabel.width) * Math.max(0.0, Math.min(1.0,
                                                                  bridge.importer
                                                                  ? bridge.importer.fraction : 0.0))
                visible: bridge.importer ? bridge.importer.running : false
                color: theme.accent
                radius: 2
                z: -1
            }

            RowLayout {
                id: editBar
                anchors.right: parent.right
                anchors.rightMargin: theme.spacing
                anchors.verticalCenter: parent.verticalCenter
                spacing: theme.spacingTight
                visible: libraryPage.editMode

                Label {
                    text: bridge.selectedCountLabel(bridge.stickers.selectedCount)
                    color: theme.text
                    font.pixelSize: theme.fontSizeSmall
                }

                component EditButton: Button {
                    id: editBtn
                    height: 22
                    flat: true

                    background: Rectangle {
                        radius: 4
                        color: parent.enabled
                               ? (parent.hovered ? theme.surfaceHover
                                                  : theme.surfaceAlt)
                               : "transparent"
                        border.color: theme.border
                        border.width: parent.enabled ? 1 : 0
                    }
                    contentItem: Label {
                        text: editBtn.text
                        color: editBtn.enabled ? theme.text : theme.textMuted
                        font.pixelSize: theme.fontSizeSmall
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 10
                        rightPadding: 10
                    }
                }

                EditButton {
                    text: bridge.trE("edit_select_all", bridge.languageEpoch)
                    onClicked: bridge.stickers.selectAll()
                }
                EditButton {
                    text: bridge.trE("edit_delete", bridge.languageEpoch)
                    enabled: bridge.stickers.selectedCount > 0
                    onClicked: editDeleteDialog.open()
                }
                EditButton {
                    id: editMoveButton
                    text: bridge.trE("edit_move", bridge.languageEpoch)
                    enabled: bridge.stickers.selectedCount > 0
                    // Opens the SAME dialog the card menu uses, rather than a menu whose
                    // contents are built from a model. The menu version went through three
                    // separate failure modes and the dialog has none of them.
                    // 打开与卡片菜单"同一个"对话框，而不是一个内容由模型构建的菜单。菜单版本经历了
                    // 三种各自独立的失败方式，而对话框一种都没有。
                    onClicked: libraryPage.openMoveForSelection()
                }
                EditButton {
                    text: bridge.trE("edit_exit", bridge.languageEpoch)
                    onClicked: libraryPage.exitEditMode()
                }
            }

            // The move picker for the edit-mode SELECTION. The same dialog the card menu uses;
            // only the target list differs, and the dialog asks the bridge for the right one.
            // 编辑模式"选择"的移动选取器。与卡片菜单同一个对话框；只有目标列表不同，而对话框会
            // 向桥询问正确的那一个。
            MoveDialog {
                id: moveSelectionDialog
                popupType: Popup.Item
                app: bridge
            }

            // The timeout is armed HERE rather than in Python, because a timer is
            // a presentation concern: a different front-end may show the message
            // until the next one arrives.
            // 超时在"此处"武装而非在 Python 里，因为定时器是呈现层关注点：另一个前端可能
            // 让消息一直显示到有下一条。
            Timer {
                id: statusTimer
                onTriggered: bridge.showStatus("", 0)
            }

            Connections {
                target: bridge
                function onStatusMessage(message, timeout) {
                    if (timeout > 0) {
                        statusTimer.interval = timeout
                        statusTimer.restart()
                    } else {
                        statusTimer.stop()
                    }
                }
            }
        }
    }

    // ---- drop files onto the window to import -----------------------------
    //
    // The original window accepted file drops and imported them into the current
    // group; this is the same route, expressed with a `DropArea`.
    // 原窗口接受文件拖放并把它们导入当前分组；同一条路由，用 `DropArea` 表达。
    DropArea {
        anchors.fill: parent
        onDropped: function (drop) {
            if (!drop.hasUrls)
                return
            var paths = []
            for (var i = 0; i < drop.urls.length; i++) {
                var path = bridge.urlToPath(drop.urls[i])
                if (path !== "")
                    paths.push(path)
            }
            if (paths.length > 0)
                bridge.importFiles(paths)
        }
    }

    // ---- dialogs ----------------------------------------------------------
    Dialog {
        // Item 型弹窗：在场景内绘制。无边框工具窗口上 Window 型原生弹窗不显示。
        // Item-type popup: rendered inside the scene, because a Window-type
        // native popup does not show on a frameless tool window.
        popupType: Popup.Item
        id: messageDialog
        anchors.centerIn: parent
        modal: true
        standardButtons: Dialog.Ok
        width: Math.min(460, shell.width - 60)

        property string bodyText: ""

        contentItem: Label {
            text: messageDialog.bodyText
            wrapMode: Text.WordWrap
            color: theme.text
            font.pixelSize: theme.fontSizeBody
        }

        background: Rectangle {
            color: theme.surface
            radius: theme.radiusLarge
            border.color: theme.border
        }
    }

    // ---- dialogs requested by the bridge ----------------------------------
    Connections {
        target: bridge
        function onDialogRequested(kind, title, body) {
            if (kind === "import") {
                importDialog.open()
                return
            }
            if (kind === "update") {
                updateDialog.openWithCheck(false)
                return
            }
            if (kind === "groupCreate") {
                groupDialog.openCreate()
                return
            }
            if (kind === "groupRename") {
                groupDialog.openRename(bridge.currentGroupId())
                return
            }
            if (kind === "groupDelete") {
                groupDialog.openDelete(bridge.currentGroupId())
                return
            }
            if (kind === "textSticker") {
                var target = bridge.textStickerTarget()
                if (!target.ok) {
                    bridge.showStatus(bridge.trE("text_only_group_needed", bridge.languageEpoch), 3500)
                    return
                }
                textDialog.openCreateFor(target.id)
                return
            }
            messageDialog.title = title
            messageDialog.bodyText = body
            messageDialog.standardButtons = Dialog.Ok
            messageDialog.open()
        }
    }

    // The edit bar's delete: one confirmation for the whole selection. The card
    // menu's delete (with its copies count) lives on the library page, next to
    // the menu that raises it.
    // 编辑操作栏的删除：对整个选择的一次确认。卡片菜单的删除（带副本计数）位于表情库
    // 页，就在提出它的菜单旁边。
    Dialog {
        // Item 型弹窗：在场景内绘制。无边框工具窗口上 Window 型原生弹窗不显示。
        // Item-type popup: rendered inside the scene, because a Window-type
        // native popup does not show on a frameless tool window.
        popupType: Popup.Item
        id: editDeleteDialog
        anchors.centerIn: parent
        modal: true
        standardButtons: Dialog.Yes | Dialog.Cancel
        title: bridge.trE("confirm_delete", bridge.languageEpoch)
        width: Math.min(380, shell.width - 60)

        contentItem: Label {
            // `trArgsE`, not `trE`. `trE` only looks the key up and returns the raw string,
            // so the `{count}` placeholder was printed literally:
            //
            //     确定删除选中的 {count} 个表情包吗?
            //
            // A confirmation that does not say how many will be deleted is worse than no
            // confirmation, because it asks the user to approve an unknown quantity. The
            // `.replace` is belt-and-braces: if the translation is missing its placeholder
            // the count is still shown rather than silently dropped.
            // 用 `trArgsE` 而不是 `trE`。`trE` 只查键并返回原始字符串，因此 `{count}` 占位符被
            // 原样打印：
            //
            //     确定删除选中的 {count} 个表情包吗?
            //
            // 一条不说明将删除多少条的确认提示比没有确认更糟，因为它要求用户批准一个未知数量。
            // `.replace` 是双保险：若译文缺少占位符，数量仍会显示而不是被静默丢弃。
            text: {
                var message = bridge.trArgsE(
                    "edit_delete_confirm",
                    JSON.stringify({ count: bridge.stickers.selectedCount }),
                    bridge.languageEpoch)
                if (message.indexOf("{count}") >= 0) {
                    message = message.replace("{count}",
                                              String(bridge.stickers.selectedCount))
                }
                return message
            }
            wrapMode: Text.WordWrap
            color: theme.text
            font.pixelSize: theme.fontSizeBody
        }

        background: Rectangle {
            color: theme.surface
            radius: theme.radiusLarge
            border.color: theme.border
        }

        onAccepted: bridge.deleteSelection()
    }

    ImportDialog {
        id: importDialog
        app: bridge
    }

    GroupDialog {
        id: groupDialog
        app: bridge
    }

    TextStickerDialog {
        id: textDialog
        app: bridge
    }

    UpdateDialog {
        id: updateDialog
        app: bridge
    }

    SettingsWindow {
        id: settingsWindow
        app: bridge
    }

    // ---- tray and global hotkey -------------------------------------------
    //
    // Both are SYSTEM surfaces, so they are wired here rather than on a page.
    //
    // 两者都是"系统级"界面，因此在此接线而不是在某个页面上。

    Component.onCompleted: {
        // The frameless flags and the restored geometry must land before the
        // first show, or the window flashes with a title bar.
        // 无边框标志与恢复的几何必须在首次显示"之前"落地，否则窗口会带着标题栏闪现。
        shell.flags = shell.baseFlags
                      | (bridge.alwaysOnTop ? Qt.WindowStaysOnTopHint : 0)
        var geometry = bridge.loadWindowGeometry()
        if (geometry && geometry.width > 0 && geometry.height > 0) {
            shell.x = geometry.x
            shell.y = geometry.y
            shell.width = geometry.width
            shell.height = geometry.height
        } else {
            // First launch: centre on the screen, like the original's
            // `_restore_geometry` did. Guarded: headless platforms (offscreen)
            // report no usable screen, and a thrown binding here would break the
            // whole startup chain in `Component.onCompleted`.
            // 首次启动：在屏幕上居中，与原版的 `_restore_geometry` 一致。带防护：无头
            // 平台（offscreen）报不出可用屏幕，而这里绑定抛错会打断 Component.onCompleted
            // 里的整条启动链。
            var screen = shell.screen
            if (screen && screen.availableVirtualWidth > 0) {
                shell.x = screen.availableVirtualX
                          + (screen.availableVirtualWidth - shell.width) / 2
                shell.y = screen.availableVirtualY
                          + (screen.availableVirtualHeight - shell.height) / 2
            }
        }
        shell.show()
        bridge.applyWindowEffects(shell)
        bridge.attach_window(shell)
        bridge.showStatus(bridge.trE("ready", bridge.languageEpoch), 1500)
    }

    Connections {
        target: bridge
        function onToggleWindowRequested() {
            if (shell.visible)
                shell.hide()
            else {
                shell.show()
                shell.raise()
                shell.requestActivate()
            }
        }
        // Explicit show/hide, for a compositor key binding that uses two keys rather than one
        // toggle. Kept separate from the toggle because a binding that says "show" must work even
        // when the window is already visible - collapsing both into a toggle would HIDE it, which
        // is the opposite of what the user bound.
        // 显式的显示/隐藏，供使用两个按键而非单一切换键的合成器键绑定。与切换分开，因为一条写着
        // "显示"的绑定必须在窗口已可见时也有效——把两者合并成切换反而会"隐藏"它，与用户的绑定意图
        // 相反。
        function onShowWindowRequested() {
            shell.show()
            shell.raise()
            shell.requestActivate()
        }
        function onHideWindowRequested() {
            shell.hide()
        }
        function onOpenSettingsRequested() {
            shell.show()
            shell.raise()
            shell.openSettings()
        }
        function onAlwaysOnTopChanged() {
            // The setting must reach the LIVE window, not only the next launch:
            // changing the flags re-creates the native window, which hides it —
            // re-showing is part of the change.
            // 该设置必须作用于"活着的"窗口而非下次启动：改标志会重建原生窗口并使其
            // 隐藏——重新显示是这次变更的一部分。
            shell.flags = shell.baseFlags
                          | (bridge.alwaysOnTop ? Qt.WindowStaysOnTopHint : 0)
            shell.show()
            bridge.applyWindowEffects(shell)
        }
    }
}
