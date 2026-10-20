// =============================================
// =============== 单个文本块组件 ===============
// =============================================

import QtQuick 2.15
import QtQuick.Controls 2.15
import ".."

Item {
    id: tRoot
    property string text: ""
    property var points: [[0, 0], [1, 0], [1, 1], [0, 1]]
    readonly property var polygon: {
        const local = []
        for(let point of points)
            local.push([point[0] - x, point[1] - y])
        return local
    }
    readonly property real textWidth: polygon.length === 4
        ? Math.hypot(polygon[1][0] - polygon[0][0], polygon[1][1] - polygon[0][1]) : width
    readonly property real textHeight: polygon.length === 4
        ? (Math.hypot(polygon[3][0] - polygon[0][0], polygon[3][1] - polygon[0][1])
           + Math.hypot(polygon[2][0] - polygon[1][0], polygon[2][1] - polygon[1][1])) / 2 : height
    readonly property real textAngle: polygon.length === 4
        ? Math.atan2(polygon[1][1] - polygon[0][1], polygon[1][0] - polygon[0][0]) * 180 / Math.PI : 0

    // 颜色固定，不受主题影响
    property color bgColor: "#99000000"
    property color textColor: "#FFFFFF"

    // 外部接口，重设字体和组件大小
    property alias textEdit: textEdit // 文本组件
    property string end: "" // 结尾间隔符

    function resetSize() {
        textEdit.resetFontSize()
    }

    // 传入一个相对于item的坐标，返回该坐标的文本序号。
    function where(item, mx, my) {
        const textPoint = textEdit.mapFromItem(item, mx, my)
        const textPos = textEdit.positionAt(textPoint.x, textPoint.y)
        return textPos
    }

    function containsPoint(item, mx, my) {
        const point = mapFromItem(item, mx, my)
        let inside = false
        for(let i=0, j=polygon.length-1; i<polygon.length; j=i++) {
            const xi=polygon[i][0], yi=polygon[i][1]
            const xj=polygon[j][0], yj=polygon[j][1]
            const crosses = ((yi > point.y) !== (yj > point.y))
                && point.x < (xj-xi) * (point.y-yi) / (yj-yi) + xi
            if(crosses) inside = !inside
        }
        return inside
    }

    // 背景
    Canvas {
        id: bgRect
        anchors.fill: parent
        onPaint: {
            const context = getContext("2d")
            context.clearRect(0, 0, width, height)
            if(tRoot.polygon.length < 3) return
            context.beginPath()
            context.moveTo(tRoot.polygon[0][0], tRoot.polygon[0][1])
            for(let i=1; i<tRoot.polygon.length; i++)
                context.lineTo(tRoot.polygon[i][0], tRoot.polygon[i][1])
            context.closePath()
            context.fillStyle = tRoot.bgColor
            context.fill()
        }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        Connections {
            target: tRoot
            function onPolygonChanged() { bgRect.requestPaint() }
            function onBgColorChanged() { bgRect.requestPaint() }
        }
    }
    // 结尾标识
    Icon_ {
        icon: "line_feed"
        visible: end == "\n" // 标记换行符
        anchors.left: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 1
        height: Math.min(tRoot.height * 0.8 ,tRoot.width * 0.8 , size_.line * 2)
        width: height
        color: theme.subTextColor
    }
    // 文本
    TextEdit_ {
        id: textEdit
        x: tRoot.polygon.length === 4 ? tRoot.polygon[0][0] : 0
        y: tRoot.polygon.length === 4 ? tRoot.polygon[0][1] : 0
        width: Math.max(1, tRoot.textWidth)
        height: Math.max(1, tRoot.textHeight)
        rotation: tRoot.textAngle
        transformOrigin: Item.TopLeft
        color: textColor
        readOnly: true // 只读
        selectByMouse: false // 禁止选择文本
        selectByKeyboard: false
        persistentSelection: true // 丢失焦点时，保留选区
        font.pixelSize: 10 // 初始：10像素
        
        // 重设字体大小，以适合组件大小
        function resetFontSize() {
            text = tRoot.text
            font.pixelSize = 10
            font.letterSpacing = 0
            // 初次调整，利用初始文字面积与容器面积的比值，计算字体大小
            let s = 1
            if(contentWidth>0 && contentHeight>0)
                s = (width * height) / (contentWidth * contentHeight)
            let ps = Math.max(1, font.pixelSize * Math.sqrt(s))
            font.pixelSize = ps
            // 长文本只能缩小字体，不能扩大 OCR 几何框。
            for(let i=0; i<20 && (contentWidth > width || contentHeight > height); i++) {
                font.pixelSize = Math.max(1, font.pixelSize * 0.9)
            }
            // 二次调整：如果当前只有一行，则优化字间距
            if(lineCount === 1 && text.length > 0) {
                const s = (width - contentWidth) / text.length
                if(s > 0) {
                    font.letterSpacing = s
                }
            }
        }
    }
}
