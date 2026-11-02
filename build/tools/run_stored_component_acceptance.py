"""Narrow real Stored-worker acceptance; default is a no-I/O, no-GPU plan.

CUDA: one existing ordinary image. VL: ordinary spotting and original PDF page 2,
8K/single-slot/original model bytes and the existing quality metrics. Dense's
historical FAIL is retained, never rerun or waived. No candidate/model tree is
copied, no build/publication/cleanup is provided, and no extra kill fallback is
allowed. Only an explicit --execute-gpu may import product code or launch it.
"""
from __future__ import annotations

import argparse
import atexit
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import queue
import re
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[2]
VL_TOOLS = PROJECT.parent / "Umi-OCR-Plugin/build/tools"
IDS = {"cuda": "win32_PaddleOCRv6_CUDA", "vl": "win32_PaddleOCRVL_1_6"}
GENERATED = {"runtime.lock.json", "runtime-archives.json", "runtime-archive-inputs.json", ".runtime-archive-candidate.json"}
CODE_SUFFIXES = {".py", ".qml", ".js", ".csv"}
TOOLS_USED = {}


class AcceptanceError(RuntimeError):
    pass


class AcceptanceTimeout(AcceptanceError):
    pass


class KillFallbackBlocked(AcceptanceError):
    pass


def require(condition, message):
    if not condition:
        raise AcceptanceError(message)


def plain(path):
    path = Path(path)
    require(path.is_absolute() and not str(path).startswith(("\\\\", "//", "\\/", "/\\")) and ".." not in path.parts,
            "Use an absolute ordinary local path without parent traversal")
    for node in (path, *path.parents):
        try:
            info = node.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
                "Link/junction/reparse input is forbidden: " + str(node))
    return path.resolve()


def sha256(path):
    with plain(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _pairs(pairs):
    result = {}
    for name, value in pairs:
        require(name not in result, "Duplicate JSON key: " + name)
        result[name] = value
    return result


def read_json(path):
    path = plain(path)
    require(path.is_file() and path.stat().st_size <= 8 * 1024 * 1024, "Missing/oversized JSON input: " + str(path))
    return json.loads(path.read_text("utf-8-sig"), object_pairs_hook=_pairs)


def write_new(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def pinned_json(path, expected):
    require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected), "An explicit pinned JSON SHA256 is required")
    require(sha256(path) == expected, "Pinned JSON input changed: " + str(path))
    return read_json(path)


def trusted_tool(name, directory=None):
    path = plain((PROJECT / "build/tools" if directory is None else directory) / (name + ".py"))
    spec = importlib.util.spec_from_file_location("umi_stored_acceptance_" + name, path)
    require(spec is not None and spec.loader is not None, "Missing trusted acceptance helper")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    TOOLS_USED[str(path)] = sha256(path)
    return module


def fixture_inputs(root, expected, component):
    manifest = plain(root) / "fixtures.json"
    value = pinned_json(manifest, expected)
    require("deterministic nonsensitive synthetic input" in str(value.get("scope", "")), "Only the existing nonsensitive fixture manifest is accepted")
    ordinary = [record for record in value.get("cases", []) if record.get("id") == "ordinary"]
    require(len(ordinary) == 1, "Exactly one original ordinary fixture is required")
    selected = [ordinary[0]] + ([value.get("document")] if component == "vl" else [])
    criteria = {"identifierHitRatio": .95, "completeLineHitRatio": .90, "allEdgeIdentifiers": True,
                "coordinatesBounded": True, "partial": False}
    for record in selected:
        require(isinstance(record, dict) and record.get("criteria") == criteria, "Original quality criteria must not change")
        source = plain(record["path"])
        require(source.parent == manifest.parent and source.is_file() and sha256(source) == record.get("sha256"), "Fixture escaped its original directory or changed")
        truth = record.get("truth")
        prefix, count, size = ("NORMAL", 14, [1000, 700]) if record["id"] == "ordinary" else ("PAGE2", 22, [1100, 1500])
        require(isinstance(truth, list) and len(truth) == count and record.get("size") == size and
                all(isinstance(row, dict) and str(row.get("token", "")).startswith(prefix) for row in truth), "Unexpected original fixture expectations")
        if prefix == "PAGE2":
            require(record.get("id") == "selected-document" and record.get("pageRange") == [2, 2] and record.get("expectedPages") == [2], "Selected PDF must retain original page 2")
    return {"manifest": str(manifest), "sha256": expected, "cases": selected}


