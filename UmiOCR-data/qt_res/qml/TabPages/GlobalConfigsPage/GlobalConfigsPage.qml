// ==============================================
// =============== 功能页：全局设置 ===============
// ==============================================

import QtQuick 2.15
import QtQuick.Controls 2.15

import ".."
import "../../Widgets"

TabPage {
    id: tabPage
    property QtObject confComp: qmlapp.globalConfigs.panelComponent
    property var groupList: []
    property string requestedGroupKey: ""
    function refreshGroupList() {
        groupList = confComp.getGroupList()
        Qt.callLater(updateGroupPosition)
    }
    function updateGroupPosition() {
        if(requestedGroupKey) {
            // 纯本体或禁用全部 OCR 插件时没有模型组，回退到可安装／启用的插件组。
            if(!confComp.scrollToGroupKey(requestedGroupKey)) confComp.scrollToGroupKey("plugins")
            requestedGroupKey = ""
        }
        else confComp.syncCurrentGroup()
    }
    function focusGroup(key) {
        requestedGroupKey = key
        qmlapp.globalConfigs.ensurePanel()
        Qt.callLater(updateGroupPosition)
    }
    onShowPage: {
        qmlapp.globalConfigs.ensurePanel()
        refreshGroupList()
    }

    Connections {
        target: qmlapp.globalConfigs
        function onPanelRebuilt() { tabPage.refreshGroupList() }
    }

    DoubleRowLayout {
        anchors.fill: parent
        initSplitterX: Math.min(size_.line * 15, width * 0.3)

        // 左面板：设置标题列表
        leftItem: Panel {
            anchors.fill: parent
            // 上：标题栏
            Item {
                id: leftTop
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.bottom: leftBottom.top
                anchors.margins: size_.spacing
                ScrollView {
                    id: scrollView
                    anchors.fill: parent
                    anchors.margins: size_.spacing
                    clip: true
                    Column {
                        anchors.fill: parent
                        Repeater {
                            model: groupList
                            Button_ {
                                visible: !modelData.advanced || confComp.advanced
                                text_: modelData.title
                                toolTip: modelData.title
                                width: scrollView.width
                                height: size_.line * 2.5
                                activeFocusOnTab: true
                                bold_: confComp.currentGroupIndex === index
                                textColor_: confComp.currentGroupIndex === index ? theme.specialTextColor : theme.textColor
                                bgColor_: confComp.currentGroupIndex === index ? theme.coverColor2 : "transparent"
                                borderWidth: visualFocus ? 2 : 0
                                borderColor: theme.specialTextColor
                                Accessible.name: modelData.title
                                Accessible.description: toolTip
                                onClicked: {
                                    confComp.scrollToGroup(index)
                                }
                            }
                        }
                    }
                }
            }
            // 下：控制按钮栏
            Item {
                id: leftBottom
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: size_.line * 2
                anchors.margins: size_.spacing
            }
        }

        // 右面板：设置面板
        rightItem: Panel {
            anchors.fill: parent
            Item {
                anchors.fill: parent
                anchors.margins: size_.spacing
                Component.onCompleted: { // 将全局设置UI的父级重定向过来
                    // 就算本页面删除，全局UI也不会被删，只会丢失父级
                    confComp.parent = this
                    confComp.ctrlBar.parent = leftBottom
                    confComp.ctrlBar.anchors.fill = leftBottom
                }
            }
        }
    }

    // 字体设置面板
    FontPanel {
        anchors.fill: parent
        z: 10
    }
}
