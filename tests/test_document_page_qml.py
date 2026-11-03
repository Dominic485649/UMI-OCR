"""文档解析页与逐页回调的定向源码回归：内存设置，不创建窗口或模型。"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run(runtime, plugin, output):
    helper = load("document_page_source_helpers", ROOT / "tests/test_ignore_area_qml.py")
    handles = helper.configure_source_runtime(runtime, ROOT / "UmiOCR-data")
    sys.path.insert(0, str(plugin.parent))
    os.environ["QML_DISABLE_DISK_CACHE"] = "1"
    from PySide6.QtCore import QCoreApplication, QEvent, QObject, Property, QUrl, Signal, Slot, QtMsgType, qInstallMessageHandler
    from PySide6.QtGui import QColor, QGuiApplication
    from PySide6.QtQml import QQmlComponent, QQmlEngine, qmlRegisterType
    from PySide6.QtQuickControls2 import QQuickStyle

    from py_src.document.markdown_preview import initialize_preview, MarkdownPreviewConnector
    initialize_preview()
    qmlRegisterType(MarkdownPreviewConnector, "MarkdownPreviewConnector", 1, 0, "MarkdownPreviewConnector")
    QQuickStyle.setStyle("Basic")
    app = QGuiApplication(["document-page-contracts"])
    engine = QQmlEngine()
    engine.addImportPath(str(runtime / "site-packages/PySide6/qml"))
    messages, roots, components, checks = [], [], [], []
    old_handler = qInstallMessageHandler(lambda kind, _context, text: messages.append((kind, text)))

    def checkpoint():
        app.processEvents()
        assert not app.allWindows(), "定向逻辑回归不能创建窗口"
        errors = [text for kind, text in messages if kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)]
        assert not errors, errors[:15]

    def plain(value):
        return value.toVariant() if hasattr(value, "toVariant") else value

    class Settings(QObject):
        def __init__(self):
            super().__init__()
            self.values = {}
        @Slot(str, str, result=bool)
        def contains(self, category, key): return (category, key) in self.values
        @Slot(str, str, "QVariant", result="QVariant")
        def value(self, category, key, default): return self.values.get((category, key), plain(default))
        @Slot(str, str, "QVariant")
        def setValue(self, category, key, value): self.values[category, key] = plain(value)
        @Slot()
        def sync(self): pass

    class Bus(QObject):
        @Slot(str, "QVariant", str, str)
        def subscribeGroup(self, *_args): pass
        @Slot(str)
        def unsubscribeGroup(self, *_args): pass

    class Popup(QObject):
        @Slot(str, str, str)
        def message(self, *_args): pass
        @Slot(str, str)
        def simple(self, *_args): pass

    class DocumentManager(QObject):
        @Slot("QVariant", str, result="QVariant")
        def deploy(self, *_args):
            return {"title": "文档解析设置", "type": "group", "output": {"title": "输出", "default": 4096}}

    class Connector(QObject):
        admission_error = False
        @Slot(str, str, "QVariant", result="QVariant")
        def callPy(self, _key, name, _args):
            if name == "parseDocuments": return "[Error] controlled rejection" if self.admission_error else "mission-1"
            return {"ok": True}

    class Preview(QObject):
        previewInfo = Signal("QVariant")
        previewImg = Signal(str)
        instances = []
        def __init__(self, *args):
            super().__init__(*args)
            self.requests = []
            self.instances.append(self)
        @Slot(str, int, str)
        def preview(self, *args): self.requests.append(args)
        @Slot()
        def clear(self): pass

    qmlRegisterType(Preview, "DocPreviewConnector", 1, 0, "DocPreviewConnector")
    settings, bus, popup, document_manager, connector = Settings(), Bus(), Popup(), DocumentManager(), Connector()

    class App(QObject):
        @Property(QObject, constant=True)
        def globalConfigs(self): return self.shared
        @Property(QObject, constant=True)
        def pubSub(self): return bus
        @Property(QObject, constant=True)
        def popup(self): return popup
        @Property(bool, constant=True)
        def enabledEffect(self): return False

    stub = App()
    stub.shared = None
    context = engine.rootContext()
    context.setContextProperty("qmlapp", stub)
    context.setContextProperty("UmiSettings", settings)
    theme_values = {**{key: QColor(value) for key, value in {
        "bgColor": "#ffffff", "textColor": "#111111", "subTextColor": "#555555", "noColor": "#bb3322",
        "yesColor": "#228844", "specialBgColor": "#eeeeee", "specialTextColor": "#1166cc",
        "coverColor1": "#11000000", "coverColor2": "#22000000", "coverColor3": "#33000000", "coverColor4": "#55000000",
    }.items()}, "fontFamily": "Microsoft YaHei", "dataFontFamily": "Microsoft YaHei"}
    context.setContextProperty("theme", theme_values)
    context.setContextProperty("baseTheme", theme_values)
    qml = ROOT / "UmiOCR-data/qt_res/qml"

    def create(component, properties=None):
        components.append(component)
        deadline = time.monotonic() + 8
        while component.isLoading():
            assert time.monotonic() < deadline
            app.processEvents()
        assert component.isReady(), component.errorString()
        item = component.createWithInitialProperties(properties or {})
        assert item is not None, component.errorString()
        roots.append(item)
        return item

    def evaluate(code):
        value = engine.evaluate(code)
        assert not value.isError(), value.toString() + "\n" + value.property("stack").toString()
        return value

    try:
        size = create(QQmlComponent(engine, QUrl.fromLocalFile(str(qml / "MainWindow/Size_.qml"))))
        context.setContextProperty("size_", size)
        assert size.property("scale") == 1.25
        engine.globalObject().setProperty("size_", engine.newQObject(size))
        extract = load("document_page_function_extractor", ROOT / "tests/test_optional_backend_configs.py")
        scale_component = QQmlComponent(engine)
        scale_component.setData(('import QtQuick 2.15\nimport "' + QUrl.fromLocalFile(str(qml / "Configs")).toString() + '"\nConfigs { lazyPanel:true; '
            + 'property var theme: Object.assign({},baseTheme,{manager:{getOptionsList:function(){return []},followSystemKey:"system"}})\n'
            + 'property var utilsDicts: ({getSimpleNotificationType:function(){return {}}})\n'
            + 'property var globalConfigConn: ({open_logs_dir:function(){}})\n'
            + 'function _getI18n(){return {}}\nfunction openFontPanel(){}\n'
            + 'configDict: ({ui:{type:"group",scale:makeConfigDict().ui.scale}})\n'
            + extract.qml_function(qml / "Configs/GlobalConfigs.qml", "makeConfigDict") + '\n}').encode(), QUrl.fromLocalFile(str(qml / "default-scale-contract.qml")))
        fresh = create(scale_component, {"category_": "NewScale"})
        engine.globalObject().setProperty("fresh", engine.newQObject(fresh))
        checkpoint()
        assert evaluate('fresh.getValue("ui.scale")').toNumber() == 1.25
        settings.values["SavedScale", "ui.scale"] = 0.9
        saved = create(scale_component, {"category_": "SavedScale"})
        engine.globalObject().setProperty("saved", engine.newQObject(saved))
        assert evaluate('saved.getValue("ui.scale")').toNumber() == 0.9
        assert settings.values["SavedScale", "ui.scale"] == 0.9
        size.setProperty("scale", 1.25)
        assert 'messageMemory("globalConfigsKey"' not in (qml / "TabPages/GlobalConfigsPage/GlobalConfigsPage.qml").read_text(encoding="utf-8")
        checks.append("125%初始和缺失键默认生效，已有90%原值保留，小贴士自动调用已移除")

        shared_component = QQmlComponent(engine)
        shared_component.setData(('import QtQuick 2.15\nimport "' + QUrl.fromLocalFile(str(qml / "Configs")).toString() + '"\nConfigs { lazyPanel:true; property var documentManager: null }').encode(), QUrl.fromLocalFile(str(qml / "document-page-global-test.qml")))
        stub.shared = create(shared_component, {"category_": "Global", "documentManager": document_manager,
            "configDict": {"window": {"type": "group", "doubleLayout": {"type": "var", "default": {}}}}})
        component = QQmlComponent(engine)
        source = plugin / "StructuredDocument.qml"
        # 内容来自插件源码；虚拟基址只令相对 imports 指向宿主源码，不冒称包内运行。
        component.setData(source.read_bytes(), QUrl.fromLocalFile(str(ROOT / "UmiOCR-data/plugins" / plugin.name / "StructuredDocument.qml")))
        page = create(component, {"connector": connector, "ctrlKey": "test-page", "width": 1280, "height": 800})
        engine.globalObject().setProperty("page", engine.newQObject(page))
        preview = Preview.instances[-1]
        evaluate('page.addPaths(["A.pdf","B.pdf"])')
        preview.previewInfo.emit({"path": "A.pdf", "page": 1, "pageCount": 3, "error": ""})
        checkpoint()
        assert evaluate('page.pageCount').toInt() == 3
        evaluate('page.setCurrentPage(3)')
        assert preview.requests[-1] == ("A.pdf", 3, "")
        assert not evaluate('page.parsing').toBool()
        preview.previewInfo.emit({"path": "B.pdf", "page": 1, "pageCount": 999, "error": ""})
        preview.previewInfo.emit({"path": "A.pdf", "page": 1, "pageCount": 888, "error": ""})
        assert evaluate('page.pageCount').toInt() == 3
        checks.append("无需解析即可用实际页数跳到第3页，旧文档/旧页元信息不能覆盖当前状态")

        evaluate('page.startParse(); page.selectDocument("B.pdf")')
        assert evaluate('page.currentPath').toString() == "B.pdf"
        record = {"page": 2, "text": "第二页", "markdown": "# 第二页", "blocks": [{"id": "b2", "globalId": "g2", "content": "第二页块", "bbox": [[0,0],[20,0],[20,20],[0,20]]}]}
        event = {"path": "A.pdf", "page": 2, "completedPages": 1, "totalPages": 3,
            "result": {"code": 100, "data": {"pages": [record], "assets": []}}}
        evaluate('page.onMissionPartial("mission-old",' + json.dumps(event, ensure_ascii=False) + ')')
        assert evaluate('Object.keys(page.documentResults).length').toInt() == 0
        page.onMissionPartial("mission-1", event)
        assert evaluate('page.currentPath').toString() == "B.pdf"
        evaluate('page.selectDocument("A.pdf")')
        preview.previewInfo.emit({"path": "A.pdf", "page": 1, "pageCount": 3, "error": ""})
        evaluate('page.setCurrentPage(2)')
        assert evaluate('page.resultText(0)').toString() == "# 第二页"
        assert json.loads(evaluate('page.resultText(2)').toString())["page"] == 2
        assert evaluate('page.resultBlocks[0].content').toString() == "第二页块"
        assert evaluate('page.structuredResult.partial').toBool()
        checks.append("逐页回调在整篇完成前可查看文本/JSON/结构块，不抢占另一文档，不接受旧任务结果")

        evaluate('page.cancelParse(); page.onMissionEnd("mission-1","[Warning] cancelled")')
        assert not evaluate('page.parsing').toBool()
        assert evaluate('page.resultText(0)').toString() == "# 第二页"
        assert evaluate('page.documentStates["A.pdf"]').toString() == "partial"
        evaluate('page.onMissionPartial("mission-1",' + json.dumps({**event, "page": 3}, ensure_ascii=False) + ')')
        assert evaluate('page.documentResults["A.pdf"].data.pages.length').toInt() == 1
        checks.append("取消后保留已完成页，任务结束后的迟到回调不能写入")

        evaluate('page.startParse(); page.setCurrentPage(3)')
        final = {"code": 100, "text": "最终整篇", "markdown": "# 最终", "data": {"pages": [{**record, "text": "最终第二页"}], "assets": []}, "metadata": {"pageCount": 1}}
        page.onMissionGet("mission-1", "A.pdf", final)
        assert evaluate('page.currentPage').toInt() == 3
        assert evaluate('page.pageCount').toInt() == 3
        evaluate('page.wholeDocument=true')
        assert evaluate('page.resultText(0)').toString() == "# 最终"
        evaluate('page.selectBlock(page.resultBlocks[0])')
        assert evaluate('page.currentPage').toInt() == 2
        assert evaluate('page.selectedBlockKey').toString() == "2:g2"
        evaluate('page.onMissionEnd("mission-1","[Success]")')
        connector.admission_error = True
        evaluate('page.startParse()')
        assert not evaluate('page.parsing').toBool()
        assert evaluate('page.structuredResult.text').toString() == "最终整篇"
        evaluate('page.configsComp.setValue("document.output",777,true); page.resetPage()')
        assert evaluate('page.configsComp.getValue("document.output")').toInt() == 777
        assert evaluate('page.runPaths.length + page.finishedPaths.length + page.pageProgress').toNumber() == 0
        checkpoint()
        checks.append("最终重组结果替换临时结果但不改源页数/浏览页，整篇结构块跳转对应页面，清空不重置参数")

        geometry = {"geometry.pdf": {"code": 100, "data": {"pages": [{"page": 1, "width": 1200, "height": 800,
            "blocks": [{"id": "geometry", "bbox": [[100, 80], [500, 80], [500, 240], [100, 240]]}]}]}}}
        evaluate('page.addPaths(["geometry.pdf"]); page.documentResults=' + json.dumps(geometry))
        preview_item = page.findChild(QObject, "structuredPagePreview")
        engine.globalObject().setProperty("testedPreview", engine.newQObject(preview_item))
        evaluate('testedPreview.imageSW=600; testedPreview.imageSH=400; page.previewLoading=false')
        checkpoint()
        def regions(item):
            yield item
            for child in item.childItems(): yield from regions(child)
        overlay = preview_item.property("overlayLayer")
        region = next(item for item in regions(overlay) if item.objectName() == "documentRegion:1:geometry")
        assert [region.property(key) for key in ("x", "y", "width", "height")] == [50, 40, 200, 80]
        evaluate('testedPreview.scale=1.75')
        assert [region.property(key) for key in ("x", "y", "width", "height")] == [50, 40, 200, 80], "视图缩放不能再乘到源几何上"
        evaluate('testedPreview.imageSW=900; testedPreview.imageSH=600')
        checkpoint()
        assert [region.property(key) for key in ("x", "y", "width", "height")] == [75, 60, 300, 120]
        checks.append("真实版面委托按推理页到预览像素转换，视图缩放不重复计算，异步尺寸变化重映射")

        cases = helper.test_preview_connector_races(app, ROOT / "UmiOCR-data")
        checkpoint()
        checks.append("真实SimpleMission/CallFunc元信息与图片竞争回归通过，页数可早于渲染交付")
        report = {"status": "PASS", "checks": checks, "preview_race_cases": cases, "qwindow_count": 0,
            "settings": "memory-only", "model_inference": "NOT_RUN", "source_sha256": {
                str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (source, ROOT / "UmiOCR-data/py_src/mission/doc_preview_connector.py", Path(__file__))}}
        with output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        for item in reversed(roots): item.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        qInstallMessageHandler(old_handler)
        del handles


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime", type=Path)
    parser.add_argument("--plugin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.runtime.resolve(), args.plugin.resolve(), args.output.resolve())
    except Exception:
        import traceback
        if not args.output.exists():
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump({"status": "FAIL", "traceback": traceback.format_exc(),
                    "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
        raise
