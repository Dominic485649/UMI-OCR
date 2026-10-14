// ==================================================
// =============== 可缩放的图片预览组件 ===============
// ==================================================

import QtQuick 2.15
import QtQuick.Controls 2.15

import ".."

Rectangle {
    id: iRoot
    // ========================= 【接口】 =========================

    // 可设置
    property real scaleMax: 2.0 // 比例上下限
    property real scaleMin: 0.1 // 比例上下限
    property Item overlayLayer // 图片叠加层
    property var border: bRect.border // 边框
    // 只读
    property alias showImage: showImage // 图片组件
    property real scale: 1.0 // 图片缩放比例
    property int imageSW: 0 // 图片原始宽高
    property int imageSH: 0
    // 子类重写
    property var beforeShow: undefined // 展示图片之前执行的操作

    // 设置图片源，展示一张图片
    function setSource(source) {
        if(source) {
            // 特殊字符#替换为%23
            if(source.startsWith("file:///") && source.includes("#"))
                source = source.replace(new RegExp("#", "g"), "%23");
            showImage.source = source // 设置源
        }
        else
            showImage.source = ""
    }

    // 传入路径，展示图片
    function showPath(path) {
        if(beforeShow) beforeShow()
        showImage.showPath(path)
    }

    // 传入imgID，展示图片
    function showImgID(imgID) {
        if(beforeShow) beforeShow()
        showImage.showImgID(imgID)
    }

    // 清空展示
    function clear() {
        if(beforeShow) beforeShow()
        // showImage.clear()
        showImage.source = ""
        imageSW = imageSH = 0
    }

    // 复制当前图片
    function copyImage() {
        if(showImage.source == "") return
        const res = qmlapp.imageManager.copyImage(showImage.source)
        if(res === "[Success]")
            qmlapp.popup.simple(qsTr("复制图片"), "")
        else
            qmlapp.popup.simple(qsTr("复制图片失败"), res)
    }

    // 用系统默认应用打开图片
    function openImage() {
        if(showImage.source == "") return
        const res = qmlapp.imageManager.openImage(showImage.source)
        if(res === "[Success]")
            qmlapp.popup.simple(qsTr("打开图片"), "")
        else
            qmlapp.popup.simple(qsTr("打开图片失败"), res)
    }

    // 保存当前图片
    function saveImage() {
        if(showImage.source == "") return
        saveDialog.open()
    }

    FileDialog_ {
        id: saveDialog
        title: qsTr("保存图片")
        selectExisting: false
        selectFolder: false
        nameFilters: ["*.png", "*.jpg"]
        onAccepted: {
            if(!fileUrl) {
                console.log("文件对话框：未选择任何文件")
                return
            }
            let filePath = fileUrl
            const res = qmlapp.imageManager.saveImage(showImage.source, filePath)
            if(res.startsWith("[Success]"))
                qmlapp.popup.simple(qsTr("保存图片"), res)
            else
                qmlapp.popup.simple(qsTr("保存图片失败"), res)
        }
    }

    // ========================= 【处理】 =========================

    Component.onCompleted: {
        // 叠加层挂父级
        if(overlayLayer)
            overlayLayer.parent = showImage
    }
    

    // 图片组件的状态改变
    function imageStatusChanged(s) {
        // 已就绪
        if(s == Image.Ready) {
            imageSW = showImage.sourceSize.width // 记录图片原始宽高
            imageSH = showImage.sourceSize.height
            imageFullFit() // 初始大小
        }
        else {
            imageSW = imageSH = 0
            iRoot.scale = 1 
        }
    }

    function imagePointAt(viewX, viewY) {
        const visualX = (showImageContainer.width - imageSW * iRoot.scale) / 2
        const visualY = (showImageContainer.height - imageSH * iRoot.scale) / 2
        return [
            Math.max(0, Math.min(imageSW,
                (flickable.contentX + viewX - visualX) / iRoot.scale)),
            Math.max(0, Math.min(imageSH,
                (flickable.contentY + viewY - visualY) / iRoot.scale)),
        ]
    }

    // 缩放，传入 flag>0 放大， <0 缩小 ，0回归100%。默认以相框中心为锚点。
    function imageScaleAddSub(flag=0, step=0.1, anchorX=undefined, anchorY=undefined) {
        if(showImage.status != Image.Ready) return
        const ax = anchorX === undefined ? flickable.width / 2 : anchorX
        const ay = anchorY === undefined ? flickable.height / 2 : anchorY
        const sourcePoint = imagePointAt(ax, ay)
        // 计算缩放比例
        let s = 1.0 // flag==0 时复原
        if (flag > 0) {  // 放大
            s = Math.round((iRoot.scale + step) * 100) / 100
            // 禁止大于上限 或 图片填满大小（裁切）
            const max = Math.max(flickable.width/imageSW, flickable.height/imageSH, scaleMax)
            if(s > max) s = max
        }
        else if(flag < 0) {  // 缩小
            s = Math.round((iRoot.scale - step) * 100) / 100
            // 禁止小于下限 或 图片填满大小（不裁切）
            const min = Math.min(flickable.width/imageSW, flickable.height/imageSH, scaleMin)
            if(s < min) s = min
        }

        iRoot.scale = Number(s)
        const newVisualX = (showImageContainer.width - imageSW * iRoot.scale) / 2
        const newVisualY = (showImageContainer.height - imageSH * iRoot.scale) / 2
        const targetX = newVisualX + sourcePoint[0] * iRoot.scale - ax
        const targetY = newVisualY + sourcePoint[1] * iRoot.scale - ay
        flickable.contentX = Math.max(0, Math.min(
            Math.max(0, showImageContainer.width - flickable.width), targetX))
        flickable.contentY = Math.max(0, Math.min(
            Math.max(0, showImageContainer.height - flickable.height), targetY))
    }

    // 图片填满组件，不裁切
    function imageFullFit() {
        if(showImage.source == "" || imageSW <= 0) return
        iRoot.scale = Math.min(flickable.width/imageSW, flickable.height/imageSH)
        // 图片中心对齐相框
        flickable.contentY =  - (flickable.height - showImageContainer.height)/2
        flickable.contentX =  - (flickable.width - showImageContainer.width)/2
    }
    
    // ======================== 【布局】 =========================
    color: theme.bgColor


    // 滑动区域，显示图片，监听左键拖拽
    Flickable {
        id: flickable
        anchors.fill: parent
        contentWidth: showImageContainer.width
        contentHeight: showImageContainer.height
        clip: true
        
        // 图片容器，大小不小于滑动区域
        Item {
            id: showImageContainer
            width: Math.max( imageSW * iRoot.scale , flickable.width )
            height: Math.max( imageSH * iRoot.scale , flickable.height )
            Image_ {
                id: showImage
                anchors.centerIn: parent
                width: sourceSize.width
                height: sourceSize.height
                scale: iRoot.scale
                onStatusChanged: imageStatusChanged(status)
            }
        }

        // 滚动条
        ScrollBar.vertical: ScrollBar { }
        ScrollBar.horizontal: ScrollBar { }
    }

    // 监听滚轮缩放
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.NoButton
        // 滚轮缩放
        onWheel: function(wheel) {
            let delta = wheel.angleDelta.y
            if(delta === 0 && wheel.pixelDelta)
                delta = wheel.pixelDelta.y
            if(delta === 0) return
            const step = Math.max(0.02, Math.min(0.2, Math.abs(delta) * 0.1 / 120))
            imageScaleAddSub(delta > 0 ? 1 : -1, step, wheel.x, wheel.y)
            wheel.accepted = true
        }
    }

    // 边框
    Rectangle {
        id: bRect
        anchors.fill: parent
        color: "#00000000"
        border.width: 1
        border.color: theme.coverColor4
    }
}
