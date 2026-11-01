// The About page: the icon, then who made it, then the licence, then the repository.
//
// # The shape, and why it is centred rather than two columns
//
// This page used to be a two-column report: identity and licence on the left, a live
// capability table on the right. The capability table had already moved to its own settings
// category ("系统能力"), so what remained was a centred identity card trying to look like a
// document — the licence text was squeezed into a narrow column and the page had no focal
// point.
//
// It is now a single centred column in the order a person reads an about box: icon, name,
// version, author, licence, repository. The icon is the largest element, which gives the page
// the focal point it was missing.
//
// # The icon is rendered through the SVG provider
//
// `gifmanager.png` is 498 KB and fixed in size; the bundled `setting.svg` machinery already
// renders a bundled SVG at the requested size with the theme's colour injected, so the app icon
// and the GitHub mark both go through it. That keeps them crisp at any size and correct in both
// themes, and means no 498 KB bitmap has to be loaded to draw a 64 px icon.
//
// 关于页：图标、制作者、许可、仓库。
//
// # 这样的形状，以及为什么用居中而不是两列
//
// 本页过去是一份两列报告：左边是身份与许可，右边是实时能力表。能力表已经迁到它自己的设置分类
// （"系统能力"），于是剩下的是一个试图扮成文档的居中身份卡——许可文本被挤在窄列里，而页面没有视觉
// 焦点。
//
// 现在它是单一居中列，按人阅读"关于"框的顺序排列：图标、名称、版本、作者、许可、仓库。图标是最大的
// 元素，这给了页面此前缺失的焦点。
//
// # 图标经 SVG 提供器渲染
//
// `gifmanager.png` 有 498 KB 且尺寸固定；随包的 `setting.svg` 机制已经能把随包 SVG 按请求尺寸渲染、
// 并注入主题色，因此应用图标与 GitHub 标记都走它。这使它们在任意尺寸下都清晰、在两种主题下都正确，
// 也意味着不必为了画一个 64px 图标去加载 498 KB 的位图。

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components/ui"

