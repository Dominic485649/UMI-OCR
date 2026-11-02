"""Pure unit/parameter tests. Never starts Qt, an EXE, HTTP, or a model."""

import argparse
import ast
import builtins
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
TMP = REPO / "build/tmp/startup-small-files-20261028-r1"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


trace = load("startup_trace_units", REPO / "UmiOCR-data/py_src/utils/startup_trace.py")
bench = load("startup_benchmark_units", REPO / "benchmarks/benchmark_startup_isolated.py")


def run_function_fixture(name, imports, namespace, *, before_engine=False):
    """Execute the real function body with fixture-only imports, never Qt.

    runQml's prefix stops before engine creation; engine/GUI behavior is not
    asserted by this pure fixture.
    """
    path = REPO / "UmiOCR-data/py_src/run.py"
    tree = ast.parse(path.read_text("utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    if before_engine:
        stop = next(index for index, node in enumerate(function.body)
                    if isinstance(node, ast.Assign) and any(
                        isinstance(target, ast.Name) and target.id == "engine" for target in node.targets))
        function.body = function.body[:stop]
    namespace["__builtins__"] = {**vars(builtins), "__import__": imports}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


class DialogFixture:
    def __init__(self, pid=12345):
        def window(hwnd, parent, kind, text, *, owner=pid, control=0):
            return {"hwnd": hwnd, "pid": owner, "parent": parent, "class": kind, "text": text,
                    "controlId": control, "visible": True, "enabled": True, "textTruncated": False}
        self.rows = {10: window(10, 0, "#32770", bench.STARTUP_ERROR_TITLE, owner=33836),
                     20: window(20, 0, "#32770", "Unknown dialog"),
                     30: window(30, 0, "#32770", bench.STARTUP_ERROR_TITLE),
                     31: window(31, 30, "Static", "ModuleNotFoundError: runtime_archive_bootstrap"),
                     32: window(32, 30, "Button", "确定", control=1)}
        self.reads, self.clicks = [], []

    def windows(self, parent=None):
        return [key for key, value in self.rows.items() if value["parent"] == (parent or 0)]

    def pid(self, hwnd):
        return self.rows[hwnd]["pid"]

    def info(self, hwnd):
        self.reads.append(hwnd)
        return dict(self.rows[hwnd])

    def click_ok(self, hwnd):
        self.clicks.append(hwnd)


class StartupTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        TMP.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        # This fixture owns only its newly created tiny fake artifact; no process
        # is launched from it. TemporaryDirectory removes only that exact tree.
        self.temporary = tempfile.TemporaryDirectory(prefix="unit-", dir=TMP)
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_disabled_has_no_io_or_qt_initialization(self):
        before = {name for name in sys.modules if name.startswith("PySide6")}
        with mock.patch.object(Path, "open", side_effect=AssertionError("disabled trace wrote a file")):
            self.assertIsNone(trace.from_environment({}))
            self.assertIsNone(trace.from_environment({"UMI_STARTUP_TRACE": ""}))
        self.assertEqual(before, {name for name in sys.modules if name.startswith("PySide6")})

    def test_trace_stages_are_ordered_unique_and_correlated(self):
        path = self.root / "trace.jsonl"
        observer = trace.StartupTrace(path, "unit-1", 10, clock=lambda: 100)
        try:
            with self.assertRaises(ValueError):
                observer.mark("S2")
            for stage in trace.STAGES[1:]:
                self.assertTrue(observer.mark(stage))
                self.assertFalse(observer.mark(stage))
        finally:
            observer.close()
        events = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
        self.assertEqual([event["event"] for event in events], list(trace.STAGES))
        self.assertEqual({event["runId"] for event in events}, {"unit-1"})
        self.assertEqual(len({event["pid"] for event in events}), 1)
        self.assertEqual(events[0]["t_ns"], 10)
        self.assertTrue(all(event["t_ns"] >= 10 for event in events))
        with self.assertRaises(FileExistsError):
            trace.StartupTrace(path, "unit-1", 10, clock=lambda: 100)

    def test_trace_rejects_bad_configuration_before_creating_file(self):
        for run_id, s0 in (("../bad", 1), ("valid", 101), ("valid", 0)):
            with self.assertRaises(ValueError):
                trace.StartupTrace(self.root / "invalid.jsonl", run_id, s0, clock=lambda: 100)
        self.assertFalse((self.root / "invalid.jsonl").exists())

    def test_task_completion_is_explicit(self):
        observer = trace.StartupTrace(self.root / "pending.jsonl", "unit-pending", 1, clock=lambda: 100)
        try:
            observer.scheduled("pages", True)
            observer.scheduled("extra", False)
            self.assertEqual(observer.pending(True), ["pages"])
            self.assertEqual(observer.pending(False), ["extra"])
            with self.assertRaises(ValueError):
                observer.scheduled("pages", True)
            observer.completed("pages")
            self.assertEqual(observer.pending(True), [])
            with self.assertRaises(ValueError):
                observer.completed("pages")
        finally:
            observer.close()

    def test_first_frame_is_not_interactive(self):
        ready = {"pageReady": True, "connectorsReady": True, "backendReady": True, "httpReady": True}
        self.assertEqual(trace.readiness_blockers(ready, frame_seen=True, cli_registered=True), [])
        for key in ready:
            state = {**ready, key: False}
            self.assertTrue(trace.readiness_blockers(state, frame_seen=True, cli_registered=True), key)
        self.assertIn("cli-registration", trace.readiness_blockers(ready, frame_seen=True, cli_registered=False))
        self.assertIn("restore-pages", trace.readiness_blockers(ready, frame_seen=True, cli_registered=True, pending_required=["restore-pages"]))
        self.assertIn("first-frame", trace.readiness_blockers(ready, frame_seen=False, cli_registered=True))

    def test_s6_does_not_claim_unobserved_or_delayed_work_complete(self):
        state = {"warmupMode": "lazy", "modelState": "unloaded", "cudaPending": False, "pluginsBusy": False}
        self.assertEqual(trace.optional_blockers(state, native_timers=False, native_observer_available=True), [])
        for changed in ({"warmupMode": "delayed"}, {"cudaPending": True}, {"pluginsBusy": True}, {"modelState": "warming"}):
            self.assertTrue(trace.optional_blockers({**state, **changed}, native_timers=False, native_observer_available=True))
        self.assertTrue(trace.optional_blockers(state, native_timers=False, native_observer_available=False))
        self.assertTrue(trace.optional_blockers(state, native_timers=True, native_observer_available=True))

    def test_native_plugin_connector_does_not_use_private_qml_id(self):
        class Object:
            def __init__(self, parent):
                pass
        core = mock.Mock(QObject=Object, QTimer=mock.Mock(), Qt=mock.Mock(),
                         Slot=lambda *args: lambda method: method)
        qml = mock.Mock()
        plugin_type = type("PluginsConnector", (), {})
        modules = {"PySide6.QtCore": core, "PySide6.QtQml": qml,
                   "py_src.plugins_controller.plugins_connector": mock.Mock(PluginsConnector=plugin_type)}
        with mock.patch.dict(sys.modules, modules):
            observer = trace._attach_qt(mock.Mock(), mock.Mock(), mock.Mock())
            connector = mock.Mock()
            connector.isBusy.side_effect = [False, True]
            observer.window = mock.Mock()
            observer.window.findChildren.return_value = [connector]
            def evaluate(obj, code):
                if code != trace._STATE:
                    raise RuntimeError("组件外层上下文没有pluginsConnector私有id")
                return "{}"
            observer.evaluate = evaluate
            self.assertFalse(observer.state()["pluginsBusy"])
            self.assertTrue(observer.state()["pluginsBusy"])
            observer.window.findChildren.assert_called_once_with(plugin_type)
            for discovered in ([], [connector, connector]):
                other = trace._attach_qt(mock.Mock(), mock.Mock(), mock.Mock())
                other.window = mock.Mock()
                other.window.findChildren.return_value = discovered
                other.evaluate = evaluate
                with self.assertRaisesRegex(RuntimeError, "无法唯一观察"):
                    other.state()

    def test_detail_contract_is_bounded_and_cannot_admit_stages(self):
        path = self.root / "details.jsonl"
        observer = trace.StartupTrace(path, "unit-details", 1, clock=lambda: 100)
        try:
            for name in sorted(trace.DETAIL_NAMES):
                for phase in ("begin", "end"):
                    self.assertTrue(observer.detail(name, phase, "x" * 1000, "y" * 1000))
            for name, phase in (("S0", "begin"), ("S3", "end"), ("unknown", "begin"),
                                ("about-json", "S6"), ([], "begin")):
                self.assertFalse(observer.detail(name, phase))
            self.assertFalse(observer.detail("about-json", "begin", subject={}))
            self.assertEqual(observer._stages, {"S0"})
            self.assertEqual(observer.pending(True), [])
            with self.assertRaises(ValueError):
                observer.mark("S2")
            for stage in trace.STAGES[1:]:
                observer.mark(stage)
            self.assertFalse(observer.detail("about-json", "begin"))
        finally:
            observer.close()
        self.assertFalse(observer.detail("about-json", "end"))
        rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
        details = [row for row in rows if row["event"] == "detail"]
        self.assertEqual(len(details), len(trace.DETAIL_NAMES) * 2)
        self.assertEqual([row["details"]["sequence"] for row in details], list(range(1, len(details) + 1)))
        self.assertTrue(all(len(row["details"]["subject"]) == trace.DETAIL_TEXT_LIMIT for row in details))
        self.assertTrue(all(len(row["details"]["outcome"]) == trace.DETAIL_TEXT_LIMIT for row in details))
        self.assertEqual([row["event"] for row in rows if row["event"] in trace.STAGES], list(trace.STAGES))
        self.assertTrue(all(row["runId"] == "unit-details" and row["t_ns"] >= 1 for row in rows))

    def test_detail_budget_reports_once_without_limiting_existing_stages(self):
        path = self.root / "detail-budget.jsonl"
        observer = trace.StartupTrace(path, "unit-budget", 1, clock=lambda: 100)
        try:
            accepted = [observer.detail("page-controller", "begin", "Navigation")
                        for _ in range(trace.DETAIL_EVENT_LIMIT + 10)]
            self.assertEqual(sum(accepted), trace.DETAIL_EVENT_LIMIT)
            observer.scheduled("fixture", True)
            observer.completed("fixture")
            for stage in trace.STAGES[1:]:
                observer.mark(stage)
        finally:
            observer.close()
        rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
        self.assertEqual(sum(row["event"] == "detail" for row in rows), trace.DETAIL_EVENT_LIMIT)
        notices = [row for row in rows if row["event"] == "detail-limit"]
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]["details"]["limit"], trace.DETAIL_EVENT_LIMIT)
        self.assertEqual([row["event"] for row in rows if row["event"] in trace.STAGES], list(trace.STAGES))

    def test_qml_detail_slot_only_forwards_to_detail_api(self):
        class Object:
            def __init__(self, parent):
                pass
        core = mock.Mock(QObject=Object, QTimer=mock.Mock(), Qt=mock.Mock(),
                         Slot=lambda *args: lambda method: method)
        recorder = mock.Mock()
        with mock.patch.dict(sys.modules, {"PySide6.QtCore": core, "PySide6.QtQml": mock.Mock()}):
            observer = trace._attach_qt(recorder, mock.Mock(), mock.Mock())
            observer.detail("page-controller", "begin", "Navigation", "simple")
            recorder.detail.assert_called_once_with("page-controller", "begin", "Navigation", "simple")
            recorder.mark.assert_not_called()
            recorder.scheduled.assert_not_called()
            with self.assertRaises(ValueError):
                observer.stage("S4")

    def about_fixture(self, calls):
        platform = mock.Mock()
        psutil = mock.Mock()
        for method, value in (("platform", "fixture-platform"), ("python_version", "3.fixture"),
                              ("processor", "fixture-cpu")):
            getattr(platform, method).side_effect = lambda m=method, v=value: (calls.append(m), v)[1]
        psutil.cpu_count.side_effect = lambda *, logical: (calls.append("cpu-logical" if logical else "cpu-physical"),
                                                          8 if logical else 4)[1]
        psutil.virtual_memory.side_effect = lambda: (calls.append("memory"), SimpleNamespace(total=8 * 1073741824))[1]
        modules = mock.patch.dict(sys.modules, {"platform": platform, "psutil": psutil, "umi_log": mock.Mock()})
        modules.start()
        self.addCleanup(modules.stop)
        module = load("startup_about_detail_fixture", REPO / "UmiOCR-data/py_src/imports/umi_about.py")
        return module, platform

    def test_about_details_preserve_default_data_and_probe_order(self):
        data = {"name": "fixture", "version": {"major": 1, "minor": 2, "patch": 3,
                "prerelease": "", "prereleaseNumber": 0}}
        probe_order = ["platform", "python_version", "processor", "cpu-physical", "cpu-logical", "memory"]
        results = []
        for enabled in (False, True):
            calls = []
            module, _ = self.about_fixture(calls)
            recorder = mock.Mock()
            recorder.detail.side_effect = lambda name, phase, **kw: calls.append((name, phase, kw.get("outcome", "")))
            opened = mock.mock_open(read_data=json.dumps(data))
            with mock.patch("builtins.open", opened), mock.patch.object(Path, "open", side_effect=AssertionError("extra trace I/O")), mock.patch.object(subprocess, "Popen", side_effect=AssertionError("extra process")), mock.patch("threading.Thread.start", side_effect=AssertionError("extra thread")):
                arguments = {"startupTrace": recorder} if enabled else {}
                self.assertTrue(module.init(str(self.root / "fixture.exe"), **arguments))
            opened.assert_called_once_with("about.json", "r", encoding="utf-8")
            self.assertEqual([call for call in calls if isinstance(call, str)], probe_order)
            if enabled:
                self.assertEqual(calls, [("about-json", "begin", ""), ("about-json", "end", "ok"),
                    ("about-diagnostics-import", "begin", ""), ("about-diagnostics-import", "end", "ok"),
                    ("about-platform", "begin", ""), "platform", "python_version", ("about-platform", "end", "ok"),
                    ("about-hardware", "begin", ""), *probe_order[2:], ("about-hardware", "end", "ok")])
            else:
                self.assertEqual(calls, probe_order)
                recorder.assert_not_called()
                recorder.detail.assert_not_called()
            results.append(module.UmiAbout)
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0]["app"]["cpu"], "fixture-cpu | 4C8T")
        self.assertEqual(results[0]["app"]["ram"], "8.0 GB")

    def test_about_failure_does_not_claim_success_or_start_hardware_collection(self):
        calls = []
        module, _ = self.about_fixture(calls)
        recorder = mock.Mock()
        with mock.patch("builtins.open", side_effect=OSError("fixture unreadable")), mock.patch.object(module.os, "MessageBox", create=True) as message:
            self.assertFalse(module.init("fixture.exe", startupTrace=recorder))
        self.assertIsNone(module.UmiAbout)
        self.assertEqual(calls, [])
        self.assertEqual(recorder.detail.call_args_list, [mock.call("about-json", "begin"),
                         mock.call("about-json", "end", outcome="error")])
        message.assert_called_once()

    def test_main_about_import_details_are_opt_in_without_reordering_work(self):
        observed = []
        for enabled in (False, True):
            calls = []
            recorder = mock.Mock()
            recorder.detail.side_effect = lambda name, phase, **kw: calls.append(("detail", name, phase))
            about = mock.Mock()
            about.init.side_effect = lambda *a, **kw: (calls.append("about-init"), True)[1]
            pre = mock.Mock()
            pre.readConfigs.side_effect = lambda: calls.append("preconfigs")
            cmd = mock.Mock(side_effect=lambda: (calls.append("cmd-init"), True)[1])
            def imports(name, globals=None, locals=None, fromlist=(), level=0):
                calls.append("import:" + name)
                return {"umi_about": about, "utils": SimpleNamespace(pre_configs=pre),
                        "server.cmd_client": SimpleNamespace(initCmd=cmd)}[name]
            run_qml = mock.Mock(side_effect=lambda *a: calls.append("runQml"))
            site = mock.Mock()
            site.addsitedir.side_effect = lambda *a: calls.append("site")
            main = run_function_fixture("main", imports, {"site": site, "os": SimpleNamespace(environ={}),
                "sys": SimpleNamespace(exit=mock.Mock(side_effect=SystemExit(0))), "runQml": run_qml})
            arguments = {"startupTrace": recorder} if enabled else {}
            with self.assertRaises(SystemExit):
                main("fixture.exe", **arguments)
            about.init.assert_called_once_with("fixture.exe", startupTrace=recorder if enabled else None, deferSystemInfo=True)
            run_qml.assert_called_once_with("", 0, recorder if enabled else None)
            ordinary = [call for call in calls if isinstance(call, str)]
            observed.append(ordinary)
            if enabled:
                start, imported, finish = (calls.index(value) for value in (
                    ("detail", "about-import", "begin"), "import:umi_about", ("detail", "about-import", "end")))
                self.assertLess(start, imported)
                self.assertLess(imported, finish)
                self.assertLess(finish, calls.index("about-init"))
            else:
                recorder.detail.assert_not_called()
        self.assertEqual(observed[0], observed[1])
        self.assertEqual(observed[0], ["site", "import:umi_about", "about-init", "import:utils",
                         "import:server.cmd_client", "preconfigs", "cmd-init", "runQml"])

    def test_qt_prefix_details_bracket_fixture_work_without_changing_order(self):
        observed = []
        for enabled in (False, True):
            calls = []
            recorder = mock.Mock()
            recorder.detail.side_effect = lambda name, phase, **kw: calls.append(("detail", name, phase))
            recorder.mark.side_effect = lambda name, **kw: calls.append(("stage", name))
            app = mock.Mock()
            app.styleHints.return_value.wheelScrollLines.return_value = 3
            create_app = mock.Mock(side_effect=lambda *a: (calls.append("QApplication"), app)[1])
            opengl = mock.Mock()
            opengl.initOpengl.side_effect = lambda: calls.append("initOpengl")
            opengl.checkOpengl.side_effect = lambda: calls.append("checkOpengl")
            i18n = mock.Mock()
            i18n.init.side_effect = lambda *a: calls.append("translation")
            def register(*args):
                calls.append("register:" + args[-1])
            def imports(name, globals=None, locals=None, fromlist=(), level=0):
                calls.append("import:" + name)
                fixed = {
                    "PySide6.QtCore": SimpleNamespace(Qt=SimpleNamespace(ApplicationAttribute=SimpleNamespace(AA_ShareOpenGLContexts=1)), QTimer=mock.Mock(), qInstallMessageHandler=mock.Mock()),
                    "PySide6.QtQml": SimpleNamespace(QQmlApplicationEngine=mock.Mock(side_effect=AssertionError("real engine")), qmlRegisterType=register),
                    "PySide6.QtQuickControls2": SimpleNamespace(QQuickStyle=mock.Mock()),
                    "PySide6.QtWidgets": SimpleNamespace(QApplication=create_app),
                    "umi_about": SimpleNamespace(UmiAbout={"name": "fixture", "authors": [{"name": "fixture"}], "url": {"home": "fixture"}}, collectSystemInfo=mock.Mock()),
                    "umi_log": SimpleNamespace(get_qt_message_handler=mock.Mock(), logger=mock.Mock()),
                    "utils": SimpleNamespace(app_opengl=opengl),
                    "utils.portable_settings": SimpleNamespace(PortableSettings=mock.Mock()),
                    "utils.i18n_configs": SimpleNamespace(I18n=i18n),
                }
                if name in fixed:
                    return fixed[name]
                self.assertIn(fromlist[0], {"TagPageConnector", "MissionConnector", "DocPreviewConnector",
                    "PubSubConnector", "KeyMouseConnector", "PluginsConnector", "UtilsConnector",
                    "GlobalConfigsConnector", "ThemeConnector", "ImageConnector", "PixmapProvider"})
                return SimpleNamespace(**{fromlist[0]: object()})
            run_qml = run_function_fixture("runQml", imports, {"sys": SimpleNamespace(argv=["fixture"])}, before_engine=True)
            run_qml("", **({"startupTrace": recorder} if enabled else {}))
            observed.append([call for call in calls if isinstance(call, str)])
            if enabled:
                for name, first, last in (
                        ("qt-application", "QApplication", "QApplication"),
                        ("connectors-import", "import:tag_pages.tag_pages_connector", "import:utils.i18n_configs"),
                        ("connectors-register", "register:TagPageConnector", "register:DocPreviewConnector"),
                        ("translation", "translation", "translation")):
                    self.assertLess(calls.index(("detail", name, "begin")), calls.index(first))
                    self.assertLess(calls.index(last), calls.index(("detail", name, "end")))
                self.assertLess(calls.index(("detail", "translation", "end")), calls.index(("stage", "S2")))
            else:
                recorder.detail.assert_not_called()
        self.assertEqual(observed[0], observed[1])
        self.assertEqual(sum(call.startswith("register:") for call in observed[0]), 10)

    def test_pages_detail_contract_is_guarded_and_preserves_synchronous_calls(self):
        source = (REPO / "UmiOCR-data/qt_res/qml/TabPages/PagesManager.qml").read_text("utf-8")
        lines = [line.strip() for line in source.splitlines() if "UmiStartupTrace.detail(" in line]
        self.assertEqual(len(lines), 7)
        for line in lines:
            self.assertTrue(line.startswith('if(typeof UmiStartupTrace !== "undefined") '))
            name, phase = re.search(r'\.detail\("([^"]+)", "([^"]+)"', line).groups()
            self.assertIn(name, trace.DETAIL_NAMES)
            self.assertIn(phase, {"begin", "end"})
        for name, operation in (("page-create-component", "Qt.createComponent(url)"),
                                ("page-create-object", "comp.createObject(pagesNest, properties)")):
            self.assertLess(source.index('detail("' + name + '", "begin"'), source.index(operation))
            self.assertLess(source.index(operation), source.index('detail("' + name + '", "end"'))
        self.assertLess(source.index("if(info.comp) return info.comp"), source.index('detail("page-create-component", "begin"'))
        begin = source.index('detail("page-controller", "begin"')
        for operation in ("connector.addPage(info.key)", "connector.addSimplePage(info.key)"):
            call = source.index(operation)
            self.assertLess(begin, call)
            self.assertLess(call, source.index('detail("page-controller", "end"', call))
        self.assertLess(source.index('detail("page-controller", "end"'), source.index("if(!ctrlKey)"))
        self.assertNotIn("Qt.callLater", source)
        self.assertNotIn("Timer {", source)

    def fake_artifact(self):
        root = self.root / "artifact"
        (root / "UmiOCR-data").mkdir(parents=True)
        (root / "Umi-OCR.exe").write_bytes(b"unit fixture, never executable")
        (root / "UmiOCR-data/main.py").write_text("# unit fixture\n", "utf-8")
        return root / "Umi-OCR.exe"

    def test_release_and_boundary_root_are_refused(self):
        for path in (REPO / "release/Umi-OCR/Umi-OCR.exe", TMP, REPO / "build/staging/not-authorized/Umi-OCR.exe"):
            with self.assertRaises(RuntimeError):
                bench.checked_path(path, TMP)

    def test_prepare_is_new_state_only_and_defaults_to_no_http(self):
        executable = self.fake_artifact()
        args = argparse.Namespace(artifact=str(executable), identity="unit-baseline", http=False)
        with mock.patch.object(bench, "running_in", return_value=[]), mock.patch.object(subprocess, "Popen", side_effect=AssertionError("prepare launched a process")):
            result = bench.prepare(args)
            self.assertEqual(result["status"], "PREPARED_NOT_RUN")
            self.assertFalse(result["http"])
            self.assertIn("server.enable=false", (executable.parent / "UmiOCR-data/.settings").read_text("utf-8"))
            self.assertEqual(bench.load_owner(executable)["identity"], "unit-baseline")
            with self.assertRaises(RuntimeError):
                bench.prepare(args)

    def test_prepare_does_not_adopt_or_backup_existing_state(self):
        executable = self.fake_artifact()
        settings = executable.parent / "UmiOCR-data/.settings"
        settings.write_bytes(b"existing-state-must-survive")
        args = argparse.Namespace(artifact=str(executable), identity="unit", http=True)
        with mock.patch.object(bench, "running_in", return_value=[]):
            with self.assertRaises(RuntimeError):
                bench.prepare(args)
        self.assertEqual(settings.read_bytes(), b"existing-state-must-survive")
        self.assertFalse((executable.parent / bench.OWNER).exists())

    def test_measurement_needs_separate_explicit_execution_flag(self):
        with mock.patch.object(subprocess, "Popen", side_effect=AssertionError("unapproved launch")):
            with self.assertRaises(RuntimeError):
                bench.measure(argparse.Namespace(execute_authorized=False))

    def test_http_never_addresses_existing_release_pid(self):
        with mock.patch.object(bench, "listening_pids", return_value={33836}), mock.patch.object(bench.urllib.request, "build_opener") as opener:
            with self.assertRaises(RuntimeError):
                bench.own_command(12345, 1224, ["--quit"])
            opener.assert_not_called()

    def test_timeout_requests_normal_close_but_never_terminates(self):
        executable = self.fake_artifact()
        output = self.root / "unit-timeout"
        output.mkdir()
        process = mock.Mock(pid=12345)
        process.poll.return_value = None
        process.wait.side_effect = subprocess.TimeoutExpired("fake-exe", 1)
        with mock.patch.object(bench, "assert_idle"), mock.patch.object(bench, "verify_state"), mock.patch.object(bench, "collect_events", return_value=[]), mock.patch.object(bench, "find_owned_startup_error", return_value=None), mock.patch.object(subprocess, "Popen", return_value=process), mock.patch.object(bench, "window_message") as message:
            result = bench.sample(executable, {"http": False}, output, 0, 0, 0, 1)
        message.assert_called_once_with(12345, close=True)
        process.terminate.assert_not_called()
        process.kill.assert_not_called()
        self.assertEqual(result["leftRunningPid"], 12345)
        self.assertFalse(result["normalExit"])
        self.assertEqual(result["status"], "FAIL")

    def test_trace_reader_ignores_only_incomplete_tail_and_checks_identity(self):
        path = self.root / "reader.jsonl"
        event = {"format": "umi-startup-trace-v1", "pid": 123, "runId": "unit", "clock": "windows-perf-counter-ns", "event": "S0", "t_ns": 1}
        path.write_bytes(json.dumps(event).encode() + b"\n{unfinished")
        self.assertEqual(bench.collect_events(path, 123, "unit"), [event])
        with self.assertRaises(RuntimeError):
            bench.collect_events(path, 33836, "unit")

    def test_normal_entry_guards_observer_and_bootstraps_archives_before_qt(self):
        tree = ast.parse((REPO / "UmiOCR-data/main.py").read_text("utf-8"))
        imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        helper = next(node for node in imports if node.module == "runtime_archive_bootstrap")
        qt = next(node for node in imports if node.module == "PySide6.QtCore")
        self.assertLess(helper.lineno, qt.lineno)
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "prepare_archives"]
        self.assertEqual(len(calls), 1)
        self.assertEqual([(item.arg, item.value.value) for item in calls[0].keywords], [("kind", "host")])
        observer_import = next(node for node in imports if node.module == "py_src.utils.startup_trace")
        guards = [node for node in ast.walk(tree) if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "traceRequested"]
        self.assertTrue(any(observer_import in list(ast.walk(guard)) for guard in guards))
        ast.parse((REPO / "UmiOCR-data/py_src/run.py").read_text("utf-8"))

    def test_isolated_settings_drift_is_not_silently_repaired(self):
        executable = self.fake_artifact()
        args = argparse.Namespace(artifact=str(executable), identity="unit-drift", http=False)
        with mock.patch.object(bench, "running_in", return_value=[]):
            bench.prepare(args)
        settings = executable.parent / "UmiOCR-data/.settings"
        changed = settings.read_text("utf-8").replace("warmupMode=lazy", "warmupMode=delayed")
        settings.write_text(changed, "utf-8")
        with self.assertRaises(RuntimeError):
            bench.load_owner(executable)
        self.assertEqual(settings.read_text("utf-8"), changed)

    def test_error_fixture_captures_static_text_without_reading_other_pid(self):
        windows = DialogFixture()
        evidence = bench.find_owned_startup_error(12345, windows=windows)
        self.assertEqual(evidence["dialog"]["hwnd"], 30)
        self.assertEqual(evidence["staticTexts"], ["ModuleNotFoundError: runtime_archive_bootstrap"])
        self.assertNotIn(10, windows.reads)
        self.assertEqual(windows.clicks, [])
        windows.rows[30]["text"] = "Unrecognized Umi-OCR title"
        self.assertIsNone(bench.find_owned_startup_error(12345, windows=windows))

    def test_error_fixture_clicks_only_revalidated_standard_idok(self):
        for label in bench.OK_LABELS:
            with self.subTest(label=label):
                windows = DialogFixture()
                windows.rows[32]["text"] = label
                evidence = bench.find_owned_startup_error(12345, windows=windows)
                result = bench.dismiss_owned_startup_error(12345, evidence, windows=windows)
                self.assertEqual(windows.clicks, [32])
                self.assertEqual((result["message"], result["flags"], result["timeoutMs"]), (0xF5, 2, 2000))

    def test_changed_error_or_unknown_button_is_evidence_only(self):
        changes = [(30, "pid", 33836), (30, "class", "Unknown"), (30, "text", "Other title"),
                   (32, "pid", 33836), (32, "parent", 20), (32, "class", "Unknown"),
                   (32, "controlId", 2), (32, "text", "Cancel"), (32, "visible", False), (32, "enabled", False)]
        for hwnd, key, value in changes:
            with self.subTest(hwnd=hwnd, key=key):
                windows = DialogFixture()
                evidence = bench.find_owned_startup_error(12345, windows=windows)
                windows.rows[hwnd][key] = value
                with self.assertRaises(RuntimeError):
                    bench.dismiss_owned_startup_error(12345, evidence, windows=windows)
                self.assertEqual(windows.clicks, [])

    def test_native_ok_method_uses_bm_click_with_finite_send_timeout(self):
        windows = bench._DialogWindows.__new__(bench._DialogWindows)
        windows.user = mock.Mock()
        windows.user.SendMessageTimeoutW.return_value = 1
        windows.click_ok(32)
        arguments = windows.user.SendMessageTimeoutW.call_args.args
        self.assertEqual(arguments[:6], (32, 0xF5, 0, 0, 2, 2000))
        self.assertEqual(len(arguments), 7)
        windows.user.SendMessageW.assert_not_called()
        windows.user.SendMessageTimeoutW.return_value = 0
        with self.assertRaises(RuntimeError):
            windows.click_ok(32)

    def test_error_dialog_is_normal_acknowledged_but_sample_stays_failed(self):
        executable = self.fake_artifact()
        output = self.root / "unit-error-dialog"
        output.mkdir()
        windows = DialogFixture()
        evidence = bench.find_owned_startup_error(12345, windows=windows)
        process = mock.Mock(pid=12345)
        process.poll.return_value = None
        def exited(*_a, **_k):
            process.poll.return_value = 0
            return 0
        process.wait.side_effect = exited
        real_acknowledge = bench.dismiss_owned_startup_error
        def acknowledge(pid, observed):
            return real_acknowledge(pid, observed, windows=windows)
        with mock.patch.object(bench, "assert_idle"), mock.patch.object(bench, "verify_state"), mock.patch.object(bench, "running_in", return_value=[]), mock.patch.object(bench, "collect_events", return_value=[]), mock.patch.object(bench, "find_owned_startup_error", return_value=evidence), mock.patch.object(bench, "dismiss_owned_startup_error", side_effect=acknowledge), mock.patch.object(subprocess, "Popen", return_value=process), mock.patch.object(bench, "window_message") as normal_window:
            result = bench.sample(executable, {"http": False}, output, 0, 1, 0, 1)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["normalExit"])
        self.assertEqual(result["startupErrorDialog"]["staticTexts"], evidence["staticTexts"])
        self.assertEqual(windows.clicks, [32])
        normal_window.assert_not_called()
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    def test_benchmark_fingerprint_is_written_before_any_sample(self):
        executable = self.fake_artifact()
        with mock.patch.object(bench, "running_in", return_value=[]):
            bench.prepare(argparse.Namespace(artifact=str(executable), identity="unit-fingerprint", http=False))
        audit = self.root / "audit"
        output = audit / "unit-driver-fingerprint"
        args = argparse.Namespace(execute_authorized=True, artifact=str(executable), output=str(output),
                                  warmups=0, samples=1, timeout=1, exit_timeout=1, dwell=0)
        expected = bench.hashlib.sha256(Path(bench.__file__).read_bytes()).hexdigest()
        def observed_sample(*_a, **_k):
            inputs = json.loads((output / "inputs.json").read_text("utf-8"))
            self.assertEqual(inputs["benchmarkSha256"], expected)
            self.assertEqual(inputs["benchmarkPath"], str(Path(bench.__file__).resolve()))
            return {"status": "PASS", "interactiveMs": 1.0, "normalExit": True}
        with mock.patch.object(bench, "AUDIT_ROOT", audit), mock.patch.object(bench, "running_in", return_value=[]), mock.patch.object(bench, "sample", side_effect=observed_sample):
            result = bench.measure(args)
        self.assertEqual(result["status"], "PASS")

    def test_parameter_self_check_does_not_launch_or_initialize_qt(self):
        with mock.patch.object(subprocess, "Popen", side_effect=AssertionError("self-check launched")), mock.patch("builtins.print") as printed:
            self.assertEqual(bench.main(["self-check"]), 0)
        result = json.loads(printed.call_args.args[0])
        self.assertFalse(result["guiStarted"])
        self.assertFalse(result["defaultHttp"])


if __name__ == "__main__":
    unittest.main()
