// ====================================================
// =============== 结构化文档 接口管理 ===============
// ====================================================

// qml 的 api key 与 python document/api 注册表中的键要一致。
//
// 与 OcrManager 平级但【不共用】：document 后端可能是外部服务，
// 需要连接测试与健康检查，失败原因也与 OCR 完全不同。

import QtQuick 2.15

Item {
    property bool applying: false
    property var applyCallback: null


    // 配置在python那边编写
    property var globalOptions: makeGlobalOptions()
    function makeGlobalOptions() { return {
        "title": qsTr("结构化文档"),
        "type": "group",

        "btns": {
            "title": qsTr("操作"),
            "btnsList": [
                {"text":qsTr("强制终止任务"), "onClicked": stopAllMissions, "textColorKey":"noColor"},
                {"text":qsTr("检查后端状态"), "onClicked": ()=>runHealthCheck(true)},

            ],
        },
        "api": {
            "title": qsTr("当前接口"),
            "optionsList": [],
        },
    }

    }

    // ========================= 【外部接口】 =========================

    function applyConfigs(showSuccess=true) { qmlapp.globalConfigs.requestBackendApply() }

    function backendSpec() {
        const nowKey = Object.keys(localOptions).length ? qmlapp.globalConfigs.getValue("document.api") : ""
        if(nowKey && !localOptions.hasOwnProperty(nowKey))
            throw new Error(qsTr("结构化文档接口列表中不存在 %1").arg(nowKey))
        const info = {}
        const all = qmlapp.globalConfigs.getValueDict()
        for(const key in all)
            if(nowKey && key.startsWith("document." + nowKey + ".")) info[key] = all[key]
        const services = qmlapp.globalConfigs.getPluginServiceValues(nowKey, serviceRefs[nowKey] || [])
        for(const key in services) info[key] = services[key]
        return {apiKey: nowKey, info: info}
    }

    function backendApplied(spec) {
        apiKey = spec.apiKey
        for(const key in deployDict) {
            const entry = deployDict[key]
            if(!entry.page || !entry.page.configDict) { delete deployDict[key]; continue }
            entry.page.configDict[entry.configKey] = localOptions[apiKey] || {title: "", type: "group"}
            entry.page.reload()
        }
        healthOk = false
        healthMessage = qsTr("尚未启动；首次解析时检查并加载。")
    }

    // 健康检查。showMessage=true 时弹窗展示结果。
    // 这是"可用"的唯一判定来源：未通过检查时界面不得宣称后端可用。
    function runHealthCheck(showMessage=true) {
        if(!apiKey) {
            healthOk = false
            healthMessage = noBackendHint()
            if(showMessage)
                qmlapp.popup.message(qsTr("结构化文档后端不可用"), healthMessage, "warning")
            return false
        }
        const allDict = qmlapp.globalConfigs.getValueDict()
        const prefix = "document." + apiKey
        const info = {}
        for(let k in allDict) {
            if(k.startsWith(prefix))
                info[k] = allDict[k]
        }
        const serviceInfo = qmlapp.globalConfigs.getPluginServiceValues(
            apiKey, serviceRefs[apiKey] || [])
        for(let k in serviceInfo)
            info[k] = serviceInfo[k]
        healthMessage = qsTr("正在后台检查…")
        qmlapp.msnConnector.requestCall("document", "health", [info])
        return true
    }

    // 终止所有任务
    function stopAllMissions() {
        const pyStatus = qmlapp.msnConnector.callPy("document", "getStatus", [])
        const msnLen = Object.keys(pyStatus.missionListsLength).length
        if(msnLen == 0) {
            qmlapp.popup.simple(qsTr("当前没有运行中的任务"), "")
            return
        }
        let n = 0
        for(let k in pyStatus.missionListsLength)
            n += pyStatus.missionListsLength[k]
        const s = qsTr("当前已有%1组任务队列、共%2个任务正在执行。\n要强制终止全部任务吗？").arg(msnLen).arg(n)
        const argd = {yesText: qsTr("强制终止任务")}
        const callback = (flag)=>{ if(flag) qmlapp.msnConnector.callPy("document", "stopAllMissions", []) }
        qmlapp.popup.dialog("", s, callback, "warning", argd)
    }

    // 未安装任何 document 后端时的提示。措辞必须明确，不得暗示内置可用。
    function noBackendHint() {
        return qsTr("未安装结构化文档插件。\n本体不内置文档解析后端，请安装一个 document 能力插件后刷新插件列表。")
    }

    // 部署进一个Configs的配置项里
    function deploy(page, configKey) {
        const pageId = page.toString()
        deployDict[pageId] = {
            "page": page,
            "configKey": configKey,
        }
        if(apiKey === ""){
            return {
                "title": "",
                "type": "group",
            }
        }
        return localOptions[apiKey]
    }

    // 初始化1：传入python document信息，整理信息，返回全局配置字典
    function init1(options) {
        localOptions = {}
        serviceRefs = ({})
        globalOptions = makeGlobalOptions()
        for (var key in options) {
            const gOpt = options[key].global_options
            const lOpt = options[key].local_options
            serviceRefs[key] = (options[key].meta && options[key].meta.serviceRefs) || []
            if(gOpt) {
                globalOptions.api.optionsList.push([key, gOpt.title])
                globalOptions[key] = gOpt
            }
            else {
                globalOptions.api.optionsList.push([key, key])
                globalOptions[key] = {"title":key, "type":"group"}
            }
            localOptions[key] = lOpt ? lOpt : {"title":key, "type":"group"}
        }
        if(globalOptions.api.optionsList.length === 0) {
            // 可选后端缺席不是无效配置，刷新时也要移除旧接口枚举。
            delete qmlapp.globalConfigs.configDict.document
            return
        }
        qmlapp.globalConfigs.configDict.document = globalOptions
    }

    // 初始化2：应用更改
    function init2() { applyConfigs(false) }

    Connections {
        target: qmlapp.msnConnector
        function onOperationFinished(kind, operation, result) {
            if(kind !== "document" || operation !== "health") return
            healthOk = !!(result && result.ok)
            healthMessage = result && result.message || qsTr("未知错误")
            const stopped = result && result.details && result.details.state === "stopped"
            if(healthOk || stopped) qmlapp.popup.simple(qsTr("文档后端状态"), healthMessage)
            else qmlapp.popup.message(qsTr("文档后端异常"), healthMessage, "error")
        }
    }

    Connections {
        target: qmlapp.msnConnector
        function onOperationFinished(kind, operation, result) {
            if(kind === "document" && operation === "setApi" && applying && applyCallback) {
                const callback = applyCallback
                applyCallback = null
                callback(result)
            }
        }
    }

    // ========================= 【内部】 =========================
    property string apiKey: ""
    property var deployDict: {}
    property var localOptions: {}
    property var serviceRefs: ({})
    property bool healthOk: false
    property string healthMessage: ""
    // 供界面显示：仅在健康检查通过后才算可用
    property bool available: apiKey !== ""

    Component.onCompleted: {
        deployDict = {}
    }
}
