// The update dialog: what is available, download it, then apply it.
//
// Three things it says plainly rather than implying:
//
//   * whether the download was SIGNATURE-verified or only checksum-verified — the two
//     are not the same, and "we check the hash" reads like the stronger one;
//   * whether THIS build can replace itself at all, because a source checkout cannot
//     and offering a button that fails is worse than explaining;
//   * on Linux, that the package manager owns the installation, so the file is
//     downloaded and verified but NOT applied behind the user's package manager.
//
// # Every guard yields a real boolean
//
// `a && a.b` evaluates to `undefined` — not `false` — when `a` is unset, and assigning
// `undefined` to a `bool` property raises "Unable to assign [undefined] to bool". A
// dialog is constructed as a child of the window, so these bindings run while the
// parent is still assigning `app`. Every guard below is therefore written as an
// explicit comparison rather than relying on truthiness. That looks verbose and is the
// only form that survives construction order.
//
// 更新对话框：有什么可用、下载它、然后应用它。
//
// 它明确说明而非暗示三件事：
//
//   * 下载是经"签名"校验还是仅经"校验和"校验——两者不同，而"我们检查了哈希"读起来像更强的
//     那个；
//   * "本构建"能否替换自身，因为源码目录不能，而提供一个会失败的按钮比解释更糟；
//   * 在 Linux 上，包管理器拥有该安装，因此文件被下载并校验，但"不会"在用户的包管理器背后被
//     应用。
//
// # 每处防护都产出真正的布尔值
//
// 当 `a` 未设置时，`a && a.b` 求值为 `undefined` 而非 `false`，而把 `undefined` 赋给 `bool`
// 属性会抛 "Unable to assign [undefined] to bool"。对话框作为窗口的子项被构建，因此这些绑定
// 在父级仍在赋值 `app` 时就会运行。因此下面每处防护都写成显式比较，而不是依赖真值性。这看起来
// 啰嗦，而它是唯一能在构建顺序下存活的形式。

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "./ui"
import "../components/ui"

