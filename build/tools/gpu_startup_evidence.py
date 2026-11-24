"""Read-only evidence for the 3.0.4 CUDA startup hotfix, never OCR/approval.

Only the named startup scope may consume this result. No product code is loaded,
no archive is extracted, and no program, GPU operation or OCR workflow is run.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import xml.etree.ElementTree as ET

_spec = importlib.util.spec_from_file_location(
    "umi_startup_gate_inputs", Path(__file__).with_name("release_gate_inputs.py")
)
gates = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gates)

REPOSITORY = Path(__file__).resolve().parents[2]
VALIDATION_SCOPE = "cuda-startup-hotfix"
RECORD_SCOPE = "GPU_STARTUP_ONLY_NOT_OCR_OR_RELEASE_AUTHORIZATION"
PLUGIN_VERSION = "3.0.4"
HOST_VERSION = "3.0.3"
PLUGIN_RELATIVE = "UmiOCR-data/plugins/" + gates.PLUGIN_ID
LAUNCHER = "UmiOCR-CudaWorker.exe"
MODEL_NAMES = [
    "PP-LCNet_x1_0_doc_ori", "UVDoc", "PP-LCNet_x1_0_textline_ori",
    "PP-OCRv6_medium_det", "PP-OCRv6_medium_rec",
]
OFFICIAL_ARCHIVE_SHA256 = {
    "base303": "c9b50f780c3923bd22169ed095fbe69dc5791b3a75370ccb206dac51698cf400",
    "gpu303": "be8bd1f8d20181500370cc5a64cb867514478a45bc0f897c63a3ebde96ce4485",
}
NATIVE_SOURCES = (
    "build/windows/CudaWorker/CMakeLists.txt", "build/windows/CudaWorker/worker_main.cpp",
    "build/windows/CudaWorker/resource.rc.in", "build/windows/CudaWorker/worker.manifest",
)
WORKER_OCR_FUNCTIONS = ("assert_cuda", "create_engine", "decode_request", "convert_results", "stop_engine")
API_OCR_METHODS = ("_normalize_config", "_validate_config", "_request", "runPath", "runBytes", "runBase64")
EXECUTABLE_SUFFIXES = {".exe", ".dll", ".pyd", ".py", ".pyc", ".qml", ".js", ".zip", ".rcc", ".qm"}


def local_path(value) -> Path:
    if not isinstance(value, (str, Path)):
        raise ValueError("Startup evidence requires a local project path")
    path = Path(value)
    if (not path.is_absolute() or ".." in path.parts or
            str(path).startswith(("\\\\", "//", "\\/", "/\\")) or
            not path.is_relative_to(REPOSITORY)):
        raise ValueError("Startup evidence must stay in this project, without parent/network paths")
    gates.no_links(path)
    return path


def reference(value):
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise ValueError("Startup evidence requires exactly path and sha256")
    local_path(value["path"])
    return gates.evidence_file(value)


def files(root: Path) -> dict[str, str]:
    """Walk without following even a directory junction; hash actual bytes."""
    root = local_path(root)
    if not root.is_dir():
        raise ValueError("Startup evidence tree is missing")
    result, folded, pending = {}, set(), [root]
    while pending:
        directory = pending.pop()
        for path in sorted(directory.iterdir()):
            local_path(path)
            relative = path.relative_to(root).as_posix()
            if relative.casefold() in folded or any(ord(char) < 32 for char in relative):
                raise ValueError("Ambiguous startup evidence filename")
            folded.add(relative.casefold())
            if path.is_dir():
                pending.append(path)
            elif path.is_file():
                result[relative] = gates.digest(path)
            else:
                raise ValueError("Non-regular startup evidence member")
    if not result:
        raise ValueError("Empty startup evidence tree")
    return result


def adapter_sources(records):
    return {name: value for name, value in records.items() if name.endswith(".py")
            and not {"vendor", "models", "__pycache__"} & set(PurePosixPath(name).parts)}


def archive_files(path: Path) -> dict[str, str]:
    """Hash a tar as data, never extract/import/execute its contents."""
    result, seen = {}, set()
    with tarfile.open(path, "r|xz") as archive:
        for member in archive:
            name = member.name.rstrip("/") if member.isdir() else member.name
            pure = PurePosixPath(name)
            if (not name or pure.as_posix() != name or pure.is_absolute() or
                    any(part in {".", ".."} or ":" in part or "\\" in part for part in pure.parts) or
                    any(ord(char) < 32 for char in name) or name.casefold() in seen):
                raise ValueError("Unsafe/duplicate official baseline tar member")
            seen.add(name.casefold())
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError("Official baseline must not contain links/special files")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("Unreadable official baseline member")
            with stream:
                result[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    if not result:
        raise ValueError("Empty official baseline archive")
    return result


def version(document) -> str:
    value = document.get("version")
    if isinstance(value, dict):
        if any(type(value.get(key)) is not int for key in ("major", "minor", "patch")):
            raise ValueError("Invalid startup host version")
        value = ".".join(str(value[key]) for key in ("major", "minor", "patch"))
    if not isinstance(value, str):
        raise ValueError("Invalid startup product version")
    return value


def _function_nodes(path, names, class_name=None):
    try:
        tree = ast.parse(path.read_text("utf-8-sig"), filename=path.name)
    except SyntaxError as exc:
        raise ValueError("Invalid OCR adapter Python source") from exc
    body = tree.body
    if class_name:
        classes = [node for node in body if isinstance(node, ast.ClassDef) and node.name == class_name]
        if len(classes) != 1:
            raise ValueError("Missing/duplicate baseline adapter class")
        body = classes[0].body
    result = {}
    for name in names:
        nodes = [node for node in body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
        if len(nodes) != 1:
            raise ValueError("Missing/duplicate OCR computation function")
        result[name] = ast.dump(nodes[0], include_attributes=False)
    return result


def unchanged_ocr(plugin: Path, baseline: Path, current_records=None, baseline_records=None) -> dict:
    current = adapter_sources(files(plugin) if current_records is None else current_records)
    old = adapter_sources(files(baseline) if baseline_records is None else baseline_records)
    if set(current) != set(old) or not {"worker.py", "api.py", "coordinates.py", "config.py"} <= set(old):
        raise ValueError("The startup hotfix changed the existing adapter module set")
    compared = {}
    for filename, names, class_name in (
        ("worker.py", WORKER_OCR_FUNCTIONS, None), ("api.py", API_OCR_METHODS, "Api"),
    ):
        if _function_nodes(plugin / filename, names, class_name) != _function_nodes(baseline / filename, names, class_name):
            raise ValueError("The startup hotfix changed original OCR computation: " + filename)
        compared[filename] = list(names)
    unchanged = {name: value for name, value in old.items() if name not in {"api.py", "worker.py"}}
    if any(current[name] != checksum for name, checksum in unchanged.items()):
        raise ValueError("The startup hotfix changed an existing non-startup adapter module")
    return {"verified": True, "ast_compared": compared, "byte_identical_modules": unchanged}


def historical_functionality(plugin: Path, baseline_records) -> dict:
    """Official 3.0.3 functionality supports cuDNN's condition, NOT new OCR PASS."""
    path = plugin / "gpu-e2e-evidence.json"
    raw = gates.read_json(path)
    sources = adapter_sources(baseline_records)
    lock = plugin / "runtime.lock.json"
    valid = (
        raw.get("test_type") == "real_gpu_ocr_workflows_e2e" and raw.get("status") == "PASS" and
        re.fullmatch(r"gpu:[0-9]+", str(raw.get("device", ""))) is not None and
        raw.get("architecture") == {
            "type": "separate-worker-stdio-ipc", "host_loaded_proprietary_modules": [],
            "ipc_payload": "JSON-lines path/base64 -> JSON OCR result",
        } and raw.get("plugin_source_sha256") == sources and
        raw.get("plugin_runtime_lock_sha256") == gates.digest(lock) and
        raw.get("model_initialization") == MODEL_NAMES and
        type(raw.get("ffmpeg_backend_dll_count")) is int and raw["ffmpeg_backend_dll_count"] == 0 and
        type(raw.get("cusolvermg_dll_count")) is int and raw["cusolvermg_dll_count"] == 0 and
        isinstance(raw.get("exercised_paths"), list) and
        {"batch OCR", "document PDF OCR", "CUDA-only failure paths"} <= set(raw["exercised_paths"])
    )
    if not valid:
        raise ValueError("Official 3.0.3 historical functionality evidence is malformed or unbound")
    return {"verified": True, "release_version": HOST_VERSION,
            "official_archive_sha256": OFFICIAL_ARCHIVE_SHA256["gpu303"],
            "evidence": {"name": path.name, "sha256": gates.digest(path)},
            "use": "historical material additional functionality only; not current OCR acceptance"}


