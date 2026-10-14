// ==========================================
// =============== OCR接口管理 ===============
// ==========================================

// qml的 api key 与 python api.ocr 中的字典要一致

import QtQuick 2.15

Item {
    property bool applying: false
    property var applyCallback: null


    // 配置在python那边编写
    // 缓存全局配置，如引擎路径、账号密钥等
    property var globalOptions: makeGlobalOptions()
    function makeGlobalOptions() { return {
        "title": qsTr("文字识别"),
        "type": "group",

        "btns": {
            "title": qsTr("操作"),
            "btnsList": [
                {"text":qsTr("强制终止任务"), "onClicked": stopAllMissions, "textColorKey":"noColor"},
                // {"text":qsTr("测试API"), "onClicked":()=>{}},

            ],
        },
        "lifecycle": {
            "title": qsTr("模型后台"),
            "type": "group",
            "warmupMode": {
                "title": qsTr("模型预热"),
                "default": "lazy",
                "optionsList": [
                    ["delayed", qsTr("延迟预热")],
                    ["lazy", qsTr("首次使用时加载")],
                ],
                "toolTip": qsTr("延迟预热会在启动后按设定时间加载模型，提前占用显存和内存以降低首次 OCR 等待；首次使用时加载不会提前占用资源。"),
                "onChanged": scheduleWarmup,
            },
            "warmupDelayMinutes": {
                "title": qsTr("预热延迟"),
                "default": 0,
                "min": 0,
                "max": 60,
                "isInt": true,
                "unit": qsTr("分钟"),
                "toolTip": qsTr("仅用于“延迟预热”。0 表示界面启动后立即在后台加载；提高数值可推迟显存和内存占用。"),
                "onChanged": scheduleWarmup,
            },
            "cleanupPolicy": {
                "title": qsTr("自动清理模型"),
                "default": "never",
                "optionsList": [
                    ["never", qsTr("不自动清理")],
                    ["memory", qsTr("内存占用超过 90%")],
                    ["idle", qsTr("无使用时自动清理")],
                ],
                "toolTip": qsTr("清理会释放 OCR 模型占用的显存和内存，下次识别需要重新加载。内存策略每 6 分钟检查一次；任务运行时绝不清理。"),
                "onChanged": resetCleanupSchedule,
            },
            "idleCleanupMinutes": {
                "title": qsTr("无使用清理时间"),
                "default": 30,
                "min": 5,
                "max": 120,
                "isInt": true,
                "unit": qsTr("分钟"),
                "toolTip": qsTr("仅用于“无使用时自动清理”。从最后一次 OCR 完成后计时；清理可降低显存和内存占用，但下次识别会增加加载时间。"),
            },
        },
        "api": {
            "title": qsTr("当前接口"),
            "optionsList": [],
        },
    }

    }

    // ========================= 【外部接口】 =========================

    // 应用更改，showSuccess=false时不显示成功提示
    function applyConfigs(showSuccess=true) {

        // 成功应用修改之后的刷新函数
        function successUpdate() {
            // 刷新qml各个页面的独立配置
            for (let key in deployDict) {
                const p = deployDict[key].page
                if(!p.configDict) { // 页面已经不存在了，则从记录字典中删除
                    delete deployDict[key]
                    continue
                }
                const k = deployDict[key].configKey
                p.configDict[k] = localOptions[apiKey] // 刷新页面设置
                p.reload() // 刷新页面UI
            }
        }

        // 验证
        if(Object.keys(localOptions).length === 0){
            qmlapp.popup.message("", noBackendHint(), "error")
            return
        }

        // 获取当前全局 apiKey ，验证在本字典中的存在性
        const nowKey = qmlapp.globalConfigs.getValue("ocr.api")
        if(!localOptions.hasOwnProperty(nowKey)) {
            const s = qsTr("OCR API 列表中不存在%1").arg(nowKey)
            qmlapp.popup.message("", s, "error")
            return
        }
        // 验证 py 是否有执行中的任务
        const lengths = qmlapp.msnConnector.callPy("ocr", "getMissionListsLength", [])
        const msnLen = Object.keys(lengths).length
        if(msnLen > 0) {
            qmlapp.globalConfigs.requestBackendApply()
            return
        }
        // 从全局配置中，提取出目前apiKey对应的配置项
        const allDict = qmlapp.globalConfigs.getValueDict()
        const ocrk = "ocr."+nowKey
        const info = {} // 汇聚为配置信息
        for(let k in allDict) { // 从全局配置中，提取以该api开头的键/值
            if(k.startsWith(ocrk)) {
                info[k] = allDict[k]
            }
        }
        const serviceInfo = qmlapp.globalConfigs.getPluginServiceValues(
            nowKey, serviceRefs[nowKey] || [])
        for(let k in serviceInfo)
            info[k] = serviceInfo[k]
        // 将配置信息发送给py，然后验证操作是否成功
        applying = true
        qmlapp.msnConnector.callPy("ocr", "deferAdmissions", [true])
        applyCallback = function(msg) {
        msg = String(msg)

        // 成功，写入记录
        if(msg.startsWith("[Success]")) {
            apiKey = nowKey
            successUpdate()
            scheduleWarmup()
            refreshModelState(false)
            if(showSuccess) { // 显示弹窗
                qmlapp.popup.simple(qsTr("文字识别接口应用成功"), qsTr("当前API为【%1】").arg(nowKey))
            }
        }
        else {
            qmlapp.popup.message(qsTr("文字识别接口应用失败"), msg, "error")
        }
        applying = false
        if(!qmlapp.globalConfigs.backendApplyPending && qmlapp.globalConfigs.applyPhase === 0)
            qmlapp.msnConnector.callPy("ocr", "deferAdmissions", [false])
        }
        qmlapp.msnConnector.requestCall("ocr", "setApi", [nowKey, info])
    }

    // 终止所有任务
    function stopAllMissions() {
        const pyStatus = qmlapp.msnConnector.callPy("ocr", "getStatus", [])
        const msnLen = Object.keys(pyStatus.missionListsLength).length
        if(msnLen == 0) { // 无任务
            qmlapp.popup.simple(qsTr("当前没有运行中的任务"), "")
            return
        }

        let n = 0
        for(let k in pyStatus.missionListsLength)
            n += pyStatus.missionListsLength[k]
        const s = qsTr("当前已有%1组任务队列、共%2个任务正在执行。\n要强制终止全部任务吗？").arg(msnLen).arg(n)

        const argd = {yesText: qsTr("强制终止任务")}
        const callback = (flag)=>{ if(flag) qmlapp.msnConnector.callPy("ocr", "stopAllMissions", []) }
        qmlapp.popup.dialog("", s, callback, "warning", argd)
    }

    // 部署进一个Configs的配置项里，可动态改变配置页。
    // 传入configs页引用和所在字典键（只能在最外层）
    function deploy(page, configKey) {
        // 记录已部署页面
        const pageId = page.toString()
        deployDict[pageId] = { 
            "page": page,
            "configKey": configKey,
        }
        // 返回初始配置字典
        if(apiKey === ""){
            return { // apiKey未初始化，先返回空的占位
                "title": "",
                "type": "group",
            }
        }
        else{ // apiKey已初始化，返回对应配置
            return localOptions[apiKey]
        }
    }

    // 初始化1：传入python ocr信息，整理信息，返回全局配置字典
    function init1(options) {
        localOptions = {}
        serviceRefs = ({})
        globalOptions = makeGlobalOptions()
        for (var key in options) {
            const gOpt = options[key].global_options
            const lOpt = options[key].local_options
            serviceRefs[key] = (options[key].meta && options[key].meta.serviceRefs) || []
            if(gOpt) { // 有全局配置
                globalOptions.api.optionsList.push([key, gOpt.title])
                globalOptions[key] = gOpt
            }
            else { // 无全局配置
                globalOptions.api.optionsList.push([key, key])
                globalOptions[key] = {"title":key, "type":"group"}
            }
            if(lOpt) // 有局部配置
                localOptions[key] = lOpt
            else // 无局部配置
                localOptions[key] = {"title":key, "type":"group"}
        }
        const preferred = ["win32_PaddleOCRv6_CPU", "win32_PaddleOCRv6_CUDA"].find(key => localOptions.hasOwnProperty(key)) || Object.keys(localOptions)[0]
        if(preferred) globalOptions.api.default = preferred
        qmlapp.globalConfigs.configDict.ocr = globalOptions // 写入全局预配置
    }
    // 未安装任何 OCR 后端时的提示。
    // 措辞必须明确：本体【不内置】任何 OCR 推理，也没有可用的 CPU 后端。
    function noBackendHint() {
        return qsTr("未安装 OCR 后端。\n本体只提供界面与任务调度，不内置任何文字识别推理（包括 CPU）。\n请解压一个 OCR 插件归档到 Umi-OCR 本体目录后刷新插件列表。")
    }

    // 初始化2：应用更改
    function init2() {
        if(Object.keys(localOptions).length === 0) {
            apiKey = ""
            qmlapp.msnConnector.callPy("ocr", "setApi", ["", {}])
            return
        }
        applyConfigs(false)
        console.log("OcrManager 初始化OCR管理器完毕！")
    }

    function buildWarmupInfo() {
        if(!apiKey || !localOptions.hasOwnProperty(apiKey))
            return undefined
        const info = {}
        const options = localOptions[apiKey]
        const prefix = "ocr." + apiKey + "."
        for(const key in options) {
            const option = options[key]
            if(typeof option !== "object" || !option.hasOwnProperty("default"))
                continue
            const fullKey = prefix + key
            info[fullKey] = UmiSettings.contains("ScreenshotOCR", fullKey)
                ? UmiSettings.value("ScreenshotOCR", fullKey, option.default)
                : option.default
        }
        info["ocr.taskType"] = "screenshot"
        return info
    }

    function warmup(showMessage=false) {
        // A plugin-declared service has its own global lifecycle policy.  Do
        // not start a second worker/server path through the legacy OCR
        // warm-up controls; the tray action (when invoked programmatically)
        // merely asks that one shared service to prestart.
        if(usesSharedService()) {
            const refs = serviceRefs[apiKey] || []
            qmlapp.globalConfigs.configurePluginService(apiKey, refs[0])
            return "[Success] 模型服务正在后台预启动。"
        }
        const info = buildWarmupInfo()
        if(!info) return "[Error] OCR 接口尚未初始化。"
        modelState = "warming"
        qmlapp.msnConnector.requestCall("ocr", "warmup", [info])
        return "[Success] 模型正在后台预热。"
    }
    Connections {
        target: qmlapp.msnConnector
        function onOperationFinished(kind, operation, result) {
            if(kind !== "ocr" || operation !== "warmup") return
            refreshModelState(false)
            if(typeof result === "string" && result.startsWith("[Error]"))
                qmlapp.popup.message(qsTr("预热失败"), result, "error")
        }
    }

    function scheduleWarmup() {
        warmupTimer.stop()
        if(usesSharedService())
            return
        if(!apiKey || qmlapp.globalConfigs.getValue("ocr.lifecycle.warmupMode") !== "delayed")
            return
        refreshModelState(false)
        if(modelState === "loaded" || modelState === "warming")
            return
        const minutes = Number(qmlapp.globalConfigs.getValue("ocr.lifecycle.warmupDelayMinutes"))
        warmupTimer.interval = Math.max(0, Math.min(60, isNaN(minutes) ? 0 : minutes)) * 60000
        warmupTimer.start()
    }

    function refreshModelState(showError=true) {
        if(!apiKey)
            return undefined
        if(usesSharedService()) {
            const refs = serviceRefs[apiKey] || []
            const service = pluginsConnector.getServiceStatus(apiKey, refs[0]) || ({})
            const state = service.state || "stopped"
            modelState = (state === "ready" || state === "busy" || state === "sleeping")
                ? "loaded" : (state === "starting" ? "warming" : "unloaded")
            modelIdleSeconds = Number(service.idleSeconds || 0)
            modelBusy = Number(service.activeLeases || 0) > 0 || Number(service.waitingRequests || 0) > 0
            const error = service.error || ""
            if(error && showError && error !== lastModelError) {
                lastModelError = error
                qmlapp.popup.message(qsTr("模型服务异常"), error, "error")
            }
            else if(!error) {
                lastModelError = ""
            }
            return {apiState: service, missionListsLength: ({})}
        }
        const status = qmlapp.msnConnector.callPy("ocr", "getStatus", [])
        if(!status || !status.apiState)
            return status
        modelState = status.apiState.state || "unloaded"
        modelIdleSeconds = Number(status.apiState.idleSeconds || 0)
        modelBusy = Object.keys(status.missionListsLength || {}).length > 0
        const error = status.apiState.error || ""
        if(error && showError && error !== lastModelError) {
            lastModelError = error
            qmlapp.popup.message(qsTr("OCR 模型后台异常"), error, "error")
        }
        else if(!error) {
            lastModelError = ""
        }
        return status
    }

    function releaseModel(showMessage=true) {
        if(usesSharedService()) {
            if(showMessage)
                qmlapp.popup.simple(qsTr("模型服务由全局设置管理"), qsTr("请在全局设置的模型服务区域调整预启动和空闲策略。"))
            return false
        }
        const status = refreshModelState(false)
        if(!status || modelBusy) {
            if(showMessage)
                qmlapp.popup.simple(qsTr("无法清理 OCR 后台"), qsTr("OCR 任务正在运行。"))
            return false
        }
        const msg = qmlapp.msnConnector.callPy("ocr", "releaseModel", [])
        if(msg && !msg.startsWith("[Error]")) {
            modelState = "unloaded"
            modelIdleSeconds = 0
            if(showMessage)
                qmlapp.popup.simple(qsTr("OCR 后台已清理"), msg)
            return true
        }
        if(showMessage)
            qmlapp.popup.message(qsTr("清理 OCR 后台失败"), msg || qsTr("未知错误"), "error")
        return false
    }

    function toggleModel() {
        refreshModelState(false)
        if(modelState === "loaded")
            releaseModel(true)
        else if(modelState !== "warming")
            warmup(true)
    }

    function resetCleanupSchedule() {
        memoryCheckTicks = 0
    }

    function checkCleanup() {
        if(usesSharedService())
            return
        const policy = qmlapp.globalConfigs.getValue("ocr.lifecycle.cleanupPolicy")
        if(policy === "never")
            return
        if(policy === "memory") {
            memoryCheckTicks += 1
            if(memoryCheckTicks < 6)
                return
            memoryCheckTicks = 0
        }
        const status = refreshModelState(false)
        if(!status || modelState !== "loaded" || modelBusy)
            return
        if(policy === "memory") {
            const percent = Number(qmlapp.msnConnector.callPy("ocr", "getSystemMemoryPercent", []))
            if(percent > 90)
                releaseModel(false)
        }
        else if(policy === "idle") {
            const minutes = Number(qmlapp.globalConfigs.getValue("ocr.lifecycle.idleCleanupMinutes"))
            if(modelIdleSeconds >= Math.max(5, Math.min(120, isNaN(minutes) ? 30 : minutes)) * 60)
                releaseModel(false)
        }
    }

    Connections {
        target: qmlapp.msnConnector
        function onOperationFinished(kind, operation, result) {
            if(kind === "ocr" && operation === "setApi" && applying && applyCallback) {
                const callback = applyCallback
                applyCallback = null
                callback(result)
            }
        }
    }

    // ========================= 【内部】 =========================
    property string apiKey: "" // 当前选定的apiKey
    // 是否有可用的 OCR 后端。基础包不内置任何后端，因此默认为 false 。
    property bool available: apiKey !== ""
    property var deployDict: {} // 存放 部署了配置的页面
    property var localOptions: {} // 缓存局部配置
    property var serviceRefs: ({}) // capability → 插件级共享服务 id
    property var pyOptions: undefined // 由py定义的配置参数的原始内容
    property string modelState: "unloaded"
    property bool modelBusy: false
    property real modelIdleSeconds: 0
    property string lastModelError: ""
    property int memoryCheckTicks: 0
    property string modelActionText: usesSharedService()
        ? qsTr("模型服务由全局设置管理")
        : (modelState === "loaded"
            ? qsTr("清理 OCR 后台")
            : (modelState === "warming" ? qsTr("OCR 模型预热中") : qsTr("预热 OCR 模型")))
    property bool modelActionEnabled: apiKey !== "" && !usesSharedService() && modelState !== "warming"

    function usesSharedService() {
        return apiKey !== "" && Array.isArray(serviceRefs[apiKey]) && serviceRefs[apiKey].length > 0
    }

    Timer {
        id: warmupTimer
        repeat: false
        onTriggered: warmup(false)
    }
    Timer {
        interval: 3000
        repeat: true
        running: apiKey !== ""
        onTriggered: refreshModelState(true)
    }
    Timer {
        interval: 60000
        repeat: true
        running: apiKey !== ""
        onTriggered: checkCleanup()
    }

    Component.onCompleted: {
        deployDict = {}
    }
}
