"""Offline publication-gate regressions; all written artifacts are temporary."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "build/tools" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gates = load("gate_inputs_test", "release_gate_inputs.py")
verifier = load("evidence_gate_test", "verify_release_evidence.py")


class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.staging = self.root / "base"
        self.source = self.staging / "source"
        self.raw = self.root / "raw"
        self.raw.mkdir()
        self.write(self.staging / "UmiOCR-data/about.json", {"version": {"major": 3, "minor": 0, "patch": 1}})
        self.write(self.staging / "UmiOCR-data/main.py", "# actual host\n")
        self.write(self.source / "UmiOCR-data/main.py", "# actual host\n")
        self.write(self.source / "build/build.py", "# actual build input\n")
        self.disclosure = "混合屏 HDR/SDR 人工验收未完成；保留 NOT_RUN，用户在获知限制后决定发布。"
        self.hdr_quote = "HDR捕获是成功的，能否继续？"
        self.approval = "我觉得可以发布了"
        self.acceptance_path = self.raw / "RELEASE_3.0.1_ACCEPTANCE.md"
        self.write(self.acceptance_path, self.disclosure + "\n" + self.hdr_quote + "\n" + self.approval)
        self.evidence = {}
        for name, content in (
            ("base_tests", "Base regression suite passed.\n"),
            ("combined_tests", "Combined regression suite passed.\n"),
            ("gui", {"hot": True, "errors": []}),
            ("tray", {"status": "PASS", "exit_code": 0, "http_ready_before_quit": True,
                      "initial_legacy_probe": {"status": "FAILED", "error": "10061"}}),
        ):
            path = self.raw / (name + (".log" if isinstance(content, str) else ".json"))
            self.write(path, content)
            self.evidence[name] = self.reference(path)
        _, self.binding, _ = gates.artifact_inputs(self.staging, "base")
        self.document = self.receipt("base")
        self.input = self.root / "release-gates.json"

    @staticmethod
    def write(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content, ensure_ascii=False) if not isinstance(content, str) else content, encoding="utf-8")

    @staticmethod
    def reference(path):
        return {"path": str(path), "sha256": gates.digest(path)}

    def receipt(self, kind):
        role = "host" if kind == "base" else "cuda"
        return {
            "schema_version": 1, "artifact_kind": kind, "release_version": "3.0.1",
            "publication_authorized": True,
            "source_delivery": {"status": "PASS", "repositories": [{
                "role": role, "url": gates.PUBLIC_REPOSITORIES[role], "tag": "v3.0.1",
                "commit": "a" * 40, "checkout": str(self.root),
            }]},
            "current_source_e2e": {
                "status": "ACCEPTED_WITH_LIMITATIONS", "binding": self.binding,
                "automated_evidence": copy.deepcopy(self.evidence),
                "manual_checks": {name: "NOT_RUN" for name in gates.MANUAL_CHECKS},
                "unverified_scenarios": ["mixed HDR/SDR monitors remain untested"],
                "user_acceptance": {
                    "source": "User messages after the release-limitations disclosure",
                    "hdr_capture_success": True, "hdr_capture_success_quote": self.hdr_quote,
                    "publish_with_untested_mixed_monitors": True,
                    "limitations_disclosure_quote": self.disclosure,
                    "publication_quote": self.approval, "binding": self.binding,
                    "record": self.reference(self.acceptance_path),
                },
            },
        }

    def validate(self, document=None, kind="base", staging=None):
        self.write(self.input, self.document if document is None else document)
        with patch.object(gates, "public_tag", return_value={"refs/tags/v3.0.1": "a" * 40}), patch.object(gates, "git_source_matches"):
            return gates.validate_release_gates(self.input, staging or self.staging, kind)

    def test_no_input_preserves_block_and_does_not_trust_old_pass(self):
        for status in ("BLOCK", "PASS", "NOT_INCLUDED", "ACCEPTED_WITH_LIMITATIONS"):
            old = {"gates": {name: status for name in gates.RELEASE_GATES}}
            result = gates.validate_release_gates(None, self.staging, "base", old)
            for name in gates.RELEASE_GATES:
                self.assertEqual(result[name]["status"], "BLOCK")
                self.assertEqual(result[name]["previous_recorded_status"], status)
                self.assertFalse(result[name]["verified"])

    def test_valid_limited_acceptance_is_not_manual_pass_or_path_leak(self):
        result = self.validate()
        self.assertEqual(result["source_delivery"]["status"], "PASS")
        current = result["current_source_e2e"]
        self.assertEqual(current["status"], "ACCEPTED_WITH_LIMITATIONS")
        self.assertTrue(current["verified"])
        self.assertTrue(all(value == "NOT_RUN" for value in current["manual_checks"].values()))
        self.assertNotIn(str(self.root), json.dumps(result, ensure_ascii=False))

    def test_missing_or_invented_gate_status_cannot_publish(self):
        for name in gates.RELEASE_GATES:
            for status in (None, "BLOCK", "NOT_INCLUDED", "WAIVED", "PASS_WITH_REQUIREMENTS", True):
                with self.subTest(name=name, status=status):
                    document = copy.deepcopy(self.document)
                    document[name]["status"] = status
                    self.assertEqual(self.validate(document)[name]["status"], "BLOCK")

    def test_publication_authorization_must_be_literal_true(self):
        for value in (False, None, "true", 1):
            document = copy.deepcopy(self.document)
            document["publication_authorized"] = value
            result = self.validate(document)
            self.assertTrue(all(item["status"] == "BLOCK" for item in result.values()))

    def test_binding_detects_payload_or_source_change(self):
        for relative in ("UmiOCR-data/main.py", "source/build/build.py"):
            with self.subTest(relative=relative):
                target = self.staging / relative
                original = target.read_text("utf-8")
                self.write(target, original + "# changed\n")
                self.assertEqual(self.validate()["current_source_e2e"]["status"], "BLOCK")
                self.write(target, original)

    def test_user_record_and_approval_are_required_and_bound(self):
        for field in ("hdr_capture_success", "hdr_capture_success_quote", "publication_quote", "limitations_disclosure_quote", "publish_with_untested_mixed_monitors", "source", "binding", "record"):
            document = copy.deepcopy(self.document)
            document["current_source_e2e"]["user_acceptance"].pop(field)
            self.assertEqual(self.validate(document)["current_source_e2e"]["status"], "BLOCK", field)

    def test_confirmation_document_cannot_disagree_with_the_quotes(self):
        self.write(self.acceptance_path, "A different decision")
        document = copy.deepcopy(self.document)
        document["current_source_e2e"]["user_acceptance"]["record"] = self.reference(self.acceptance_path)
        self.assertEqual(self.validate(document)["current_source_e2e"]["status"], "BLOCK")

    def test_failed_automated_evidence_is_not_waivable(self):
        for name in self.evidence:
            document = copy.deepcopy(self.document)
            path = self.raw / (name + ".failed")
            content = "FAILED\n" if name.endswith("tests") else {"hot": False, "errors": ["failure"], "status": "FAILED", "exit_code": 1, "http_ready_before_quit": False}
            self.write(path, content)
            document["current_source_e2e"]["automated_evidence"][name] = self.reference(path)
            self.assertEqual(self.validate(document)["current_source_e2e"]["status"], "BLOCK", name)

    def test_evidence_hash_and_missing_evidence_fail_closed(self):
        for name in self.evidence:
            document = copy.deepcopy(self.document)
            document["current_source_e2e"]["automated_evidence"][name]["sha256"] = "0" * 64
            self.assertEqual(self.validate(document)["current_source_e2e"]["status"], "BLOCK")
        document = copy.deepcopy(self.document)
        document["current_source_e2e"]["automated_evidence"].pop("tray")
        self.assertEqual(self.validate(document)["current_source_e2e"]["status"], "BLOCK")

    def test_full_pass_cannot_disguise_untested_manual_checks(self):
        document = copy.deepcopy(self.document)
        document["current_source_e2e"]["status"] = "PASS"
        self.assertEqual(self.validate(document)["current_source_e2e"]["status"], "BLOCK")
        document["current_source_e2e"]["manual_checks"] = {name: "PASS" for name in gates.MANUAL_CHECKS}
        document["current_source_e2e"]["unverified_scenarios"] = []
        self.assertEqual(self.validate(document)["current_source_e2e"]["status"], "BLOCK")

    def test_failed_manual_check_is_not_accepted_as_unknown(self):
        document = copy.deepcopy(self.document)
        document["current_source_e2e"]["manual_checks"]["manual_hdr_acceptance"] = "BLOCK"
        self.assertEqual(self.validate(document)["current_source_e2e"]["status"], "BLOCK")

    def test_source_url_tag_commit_and_roles_are_not_arbitrary(self):
        for field, value in (("url", "https://example.com/private"), ("url", "git@github.com:Dominic485649/UMI-OCR.git"), ("tag", "main"), ("commit", "abc"), ("role", "other")):
            document = copy.deepcopy(self.document)
            document["source_delivery"]["repositories"][0][field] = value
            self.assertEqual(self.validate(document)["source_delivery"]["status"], "BLOCK")
        document = copy.deepcopy(self.document)
        document["source_delivery"]["repositories"] *= 2
        self.assertEqual(self.validate(document)["source_delivery"]["status"], "BLOCK")

    def test_duplicate_json_keys_and_wrong_identity_are_rejected(self):
        self.input.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        result = gates.validate_release_gates(self.input, self.staging, "base")
        self.assertTrue(all(item["status"] == "BLOCK" for item in result.values()))
        for field, value in (("schema_version", True), ("release_version", "3.0.0"), ("artifact_kind", "gpu")):
            document = copy.deepcopy(self.document)
            document[field] = value
            self.assertTrue(all(item["status"] == "BLOCK" for item in self.validate(document).values()))

    def test_anonymous_tag_check_handles_lightweight_and_peeled_tags(self):
        for output in (
            b"a" * 40 + b"\trefs/tags/v3.0.1\n",
            b"b" * 40 + b"\trefs/tags/v3.0.1\n" + b"a" * 40 + b"\trefs/tags/v3.0.1^{}\n",
        ):
            with patch.object(gates, "_git", return_value=output) as command:
                gates.public_tag(gates.PUBLIC_REPOSITORIES["host"], "v3.0.1", "a" * 40, cwd=self.staging)
                self.assertTrue(command.call_args.kwargs["anonymous"])
        with patch.object(gates, "_git", return_value=b"b" * 40 + b"\trefs/tags/v3.0.1\n"):
            with self.assertRaises(ValueError):
                gates.public_tag(gates.PUBLIC_REPOSITORIES["host"], "v3.0.1", "a" * 40, cwd=self.staging)

    def test_anonymous_git_cannot_inherit_repository_or_credential_configuration(self):
        from types import SimpleNamespace
        response = SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        with patch.dict(gates.os.environ, {"GIT_DIR": "private-repo", "GIT_WORK_TREE": "private-tree", "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.extraHeader", "GIT_CONFIG_VALUE_0": "private-token"}), patch.object(gates.subprocess, "run", return_value=response) as execute:
            gates._git(["ls-remote", "https://github.com/example/public"], cwd=Path(self.root.anchor), anonymous=True)
        environment = execute.call_args.kwargs["env"]
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0"):
            self.assertNotIn(name, environment)
        self.assertEqual(environment["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertEqual(environment["GIT_CONFIG_GLOBAL"], gates.os.devnull)
        self.assertEqual(environment["GIT_NO_REPLACE_OBJECTS"], "1")
        self.assertEqual(environment["GIT_NO_LAZY_FETCH"], "1")
        self.assertEqual(environment["GIT_TERMINAL_PROMPT"], "0")

    def test_git_object_comparison_verifies_member_set_and_bytes(self):
        content = b"canonical source\n"
        oid = b"a" * 40
        tree = b"100644 blob " + oid + b"\tmain.py\0"
        blob = oid + b" blob " + str(len(content)).encode() + b"\n" + content + b"\n"
        source = {"main.py": __import__("hashlib").sha256(content).hexdigest()}
        with patch.object(gates, "_git", side_effect=[tree, blob]):
            gates.git_source_matches(self.root, "b" * 40, source)
        with patch.object(gates, "_git", return_value=tree):
            with self.assertRaises(ValueError):
                gates.git_source_matches(self.root, "b" * 40, {**source, "extra.py": "0" * 64})
        with patch.object(gates, "_git", side_effect=[tree, blob]):
            with self.assertRaises(ValueError):
                gates.git_source_matches(self.root, "b" * 40, {"main.py": "0" * 64})

    def test_overlay_uses_nested_metadata_without_root_fabrication(self):
        overlay = self.root / "overlay"
        plugin = overlay / "UmiOCR-data/plugins" / gates.PLUGIN_ID
        metadata = overlay / "LICENSES/plugins" / gates.PLUGIN_ID
        self.write(plugin / "umi-plugin.json", {"version": "3.0.1"})
        self.write(plugin / "api.py", "# CUDA\n")
        self.write(metadata / "LICENSES/Apache-2.0.txt", "license")
        self.write(metadata / "source/build/build.py", "# canonical CUDA source\n")
        self.assertEqual(gates.artifact_metadata_root(overlay, "gpu"), metadata)
        version, binding, _ = gates.artifact_inputs(overlay, "gpu")
        self.assertEqual(version, "3.0.1")
        self.assertGreater(binding["payload"]["files"], 0)
        eula = metadata / verifier.CUDA_EULA_SNAPSHOT
        self.write(eula, "the exact EULA evidence")
        with patch.object(verifier, "CUDA_EULA_SNAPSHOT_SHA256", gates.digest(eula)):
            snapshot = verifier.cuda_eula_snapshot(overlay)
        self.assertTrue(snapshot["verified"])
        self.assertEqual(snapshot["artifact_path"], eula.relative_to(overlay).as_posix())
        self.assertFalse((overlay / "source").exists())
        self.assertFalse((overlay / "LICENSES/RELEASE_EVIDENCE.json").exists())
        self.write(overlay / "SOURCE-CODE.md", "conflicting root record")
        with self.assertRaises(ValueError):
            gates.artifact_metadata_root(overlay, "gpu")

    def test_real_gpu_record_and_separate_workflow_log_bind_the_overlay(self):
        staging = self.root / "cuda"
        plugin = staging / "UmiOCR-data/plugins" / gates.PLUGIN_ID
        metadata = staging / "LICENSES/plugins" / gates.PLUGIN_ID
        self.write(plugin / "umi-plugin.json", {"version": "3.0.1"})
        self.write(plugin / "api.py", "# tested adapter\n")
        self.write(plugin / "worker.py", "# tested worker\n")
        self.write(plugin / "runtime.lock.json", {"files": []})
        workflow_test = metadata / "source/tests/test_ocr_workflows.py"
        self.write(workflow_test, "# real workflow test source\n")
        self.write(metadata / "LICENSES/Apache-2.0.txt", "license")
        log = self.raw / "independent-gpu-workflow.log"
        self.write(log, "OCR workflow tests passed: real CUDA\n")
        raw = self.raw / "gpu-record.json"
        record = {
            "test_type": "real_gpu_ocr_workflows_e2e", "status": "PASS", "device": "gpu:0",
            "plugin_runtime_lock_sha256": gates.digest(plugin / "runtime.lock.json"),
            "plugin_source_sha256": {name: gates.digest(plugin / name) for name in ("api.py", "worker.py")},
            "workflow_test": {"path": "tests/test_ocr_workflows.py", "SHA256": gates.digest(workflow_test)},
            "workflow_log": {"file": log.name, "SHA256": gates.digest(log)},
        }
        self.write(raw, record)
        self.write(plugin / "gpu-e2e-evidence.json", record)
        _, binding, _ = gates.artifact_inputs(staging, "gpu")
        document = self.receipt("gpu")
        document["current_source_e2e"]["binding"] = binding
        document["current_source_e2e"]["user_acceptance"]["binding"] = binding
        automated = document["current_source_e2e"]["automated_evidence"]
        automated["gpu_workflows"] = self.reference(raw)
        automated["gpu_workflow_log"] = self.reference(log)
        result = self.validate(document, "gpu", staging)
        self.assertTrue(result["current_source_e2e"]["verified"], result)
        self.write(log, "OCR workflow tests FAILED\n")
        automated["gpu_workflow_log"] = self.reference(log)
        self.assertEqual(self.validate(document, "gpu", staging)["current_source_e2e"]["status"], "BLOCK")

    def test_linked_release_inputs_are_rejected(self):
        original = Path.is_junction
        with patch.object(Path, "is_junction", lambda path: path == self.source or original(path)):
            with self.assertRaises(ValueError):
                gates.artifact_inputs(self.staging, "base")

    def test_verifier_rebuild_keeps_all_license_diagnostics_and_new_blocks(self):
        repo = self.root / "repo"
        self.write(repo / "build/sources-windows-cu126.lock.json", {})
        (self.staging / "UmiOCR-data/site-packages").mkdir()
        old = {"gates": {"source_delivery": "BLOCK", "current_source_e2e": "BLOCK"}, "local_candidate": True,
               "source_delivery": {"status": "BLOCK"},
               "current_source_validation": {"manual_hdr_acceptance": "NOT_RUN"}}
        self.write(self.staging / "LICENSES/RELEASE_EVIDENCE.json", old)
        with patch.object(verifier, "ensure_apache_license", return_value="LICENSES/Apache-2.0.txt"), patch.object(verifier, "verify_runtime_vendor", return_value={"status": "PASS"}), patch.object(verifier, "verify_opencv", return_value={"status": "PASS"}), patch.object(verifier, "verify_ffmpeg", return_value={"status": "NOT_INCLUDED"}), patch.object(verifier, "verify_cpu_and_document", return_value={"cpu_ocr": {"status": "NOT_INCLUDED"}, "document_models": {"status": "NOT_INCLUDED"}}):
            report = verifier.verify(self.staging, repo, "base", None)
        self.assertEqual(report["gates"]["runtime_vendor"], "PASS")
        self.assertEqual(report["gates"]["opencv"], "PASS")
        self.assertEqual(report["gates"]["source_delivery"], "BLOCK")
        self.assertEqual(report["gates"]["current_source_e2e"], "BLOCK")
        self.assertFalse(report["public_prerelease_allowed"])
        self.assertEqual(report["current_source_validation"], old["current_source_validation"])

    def test_explicit_verified_receipt_replaces_old_candidate_flag(self):
        repo = self.root / "repo"
        self.write(repo / "build/sources-windows-cu126.lock.json", {})
        (self.staging / "UmiOCR-data/site-packages").mkdir()
        self.write(self.staging / "LICENSES/RELEASE_EVIDENCE.json", {
            "local_candidate": True, "gates": {name: "BLOCK" for name in gates.RELEASE_GATES},
        })
        accepted = {"source_delivery": {"status": "PASS", "verified": True},
                    "current_source_e2e": {"status": "ACCEPTED_WITH_LIMITATIONS", "verified": True, "publication_authorized": True}}
        with patch.object(verifier, "ensure_apache_license", return_value="LICENSES/Apache-2.0.txt"), patch.object(verifier, "verify_runtime_vendor", return_value={"status": "PASS"}), patch.object(verifier, "verify_opencv", return_value={"status": "PASS"}), patch.object(verifier, "verify_ffmpeg", return_value={"status": "NOT_INCLUDED"}), patch.object(verifier, "verify_cpu_and_document", return_value={"cpu_ocr": {"status": "NOT_INCLUDED"}, "document_models": {"status": "NOT_INCLUDED"}}), patch.object(verifier.release_gate_inputs, "validate_release_gates", return_value=accepted):
            report = verifier.verify(self.staging, repo, "base", None, release_gates=self.input)
        self.assertFalse(report["local_candidate"])
        self.assertTrue(report["public_prerelease_allowed"])
        self.assertEqual(report["gates"]["current_source_e2e"], "ACCEPTED_WITH_LIMITATIONS")

    def test_public_aggregation_only_accepts_validated_special_exception(self):
        valid = {"license": {"status": "PASS"}, "source_delivery": {"status": "PASS", "verified": True},
                 "current_source_e2e": {"status": "ACCEPTED_WITH_LIMITATIONS", "verified": True, "publication_authorized": True}}
        self.assertTrue(verifier.public_release_allowed(valid))
        self.assertFalse(verifier.public_release_allowed({"license": {"status": "PASS"}}))
        for name in valid:
            changed = copy.deepcopy(valid)
            changed[name] = {"status": "ACCEPTED_WITH_LIMITATIONS", "verified": True, "publication_authorized": True}
            if name != "current_source_e2e":
                self.assertFalse(verifier.public_release_allowed(changed))
        changed = copy.deepcopy(valid)
        changed["current_source_e2e"].pop("verified")
        self.assertFalse(verifier.public_release_allowed(changed))

    def test_overlay_verifier_writes_only_nested_derived_reports(self):
        staging = self.root / "gpu-overlay"
        metadata = staging / "LICENSES/plugins" / gates.PLUGIN_ID
        self.write(staging / "UmiOCR-data/plugins" / gates.PLUGIN_ID / "umi-plugin.json", {"version": "3.0.1"})
        (staging / "UmiOCR-data/plugins" / gates.PLUGIN_ID / "vendor").mkdir()
        self.write(metadata / "source/build/build.py", "# canonical source never rewritten\n")
        self.write(metadata / "LICENSES/RELEASE_EVIDENCE.json", {"gates": {"source_delivery": "BLOCK", "current_source_e2e": "BLOCK"}})
        repo = self.root / "repo"
        self.write(repo / "build/sources-windows-cu126.lock.json", {})
        source_before = gates._files(metadata / "source")
        _, binding_before, _ = gates.artifact_inputs(staging, "gpu")
        functions = ("verify_runtime_vendor", "verify_models", "verify_nvidia", "verify_cudnn", "verify_opencv", "verify_mpl", "verify_agpl", "verify_gpu_e2e")
        from contextlib import ExitStack
        with ExitStack() as stack:
            stack.enter_context(patch.object(verifier, "ensure_apache_license", return_value="LICENSES/Apache-2.0.txt"))
            for name in functions:
                stack.enter_context(patch.object(verifier, name, return_value={"status": "PASS"}))
            stack.enter_context(patch.object(verifier, "verify_ffmpeg", return_value={"status": "NOT_INCLUDED"}))
            stack.enter_context(patch.object(verifier, "verify_cpu_and_document", return_value={"cpu_ocr": {"status": "NOT_INCLUDED"}, "document_models": {"status": "NOT_INCLUDED"}}))
            report = verifier.verify(staging, repo, "gpu", None)
        self.assertEqual(report["gates"]["cuda"], "PASS")
        self.assertEqual(report["gates"]["source_delivery"], "BLOCK")
        self.assertFalse(report["public_prerelease_allowed"])
        self.assertFalse((staging / "LICENSES/RELEASE_EVIDENCE.json").exists())
        self.assertFalse((staging / "source").exists())
        self.assertEqual(gates._files(metadata / "source"), source_before)
        self.assertEqual(gates.artifact_inputs(staging, "gpu")[1], binding_before)
        markdown = (metadata / "LICENSES/RELEASE_EVIDENCE.md").read_text("utf-8")
        self.assertIn("LICENSES/plugins/" + gates.PLUGIN_ID + "/LICENSES/source-delivery.json", markdown)

    def test_powershell_rejects_conflicting_modes_before_artifact_access(self):
        script = ROOT / "build/windows/Audit-Package.ps1"
        for arguments in (
            ["-LocalCandidate", "-RequirePublicRelease"],
            ["-LocalCandidate", "-ReleaseGates", str(self.input)],
            ["-RequirePublicRelease"],
        ):
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), "-PackageRoot", str(self.root / "does-not-exist"), *arguments], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("ParserError", result.stdout + result.stderr)
            self.assertRegex(result.stdout + result.stderr, "mutually exclusive|requires an explicit")


startup_fixtures = load("release_startup_fixtures", "../../tests/test_gpu_startup_evidence.py")


class StartupGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="umi-startup-gates-")
        self.addCleanup(self.temporary.cleanup)
        self.fixture = startup_fixtures.StartupFixture(Path(self.temporary.name))
        self.startup = startup_fixtures.startup
        self.acceptance_path = self.fixture.audit / "current-review.txt"
        self.notes = self.fixture.audit / "release-notes.txt"
        self.write = startup_fixtures.write
        self.write(self.notes, "3.0.4 program and release notes; OCR not retested.\n")
        # These exact corresponding-source test members are tiny fixture bytes.
        for name in gates.STARTUP_TEST_SOURCES:
            self.write(self.fixture.metadata / "source" / name, "# fixture scoped test source\n")
        _, self.fixture.binding, _ = gates.artifact_inputs(self.fixture.staging, "gpu")
        self.fixture.matrix["binding"] = self.fixture.binding
        host = json.loads(self.fixture.host_path.read_text("utf-8"))
        host["binding"] = self.fixture.binding
        self.write(self.fixture.host_path, host)
        self.fixture.matrix["host_startup"] = self.fixture.ref(self.fixture.host_path)
        self.fixture.save()
        binding = self.fixture.binding
        logs, runs = [], []
        for optimization in (0, 1):
            path = self.fixture.audit / f"unit-{optimization}.log"
            self.write(path, "SYNTHETIC scoped unit test output\nRan 17 tests in 0.01s\n\nOK\n")
            logs.append(path)
            runs.append({"optimization": optimization, "exit_code": 0, "log": self.fixture.ref(path)})
        self.unit_logs = logs
        self.units = self.fixture.audit / "units.json"
        self.write(self.units, {"schema_version": 1, "test_type": "cuda_startup_hotfix_unit_tests", "status": "PASS", "binding": binding,
                                "runs": runs, "test_source_sha256": {name: gates.digest(self.fixture.metadata / "source" / name) for name in gates.STARTUP_TEST_SOURCES}})
        matrix_ref = self.fixture.ref(self.fixture.matrix_path)
        quotes = {"program_review_quote": "我已审查本轮程序，同意该程序。", "release_notes_quote": "我已审查本轮文案，同意该文案。",
                  "limitations_disclosure_quote": "本轮 OCR 未重测，只验证启动，保留 NOT_RUN。", "publication_quote": "同意按所披露限制发布 3.0.4。"}
        self.write(self.acceptance_path, "\n".join(["3.0.4", gates.STARTUP_SCOPE, binding["payload"]["sha256"], binding["source"]["sha256"],
                                                  gates.digest(self.notes), matrix_ref["sha256"], *quotes.values()]))
        self.record = {"validation_scope": gates.STARTUP_SCOPE, "status": "ACCEPTED_WITH_LIMITATIONS", "binding": binding,
                       "gpu_ocr_e2e": "NOT_RUN", "manual_checks": {name: "NOT_RUN" for name in gates.MANUAL_CHECKS},
                       "unverified_scenarios": ["OCR workflows not rerun for this startup-only hotfix", "HDR/mixed monitors not rerun"],
                       "automated_evidence": {"startup_unit_tests": self.fixture.ref(self.units), "gpu_startup_matrix": matrix_ref},
                       "user_acceptance": {"source": "Current 3.0.4 review conversation", "record": self.fixture.ref(self.acceptance_path),
                                           "validation_scope": gates.STARTUP_SCOPE, "release_version": "3.0.4", "binding": binding,
                                           "program_review_approved": True, "release_notes_approved": True, "publish_with_untested_ocr": True,
                                           "release_notes": self.fixture.ref(self.notes), "evidence_binding": matrix_ref, **quotes}}

    def verify(self, record=None, kind="gpu", authorized=True):
        with self.fixture.patches(), patch.object(gates, "startup_evidence_module", return_value=self.startup):
            return gates.verify_current_source(record or self.record, kind, self.fixture.binding, self.fixture.staging, authorized)

    def blocked(self, record=None, kind="gpu", authorized=True):
        with self.assertRaises((ValueError, OSError, TypeError, KeyError)):
            self.verify(record, kind, authorized)

    def test_complete_scoped_acceptance_keeps_ocr_not_run_and_public_paths_private(self):
        result = self.verify()
        self.assertEqual(result["status"], "ACCEPTED_WITH_LIMITATIONS")
        self.assertEqual(result["gpu_ocr_e2e"], "NOT_RUN")
        self.assertEqual(result["gpu_worker_startup"]["status"], "PASS")
        self.assertTrue(gates.verified_startup_exception(result))
        self.assertNotIn(str(self.fixture.root), json.dumps(result, ensure_ascii=False))
        self.assertTrue(all(value == "NOT_RUN" for value in result["manual_checks"].values()))

    def test_scope_cannot_apply_to_base_cpu_unknown_or_default_full(self):
        self.blocked(kind="base")
        self.blocked(kind="cpu")
        for scope in (None, "full", "anything-else"):
            record = copy.deepcopy(self.record)
            if scope is None:
                record.pop("validation_scope")
            else:
                record["validation_scope"] = scope
            self.blocked(record)

    def test_current_publication_authorization_is_not_inferred_from_startup_pass(self):
        self.blocked(authorized=False)
        for field in ("program_review_approved", "release_notes_approved", "publish_with_untested_ocr", "record", "release_notes", "evidence_binding", "binding", "release_version"):
            record = copy.deepcopy(self.record)
            record["user_acceptance"].pop(field)
            self.blocked(record)

    def test_old_hdr_approval_or_old_program_note_context_cannot_authorize_hotfix(self):
        original = self.acceptance_path.read_bytes()
        self.write(self.acceptance_path, "HDR捕获成功，3.0.3可以发布。")
        record = copy.deepcopy(self.record)
        record["user_acceptance"]["record"] = self.fixture.ref(self.acceptance_path)
        self.blocked(record)
        self.write(self.acceptance_path, original)
        for field, value in (("release_version", "3.0.3"), ("limitations_disclosure_quote", "HDR捕获成功"),
                             ("release_notes_quote", "我没有审查文案"), ("program_review_approved", 1)):
            record = copy.deepcopy(self.record)
            record["user_acceptance"][field] = value
            self.blocked(record)

    def test_negative_review_or_publication_quotes_cannot_become_boolean_approval(self):
        original = self.acceptance_path.read_text("utf-8")
        for field, quote in (("program_review_quote", "我不同意本轮程序。"), ("release_notes_quote", "I do not approve these release notes."),
                             ("publication_quote", "现在不能发布 3.0.4。")):
            record = copy.deepcopy(self.record)
            old_quote = record["user_acceptance"][field]
            record["user_acceptance"][field] = quote
            self.write(self.acceptance_path, original.replace(old_quote, quote))
            record["user_acceptance"]["record"] = self.fixture.ref(self.acceptance_path)
            self.blocked(record)
        self.write(self.acceptance_path, original)

    def test_ocr_must_remain_explicit_not_run_not_pass_block_or_other_token(self):
        for value in ("PASS", "BLOCK", "NOT_INCLUDED", None, False):
            record = copy.deepcopy(self.record)
            record["gpu_ocr_e2e"] = value
            self.blocked(record)
        record = copy.deepcopy(self.record)
        record["status"] = "PASS"
        self.blocked(record)
        record = copy.deepcopy(self.record)
        record["manual_checks"]["manual_hdr_acceptance"] = "PASS"
        self.blocked(record)

    def test_only_scoped_unit_evidence_is_accepted_and_must_include_normal_and_optimized_runs(self):
        record = copy.deepcopy(self.record)
        record["automated_evidence"]["base_tests"] = record["automated_evidence"]["startup_unit_tests"]
        self.blocked(record)
        units = json.loads(self.units.read_text("utf-8"))
        units["runs"] = units["runs"][:1]
        self.write(self.units, units)
        record = copy.deepcopy(self.record)
        record["automated_evidence"]["startup_unit_tests"] = self.fixture.ref(self.units)
        self.blocked(record)

    def test_no_public_current_source_is_always_block_even_with_valid_startup_acceptance(self):
        receipt = {"schema_version": 1, "artifact_kind": "gpu", "release_version": "3.0.4", "publication_authorized": True,
                   "source_delivery": {"status": "PASS", "repositories": [{"role": "cuda", "url": gates.PUBLIC_REPOSITORIES["cuda"],
                       "tag": "v3.0.4", "commit": "a" * 40, "checkout": str(self.fixture.root)}]}, "current_source_e2e": self.record}
        path = self.fixture.audit / "gates.json"
        self.write(path, receipt)
        with self.fixture.patches(), patch.object(gates, "startup_evidence_module", return_value=self.startup), patch.object(gates, "public_tag", side_effect=ValueError("Current public v3.0.4 source unavailable")):
            result = gates.validate_release_gates(path, self.fixture.staging, "gpu")
        self.assertEqual(result["source_delivery"]["status"], "BLOCK")
        self.assertEqual(result["current_source_e2e"]["status"], "ACCEPTED_WITH_LIMITATIONS")
        component_gates = {"source_delivery": result["source_delivery"], "current_source_e2e": result["current_source_e2e"],
                           "gpu_worker_startup": result["current_source_e2e"]["gpu_worker_startup"],
                           "gpu_ocr_e2e": {"status": "NOT_RUN", "validation_scope": gates.STARTUP_SCOPE}}
        self.assertFalse(verifier.public_release_allowed(component_gates))


if __name__ == "__main__":
    unittest.main(verbosity=2)
