"""Synthetic, offline startup-scope evidence tests; never launch product code."""
from __future__ import annotations

from contextlib import ExitStack
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


startup = load("startup_evidence_test", ROOT / "build/tools/gpu_startup_evidence.py")


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else (data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)).encode("utf-8"))


def pe_manifest(xml):
    """A small PE32+ resource fixture, deliberately not executable code."""
    payload = xml.encode("utf-8")
    data = bytearray(0x300 + len(payload))
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", data, 0x84, 0x8664, 1)
    struct.pack_into("<H", data, 0x94, 240)
    struct.pack_into("<H", data, 0x98, 0x20B)
    struct.pack_into("<II", data, 0x98 + 128, 0x1000, 0x100 + len(payload))
    section = 0x98 + 240
    struct.pack_into("<IIII", data, section + 8, 0x100 + len(payload), 0x1000, 0x100 + len(payload), 0x200)
    # RT_MANIFEST / ID 1 / neutral language / data entry.
    for offset, key, target in ((0, 24, 0x80000020), (0x20, 1, 0x80000040), (0x40, 0, 0x60)):
        struct.pack_into("<H", data, 0x200 + offset + 14, 1)
        struct.pack_into("<II", data, 0x200 + offset + 16, key, target)
    struct.pack_into("<II", data, 0x260, 0x1100, len(payload))
    data[0x300:] = payload
    return bytes(data)


