"""3.1.3 发布授权边界的合成单元夹具；不接受或发布任何实际程序。"""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release313_gate_fixture", ROOT / "build/tools/release_gate_inputs.py")
gates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gates)
m = gates.directed313
WORK = ROOT / "build/tmp/release-313-public-20261106-r1/scope-fixtures"


class Release313DirectedTests(unittest.TestCase):
    def setUp(self):
        WORK.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=WORK)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.notes = self.root / "notes.md"
        self.notes.write_text("SYNTHETIC UNIT TEST FIXTURE ONLY\n3.1.3 / CUDA 3.0.5; NOT_RUN\n", encoding="utf-8")
        self.distribution = {"component": "base", "runtimePayload": {"Umi-OCR.exe": "a" * 64, "SOURCE.txt": "b" * 64}}
        self.auth = {"fixture_only": True, "recordType": "explicit-current-program-and-notes-review",
                     "confirmationQuestion": m.APPROVAL_QUESTION, "selectedAnswer": m.APPROVAL_ANSWER,
                     "publicationAuthorized": True, "programReviewApproved": True, "releaseNotesApproved": True,
                     "approvedComponents": copy.deepcopy(m.APPROVED_COMPONENTS),
                     "approvedExecutionBindings": copy.deepcopy(m.RUNTIME_BINDINGS),
                     "releaseNotesSha256": gates.digest(self.notes), "mandatoryFormalGatesMayBeSkipped": False,
                     "furtherDesktopCaptureTestsAllowed": False,
                     "approvedMinimalRuntimeBindings": {key: gates.tree_binding(self.distribution["runtimePayload"])
                                                        for key in m.APPROVED_COMPONENTS}}
        self.path = self.root / "fixture-authorization.json"

    def approval(self):
        self.path.write_text(json.dumps(self.auth, ensure_ascii=False), encoding="utf-8")
        acceptance = {"authorization": {"path": str(self.path), "sha256": gates.digest(self.path)},
                      "release_notes": {"path": str(self.notes), "sha256": gates.digest(self.notes)}}
        return m.approval(acceptance, self.distribution, gates.__dict__)

    def derived(self):
        return {"validation_scope": m.SCOPE, "artifact_kind": "base", "release_version": "3.1.3",
                "status": "ACCEPTED_WITH_LIMITATIONS", "verified": True, "publication_authorized": True,
                "runtime_binding": copy.deepcopy(m.RUNTIME_BINDINGS["base"]),
                "approved_components": copy.deepcopy(m.APPROVED_COMPONENTS), "authorization_sha256": "f" * 64,
                "manual_checks": {key: "NOT_RUN" for key in m.MANUAL}, "unverified_scenarios": sorted(m.MANUAL),
                "hdr_capture_success": False, "validation_limits": {"new_full_pdf_matrix": "NOT_RUN",
                    "large_model_weight_network_download": "NOT_RUN", "non_windows_x64": "NOT_RUN"}}

    def test_exact_synthetic_approval_matches_notes_and_complete_minimal_payload(self):
        auth, notes = self.approval()
        self.assertEqual(auth["sha256"], gates.digest(self.path))
        self.assertEqual(notes["sha256"], gates.digest(self.notes))

    def test_generic_publication_intent_and_previous_version_are_not_review_approval(self):
        for change in ({"recordType": "publication-intent-not-final-review-approval", "selectedAnswer": "压缩方式的不考虑，发布新版本"},
                       {"selectedAnswer": "同意三组件发布"}, {"publicationAuthorized": False},
                       {"programReviewApproved": False}, {"releaseNotesApproved": False},
                       {"approvedComponents": {"base": "3.1.2", "cuda": "3.0.5", "paddlevl": "3.1.2"}},
                       {"furtherDesktopCaptureTestsAllowed": True}, {"mandatoryFormalGatesMayBeSkipped": True}):
            with self.subTest(change=change):
                before = copy.deepcopy(self.auth)
                self.auth.update(change)
                with self.assertRaises(ValueError):
                    self.approval()
                self.auth = before

    def test_changed_notices_source_guide_or_release_notes_invalidate_review(self):
        self.distribution["runtimePayload"]["SOURCE.txt"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "最简载荷"):
            self.approval()
        self.distribution["runtimePayload"]["SOURCE.txt"] = "b" * 64
        self.notes.write_text("changed 3.1.3 3.0.5 NOT_RUN", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.approval()

    def test_derived_receipt_requires_untested_limits_and_no_fabricated_hdr_success(self):
        original = self.derived()
        self.assertTrue(m.verified_receipt(original))
        for change in ({"publication_authorized": False}, {"release_version": "3.1.2"},
                       {"hdr_capture_success": True}, {"manual_checks": {name: "PASS" for name in m.MANUAL}},
                       {"authorization_sha256": ""}, {"runtime_binding": {"files": 1, "sha256": "f" * 64}},
                       {"unverified_scenarios": [{}]}, {"validation_limits": {}}):
            with self.subTest(change=change):
                value = copy.deepcopy(original)
                value.update(change)
                self.assertFalse(m.verified_receipt(value))

    def test_read_only_automated_preflight_is_not_a_publication_receipt(self):
        value = self.derived()
        value.update(status="AUTOMATED_FACTS_VERIFIED_NOT_AUTHORIZED", publication_authorized=False, verified=False)
        self.assertFalse(m.verified_receipt(value))
        with self.assertRaises(ValueError):
            m.verify({"validation_scope": m.SCOPE, "status": "ACCEPTED_WITH_LIMITATIONS", "binding": {}},
                     "base", {}, self.root, False, gates.__dict__)

    def test_old_scope_remains_distinct_and_cannot_accept_this_version(self):
        self.assertNotEqual(gates.directed.SCOPE, m.SCOPE)
        self.assertEqual(gates.directed.VERSIONS["base"], "3.1.2")
        self.assertFalse(gates.directed.verified_receipt(self.derived()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
