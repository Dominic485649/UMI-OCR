"""Stdlib-only driver fixtures: never launch product/worker/model/GPU code."""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build/tmp/startup-small-files-20261028-r1/stored-component-acceptance-driver-r1/fixtures"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


TOOL = load("stored_acceptance_driver_fixture", ROOT / "build/tools/run_stored_component_acceptance.py")
LAYOUT = load("stored_acceptance_layout_fixture", ROOT / "build/tools/runtime_archive_layout.py")


class StoredAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        LAYOUT.plain_path(WORK)
        WORK.mkdir(parents=True, exist_ok=True)
        cls.scratch = Path(tempfile.mkdtemp(prefix="stdlib-", dir=WORK))
        cls.counter = 0

    @classmethod
    def tearDownClass(cls):
        merge = load("stored_fixture_occupancy", ROOT / "build/tools/merge_runtime.py")
        LAYOUT.tree_files(cls.scratch)
        if merge.running_processes(cls.scratch):
            raise RuntimeError("Fixture became occupied; retaining the small workspace")
        shutil.rmtree(cls.scratch)

    def setUp(self):
        type(self).counter += 1
        self.root = self.scratch / str(self.counter)
        self.root.mkdir()

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else value.encode("utf-8"))
        return path

    def document(self, relative, value):
        path = self.write(relative, json.dumps(value))
        return path, TOOL.sha256(path)

    def test_default_plan_neither_touches_inputs_nor_imports_product(self):
        before = {name for name in sys.modules if name.startswith(("py_src", "PySide6", "win32_Paddle"))}
        for component in ("cuda", "vl"):
            output = io.StringIO()
            with redirect_stdout(output), patch.object(TOOL, "plain", side_effect=AssertionError("touched input")), \
                    patch.object(TOOL, "trusted_tool", side_effect=AssertionError("imported helper/product")), \
                    patch.object(TOOL.subprocess, "Popen", side_effect=AssertionError("launched process")):
                status = TOOL.main(["--component", component, "--host-root", "missing-host", "--plugin-root", "missing-plugin", "--work", "missing-work", "--audit", "missing-audit"])
            result = json.loads(output.getvalue())
            self.assertEqual(status, 0)
            self.assertTrue(result["planOnly"])
            self.assertFalse(result["gpuExecuted"])
            self.assertFalse(result["productImported"])
            self.assertEqual(result["cases"], ["ordinary"] if component == "cuda" else ["ordinary", "selected-document"])
        self.assertEqual(before, {name for name in sys.modules if name.startswith(("py_src", "PySide6", "win32_Paddle"))})

    def test_runtime_mirror_requires_exact_original_member_set_and_bytes(self):
        for parent in ("host/runtime", "plugin-data/runtime"):
            for name in ("python.exe", "python3.dll", "python313.dll", "python313._pth"):
                self.write(parent + "/" + name, b"synthetic non-executable runtime fixture")
        result = TOOL.runtime_mirror_binding(self.root / "host", self.root / "plugin-data", LAYOUT)
        self.assertTrue(result["same_bytes"])
        self.write("plugin-data/runtime/python3.dll", b"changed fixture")
        with self.assertRaises(TOOL.AcceptanceError):
            TOOL.runtime_mirror_binding(self.root / "host", self.root / "plugin-data", LAYOUT)
        self.write("plugin-data/runtime/extra.dll", b"extra fixture")
        with self.assertRaises(TOOL.AcceptanceError):
            TOOL.runtime_mirror_binding(self.root / "host", self.root / "plugin-data", LAYOUT)

    def test_cuda_native_only_lock_is_not_confused_with_vl_full_lock(self):
        plugin = self.root / "plugin"
        native = self.write("plugin/vendor/native.pyd", b"non-executable native fixture")
        self.write("plugin/api.py", b"raise RuntimeError('never execute fixture')\n")
        rows = [{"path": "vendor/native.pyd", "sha256": TOOL.sha256(native)}]
        self.document("plugin/runtime.lock.json", {"pluginId": TOOL.IDS["cuda"], "files": rows})
        self.assertEqual(TOOL.lock_binding(plugin, "cuda", LAYOUT)["scope"], "CUDA-native-only")
        self.document("plugin/runtime.lock.json", {"pluginId": TOOL.IDS["vl"], "files": rows})
        with self.assertRaisesRegex(TOOL.AcceptanceError, "coverage"):
            TOOL.lock_binding(plugin, "vl", LAYOUT)
        rows.append({"path": "api.py", "sha256": TOOL.sha256(plugin / "api.py")})
        self.document("plugin/runtime.lock.json", {"pluginId": TOOL.IDS["vl"], "files": rows})
        self.assertEqual(TOOL.lock_binding(plugin, "vl", LAYOUT)["scope"], "all-physical-files-after-assembly")

    def test_bad_lock_or_duplicate_lock_entry_never_passes(self):
        plugin = self.root / "plugin"
        native = self.write("plugin/a.pyd", b"synthetic fixture")
        row = {"path": "a.pyd", "sha256": TOOL.sha256(native)}
        for rows in ([row, row], [{**row, "sha256": "0" * 64}], [{**row, "path": "../escape.pyd"}]):
            self.document("plugin/runtime.lock.json", {"pluginId": TOOL.IDS["cuda"], "files": rows})
            with self.assertRaises((TOOL.AcceptanceError, LAYOUT.LayoutError)):
                TOOL.lock_binding(plugin, "cuda", LAYOUT)

    def test_corresponding_source_is_exact_not_just_an_independent_digest(self):
        for parent in ("plugin", "retained-source"):
            self.write(parent + "/worker.py", b"raise RuntimeError('never execute fixture')\n")
            self.write(parent + "/umi-plugin.json", b'{"id":"fixture"}')
            self.write(parent + "/i18n.csv", b"original fixture translation\n")
        TOOL.source_binding(self.root / "plugin", self.root / "retained-source", LAYOUT)
        self.write("plugin/worker.py", b"different fixture source\n")
        with self.assertRaises(TOOL.AcceptanceError):
            TOOL.source_binding(self.root / "plugin", self.root / "retained-source", LAYOUT)

    def origins(self):
        plugin = self.root / "plugin"
        entries = [{"member": "idna/__init__.py", "archive": "vendor.zip"}, {"member": "packaging/version.py", "archive": "vendor.zip"}]
        response = {"runtime_archives": [str(plugin / "vendor.zip")], "archive_modules": {"idna": str(plugin / "vendor.zip/idna/__init__.py")}}
        return plugin, entries, response

    def test_actual_archive_module_is_bound_to_member_without_hardcoding_baidubce(self):
        plugin, entries, response = self.origins()
        self.assertEqual(TOOL.archive_module_origins(response, plugin, ["vendor.zip"], entries)["verified_members"], 1)

    def test_legitimate_sys_modules_alias_keeps_exact_audited_source_binding(self):
        plugin, entries, response = self.origins()
        response["archive_modules"]["requests.packages.idna"] = response["archive_modules"]["idna"]
        verified = TOOL.archive_module_origins(response, plugin, ["vendor.zip"], entries)
        self.assertEqual(verified["verified_modules"], 2)
        self.assertEqual(verified["verified_members"], 1)
        self.assertEqual(verified["verified_bindings"]["requests.packages.idna"]["physical_module"], "idna")

    def test_empty_unknown_or_wrong_candidate_archive_origins_fail(self):
        plugin, entries, response = self.origins()
        mutations = [
            {**response, "archive_modules": {}},
            {**response, "runtime_archives": [str(self.root / "different/vendor.zip")]},
            {**response, "archive_modules": {"evil": str(plugin / "vendor.zip/unlisted.py")}},
            {**response, "archive_modules": {"idna": str(plugin / "vendor.zip/../idna/__init__.py")}},
            {**response, "runtime_archives": response["runtime_archives"] * 2},
        ]
        for value in mutations:
            with self.subTest(value=value), self.assertRaises(TOOL.AcceptanceError):
                TOOL.archive_module_origins(value, plugin, ["vendor.zip"], entries)

    def test_historical_dense_fail_cannot_be_waived_or_relabelled(self):
        record = {"contexts": [{"cases": [{"id": "dense", "metrics": {"passed": False, "missingEdgeIdentifiers": ["DENSEEDGETOP"]}}]}]}
        path, checksum = self.document("historical.json", record)
        result = TOOL.dense_failure(path, checksum)
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["rerun"])
        self.assertEqual(result["original_cases"][0], record["contexts"][0]["cases"][0])
        record["contexts"][0]["cases"][0]["metrics"]["passed"] = True
        path, checksum = self.document("historical.json", record)
        with self.assertRaises(TOOL.AcceptanceError):
            TOOL.dense_failure(path, checksum)

    def test_pinned_json_detects_changed_and_duplicate_inputs(self):
        path, checksum = self.document("inputs.json", {"first": True})
        self.assertTrue(TOOL.pinned_json(path, checksum)["first"])
        path.write_text('{"first":true,"first":false}', encoding="utf-8")
        with self.assertRaises(TOOL.AcceptanceError):
            TOOL.pinned_json(path, checksum)
        with self.assertRaises(TOOL.AcceptanceError):
            TOOL.read_json(path)

    def test_fixture_expectations_and_thresholds_remain_original(self):
        image = self.write("ordinary.png", b"non-image bytes for input-validator fixture only")
        criteria = {"identifierHitRatio": .95, "completeLineHitRatio": .90, "allEdgeIdentifiers": True, "coordinatesBounded": True, "partial": False}
        ordinary = {"id": "ordinary", "path": str(image), "sha256": TOOL.sha256(image), "size": [1000, 700],
                    "truth": [{"token": "NORMAL%04d" % index} for index in range(14)], "criteria": criteria}
        record = {"scope": "deterministic nonsensitive synthetic input; validator fixture only", "cases": [ordinary]}
        path, checksum = self.document("fixtures.json", record)
        self.assertEqual(TOOL.fixture_inputs(self.root, checksum, "cuda")["cases"][0], ordinary)
        ordinary["criteria"]["identifierHitRatio"] = .1
        path, checksum = self.document("fixtures.json", record)
        with self.assertRaises(TOOL.AcceptanceError):
            TOOL.fixture_inputs(self.root, checksum, "cuda")

    def fake_observer(self, *, server=False):
        executable = self.write("llama-server.exe" if server else "UmiOCR-CudaWorker.exe", b"NONEXECUTABLE fixture")
        fake = SimpleNamespace(pid=4711, returncode=None, terminate_calls=0, kill_calls=0)
        fake.poll = lambda: fake.returncode
        def terminate():
            fake.terminate_calls += 1
            fake.returncode = 1
        def kill():
            fake.kill_calls += 1
        fake.terminate, fake.kill = terminate, kill
        observer = TOOL.ProcessObservations({str(executable): TOOL.sha256(executable)}, self.root, time.monotonic() + 60, 19991)
        observer.original_popen = lambda *args, **kwargs: fake
        return observer, executable, fake

    def test_product_owned_service_terminate_is_recorded_not_replaced(self):
        observer, executable, fake = self.fake_observer(server=True)
        process = observer.spawn([str(executable), "--port", "19991"])
        process.terminate()
        self.assertEqual(fake.terminate_calls, 1)
        self.assertTrue(observer.snapshot()[0]["terminate_called"])
        self.assertEqual(observer.snapshot()[0]["exit_code"], 1)

    def test_internal_kill_fallback_is_fail_and_never_uses_an_extra_kill(self):
        observer, executable, fake = self.fake_observer()
        process = observer.spawn([str(executable)])
        with self.assertRaises(TOOL.KillFallbackBlocked):
            process.kill()
        self.assertEqual(fake.kill_calls, 0)
        self.assertTrue(observer.snapshot()[0]["kill_fallback"])
        self.assertTrue(observer.snapshot()[0]["still_running"])
        with self.assertRaises(TOOL.AcceptanceError):
            process.terminate()
        self.assertEqual(fake.terminate_calls, 0)

    def test_unbound_executable_or_server_port_never_starts(self):
        observer, executable, _fake = self.fake_observer(server=True)
        with patch.object(observer, "original_popen", side_effect=AssertionError("must not start")):
            with self.assertRaises(TOOL.AcceptanceError):
                observer.spawn([str(executable), "--port", "29992"])
            with self.assertRaises(TOOL.AcceptanceError):
                observer.spawn([str(self.root / "unknown.exe")])

    def test_timeout_does_not_cancel_or_forge_normal_release(self):
        observer, _exe, _fake = self.fake_observer()
        done = threading.Event()
        observer.deadline = time.monotonic() + .02
        try:
            with self.assertRaises(TOOL.AcceptanceTimeout):
                observer.call("synthetic-active-call", lambda: done.wait(2))
            self.assertTrue(observer.pending)
            self.assertTrue(observer.abort)
            self.assertEqual(observer.events, [])
        finally:
            done.set()

    def test_original_shutdown_can_run_after_request_deadline(self):
        observer, _exe, _fake = self.fake_observer()
        observer.deadline = time.monotonic() - 1
        self.assertEqual(observer.call("release", lambda: "original release result", seconds=1, shutdown=True), "original release result")

    def test_start_observation_preserves_original_return_and_wire(self):
        observer, _exe, fake = self.fake_observer()
        original_response = {"ok": True, "runtime_archives": ["fixture.zip"], "archive_modules": {"fixture": "fixture.zip/fixture.py"}}
        seen = []
        client = SimpleNamespace(process=fake)
        client._read = lambda stream, responses: seen.extend(list(stream))
        client.start = lambda: original_response
        observer.observe_client(client, "fixture-client")
        self.assertIs(client.start(), original_response)
        raw = '{"ok":true,"status":"stopped"}\n'
        client._read(io.StringIO(raw), None)
        self.assertEqual(seen, [raw])
        self.assertEqual(observer.wire, [{"client": "fixture-client", "raw": raw}])
        self.assertEqual(observer.starts[0]["pid"], fake.pid)

    def test_only_actual_stop_ack_not_ocr_text_counts_as_normal_worker_stop(self):
        wire = [{"client": "not-stop", "raw": '{"ok":true,"result":{"text":"stopped"}}'},
                {"client": "failed-stop", "raw": '{"ok":false,"status":"stopped"}'},
                {"client": "real-stop", "raw": '{"ok":true,"status":"stopped"}'},
                {"client": "bad-json", "raw": "stopped"}]
        self.assertEqual(TOOL.json_stopped_clients(wire), {"real-stop"})

    def test_cuda_minimum_contract_does_not_accept_empty_or_invalid_success(self):
        value = {"code": 100, "data": [{"text": "fixture", "score": .9, "box": [[0, 0], [1, 0], [1, 1], [0, 1]]}]}
        self.assertTrue(TOOL.cuda_contract(value)["passed"])
        for result in ({"code": 101, "data": []}, {"code": 100, "data": []}, {"code": 100, "data": [None]}):
            with self.assertRaises(TOOL.AcceptanceError):
                TOOL.cuda_contract(result)

    def test_evidence_write_is_no_clobber(self):
        path = self.root / "result.json"
        TOOL.write_new(path, {"first": True})
        with self.assertRaises(FileExistsError):
            TOOL.write_new(path, {"second": True})
        self.assertEqual(TOOL.read_json(path), {"first": True})


