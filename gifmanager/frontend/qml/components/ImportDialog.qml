// The import dialog: pick files or a folder, choose the target group, watch it run.
//
// Importing is the one operation in this interface that can take minutes, so it is
// the one place with a progress bar and a cancel button. Everything it needs comes
// from `bridge.importer`, whose progress is exposed as PROPERTIES: a progress bar
// bound to `bridge.importer.fraction` updates itself, with no handler copying
// values around.
//
// 导入对话框：选择文件或文件夹、选择目标分组、观察它运行。
//
// 导入是本界面中唯一可能耗时数分钟的操作，因此也是唯一带进度条与取消按钮的地方。它需要的
// 一切来自 `bridge.importer`，其进度以"属性"暴露：绑定到 `bridge.importer.fraction` 的
// 进度条自行更新，无需任何处理器搬运取值。

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "./ui"
import "../components/ui"

UiDialog {
    // Item 型弹窗：在场景内绘制。无边框工具窗口上 Window 型原生弹窗不显示。
    // Item-type popup: rendered inside the scene, because a Window-type
    // native popup does not show on a frameless tool window.
    id: importDialog

    required property var app
    // The image groups an import may target, refreshed on every open.
    // 导入可去的图片分组，每次打开时刷新。
    property var targets: []

    anchors.centerIn: parent
    modal: true
    width: Math.min(520, parent ? parent.width - 60 : 460)
    title: importDialog.app ? importDialog.app.trE("import_stickers", importDialog.app.languageEpoch) : ""
    // The standard buttons are replaced by explicit ones in `footer`, because the
    // Accept button must be disabled until something is selected and a Cancel button
    // must appear only while a job runs.
    // 标准按钮由 `footer` 中的显式按钮取代，因为"开始"按钮必须在选中东西之前禁用，而"取消"
    // 按钮只在任务运行时出现。
    standardButtons: Dialog.NoButton

    // Every reference to `app` is guarded, and the guard is written as an EXPLICIT
    // comparison.
    //
    // A chain like `a && a.b && a.b.c` yields `undefined` — not `false` — when `a` is
    // unset, and assigning `undefined` to a `bool` property raises "Unable to assign
    // [undefined] to bool". A dialog is constructed as a child of the window, so its
    // bindings are evaluated while the parent is still assigning `app`, which means
    // this is the normal case rather than an edge one.
    //
    // 每一处对 `app` 的引用都带防护，且防护写成"显式比较"。
    //
    // 当 `a` 未设置时，`a && a.b && a.b.c` 这样的链会产出 `undefined` 而非 `false`，
    // 而把 `undefined` 赋给 `bool` 属性会抛 "Unable to assign [undefined] to bool"。
    // 对话框作为窗口的子项被构建，因此其绑定在父级仍在赋值 `app` 时就会求值——这意味着这是
    // 常态而非边界情况。
    readonly property var importer: (importDialog.app === undefined
                                     || importDialog.app === null)
                                    ? null : importDialog.app.importer
    readonly property bool busy: importDialog.importer !== null
                                 && importDialog.importer !== undefined
                                 && importDialog.importer.running === true

    closePolicy: importDialog.busy ? Popup.NoAutoClose : Popup.CloseOnEscape

    // Collected paths, as a list the bridge can take directly.
    // 已收集的路径，作为桥可直接接收的列表。
    property var pendingPaths: []
    // Cached label text, so the binding does not depend on a function call that
    // could throw while `app` is still unset.
    // 缓存的标签文本，使绑定不依赖一个在 `app` 尚未赋值时可能抛错的函数调用。
    property string sourceLabel: ""
    property int sourceCount: 0

    // NOT named `reset`: `Dialog` already has a `reset()` method, and a local
    // function of the same name is reported as "Duplicate method name: invalid
    // override of property change signal or superclass signal" — a message that
    // says nothing about the actual problem.
    // "不"叫 `reset`：`Dialog` 已有 `reset()` 方法，同名的本地函数会被报告为
    // "Duplicate method name: invalid override of property change signal or
    // superclass signal"——一条完全没有说明真实问题的消息。
    function clearSelection() {
        pendingPaths = []
        sourceLabel = ""
        sourceCount = 0
    }

    function setPaths(paths) {
        pendingPaths = paths
        sourceCount = paths.length
        if (paths.length === 0)
            sourceLabel = ""
        else if (paths.length === 1)
            sourceLabel = importDialog.app.fileNameOf(paths[0])
        else
            sourceLabel = importDialog.app.selectedCountLabel(paths.length)
    }

    // ---- file and folder pickers ------------------------------------------
    //
    // `FileDialog` with `fileMode: OpenFiles` covers multi-select; a folder needs a
    // separate `FolderDialog` because Qt does not allow both in one dialog. Two
    // buttons is the honest presentation of that constraint.
    // `FileDialog` 配 `fileMode: OpenFiles` 覆盖多选；文件夹需要单独的 `FolderDialog`，
    // 因为 Qt 不允许在同一个对话框里两者兼得。两个按钮是这一约束的诚实呈现。

    FileDialog {
        id: filePicker
        title: importDialog.app ? importDialog.app.trE("import_pick_files", importDialog.app.languageEpoch) : ""
        fileMode: FileDialog.OpenFiles
        nameFilters: importDialog.app
                     ? [importDialog.app.importFileFilter(), "All files (*)"]
                     : ["All files (*)"]
        onAccepted: {
            var paths = []
            for (var i = 0; i < selectedFiles.length; i++)
                paths.push(importDialog.app.urlToPath(selectedFiles[i]))
            importDialog.setPaths(paths)
        }
    }

    FolderDialog {
        id: folderPicker
        title: importDialog.app ? importDialog.app.trE("import_pick_folder", importDialog.app.languageEpoch) : ""
        onAccepted: importDialog.setPaths(
            [importDialog.app.urlToPath(selectedFolder)])
    }

    contentItem: ColumnLayout {
        spacing: theme.spacing

        Label {
            Layout.fillWidth: true
            text: importDialog.app ? importDialog.app.trE("import_explain", importDialog.app.languageEpoch) : ""
            color: theme.textMuted
            font.pixelSize: theme.fontSizeSmall
            wrapMode: Text.WordWrap
        }

        // ---- source -------------------------------------------------------
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.spacing

            UiButton {
                text: importDialog.app ? importDialog.app.trE("import_pick_files", importDialog.app.languageEpoch)
                                       : ""
                enabled: !importDialog.busy
                onClicked: filePicker.open()
            }
            UiButton {
                text: importDialog.app ? importDialog.app.trE("import_pick_folder", importDialog.app.languageEpoch)
                                       : ""
                enabled: !importDialog.busy
                onClicked: folderPicker.open()
            }
            Label {
                Layout.fillWidth: true
                text: importDialog.sourceLabel !== ""
                      ? importDialog.sourceLabel
                      : (importDialog.app
                         ? importDialog.app.trE("import_nothing_selected", importDialog.app.languageEpoch) : "")
                color: importDialog.sourceCount > 0 ? theme.text : theme.textMuted
                font.pixelSize: theme.fontSizeSmall
                elide: Text.ElideMiddle
            }
        }

        // ---- target group -------------------------------------------------
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.spacing

            Label {
                text: importDialog.app ? importDialog.app.trE("import_target_group", importDialog.app.languageEpoch)
                                       : ""
                color: theme.text
                font.pixelSize: theme.fontSizeBody
            }
            ComboBox {
                id: targetGroup
                Layout.fillWidth: true
                enabled: !importDialog.busy
                textRole: "name"
                valueRole: "id"
                // Re-read the targets on EVERY open: a group created after the
                // window was built must appear here (the old binding evaluated
                // once at construction and stayed stale forever).
                // 每次打开都重读目标列表：窗口构建之后新建的分组必须出现在这里
                // （旧绑定只在构建时求值一次，永远过期）。
                model: importDialog.targets

                onModelChanged: {
                    if (!importDialog.app || count === 0)
                        return
                    var preferred = importDialog.app.currentImportGroupId()
                    var found = indexOfValue(preferred)
                    currentIndex = found >= 0 ? found : 0
                }
            }
        }

        // ---- progress -----------------------------------------------------
        ColumnLayout {
            Layout.fillWidth: true
            spacing: theme.spacingTight
            visible: importDialog.busy

            ProgressBar {
                Layout.fillWidth: true
                // Bound to the property, so it advances without any refresh call.
                // 绑定到属性，因此无需任何刷新调用即可推进。
                from: 0
                to: 1
                value: importDialog.importer ? importDialog.importer.fraction : 0
            }
            Label {
                text: importDialog.importer
                      ? (importDialog.importer.done + " / "
                         + importDialog.importer.total)
                      : ""
                color: theme.textMuted
                font.pixelSize: theme.fontSizeSmall
            }
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
                text: importDialog.app ? importDialog.app.trE("cancel", importDialog.app.languageEpoch) : ""
                visible: importDialog.busy
                onClicked: importDialog.importer.cancel()
            }
            UiButton {
                text: importDialog.app ? importDialog.app.trE("import_start", importDialog.app.languageEpoch) : ""
                enabled: !importDialog.busy && importDialog.pendingPaths.length > 0
                onClicked: {
                    // The picker's choice DECIDES the target — the old call ignored
                    // it entirely, which is why imports "landed in 全部".
                    // 选择器的决定“就是”目标——旧调用完全忽略它，这正是导入“落进
                    // 全部”的原因。
                    var report = importDialog.app.importFilesInto(
                        importDialog.pendingPaths, targetGroup.currentValue)
                    if (!report.started) {
                        importDialog.app.showStatus(
                            importDialog.app.trE("import_could_not_start", importDialog.app.languageEpoch), 3000)
                    } else {
                        importDialog.close()
                    }
                }
            }
            UiButton {
                text: importDialog.app ? importDialog.app.trE("close", importDialog.app.languageEpoch) : ""
                enabled: !importDialog.busy
                onClicked: importDialog.close()
            }
        }
    }


    onOpened: {
        clearSelection()
        // Refresh the target list at open time (new groups included).
        // 打开时刷新目标列表（包含新建分组）。
        targets = importDialog.app ? importDialog.app.importTargets() : []
    }
}
