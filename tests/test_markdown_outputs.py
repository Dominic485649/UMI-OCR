"""Markdown、HTTP TXT 别名及真实批量配置一次性迁移的定向回归。"""
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
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    data, work = args.data.resolve(), args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    os.environ["QML_DISABLE_DISK_CACHE"] = "1"
    sys.path.insert(0, str(ROOT / "build/tools"))
    from staging_smoke import configure_runtime
    handles = configure_runtime(data)
    sys.path[:0] = [str(ROOT / "UmiOCR-data"), str(ROOT / "UmiOCR-data/py_src/imports")]
    os.chdir(work)
    from py_src.ocr.output import output_factories, ui_output_factories
    from py_src.ocr.output.output_md import OutputMD, OutputMDIndividual, OutputMDTxt, OutputMDTxtIndividual
    from PySide6.QtCore import QObject, QUrl, Slot, qInstallMessageHandler
    from PySide6.QtGui import QColor, QGuiApplication
    from PySide6.QtQml import QQmlEngine, QQmlComponent
    from PySide6.QtQuickControls2 import QQuickStyle

    passed = []
    options = {"outputDir": str(work), "outputDirType": "specify", "outputFileName": "result",
               "startDatetime": "2026-11-03 00:00:00", "ignoreBlank": False, "attemptPrefix": True}
    source = work / "输入 空格 [图].JXL"
    source.write_bytes(b"source-is-not-modified")
    result = {"code": 100, "path": str(source), "fileName": source.name,
              "data": [{"text": "普通识别文本"}], "markdown": "# 标题\n\n$x_1^2$\n\n```python\nprint(1)\n```"}
    for normal, compatible in ((OutputMD, OutputMDTxt), (OutputMDIndividual, OutputMDTxtIndividual)):
        writers = [normal(options), compatible(options)]
        for writer in writers:
            writer.print(result)
            writer.onEnd()
        paths = [Path(writer.getArtifacts()[0]["path"]) for writer in writers]
        assert paths[0].read_bytes() == paths[1].read_bytes(), paths
        assert str(paths[0]).endswith(".md") and str(paths[1]).endswith(".md.txt")
        text = paths[0].read_text("utf-8")
        assert result["markdown"] in text and "%20" in text
        assert source.read_bytes() == b"source-is-not-modified"
    assert [key for key, _ in output_factories(["txt", "txtPlain", "md", "txtIndividual", "mdIndividual"])] == ["md", "mdIndividual"]
    assert [key for key, _ in output_factories(["txt", "txtPlain", "md"], compatibility=True)] == ["txt", "md"]
    assert [key for key, _ in ui_output_factories({"mission.filesType.txt": True, "mission.filesType.md": True})] == ["md"]
    pdf_result = dict(result, path=str(work / "input.pdf"), fileName="page 1")
    from py_src.ocr.output.output_md import markdown_record
    assert "![" not in markdown_record(pdf_result, str(work / "document.md"))
    passed.append("共享 Markdown 内容、.md.txt 字节相同、别名去重、PDF 不伪装图片、源文件未修改")

    # 真实传统 HTTP 输出器，不只检查 registry。
    from py_src.server.doc_server import _DocUnit
    from PySide6.QtCore import QMutex
    legacy = work / "legacy-http"
    legacy.mkdir()
    original = legacy / "input.png"
    original.write_bytes(b"source")
    unit = object.__new__(_DocUnit)
    unit.is_done, unit.state, unit.msnID = True, "success", "test"
    unit.dir_path, unit.dir_id = str(legacy), "test"
    unit.origin_name, unit.origin_prefix = original.name, original.stem
    unit.origin_path, unit.password, unit.start_timestamp = str(original), "", 0
    unit._mutex = QMutex()
    unit.results = {0: dict(result, path=str(original), fileName="1")}
    downloads = unit.get_files("http://localhost", ["txt", "txtPlain", "md"])
    assert downloads["code"] == 100, downloads
    import zipfile
    with zipfile.ZipFile(legacy / downloads["name"]) as archive:
        assert sorted(archive.namelist()) == ["[OCR]_input.md", "[OCR]_input.md.txt"]
        assert archive.read("[OCR]_input.md") == archive.read("[OCR]_input.md.txt")
    passed.append("传统 /api/doc 输出真实 ZIP，仅一个 TXT 兼容文件且与 Markdown 相同")

    class Settings(QObject):
        def __init__(self):
            super().__init__()
            self.values, self.writes = {}, []
        @Slot(str, str, result=bool)
        def contains(self, category, key): return (category, key) in self.values
        @Slot(str, str, "QVariant", result="QVariant")
        def value(self, category, key, default): return self.values.get((category, key), default)
        @Slot(str, str, "QVariant")
        def setValue(self, category, key, value):
            value = value.toVariant() if hasattr(value, "toVariant") else value
            self.values[category, key] = value
            self.writes.append((category, key, value))
        @Slot()
        def sync(self): pass

    QQuickStyle.setStyle("Basic")
    app = QGuiApplication.instance() or QGuiApplication([])
    engine = QQmlEngine()
    engine.addImportPath(str(data / "site-packages/PySide6/qml"))
    settings = Settings()
    messages = []
    qInstallMessageHandler(lambda kind, context, text: messages.append(text))
    engine.rootContext().setContextProperty("UmiSettings", settings)
    engine.rootContext().setContextProperty("size_", {"scale": 1, "line": 20, "smallLine": 16, "largeLine": 24, "text": 14, "smallText": 12, "largeText": 18, "spacing": 8, "smallSpacing": 4, "btnRadius": 4, "panelRadius": 6, "baseRadius": 4})
    engine.rootContext().setContextProperty("theme", {**{key: QColor(value) for key, value in {"bgColor": "#ffffff", "textColor": "#111111", "subTextColor": "#555555", "coverColor1": "#11000000", "coverColor2": "#22000000", "coverColor3": "#33000000", "coverColor4": "#55000000"}.items()}, "fontFamily": "Microsoft YaHei", "dataFontFamily": "Microsoft YaHei"})
    qml = ROOT / "UmiOCR-data/qt_res/qml"
    for kind, category in (("BatchOCR", "BatchOCR"), ("BatchDOC", "BatchPDF")):
        for enabled in (True, False):
            settings.values = {(category, "mission.filesType.txt"): enabled,
                               (category, "mission.filesType.md"): False,
                               (category, "mission.filesType.txtIndividual"): enabled,
                               (category, "mission.filesType.csv"): True}
            settings.writes.clear()
            component = QQmlComponent(engine)
            component.setData(('''import QtQuick
import "TabPages/''' + kind + '''" as Batch
Item {
    id: qmlapp
    property bool enabledEffect: false
    property var pubSub: ({subscribeGroup: function(){}, unsubscribeGroup: function(){}})
    property var globalConfigs: ({ocrManager: {modelPanelLayout: function(){return []}, taskSource: function(){return null}},
        utilsDicts: {getTbpuParser: function(){return {}}, getPostTaskActions: function(){return {}}, getSimpleNotificationType: function(){return {default:"always"}}}})
    property alias config: config
    Batch.''' + kind + '''Configs { id: config; lazyPanel: true }
}''').encode(), QUrl.fromLocalFile(str(qml / "markdown-test.qml")))
            deadline = time.monotonic() + 10
            while component.isLoading():
                assert time.monotonic() < deadline
                app.processEvents()
            root = component.create()
            assert root is not None, component.errorString()
            app.processEvents()
            app.processEvents()
            engine.globalObject().setProperty("testRoot", engine.newQObject(root))
            def evaluate(code):
                value = engine.evaluate(code)
                assert not value.isError(), value.toString()
                return value
            schema = json.loads(evaluate("JSON.stringify(Object.keys(testRoot.config.originDict))").toString())
            assert not any(key in schema for key in ("mission.filesType.txt", "mission.filesType.txtPlain", "mission.filesType.txtIndividual"))
            assert evaluate('testRoot.config.getValue("mission.filesType.md")').toBool() == enabled, (kind, enabled, settings.values, settings.writes, evaluate('JSON.stringify(testRoot.config.configDict)').toString(), messages)
            if kind == "BatchOCR":
                assert evaluate('testRoot.config.getValue("mission.filesType.mdIndividual")').toBool() == enabled
            assert evaluate('testRoot.config.getValue("mission.filesType.csv")').toBool()
            # 用户后来取消 MD，旧 TXT=true 也不能再次开启它。
            evaluate('testRoot.config.setValue("mission.filesType.md", false, true); testRoot.config.flushCache(); testRoot.config.settingsReload()')
            assert not evaluate('testRoot.config.getValue("mission.filesType.md")').toBool()
            assert settings.values[category, "mission.markdownFormatVersion"] == 1
            root.deleteLater()
            app.processEvents()
    assert not app.allWindows()
    passed.append("真实 BatchOCR／BatchDOC 配置无 TXT，旧 true/false 正确迁移，用户取消后不再重启 MD，其他格式保留")
    (work / "result.json").write_text(json.dumps({"status": "PASS", "source": str(ROOT / "UmiOCR-data"),
        "runtime": str(data), "checks": passed}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "PASS", "checks": passed}, ensure_ascii=False))


if __name__ == "__main__":
    main()