Item {
    id: page
    required property var app

    // Card edge for the app icon. Named so the image and the label block agree on one number.
    // 应用图标的边长。命名使图像与文字块对同一个数字达成一致。
    readonly property int iconSize: 72
    readonly property int markSize: 18

    // A `Flickable` with an explicitly sized `contentHeight`, NOT a `ScrollView`.
    //
    // The first version put a `ColumnLayout` inside a `ScrollView` and positioned it with `x`
    // and `y` plus a fixed `width`. `ScrollView` derives its scrollable range from the content
    // item's IMPLICIT size, and a layout whose position is set by hand has no implicit height
    // to offer - so the scroll range was wrong and the page could not be scrolled to the bottom,
    // cutting off the repository link. The `Layout.fillHeight` spacer inside made it worse by
    // reporting a height that did not match the content.
    //
    // A `Flickable` makes the contract explicit: `contentHeight` is the column's own implicit
    // height, so the scroll range is exactly the content.
    // 用 `Flickable` 并显式指定 `contentHeight`，而不是 `ScrollView`。
    //
    // 第一个版本把 `ColumnLayout` 放进 `ScrollView`，用 `x`、`y` 加固定 `width` 定位。`ScrollView`
    // 依据内容元素的"隐式"尺寸推导可滚动范围，而位置由手工设置的布局没有隐式高度可提供——于是滚动
    // 范围是错的、页面无法滚到底部，仓库链接被截断。里面那个 `Layout.fillHeight` 弹簧使情况更糟，
    // 它报告的高度与内容并不相符。
    //
    // `Flickable` 使契约显式：`contentHeight` 就是该列自身的隐式高度，因此滚动范围恰好等于内容。
    Flickable {
        id: flick
        anchors.fill: parent
        clip: true
        contentWidth: width
        contentHeight: column.implicitHeight + 4 * theme.spacingLoose
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: UiScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: column
            // Full width, with a narrower CONTENT width applied to the wide children below.
            // Centring one narrow column inside a full-width layout is what lets a single width
            // describe both the layout and the reading measure.
            // 整宽，而"较窄的内容宽度"应用到下面那些宽子项上。在整宽布局内居中一个窄列，正是让
            // 一个宽度同时描述布局与阅读行长的做法。
            width: flick.width
            x: 0
            y: theme.spacingLoose * 2
            spacing: theme.spacing

            // The reading measure for prose and the icon block, so the licence is not a
            // 900 px line.
            // 段落文本与图标块的阅读行长，使许可不是一行 900px。
            readonly property int measure: Math.min(420, flick.width - 2 * theme.spacingLoose)

            // ---- the icon ------------------------------------------------
            Image {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: page.iconSize
                Layout.preferredHeight: page.iconSize
                // The app icon: the same `gifmanager.ico` the window and the tray use, rendered
                // from the PNG beside it at the requested size.
                // 应用图标：与窗口和托盘同一个 `gifmanager.ico`，按请求尺寸由旁边的 PNG 渲染。
                source: "image://appicon/" + theme.name
                sourceSize.width: page.iconSize
                sourceSize.height: page.iconSize
                fillMode: Image.PreserveAspectFit
                smooth: true
            }

            Label {
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: theme.spacingTight
                text: page.app ? page.app.appName : ""
                color: theme.textStrong
                font.pixelSize: theme.fontSizeHeading
                font.bold: true
            }

            Label {
                Layout.alignment: Qt.AlignHCenter
                // The version and the platform on one line: the platform is worth stating,
                // because half this application's behaviour is platform-dependent.
                // 版本与平台在同一行：平台值得说明，因为本应用一半的行为都与平台相关。
                text: {
                    if (!page.app)
                        return ""
                    return "v" + page.app.version
                           + (page.app.platformName
                              ? "   \u00b7   " + page.app.platformName : "")
                }
                color: theme.textMuted
                font.pixelSize: theme.fontSizeBody
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.topMargin: theme.spacingLoose
                height: 1
                color: theme.borderStrong
            }

            // ---- the author ----------------------------------------------
            Label {
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: theme.spacingLoose
                text: page.app ? page.app.trE("made_by", page.app.languageEpoch) : ""
                color: theme.textMuted
                font.pixelSize: theme.fontSizeSmall
            }

            Label {
                Layout.alignment: Qt.AlignHCenter
                text: "LwoSnow"
                color: theme.text
                font.pixelSize: theme.fontSizeTitle
                font.bold: true
            }

            // ---- the licence ---------------------------------------------
            Label {
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: theme.spacingLoose
                text: page.app ? page.app.trE("license_group", page.app.languageEpoch) : ""
                color: theme.textMuted
                font.pixelSize: theme.fontSizeSmall
            }

            // A framed, LEFT-ALIGNED monospace block, the way a Markdown fenced code block
            // renders.
            //
            // It was a centred prose label. That is wrong for this text twice over: a licence is
            // a quotation, and a quotation reads as a block with a fixed left edge, not as
            // centred prose; and the text contains its own line structure (the copyright line,
            // then the permission paragraph), which centring destroys by giving every line a
            // different indent.
            //
            // `TextEdit` with `readOnly` and `selectByMouse` rather than a `Label`: a licence is
            // the one piece of text on this page a user may want to COPY, and a `Label` cannot
            // be selected. `textFormat: PlainText` because the string contains no markup and
            // must not be interpreted as any.
            // 一个带边框、"左对齐"的等宽块，形如 Markdown 的围栏代码块渲染出来的样子。
            //
            // 它过去是居中的段落标签。对这个文本而言这错了两次：许可是引文，而引文读起来是一个
            // 左边缘固定的块而不是居中段落；并且该文本自带行结构（版权行，然后是授权段落），居中的
            // 做法会给每一行不同的缩进，从而破坏它。
            //
            // 用 `TextEdit` 加 `readOnly`、`selectByMouse`，而不是 `Label`：许可是本页唯一用户
            // 可能想"复制"的文字，而 `Label` 无法选中。`textFormat: PlainText` 是因为该字符串
            // 不含标记，也绝不能被当作标记解释。
            Rectangle {
                Layout.fillWidth: true
                Layout.maximumWidth: column.measure
                Layout.alignment: Qt.AlignHCenter
                Layout.bottomMargin: theme.spacing
                implicitHeight: licenseText.implicitHeight + 2 * theme.spacing
                color: theme.surfaceAlt
                radius: theme.radius
                border.color: theme.border
                border.width: 1

                TextEdit {

    // No context menu: see `UiTextField` for why. Only right clicks are taken, so editing and
    // selection are untouched.
    // 不显示上下文菜单：理由见 `UiTextField`。只接管右键，因此编辑与选择不受影响。
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.RightButton
        onPressed: function (mouse) { mouse.accepted = true }
    }

                    id: licenseText
                    anchors.fill: parent
                    anchors.margins: theme.spacing
                    readOnly: true
                    selectByMouse: true
                    textFormat: TextEdit.PlainText
                    wrapMode: TextEdit.Wrap
                    text: page.app ? page.app.licenseText : ""
                    color: theme.text
                    // A monospace family, because that is what makes the block read as code
                    // rather than as body copy — and because the licence's own line breaks then
                    // line up instead of drifting.
                    // 等宽字体族，因为那正是让该块读起来像代码而不是正文的原因——也因为这样许可自身
                    // 的换行会对齐而不会漂移。
                    font.family: "Consolas, Menlo, DejaVu Sans Mono, monospace"
                    font.pixelSize: theme.fontSizeSmall
                    selectionColor: theme.uiColors.selected
                    selectedTextColor: theme.uiColors.selectedForeground
                }
            }

            // ---- the repository, last, as the closing line ---------------
            //
            // NO `Layout.fillHeight` spacer here any more. It reported a height that did not
            // match the content, which is what made the enclosing `ScrollView` compute the wrong
            // scroll range - so the bottom of the page, which is exactly this link, could not be
            // reached.
            // 此处"不再"有 `Layout.fillHeight` 弹簧。它报告的高度与内容不符，正是它让外层
            // `ScrollView` 算出错误的滚动范围——于是页面底部（恰好就是这个链接）无法到达。
            Rectangle {
                Layout.fillWidth: true
                Layout.maximumWidth: column.measure
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: theme.spacingLoose
                height: 1
                color: theme.borderStrong
            }

            // A button rather than a bare label: the URL is the one thing on this page a user
            // may want to act on, and a clickable target says so.
            // 用按钮而不是裸标签：URL 是本页唯一可能让用户想"操作"的东西，而可点击的目标会表明这
            // 一点。
            UiButton {
                id: repoButton
                Layout.alignment: Qt.AlignHCenter
                Layout.topMargin: theme.spacing
                Layout.bottomMargin: theme.spacingLoose
                flat: true
                onClicked: if (page.app) page.app.openUrl(page.app.repositoryUrl)

                contentItem: RowLayout {
                    spacing: theme.spacingTight

                    Image {
                        Layout.preferredWidth: page.markSize
                        Layout.preferredHeight: page.markSize
                        // `sourceSize` asks the provider for exactly this many pixels. WITHOUT it
                        // Qt renders the SVG at its intrinsic size and scales the result, and a
                        // 24-unit viewBox in an 18 px slot came out clipped rather than fitted.
                        // `sourceSize` 让提供器渲染恰好这么多像素。"没有"它时 Qt 会按 SVG 的固有
                        // 尺寸渲染再缩放结果，而 24 单位 viewBox 放进 18px 的位置会显示不全而不是被
                        // 适配。
                        source: "image://gear/github/" + theme.name
                        sourceSize.width: page.markSize
                        sourceSize.height: page.markSize
                        fillMode: Image.PreserveAspectFit
                        smooth: true
                    }

                    Label {
                        text: page.app ? page.app.repositoryUrl : ""
                        color: repoButton.hovered ? theme.text : theme.textMuted
                        font.pixelSize: theme.fontSizeSmall
                        verticalAlignment: Text.AlignVCenter
                    }
                }

                background: Rectangle {
                    radius: theme.radius
                    color: repoButton.hovered ? theme.surfaceHover : "transparent"
                }
            }
        }
    }
}
