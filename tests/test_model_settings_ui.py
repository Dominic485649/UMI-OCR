"""共享配置展示、生命周期及主题连接的无窗口定向测试，不导入推理后端。"""

import argparse
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(data_root, source_root):
    sys.dont_write_bytecode = True
    os.environ["QML_DISABLE_DISK_CACHE"] = "1"
    packages = data_root / "site-packages"
    sys.path.insert(0, str(packages))
    handles = [os.add_dll_directory(str(packages / "PySide6"))]
    from PySide6.QtCore import QObject, Property, QCoreApplication, QEvent, QUrl, Signal, Slot, QtMsgType, qInstallMessageHandler
    from PySide6.QtGui import QColor, QGuiApplication
    from PySide6.QtQml import QJSEngine, QQmlComponent, QQmlEngine
    from PySide6.QtQuickControls2 import QQuickStyle

    QQuickStyle.setStyle("Basic")
    app = QGuiApplication.instance() or QGuiApplication(["model-settings-windowless"])
    assert not app.allWindows()
    helper = load_module("qml_function_helper", ROOT / "tests/test_optional_backend_configs.py")
    qml = source_root / "qt_res/qml"
    configs_path = qml / "Configs/Configs.qml"
    manager_path = qml / "ApiManager/OcrManager.qml"
    global_path = qml / "Configs/GlobalConfigs.qml"
    passed = []
    registered_connectors = set()

    class MemorySettings(QObject):
        def __init__(self):
            super().__init__()
            self.values = {("Global", "ocr.api"): "cuda", ("Global", "ocr.lifecycle.warmupMode"): "lazy"}
            self.writes = []
            for category in ("ScreenshotOCR", "BatchOCR", "BatchPDF"):
                self.values[category, "ocr.threshold"] = 2

        @Slot(str, str, result=bool)
        def contains(self, category, key):
            return (category, key) in self.values

        @Slot(str, str, "QVariant", result="QVariant")
        def value(self, category, key, default):
            return self.values.get((category, key), default)

        @Slot(str, str, "QVariant")
        def setValue(self, category, key, value):
            value = value.toVariant() if hasattr(value, "toVariant") else value
            self.values[category, key] = value
            self.writes.append((category, key, value))

        @Slot()
        def sync(self):
            pass

    class Bus(QObject):
        @Slot(str, "QVariant", str, str)
        def subscribeGroup(self, *_args):
            pass

        @Slot(str)
        def unsubscribeGroup(self, *_args):
            pass

    class Popup(QObject):
        @Slot(str, str, str)
        def message(self, *_args):
            raise AssertionError("测试不能显示窗口")

    class App(QObject):
        def __init__(self):
            super().__init__()
            self.bus, self.popup_stub = Bus(self), Popup(self)

        @Property(QObject, constant=True)
        def pubSub(self):
            return self.bus

        @Property(QObject, constant=True)
        def popup(self):
            return self.popup_stub

        @Property(bool, constant=True)
        def enabledEffect(self):
            return True

        @Property(QObject, constant=True)
        def globalConfigs(self):
            return self.shared

    settings, app_stub = MemorySettings(), App()
    engine = QQmlEngine()
    engine.addImportPath(str(packages / "PySide6/qml"))
    context = engine.rootContext()
    context.setContextProperty("UmiSettings", settings)
    context.setContextProperty("qmlapp", app_stub)
    engine.globalObject().setProperty("qmlapp", engine.newQObject(app_stub))
    context.setContextProperty("theme", {**{name: QColor(value) for name, value in {
        "bgColor": "#ffffff", "textColor": "#111111", "subTextColor": "#555555", "noColor": "#bb3322",
        "yesColor": "#228844", "specialBgColor": "#eeeeee", "specialTextColor": "#1166cc",
        "coverColor1": "#11000000", "coverColor2": "#22000000", "coverColor3": "#33000000", "coverColor4": "#55000000",
    }.items()}, "fontFamily": "Microsoft YaHei", "dataFontFamily": "Microsoft YaHei"})
    context.setContextProperty("size_", {"scale": 1, "line": 20, "smallLine": 16, "largeLine": 24,
        "text": 14, "smallText": 12, "largeText": 18, "spacing": 8, "smallSpacing": 4, "btnRadius": 4, "panelRadius": 6, "baseRadius": 4})
    errors = []
    previous = qInstallMessageHandler(lambda kind, _context, text: errors.append((kind, text)))
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(configs_path)))
    roots = []

    def evaluate(code):
        result = engine.evaluate(code)
        assert not result.isError(), result.toString() + "\n" + result.property("stack").toString()
        return result

    def checkpoint():
        app.processEvents()
        assert not app.allWindows(), "不能创建 QWindow"
        failures = [text for kind, text in errors if kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)]
        assert not failures, failures

    def create(name, category, *, lazy_panel=False):
        obj = component.createWithInitialProperties({"category_": category, "autoLoad": False,
            "lazyPanel": lazy_panel, "width": 720, "height": 400})
        assert obj is not None, component.errorString()
        roots.append(obj)
        engine.globalObject().setProperty(name, engine.newQObject(obj))
        assert QQmlEngine.contextForObject(obj).baseUrl().toLocalFile() == str(configs_path).replace("\\", "/")
        return obj

    def combo(name, source_key):
        item = evaluate(f"{name}.compList.find(function(item){{return item.sourceKey === {json.dumps(source_key)};}})").toQObject()
        assert item is not None
        controls = [child for child in item.children() if child.metaObject().indexOfSignal("activated(int)") >= 0]
        assert len(controls) == 1
        engine.globalObject().setProperty("combo", engine.newQObject(controls[0]))

    try:
        deadline = time.monotonic() + 5
        while component.isLoading():
            assert time.monotonic() < deadline
            app.processEvents()
        assert component.isReady(), component.errorString()
        app_stub.shared = create("shared", "Global", lazy_panel=True)
        cold_map = json.loads(evaluate('JSON.stringify({panelBuilt:shared.panelBuilt,mapType:typeof shared.compDict})').toString())
        assert cold_map == {"panelBuilt": False, "mapType": "object"}, cold_map
        assert evaluate('Object.keys(shared.compDict).length').toInt() == 0
        commits = []
        app_stub.shared.valueCommitted.connect(lambda key, value: commits.append((key, value.toVariant() if hasattr(value, "toVariant") else value)))
        # 继续验证通用规范引用契约，不再把旧任务页模型块当成本轮界面。
        evaluate('function sharedReferenceLayout(page) { return [{key:"sharedReference",origin:{title:"共享引用契约",type:"group"},items:["ocr.api","ocr.lifecycle.warmupMode"].map(key=>({sourceConfigs:shared,sourceKey:key}))}].concat(page.defaultPanelLayout()); }')
        evaluate('shared.configDict = {ocr:{type:"group",title:"OCR",api:{title:"模型",optionsList:[["cuda","PP-OCRv6_medium"],["vl","PaddleOCR-VL1.6"]]},lifecycle:{type:"group",title:"后台",warmupMode:{title:"预热",default:"lazy",optionsList:[["delayed","延迟"],["lazy","首次"]]}}}}; shared.reload()')
        for index, category in enumerate(("ScreenshotOCR", "BatchOCR", "BatchPDF")):
            name = f"page{index}"
            create(name, category)
            evaluate(f'{name}.configDict = {{ocr:{{title:"专属参数",type:"group",threshold:{{title:"阈值",default:1,min:0,isInt:true}}}}}}; {name}.reload()')
            evaluate(f'{name}.panelLayout = sharedReferenceLayout({name}); {name}.initPanelComponent()')
        checkpoint()
        # 编译受影响真实 QML 依赖图但不实例化 Main/Window，不执行启动回调。
        from PySide6.QtQml import qmlRegisterType
        class ConnectorStub(QObject):
            systemDarkChanged = Signal()
            nativeThemeFailed = Signal(str)
        for path in qml.rglob("*.qml"):
            for connector_name in re.findall(r"^import (\w+Connector) 1\.0", path.read_text(encoding="utf-8"), re.MULTILINE):
                if connector_name not in registered_connectors:
                    qmlRegisterType(ConnectorStub, connector_name, 1, 0, connector_name)
                    registered_connectors.add(connector_name)
        for relative in ("Main.qml", "Configs/GlobalConfigs.qml", "ApiManager/OcrManager.qml", "ApiManager/DocumentManager.qml",
                         "TabPages/Navigation/Navigation.qml", "TabPages/GlobalConfigsPage/GlobalConfigsPage.qml",
                         "TabPages/ScreenshotOCR/ScreenshotOcrConfigs.qml", "TabPages/BatchOCR/BatchOCRConfigs.qml", "TabPages/BatchDOC/BatchDOCConfigs.qml",
                         "TabPages/ScreenshotOCR/ScreenshotOCR.qml", "TabPages/BatchOCR/PreviewImage.qml",
                         "Widgets/ResultLayout/ResultsTableView.qml", "Widgets/ResultLayout/ResultTextContainer.qml"):
            compiled = QQmlComponent(engine, QUrl.fromLocalFile(str(qml / relative)))
            deadline = time.monotonic() + 5
            while compiled.isLoading():
                assert time.monotonic() < deadline
                app.processEvents()
            assert compiled.isReady(), (relative, compiled.errorString())
            compiled.deleteLater()
        checkpoint()
        passed.append("受影响真实 QML 依赖图编译通过（连接器仅注册类型，不实例化 Main/Window）")
        assert not settings.writes, settings.writes
        for index in range(3):
            assert evaluate(f'JSON.stringify(Object.keys(page{index}.getValueDict()))').toString() == '["ocr.threshold"]'
        assert not evaluate('shared.panelBuilt').toBool()
        assert not commits
        passed.append("三个实际 Configs 页面仅存局部模型参数，构建引用控件不提交全局值")
        passed.append("全局面板未展开时控件映射已为空对象，构建外部入口不强制展开全局面板")

        combo("page0", "ocr.lifecycle.warmupMode")
        evaluate("combo.currentIndex=0; combo.activated(0)")
        checkpoint()
        assert settings.writes == [("Global", "ocr.lifecycle.warmupMode", "delayed")], settings.writes
        for index in range(3):
            combo(f"page{index}", "ocr.lifecycle.warmupMode")
            assert evaluate("combo.currentIndex").toInt() == 0
        evaluate('page1.reset(); page1.initPanelComponent(); page2.settingsReload()')
        checkpoint()
        assert settings.values["Global", "ocr.lifecycle.warmupMode"] == "delayed"
        assert not any(category != "Global" and key.startswith("ocr.lifecycle.") for category, key, _ in settings.writes)
        assert commits == [("ocr.lifecycle.warmupMode", "delayed")], commits
        assert not evaluate('shared.panelBuilt').toBool()
        evaluate('shared.setValue("ocr.lifecycle.warmupMode","lazy",true); shared.setValue("ocr.lifecycle.warmupMode","delayed",true); shared.setValue("ocr.lifecycle.warmupMode","delayed",true)')
        checkpoint()
        assert commits == [("ocr.lifecycle.warmupMode", value) for value in ("delayed", "lazy", "delayed")], commits
        assert not evaluate('shared.panelBuilt').toBool()
        assert evaluate('Object.keys(shared.compDict).length').toInt() == 0
        for index in range(3):
            combo(f"page{index}", "ocr.lifecycle.warmupMode")
            assert evaluate("combo.currentIndex").toInt() == 0
        passed.append("未建全局面板的外部activated及setValue(...,true)正常保存并只提交一次，多入口同步且不强制建panel")
        passed.append("真实 activated 只写一次 Global，多入口同步；页面重置/重建不重置共享策略")

        evaluate('shared.originDict["ocr.api"].onChanged = function(){return true}')
        combo("page2", "ocr.api")
        evaluate("combo.currentIndex=1; combo.activated(1)")
        assert evaluate("combo.currentIndex").toInt() == 0
        assert settings.values["Global", "ocr.api"] == "cuda"
        before_commits = list(commits)
        before_writes = list(settings.writes)
        evaluate('shared.setValue("ocr.api","vl",true); shared.settingsReload()')
        checkpoint()
        assert commits == before_commits and settings.writes == before_writes
        assert not evaluate('shared.panelBuilt').toBool()
        assert evaluate('Object.keys(shared.compDict).length').toInt() == 0
        passed.append("未建全局panel的拒绝更新分支不报错、不保存或valueCommitted，外部入口恢复真实模型")
        passed.append("规范来源拒绝切换后，外部引用恢复真实当前模型且不写入假选择")
        evaluate('shared.ensurePanel(); shared.initPanelComponent()')
        checkpoint()
        assert evaluate('shared.panelBuilt && shared.compDict["ocr.api"] !== undefined').toBool()
        assert commits == before_commits and settings.writes == before_writes
        passed.append("稍后真正展开及重建全局panel会建立控件映射，不额外提交或破坏现有共享入口")

        # 执行真实 QML 函数验证布局、模型候选、任务门禁、预热参数及服务映射。
        js = QJSEngine()
        functions = [helper.qml_function(manager_path, name) for name in
                     ("modelDisplayName", "makeGlobalOptions", "orderedModelKeys", "init1", "buildWarmupInfo", "modelPanelLayout")]
        functions += [helper.qml_function(global_path, name) for name in ("getPluginServiceValues", "publishBackendSnapshots", "backendsBusy", "orderedPluginStates", "modelSettingsLayout", "withoutDeviceItems", "buildPanelLayout", "maintainPluginServices")]
        functions += [helper.qml_function(configs_path, "defaultPanelLayout")]
        setup = '''
        var apiKey="win32_PaddleOCRv6_CUDA", localOptions={}, serviceRefs={}, globalOptions={};
        var ocrManager={taskSourcesRevision:0,taskSources:{},usesSharedService:function(){return false}};
        var definitionRevision=1, configDict={}, originDict={}, busy=false, applying=false;
        var stored={"ocr.longSide":6333,"ocr.nested.limit":7}, values={
          "ocr.lifecycle.cleanupPolicy":"idle","ocr.lifecycle.idleCleanupMinutes":17,
          "pluginServices.vl.model.modelPath":"keep.gguf","pluginServices.vl.model.lifecycle.autoStopMode":"never"};
        var snapshots=[], pluginServiceSpecs={vl:[{id:"model"}]};
        function getValue(key){return values[key]}
        function getValueDict(){return values}
        function stopAllMissions(){} function scheduleWarmup(){} function resetCleanupSchedule(){}
        function qsTr(text){return text}
        var UmiSettings={contains:function(category,key){return category==="ScreenshotOCR" && key in stored},
          value:function(category,key,fallback){return stored[key]}};
        var qmlapp={globalConfigs:{configDict:configDict,originDict:originDict,backendsBusy:function(){return busy},applyPhase:0},
          popup:{simple:function(){}},msnConnector:{callPy:function(kind,op,args){
            if(op==="backendsBusy")return busy;
            if(op==="getMissionListsLength")return {};
            if(op==="configureBackends"){snapshots.push(args[0]);return "[Success]";}
          }}};
        '''
        def js_eval(code):
            result = js.evaluate(code)
            assert not result.isError(), result.toString() + "\n" + result.property("stack").toString()
            return result
        js_eval(setup + "\n" + "\n".join(functions))
        assert js_eval('modelDisplayName({meta:{modelName:"模型元数据"}},"任意插件")').toString() == "模型元数据"
        assert js_eval('modelDisplayName({local_options:{detModel:{optionsList:[["真实模型键","显示标签"]]}}},"任意插件")').toString() == "真实模型键"
        assert js_eval('modelDisplayName({global_options:{title:"通用插件标题"}},"任意插件")').toString() == "通用插件标题"
        js_eval('qmlapp.globalConfigs.getPluginServiceValues=getPluginServiceValues; init1({win32_PaddleOCRv6_CUDA:{global_options:{title:"CUDA",modelName:"PP-OCRv6_medium",type:"group"},local_options:{longSide:{default:4000},nested:{type:"group",limit:{default:2}}}}})')
        assert json.loads(js_eval('JSON.stringify(globalOptions.api.optionsList)').toString()) == [["win32_PaddleOCRv6_CUDA", "PP-OCRv6_medium"]]
        js_eval('busy=true')
        assert js_eval('globalOptions.api.onChanged("other","win32_PaddleOCRv6_CUDA")').toBool()
        assert js_eval('backendsBusy()').toBool()
        js_eval('busy=false')
        warmup = json.loads(js_eval('JSON.stringify(buildWarmupInfo())').toString())
        assert warmup == {"ocr.longSide": 6333, "ocr.nested.limit": 7, "ocr.taskType": "screenshot"}, warmup
        assert js_eval('Object.keys(getPluginServiceValues("win32_PaddleOCRv6_CUDA",[])).length').toInt() == 0
        service = json.loads(js_eval('JSON.stringify(getPluginServiceValues("vl",["model"]))').toString())
        assert service["lifecycle.autoStopMode"] == "stop" and service["lifecycle.idleStopMinutes"] == 17
        assert service["lifecycle.prestartMode"] == "lazy" and service["modelPath"] == "keep.gguf"
        js_eval('publishBackendSnapshots()')
        assert js_eval('snapshots[0]["pluginServices.vl.model.lifecycle.autoStopMode"]').toString() == "stop"
        js_eval('values["ocr.lifecycle.cleanupPolicy"]="memory"')
        assert js_eval('getPluginServiceValues("vl",["model"])["lifecycle.autoStopMode"]').toString() == "never"
        js_eval('init1({})')
        assert js_eval('Object.keys(localOptions).length').toInt() == 0
        assert not js_eval('"ocr" in configDict').toBool()
        passed.append("实际管理函数：只提供已安装模型，繁忙拒绝切换，预热读页面真实键，统一策略映射并发布后端快照")
        js_eval('''
          var pluginStates=[{id:"vl",name:"PaddleVL",state:"ready"},{id:"disabled",name:"禁用插件",state:"disabled"}];
          configDict={plugins:{title:"插件管理",type:"group",fullKey:"plugins"}};
          var pathOrigin={title:"模型文件",type:"file",fullKey:"pluginServices.vl.model.modelPath"};
          originDict={"pluginServices.vl.model":{title:"重复服务标题",type:"group",modelPath:pathOrigin}};
          var layout=buildPanelLayout();
        ''')
        layout = json.loads(js_eval('JSON.stringify(layout)').toString())
        assert len(layout) == 1 and layout[0]["key"] == "plugins", layout
        ready_group, disabled_group = layout[0]["items"][1:]
        assert [entry["key"] for entry in ready_group["items"]] == ["plugins.enable_vl", "pluginServices.vl.model.modelPath"]
        assert [entry["key"] for entry in disabled_group["items"]] == ["plugins.enable_disabled"]
        assert "重复服务标题" not in json.dumps(layout, ensure_ascii=False)
        passed.append("实际服务展示函数：已启用插件下直接引用服务子项，禁用插件只有开关，不生成服务顶层及重复标题")
        js_eval('''
          var backendApplyPending=false, applyPhase=0, operations=[];
          var serviceStatus={activeLeases:0,waitingRequests:0,idleSeconds:18*60};
          var pluginsConnector={isBusy:function(){return false},getServiceStatus:function(){return serviceStatus},
            requestOperation:function(op,plugin,service,args){operations.push([op,plugin,service,args])}};
          maintainPluginServices("idle");
        ''')
        assert js_eval('operations[0][3].reason').toString() == "idle"
        js_eval('operations=[]; serviceStatus.activeLeases=1; maintainPluginServices("memory")')
        assert js_eval('operations.length').toInt() == 0
        js_eval('serviceStatus.activeLeases=0; serviceStatus.waitingRequests=1; maintainPluginServices("idle")')
        assert js_eval('operations.length').toInt() == 0
        js_eval('serviceStatus.waitingRequests=0; busy=true; maintainPluginServices("idle")')
        assert js_eval('operations.length').toInt() == 0
        js_eval('busy=false; serviceStatus.idleSeconds=60; maintainPluginServices("idle")')
        assert not js_eval('"reason" in operations[0][3]').toBool()
        passed.append("实际服务维护函数：达到闲置阈值才发 reason=idle，文档租约/等待请求/HTTP繁忙均不发清理指令")
        js_eval(helper.qml_function(qml / "TabPages/Navigation/Navigation.qml", "versionLines"))
        js_eval('''
          var UmiAbout={version:{string:"3.0.test"}};
          qmlapp.globalConfigs.pluginStates=[{id:"vl",name:"PaddleVL",version:"3.1.7",state:"ready"},
            {id:"cuda",name:"PP-OCR CUDA",version:"8.2.4",state:"disabled"}];
          qmlapp.globalConfigs.pluginStateText=function(state){return state==="disabled" ? "已禁用" : state};
        ''')
        versions = json.loads(js_eval('JSON.stringify(versionLines())').toString())
        assert versions == ["Umi-OCR  3.0.test", "PaddleVL  3.1.7", "PP-OCR CUDA  8.2.4  [已禁用]"], versions
        js_eval('qmlapp.globalConfigs.pluginStates=[]')
        assert json.loads(js_eval('JSON.stringify(versionLines())').toString()) == ["Umi-OCR  3.0.test"]
        global_source = global_path.read_text(encoding="utf-8")
        assert '"title": "语言/language"' in global_source
        assert '"default": theme.manager.followSystemKey' in global_source
        for removed in ("disableEffect", "imgShowOverlay"):
            assert removed not in global_source
            assert removed not in (qml / "Widgets/ImageViewer/ImageWithText.qml").read_text(encoding="utf-8")
        js_eval(helper.qml_function(qml / "TabPages/Navigation/Navigation.qml", "initData"))
        js_eval('''
          var introText="",welcomeText="欢迎",pageModel={items:[],clear:function(){this.items=[]},append:function(item){this.items.push(item)}};
          qmlapp.tab={infoList:[{}, {title:"截图OCR",intro:"旧简介"}]}; initData();
          qmlapp.tab.infoList=[{}, {title:"Screenshot OCR",intro:"New introduction"}]; initData();
        ''')
        assert js_eval('pageModel.items[0].title').toString() == "Screenshot OCR"
        assert js_eval('pageModel.items[0].intro').toString() == "New introduction"
        passed.append("实际首页版本和导航快照重建函数：独立版本、禁用标注、未安装隐藏及新文案；固定语言/默认主题/删除项源核验")

        # 真实结果表只创建 Item：正文与警告分别存储，部分可用文本不丢弃。
        results_component = QQmlComponent(engine, QUrl.fromLocalFile(str(qml / "Widgets/ResultLayout/ResultsTableView.qml")))
        assert results_component.isReady(), results_component.errorString()
        result_item = results_component.createWithInitialProperties({"width": 720, "height": 400, "autoToBottom": False})
        assert result_item is not None, results_component.errorString()
        roots.append(result_item)
        engine.globalObject().setProperty("testedResults", engine.newQObject(result_item))
        partial_result = {"code": 100, "timestamp": 123, "time": 1.2, "title": "原始图片标题", "partial": True,
                          "warnings": ["输出被截断", "输出被截断", {"message": "部分区域未完成"}],
                          "data": [{"text": "有效第一行", "end": "\n"}, {"text": "有效第二行"}]}
        evaluate("var partialResult=" + json.dumps(partial_result, ensure_ascii=False))
        assert evaluate("testedResults.addOcrResult(partialResult)").toString() == "有效第一行\n有效第二行"
        assert evaluate('testedResults.getResult("",123).status__').toString() == "partial"
        assert evaluate('testedResults.getResult("",123).title').toString() == "部分结果 | 原始图片标题"
        assert evaluate('testedResults.getResult("",123).warningText_').toString() == "输出被截断\n部分区域未完成"
        evaluate('testedResults.addOcrResult({code:101,timestamp:124,time:0.3,warnings:["已达到图像预算"],data:[]})')
        assert evaluate('testedResults.getResult("",124).status__').toString() == "warning"
        assert evaluate('testedResults.getResult("",124).resText').toString() == ""
        assert evaluate('testedResults.getResult("",124).warningText_').toString() == "已达到图像预算"
        evaluate('testedResults.addOcrResult({code:100,timestamp:125,time:0.3,partial:true,data:[{text:"可用片段"}]})')
        assert evaluate('testedResults.getResult("",125).warningText_').toString() == "识别未全部完成，当前仅显示已获得的结果。"
        evaluate('testedResults.addOcrResult({code:100,timestamp:126,time:0.3,warnings:["建议复核"],data:[{text:"完整正文"}]})')
        assert evaluate('testedResults.getResult("",126).status__').toString() == "warning"
        assert evaluate('testedResults.getResult("",126).resText').toString() == "完整正文"
        results_component.deleteLater()
        checkpoint()

        # 执行真实通知与截图回调函数，验证不会抑制部分结果警告或污染复制文字。
        screenshot_path = qml / "TabPages/ScreenshotOCR/ScreenshotOCR.qml"
        js_eval(helper.qml_function(qml / "Widgets/ResultLayout/ResultsTableView.qml", "resultNotice"))
        js_eval(helper.qml_function(screenshot_path, "showSimple"))
        js_eval(helper.qml_function(screenshot_path, "onOcrGet"))
        js_eval('''
          String.prototype.arg=function(value){return this.replace(/%[1-9]/,String(value))};
          var notifications=[], copied=[], overlayResults=[], visible=true;
          var configsComp={getValue:function(key){return key==="action.copy" ? true : "inside"}};
          var resultsTableView={resultNotice:resultNotice,addOcrResult:function(){return "有效文字"}};
          var imageText={showTextBoxes:function(res){overlayResults.push(res)},showImgID:function(){},showPath:function(){}};
          var tabPanel={indexChangeNum:3}; function popMainWindow(){}
          qmlapp.mainWin={getVisibility:function(){return visible}};
          qmlapp.utilsConnector={copyText:function(text){copied.push(text)}};
          qmlapp.popup.simple=function(title,text,kind){notifications.push([title,text,kind])};
          var partialInput={code:100,time:1,partial:true,warnings:["未完成的区域"],data:[{text:"有效文字"}]};
          showSimple(partialInput,"有效文字",false);
        ''')
        assert js_eval('notifications[0][0].indexOf("部分结果")>=0').toBool()
        assert js_eval('notifications[0][1]').toString() == "未完成的区域\n\n有效文字"
        js_eval('notifications=[]; showSimple({code:101,time:1,warnings:["图像超出预算"]},"",false)')
        assert js_eval('notifications.length').toInt() == 1
        assert js_eval('notifications[0][0].indexOf("无文字")>=0 && notifications[0][0].indexOf("结果警告")>=0').toBool()
        assert js_eval('notifications[0][1]').toString() == "图像超出预算"
        js_eval('notifications=[]; showSimple({code:100,time:1,data:[]},"普通结果",false)')
        assert js_eval('notifications.length').toInt() == 0
        js_eval('onOcrGet(partialInput)')
        assert js_eval('copied[0]').toString() == "有效文字"
        assert js_eval('overlayResults[0]===partialInput && overlayResults[0].data[0].text==="有效文字"').toBool()
        js_eval(helper.qml_function(qml / "Widgets/ResultLayout/ResultsTableView.qml", "selectAllCopy"))
        record_text = evaluate('testedResults.getResult("",123).resText').toString()
        js_eval('var recordRows=[{resText:' + json.dumps(record_text, ensure_ascii=False) + ',warningText_:"输出被截断"},{resText:"",warningText_:"图像预算"}];')
        js_eval('var resultsModel={count:recordRows.length,get:function(i){return recordRows[i]}}; function selectAll(){}; copied=[]; selectAllCopy()')
        assert js_eval('copied[0]').toString() == record_text + "\n"
        passed.append("实际结果表与截图回调：部分结果及101警告显式显示，警告独立于复制正文，正常通知抑制保留，有效叠加数据不丢弃")

        # 仅替身 HWND/DWM 调用，验证实际连接器不读取系统深浅色来覆盖软件主题。
        fake_log = types.ModuleType("umi_log")
        fake_log.logger = types.SimpleNamespace(warning=lambda *args, **kwargs: None)
        original_log = sys.modules.get("umi_log")
        sys.modules["umi_log"] = fake_log
        # 用真实源码目录提供包上下文，允许主题连接器导入相邻的热翻译模块。
        package_name = "_umi_model_settings_theme_probe"
        package = types.ModuleType(package_name)
        package.__path__ = [str(source_root / "py_src/utils")]
        package.__package__ = package_name
        sys.modules[package_name] = package
        try:
            theme_module = load_module(package_name + ".theme_connector", source_root / "py_src/utils/theme_connector.py")
            connector = theme_module.ThemeConnector()
            class WindowStub(QObject):
                def winId(self):
                    return 123
            window = WindowStub()
            native = []
            connector._set_native_dark = lambda hwnd, dark: native.append((hwnd, dark))
            connector.syncWindowTheme(window, True)
            app.processEvents()
            connector.syncWindowTheme(window, False)
            app.processEvents()
            app.sendEvent(window, QEvent(QEvent.Type.WinIdChange))
            app.processEvents()
            assert native == [(123, True), (123, False), (123, False)], native
            failures = []
            connector.nativeThemeFailed.connect(failures.append)
            def fail(*_args):
                raise OSError("DWM_TEST_FAILURE")
            connector._set_native_dark = fail
            connector._apply_window_theme()
            connector._apply_window_theme()
            assert len(failures) == 1 and "DWM_TEST_FAILURE" in failures[0]
            connector.deleteLater()
        finally:
            if original_log is None: sys.modules.pop("umi_log", None)
            else: sys.modules["umi_log"] = original_log
            for module_name in list(sys.modules):
                if module_name == package_name or module_name.startswith(package_name + "."):
                    sys.modules.pop(module_name, None)
        passed.append("实际主题连接器：软件深浅优先、句柄变化重同步、失败一次可见诊断且不崩溃（DWM替身，未启动窗口）")
        checkpoint()
        forbidden = [name for name in sys.modules if name.split(".")[0] in {"paddle", "paddlex", "paddleocr", "onnxruntime"}]
        assert not forbidden, forbidden
    finally:
        for obj in roots: obj.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        component.deleteLater()
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        qInstallMessageHandler(previous)
        assert not app.allWindows()
        del handles
    inputs = [source_root / "py_src/utils/theme_connector.py", ROOT / "tests/test_model_settings_ui.py",
              ROOT / "tests/test_optional_backend_configs.py"]
    if (source_root / "py_src/utils/runtime_i18n.py").is_file():
        inputs.append(source_root / "py_src/utils/runtime_i18n.py")
    inputs += [qml / relative for relative in ("Main.qml", "Configs/Configs.qml", "Configs/ConfigItemComp.qml", "Configs/GlobalConfigs.qml",
              "ApiManager/OcrManager.qml", "ApiManager/DocumentManager.qml", "Themes/ThemeManager.qml",
              "TabPages/Navigation/Navigation.qml", "TabPages/GlobalConfigsPage/GlobalConfigsPage.qml",
              "TabPages/ScreenshotOCR/ScreenshotOcrConfigs.qml", "TabPages/BatchOCR/BatchOCRConfigs.qml", "TabPages/BatchDOC/BatchDOCConfigs.qml",
              "Widgets/ImageViewer/ImageWithText.qml", "TabPages/ScreenshotOCR/ScreenshotOCR.qml", "TabPages/BatchOCR/PreviewImage.qml",
              "Widgets/ResultLayout/ResultsTableView.qml", "Widgets/ResultLayout/ResultTextContainer.qml")]
    return {"source_root": str(source_root), "runtime_root": str(data_root), "qwindow_count": 0,
            "source_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs},
            "gpu_started": False, "settings": "memory-only", "passed": passed,
            "limits": "未测试真实GUI、DWM视觉效果、系统主题交叉组合及真实插件推理"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run(args.data_root.resolve(), args.source_root.resolve())
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
