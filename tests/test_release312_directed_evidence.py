"""本次有限验收门禁的合成证据正反回归，不运行程序、模型或截图。"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "build/tools" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gates = load("directed_test_gates", "release_gate_inputs.py")
verifier = load("directed_test_verifier", "verify_release_evidence.py")
finalizer = load("directed_test_finalizer", "finalize_release.py")


class DirectedEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="release312-scope-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.stage, self.raw = self.root / "product", self.root / "raw"
        self.raw.mkdir()
        self.write(self.stage / "UmiOCR-data/about.json", {"version": {"major": 3, "minor": 1, "patch": 2}})
        self.write(self.stage / "UmiOCR-data/main.py", "# 合成程序，不执行\n")
        self.write(self.stage / "Umi-OCR.exe", "synthetic executable, never executed")
        self.write(self.stage / "VERSION", "3.1.2")
        self.write(self.stage / "source/UmiOCR-data/main.py", "# 合成源码，不执行\n")
        for name in gates.directed.REGRESSIONS | {"tests/test_release312_native.py", "tests/test_windows_tray.py"}:
            self.write(self.stage / "source" / name, "# 合成测试字节，不执行\n")
        self.notes = self.raw / "notes.md"
        self.write(self.notes, "# 主程序3.1.2／VL3.1.2／CUDA3.0.5\n截图、HDR、混屏NOT_RUN。\n")
        self.auth = self.raw / "authorization.json"
        self.write(self.auth, {"confirmationQuestion": gates.directed.APPROVAL_QUESTION,
            "selectedAnswer": gates.directed.APPROVAL_ANSWER, "approvedComponents": gates.directed.APPROVED_COMPONENTS,
            "mandatoryFormalGatesMayBeSkipped": False, "furtherDesktopCaptureTestsAllowed": False})
        runtime = gates.tree_binding(gates.directed.runtime_records(self.stage, "base", gates.__dict__))
        for module in (gates.directed, verifier.release_gate_inputs.directed, finalizer.gates.directed):
            for name, value in (("RUNTIME_BINDINGS", {"base": runtime, "gpu": {"files": 999, "sha256": "f" * 64}}),
                                ("AUTHORIZATION_SHA256", gates.digest(self.auth))):
                override = patch.object(module, name, value)
                override.start()
                self.addCleanup(override.stop)
        self.running = self.root / "ran-here"
        shutil.copytree(self.stage, self.running)
        _, self.binding, _ = gates.artifact_inputs(self.stage, "base")
        regressions = {}
        for number, name in enumerate(sorted(gates.directed.REGRESSIONS)):
            log = self.raw / f"unit-{number}.log"
            self.write(log, "合成门禁夹具，不代表测试曾真实执行。\n")
            path = self.raw / f"unit-{number}.json"
            self.write(path, {"status": "PASS", "returncode": 0, "scriptHashes": {name: gates.digest(self.stage / "source" / name)},
                "log": str(log), "logSha256": gates.digest(log)})
            regressions[name] = self.reference(path)
        reg = self.raw / "regressions.json"
        self.write(reg, {"status": "PASS", "tests": regressions})
        cases = {}
        for reason in ("unlocked", "missing", "untrusted-content"):
            enabled = reason == "unlocked"
            path = self.raw / (reason + ".json")
            self.write(path, {"status": "PASS", "expect": reason, "root": str(self.running),
                "verdict": {"reason": reason, "enabled": enabled}, "pageOpened": enabled, "pageRegistered": enabled,
                "httpConfigurationRetained": True, "layoutModelConfigurationVisible": True,
                "modelsUnchanged": True, "startupErrors": [], "documentBackend": "win32_PaddleOCRVL_1_6",
                "ocrBackend": "win32_PaddleOCRv6_CUDA"})
            cases[reason] = self.reference(path)
        gui = self.raw / "gui.json"
        self.write(gui, {"status": "PASS", "cases": cases})
        self.tray = self.raw / "tray.json"
        self.write(self.tray, {"status": "PASS", "root": str(self.running), "exit_code": 0, "http_ready_before_quit": True,
            "cli_forwarded": True, "shell_icons": [{"rect": [0, 0, 20, 20]}], "exe_sha256": gates.digest(self.running / "Umi-OCR.exe"),
            "test_sources": {name: gates.digest(self.stage / "source" / name) for name in ("tests/test_release312_native.py", "tests/test_windows_tray.py")}})
        self.document = self.raw / "document.json"
        self.write(self.document, {"status": "PASS", "root": str(self.running), "realSocket": True, "realModels": True,
            "fakeModelResponses": False, "passed": True, "plugins": {"uiFeatures": {"documentUi": False, "unlockState": "missing"}},
            "cases": [{"name": name, "sourcePageIdentifiers": "22/22", "sameTxtBytes": True,
                "allPageCoordinatesBounded": True, "execution": {"device": "GPU"}} for name in ("selected-page", "full-document")]})
        self.record = {"status": "ACCEPTED_WITH_LIMITATIONS", "validation_scope": gates.directed.SCOPE,
            "binding": self.binding, "manual_checks": {name: "NOT_RUN" for name in gates.directed.MANUAL},
            "unverified_scenarios": sorted(gates.directed.MANUAL),
            "user_acceptance": {"program_review_approved": True, "release_notes_approved": True,
                "capture_tests_cancelled": True, "hdr_capture_success": False, "published_components": gates.directed.APPROVED_COMPONENTS,
                "binding": self.binding, "authorization": self.reference(self.auth), "release_notes": self.reference(self.notes)},
            "automated_evidence": {"regressions": self.reference(reg), "gui_cases": self.reference(gui),
                "tray": self.reference(self.tray), "document_http": self.reference(self.document)}}

    @staticmethod
    def write(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)).encode("utf-8"))

    @staticmethod
    def reference(path):
        return {"path": str(path), "sha256": gates.digest(path)}

    def verify(self, record=None, kind="base", authorized=True):
        return gates.verify_current_source(self.record if record is None else record, kind, self.binding, self.stage, authorized)

    def blocked(self, record=None, **kwargs):
        with self.assertRaises((ValueError, OSError, TypeError, KeyError)):
            self.verify(record, **kwargs)

    def test_current_scope_preserves_all_not_run_and_exact_authorization(self):
        result = self.verify()
        self.assertTrue(gates.directed.verified_receipt(result))
        self.assertFalse(result["hdr_capture_success"])
        self.assertNotIn(str(self.root), json.dumps(result, ensure_ascii=False))
        self.assertEqual(result["manual_checks"], {name: "NOT_RUN" for name in gates.directed.MANUAL})

    def test_approval_flags_must_be_literal_true(self):
        for key in ("program_review_approved", "release_notes_approved", "capture_tests_cancelled"):
            for value in (False, 1, "true", None):
                with self.subTest(key=key, value=value):
                    record = copy.deepcopy(self.record)
                    record["user_acceptance"][key] = value
                    self.blocked(record)
        self.blocked(authorized=False)

    def test_no_other_kind_version_or_runtime_can_reuse_scope(self):
        self.blocked(kind="gpu")
        self.blocked(kind="cpu")
        self.write(self.stage / "UmiOCR-data/main.py", "# 改变已审运行字节\n")
        self.blocked()

    def test_other_version_cannot_get_new_pin_from_a_record(self):
        self.write(self.stage / "UmiOCR-data/about.json", {"version": {"major": 3, "minor": 1, "patch": 1}})
        self.blocked()

    def test_untested_capture_cannot_be_promoted_to_pass(self):
        for kind in ("manual", "hdr", "status", "missing", "duplicate"):
            with self.subTest(kind=kind):
                record = copy.deepcopy(self.record)
                if kind == "manual":
                    record["manual_checks"]["manual_hdr_acceptance"] = "PASS"
                elif kind == "hdr":
                    record["user_acceptance"]["hdr_capture_success"] = True
                elif kind == "status":
                    record["status"] = "PASS"
                elif kind == "missing":
                    record["unverified_scenarios"] = []
                else:
                    record["unverified_scenarios"] = ["manual_hdr_acceptance"] * 3
                self.blocked(record)

    def test_missing_evidence_and_extra_kinds_are_not_allowed(self):
        for name in self.record["automated_evidence"]:
            record = copy.deepcopy(self.record)
            record["automated_evidence"].pop(name)
            self.blocked(record)
        record = copy.deepcopy(self.record)
        record["automated_evidence"]["imagined_pass"] = self.reference(self.tray)
        self.blocked(record)

    def test_stale_source_and_full_binding_are_blocked(self):
        record = copy.deepcopy(self.record)
        record["binding"]["source"]["sha256"] = "f" * 64
        self.blocked(record)
        name = sorted(gates.directed.REGRESSIONS)[0]
        self.write(self.stage / "source" / name, "# 不同测试源码\n")
        _, self.binding, _ = gates.artifact_inputs(self.stage, "base")
        self.record["binding"] = self.binding
        self.record["user_acceptance"]["binding"] = self.binding
        self.blocked()

    def test_actual_run_root_cannot_be_swapped(self):
        self.write(self.running / "UmiOCR-data/main.py", "# 不同实际程序\n")
        self.blocked()

    def test_altered_or_declined_original_authorization_is_blocked(self):
        value = json.loads(self.auth.read_text("utf-8"))
        value["selectedAnswer"] = "暂不发布"
        self.write(self.auth, value)
        self.record["user_acceptance"]["authorization"] = self.reference(self.auth)
        self.blocked()

    def test_untested_or_fake_document_http_is_blocked(self):
        value = json.loads(self.document.read_text("utf-8"))
        value["fakeModelResponses"] = True
        self.write(self.document, value)
        self.record["automated_evidence"]["document_http"] = self.reference(self.document)
        self.blocked()

    def test_native_cli_and_prequit_readiness_are_required(self):
        value = json.loads(self.tray.read_text("utf-8"))
        value["http_ready_before_quit"] = False
        self.write(self.tray, value)
        self.record["automated_evidence"]["tray"] = self.reference(self.tray)
        self.blocked()

    def test_public_notes_cannot_lose_limitations_or_add_enablement_text(self):
        for text in ("3.1.2 3.0.5", "3.1.2 3.0.5 NOT_RUN Umi-OCR-UIUnlock.dll"):
            self.write(self.notes, text)
            self.record["user_acceptance"]["release_notes"] = self.reference(self.notes)
            self.blocked()

    def test_public_release_and_finalizer_accept_only_verified_scope(self):
        current = self.verify()
        source = {"status": "PASS", "verified": True}
        all_gates = {"source_delivery": source, "current_source_e2e": current, "runtime_vendor": {"status": "PASS"}}
        self.assertTrue(verifier.public_release_allowed(all_gates))
        all_gates["runtime_vendor"]["status"] = "BLOCK"
        self.assertFalse(verifier.public_release_allowed(all_gates))
        current["hdr_capture_success"] = True
        self.assertFalse(gates.directed.verified_receipt(current))
        current = self.verify()
        receipt = self.raw / "gate-input.json"
        self.write(receipt, {"synthetic": True})
        statuses = {name: "NOT_INCLUDED" for name in ("runtime_vendor", "paddle_models", "cuda", "cudnn", "opencv", "ffmpeg", "mpl", "agpl_nvidia", "cpu_ocr", "document_models")}
        statuses.update(source_delivery="PASS", current_source_e2e="ACCEPTED_WITH_LIMITATIONS")
        report = {"artifact_kind": "base", "public_prerelease_allowed": True, "local_candidate": False, "validation_errors": [],
            "release_gate_input": {"name": receipt.name, "sha256": gates.digest(receipt)},
            "source_delivery": source, "current_source_e2e": current, "gates": statuses}
        self.write(self.stage / "LICENSES/RELEASE_EVIDENCE.json", report)
        finalizer.check_report(self.stage, "base", self.binding, receipt, gates.digest(receipt))
        report["current_source_e2e"]["hdr_capture_success"] = True
        self.write(self.stage / "LICENSES/RELEASE_EVIDENCE.json", report)
        with self.assertRaises(finalizer.FinalizationError):
            finalizer.check_report(self.stage, "base", self.binding, receipt, gates.digest(receipt))

    def test_source_gate_failure_cannot_be_waived(self):
        current = self.verify()
        for status in ("BLOCK", "ACCEPTED_WITH_LIMITATIONS", "NOT_RUN"):
            self.assertFalse(verifier.public_release_allowed({"source_delivery": {"status": status, "verified": True},
                "current_source_e2e": current}))


if __name__ == "__main__":
    unittest.main()
