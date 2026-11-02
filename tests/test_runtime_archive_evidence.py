"""Fixture-only integration of native locks and Python runtime archive evidence."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "build/tools"


def trusted_tool(name):
    spec = importlib.util.spec_from_file_location("archive_evidence_fixture_" + name, TOOLS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verifier = trusted_tool("verify_release_evidence")
merge = trusted_tool("merge_runtime")
layout = merge.layout
WORK = ROOT / "build/tmp/startup-small-files-20261028-r1/formal-container-integration-r1/archive-evidence-tests"


class RuntimeArchiveEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        layout.plain_path(WORK)
        WORK.mkdir(parents=True, exist_ok=True)
        cls.scratch = Path(tempfile.mkdtemp(prefix="evidence-", dir=WORK))
        cls.counter = 0

    @classmethod
    def tearDownClass(cls):
        layout.tree_files(cls.scratch)
        if merge.running_processes(cls.scratch):
            raise RuntimeError("Fixture tree became occupied; preserving it for review")
        shutil.rmtree(cls.scratch)

    def setUp(self):
        type(self).counter += 1
        self.project = self.scratch / str(self.counter)
        self.stage = self.project / "build/staging/candidate"
        self.data = self.stage / "UmiOCR-data"
        self.package = self.data / "plugins/win32_PaddleOCRv6_CUDA"
        self.vendor = self.package / "vendor"
        self.vendor.mkdir(parents=True)
        self.prefix = "vendor"
        self.make_native()

    @staticmethod
    def write(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        return path

    @staticmethod
    def checksum(content):
        return hashlib.sha256(content).hexdigest()

    def make_native(self):
        self.native = self.write(self.vendor / "native_fixture.pyd", b"SYNTHETIC NONEXECUTABLE NATIVE FIXTURE\n")
        info = self.vendor / "fixture_native-1.0.dist-info"
        self.write(info / "METADATA", "Name: fixture-native\nVersion: 1.0\nLicense: MIT\n")
        self.write(info / "RECORD", "native_fixture.pyd,,\n")
        self.write(info / "LICENSE", "Synthetic retained notice; not a real component license.\n")
        self.lock = self.package / ("runtime.lock.json" if self.prefix == "vendor" else "native-dlls.lock.json")
        entry_path = self.native.relative_to(self.package if self.prefix == "vendor" else self.stage).as_posix()
        entries = [{"path": entry_path, "sha256": verifier.sha256(self.native)}]
        self.write(self.lock, json.dumps({"files": entries} if self.prefix == "vendor" else entries))

    def aggregate(self, kind):
        return merge.aggregate_runtime(self.package, kind=kind, project_root=self.project, occupancy_check=lambda _root: [])

    def plugin(self, *, record=True):
        source = b"raise RuntimeError('archive evidence must never execute third-party fixture code')\n"
        self.write(self.vendor / "six.py", source)
        if record:
            info = self.vendor / "six-1.0.dist-info"
            digest = base64.urlsafe_b64encode(hashlib.sha256(source).digest()).rstrip(b"=").decode()
            self.write(info / "RECORD", f"six.py,sha256={digest},{len(source)}\n")
            self.write(info / "METADATA", "Name: six\nVersion: 1.0\nLicense: MIT\n")
        self.aggregate("plugin")
        return source

    def host(self):
        self.package = self.data
        self.vendor = self.data / "site-packages"
        self.vendor.mkdir(parents=True)
        self.prefix = "site-packages"
        self.make_native()
        source = b"raise RuntimeError('archive evidence must never execute host fixture code')\n"
        self.write(self.data / "py_src/run.py", source)
        self.snapshot = self.write(self.stage / "source-snapshot.json", json.dumps({"host/UmiOCR-data/py_src/run.py": self.checksum(source)}))
        self.aggregate("host")
        return source

    def verify(self, errors=None):
        errors = [] if errors is None else errors
        return verifier.verify_runtime_vendor(self.stage, self.package, self.vendor, errors), errors

    def assert_archive_block(self, result, errors):
        self.assertEqual(result["status"], "BLOCK", result)
        self.assertEqual(result["runtime_archives"]["status"], "BLOCK")
        self.assertTrue(result["runtime_lock_valid"], "Native lock success must not stand in for Python provenance")
        self.assertTrue(any("Runtime Python archive/source evidence failed" in error for error in errors), errors)
        self.assertTrue(result["blockers"])

    def test_native_only_layout_preserves_original_result_and_does_not_load_auditor(self):
        # A nested embedded-stdlib ZIP is not a runtime archive layout indicator.
        self.write(self.package / "runtime/python313.zip", b"untouched standard-library fixture")
        with patch.object(verifier.importlib.util, "spec_from_file_location", side_effect=AssertionError("Archive auditor must not run")):
            result, errors = self.verify()
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["runtime_lock_valid"])
        self.assertEqual(result["blockers"], [])
        self.assertEqual(errors, [])
        self.assertNotIn("runtime_archives", result)
        self.assertEqual(len(result["binaries"]), 1)

    def test_original_native_only_failure_semantics_are_not_relaxed(self):
        self.native.write_bytes(b"changed native fixture")
        result, errors = self.verify()
        self.assertEqual(result["status"], "BLOCK")
        self.assertFalse(result["runtime_lock_valid"])
        self.assertEqual(result["runtime_lock_failures"], ["vendor/native_fixture.pyd"])
        self.assertEqual(errors, [])  # Existing native diagnostics remain in blockers.
        self.assertNotIn("runtime_archives", result)

    def test_valid_third_party_archive_and_native_lock_are_both_reported(self):
        source = self.plugin()
        result, errors = self.verify()
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(errors, [])
        archives = result["runtime_archives"]
        self.assertEqual(archives["status"], "PASS")
        self.assertEqual(archives["archived_paths"], ["vendor/six.py"])
        self.assertEqual(archives["members"][0]["sha256"], self.checksum(source))
        self.assertEqual(archives["members"][0]["binding"], "retained-wheel-RECORD")
        self.assertEqual(len(result["binaries"]), 1)
        self.assertTrue(result["runtime_lock_valid"])

    def test_valid_archive_does_not_replace_a_failing_native_lock(self):
        self.plugin()
        self.native.write_bytes(b"different native fixture")
        result, _errors = self.verify()
        self.assertEqual(result["runtime_archives"]["status"], "PASS")
        self.assertEqual(result["status"], "BLOCK")
        self.assertFalse(result["runtime_lock_valid"])
        self.assertIn("vendor/native_fixture.pyd", result["runtime_lock_failures"])

    def test_valid_archive_does_not_replace_a_missing_native_lock(self):
        self.plugin()
        self.lock.unlink()
        result, errors = self.verify()
        self.assertEqual(result["runtime_archives"]["status"], "PASS")
        self.assertEqual(result["status"], "BLOCK")
        self.assertFalse(result["runtime_lock_valid"])
        self.assertTrue(any("Missing runtime lock" in item for item in errors))
        self.assertTrue(any("Missing runtime lock" in item for item in result["blockers"]))

    def test_valid_host_archive_does_not_replace_a_missing_native_dll_lock(self):
        self.host()
        self.lock.unlink()
        result, errors = self.verify()
        self.assertEqual(result["runtime_archives"]["status"], "PASS")
        self.assertEqual(result["status"], "BLOCK")
        self.assertFalse(result["runtime_lock_valid"])
        self.assertTrue(any("Missing runtime lock" in item for item in errors))
        self.assertTrue(any("Missing runtime lock" in item for item in result["blockers"]))

    def test_valid_archive_does_not_replace_a_malformed_native_lock(self):
        self.plugin()
        for document in ('{', '{}', 'null', '{"files":null}', '{"files":[null]}',
                         '{"files":[{"path":"vendor/native_fixture.pyd","sha256":false}]}',
                         '{"files":[],"files":[]}'):
            with self.subTest(document=document):
                self.lock.write_text(document, encoding="utf-8")
                result, errors = self.verify()
                self.assertEqual(result["runtime_archives"]["status"], "PASS")
                self.assertEqual(result["status"], "BLOCK")
                self.assertFalse(result["runtime_lock_valid"])
                self.assertTrue(any("Invalid runtime lock" in item for item in errors), errors)
                self.assertTrue(any("Invalid runtime lock" in item for item in result["blockers"]))

    def test_unreadable_native_lock_still_blocks_valid_archives(self):
        self.plugin()
        with patch.object(verifier.release_gate_inputs, "read_json", side_effect=PermissionError("synthetic native lock read denial")):
            result, errors = self.verify()
        self.assertEqual(result["runtime_archives"]["status"], "PASS")
        self.assertEqual(result["status"], "BLOCK")
        self.assertFalse(result["runtime_lock_valid"])
        self.assertTrue(any("PermissionError" in item for item in errors), errors)

    def test_native_lock_outside_path_is_not_replaced_by_valid_archive_evidence(self):
        self.plugin()
        outside = self.write(self.project / "outside.pyd", b"must never be accepted as package input")
        self.write(self.lock, json.dumps({"files": [{"path": "../../../../outside.pyd", "sha256": verifier.sha256(outside)}]}))
        result, _errors = self.verify()
        self.assertEqual(result["runtime_archives"]["status"], "PASS")
        self.assertEqual(result["status"], "BLOCK")
        self.assertFalse(result["runtime_lock_valid"])
        self.assertEqual(result["runtime_lock_failures"], ["../../../../outside.pyd"])

    def test_valid_archive_does_not_replace_native_binary_ownership(self):
        self.plugin()
        (self.vendor / "fixture_native-1.0.dist-info/RECORD").unlink()
        result, _errors = self.verify()
        self.assertEqual(result["runtime_archives"]["status"], "PASS")
        self.assertEqual(result["status"], "BLOCK")
        self.assertTrue(any("Unowned runtime binaries" in item for item in result["blockers"]))

    def test_missing_generated_archive_is_blocked_and_added_to_errors(self):
        self.plugin()
        (self.package / "vendor.zip").unlink()
        self.assert_archive_block(*self.verify())

    def test_corrupt_generated_archive_is_blocked_and_added_to_errors(self):
        self.plugin()
        (self.package / "vendor.zip").write_bytes(b"corrupt runtime container")
        self.assert_archive_block(*self.verify())

    def test_undeclared_root_container_is_not_native_only_acceptance(self):
        self.write(self.package / "unlisted.zip", b"undeclared")
        self.assert_archive_block(*self.verify())

    def test_generated_archive_without_layout_manifest_is_blocked(self):
        self.plugin()
        (self.package / layout.MANIFEST_NAME).unlink()
        self.assert_archive_block(*self.verify())

    def test_partial_marker_and_legacy_declaration_trigger_fail_closed_audit(self):
        for name in (layout.MARKER_NAME, "archive-layout.json"):
            with self.subTest(indicator=name):
                marker = self.write(self.package / name, '{"state":"assembling"}')
                self.assert_archive_block(*self.verify())
                marker.unlink()

    def test_legacy_declaration_cannot_hide_beside_valid_current_archive(self):
        self.plugin()
        self.write(self.package / "archive-layout.json", '{"legacy":true}')
        self.assert_archive_block(*self.verify())

    def test_changed_missing_or_incomplete_assembly_records_block_native_pass(self):
        self.plugin()
        for name, replacement in ((layout.INPUTS_NAME, None), (layout.INPUTS_NAME, b'{"files":{}}'),
                                  (layout.MANIFEST_NAME, b'{'),
                                  (layout.MARKER_NAME, b'{"purpose":"fresh-runtime-archive-assembly","state":"assembling"}')):
            with self.subTest(name=name, replacement=replacement):
                path = self.package / name
                original = path.read_bytes()
                if replacement is None:
                    path.unlink()
                else:
                    path.write_bytes(replacement)
                self.assert_archive_block(*self.verify())
                path.write_bytes(original)

    def test_loose_source_or_bytecode_shadow_cannot_use_native_only_pass(self):
        self.plugin()
        for name in ("vendor/six.py", "vendor/six.pyc", "six.py", "site-packages/six.py"):
            with self.subTest(name=name):
                path = self.write(self.package / name, b"synthetic shadow must never execute\n")
                self.assert_archive_block(*self.verify())
                path.unlink()

    def test_reserved_case_variant_is_detected_and_blocked(self):
        self.write(self.package / "Runtime-Archive-Inputs.json", '{"schema_version":1,"files":{}}')
        self.assert_archive_block(*self.verify())

    def test_self_recorded_archive_without_original_record_source_is_blocked(self):
        self.plugin(record=False)
        result, errors = self.verify()
        self.assert_archive_block(result, errors)
        self.assertTrue(any("RECORD" in item for item in errors))

    def test_missing_or_changed_original_record_source_is_blocked(self):
        self.plugin()
        record = self.vendor / "six-1.0.dist-info/RECORD"
        original = record.read_bytes()
        record.unlink()
        self.assert_archive_block(*self.verify())
        record.write_bytes(original + b"changed,,\n")
        self.assert_archive_block(*self.verify())

    def test_valid_host_archive_is_bound_to_same_candidate_source_snapshot(self):
        source = self.host()
        result, errors = self.verify()
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(errors, [])
        self.assertEqual(result["runtime_archives"]["members"][0]["binding"], "canonical-host-source")
        self.assertEqual(result["runtime_archives"]["members"][0]["sha256"], self.checksum(source))
        self.assertTrue(result["runtime_lock"].endswith("UmiOCR-data/native-dlls.lock.json"))

    def test_host_missing_source_snapshot_has_no_source_free_fallback(self):
        self.host()
        self.snapshot.unlink()
        self.assert_archive_block(*self.verify())

    def test_host_different_source_snapshot_is_blocked(self):
        self.host()
        self.snapshot.write_text(json.dumps({"host/UmiOCR-data/py_src/run.py": "0" * 64}), encoding="utf-8")
        self.assert_archive_block(*self.verify())

    def test_existing_license_or_source_errors_are_never_erased(self):
        self.plugin()
        previous = ["Existing license gate BLOCK", "Existing model/source gate BLOCK"]
        result, errors = self.verify(previous.copy())
        self.assertEqual(result["runtime_archives"]["status"], "PASS")
        self.assertEqual(errors, previous)
        self.assertFalse(verifier.public_release_allowed({"runtime_vendor": result, "source_delivery": {"status": "BLOCK"}}))

    def test_only_trusted_adjacent_auditor_is_loaded_not_candidate_code(self):
        self.plugin()
        sentinel = self.package / "untrusted-code-executed"
        planted = f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('executed')\nraise RuntimeError('must not execute candidate audit helper')\n"
        self.write(self.package / "audit_runtime_archives.py", planted)
        self.write(self.package / "runtime_archive_layout.py", planted)
        sys.path.insert(0, str(self.package))
        try:
            result, errors = self.verify()
        finally:
            sys.path.remove(str(self.package))
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(errors, [])
        self.assertFalse(sentinel.exists())

    def test_trusted_auditor_load_failure_is_blocked_not_native_only_pass(self):
        self.plugin()
        with patch.object(verifier.importlib.util, "spec_from_file_location", side_effect=ImportError("fixture auditor unavailable")):
            self.assert_archive_block(*self.verify())
        for spec in (None, SimpleNamespace(loader=None)):
            with self.subTest(spec=spec), patch.object(verifier.importlib.util, "spec_from_file_location", return_value=spec):
                self.assert_archive_block(*self.verify())

    def test_incomplete_or_nonpass_trusted_auditor_result_is_not_acceptance(self):
        self.plugin()
        spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda _module: None))
        for report in (None, {"status": "NOT_INCLUDED"}, {"status": "PASS"},
                       {"status": "PASS", "archives": [], "members": None, "archived_paths": []}):
            with self.subTest(report=report):
                auditor = SimpleNamespace(audit=lambda _root: report)
                with patch.object(verifier.importlib.util, "spec_from_file_location", return_value=spec), \
                        patch.object(verifier.importlib.util, "module_from_spec", return_value=auditor):
                    self.assert_archive_block(*self.verify())


if __name__ == "__main__":
    unittest.main(verbosity=2)
