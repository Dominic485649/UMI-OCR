// ==============================================
// =============== 功能页：批量OCR ===============
// ==============================================

import QtQuick 2.15
import QtQuick.Controls 2.15
import ".."
import "../../Widgets"
import "../../Widgets/ResultLayout"
import "../../Widgets/IgnoreArea"

TabPage {
    id: tabPage
    objectName: "batchOcrPage"
    property string msnID: ""
    property bool pageAlive: true
    property var backendState: ({rows: [], running: false, importCount: 0})
    property var importRequests: []
    property string timedBatchId: ""
    property string notifiedBatchId: ""
    property var resultTimes: ({})
    property var resultLabels: ({})
    property int errorNum: backendState.failedDocs || 0

    function reportError(message) { qmlapp.popup.simple(qsTr("批量 OCR"), message || qsTr("操作未能完成，请重试。")) }
    function applyResult(result) {
        if(typeof result === "string" && result.startsWith("[Error]")) { reportError(result); return false }
        if(result && result.ok === false) { reportError(result.error); return false }
        if(result && result.rows) onBatchState(result)
        return result
    }
    function invoke(name, ...args) { return applyResult(tabPage.callPy(name, ...args)) }
    function refreshBatchState() {
        if(pageAlive && connector && ctrlKey) applyResult(tabPage.callPy("getBatchState"))
    }
    onConnectorChanged: { if(connector) Qt.callLater(refreshBatchState) }
    onCtrlKeyChanged: { if(ctrlKey) Qt.callLater(refreshBatchState) }

    // 打开与拖入共用入口；运行中也登记票据，不静默 return，也不重交整张表。
    function addImages(paths) {
        if(!pageAlive || !paths || !paths.length) return false
        const ticket = tabPage.callPy("beginImport")
        if(!ticket || !ticket.ok) { reportError(ticket ? ticket.error : ""); return false }
        let requestId = ""
        try {
            requestId = qmlapp.asynFilesLoader.start(paths, "image",
                configsComp.getValue("mission.recurrence"), function(images, terminal) {
                    if(!tabPage || !tabPage.pageAlive) return
                    importRequests = importRequests.filter(function(item) { return item.requestId !== terminal.requestId })
                    invoke("finishImport", ticket.ticketId, images, terminal)
                })
            importRequests = importRequests.concat([{requestId: requestId, ticketId: ticket.ticketId}])
        }
        catch(error) {
            invoke("finishImport", ticket.ticketId, [], {requestId: requestId, status: "error", error: String(error)})
            return false
        }
        return requestId
    }
    function cancelPageImports() {
        const requests = importRequests
        importRequests = []
        for(const request of requests) qmlapp.asynFilesLoader.cancel(request.requestId)
    }
    function ocrStart() {
        resultTimes = {}
        resultLabels = {}
        const paths = (backendState.rows || []).map(function(row) { return row.path })
        const id = invoke("msnPaths", paths, configsComp.getValueDict())
        if(id === false) { ctrlPanel.stopFinished(); return }
        if(tabPanel.indexChangeNum < 2) tabPanel.currentIndex = 1
        refreshBatchState()
    }
    function ocrStop() { invoke("msnStop"); refreshBatchState() }
    function ocrClear() {
        if(backendState.running) return false
        if(invoke("clearRows") === false) return false
        cancelPageImports()
        return true
    }
    function rowStateText(row) {
        switch(row.status) {
            case "pending": return qsTr("排队")
            case "preparing": return qsTr("准备")
            case "active": return qsTr("处理")
            case "finalizing": return qsTr("保存中")
            case "finished": return resultLabels[row.path] || "√"
            case "failed": return resultLabels[row.path] || ("× " + qsTr("失败"))
            case "stopped": return qsTr("已停止")
            default: return ""
        }
    }
    function displayRows(rows) {
        return rows.map(function(row) { return {path: row.path, time: resultTimes[row.path] || "", state: rowStateText(row)} })
    }
    function onBatchState(state) {
        if(!pageAlive || !state || !state.rows) return
        if(backendState.generation !== undefined && state.generation < backendState.generation) return
        backendState = state
        msnID = state.batchId || ""
        filesTableView.reconcileRows(displayRows(state.rows))
        if(state.running && timedBatchId !== msnID) {
            timedBatchId = msnID
            ctrlPanel.runFinished(state.totalPages || 0)
        }
        ctrlPanel.msnAllNum = state.totalPages || 0
        ctrlPanel.msnNowNum = state.donePages || 0
        ctrlPanel.statusOverride = state.state === "waiting_import" ? qsTr("等待导入")
            : (state.state === "stopped" ? qsTr("任务停止")
            : (state.completed && state.failedDocs ? qsTr("已完成（存在失败）") : ""))
        if(state.running) {
            if(state.paused && ctrlPanel.state_ !== "pause") ctrlPanel.pauseFinished()
            else if(!state.paused && ctrlPanel.state_ === "pause") ctrlPanel.resumeFinished()
            ctrlPanel.isWaiting = false
            ctrlPanel.msnStep(0)
        }
        else ctrlPanel.stopFinished()
        if(state.completed && msnID && notifiedBatchId !== msnID) {
            notifiedBatchId = msnID
            const summary = qsTr("成功 %1，失败 %2，跳过 %3，停止 %4")
                .arg(state.successDocs || 0).arg(state.failedDocs || 0).arg(state.skippedDocs || 0).arg(state.stoppedDocs || 0)
            qmlapp.popup.simple(qsTr("批量识别完成"), summary, configsComp.getValue("other.simpleNotificationType"))
            if(state.canPostTaskActions)
                qmlapp.globalConfigs.utilsDicts.postTaskHardwareCtrl(configsComp.getValue("postTaskActions.system"))
        }
    }
    function queueSummary() {
        let text = qsTr("图片 %1/%2").arg(backendState.doneDocs || 0).arg(backendState.totalDocs || 0)
        if(backendState.importCount) text += qsTr(" · 导入中 %1 组").arg(backendState.importCount)
        for(const request of importRequests) {
            if(request.requestId === qmlapp.asynFilesLoader.activeRequestId) {
                text += " · " + qmlapp.asynFilesLoader.statusText
                break
            }
        }
        return text
    }
    function finishClose() {
        if(!pageAlive) return
        tabPage.callPy("closeBatch")
        pageAlive = false
        cancelPageImports()
        delPage()
    }
    function closePage() {
        if(backendState.running) {
            qmlapp.popup.dialog("", qsTr("任务正在进行中。\n要结束任务并关闭页面吗？"),
                function(flag) { if(flag) finishClose() }, "warning", {yesText: qsTr("依然关闭")})
        }
        else finishClose()
    }
    Component.onDestruction: { pageAlive = false }

    // 单段结束不等于整批输出完成；续接/收尾只由 onBatchState 决定。
    function onOcrReady(path) {}
    function onOcrGet(path, res) {
        if(!pageAlive) return
        const times = Object.assign({}, resultTimes), labels = Object.assign({}, resultLabels)
        times[path] = typeof res.time === "number" ? res.time.toFixed(2) : ""
        labels[path] = res.code === 100 && typeof res.score === "number" && isFinite(res.score)
            ? "√ " + res.score.toFixed(2) : (res.code === 100 || res.code === 101 ? "√ ----" : "× " + res.code)
        resultTimes = times
        resultLabels = labels
        filesTableView.reconcileRows(displayRows(backendState.rows || []))
        res.title = res.fileName
        resultsTableView.addOcrResult(res)
    }
    function onOcrEnd(msg, thisMsnID) {
        if(pageAlive && msg && msg.startsWith("[Error]")) reportError(msg)
    }
    function msnPreview(path) { tabPage.callPy("msnPreview", path, configsComp.getValueDict()) }
    function onPreview(path, res) { ignoreArea.getPreview(res, path, "") }
    function path2name(path) { const parts = path.replace(/\\/g, "/").split("/"); return parts[parts.length - 1] }
    function onClickPath(index) {
        const info = filesTableView.get(index)
        const res = resultsTableView.getResult(path2name(info.path))
        const data = res && res.source ? JSON.parse(res.source) : undefined
        previewImage.show(info.path, data, res ? res.resText : undefined)
    }

    configsComp: BatchOCRConfigs {
        onClickIgnoreArea: { if(filesTableView.rowCount) ignoreArea.showPath(filesTableView.get(0).path); else ignoreArea.show() }
    }
    DoubleSwitchableLayout {
        id: doubleLayout
        saveKey: "BatchOCR_1"
        anchors.fill: parent
        itemA: Panel {
            anchors.fill: parent
            MissionCtrlPanel {
                id: ctrlPanel
                objectName: "batchOcrMissionCtrl"
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.margins: size_.spacing
                height: size_.line * 2
                onRunClicked: tabPage.ocrStart()
                onPauseClicked: { tabPage.invoke("msnPause"); tabPage.refreshBatchState() }
                onResumeClicked: { tabPage.invoke("msnResume"); tabPage.refreshBatchState() }
                onStopClicked: tabPage.ocrStop()
            }
            FilesTableView {
                id: filesTableView
                objectName: "batchOcrFilesTable"
                anchors.top: ctrlPanel.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: size_.spacing
                anchors.topMargin: size_.smallSpacing
                headers: [
                    {key: "path", title: qsTr("图片"), left: true, display: path2name, btn: true, onClicked: onClickPath},
                    {key: "time", title: qsTr("耗时")}, {key: "state", title: qsTr("状态")}
                ]
                openBtnText: qsTr("打开图片")
                defaultTips: qsTr("拖入图片或文件夹")
                fileDialogTitle: qsTr("请选择图片")
                fileDialogNameFilters: [qsTr("图片") + " (*.jpg *.jpe *.jpeg *.jfif *.png *.avif *.webp *.jxl *.jxr *.wdp *.hdp *.bmp *.tif *.tiff)"]
                isLock: !!backendState.running
                allowOpenWhileLocked: true
                clearHandler: tabPage.ocrClear
                statusText: tabPage.queueSummary()
                // 文档页专属的排序和右键菜单保持默认关闭。
                onAddPaths: function(paths) { tabPage.addImages(paths) }
            }
        }
        itemB: Panel {
            anchors.fill: parent
            TabPanel {
                id: tabPanel
                anchors.fill: parent
                anchors.margins: size_.spacing
                isMenuTop: doubleLayout.isRow
                menuHeight: size_.line * 2
                ResultsTableView { id: resultsTableView; anchors.fill: parent; visible: false }
                tabsModel: [
                    {key: "configs", title: qsTr("设置"), component: configsComp.panelComponent},
                    {key: "ocrResult", title: qsTr("记录"), component: resultsTableView}
                ]
            }
        }
    }
    DropArea_ { objectName: "batchOcrExternalDrop"; anchors.fill: parent; callback: tabPage.addImages }
    PreviewImage { id: previewImage; anchors.fill: parent }
    IgnoreArea { id: ignoreArea; anchors.fill: parent; pathPreview: msnPreview; configsComp: tabPage.configsComp; configKey: "tbpu.ignoreArea" }
}
