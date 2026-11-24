// =============================================
// =============== 外部本地文件拖入 ===============
// =============================================

import QtQuick 2.15

DropArea {
    id: fileDropArea
    property var callback: undefined
    property bool enable: true
    property string tips: qsTr("松手放入文件")
    property bool acceptableDrag: false
    signal dropObserved(string phase, bool accepted, int urlCount)
    keys: ["text/uri-list"]

    function localPaths(event) {
        if(!enable || event.source || !event.hasUrls || !event.urls.length) return []
        // 不把 http、剪贴板文本等交给目录扫描；编码转换仍由既有 QUrl 工具处理。
        for(let i = 0; i < event.urls.length; i++) {
            if(!String(event.urls[i]).toLowerCase().startsWith("file:")) return []
        }
        const paths = qmlapp.utilsConnector.QUrl2String(event.urls)
        return paths && paths.length === event.urls.length ? paths : []
    }
    function inspectDrag(event) {
        const accepted = localPaths(event).length > 0
        event.accepted = accepted
        acceptableDrag = accepted
        return accepted
    }
    onEntered: function(drag) {
        const accepted = inspectDrag(drag)
        dropObserved("entered", accepted, drag.hasUrls ? drag.urls.length : 0)
    }
    onPositionChanged: function(drag) { inspectDrag(drag) }
    onExited: {
        acceptableDrag = false
        dropObserved("exited", false, 0)
    }
    onEnableChanged: { if(!enable) acceptableDrag = false }
    onDropped: function(drop) {
        acceptableDrag = false
        drop.accepted = false
        const paths = localPaths(drop)
        if(paths.length === 0 || !callback) {
            dropObserved("dropped", false, drop.hasUrls ? drop.urls.length : 0)
            return
        }
        try {
            const result = callback(paths)
            if(result !== false) {
                // 导入只读取文件，不接受会暗示移动原文件的 MoveAction。
                drop.accept(Qt.CopyAction)
                dropObserved("dropped", true, paths.length)
                return
            }
        }
        catch(error) {
            qmlapp.popup.simple(qsTr("文件未导入"), qsTr("无法接收本次拖入，请重试。"))
        }
        dropObserved("dropped", false, paths.length)
    }

    // 局部、不接管鼠标的落点提示；不用全局 modal 遮罩覆盖拖放目标。
    Rectangle {
        anchors.fill: parent
        visible: fileDropArea.acceptableDrag
        color: "transparent"
        border.width: 2
        border.color: theme.specialTextColor
        radius: size_.panelRadius
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: size_.spacing
            width: dropText.implicitWidth + size_.spacing * 2
            height: size_.line * 1.5
            radius: size_.btnRadius
            color: theme.specialBgColor
            Text_ {
                id: dropText
                anchors.centerIn: parent
                text: fileDropArea.tips
            }
        }
    }
}
