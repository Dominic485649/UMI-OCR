"""加载仓库当前源码 QML 的批量队列回归；不使用 QtTest、offscreen 或旧 ui.rcc。

用法：build/cache/python-31316/python.exe -I -B tests/test_batch_queue_qml.py <便携 UmiOCR-data>
这里只验证真实组件的逻辑/绑定和请求边界，原生 Explorer 拖放与鼠标手势另行验收。
"""

import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "UmiOCR-data" / "qt_res" / "qml"


def _value(value):
    return value.toVariant() if hasattr(value, "toVariant") else value


def run(data_root):
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError("请使用项目便携 Python 3.13，不使用系统 Python。")
    if os.environ.get("QT_QPA_PLATFORM", "").lower() in {"offscreen", "minimal"}:
        raise RuntimeError("本测试使用 Windows Qt 平台，不允许 offscreen/minimal。")
    sys.dont_write_bytecode = True
    packages = data_root.resolve() / "site-packages"
    sys.path.insert(0, str(packages))
    dll_handles = [os.add_dll_directory(str(packages / "PySide6"))]
    from PySide6.QtCore import QObject, Property, QUrl, Signal, Slot, qInstallMessageHandler
    from PySide6.QtGui import QColor, QGuiApplication
    from PySide6.QtQml import QQmlComponent, QQmlEngine, qmlRegisterType
    from PySide6.QtQuickControls2 import QQuickStyle

    messages = []
    previous_handler = qInstallMessageHandler(lambda _kind, _context, text: messages.append(text))
    QQuickStyle.setStyle("Basic")
    app = QGuiApplication.instance() or QGuiApplication(["batch-queue-source-qml-test"])
    app.setOrganizationName("UmiOCRRegression")
    app.setApplicationName("BatchQueueSourceQml")

    class SettingsStub(QObject):
        @Slot(str, str, result=bool)
        def contains(self, _category, _key):
            return False

        @Slot(str, str, "QVariant", result="QVariant")
        def value(self, _category, _key, default):
            return _value(default)

        @Slot(str, str, "QVariant")
        def setValue(self, _category, _key, _value):
            pass

        @Slot(str, str)
        def remove(self, _category, _key):
            pass

        @Slot()
        def sync(self):
            pass

    class BusStub(QObject):
        def __init__(self):
            super().__init__()
            self.subscriptions = {}
            self.groups = {}

        @Slot(str, "QVariant", str)
        def subscribe(self, title, item, name):
            self.subscriptions.setdefault(title, []).append((_value(item), name))

        @Slot(str, "QVariant", str, str)
        def subscribeGroup(self, title, item, name, group):
            item = _value(item)
            self.subscribe(title, item, name)
            self.groups.setdefault(group, []).append((title, item, name))

        @Slot(str, "QVariant", str)
        def unsubscribe(self, title, item, name):
            item = _value(item)
            self.subscriptions[title] = [entry for entry in self.subscriptions.get(title, []) if entry != (item, name)]

        @Slot(str)
        def unsubscribeGroup(self, group):
            for title, item, name in self.groups.pop(group, []):
                self.unsubscribe(title, item, name)

        def publish(self, title, *args):
            for item, name in list(self.subscriptions.get(title, [])):
                getattr(item, name)(*args)

    class UtilsStub(QObject):
        def __init__(self):
            super().__init__()
            self.scans = []
            self.opened = []

        @Slot("QVariant", str, bool, str, str, float)
        def asynFindFiles(self, urls, kind, recurrence, complete, update, _interval):
            self.scans.append({"urls": _value(urls), "kind": kind, "recurrence": recurrence,
                               "complete": complete, "update": update})

        @Slot("QVariant", result="QVariant")
        def QUrl2String(self, urls):
            result = []
            for value in _value(urls):
                url = value if isinstance(value, QUrl) else QUrl(str(value))
                if url.isLocalFile():
                    result.append(url.toLocalFile())
            return result

        @Slot(str)
        def startfile(self, path):
            self.opened.append(path)

        @Slot(str)
        def copyText(self, _text):
            pass

    class PopupStub(QObject):
        def __init__(self):
            super().__init__()
            self.notifications = []
            self.masks = []

        @Slot(str, str)
        @Slot(str, str, str)
        def simple(self, title, text, kind="default"):
            self.notifications.append((title, text, kind))

        @Slot(str, str)
        @Slot(str, str, str)
        def message(self, title, text, kind=""):
            self.notifications.append((title, text, kind))

        @Slot(str, str)
        def showMask(self, text, identity):
            self.masks.append(("show", identity))

        @Slot(str)
        def hideMask(self, identity):
            self.masks.append(("hide", identity))

        @Slot(str, str, "QVariant", str, "QVariant")
        def dialog(self, _title, _text, callback, _kind, _options):
            callback.call([engine.toScriptValue(True)])

    class UtilsDictStub(QObject):
        def __init__(self):
            super().__init__()
            self.post_calls = []

        @Slot(result="QVariant")
        def getTbpuParser(self):
            return {"title": "排版", "default": "none", "optionsList": [["none", "无"]]}

        @Slot(result="QVariant")
        def getPostTaskActions(self):
            return {"title": "完成操作", "type": "group", "system": {"title": "系统", "optionsList": [["", "无"]]}}

        @Slot(result="QVariant")
        def getSimpleNotificationType(self):
            return {"title": "通知", "optionsList": [["default", "默认"]]}

        @Slot(str)
        def postTaskHardwareCtrl(self, value):
            self.post_calls.append(value)

    class OcrManagerStub(QObject):
        @Slot("QVariant", str, result="QVariant")
        def deploy(self, _page, _key):
            return {"title": "测试 OCR", "type": "group", "engine": {"default": "stub"}}

    class GlobalConfigsStub(QObject):
        def __init__(self):
            super().__init__()
            self.dicts = UtilsDictStub()
            self.ocr = OcrManagerStub()
            self.values = {"window.doubleLayout": {}, "ui.imgShowOverlay": True}

        @Property(QObject, constant=True)
        def utilsDicts(self):
            return self.dicts

        @Property(QObject, constant=True)
        def ocrManager(self):
            return self.ocr

        @Slot(str, result="QVariant")
        def getValue(self, key):
            return self.values.get(key, False)

        @Slot(str, "QVariant")
        @Slot(str, "QVariant", bool)
        def setValue(self, key, value, _save=False):
            self.values[key] = _value(value)

    class TabStub(QObject):
        def __init__(self):
            super().__init__()
            self.closed = []

        @Slot("QVariant", result=int)
        def getTabPageIndex(self, _page):
            return 0

        @Slot(int)
        def delTabPage(self, index):
            self.closed.append(index)

    class ImageManagerStub(QObject):
        @Slot(str, result=str)
        def loadImage(self, _path):
            return ""

    class PreviewStub(QObject):
        previewImg = Signal(str)
        previewOcr = Signal("QVariant")

        @Slot()
        def clear(self):
            pass

        @Slot(str, int, str)
        def preview(self, _path, _page, _password):
            pass

        @Slot(str, int, str, "QVariant")
        def ocr(self, _path, _page, _password, _args):
            pass

    qmlRegisterType(PreviewStub, "DocPreviewConnector", 1, 0, "DocPreviewConnector")

    bus, utils, popup, global_configs, tabs = BusStub(), UtilsStub(), PopupStub(), GlobalConfigsStub(), TabStub()
    image_manager = ImageManagerStub()

    class AppStub(QObject):
        loaderChanged = Signal()

        def __init__(self):
            super().__init__()
            self.loader = None

        @Property(bool, constant=True)
        def enabledEffect(self):
            return False

        @Property(QObject, constant=True)
        def pubSub(self):
            return bus

        @Property(QObject, constant=True)
        def utilsConnector(self):
            return utils

        @Property(QObject, constant=True)
        def popup(self):
            return popup

        @Property(QObject, constant=True)
        def globalConfigs(self):
            return global_configs

        @Property(QObject, constant=True)
        def tab(self):
            return tabs

        @Property(QObject, constant=True)
        def imageManager(self):
            return image_manager

        @Property(QObject, notify=loaderChanged)
        def asynFilesLoader(self):
            return self.loader

    def state(rows=(), **changes):
        value = {"ok": True, "batchId": "", "generation": 0, "state": "idle", "running": False,
                 "paused": False, "completed": False, "canPostTaskActions": False, "activeId": "",
                 "pending": [], "importCount": 0, "lockedCount": 0, "totalDocs": len(rows), "doneDocs": 0,
                 "successDocs": 0, "failedDocs": 0, "skippedDocs": 0, "stoppedDocs": 0,
                 "totalPages": sum(row.get("page_count", 1) for row in rows), "donePages": 0, "elapsed": 0,
                 "rows": list(rows), "summary": {}}
        value.update(changes)
        return value

    def row(path, status="ready", **changes):
        value = {"id": path, "path": path, "status": status, "page_count": 3, "range_start": 1,
                 "range_end": 3, "is_encrypted": False, "is_authenticate": True, "password": "",
                 "donePages": 0, "artifacts": [], "attemptArtifacts": [],
                 "canMove": status in {"ready", "pending"}, "canRemove": status not in {"active", "finalizing"},
                 "canReocr": status in {"finished", "failed", "stopped"}, "canUnlock": status == "locked"}
        value.update(changes)
        return value

    class ControllerStub(QObject):
        def __init__(self):
            super().__init__()
            self.calls = []
            self.states = {"doc": state(), "ocr": state()}
            self.answers = {}
            self.originals = {}
            self.artifacts = {}
            self.next_ticket = 0
            self.next_unlock = 0
            self.unlocks = {}

        @Slot(str, str, "QVariant", result="QVariant")
        def callPy(self, key, name, args):
            args = _value(args)
            self.calls.append((key, name, copy.deepcopy(args)))
            if (key, name) in self.answers:
                answer = self.answers.pop((key, name))
                if isinstance(answer, dict) and "rows" in answer:
                    self.states[key] = copy.deepcopy(answer)
                return answer
            if name == "unlockDocument":
                self.next_unlock += 1
                token = f"controlled-unlock-{self.next_unlock}"
                current = copy.deepcopy(self.states[key])
                for item in current["rows"]:
                    if item["path"] == args[0]:
                        item.update(status="unlocking", canUnlock=False)
                current["unlockToken"] = token
                self.unlocks[args[0]] = (token, current["generation"])
                self.states[key] = copy.deepcopy(current)
                return current
            if name == "cancelUnlock":
                current = copy.deepcopy(self.states[key])
                matches = self.unlocks.get(args[0]) == (args[1], args[2]) and current["generation"] == args[2]
                if matches:
                    del self.unlocks[args[0]]
                    for item in current["rows"]:
                        if item["path"] == args[0]:
                            item.update(status="locked", canUnlock=True)
                current["cancelled"] = matches
                self.states[key] = copy.deepcopy(current)
                return current
            if name == "beginImport":
                self.next_ticket += 1
                return {"ok": True, "ticketId": f"ticket-{self.next_ticket}",
                        "batchId": self.states[key]["batchId"], "generation": self.states[key]["generation"]}
            if name == "getOriginal":
                return self.originals.get(args[0], {"path": args[0], "exists": True, "openable": True, "error": ""})
            if name == "getArtifacts":
                return copy.deepcopy(self.artifacts.get(args[0], []))
            if name == "openArtifact":
                for artifact in self.artifacts.get(args[0], []):
                    if artifact["format"] == args[1] and artifact["path"] == args[2] and artifact["openable"]:
                        return {"ok": True, "path": artifact["path"]}
                return {"ok": False, "error": "产物已失效"}
            if name in {"msnDocs", "msnPaths"}:
                return self.states[key]["batchId"] or "test-started"
            return copy.deepcopy(self.states[key])

        def matching(self, key, name):
            return [args for call_key, call_name, args in self.calls if (call_key, call_name) == (key, name)]

    qml_app, settings, controller = AppStub(), SettingsStub(), ControllerStub()
    engine = QQmlEngine()
    engine.addImportPath(str(packages / "PySide6" / "qml"))
    context = engine.rootContext()
    context.setContextProperty("qmlapp", qml_app)
    context.setContextProperty("UmiSettings", settings)
    context.setContextProperty("UmiAbout", {"app": {"system": "win32"}, "version": "3.0.2"})
    context.setContextProperty("theme", {
        **{name: QColor(value) for name, value in {
            "tabBarColor": "#eeeeee", "bgColor": "#ffffff", "textColor": "#111111", "subTextColor": "#555555",
            "yesColor": "#228844", "noColor": "#bb3322", "specialBgColor": "#eeeeee", "specialTextColor": "#1166cc",
            "coverColor1": "#11000000", "coverColor2": "#22000000", "coverColor3": "#33000000", "coverColor4": "#55000000"
        }.items()}, "fontFamily": "Microsoft YaHei", "dataFontFamily": "Microsoft YaHei"})
    context.setContextProperty("size_", {"scale": 1, "line": 24, "smallLine": 18, "largeLine": 28,
        "textScale": 1, "text": 16, "smallText": 13, "largeText": 20, "spacing": 8, "smallSpacing": 4,
        "btnRadius": 4, "panelRadius": 6, "hTabBarHeight": 36, "windowRadius": 0})
    components, objects, windows = [], [], []

    def wait(predicate, message="QML 条件未满足"):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            app.processEvents()
            if predicate():
                return
        raise AssertionError(message)

    def load(relative, initial=None):
        component = QQmlComponent(engine, QUrl.fromLocalFile(str(SOURCE / relative)))
        wait(lambda: not component.isLoading())
        obj = component.createWithInitialProperties(initial or {})
        if obj is None:
            raise AssertionError(component.errorString())
        components.append(component)
        objects.append(obj)
        return obj

    def expose(name, obj):
        engine.globalObject().setProperty(name, engine.newQObject(obj))

    def js(code):
        value = engine.evaluate(code)
        if value.isError():
            raise AssertionError(value.toString() + "\n" + code[:350])
        return value.toVariant()

    def window_for(item):
        component = QQmlComponent(engine)
        component.setData(b"import QtQuick; import QtQuick.Window; Window { width: 1000; height: 720; visible: false }", QUrl("inline:batch-test-window.qml"))
        wait(lambda: not component.isLoading())
        window = component.create()
        assert window is not None, component.errorString() or "\n".join(messages[-10:])
        item.setParentItem(window.contentItem())
        item.setWidth(1000)
        item.setHeight(720)
        components.append(component)
        windows.append(window)
        return window

    def push(name, key, value):
        controller.states[key] = copy.deepcopy(value)
        js(f"{name}.onBatchState({json.dumps(value, ensure_ascii=False)})")

    passed = []
    ui_settings = load("Configs/Settings_.qml", {"category": "BatchQueueSourceQmlTest"})
    context.setContextProperty("uiSettings", ui_settings)
    loader = load("MainWindow/AsynFilesLoader.qml")
    qml_app.loader = loader
    qml_app.loaderChanged.emit()
    expose("loader", loader)
    table = load("Widgets/FilesTableView.qml")
    window_for(table)
    expose("table", table)
    js('table.add({path:"A",time:"",state:""}); table.add({path:"C",time:"",state:""}); table.add({path:"B",time:"",state:""},1)')
    assert js('JSON.stringify(table.getColumnsValue("path"))') == '["A","B","C"]'
    assert js('table.ik2i("C")') == 2
    js('table.del("B"); table.setProperty("C","state","correct"); table.add({path:"D",time:"",state:""},0); table.move("C",0)')
    assert js('JSON.stringify(table.getColumnsValue("path"))') == '["C","D","A"]'
    assert js('table.get("C").state') == "correct"
    assert js('table.ik2i("A")') == 2
    assert not table.property("dragSortEnabled") and not table.property("contextMenuEnabled")
    js('table.reconcileRows([{path:"A",time:"",state:"a"},{path:"C",time:"",state:"c"}])')
    assert js('table.ik2i("A")') == 0 and js('table.ik2i("C")') == 1 and js('table.ik2i("D")') == -1
    js('table.isLock=true; table.allowOpenWhileLocked=true')
    assert table.property("openEnabled") and not table.property("clearEnabled")
    assert js('table.requestClear()') is False and table.property("rowCount") == 2
    passed.append("索引插入/删除/移动/快照协调与导入独立授权")

    # 请求持有真实扫描终态；每个请求的 topic 和回调均不共用。
    js('var loadResults=[]; var first=loader.start(["one"],"doc",true,function(rows,t){loadResults.push([t.requestId,t.status,rows])}); var second=loader.run(["two"],"image",false,function(rows,t){loadResults.push([t.requestId,t.status,rows])})')
    wait(lambda: len(utils.scans) == 1)
    first, second = js("first"), js("second")
    scan1 = utils.scans[-1]
    assert loader.cancel(first) and loader.property("pendingCount") == 2
    app.processEvents()
    assert len(utils.scans) == 1
    bus.publish(scan1["complete"], [{"path": "late-cancelled"}], [])
    wait(lambda: len(utils.scans) == 2)
    scan2 = utils.scans[-1]
    assert scan1["complete"] != scan2["complete"]
    bus.publish(scan1["complete"], [{"path": "must-not-cross"}], [])
    bus.publish(scan2["complete"], ["two.png"], [])
    assert js("loadResults") == [[first, "cancelled", []], [second, "complete", ["two.png"]]]
    js('var emptyWasAsync=false; var returnedId=loader.start([],"image",false,function(rows,t){emptyWasAsync=(returnedId===t.requestId && t.status==="empty")})')
    assert js("emptyWasAsync") is False
    wait(lambda: js("emptyWasAsync") is True)
    js('var badStatus=""; loader.start(["bad"],"invalid",false,function(rows,t){badStatus=t.status}); loader.start(["fatal"],"doc",false,function(rows,t){loadResults.push([t.requestId,t.status,rows])})')
    wait(lambda: js("badStatus") == "error" and len(utils.scans) == 3)
    bus.publish(utils.scans[-1]["complete"], [], [{"kind": "scanerror", "message": "受控扫描失败"}])
    assert js("loadResults[loadResults.length-1][1]") == "error"
    callback_failures = []
    loader.callbackFailed.connect(callback_failures.append)
    js('var continued=false; loader.start([],"image",false,function(){throw new Error("受控回调失败")}); loader.start([],"image",false,function(){continued=true})')
    wait(lambda: js("continued") is True)
    assert len(callback_failures) == 1 and not popup.masks
    baseline = len(utils.scans)
    js('var queuedCancelled=false; loader.start(["keep"],"image",false,function(){}); var cancelledId=loader.start(["skip"],"doc",false,function(rows,t){queuedCancelled=t.status==="cancelled" && rows.length===0})')
    wait(lambda: len(utils.scans) == baseline + 1)
    assert loader.cancel(js("cancelledId")) and js("queuedCancelled") is True
    assert loader.property("pendingCount") == 1
    bus.publish(utils.scans[-1]["complete"], ["keep.png"], [])
    assert len(utils.scans) == baseline + 1
    baseline = len(utils.scans)
    js('var onStartCancelled=false; var cancelNext=function(id){loader.requestStarted.disconnect(cancelNext);loader.cancel(id)};loader.requestStarted.connect(cancelNext);loader.start(["not-started"],"doc",false,function(rows,t){onStartCancelled=t.status==="cancelled"})')
    wait(lambda: js("onStartCancelled") is True)
    assert len(utils.scans) == baseline
    assert not any(values for key, values in bus.subscriptions.items() if key.startswith("<<fileLoad"))
    passed.append("请求身份/串行/发起前取消/取消等待真实终态/排队取消/旧事件隔离/空与异常/回调异常续行")

    drop = load("Widgets/DropArea_.qml")
    expose("fileDrop", drop)
    paths = js('fileDrop.localPaths({source:null,hasUrls:true,urls:["file:///C:/中文%20目录/a.pdf"]})')
    assert paths == ["C:/中文 目录/a.pdf"]
    assert js('fileDrop.localPaths({source:null,hasUrls:true,urls:["https://example.invalid/a.pdf"]})') == []
    assert js('fileDrop.localPaths({source:{internal:true},hasUrls:true,urls:["file:///C:/a.pdf"]})') == []
    assert js('fileDrop.localPaths({source:null,hasUrls:true,urls:["file:///C:/a.pdf","https://example.invalid/b"]})') == []
    assert js('var e={source:null,hasUrls:true,urls:["file:///C:/a.pdf"],accepted:false};fileDrop.inspectDrag(e);e.accepted') is True
    js('fileDrop.enable=false')
    assert not drop.property("acceptableDrag")
    passed.append("外部本地 URL 与内部拖序分型、拒绝非本地及混合 URL")

    doc = load("TabPages/BatchDOC/BatchDOC.qml", {"connector": controller, "ctrlKey": "doc"})
    ocr = load("TabPages/BatchOCR/BatchOCR.qml", {"connector": controller, "ctrlKey": "ocr"})
    doc_window = window_for(doc)
    window_for(ocr)
    expose("doc", doc)
    expose("ocr", ocr)
    doc_table = doc.findChild(QObject, "batchDocFilesTable")
    ocr_table = ocr.findChild(QObject, "batchOcrFilesTable")
    doc_ctrl = doc.findChild(QObject, "batchDocMissionCtrl")
    ocr_ctrl = ocr.findChild(QObject, "batchOcrMissionCtrl")
    assert all((doc_table, ocr_table, doc_ctrl, ocr_ctrl))
    expose("docTable", doc_table)
    expose("ocrTable", ocr_table)
    expose("docCtrl", doc_ctrl)
    expose("ocrCtrl", ocr_ctrl)
    a, b, c = row("A.pdf", "active", canMove=False, canRemove=False), row("B.pdf", "pending"), row("C.pdf", "pending")
    active = state([a, b, c], batchId="batch-1", running=True, state="active", totalPages=9, donePages=2, activeId="A.pdf")
    push("doc", "doc", active)
    assert doc_table.property("openEnabled") and not doc_table.property("clearEnabled")
    assert doc_ctrl.property("msnAllNum") == 9 and doc_ctrl.property("msnNowNum") == 2
    assert not ocr_table.property("contextMenuEnabled") and not ocr_table.property("dragSortEnabled")
    js('docTable.beginRowDrag("C.pdf",20);docTable.dragBeforePath="B.pdf";docTable.finishRowDrag()')
    assert controller.matching("doc", "movePending")[-1] == ["C.pdf", "B.pdf"]
    assert js('docTable.getColumnsValue("path")') == ["A.pdf", "B.pdf", "C.pdf"]
    reordered = dict(active, rows=[a, c, b])
    push("doc", "doc", reordered)
    assert js('docTable.getColumnsValue("path")') == ["A.pdf", "C.pdf", "B.pdf"]
    js('var capturedMenu=doc.buildDocMenu("B.pdf")')
    shifted = dict(active, rows=[a, b], totalPages=6)
    push("doc", "doc", shifted)
    js('capturedMenu[3].action()')
    assert controller.matching("doc", "removeRows")[-1] == [["B.pdf"]]
    assert js('docTable.getColumnsValue("path")') == ["A.pdf", "B.pdf"]
    # 已经升为 current 时，仍提交稳定路径给后端终审；被拒绝不本地挪动/删除。
    js('docTable.beginRowDrag("B.pdf",20)')
    current_b = row("B.pdf", "active", canMove=False, canRemove=False)
    push("doc", "doc", dict(active, rows=[a, current_b], totalPages=6))
    controller.answers[("doc", "movePending")] = {"ok": False, "error": "当前项不可移动"}
    js('docTable.dragBeforePath="";docTable.finishRowDrag()')
    assert controller.matching("doc", "movePending")[-1] == ["B.pdf", ""]
    assert js('doc.buildDocMenu("B.pdf")[3].enabled') is False
    assert doc_ctrl.property("msnNowNum") == 2
    passed.append("拖序/移除只提交稳定路径、接受后端快照、current 状态改变时不本地越权")

    products = [{"format": fmt, "path": f"C:/results/B.{fmt}", "status": "saved", "saved": True,
                 "exists": True, "openable": True, "error": ""} for fmt in ("txt", "pdf")]
    controller.artifacts["B.pdf"] = products
    finished_b = row("B.pdf", "finished")
    push("doc", "doc", dict(active, rows=[a, finished_b], totalPages=6))
    assert js('doc.buildDocMenu("B.pdf")[1].children.length') == 2
    js('var artifactMenu=doc.buildDocMenu("B.pdf");artifactMenu[1].children[1].action()')
    assert controller.matching("doc", "openArtifact")[-1] == ["B.pdf", "pdf", "C:/results/B.pdf"]
    assert utils.opened[-1] == "C:/results/B.pdf"
    js('artifactMenu[2].action()')
    assert controller.matching("doc", "reOCR")[-1][0] == "B.pdf"
    opened_before = len(utils.opened)
    controller.artifacts["B.pdf"][1].update(exists=False, openable=False)
    js('artifactMenu[1].children[1].action()')
    assert len(utils.opened) == opened_before
    controller.originals["B.pdf"] = {"path": "B.pdf", "exists": False, "openable": False, "error": "已缺失"}
    assert js('doc.buildDocMenu("B.pdf")[0].enabled') is False
    assert js('doc.openOriginal("B.pdf")') is False
    assert len(utils.opened) == opened_before
    # 打开真实 Menu_，检查新条目的 disabled 与真实多格式子菜单，而非复制菜单逻辑。
    # doc_window.show()
    js('docTable.openRowMenu("B.pdf",30,30)')
    menu_obj = doc_table.findChild(QObject, "filesRowMenu")
    expose("realMenu", menu_obj)
    js('realMenu.activate(realMenu.menuList[1],20)')
    assert js('realMenu.childMenu_ !== null') is True
    js('realMenu.close()')
    # doc_window.hide()
    passed.append("菜单捕获路径、多格式真实子菜单、点击时产物/原件校验、单件重 OCR")

    locked = row("locked.pdf", "locked", page_count=0, range_end=0, is_encrypted=True, is_authenticate=False)
    push("doc", "doc", state([locked], batchId="unlock-batch", running=True, state="waiting_unlock", lockedCount=1, totalPages=0))
    assert js('doc.showPassword("locked.pdf")') is True
    password_input = doc.findChild(QObject, "batchDocPasswordInput")
    password_dialog = doc.findChild(QObject, "batchDocPasswordDialog")
    password_cancel = doc.findChild(QObject, "batchDocPasswordCancel")
    preview = doc.findChild(QObject, "documentPreview")
    assert all((password_input, password_dialog, password_cancel, preview)) and not preview.property("visible")
    expose("passwordDialog", password_dialog)
    expose("passwordCancel", password_cancel)
    password_input.setProperty("text", "controlled-correct-password")
    cancellations_before_success = len(controller.matching("doc", "cancelUnlock"))
    js('doc.submitPassword()')
    assert controller.matching("doc", "unlockDocument")[-1][0] == "locked.pdf"
    assert js('passwordDialog.verification.unlockToken').startswith("controlled-unlock-")
    unlocked = row("locked.pdf", "pending", is_encrypted=True, is_authenticate=True, page_count=4, range_end=4)
    push("doc", "doc", state([unlocked], batchId="unlock-batch", running=True, state="active", totalPages=4))
    assert not password_dialog.property("visible")
    assert len(controller.matching("doc", "cancelUnlock")) == cancellations_before_success
    expose("docPreview", preview)
    js('docPreview.updateInfo("locked.pdf",{range_start:2,range_end:3,argd:{"tbpu.ignoreRangeStart":2}})')
    assert controller.matching("doc", "syncMetadata")[-1][0] == "locked.pdf"
    assert js('docTable.get("locked.pdf").pages') == "4"
    passed.append("独立密码输入不打开完整预览、确认元信息经 controller、成功主动关闭不反向取消")

    def pending_password(generation=0):
        pending_state = state([copy.deepcopy(locked)], generation=generation, batchId="unlock-batch", running=True,
                              state="waiting_unlock", lockedCount=1, totalPages=0)
        push("doc", "doc", pending_state)
        assert js('doc.showPassword("locked.pdf")') is True
        password_input.setProperty("text", "controlled-correct-password")
        js('doc.submitPassword()')
        assert password_dialog.property("busy")
        return js("passwordDialog.verification")

    starts_before_cancel = len(controller.matching("doc", "msnDocs"))
    for dismissal in ("button", "reject", "close"):
        verification = pending_password()
        cancel_count = len(controller.matching("doc", "cancelUnlock"))
        if dismissal == "button":
            js("passwordCancel.clicked()")
        elif dismissal == "reject":
            # 真实 Dialog.reject()/onRejected 是 Esc 使用的同一拒绝通道，不冒充原生按键验收。
            js("passwordDialog.reject()")
        else:
            js("passwordDialog.close()")
        wait(lambda: not password_dialog.property("visible"))
        assert len(controller.matching("doc", "cancelUnlock")) == cancel_count + 1
        assert controller.matching("doc", "cancelUnlock")[-1] == [verification["path"], verification["unlockToken"], verification["generation"]]
        late_success = {"ok": True, "unlockToken": verification["unlockToken"], "generation": verification["generation"]}
        js(f'doc.onUnlockResult("locked.pdf",{json.dumps(late_success)})')
        assert not password_dialog.property("visible")
        assert js('doc.rowForPath("locked.pdf").status') == "locked"
        assert len(controller.matching("doc", "msnDocs")) == starts_before_cancel
    # 成功快照早于 unlockDocument 返回：程序关闭也不能补发 cancelUnlock。
    push("doc", "doc", state([copy.deepcopy(locked)], batchId="unlock-batch", running=True, state="waiting_unlock", lockedCount=1, totalPages=0))
    assert js('doc.showPassword("locked.pdf")') is True
    password_input.setProperty("text", "controlled-correct-password")
    controller.answers[("doc", "unlockDocument")] = state([unlocked], batchId="unlock-batch", running=True,
        state="active", totalPages=4, unlockToken="controlled-sync-success")
    cancels_before_early_success = len(controller.matching("doc", "cancelUnlock"))
    js("doc.submitPassword()")
    assert not password_dialog.property("visible")
    assert len(controller.matching("doc", "cancelUnlock")) == cancels_before_early_success
    passed.append("真实取消按钮/rejected/用户关闭均取消当前 token、晚成功不回填、同步成功关闭不取消")

    # 两个输入入口运行中调用相同导入协议；只 finishImport，不再次 msnDocs/msnPaths。
    doc_drop = doc.findChild(QObject, "batchDocExternalDrop")
    ocr_drop = ocr.findChild(QObject, "batchOcrExternalDrop")
    expose("docDrop", doc_drop)
    expose("ocrDrop", ocr_drop)
    push("ocr", "ocr", state([row("A.png", "active", page_count=1)], batchId="ocr-batch", state="active", running=True))
    baseline = len(utils.scans)
    doc_starts = len(controller.matching("doc", "msnDocs"))
    ocr_starts = len(controller.matching("ocr", "msnPaths"))
    js('docTable.addPaths(["C:/open.pdf"]);docDrop.callback(["C:/drop.pdf"]);ocrTable.addPaths(["C:/open.png"]);ocrDrop.callback(["C:/drop.png"])')
    for index in range(4):
        wait(lambda index=index: len(utils.scans) == baseline + index + 1)
        scan = utils.scans[-1]
        values = [{"path": scan["urls"][0], "page_count": 1, "is_encrypted": False}] if scan["kind"] == "doc" else scan["urls"]
        bus.publish(scan["complete"], values, [])
    assert len(controller.matching("doc", "msnDocs")) == doc_starts
    assert len(controller.matching("ocr", "msnPaths")) == ocr_starts
    assert len(controller.matching("doc", "finishImport")) == 2
    assert len(controller.matching("ocr", "finishImport")) == 2
    assert [scan["kind"] for scan in utils.scans[baseline:]] == ["doc", "doc", "image", "image"]
    passed.append("DOC/OCR 打开与拖入同入口、运行中追加仅 finishImport、不重交整表")

    # 开始时扫描尚未结束仍交由后端 hold，不能因为当前表空就静默提前结束。
    held = state([], batchId="holding-batch", state="waiting_import", running=True, importCount=1)
    controller.states["doc"] = held
    js('doc.onBatchState({ok:true,rows:[],running:false,importCount:1,generation:0});doc.docStart()')
    assert controller.matching("doc", "msnDocs")[-1][0] == []
    assert doc_ctrl.property("state_") == "run"
    # 清空后晚结果仍需结算原票据；后端返回新代次空表，前端绝不重新 add。
    baseline = len(utils.scans)
    js('doc.addDocs(["C:/late.pdf"])')
    wait(lambda: len(utils.scans) == baseline + 1)
    late_scan = utils.scans[-1]
    cleared = state([], generation=1)
    controller.states["doc"] = cleared
    controller.answers[("doc", "clearRows")] = cleared
    push("doc", "doc", state([], generation=0))
    js('doc.docClear()')
    bus.publish(late_scan["complete"], [{"path": "C:/late.pdf", "page_count": 1}], [])
    assert doc_table.property("rowCount") == 0
    assert controller.matching("doc", "finishImport")[-1][2]["status"] == "cancelled"
    assert controller.matching("doc", "finishImport")[-1][1] == []
    passed.append("初次扫描委托 hold、清空代次后的扫描晚到不复活、取消仍结算票据")

    # Stop 后扫描不丢身份；新批已经开始时，旧结果只按后端 ready 快照显示。
    old_running = state([a], generation=1, batchId="old-batch", state="active", running=True)
    push("doc", "doc", old_running)
    baseline = len(utils.scans)
    js('doc.addDocs(["C:/stopped-late.pdf"])')
    old_ticket = controller.matching("doc", "beginImport")[-1]
    old_ticket_id = f"ticket-{controller.next_ticket}"
    wait(lambda: len(utils.scans) == baseline + 1)
    stopped_scan = utils.scans[-1]
    stopped = state([row("A.pdf", "stopped")], generation=2, batchId="old-batch", state="stopped")
    controller.states["doc"] = stopped
    controller.answers[("doc", "msnStop")] = stopped
    js('doc.docStop()')
    new_running = state([a], generation=2, batchId="new-batch", state="active", running=True)
    controller.states["doc"] = new_running
    js('doc.docStart()')
    starts_before_late = len(controller.matching("doc", "msnDocs"))
    late_ready = state([a, row("C:/stopped-late.pdf", "ready", canMove=False)], generation=2,
                       batchId="new-batch", state="active", running=True, totalDocs=1, totalPages=3)
    controller.states["doc"] = late_ready
    bus.publish(stopped_scan["complete"], [{"path": "C:/stopped-late.pdf", "page_count": 3}], [])
    assert controller.matching("doc", "finishImport")[-1][0] == old_ticket_id
    assert len(controller.matching("doc", "msnDocs")) == starts_before_late
    assert js('docTable.get("C:/stopped-late.pdf").state') == ""
    assert doc_ctrl.property("msnAllNum") == 3
    passed.append("Stop 旧票据跨新批仍结算原身份、晚结果只显示 ready 而不再次提交")

    # OCR 的单段结束不会让仍在保存/续接的整批停止。
    segment = state([row("A.png", "finalizing", page_count=1)], batchId="ocr-batch", state="finalizing",
                    running=True, totalPages=1, donePages=1)
    push("ocr", "ocr", segment)
    js('ocr.onOcrEnd("[Success] segment complete","segment-id")')
    assert ocr_ctrl.property("state_") == "run"
    push("ocr", "ocr", dict(segment, totalPages=3, donePages=1))
    assert ocr_ctrl.property("msnAllNum") == 3 and ocr_ctrl.property("msnNowNum") == 1
    passed.append("OCR 段结束不冒充整批输出结束、续接预算来自后端")

    # 用实际计时器的起点哨兵证明追加/删除只改预算，不再 runFinished 重置。
    counted = state([a, b], generation=2, batchId="counts-batch", state="active", running=True, totalPages=6, donePages=2)
    push("doc", "doc", counted)
    timer = doc_ctrl.findChild(QObject, "missionTimer")
    assert timer is not None
    timer.setProperty("startStamp", 123.0)
    push("doc", "doc", dict(counted, totalPages=12, donePages=3))
    assert timer.property("startStamp") == 123.0
    push("doc", "doc", dict(counted, totalPages=5, donePages=3))
    assert timer.property("startStamp") == 123.0
    assert doc_ctrl.property("msnAllNum") == 5 and doc_ctrl.property("msnNowNum") == 3
    notifications = len([item for item in popup.notifications if item[0] == "批量识别完成"])
    equal_not_done = dict(counted, totalPages=3, donePages=3, skippedDocs=1, completed=False)
    push("doc", "doc", equal_not_done)
    assert len([item for item in popup.notifications if item[0] == "批量识别完成"]) == notifications
    finished = dict(equal_not_done, state="finished", running=False, completed=True, canPostTaskActions=False)
    push("doc", "doc", finished)
    push("doc", "doc", finished)
    assert len([item for item in popup.notifications if item[0] == "批量识别完成"]) == notifications + 1
    assert not global_configs.dicts.post_calls
    assert "失败或跳过" in doc_ctrl.property("statusOverride")
    assert "文档" in js("doc.queueSummary()") and "页" in js("doc.queueSummary()")
    passed.append("文档/页数分离、预算增删不重置计时、计数相等不误判完成或执行电源动作")

    # Stop/清空先使原代次失效；旧 Dialog 不得取消同路径的新 token，也不能接收其晚结果。
    for invalidation, old_generation, new_generation in (("stop", 2, 3), ("clear", 3, 4)):
        old_verification = pending_password(old_generation)
        if invalidation == "clear":
            # 空闲时验证密码也允许用户清空；运行中的清空仍保持禁用。
            push("doc", "doc", dict(controller.states["doc"], running=False, state="idle"))
        cancels_before_invalidation = len(controller.matching("doc", "cancelUnlock"))
        invalidated = state([copy.deepcopy(locked)] if invalidation == "stop" else [], generation=new_generation,
                            batchId="unlock-batch", state="stopped" if invalidation == "stop" else "idle")
        method = "msnStop" if invalidation == "stop" else "clearRows"
        controller.answers[("doc", method)] = invalidated
        js("doc.docStop()" if invalidation == "stop" else "doc.docClear()")
        assert not password_dialog.property("visible")
        assert len(controller.matching("doc", "cancelUnlock")) == cancels_before_invalidation
        current_verification = pending_password(new_generation)
        stale_result = {"unlockToken": old_verification["unlockToken"], "generation": old_generation, "error": "旧验证结果"}
        js(f'doc.onUnlockResult("locked.pdf",{json.dumps(stale_result, ensure_ascii=False)})')
        # 即便代次相同，不匹配的旧 token 也不得改变当前 busy/错误状态。
        stale_result["generation"] = new_generation
        js(f'doc.onUnlockResult("locked.pdf",{json.dumps(stale_result, ensure_ascii=False)})')
        assert password_dialog.property("busy")
        assert js("passwordDialog.verification.unlockToken") == current_verification["unlockToken"]
        assert password_dialog.property("errorText") == ""
        js("passwordDialog.reject()")
        assert controller.matching("doc", "cancelUnlock")[-1] == ["locked.pdf", current_verification["unlockToken"], new_generation]
        assert len(controller.matching("doc", "cancelUnlock")) == cancels_before_invalidation + 1
    passed.append("Stop/清空旧代次和旧 token 不取消同路径的新验证、晚回调不污染新 Dialog")

    # 关闭使页面失活；真实扫描结束后不再向已经关闭的 controller 写入。
    baseline = len(utils.scans)
    js('doc.addDocs(["C:/closing.pdf"])')
    wait(lambda: len(utils.scans) == baseline + 1)
    closing_scan = utils.scans[-1]
    finish_count = len(controller.matching("doc", "finishImport"))
    js('doc.finishClose()')
    assert not doc.property("pageAlive") and controller.matching("doc", "closeBatch")
    bus.publish(closing_scan["complete"], [{"path": "C:/closing.pdf", "page_count": 1}], [])
    assert len(controller.matching("doc", "finishImport")) == finish_count
    assert not loader.property("busy")
    assert not popup.masks
    passed.append("关闭代次与晚扫描隔离、加载和拖入不创建全局 modal 遮罩")

    # 真正销毁页面 QObject 后再送扫描终态，不能调用已销毁的页面上下文。
    from PySide6.QtCore import QCoreApplication, QEvent
    from shiboken6 import isValid
    baseline = len(utils.scans)
    js('ocr.addImages(["C:/destroyed-page.png"])')
    wait(lambda: len(utils.scans) == baseline + 1)
    destroyed_scan = utils.scans[-1]
    failures_before_destroy = len(callback_failures)
    js('ocr.finishClose()')
    ocr.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not isValid(ocr)
    bus.publish(destroyed_scan["complete"], ["C:/destroyed-page.png"], [])
    assert len(callback_failures) == failures_before_destroy
    assert not loader.property("busy")
    passed.append("页面 QObject 真正销毁后的扫描终态安全忽略")

    app.processEvents()
    # 资源图标不是本测试目标；任何绑定/运行时错误仍必须失败，不用截断掩盖。
    errors = [text for text in messages if any(marker in text for marker in (
        "ReferenceError:", "TypeError:", "SyntaxError:", "Unable to assign", "Cannot assign", "Binding loop", "is not a function"))]
    if errors:
        raise AssertionError("QML 运行时错误：\n" + "\n".join(errors[:20]))
    for window in windows:
        window.close()
    for obj in reversed(objects):
        if isValid(obj):
            obj.deleteLater()
    app.processEvents()
    engine.deleteLater()
    app.processEvents()
    qInstallMessageHandler(previous_handler)
    del dll_handles
    return {"python": sys.version.split()[0], "source_qml": str(SOURCE), "passed": passed,
            "native_explorer_drop": "未在此脚本测试", "native_mouse_gestures": "未在此脚本测试"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", type=Path, help="只借用此目录的便携 PySide6，不加载其 app.zip/ui.rcc")
    args = parser.parse_args()
    print(json.dumps(run(args.data_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
