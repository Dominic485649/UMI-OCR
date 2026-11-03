"""Directed, package-Python native Qt UI acceptance for a fresh Stored candidate.

Prepare only (no Qt/window/process):
  <portable-python> -I -B -X utf8 test_stored_native_ui.py --self-test --output <new-audit-dir>
Run only after the coordinator provides a fresh copy and execution window:
  <root>/UmiOCR-data/runtime/python.exe -I -B -X utf8 test_stored_native_ui.py
    --root <this-project/build/tmp-or-staging/fresh-copy> --output <new-audit-dir>
    --profile base|combined|navigation --execute-authorized

This runs the candidate's main/initRuntimeEnvironment/py_src.run and real Qt,
NOT Umi-OCR.exe or an EXE performance measurement. No source sandbox is mounted.
A reported test-only Event barrier holds the original packaged diagnostic
collector until a pending About frame/copy has been observed. No diagnostic
values are synthesized. Clipboard writes are captured at the packaged text
utility; the user's clipboard is never read or written. No inference is run.
"""

import argparse
import ast
import ctypes
import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import re
import runpy
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unittest
from unittest import mock
import zipfile


REPO = Path(__file__).resolve().parents[1]
PP, VL = "win32_PaddleOCRv6_CUDA", "win32_PaddleOCRVL_1_6"
LANGUAGES = ("zh_CN", "zh_TW", "en_US", "ja_JP", "pt", "ru_RU", "ta")
ABOUT_KEYS = ("正在后台采集系统信息…", "系统信息采集失败：%1", "系统信息采集已取消")
FORBIDDEN = frozenset({"paddle", "paddleocr", "paddlex", "openai", "onnxruntime", "torch", "transformers"})
MEMBERS = ("py_src/run.py", "py_src/imports/umi_about.py", "py_src/utils/system_info.py",
    "py_src/utils/i18n_configs.py", "py_src/utils/utils.py", "py_src/utils/utils_connector.py",
    "py_src/utils/cuda_device_probe.py", "py_src/utils/_cuda_device_probe_worker.py")
QML = ("Main.qml", "TabPages/About/About.qml", "TabPages/Navigation/Navigation.qml", "Configs/GlobalConfigs.qml",
    "TabPages/GlobalConfigsPage/GlobalConfigsPage.qml", "Configs/NvidiaDeviceConfig.qml")
REQUIRED = ("package_provenance", "first_frame", "about.pending", "about.ready", "about.copy",
    "languages", "model_settings", "no_models", "normal_exit", "payload_unchanged", "settings_restored")
_HARNESS = {}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def harness(name):
    files = {"old": "test_model_settings_native_ui.py", "scheduler": "test_hot_ui.py",
             "translations": "test_startup_system_info_i18n.py"}
    if name not in _HARNESS:
        _HARNESS[name] = load("stored_ui_harness_" + name, Path(__file__).with_name(files[name]))
    return _HARNESS[name]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(path):
    return harness("old").sha256(path)


def write_new(path, value):
    harness("old").write_new_json(path, value)


def plain(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.exists() and harness("old").reparse(part):
            raise ValueError("Link/junction is not allowed: " + str(part))
    return path.resolve()


def pristine(data, *, allow_owner=False):
    # Existing configuration is always refused without reading it. Only a
    # separately verified original owner marker may survive a controlled retry.
    names = harness("old").SETTINGS_NAMES if allow_owner else (*harness("old").SETTINGS_NAMES, ".stored-native-ui-owner.json")
    for name in names:
        path = Path(data) / name
        plain(path)
        if os.path.lexists(path):
            raise ValueError("Fresh copy required; existing configuration is not read: " + str(path))


def prior_safety_gate(record, *, report_sha256=None):
    """Preserve incomplete/failed history; never make it a retrospective PASS.

    Two exact old driver failures have a narrowly pinned retry path. All other
    records must have completed their no-model check. The caller separately
    requires normal exit, restored absence and identical execution inputs.
    """
    blocks = record.get("safety_blocks", [])
    status = record.get("checks", {}).get("no_models", {})
    if not blocks and status.get("status") == "PASS":
        return {"mode": "previous-no-models-PASS"}
    incomplete_sha = "b3b4b92d68ed6179bb99a1b38b39c48473f4503933745d269bf107033a70eefc"
    launches = record.get("allowed_nvidia_launches", [])
    incomplete = (report_sha256 == incomplete_sha
        and record.get("driverSha256") == "24a917df4a076e3ae68fc282a2862e9f045772fed170875cd5d0a49cc72d8fc3"
        and blocks == [] and status.get("status") == "NOT_RUN"
        and record.get("checks", {}).get("model_settings", {}).get("reason")
            == "libshiboken: Internal C++ object (PySide6.QtQuick.QQuickItem) already deleted."
        and len(launches) == 1 and launches[0].get("argv_sha256")
            == "4042c9bbdace9d48f3109af790123011f58faefb487256f4231800b4a825c11d")
    if incomplete:
        return {"mode": "pinned-restored-driver-failure-before-no-model-check",
                "originalStatus": "NOT_RUN", "originalReportSha256": incomplete_sha,
                "modelServiceStatePreviouslyVerified": False, "oldFailurePreserved": True}
    legacy = "e9ecd134af93d7b1c40ba4146201ad5d3fc3de588d33b0bf8c82bd8a140f5adb"
    refused_only = (record.get("driverSha256") == legacy and isinstance(blocks, list) and blocks
        and all(isinstance(block, dict) and block.get("kind") == "subprocess" and block.get("executable") == "None" for block in blocks)
        and record.get("allowed_nvidia_launches") == [] and status.get("status") == "FAIL" and status.get("blocked") == blocks)
    require(refused_only, "Previous no-model guard did not pass and is not the pinned pre-CreateProcess driver refusal")
    return {"mode": "pinned-driver-refused-all-child-creation", "originalStatus": "FAIL",
            "originalDriverSha256": legacy, "blockedAttempts": len(blocks), "oldFailurePreserved": True}


def verify_owned_reuse(root, previous_path, profile, current_inputs, *, audit_root=None):
    """Read only this driver's marker/audit records, never adopt existing settings."""
    root = plain(root)
    pristine(root / "UmiOCR-data", allow_owner=True)
    audit_root = plain(audit_root or REPO / "build/audit")
    marker = plain(root / "UmiOCR-data/.stored-native-ui-owner.json")
    owner = json.loads(marker.read_text("utf-8"))
    require(owner.get("schema") == 1 and plain(owner["root"]) == root, "Unrecognized owner marker")
    previous_path = plain(previous_path)
    initial_path = plain(Path(owner["output"]) / "report.json")
    for path in (previous_path, initial_path):
        require(path.is_relative_to(audit_root) and path.is_file(), "Owned retry evidence must exist inside this project's audit root")
    previous = json.loads(previous_path.read_text("utf-8"))
    initial = json.loads(initial_path.read_text("utf-8"))
    require(initial.get("driverSha256") == owner.get("driverSha256"), "Owner marker and original driver evidence disagree")
    safety_gates = []
    for label, record, path in (("original", initial, initial_path), ("previous", previous, previous_path)):
        require(record.get("mode") == "candidate-python-native-qt-not-exe" and plain(record["root"]) == root
                and record.get("profile") == profile, "Retry evidence refers to another candidate/profile")
        require(record.get("normal_exit") is True, "Previous candidate did not safely exit")
        restored = record.get("checks", {}).get("settings_restored", {})
        stable = record.get("checks", {}).get("payload_unchanged", {})
        require(restored.get("status") == "PASS" and restored.get("absent_before") is True
                and restored.get("restored_absence") is True, "Previous state was not restored to complete absence")
        require(stable.get("status") == "PASS" and stable.get("input_sha256_after") == record.get("input_sha256")
                == current_inputs and current_inputs, "Candidate payload changed before/during/after the previous run")
        safety_gates.append({"report": label, **prior_safety_gate(record, report_sha256=sha(path))})
    return {"marker": str(marker), "markerSha256": sha(marker), "originalReport": str(initial_path),
            "originalReportSha256": sha(initial_path), "previousReport": str(previous_path),
            "previousReportSha256": sha(previous_path), "same_payload_verified": True,
            "configuration_absent": True, "owner_marker_preserved": True, "previous_safety_evidence": safety_gates}


def isolated_runtime(root):
    expected = plain(Path(root) / "UmiOCR-data/runtime/python.exe")
    require(plain(sys.executable) == expected, "Use the candidate's own runtime/python.exe")
    require(sys.flags.isolated and sys.flags.dont_write_bytecode, "Native execution requires -I -B")
    require(sys.version.split()[0] == "3.13.16", "This acceptance requires CPython 3.13.16")


def bootstrap_literal(source):
    tree = ast.parse(source)
    values = [node.value.value for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_WORKER_BOOTSTRAP" for target in node.targets)
        and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)]
    require(len(values) == 1, "Cannot bind the packaged NVIDIA probe bootstrap")
    return values[0]


