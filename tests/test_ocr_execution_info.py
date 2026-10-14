"""Run with portable Python: test_ocr_execution_info.py <packaged UmiOCR-data>."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build/tools"))
from staging_smoke import configure_runtime


def main():
    data_root = Path(sys.argv[1]).resolve()
    handles = configure_runtime(data_root)
    os.environ["QT_QPA_PLATFORM"] = "windows"
    sys.path[:0] = [str(ROOT / "UmiOCR-data"), str(ROOT / "UmiOCR-data/plugins"),
                    str(ROOT.parent / "Umi-OCR-Plugin")]
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QGuiApplication, QColor
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuickControls2 import QQuickStyle
    from py_src.plugins_controller.services import PluginServices
    from py_src.plugins_controller.plugins_connector import PluginsConnector
    from py_src.mission.mission_ocr import MissionOCR
    from win32_PaddleOCRv6_CPU.api import Api as CpuApi
    from win32_PaddleOCRv6_CUDA.api import Api as GpuApi

    QQuickStyle.setStyle("Basic")
    app = QGuiApplication([])
    engine = QQmlEngine()
    engine.addImportPath(str(data_root / "site-packages/PySide6/qml"))
    calls = []
    class Service:
        def configure(self, args):
            assert isinstance(args, dict) and args["nested"] == {"items": [1, True]}
            calls.append("configure")
            return {"ok": True}
        def health(self, args):
            calls.append("health")
            return {"ok": True, "details": args}
        prestart = health
        maintain = health
    PluginServices.register("qt-test", "model", lambda: Service())
    connector = PluginsConnector()
    engine.globalObject().setProperty("connector", engine.newQObject(connector))
    for method in ("runServiceHealth", "prestartService", "maintainService"):
        result = engine.evaluate(f'connector.{method}("qt-test", "model", {{nested: {{items: [1, true]}}}})')
        assert not result.isError(), result.toString()
        assert result.toVariant() == {"ok": True, "details": {"nested": {"items": [1, True]}}}
    assert calls == ["configure", "health"] * 3
    assert not PluginServices.call("qt-test", "model", "health", engine.evaluate("[]"))["ok"]

    mission = type(MissionOCR)()
    cpu = CpuApi({})
    cpu._config = {"running": True}
    cpu._worker.process = Mock()
    cpu._worker.process.poll.return_value = None
    cpu._worker.request = Mock(return_value={"ok": True, "result": {"code": 101, "data": ""}})
    mission._apiKey, mission._api = "win32_PaddleOCRv6_CPU", cpu
    cpu_result = mission.msnTask({"tbpu": []}, {"bytes": b"image"})
    assert cpu_result["execution"]["device"] == "CPU"
    assert cpu_result["execution"]["model"] == "PP-OCRv6 medium"
    assert "win32_PaddleOCRVL_1_6.runtime" not in sys.modules
    gpu = GpuApi({"device": "gpu:1"})
    gpu._config = {"device": "gpu:1", "detModel": "PP-OCRv6_medium", "recModel": "PP-OCRv6_medium"}
    gpu._worker.request = Mock(return_value={"ok": True, "result": {"code": 101, "data": ""}})
    mission._apiKey, mission._api = "win32_PaddleOCRv6_CUDA", gpu
    gpu_result = mission.msnTask({"tbpu": []}, {"path": "test.png"})
    assert gpu_result["execution"]["device"] == "GPU:1"
    assert cpu_result["execution"]["device"] == "CPU"  # Earlier record stays immutable.

    from win32_PaddleOCRVL_1_6.runtime import RuntimeService
    with tempfile.TemporaryDirectory() as raw:
        runtime = RuntimeService()
        runtime._process = Mock()
        runtime._process.poll.return_value = None
        runtime._command = ["llama-server", "-m", "test.gguf"]
        runtime._logPath = Path(raw) / "server.log"
        for layers, vision, device in (("29/29", "CUDA0", "GPU"), ("0/29", "CPU", "CPU"),
                                       ("12/29", "CUDA0", "GPU+CPU"), ("29/29", "CPU", "GPU+CPU")):
            runtime._logPath.write_text(f"load_tensors: offloaded {layers} layers to GPU\nclip: using {vision} backend", encoding="utf-8")
            info = runtime.get_execution_info()
            assert info["device"] == device, info
            assert info["model"] == "Paddlevl1.6" and "modelFile" not in info
        runtime._external = True
        assert runtime.get_execution_info()["device"] == "设备未确认"
        runtime._process = None  # Mock must not be shut down as an owned process.

    context = engine.rootContext()
    context.setContextProperty("theme", {**{k: QColor("#333333") for k in (
        "bgColor", "coverColor1", "coverColor4", "subTextColor", "textColor", "specialTextColor",
        "specialBgColor", "noColor", "yesColor")}, "fontFamily": "Arial", "dataFontFamily": "Arial"})
    context.setContextProperty("size_", {"line": 24, "smallLine": 16, "text": 14, "smallText": 12,
        "spacing": 8, "smallSpacing": 4, "baseRadius": 4, "btnRadius": 4, "panelRadius": 4})
    context.setContextProperty("qmlapp", {"enabledEffect": False})
    component = QQmlComponent(engine)
    url = (ROOT / "UmiOCR-data/qt_res/qml/Widgets/ResultLayout").as_uri()
    if (data_root / "ui.rcc").is_file():
        url = "qrc:/qt_res/qml/Widgets/ResultLayout"
    component.setData(f'import QtQuick\nimport "{url}" as R\nR.ResultsTableView {{ width: 500; height: 500; autoToBottom: false }}'.encode(), QUrl("inline:records-test.qml"))
    while component.isLoading():
        app.processEvents()
    obj = component.create()
    assert obj is not None, component.errorString()
    engine.globalObject().setProperty("records", engine.newQObject(obj))
    cpu_result.update(time=0.25, timestamp=1, score=None)
    result = engine.evaluate(f'records.addOcrResult({json.dumps(cpu_result, ensure_ascii=False)}); records.getResult("", 1).title')
    assert not result.isError(), result.toString()
    assert "耗时 0.25 | CPU · PP-OCRv6 medium" == result.toString()
    vl_result = {"code": 101, "data": "", "time": 1.5, "timestamp": 2,
                 "execution": {"device": "GPU", "model": "Paddlevl1.6", "modelFile": "test-Q4.gguf"}}
    title = engine.evaluate(f'records.addOcrResult({json.dumps(vl_result)}); records.getResult("", 2).title')
    assert "GPU · Paddlevl1.6" in title.toString() and "gguf" not in title.toString(), title.toString()
    print("Qt service arguments, CPU routing, execution snapshots, VL devices and QML records passed.")
    obj.deleteLater()
    app.processEvents()
    PluginServices.reset()
    del handles


if __name__ == "__main__":
    main()
