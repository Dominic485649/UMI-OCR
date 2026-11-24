"""Actual Windows QML window, event-loop timing and hot configuration checks."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import runpy
import sys
import time
import traceback


def wait_transition(predicate, timeout=12, label="UI transition", clock=None):
    """每次等待都归还 Qt 主循环，不递归 processEvents 或延长原超时。"""
    clock = clock or time.perf_counter
    end = clock() + timeout
    while not predicate():
        assert clock() < end, label + " timed out"
        yield 10


def start_steps(steps, schedule, completed, failed):
    """由 QTimer 调度生成器，每一步完成后都返回正常 exec。"""
    def advance():
        try:
            delay = next(steps)
            if not isinstance(delay, int) or delay < 0:
                raise ValueError("UI step must yield a nonnegative millisecond delay")
        except StopIteration:
            completed()
        except Exception as exc:
            failed(exc)
        else:
            schedule(delay, advance)
    schedule(0, advance)


def memory():
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_uint32), ("PageFaultCount", ctypes.c_uint32)] + [
            (name, ctypes.c_size_t) for name in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage",
            )
        ]
    value = Counters()
    value.cb = ctypes.sizeof(value)
    ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    assert ctypes.windll.psapi.GetProcessMemoryInfo(
        ctypes.c_void_p(ctypes.windll.kernel32.GetCurrentProcess()), ctypes.byref(value), value.cb
    )
    return {"working_set_mb": value.WorkingSetSize / 1048576,
            "peak_working_set_mb": value.PeakWorkingSetSize / 1048576,
            "private_mb": value.PrivateUsage / 1048576}


def completion_errors(report, hot_required=False):
    """首帧或正常退出不代表生成器已经完成。"""
    errors = []
    if report.get("scenario_completed") is not True:
        errors.append("UI scenario 未完成 before the event loop exited")
    if hot_required and report.get("hot") is not True:
        errors.append("Hot configuration scenario 未完成")
    return errors


def main(argv=None):
    started = time.perf_counter()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hot", action="store_true")
    parser.add_argument("--profile", choices=("cuda-only", "all-plugins"), default="all-plugins")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    data = root / "UmiOCR-data"
    output = args.output.resolve()
    if output.exists():
        raise RuntimeError("Use a new UI evidence path; existing records are never overwritten")
    output.parent.mkdir(parents=True, exist_ok=True)
    saved_settings = {data / name: (data / name).read_bytes() if (data / name).is_file() else None
                      for name in (".settings", ".pre_settings")}
    report = {"python": sys.version.split()[0], "profile": args.profile,
              "hot": False, "scenario_completed": False, "errors": [],
              "operation_events": [], "artifact_root": str(root)}
    namespace = runpy.run_path(str(data / "main.py"), run_name="runtime_test")
    namespace["initRuntimeEnvironment"]()
    os.MessageBox = lambda message, *unused: print(message)
    from PySide6 import QtQml
    from PySide6.QtCore import QTimer
    from PySide6.QtQml import QQmlExpression, QQmlEngine
    from PySide6.QtWidgets import QApplication

    def evaluate(engine, window, expression):
        expr = QQmlExpression(QQmlEngine.contextForObject(window), window, expression)
        value = expr.evaluate()
        assert not expr.hasError(), expr.error().toString()
        if isinstance(value, tuple):
            value = value[0]
        return value.toVariant() if hasattr(value, "toVariant") else value

    original = QtQml.QQmlApplicationEngine

    class Engine(original):
        def load(self, *values):
            super().load(*values)
            assert self.rootObjects(), "No QML root"
            window = self.rootObjects()[0]
            self._test_started = False
            self._test_finished = False

            def js(code):
                return evaluate(self, window, code)

            def state():
                return json.loads(js("JSON.stringify({"
                    "applyPhase:qmlapp.globalConfigs.applyPhase,"
                    "backendApplyPending:qmlapp.globalConfigs.backendApplyPending,"
                    "pluginRefreshPending:qmlapp.globalConfigs.pluginRefreshPending,"
                    "ocrApplying:qmlapp.globalConfigs.ocrManager.applying,"
                    "documentApplying:qmlapp.globalConfigs.documentManager.applying,"
                    "missionBridgeBusy:qmlapp.msnConnector.isBusy(),"
                    "ocrQueues:qmlapp.msnConnector.callPy('ocr','getMissionListsLength',[]),"
                    "documentQueues:qmlapp.msnConnector.callPy('document','getMissionListsLength',[])"
                    "})"))

            def finish(error=None):
                if self._test_finished:
                    return
                self._test_finished = True
                if error is not None:
                    text = "".join(traceback.format_exception(type(error), error, error.__traceback__))
                    report["errors"].append(text)
                    print(text)
                    try:
                        report["failure_state"] = state()
                    except Exception as diagnostics_error:
                        report["diagnostic_error"] = str(diagnostics_error)
                QApplication.instance().quit()

            def capture(suffix):
                image = window.grabWindow()
                assert not image.isNull(), "Application window capture is empty"
                assert image.save(str(output.with_name(output.stem + suffix))), "Window capture could not be saved"

            def scenario():
                report["idle"] = memory()
                if args.hot:
                    report["plugins"] = js("JSON.stringify(qmlapp.globalConfigs.pluginStates)")
                    assert js("qmlapp.tab.savedPageIndex('file:///D:/old/UmiOCR-data/plugins/win32_PaddleOCRVL_1_6/StructuredDocument.qml')") == js("qmlapp.tab.savedPageIndex('StructuredDocument')")
                    assert not any(name in sys.modules for name in ("paddle", "paddlex", "paddleocr", "onnxruntime", "fitz", "pymupdf"))
                    assert not js("qmlapp.globalConfigs.panelBuilt")
                    js("qmlapp.globalConfigs.initPanelComponent()")
                    assert js("qmlapp.globalConfigs.panelBuilt")
                    selected = "win32_PaddleOCRv6_CUDA" if args.profile == "cuda-only" else "win32_PaddleOCRv6_CPU"
                    js("qmlapp.globalConfigs.setValue('ocr.api'," + json.dumps(selected) + ",true)")
                    yield from wait_transition(lambda: js("qmlapp.globalConfigs.applyPhase === 0 && !qmlapp.globalConfigs.backendApplyPending && !qmlapp.globalConfigs.ocrManager.applying"), label="Initial backend apply")
                    from py_src.mission.mission_ocr import MissionOCR
                    assert MissionOCR._apiKey == selected
                    assert MissionOCR._api.get_status()["state"] == "unloaded"
                    from py_src.plugins_controller.services import PluginServices
                    assert all(not entry["instance"] or not entry["instance"].get_status().get("pid") for entry in PluginServices._entries.values())
                    from py_src.plugins_controller.plugins_controller import PluginsController
                    ready_plugins = {item["id"] for item in PluginsController.getPlugins() if item["state"] == "ready"}
                    if args.profile == "cuda-only":
                        assert ready_plugins == {"win32_PaddleOCRv6_CUDA"}, ready_plugins
                        assert {item["id"] for item in PluginsController.getPlugins()} == ready_plugins
                    else:
                        js("qmlapp.globalConfigs.setValue('document.win32_PaddleOCRVL_1_6.pipeline.layoutModelDir','D:/AI/models/PP-DocLayoutV3',true)")
                        yield from wait_transition(lambda: js("qmlapp.globalConfigs.applyPhase === 0 && !qmlapp.globalConfigs.backendApplyPending"), label="Document configuration apply")
                        assert js("qmlapp.globalConfigs.getValue('document.win32_PaddleOCRVL_1_6.pipeline.layoutModelDir')") == "D:/AI/models/PP-DocLayoutV3"
                        assert ready_plugins == {"win32_PaddleOCRv6_CPU", "win32_PaddleOCRv6_CUDA", "win32_PaddleOCRVL_1_6"}, ready_plugins
                    js("qmlapp.globalConfigs.setPluginEnabled('win32_PaddleOCRv6_CUDA', false)")
                    yield from wait_transition(lambda: not js("qmlapp.globalConfigs.pluginRefreshPending || qmlapp.globalConfigs.applyPhase !== 0"), label="Plugin disable")
                    assert not PluginsController.isEnabled("win32_PaddleOCRv6_CUDA")
                    js("qmlapp.globalConfigs.setPluginEnabled('win32_PaddleOCRv6_CUDA', true)")
                    yield from wait_transition(lambda: not js("qmlapp.globalConfigs.pluginRefreshPending || qmlapp.globalConfigs.applyPhase !== 0"), label="Plugin enable")
                    assert PluginsController.isEnabled("win32_PaddleOCRv6_CUDA")
                    js("qmlapp.globalConfigs.setValue('ui.i18n','en_US',true)")
                    yield from wait_transition(lambda: not js("qmlapp.globalConfigs.pluginRefreshPending || qmlapp.globalConfigs.applyPhase !== 0"), label="English UI apply")
                    from py_src.utils.i18n_configs import I18n
                    assert I18n.langCode == "en_US"
                    assert js("qmlapp.globalConfigs.getOriginDict()['shortcut'].title") == "Shortcut"
                    js("qmlapp.globalConfigs.setValue('ui.i18n','zh_CN',true)")
                    yield from wait_transition(lambda: not js("qmlapp.globalConfigs.pluginRefreshPending || qmlapp.globalConfigs.applyPhase !== 0"), label="Chinese UI apply")
                    assert js("qmlapp.globalConfigs.getOriginDict()['shortcut'].title") == "快捷方式"
                    import socket
                    import urllib.request
                    with socket.socket() as sock:
                        sock.bind(("127.0.0.1", 0))
                        port = sock.getsockname()[1]
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    js("qmlapp.globalConfigs.setValue('server.port'," + str(port) + ",true)")

                    def responds():
                        try:
                            with opener.open("http://127.0.0.1:" + str(port) + "/", timeout=.2) as response:
                                return response.status == 200
                        except OSError:
                            return False

                    yield from wait_transition(responds, label="HTTP port rebind")
                    js("qmlapp.globalConfigs.setValue('server.enable',false,true)")
                    yield from wait_transition(lambda: not responds(), label="HTTP disable")
                    js("qmlapp.globalConfigs.setValue('server.enable',true,true)")
                    yield from wait_transition(responds, label="HTTP enable")
                    js("qmlapp.globalConfigs.setValue('window.messageMemory',['globalConfigsKey'],true)")
                    js("qmlapp.globalConfigs.setValue('window.simpleNotificationType','none',true)")
                    js("qmlapp.tab.openTabPageByKey('GlobalConfigsPage')")
                    yield 0
                    window.setWidth(640)
                    window.setHeight(540)
                    js("qmlapp.globalConfigs.setValue('ui.theme','Neutral Dark',true)")
                    yield 300
                    capture("-dark-narrow.png")
                    js("qmlapp.globalConfigs.setValue('ui.theme','Default Light',true)")
                    yield from wait_transition(lambda: js("theme.bgColor.toString() !== '#181818'"), label="Light theme apply")
                    yield 0
                    capture("-settings-light.png")
                    assert js("UmiAbout.url.home") == "https://github.com/Dominic485649/UMI-OCR"
                    assert js("UmiAbout.url.plugins") == "https://github.com/Dominic485649/UMI-OCR_plugins"
                    expected_version = json.loads((data / "about.json").read_text(encoding="utf-8"))["version"]
                    version_string = ".".join(str(expected_version[key]) for key in ("major", "minor", "patch"))
                    assert js("UmiAbout.version.string") == version_string
                    assert js("!!qmlapp.tab.openTabPageByKey('About')"), "About page failed to instantiate"
                    yield 300
                    capture("-about.png")
                    if args.profile == "all-plugins":
                        assert js("!!qmlapp.tab.openTabPageByKey('StructuredDocument')"), "Document page failed to instantiate"
                        yield 300
                        capture("-document.png")
                    report["hot"] = True
                capture(".png")
                report["end"] = memory()
                report["final_state"] = state()

            def ready():
                try:
                    connector = js("qmlapp.msnConnector")
                    connector.operationFinished.connect(lambda kind, operation, result: report["operation_events"].append({
                        "kind": kind, "operation": operation, "seconds": time.perf_counter() - started
                    }) if len(report["operation_events"]) < 64 else None)
                except Exception as exc:
                    report["signal_diagnostics_unavailable"] = str(exc)
                def completed():
                    report["scenario_completed"] = True
                    finish()
                self._steps = scenario()
                start_steps(self._steps, QTimer.singleShot, completed, finish)

            def first_frame():
                if not self._test_started:
                    self._test_started = True
                    report["interactive_seconds"] = time.perf_counter() - started
                    QTimer.singleShot(0, ready)

            window.frameSwapped.connect(first_frame)
            window.show()
            QTimer.singleShot(12000, lambda: finish(AssertionError("No interactive frame observed")) if not self._test_started else None)

    QtQml.QQmlApplicationEngine = Engine
    try:
        from py_src.run import main as run_application
        module_path = Path(sys.modules["py_src.run"].__file__).resolve()
        assert module_path.is_relative_to(data), "GUI test loaded application code outside the selected artifact"
        report["application_module"] = str(module_path)
        sys.argv = [str(root / "Umi-OCR.exe"), "--force"]
        try:
            run_application(str(root / "Umi-OCR.exe"), "./site-packages/PySide6/qml")
        except SystemExit as exc:
            if exc.code not in (0, None):
                raise
        report["normal_exit"] = True
    except Exception as exc:
        report["errors"].append("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        report["normal_exit"] = False
    finally:
        QtQml.QQmlApplicationEngine = original
        for path, contents in saved_settings.items():
            if contents is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(contents)
        report["settings_restored"] = all(path.read_bytes() == contents if contents is not None else not path.exists()
                                          for path, contents in saved_settings.items())
        if "interactive_seconds" not in report and not report["errors"]:
            report["errors"].append("No interactive frame observed")
        report["errors"].extend(completion_errors(report, args.hot))
        with output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    assert not report["errors"], report["errors"]
    assert report["settings_restored"]
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
