"""Small offline fixtures only; never build products or start an OCR worker."""
from __future__ import annotations

import hashlib
import io
import json
import lzma
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "build/tools"))
import export_cuda_source as cuda
import package_tar_xz as packaging
import prepare_products as products
import source_snapshot as snapshot
sys.path.insert(0, str(REPO / "tests"))
import test_cuda_overlay as cuda_fixtures


class LocalBuildToolsTests(unittest.TestCase):
    def test_real_source_selection_includes_untracked_required_files(self):
        selected = {path.as_posix() for path in snapshot.files_for_repo(REPO, public=True)}
        for name in ("UmiOCR-data/runtime_archive_bootstrap.py",
                     "UmiOCR-data/py_src/plugins_controller/services.py",
                     "UmiOCR-data/py_src/server/http_utils.py", "UmiOCR-data/py_src/ocr/score.py",
                     "build/tools/prepare_products.py", "build/tools/package_tar_xz.py",
                     "build/tools/merge_runtime.py", "build/tools/runtime_archive_layout.py",
                     "build/tools/audit_runtime_archives.py",
                     "build/windows/runtime_archives_host.json", "build/windows/runtime_archives_cuda.json"):
            self.assertIn(name, selected)
        self.assertFalse(any("win32_PaddleOCRv6_CPU/" in name or "win32_PaddleOCRVL" in name for name in selected))
        self.assertFalse(any(name.startswith(("build/logs/", "build/artifacts/", "build/audit/", "$tmp/", "temp_doc/")) for name in selected))

    def test_source_boundary(self):
        for name in ("$tmp/private.py", "build/logs/private.json", "build/tmp/config.py",
                     "UmiOCR-data/runtime/python.exe", "UmiOCR-data/.settings/state.json",
                     "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/models/weights.json",
                     "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/vendor/paddle.py",
                     "UmiOCR-data/plugins/win32_PaddleOCRv6_CPU/api.py",
                     "benchmarks/results/private-machine.json", "benchmarks/README-local.md",
                     "docs/CLAUDE.md", "docs/nested/.CoDeX/settings.json",
                     "UmiOCR-data/py_src/.CLAUDE/session.py", "tests/AGENTS.md"):
            self.assertTrue(snapshot.is_excluded(Path(name), public=True), name)
        for name in ("LICENSES/GPL-3.0.txt", "LICENSES/PyMuPDF-AGPL-3.0.txt",
                     "benchmarks/benchmark_startup_isolated.py",
                     "third_party/pymupdf.tar.gz", "docs/PLUGIN_API.md"):
            self.assertFalse(snapshot.is_excluded(Path(name), public=True), name)

    def test_snapshot_and_source_mirror_small_fixture(self):
        with tempfile.TemporaryDirectory(prefix="umi-source-test-") as temp:
            repo = Path(temp)
            source = repo / "UmiOCR-data/py_src/new_service.py"
            source.parent.mkdir(parents=True)
            source.write_text("VALUE = 300\n", encoding="utf-8")
            (repo / "COPYING").write_text("fixture license\n", encoding="utf-8")
            paths = [source.relative_to(repo), Path("COPYING")]
            mirror = repo / "build/fresh-source"
            with patch.object(snapshot, "relative_entries", return_value=paths), patch.object(snapshot, "git_output", return_value="fixture-parent"):
                snapshot.mirror_sources(repo, mirror)
                manifest, provenance, boundaries = snapshot.collect_mirror(repo, mirror)
                output = repo / "build/fresh-snapshot"
                snapshot.write_snapshot(output, manifest, provenance, {"version": "3.0.0", "scope": "public", "boundaries": boundaries, "repositories": {"host": mirror}})
                with zipfile.ZipFile(output / "source-snapshot.zip") as archive:
                    self.assertIn("host/UmiOCR-data/py_src/new_service.py", archive.namelist())
                products.check_snapshot_version(output, "3.0.0")
                with self.assertRaises(RuntimeError):
                    snapshot.write_snapshot(output, manifest, provenance, {"version": "3.0.0"})

    def test_data_mirror_includes_external_runtime_bootstrap(self):
        work = REPO / "build/tmp/startup-small-files-20261028-r1/source-mirror-tests"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="data-mirror-", dir=work) as temp:
            repo = Path(temp)
            inputs = {
                "UmiOCR-data/main.py": b"from runtime_archive_bootstrap import prepare_archives\n",
                "UmiOCR-data/runtime_archive_bootstrap.py": b"def prepare_archives(*args, **kwargs): return []\n",
                "UmiOCR-data/py_src/run.py": b"VALUE = 1\n",
            }
            for name, content in inputs.items():
                path = repo / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            destination = repo / "build/fresh/UmiOCR-data"
            with patch.object(snapshot, "relative_entries", return_value=[Path(name) for name in inputs]):
                snapshot.mirror_sources(repo, destination, data_only=True)
            for name, content in inputs.items():
                self.assertEqual((destination / Path(name).relative_to("UmiOCR-data")).read_bytes(), content)

    def test_locked_sources_fail_offline_and_accept_exact_small_input(self):
        with tempfile.TemporaryDirectory(prefix="umi-lock-test-") as temp:
            root = Path(temp)
            (root / "build").mkdir()
            data = b"small corresponding-source fixture"
            asset = {"name": "source.tar.gz", "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
            lock = root / "build/sources-windows-cu126.lock.json"
            lock.write_text(json.dumps({"thirdPartySources": [asset]}), encoding="utf-8")
            cache = root / "build/cache/sources"
            with self.assertRaises(RuntimeError):
                snapshot.locked_sources(root, cache)
            cache.mkdir(parents=True)
            (cache / asset["name"]).write_bytes(data)
            self.assertEqual(len(snapshot.locked_sources(root, cache)), 1)
            asset["name"] = "../outside.tar.gz"
            lock.write_text(json.dumps({"thirdPartySources": [asset]}), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                snapshot.locked_sources(root, cache)

    def test_independent_base_has_no_plugin_payload(self):
        with tempfile.TemporaryDirectory(prefix="umi-products-test-") as temp:
            root = Path(temp)
            complete = root / "complete"
            plugin = complete / "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA"
            plugin.mkdir(parents=True)
            (plugin / "api.py").write_text("fixture\n", encoding="utf-8")
            (complete / "Umi-OCR.exe").write_bytes(b"not an executable")
            licenses = complete / "LICENSES/plugins/win32_PaddleOCRv6_CUDA"
            licenses.mkdir(parents=True)
            (licenses / "NOTICE.md").write_text("fixture notice\n", encoding="utf-8")
            private = (
                "UmiOCR-data/.settings", "UmiOCR-data/.pre_settings", "UmiOCR-data/themes.json",
                "UmiOCR-data/plugins/.plugins_state", "UmiOCR-data/logs/session.txt",
                "UmiOCR-data/temp/image.png", "UmiOCR-data/temp_doc/document.pdf",
                "UmiOCR-data/py_src/__PyCache__/cached.pyc", "UmiOCR-data/py_src/loose.pyc",
                ".build/compiler.log", "assembly.json", "prepared-products.json", "UmiOCR-data/startup_error.log",
            )
            for name in private:
                path = complete / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("private fixture", encoding="utf-8")
            target = root / "base"
            products.prepare_base(complete, target)
            for name in private:
                self.assertFalse((target / name).exists(), name)
                self.assertEqual((complete / name).read_text(encoding="utf-8"), "private fixture")
            self.assertFalse((target / ".build").exists())
            self.assertFalse((target / "UmiOCR-data/py_src/__PyCache__").exists())
            self.assertFalse((target / plugin.relative_to(complete)).exists())
            self.assertFalse((target / "LICENSES/plugins").exists())
            self.assertEqual(products.payload(target), products.payload(complete, exclude=products.base_excluded))
            self.assertTrue((target / "Umi-OCR.exe").is_file())
            self.assertTrue((plugin / "api.py").is_file())

    def test_path_components(self):
        for value in ("../paid", "C:drive", "cuda/escape", "bad\\path", ".", ".."):
            with self.assertRaises(products.PreparationError):
                products.safe_component(value)
        for value in ("../paid", "C:drive", ".", ".."):
            with self.assertRaises(packaging.ArchiveError):
                packaging._safe_relative(value)
        self.assertEqual(packaging._safe_relative("cuda/escape"), "cuda/escape")
        self.assertEqual(packaging._safe_relative("bad\\path"), "bad/path")
        self.assertEqual(products.safe_component("3.0.0-local-candidate"), "3.0.0-local-candidate")

    def test_products_cli_small_base_and_cuda(self):
        with tempfile.TemporaryDirectory(prefix="umi-cli-products-test-") as temp:
            repo = Path(temp)
            about = repo / "UmiOCR-data/about.json"
            about.parent.mkdir()
            about.write_text(json.dumps({"version": {"major": 3, "minor": 0, "patch": 0}}), encoding="utf-8")
            complete = repo / "build/complete"
            gpu = cuda_fixtures.make_gpu(repo / "gpu", version="3.0.4", host_version="3.0.0")
            plugin = complete / "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA"
            shutil.copytree(gpu / cuda_fixtures.PLUGIN, plugin)
            licenses = complete / "LICENSES/plugins/win32_PaddleOCRv6_CUDA"
            licenses.mkdir(parents=True)
            (licenses / "THIRD_PARTY_NOTICES.md").write_text("CUDA fixture notices", encoding="utf-8")
            (licenses / "RELEASE_EVIDENCE.json").write_text(json.dumps({"public_prerelease_allowed": False}), encoding="utf-8")
            (complete / "LICENSES/THIRD_PARTY_NOTICES.md").write_text("host fixture notices", encoding="utf-8")
            for name in ("COPYING", "LICENSE", "NOTICE.md", "SOURCE-CODE.md"):
                (complete / name).write_text(f"host fixture {name}\n", encoding="utf-8")
            (complete / "Umi-OCR.exe").write_bytes(b"not an executable")
            private = (
                "assembly.json", "prepared-products.json", "UmiOCR-data/.settings", "UmiOCR-data/themes.json",
                "UmiOCR-data/logs/session.txt", "UmiOCR-data/py_src/__pycache__/host.pyc",
                "UmiOCR-data/plugins/.plugins_state", "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/__pycache__/api.pyc",
                "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/loose.pyc",
            )
            for name in private:
                path = complete / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("private fixture", encoding="utf-8")
            source = repo / "small-public-source.py"
            source.write_text("VALUE = 300\n", encoding="utf-8")
            manifest = {"host/small-public-source.py": hashlib.sha256(source.read_bytes()).hexdigest()}
            snapshot.write_snapshot(complete, manifest, {"host": "fixture"}, {"version": "3.0.0", "scope": "public", "boundaries": ["fixture"], "repositories": {"host": repo}})
            cuda_fixtures.retain_records(gpu, complete / cuda_fixtures.module.SOURCE_NAMESPACE)
            output = repo / "build/products"
            args = ["--repo-root", str(repo), "--complete-root", str(complete), "--products-root", str(output)]
            result = subprocess.run([sys.executable, "-I", "-B", "-S", str(REPO / "build/tools/prepare_products.py"), *args],
                                    capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads((output / "prepared-products.json").read_text(encoding="utf-8"))
            self.assertEqual(set(report["products"]), {"base", "cuda"})
            self.assertFalse(report["public_release_allowed"])
            base = Path(report["products"]["base"]["path"])
            overlay = Path(report["products"]["cuda"]["path"])
            self.assertEqual(report["version"], "3.0.0")
            self.assertEqual(report["products"]["base"]["version"], "3.0.0")
            self.assertEqual(report["products"]["cuda"]["version"], "3.0.4")
            self.assertIn("_v3.0.4-local-candidate_", overlay.name)
            self.assertEqual((overlay / "LICENSES/plugins/win32_PaddleOCRv6_CUDA/VERSION").read_text("utf-8-sig").strip(), "3.0.4")
            self.assertFalse((base / "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA").exists())
            for name in private:
                self.assertFalse((base / name).exists(), name)
                self.assertEqual((complete / name).read_text(encoding="utf-8"), "private fixture")
            self.assertEqual(products.payload(base), products.payload(complete, exclude=products.base_excluded))
            self.assertEqual({path.name for path in overlay.iterdir()}, {"UmiOCR-data", "LICENSES"})
            overlay_plugin = overlay / plugin.relative_to(complete)
            self.assertEqual(products.payload(overlay_plugin), products.payload(plugin, exclude=products.cuda_overlay.private_path))
            records = overlay / "LICENSES/plugins/win32_PaddleOCRv6_CUDA"
            for name in ("COPYING", "LICENSE", "NOTICE.md", "VERSION", "SOURCE-CODE.md", "source-snapshot.zip", "source-snapshot.json", "source-provenance.json"):
                self.assertEqual((records / name).read_bytes(), (gpu / name).read_bytes(), name)
            self.assertNotEqual((records / "source-snapshot.zip").read_bytes(), (complete / "source-snapshot.zip").read_bytes())
            self.assertFalse((records / "LICENSES" / cuda_fixtures.module.SOURCE_RECORDS_DIR).exists())
            self.assertEqual(len(list(overlay.rglob("source-snapshot.zip"))), 1)
            self.assertEqual((records / "LICENSES/THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8"), "CUDA fixture notices")
            self.assertFalse(json.loads((records / "LICENSES/RELEASE_EVIDENCE.json").read_text(encoding="utf-8"))["public_prerelease_allowed"])
            host_records = {name: (base / name).read_bytes() for name in
                            ("COPYING", "LICENSE", "NOTICE.md", "SOURCE-CODE.md", "source-snapshot.zip", "source-snapshot.json", "source-provenance.json", "LICENSES/THIRD_PARTY_NOTICES.md")}
            shutil.copytree(overlay, base, dirs_exist_ok=True)
            for name, expected in host_records.items():
                self.assertEqual((base / name).read_bytes(), expected, name)
            self.assertTrue((base / plugin.relative_to(complete) / "api.py").is_file())
            self.assertFalse((base / plugin.relative_to(complete) / "__pycache__").exists())
            self.assertFalse((base / plugin.relative_to(complete) / "loose.pyc").exists())
            self.assertEqual(products.main(args), 2)

    def test_missing_offline_inputs_stop_before_copy(self):
        pwsh = shutil.which("pwsh") or shutil.which("pwsh.exe")
        with tempfile.TemporaryDirectory(prefix="umi-missing-seed-test-", dir=REPO / "build") as temp:
            root = Path(temp)
            stage = root / "new-stage"
            command = [pwsh, "-NoProfile", "-File", str(REPO / "build/windows/Build-Release.ps1"),
                       "-StagingRoot", str(stage), "-Offline", "-ReuseDependencies",
                       "-ReuseFromStagingRoot", str(root / "missing-seed"), "-SkipTests", "-SkipArchive", "-LocalCandidate"]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Offline reuse input is missing", result.stdout + result.stderr)
            self.assertFalse(stage.exists())

    def test_real_tar_xz_round_trip_and_no_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="umi-xz-test-") as temp:
            root = Path(temp) / "payload"
            plugin = root / "UmiOCR-data/plugins/cuda"
            plugin.mkdir(parents=True)
            (plugin / "api.py").write_bytes(b"small test fixture\n")
            output = Path(temp) / "candidate.tar.xz"
            result = packaging.create_archive(root, output)
            self.assertEqual(result["outer_method"], "LZMA2")
            self.assertTrue(output.read_bytes().startswith(b"\xfd7zXZ\x00"))
            with tarfile.open(output, "r:xz") as archive:
                self.assertIn("UmiOCR-data/plugins/cuda/api.py", archive.getnames())
                self.assertFalse(any(name.startswith("payload/") for name in archive.getnames()))
            before = output.read_bytes()
            with self.assertRaises(packaging.ArchiveError):
                packaging.create_archive(root, output)
            self.assertEqual(output.read_bytes(), before)
            with self.assertRaises(packaging.ArchiveError):
                packaging.create_archive(root, root / "self.tar.xz")

    def test_streamed_tar_xz_has_same_payload_without_temporary_tar(self):
        work = REPO / "build/tmp/startup-small-files-20261028-r1/stream-archive-tests"
        work.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="stream-", dir=work) as temporary:
            root = Path(temporary) / "payload"
            root.mkdir()
            (root / "original.py").write_bytes(b"VALUE = 1\n")
            (root / "LICENSE").write_bytes(b"unchanged license\n")
            output = Path(temporary) / "candidate.tar.xz"
            with patch.object(packaging.tempfile, "TemporaryDirectory", side_effect=AssertionError("streaming must not create an intermediate tar")):
                result = packaging.create_archive(root, output, streaming=True)
            self.assertFalse(result["temporary_tar_created"])
            self.assertEqual(result["format"], "tar.xz")
            self.assertEqual(result["outer_method"], "LZMA2")
            with tarfile.open(output, "r:xz") as archive:
                self.assertEqual(set(archive.getnames()), {"original.py", "LICENSE"})
                for name in archive.getnames():
                    self.assertEqual(archive.extractfile(name).read(), (root / name).read_bytes())
            before = output.read_bytes()
            with self.assertRaises(packaging.ArchiveError):
                packaging.create_archive(root, output, streaming=True)
            self.assertEqual(output.read_bytes(), before)
            with self.assertRaises(packaging.ArchiveError):
                packaging.create_archive(root, root / "self.tar.xz", streaming=True)

    def test_unsafe_tar_members(self):
        with tempfile.TemporaryDirectory(prefix="umi-tar-path-test-") as temp:
            for index, name in enumerate(("../outside", "C:/outside", "safe")):
                output = Path(temp) / f"unsafe-{index}.tar.xz"
                with tarfile.open(output, "w:xz") as archive:
                    member = tarfile.TarInfo(name)
                    if name == "safe":
                        member.type = tarfile.LNKTYPE
                        member.linkname = "../outside"
                        archive.addfile(member)
                    else:
                        member.size = 1
                        archive.addfile(member, io.BytesIO(b"x"))
                with self.assertRaises(packaging.ArchiveError):
                    packaging.verify_archive(output)

    def test_cuda_export_scope_no_git_or_paid_source(self):
        selected = {path.as_posix() for path in cuda.selected_sources(REPO)}
        self.assertIn("build/tools/package_tar_xz.py", selected)
        self.assertIn("build/windows/Build-GpuPlugin.ps1", selected)
        for name in ("build/windows/runtime_archives_cuda.json", "build/tools/merge_runtime.py",
                     "build/tools/runtime_archive_layout.py", "build/tools/audit_runtime_archives.py",
                     "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/runtime_archive_bootstrap.py"):
            self.assertIn(name, selected)
        self.assertIn("SOURCE-CODE.md", selected)
        self.assertFalse(any("win32_PaddleOCRv6_CPU/" in name or "win32_PaddleOCRVL" in name or name.startswith(".git/") for name in selected))
        self.assertFalse(any(name.startswith("UmiOCR-data/qt_res/") for name in selected))

    def test_cuda_export_uses_independent_plugin_version(self):
        with tempfile.TemporaryDirectory(prefix="umi-cuda-version-test-", dir=REPO / "build") as temp:
            repo = Path(temp)
            about = Path("UmiOCR-data/about.json")
            manifest = Path(cuda.PLUGIN) / "umi-plugin.json"
            (repo / about).parent.mkdir(parents=True)
            (repo / about).write_text(json.dumps({"version": {"major": 3, "minor": 0, "patch": 3}}), encoding="utf-8")
            (repo / manifest).parent.mkdir(parents=True)
            (repo / manifest).write_text(json.dumps({"id": "win32_PaddleOCRv6_CUDA", "version": "3.0.4"}), encoding="utf-8")
            before = (repo / about).read_bytes()
            with patch.object(cuda, "selected_sources", return_value=[about, manifest]), patch.object(cuda, "locked_sources", return_value=[]), patch.object(cuda, "git_output", return_value="fixture-parent"):
                result = cuda.export_repository(repo, repo / "build/cuda-source", repo / "build/cache/sources")
            output = repo / "build/cuda-source"
            self.assertEqual(result["version"], "3.0.4")
            self.assertEqual((output / "VERSION").read_text("utf-8"), "3.0.4\n")
            self.assertEqual((output / about).read_bytes(), before)
            self.assertEqual((repo / about).read_bytes(), before)

    def test_cuda_native_source_allowlist_is_exact(self):
        candidates = snapshot.files_for_repo(REPO, public=True)
        extra = Path("build/windows/CudaWorker/unrelated.cpp")
        with patch.object(cuda, "files_for_repo", return_value=[*candidates, extra]):
            selected = {path.as_posix() for path in cuda.selected_sources(REPO)}
        self.assertEqual({name for name in selected if name.startswith("build/windows/CudaWorker/")}, cuda.NATIVE_SOURCES)
        self.assertNotIn(extra.as_posix(), selected)
        self.assertTrue({"build/tools/record_gpu_startup.py", "build/tools/gpu_startup_evidence.py",
                         "tests/test_gpu_startup_record.py", "tests/test_gpu_startup_evidence.py",
                         "tests/test_cuda_native_launcher.py", "docs/RELEASE_CUDA_3.0.4_DRAFT.md",
                         "docs/RELEASE_CUDA_3.0.4_REVIEW.md"} <= selected)
        self.assertNotIn("build/windows/PyStand/PyStand.cpp", selected)

    def test_powershell_parse_and_reuse_models_scope(self):
        pwsh = shutil.which("pwsh") or shutil.which("pwsh.exe")
        self.assertIsNotNone(pwsh, "PowerShell 7 is required for Windows build syntax tests")
        script = r'''
$ErrorActionPreference = 'Stop'
foreach ($file in @('Build-Release.ps1','Build-GpuPlugin.ps1','Assemble-Candidate.ps1')) {
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $args[0] $file), [ref]$tokens, [ref]$errors)
    if ($errors) { throw (($errors | ForEach-Object { $_.Message }) -join '; ') }
    if ($file -eq 'Build-GpuPlugin.ps1') {
        $reuse = @($ast.FindAll({param($n) $n -is [System.Management.Automation.Language.IfStatementAst] -and $n.Extent.Text -match '^if \(\$ReuseModels\)'}, $true))
        if ($reuse.Count -ne 1 -or $reuse[0].Parent -ne $ast.EndBlock) { throw 'ReuseModels must be a top-level independent branch.' }
    }
    Write-Output "$file syntax OK"
}
'''
        script = script.replace("$args[0]", "'" + str(REPO / "build/windows").replace("'", "''") + "'")
        result = subprocess.run([pwsh, "-NoProfile", "-Command", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_existing_staging_is_rejected_without_modification(self):
        pwsh = shutil.which("pwsh") or shutil.which("pwsh.exe")
        with tempfile.TemporaryDirectory(prefix="umi-small-stage-test-", dir=REPO / "build") as temp:
            root = Path(temp)
            marker = root / "keep.bin"
            marker.write_bytes(b"new small fixture only")
            for filename in ("Build-Release.ps1", "Build-GpuPlugin.ps1"):
                result = subprocess.run([pwsh, "-NoProfile", "-File", str(REPO / "build/windows" / filename), "-StagingRoot", str(root), "-Offline", "-ReuseDependencies", "-LocalCandidate", "-SkipArchive"], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Use a new staging directory", result.stdout + result.stderr)
                self.assertEqual(marker.read_bytes(), b"new small fixture only")


if __name__ == "__main__":
    unittest.main()