def verify_baselines(matrix, plugin: Path):
    receipt_path, public_receipt = reference(matrix.get("baselines"))
    receipt = gates.read_json(receipt_path)
    baseline = receipt.get("baselines")
    archives = matrix.get("official_archives")
    if not isinstance(baseline, dict) or set(baseline) != set(OFFICIAL_ARCHIVE_SHA256) or not isinstance(archives, dict) or set(archives) != set(OFFICIAL_ARCHIVE_SHA256):
        raise ValueError("The startup scope requires both fixed official 3.0.3 baselines")
    roots, trees, public = {}, {}, {}
    for name, expected in OFFICIAL_ARCHIVE_SHA256.items():
        item = baseline[name]
        if not isinstance(item, dict) or item.get("version") != HOST_VERSION:
            raise ValueError("Baseline identity must remain 3.0.3")
        archive_path, archive_public = reference(archives[name])
        if archive_public["sha256"] != expected or item.get("archive", {}).get("sha256") != expected:
            raise ValueError("Baseline archive is not the fixed official 3.0.3 tar")
        root = local_path(item.get("path"))
        actual = files(root)
        if actual != archive_files(archive_path):
            raise ValueError("Extracted baseline file set/bytes differ from the official tar")
        roots[name], trees[name] = root, actual
        public[name] = {"archive": archive_public, "actual_tree": gates.tree_binding(actual)}
    base = roots["base303"]
    baseline_plugin = roots["gpu303"] / PLUGIN_RELATIVE
    about = gates.read_json(base / "UmiOCR-data/about.json")
    if version(about) != HOST_VERSION or version(gates.read_json(baseline_plugin / "umi-plugin.json")) != HOST_VERSION:
        raise ValueError("Official startup baselines must both identify 3.0.3")
    current_files = files(plugin)
    baseline_files = {name.removeprefix(PLUGIN_RELATIVE + "/"): value
                      for name, value in trees["gpu303"].items() if name.startswith(PLUGIN_RELATIVE + "/")}
    closures = {}
    for directory in ("vendor", "models"):
        prefix = directory + "/"
        old = {name: value for name, value in baseline_files.items() if name.startswith(prefix)}
        current = {name: value for name, value in current_files.items() if name.startswith(prefix)}
        if not old or current != old:
            raise ValueError("The startup scope changed actual " + directory + " file set/SHA256")
        closures[directory] = gates.tree_binding(current)
    ocr = unchanged_ocr(plugin, baseline_plugin, current_files, baseline_files)
    history = historical_functionality(baseline_plugin, baseline_files)
    return {"verified": True, "receipt": public_receipt, "official_baselines": public,
            "unchanged_closures": closures, "unchanged_ocr": ocr,
            "historical_functionality": history}, trees["base303"], about, current_files


