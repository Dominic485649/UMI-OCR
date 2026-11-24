// ================================================
// =============== 导航页（识别工作台） ===============
// ================================================

import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

import ".."
import "../.."
import "../../Widgets"

TabPage {
    id: naviPage
    ListModel { id: pageModel }

    // 保留独立链接文本与安装版本；入口焦点和悬停均不替换它们。
    property string welcomeText: qsTr("项目链接")+`   •   [`+qsTr("仓库链接")+`](${UmiAbout.url.home})    [`+qsTr("插件拓展")+`](${UmiAbout.url.plugins})    [`+qsTr("问题反馈")+`](${UmiAbout.url.issue})`
    property string introText: welcomeText
    onWelcomeTextChanged: introText = welcomeText
    property var installedVersions: versionLines()
    readonly property bool hasOcrPlugin: qmlapp.globalConfigs.pluginStates.some(
        info => info.state === "ready" && (info.capabilities || []).indexOf("ocr") >= 0)

    function versionLines() {
        const lines = ["Umi-OCR  " + UmiAbout.version.string]
        for(const info of qmlapp.globalConfigs.pluginStates) {
            const state = info.state === "ready" ? "" : "  [" + qmlapp.globalConfigs.pluginStateText(info.state) + "]"
            lines.push((info.name || info.id) + "  " + (info.version || "-") + state)
        }
        return lines
    }
    function initData() {
        introText = welcomeText
        pageModel.clear()
        const f = qmlapp.tab.infoList
        for(let i = 1, c = f.length; i < c; i++) {
            pageModel.append({
                "title": f[i].title,
                "intro": f[i].intro,
                "pageKey": f[i].key || "",
                "infoIndex": i,
            })
        }
    }
    function summaryFor(intro) {
        // 页面简介的首段是用途，后面的格式／协议清单留在对应页面说明中。
        return String(intro || "").replace(/^#{1,6}[^\n]*(?:\n|$)/, "").trim()
            .split(/\n\s*\n/)[0].replace(/`/g, "")
    }
    function openTask(infoIndex) {
        const index = qmlapp.tab.getTabPageIndex(naviPage)
        if(index >= 0) qmlapp.tab.changeTabPage(index, infoIndex)
    }
    // 键盘到达视口外入口时滚动呈现焦点，不把可聚焦误当成可见。
    function revealItem(item) {
        const view = workbench.contentItem
        if(!view || view.contentY === undefined) return
        const top = item.mapToItem(view.contentItem, 0, 0).y
        let y = view.contentY
        if(top < y) y = top
        else if(top + item.height > y + view.height) y = top + item.height - view.height
        view.contentY = Math.max(0, Math.min(y, Math.max(0, view.contentHeight - view.height)))
    }
    function openSettings(groupKey) {
        const page = qmlapp.tab.openTabPageByKey("GlobalConfigsPage")
        if(page && groupKey) page.focusGroup(groupKey)
    }
    Connections {
        target: qmlapp.tab
        function onInfoListChanged() { naviPage.initData() }
    }
    Component.onCompleted: initData()

    ScrollView {
        id: workbench
        objectName: "navigationWorkbench"
        anchors.fill: parent
        anchors.margins: size_.spacing * 2
        contentWidth: availableWidth
        clip: true

        Column {
            width: workbench.availableWidth
            spacing: size_.spacing * 2

            Column {
                width: parent.width
                spacing: size_.smallSpacing
                Text_ {
                    width: parent.width
                    text: qsTr("欢迎使用 Umi-OCR")
                    font.pixelSize: size_.largeText * 1.25
                    font.bold: true
                    wrapMode: Text.Wrap
                }
                Text_ {
                    width: parent.width
                    text: qsTr("请选择功能页")
                    color: theme.subTextColor
                    wrapMode: Text.Wrap
                }
            }

            GridLayout {
                id: workspaceLayout
                width: parent.width
                columns: width >= size_.line * 46 ? 2 : 1
                columnSpacing: size_.spacing * 2
                rowSpacing: size_.spacing * 2

                // 标题跨列，下方两区从同一行上沿开始；窄窗仍按功能区、版本卡片排列。
                Text_ {
                    objectName: "navigationTaskHeading"
                    Layout.columnSpan: workspaceLayout.columns
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: qsTr("功能页")
                    font.bold: true
                    wrapMode: Text.Wrap
                }

                GridLayout {
                    id: taskGrid
                    objectName: "navigationTaskGrid"
                    Layout.fillWidth: true
                    Layout.preferredWidth: size_.line * 29
                    Layout.minimumWidth: 0
                    Layout.fillHeight: false
                    Layout.alignment: Qt.AlignTop
                    columns: width >= size_.line * 28 ? 2 : 1
                    columnSpacing: size_.spacing
                    rowSpacing: size_.spacing
                    Repeater {
                        model: pageModel
                        NavigationTask {
                            objectName: "navigationTask_" + pageKey
                            onActiveFocusChanged: if(activeFocus) naviPage.revealItem(this)
                            visible: pageKey !== "GlobalConfigsPage" && pageKey !== "About"
                            Layout.fillWidth: true
                            Layout.preferredWidth: 1
                            Layout.fillHeight: true
                            Layout.minimumWidth: 0
                            text_: title
                            description: naviPage.summaryFor(intro)
                            onClicked: naviPage.openTask(infoIndex)
                        }
                    }
                }

                Panel {
                    objectName: "navigationVersionCard"
                    Layout.fillWidth: true
                    Layout.preferredWidth: size_.line * 17
                    Layout.minimumWidth: 0
                    Layout.fillHeight: false
                    Layout.alignment: Qt.AlignTop
                    implicitHeight: environmentColumn.implicitHeight + size_.spacing * 4
                    Column {
                        id: environmentColumn
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: size_.spacing * 2
                        spacing: size_.spacing
                        Text_ {
                            width: parent.width
                            text: qsTr("当前版本")
                            font.bold: true
                            wrapMode: Text.Wrap
                        }
                        Column {
                            id: versionBlock
                            width: parent.width
                            spacing: size_.smallSpacing
                            Repeater {
                                model: installedVersions
                                Text_ {
                                    width: versionBlock.width
                                    text: modelData
                                    color: theme.subTextColor
                                    wrapMode: Text.Wrap
                                    textFormat: Text.PlainText
                                }
                            }
                        }
                        Text_ {
                            objectName: "navigationSetupHint"
                            width: parent.width
                            text: naviPage.hasOcrPlugin
                                ? qsTr("请在 OCR 功能页选择识别模型；全局设置用于配置模型与设备。")
                                : qsTr("请先安装 OCR 插件，再到全局设置启用。")
                            color: theme.subTextColor
                            wrapMode: Text.Wrap
                        }
                        Button_ {
                            objectName: "navigationPluginSettings"
                            width: parent.width
                            text_: qsTranslate("GlobalConfigs", "插件管理")
                            activeFocusOnTab: true
                            onActiveFocusChanged: if(activeFocus) naviPage.revealItem(this)
                            borderWidth: visualFocus ? 2 : 0
                            borderColor: theme.specialTextColor
                            Accessible.name: text_
                            onClicked: naviPage.openSettings("plugins")
                        }
                    }
                }
            }

            Flow {
                width: parent.width
                spacing: size_.spacing
                Button_ {
                    text_: qsTranslate("PagesManager", "全局设置")
                    activeFocusOnTab: true
                    onActiveFocusChanged: if(activeFocus) naviPage.revealItem(this)
                    borderWidth: visualFocus ? 2 : 0
                    borderColor: theme.specialTextColor
                    Accessible.name: text_
                    onClicked: naviPage.openSettings("")
                }
                Button_ {
                    text_: qsTranslate("PagesManager", "关于")
                    activeFocusOnTab: true
                    onActiveFocusChanged: if(activeFocus) naviPage.revealItem(this)
                    borderWidth: visualFocus ? 2 : 0
                    borderColor: theme.specialTextColor
                    Accessible.name: text_
                    onClicked: qmlapp.tab.openTabPageByKey("About")
                }
            }
            MarkdownView {
                id: introView
                width: parent.width
                height: Math.max(size_.line * 2.5, Math.min(contentHeight, size_.line * 7))
                text: introText
            }
        }
    }
    DropArea_ {
        id: addDocsDropArea
        anchors.fill: parent
        tips: qsTr("请打开对应标签页（如批量OCR、批量文档），再拖入文件。")
    }
}
