"""3.1.2 包内定向验收：只读既有模型、真实 GUI 待切换与 HTTP 图片矩阵。"""
from __future__ import annotations
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import socket
import sys
import threading
import time
import traceback
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import model_settings_http_acceptance as helpers


def digest(path):
    with Path(path).open("rb") as stream: return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream: json.dump(value, stream, ensure_ascii=False, indent=2)


def prepare_models(output):
    files = [Path("D:/AI/models/PaddleOCR-VL-1.6-GGUF") / name for name in ("PaddleOCR-VL-1.6-GGUF.gguf", "PaddleOCR-VL-1.6-GGUF-mmproj.gguf")]
    files += [Path("D:/AI/models/PP-DocLayoutV3") / name for name in ("inference.json", "inference.pdiparams")]
    values = {str(helpers.safe_path(path)): digest(path) for path in files}
    write(output, {"sha256": values, "readOnly": True, "downloaded": False, "quantizationChanged": False})
    print(json.dumps({"status": "PASS", "readOnlyModelFiles": len(values), "output": str(output)}, ensure_ascii=False))


def imports(data):
    from staging_smoke import configure_runtime
    handles = configure_runtime(data)
    return handles


def matrix(args, models, work, audit):
    data = args.root / "UmiOCR-data"
    handles = imports(data)
    os.chdir(work)
    from PySide6.QtCore import QThreadPool
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication([])
    from plugin_i18n import setLangCode
    setLangCode("zh_CN")
    from py_src.plugins_controller import plugins_controller
    plugins_controller.PLUGINS_PATH = str(data / "plugins")
    summary = plugins_controller.PluginsController.init()
    from py_src.plugins_controller.capabilities import CAPABILITY_TYPES
    from py_src.plugins_controller.services import PluginServices
    from py_src.mission.backend_runtime import BackendRuntime
    cuda, vl, port, configurations, bindings = helpers.configure_backends(BackendRuntime,
        {key: CAPABILITY_TYPES[key] for key in ("ocr", "document")}, PluginServices, models, args.root)
    from py_src.mission.mission_ocr import MissionOCR
    from py_src.mission.mission_document import MissionDocument
    helpers.require(MissionOCR.setApi(cuda, configurations["ocr", cuda]).startswith("[Success]"), "CUDA configuration failed")
    helpers.require(MissionDocument.setApi(vl, configurations["document", vl]).startswith("[Success]"), "VL configuration failed")
    from py_src.mission.doc_preview_connector import DocPreviewConnector
    from py_src.image_controller.image_provider import PixmapProvider
    from py_src.utils.call_func import CallFunc
    preview, preview_result = DocPreviewConnector(), {}
    def preview_delivered(identifier):
        if identifier.startswith("["):
            preview_result["error"] = identifier
        else:
            pixmap = PixmapProvider.getPixmap(identifier)
            preview_result.update(size=[pixmap.width(), pixmap.height()], identifier=identifier)
    preview.previewImg.connect(preview_delivered)
    def request_preview(path, page):
        preview_result.clear()
        preview.preview(str(path), page, "")
    from py_src.server import web_server, structured_document_server as structured
    from wsgiref.simple_server import make_server
    server = make_server("127.0.0.1", 0, web_server.UmiWeb, server_class=web_server._WSGIRefServer.CustomWSGIServer)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.1), daemon=True)
    thread.start()
    deadline = time.monotonic() + args.deadline
    client = helpers.HttpClient(server.server_port, deadline, audit)
    fixtures = json.loads(args.fixtures.read_text("utf-8"))
    helpers.require(fixtures.get("passed") is True, "Input decoder/preview fixtures did not pass")
    outcome, completed = {}, threading.Event()
    report = {"mode": "matrix", "realSocket": True, "realModels": True, "fakeModelResponses": False,
              "bindings": bindings, "models": models, "plugins": summary, "cases": []}
    def run():
        try:
            cases = list(fixtures["formats"])
            # TIFF 选页保留原页号、EXIF 输入保留方向转换后的尺寸。
            fixture_root = Path(cases[0]["source"]).parent
            cases += [{"source": str(fixture_root / "方向.JPG"), "suffix": ".JPG", "previewSize": [280, 600], "geometryOnly": True},
                      {"source": str(fixture_root / "多页.tiff"), "suffix": ".tiff", "previewSize": [80, 50], "pageRange": [2, 2], "geometryOnly": True}]
            for index, case in enumerate(cases):
                path = Path(case["source"])
                before = digest(path)
                helpers.require(before == case.get("sourceSha256", before), "Fixture changed")
                CallFunc.sync(request_preview, path, case.get("pageRange", [1])[0])
                actual_preview = helpers.wait_for(lambda: dict(preview_result) or None, deadline, "packaged preview " + path.name)
                helpers.require(actual_preview.get("size") == case["previewSize"], str(actual_preview))
                CallFunc.sync(PixmapProvider.delPixmap, actual_preview["identifier"])
                parameters = {"backendId": "current", "taskTimeoutSeconds": 300, "options": {"maxOutputTokens": 4096}}
                if case.get("pageRange"): parameters["pageRange"] = case["pageRange"]
                submitted = client.upload("/api/document/upload", path.read_bytes(), parameters, filename=path.stem + case["suffix"].upper())
                helpers.require(submitted.get("code") == 100, str(submitted))
                identifier = submitted["jobId"]
                def finished():
                    value = client.json("/api/document/result", data={"jobId": identifier})
                    return value if value.get("state") in structured.TERMINAL else None
                result = helpers.wait_for(finished, deadline, "document " + path.name)
                write(audit / (f"case-{index:02d}.json"), result)
                helpers.require(result["state"] == "succeeded", str(result)[:1800])
                parsed = result["result"]
                helpers.require((parsed.get("metadata") or {}).get("sourceStem") == path.stem, "Original upload filename identity was lost")
                pages = parsed["data"]["pages"]
                helpers.require(len(pages) == 1 and [pages[0]["width"], pages[0]["height"]] == case["previewSize"], "Result/preview dimensions differ")
                if case.get("pageRange"): helpers.require(pages[0]["page"] == 2, "TIFF page number was renumbered")
                from win32_PaddleOCRVL_1_6.runtime import getService
                execution = getService().get_execution_info()
                helpers.assert_gpu_result({"execution": execution})
                if not case.get("geometryOnly"):
                    helpers.require("12345" in helpers.text_from(parsed).replace(" ", ""), "Expected synthetic text was not recognized")
                downloads = {}
                for kind in ("md", "txt", "json", "zip"):
                    status, payload, headers = client.call("/api/document/download", data={"jobId": identifier, "format": kind})
                    helpers.require(status == 200 and "attachment" in headers.get("Content-Disposition", ""), "Download failed")
                    downloads[kind] = payload
                    if kind == "txt": helpers.require("document.md.txt" in headers["Content-Disposition"] and headers["Content-Type"].startswith("text/plain"), "TXT compatibility metadata differs")
                helpers.require(downloads["md"] == downloads["txt"], "TXT and Markdown bytes differ")
                with zipfile.ZipFile(io.BytesIO(downloads["zip"])) as archive:
                    helpers.require({"document.md", "document.json"} <= set(archive.namelist()) and "document.txt" not in archive.namelist(), "Default ZIP has wrong format set")
                    helpers.require(b"file://" not in archive.read("document.json"), "Export exposes local asset URIs")
                helpers.require(digest(path) == before, "Input was modified")
                report["cases"].append({"suffix": case["suffix"], "source": str(path), "sha256": before,
                    "state": result["state"], "page": pages[0]["page"], "size": case["previewSize"],
                    "packagedPreviewSize": actual_preview["size"], "markdownBytes": len(downloads["md"]),
                    "sourceStem": (parsed.get("metadata") or {}).get("sourceStem"), "sameTxtBytes": True, "execution": execution})
                print("HTTP " + case["suffix"] + " PASS", flush=True)
            submitted = client.upload("/api/document/upload", b"not-an-image", {"backendId": "current"}, filename="损坏.JXL")
            identifier = submitted["jobId"]
            def rejected():
                value = client.json("/api/document/result", data={"jobId": identifier})
                return value if value.get("state") in structured.TERMINAL else None
            bad = helpers.wait_for(rejected, deadline, "corrupt input rejection")
            helpers.require(bad["state"] == "failed", "Corrupt input looked like an empty successful page")
            report["corruptInputRejected"] = bad
            report["provenance"] = helpers.module_provenance(args.root, (cuda, vl))
            helpers.require(helpers.trusted_model_inputs(args.models)["verified"] == models["verified"], "Models changed")
            outcome["passed"] = True
        except BaseException: outcome["error"] = traceback.format_exc()
        finally: completed.set()
    orchestration = threading.Thread(target=run, daemon=True)
    orchestration.start()
    try:
        while not completed.wait(0.01):
            app.processEvents()
            helpers.require(time.monotonic() < deadline, "Matrix deadline exceeded")
    finally:
        preview.clear()
        for job in tuple(structured.JOBS.values()):
            if job.state not in structured.TERMINAL: job.cancel()
        end = time.monotonic() + 30
        while BackendRuntime.busy() and time.monotonic() < end: app.processEvents(); time.sleep(0.01)
        if not BackendRuntime.busy():
            MissionOCR.shutdown(); MissionDocument.shutdown(); BackendRuntime.reset(); PluginServices.shutdownAll()
        else: outcome["cleanupError"] = "Tasks did not drain; no unrelated process was terminated"
        server.shutdown(); server.close_all_request(); server.server_close(); thread.join(3)
        QThreadPool.globalInstance().waitForDone(3000)
    report.update(outcome)
    report["status"] = "PASS" if outcome.get("passed") and not outcome.get("cleanupError") else "FAIL"
    write(audit / "result.json", report)
    return report["status"] == "PASS"


