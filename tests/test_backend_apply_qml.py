"""执行真实 GlobalConfigs／能力管理器的待切换状态机，不复制其 JS 实现。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data, output = args.data.resolve(), args.output.resolve()
    os.chdir(output.parent)
    os.environ["QML_DISABLE_DISK_CACHE"] = "1"
    sys.path[:0] = [str(data / "site-packages"), str(data / "dependencies.zip")]
    dll = os.add_dll_directory(str(data / "site-packages/PySide6"))
    from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot, qInstallMessageHandler, QtMsgType
    from PySide6.QtGui import QColor, QGuiApplication
    from PySide6.QtQml import QQmlComponent, QQmlEngine, qmlRegisterType
    from PySide6.QtQuickControls2 import QQuickStyle

    def plain(value):
        return value.toVariant() if hasattr(value, "toVariant") else value

    class Settings(QObject):
        @Slot(str, str, result=bool)
        def contains(self, *_args): return False
        @Slot(str, str, "QVariant", result="QVariant")
        def value(self, _category, _key, default): return plain(default)
        @Slot(str, str, "QVariant")
        def setValue(self, *_args): pass
        @Slot()
        def sync(self): pass

    class Connector(QObject):
        operationFinished = Signal(str, str, "QVariant")
        runtimeChanged = Signal()
        def __init__(self):
            super().__init__()
            self.busy = False
            self.requests = []
            self.gates = []
            self.outstanding = None
        @Slot(str, str, "QVariant", result="QVariant")
        def callPy(self, _kind, operation, _args):
            if operation == "backendsBusy": return self.busy
            if operation == "getMissionListsLength": return {}
            if operation == "getStatus": return {"missionListsLength": {}, "apiState": {"state": "unloaded"}}
            return "[Success]"
        @Slot(result=bool)
        def isBusy(self): return self.outstanding is not None
        @Slot(bool)
        def deferBackendAdmissions(self, enabled): self.gates.append(enabled)
        @Slot(str)
        def rejectDeferredAdmissions(self, _message): pass
        @Slot("QVariant")
        def requestBackendApply(self, request):
            assert self.outstanding is None, "配置请求不允许并发"
            self.outstanding = plain(request)
            self.requests.append(self.outstanding)
        def complete(self, state="applied", applied=None):
            current, self.outstanding = self.outstanding, None
            assert current
            self.operationFinished.emit("backends", "apply", {"revision": current["revision"], "state": state,
                "applied": (current["interfaces"] if applied is None else applied) if state == "applied" else {},
                "message": "测试故障" if state == "failed" else ""})

    class Plugins(QObject):
        operationFinished = Signal(str, "QVariant")
        cudaDevicesDiscovered = Signal(str, "QVariant")
        @Slot(result=bool)
        def isBusy(self): return False
        @Slot(str)
        def releaseUnusedServices(self, _key): pass
        @Slot(str, str, str, "QVariant")
        def requestOperation(self, *_args): pass
        @Slot(str, str, result="QVariant")
        def getServiceStatus(self, *_args): return {"state": "stopped"}
    class GlobalConnector(QObject):
        pass
    class Popup(QObject):
        def __init__(self): super().__init__(); self.messages = []
        @Slot(str, str, str)
        def message(self, *args): self.messages.append(args)
        @Slot(str, str)
        def simple(self, *_args): pass
    class Bus(QObject):
        @Slot(str, "QVariant", str, str)
        def subscribeGroup(self, *_args): pass
        @Slot(str)
        def unsubscribeGroup(self, *_args): pass
        @Slot(str)
        def publish(self, *_args): pass
    class App(QObject):
        changed = Signal()
        def __init__(self):
            super().__init__(); self.shared = None
        @Property(QObject, notify=changed)
        def globalConfigs(self): return self.shared
        @Property(QObject, constant=True)
        def msnConnector(self): return connector
        @Property(QObject, constant=True)
        def popup(self): return popup
        @Property(QObject, constant=True)
        def pubSub(self): return bus
        @Property(bool, constant=True)
        def enabledEffect(self): return False

    QQuickStyle.setStyle("Basic")
    app = QGuiApplication([])
    qmlRegisterType(GlobalConnector, "GlobalConfigsConnector", 1, 0, "GlobalConfigsConnector")
    qmlRegisterType(Plugins, "PluginsConnector", 1, 0, "PluginsConnector")
    engine = QQmlEngine()
    engine.addImportPath(str(data / "site-packages/PySide6/qml"))
    connector, popup, bus, settings, stub = Connector(), Popup(), Bus(), Settings(), App()
    context = engine.rootContext()
    context.setContextProperty("qmlapp", stub)
    context.setContextProperty("UmiSettings", settings)
    context.setContextProperty("theme", {**{key: QColor("#333333") for key in ("textColor", "subTextColor", "bgColor", "specialBgColor", "specialTextColor", "noColor", "yesColor", "coverColor1", "coverColor2", "coverColor3", "coverColor4")}, "fontFamily": "Arial", "dataFontFamily": "Arial"})
    context.setContextProperty("size_", {"line": 24, "smallLine": 16, "text": 14, "smallText": 12, "spacing": 8, "smallSpacing": 4, "baseRadius": 4, "btnRadius": 4, "panelRadius": 4})
    failures = []
    old_handler = qInstallMessageHandler(lambda kind, _context, text: failures.append(text) if kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg) else None)
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(ROOT / "UmiOCR-data/qt_res/qml/Configs/GlobalConfigs.qml")))
    while component.isLoading(): app.processEvents()
    root = component.createWithInitialProperties({"autoInitialize": False, "configDict": {}, "panelLayout": []})
    assert root is not None, component.errorString()
    stub.shared = root
    stub.changed.emit()
    engine.globalObject().setProperty("global", engine.newQObject(root))

    def js(code):
        result = engine.evaluate(code)
        assert not result.isError(), result.toString() + "\n" + result.property("stack").toString()
        return result.toVariant()
    def pump(predicate=lambda: True):
        deadline = time.monotonic() + 3
        while True:
            app.processEvents()
            if predicate(): break
            assert time.monotonic() < deadline, "QML 状态机没有及时推进"
            time.sleep(0.001)

    js('global.ocrManager.init1({pp:{global_options:{type:"group",title:"PPOCR"}},vl:{global_options:{type:"group",title:"PaddleVL"}}}); global.documentManager.init1({vl:{global_options:{type:"group",title:"文档"}}}); global.configDict.ocr.lifecycle={type:"group",warmupMode:{default:"lazy"}}; global.reload();')
    connector.busy = True
    js('global.requestBackendApply()')
    pump()
    assert not connector.requests
    connector.busy = False
    connector.runtimeChanged.emit()
    pump(lambda: connector.outstanding is not None)
    assert set(connector.outstanding["interfaces"]) == {"ocr", "document"}
    connector.complete()
    pump(lambda: js('global.applyPhase') == 0)
    assert connector.gates[-1] is False
    assert js('global.ocrManager.apiKey') == "pp"
    assert js('global.documentManager.apiKey') == "vl"
    before = len(connector.requests)
    connector.busy = True
    js('global.setValue("ocr.api","vl",true)')
    pump()
    assert js('global.getValue("ocr.api")') == "vl", "忙时选择不能被回退"
    assert js('global.ocrManager.apiKey') == "pp"
    assert "任务结束后切换" in js('global.backendSwitchMessage()')
    js('global.setValue("ocr.api","pp",true); global.setValue("ocr.api","vl",true)')
    pump()
    assert len(connector.requests) == before
    connector.busy = False
    connector.runtimeChanged.emit()
    pump(lambda: connector.outstanding is not None)
    assert set(connector.outstanding["interfaces"]) == {"ocr"}, "OCR 变化不能无故重建 document"
    assert connector.outstanding["interfaces"]["ocr"]["apiKey"] == "vl"
    # 应用期间又选回 PP：旧完成回调可以更新真实 active，但不能覆盖最后 desired。
    js('global.setValue("ocr.api","pp",true)')
    connector.complete()
    pump(lambda: connector.outstanding is not None)
    assert connector.outstanding["interfaces"]["ocr"]["apiKey"] == "pp"
    connector.complete("pending")
    pump(lambda: connector.outstanding is not None)
    connector.complete()
    pump(lambda: not js('global.backendApplyPending') and js('global.applyPhase') == 0)
    assert js('global.ocrManager.apiKey') == "pp" and js('global.getValue("ocr.api")') == "pp"
    assert not popup.messages
    js('global.setValue("ocr.api","vl",true)')
    pump(lambda: connector.outstanding is not None)
    connector.complete("failed")
    pump(lambda: js('global.applyPhase') == 0)
    assert len(popup.messages) == 1
    assert connector.gates[-1] is False
    assert js('global.ocrManager.apiKey') == "pp"
    assert "失败" in js('global.backendSwitchMessage()')
    js('global.documentManager.localOptions = {win32_PaddleOCRVL_1_6:{}}; global.documentUiBackendIds = ["win32_PaddleOCRVL_1_6"]; global.documentUiEnabled = false')
    assert not js('global.buildPanelLayout().some(entry => entry.key === "document")')
    assert js('global.originDict["document.api"] !== undefined'), "隐藏面板不能删除HTTP所需的规范配置"
    assert js('global.documentManager.apiKey') == "vl", "UI门控不能清空活动文档接口"
    js('global.documentUiEnabled = true')
    assert js('global.buildPanelLayout().some(entry => entry.key === "document")')
    assert not failures, failures
    result = {"passed": True, "requests": connector.requests, "checks": ["忙时选择不回退", "空闲事件自动应用", "只重设变化能力", "最后选择生效", "忙碌自动重试", "真实失败解锁", "文档UI面板门控保留HTTP规范配置与活动接口"]}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("真实全局 QML 配置待切换状态机回归通过。")
    root.deleteLater()
    app.processEvents()
    qInstallMessageHandler(old_handler)
    del dll


if __name__ == "__main__":
    main()