def allowed_probe(executable, argv, cwd, root, bootstrap):
    """One bound NVIDIA command, including CPython's Windows audit encoding.

    Windows reports executable=None and an already serialized command line.
    Never parse/generalize that string: compare the entire list2cmdline value.
    """
    data = Path(root) / "UmiOCR-data"
    expected = [str(data / "runtime/python.exe"), "-I", "-B", "-X", "utf8", "-u", "-c", bootstrap, str(data / "app.zip")]
    try:
        if executable is not None and (not Path(executable).is_absolute() or plain(executable) != plain(expected[0])):
            return False
        if cwd is None or not Path(cwd).is_absolute() or plain(cwd) != plain(data):
            return False
        if isinstance(argv, str):
            return argv == subprocess.list2cmdline(expected)
        if not isinstance(argv, (list, tuple)) or len(argv) != 9 or not all(isinstance(arg, str) for arg in argv):
            return False
        return (Path(argv[0]).is_absolute() and plain(argv[0]) == plain(expected[0])
            and list(argv[1:7]) == expected[1:7] and argv[7] == bootstrap
            and Path(argv[8]).is_absolute() and plain(argv[8]) == plain(expected[8]))
    except (OSError, ValueError, TypeError):
        return False


def member_origin(origin, data):
    prefix = str(Path(data) / "app.zip").replace("\\", "/") + "/"
    value = str(origin).replace("\\", "/")
    if not value.casefold().startswith(prefix.casefold()):
        raise ValueError("Application module is not from the candidate app.zip: " + value)
    member = value[len(prefix):]
    if not member.startswith("py_src/") or ".." in Path(member).parts or "\\" in member:
        raise ValueError("Invalid application member origin: " + member)
    return member


def bind_archive(root, audited):
    data = Path(root) / "UmiOCR-data"
    require(audited.get("status") == "PASS" and audited.get("kind") == "host", "Host container audit must PASS")
    require(plain(audited["root"]) == plain(data), "Container audit refers to another candidate")
    snapshot_path = plain(Path(root) / "source-snapshot.json")
    snapshot = json.loads(snapshot_path.read_text("utf-8"))
    approved = {item["path"]: item["sha256"] for item in audited["members"]}
    bound = {}
    with zipfile.ZipFile(plain(data / "app.zip")) as archive:
        for member in MEMBERS:
            payload = archive.read(member)
            checksum = hashlib.sha256(payload).hexdigest()
            require(archive.getinfo(member).compress_type == zipfile.ZIP_STORED, member)
            require(approved.get(member) == checksum == snapshot.get("host/UmiOCR-data/" + member),
                    "App member is not bound to the container audit/canonical source: " + member)
            bound[member] = checksum
        bootstrap = bootstrap_literal(archive.read("py_src/utils/cuda_device_probe.py").decode("utf-8"))
    require(sha(data / "main.py") == snapshot.get("host/UmiOCR-data/main.py"), "main.py does not match canonical source")
    for code in LANGUAGES[1:]:
        relative = "i18n/" + code + ".qm"
        require(sha(plain(data / relative)) == snapshot.get("host/UmiOCR-data/" + relative), "Unbound translation: " + code)
    return {"sourceSnapshotSha256": sha(snapshot_path), "members": bound, "snapshot": snapshot,
            "bootstrap": bootstrap}


def payload_hashes(root):
    root = Path(root)
    data = root / "UmiOCR-data"
    paths = [root / "Umi-OCR.exe", root / "source-snapshot.json"]
    paths += [data / name for name in ("main.py", "app.zip", "dependencies.zip", "ui.rcc", "about.json",
        "runtime/python.exe", "runtime_archive_bootstrap.py", "runtime-archives.json", "runtime-archive-inputs.json")]
    paths += sorted((data / "i18n").glob("*.qm"))
    paths += sorted((data / "plugins").glob("*/umi-plugin.json"))
    paths += sorted((data / "plugins").glob("*/runtime-archives.json"))
    paths += sorted((data / "plugins").glob("*/vendor.zip"))
    return {str(plain(path)): sha(path) for path in paths if path.is_file()}


def rule_hashes():
    files = [Path(__file__), Path(__file__).with_name("test_navigation_repository_link.py"),
             Path(__file__).with_name("test_model_settings_native_ui.py"),
             Path(__file__).with_name("test_hot_ui.py"), Path(__file__).with_name("test_startup_system_info_i18n.py"),
             REPO / "build/tools/audit_runtime_archives.py", REPO / "build/tools/runtime_archive_layout.py"]
    return {str(path): sha(path) for path in files}


def audit_containers(root, output):
    saved = list(sys.path)
    try:
        tool = load("stored_ui_archive_audit", REPO / "build/tools/audit_runtime_archives.py")
        host = tool.audit(Path(root) / "UmiOCR-data")
        write_new(output / "container-host.json", host)
        plugins = []
        for declaration in sorted((Path(root) / "UmiOCR-data/plugins").glob("*/runtime-archives.json")):
            record = tool.audit(declaration.parent)
            require(record["status"] == "PASS", "Declared plugin container did not PASS")
            path = output / ("container-" + declaration.parent.name + ".json")
            write_new(path, record)
            plugins.append({"path": str(path), "sha256": sha(path)})
        return host, {"host": {"path": str(output / "container-host.json"), "sha256": sha(output / "container-host.json")}, "plugins": plugins}
    finally:
        # Audit helpers are not application search roots.
        sys.path[:] = saved


def acceptance(report):
    checks = report.get("checks", {})
    required = tuple(key for key in REQUIRED if report.get("profile") != "navigation" or key != "model_settings")
    missing = [key for key in required if checks.get(key, {}).get("status") != "PASS"]
    if report.get("profile") == "combined" and checks.get("task_sources", {}).get("status") != "PASS":
        missing.append("task_sources")
    if report.get("homepage_repository_required") or report.get("profile") == "navigation":
        homepage = checks.get("navigation_repository", {})
        languages = homepage.get("languages", [])
        if (homepage.get("status") != "PASS" or len(languages) != len(LANGUAGES)
                or {item.get("code") for item in languages} != set(LANGUAGES)
                or any(item.get("visible_link", {}).get("fully_visible") is not True
                    or item.get("visible_link", {}).get("rendered_target") != "https://github.com/Dominic485649/UMI-OCR"
                    for item in languages)):
            missing.append("navigation_repository")
    failed = [key for key, value in checks.items() if value.get("status") == "FAIL"]
    okay = (report.get("scenario_completed") is True and report.get("normal_exit") is True
            and not missing and not failed and not report.get("errors") and not report.get("safety_blocks"))
    return {"status": "PASS" if okay else "INCOMPLETE", "required_not_passed": missing, "failed": failed}