def dense_failure(path, expected):
    value = pinned_json(path, expected)
    contexts = value.get("contexts", [value])
    failures = [case for context in contexts for case in context.get("cases", [])
                if case.get("id") == "dense" and (case.get("metrics") or {}).get("passed") is False]
    require(failures, "Historical dense FAIL must be present; never relabel it PASS or NOT_INCLUDED")
    return {"path": str(plain(path)), "sha256": expected, "status": "FAIL", "rerun": False, "original_cases": failures}


def lock_binding(plugin, component, layout):
    disk = layout.tree_files(plugin)
    document = read_json(plugin / "runtime.lock.json")
    require(isinstance(document, dict) and document.get("pluginId") == IDS[component] and
            isinstance(document.get("files"), list) and document["files"], "Missing/invalid component runtime lock")
    entries, folded = {}, set()
    for row in document["files"]:
        require(isinstance(row, dict), "Invalid runtime lock row")
        name = layout.canonical_relative(row.get("path"))
        require(name.casefold() not in folded and
                isinstance(row.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]), "Invalid/duplicate runtime lock entry")
        require(name in disk and sha256(disk[name]) == row["sha256"], "Runtime lock mismatch: " + name)
        entries[name] = row["sha256"]
        folded.add(name.casefold())
    if component == "vl":
        # VL's current formal builder freezes ALL physical files after assembly.
        expected = set(disk) - {"runtime.lock.json"}
    else:
        # CUDA's formal freeze_gpu_runtime is intentionally native-only.
        expected = {name for name in disk if Path(name).suffix.lower() in {".dll", ".pyd"} or name == "UmiOCR-CudaWorker.exe"}
    require(set(entries) == expected, "Runtime lock coverage differs from this component's actual lock contract")
    return {"path": str(plugin / "runtime.lock.json"), "sha256": sha256(plugin / "runtime.lock.json"),
            "scope": "all-physical-files-after-assembly" if component == "vl" else "CUDA-native-only",
            "files": entries}


def source_binding(plugin, source, layout):
    source = plain(source)
    require(source.is_dir() and not source.is_relative_to(plugin), "Supply the retained independent corresponding plugin source directory")
    def code_records(root):
        records = {}
        for name, path in layout.tree_files(root).items():
            if set(Path(name).parts) & {"vendor", "models", "resources", "__pycache__"}:
                continue
            if Path(name).suffix.lower() in CODE_SUFFIXES or name == "umi-plugin.json":
                records[name] = sha256(path)
        return records
    expected, actual = code_records(source), code_records(plugin)
    require("worker.py" in expected and "umi-plugin.json" in expected and expected == actual,
            "Installed adapter/worker/manifest code differs from retained corresponding source")
    return {"root": str(source), "files": expected,
            "scope": "exact retained adapter/worker/QML/JS/CSV/plugin-manifest equality, not public-source/license authorization"}


def archive_module_origins(response, plugin, archives, entries):
    """Check actual startup origins against already audited physical ZIP members."""
    reported, modules = response.get("runtime_archives"), response.get("archive_modules")
    require(isinstance(reported, list) and isinstance(modules, dict) and modules, "Worker did not prove any actual Stored imports")
    normalize = lambda value: str(value).replace("\\", "/").casefold()
    expected = {normalize(plugin / name) for name in archives}
    require(len(reported) == len(set(map(normalize, reported))) and set(map(normalize, reported)) == expected,
            "Worker runtime_archives do not identify exactly the audited candidate ZIPs")
    allowed = {}
    for entry in entries:
        member = entry["member"]
        if not member.endswith(".py"):
            continue
        module = member[:-3].replace("/", ".")
        if module.endswith(".__init__"):
            module = module[:-9]
        allowed[normalize(str(plugin / entry["archive"]) + "/" + member)] = {"archive": entry["archive"], "member": member, "physical_module": module}
    used, bindings = set(), {}
    for name, origin in modules.items():
        require(isinstance(name, str) and all(part.isidentifier() for part in name.split(".")) and isinstance(origin, str), "Invalid worker module origin record")
        key = normalize(origin)
        require(key in allowed, "Worker imported an unbound/cross-candidate ZIP module: " + name)
        # sys.modules keys can be legitimate aliases (requests.packages.idna,
        # etc.). Source proof is the exact audited ZIP/member, not guessing that
        # a module label must equal its physical package name.
        bindings[name] = allowed[key]
        used.add(allowed[key]["archive"])
    require(used == set(archives), "An audited runtime archive has no observed imported module")
    return {"runtime_archives": reported, "archive_modules": modules, "verified_bindings": bindings,
            "verified_modules": len(modules), "verified_members": len({normalize(origin) for origin in modules.values()})}