UiDialog {
    // Item 型弹窗：在场景内绘制。无边框工具窗口上 Window 型原生弹窗不显示。
    // Item-type popup: rendered inside the scene, because a Window-type
    // native popup does not show on a frameless tool window.
    id: updateDialog

    required property var app

    anchors.centerIn: parent
    modal: true
    width: Math.min(520, parent ? parent.width - 60 : 480)
    standardButtons: Dialog.NoButton

    // The service, or null before `app` is assigned.
    //
    // A local alias rather than repeating `app.updater` in twenty bindings: one place
    // to get the guard right instead of twenty.
    // 该服务，或在 `app` 被赋值之前为 null。
    //
    // 用本地别名而不是在二十处绑定里重复 `app.updater`：一处把防护写对，而不是二十处。
    readonly property var updater: (updateDialog.app === undefined
                                    || updateDialog.app === null)
                                   ? null : updateDialog.app.updater
    readonly property bool hasUpdater: updateDialog.updater !== null
                                       && updateDialog.updater !== undefined
    readonly property bool busy: updateDialog.hasUpdater
                                 && updateDialog.updater.busy === true
    readonly property bool available: updateDialog.hasUpdater
                                      && updateDialog.updater.updateAvailable === true
    readonly property bool checking: updateDialog.hasUpdater
                                     && updateDialog.updater.phase === "checking"
    readonly property bool downloading: updateDialog.hasUpdater
                                        && updateDialog.updater.phase === "downloading"
    readonly property bool checked: updateDialog.hasUpdater
                                    && updateDialog.updater.checked === true
    readonly property bool hasError: updateDialog.hasUpdater
                                     && updateDialog.updater.error !== ""
    readonly property bool signedManifest: updateDialog.hasUpdater
                                           && updateDialog.updater.signed === true
    readonly property bool cannotSelfUpdate: updateDialog.hasUpdater
                                             && updateDialog.updater.canSelfUpdate
                                                === false
    readonly property bool staged: updateDialog.hasUpdater
                                   && updateDialog.updater.staged === true

    closePolicy: updateDialog.busy ? Popup.NoAutoClose : Popup.CloseOnEscape
    // Assigned rather than bound to a local property: `Dialog.title` already exists, and
    // declaring one would shadow it instead of setting it.
    // 赋值而非绑定到本地属性：`Dialog.title` 已存在，再声明一个会遮蔽它而不是设置它。
    title: updateDialog.app ? updateDialog.app.trE("update_title", updateDialog.app.languageEpoch) : ""

    function openWithCheck(force) {
        open()
        if (updateDialog.hasUpdater && !updateDialog.checked)
            updateDialog.updater.check(force === true)
    }

    contentItem: ColumnLayout {
        spacing: theme.spacing

        // ---- current version ----------------------------------------------
        Label {
            Layout.fillWidth: true
            text: (updateDialog.app ? updateDialog.app.trE("update_current_version", updateDialog.app.languageEpoch)
                                    : "")
                  + ": "
                  + (updateDialog.hasUpdater
                     ? updateDialog.updater.currentVersion : "")
            color: theme.textMuted
            font.pixelSize: theme.fontSizeSmall
        }

        // ---- checking -----------------------------------------------------
        RowLayout {
            Layout.fillWidth: true
            spacing: theme.spacing
            visible: updateDialog.checking
            BusyIndicator {
                running: true
                width: 20
                height: 20
            }
            Label {
                Layout.fillWidth: true
                text: updateDialog.app ? updateDialog.app.trE("update_checking", updateDialog.app.languageEpoch) : ""
                color: theme.text
                font.pixelSize: theme.fontSizeBody
            }
        }

        // ---- no update ----------------------------------------------------
        Label {
            Layout.fillWidth: true
            visible: updateDialog.checked && !updateDialog.available
                     && !updateDialog.busy && !updateDialog.hasError
            text: updateDialog.app ? updateDialog.app.trE("update_up_to_date", updateDialog.app.languageEpoch) : ""
            color: theme.text
            font.pixelSize: theme.fontSizeBody
            wrapMode: Text.WordWrap
        }

        // ---- the error, if any --------------------------------------------
        Label {
            Layout.fillWidth: true
            visible: updateDialog.hasError
            text: updateDialog.hasError ? updateDialog.updater.error : ""
            color: theme.danger
            font.pixelSize: theme.fontSizeSmall
            wrapMode: Text.WordWrap
        }

        // ---- what is available --------------------------------------------
        ColumnLayout {
            Layout.fillWidth: true
            spacing: theme.spacingTight
            visible: updateDialog.available

            Label {
                Layout.fillWidth: true
                text: (updateDialog.app ? updateDialog.app.trE("update_available", updateDialog.app.languageEpoch) : "")
                      + ": "
                      + (updateDialog.hasUpdater
                         ? updateDialog.updater.latestVersion : "")
                color: theme.textStrong
                font.pixelSize: theme.fontSizeTitle
                font.bold: true
            }

            Label {
                Layout.fillWidth: true
                visible: updateDialog.hasUpdater
                         && updateDialog.updater.published !== ""
                text: updateDialog.hasUpdater ? updateDialog.updater.published : ""
                color: theme.textMuted
                font.pixelSize: theme.fontSizeSmall
            }

            // The verification level, stated rather than implied. An unsigned manifest
            // proves the download is intact and says nothing about its origin, and the
            // colour says which of the two this is.
            // 校验级别，明说而非暗示。未签名的清单证明下载完好，而对它的来源毫无说明，颜色标出
            // 这是两者中的哪一个。
            Label {
                Layout.fillWidth: true
                text: updateDialog.signedManifest
                      ? (updateDialog.app
                         ? updateDialog.app.trE("update_verified_signed", updateDialog.app.languageEpoch) : "")
                      : (updateDialog.app
                         ? updateDialog.app.trE("update_verified_checksum_only", updateDialog.app.languageEpoch) : "")
                color: updateDialog.signedManifest ? theme.textMuted : "#D08A2C"
                font.pixelSize: theme.fontSizeSmall
                wrapMode: Text.WordWrap
            }

            ScrollView {
                Layout.fillWidth: true
                Layout.preferredHeight: 100
                clip: true
                visible: updateDialog.hasUpdater
                         && updateDialog.updater.notes !== ""
                Label {
                    width: updateDialog.width - 60
                    text: updateDialog.hasUpdater ? updateDialog.updater.notes : ""
                    color: theme.text
                    font.pixelSize: theme.fontSizeSmall
                    wrapMode: Text.WordWrap
                }
            }
        }

        // ---- download progress --------------------------------------------
        ColumnLayout {
            Layout.fillWidth: true
            spacing: theme.spacingTight
            visible: updateDialog.downloading

            ProgressBar {
                Layout.fillWidth: true
                from: 0
                to: 1
                value: updateDialog.hasUpdater
                       ? updateDialog.updater.fraction : 0
            }
            Label {
                text: updateDialog.hasUpdater
                      ? (Math.round(updateDialog.updater.received / 1024) + " / "
                         + Math.round(updateDialog.updater.total / 1024) + " KiB")
                      : ""
                color: theme.textMuted
                font.pixelSize: theme.fontSizeSmall
            }
        }

        // ---- why this build cannot self-update ----------------------------
        Label {
            Layout.fillWidth: true
            visible: updateDialog.cannotSelfUpdate
                     && updateDialog.updater.selfUpdateReason !== ""
            text: updateDialog.hasUpdater
                  ? updateDialog.updater.selfUpdateReason : ""
            color: "#D08A2C"
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
                text: updateDialog.app ? updateDialog.app.trE("update_check", updateDialog.app.languageEpoch) : ""
                enabled: !updateDialog.busy
                onClicked: if (updateDialog.hasUpdater) updateDialog.updater.check(true)
            }
            UiButton {
                text: updateDialog.app ? updateDialog.app.trE("update_download", updateDialog.app.languageEpoch) : ""
                visible: updateDialog.available && !updateDialog.downloading
                enabled: !updateDialog.busy
                onClicked: {
                    var result = updateDialog.updater.download()
                    if (!result.ok)
                        updateDialog.app.showStatus(result.reason, 4000)
                }
            }
            UiButton {
                // Only offered when the platform can actually do it. On Linux the package
                // manager owns the files, so this button is hidden rather than present and
                // failing.
                // 只在平台确实能做到时提供。Linux 上包管理器拥有这些文件，因此该按钮被隐藏，而不是
                // 存在却失败。
                text: updateDialog.app ? updateDialog.app.trE("update_install", updateDialog.app.languageEpoch) : ""
                visible: updateDialog.available && !updateDialog.cannotSelfUpdate
                         && updateDialog.staged
                onClicked: {
                    var result = updateDialog.updater.install()
                    updateDialog.app.showStatus(
                        result.ok ? updateDialog.app.trE("update_install_started", updateDialog.app.languageEpoch)
                                  : (result.reason || ""), 5000)
                }
            }
            UiButton {
                text: updateDialog.app ? updateDialog.app.trE("close", updateDialog.app.languageEpoch) : ""
                enabled: !updateDialog.busy
                onClicked: updateDialog.close()
            }
        }
    }

}