def main():
    global WORK
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=WORK)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    WORK = TOOL.plain(args.work)
    audit = TOOL.plain(args.audit)
    TOOL.require(audit.is_relative_to(ROOT / "build/audit") and not audit.exists(), "Use a new project audit subdirectory")
    TOOL.require(WORK.is_relative_to(ROOT / "build/tmp"), "Fixture work must stay under project build/tmp")
    audit.mkdir(parents=True)
    paths = [Path(__file__).resolve(), ROOT / "build/tools/run_stored_component_acceptance.py", ROOT / "build/tools/runtime_archive_layout.py", ROOT / "build/tools/merge_runtime.py"]
    before = {str(path): TOOL.sha256(path) for path in paths}
    started = datetime.now(timezone.utc).isoformat()
    with (audit / "raw.log").open("x", encoding="utf-8") as log, redirect_stdout(log), redirect_stderr(log):
        print("ACTUAL ARGV " + json.dumps(sys.orig_argv))
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(unittest.TestLoader().loadTestsFromTestCase(StoredAcceptanceTests))
    after = {str(path): TOOL.sha256(path) for path in paths}
    report = {"purpose": "stdlib-only Stored acceptance driver fixtures, not actual model acceptance", "started_utc": started,
              "finished_utc": datetime.now(timezone.utc).isoformat(), "command_argv": sys.orig_argv, "interpreter": sys.version,
              "source_before": before, "source_after": after, "source_drift": before != after,
              "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "skipped": result.skipped,
              "gpu_execution_started": False, "product_imported": False, "status": "PASS" if result.wasSuccessful() and before == after else "FAIL"}
    TOOL.write_new(audit / "result.json", report)
    print(json.dumps({key: report[key] for key in ("status", "tests_run", "failures", "errors", "source_drift")}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
