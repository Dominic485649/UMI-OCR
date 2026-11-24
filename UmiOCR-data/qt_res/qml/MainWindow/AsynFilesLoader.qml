// =============================================
// =============== 异步文件加载器 ===============
// =============================================
// 扫描串行执行，接收请求不阻塞。每个请求拥有独立身份、事件和终态回调。

import QtQuick 2.15

Item {
    id: filesLoader
    property real updateTime: 0.2
    readonly property bool busy: activeRequest_ !== null || requests_.length > 0
    readonly property int pendingCount: requests_.length + (activeRequest_ ? 1 : 0)
    readonly property string activeRequestId: activeRequest_ ? activeRequest_.id : ""
    property string statusText: ""
    property var lastTerminal: ({})
    property var requests_: []
    property var activeRequest_: null
    property int nextRequestId_: 0

    // 调试边界只含请求身份和数量，不记录用户的文件路径或密码。
    signal requestStarted(string requestId)
    signal requestFinished(string requestId, string status)
    signal callbackFailed(string requestId)

    Component {
        id: requestBridge
        QtObject {
            property string requestId: ""
            function fileLoadComplete(paths, issues) {
                filesLoader.fileLoadComplete(requestId, paths, issues)
            }
            function fileLoadUpdate(filesCount, lastPath) {
                filesLoader.fileLoadUpdate(requestId, filesCount)
            }
        }
    }

    // 回调为 callback(rows, terminal)，旧的单参数回调仍可使用。
    // 延后启动保证调用方先拿到 requestId，空输入也不会同步抢跑回调。
    function start(urls, sufType, isRecurrence, callback) {
        const id = "FilesLoader-" + (++nextRequestId_)
        const request = {
            id: id, urls: urls ? Array.from(urls) : [], sufType: sufType,
            isRecurrence: isRecurrence, callback: callback, cancelled: false,
            bridge: null, completeKey: "<<fileLoadComplete:" + id + ">>",
            updateKey: "<<fileLoadUpdate:" + id + ">>"
        }
        requests_ = requests_.concat([request])
        Qt.callLater(pump)
        return id
    }
    function run(urls, sufType, isRecurrence, callback) {
        return start(urls, sufType, isRecurrence, callback)
    }

    function cancel(requestId) {
        if(activeRequest_ && activeRequest_.id === requestId) {
            // finder 没有取消/加入线程接口。必须等这个扫描的真实终态，不能放行下一个。
            // 保持同一个请求对象：requestStarted 的同步监听器也可能在桥创建前取消。
            activeRequest_.cancelled = true
            statusText = qsTr("正在取消导入，等待当前扫描结束…")
            return true
        }
        for(let i = 0; i < requests_.length; i++) {
            if(requests_[i].id !== requestId) continue
            const request = requests_[i]
            requests_ = requests_.slice(0, i).concat(requests_.slice(i + 1))
            request.cancelled = true
            settle(request, [], "cancelled", [], "")
            Qt.callLater(pump)
            return true
        }
        return false
    }

    function pump() {
        if(activeRequest_ || requests_.length === 0) return
        const request = requests_[0]
        requests_ = requests_.slice(1)
        activeRequest_ = request
        statusText = qsTr("正在扫描文件，可继续添加…")
        requestStarted(request.id)
        if(request.cancelled || request.urls.length === 0) {
            // 此时还没有提交底层扫描，可以直接结算；一旦提交则仍等待它的真实终态。
            finishActive([], request.cancelled ? "cancelled" : "empty", [], "")
            return
        }
        try {
            if(request.sufType !== "image" && request.sufType !== "doc")
                throw new Error(qsTr("不支持的文件类型"))
            request.bridge = requestBridge.createObject(filesLoader, {requestId: request.id})
            qmlapp.pubSub.subscribe(request.completeKey, request.bridge, "fileLoadComplete")
            qmlapp.pubSub.subscribe(request.updateKey, request.bridge, "fileLoadUpdate")
            // 保留 finder 的协议，只给事件名加请求身份；晚到或重复事件不会结算其它请求。
            qmlapp.utilsConnector.asynFindFiles(request.urls, request.sufType,
                request.isRecurrence, request.completeKey, request.updateKey, updateTime)
        }
        catch(error) {
            finishActive([], "error", [], String(error))
        }
    }

    function detach(request) {
        if(!request.bridge) return
        qmlapp.pubSub.unsubscribe(request.completeKey, request.bridge, "fileLoadComplete")
        qmlapp.pubSub.unsubscribe(request.updateKey, request.bridge, "fileLoadUpdate")
        request.bridge.destroy()
    }
    function finishActive(paths, status, issues, error) {
        const request = activeRequest_
        if(!request) return
        detach(request)
        activeRequest_ = null
        statusText = ""
        settle(request, request.cancelled ? [] : paths,
            request.cancelled ? "cancelled" : status, issues, error)
        Qt.callLater(pump)
    }
    function settle(request, paths, status, issues, error) {
        const terminal = {
            requestId: request.id, status: status, issues: issues || [], error: error || ""
        }
        lastTerminal = terminal
        try {
            if(request.callback) request.callback(paths || [], terminal)
        }
        catch(callbackError) {
            // 一个页面的回调失败不能覆盖或阻塞其它页面的请求。
            callbackFailed(request.id)
            console.warn("文件导入回调异常（请求 " + request.id + "）")
        }
        requestFinished(request.id, status)
        if(status !== "cancelled" && ((issues && issues.length) || error)) {
            const messages = []
            if(error) messages.push(error)
            for(let i = 0; issues && i < issues.length; i++)
                messages.push(issues[i].message || qsTr("路径未能导入"))
            // 加载进度与诊断均不创建 modal 遮罩，保留其它真正模态对话框的原有行为。
            qmlapp.popup.simple(qsTr("部分路径未导入"), messages.join("\n"))
        }
    }
    function fileLoadComplete(requestId, paths, issues) {
        if(!activeRequest_ || activeRequest_.id !== requestId) return
        paths = paths || []
        issues = issues || []
        const status = paths.length > 0 ? "complete" : (issues.length ? "error" : "empty")
        finishActive(paths, status, issues, "")
    }
    function fileLoadUpdate(requestId, filesCount) {
        if(!activeRequest_ || activeRequest_.id !== requestId || activeRequest_.cancelled) return
        statusText = qsTr("已载入 %1 个文件，可继续添加…").arg(filesCount)
    }
}