def runtime_mirror_binding(host_data, worker_data, layout):
    original, mirror = host_data / "runtime", worker_data / "runtime"
    original_files, mirror_files = layout.tree_files(original), layout.tree_files(mirror)
    require({"python.exe", "python3.dll", "python313.dll"} <= set(original_files), "The assigned host lacks its actual portable runtime")
    require(set(original_files) == set(mirror_files), "CUDA acceptance runtime mirror has missing/extra files")
    expected = {name: sha256(path) for name, path in original_files.items()}
    actual = expected if mirror == original else {name: sha256(path) for name, path in mirror_files.items()}
    require(actual == expected, "CUDA relative portable runtime is not byte-identical to the assigned real host")
    return {"source_host_runtime": str(original), "actual_worker_runtime": str(mirror), "files": expected,
            "same_bytes": True, "scope": "explicit acceptance-only runtime mirror; not the host package or plugin overlay payload"}


def preflight(args):
    host, plugin = plain(args.host_root), plain(args.plugin_root)
    data = host / "UmiOCR-data"
    require(plugin.name == IDS[args.component], "Wrong selected plugin identity")
    require(Path(sys.executable).resolve() == plain(data / "runtime/python.exe") and sys.version_info[:3] == (3, 13, 16) and
            sys.flags.isolated and sys.dont_write_bytecode and sys.flags.utf8_mode, "Run explicitly with the assigned host's CPython 3.13.16 -I -B -X utf8")
    if args.component == "cuda":
        require((plugin.parent.parent / "runtime/python3.dll").is_file(), "Native CUDA launcher requires its genuine relative portable runtime; no alternate worker entry")
    require(args.source_root is not None and args.fixture_root is not None, "Retained source-root and pinned existing fixture-root are required")
    auditor = trusted_tool("audit_runtime_archives")
    layout = trusted_tool("runtime_archive_layout")
    for directory in (data, plugin):
        require(not any(path.name.casefold() == "archive-layout.json" for path in directory.iterdir()), "Legacy archive declaration is not supported")
    host_report, plugin_report = auditor.audit(data), auditor.audit(plugin)
    require(host_report.get("status") == plugin_report.get("status") == "PASS", "Both assigned host and plugin must be complete, source-verified Stored candidates")
    with layout.load_layout(plugin) as view:
        require(view.manifest["kind"] == "plugin" and view.archives, "Missing plugin Stored assembly")
        entries = [dict(entry) for entry in view.entries.values()]
        archive_names = sorted(view.archives)
    manifest = read_json(plugin / "umi-plugin.json")
    require(manifest.get("id") == IDS[args.component], "Plugin manifest identity mismatch")
    result = {"host": str(host), "plugin": str(plugin), "manifest": manifest,
              "host_archives": host_report, "plugin_archives": plugin_report, "archive_names": archive_names, "archive_entries": entries,
              "source": source_binding(plugin, args.source_root, layout), "runtime_lock": lock_binding(plugin, args.component, layout),
              "fixtures": fixture_inputs(args.fixture_root, args.fixtures_sha256, args.component),
              "host_identity": {name: sha256(data / name) for name in ("about.json", "runtime/python.exe", "runtime/python3.dll", "runtime/python313.dll")},
              "source_records": {str(plain(path)): sha256(path) for path in args.source_record},
              "driver_sha256": sha256(Path(__file__))}
    if args.component == "cuda":
        result["worker_runtime_mirror"] = runtime_mirror_binding(data, plugin.parent.parent, layout)
        models = layout.tree_files(plugin / "models")
        require(models and any(name.endswith(".pdiparams") for name in models), "CUDA candidate models are missing")
        result["models"] = {str(path): sha256(path) for path in models.values()}
    else:
        require(args.model_inputs and args.dense_history, "VL requires pinned original model-inputs and historical dense FAIL")
        pinned_json(args.model_inputs, args.model_inputs_sha256)
        http_tool = trusted_tool("model_settings_http_acceptance")
        result["model_paths"] = http_tool.trusted_model_inputs(args.model_inputs)
        result["models"] = result["model_paths"]["verified"]
        result["model_inputs_record"] = {"path": str(plain(args.model_inputs)), "sha256": args.model_inputs_sha256}
        result["dense_historical"] = dense_failure(args.dense_history, args.dense_history_sha256)
    helpers = [PROJECT / "build/tools" / (name + ".py") for name in
               ("audit_runtime_archives", "runtime_archive_layout", "record_gpu_startup", "model_settings_http_acceptance")]
    if args.component == "vl":
        helpers.append(VL_TOOLS / "vl_candidate_acceptance.py")
    result["acceptance_helpers"] = {str(path): sha256(path) for path in helpers}
    return result