def embedded_manifest(path: Path) -> dict:
    """Read RT_MANIFEST(24)/1 from PE resource bytes, not LoadLibrary/EXE code."""
    local_path(path)
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Unexpectedly large CUDA launcher")
    data = path.read_bytes()

    def number(offset, width=4):
        if offset < 0 or offset + width > len(data):
            raise ValueError("Truncated CUDA launcher PE")
        return int.from_bytes(data[offset:offset + width], "little")

    if data[:2] != b"MZ":
        raise ValueError("CUDA launcher is not a PE executable")
    pe = number(0x3C)
    if data[pe:pe + 4] != b"PE\0\0" or number(pe + 4, 2) != 0x8664:
        raise ValueError("CUDA launcher must be an x64 PE executable")
    count, optional_size = number(pe + 6, 2), number(pe + 20, 2)
    optional = pe + 24
    if number(optional, 2) != 0x20B or count < 1 or count > 96 or optional_size < 136:
        raise ValueError("Invalid CUDA launcher PE32+ header")
    sections = []
    for index in range(count):
        offset = optional + optional_size + index * 40
        sections.append((number(offset + 12), number(offset + 16), number(offset + 20)))

    def mapped(rva, size):
        hits = [raw + rva - va for va, length, raw in sections if va <= rva and rva + size <= va + length]
        if len(hits) != 1 or hits[0] < 0 or hits[0] + size > len(data):
            raise ValueError("Invalid CUDA launcher resource RVA")
        return hits[0]

    resource_rva, resource_size = number(optional + 128), number(optional + 132)
    if not resource_rva or resource_size < 16:
        raise ValueError("CUDA launcher has no embedded manifest resources")
    base = mapped(resource_rva, resource_size)

    def entries(relative):
        if relative < 0 or relative + 16 > resource_size:
            raise ValueError("Invalid CUDA launcher resource directory")
        named, ids = number(base + relative + 12, 2), number(base + relative + 14, 2)
        total = named + ids
        if total > 4096 or relative + 16 + total * 8 > resource_size:
            raise ValueError("Invalid CUDA launcher resource entries")
        values = [(number(base + relative + 16 + index * 8), number(base + relative + 20 + index * 8)) for index in range(total)]
        if len({key for key, _ in values}) != len(values):
            raise ValueError("Duplicate CUDA launcher resources")
        return dict(values)

    def directory(parent, key):
        value = entries(parent).get(key)
        if value is None or not value & 0x80000000:
            raise ValueError("CUDA launcher manifest resource 24/1 is missing")
        return value & 0x7FFFFFFF

    leaves = entries(directory(directory(0, 24), 1))
    if not leaves:
        raise ValueError("CUDA launcher manifest has no language resource")
    hashes = []
    for key, offset in leaves.items():
        if key & 0x80000000 or offset & 0x80000000 or offset + 16 > resource_size:
            raise ValueError("Invalid CUDA launcher manifest data entry")
        rva, length = number(base + offset), number(base + offset + 4)
        if not length or length > 1024 * 1024:
            raise ValueError("Invalid CUDA launcher manifest size")
        start = mapped(rva, length)
        payload = data[start:start + length]
        try:
            document = ET.fromstring(payload)
        except ET.ParseError as exc:
            raise ValueError("CUDA launcher embedded manifest is not XML") from exc
        codepages = document.findall(".//{http://schemas.microsoft.com/SMI/2019/WindowsSettings}activeCodePage")
        if len(codepages) != 1 or (codepages[0].text or "").strip() != "UTF-8":
            raise ValueError("CUDA launcher embedded activeCodePage is not UTF-8")
        hashes.append(hashlib.sha256(payload).hexdigest())
    return {"verified": True, "resource_type": 24, "resource_id": 1,
            "active_code_page": "UTF-8", "resource_sha256": sorted(hashes),
            "launcher_sha256": gates.digest(path)}


