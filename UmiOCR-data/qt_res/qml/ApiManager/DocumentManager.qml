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

    // 应用更改，showSuccess=false时不显示成功提示
    function applyConfigs(showSuccess=true) {

        function successUpdate() {
            for (let key in deployDict) {
                const p = deployDict[key].page
                if(!p.configDict) {
                    delete deployDict[key]
                    continue
                }
                const k = deployDict[key].configKey
                p.configDict[k] = localOptions[apiKey]
                p.reload()
            }
        }

        if(Object.keys(localOptions).length === 0){
            qmlapp.popup.message("", noBackendHint(), "error")
            return
        }

        const nowKey = qmlapp.globalConfigs.getValue("document.api")
        if(!localOptions.hasOwnProperty(nowKey)) {
            const s = qsTr("结构化文档接口列表中不存在 %1").arg(nowKey)
            qmlapp.popup.message("", s, "error")
            return
        }
        // 验证 py 是否有执行中的任务
        const lengths = qmlapp.msnConnector.callPy("document", "getMissionListsLength", [])
        const msnLen = Object.keys(lengths).length
        if(msnLen > 0) {
            qmlapp.globalConfigs.requestBackendApply()
            return
        }
        // 从全局配置中，提取出目前apiKey对应的配置项
        const allDict = qmlapp.globalConfigs.getValueDict()
        const prefix = "document." + nowKey
        const info = {}
        for(let k in allDict) {
            if(k.startsWith(prefix)) {
                info[k] = allDict[k]
            }
        }
        const serviceInfo = qmlapp.globalConfigs.getPluginServiceValues(
            nowKey, serviceRefs[nowKey] || [])
        for(let k in serviceInfo)
            info[k] = serviceInfo[k]
        applying = true
        qmlapp.msnConnector.callPy("document", "deferAdmissions", [true])
        applyCallback = function(msg) {
        msg = String(msg)

        if(msg.startsWith("[Success]")) {
            apiKey = nowKey
            successUpdate()
            // 应用之后立刻做一次健康检查：只有检查通过才允许显示"可用"
            healthOk = false
            healthMessage = qsTr("尚未启动；首次解析时检查并加载。")
            if(showSuccess) {
                qmlapp.popup.simple(qsTr("结构化文档接口应用成功"), qsTr("当前接口为【%1】").arg(nowKey))
            }
        }
        else {
            qmlapp.popup.message(qsTr("结构化文档接口应用失败"), msg, "error")
        }
        applying = false
        if(!qmlapp.globalConfigs.backendApplyPending && qmlapp.globalConfigs.applyPhase === 0)
            qmlapp.msnConnector.callPy("document", "deferAdmissions", [false])
        }
        qmlapp.msnConnector.requestCall("document", "setApi", [nowKey, info])
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
    function init2() {
        if(Object.keys(localOptions).length === 0) {
            apiKey = ""
            qmlapp.msnConnector.callPy("document", "setApi", ["", {}])
            return
        }
        applyConfigs(false)
        console.log("DocumentManager 初始化结构化文档管理器完毕！")
    }

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
