"""纯本体截图免测门禁；仅合成文件与日志，不启动程序、不截图、不运行模型。"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "build/tools" / filename)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


gates = load("capture_waiver_gates_test", "release_gate_inputs.py")
verifier = load("capture_waiver_verifier_test", "verify_release_evidence.py")
finalizer = load("capture_waiver_finalizer_test", "finalize_release.py")


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False), encoding="utf-8")


def reference(path):
    return {"path": str(path), "sha256": gates.digest(path)}


class BaseCaptureWaiverTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="base-capture-waiver-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.stage = self.root / "base"
        self.input = self.root / "gates.json"
        self.original_notes = self.root / "original-notes.md"
        self.notes = self.root / "scope-notes.md"
        self.confirmation = self.root / "user-decisions.md"
        write(self.stage / "UmiOCR-data/about.json", {"version": {"major": 3, "minor": 1, "patch": 1}})
        write(self.stage / "UmiOCR-data/main.py", "# SYNTHETIC SOURCE, NEVER EXECUTED\n")
        write(self.stage / "source/main.py", "# SYNTHETIC CORRESPONDING SOURCE\n")
        _, self.binding, _ = gates.artifact_inputs(self.stage, "base")
        write(self.original_notes, "UNIT TEST reviewed notes 3.1.1\n")
        write(self.notes, "# Umi-OCR v3.1.1\n本次仅发布主程序，CUDA 不发布。\n截图/HDR/混屏 NOT_RUN。\n")
        for module in (gates, verifier.release_gate_inputs, finalizer.gates):
            for name, value in (("BASE_CAPTURE_PAYLOAD", self.binding["payload"]), ("BASE_APPROVED_NOTES_SHA256", gates.digest(self.original_notes))):
                override = patch.object(module, name, value)
                override.start(); self.addCleanup(override.stop)
        evidence = {}
        for name, content in (("base_tests", "Base regression suite passed\n"),
                ("combined_tests", "Combined regression suite passed\n"),
                ("gui", {"hot": True, "errors": []}),
                ("tray", {"status": "PASS", "exit_code": 0, "http_ready_before_quit": True})):
            path = self.root / (name + ".log")
            write(path, content); evidence[name] = reference(path)
        acceptance = {"source": "Current user review and 2026-11-02 scope change",
            "program_review_quote": "本次3.1.1程序验收通过", "release_notes_quote": "3.1.1文案通过",
            "publication_quote": "发布3.1.1版本的release", "scope_change_quote": "cuda不发布\n截图后续不再测试",
            "binding": self.binding, "published_components": ["base"], "program_review_approved": True,
            "release_notes_approved": True, "capture_tests_cancelled": True, "cuda_publication_cancelled": True,
            "hdr_capture_success": False, "original_approved_notes": reference(self.original_notes), "release_notes": reference(self.notes)}
        text = "\n".join([acceptance[key] for key in ("program_review_quote", "release_notes_quote", "publication_quote", "scope_change_quote")])
        text += "\n" + "\n".join((gates.BASE_CAPTURE_SCOPE, "3.1.1", self.binding["payload"]["sha256"], self.binding["source"]["sha256"],
            gates.digest(self.original_notes), gates.digest(self.notes), *sorted(gates.MANUAL_CHECKS), "NOT_RUN"))
        write(self.confirmation, text)
        acceptance["record"] = reference(self.confirmation)
        self.current = {"status": "ACCEPTED_WITH_LIMITATIONS", "validation_scope": gates.BASE_CAPTURE_SCOPE,
            "binding": self.binding, "automated_evidence": evidence,
            "manual_checks": {name: "NOT_RUN" for name in gates.MANUAL_CHECKS},
            "unverified_scenarios": sorted(gates.MANUAL_CHECKS), "user_acceptance": acceptance}
        self.document = {"schema_version": 1, "artifact_kind": "base", "release_version": "3.1.1", "publication_authorized": True,
            "source_delivery": {"status": "PASS", "repositories": [{"role": "host", "url": gates.PUBLIC_REPOSITORIES["host"],
                "tag": "v3.1.1", "commit": "a" * 40, "checkout": str(self.root)}]}, "current_source_e2e": self.current}

    def validate(self, document=None):
        write(self.input, self.document if document is None else document)
        with patch.object(gates, "public_tag", return_value={"refs/tags/v3.1.1": "a" * 40}), patch.object(gates, "git_source_matches"):
            return gates.validate_release_gates(self.input, self.stage, "base")

    def blocked(self, document):
        self.assertEqual(self.validate(document)["current_source_e2e"]["status"], "BLOCK")

    def test_current_base_waiver_is_limited_and_has_no_hdr_success_or_host_path(self):
        result = self.validate()["current_source_e2e"]
        self.assertTrue(gates.verified_base_capture_waiver(result))
        self.assertEqual(result["status"], "ACCEPTED_WITH_LIMITATIONS")
        self.assertTrue(all(value == "NOT_RUN" for value in result["manual_checks"].values()))
        self.assertIs(result["user_acceptance"]["hdr_capture_success"], False)
        self.assertNotIn(str(self.root), json.dumps(result, ensure_ascii=False))

    def test_gpu_cannot_use_base_waiver(self):
        with self.assertRaises(ValueError):
            gates.verify_current_source(self.current, "gpu", self.binding, self.stage, True)

    def test_other_version_and_changed_payload_cannot_inherit_approval(self):
        for relative in ("UmiOCR-data/about.json", "UmiOCR-data/main.py"):
            path = self.stage / relative
            original = path.read_text("utf-8")
            write(path, {"version": {"major": 3, "minor": 1, "patch": 2}} if relative.endswith("about.json") else "# changed payload\n")
            document = copy.deepcopy(self.document)
            _, binding, _ = gates.artifact_inputs(self.stage, "base")
            document["release_version"] = "3.1.2" if relative.endswith("about.json") else "3.1.1"
            document["current_source_e2e"]["binding"] = binding
            document["current_source_e2e"]["user_acceptance"]["binding"] = binding
            self.blocked(document)
            write(path, original)

    def test_missing_quotes_and_literal_approvals_fail_closed(self):
        for name in ("program_review_quote", "release_notes_quote", "publication_quote", "scope_change_quote", "record",
                "original_approved_notes", "release_notes", "program_review_approved", "release_notes_approved",
                "capture_tests_cancelled", "cuda_publication_cancelled", "binding", "published_components"):
            document = copy.deepcopy(self.document)
            document["current_source_e2e"]["user_acceptance"].pop(name)
            self.blocked(document)

    def test_flags_must_be_literal_true(self):
        for value in (False, 1, "true", None):
            document = copy.deepcopy(self.document)
            document["current_source_e2e"]["user_acceptance"]["capture_tests_cancelled"] = value
            self.blocked(document)

    def test_cancelled_tests_cannot_be_reported_as_manual_pass_or_hdr_success(self):
        for field in ("manual", "hdr", "status"):
            document = copy.deepcopy(self.document)
            if field == "manual": document["current_source_e2e"]["manual_checks"]["manual_hdr_acceptance"] = "PASS"
            elif field == "hdr": document["current_source_e2e"]["user_acceptance"]["hdr_capture_success"] = True
            else: document["current_source_e2e"]["status"] = "PASS"
            self.blocked(document)

    def test_all_three_untested_scenarios_must_be_disclosed_once(self):
        for untested in ([], ["manual_hdr_acceptance"], ["manual_hdr_acceptance"] * 3, ["other"]):
            document = copy.deepcopy(self.document)
            document["current_source_e2e"]["unverified_scenarios"] = untested
            self.blocked(document)

    def test_original_user_record_cannot_be_replaced_with_invented_confirmation(self):
        write(self.confirmation, "A different decision")
        document = copy.deepcopy(self.document)
        document["current_source_e2e"]["user_acceptance"]["record"] = reference(self.confirmation)
        self.blocked(document)

    def test_original_notes_and_current_note_hashes_are_required(self):
        for name in ("original_approved_notes", "release_notes"):
            document = copy.deepcopy(self.document)
            document["current_source_e2e"]["user_acceptance"][name]["sha256"] = "0" * 64
            self.blocked(document)

    def test_cuda_implementation_or_plugin_execution_is_not_publishable_in_base_scope(self):
        for relative in ("source/UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/api.py", "source/build/windows/CudaWorker/worker_main.cpp", "UmiOCR-data/plugins/other/umi-plugin.json"):
            target = self.stage / relative
            write(target, "# forbidden implementation\n")
            document = copy.deepcopy(self.document)
            _, binding, _ = gates.artifact_inputs(self.stage, "base")
            document["current_source_e2e"]["binding"] = binding
            document["current_source_e2e"]["user_acceptance"]["binding"] = binding
            self.blocked(document)
            target.unlink()
            while target.parent != self.stage and not list(target.parent.iterdir()):
                parent = target.parent; parent.rmdir(); target = parent

    def test_failed_automatic_evidence_and_missing_publication_auth_stay_blocked(self):
        for name in self.current["automated_evidence"]:
            document = copy.deepcopy(self.document)
            document["current_source_e2e"]["automated_evidence"][name]["sha256"] = "0" * 64
            self.blocked(document)
        document = copy.deepcopy(self.document); document["publication_authorized"] = False
        self.blocked(document)

    def test_public_locator_cannot_include_host_paths(self):
        for locator in (r"C:\Users\private", r"\\server\share", "/home/private"):
            document = copy.deepcopy(self.document)
            document["current_source_e2e"]["user_acceptance"]["source"] = locator
            self.blocked(document)

    def test_component_gates_are_not_waived_by_capture_policy(self):
        result = self.validate()
        self.assertTrue(verifier.public_release_allowed({**result, "runtime_vendor": {"status": "PASS"}}))
        for name in ("runtime_vendor", "paddle_models", "cuda", "agpl_nvidia"):
            self.assertFalse(verifier.public_release_allowed({**result, name: {"status": "BLOCK"}}))
        changed = copy.deepcopy(result); changed["current_source_e2e"]["artifact_kind"] = "gpu"
        self.assertFalse(verifier.public_release_allowed(changed))

    def test_finalizer_checks_scoped_base_acceptance_without_mutating_manual_statuses(self):
        current = self.validate()["current_source_e2e"]
        technical = {name: "NOT_INCLUDED" for name in ("runtime_vendor", "paddle_models", "cuda", "cudnn", "opencv", "ffmpeg", "mpl", "agpl_nvidia", "cpu_ocr", "document_models")}
        report = {"artifact_kind": "base", "public_prerelease_allowed": True, "local_candidate": False, "validation_errors": [],
            "release_gate_input": {"name": self.input.name, "sha256": gates.digest(self.input)},
            "source_delivery": {"status": "PASS", "verified": True}, "current_source_e2e": current,
            "gates": {**technical, "source_delivery": "PASS", "current_source_e2e": "ACCEPTED_WITH_LIMITATIONS"}}
        write(self.stage / "LICENSES/RELEASE_EVIDENCE.json", report)
        finalizer.check_report(self.stage, "base", self.binding, self.input, gates.digest(self.input))
        report["current_source_e2e"]["artifact_kind"] = "gpu"
        write(self.stage / "LICENSES/RELEASE_EVIDENCE.json", report)
        with self.assertRaises(finalizer.FinalizationError):
            finalizer.check_report(self.stage, "base", self.binding, self.input, gates.digest(self.input))


if __name__ == "__main__":
    unittest.main()