def _host_execution(records):
    return {name: value for name, value in records.items()
            if name == "Umi-OCR.exe" or name.startswith("UmiOCR-data/") and not name.startswith("UmiOCR-data/plugins/")}


def verify_installation(root, plugin_records, base_records):
    root = local_path(root)
    actual = files(root)
    installed = {name.removeprefix(PLUGIN_RELATIVE + "/"): value for name, value in actual.items()
                 if name.startswith(PLUGIN_RELATIVE + "/")}
    if installed != plugin_records:
        raise ValueError("Tested installation plugin source/EXE/model/runtime payload differs from current artifact")
    host = _host_execution(base_records)
    if not host or any(actual.get(name) != checksum for name, checksum in host.items()):
        raise ValueError("Tested installation changed the official 3.0.3 host baseline")
    extras = set(_host_execution(actual)) - set(host)
    if any(PurePosixPath(name).suffix.lower() in EXECUTABLE_SUFFIXES for name in extras):
        raise ValueError("Tested installation added executable host code outside the official baseline")
    return root


def verify_case(path, plugin, plugin_records, base_records, about, recorder_sha):
    raw = gates.read_json(path)
    if not isinstance(raw, dict) or raw.get("test_type") != "real_gpu_worker_startup_only" or raw.get("status") != "PASS" or raw.get("scope") != RECORD_SCOPE:
        raise ValueError("A matrix cell must be an actual worker-startup-only record")
    if (raw.get("public_release_allowed") is not False or type(raw.get("ocr_operations")) is not int or
            raw["ocr_operations"] != 0 or raw.get("ocr_workflows_status") != "NOT_RUN"):
        raise ValueError("Startup evidence cannot claim OCR or publication approval")
    if (raw.get("plugin_version") != PLUGIN_VERSION or not gates._same_binding(raw.get("host_version"), about["version"]) or
            raw.get("normal_exit") is not True or type(raw.get("worker_exit_code")) is not int or raw["worker_exit_code"] != 0 or
            raw.get("host_loaded_proprietary_modules") != [] or raw.get("execution_inputs_unchanged") is not True or
            raw.get("exception") is not None or raw.get("shutdown_exception") is not None):
        raise ValueError("Worker did not cleanly start/exit with unchanged 3.0.4/3.0.3 inputs")
    acp = raw.get("parent_native_code_page")
    if type(acp) is not int or acp not in {936, 65001}:
        raise ValueError("Matrix parent ACP must be 936 or 65001")
    installation = verify_installation(raw.get("installation"), plugin_records, base_records)
    non_ascii = not str(installation).isascii()
    if raw.get("installation_contains_non_ascii") is not non_ascii or non_ascii and " " not in str(installation):
        raise ValueError("Matrix path must report actual ASCII/non-ASCII-with-spaces installation")
    models = {name.removeprefix("models/"): value for name, value in plugin_records.items() if name.startswith("models/")}
    if (raw.get("plugin_source_sha256") != adapter_sources(plugin_records) or
            raw.get("plugin_runtime_lock_sha256") != gates.digest(plugin / "runtime.lock.json") or
            raw.get("launcher") != {"file": LAUNCHER, "sha256": gates.digest(plugin / LAUNCHER)} or
            raw.get("models") != gates.tree_binding(models) or raw.get("recording_tool_sha256") != recorder_sha):
        raise ValueError("Startup raw source/EXE/model/lock/recording-tool SHA256 binding is stale")
    startup, pid, device = raw.get("startup"), raw.get("worker_pid"), raw.get("device")
    if type(pid) is not int or pid <= 0 or not re.fullmatch(r"gpu:[0-9]+", str(device)) or not isinstance(startup, dict):
        raise ValueError("Missing actual CUDA worker PID/device/startup")
    if (type(startup.get("pid")) is not int or startup["pid"] != pid or
            type(startup.get("native_code_page")) is not int or startup["native_code_page"] != 65001 or
            startup.get("python_utf8_mode") is not True or
            startup.get("stdin_encoding") != "utf-8" or startup.get("stdout_encoding") != "utf-8" or
            startup.get("model_names") != MODEL_NAMES or startup.get("device") != device or
            not isinstance(startup.get("python_version"), str) or not startup["python_version"].startswith("3.13.")):
        raise ValueError("Actual worker PID/UTF-8/five-model CUDA initialization is invalid")
    if local_path(startup.get("python_dll")) != installation / "UmiOCR-data/runtime/python313.dll":
        raise ValueError("Actual worker Python DLL is outside the unchanged host runtime")
    if local_path(startup.get("executable")) != installation / PLUGIN_RELATIVE / LAUNCHER:
        raise ValueError("Actual worker executable is not the tested native launcher")
    log, public_log = reference(raw.get("startup_log"))
    try:
        events = [json.loads(line, object_pairs_hook=gates._object) for line in log.read_text("utf-8-sig").splitlines() if line.strip()]
    except (ValueError, TypeError) as exc:
        raise ValueError("Startup raw log is malformed") from exc
    if (len(events) != 3 or events[0].get("operation") != "start" or events[0].get("result") not in (None, "") or
            not gates._same_binding(events[1], {"startup": startup}) or
            not gates._same_binding(events[2], {"status": "PASS", "normal_exit": True, "ocr_operations": 0})):
        raise ValueError("Startup log does not independently record the same PID/start/clean exit without OCR")
    diagnostics = raw.get("worker_diagnostics")
    if not isinstance(diagnostics, list):
        raise ValueError("Startup worker diagnostic references are missing")
    for item in diagnostics:
        reference(item)
    return (acp, non_ascii), installation, {"parent_native_code_page": acp, "non_ascii_with_spaces": non_ascii,
                                         "worker_pid": pid, "startup_log": public_log, "verified": True}


