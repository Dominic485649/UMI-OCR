// =========================================
// =============== 全局配置项 ===============
// =========================================

import QtQuick 2.15
import GlobalConfigsConnector 1.0
import PluginsConnector 1.0
import "../Configs"
import "../ApiManager"

Configs {
    id: gRoot
    lazyPanel: true
    category_: "Global"
    autoLoad: false
    // ========================= 【全局配置项】 =========================
    configDict: makeConfigDict()
    function makeConfigDict() { return {

        // 快捷方式
        "shortcut": {
            "title": qsTr("快捷方式"),
            "type": "group",

            "desktop": {
                "title": qsTr("桌面"),
                "default": false,
                "onChanged": (newFlag, oldFlag)=>{
                    if(oldFlag !== undefined)
                        return changeShortcut(newFlag, "desktop")
                },
            },
            "startMenu": {
                "title": qsTr("开始菜单"),
                "default": false,
                "onChanged": (newFlag, oldFlag)=>{
                    if(oldFlag !== undefined)
                        return changeShortcut(newFlag, "startMenu")
                },
            },
            "startup": {
                "title": qsTr("开机自启"),
                "default": false,
                "onChanged": (newFlag, oldFlag)=>{
                    if(oldFlag !== undefined)
                        return changeShortcut(newFlag, "startup")
                },
            },
        },

        // 界面和外观
        "ui": {
            "title": qsTr("界面和外观"),
            "type": "group",

            "i18n": _getI18n(),
            "theme": {
                "title": qsTr("主题"),
                "optionsList": theme.manager.getOptionsList(), // 从全局主题管理器中取列表
                "default": "Default Light",
                "onChanged": (val, old)=>{
                    applyThemeSettings(val)
                    if(old)
                        qmlapp.popup.simple(qsTr("切换主题"), theme.manager.getTitle(val))
                },
            },
            "systemLightTheme": {
                "title": qsTr("系统浅色模式主题"),
                "default": "Default Light",
                "optionsList": theme.manager.getOptionsList(false),
                "toolTip": qsTr("选择“跟随系统”时，Windows 使用浅色模式所应用的主题。"),
                "onChanged": (val)=>applyThemeSettings(undefined, val),
            },
            "systemDarkTheme": {
                "title": qsTr("系统深色模式主题"),
                "default": "Neutral Dark",
                "optionsList": theme.manager.getOptionsList(false),
                "toolTip": qsTr("选择“跟随系统”时，Windows 使用深色模式所应用的主题。默认背景为 rgb(24, 24, 24)。"),
                "onChanged": (val)=>applyThemeSettings(undefined, undefined, val),
            },
            "fontBtn": {
                "title": qsTr("字体"),
                "btnsList": [
                    {
                        "text":qsTr("修改字体"),
                        "onClicked": openFontPanel,
                        "textColorKey":"specialTextColor",
                    },
                ],
            },
            "fontFamily": {
                "default": "Microsoft YaHei",
                "onChanged": (val)=>{ theme.fontFamily = val },
            },
            "dataFontFamily": {
                "default": "Microsoft YaHei",
                "onChanged": (val)=>{ theme.dataFontFamily = val },
            },
            "scale": {
                "title": qsTr("界面与文字大小"),
                "default": 1,
                "optionsList": [
                    [0.5, "50%"],
                    [0.75, "75%"],
                    [0.9, "90%"],
                    [1, "100%"],
                    [1.1, "110%"],
                    [1.25, "125%"],
                    [1.5, "150%"],
                ],
                "onChanged": (val)=>{
                    size_.scale = val
                },
            },
            "disableEffect": {
                "title": qsTr("禁用美化效果"),
                "default": false,
                "toolTip": qsTr("在低配置机器上，禁用动画、阴影等效果可减少部分资源占用"),
                "onChanged": (flag)=>{
                    qmlapp.enabledEffect = !flag
                },
            },
            "imgShowOverlay": {
                "title": qsTr("图片预览默认显示叠加层"),
                "default": true,
                "toolTip": qsTr("默认开启/关闭叠加层显示\n对所有图片预览组件生效"),
            }
        },

        // 窗口
        "window": {
            "title": qsTr("窗口"),
            "type": "group",

            "startupInvisible": {
                "title": qsTr("启动时缩小到任务栏"),
                "default": false,
                "toolTip": qsTr("软件启动时，不弹出主窗口"),
            },
            "isMainWindowTop": {
                "title": qsTr("窗口置顶"),
                "default": false,
                "toolTip": qsTr("捷径：窗口左上角图钉"),
                "onChanged": (val)=>{
                    mainWindowRoot.isMainWindowTop = val
                },
            },
            "barIsLock": {
                "title": qsTr("锁定标签栏"),
                "default": false,
                "toolTip": qsTr("捷径：窗口右上角小锁"),
                "onChanged": (val)=>{
                    qmlapp.tab.barIsLock = val
                },
            },
            "closeWin2Hide": {
                "title": qsTr("关闭主窗口时"),
                "optionsList": [
                    [true, qsTr("最小化到系统托盘")],
                    [false, qsTr("退出应用")],
                ],
            },
            "simpleNotificationType": utilsDicts.getSimpleNotificationType(true),
            "geometry": { // 存放主窗位置大小，字符串格式 "x,y,w,h"
                "type": "var",
                "default": "", // 如： 300,20,500,300
            },
            "messageMemory": { // 存放“不再弹出”的消息弹窗的mid
                "type": "var",
                "default": [], // 如： ["aaa", "bbb"]
            },
            "doubleLayout": { // 存放 Double__Layout 的 hide 信息
                "type": "var",
                "default": {}, // 如： {"ScreenshotOCR1": 0, }
            },
        },

        // 截图
        "screenshot": {
            "title": qsTr("截图"),
            "type": "group",

            "hideWindow": {
                "title": qsTr("截图前隐藏主窗口"),
                "toolTip": qsTr("截图前，如果主窗口处于前台，则隐藏主窗口\n将会延时等待主窗口关闭"),
                "default": true,
            },
            "hideWindowTime": {
                "title": qsTr("隐藏等待时间"),
                "default": 0.2,
                "min": 0,
                "unit": qsTr("秒"),
                "isInt": false,
                "advanced": true,
            },
            "sdrWhiteNits": {
                "title": qsTr("HDR SDR 白点"),
                "default": 0,
                "min": 0,
                "max": 1000,
                "unit": "nits",
                "isInt": false,
                "advanced": true,
                "toolTip": qsTr("0 = 读取 Windows 系统 SDR 白色亮度。手动提高可保留更亮的 HDR 映射，但可能让普通显示器上的导出图偏暗。"),
            },
            "peakNits": {
                "title": qsTr("HDR 峰值亮度"),
                "default": 0,
                "min": 0,
                "max": 10000,
                "unit": "nits",
                "isInt": false,
                "advanced": true,
                "toolTip": qsTr("0 = 读取 DXGI 显示器峰值。值越高，BT.2390 会压缩更大的高光范围；设置错误会降低对比度或丢失高光层次。"),
            },
        },

        // 服务
        "server": {
            "title": qsTr("服务"),
            "type": "group",

            "enable": {
                "title": qsTr("允许HTTP服务"),
                "toolTip": qsTr("Umi-OCR依赖HTTP接口进行本机跨进程通信。如果禁用，将无法使用命令行模式、多开检测等功能。"),
                "default": true,
                "onChanged": (val, old)=>{
                    if(old!==undefined) Qt.callLater(updateHttpService)
                },
            },
            "host": {
                "title": qsTr("主机"),
                "optionsList": [
                    ["127.0.0.1", qsTr("仅本地")+" (127.0.0.1)"],
                    ["0.0.0.0", qsTr("任何可用地址")],
                ],
                "onChanged": (val, old)=>{
                    if(old!==undefined) {
                        Qt.callLater(updateHttpService)
                    }
                },
            },
            "port": {
                "title": qsTr("端口"),
                "isInt": true,
                "default": 1224,
                "max": 65535,
                "min": 1,
                // 保存数值，只是用于前端展示。实际端口号由pre_config保存。
                "onChanged": (port, old)=>{
                    old!==undefined && setServerPort(port)
                },
            },
        },

        // 日志
        "logs": {
            "title": qsTr("日志"),
            "type": "group",

            "btns": {
                "title": qsTr("操作"),
                "btnsList": [
                    {
                        "text":qsTr("打开日志保存目录"),
                        "onClicked": globalConfigConn.open_logs_dir,
                        "textColorKey":"specialTextColor",
                    },
                ],
            },
            "saveLogLevel": {
                "title": qsTr("保存的日志级别"),
                "default": "ERROR",
                "optionsList": [
                    ["NONE", "Close"],
                    ["DEBUG", "DEBUG"],
                    ["INFO", "INFO"],
                    ["WARNING", "WARNING"],
                    ["ERROR", "ERROR"],
                    ["CRITICAL", "CRITICAL"],
                ],
                "onChanged": (val, old)=>{
                    // 调整级别，如果修改失败则不动UI
                    if(!globalConfigConn.change_save_log_level(val))
                        return true
                    if(val === "NONE")
                        qmlapp.popup.simple(qsTr("已禁用日志文件保存"), "")
                },
            },
        },

        // 插件管理。由 initPlugins() 填充。
        "plugins": undefined,
        // 插件级共享模型服务。一个服务可被 OCR/document 等多个能力复用，
        // 其参数只在这里显示一次。
        "pluginServices": undefined,

        // 插件能力的全局设定。每种能力类型一个键，由对应的管理器在
        // initPlugins() 中填充；未安装该类插件时保持 undefined 。
        "ocr": undefined,
        "document": undefined,

    }

    }

    // ========================= 【全局单例，通过 qmlapp.globalConfigs.xxx 访问】 =========================

    OcrManager { id: ocrManager } // OCR管理器 qmlapp.globalConfigs.ocrManager
    DocumentManager { id: documentManager } // 结构化文档管理器 qmlapp.globalConfigs.documentManager
    UtilsConfigDicts { id: utilsDicts } // 通用配置项 qmlapp.globalConfigs.utilsDicts
    GlobalConfigsConnector { id: globalConfigConn } // 全局设置连接器
    PluginsConnector { id: pluginsConnector } // 插件全局设置连接器

    property alias ocrManager: ocrManager
    property alias documentManager: documentManager
    property alias utilsDicts: utilsDicts

    // 能力类型 → 管理器。新增能力类型时只需在这里登记一行，
    // initPlugins 与初始化流程都不需要再改。
    property var capabilityManagers: ({
        "ocr": ocrManager,
        "document": documentManager,
    })
    // 插件状态快照，供插件管理界面使用
    property var pluginStates: []
    property var pluginHost: ({})
    property string pluginsPath: ""
    property var pluginServiceSpecs: ({})
    property var pluginServiceStarts: ({})

    // 插件状态 → 界面文案。每种状态都必须有明确说法，不存在"静默消失"。
    function pluginStateText(state) {
        switch(state) {
            case "ready":        return qsTr("已安装")
            case "disabled":     return qsTr("已禁用")
            case "incompatible": return qsTr("不兼容")
            case "conflict":     return qsTr("与其它插件互斥")
            case "invalid":      return qsTr("清单非法")
            case "error":        return qsTr("加载失败")
            case "unhealthy":    return qsTr("健康检查未通过")
        }
        return state
    }

    // 构建【插件管理】配置组。每个插件一个开关，提示里带状态与原因。
    function buildPluginsConfig() {
        const host = pluginHost
        const group = {
            "title": qsTr("插件管理"),
            "type": "group",
            "btns": {
                "title": qsTr("操作"),
                "btnsList": [
                    {"text": qsTr("打开插件目录"), "onClicked": openPluginsDir},
                    {"text": qsTr("检查全部插件状态"), "onClicked": checkAllPluginsHealth},
                    {"text": qsTr("刷新插件列表"), "onClicked": requestPluginRefresh},
                ],
            },
            "hostApi": {
                "title": qsTr("宿主插件 API"),
                "type": "text",
                "save": false,
                "default": `${host.hostApiVersion||"?"}   ${host.platform||"?"}/${host.arch||"?"}   Python ${host.python||"?"}`,
                "toolTip": qsTr("插件通过清单中的 host_api 字段声明支持的宿主范围。"),
            },
        }
        if(pluginStates.length === 0) {
            group.empty = {
                "title": qsTr("已安装插件"),
                "type": "text",
                "save": false,
                "default": qsTr("无。安装插件后刷新插件列表即可。"),
            }
            return group
        }
        for(let info of pluginStates) {
            const caps = (info.capabilities||[]).join(", ") || "-"
            let tip = qsTr("状态：%1").arg(pluginStateText(info.state))
                + "\n" + qsTr("能力：%1").arg(caps)
                + "\n" + qsTr("版本：%1").arg(info.version||"-")
            if(info.legacy)
                tip += "\n" + qsTr("旧版插件（无 umi-plugin.json 清单）")
            if(info.message)
                tip += "\n\n" + info.message
            tip += "\n\n" + qsTr("卸载：禁用插件后删除 %1，再刷新列表。").arg(info.path||"")
            group["enable_"+info.id] = {
                "title": `${info.name||info.id}  [${pluginStateText(info.state)}]`,
                "default": info.state !== "disabled",
                "toolTip": tip,
                "onChanged": (newFlag, oldFlag)=>{
                    if(oldFlag === undefined) return
                    return setPluginEnabled(info.id, newFlag)
                },
            }
        }
        return group
    }

    function setPluginEnabled(pluginId, enabled) {
        const msg = pluginsConnector.setEnabled(pluginId, enabled)
        if(msg.startsWith("[Success]")) {
            requestPluginRefresh()
            qmlapp.popup.simple(pluginId, msg.substring(9).trim())
            return // 不阻止变化
        }
        qmlapp.popup.message(qsTr("修改插件状态失败"), msg, "error")
        return true // 阻止变化
    }

    function openPluginsDir() {
        if(!pluginsPath) {
            qmlapp.popup.simple(qsTr("插件目录不可用"), "")
            return
        }
        Qt.openUrlExternally("file:///" + pluginsPath.replace(/\\/g, "/"))
    }

    // 逐个执行健康检查。只有检查通过的插件才允许被称为"可用"。
    property int pendingHealthChecks: 0
    property var healthLines: []
    function checkAllPluginsHealth() {
        if(pendingHealthChecks) return
        healthLines = []
        pendingHealthChecks = pluginStates.length
        for(const info of pluginStates)
            pluginsConnector.requestOperation("pluginHealth", info.id, "", {})
    }
    Connections {
        target: pluginsConnector
        function onOperationFinished(key, result) {
            if(key.startsWith("pluginHealth:")) {
                healthLines.push(`${result.ok ? "√" : "×"} ${key.split(":")[1]}: ${result.message || ""}`)
                pendingHealthChecks--
                if(pendingHealthChecks === 0)
                    qmlapp.popup.message(qsTr("插件状态检查"), healthLines.join("\n"), "info")
            } else if(key.startsWith("health:") || key.startsWith("prestart:")) {
                const details = result.details || {}
                if(result.ok || details.state === "stopped")
                    qmlapp.popup.simple(qsTr("模型服务状态"), result.message || qsTr("尚未启动"))
                else
                    qmlapp.popup.message(qsTr("模型服务异常"), result.message || "", "error")
            }
        }
    }

    function getPluginServiceValues(pluginId, serviceIds) {
        const values = {}
        const all = getValueDict()
        for(const serviceId of (serviceIds || [])) {
            const prefix = "pluginServices." + pluginId + "." + serviceId + "."
            for(const key in all) {
                if(key.startsWith(prefix))
                    values[key.substring(prefix.length)] = all[key]
            }
        }
        return values
    }

    function configurePluginService(pluginId, serviceId) {
        pluginsConnector.requestOperation("prestart", pluginId, serviceId,
                                          getPluginServiceValues(pluginId, [serviceId]))
        return {ok: true, message: qsTr("正在后台启动服务。")}
    }
    function showPluginServiceHealth(pluginId, serviceId) {
        pluginsConnector.requestOperation("health", pluginId, serviceId,
                                          getPluginServiceValues(pluginId, [serviceId]))
    }

    function buildPluginServicesConfig(services) {
        const root = {"title": qsTr("模型服务"), "type": "group"}
        pluginServiceSpecs = services || ({})
        for(const pluginId in pluginServiceSpecs) {
            for(const spec of pluginServiceSpecs[pluginId]) {
                const serviceId = spec.id
                const group = Object.assign({}, spec.config || {})
                if(!group.title) group.title = serviceId
                if(!group.type) group.type = "group"
                // JSON manifests cannot carry QML callbacks.  Add the small
                // lifecycle hooks here so a newly selected delayed/immediate
                // prestart policy takes effect without waiting for an app
                // restart.  setValue invokes onChanged before storing the
                // value, hence defer the re-read by one event-loop turn.
                if(group.lifecycle && group.lifecycle.prestartMode)
                    group.lifecycle.prestartMode.onChanged = ()=>Qt.callLater(schedulePluginServices)
                if(group.lifecycle && group.lifecycle.prestartDelayMinutes)
                    group.lifecycle.prestartDelayMinutes.onChanged = ()=>Qt.callLater(schedulePluginServices)
                if(group.lifecycle && group.lifecycle.autoStopMode)
                    group.lifecycle.autoStopMode.onChanged = ()=>Qt.callLater(maintainPluginServices)
                if(group.lifecycle && group.lifecycle.idleStopMinutes)
                    group.lifecycle.idleStopMinutes.onChanged = ()=>Qt.callLater(maintainPluginServices)
                group.btns = {
                    "title": qsTr("操作"),
                    "btnsList": [
                        {"text":qsTr("检查服务"), "onClicked":()=>showPluginServiceHealth(pluginId, serviceId)},
                        {"text":qsTr("预启动服务"), "onClicked":()=>configurePluginService(pluginId, serviceId), "textColorKey":"yesColor"},
                    ],
                }
                root[pluginId] = root[pluginId] || {
                    "title": (spec.meta && spec.meta.pluginName) || group.title || pluginId,
                    "type": "group"
                }
                root[pluginId][serviceId] = group
            }
        }
        return Object.keys(pluginServiceSpecs).length ? root : undefined
    }

    function schedulePluginServices() {
        const starts = ({})
        const now = Date.now()
        for(const pluginId in pluginServiceSpecs) {
            for(const spec of pluginServiceSpecs[pluginId]) {
                const config = getPluginServiceValues(pluginId, [spec.id])
                const mode = config["lifecycle.prestartMode"] || "lazy"
                if(mode === "delayed") {
                    const minutes = Number(config["lifecycle.prestartDelayMinutes"] || 0)
                    starts[pluginId+"/"+spec.id] = now + Math.max(0, minutes) * 60000
                }
                else if(mode === "immediate") {
                    configurePluginService(pluginId, spec.id)
                }
            }
        }
        // Reassign instead of mutating the existing var object.  QML binding
        // notifications are emitted for the property assignment, ensuring the
        // delayed-prestart Timer actually starts and stops as the schedule
        // changes.
        pluginServiceStarts = starts
    }

    // Older document plugins stored shared model paths under
    // document.<plugin>.  The shared-service contract moved them to
    // pluginServices.<plugin>.<service>; migrate only an actually empty new
    // path and only when the old setting exists.  This is deliberately narrow
    // so a user who has already selected a new path is never overwritten.
    function migrateLegacyPluginServicePaths() {
        for(const pluginId in pluginServiceSpecs) {
            for(const spec of pluginServiceSpecs[pluginId]) {
                const prefix = "pluginServices." + pluginId + "." + spec.id + "."
                for(const newKey in getOriginDict()) {
                    if(!newKey.startsWith(prefix) || String(getValue(newKey) || "").trim() !== "")
                        continue
                    const oldKey = "document." + pluginId + "." + newKey.slice(prefix.length)
                    if(!UmiSettings.contains("Global", oldKey)) continue
                    const oldValue = UmiSettings.value("Global", oldKey, "")
                    if(String(oldValue || "").trim() !== "")
                        setValue(newKey, oldValue, true)
                }
            }
        }
    }

    function maintainPluginServices() {
        for(const pluginId in pluginServiceSpecs) {
            for(const spec of pluginServiceSpecs[pluginId]) {
                pluginsConnector.requestOperation("maintain",
                    pluginId, spec.id, getPluginServiceValues(pluginId, [spec.id]))
            }
        }
    }
    property bool isPortInit: false // 标记端口号是否初始化完毕
    property var fontPanel: undefined // 缓存字体控制面板组件引用

    Component.onCompleted: {
        // 初始化主题
        theme.manager.init()
        configDict.ui.theme.optionsList = theme.manager.getOptionsList()
        configDict.ui.systemLightTheme.optionsList = theme.manager.getOptionsList(false)
        configDict.ui.systemDarkTheme.optionsList = theme.manager.getOptionsList(false)
        // 加载插件
        initPlugins()
        // 初始化配置项
        reload()
        migrateLegacyPluginServicePaths()
        // 检查权限和异常情况
        checkAccess()
        // 应用各能力类型的接口信息
        for(let capType in capabilityManagers) {
            if(configDict[capType])
                capabilityManagers[capType].init2()
        }
        schedulePluginServices()
        console.log("GlobalConfig 初始化全局配置完毕！")
        // 延迟执行
        Qt.callLater(()=>{
            setQmlToCmd()  // 将qml模块字典传入cmd执行模块
            // 启动web服务
            const enab = getValue("server.enable")
            if(enab) {
                const host = getValue("server.host")
                globalConfigConn.runUmiWeb(gRoot, "setRealPort", host)
            }
        })
    }

    property bool backendApplyPending: false
    property bool pluginRefreshPending: false
    property int applyPhase: 0
    function requestBackendApply() {
        for(const kind of ["ocr", "document"])
            qmlapp.msnConnector.callPy(kind, "deferAdmissions", [true])
        backendApplyPending = true
        applyTimer.restart()
    }
    function requestPluginRefresh() { pluginRefreshPending = true; requestBackendApply() }
    function backendsBusy() {
        for(const kind of ["ocr", "document"]) {
            const lengths = qmlapp.msnConnector.callPy(kind, "getMissionListsLength", [])
            if(Object.keys(lengths).length) return true
        }
        return false
    }
    onValueCommitted: function(key, value) {
        if(key.startsWith("ocr.") || key.startsWith("document.") || key.startsWith("pluginServices."))
            requestBackendApply()
    }
    Timer {
        id: applyTimer
        interval: 200
        repeat: true
        onTriggered: {
            if(backendsBusy() || pluginsConnector.isBusy() || qmlapp.msnConnector.isBusy() || ocrManager.applying || documentManager.applying) return
            if(applyPhase === 2) {
                // Edits during an asynchronous transition are applied in the next cycle.
                if(pluginRefreshPending || backendApplyPending) { applyPhase = 0; return }
                pluginsConnector.releaseUnusedServices(ocrManager.apiKey)
                for(const kind of ["ocr", "document"])
                    qmlapp.msnConnector.callPy(kind, "deferAdmissions", [false])
                applyPhase = 0
                stop()
                return
            }
            if(pluginRefreshPending && applyPhase === 0) {
                qmlapp.msnConnector.requestCall("ocr", "setApi", ["", {}])
                qmlapp.msnConnector.requestCall("document", "setApi", ["", {}])
                pluginsConnector.requestOperation("shutdownServices", "", "", null)
                applyPhase = 1
                return
            }
            if(pluginRefreshPending) {
                pluginRefreshPending = false
                initPlugins()
                reload()
            }
            backendApplyPending = false
            applyPhase = 2
            ocrManager.init2()
            documentManager.init2()
        }
    }

    function updateHttpService() {
        globalConfigConn.configureHttp(gRoot, "setRealPort", !!getValue("server.enable"),
                                      getValue("server.host"), Number(getValue("server.port")))
    }

    // 检查权限和异常情况
    function checkAccess() {
        let msg = globalConfigConn.checkAccess()
        if(msg.length > 0) {
            msg += "\n" + qsTr("请尝试更换软件路径！")
            qmlapp.popup.message(qsTr("配置文件读写异常"), msg, "error")
        }
    }

    // 初始化插件
    function initPlugins() {
        isChangedInit = false
        configDict = makeConfigDict()
        // 初始化插件
        let pluginInfos = pluginsConnector.init()
        if(!pluginInfos) return false // 没有加载插件
        // 记录失败信息
        if(pluginInfos.errors && Object.keys(pluginInfos.errors).length > 0) {
            const errs = pluginInfos.errors
            let msg = ""
            for (let key in errs) {
                msg += `${key}: ${errs[key]}\n`
            }
            qmlapp.popup.message(qsTr("插件加载失败"), msg, "error")
        }
        // 记录宿主环境与每个插件的状态，供插件管理界面使用
        pluginHost = pluginInfos.host || {}
        pluginStates = pluginInfos.plugins || []
        pluginsPath = pluginInfos.pluginsPath || ""
        configDict.plugins = buildPluginsConfig()
        configDict.pluginServices = buildPluginServicesConfig(pluginInfos.services || {})
        // 成功的插件：按能力类型分发给各自的管理器
        if(pluginInfos.options) {
            for(let capType in capabilityManagers) {
                const options = pluginInfos.options[capType]
                capabilityManagers[capType].init1(options || {})
            }
            // 宿主支持、但本 QML 没有对应管理器的能力类型：如实告警，
            // 不要静默吞掉，否则会重演 v1 里 document 插件被无声拒绝的问题。
            for(let capType in pluginInfos.options) {
                if(!capabilityManagers.hasOwnProperty(capType)
                    && Object.keys(pluginInfos.options[capType]).length > 0) {
                    console.warn(`【Warning】能力类型 ${capType} 没有对应的 QML 管理器，其配置界面不会显示。`)
                }
            }
        }
        if(pluginInfos.pages)
            qmlapp.tab.page.registerPluginPages(pluginInfos.pages)
    }

    Timer {
        interval: 1000
        repeat: true
        running: Object.keys(pluginServiceStarts).length > 0
        onTriggered: {
            const now = Date.now()
            const remaining = ({})
            for(const key in pluginServiceStarts) {
                if(now < pluginServiceStarts[key]) {
                    remaining[key] = pluginServiceStarts[key]
                    continue
                }
                const parts = key.split("/")
                configurePluginService(parts[0], parts.slice(1).join("/"))
            }
            pluginServiceStarts = remaining
        }
    }
    Timer {
        interval: 60000
        repeat: true
        running: Object.keys(pluginServiceSpecs).length > 0
        onTriggered: maintainPluginServices()
    }

    function applyThemeSettings(selected=undefined, light=undefined, dark=undefined) {
        theme.manager.configure(
            selected === undefined ? getValue("ui.theme") : selected,
            light === undefined ? getValue("ui.systemLightTheme") : light,
            dark === undefined ? getValue("ui.systemDarkTheme") : dark)
    }

    // 添加/删除快捷方式
    function changeShortcut(flag, position) {
        if(flag) {
            const res = globalConfigConn.createShortcut(position)
            if(res === "[Success]") {
                qmlapp.popup.simple(qsTr("成功添加快捷方式"), "")
            }
            else {
                qmlapp.popup.message(qsTr("添加快捷方式失败"), res, "error")
                return true // 阻止变化
            }
        }
        else {
            let res = globalConfigConn.deleteShortcut(position)
            if(res > 0) {
                qmlapp.popup.simple(qsTr("成功移除 %1 个快捷方式").arg(res), "")
            }
            else {
                qmlapp.popup.message(qsTr("提示"), qsTr("没有找到可移除的快捷方式。"), "warning")
            }
        }
    }

    // 初始化i18n参数
    function _getI18n() {
        const info = globalConfigConn.i18nGetInfos()
        const lang = info[0]
        const langDict = info[1]
        let optionsList = []
        for(let code in langDict) {
            const text = langDict[code][0]
            optionsList.push([code, text])
        }
        return {
            "title": "语言 / Language",
            "save": false,
            "default": lang,
            "optionsList": optionsList,
            "onChanged": changeI18n,
        }
    }
    // 改变i18n
    function changeI18n(lang, old) {
        if(old===undefined) return
        const flag = globalConfigConn.i18nSetLanguage(lang)
        if(flag) {
            // QTranslator and QML bindings are refreshed by the host.
            requestPluginRefresh()
        }
    }

    // 设置服务端口号
    function setServerPort(port) {
        if(port===null || port===undefined) {
            qmlapp.popup.simple(qsTr("端口号不合法"), "")
            return
        }
        if(isPortInit) { // 用户修改，忽略系统修改
            globalConfigConn.setServerPort(port)
            Qt.callLater(updateHttpService)
        }
    }
    // py回调，设置当前实际的端口号
    function setRealPort(port1) {
        const port2 = getValue("server.port")
        if(port1 !== port2) {
            setValue("server.port", port1, true)
            if(advanced) {
                const msg = qsTr("原端口号%1被占用，\n切换为新端口号%2。\n\n若不想看到此通知，请在全局设置关闭高级模式。").arg(port2).arg(port1)
                qmlapp.popup.message("", msg, "")
            }
            else {
                console.log(`原端口号${port1}被占用，\n切换为新端口号${port2}。`)
            }
        }
        isPortInit = true
    }
    // 将qml模块字典传入cmd执行模块
    function setQmlToCmd() {
        const moduleDict = {
            "GlobalConfigs": this,
            "MainWindow": qmlapp.mainWin,
            "TabViewManager": qmlapp.tab,
        }
        globalConfigConn.setQmlToCmd(moduleDict)
    }

    // 打开字体控制板
    function openFontPanel() {
        if(fontPanel) {
            fontPanel.visible = true
        }
    }

}
