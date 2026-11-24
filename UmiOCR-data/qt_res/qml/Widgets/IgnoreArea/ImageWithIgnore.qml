// ====================================================
// =============== 可框选的增强Image组件 ===============
// ====================================================

import QtQuick 2.15
import QtQuick.Controls 2.15
import "../ImageViewer"

ImageScale {
    id: iRoot
    objectName: "ignoreAreaCanvas"
    property bool showOverlay: true // 显示叠加层
    property int lineWidth: 1 // 线宽
    property color crossLineColor: "#00f91a" // 十字指示器的颜色
    readonly property bool drawingIgnore: mouseArea.drawing

    beforeShow: () => {
        cancelSelection()
        textBoxes = [] // 清空旧文本块
    }
    // 展示文本块
    function showTextBoxes(res) {
        beforeShow()
        // 提取文本框
        if(res.code == 100 && res.data.length > 0) {
            let tbs = []
            for(let i in res.data) {
                const d = res.data[i]
                const info = {
                    x: d.box[0][0],
                    y: d.box[0][1],
                    width: d.box[2][0] - d.box[0][0],
                    height: d.box[2][1] - d.box[0][1],
                    text: d.text,
                }
                tbs.push(info)
            }
            textBoxes = tbs
        }
    }
    // 显示/隐藏叠加层
    function switchOverlay() {
        showOverlay = !showOverlay
    }

    // 撤销、清空均替换数组引用，通知区域数量和 Repeater 刷新。
    function revokeIg() {
        cancelSelection()
        if(ig1Boxes.length > 0)
            ig1Boxes = ig1Boxes.slice(0, -1)
    }
    function clearIg() {
        cancelSelection()
        ig1Boxes = []
    }
    // 保留原有四角坐标格式，预览和最终保存共用此转换。
    function getIgnoreArea() {
        let areas = []
        for(let i=0; i<ig1Boxes.length; i++) {
            const b = ig1Boxes[i]
            const x1 = Math.round(b.x), y1 = Math.round(b.y)
            const x2 = Math.round(b.x + b.width), y2 = Math.round(b.y + b.height)
            if(isFinite(x1) && isFinite(y1) && isFinite(x2) && isFinite(y2)
                    && x2 > x1 && y2 > y1)
                areas.push([[x1, y1], [x2, y1], [x2, y2], [x1, y2]])
        }
        return areas.length > 0 ? areas : undefined
    }

    function canSelect() {
        return imageSW > 0 && imageSH > 0 && scale > 0
                && showImage.status === Image.Ready
    }
    function containsSelectionPoint(x, y) {
        return isFinite(x) && isFinite(y) && x >= 0 && y >= 0
                && x <= width && y <= height
    }
    // 取消不能留下可在下一次 release 时提交的草稿。
    function cancelSelection() {
        if(!mouseArea || !cross) return
        mouseArea.drawing = false
        mouseArea.startX = mouseArea.startY = 0
        mouseArea.endX = mouseArea.endY = 0
        cross.showPointer = false
        cross.ax = cross.ay = cross.aw = cross.ah = 0
    }
    function beginSelection(button, x, y) {
        cancelSelection()
        if(button !== Qt.RightButton || !canSelect() || !containsSelectionPoint(x, y))
            return false
        mouseArea.startX = mouseArea.endX = x
        mouseArea.startY = mouseArea.endY = y
        mouseArea.drawing = true
        return true
    }
    function updateSelection(x, y) {
        if(!mouseArea.drawing || !canSelect() || !containsSelectionPoint(x, y)) {
            cancelSelection()
            return false
        }
        mouseArea.endX = x
        mouseArea.endY = y
        cross.ax = Math.min(mouseArea.startX, x)
        cross.ay = Math.min(mouseArea.startY, y)
        cross.aw = Math.abs(x - mouseArea.startX)
        cross.ah = Math.abs(y - mouseArea.startY)
        return true
    }
    function finishSelection(button, x, y) {
        if(button !== Qt.RightButton || !updateSelection(x, y)) {
            cancelSelection()
            return false
        }
        // 复用 ImageScale 的原图映射，不另外换算 DPI、缩放或平移。
        const p1 = imagePointAt(mouseArea.startX, mouseArea.startY)
        const p2 = imagePointAt(mouseArea.endX, mouseArea.endY)
        const x1 = Math.max(0, Math.min(imageSW, Math.min(p1[0], p2[0])))
        const y1 = Math.max(0, Math.min(imageSH, Math.min(p1[1], p2[1])))
        const x2 = Math.max(0, Math.min(imageSW, Math.max(p1[0], p2[0])))
        const y2 = Math.max(0, Math.min(imageSH, Math.max(p1[1], p2[1])))
        cancelSelection()
        // 至少一个原图像素，避免零面积或保存取整后退化的矩形。
        if(!isFinite(x1) || !isFinite(y1) || !isFinite(x2) || !isFinite(y2)
                || x2 - x1 < 1 || y2 - y1 < 1)
            return false
        ig1Boxes = ig1Boxes.concat([{
            "x": x1,
            "y": y1,
            "width": x2 - x1,
            "height": y2 - y1,
        }])
        return true
    }

    onVisibleChanged: if(!visible) cancelSelection()
    onEnabledChanged: if(!enabled) cancelSelection()
    onScaleChanged: cancelSelection()
    onImageSWChanged: if(imageSW <= 0) cancelSelection()
    onImageSHChanged: if(imageSH <= 0) cancelSelection()
    Connections {
        target: iRoot.showImage
        function onSourceChanged() { iRoot.cancelSelection() }
    }

    property var textBoxes: [] // 文本块列表
    property var ig1Boxes: [] // 忽略区域1

    // 文本框叠加层
    overlayLayer: Item {
        id: oRoot
        anchors.fill: parent
        visible: showOverlay
        property real borderWidth: Math.max(1, 1/iRoot.scale)

        // 文本块
        Repeater {
            model: textBoxes
            Rectangle {
                x: modelData.x
                y: modelData.y
                width: modelData.width
                height: modelData.height
                color: "#00000000"
                border.width: oRoot.borderWidth
                border.color: "#000"
                Rectangle {
                    anchors.fill: parent
                    anchors.margins: oRoot.borderWidth
                    color: "#22000000"
                    border.width: oRoot.borderWidth
                    border.color: "#FFF"
                }
            }
        }

        // 忽略区域1
        Repeater {
            model: ig1Boxes
            Rectangle {
                x: modelData.x
                y: modelData.y
                width: modelData.width
                height: modelData.height
                color: "#99000000"
                border.width: oRoot.borderWidth
                border.color: "#FFFF00"
            }
        }
    }
    // 十字线与当前选区：草稿仅存在于显式右键绘制状态。
    Item {
        id: cross
        anchors.fill: parent
        clip: true
        property bool showPointer: false
        property real px: 0
        property real py: 0
        property real ax: 0
        property real ay: 0
        property real aw: 0
        property real ah: 0
        Rectangle {
            visible: cross.showPointer
            color: crossLineColor
            anchors.left: parent.left
            anchors.right: parent.right
            y: cross.py
            height: lineWidth
        }
        Rectangle {
            visible: cross.showPointer
            color: crossLineColor
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            x: cross.px
            width: lineWidth
        }
        Rectangle {
            visible: mouseArea.drawing && width > 0 && height > 0
            x: cross.ax
            y: cross.ay
            width: cross.aw
            height: cross.ah
            border.width: lineWidth
            border.color: crossLineColor
            color: "#00000000"
        }
    }

    MouseArea {
        id: mouseArea
        objectName: "ignoreAreaDrawArea"
        anchors.fill: parent
        hoverEnabled: true
        // 左键交给底层 Flickable 平移，不参与区域绘制。
        acceptedButtons: Qt.RightButton
        preventStealing: true
        property bool drawing: false
        property real startX: 0
        property real startY: 0
        property real endX: 0
        property real endY: 0

        onPressed: function(mouse) {
            mouse.accepted = iRoot.beginSelection(mouse.button, mouse.x, mouse.y)
        }
        onPositionChanged: function(mouse) {
            if(!iRoot.canSelect()) {
                iRoot.cancelSelection()
                return
            }
            if(drawing) {
                if(mouse.buttons & Qt.RightButton)
                    iRoot.updateSelection(mouse.x, mouse.y)
                else
                    iRoot.cancelSelection()
            }
            else {
                cross.showPointer = mouse.buttons === Qt.NoButton
                        && iRoot.containsSelectionPoint(mouse.x, mouse.y)
                cross.px = mouse.x
                cross.py = mouse.y
            }
        }
        onReleased: function(mouse) {
            iRoot.finishSelection(mouse.button, mouse.x, mouse.y)
        }
        onCanceled: iRoot.cancelSelection()
        onExited: iRoot.cancelSelection()
    }
}