class StartupFixture:
    """Only miniature fixture files under the caller's temporary root."""
    def __init__(self, root, module=startup):
        self.root, self.module = root, module
        self.about = {"version": {"major": 3, "minor": 0, "patch": 3, "prerelease": "", "prereleaseNumber": 0}}
        self.baseline_base = root / "baselines/base303"
        self.baseline_gpu = root / "baselines/gpu303"
        self.old_plugin = self.baseline_gpu / module.PLUGIN_RELATIVE
        self.staging = root / "overlay"
        self.plugin = self.staging / module.PLUGIN_RELATIVE
        self.metadata = self.staging / "LICENSES/plugins" / module.gates.PLUGIN_ID
        self.audit = root / "build/audit"
        self.matrix_path = self.audit / "matrix.json"
        self.xml = '<assembly xmlns="urn:schemas-microsoft-com:asm.v1"><application><windowsSettings><activeCodePage xmlns="http://schemas.microsoft.com/SMI/2019/WindowsSettings">UTF-8</activeCodePage></windowsSettings></application></assembly>'
        write(self.baseline_base / "Umi-OCR.exe", b"SYNTHETIC HOST - NOT EXECUTABLE")
        write(self.baseline_base / "UmiOCR-data/about.json", self.about)
        write(self.baseline_base / "UmiOCR-data/runtime/python313.dll", b"SYNTHETIC DLL - NOT EXECUTABLE")
        write(self.baseline_base / "UmiOCR-data/main.py", "raise RuntimeError('never execute fixture host')\n")
        worker = "\n".join("def " + name + "(*args):\n    return 'unchanged OCR computation'\n" for name in module.WORKER_OCR_FUNCTIONS)
        api = "class Api:\n" + "\n".join("    def " + name + "(self, *args):\n        return 'unchanged OCR computation'\n" for name in module.API_OCR_METHODS)
        for name, text in (("worker.py", worker), ("api.py", api), ("__init__.py", ""), ("coordinates.py", "COORDS = 1\n"), ("config.py", "CONFIG = {}\n"), ("health.py", "HEALTH = 1\n")):
            write(self.old_plugin / name, text)
        for name in module.MODEL_NAMES:
            write(self.old_plugin / "models" / name / "inference.pdiparams", b"SYNTHETIC MODEL - NO INFERENCE")
        write(self.old_plugin / "vendor/paddle/base/paddle.pyd", b"SYNTHETIC VENDOR - NOT EXECUTABLE")
        write(self.old_plugin / "runtime.lock.json", {"files": []})
        self.manifest = {"id": module.gates.PLUGIN_ID, "version": "3.0.3", "runtime": {
            "vendor_dirs": [], "dll_dirs": [], "process_boundary": {"type": "separate-worker-stdio-ipc", "entry": "worker.py"}}}
        write(self.old_plugin / "umi-plugin.json", self.manifest)
        old_sources = {path.name: module.gates.digest(path) for path in self.old_plugin.glob("*.py")}
        history = {"test_type": "real_gpu_ocr_workflows_e2e", "status": "PASS", "device": "gpu:0",
                   "architecture": {"type": "separate-worker-stdio-ipc", "host_loaded_proprietary_modules": [], "ipc_payload": "JSON-lines path/base64 -> JSON OCR result"},
                   "plugin_source_sha256": old_sources, "plugin_runtime_lock_sha256": module.gates.digest(self.old_plugin / "runtime.lock.json"),
                   "model_initialization": module.MODEL_NAMES, "ffmpeg_backend_dll_count": 0, "cusolvermg_dll_count": 0,
                   "exercised_paths": ["batch OCR", "document PDF OCR", "CUDA-only failure paths"]}
        write(self.old_plugin / "gpu-e2e-evidence.json", history)
        # Fixed hashes are substituted ONLY for these explicitly synthetic tars.
        self.archive_hashes, archive_refs = {}, {}
        for name, baseline in (("base303", self.baseline_base), ("gpu303", self.baseline_gpu)):
            archive = root / "archives" / (name + ".tar.xz")
            archive.parent.mkdir(parents=True, exist_ok=True)
            with tarfile.open(archive, "w:xz") as bundle:
                for child in baseline.iterdir():
                    bundle.add(child, arcname=child.name)
            archive_refs[name] = self.ref(archive)
            self.archive_hashes[name] = module.gates.digest(archive)
        receipt = {"status": "THIS TOKEN IS NOT TRUSTED", "baselines": {
            name: {"path": str(path), "version": "3.0.3", "archive": {"sha256": self.archive_hashes[name]}}
            for name, path in (("base303", self.baseline_base), ("gpu303", self.baseline_gpu))}}
        baseline_receipt = self.audit / "baselines.json"
        write(baseline_receipt, receipt)
        shutil.copytree(self.old_plugin, self.plugin)
        self.manifest = copy.deepcopy(self.manifest)
        self.manifest["version"] = "3.0.4"
        self.manifest["runtime"]["process_boundary"]["entry"] = module.LAUNCHER
        write(self.plugin / "umi-plugin.json", self.manifest)
        write(self.plugin / module.LAUNCHER, pe_manifest(self.xml))
        write(self.plugin / "runtime.lock.json", {"files": [{"path": module.LAUNCHER, "sha256": module.gates.digest(self.plugin / module.LAUNCHER)}]})
        write(self.plugin / "worker.py", worker + "\ndef startup_info():\n    return 'only startup changed'\n")
        write(self.plugin / "api.py", api + "\ndef launch_native():\n    return 'only startup changed'\n")
        for path in self.plugin.glob("*.py"):
            write(self.metadata / "source" / module.PLUGIN_RELATIVE / path.name, path.read_bytes())
        write(self.metadata / "source" / module.PLUGIN_RELATIVE / "umi-plugin.json", (self.plugin / "umi-plugin.json").read_bytes())
        for name in (*module.NATIVE_SOURCES, "build/tools/record_gpu_startup.py"):
            text = self.xml if name.endswith("worker.manifest") else "SYNTHETIC TRUSTED SOURCE - NOT EXECUTED\n"
            write(root / name, text)
            write(self.metadata / "source" / name, text)
        _, self.binding, _ = module.gates.artifact_inputs(self.staging, "gpu")
        self.installs, self.raw_paths, self.logs = [], [], []
        cases = []
        for index, (acp, non_ascii) in enumerate(((936, False), (936, True), (65001, False), (65001, True))):
            installation = root / (f"程序 安装 {index}" if non_ascii else f"ascii-install-{index}")
            shutil.copytree(self.baseline_base, installation)
            shutil.copytree(self.plugin, installation / module.PLUGIN_RELATIVE)
            self.installs.append(installation)
            worker_info = {"pid": 10000 + index, "native_code_page": 65001, "python_utf8_mode": True,
                           "stdin_encoding": "utf-8", "stdout_encoding": "utf-8", "python_version": "3.13.9",
                           "python_dll": str(installation / "UmiOCR-data/runtime/python313.dll"),
                           "executable": str(installation / module.PLUGIN_RELATIVE / module.LAUNCHER),
                           "model_names": module.MODEL_NAMES, "device": "gpu:0"}
            log = self.audit / f"case-{index}.log"
            write(log, "\n".join(json.dumps(item) for item in ({"operation": "start", "result": ""}, {"startup": worker_info}, {"status": "PASS", "normal_exit": True, "ocr_operations": 0})) + "\n")
            raw = {"test_type": "real_gpu_worker_startup_only", "status": "PASS", "scope": module.RECORD_SCOPE,
                   "plugin_version": "3.0.4", "host_version": self.about["version"], "installation": str(installation),
                   "installation_contains_non_ascii": non_ascii, "parent_native_code_page": acp, "device": "gpu:0",
                   "plugin_source_sha256": {path.name: module.gates.digest(path) for path in self.plugin.glob("*.py")},
                   "plugin_runtime_lock_sha256": module.gates.digest(self.plugin / "runtime.lock.json"),
                   "launcher": {"file": module.LAUNCHER, "sha256": module.gates.digest(self.plugin / module.LAUNCHER)},
                   "models": module.gates.tree_binding({path.relative_to(self.plugin / "models").as_posix(): module.gates.digest(path) for path in (self.plugin / "models").rglob("*") if path.is_file()}),
                   "recording_tool_sha256": module.gates.digest(root / "build/tools/record_gpu_startup.py"),
                   "startup": worker_info, "worker_pid": 10000 + index, "normal_exit": True, "worker_exit_code": 0,
                   "host_loaded_proprietary_modules": [], "execution_inputs_unchanged": True,
                   "exception": None, "worker_diagnostics": [], "startup_log": self.ref(log),
                   "ocr_operations": 0, "ocr_workflows_status": "NOT_RUN", "public_release_allowed": False}
            raw_path = self.audit / f"case-{index}.json"
            write(raw_path, raw)
            self.logs.append(log)
            self.raw_paths.append(raw_path)
            cases.append(self.ref(raw_path))
        host_log = self.audit / "host.log"
        write(host_log, "SYNTHETIC host PID 123 ready then exited normally; no application was run.\n")
        self.host_path = self.audit / "host.json"
        write(self.host_path, {"schema_version": 1, "test_type": "real_host_startup_exit", "status": "PASS",
                              "host_version": self.about["version"], "installation": str(self.installs[0]), "binding": self.binding,
                              "host_pid": 123, "host_executable_sha256": module.gates.digest(self.baseline_base / "Umi-OCR.exe"),
                              "http_ready_before_quit": True, "normal_exit": True, "exit_code": 0,
                              "ocr_operations": 0, "ocr_workflows_status": "NOT_RUN", "public_release_allowed": False,
                              "startup_log": self.ref(host_log)})
        self.matrix = {"schema_version": 1, "test_type": "real_gpu_startup_matrix", "validation_scope": module.VALIDATION_SCOPE,
                       "plugin_version": "3.0.4", "binding": self.binding, "cases": cases,
                       "host_startup": self.ref(self.host_path), "baselines": self.ref(baseline_receipt), "official_archives": archive_refs}
        self.save()

    def ref(self, path):
        return {"path": str(path), "sha256": self.module.gates.digest(path)}

    def save(self):
        write(self.matrix_path, self.matrix)

    def raw(self, index=0):
        return json.loads(self.raw_paths[index].read_text("utf-8"))

    def update_raw(self, raw, index=0):
        write(self.raw_paths[index], raw)
        self.matrix["cases"][index] = self.ref(self.raw_paths[index])
        self.save()

    def patches(self):
        stack = ExitStack()
        stack.enter_context(patch.object(self.module, "REPOSITORY", self.root))
        stack.enter_context(patch.object(self.module, "OFFICIAL_ARCHIVE_SHA256", self.archive_hashes))
        return stack

    def verify(self):
        with self.patches():
            return self.module.verify_startup_matrix(self.matrix_path, self.staging, self.binding)


class StartupEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="umi-startup-evidence-")
        self.addCleanup(self.temporary.cleanup)
        self.fixture = StartupFixture(Path(self.temporary.name))

    def blocked(self):
        with self.assertRaises((ValueError, OSError, KeyError, TypeError)):
            self.fixture.verify()

    def test_complete_matrix_is_startup_pass_not_ocr_or_approval(self):
        result = self.fixture.verify()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["gpu_ocr_e2e"], "NOT_RUN")
        self.assertFalse(result["public_release_allowed"])
        self.assertTrue(result["baselines"]["unchanged_ocr"]["verified"])
        self.assertTrue(result["baselines"]["historical_functionality"]["verified"])
        self.assertNotIn(str(self.fixture.root), json.dumps(result))

    def test_missing_duplicate_or_wrong_acp_cell_blocks(self):
        original = copy.deepcopy(self.fixture.matrix)
        for cases in (original["cases"][:3], [original["cases"][0]] * 4):
            self.fixture.matrix["cases"] = cases
            self.fixture.save()
            self.blocked()
        self.fixture.matrix = original
        raw = self.fixture.raw()
        raw["parent_native_code_page"] = 1252
        self.fixture.update_raw(raw)
        self.blocked()

    def test_normal_exit_pid_dll_and_encodings_are_required(self):
        original = self.fixture.raw()
        for key, value in (("normal_exit", False), ("worker_exit_code", 1), ("worker_exit_code", False),
                           ("worker_pid", 999), ("execution_inputs_unchanged", False), ("host_loaded_proprietary_modules", ["paddle"])):
            raw = copy.deepcopy(original)
            raw[key] = value
            self.fixture.update_raw(raw)
            self.blocked()
        for key, value in (("native_code_page", 936), ("python_utf8_mode", False), ("stdin_encoding", "cp936"),
                           ("stdout_encoding", "gbk"), ("python_dll", str(self.fixture.root / "wrong.dll")),
                           ("executable", str(self.fixture.root / "python.exe")), ("model_names", [])):
            raw = copy.deepcopy(original)
            raw["startup"][key] = value
            self.fixture.update_raw(raw)
            self.blocked()

    def test_raw_cannot_claim_any_ocr_or_publication_pass(self):
        original = self.fixture.raw()
        for key, value in (("ocr_operations", 1), ("ocr_operations", False), ("ocr_workflows_status", "PASS"),
                           ("ocr_workflows_status", "BLOCK"), ("public_release_allowed", True), ("scope", "OCR")):
            raw = copy.deepcopy(original)
            raw[key] = value
            self.fixture.update_raw(raw)
            self.blocked()

    def test_record_log_source_exe_lock_and_model_hash_changes_block(self):
        candidates = (self.fixture.raw_paths[0], self.fixture.logs[0], self.fixture.plugin / "api.py",
                      self.fixture.plugin / startup.LAUNCHER, self.fixture.plugin / "runtime.lock.json",
                      self.fixture.plugin / "models/UVDoc/inference.pdiparams")
        for path in candidates:
            with self.subTest(path=path.name):
                original = path.read_bytes()
                write(path, original + b"\nchanged\n")
                self.blocked()
                write(path, original)

    def test_changed_vendor_models_and_ocr_cannot_be_hidden_by_fresh_artifact_binding(self):
        for name in ("vendor/paddle/base/paddle.pyd", "models/UVDoc/inference.pdiparams", "coordinates.py", "config.py", "worker.py", "api.py"):
            with self.subTest(name=name):
                target = self.fixture.plugin / name
                original = target.read_bytes()
                replacement = original.replace(b"unchanged OCR computation", b"changed OCR computation") if name in {"api.py", "worker.py"} else original + b"\nCHANGED\n"
                write(target, replacement)
                _, binding, _ = startup.gates.artifact_inputs(self.fixture.staging, "gpu")
                previous = self.fixture.binding
                self.fixture.binding = binding
                self.fixture.matrix["binding"] = binding
                self.fixture.save()
                self.blocked()
                write(target, original)
                self.fixture.binding = previous
                self.fixture.matrix["binding"] = previous
                self.fixture.save()

    def test_vendor_model_member_set_and_native_source_changes_are_not_waivable(self):
        for relative in ("vendor/extra.dll", "models/extra/inference.pdiparams"):
            target = self.fixture.plugin / relative
            write(target, b"unexpected closure member")
            _, binding, _ = startup.gates.artifact_inputs(self.fixture.staging, "gpu")
            previous = self.fixture.binding
            self.fixture.binding = binding
            self.fixture.matrix["binding"] = binding
            self.fixture.save()
            self.blocked()
            target.unlink()  # Only this test's tiny newly-created fixture file.
            self.fixture.binding = previous
            self.fixture.matrix["binding"] = previous
            self.fixture.save()
        target = self.fixture.metadata / "source/build/windows/CudaWorker/worker_main.cpp"
        write(target, b"different corresponding native source")
        _, self.fixture.binding, _ = startup.gates.artifact_inputs(self.fixture.staging, "gpu")
        self.fixture.matrix["binding"] = self.fixture.binding
        self.fixture.save()
        self.blocked()

    def test_baseline_pass_token_never_substitutes_official_archive_bytes(self):
        write(self.fixture.old_plugin / "vendor/paddle/base/paddle.pyd", b"CHANGED baseline bytes")
        self.blocked()

    def test_arbitrary_historical_pass_is_not_functionality_evidence(self):
        with self.fixture.patches():
            path = self.fixture.old_plugin / "gpu-e2e-evidence.json"
            write(path, {"status": "PASS"})
            records = startup.files(self.fixture.old_plugin)
            with self.assertRaisesRegex(ValueError, "historical functionality"):
                startup.historical_functionality(self.fixture.old_plugin, records)

    def test_manifest_is_read_as_resource_not_a_utf8_string_search(self):
        path = self.fixture.plugin / startup.LAUNCHER
        with self.fixture.patches():
            self.assertTrue(startup.embedded_manifest(path)["verified"])
            for payload in (b"MZ UTF-8 activeCodePage", pe_manifest(self.fixture.xml.replace("UTF-8", "936")), pe_manifest("<assembly/>")):
                write(path, payload)
                with self.assertRaises(ValueError):
                    startup.embedded_manifest(path)

    def test_installation_host_exe_dll_and_plugin_must_be_actual_current_bytes(self):
        for relative in ("Umi-OCR.exe", "UmiOCR-data/runtime/python313.dll", startup.PLUGIN_RELATIVE + "/worker.py"):
            path = self.fixture.installs[0] / relative
            original = path.read_bytes()
            write(path, original + b"CHANGED")
            self.blocked()
            write(path, original)

    def test_host_readiness_exit_and_current_binding_are_required(self):
        original = json.loads(self.fixture.host_path.read_text("utf-8"))
        for field, value in (("http_ready_before_quit", False), ("normal_exit", False), ("exit_code", 1),
                             ("binding", {}), ("ocr_workflows_status", "PASS"), ("public_release_allowed", True)):
            raw = copy.deepcopy(original)
            raw[field] = value
            write(self.fixture.host_path, raw)
            self.fixture.matrix["host_startup"] = self.fixture.ref(self.fixture.host_path)
            self.fixture.save()
            self.blocked()

    def test_no_cross_project_evidence_paths_or_junctions(self):
        with self.fixture.patches():
            with self.assertRaises(ValueError):
                startup.local_path(self.fixture.root.parent / "sibling" / "evidence.json")
            with patch.object(Path, "is_junction", lambda path: path == self.fixture.plugin):
                with self.assertRaises(ValueError):
                    startup.files(self.fixture.plugin)


if __name__ == "__main__":
    unittest.main(verbosity=2)
