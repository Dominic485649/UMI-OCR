// =============================================
// =============== 参数项组件基类 ===============
// =============================================

import QtQuick 2.15
import "../Widgets"

Item {
    id: itemRoot
    property string key: "" // 展示入口的键
    property var configs: undefined // 所属展示面板
    property var sourceConfigs: configs // 规范配置来源，跨页引用不创建本地副本
    property string sourceKey: key
    property bool updatingUI: false
    property bool itemReady: false
    property var updateUI: ()=>{console.log(`${key} 更新设置UI为${value()}`)} // 更新UI函数，子类重写，通过value()获取最新值
    property int cursorShape_: Qt.ArrowCursor // 鼠标指针

    property string title: "" // 标题，可不填
    property var origin: undefined // 起源参数（静态）
    property bool advanced: false // true时是高级选项
    property bool hasEditor: false
    property real editorLeadingWidth: 0 // 输入框左侧操作占用的宽度
    readonly property bool alignedEditor: hasEditor && !!configs && configs.alignEditorColumn === true
    readonly property real lineHeight: size_.line + size_.spacing
    readonly property real editorTopInset: alignedEditor && configs.stackEditorTitles ? lineHeight : 0
    readonly property real editorLeft: alignedEditor ? configs.editorLeftFor(itemRoot) : 0
    function editorWidth(oldRatio) {
        return alignedEditor ? Math.max(0, width - editorLeft - 1) : width * oldRatio
    }

    anchors.left: parent.left
    anchors.right: parent.right
    clip: true
    // 这个选项是高级选项，且设置页未开启高级模式，则高度为0隐藏
    height: (advanced&&!configs.advanced) ? 0 : lineHeight + editorTopInset
    visible: !(advanced&&!configs.advanced)

    // 初始化只读规范值，禁止控件重建时反向提交。
    Component.onCompleted: {
        origin = sourceConfigs.originDict[sourceKey]
        title = origin.title
        refreshValue()
        itemReady = true
        // 如果设定了提示，则加载提示组件
        if(origin.toolTip) {
            toolTipLoader.sourceComponent = toolTip
        }
        if(origin.advanced) {
            advanced = origin.advanced
            title = "* "+title
        }
        Qt.callLater(() => { // 延迟一个事件循环，再激活背景鼠标响应
            mouseAreaBackgroud.hoverEnabled = true
        })
    }
    function refreshValue() {
        updatingUI = true
        try { updateUI() }
        finally { updatingUI = false }
    }
    Connections {
        target: sourceConfigs
        function onValueCommitted(changedKey, newValue) {
            if(itemReady && changedKey === sourceKey) refreshValue()
        }
        function onConfigurationReloaded() {
            if(!itemReady || !sourceConfigs.originDict[sourceKey]) return
            origin = sourceConfigs.originDict[sourceKey]
            title = (origin.advanced ? "* " : "") + origin.title
            refreshValue()
        }
    }
    // 所有入口均走规范来源的 getValue/setValue；拒绝提交时也恢复此入口。
    function value(v=undefined) {
        if(v === undefined) return sourceConfigs.getValue(sourceKey)
        if(updatingUI || !itemReady) return
        sourceConfigs.setValue(sourceKey, v, true)
        refreshValue()
    }
    
    // 左边 标题
    Text_ {
        objectName: "configRowTitle"
        text: title
        anchors.left: parent.left
        anchors.leftMargin: size_.smallSpacing
        width: {
            const gap = size_.smallSpacing
            if(!itemRoot.alignedEditor) return Math.max(0, parent.width - Math.max(size_.line, parent.width * 0.52) - gap)
            if(itemRoot.editorTopInset) return Math.max(0, parent.width - 2 * gap)
            return Math.max(0, itemRoot.editorLeft - itemRoot.editorLeadingWidth - 2 * gap)
        }
        elide: Text.ElideRight
        anchors.verticalCenter: parent.verticalCenter
        anchors.verticalCenterOffset: -itemRoot.editorTopInset / 2
        clip: true
    }
    // 背景
    MouseAreaBackgroud {
        id: mouseAreaBackgroud
        cursorShape: cursorShape_
        hoverEnabled: false
    }
    // 提示
    Component {
        id: toolTip
        ToolTip_ {
            visible: mouseAreaBackgroud.hovered
            text: origin.toolTip
        }
    }
    Loader { id: toolTipLoader } // 默认不加载
}