def verify_host_startup(value, binding, installations, base_records, about):
    path, public = reference(value)
    raw = gates.read_json(path)
    if (not isinstance(raw, dict) or type(raw.get("schema_version")) is not int or raw["schema_version"] != 1 or
            raw.get("test_type") != "real_host_startup_exit" or raw.get("status") != "PASS" or
            not gates._same_binding(raw.get("binding"), binding) or not gates._same_binding(raw.get("host_version"), about["version"]) or
            local_path(raw.get("installation")) not in installations or
            raw.get("host_executable_sha256") != base_records.get("Umi-OCR.exe") or
            type(raw.get("host_pid")) is not int or raw["host_pid"] <= 0 or raw.get("http_ready_before_quit") is not True or
            raw.get("normal_exit") is not True or type(raw.get("exit_code")) is not int or raw["exit_code"] != 0 or
            type(raw.get("ocr_operations")) is not int or raw["ocr_operations"] != 0 or
            raw.get("ocr_workflows_status") != "NOT_RUN" or raw.get("public_release_allowed") is not False):
        raise ValueError("Current unchanged-host readiness/normal-exit evidence is missing or unbound")
    _, log = reference(raw.get("startup_log"))
    return {"verified": True, "record": public, "startup_log": log, "host_version": HOST_VERSION,
            "host_executable_sha256": raw["host_executable_sha256"]}


