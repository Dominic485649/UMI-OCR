// =============================================
// =============== 异步文件加载器 ===============
// =============================================
// 用于全局任意模块加载大量文件

import QtQuick 2.15

Item {
    property string tips: qsTr("正在载入 %1 个文件：\n%2")
    property real updateTime: 0.2 // 刷新事件时间间隔
    property var callback_: undefined // 缓存最近一次回调函数

    Component.onCompleted: {
        // 订阅事件
        qmlapp.pubSub.subscribeGroup("<<fileLoadComplete>>", this,
            "fileLoadComplete", "FilesLoader")
        qmlapp.pubSub.subscribeGroup("<<fileLoadUpdate>>", this,
            "fileLoadUpdate", "FilesLoader")
    }

    function run(
        urls,  // 初始路径列表
        sufType,  // 后缀类型，image / doc
        isRecurrence,  // 若为True，则递归搜索
        callback  // 加载完成后，向此回调函数传入路径列表
    ) {
        callback_ = callback
        qmlapp.popup.showMask(tips.arg(1).arg(""), "LoadingFiles")
        qmlapp.utilsConnector.asynFindFiles(
            urls,
            sufType,
            isRecurrence,
            "<<fileLoadComplete>>",
            "<<fileLoadUpdate>>",
            updateTime
        )
    }
    // 文件扫描结束，获取合法文件列表
    function fileLoadComplete(paths, issues) {
        qmlapp.popup.hideMask("LoadingFiles")
        if(issues && issues.length > 0) {
            const messages = []
            for(let i = 0; i < issues.length; i++)
                messages.push(issues[i].message)
            qmlapp.popup.message(qsTr("部分路径未导入"), messages.join("\n"), "warning")
        }
        if(callback_)
            callback_(paths)
        callback_ = undefined
    }
    // 文件扫描更新，刷新提示文本
    function fileLoadUpdate(filesCount, lastPath) {
        qmlapp.popup.showMask(tips.arg(filesCount).arg(lastPath),
            "LoadingFiles")
    }
}
