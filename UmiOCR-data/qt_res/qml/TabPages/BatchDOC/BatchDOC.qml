// ==================================================
// =============== 功能页：批量文档处理 ===============
// ==================================================

import QtQuick 2.15
import QtQuick.Controls 2.15
import ".."
import "../../Widgets"
import "../../Widgets/ResultLayout"
import "../../Widgets/IgnoreArea"

TabPage {
    id: tabPage
    objectName: "batchDocPage"
    property string msnID: ""
    property bool pageAlive: true
    property var backendState: ({rows: [], running: false, importCount: 0})
    property var importRequests: []
    property string timedBatchId: ""
    property string notifiedBatchId: ""

    // ========================= 【权威队列与导入】 =========================

    function reportError(message) {
        qmlapp.popup.simple(qsTr("批量文档"), message || qsTr("操作未能完成，请重试。"))
    }
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

    // 打开与外部拖入只有这一个入口。票据先登记，再开始异步扫描。
    function addDocs(paths) {
        if(!pageAlive || !paths || !paths.length) return false
        const ticket = tabPage.callPy("beginImport")
        if(!ticket || !ticket.ok) { reportError(ticket ? ticket.error : ""); return false }
        let requestId = ""
        try {
            requestId = qmlapp.asynFilesLoader.start(paths, "doc",
                configsComp.getValue("mission.recurrence"), function(docs, terminal) {
                    if(!tabPage || !tabPage.pageAlive) return
                    importRequests = importRequests.filter(function(item) { return item.requestId !== terminal.requestId })
                    // 空、异常和取消也必须结算；代次/移除代次由后端最终校验。
                    invoke("finishImport", ticket.ticketId, docs, terminal)
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
    function docStart() {
        const id = invoke("msnDocs", backendState.rows || [], configsComp.getValueDict())
        if(id === false) { ctrlPanel.stopFinished(); return }
        // 已登记的初次扫描由后端 hold，不能提前拍一张表格快照漏掉晚结果。
        if(tabPanel.indexChangeNum < 2) tabPanel.currentIndex = 1
        refreshBatchState()
    }
    function docStop() { invoke("msnStop"); refreshBatchState() }
    function docClear() {
        if(backendState.running) { reportError(qsTr("任务进行中，不能清空当前文档。")); return false }
        if(invoke("clearRows") === false) return false
        cancelPageImports()
        return true
    }
    function rowForPath(path) {
        const rows = backendState.rows || []
        for(const row of rows) if(row.path === path || row.id === path) return row
        return null
    }
    function rowStateText(row) {
        switch(row.status) {
            case "pending": return qsTr("排队")
            case "locked": return qsTr("待解密")
            case "unlocking": return qsTr("验证密码")
            case "preparing": return qsTr("准备")
            case "active": return `${row.donePages || 0}/${Math.max(0, row.range_end - row.range_start + 1)}`
            case "finalizing": return qsTr("保存中")
            case "finished": return "√"
            case "failed": return "× " + qsTr("失败")
            case "stopped": return qsTr("已停止")
            default: return ""
        }
    }
    function displayRows(rows) {
        return rows.map(function(row) {
            const fullRange = row.range_start === 1 && row.range_end === row.page_count
            return {path: row.path, state: rowStateText(row),
                pages: !row.page_count ? "?" : (fullRange ? String(row.page_count) : `${row.range_start}-${row.range_end}`)}
        })
    }
    function batchStatusText(state) {
        if(state.state === "waiting_import") return qsTr("等待导入")
        if(state.state === "waiting_unlock") return qsTr("等待解密")
        if(state.state === "stopped") return qsTr("任务停止")
        if(state.completed && (state.failedDocs || state.skippedDocs)) return qsTr("已完成（存在失败或跳过）")
        return ""
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
        // 追加、删除与排序只刷新预算；不再用 runFinished 重置计时或已完成页数。
        ctrlPanel.msnAllNum = state.totalPages || 0
        ctrlPanel.msnNowNum = state.donePages || 0
        ctrlPanel.statusOverride = batchStatusText(state)
        if(state.running) {
            if(state.paused && ctrlPanel.state_ !== "pause") ctrlPanel.pauseFinished()
            else if(!state.paused && ctrlPanel.state_ === "pause") ctrlPanel.resumeFinished()
            ctrlPanel.isWaiting = false
            ctrlPanel.msnStep(0)
        }
        else ctrlPanel.stopFinished()
        if(passwordDialog.visible) {
            const row = rowForPath(passwordDialog.targetPath)
            if(!row || state.generation !== passwordDialog.requestGeneration) closePasswordDialog(false)
            else if(row.is_authenticate) closePasswordDialog(true)
        }
        if(state.completed && msnID && notifiedBatchId !== msnID) {
            notifiedBatchId = msnID
            const simpleType = configsComp.getValue("other.simpleNotificationType")
            const summary = qsTr("成功 %1，失败 %2，跳过 %3，停止 %4")
                .arg(state.successDocs || 0).arg(state.failedDocs || 0).arg(state.skippedDocs || 0).arg(state.stoppedDocs || 0)
            qmlapp.popup.simple(qsTr("批量识别完成"), summary, simpleType)
            if(state.canPostTaskActions)
                qmlapp.globalConfigs.utilsDicts.postTaskHardwareCtrl(configsComp.getValue("postTaskActions.system"))
        }
    }
    function queueSummary() {
        const state = backendState
        let text = qsTr("文档 %1/%2 · 页 %3/%4").arg(state.doneDocs || 0).arg(state.totalDocs || 0)
            .arg(state.donePages || 0).arg(state.totalPages || 0)
        if(state.lockedCount) text += qsTr(" · 待解密 %1").arg(state.lockedCount)
        if(state.importCount) text += qsTr(" · 导入中 %1 组").arg(state.importCount)
        for(const request of importRequests) {
            if(request.requestId === qmlapp.asynFilesLoader.activeRequestId) {
                text += " · " + qmlapp.asynFilesLoader.statusText
                break
            }
        }
        return text
    }

    // ========================= 【稳定路径交互】 =========================

    function moveDoc(path, beforePath) { return invoke("movePending", path, beforePath) }
    function removeDoc(path) { return invoke("removeRows", [path]) }
    function reocrDoc(path) { return invoke("reOCR", path, configsComp.getValueDict()) }
    function openOriginal(path) {
        const source = tabPage.callPy("getOriginal", path)
        if(!source || !source.openable || !source.exists) { reportError(source ? source.error : qsTr("原始文件不存在")); return false }
        qmlapp.utilsConnector.startfile(source.path)
        return true
    }
    function openArtifact(path, format, artifactPath) {
        // 点击时再次验证最近成功产物及存在性，不根据文件名猜输出路径。
        const result = invoke("openArtifact", path, format, artifactPath)
        if(!result || !result.ok || !result.path) return false
        qmlapp.utilsConnector.startfile(result.path)
        return true
    }
    function buildDocMenu(path) {
        const row = rowForPath(path)
        const source = row ? tabPage.callPy("getOriginal", path) : null
        const artifacts = row ? tabPage.callPy("getArtifacts", path) || [] : []
        const artifactItems = artifacts.map(function(artifact) {
            return {text: String(artifact.format).toUpperCase(), objectName: "docArtifactAction:" + artifact.format,
                enabled: !!(artifact.saved && artifact.openable && artifact.exists),
                tip: artifact.openable ? "" : (artifact.error || qsTr("产物尚未成功保存或文件已不存在")),
                action: function() { openArtifact(path, artifact.format, artifact.path) }}
        })
        const artifactEnabled = artifactItems.some(function(item) { return item.enabled })
        const artifactEntry = {
            text: qsTr("打开 OCR 后的文件"), objectName: "docOpenArtifactsAction", enabled: artifactEnabled,
            tip: artifacts.length ? qsTr("仅打开本次记录的最近成功产物") : qsTr("尚未生成成功保存的产物"),
            children: artifactItems.length > 1 ? artifactItems : [],
            action: function() { if(artifacts.length === 1) openArtifact(path, artifacts[0].format, artifacts[0].path) }
        }
        return [
            {text: qsTr("打开原始文件"), objectName: "docOpenOriginalAction", enabled: !!(source && source.exists && source.openable),
                tip: source && source.openable ? "" : qsTr("原始文件不存在或已移出队列"), action: function() { openOriginal(path) }},
            artifactEntry,
            {text: qsTr("重新 OCR 此文档"), objectName: "docReocrAction", enabled: !!(row && row.canReocr),
                tip: row && row.canReocr ? qsTr("仅识别此文档，使用本次确认的范围和设置") : qsTr("当前、等待、保存中或未解密的文档不能重复入队"),
                action: function() { reocrDoc(path) }},
            {text: qsTr("移出队列（不删除文件）"), objectName: "docRemoveAction", color: "noColor", enabled: !!(row && row.canRemove),
                tip: row && row.canRemove ? qsTr("只移除队列记录，不删除磁盘文件") : qsTr("当前文档正在处理或保存，不能移除"),
                action: function() { removeDoc(path) }}
        ]
    }
    function onClickDoc(index) {
        const path = filesTableView.get(index).path
        const row = rowForPath(path)
        if(!row) return
        if(row.canUnlock) { showPassword(path); return }
        if(backendState.running) { reportError(qsTr("任务运行中只能解密等待文档；编辑完整预览请先停止任务。")); return }
        previewDoc.show(Object.assign({}, row, {pages: filesTableView.get(path).pages, state: rowStateText(row)}))
    }
    function showPassword(path) {
        const row = rowForPath(path)
        if(!row || !row.canUnlock || passwordDialog.visible) return false
        passwordDialog.sessionId++
        passwordDialog.targetPath = row.path
        passwordDialog.requestGeneration = backendState.generation
        passwordDialog.verification = null
        passwordDialog.acceptedResult = false
        passwordDialog.busy = false
        passwordDialog.errorText = ""
        passwordInput.text = ""
        passwordDialog.open()
        Qt.callLater(function() { if(passwordDialog.visible) passwordInput.forceActiveFocus() })
        return true
    }
    function cancelPasswordVerification() {
        const verification = passwordDialog.verification
        // 先消费本次身份，再调用可能同步回传快照的后端，重复关闭不会误取消下一次验证。
        passwordDialog.verification = null
        passwordDialog.busy = false
        if(!verification || passwordDialog.acceptedResult || !pageAlive) return
        invoke("cancelUnlock", verification.path, verification.unlockToken, verification.generation)
    }
    function closePasswordDialog(accepted) {
        passwordDialog.acceptedResult = accepted
        passwordDialog.verification = null
        passwordDialog.busy = false
        if(accepted) passwordDialog.accept()
        else passwordDialog.close() // 清空/Stop 等已经使原代次失效，不对新路径发取消请求。
    }
    function submitPassword() {
        if(passwordDialog.busy || !passwordDialog.visible || passwordDialog.acceptedResult) return
        const sessionId = passwordDialog.sessionId
        const path = passwordDialog.targetPath
        passwordDialog.busy = true
        passwordDialog.errorText = ""
        const result = invoke("unlockDocument", path, passwordInput.text)
        if(result === false || !result || !result.unlockToken) {
            if(passwordDialog.sessionId === sessionId && passwordDialog.visible) {
                passwordDialog.busy = false
                passwordDialog.errorText = qsTr("无法开始密码验证，请重试。")
            }
            return
        }
        const verification = {path: path, unlockToken: result.unlockToken, generation: result.generation}
        if(passwordDialog.sessionId !== sessionId || !passwordDialog.visible) {
            // 覆盖调用返回前已关闭的边界；成功主动关闭不能反向取消已接受的结果。
            if(passwordDialog.sessionId !== sessionId || !passwordDialog.acceptedResult)
                invoke("cancelUnlock", verification.path, verification.unlockToken, verification.generation)
            return
        }
        if(passwordDialog.acceptedResult) return
        passwordDialog.verification = verification
        const row = rowForPath(path)
        if(row && row.is_authenticate) closePasswordDialog(true)
        else if(row && row.status !== "unlocking") {
            // 极快的失败回调可能早于调用返回；终态不再保留一个永远 busy 的输入框。
            passwordDialog.verification = null
            passwordDialog.busy = false
            passwordDialog.errorText = row.message || qsTr("密码不正确或文档读取失败，请重试。")
        }
    }
    function onUnlockResult(path, result) {
        const verification = passwordDialog.verification
        if(!passwordDialog.visible || !verification || !result || verification.path !== path
            || verification.unlockToken !== result.unlockToken || verification.generation !== result.generation) return
        passwordDialog.verification = null
        passwordDialog.busy = false
        const row = rowForPath(path)
        if(row && row.is_authenticate) closePasswordDialog(true)
        else passwordDialog.errorText = result.error || result.message || qsTr("密码不正确或文档读取失败，请重试。")
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

    // 单件回调仅展示结果；队列、状态和计数完全以 onBatchState 为准。
    function onDocStart(path) {}
    function onDocGet(path, page, res) {
        if(!pageAlive) return
        res.title = `${path2name(path)} - ${page}`
        resultsTableView.addOcrResult(res)
    }
    function onDocEnd(path, msg, isAll) {
        if(pageAlive && msg && !msg.startsWith("[Success]")) qmlapp.popup.simple(qsTr("文档识别异常"), msg)
    }
    function path2name(path) { const parts = path.replace(/\\/g, "/").split("/"); return parts[parts.length - 1] }

    // ========================= 【布局】 =========================

    configsComp: BatchDOCConfigs {}
    DoubleSwitchableLayout {
        id: doubleLayout
        saveKey: "BatchDOC_1"
        anchors.fill: parent
        itemA: Panel {
            anchors.fill: parent
            MissionCtrlPanel {
                id: ctrlPanel
                objectName: "batchDocMissionCtrl"
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.margins: size_.spacing
                height: size_.line * 2
                onRunClicked: tabPage.docStart()
                onPauseClicked: { tabPage.invoke("msnPause"); tabPage.refreshBatchState() }
                onResumeClicked: { tabPage.invoke("msnResume"); tabPage.refreshBatchState() }
                onStopClicked: tabPage.docStop()
            }
            FilesTableView {
                id: filesTableView
                objectName: "batchDocFilesTable"
                anchors.top: ctrlPanel.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: size_.spacing
                anchors.topMargin: size_.smallSpacing
                headers: [
                    {key: "path", title: qsTr("文档"), left: true, display: path2name, btn: true, onClicked: onClickDoc},
                    {key: "state", title: qsTr("状态"), btn: true, onClicked: onClickDoc},
                    {key: "pages", title: qsTr("页数"), btn: true, onClicked: onClickDoc}
                ]
                openBtnText: qsTr("打开文档")
                defaultTips: qsTr("拖入文档或文件夹")
                fileDialogTitle: qsTr("请选择文档")
                fileDialogNameFilters: [qsTr("文档") + " (*.pdf *.xps *.epub *.mobi *.fb2 *.cbz)"]
                isLock: !!backendState.running
                allowOpenWhileLocked: true
                clearHandler: tabPage.docClear
                statusText: tabPage.queueSummary()
                dragSortEnabled: true
                contextMenuEnabled: true
                canMoveRow: function(path) { const row = tabPage.rowForPath(path); return !!(row && row.canMove) }
                rowMenuBuilder: tabPage.buildDocMenu
                onRowMoveRequested: function(path, beforePath) { tabPage.moveDoc(path, beforePath) }
                onAddPaths: function(paths) { tabPage.addDocs(paths) }
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
    DropArea_ {
        objectName: "batchDocExternalDrop"
        anchors.fill: parent
        callback: tabPage.addDocs
    }
    PreviewDoc {
        id: previewDoc
        anchors.fill: parent
        configsComp: tabPage.configsComp
        updateInfo: function(path, info) { tabPage.invoke("syncMetadata", path, info) }
    }
    // 与完整预览分开：运行中验证密码不会改全局忽略区域，也不会提交当前文档。
    Dialog {
        id: passwordDialog
        objectName: "batchDocPasswordDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(parent ? parent.width - size_.line * 2 : size_.line * 24, size_.line * 24)
        modal: true
        title: qsTr("解密等待文档")
        property string targetPath: ""
        property int requestGeneration: -1
        property int sessionId: 0
        property var verification: null // 只保存本 Dialog 发起的 path/token/generation。
        property bool acceptedResult: false
        property bool busy: false
        property string errorText: ""
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onRejected: tabPage.cancelPasswordVerification()
        onAboutToHide: tabPage.cancelPasswordVerification() // 同时覆盖 Esc、点击外部和普通 close()。
        onClosed: { if(!visible) passwordInput.text = "" }
        contentItem: Column {
            spacing: size_.spacing
            Text_ { width: parent.width; text: path2name(passwordDialog.targetPath); elide: Text.ElideMiddle }
            TextField_ {
                id: passwordInput
                objectName: "batchDocPasswordInput"
                width: parent.width
                height: size_.line * 1.5
                echoMode: TextInput.Password
                placeholderText: qsTr("文档密码")
                enabled: !passwordDialog.busy
                onAccepted: tabPage.submitPassword()
            }
            Text_ {
                width: parent.width
                text: passwordDialog.busy ? qsTr("正在验证密码…") : passwordDialog.errorText
                color: theme.noColor
                wrapMode: Text.Wrap
            }
        }
        footer: Item {
            height: size_.line * 2
            Row {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: size_.spacing
                Button_ {
                    objectName: "batchDocPasswordCancel"
                    width: size_.line * 3
                    height: size_.line * 1.5
                    text_: qsTr("取消")
                    onClicked: passwordDialog.reject()
                }
                Button_ {
                    objectName: "batchDocPasswordConfirm"
                    width: size_.line * 4
                    height: size_.line * 1.5
                    text_: qsTr("验证密码")
                    enabled: !passwordDialog.busy
                    onClicked: tabPage.submitPassword()
                }
            }
        }
    }
}
