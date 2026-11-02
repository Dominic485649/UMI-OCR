"""设置集中与设备下拉的真实 Qt 定向回归，内存配置，不启动窗口或推理。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def run(data: Path, output: Path):
    sys.dont_write_bytecode = True
    os.environ["QML_DISABLE_DISK_CACHE"] = "1"
    packages = data / "site-packages"
    sys.path.insert(0, str(packages))
    handles = [os.add_dll_directory(str(packages / "PySide6"))]
    from PySide6.QtCore import QObject, Property, Signal, Slot, QCoreApplication, QEvent, QUrl, QtMsgType, qInstallMessageHandler
    from PySide6.QtGui import QColor, QGuiApplication
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuickControls2 import QQuickStyle
    from shiboken6 import isValid

    QQuickStyle.setStyle("Basic")
    app = QGuiApplication(["settings-center-windowless"])
    engine = QQmlEngine()
    engine.addImportPath(str(packages / "PySide6/qml"))
    qml = ROOT / "UmiOCR-data/qt_res/qml"
    spec = importlib.util.spec_from_file_location("center_function_helper", ROOT / "tests/test_optional_backend_configs.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)

    def plain(value):
        return value.toVariant() if hasattr(value, "toVariant") else value

    class Settings(QObject):
        def __init__(self):
            super().__init__()
            self.values = {("Global", "ocr.api"): "pp", ("Global", "ocr.pp.device"): "gpu:7"}
            for category, value in (("ScreenshotOCR", 2), ("BatchOCR", 4), ("BatchPDF", 6)):
                self.values[category, "ocr.threshold"] = value
            self.writes = []

        @Slot(str, str, result=bool)
        def contains(self, category, key): return (category, key) in self.values
        @Slot(str, str, "QVariant", result="QVariant")
        def value(self, category, key, default): return self.values.get((category, key), plain(default))
        @Slot(str, str, "QVariant")
        def setValue(self, category, key, value):
            self.values[category, key] = plain(value)
            self.writes.append((category, key, plain(value)))
        @Slot()
        def sync(self): pass

    class Bus(QObject):
        def __init__(self):
            super().__init__()
            self.subscriptions = {}
            self.removed = []
        @Slot(str, "QVariant", str, str)
        def subscribeGroup(self, _event, item, method, group):
            item = item.toQObject() if hasattr(item, "toQObject") else item
            assert group not in self.subscriptions, "订阅组必须按实例唯一"
            self.subscriptions[group] = (item, method)
        @Slot(str)
        def unsubscribeGroup(self, group):
            self.removed.append(group)
            self.subscriptions.pop(group, None)

    class Popup(QObject):
        @Slot(str, str, str)
        def message(self, *_args): raise AssertionError("此回归不得打开提示窗口")
        @Slot(str, str)
        def simple(self, *_args): pass

    class Connector(QObject):
        operationFinished = Signal(str, str, "QVariant")
        @Slot(str, str, "QVariant", result="QVariant")
        def callPy(self, _kind, operation, _arguments):
            if operation == "getStatus": return {"missionListsLength": {}, "apiStatus": "closed"}
            if operation == "getMissionListsLength": return {}
            if operation == "backendsBusy": return False
            return "[Success]"
        @Slot(str, str, "QVariant")
        def requestCall(self, *_args): raise AssertionError("此回归不得启动后端")
        @Slot(str, str, result="QVariant")
        def getServiceStatus(self, *_args): return {"state": "stopped"}
        @Slot(result=bool)
        def isBusy(self): return False
        @Slot(result="QVariant")
        def modelOptions(self): return options

    class App(QObject):
        @Property(QObject, constant=True)
        def globalConfigs(self): return self.shared
        @Property(QObject, constant=True)
        def pubSub(self): return bus
        @Property(QObject, constant=True)
        def popup(self): return popup
        @Property(QObject, constant=True)
        def msnConnector(self): return connector
        @Property(bool, constant=True)
        def enabledEffect(self): return True

    settings, bus, popup, connector = Settings(), Bus(), Popup(), Connector()
    stub = App()
    stub.shared = None
    context = engine.rootContext()
    context.setContextProperty("qmlapp", stub)
    context.setContextProperty("UmiSettings", settings)
    context.setContextProperty("pluginsConnector", connector)
    context.setContextProperty("theme", {**{key: QColor(value) for key, value in {
        "bgColor": "#ffffff", "textColor": "#111111", "subTextColor": "#555555", "noColor": "#bb3322",
        "yesColor": "#228844", "specialBgColor": "#eeeeee", "specialTextColor": "#1166cc",
        "coverColor1": "#11000000", "coverColor2": "#22000000", "coverColor3": "#33000000", "coverColor4": "#55000000",
    }.items()}, "fontFamily": "Microsoft YaHei", "dataFontFamily": "Microsoft YaHei"})
    context.setContextProperty("size_", {"scale": 1, "line": 20, "smallLine": 16, "largeLine": 24,
        "text": 14, "smallText": 12, "largeText": 18, "spacing": 8, "smallSpacing": 4,
        "btnRadius": 4, "panelRadius": 6, "baseRadius": 4})
    engine.globalObject().setProperty("qmlapp", engine.newQObject(stub))
    errors, roots, checks = [], [], []
    previous = qInstallMessageHandler(lambda kind, _context, text: errors.append((kind, text)))

    def evaluate(code):
        result = engine.evaluate(code)
        assert not result.isError(), result.toString() + "\n" + result.property("stack").toString()
        return result

    def checkpoint():
        app.processEvents()
        assert not app.allWindows(), "无窗口测试不能创建 QWindow"
        failures = [text for kind, text in errors if kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)]
        assert not failures, failures

    def create(component, name, properties):
        deadline = time.monotonic() + 5
        while component.isLoading():
            assert time.monotonic() < deadline
            app.processEvents()
        assert component.isReady(), component.errorString()
        obj = component.createWithInitialProperties(properties)
        assert obj is not None, component.errorString()
        roots.append(obj)
        engine.globalObject().setProperty(name, engine.newQObject(obj))
        return obj

    try:
        shared_component = QQmlComponent(engine)
        shared_component.setData(('import QtQuick 2.15\nimport "' + QUrl.fromLocalFile(str(qml / "Configs")).toString() + '"\n' + '''Configs {
            property var ocrManager: null
            property var cudaDeviceSnapshot: ({state: "pending", devices: []})
            property var discoveries: []
            property int applyPhase: 0
            property var prestarts: []
            function refreshCudaDevices(force) { discoveries.push(force) }
            function backendsBusy() { return false }
            function configurePluginService(pluginId, serviceId) {
                prestarts.push([pluginId, serviceId])
                return {ok: true}
            }
        }''').encode(), QUrl.fromLocalFile(str(qml / "center-test.qml")))
        stub.shared = create(shared_component, "shared", {"category_": "Global", "configDict": {}, "autoLoad": False, "lazyPanel": True, "width": 1000, "height": 650})
        manager_component = QQmlComponent(engine, QUrl.fromLocalFile(str(qml / "ApiManager/OcrManager.qml")))
        create(manager_component, "manager", {})
        options = {
            "other": {"global_options": {"title": "其他", "type": "group"}},
            "vl": {"global_options": {"title": "VL", "type": "group"}, "meta": {"settingsOrder": 20, "serviceRefs": ["model"]}},
            "pp": {"global_options": {"title": "PP", "type": "group", "device": {"title": "GPU", "default": "gpu:0", "deviceProvider": "nvidia-cuda"}, "threads": {"title": "线程", "default": 4}},
                   "local_options": {"title": "识别参数", "type": "group", "threshold": {"title": "阈值", "default": 1}}, "meta": {"settingsOrder": 10}},
        }
        evaluate('shared.ocrManager=manager; manager.init1(qmlapp.msnConnector.modelOptions()); shared.reload(); manager.apiKey="pp"; manager.ensureTaskSources()')
        checkpoint()
        assert evaluate('JSON.stringify(manager.globalOptions.api.optionsList.map(item=>item[0]))').toString() == '["pp","vl","other"]'
        assert evaluate('shared.getValue("ocr.api")').toString() == "pp"
        transported = json.loads(evaluate('manager.apiKey="vl"; var incomingRefs=qmlapp.msnConnector.modelOptions().vl.meta.serviceRefs; var transported={inputIsArray:Array.isArray(incomingRefs),inputTag:Object.prototype.toString.call(incomingRefs),uses:manager.usesSharedService(),isArray:Array.isArray(manager.serviceRefs.vl),length:manager.serviceRefs.vl.length}; manager.apiKey="pp"; JSON.stringify(transported)').toString())
        assert transported["uses"] and transported["isArray"] and transported["length"] == 1, transported
        assert not evaluate('manager.usesSharedService()').toBool()
        assert evaluate('manager.apiKey="vl"; manager.warmup().startsWith("[Success]")').toBool()
        assert evaluate('JSON.stringify(shared.prestarts)').toString() == '[["vl","model"]]'
        evaluate('manager.apiKey="pp"')
        checkpoint()
        checks.append("真实Python QVariant桥返回的服务引用仍被识别为共享服务，预热只转发给该共享服务而不另起OCR worker")
        assert evaluate('Object.keys(manager.taskSources).length').toInt() == 3
        assert evaluate('manager.taskSource("ScreenshotOCR") === manager.taskSource("ScreenshotOCR")').toBool()
        for category, expected in (("ScreenshotOCR", 2), ("BatchOCR", 4), ("BatchPDF", 6)):
            assert evaluate(f'manager.taskSource("{category}").getValue("ocr.threshold")').toInt() == expected
        checks.append("任务页未打开时已有按原类别唯一的参数来源，模型按元数据排序")

        page_component = QQmlComponent(engine, QUrl.fromLocalFile(str(qml / "Configs/Configs.qml")))
        for name in ("pageA", "pageB"):
            create(page_component, name, {"category_": "ScreenshotOCR", "autoLoad": False, "lazyPanel": True})
            evaluate(f'{name}.valueSources={{ocr:manager.taskSource("ScreenshotOCR")}}; {name}.configDict={{other:{{title:"其他",default:true}}}}; {name}.reload()')
        checkpoint()
        evaluate('pageA.setValue("ocr.threshold",11,true)')
        assert evaluate('pageB.getValue("ocr.threshold")').toInt() == 11
        assert evaluate('manager.taskSource("BatchOCR").getValue("ocr.threshold")').toInt() == 4
        snapshot = json.loads(evaluate('JSON.stringify(pageA.getValueDict())').toString())
        assert snapshot == {"other": True, "ocr.threshold": 11}, snapshot
        assert not evaluate('"ocr.threshold" in pageA.valueDict').toBool()
        checks.append("多个任务页读写同一来源，任务快照完整且不泄漏共享策略，不同类别互不覆盖")
        source_group = evaluate('manager.taskSource("ScreenshotOCR").reloadSubscriptionGroup').toString()
        page_group = evaluate('pageA.reloadSubscriptionGroup').toString()
        assert source_group != page_group
        roots[-2].deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        checkpoint()
        assert source_group in bus.subscriptions and page_group not in bus.subscriptions
        assert evaluate('manager.taskSource("ScreenshotOCR").getValue("ocr.threshold")').toInt() == 11
        evaluate('pageB.settingsReload(); pageB.reset()')
        assert evaluate('manager.taskSource("ScreenshotOCR").getValue("ocr.threshold")').toInt() == 1
        assert evaluate('manager.taskSource("BatchPDF").getValue("ocr.threshold")').toInt() == 6
        checks.append("关闭任务页不会销毁或注销来源，重载/重置继续路由到原类别")

        functions = [helper.qml_function(qml / "Configs/GlobalConfigs.qml", name) for name in
                     ("orderedPluginStates", "modelSettingsLayout", "withoutDeviceItems", "buildPanelLayout", "serviceActionButtons")]
        functions += [helper.qml_function(qml / "Configs/Configs.qml", "defaultPanelLayout")]
        evaluate('var ocrManager=manager,definitionRevision=1; var pluginStates=[{id:"other",name:"其他",state:"disabled"},{id:"vl",name:"VL",state:"ready",settingsOrder:20},{id:"pp",name:"PP",state:"ready",settingsOrder:10}]; var pluginServiceSpecs={vl:[{id:"model"}]}; function showPluginServiceHealth(){} function configurePluginService(){}; shared.configDict.plugins={title:"插件管理",type:"group",btns:{title:"操作",btnsList:[]},enable_pp:{title:"启用",default:true},enable_vl:{title:"启用",default:true},enable_other:{title:"启用",default:false}}; shared.configDict.document={title:"结构化文档",type:"group",api:{title:"接口",default:"vl"},vl:{title:"VL",type:"group",pipeline:{title:"版面",type:"group",model:{title:"模型",default:"layout"},cudaDevice:{title:"版面GPU",default:"gpu:0",deviceProvider:"nvidia-cuda"}}}}; shared.configDict.pluginServices={type:"group",vl:{type:"group",model:{type:"group",context:{title:"上下文",default:16384}}}}; shared.reload(); var configDict=shared.configDict,originDict=shared.originDict;')
        evaluate('\n'.join(functions))
        evaluate('var layout=buildPanelLayout(); var pluginLayout=layout.find(item=>item.key==="plugins");')
        assert evaluate('layout.some(item=>item.key==="ocr")').toBool() is False
        assert evaluate('JSON.stringify(pluginLayout.items.map(item=>item.key))').toString() == '["plugins.btns","plugins.models","plugins.pp","plugins.vl","plugins.other"]'
        assert evaluate('pluginLayout.items[2].items.slice(-1)[0].key').toString() == "ocr.pp.device"
        assert evaluate('pluginLayout.items[3].items.slice(-1)[0].key').toString() == "document.vl.pipeline.cudaDevice"
        assert evaluate('layout.find(item=>item.key==="document").items.some(item=>item.key==="document.vl")').toBool() is False
        assert evaluate('pluginLayout.items[1].items.filter(item=>item.key.indexOf("plugins.models.")===0).length').toInt() == 0
        assert not evaluate('pluginLayout.items[1].items.some(item=>item.key==="ocr.api")').toBool()
        evaluate('manager.apiKey="vl"')
        assert not evaluate('modelSettingsLayout().items.some(item=>item.key==="ocr.btns")').toBool()
        assert evaluate('JSON.stringify(serviceActionButtons("vl","model").map(item=>item.text))').toString() == '["检查服务","预启动服务","终止文字识别任务"]'
        evaluate('manager.apiKey="pp"')
        assert evaluate('modelSettingsLayout().items.some(item=>item.key==="ocr.btns")').toBool()
        evaluate('shared.panelLayout=buildPanelLayout(); shared.ensurePanel()')
        checkpoint()
        checks.append("模型设置位于插件前，PP/VL/其他稳定排序，GPU位于所属插件末尾，旧文字识别组消失")
        checks.append("OCR终止紧随当前共享服务预启动，不扩大到文档终止")

        device_item = evaluate('shared.compList.find(item=>item.sourceKey==="ocr.pp.device")').toQObject()
        assert device_item is not None
        engine.globalObject().setProperty("deviceItem", engine.newQObject(device_item))
        combo = device_item.findChild(QObject, "nvidiaDeviceCombo")
        assert combo is not None
        assert evaluate('shared.getValue("ocr.pp.device")').toString() == "gpu:7"
        writes_before = len(settings.writes)
        for state in ("pending", "no_devices", "driver_missing", "timeout", "failed"):
            evaluate(f'shared.cudaDeviceSnapshot={{state:"{state}",devices:[]}}')
            checkpoint()
        evaluate('shared.cudaDeviceSnapshot={state:"ready",devices:[{value:"gpu:0",ordinal:0,name:"同名NVIDIA",uuid:"GPU-A"},{value:"gpu:1",ordinal:1,name:"同名NVIDIA",uuid:"GPU-B"}]}')
        checkpoint()
        assert len(settings.writes) == writes_before
        assert evaluate('deviceItem.deviceOptions[0].available').toBool() is False
        index = evaluate('deviceItem.deviceOptions.findIndex(item=>item.value==="gpu:1")').toInt()
        combo.setProperty("currentIndex", index)
        combo.activated.emit(index)
        checkpoint()
        assert evaluate('shared.getValue("ocr.pp.device")').toString() == "gpu:1"
        assert len(settings.writes) == writes_before + 1
        evaluate('shared.cudaDeviceSnapshot={state:"ready",devices:[{value:"gpu:1",ordinal:1,name:"重排后的显卡",uuid:"GPU-B"}]}')
        checkpoint()
        assert len(settings.writes) == writes_before + 1
        assert evaluate('deviceItem.deviceOptions[deviceItem.children.find(item=>item.objectName==="nvidiaDeviceCombo").currentIndex].value').toString() == "gpu:1"
        checks.append("真实专用ComboBox保留失效值，发现/重排/失败不写配置，仅用户activated提交gpu:N")
        # 缓存保留仅属于轻量来源，不能让只读导航在普通重载时提前写回。
        assert evaluate('manager.taskSource("ScreenshotOCR").preserveCacheOnReload').toBool()
        evaluate('manager.taskSource("ScreenshotOCR").configDict={ocr:{type:"group",threshold:{title:"阈值",default:1},pendingDefault:{default:77}}}; manager.taskSource("ScreenshotOCR").reload(); manager.taskSource("ScreenshotOCR").reload()')
        assert settings.values["ScreenshotOCR", "ocr.pendingDefault"] == 77
        create(page_component, "ordinary", {"category_": "OrdinaryCacheContract", "autoLoad": False, "lazyPanel": True})
        count = len(settings.writes)
        evaluate('ordinary.configDict={draft:{default:42}}; ordinary.reload(); ordinary.reload()')
        assert len(settings.writes) == count
        checks.append("仅canonical来源在重载前保留待写默认值，普通Configs的只读重载契约保持不变")
        evaluate('var originalStates=pluginStates, originalApiOrigin=originDict["ocr.api"]')
        for ids, expected in (([], []), (["pp"], ["plugins.pp"]), (["vl"], ["plugins.vl"]),
                              (["vl", "pp"], ["plugins.pp", "plugins.vl"]),
                              (["other", "vl", "pp"], ["plugins.pp", "plugins.vl", "plugins.other"])):
            evaluate('pluginStates=originalStates.filter(item=>' + json.dumps(ids) + '.indexOf(item.id)>=0);' + ('delete originDict["ocr.api"];' if not ids else 'originDict["ocr.api"]=originalApiOrigin;'))
            keys = json.loads(evaluate('JSON.stringify(buildPanelLayout().find(item=>item.key==="plugins").items.filter(item=>item.key!=="plugins.btns"&&item.key!=="plugins.models"&&item.key!=="plugins.empty").map(item=>item.key))').toString())
            assert keys == expected, (ids, keys)
            if not ids:
                assert not evaluate('buildPanelLayout().find(item=>item.key==="plugins").items.some(item=>item.key==="plugins.models")').toBool()
        evaluate('pluginStates=originalStates; originDict["ocr.api"]=originalApiOrigin')
        checks.append("无/单/双/额外插件展示矩阵不伪造缺失条目，无后端时不造模型设置")

        # 真正绑定任务页布局，模型引用全局，参数引用所属类别，不能只测一次性 JS。
        live_component = QQmlComponent(engine)
        live_component.setData(('import QtQuick 2.15\nimport "' + QUrl.fromLocalFile(str(qml / "Configs")).toString() + '"\nConfigs {\n'
            + 'property var ocrManager: null\nproperty var ocrSource: null\npanelLayout: ocrManager ? ocrManager.modelPanelLayout(this) : null\n'
            + 'valueSources: ocrSource ? ({ocr: ocrSource}) : ({})\nComponent.onCompleted: { ocrSource=ocrManager.taskSource(category_) }\n}').encode(), QUrl.fromLocalFile(str(qml / "live-layout-test.qml")))
        evaluate('manager.refreshDeployedPages()')
        for name, category in (("liveShot", "ScreenshotOCR"), ("liveBatch", "BatchOCR"), ("liveDoc", "BatchPDF"), ("liveShot2", "ScreenshotOCR")):
            create(live_component, name, {"category_": category, "autoLoad": False, "lazyPanel": True,
                   "ocrManager": evaluate('manager').toQObject(), "configDict": {}, "width": 1000, "height": 650})
            evaluate(f'{name}.configDict={{other:{{title:"其他",default:true}}}}; {name}.reload(); {name}.ensurePanel()')
        checkpoint()
        for _ in range(3):
            evaluate('manager.refreshDeployedPages(); shared.settingsReload(); for(const category in manager.taskSources) manager.taskSources[category].settingsReload()')
            checkpoint()
            for name in ("liveShot", "liveBatch", "liveDoc", "liveShot2"):
                active = json.loads(evaluate(f'JSON.stringify({name}.compList.filter(item=>item.sourceKey && item.sourceKey.indexOf("ocr.")===0).map(item=>item.sourceKey))').toString())
                assert active == ["ocr.api", "ocr.threshold"], (name, active)
                assert evaluate(f'{name}.compList.find(item=>item.sourceKey==="ocr.api").sourceConfigs===shared').toBool()
                assert evaluate(f'{name}.compList.find(item=>item.sourceKey==="ocr.threshold").sourceConfigs===manager.taskSource({name}.category_)').toBool()
                snapshot = json.loads(evaluate(f'JSON.stringify({name}.getValueDict())').toString())
                assert "ocr.threshold" in snapshot and "ocr.api" not in snapshot and not any(key.startswith("ocr.lifecycle.") for key in snapshot), snapshot
        evaluate('liveShot.compList.find(item=>item.sourceKey==="ocr.threshold").value(19)')
        assert evaluate('liveShot2.getValue("ocr.threshold")').toInt() == 19
        assert evaluate('liveBatch.getValue("ocr.threshold")').toInt() == 4
        evaluate('liveShot.compList.find(item=>item.sourceKey==="ocr.api").value("vl")')
        for name in ("liveShot", "liveBatch", "liveDoc", "liveShot2"):
            assert evaluate(f'{name}.compList.find(item=>item.sourceKey==="ocr.api").value()').toString() == "vl"
        evaluate('manager.apiKey="vl"; manager.refreshDeployedPages()')
        checkpoint()
        assert not evaluate('liveShot.compList.some(item=>item.sourceKey==="ocr.threshold")').toBool()
        evaluate('manager.apiKey="pp"; shared.setValue("ocr.api","pp",true); manager.refreshDeployedPages()')
        checkpoint()
        assert evaluate('liveShot.getValue("ocr.threshold")').toInt() == 19
        assert evaluate('liveShot.compList.some(item=>item.sourceKey==="ocr.threshold")').toBool()
        checks.append("任务页反复重载与模型切换仍显示唯一全局模型和所属类别参数，多页面同步且任务快照不混入全局项")
        # destroy() 在下一事件循环才执行；重建本帧旧控件也必须立即停止展示。
        evaluate('var retiringGroups=liveShot.panelComponent.activeGroupItems(); liveShot.initPanelComponent()')
        assert evaluate('retiringGroups.every(item=>!item.visible)').toBool(), "重建时旧设置组仍可见"
        assert evaluate('liveShot.panelComponent.activeGroupItems().length').toInt() == 2
        checkpoint()
        checks.append("设置面板重建时旧控件在延迟销毁前立即隐藏，同一事件循环不重复展示旧组")
        create(manager_component, "freshManager", {})
        evaluate('shared.ocrManager=freshManager; freshManager.init1(qmlapp.msnConnector.modelOptions()); shared.reload(); freshManager.apiKey="pp"')
        assert evaluate('Object.keys(freshManager.taskSources).length').toInt() == 0
        create(live_component, "firstTaskPage", {"category_": "ScreenshotOCR", "autoLoad": False, "lazyPanel": True,
               "ocrManager": evaluate('freshManager').toQObject(), "configDict": {}, "width": 1000, "height": 650})
        evaluate('firstTaskPage.reload(); firstTaskPage.ensurePanel()')
        checkpoint()
        assert evaluate('Object.keys(freshManager.taskSources).length').toInt() == 1
        assert evaluate('firstTaskPage.compList.some(item=>item.sourceKey==="ocr.threshold")').toBool()
        checks.append("未预建任务来源时首次打开页面也无panelLayout绑定循环，布局计算本身不创建来源")
        assert not any(name.split(".")[0] in {"paddle", "torch", "paddlex", "paddleocr"} for name in sys.modules)
        report = {"passed": checks, "qwindow_count": 0, "gpu_started": False, "settings": "memory-only",
                  "reference_transport": transported,
                  "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                      for path in [qml / "Configs/Configs.qml", qml / "Configs/GlobalConfigs.qml", qml / "Configs/NvidiaDeviceConfig.qml", qml / "ApiManager/OcrManager.qml", Path(__file__)]}}
        with output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        for obj in reversed(roots):
            if isValid(obj): obj.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        qInstallMessageHandler(previous)
        del handles


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.data_root.resolve(), args.output.resolve())