class ProcessObservations:
    """Transparent original calls; a kill fallback is a failing assertion, not a new stop path."""
    def __init__(self, pinned, audit, deadline, port=None):
        self.pinned, self.audit, self.deadline, self.port = pinned, audit, deadline, port
        self.processes, self.events, self.starts, self.wire = [], [], [], []
        self.lock = threading.Lock()
        self.abort = self.pending = False
        self.original_popen = subprocess.Popen

    def event(self, value):
        value = {"monotonic": time.monotonic(), **value}
        with self.lock:
            self.events.append(value)
            with (self.audit / "observations.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(value, ensure_ascii=False) + "\n")

    def spawn(self, command, *positional, **keywords):
        require(not self.abort and time.monotonic() < self.deadline, "No new process after the assigned acceptance deadline")
        require(isinstance(command, (list, tuple)) and command and not keywords.get("shell"), "Only original explicit argv without a shell is allowed")
        executable = plain(command[0])
        require(str(executable) in self.pinned and sha256(executable) == self.pinned[str(executable)], "Product tried an unbound executable")
        role = "server" if "--port" in command else "worker" if any(str(part).endswith("worker.py") for part in command) or executable.name == "UmiOCR-CudaWorker.exe" else "binary-probe"
        if role == "server":
            require(str(command[command.index("--port") + 1]) == str(self.port), "Server did not use the assigned unoccupied loopback port")
        process = self.original_popen(command, *positional, **keywords)
        record = {"pid": process.pid, "role": role, "executable": str(executable), "executable_sha256": self.pinned[str(executable)],
                  "argv": list(map(str, command)), "process": process, "kill_fallback": False, "terminate_called": False,
                  "stdout_log": str(getattr(keywords.get("stdout"), "name", "")),
                  "stderr_log": str(getattr(keywords.get("stderr"), "name", ""))}
        self.processes.append(record)
        terminate = process.terminate
        def observed_terminate():
            require(role == "server", "An unexpected worker terminate is not a normal JSON stop")
            require(sha256(executable) == self.pinned[str(executable)], "Bound server executable changed before product shutdown")
            record["terminate_called"] = True
            self.event({"event": "product-owned-terminate", "pid": process.pid, "role": role})
            return terminate()
        def forbidden_kill():
            record["kill_fallback"] = True
            self.event({"event": "product-kill-fallback-blocked-FAIL", "pid": process.pid, "role": role})
            raise KillFallbackBlocked("Original product reached kill fallback; bound PID retained for coordinator: " + str(process.pid))
        process.terminate, process.kill = observed_terminate, forbidden_kill
        self.event({"event": "original-Popen", **{key: value for key, value in record.items() if key != "process"}})
        return process

    def observe_client(self, client, label):
        observations, original_read, original_start = self, client._read, client.start
        class Tee:
            def __init__(self, stream):
                self.stream = stream
            def __iter__(self):
                for line in self.stream:
                    observations.wire.append({"client": label, "raw": line})
                    observations.event({"event": "worker-stdout-original", "client": label, "raw": line})
                    yield line
        def reader(stream=None, responses=None):
            return original_read(Tee(stream or client.process.stdout), responses)
        def start(*arguments, **keywords):
            response = original_start(*arguments, **keywords)
            observations.starts.append({"client": label, "pid": client.process.pid, "response": response})
            observations.event({"event": "start-response-original", "client": label, "pid": client.process.pid, "response": response})
            return response
        client._read, client.start = reader, start

    def call(self, label, function, *, seconds=None, shutdown=False):
        remaining = self.deadline - time.monotonic()
        if seconds is not None:
            remaining = seconds if shutdown else min(seconds, remaining)
        require(remaining > 0, "Assigned acceptance deadline exhausted before " + label)
        completed = queue.Queue()
        def invoke():
            try:
                completed.put((True, function()))
            except BaseException as exc:
                completed.put((False, exc))
        thread = threading.Thread(target=invoke, daemon=True, name="Stored-acceptance-" + label)
        thread.start()
        try:
            ok, result = completed.get(timeout=remaining)
        except queue.Empty:
            self.abort = self.pending = True
            raise AcceptanceTimeout("Operation still active; no cancellation/extra kill; retain bound PIDs: " + label)
        if not ok:
            raise result
        return result

    def snapshot(self):
        return [{**{key: value for key, value in row.items() if key != "process"},
                 "exit_code": row["process"].poll(), "still_running": row["process"].poll() is None} for row in self.processes]


@contextmanager
def execution_environment(data, work):
    helper = trusted_tool("model_settings_http_acceptance")
    environment, overrides, paths = helper.isolated_worker_environment(work)
    for path in set(paths.values()):
        plain(path).mkdir(parents=True, exist_ok=True)
    environment.update({"PIP_NO_INDEX": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"})
    previous_env, previous_cwd, previous_paths, previous_temp = os.environ.copy(), Path.cwd(), sys.path[:], tempfile.tempdir
    try:
        os.environ.clear()
        os.environ.update(environment)
        tempfile.tempdir = environment["TEMP"]
        os.chdir(work)
        sys.path[:0] = [str(data), str(data / "site-packages"), str(data / "app.zip"), str(data / "app.zip/py_src/imports"), str(data / "dependencies.zip")]
        yield overrides
    finally:
        os.chdir(previous_cwd)
        sys.path[:] = previous_paths
        tempfile.tempdir = previous_temp
        os.environ.clear()
        os.environ.update(previous_env)


def cuda_contract(result):
    require(isinstance(result, dict) and result.get("code") == 100 and isinstance(result.get("data"), list) and result["data"], "Ordinary CUDA OCR did not succeed")
    for item in result["data"]:
        require(isinstance(item, dict), "Invalid CUDA OCR item")
        require(isinstance(item.get("text"), str) and item["text"] and isinstance(item.get("score"), float) and math.isfinite(item["score"]) and
                isinstance(item.get("box"), list) and len(item["box"]) == 4 and all(isinstance(point, (list, tuple)) and len(point) == 2 for point in item["box"]),
                "CUDA result violates the existing workflow OCR contract")
    return {"passed": True, "items": len(result["data"]), "scope": "existing test_ocr_workflows result contract, not a new accuracy claim"}


def json_stopped_clients(wire):
    stopped = set()
    for row in wire:
        try:
            payload = json.loads(row["raw"])
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict) and payload.get("ok") is True and payload.get("status") == "stopped":
            stopped.add(row["client"])
    return stopped


def validate_output_paths(args):
    host, plugin, work, audit = map(plain, (args.host_root, args.plugin_root, args.work, args.audit))
    require(host.is_dir() and plugin.is_dir(), "Assigned completed candidates must exist; never wait/build/start a partial candidate")
    for path, parent in ((work, PROJECT / "build/tmp"), (audit, PROJECT / "build/audit")):
        require(path.is_relative_to(parent) and path != parent and not path.exists(), "Work/audit must be NEW task-owned paths below their project roots")
        require(not any(path.is_relative_to(root) or root.is_relative_to(path) for root in (host, plugin)), "Candidate and work/audit must be disjoint")
    require(not work.is_relative_to(audit) and not audit.is_relative_to(work), "Work and audit must be disjoint")
    return host, plugin, work, audit


def execute(args):
    require(os.name == "nt", "Real execution is Windows-only")
    host, plugin, work, audit = validate_output_paths(args)
    work.mkdir(parents=True)
    audit.mkdir(parents=True)
    report = {"schema_version": 1, "component": args.component, "status": "FAIL", "scope": "one CUDA ordinary image" if args.component == "cuda" else "VL ordinary spotting and original selected PDF page 2 only",
              "command_argv": sys.orig_argv, "started_utc": datetime.now(timezone.utc).isoformat(), "gpu_execution_explicit": True,
              "publication_authorized": False, "precision_changes_authorized": False, "requests": [], "errors": [], "deleted": []}
    observer, service, apis, runtime_module, binding = None, None, [], None, None
    contexts = ExitStack()
    try:
        binding = preflight(args)
        write_new(audit / "inputs-before.json", binding)
        if "dense_historical" in binding:
            report["dense_historical"] = binding["dense_historical"]
        port = None
        if args.component == "vl":
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
        executables = [host / "UmiOCR-data/runtime/python.exe", plugin / ("UmiOCR-CudaWorker.exe" if args.component == "cuda" else "resources/llama.cpp/llama-server.exe")]
        observer = ProcessObservations({str(plain(path)): sha256(path) for path in executables}, audit, time.monotonic() + args.deadline_seconds, port)
        report["environment"] = contexts.enter_context(execution_environment(host / "UmiOCR-data", work))
        with patch.object(subprocess, "Popen", observer.spawn):
            sys.path.insert(0, str(plugin.parent))
            module = importlib.import_module(IDS[args.component] + ".api")
            require(Path(module.__file__).resolve() == plugin / "api.py", "API import escaped the assigned candidate")
            if args.component == "cuda":
                api = module.Api({"device": "gpu:0", "preprocessThreads": 2})
                apis.append(("cuda", api))
                observer.observe_client(api._worker, "cuda")
                error = observer.call("cuda-start", lambda: api.start({"taskType": "document"}))
                require(not error, "Original CUDA Api.start failed: " + str(error))
                startup = api.get_status()["startup"]
                trusted_tool("record_gpu_startup").validate_startup(startup, api._worker.process.pid, plugin.parent.parent, "gpu:0")
                report["archive_origins"] = archive_module_origins(startup, plugin, binding["archive_names"], binding["archive_entries"])
                result = observer.call("cuda-ordinary", lambda: api.runPath(binding["fixtures"]["cases"][0]["path"]))
                write_new(audit / "ordinary-result.json", result)
                report["requests"].append({"id": "ordinary", "metrics": cuda_contract(result)})
            else:
                metrics_tool = trusted_tool("vl_candidate_acceptance", VL_TOOLS)
                runtime_module = importlib.import_module(IDS["vl"] + ".runtime")
                ocr_module = importlib.import_module(IDS["vl"] + ".ocr_api")
                service = runtime_module.getService()
                require(not service.isRunning(), "Never adopt an existing product service")
                models = binding["model_paths"]
                config = {"service.mainModel": models["model"], "service.mmprojModel": models["projector"], "service.port": port,
                          "resources.contextLength": 8192, "resources.slots": 1, "resources.maxOutputTokens": 4096,
                          "resources.timeoutSeconds": 120, "resources.startupTimeoutSeconds": 240,
                          "resources.cacheKeyType": "f16", "resources.cacheValueType": "f16",
                          "pipeline.layoutModelDir": models["layout"], "pipeline.cudaDevice": "gpu:0", "maxOutputTokens": 4096}
                report["original_budget"] = config
                for label, factory, fixture in (("ordinary", ocr_module.Api, binding["fixtures"]["cases"][0]),
                                                 ("selected-document", module.Api, binding["fixtures"]["cases"][1])):
                    api = factory(config)
                    apis.append((label, api))
                    observer.observe_client(api._worker, label)
                    progress = []
                    if label == "selected-document":
                        api.on_partial = progress.append
                    error = observer.call(label + "-start", lambda: api.start(config))
                    require(not error, "Original VL Api.start failed: " + str(error))
                    start = observer.starts[-1]
                    verified_origins = archive_module_origins(start["response"], plugin, binding["archive_names"], binding["archive_entries"])
                    status = service.get_status()
                    require(status["pid"] > 0 and Path(status["command"][0]).resolve() == plugin / "resources/llama.cpp/llama-server.exe", "VL service is not the bound bundled native engine")
                    if "service_before" not in report:
                        report["service_before"] = status
                    require(status["pid"] == report["service_before"]["pid"], "Original spotting/document did not reuse its service instance")
                    require(service.get_execution_info().get("device") in {"GPU", "GPU+CPU"}, "VL did not report actual CUDA load")
                    if label == "ordinary":
                        result = observer.call(label, lambda: api.runPath(fixture["path"]))
                    else:
                        result = observer.call(label, lambda: api.parseDoc({"path": fixture["path"], "pageRange": fixture["pageRange"],
                                                    "taskTimeoutSeconds": 1800, "assetOutputRoot": str(work / "document-assets")}))
                    write_new(audit / (label + "-result.json"), result)
                    metrics = metrics_tool.result_metrics(result, fixture["truth"], fixture["size"], fixture.get("expectedPages"))
                    if label == "selected-document":
                        metrics["progressOnlySelectedPage"] = metrics_tool.document_progress_complete(progress, fixture["expectedPages"])
                        write_new(audit / "document-progress.json", progress)
                    report["requests"].append({"id": label, "metrics": metrics, "worker_start_original": start, "verified_archive_origins": verified_origins})
                    require(metrics["passed"] and metrics.get("progressOnlySelectedPage", True), "Original representative VL quality criteria failed: " + label)
                report["native_execution"] = service.get_execution_info()
                report["dense_historical"] = binding["dense_historical"]
            require(not ({name.split(".", 1)[0] for name in sys.modules} & {"paddle", "paddleocr", "paddlex", "onnxruntime"}), "Private inference dependencies leaked into the host")
    except BaseException:
        report["errors"].append(traceback.format_exc())
    finally:
        # Re-enter only the observation hook, not an alternative lifecycle. The
        # original release/shutdown implementations remain the operations tested.
        if observer is not None:
            with patch.object(subprocess, "Popen", observer.spawn):
                if not observer.pending:
                    for label, api in reversed(apis):
                        try:
                            released = observer.call(label + "-release", api.release, seconds=30, shutdown=True)
                            report.setdefault("release", []).append({"client": label, "result": released})
                            require(isinstance(released, str) and released.startswith("[Success]"), "Original API did not report successful release")
                            if api._worker.reader is not None:
                                api._worker.reader.join(timeout=2)
                        except BaseException:
                            report["errors"].append(traceback.format_exc())
                        if observer.pending:
                            break
                    if service is not None and not observer.pending:
                        try:
                            report["service_shutdown_original"] = observer.call("service-shutdown", service.shutdown_owned, seconds=30, shutdown=True)
                        except BaseException:
                            report["errors"].append(traceback.format_exc())
                else:
                    report["errors"].append("Active timed-out original operation: release is not fabricated, no extra cancellation/kill or path cleanup")
                report["processes"] = observer.snapshot()
                report["start_responses_original"] = observer.starts
                report["lifecycle_events"] = [event for event in observer.events if event["event"] != "worker-stdout-original"]
                live = [row["pid"] for row in report["processes"] if row["still_running"]]
                report["retained_pids"] = live
                if live or observer.pending or any(row["kill_fallback"] for row in report["processes"]):
                    report["errors"].append("Owned live/kill-fallback/timeout processes are FAIL; PIDs and all logs retained for coordinator")
                    if service is not None:
                        # Failure-only: prevent a second unobserved atexit retry
                        # from discarding the retained PID. Never turns FAIL into PASS.
                        atexit.unregister(service.shutdown_owned)
                        report["failure_atexit_retry_suppressed"] = True
                workers = [row for row in report["processes"] if row["role"] == "worker"]
                stopped = json_stopped_clients(observer.wire)
                report["worker_json_stop_normal_exit"] = bool(workers) and all(row["exit_code"] == 0 and not row["kill_fallback"] for row in workers) and all(label in stopped for label, _api in apis)
                if not report["worker_json_stop_normal_exit"]:
                    report["errors"].append("Actual worker JSON stop plus exit code 0 was not proven")
                report["service_shutdown_semantics"] = "Original product shutdown_owned; on Windows product terminate is recorded, not described as JSON/CTRL_BREAK graceful exit"
        if binding is not None and not (observer and (observer.pending or any(row["still_running"] or row["kill_fallback"] for row in observer.snapshot()))):
            try:
                after = preflight(args)
                write_new(audit / "inputs-after.json", after)
                report["execution_inputs_unchanged"] = after == binding
                require(after == binding, "Candidate/source/lock/ZIP/fixture/model inputs changed during acceptance")
            except BaseException:
                report["errors"].append(traceback.format_exc())
        expected = 1 if args.component == "cuda" else 2
        report["representative_cases_passed"] = len(report["requests"]) == expected and all(row["metrics"].get("passed") for row in report["requests"])
        if not report["errors"] and report["representative_cases_passed"] and report.get("execution_inputs_unchanged"):
            report["status"] = "PASS" if args.component == "cuda" else "PASS_WITH_LIMITATIONS"
        report["limitations"] = ["Not a full resource/quality matrix, real GUI, publication or license approval",
                                  "No model downloads/quantization or precision changes; original model bytes are hashed before/after",
                                  "Offline cache flags/local model paths are applied; no universal native-network interception is claimed",
                                  "VL dense historical FAIL is not rerun, waived or converted into representative-case PASS",
                                  "On timeout no replacement stop path, extra kill, candidate overwrite or cleanup is attempted"]
        if not (observer and observer.pending):
            try:
                contexts.close()
            except BaseException:
                report["errors"].append(traceback.format_exc())
                report["status"] = "FAIL"
        report["trusted_helpers_sha256"] = TOOLS_USED.copy()
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        report["interpreter"] = {"path": sys.executable, "version": sys.version}
        write_new(audit / "result.json", report)
    print(json.dumps({key: report[key] for key in ("component", "status", "representative_cases_passed")}, ensure_ascii=False))
    return 0 if report["status"] in {"PASS", "PASS_WITH_LIMITATIONS"} else 1


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--component", choices=IDS, required=True)
    for name in ("host-root", "plugin-root", "work", "audit"):
        value.add_argument("--" + name, required=True, type=Path)
    for name in ("source-root", "fixture-root", "model-inputs", "dense-history"):
        value.add_argument("--" + name, type=Path)
    for name in ("fixtures-sha256", "model-inputs-sha256", "dense-history-sha256"):
        value.add_argument("--" + name)
    value.add_argument("--source-record", type=Path, action="append", default=[])
    value.add_argument("--deadline-seconds", type=int, default=540)
    value.add_argument("--execute-gpu", action="store_true")
    return value


def main(argv=None):
    args = parser().parse_args(argv)
    require(120 <= args.deadline_seconds <= 1800, "Explicit acceptance window must be 120..1800 seconds")
    if not args.execute_gpu:
        print(json.dumps({"planOnly": True, "gpuExecuted": False, "productImported": False, "component": args.component,
                          "cases": ["ordinary"] if args.component == "cuda" else ["ordinary", "selected-document"],
                          "dense": "historical FAIL retained; not run", "required": "Completed assigned candidates, corresponding source, pinned existing fixtures, explicit GPU window",
                          "copiesCandidateOrModels": False}, ensure_ascii=False, indent=2))
        return 0
    return execute(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AcceptanceError, OSError, ValueError) as exc:
        print("STORED ACCEPTANCE BLOCKED: " + str(exc), file=sys.stderr)
        raise SystemExit(2)