def verify_startup_matrix(path: Path, staging: Path, binding: dict | None = None) -> dict:
    path, staging = local_path(path), local_path(staging)
    matrix = gates.read_json(path)
    actual_version, actual_binding, source = gates.artifact_inputs(staging, "gpu")
    if binding is not None and not gates._same_binding(binding, actual_binding):
        raise ValueError("Startup matrix was supplied a stale artifact binding")
    binding = actual_binding
    if (not isinstance(matrix, dict) or type(matrix.get("schema_version")) is not int or matrix["schema_version"] != 1 or
            matrix.get("test_type") != "real_gpu_startup_matrix" or matrix.get("validation_scope") != VALIDATION_SCOPE or
            matrix.get("plugin_version") != PLUGIN_VERSION or actual_version != PLUGIN_VERSION or
            not gates._same_binding(matrix.get("binding"), binding)):
        raise ValueError("Startup-only scope is restricted to the current bound CUDA 3.0.4 payload")
    metadata = gates.artifact_metadata_root(staging, "gpu")
    plugin = staging / PLUGIN_RELATIVE
    manifest = gates.read_json(plugin / "umi-plugin.json")
    runtime = manifest.get("runtime", {})
    if (manifest.get("id") != gates.PLUGIN_ID or runtime.get("vendor_dirs") != [] or runtime.get("dll_dirs") != [] or
            runtime.get("process_boundary", {}).get("type") != "separate-worker-stdio-ipc" or
            runtime["process_boundary"].get("entry") != LAUNCHER):
        raise ValueError("The startup scope requires the separate native CUDA worker")
    baseline, base_records, about, plugin_records = verify_baselines(matrix, plugin)
    sources = adapter_sources(plugin_records)
    if any(source.get(PLUGIN_RELATIVE + "/" + name) != value for name, value in sources.items()):
        raise ValueError("Actual startup adapter source differs from corresponding source")
    native_sources = {}
    for name in (*NATIVE_SOURCES, "build/tools/record_gpu_startup.py"):
        original = local_path(REPOSITORY / name)
        exported = metadata / "source" / name
        if not original.is_file() or not exported.is_file() or gates.digest(original) != gates.digest(exported) or source.get(name) != gates.digest(exported):
            raise ValueError("Current native/recording-tool source is missing or differs from corresponding source")
        native_sources[name] = gates.digest(exported)
    native_manifest = embedded_manifest(plugin / LAUNCHER)
    native_manifest["source_sha256"] = native_sources[NATIVE_SOURCES[-1]]
    lock = gates.read_json(plugin / "runtime.lock.json")
    if not isinstance(lock.get("files"), list) or not any(
        item == {"path": LAUNCHER, "sha256": gates.digest(plugin / LAUNCHER)} for item in lock["files"]
    ):
        raise ValueError("The current native launcher is not bound by runtime.lock.json")
    cases = matrix.get("cases")
    if not isinstance(cases, list) or len(cases) != 4:
        raise ValueError("Startup evidence requires all four independent ACP/path cells")
    seen, records, installations, references = set(), [], set(), set()
    for value in cases:
        raw, public = reference(value)
        if raw in references:
            raise ValueError("Startup matrix cannot reuse the same raw record")
        references.add(raw)
        cell, installation, result = verify_case(raw, plugin, plugin_records, base_records, about, native_sources["build/tools/record_gpu_startup.py"])
        if cell in seen:
            raise ValueError("Startup matrix has duplicate ACP/path cells")
        seen.add(cell)
        installations.add(installation)
        result["record"] = public
        records.append(result)
    if seen != {(936, False), (936, True), (65001, False), (65001, True)}:
        raise ValueError("Startup evidence is missing a required ACP/path cell")
    host = verify_host_startup(matrix.get("host_startup"), binding, installations, base_records, about)
    return {"schema_version": 1, "test_type": "verified_gpu_startup_matrix", "validation_scope": VALIDATION_SCOPE,
            "status": "PASS", "verified": True, "binding": binding,
            "plugin_version": PLUGIN_VERSION, "host_version": HOST_VERSION,
            "evidence": {"name": path.name, "sha256": gates.digest(path)},
            "cases": records, "host_startup": host, "baselines": baseline,
            "native_manifest": native_manifest, "native_source_sha256": native_sources,
            "gpu_ocr_e2e": "NOT_RUN", "ocr_workflows_status": "NOT_RUN", "ocr_operations": 0,
            "public_release_allowed": False, "blockers": []}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--staging-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify_startup_matrix(args.matrix.absolute(), args.staging_root.absolute())
    except (OSError, ValueError, TypeError, KeyError, AttributeError, tarfile.TarError) as exc:
        print(json.dumps({"status": "BLOCK", "public_release_allowed": False,
                          "blockers": [str(exc) if isinstance(exc, ValueError) else "Cannot verify startup evidence inputs."]}))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