def gui(args, models, work, audit):
    data = args.root / "UmiOCR-data"
    namespace = runpy.run_path(str(data / "main.py"), run_name="umi_acceptance_runtime")
    namespace["initRuntimeEnvironment"]()
    from PySide6 import QtQml
    from PySide6.QtCore import QSettings, QTimer, QCoreApplication
    from PySide6.QtQml import QQmlExpression, QQmlEngine
    cuda, vl = "win32_PaddleOCRv6_CUDA", "win32_PaddleOCRVL_1_6"
    with socket.socket() as listener: listener.bind(("127.0.0.1", 0)); port = listener.getsockname()[1]
    settings = QSettings(str(data / ".settings"), QSettings.Format.IniFormat)
    helpers.require(not settings.allKeys(), "GUI acceptance requires a fresh installation, not user settings")
    prefix = "pluginServices." + vl + ".paddlevl."
    values = {"ocr.api": cuda, "document.api": vl, "ocr.lifecycle.warmupMode": "lazy", "server.enable": False,
        prefix + "service.mainModel": models["model"], prefix + "service.mmprojModel": models["projector"],
        prefix + "service.port": port, prefix + "resources.contextLength": 8192, prefix + "resources.slots": 1,
        prefix + "resources.maxOutputTokens": 4096, "document." + vl + ".pipeline.layoutModelDir": models["layout"]}
    for key, value in values.items(): settings.setValue("Global/" + key, value)
    settings.sync()
    fixtures = json.loads(args.fixtures.read_text("utf-8"))
    image = next(case["source"] for case in fixtures["formats"] if case["suffix"] == ".png")
    records, results, ends, notices, changes = [], {}, {}, [], []
    state = {"phase": "initializing", "deadline": time.monotonic() + args.deadline}
    original_engine = QtQml.QQmlApplicationEngine
    class ObservedEngine(original_engine):
        def load(self, *arguments):
            super().load(*arguments)
            if not self.rootObjects(): return
            window = self.rootObjects()[0]
            from py_src.mission.mission_ocr import MissionOCR
            from py_src.mission.mission_document import MissionDocument
            from py_src.mission.backend_runtime import BackendRuntime
            from py_src.utils.call_func import CallFunc
            original_document = MissionDocument.setApi
            def document_apply(*args, **kwargs):
                changes.append({"time": time.monotonic(), "api": args[0] if args else ""})
                return original_document(*args, **kwargs)
            MissionDocument.setApi = document_apply
            def evaluate(code):
                expression = QQmlExpression(QQmlEngine.contextForObject(window), window, code)
                value = expression.evaluate()
                if expression.hasError(): raise RuntimeError(expression.error().toString())
                if isinstance(value, tuple): value = value[0]
                return value.toVariant() if hasattr(value, "toVariant") else value
            def select(target, label):
                try:
                    before = MissionOCR._apiKey
                    evaluate("qmlapp.globalConfigs.setValue('ocr.api'," + json.dumps(target) + ",true)")
                    records.append({"event": "selected-while-running", "task": label, "activeBefore": before,
                        "activeAfter": MissionOCR._apiKey, "desired": evaluate("qmlapp.globalConfigs.getValue('ocr.api')"),
                        "pending": evaluate("qmlapp.globalConfigs.backendApplyPending"), "busy": BackendRuntime.configuration_busy(),
                        "message": evaluate("qmlapp.globalConfigs.backendSwitchMessage()")})
                    helpers.require(MissionOCR._apiKey == before and before != target, "Selection changed the active task backend")
                except BaseException:
                    state["error"] = traceback.format_exc(); QCoreApplication.instance().quit()
            def submit(label, next_target):
                info = {"argd": {"ocr.taskType": "batch"},
                    "onStart": lambda _info: CallFunc.now(select, next_target, label),
                    "onGet": lambda _info, _item, value: results.update({label: value}),
                    "onEnd": lambda _info, message: ends.update({label: message})}
                identifier = MissionOCR.addMissionList(info, [{"path": image}])
                helpers.require(identifier and not identifier.startswith("["), str(identifier))
            def tick():
                try:
                    helpers.require(time.monotonic() < state["deadline"], "GUI model switch deadline")
                    error = evaluate("qmlapp.globalConfigs.backendApplyError")
                    helpers.require(not error, "Backend apply error: " + str(error))
                    idle = not BackendRuntime.configuration_busy() and not evaluate("qmlapp.globalConfigs.backendApplyPending") and evaluate("qmlapp.globalConfigs.applyPhase") == 0
                    if state["phase"] == "initializing" and idle and MissionOCR._apiKey == cuda and MissionDocument._apiKey == vl:
                        state["documentBaseline"] = len(changes)
                        state["phase"] = "cuda-running"; submit("cuda", vl)
                    elif state["phase"] == "cuda-running" and "cuda" in ends and idle and MissionOCR._apiKey == vl:
                        helpers.require(ends["cuda"].startswith("[Success]") and results["cuda"].get("code") == 100, str(ends))
                        helpers.assert_gpu_result(results["cuda"])
                        state["phase"] = "vl-running"; submit("vl", cuda)
                    elif state["phase"] == "vl-running" and "vl" in ends and idle and MissionOCR._apiKey == cuda:
                        helpers.require(ends["vl"].startswith("[Success]") and results["vl"].get("code") == 100, str(ends))
                        helpers.assert_gpu_result(results["vl"])
                        helpers.require(results["vl"].get("confidenceSupported") is False and all(block.get("score") is None for block in results["vl"].get("data", [])), "VL confidence was fabricated")
                        helpers.require(len(changes) == state["documentBaseline"], "Unchanged document interface was reset")
                        helpers.require(len(records) == 2 and all(record["pending"] and record["busy"] for record in records), "Pending selection was not visible while tasks were running")
                        state["passed"] = True; state["phase"] = "done"; QCoreApplication.instance().quit()
                except BaseException:
                    state["error"] = traceback.format_exc(); QCoreApplication.instance().quit()
            self.acceptanceTimer = QTimer(self)
            self.acceptanceTimer.setInterval(50)
            self.acceptanceTimer.timeout.connect(tick)
            self.acceptanceTimer.start()
    QtQml.QQmlApplicationEngine = ObservedEngine
    os.MessageBox = lambda message, *_args, **_kwargs: notices.append(str(message))
    from py_src.run import main as run_app
    from py_src.utils import pre_configs
    pre_configs.readConfigs(); pre_configs.setValue("last_pid", -1); pre_configs.setValue("last_ptime", -1); pre_configs.setValue("i18n", "zh_CN")
    sys.argv = [str(args.root / "Umi-OCR.exe"), "--force"]
    try:
        run_app(app_path=str(args.root / "Umi-OCR.exe"), engineAddImportPath="./site-packages/PySide6/qml")
    except SystemExit as exc:
        if exc.code not in (None, 0): state["error"] = "Application exit: " + str(exc.code)
    finally: QtQml.QQmlApplicationEngine = original_engine
    for label, result in results.items(): write(audit / (label + "-result.json"), result)
    unchanged = helpers.trusted_model_inputs(args.models)["verified"] == models["verified"]
    report = {"status": "PASS" if state.get("passed") and unchanged and not notices else "FAIL", "state": state,
        "records": records, "taskEnds": ends, "documentApplyCalls": changes, "modelsUnchanged": unchanged,
        "root": str(args.root), "controlledSettings": values, "startupErrors": notices, "desktopCapture": "NOT_RUN",
        "boundary": "真实 Main.qml、GlobalConfigs、MissionConnector 与 CUDA/VL 推理；只提交合成导入图片，不进行截图捕获。"}
    write(audit / "result.json", report)
    return report["status"] == "PASS"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("models", "matrix", "gui"))
    for name in ("root", "work", "audit", "models", "fixtures"): parser.add_argument("--" + name, type=Path)
    parser.add_argument("--deadline", type=int, default=1800)
    args = parser.parse_args()
    if args.mode == "models": prepare_models(args.models); return 0
    for name in ("root", "work", "audit", "models", "fixtures"):
        if getattr(args, name) is None: parser.error("missing --" + name)
        setattr(args, name, helpers.safe_path(getattr(args, name)))
    helpers.require(Path(sys.executable).resolve() == helpers.candidate_python(args.root), "Use the candidate's own Python interpreter")
    for path in (args.work, args.audit):
        path.relative_to(ROOT / "build")
        if path.exists(): raise FileExistsError(path)
        path.mkdir(parents=True)
    environment, overrides = helpers.prepare_worker_environment(args.work)
    os.environ.clear(); os.environ.update(environment)
    write(args.audit / "environment.json", overrides)
    models = helpers.trusted_model_inputs(args.models)
    passed = matrix(args, models, args.work, args.audit) if args.mode == "matrix" else gui(args, models, args.work, args.audit)
    print(json.dumps({"status": "PASS" if passed else "FAIL", "mode": args.mode, "audit": str(args.audit)}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__": raise SystemExit(main())
