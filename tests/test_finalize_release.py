"""Offline, miniature freeze/finalize tests; never build or accept real products.

Synthetic evidence exists only under TemporaryDirectory. Public Git checks and
heavy license/runtime checks are substituted in positive unit cases; the real
publication-input validator, source/overlay checks, and tar.xz writer still run.
Negative CLI coverage also executes the unmodified real audit/verifier offline.
All assertions use unittest methods and remain active with Python -O.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
import copy
import importlib.util
import io
import json
import marshal
import zipfile
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


finalizer = load("finalize_fixture", ROOT / "build/tools/finalize_release.py")
verifier = load("finalize_verifier_fixture", ROOT / "build/tools/verify_release_evidence.py")
cuda = load("finalize_cuda_fixtures", ROOT / "tests/test_cuda_overlay.py")
exporter = load("finalize_export_fixture", ROOT / "build/tools/export_cuda_source.py")


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else
                     (value.encode("utf-8") if isinstance(value, str) else cuda.encoded(value)))


def file_bytes(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


class FinalizeFixtures(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="umi-finalize-test-", dir=ROOT / "build")
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name) / "repo"
        for relative in ("build/staging", "build/artifacts", "build/audit", "release"):
            (self.repo / relative).mkdir(parents=True, exist_ok=True)
        self.version = "3.0.3"
        self.about = {"version": {"major": 3, "minor": 0, "patch": 3, "prerelease": "", "prereleaseNumber": 0}}
        write(self.repo / "UmiOCR-data/about.json", self.about)
        write(self.repo / "build/sources-windows-cu126.lock.json", {})
        trusted = (
            "build/windows/Finalize-Release.ps1", "build/windows/Audit-Package.ps1",
            "build/tools/finalize_release.py", "build/tools/release_gate_inputs.py",
            "build/tools/verify_release_evidence.py", "build/tools/package_tar_xz.py",
            "build/tools/prepare_cuda_overlay.py", "build/tools/verify_public_payload.py",
        )
        for name in trusted:
            target = self.repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        self.counter = 0
        self.commands = []

    def base(self, name="base", application_sources=None):
        root = self.repo / "build/staging" / name
        write(root / "Umi-OCR.exe", b"UNIT TEST FIXTURE, not an executable\n")
        write(root / "UmiOCR-data/about.json", self.about)
        write(root / "UmiOCR-data/main.py", "# synthetic host payload\n")
        (root / "UmiOCR-data/site-packages").mkdir()
        for record in ("COPYING", "LICENSE", "SOURCE-CODE.md"):
            write(root / record, "UNIT TEST FIXTURE noncandidate source record\n")
        write(root / "VERSION", self.version + "\n")
        write(root / "LICENSES/Apache-2.0.txt", "UNIT TEST FIXTURE license\n")
        write(root / "LICENSES/THIRD_PARTY_NOTICES.md", "UNIT TEST FIXTURE static notices\n")
        source = {
            "UmiOCR-data/about.json": (root / "UmiOCR-data/about.json").read_bytes(),
            "UmiOCR-data/main.py": (root / "UmiOCR-data/main.py").read_bytes(),
            "build/build.py": b"# synthetic build input\n",
            "LICENSES/Apache-2.0.txt": b"UNIT TEST FIXTURE canonical license\n",
        }
        for relative, data in (application_sources or {}).items():
            target = root / "UmiOCR-data" / relative
            write(target, data)
            source["UmiOCR-data/" + relative] = target.read_bytes()
        for relative, data in source.items():
            write(root / "source" / relative, data)
        cuda.write_snapshot(root, {"host/" + name: data for name, data in source.items()}, self.version)
        self.blocked_report(root)
        return root

    def pack_app(self, root):
        # Construct the existing merge_runtime representation without importing
        # or executing application code, then remove only this fixture's loose
        # Python copies. Canonical source/snapshot are never changed here.
        from importlib import _bootstrap_external as bytecode
        directory = root / "UmiOCR-data/py_src"
        paths = sorted(directory.rglob("*.py"))
        with zipfile.ZipFile(root / "UmiOCR-data/app.zip", "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("py_src/", b"")
            for path in paths:
                name, data = path.relative_to(directory).as_posix(), path.read_bytes()
                code = compile(data, name, "exec", dont_inherit=True, optimize=0)
                archive.writestr("py_src/" + name, data)
                archive.writestr("py_src/" + name[:-3] + ".pyc", bytecode._code_to_hash_pyc(code, importlib.util.source_hash(data), checked=True))
        for path in paths:
            path.unlink()

    def gpu(self, name="gpu"):
        staging = cuda.make_gpu(self.repo / "build/staging" / name, loose_source=True)
        write(staging / "LICENSES/Apache-2.0.txt", "UNIT TEST FIXTURE license\n")
        workflow = b"# synthetic source-bound GPU workflow fixture\n"
        write(staging / "source/tests/test_ocr_workflows.py", workflow)
        cuda.change_archive(staging, lambda members: members.update({"host/tests/test_ocr_workflows.py": workflow}))
        plugin = staging / cuda.PLUGIN
        (plugin / "vendor").mkdir()
        write(plugin / "runtime.lock.json", {"files": []})
        raw = self.repo / "build/audit" / (name + "-workflow.log")
        write(raw, "OCR workflow tests passed: SYNTHETIC UNIT TEST FIXTURE ONLY\n")
        record = {
            "fixture_only": True, "test_type": "real_gpu_ocr_workflows_e2e", "status": "PASS", "device": "gpu:0",
            "plugin_runtime_lock_sha256": finalizer.gates.digest(plugin / "runtime.lock.json"),
            "plugin_source_sha256": {"api.py": finalizer.gates.digest(plugin / "api.py")},
            "workflow_test": {"SHA256": cuda.sha(workflow)},
            "workflow_log": {"file": raw.name, "SHA256": finalizer.gates.digest(raw)},
        }
        write(plugin / "gpu-e2e-evidence.json", record)
        self.blocked_report(staging)
        output = self.repo / "build/artifacts" / (name + "-overlay")
        finalizer.overlay.prepare(staging, output)
        return output, staging

    def blocked_report(self, metadata):
        write(metadata / "LICENSES/RELEASE_EVIDENCE.json", {
            "fixture_only": True, "local_candidate": True, "public_prerelease_allowed": False,
            "gates": {"source_delivery": "BLOCK", "current_source_e2e": "BLOCK"},
        })
        write(metadata / "LICENSES/RELEASE_EVIDENCE.md", "UNIT TEST FIXTURE: source/current BLOCK\n")

    def receipt(self, root, kind):
        self.counter += 1
        raw = self.repo / "build/audit" / f"evidence-{self.counter}"
        _, binding, _ = finalizer.gates.artifact_inputs(root, kind)
        evidence = {}
        for name, value in (
            ("base_tests", "Base regression suite passed. SYNTHETIC UNIT TEST FIXTURE ONLY\n"),
            ("combined_tests", "Combined regression suite passed. SYNTHETIC UNIT TEST FIXTURE ONLY\n"),
            ("gui", {"hot": True, "errors": [], "fixture_only": True}),
            ("tray", {"status": "PASS", "exit_code": 0, "http_ready_before_quit": True, "fixture_only": True}),
        ):
            path = raw / name
            write(path, value)
            evidence[name] = {"path": str(path), "sha256": finalizer.gates.digest(path)}
        manual = {}
        for name in finalizer.gates.MANUAL_CHECKS:
            path = raw / (name + ".json")
            write(path, {"status": "PASS", "check": name, "binding": binding, "fixture_only": True})
            manual[name] = {"path": str(path), "sha256": finalizer.gates.digest(path)}
        if kind == "gpu":
            plugin = root / cuda.PLUGIN
            record = plugin / "gpu-e2e-evidence.json"
            log = self.repo / "build/audit" / json.loads(record.read_bytes())["workflow_log"]["file"]
            evidence.update({
                "gpu_workflows": {"path": str(record), "sha256": finalizer.gates.digest(record)},
                "gpu_workflow_log": {"path": str(log), "sha256": finalizer.gates.digest(log)},
            })
        role = "host" if kind == "base" else "cuda"
        document = {
            "fixture_only": True, "schema_version": 1, "artifact_kind": kind,
            "release_version": self.version, "publication_authorized": True,
            "source_delivery": {"status": "PASS", "repositories": [{
                "role": role, "url": finalizer.gates.PUBLIC_REPOSITORIES[role],
                "tag": "v" + self.version, "commit": "a" * 40, "checkout": str(self.repo),
            }]},
            "current_source_e2e": {
                "status": "PASS", "binding": binding, "automated_evidence": evidence,
                "manual_checks": {name: "PASS" for name in finalizer.gates.MANUAL_CHECKS},
                "manual_evidence": manual, "unverified_scenarios": [],
            },
        }
        path = self.repo / "build/audit" / f"receipt-{self.counter}.json"
        write(path, document)
        return path

    def freeze(self, root, kind="base"):
        self.counter += 1
        path = self.repo / "build/audit" / f"frozen-{self.counter}.json"
        finalizer.freeze(self.repo, root, kind, path)
        return path

    @contextmanager
    def permitted_commands(self, root, kind="base", *, hook=None):
        """Real release-input validation, synthetic heavyweight checks, no network."""
        self.commands = []
        def execute(command, repo, environment):
            self.commands.append(command)
            self.assertEqual(repo, self.repo)
            self.assertEqual(environment["PATH"].split(os.pathsep)[0], str(Path(sys.executable).parent))
            receipt = command[command.index("-ReleaseGates" if len(self.commands) == 1 else "--release-gates") + 1]
            report = verifier.verify(root, self.repo, kind, None, release_gates=Path(receipt))
            if not report["public_prerelease_allowed"]:
                raise finalizer.FinalizationError("Synthetic fixture required verifier gate was BLOCK")
            if hook is not None:
                hook(len(self.commands))
        with ExitStack() as stack:
            stack.enter_context(patch.object(finalizer, "checked_command", side_effect=execute))
            stack.enter_context(patch.object(verifier.release_gate_inputs, "public_tag", return_value={"refs/tags/v3.0.3": "a" * 40}))
            stack.enter_context(patch.object(verifier.release_gate_inputs, "git_source_matches"))
            stack.enter_context(patch.object(verifier, "ensure_apache_license", return_value="LICENSES/Apache-2.0.txt"))
            for name in ("verify_runtime_vendor", "verify_models", "verify_nvidia", "verify_cudnn", "verify_opencv", "verify_mpl", "verify_agpl", "verify_gpu_e2e"):
                stack.enter_context(patch.object(verifier, name, return_value={"status": "PASS"}))
            stack.enter_context(patch.object(verifier, "verify_ffmpeg", return_value={"status": "NOT_INCLUDED"}))
            stack.enter_context(patch.object(verifier, "verify_cpu_and_document", return_value={
                "cpu_ocr": {"status": "NOT_INCLUDED"}, "document_models": {"status": "NOT_INCLUDED"},
            }))
            yield

    def finalize(self, root, kind, frozen, receipt, output=None):
        return finalizer.finalize(self.repo, root, kind, frozen, receipt, output or self.repo / "release")

    def no_archive(self):
        self.assertEqual(list((self.repo / "release").glob("*.tar.xz*")), [])

    def rejected(self, root, kind, frozen, receipt, *, pattern=".+", output=None):
        with self.assertRaisesRegex((RuntimeError, OSError, ValueError), pattern):
            self.finalize(root, kind, frozen, receipt, output)
        self.no_archive()

    def junction(self, link, target):
        if os.name != "nt":
            link.symlink_to(target, target_is_directory=True)
        else:
            result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class FreezeFinalizeTests(FinalizeFixtures):
    def test_pre_freeze_main_mismatch_is_rejected_even_with_fresh_independent_receipts(self):
        root = self.base()
        write(root / "UmiOCR-data/main.py", "# payload changed before review\n")
        receipt = self.receipt(root, "base")
        # Demonstrate the original gap: existing source/current gate inputs can
        # validate two independent digests without bridging the execution text.
        with self.permitted_commands(root):
            report = verifier.verify(root, self.repo, "base", None, release_gates=receipt)
        self.assertTrue(report["public_prerelease_allowed"])
        with self.assertRaisesRegex(finalizer.FinalizationError, "Execution source differs"):
            self.freeze(root)
        self.no_archive()

    def test_pre_freeze_loose_host_sources_cannot_differ_be_added_or_disappear(self):
        for mutation in ("changed", "extra", "missing", "qml"):
            with self.subTest(mutation=mutation):
                root = self.base(mutation, {"py_src/run.py": b"VALUE = 3\n", "qt_res/qml/Main.qml": b"Item {}\n"})
                if mutation == "changed":
                    write(root / "UmiOCR-data/py_src/run.py", b"VALUE = 4\n")
                elif mutation == "extra":
                    write(root / "UmiOCR-data/py_src/extra.py", b"EXTRA = True\n")
                elif mutation == "missing":
                    (root / "UmiOCR-data/py_src/run.py").unlink()
                else:
                    write(root / "UmiOCR-data/qt_res/qml/Main.qml", b"Item { visible: false }\n")
                with self.assertRaisesRegex(finalizer.FinalizationError, "Execution.*source"):
                    self.freeze(root)
        self.no_archive()

    def test_legal_app_zip_original_text_and_checked_bytecode_pass_without_execution(self):
        root = self.base(application_sources={
            "py_src/run.py": b"raise RuntimeError('application source must never execute in this check')\n",
            "py_src/imports/helper.py": b"assert __debug__\nVALUE = 3\n",
        })
        canonical = file_bytes(root / "source")
        self.pack_app(root)
        frozen, receipt = self.freeze(root), self.receipt(root, "base")
        with self.permitted_commands(root):
            result = self.finalize(root, "base", frozen, receipt)
        self.assertEqual(result["sha256"], finalizer.gates.digest(Path(result["archive"])))
        self.assertEqual(file_bytes(root / "source"), canonical)
        self.assertFalse((root / "UmiOCR-data/py_src/run.py").exists())

    def test_app_zip_source_bytecode_and_member_mismatches_are_rejected_before_freeze(self):
        for mutation in ("source", "bytecode", "orphan", "missing", "extra", "escape", "case"):
            with self.subTest(mutation=mutation):
                root = self.base(mutation, {"py_src/run.py": b"VALUE = 3\n"})
                self.pack_app(root)
                path = root / "UmiOCR-data/app.zip"
                with zipfile.ZipFile(path) as archive:
                    members = {name: archive.read(name) for name in archive.namelist()}
                if mutation == "source":
                    members["py_src/run.py"] += b"# different source\n"
                elif mutation == "bytecode":
                    # Preserve a genuine canonical-source hash header and forge
                    # only executable code. Header-only checking must not pass.
                    code = compile(b"EVIL = True\n", "run.py", "exec", dont_inherit=True, optimize=0)
                    members["py_src/run.pyc"] = members["py_src/run.pyc"][:16] + marshal.dumps(code)
                elif mutation == "orphan":
                    members.pop("py_src/run.py")
                elif mutation == "missing":
                    members.pop("py_src/run.py")
                    members.pop("py_src/run.pyc")
                elif mutation == "extra":
                    members["py_src/unpublished.py"] = b"# unexpected module\n"
                elif mutation == "escape":
                    members["../outside.py"] = b"# path traversal\n"
                else:
                    members["PY_SRC/run.py"] = members["py_src/run.py"]
                with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
                    for name, data in members.items():
                        archive.writestr(name, data)
                with self.assertRaises((RuntimeError, ValueError)):
                    self.freeze(root)
                self.no_archive()

    def test_pre_freeze_cuda_adapter_mismatch_cannot_hide_behind_fresh_e2e_hashes(self):
        root, _ = self.gpu()
        plugin = root / cuda.PLUGIN
        write(plugin / "api.py", b"# different tested adapter, not canonical source\n")
        record_path = plugin / "gpu-e2e-evidence.json"
        record = json.loads(record_path.read_bytes())
        record["plugin_source_sha256"]["api.py"] = finalizer.gates.digest(plugin / "api.py")
        write(record_path, record)
        receipt = self.receipt(root, "gpu")
        with self.permitted_commands(root, "gpu"):
            report = verifier.verify(root, self.repo, "gpu", None, release_gates=receipt)
        self.assertTrue(report["public_prerelease_allowed"])
        with self.assertRaisesRegex(finalizer.FinalizationError, "Execution source differs"):
            self.freeze(root, "gpu")
        self.no_archive()

    def test_cleanup_permission_denial_after_publication_is_success_with_visible_warning(self):
        root = self.base()
        frozen, receipt = self.freeze(root), self.receipt(root, "base")
        cleanup_calls = []
        real_rmtree = shutil.rmtree
        def denied_workspace(path, *args, **kwargs):
            candidate = Path(path)
            if candidate.parent == self.repo / "build/artifacts" and candidate.name.startswith("finalize-"):
                cleanup_calls.append(candidate)
                raise PermissionError("synthetic reader denies deleting the published tar hard link")
            return real_rmtree(path, *args, **kwargs)
        stdout, stderr = io.StringIO(), io.StringIO()
        with self.permitted_commands(root), patch.object(finalizer.shutil, "rmtree", side_effect=denied_workspace), redirect_stdout(stdout), redirect_stderr(stderr):
            status = finalizer.main([
                "finalize", "--repo-root", str(self.repo), "--package-root", str(root), "--kind", "base",
                "--frozen-manifest", str(frozen), "--release-gates", str(receipt),
            ])
        self.assertEqual(status, 0)
        result = json.loads(stdout.getvalue())
        archive = Path(result["archive"])
        self.assertTrue(archive.is_file())
        self.assertEqual(result["sha256"], finalizer.gates.digest(archive))
        self.assertEqual(json.loads(Path(str(archive) + ".integrity.json").read_bytes())["sha256"], result["sha256"])
        self.assertEqual(len(cleanup_calls), 1)
        self.assertEqual(result["cleanup_warning"]["workspace"], str(cleanup_calls[0]))
        self.assertTrue(cleanup_calls[0].is_dir())
        self.assertIn("WARNING: verified archive published successfully", stderr.getvalue())
        self.assertIn("No automatic retry", stderr.getvalue())

    def test_cleanup_permission_denial_before_publication_stays_failed_without_archive(self):
        root = self.base()
        frozen, receipt = self.freeze(root), self.receipt(root, "base")
        cleanup_calls = []
        real_rmtree = shutil.rmtree
        def denied_workspace(path, *args, **kwargs):
            candidate = Path(path)
            if candidate.parent == self.repo / "build/artifacts" and candidate.name.startswith("finalize-"):
                cleanup_calls.append(candidate)
                raise PermissionError("synthetic unpublished-workspace permission denial")
            return real_rmtree(path, *args, **kwargs)
        stdout, stderr = io.StringIO(), io.StringIO()
        with self.permitted_commands(root), patch.object(finalizer.packaging, "create_archive", side_effect=finalizer.packaging.ArchiveError("synthetic pre-publication compressor failure")), patch.object(finalizer.shutil, "rmtree", side_effect=denied_workspace), redirect_stdout(stdout), redirect_stderr(stderr):
            status = finalizer.main([
                "finalize", "--repo-root", str(self.repo), "--package-root", str(root), "--kind", "base",
                "--frozen-manifest", str(frozen), "--release-gates", str(receipt),
            ])
        self.assertEqual(status, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("finalization failed before publication", stderr.getvalue())
        self.assertIn("pre-publication compressor failure", stderr.getvalue())
        self.assertEqual(len(cleanup_calls), 1)
        self.assertTrue(cleanup_calls[0].is_dir())
        self.no_archive()

    def test_path_guard_test_is_an_exact_required_cuda_source_member(self):
        selected = exporter.selected_sources(ROOT)
        name = Path("tests/test_finalize_path_guards.py")
        self.assertIn(name, selected)
        with patch.object(exporter, "files_for_repo", return_value=[path for path in selected if path != name]):
            with self.assertRaisesRegex(RuntimeError, "test_finalize_path_guards"):
                exporter.selected_sources(ROOT)
        nested = Path("tests/non-public/test_finalize_path_guards.py")
        with patch.object(exporter, "files_for_repo", return_value=selected + [nested]):
            self.assertNotIn(nested, exporter.selected_sources(ROOT))

    def test_freeze_is_not_approval_and_preserves_honest_preparation_blocks(self):
        root = self.base()
        before = file_bytes(root)
        with patch.object(finalizer, "checked_command", side_effect=RuntimeError("must not execute")):
            frozen = self.freeze(root)
        record = json.loads(frozen.read_bytes())
        self.assertEqual(record["purpose"], "immutable-review-product-not-approval")
        self.assertNotIn("publication_authorized", record)
        self.assertEqual(file_bytes(root), before)
        self.assertTrue(json.loads((root / "LICENSES/RELEASE_EVIDENCE.json").read_bytes())["local_candidate"])
        self.no_archive()
        with self.assertRaisesRegex(finalizer.FinalizationError, "overwrite"):
            finalizer.freeze(self.repo, root, "base", frozen)

    def test_base_positive_uses_same_bytes_real_gate_validator_and_real_tar_xz(self):
        root = self.base()
        before = file_bytes(root / "source")
        records = {name: (root / name).read_bytes() for name in finalizer.SOURCE_RECORDS}
        frozen, receipt = self.freeze(root), self.receipt(root, "base")
        with self.permitted_commands(root):
            result = self.finalize(root, "base", frozen, receipt)
        archive = Path(result["archive"])
        self.assertEqual(archive.name, "Umi-OCR_v3.0.3_Windows_x64.tar.xz")
        self.assertTrue(archive.read_bytes().startswith(b"\xfd7zXZ\x00"))
        self.assertEqual(file_bytes(root / "source"), before)
        for name, data in records.items():
            self.assertEqual((root / name).read_bytes(), data)
        current = finalizer.inspect_product(self.repo, root, "base")
        finalizer.archive_matches(archive, current[3], current[4])
        self.assertEqual(json.loads(frozen.read_bytes()), current[2])
        self.assertEqual(result["sha256"], finalizer.gates.digest(archive))
        self.assertEqual(result["release_gate_input_sha256"], finalizer.gates.digest(receipt))
        self.assertEqual(len(self.commands), 2)
        self.assertIn("-RequirePublicRelease", self.commands[0])
        self.assertIn("-ReleaseGates", self.commands[0])
        self.assertIn("--require-public-release", self.commands[1])
        self.assertIn("--release-gates", self.commands[1])
        self.assertEqual(self.commands[1][self.commands[1].index("--kind") + 1], "base")
        self.assertEqual(self.commands[1][self.commands[1].index("--staging-root") + 1], str(root))

    def test_gpu_positive_binds_overlay_not_standalone_and_retains_nested_records(self):
        root, standalone = self.gpu()
        metadata = root / "LICENSES/plugins" / finalizer.gates.PLUGIN_ID
        before = file_bytes(metadata / "source")
        self.assertNotEqual(finalizer.gates.artifact_inputs(root, "gpu")[1], finalizer.gates.artifact_inputs(standalone, "gpu")[1])
        frozen, receipt = self.freeze(root, "gpu"), self.receipt(root, "gpu")
        with self.permitted_commands(root, "gpu"):
            result = self.finalize(root, "gpu", frozen, receipt)
        self.assertIn("CUDA12.6.tar.xz", result["archive"])
        self.assertEqual(file_bytes(metadata / "source"), before)
        self.assertFalse((root / "source").exists())
        self.assertFalse((root / "LICENSES/RELEASE_EVIDENCE.json").exists())
        self.assertTrue((metadata / "LICENSES/RELEASE_EVIDENCE.json").is_file())
        self.assertEqual(self.commands[0][self.commands[0].index("-PackageRoot") + 1], str(root))
        self.assertEqual(self.commands[1][self.commands[1].index("--kind") + 1], "gpu")
        current = finalizer.inspect_product(self.repo, root, "gpu")
        finalizer.archive_matches(Path(result["archive"]), current[3], current[4])

    def test_missing_receipt_and_wrong_identity_authorization_or_binding_never_archive(self):
        root = self.base()
        frozen = self.freeze(root)
        receipt = self.receipt(root, "base")
        original = json.loads(receipt.read_bytes())
        with patch.object(finalizer, "checked_command") as execute:
            self.rejected(root, "base", frozen, self.repo / "build/audit/missing.json")
            for field, value in (("schema_version", True), ("artifact_kind", "gpu"),
                                 ("release_version", "3.0.2"), ("publication_authorized", 1)):
                with self.subTest(field=field):
                    document = copy.deepcopy(original)
                    document[field] = value
                    write(receipt, document)
                    self.rejected(root, "base", frozen, receipt, pattern="identity/authorization/product binding")
            document = copy.deepcopy(original)
            document["current_source_e2e"]["binding"]["payload"]["sha256"] = "0" * 64
            write(receipt, document)
            self.rejected(root, "base", frozen, receipt, pattern="binding")
            write(receipt, '{"schema_version":1,"schema_version":1}')
            self.rejected(root, "base", frozen, receipt, pattern="duplicate")
            execute.assert_not_called()

    def test_actual_source_or_current_gate_block_and_missing_manual_evidence_are_not_bypassed(self):
        root = self.base()
        frozen, receipt = self.freeze(root), self.receipt(root, "base")
        original = json.loads(receipt.read_bytes())
        for mutation in ("source", "current", "manual", "automated"):
            with self.subTest(mutation=mutation):
                document = copy.deepcopy(original)
                if mutation == "source":
                    document["source_delivery"]["status"] = "BLOCK"
                elif mutation == "current":
                    document["current_source_e2e"]["status"] = "WAIVED"
                elif mutation == "manual":
                    document["current_source_e2e"].pop("manual_evidence")
                else:
                    document["current_source_e2e"]["automated_evidence"].pop("tray")
                write(receipt, document)
                with self.permitted_commands(root):
                    self.rejected(root, "base", frozen, receipt, pattern="gate was BLOCK")

    def test_payload_source_records_provenance_and_static_notices_cannot_change_after_review(self):
        changes = ("UmiOCR-data/main.py", "source/build/build.py", "source/LICENSES/Apache-2.0.txt",
                   "source-snapshot.zip", "source-snapshot.json", "source-provenance.json",
                   "LICENSES/THIRD_PARTY_NOTICES.md", "LICENSES/Apache-2.0.txt", "SOURCE-CODE.md")
        with patch.object(finalizer, "checked_command") as execute:
            for index, relative in enumerate(changes):
                with self.subTest(relative=relative):
                    root = self.base(str(index))
                    frozen, receipt = self.freeze(root), self.receipt(root, "base")
                    target = root / relative
                    target.write_bytes(target.read_bytes() + b"\nCHANGED AFTER REVIEW\n")
                    self.rejected(root, "base", frozen, receipt)
            execute.assert_not_called()

    def test_mutation_during_audit_is_rejected_before_archiver(self):
        for index, relative in enumerate(("source/build/build.py", "source-snapshot.zip", "UmiOCR-data/main.py")):
            with self.subTest(relative=relative):
                root = self.base(str(index))
                frozen, receipt = self.freeze(root), self.receipt(root, "base")
                def change(_step):
                    write(root / relative, b"changed by an audit fixture\n")
                with self.permitted_commands(root, hook=change), patch.object(finalizer.packaging, "create_archive") as package:
                    self.rejected(root, "base", frozen, receipt, pattern="changed during finalization")
                    package.assert_not_called()

    def test_mutating_receipt_or_freeze_file_during_audit_is_rejected(self):
        for name in ("receipt", "freeze"):
            root = self.base(name)
            frozen, receipt = self.freeze(root), self.receipt(root, "base")
            target = receipt if name == "receipt" else frozen
            def change(_step):
                target.write_bytes(target.read_bytes() + b"\n")
            with self.permitted_commands(root, hook=change):
                self.rejected(root, "base", frozen, receipt, pattern="inputs changed")

    def test_audit_or_final_verifier_failure_stops_before_packaging(self):
        root = self.base()
        frozen, receipt = self.freeze(root), self.receipt(root, "base")
        for effects in ([finalizer.FinalizationError("audit failed")], [None, finalizer.FinalizationError("verifier failed")]):
            with patch.object(finalizer, "checked_command", side_effect=effects), patch.object(finalizer.packaging, "create_archive") as package:
                self.rejected(root, "base", frozen, receipt, pattern="failed")
                package.assert_not_called()

    def test_zero_exit_without_fresh_report_cannot_reuse_historical_pass(self):
        root = self.base()
        frozen, receipt = self.freeze(root), self.receipt(root, "base")
        write(root / "LICENSES/RELEASE_EVIDENCE.json", {
            "artifact_kind": "base", "public_prerelease_allowed": True, "local_candidate": False,
            "validation_errors": [], "gates": {"source_delivery": "PASS", "current_source_e2e": "PASS"},
        })
        with patch.object(finalizer, "checked_command"), patch.object(finalizer.packaging, "create_archive") as package:
            self.rejected(root, "base", frozen, receipt, pattern="fresh verifier report")
            package.assert_not_called()

    def test_archiver_failure_never_leaves_formal_archive_or_integrity_report(self):
        root = self.base()
        frozen, receipt = self.freeze(root), self.receipt(root, "base")
        def fail(_root, output):
            write(output, b"partial workspace output, not a formal archive")
            raise finalizer.packaging.ArchiveError("synthetic compressor failure")
        with self.permitted_commands(root), patch.object(finalizer.packaging, "create_archive", side_effect=fail):
            self.rejected(root, "base", frozen, receipt, pattern="compressor failure")
        self.assertEqual(list((self.repo / "build/artifacts").glob("finalize-*")), [])

    def test_mutation_while_archiving_is_rejected(self):
        root = self.base()
        frozen, receipt = self.freeze(root), self.receipt(root, "base")
        create = finalizer.packaging.create_archive
        def mutate(package_root, output):
            result = create(package_root, output)
            write(root / "UmiOCR-data/main.py", b"changed after compression\n")
            return result
        with self.permitted_commands(root), patch.object(finalizer.packaging, "create_archive", side_effect=mutate):
            self.rejected(root, "base", frozen, receipt, pattern="changed during finalization")

    def test_archive_member_bytes_are_checked_even_if_product_was_restored(self):
        root = self.base()
        frozen, receipt = self.freeze(root), self.receipt(root, "base")
        create = finalizer.packaging.create_archive
        target = root / "UmiOCR-data/main.py"
        before = target.read_bytes()
        def tamper(package_root, output):
            target.write_bytes(b"temporary concurrent payload change\n")
            try:
                return create(package_root, output)
            finally:
                target.write_bytes(before)
        with self.permitted_commands(root), patch.object(finalizer.packaging, "create_archive", side_effect=tamper):
            self.rejected(root, "base", frozen, receipt, pattern="Archive bytes/member set")
        self.assertEqual(target.read_bytes(), before)

    def test_failed_atomic_publication_removes_only_its_new_integrity_sidecar(self):
        root = self.base()
        frozen, receipt = self.freeze(root), self.receipt(root, "base")
        link = os.link
        calls = []
        def fail_second(source, destination):
            calls.append(destination)
            if len(calls) == 2:
                raise PermissionError("synthetic archive publication denial")
            link(source, destination)
        with self.permitted_commands(root), patch.object(finalizer.os, "link", side_effect=fail_second):
            self.rejected(root, "base", frozen, receipt, pattern="publication denial")
        self.assertEqual(len(calls), 2)

    def test_existing_archive_or_sidecar_is_never_overwritten(self):
        root = self.base()
        frozen, receipt = self.freeze(root), self.receipt(root, "base")
        archive = self.repo / "release/Umi-OCR_v3.0.3_Windows_x64.tar.xz"
        for path in (archive, Path(str(archive) + ".integrity.json")):
            write(path, b"existing file, must survive\n")
            with patch.object(finalizer, "checked_command") as execute:
                with self.assertRaisesRegex(finalizer.FinalizationError, "overwrite"):
                    self.finalize(root, "base", frozen, receipt)
                execute.assert_not_called()
            self.assertEqual(path.read_bytes(), b"existing file, must survive\n")
            path.unlink()

    def test_local_candidate_missing_canonical_source_cannot_be_promoted_by_rename(self):
        root = self.base("renamed-to-formal")
        shutil.rmtree(root / "source")
        with self.assertRaisesRegex(finalizer.FinalizationError, "local candidates cannot be promoted"):
            self.freeze(root)
        self.no_archive()

    def test_wrong_product_type_standalone_gpu_or_renamed_frozen_root_is_rejected(self):
        root = self.base()
        with self.assertRaisesRegex(finalizer.FinalizationError, "Only"):
            self.freeze(root, "cpu")
        gpu, standalone = self.gpu()
        with self.assertRaisesRegex(finalizer.FinalizationError, "actual prepared install overlay"):
            self.freeze(standalone, "gpu")
        frozen, receipt = self.freeze(root), self.receipt(root, "base")
        renamed = root.with_name("renamed")
        root.rename(renamed)
        with patch.object(finalizer, "checked_command") as execute:
            self.rejected(renamed, "base", frozen, receipt, pattern="reviewed freeze manifest")
            execute.assert_not_called()
        self.assertTrue(gpu.is_dir())

    def test_gpu_standalone_binding_cannot_authorize_actual_overlay(self):
        root, standalone = self.gpu()
        frozen, receipt = self.freeze(root, "gpu"), self.receipt(root, "gpu")
        document = json.loads(receipt.read_bytes())
        document["current_source_e2e"]["binding"] = finalizer.gates.artifact_inputs(standalone, "gpu")[1]
        write(receipt, document)
        with patch.object(finalizer, "checked_command") as execute:
            self.rejected(root, "gpu", frozen, receipt, pattern="binding")
            execute.assert_not_called()

    def test_paths_private_state_and_empty_private_directories_fail_closed(self):
        root = self.base()
        frozen, receipt = self.freeze(root), self.receipt(root, "base")
        for output in (root / "nested", self.repo.parent / "outside", self.repo / "build/cache"):
            self.rejected(root, "base", frozen, receipt, output=output)
        with self.assertRaisesRegex(finalizer.FinalizationError, r"build[\\/]audit"):
            finalizer.freeze(self.repo, root, "base", self.repo / "outside.json")
        (root / "UmiOCR-data/logs").mkdir()
        with self.assertRaisesRegex(finalizer.FinalizationError, "Private/generated state"):
            self.freeze(root)
        self.no_archive()

    def test_hard_linked_derived_report_or_payload_is_rejected_before_audit_writes(self):
        for index, relative in enumerate(("LICENSES/RELEASE_EVIDENCE.json", "UmiOCR-data/main.py")):
            with self.subTest(relative=relative):
                root = self.base("hardlink-" + str(index))
                frozen, receipt = self.freeze(root), self.receipt(root, "base")
                outside = self.repo / "build/audit" / f"outside-{index}.json"
                write(outside, b"outside original bytes must not be overwritten\n")
                target = root / relative
                target.unlink()  # Only this test's own small fixture file.
                os.link(outside, target)
                self.assertGreater(target.stat().st_nlink, 1)
                with patch.object(finalizer, "checked_command") as execute:
                    self.rejected(root, "base", frozen, receipt, pattern="Hard-linked product files")
                    execute.assert_not_called()
                self.assertEqual(outside.read_bytes(), b"outside original bytes must not be overwritten\n")

    def test_input_descendant_and_output_ancestor_junctions_are_rejected(self):
        root = self.base()
        frozen, receipt = self.freeze(root), self.receipt(root, "base")
        unrelated = self.repo / "unrelated"
        unrelated.mkdir()
        write(unrelated / "keep.txt", b"untouched")
        alias = self.repo / "build/staging/alias"
        self.junction(alias, root)
        self.rejected(alias, "base", frozen, receipt, pattern="link or junction")
        # Even '..' must not hide a previously traversed junction.
        self.rejected(alias / ".." / root.name, "base", frozen, receipt, pattern="link or junction")
        output_alias = self.repo / "build/artifacts/output-alias"
        self.junction(output_alias, unrelated)
        self.rejected(root, "base", frozen, receipt, output=output_alias / "release", pattern="link or junction")
        self.junction(root / "UmiOCR-data/linked", unrelated)
        self.rejected(root, "base", frozen, receipt, pattern="link or junction")
        self.assertEqual((unrelated / "keep.txt").read_bytes(), b"untouched")

    def test_exact_cuda_corresponding_source_whitelist_contains_no_refresh_or_paid_expansion(self):
        selected = exporter.selected_sources(ROOT)
        paths = {path.as_posix() for path in selected}
        required = {"build/windows/Finalize-Release.ps1", "build/tools/finalize_release.py", "tests/test_finalize_release.py"}
        self.assertTrue(required <= paths)
        for name in ("build/tools/refresh_candidate_source.py", "tests/test_refresh_candidate_source.py"):
            self.assertNotIn(name, paths)
        self.assertFalse(any("win32_PaddleOCRv6_CPU/" in path or "win32_PaddleOCRVL" in path for path in paths))
        nested = {Path("build/tools/non-public/finalize_release.py"), Path("tests/non-public/test_finalize_release.py")}
        with patch.object(exporter, "files_for_repo", return_value=selected + list(nested)):
            self.assertFalse(nested & set(exporter.selected_sources(ROOT)))


class PowerShellEntryTests(FinalizeFixtures):
    def pwsh(self, script, *arguments):
        return subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-File", str(script), *map(str, arguments)],
                              cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)

    def test_real_freeze_entry_and_real_blocked_finalize_never_archive(self):
        root = self.base()
        frozen = self.repo / "build/audit/cli-frozen.json"
        script = self.repo / "build/windows/Finalize-Release.ps1"
        common = ("-PackageRoot", root, "-Kind", "base", "-PythonExe", sys.executable, "-FrozenManifest", frozen)
        before = file_bytes(root)
        result = self.pwsh(script, *common, "-Freeze")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(file_bytes(root), before)
        receipt = self.receipt(root, "base")
        document = json.loads(receipt.read_bytes())
        # No network: source_delivery BLOCK short-circuits public tag lookup.
        document["source_delivery"] = {"status": "BLOCK", "fixture_only": True}
        write(receipt, document)
        result = self.pwsh(script, *common, "-ReleaseGates", receipt)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("ParserError", result.stdout + result.stderr)
        self.assertIn("no formal archive", result.stdout + result.stderr)
        self.no_archive()
        self.assertEqual(file_bytes(root / "source"), {name.removeprefix("source/"): data for name, data in before.items() if name.startswith("source/")})
        for name in finalizer.SOURCE_RECORDS:
            self.assertEqual((root / name).read_bytes(), before[name])

    def test_conflicting_modes_and_missing_explicit_gate_are_parameter_errors(self):
        root = self.base()
        frozen, receipt = self.freeze(root), self.receipt(root, "base")
        script = self.repo / "build/windows/Finalize-Release.ps1"
        common = ("-PackageRoot", root, "-Kind", "base", "-PythonExe", sys.executable, "-FrozenManifest", frozen)
        for arguments in ((), ("-Freeze", "-ReleaseGates", receipt)):
            result = self.pwsh(script, *common, *arguments)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("ParserError", result.stdout + result.stderr)
        self.no_archive()

    def test_builders_reject_missing_invalid_or_conflicting_gate_without_building(self):
        for filename in ("Build-Release.ps1", "Build-GpuPlugin.ps1"):
            script = ROOT / "build/windows" / filename
            if not script.is_file():
                continue  # Independent CUDA export intentionally omits host builder.
            stage = self.repo / "build/staging" / filename
            stage.mkdir()
            marker = stage / "keep.bin"
            marker.write_bytes(b"unchanged, no real build")
            for extra, expected in (((), "explicit -ReleaseGates"),
                                    (("-LocalCandidate", "-ReleaseGates", "unused.json"), "mutually exclusive"),
                                    (("-ReleaseGates", self.repo / "build/audit/missing.json"), "existing JSON file")):
                result = self.pwsh(script, "-StagingRoot", stage, *extra)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stdout + result.stderr)
                self.assertNotIn("ParserError", result.stdout + result.stderr)
                self.assertEqual(marker.read_bytes(), b"unchanged, no real build")
        self.no_archive()

    def test_builders_accept_noncandidate_skiparchive_without_falsely_requiring_public_tag(self):
        for filename, seed_option in (("Build-Release.ps1", "-ReuseFromStagingRoot"),
                                      ("Build-GpuPlugin.ps1", "-ReuseVendorFromStagingRoot")):
            script = ROOT / "build/windows" / filename
            if not script.is_file():
                continue
            stage = self.repo / "build/staging" / (filename + "-new")
            result = self.pwsh(script, "-StagingRoot", stage, "-SkipArchive", "-Offline", "-ReuseDependencies",
                               seed_option, self.repo / "build/staging/missing-seed")
            self.assertNotEqual(result.returncode, 0)
            self.assertRegex(result.stdout + result.stderr, "Offline reuse input is missing|Offline GPU vendor seed is missing")
            self.assertNotIn("Formal archives require", result.stdout + result.stderr)
            self.assertFalse(stage.exists())
        self.no_archive()

    def test_real_builder_tail_routes_prepare_and_formal_paths_without_running_a_build(self):
        # Execute only parsed terminal statements from the real builders. Audit
        # and finalize are tiny recording stubs; GPU overlay creation is real.
        # Compilers, downloads, dependency installs, workers and old staging are
        # unreachable from the selected AST tail.
        for filename, mode in (("Build-Release.ps1", "prepare"), ("Build-Release.ps1", "formal"),
                               ("Build-GpuPlugin.ps1", "prepare"), ("Build-GpuPlugin.ps1", "overlay"),
                               ("Build-GpuPlugin.ps1", "formal")):
            actual = ROOT / "build/windows" / filename
            if not actual.is_file():
                continue
            with self.subTest(builder=filename, mode=mode):
                suffix = filename + "-" + mode
                if "Gpu" in filename:
                    root, _ = self.gpu(suffix)
                    # The builder tail receives independent GPU staging.
                    root = self.repo / "build/staging" / suffix
                else:
                    root = self.base(suffix)
                target = self.repo / "build/artifacts" / (suffix + "-selected-overlay")
                log = self.repo / "build/audit" / (suffix + "-calls.jsonl")
                receipt = self.repo / "build/audit" / (suffix + "-gates.json")
                write(receipt, {"fixture_only": True})
                def quote(value):
                    return "'" + str(value).replace("'", "''") + "'"
                audit_stub = r'''
param([string]$PackageRoot, [string]$Kind, [string]$CpuStagingRoot, [string]$ReleaseGates,
      [switch]$LocalCandidate, [switch]$RequirePublicRelease)
@{ entry='audit'; root=$PackageRoot; kind=$Kind; gates=$ReleaseGates; public=[bool]$RequirePublicRelease } |
    ConvertTo-Json -Compress | Add-Content -LiteralPath LOGPATH
exit 0
'''
                finalize_stub = r'''
param([string]$PackageRoot, [string]$Kind, [string]$PythonExe, [string]$FrozenManifest,
      [string]$ReleaseGates, [string]$OutputRoot, [switch]$Freeze)
@{ entry='finalize'; root=$PackageRoot; kind=$Kind; gates=$ReleaseGates; freeze=[bool]$Freeze; frozen=$FrozenManifest } |
    ConvertTo-Json -Compress | Add-Content -LiteralPath LOGPATH
exit 0
'''
                write(self.repo / "build/windows/Audit-Package.ps1", audit_stub.replace("LOGPATH", quote(log)))
                write(self.repo / "build/windows/Finalize-Release.ps1", finalize_stub.replace("LOGPATH", quote(log)))
                code = r'''
$ErrorActionPreference = 'Stop'
$RepoRoot = REPOROOT
$BuildRoot = Join-Path $RepoRoot 'build'
$StagingRoot = STAGEROOT
$OutputRoot = Join-Path $RepoRoot 'release'
$ReleaseGates = GATEPATH
$CpuStagingRoot = ''
$Version = '3.0.3'; $VersionLabel = $Version
$LocalCandidate = $false
$SkipArchive = SKIPARCHIVE
$basePython = PYTHONPATH; $python = $basePython
$OverlayRoot = INITIALOVERLAY
function Remove-BuildTree([string]$Path) { }
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile(BUILDERPATH,[ref]$tokens,[ref]$errors)
if ($errors) { throw 'Builder parse failure' }
if (ISGPU) {
    $expression = @($ast.EndBlock.Statements | Where-Object { $_.Extent.Text.StartsWith('$PrepareOverlay = ') })
    if ($expression.Count -ne 1) { throw 'Expected the real PrepareOverlay assignment' }
    . ([scriptblock]::Create($expression[0].Extent.Text))
    if (-not $OverlayRoot) { $OverlayRoot = TARGETOVERLAY }
    $marker = @($ast.EndBlock.Statements | Where-Object { $_.Extent.Text -eq '$previousPath = $env:PATH' })
}
else {
    $marker = @($ast.EndBlock.Statements | Where-Object { $_.Extent.Text -eq 'Remove-BuildTree (Join-Path $StagingRoot ".build")' })
}
if ($marker.Count -ne 1) { throw 'Expected a single terminal-build marker' }
$tail = ($ast.EndBlock.Statements | Where-Object { $_.Extent.StartOffset -ge $marker[0].Extent.StartOffset } |
         ForEach-Object { $_.Extent.Text }) -join "`n"
. ([scriptblock]::Create($tail))
'''
                values = {"REPOROOT": quote(self.repo), "STAGEROOT": quote(root), "GATEPATH": quote(receipt),
                          "SKIPARCHIVE": "$false" if mode == "formal" else "$true", "PYTHONPATH": quote(sys.executable),
                          "INITIALOVERLAY": quote(target) if mode == "overlay" else "''", "BUILDERPATH": quote(actual),
                          "ISGPU": "$true" if "Gpu" in filename else "$false", "TARGETOVERLAY": quote(target)}
                for key, value in values.items():
                    code = code.replace(key, value)
                runner = self.repo / "build/audit" / (suffix + "-tail.ps1")
                write(runner, code)
                result = self.pwsh(runner)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                calls = [json.loads(line) for line in log.read_text("utf-8-sig").splitlines()]
                finalized = [call for call in calls if call["entry"] == "finalize"]
                if mode == "formal":
                    self.assertEqual([call["freeze"] for call in finalized], [True, False])
                    self.assertEqual(finalized[-1]["gates"], str(receipt))
                    self.assertEqual(finalized[0]["frozen"], finalized[1]["frozen"])
                    self.assertEqual(finalized[-1]["root"], str(target if "Gpu" in filename else root))
                else:
                    self.assertEqual(finalized, [])
                    self.assertTrue(all(not call["public"] for call in calls))
                    self.assertEqual(calls[-1]["gates"], str(receipt))
                if "Gpu" in filename:
                    self.assertEqual(target.is_dir(), mode != "prepare")
                    if mode == "overlay":
                        self.assertEqual(calls[-1]["root"], str(target))
                self.no_archive()

    def test_modified_powershell_files_parse(self):
        script = r'''
$ErrorActionPreference = 'Stop'
foreach ($name in @('Build-Release.ps1', 'Build-GpuPlugin.ps1', 'Finalize-Release.ps1')) {
    $file = Join-Path $args[0] $name
    if (-not (Test-Path -LiteralPath $file)) { continue }
    $tokens = $null; $errors = $null
    [void][Management.Automation.Language.Parser]::ParseFile($file, [ref]$tokens, [ref]$errors)
    if ($errors) { throw (($errors | ForEach-Object { $_.Message }) -join '; ') }
}
'''
        script = script.replace("$args[0]", "'" + str(ROOT / "build/windows").replace("'", "''") + "'")
        result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
