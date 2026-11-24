"""Pure fixtures and portable QtCore-only loops; no window, EXE, or model."""

import ast
import builtins
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
QT_DATA = REPO / "release/Umi-OCR/UmiOCR-data"
TMP = REPO / "build/tmp/startup-small-files-20261028-r1/system-info-fixtures"
ABOUT_DATA = {"name": "fixture", "version": {"major": 1, "minor": 2, "patch": 3,
              "prerelease": "", "prereleaseNumber": 0}}
DIAGNOSTICS = {"platform": "fixture-platform", "python": "3.fixture",
               "cpu": "fixture-cpu | 4C8T", "ram": "8.0 GB"}
_DLL_HANDLES = []


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, REPO / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StartupSystemInfoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        packages = QT_DATA.resolve() / "site-packages"
        if not (packages / "PySide6/QtCore.pyd").is_file():
            raise RuntimeError("Portable QtCore is required: " + str(packages))
        sys.path.insert(0, str(packages))
        if os.name == "nt":
            _DLL_HANDLES.append(os.add_dll_directory(str(packages / "PySide6")))
        from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QThread, QTimer, qVersion
        from shiboken6 import delete, isValid
        cls.qt = SimpleNamespace(QCoreApplication=QCoreApplication, QEvent=QEvent,
            QEventLoop=QEventLoop, QThread=QThread, QTimer=QTimer, qVersion=qVersion,
            delete=delete, isValid=isValid)
        cls.app = QCoreApplication.instance() or QCoreApplication([])
        cls.info_module = load("startup_system_info_fixture", "UmiOCR-data/py_src/utils/system_info.py")
        cls.trace_module = load("startup_system_trace_fixture", "UmiOCR-data/py_src/utils/startup_trace.py")
        TMP.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="system-info-", dir=TMP)
        self.root = Path(self.temporary.name)
        self.providers, self.gates, self.threads, self.traces = [], [], [], []

    def tearDown(self):
        for provider in self.providers:
            if self.qt.isValid(provider):
                provider.stop()
        for gate in self.gates:
            gate.set()
        # Test cleanup joins only after releasing our fixture gates. Production
        # never joins; blocked quit/destruction are asserted before gate release.
        for worker in self.threads:
            if worker.ident is not None:
                worker.join(2)
                self.assertFalse(worker.is_alive(), "fixture worker did not finish")
        for provider in self.providers:
            if self.qt.isValid(provider):
                self.qt.delete(provider)
        for trace in self.traces:
            trace.close()
        self.temporary.cleanup()

    def provider(self, collector, trace=None, app_info=None):
        if app_info is None:
            app_info = {"path": "fixture.exe", "home": "fixture", "dir": "fixture", "system": "win32",
                        "platform": "", "python": "", "cpu": "", "ram": ""}
        provider = self.info_module.SystemInfo(self.app, app_info, collector, trace)
        self.providers.append(provider)
        return provider

    def start(self, provider):
        provider.start()
        if provider._worker is not None:
            self.threads.append(provider._worker)

    def blocked_collector(self, *, fail=False):
        gate, entered, finished = threading.Event(), threading.Event(), threading.Event()
        self.gates.append(gate)
        def collect(startupTrace=None):
            entered.set()
            if not gate.wait(5):
                raise RuntimeError("fixture gate was not released")
            finished.set()
            if fail:
                raise RuntimeError("fixture collection failed")
            return dict(DIAGNOSTICS)
        return collect, gate, entered, finished

    def until(self, predicate):
        if predicate():
            return
        loop = self.qt.QEventLoop()
        poll, deadline = self.qt.QTimer(), self.qt.QTimer()
        poll.setInterval(5)
        poll.timeout.connect(lambda: loop.quit() if predicate() else None)
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        poll.start()
        deadline.start(2500)
        loop.exec()
        poll.stop()
        deadline.stop()
        self.assertTrue(predicate(), "QtCore fixture timed out")

    def trace(self):
        trace = self.trace_module.StartupTrace(self.root / "trace.jsonl", "system-info-fixture", time.perf_counter_ns() - 1)
        self.traces.append(trace)
        return trace

    def about(self):
        with mock.patch.dict(sys.modules, {"umi_log": mock.Mock()}):
            return load("startup_system_about_fixture", "UmiOCR-data/py_src/imports/umi_about.py")

    def test_deferred_init_imports_no_diagnostic_dependencies_or_probes(self):
        original_import = builtins.__import__
        def imports(name, *args, **kwargs):
            if name in {"platform", "psutil"}:
                raise AssertionError("deferred init imported a diagnostic dependency")
            return original_import(name, *args, **kwargs)
        with mock.patch("builtins.__import__", side_effect=imports):
            about = self.about()
            with mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(ABOUT_DATA))), mock.patch.object(threading.Thread, "start", side_effect=AssertionError("init started background work")):
                self.assertTrue(about.init("fixture.exe", deferSystemInfo=True))
        self.assertEqual(about.UmiAbout["version"]["string"], "1.2.3")
        self.assertEqual(about.UmiAbout["app"]["path"], os.path.abspath("fixture.exe"))
        self.assertEqual(about.UmiAbout["app"]["system"], "win32")
        self.assertTrue(all(about.UmiAbout["app"][key] == "" for key in DIAGNOSTICS))

    def test_old_default_api_and_background_collection_produce_same_values(self):
        platform = mock.Mock()
        platform.platform.return_value = DIAGNOSTICS["platform"]
        platform.python_version.return_value = DIAGNOSTICS["python"]
        platform.processor.return_value = "fixture-cpu"
        psutil = mock.Mock()
        psutil.cpu_count.side_effect = lambda *, logical: 8 if logical else 4
        psutil.virtual_memory.return_value.total = 8 * 1073741824
        with mock.patch.dict(sys.modules, {"platform": platform, "psutil": psutil}):
            about = self.about()
            with mock.patch("builtins.open", mock.mock_open(read_data=json.dumps(ABOUT_DATA))):
                self.assertTrue(about.init("fixture.exe"))
                synchronous = dict(about.UmiAbout["app"])
                self.assertTrue(about.init("fixture.exe", deferSystemInfo=True))
            original = about.UmiAbout
            original_app = original["app"]
            provider = self.provider(about.collectSystemInfo, app_info=original_app)
            self.start(provider)
            self.until(lambda: provider.state == "ready")
        self.assertIs(about.UmiAbout, original)
        self.assertIs(about.UmiAbout["app"], original_app)
        self.assertEqual(original_app, synchronous)
        self.assertEqual(json.loads(provider.infoJson), synchronous)
        self.assertEqual(platform.platform.call_count, 2)
        self.assertEqual(psutil.cpu_count.call_args_list, [mock.call(logical=False), mock.call(logical=True)] * 2)

    def test_slow_collection_keeps_event_loop_and_pending_properties_responsive(self):
        collector, gate, entered, _ = self.blocked_collector()
        provider = self.provider(collector)
        committed_threads = []
        provider.infoChanged.connect(lambda: committed_threads.append(self.qt.QThread.currentThread()))
        self.start(provider)
        self.assertTrue(provider._worker.daemon)
        ticks = []
        heartbeat = self.qt.QTimer()
        heartbeat.setInterval(1)
        heartbeat.timeout.connect(lambda: ticks.append(len(ticks)))
        heartbeat.start()
        self.until(lambda: entered.is_set() and len(ticks) >= 5)
        heartbeat.stop()
        self.assertFalse(gate.is_set())
        self.assertEqual(provider.state, "pending")
        self.assertEqual(json.loads(provider.infoJson)["diagnostics"]["state"], "pending")
        self.assertEqual(committed_threads, [])
        gate.set()
        self.until(lambda: provider.state == "ready")
        self.assertEqual(committed_threads, [self.app.thread()])
        self.assertEqual(provider.error, "")

    def test_result_is_committed_once_and_properties_are_read_only(self):
        collected, changed, states = [], [], []
        def collect(startupTrace=None):
            collected.append(threading.get_ident())
            return dict(DIAGNOSTICS)
        provider = self.provider(collect)
        provider.infoChanged.connect(lambda: changed.append(provider.infoJson))
        provider.stateChanged.connect(lambda: states.append(provider.state))
        self.start(provider)
        provider.start()
        self.until(lambda: provider.state == "ready")
        provider._results.put((dict(DIAGNOSTICS, ram="must not replace"), ""))
        provider._poll()
        provider.start()
        self.assertEqual(len(collected), 1)
        self.assertNotEqual(collected[0], threading.get_ident())
        self.assertEqual(len(changed), 1)
        self.assertEqual(states, ["ready"])
        self.assertEqual(json.loads(provider.infoJson)["ram"], DIAGNOSTICS["ram"])
        meta = provider.metaObject()
        for name in ("state", "error", "infoJson"):
            self.assertFalse(meta.property(meta.indexOfProperty(name)).isWritable())

    def test_failure_is_terminal_explicit_and_finishes_optional_task(self):
        collector, gate, entered, _ = self.blocked_collector(fail=True)
        trace = self.trace()
        provider = self.provider(collector, trace)
        self.start(provider)
        self.until(entered.is_set)
        self.assertEqual(trace.pending(False), [self.info_module.OPTIONAL_TASK])
        gate.set()
        self.until(lambda: provider.state == "failed")
        self.assertIn("fixture collection failed", provider.error)
        self.assertEqual(json.loads(provider.infoJson)["diagnostics"]["state"], "failed")
        self.assertEqual(trace.pending(False), [])
        self.assertEqual(provider._app["platform"], "")
        trace.close()
        events = [json.loads(line) for line in trace.path.read_text("utf-8").splitlines()]
        self.assertEqual([row["details"]["outcome"] for row in events if row["event"] == "system-info-result"], ["failed"])
        self.assertEqual(sum(row["event"] == "task-completed" for row in events), 1)

    def test_pending_optional_work_blocks_s6_until_gui_submission(self):
        collector, gate, entered, _ = self.blocked_collector()
        trace = self.trace()
        provider = self.provider(collector, trace)
        self.start(provider)
        self.until(entered.is_set)
        state = {"warmupMode": "lazy", "modelState": "unloaded", "cudaPending": False, "pluginsBusy": False}
        def blockers():
            return self.trace_module.optional_blockers(state, native_timers=False,
                native_observer_available=True, pending=trace.pending(False))
        self.assertIn(self.info_module.OPTIONAL_TASK, blockers())
        self.assertNotIn("S6", trace._stages)
        gate.set()
        self.until(lambda: provider.state == "ready")
        self.assertEqual(blockers(), [])
        for stage in self.trace_module.STAGES[1:]:
            trace.mark(stage)
        trace.close()
        events = [json.loads(line) for line in trace.path.read_text("utf-8").splitlines()]
        self.assertLess(next(i for i, row in enumerate(events) if row["event"] == "task-completed"),
                        next(i for i, row in enumerate(events) if row["event"] == "S6"))

    def test_cancel_does_not_wait_or_claim_optional_completion(self):
        collector, gate, entered, _ = self.blocked_collector()
        trace = self.trace()
        provider = self.provider(collector, trace)
        self.start(provider)
        self.until(entered.is_set)
        provider.stop()
        self.assertFalse(gate.is_set())
        self.assertTrue(provider._worker.is_alive())
        self.assertFalse(provider._timer.isActive())
        self.assertEqual(provider.state, "cancelled")
        self.assertEqual(trace.pending(False), [self.info_module.OPTIONAL_TASK])
        gate.set()
        provider._worker.join(2)
        provider._poll()
        self.assertEqual(provider._app["platform"], "")
        self.assertEqual(trace.pending(False), [self.info_module.OPTIONAL_TASK])
        trace.close()
        events = [json.loads(line) for line in trace.path.read_text("utf-8").splitlines()]
        self.assertFalse(any(row["event"] in {"task-completed", "S6"} for row in events))
        self.assertEqual(sum(row["event"] == "system-info-cancelled" for row in events), 1)

    def test_destroyed_provider_is_never_touched_by_late_worker_result(self):
        collector, gate, entered, finished = self.blocked_collector()
        provider = self.provider(collector)
        app_info, cancelled = provider._app, provider._cancelled
        notifications = []
        provider.infoChanged.connect(lambda: notifications.append("changed"))
        self.start(provider)
        self.until(entered.is_set)
        worker = provider._worker
        self.qt.delete(provider)
        self.assertFalse(self.qt.isValid(provider))
        self.assertTrue(cancelled.is_set())
        self.assertTrue(worker.is_alive())
        gate.set()
        self.until(finished.is_set)
        worker.join(2)
        self.app.processEvents()
        self.assertEqual(notifications, [])
        self.assertEqual(app_info["platform"], "")

    def test_thread_start_failure_is_explicit_without_wait_or_retry(self):
        trace = self.trace()
        provider = self.provider(lambda **kw: dict(DIAGNOSTICS), trace)
        with mock.patch.object(threading.Thread, "start", side_effect=RuntimeError("fixture start failed")):
            provider.start()
        self.assertEqual(provider.state, "failed")
        self.assertIn("fixture start failed", provider.error)
        self.assertFalse(provider._timer.isActive())
        self.assertEqual(trace.pending(False), [])
        provider.start()
        self.assertIsNone(provider._worker.ident)

    def test_only_dedicated_about_binding_changes_not_global_context_snapshot(self):
        source = (REPO / "UmiOCR-data/py_src/run.py").read_text("utf-8")
        tree = ast.parse(source)
        globals_set = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute) and node.func.attr == "setContextProperty"
            and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "UmiAbout"]
        self.assertEqual(len(globals_set), 1)
        self.assertEqual(globals_set[0].args[1].id, "qmlAbout")
        snapshot = next(node for node in ast.walk(tree) if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "qmlAbout" for target in node.targets))
        original = {"version": {"string": "1.2.3"}, "app": {"system": "win32", "platform": ""}}
        namespace = {"UmiAbout": original}
        exec(compile(ast.Module(body=[snapshot], type_ignores=[]), "fixture-snapshot", "exec"), namespace)
        original["app"].update(DIAGNOSTICS)
        self.assertEqual(namespace["qmlAbout"]["app"], {"system": "win32", "platform": ""})
        self.assertEqual(source.count("systemInfo.start()"), 1)
        provider_source = (REPO / "UmiOCR-data/py_src/utils/system_info.py").read_text("utf-8")
        self.assertNotIn("setContextProperty", provider_source)
        self.assertNotIn("ThreadPool", provider_source)
        self.assertNotIn("thread_pool", provider_source)
        about_qml = (REPO / "UmiOCR-data/qt_res/qml/TabPages/About/About.qml").read_text("utf-8")
        self.assertNotIn("UmiAbout.app", about_qml)
        self.assertEqual(about_qml.count("UmiSystemInfo.infoJson"), 2)
        self.assertIn('UmiSystemInfo.state === "pending"', about_qml)
        self.assertIn('UmiSystemInfo.state === "failed"', about_qml)
        self.assertNotIn(".start()", about_qml)

    def test_z_qtcore_quit_returns_while_slow_daemon_probe_is_still_pending(self):
        collector, gate, entered, _ = self.blocked_collector()
        provider = self.provider(collector)
        self.start(provider)
        quit_when_started, deadline = self.qt.QTimer(), self.qt.QTimer()
        quit_when_started.setInterval(5)
        quit_when_started.timeout.connect(lambda: self.app.quit() if entered.is_set() else None)
        deadline.setSingleShot(True)
        deadline.timeout.connect(self.app.quit)
        quit_when_started.start()
        deadline.start(2500)
        self.assertEqual(self.app.exec(), 0)
        quit_when_started.stop()
        deadline.stop()
        self.assertTrue(entered.is_set())
        self.assertFalse(gate.is_set())
        self.assertTrue(provider._worker.daemon)
        self.assertTrue(provider._worker.is_alive())
        self.assertEqual(provider.state, "cancelled")
        self.assertFalse(provider._timer.isActive())


if __name__ == "__main__":
    unittest.main()
