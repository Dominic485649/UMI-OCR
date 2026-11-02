// ==========================================
// =============== OCR接口管理 ===============
// ==========================================

// qml的 api key 与 python api.ocr 中的字典要一致

import QtQuick 2.15
import "../Configs"

Item {
    id: ocrManager
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
                {"text":qsTr("预热当前模型"), "onClicked": ()=>warmup(true), "textColorKey":"yesColor"},
                {"text":qsTr("终止文字识别任务"), "onClicked": stopAllMissions, "textColorKey":"noColor"},
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
                "onChanged": ()=>Qt.callLater(scheduleWarmup),
            },
            "warmupDelayMinutes": {
                "title": qsTr("预热延迟"),
                "default": 0,
                "min": 0,
                "max": 60,
                "isInt": true,
                "unit": qsTr("分钟"),
                "toolTip": qsTr("仅用于“延迟预热”。0 表示界面启动后立即在后台加载；提高数值可推迟显存和内存占用。"),
                "onChanged": ()=>Qt.callLater(scheduleWarmup),
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
            "title": qsTr("识别模型"),
            "toolTip": qsTr("截图、批量图片和批量文档共用此模型选择；各页面的识别参数分别保存。"),
            "optionsList": [],
            "onChanged": (value, old)=>{
                if(old === undefined) return
                if(qmlapp.globalConfigs.backendsBusy() || applying || qmlapp.globalConfigs.applyPhase !== 0) {
                    qmlapp.popup.simple(qsTr("无法切换模型"), qsTr("任务正在运行或模型配置正在应用，请稍后重试。"))
                    return true
                }
            },
        },
    }

    }

    // ========================= 【外部接口】 =========================

    // 应用更改，showSuccess=false时不显示成功提示
    function applyConfigs(showSuccess=true) {


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
            refreshDeployedPages()
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

    // 各任务类别只保留一个轻量来源，关闭任务页面不销毁识别参数。
    property var taskSources: ({})
    property int taskSourcesRevision: 0
    Component {
        id: taskSourceComponent
        Configs { autoLoad: false; lazyPanel: true; preserveCacheOnReload: true }
    }
    function taskSource(category) {
        if(["ScreenshotOCR", "BatchOCR", "BatchPDF"].indexOf(category) < 0)
            throw new Error("Unknown OCR settings category: " + category)
        if(taskSources[category]) return taskSources[category]
        const source = taskSourceComponent.createObject(ocrManager, {
            category_: category, configDict: {ocr: localOptions[apiKey] || {title: "", type: "group"}}
        })
        if(!source) throw new Error("Cannot create OCR settings source: " + category)
        source.reload()
        const sources = Object.assign({}, taskSources)
        sources[category] = source
        taskSources = sources
        taskSourcesRevision++
        return source
    }
    function ensureTaskSources() {
        for(const category of ["ScreenshotOCR", "BatchOCR", "BatchPDF"]) taskSource(category)
    }
    function taskParameterItems(source) {
        // 重载会先清空 originDict；空组时也要跟踪定义完成通知，避免绑定停在缺组布局。
        const revision = source.definitionRevision
        const group = source.originDict.ocr
        if(!group) return []
        function reference(entry) {
            const result = {key: entry.key, sourceConfigs: source, sourceKey: entry.key}
            if(entry.items !== undefined) result.items = entry.items.map(reference)
            return result
        }
        return source.defaultPanelLayout(group).filter(entry => {
            if(entry.key === "ocr.preset") return false
            const origin = source.originDict[entry.key]
            return !(entry.key === "ocr.detModel" && origin.optionsList && origin.optionsList.length <= 1)
        }).map(reference)
    }

    // 兼容其他插件部署局部配置；内置任务改用应用级来源。
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

    // 只移动展示入口，模型共用全局值，识别参数仍属于各任务类别。
    function modelPanelLayout(page) {
        const global = qmlapp.globalConfigs
        const globalRevision = global.definitionRevision
        const layout = page.defaultPanelLayout().filter(entry => entry.key !== "ocr")
        const items = []
        if(global.originDict["ocr.api"])
            items.push({key: "ocr.api", sourceConfigs: global, sourceKey: "ocr.api"})
        const source = page.valueSources.ocr
        if(source) items.push(...taskParameterItems(source))
        if(items.length)
            layout.unshift({key: "ocr", origin: {title: qsTr("文字识别"), type: "group"}, items: items})
        return layout
    }

    function modelDisplayName(option, key) {
        const global = option.global_options || ({})
        const local = option.local_options || ({})
        const declared = (option.meta && option.meta.modelName) || global.modelName || local.modelName
        if(typeof declared === "string" && declared.trim()) return declared
        // 单模型插件可直接提供其真实枚举键；宿主不识别任何特定插件或产品名。
        const detector = local.detModel
        if(detector && detector.optionsList && detector.optionsList.length === 1) {
            const model = detector.optionsList[0][0]
            if(typeof model === "string" && model.trim()) return model
        }
        return global.title || local.title || key
    }

    function refreshDeployedPages() {
        const options = localOptions[apiKey] || {title: "", type: "group"}
        for(const category in taskSources) {
            const source = taskSources[category]
            source.configDict = {ocr: options}
            source.reload()
        }
        taskSourcesRevision++
        for(const key in deployDict) {
            const entry = deployDict[key]
            if(!entry.page || !entry.page.configDict) { delete deployDict[key]; continue }
            entry.page.configDict[entry.configKey] = options
            entry.page.reload()
        }
    }

    function orderedModelKeys(options) {
        return Object.keys(options).map((key, index) => ({key: key, index: index})).sort((left, right) => {
            const a = (options[left.key].meta || {}).settingsOrder
            const b = (options[right.key].meta || {}).settingsOrder
            const first = typeof a === "number" && isFinite(a) ? a : Infinity
            const second = typeof b === "number" && isFinite(b) ? b : Infinity
            return first === second ? left.index - right.index : (first < second ? -1 : 1)
        }).map(entry => entry.key)
    }
    // 初始化1：只调整模型展示和新配置默认值，不改变插件加载顺序。
    function init1(options) {
        localOptions = {}
        serviceRefs = ({})
        globalOptions = makeGlobalOptions()
        for (const key of orderedModelKeys(options)) {
            const gOpt = options[key].global_options
            const lOpt = options[key].local_options
            // QVariantList 在 QML 中是 V4Sequence，先复制为 JS 数组以统一共享服务判断。
            const refs = (options[key].meta && options[key].meta.serviceRefs) || []
            serviceRefs[key] = Array.prototype.slice.call(refs)
            if(gOpt) { // 有全局配置
                globalOptions.api.optionsList.push([key, modelDisplayName(options[key], key)])
                globalOptions[key] = gOpt
            }
            else { // 无全局配置
                globalOptions.api.optionsList.push([key, modelDisplayName(options[key], key)])
                globalOptions[key] = {"title":key, "type":"group"}
            }
            if(lOpt) // 有局部配置
                localOptions[key] = lOpt
            else // 无局部配置
                localOptions[key] = {"title":key, "type":"group"}
        }
        if(globalOptions.api.optionsList.length === 0) {
            // 基础包允许不安装 OCR 后端，不注册无法选择的接口枚举。
            delete qmlapp.globalConfigs.configDict.ocr
            return
        }
        // 新配置按插件注册表顺序选择；已有有效选择仍由 Configs 原样恢复。
        const preferred = Object.keys(localOptions)[0]
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
            refreshDeployedPages()
            warmupTimer.stop()
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
        // 页面实际持久化键是 ocr.<参数>，不包含后端 id。
        function collect(group, prefix="ocr.") {
            for(const key in group) {
                const option = group[key]
                if(!option || typeof option !== "object") continue
                const fullKey = prefix + key
                if(option.type === "group") collect(option, fullKey + ".")
                else if(option.hasOwnProperty("default")) {
                    info[fullKey] = UmiSettings.contains("ScreenshotOCR", fullKey)
                        ? UmiSettings.value("ScreenshotOCR", fullKey, option.default) : option.default
                }
            }
        }
        collect(localOptions[apiKey])
        info["ocr.taskType"] = "screenshot"
        return info
    }

    function warmup(showMessage=false) {
        if(qmlapp.globalConfigs.backendsBusy() || applying || qmlapp.globalConfigs.backendApplyPending || qmlapp.globalConfigs.applyPhase !== 0)
            return "[Warning] " + qsTr("任务正在运行或配置正在应用，跳过后台预热。")
        // 统一策略只启动现有共享服务，绝不另起 VL worker。
        if(usesSharedService()) {
            const refs = serviceRefs[apiKey] || []
            const result = qmlapp.globalConfigs.configurePluginService(apiKey, refs[0])
            return result.ok ? "[Success] " + qsTr("模型服务正在后台预启动。") : "[Warning] " + result.message
        }
        const info = buildWarmupInfo()
        if(!info) return "[Error] " + qsTr("OCR 接口尚未初始化。")
        modelState = "warming"
        qmlapp.msnConnector.requestCall("ocr", "warmup", [info])
        return "[Success] " + qsTr("模型正在后台预热。")
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
        if(qmlapp.globalConfigs.backendsBusy()) {
            if(showMessage) qmlapp.popup.simple(qsTr("无法清理 OCR 后台"), qsTr("任务正在运行。"))
            return false
        }
        if(usesSharedService()) {
            refreshModelState(false)
            if(modelBusy || pluginsConnector.isBusy()) return false
            const refs = serviceRefs[apiKey] || []
            // stop_owned 再次检查 OCR/document 租约及等待请求，绝不使用强制 shutdown。
            pluginsConnector.requestOperation("stop_owned", apiKey, refs[0], null)
            return true
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
        if(qmlapp.globalConfigs.backendsBusy() || applying || qmlapp.globalConfigs.backendApplyPending) return
        const policy = qmlapp.globalConfigs.getValue("ocr.lifecycle.cleanupPolicy")
        if(policy === "never") return
        if(policy === "memory") {
            memoryCheckTicks += 1
            if(memoryCheckTicks < 6) return
            memoryCheckTicks = 0
            const percent = Number(qmlapp.msnConnector.callPy("ocr", "getSystemMemoryPercent", []))
            if(percent <= 90 || isNaN(percent)) return
            qmlapp.globalConfigs.maintainPluginServices("memory")
            if(!usesSharedService()) releaseModel(false)
            return
        }
        // 即便 GUI 当前选 PP，也维护由文档任务使用过的同一 VL 服务。
        qmlapp.globalConfigs.maintainPluginServices("idle")
        if(usesSharedService()) return
        const status = refreshModelState(false)
        if(!status || modelState !== "loaded" || modelBusy) return
        const minutes = Number(qmlapp.globalConfigs.getValue("ocr.lifecycle.idleCleanupMinutes"))
        if(modelIdleSeconds >= Math.max(5, Math.min(120, isNaN(minutes) ? 30 : minutes)) * 60)
            releaseModel(false)
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
    property string modelActionText: modelState === "loaded"
        ? qsTr("清理 OCR 后台")
        : (modelState === "warming" ? qsTr("OCR 模型预热中") : qsTr("预热 OCR 模型"))
    property bool modelActionEnabled: apiKey !== "" && !modelBusy && !applying && modelState !== "warming"

    function usesSharedService() {
        return apiKey !== "" && Array.isArray(serviceRefs[apiKey]) && serviceRefs[apiKey].length > 0
    }

    Timer {
        id: warmupTimer
        repeat: false
        onTriggered: {
            if(qmlapp.globalConfigs.backendsBusy() || applying || qmlapp.globalConfigs.backendApplyPending || qmlapp.globalConfigs.applyPhase !== 0 || pluginsConnector.isBusy()) {
                // 预热低优先级，只保留这一份待执行计划，任务结束后再尝试。
                interval = 1000
                start()
                return
            }
            warmup(false)
        }
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