def native(args, output):
    old, scheduler = harness("old"), harness("scheduler")
    root = old.checked_root(args.root)
    isolated_runtime(root)
    data = root / "UmiOCR-data"
    occupied = old.candidate_processes(root)
    require(not occupied["candidate_processes"], "Candidate is occupied: " + str(occupied))
    reuse = None
    if args.reuse_owned_run:
        pristine(data, allow_owner=True)
        reuse = verify_owned_reuse(root, args.reuse_owned_run, args.profile, payload_hashes(root))
    else:
        pristine(data)
    snapshot = old.SettingsSnapshot(data)  # All settings are absent, never reads user settings.
    output.mkdir(parents=True, exist_ok=False)
    report = {"mode": "candidate-python-native-qt-not-exe", "profile": args.profile,
        "root": str(root), "pythonExecutable": sys.executable, "pythonVersion": sys.version,
        "driverSha256": sha(__file__), "harness_sha256": rule_hashes(), "process_preflight": occupied, "checks": {}, "errors": [],
        "screenshots": [], "copies": [], "safety_blocks": [], "allowed_nvidia_launches": [],
        "diagnostic_states": [], "control_events": [], "owned_reuse": reuse, "scenario_completed": False, "normal_exit": False,
        "instrumentation": {"diagnostic_barrier": "test-only Event before original packaged collectSystemInfo; released after pending frame/copy; no synthesized values",
                            "clipboard": "packaged utils.copyText captures only this scenario's About text; no clipboard read/write"},
        "limits": ["Not Umi-OCR.exe or an EXE/startup performance result", "No inference or model requests"],
        "homepage_repository_required": bool(getattr(args, "check_homepage", False) or args.profile == "navigation")}
    report["checks"] = {key: {"status": "NOT_RUN"} for key in (*REQUIRED, "task_sources")}
    engines, release = [], threading.Event()
    app = previous_engine = finder = None
    restore_callbacks = []
    def check(key, status="PASS", **details):
        report["checks"][key] = {"status": status, **details}
    try:
        host_audit, audit_refs = audit_containers(root, output)
        binding = bind_archive(root, host_audit)
        report["container_audits"] = audit_refs
        report["input_sha256"] = payload_hashes(root)
        report["canonical_binding"] = {key: binding[key] for key in ("sourceSnapshotSha256", "members")}
        if reuse is None:
            write_new(data / ".stored-native-ui-owner.json", {"schema": 1, "pid": os.getpid(), "root": str(root), "output": str(output), "driverSha256": report["driverSha256"]})
        class NoModels(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if FORBIDDEN.intersection(fullname.split(".")):
                    report["safety_blocks"].append({"kind": "model_import", "module": fullname})
                    raise RuntimeError("Native UI acceptance must not import inference: " + fullname)
                return None
        finder = NoModels()
        sys.meta_path.insert(0, finder)
        def audit_hook(event, values):
            if event != "subprocess.Popen":
                return
            executable, argv, cwd, _env = values
            if len(report["allowed_nvidia_launches"]) < 8 and allowed_probe(executable, argv, cwd, root, binding["bootstrap"]):
                report["allowed_nvidia_launches"].append({"executable": str(data / "runtime/python.exe"),
                    "audit_executable_field": str(executable), "argv_format": type(argv).__name__,
                    "argv_sha256": hashlib.sha256(json.dumps(argv).encode()).hexdigest(), "cwd": str(cwd),
                    "purpose": "one exact bound package NVIDIA command only"})
                return
            report["safety_blocks"].append({"kind": "subprocess", "executable": str(executable)[:300],
                "argv_format": type(argv).__name__, "argv_sha256": hashlib.sha256(json.dumps(argv, default=str).encode()).hexdigest(),
                "cwd": str(cwd)})
            raise RuntimeError("Only the exact audited package NVIDIA probe command is allowed")
        sys.addaudithook(audit_hook)
        os.environ["QML_DISABLE_DISK_CACHE"] = "1"
        for key in ("UMI_STARTUP_TRACE", "UMI_STARTUP_RUN_ID", "UMI_STARTUP_S0_NS"):
            os.environ.pop(key, None)
        namespace = runpy.run_path(str(data / "main.py"), run_name="stored_ui_candidate_bootstrap")
        namespace["initRuntimeEnvironment"]()
        os.MessageBox = lambda message, *a, **kw: report["errors"].append("Candidate startup diagnostic: " + str(message))
        from PySide6 import QtQml
        from PySide6.QtCore import QCoreApplication, QEvent, QFile, QIODevice, QPoint, QPointF, QRectF, QSettings, QTimer, Qt
        from PySide6.QtGui import QKeyEvent, QMouseEvent, QTextCursor
        from PySide6.QtQml import QQmlEngine, QQmlExpression
        from PySide6.QtQuick import QQuickTextDocument
        from PySide6.QtWidgets import QApplication
        try:
            from PySide6.QtTest import QTest
            report["event_driver"] = "candidate QtTest QWindow mouse/key events"
        except ImportError:
            QTest = None
            report["event_driver"] = "candidate QtCore.sendEvent + QtGui mouse/key press/release; QtTest is not in the product Qt whitelist"
        import umi_about
        from py_src.utils import utils as packaged_utils
        original_collect, original_copy = umi_about.collectSystemInfo, packaged_utils.copyText
        def collect(startupTrace=None):
            if not release.wait(60):
                raise RuntimeError("UI acceptance diagnostic barrier expired")
            return original_collect(startupTrace=startupTrace)
        def copy_text(text):
            require(len(report["copies"]) < 16 and len(text) <= 65536, "Copy capture exceeded the directed budget")
            report["copies"].append(str(text))
        umi_about.collectSystemInfo, packaged_utils.copyText = collect, copy_text
        restore_callbacks += [lambda: setattr(umi_about, "collectSystemInfo", original_collect),
                              lambda: setattr(packaged_utils, "copyText", original_copy)]
        settings = QSettings(str(data / ".settings"), QSettings.Format.IniFormat)
        settings.setFallbacksEnabled(False)
        for key, value in {"Global/server.enable": False, "Global/ocr.lifecycle.warmupMode": "lazy",
            "Global/ocr.lifecycle.cleanupPolicy": "never", "Global/window.startupInvisible": False,
            "Global/window.messageMemory": ["globalConfigsKey"], "Global/window.simpleNotificationType": "none",
            "Global/window.closeWin2Hide": False, "TabPageManager/openPageList": ["Navigation", "About"],
            "TabPageManager/showPageIndex": 1, "ScreenshotOCR/hotkey.screenshot": "",
            "ScreenshotOCR/hotkey.paste": "", "ScreenshotOCR/hotkey.reScreenshot": ""}.items():
            settings.setValue(key, value)
        settings.sync()
        require(settings.status() == QSettings.Status.NoError, "Cannot prepare isolated candidate settings")
        del settings
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        write_new(data / ".pre_settings", {"i18n": "zh_CN", "opengl": "", "server_port": port, "last_pid": -1, "last_ptime": -1})
        if (data / "plugins").is_dir():
            write_new(data / "plugins/.plugins_state", {})
        previous_engine = QtQml.QQmlApplicationEngine
        class Engine(previous_engine):
            def load(self, *values):
                super().load(*values)
                engines.append(self)
                require(bool(self.rootObjects()), "Candidate did not create a real QML root")
                window = self.rootObjects()[0]
                info = self.rootContext().contextProperty("UmiSystemInfo")
                require(info is not None and info.property("state") == "pending", "Dedicated info provider was not pending before collection")
                self.done, self.begun, self.active = False, False, "first_frame"
                def remember():
                    report["diagnostic_states"].append({"state": info.property("state"), "info": str(info.property("infoJson"))})
                remember()
                info.stateChanged.connect(remember)
                def js(code, obj=window):
                    expression = QQmlExpression(QQmlEngine.contextForObject(obj), obj, code)
                    value = expression.evaluate()
                    if expression.hasError():
                        raise old.ProbeUnavailable(expression.error().toString())
                    if isinstance(value, tuple): value = value[0]
                    return value.toVariant() if hasattr(value, "toVariant") else value
                def jjson(code, obj=window):
                    value = js("JSON.stringify(" + code + ")", obj)
                    require(isinstance(value, str), "Runtime expression could not be serialized")
                    return json.loads(value)
                def activate(key):
                    value = js("qmlapp.tab.openTabPageByKey(" + json.dumps(key) + ")")
                    require(value is not None, "Candidate page was not created: " + key)
                    return value
                def settled():
                    return bool(js("qmlapp.globalConfigs.applyPhase===0 && !qmlapp.globalConfigs.backendApplyPending && !qmlapp.globalConfigs.pluginRefreshPending && !qmlapp.globalConfigs.ocrManager.applying && !qmlapp.globalConfigs.documentManager.applying && !qmlapp.msnConnector.isBusy()"))
                def wait(predicate, label, timeout=15):
                    yield from scheduler.wait_transition(predicate, timeout=timeout, label=label)
                def descendants(obj):
                    pending = [obj]
                    while pending:
                        item = pending.pop(0)
                        yield item
                        pending.extend(item.childItems())
                def exposed(item):
                    if not item.property("visible") or item.width() <= 0 or item.height() <= 0:
                        return False
                    point = item.mapToScene(QPointF(item.width()/2, item.height()/2))
                    if not (0 <= point.x() < window.width() and 0 <= point.y() < window.height()):
                        return False
                    parent = item
                    while parent is not None:
                        if not parent.property("visible") or float(parent.property("opacity") or 0) < 0.9:
                            return False
                        if parent.property("clip") and not parent.boundingRect().contains(parent.mapFromScene(point)):
                            return False
                        parent = parent.parentItem()
                    return True
                def visible_area(item, rect=None):
                    area = item.mapRectToScene(item.boundingRect() if rect is None else rect)
                    area = area.intersected(QRectF(0, 0, window.width(), window.height()))
                    parent = item
                    while parent is not None and not area.isEmpty():
                        if not parent.property("visible") or float(parent.property("opacity") or 0) < 0.9:
                            return QRectF()
                        if parent.property("clip"):
                            area = area.intersected(parent.mapRectToScene(parent.boundingRect()))
                        parent = parent.parentItem()
                    return area
                def texts(obj):
                    return [str(item.property("text")) for item in descendants(obj)
                        if item.metaObject().indexOfProperty("text") >= 0 and not visible_area(item).isEmpty()]
                def homepage_link(home, label, target):
                    editors = [item for item in descendants(home)
                        if all(item.metaObject().indexOfProperty(name) >= 0 for name in ("text", "length", "readOnly"))
                        and label in str(item.property("text")) and target in str(item.property("text"))]
                    require(len(editors) == 1, "首页仓库链接必须来自唯一的真实 Markdown TextEdit")
                    editor, scrolls = editors[0], []
                    wrapper = editor.property("textDocument")
                    require(isinstance(wrapper, QQuickTextDocument), "首页缺少真实 QQuickTextDocument")
                    document = wrapper.textDocument()
                    selection = document.find(label)
                    require(not selection.isNull(), "首页实际文档没有完整仓库链接译文")
                    start, end = selection.selectionStart(), selection.selectionEnd()
                    for position in range(start, end):
                        cursor = QTextCursor(document)
                        cursor.setPosition(position)
                        cursor.setPosition(position + 1, QTextCursor.MoveMode.KeepAnchor)
                        require(cursor.charFormat().isAnchor() and cursor.charFormat().anchorHref() == target,
                            "首页实际文档的逐字符锚点目标不一致")
                    for attempt in range(3):
                        chars = jjson("(function(){var a=[];for(var i=" + str(start) + ";i<" + str(end)
                            + ";i++){var r=positionToRectangle(i);a.push([r.x,r.y,r.width,r.height]);}return a;})()", editor)
                        require(bool(chars), "首页链接字符矩形缺失")
                        rectangles = [QRectF(*char) for char in chars]
                        if all(visible_area(editor, rect).adjusted(-0.01, -0.01, 0.01, 0.01)
                                .contains(editor.mapRectToScene(rect)) for rect in rectangles):
                            return {"fully_visible": True, "rendered_target": target, "character_count": len(chars),
                                "anchor_verification": "QTextDocument per-character anchorHref",
                                "scrolls": scrolls, "scene_rectangles": [[rect.x(), rect.y(), rect.width(), rect.height()]
                                    for rect in map(editor.mapRectToScene, rectangles)]}
                        require(attempt < 2, "首页链接经过有界原生滚动仍被裁剪")
                        parent, changed = editor.parentItem(), False
                        while parent is not None:
                            if all(parent.metaObject().indexOfProperty(name) >= 0 for name in ("contentY", "contentHeight")):
                                before = float(parent.property("contentY"))
                                maximum = max(0, float(parent.property("contentHeight")) - parent.height())
                                point = parent.mapFromScene(editor.mapToScene(rectangles[len(rectangles)//2].center()))
                                wanted = max(0, min(maximum, before + point.y() - parent.height()/2))
                                if abs(wanted - before) > 0.1:
                                    require(parent.setProperty("contentY", wanted), "原生滚动位置不可写")
                                    after = float(parent.property("contentY"))
                                    scrolls.append({"kind": "native-flickable-contentY", "before": before,
                                        "after": after, "maximum": maximum, "not_mouse_wheel": True})
                                    changed = abs(after - before) > 0.1
                                    break
                            parent = parent.parentItem()
                        require(changed, "首页原生滚动区没有可用的滚动范围")
                        yield 150
                def reveal(item, scope=None):
                    if not exposed(item) and scope is not None:
                        # ConfigItemComp exposes its owner as a public property.
                        # Keep ScrollView's native contentItem inside QML, just
                        # as for popup.visible; do not convert private Qt types.
                        observation = jjson("(function(){var v=configs.panelComponent.contentItem;if(!v || typeof v.contentY!=='number' || typeof v.contentHeight!=='number')return {supported:false};var p=mapToItem(v,0,height/2),old=v.contentY,max=Math.max(0,v.contentHeight-v.height);v.contentY=Math.max(0,Math.min(max,old+p.y-v.height/2));return {supported:true,before:old,after:v.contentY,maximum:max,targetY:p.y}})()", scope)
                        if len(report["control_events"]) < 32:
                            report["control_events"].append({"kind": "settings-scroll", "observation": observation})
                        yield 50
                    if not exposed(item):
                        parent = item.parentItem()
                        while parent is not None:
                            if parent.metaObject().indexOfProperty("contentY") >= 0 and parent.metaObject().indexOfProperty("contentHeight") >= 0:
                                point = parent.mapFromScene(item.mapToScene(QPointF(item.width()/2, item.height()/2)))
                                target = float(parent.property("contentY")) + point.y() - parent.height()/2
                                maximum = max(0, float(parent.property("contentHeight")) - parent.height())
                                if maximum > 0: parent.setProperty("contentY", min(maximum, max(0, target)))
                            parent = parent.parentItem()
                    yield 50  # Let the candidate's normal polish/layout handle the scroll change.
                    yield from wait(lambda: exposed(item), "Actual control visible/exposed", timeout=3)
                def click(item):
                    require(exposed(item), "Cannot click hidden/clipped control")
                    local = item.mapToScene(QPointF(item.width()/2, item.height()/2))
                    if QTest:
                        QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(local.x()), round(local.y())))
                    else:
                        global_pos = item.mapToGlobal(QPointF(item.width()/2, item.height()/2))
                        for kind, buttons in ((QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton), (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
                            QCoreApplication.sendEvent(window, QMouseEvent(kind, local, global_pos, Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier))
                def key(value):
                    if QTest:
                        QTest.keyClick(window, value)
                    else:
                        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                            QCoreApplication.sendEvent(window, QKeyEvent(kind, value, Qt.KeyboardModifier.NoModifier))
                def button(obj, text):
                    matches = [item for item in descendants(obj) if item.metaObject().indexOfProperty("text_") >= 0 and str(item.property("text_")) == text]
                    require(len(matches) == 1, "Cannot uniquely find candidate button: " + text)
                    return matches[0]
                def combo(obj):
                    found = [item for item in descendants(obj) if all(item.metaObject().indexOfProperty(name) >= 0 for name in ("currentIndex", "count", "popup", "model"))]
                    require(len(found) == 1, "Expected one real ComboBox")
                    return found[0]
                def select(source_key, index):
                    if source_key == "ocr.api":
                        page = activate("GlobalConfigsPage")
                        navigation = button(page, QCoreApplication.translate("GlobalConfigs", "插件管理"))
                        yield from reveal(navigation)
                        click(navigation)
                        yield 50
                    yield from wait(settled, "Canonical control backend apply")
                    yield 0  # Drain already queued panel/deferred-delete callbacks.
                    control = js("qmlapp.globalConfigs.compDict[" + json.dumps(source_key) + "]")
                    require(control is not None, "Canonical control missing: " + source_key)
                    item = combo(control)
                    require(0 <= index < int(item.property("count")), "ComboBox index is out of range")
                    yield from reveal(item, control)
                    window.requestActivate()
                    yield from wait(lambda: window.isActive(), "Own candidate window activation", timeout=3)
                    item.forceActiveFocus()
                    point = item.mapToScene(QPointF(item.width()/2, item.height()/2))
                    if len(report["control_events"]) < 32:
                        report["control_events"].append({"kind": "combo-click", "index": index,
                            "currentText": str(item.property("currentText")), "center": [point.x(), point.y()],
                            "activeWindow": window.isActive(), "enabled": bool(item.property("enabled"))})
                    click(item)
                    yield from wait(lambda: bool(js("popup.visible", item)), "Actual ComboBox popup open", timeout=2)
                    key(Qt.Key.Key_Home)
                    for _ in range(index): key(Qt.Key.Key_Down)
                    key(Qt.Key.Key_Return)
                    yield 50
                def capture(label):
                    if len(report["screenshots"]) >= args.max_screenshots: return
                    path = output / (label + ".png")
                    require(not path.exists(), "Screenshot path already exists")
                    image = window.grabWindow()
                    require(not image.isNull() and image.save(str(path)), "Empty/failed own-window capture")
                    report["screenshots"].append({"path": str(path), "sha256": sha(path), "capture": "QQuickWindow.grabWindow-only"})
                def no_models():
                    bad = sorted(name for name in sys.modules if FORBIDDEN.intersection(name.split(".")))
                    require(not bad and not report["safety_blocks"], "Inference/subprocess safety gate was triggered")
                    from py_src.plugins_controller.services import PluginServices
                    states = {}
                    for identity, entry in PluginServices._entries.items():
                        instance = entry.get("instance")
                        state = instance.get_status() if instance and callable(getattr(instance, "get_status", None)) else {}
                        states[str(identity)] = state
                        require(not state.get("pid") and state.get("state") not in {"ready", "busy", "starting", "sleeping"}, "Model service unexpectedly started")
                    require(js("qmlapp.globalConfigs.getValue('ocr.lifecycle.warmupMode')") in ("lazy", None), "Warmup must remain lazy")
                    check("no_models", forbidden_loaded=bad, service_states=states)
                def provenance():
                    with zipfile.ZipFile(data / "app.zip") as archive:
                        loaded = {}
                        approved = {item["path"]: item["sha256"] for item in host_audit["members"]}
                        for name, module in list(sys.modules.items()):
                            origin = getattr(module, "__file__", None)
                            if not origin: continue
                            if name == "py_src" or name.startswith("py_src.") or name in {"umi_about", "umi_log", "plugin_i18n"}:
                                member = member_origin(origin, data)
                                checksum = hashlib.sha256(archive.read(member)).hexdigest()
                                require(approved.get(member) == checksum == binding["snapshot"].get("host/UmiOCR-data/" + member), "Loaded application module is not source-bound: " + name)
                                loaded[name] = {"origin": str(origin), "member": member, "sha256": checksum}
                            elif name.startswith(("PySide6.", "shiboken6")):
                                require(plain(origin).is_relative_to(plain(data)), "Qt module came from outside the candidate")
                        require("py_src.run" in loaded, "Package py_src.run was not observed")
                    qml = {}
                    for relative in QML:
                        logical = "qt_res/qml/" + relative
                        if (data / "ui.rcc").is_file():
                            source = QFile(":/" + logical)
                            require(source.open(QIODevice.OpenModeFlag.ReadOnly), "Cannot read mounted candidate QML: " + logical)
                            payload = bytes(source.readAll()); source.close()
                            origin = "qrc:/" + logical
                        else:
                            path = plain(data / logical)
                            payload, origin = path.read_bytes(), str(path)
                        checksum = hashlib.sha256(payload).hexdigest()
                        require(binding["snapshot"].get("host/UmiOCR-data/" + logical) == checksum, "Candidate QML does not match source snapshot: " + logical)
                        qml[logical] = {"origin": origin, "sha256": checksum}
                    check("package_provenance", loaded_modules=loaded, qml=qml, container_audits=audit_refs,
                        entry_sha256=sha(data / "main.py"), translations={code: sha(data / "i18n" / (code + ".qm")) for code in LANGUAGES[1:]})
                def copy_about(page):
                    controls = button(page, QCoreApplication.translate("About", "复制"))
                    yield from reveal(controls)
                    before = len(report["copies"])
                    click(controls)
                    yield from wait(lambda: len(report["copies"]) == before + 1, "Actual About copy click")
                    require(report["copies"][-1] == info.property("infoJson"), "About copy is not wired to the dedicated info object")
                def scenario():
                    self.active = "first_frame"
                    require(window.isVisible() and int(window.winId()) != 0, "No actual visible candidate window")
                    check("first_frame", hwnd=int(window.winId()), initial_page=jjson("qmlapp.tab.pageList[qmlapp.tab.showPageIndex].info.key"))
                    yield from wait(settled, "Initial candidate backend apply")
                    no_models()
                    about = activate("About")
                    yield 50
                    self.active = "about.pending"
                    require(info.property("state") == "pending", "Diagnostic barrier did not preserve pending state")
                    yield from copy_about(about)
                    require(QCoreApplication.translate("About", ABOUT_KEYS[0]) in texts(about), "Pending status was not visibly rendered")
                    check("about.pending", state="pending", rendered=True, copied=json.loads(report["copies"][-1]))
                    capture("about-pending")
                    initial_global = jjson("UmiAbout.app")
                    before_revision = js("qmlapp.globalConfigs.definitionRevision")
                    before_tabs = jjson("qmlapp.tab.pageList.map(e=>({key:e.info.key,ctrl:e.ctrlKey}))")
                    release.set()
                    self.active = "about.ready"
                    yield from wait(lambda: info.property("state") in ("ready", "failed"), "Original packaged diagnostic collector", timeout=20)
                    require(info.property("state") == "ready", "Original diagnostic collector failed: " + str(info.property("error")))
                    yield 50
                    actual = json.loads(str(info.property("infoJson")))
                    require(actual == umi_about.UmiAbout["app"], "Python compatibility diagnostic values differ")
                    require(jjson("UmiAbout.app") == initial_global, "Background information replaced the global QML app snapshot")
                    require(js("qmlapp.globalConfigs.definitionRevision") == before_revision, "Diagnostic completion rebuilt global settings")
                    require(jjson("qmlapp.tab.pageList.map(e=>({key:e.info.key,ctrl:e.ctrlKey}))") == before_tabs, "Diagnostic completion reloaded task pages")
                    require(any(actual.get("platform", "") in text for text in texts(about)), "Ready diagnostic JSON is not visibly rendered")
                    check("about.ready", info=actual, stable_global_snapshot=True, stable_pages=True)
                    yield from copy_about(about)
                    check("about.copy", pending_and_ready_real_clicks=True, clipboard_access=False)
                    capture("about-ready")
                    home = activate("Navigation"); yield 50
                    versions = jjson("installedVersions", home)
                    require(versions and versions[0] == "Umi-OCR  " + str(js("UmiAbout.version.string")), "Main navigation version display is not genuine")
                    require(versions[0] in texts(home), "Main navigation version is not visibly rendered")
                    report["checks"]["first_frame"]["navigation_versions"] = versions
                    self.active = "model_settings"
                    global_page = activate("GlobalConfigsPage")
                    yield from wait(lambda: settled() and js("qmlapp.globalConfigs.panelBuilt"), "Central settings build")
                    panel = jjson("qmlapp.globalConfigs.panelLayout.map(e=>({key:e.key,items:(e.items||[]).map(x=>({key:x.key,items:(x.items||[]).map(y=>({key:y.key,device:!!((y.origin||qmlapp.globalConfigs.originDict[y.key]||{}).deviceProvider==='nvidia-cuda')}))}))}))")
                    states = jjson("qmlapp.globalConfigs.pluginStates")
                    options = jjson("qmlapp.globalConfigs.originDict['ocr.api'] ? qmlapp.globalConfigs.originDict['ocr.api'].optionsList : []")
                    if args.profile == "navigation":
                        check("model_settings", "NOT_APPLICABLE", reason="首页专用档不复验未改的模型参数和任务来源")
                        check("task_sources", "NOT_APPLICABLE", reason="首页专用档不操作任务参数")
                    elif args.profile == "base":
                        require(not states and not options, "Base candidate must not manufacture backend options")
                        check("model_settings", profile="base", no_backend_options=True, panel=panel)
                        check("task_sources", "NOT_APPLICABLE", reason="No OCR backend or task recognition parameters in base profile")
                    else:
                        require({entry["id"] for entry in states} == {PP, VL} and all(entry["state"] == "ready" for entry in states), "Combined profile requires precisely the two ready plugins")
                        require([option[0] for option in options] == [PP, VL], "Models are not PP first / VL second")
                        require(js("qmlapp.globalConfigs.getValue('ocr.api')") == PP, "Fresh model default is not PP")
                        plugins = next(entry for entry in panel if entry["key"] == "plugins")
                        groups = [entry["key"] for entry in plugins["items"]]
                        require(groups.index("plugins.models") < groups.index("plugins." + PP) < groups.index("plugins." + VL), "Central models/plugin group order differs")
                        for plugin in (PP, VL):
                            children = next(entry["items"] for entry in plugins["items"] if entry["key"] == "plugins." + plugin)
                            device_flags = [entry["device"] for entry in children]
                            require(any(device_flags) and device_flags == sorted(device_flags), "GPU selector is not at the plugin group tail")
                        for index in (1, 0):
                            yield from select("ocr.api", index)
                            yield from wait(settled, "Actual central model selection")
                            require(js("qmlapp.globalConfigs.getValue('ocr.api')") == options[index][0], "Model ComboBox selection did not commit")
                            no_models()
                        yield from wait(lambda: not js("qmlapp.globalConfigs.cudaDiscoveryPending"), "Bounded NVIDIA device discovery")
                        # Query a plain snapshot for comparison; QObject/V4 arrays are not assumed to be Python lists.
                        gpu = jjson("qmlapp.globalConfigs.compList.filter(c=>c.origin && c.origin.deviceProvider==='nvidia-cuda').map(c=>({key:c.sourceKey,saved:c.value(),options:c.deviceOptions,state:c.deviceSnapshot.state}))")
                        require(len(gpu) >= 2, "Combined package lacks the real NVIDIA selector rows")
                        discovery = jjson("qmlapp.globalConfigs.cudaDeviceSnapshot")
                        require(discovery["state"] in {"ready", "no_devices", "driver_missing"}, "NVIDIA discovery failed/timed out")
                        for row in gpu:
                            require(row["state"] == discovery["state"], "GPU row has stale discovery state")
                            available = [(option["value"], option["label"]) for option in row["options"] if option["available"]]
                            expected = [(device["value"], "GPU:" + str(device["ordinal"]) + " · " + device["name"]) for device in discovery.get("devices", [])]
                            require(available == expected, "GPU combo does not show the actual NVIDIA logical devices")
                        device_control = js("qmlapp.globalConfigs.compList.find(c=>c.origin && c.origin.deviceProvider==='nvidia-cuda')")
                        actual_combo = combo(device_control)
                        yield from reveal(actual_combo, device_control); click(actual_combo); yield 30
                        require(bool(js("popup.visible", actual_combo)), "GPU dropdown did not open")
                        key(Qt.Key.Key_Escape); yield 30
                        check("model_settings", profile="combined", model_options=options, plugin_groups=groups, gpu_rows=gpu, device_tail_verified=True, actual_gpu_popup_opened=True)
                        self.active = "task_sources"
                        pages = {category: activate(page) for category, page in (("ScreenshotOCR", "ScreenshotOCR"), ("BatchOCR", "BatchOCR"), ("BatchPDF", "BatchDOC"))}
                        activate("GlobalConfigsPage")
                        yield from wait(settled, "Task source pages established")
                        key_name = "ocr.docOrientation"
                        def source_values():
                            return jjson("['ScreenshotOCR','BatchOCR','BatchPDF'].map(k=>qmlapp.globalConfigs.ocrManager.taskSources[k].getValue(" + json.dumps(key_name) + "))")
                        original = source_values()
                        observed = []
                        for category in ("ScreenshotOCR", "BatchOCR", "ScreenshotOCR", "BatchOCR"):
                            source = js("qmlapp.globalConfigs.ocrManager.taskSources[" + json.dumps(category) + "]")
                            target = js("qmlapp.globalConfigs.compList.find(c=>c.sourceConfigs===qmlapp.globalConfigs.ocrManager.taskSources[" + json.dumps(category) + "] && c.sourceKey===" + json.dumps(key_name) + ")")
                            require(source is not None and target is not None, "Missing central task parameter source/control")
                            # Expand only the relevant central display group; no model or policy mutation.
                            group = js("qmlapp.globalConfigs.compList.find(c=>c.key==='plugins.models.'+" + json.dumps(category) + ")")
                            if group is not None and group.property("fold"):
                                group.setProperty("fold", False)
                                yield 30
                            before = source_values()
                            # The canonical bool row and its indicator both expose
                            # checked. Click the one styled indicator; its parent
                            # row's real MouseArea owns the user interaction.
                            toggles = [item for item in descendants(target) if item is not target
                                and all(item.metaObject().indexOfProperty(name) >= 0 for name in ("checked", "enabledAnime")) and item.width() > 0]
                            require(len(toggles) == 1, "Expected one actual task boolean indicator")
                            index = ("ScreenshotOCR", "BatchOCR", "BatchPDF").index(category)
                            require(bool(toggles[0].property("checked")) == bool(before[index])
                                == bool(target.property("checked")), "Canonical task row/indicator is not bound to its source")
                            yield from reveal(toggles[0], target); click(toggles[0]); yield 50
                            after = source_values()
                            require(after[index] is (not bool(before[index])) and all(after[n] == before[n] for n in range(3) if n != index), "Task source values leaked into another task")
                            for name, page in pages.items():
                                require(js("configsComp.getValue(" + json.dumps(key_name) + ")", page) == after[("ScreenshotOCR", "BatchOCR", "BatchPDF").index(name)], "Task page does not read its own canonical source")
                                require(not js("Object.prototype.hasOwnProperty.call(configsComp.valueDict," + json.dumps(key_name) + ")", page), "Task page saved a second OCR value copy")
                            observed.append({"category": category, "before": before, "after": after})
                        require(source_values() == original, "Task parameter fixture did not restore original values")
                        check("task_sources", actual_boolean_clicks=observed, independent_sources=True, no_page_value_copies=True)
                    no_models()
                    self.active = "languages"
                    from py_src.utils.i18n_configs import I18n
                    target_map = harness("translations").TARGETS
                    language_records, homepage_records = [], []
                    homepage_targets = (load("stored_navigation_copy_targets", REPO / "tests/test_navigation_repository_link.py").TRANSLATIONS
                                        if report["homepage_repository_required"] else {})
                    for code in LANGUAGES:
                        activate("GlobalConfigsPage")
                        language_options = jjson("qmlapp.globalConfigs.originDict['ui.i18n'].optionsList")
                        index = next((n for n, value in enumerate(language_options) if value[0] == code), None)
                        require(index is not None, "Candidate does not offer language: " + code)
                        yield from select("ui.i18n", index)
                        yield from wait(lambda: settled() and I18n.langCode == code, "Actual seven-language switch " + code)
                        if report["homepage_repository_required"]:
                            home = activate("Navigation")
                            label = "仓库链接" if code == "zh_CN" else homepage_targets[code]
                            target = "https://github.com/Dominic485649/UMI-OCR"
                            link = "[" + label + "](" + target + ")"
                            yield from wait(lambda: link in str(js("introText", home)), "首页实际译文和链接目标 " + code)
                            yield 250
                            visibility = yield from homepage_link(home, label, target)
                            homepage_records.append({"code": code, "label": label, "url": target, "visible_link": visibility,
                                "welcome": str(js("welcomeText", home)), "visible_intro": str(js("introText", home))})
                            if code in ("zh_CN", "en_US", "ta"):
                                capture("homepage-" + code)
                                require((output / ("homepage-" + code + ".png")).is_file(), "首页截图预算不足")
                        about = activate("About"); yield 50
                        expected = ABOUT_KEYS if code == "zh_CN" else target_map[code]
                        actual = tuple(QCoreApplication.translate("About", source) for source in ABOUT_KEYS)
                        require(actual == tuple(expected), "Compiled About translations differ: " + code)
                        rendered_copy = button(about, QCoreApplication.translate("About", "复制"))
                        yield from reveal(rendered_copy)
                        require(any(str(info.property("infoJson")) in text for text in texts(about)), "Opened About JSON did not survive language switch")
                        language_records.append({"code": code, "about_targets": actual, "copy_label": str(rendered_copy.property("text_"))})
                        no_models()
                    check("languages", switches=language_records, real_combo_events=True, seven_languages=True)
                    if report["homepage_repository_required"]:
                        check("navigation_repository", languages=homepage_records, real_compiled_qml=True,
                              real_language_combo_events=True, external_link_not_opened=True)
                    provenance()
                    no_models()
                    report["scenario_completed"] = True
                def finish(error=None):
                    if self.done: return
                    self.done = True
                    release.set()
                    if error is not None:
                        try:
                            capture("failure-" + self.active.replace(".", "-"))
                        except Exception as capture_error:
                            report["errors"].append("Own-window failure capture: " + str(capture_error))
                        status = "NOT_RUN" if isinstance(error, old.ProbeUnavailable) else "FAIL"
                        check(self.active, status, reason=str(error))
                        report["errors"].append("".join(traceback.format_exception(type(error), error, error.__traceback__)))
                    try:
                        no_models()
                    except Exception as safety_error:
                        check("no_models", "FAIL", reason=str(safety_error), blocked=report["safety_blocks"])
                        report["errors"].append("Final no-model checkpoint: " + str(safety_error))
                    QApplication.instance().quit()
                def begin():
                    if self.begun: return
                    self.begun = True
                    scheduler.start_steps(scenario(), QTimer.singleShot, finish, finish)
                window.frameSwapped.connect(lambda: QTimer.singleShot(0, begin) if not self.begun else None)
                window.show()
                window.requestActivate()
                QTimer.singleShot(15000, lambda: finish(AssertionError("No real first frame")) if not self.begun else None)
                QTimer.singleShot(args.timeout * 1000, lambda: finish(AssertionError("Directed UI budget exhausted")) if not self.done else None)
        QtQml.QQmlApplicationEngine = Engine
        from py_src.run import main
        sys.argv = [str(root / "Umi-OCR.exe"), "--force"]
        try:
            main(str(root / "Umi-OCR.exe"), "./site-packages/PySide6/qml")
        except SystemExit as exc:
            require(exc.code in (0, None), "Candidate exited abnormally: " + str(exc.code))
        report["normal_exit"] = True
        check("normal_exit", "PASS" if report["scenario_completed"] else "NOT_RUN", scenario_completed=report["scenario_completed"], exit_code=0)
    except Exception as exc:
        release.set()
        report["errors"].append("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    finally:
        release.set()
        for callback in reversed(restore_callbacks): callback()
        try:
            if previous_engine is not None:
                QtQml.QQmlApplicationEngine = previous_engine
                app = QApplication.instance()
            if app is not None:
                for engine in engines: engine.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                import shiboken6
                shiboken6.delete(app)
            occupancy = old.candidate_processes(root)
            require(not occupancy["candidate_processes"], "Owned candidate child still running; do not restore settings yet")
            restored = snapshot.restore()
            check("settings_restored", "PASS" if restored else "FAIL", absent_before=True, restored_absence=restored)
            current = payload_hashes(root)
            rules_after = rule_hashes()
            unchanged = current == report.get("input_sha256") and rules_after == report["harness_sha256"]
            check("payload_unchanged", "PASS" if unchanged else "FAIL", input_sha256_after=current, harness_sha256_after=rules_after)
        except Exception as exc:
            report["errors"].append("No cleanup bypass: " + str(exc))
        if finder is not None and finder in sys.meta_path: sys.meta_path.remove(finder)
        if report["safety_blocks"]: check("no_models", "FAIL", blocked=report["safety_blocks"])
        report["acceptance"] = acceptance(report)
        write_new(output / "report.json", report)
    print(json.dumps({"output": str(output), "acceptance": report["acceptance"], "mode": report["mode"]}, ensure_ascii=False))
    return 0 if report["acceptance"]["status"] == "PASS" else 2


def self_test(output):
    """Deterministic tiny fixtures only; never imports Qt or executes a candidate."""
    before_qt = sorted(name for name in sys.modules if name.startswith("PySide6"))
    tmp = REPO / "build/tmp/startup-small-files-20261028-r1/stored-native-driver-20261029-r1"
    tmp.mkdir(parents=True, exist_ok=True)
    class Fixtures(unittest.TestCase):
        def setUp(self):
            self.temporary = tempfile.TemporaryDirectory(prefix="pure-", dir=tmp)
            self.root = Path(self.temporary.name) / "candidate"
            self.data = self.root / "UmiOCR-data"
            (self.data / "runtime").mkdir(parents=True)
            for path in (self.root / "Umi-OCR.exe", self.data / "runtime/python.exe", self.data / "main.py", self.data / "about.json"):
                path.write_bytes(b"fixture only, never executable")
        def tearDown(self): self.temporary.cleanup()
        def test_paths_reject_release_and_existing_configuration_without_read(self):
            self.assertEqual(harness("old").checked_root(self.root), self.root)
            with self.assertRaises(ValueError): harness("old").checked_root(REPO / "release/Umi-OCR")
            pristine(self.data)
            (self.data / ".settings").write_bytes(b"must not read user state")
            with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("read existing settings")):
                with self.assertRaises(ValueError): pristine(self.data)
        def test_runtime_requires_exact_candidate_and_isolated_flags(self):
            with self.assertRaises(AssertionError): isolated_runtime(self.root)
        def test_exact_nvidia_command_not_blanket_subprocess_permission(self):
            bootstrap = "import runpy\nrunpy.run_module('py_src.utils._cuda_device_probe_worker', run_name='__main__')\n"
            argv = [str(self.data / "runtime/python.exe"), "-I", "-B", "-X", "utf8", "-u", "-c", bootstrap, str(self.data / "app.zip")]
            self.assertTrue(allowed_probe(argv[0], argv, str(self.data), self.root, bootstrap))
            for index, value in ((0, sys.executable), (1, "-S"), (7, bootstrap + "# changed"), (8, str(REPO / "UmiOCR-data"))):
                wrong = list(argv); wrong[index] = value
                self.assertFalse(allowed_probe(wrong[0], wrong, str(self.data), self.root, bootstrap))
            self.assertFalse(allowed_probe(argv[0], " ".join(argv), str(self.data), self.root, bootstrap))
            self.assertFalse(allowed_probe(argv[0], argv, str(REPO), self.root, bootstrap))
        def test_windows_none_string_probe_is_one_exact_complete_command(self):
            bootstrap = "import runpy\nrunpy.run_module('py_src.utils._cuda_device_probe_worker', run_name='__main__')\n"
            argv = [str(self.data / "runtime/python.exe"), "-I", "-B", "-X", "utf8", "-u", "-c", bootstrap, str(self.data / "app.zip")]
            command = subprocess.list2cmdline(argv)
            self.assertTrue(allowed_probe(None, command, str(self.data), self.root, bootstrap))
            self.assertTrue(allowed_probe(argv[0], command, str(self.data), self.root, bootstrap))
            self.assertTrue(allowed_probe(None, argv, str(self.data), self.root, bootstrap))
            for wrong in (command + " extra", command + " & model.exe", subprocess.list2cmdline(argv + ["extra"])):
                self.assertFalse(allowed_probe(None, wrong, str(self.data), self.root, bootstrap))
            wrong_root = list(argv); wrong_root[-1] = str(REPO / "UmiOCR-data/app.zip")
            self.assertFalse(allowed_probe(None, subprocess.list2cmdline(wrong_root), str(self.data), self.root, bootstrap))
            self.assertFalse(allowed_probe(None, command, str(REPO), self.root, bootstrap))
            self.assertFalse(allowed_probe(sys.executable, command, str(self.data), self.root, bootstrap))
            self.assertFalse(allowed_probe("runtime/python.exe", command, str(self.data), self.root, bootstrap))
        def test_only_pinned_precreate_driver_refusal_can_retry_not_model_blocks(self):
            blocks = [{"kind": "subprocess", "executable": "None"}]
            record = {"driverSha256": "e9ecd134af93d7b1c40ba4146201ad5d3fc3de588d33b0bf8c82bd8a140f5adb",
                "safety_blocks": blocks, "allowed_nvidia_launches": [],
                "checks": {"no_models": {"status": "FAIL", "blocked": blocks}}}
            self.assertEqual(prior_safety_gate(record)["originalStatus"], "FAIL")
            with self.assertRaises(AssertionError): prior_safety_gate(dict(record, driverSha256="unrecognized"))
            with self.assertRaises(AssertionError): prior_safety_gate(dict(record, allowed_nvidia_launches=[{}]))
            wrong = [{"kind": "model_import", "module": "paddle"}]
            with self.assertRaises(AssertionError): prior_safety_gate(dict(record, safety_blocks=wrong))
        def test_only_exact_incomplete_report_can_retry_without_relabelling_check(self):
            pinned = "b3b4b92d68ed6179bb99a1b38b39c48473f4503933745d269bf107033a70eefc"
            record = {"driverSha256": "24a917df4a076e3ae68fc282a2862e9f045772fed170875cd5d0a49cc72d8fc3",
                "safety_blocks": [], "allowed_nvidia_launches": [{"argv_sha256": "4042c9bbdace9d48f3109af790123011f58faefb487256f4231800b4a825c11d"}],
                "checks": {"no_models": {"status": "NOT_RUN"}, "model_settings": {"reason": "libshiboken: Internal C++ object (PySide6.QtQuick.QQuickItem) already deleted."}}}
            proof = prior_safety_gate(record, report_sha256=pinned)
            self.assertEqual(proof["originalStatus"], "NOT_RUN")
            self.assertFalse(proof["modelServiceStatePreviouslyVerified"])
            self.assertEqual(record["checks"]["no_models"]["status"], "NOT_RUN")
            for checksum in (None, "unrecognized"):
                with self.assertRaises(AssertionError): prior_safety_gate(record, report_sha256=checksum)
            for changed in (dict(record, safety_blocks=[{"kind": "model_import"}]),
                    dict(record, driverSha256="unrecognized"), dict(record, allowed_nvidia_launches=[])):
                with self.assertRaises(AssertionError): prior_safety_gate(changed, report_sha256=pinned)
        def test_zip_origin_refuses_source_sandbox(self):
            member = "py_src/run.py"
            self.assertEqual(member_origin(str(self.data / "app.zip" / member), self.data), member)
            for path in (REPO / "UmiOCR-data/py_src/run.py", self.data / "py_src/run.py"):
                with self.assertRaises(ValueError): member_origin(str(path), self.data)
        def test_bootstrap_is_literal_not_guessed_or_evaluated(self):
            self.assertEqual(bootstrap_literal('_WORKER_BOOTSTRAP = "fixture"'), "fixture")
            with self.assertRaises(AssertionError): bootstrap_literal('_WORKER_BOOTSTRAP = dangerous()')
        def test_binding_requires_actual_archive_audit_and_canonical_sources(self):
            payloads = {member: b"fixture = True\n" for member in MEMBERS}
            payloads["py_src/utils/cuda_device_probe.py"] = b'_WORKER_BOOTSTRAP = "fixture-probe"\n'
            with zipfile.ZipFile(self.data / "app.zip", "x", compression=zipfile.ZIP_STORED) as archive:
                for member, value in payloads.items(): archive.writestr(member, value)
            snapshot = {"host/UmiOCR-data/" + member: hashlib.sha256(value).hexdigest() for member, value in payloads.items()}
            snapshot["host/UmiOCR-data/main.py"] = sha(self.data / "main.py")
            (self.data / "i18n").mkdir()
            for code in LANGUAGES[1:]:
                path = self.data / "i18n" / (code + ".qm"); path.write_bytes(b"fake qm, not translated")
                snapshot["host/UmiOCR-data/i18n/" + code + ".qm"] = sha(path)
            write_new(self.root / "source-snapshot.json", snapshot)
            record = {"status": "PASS", "kind": "host", "root": str(self.data),
                      "members": [{"path": member, "sha256": hashlib.sha256(value).hexdigest()} for member, value in payloads.items()]}
            self.assertEqual(bind_archive(self.root, record)["bootstrap"], "fixture-probe")
            bad = dict(record, status="NOT_INCLUDED")
            with self.assertRaises(AssertionError): bind_archive(self.root, bad)
            (self.data / "main.py").write_bytes(b"mismatched entry")
            with self.assertRaises(AssertionError): bind_archive(self.root, record)
        def test_early_exit_and_unavailable_probe_cannot_pass(self):
            report = {"profile": "combined", "scenario_completed": True, "normal_exit": True,
                      "checks": {key: {"status": "PASS"} for key in REQUIRED}, "errors": [], "safety_blocks": []}
            self.assertEqual(acceptance(report)["status"], "INCOMPLETE")
            report["checks"]["task_sources"] = {"status": "PASS"}
            self.assertEqual(acceptance(report)["status"], "PASS")
            report["scenario_completed"] = False
            self.assertEqual(acceptance(report)["status"], "INCOMPLETE")
            report["scenario_completed"] = True
            report["checks"]["about.copy"] = {"status": "NOT_RUN"}
            self.assertEqual(acceptance(report)["status"], "INCOMPLETE")
            report["checks"]["about.copy"] = {"status": "PASS"}
            report["safety_blocks"].append({"kind": "model_import"})
            self.assertEqual(acceptance(report)["status"], "INCOMPLETE")
        def owned_evidence(self):
            audit = self.root.parent / "audit"
            initial = audit / "first"
            initial.mkdir(parents=True)
            inputs = payload_hashes(self.root)
            record = {"mode": "candidate-python-native-qt-not-exe", "root": str(self.root), "profile": "base",
                "driverSha256": "f" * 64, "normal_exit": True, "safety_blocks": [], "input_sha256": inputs,
                "checks": {"no_models": {"status": "PASS"},
                    "settings_restored": {"status": "PASS", "absent_before": True, "restored_absence": True},
                    "payload_unchanged": {"status": "PASS", "input_sha256_after": inputs}}}
            write_new(initial / "report.json", record)
            write_new(self.data / ".stored-native-ui-owner.json", {"schema": 1, "root": str(self.root),
                "output": str(initial), "driverSha256": "f" * 64})
            return audit, initial / "report.json", inputs, record
        def test_owned_retry_requires_same_restored_empty_payload_and_keeps_owner(self):
            audit, previous, inputs, record = self.owned_evidence()
            before = sha(self.data / ".stored-native-ui-owner.json")
            proof = verify_owned_reuse(self.root, previous, "base", inputs, audit_root=audit)
            self.assertTrue(proof["same_payload_verified"])
            self.assertEqual(before, sha(self.data / ".stored-native-ui-owner.json"))
            with self.assertRaises(AssertionError): verify_owned_reuse(self.root, previous, "combined", inputs, audit_root=audit)
            (self.data / "main.py").write_bytes(b"changed payload")
            with self.assertRaises(AssertionError): verify_owned_reuse(self.root, previous, "base", payload_hashes(self.root), audit_root=audit)
        def test_owned_retry_never_adopts_existing_config_or_an_unfinished_run(self):
            audit, previous, inputs, record = self.owned_evidence()
            record["normal_exit"] = False
            bad = audit / "unfinished.json"
            write_new(bad, record)
            with self.assertRaises(AssertionError): verify_owned_reuse(self.root, bad, "base", inputs, audit_root=audit)
            (self.data / ".settings").write_bytes(b"never read or adopt")
            with mock.patch.object(Path, "read_text", side_effect=AssertionError("configuration was read")):
                with self.assertRaises(ValueError): verify_owned_reuse(self.root, previous, "base", inputs, audit_root=audit)
        def test_popup_probe_keeps_unwrapped_quick_pointer_inside_qml(self):
            tree = ast.parse(Path(__file__).read_text("utf-8"))
            reads = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and node.func.attr == "property"
                and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "popup"]
            self.assertEqual(reads, [], "Do not ask PySide to convert QQuickPopup*; evaluate its public visible property in QML")
        def test_selection_reacquires_canonical_control_after_navigation_yields(self):
            tree = ast.parse(Path(__file__).read_text("utf-8"))
            selection = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "select")
            self.assertEqual([arg.arg for arg in selection.args.args], ["source_key", "index"])
            calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == "select"]
            self.assertEqual({node.args[0].value for node in calls if isinstance(node.args[0], ast.Constant)}, {"ocr.api", "ui.i18n"})
            self.assertTrue(all(isinstance(node.args[0], ast.Constant) for node in calls), "Never retain a panel QObject across a model/language rebuild")
            acquire = next(n for n, node in enumerate(selection.body) if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "control" for target in node.targets))
            self.assertTrue(any(isinstance(node, (ast.Yield, ast.YieldFrom)) for statement in selection.body[:acquire] for node in ast.walk(statement)))
            self.assertIn("compDict[", ast.unparse(selection.body[acquire]))
            self.assertIn("json.dumps(source_key)", ast.unparse(selection.body[acquire]))
        def test_task_boolean_probe_distinguishes_row_from_its_indicator(self):
            tree = ast.parse(Path(__file__).read_text("utf-8"))
            assignment = next(node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "toggles" for target in node.targets))
            expression = ast.unparse(assignment.value)
            self.assertIn("item is not target", expression)
            self.assertIn("'checked'", expression)
            self.assertIn("'enabledAnime'", expression)
        def test_no_model_checkpoints_run_before_scenario_and_during_failure_exit(self):
            tree = ast.parse(Path(__file__).read_text("utf-8"))
            scenario = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "scenario")
            first_check = next(n for n, node in enumerate(scenario.body) if isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "no_models")
            first_about = next(n for n, node in enumerate(scenario.body) if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "about" for target in node.targets))
            self.assertLess(first_check, first_about)
            finish = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "finish")
            self.assertTrue(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "no_models" for node in ast.walk(finish)))
        def test_scheduler_gives_control_back_to_qt_without_running_qt(self):
            queue, seen = [], []
            def steps():
                seen.append("a"); yield 10
                seen.append("b"); yield 0
            harness("scheduler").start_steps(steps(), lambda delay, callback: queue.append((delay, callback)), lambda: seen.append("done"), lambda exc: seen.append("failed"))
            while queue:
                delay, callback = queue.pop(0); self.assertIsInstance(delay, int); callback()
            self.assertEqual(seen, ["a", "b", "done"])
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Fixtures))
    after_qt = sorted(name for name in sys.modules if name.startswith("PySide6"))
    output.mkdir(parents=True, exist_ok=False)
    report = {"mode": "pure-driver-fixtures-only", "status": "PASS" if result.wasSuccessful() and not result.skipped and before_qt == after_qt else "FAIL",
        "testsRun": result.testsRun, "failures": [(str(case), value) for case, value in result.failures],
        "errors": [(str(case), value) for case, value in result.errors], "skipped": [(str(case), value) for case, value in result.skipped],
        "pythonExecutable": sys.executable, "pythonVersion": sys.version, "isolated": sys.flags.isolated,
        "dontWriteBytecode": sys.flags.dont_write_bytecode, "driverSha256": sha(__file__), "harness_sha256": rule_hashes(), "qtModulesBefore": before_qt,
        "qtModulesAfter": after_qt, "guiStarted": False, "candidateStarted": False,
        "scope": "Non-executable fixture archives/config paths, safety allowlist, source binding and scheduler. Real native Qt scenarios NOT_RUN."}
    write_new(output / "self-tests.json", report)
    print(json.dumps({"status": report["status"], "testsRun": result.testsRun, "output": str(output), "nativeGui": "NOT_RUN"}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="A new directory beneath this project's build/audit")
    parser.add_argument("--profile", choices=("base", "combined", "navigation"), default="base", help="navigation只验收首页及七语，不冒称复验模型/任务参数")
    parser.add_argument("--check-homepage", action="store_true", help="额外验证七语首页逐字锚点与原生滚动位置可见性，保留中英泰米尔语截图；不打开链接，不冒称鼠标滚轮验收")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--execute-authorized", action="store_true")
    parser.add_argument("--reuse-owned-run", type=Path, help="Explicit previous report.json for this same driver-owned, restored-empty, unchanged, idle candidate")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--max-screenshots", type=int, default=3)
    args = parser.parse_args(argv)
    if not 30 <= args.timeout <= 240 or not 0 <= args.max_screenshots <= 6:
        parser.error("Use a bounded timeout (30..240 seconds) and screenshot budget (0..6)")
    output = harness("old").checked_output(args.output)
    if args.self_test:
        if args.root or args.execute_authorized or args.reuse_owned_run: parser.error("Pure self-test cannot adopt/run a candidate")
        return self_test(output)
    if not args.root or not args.execute_authorized:
        parser.error("Native UI requires --root and the coordinator's explicit --execute-authorized window")
    return native(args, output)


if __name__ == "__main__":
    raise SystemExit(main())
