// =======================================
// =============== 系统托盘 ===============
// =======================================

import QtQuick 2.15
import QtQml.Models 2.15
import Qt.labs.platform 1.1

SystemTrayIcon {
    id: systemTrayRoot

    // ========================= 【接口】 =========================

    // 添加一项菜单。如果只传入 eventTitle ，则发送事件。如果传入回调函数 func ，则调用函数，不发送事件。
    function addMenuItem(eventTitle, text, func=undefined) {
        // 检查重复
        const index = findMenuEvent(eventTitle)
        if(index >= 0) {
            console.warn(`注册系统托盘菜单重复！ ${eventTitle} - ${text}`)
            return
        }
        const argv = {eventTitle: eventTitle, text_:text, isFunc:func?true:false}
        if(func) funcDict[eventTitle] = func // 不能将函数塞进ListModel，故放进单独的函数字典
        menuModel.append(argv)

    }

    // 移除一项菜单
    function delMenuItem(eventTitle) {
        console.log(`删除系统托盘菜单 ${eventTitle}`)
        const index = findMenuEvent(eventTitle)
        if(index < 0) {
            console.warn(`删除系统托盘菜单，找不到对应项！ ${eventTitle} - ${text}`)
            return
        }
        const argd = menuModel.get(index)
        if(argd.isFunc) { // 删除回调函数
            delete funcDict[argd.eventTitle]
        }
        // 删除菜单项
        menuModel.remove(index)

    }

    function startScreenshot() {
        const page = qmlapp.tab.openTabPageByKey("ScreenshotOCR")
        if(page)
            page.screenshot()
    }

    function openGlobalSettings() {
        qmlapp.mainWin.setVisibility(true)
        qmlapp.tab.openTabPageByKey("GlobalConfigsPage")
    }

    // ========================= 【控制】 =========================

    // 在 menuModel 中寻找 eventTitle 对应的项，返回下标，找不到返回-1
    function findMenuEvent(eventTitle) {
        const len = menuModel.count
        let index = len-1
        for(; index >= 0; index--) {
            const d = menuModel.get(index)
            if(d.eventTitle === eventTitle)
                break
        }
        return index
    }

    // 点击菜单项
    function menuCall(index) {
        const argd = menuModel.get(index)
        if(argd.isFunc) { // 执行函数
            funcDict[argd.eventTitle]()
        }
        else { // 发布事件
            qmlapp.pubSub.publish(argd.eventTitle)
        }
    }

    // ========================= 【布局】 =========================

    visible: true
    icon.source: Qt.resolvedUrl("../../images/icons/umiocr.ico")
    tooltip: "Umi-OCR"
    property var funcDict: {} // 存放函数的字典
    Component.onCompleted: funcDict = {}
    Component.onDestruction: {
        systemTrayRoot.visible = false
        systemTrayRoot.menu = null
    }

    property Timer singleClickTimer: Timer {
        id: singleClickTimer
        interval: 250
        repeat: false
        onTriggered: systemTrayRoot.startScreenshot()
    }

    // 右键菜单
    menu: Menu {
        id: trayMenu
        ListModel{ id:menuModel } // 自定义菜单的模型
        property alias menuModel: menuModel

        // Menu { title: qsTr("所有功能") }

        Instantiator {
            model: trayMenu.menuModel
            delegate: MenuItem {
                text: text_
                onTriggered: systemTrayRoot.menuCall(index)
            }

            onObjectAdded: function(index, object) { trayMenu.insertItem(index, object) }
            onObjectRemoved: function(index, object) { trayMenu.removeItem(object) }
        }

        MenuItem {
            text: qsTr("左键单击：截屏")
            onTriggered: systemTrayRoot.startScreenshot()
        }
        MenuItem {
            text: qsTr("全局设置")
            onTriggered: systemTrayRoot.openGlobalSettings()
        }
        MenuItem {
            text: qmlapp.globalConfigs.ocrManager.modelActionText
            enabled: qmlapp.globalConfigs.ocrManager.modelActionEnabled
            onTriggered: qmlapp.globalConfigs.ocrManager.toggleModel()
        }
        MenuSeparator { }

        MenuItem {
            text: qsTr("启动界面")
            onTriggered: qmlapp.mainWin.setVisibility(true)
        }
        MenuItem {
            text: qsTr("退出 Umi-OCR")
            onTriggered: qmlapp.mainWin.quit()
        }
    }

    onActivated: {
        if(reason == SystemTrayIcon.Trigger) {
            singleClickTimer.restart()
        }
        else if(reason == SystemTrayIcon.DoubleClick) {
            singleClickTimer.stop()
            qmlapp.mainWin.setVisibility(true) // 主窗可见
        }
        else if(reason == SystemTrayIcon.Context) {
            trayMenu.open()
        }
    }
}
