"""Offline miniature CUDA/host fixtures only; no real builds or release inputs."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("overlay", ROOT / "build/tools/prepare_cuda_overlay.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
PLUGIN = Path("UmiOCR-data/plugins") / module.PLUGIN_ID
PYTHON = sys.executable


def encoded(document):
    return (json.dumps(document, indent=2) + "\n").encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_snapshot(records, members, version, parent="gpu-fixture-parent"):
    records.mkdir(parents=True, exist_ok=True)
    archive = records / "source-snapshot.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        for name, data in sorted(members.items()):
            stream.writestr(name, data)
    manifest = {name: sha(data) for name, data in members.items()}
    (records / "source-snapshot.json").write_bytes(encoded(manifest))
    (records / "source-provenance.json").write_bytes(encoded({
        "version": version, "scope": "public", "parent_revisions": {"host": parent},
        "files": len(manifest), "archive_sha256": sha(archive.read_bytes()),
    }))


def make_gpu(root, version="3.0.3", *, loose_source=False, version_file=True):
    """Model the independent build exit, including its CUDA-only export marker."""
    plugin = root / PLUGIN
    plugin.mkdir(parents=True)
    plugin_manifest = encoded({"id": module.PLUGIN_ID, "version": version})
    (plugin / "umi-plugin.json").write_bytes(plugin_manifest)
    (plugin / "api.py").write_bytes(b"# GPU plugin fixture\n")
    (root / "LICENSES").mkdir()
    (root / "LICENSES/THIRD_PARTY_NOTICES.md").write_text("CUDA fixture notices", encoding="utf-8")
    for name in ("COPYING", "LICENSE", "NOTICE.md", "SOURCE-CODE.md"):
        (root / name).write_text(f"GPU {version} {name}\n", encoding="utf-8")
    files = {
        "VERSION": (version + "\n").encode("utf-8"),
        (PLUGIN / "umi-plugin.json").as_posix(): plugin_manifest,
        (PLUGIN / "api.py").as_posix(): (plugin / "api.py").read_bytes(),
        "UmiOCR-data/about.json": encoded({"version": dict(zip(("major", "minor", "patch"), map(int, version.split("."))))}),
        "cuda-only.py": b"GPU_ONLY = True\n",
    }
    files["source-export.json"] = encoded({
        "version": version, "scope": "public-cuda-only", "parent_revision": "gpu-fixture-parent",
        "files": {name: sha(data) for name, data in files.items()},
    })
    write_snapshot(root, {"host/" + name: data for name, data in files.items()}, version)
    if version_file:
        (root / "VERSION").write_bytes(files["VERSION"])
    if loose_source:
        for name, data in files.items():
            target = root / "source" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    return root


def make_host(root, version="9.8.7"):
    root.mkdir(parents=True, exist_ok=True)
    (root / "LICENSES").mkdir(exist_ok=True)
    (root / "LICENSES/THIRD_PARTY_NOTICES.md").write_text("host fixture notices", encoding="utf-8")
    for name in ("COPYING", "LICENSE", "NOTICE.md", "SOURCE-CODE.md"):
        (root / name).write_text(f"HOST {version} {name}\n", encoding="utf-8")
    (root / "VERSION").write_bytes((version + "\r\n").encode("utf-8"))
    write_snapshot(root, {"host/host-only.py": b"HOST_ONLY = True\n"}, version, "host-fixture-parent")
    source = root / "source"
    source.mkdir()
    (source / "host-only.py").write_text("HOST_ONLY = True\n", encoding="utf-8")
    return root


def retain_records(gpu, destination):
    destination.mkdir(parents=True)
    for name in module.SOURCE_RECORDS:
        source = gpu / name
        if source.is_dir():
            shutil.copytree(source, destination / name)
        elif source.is_file():
            shutil.copy2(source, destination / name)
        elif name == "VERSION":
            with zipfile.ZipFile(gpu / "source-snapshot.zip") as archive:
                (destination / name).write_bytes(archive.read("host/VERSION"))


def make_combined(root, gpu, *, retained=True):
    make_host(root)
    shutil.copytree(gpu / PLUGIN, root / PLUGIN)
    licenses = root / "LICENSES/plugins" / module.PLUGIN_ID
    shutil.copytree(gpu / "LICENSES", licenses)
    if retained:
        retain_records(gpu, root / module.SOURCE_NAMESPACE)
    return root


def tree_bytes(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def change_archive(records, change):
    with zipfile.ZipFile(records / "source-snapshot.zip") as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    change(members)
    provenance = json.loads((records / "source-provenance.json").read_bytes())
    write_snapshot(records, members, provenance["version"], provenance["parent_revisions"]["host"])


class CudaFixtureCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="umi-cuda-overlay-test-", dir=ROOT / "build")
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def rejected(self, staging, output, *, combined=False, pattern=None):
        with self.assertRaisesRegex((RuntimeError, ValueError, OSError, zipfile.BadZipFile), pattern or ".+"):
            module.prepare(staging, output, combined=combined)
        self.assertFalse(output.exists())

    def junction(self, link, target):
        if os.name != "nt":
            link.symlink_to(target, target_is_directory=True)
            return
        result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class CudaOverlayTests(CudaFixtureCase):
    def test_combined_selects_cuda_records_and_preserves_host_on_install(self):
        gpu = make_gpu(self.root / "gpu", loose_source=True)
        combined = make_combined(self.root / "combined", gpu)
        before = tree_bytes(combined)
        output = self.root / "overlay"
        module.prepare(combined, output, combined=True)
        records = output / "LICENSES/plugins" / module.PLUGIN_ID
        for name in module.SOURCE_RECORDS:
            source = gpu / name
            if source.is_file():
                self.assertEqual((records / name).read_bytes(), source.read_bytes(), name)
            elif source.is_dir():
                self.assertEqual(tree_bytes(records / name), tree_bytes(source), name)
        self.assertNotEqual((records / "source-snapshot.zip").read_bytes(), (combined / "source-snapshot.zip").read_bytes())
        self.assertEqual((records / "VERSION").read_text().strip(), "3.0.3")
        self.assertEqual((records / "LICENSES/THIRD_PARTY_NOTICES.md").read_text(), "CUDA fixture notices")
        self.assertFalse((records / "LICENSES" / module.SOURCE_RECORDS_DIR).exists())
        self.assertEqual(len(list(output.rglob("source-snapshot.zip"))), 1)
        self.assertEqual({path.name for path in output.iterdir()}, {"LICENSES", "UmiOCR-data"})
        self.assertEqual(tree_bytes(combined), before)
        host = make_host(self.root / "host")
        host_before = tree_bytes(host)
        shutil.copytree(output, host, dirs_exist_ok=True)
        for name, data in host_before.items():
            self.assertEqual((host / name).read_bytes(), data, name)
        self.assertEqual((host / PLUGIN / "api.py").read_bytes(), (gpu / PLUGIN / "api.py").read_bytes())

    def test_standalone_preserves_records_and_filters_private_plugin_files(self):
        gpu = make_gpu(self.root / "gpu", loose_source=True)
        cache = gpu / PLUGIN / "__pycache__"
        cache.mkdir()
        (cache / "api.pyc").write_bytes(b"private cache")
        (gpu / "UmiOCR-data/themes.json").write_text("private", encoding="utf-8")
        (gpu / "logs").mkdir()
        (gpu / "logs/private.txt").write_text("private", encoding="utf-8")
        before = tree_bytes(gpu)
        output = self.root / "standalone"
        module.prepare(gpu, output)
        records = output / "LICENSES/plugins" / module.PLUGIN_ID
        self.assertEqual((records / "source-snapshot.zip").read_bytes(), (gpu / "source-snapshot.zip").read_bytes())
        self.assertEqual(tree_bytes(records / "source"), tree_bytes(gpu / "source"))
        self.assertFalse((output / PLUGIN / "__pycache__").exists())
        self.assertFalse((records / "logs").exists())
        self.assertEqual(tree_bytes(gpu), before)

    def test_standalone_local_candidate_without_loose_source_or_version(self):
        gpu = make_gpu(self.root / "gpu", version_file=False)
        output = self.root / "overlay"
        module.prepare(gpu, output)
        records = output / "LICENSES/plugins" / module.PLUGIN_ID
        self.assertEqual((records / "VERSION").read_bytes(), b"3.0.3\n")
        self.assertFalse((records / "source").exists())
        self.assertFalse((gpu / "VERSION").exists())

    def test_legacy_combined_fails_closed_without_even_creating_output_parent(self):
        gpu = make_gpu(self.root / "gpu")
        combined = make_combined(self.root / "combined", gpu, retained=False)
        before = tree_bytes(combined)
        output = self.root / "missing-parent/overlay"
        self.rejected(combined, output, combined=True, pattern="reassemble")
        self.assertFalse(output.parent.exists())
        self.assertEqual(tree_bytes(combined), before)

    def test_public_host_snapshot_is_not_a_cuda_identity(self):
        gpu = make_gpu(self.root / "gpu")
        combined = make_combined(self.root / "combined", gpu, retained=False)
        make_host(combined / module.SOURCE_NAMESPACE, version="3.0.3")
        self.rejected(combined, self.root / "overlay", combined=True, pattern="source-export")

    def test_export_scope_version_and_revision_are_checked(self):
        for key, value in (("scope", "public"), ("version", "0.0.1"), ("parent_revision", "other-parent")):
            with self.subTest(key=key):
                gpu = make_gpu(self.root / key)
                def change(members):
                    document = json.loads(members["host/source-export.json"])
                    document[key] = value
                    members["host/source-export.json"] = encoded(document)
                change_archive(gpu, change)
                self.rejected(gpu, self.root / (key + "-output"), pattern="identity/version/revision")

    def test_required_source_record_files_are_not_optional(self):
        for index, name in enumerate(module.SOURCE_RECORDS):
            if name in {"source", "VERSION"}:
                continue
            with self.subTest(name=name):
                gpu = make_gpu(self.root / str(index))
                (gpu / name).unlink()
                self.rejected(gpu, self.root / f"output-{index}", pattern="required file")

    def test_combined_version_record_is_required(self):
        gpu = make_gpu(self.root / "gpu")
        combined = make_combined(self.root / "combined", gpu)
        (combined / module.SOURCE_NAMESPACE / "VERSION").unlink()
        self.rejected(combined, self.root / "overlay", combined=True, pattern="VERSION")

    def test_identity_members_cannot_be_missing_from_a_self_consistent_zip(self):
        for index, name in enumerate(("source-export.json", "VERSION", "UmiOCR-data/about.json", (PLUGIN / "umi-plugin.json").as_posix())):
            with self.subTest(name=name):
                gpu = make_gpu(self.root / str(index))
                change_archive(gpu, lambda members: members.pop("host/" + name))
                self.rejected(gpu, self.root / f"output-{index}", pattern="identity/version members")

    def test_provenance_and_manifest_integrity_are_checked_before_output(self):
        mutations = (
            ("provenance version", "source-provenance.json", "version", "0.0.1"),
            ("provenance scope", "source-provenance.json", "scope", "legacy"),
            ("provenance count", "source-provenance.json", "files", 0),
            ("archive hash", "source-provenance.json", "archive_sha256", "0" * 64),
            ("member hash", "source-snapshot.json", "host/cuda-only.py", "0" * 64),
        )
        for index, (label, name, key, value) in enumerate(mutations):
            with self.subTest(label=label):
                gpu = make_gpu(self.root / str(index))
                document = json.loads((gpu / name).read_bytes())
                document[key] = value
                (gpu / name).write_bytes(encoded(document))
                self.rejected(gpu, self.root / f"output-{index}")

    def test_zip_member_set_and_unsafe_names_are_rejected(self):
        for index, name in enumerate(("host/../outside.py", "host/unsafe\\path.py", "other/source.py")):
            with self.subTest(name=name):
                gpu = make_gpu(self.root / str(index))
                change_archive(gpu, lambda members: members.update({name: b"unsafe"}))
                self.rejected(gpu, self.root / f"output-{index}", pattern="Unsafe")
        gpu = make_gpu(self.root / "missing-member")
        manifest = json.loads((gpu / "source-snapshot.json").read_bytes())
        manifest["host/missing.py"] = "0" * 64
        (gpu / "source-snapshot.json").write_bytes(encoded(manifest))
        provenance = json.loads((gpu / "source-provenance.json").read_bytes())
        provenance["files"] = len(manifest)
        (gpu / "source-provenance.json").write_bytes(encoded(provenance))
        self.rejected(gpu, self.root / "missing-output", pattern="member list")

    def test_root_and_archived_versions_are_checked(self):
        gpu = make_gpu(self.root / "root-version")
        (gpu / "VERSION").write_text("0.0.1\n", encoding="utf-8")
        self.rejected(gpu, self.root / "root-output", pattern="VERSION")
        for index, name in enumerate(("host/VERSION", "host/UmiOCR-data/about.json")):
            with self.subTest(name=name):
                gpu = make_gpu(self.root / str(index))
                def change(members):
                    members[name] = b"0.0.1\n" if name.endswith("VERSION") else encoded({"version": "0.0.1"})
                    document = json.loads(members["host/source-export.json"])
                    document["files"][name.removeprefix("host/")] = sha(members[name])
                    members["host/source-export.json"] = encoded(document)
                change_archive(gpu, change)
                self.rejected(gpu, self.root / f"output-{index}", pattern="version/plugin identity")

    def test_live_plugin_and_loose_source_must_match_snapshot(self):
        gpu = make_gpu(self.root / "plugin")
        manifest = json.loads((gpu / PLUGIN / "umi-plugin.json").read_bytes())
        manifest["extra"] = "changed since source export"
        (gpu / PLUGIN / "umi-plugin.json").write_bytes(encoded(manifest))
        self.rejected(gpu, self.root / "plugin-output", pattern="version/plugin identity")
        gpu = make_gpu(self.root / "mirror", loose_source=True)
        (gpu / "source/cuda-only.py").write_text("different sources", encoding="utf-8")
        self.rejected(gpu, self.root / "mirror-output", pattern="loose source tree")

    def test_staging_and_output_ancestor_junctions_are_rejected(self):
        container = self.root / "real"
        container.mkdir()
        gpu = make_gpu(container / "gpu")
        alias = self.root / "alias"
        self.junction(alias, container)
        self.rejected(alias / "gpu", self.root / "input-output", pattern="link or junction")
        self.rejected(gpu, alias / "output", pattern="link or junction")
        self.assertFalse((container / "output").exists())

    def test_plugin_and_metadata_descendant_junctions_are_rejected(self):
        gpu = make_gpu(self.root / "gpu")
        outside = self.root / "unrelated"
        outside.mkdir()
        (outside / "keep.txt").write_bytes(b"keep")
        self.junction(gpu / PLUGIN / "linked", outside)
        self.rejected(gpu, self.root / "plugin-output", pattern="link or junction")
        clean_gpu = make_gpu(self.root / "clean-gpu")
        combined = make_combined(self.root / "combined", clean_gpu, retained=False)
        self.junction(combined / module.SOURCE_NAMESPACE, clean_gpu)
        self.rejected(combined, self.root / "metadata-output", combined=True, pattern="link or junction")
        self.assertEqual((outside / "keep.txt").read_bytes(), b"keep")

    def test_file_symlink_is_rejected_before_reading_it(self):
        gpu = make_gpu(self.root / "gpu")
        target = self.root / "unrelated.json"
        target.write_text("not CUDA provenance", encoding="utf-8")
        (gpu / "source-provenance.json").unlink()
        try:
            (gpu / "source-provenance.json").symlink_to(target)
        except OSError as exc:
            self.skipTest(f"file symlink privilege unavailable: {exc}")
        self.rejected(gpu, self.root / "output", pattern="link or junction")
        self.assertEqual(target.read_text(), "not CUDA provenance")

    def test_existing_output_and_nested_output_are_rejected(self):
        gpu = make_gpu(self.root / "gpu")
        output = self.root / "existing"
        output.mkdir()
        (output / "keep.bin").write_bytes(b"keep")
        with self.assertRaisesRegex(RuntimeError, "must be new"):
            module.prepare(gpu, output)
        self.assertEqual(tree_bytes(output), {"keep.bin": b"keep"})
        self.rejected(gpu, gpu / "nested-output", pattern="inside its input")

    def test_validate_only_cli_has_no_side_effects(self):
        gpu = make_gpu(self.root / "gpu", version_file=False)
        before = tree_bytes(self.root)
        result = subprocess.run([PYTHON, "-I", "-B", "-S", str(ROOT / "build/tools/prepare_cuda_overlay.py"),
                                 "--staging-root", str(gpu), "--validate-only"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["version"], "3.0.3")
        self.assertIn("VERSION", plan["source_records"])
        self.assertNotIn("source", plan["source_records"])
        self.assertEqual(tree_bytes(self.root), before)


@unittest.skipUnless((ROOT / "build/windows/Assemble-Candidate.ps1").is_file(),
                     "host-side assembly is not part of the independent CUDA source export")
class CandidateAssemblyTests(CudaFixtureCase):
    def setUp(self):
        super().setUp()
        self.pwsh = shutil.which("pwsh") or shutil.which("pwsh.exe")
        self.assertIsNotNone(self.pwsh, "PowerShell 7 is required for miniature assembly fixtures")
        about = json.loads((ROOT / "UmiOCR-data/about.json").read_bytes())
        self.version = ".".join(str(about["version"][key]) for key in ("major", "minor", "patch"))

    def inputs(self, name="fixture", **kwargs):
        base = make_host(self.root / (name + "-base"), self.version)
        about = base / "UmiOCR-data/about.json"
        about.parent.mkdir()
        about.write_bytes(encoded({"version": dict(zip(("major", "minor", "patch"), map(int, self.version.split("."))))}))
        gpu = make_gpu(self.root / (name + "-gpu"), self.version, **kwargs)
        return base, gpu

    def assemble(self, base, gpu, destination):
        return subprocess.run([self.pwsh, "-NoProfile", "-NonInteractive", "-File",
                               str(ROOT / "build/windows/Assemble-Candidate.ps1"),
                               "-BaseStagingRoot", str(base), "-GpuStagingRoot", str(gpu),
                               "-Destination", str(destination), "-PythonExe", PYTHON],
                              cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")

    def test_assembly_preserves_independent_cuda_records_then_overlay_uses_them(self):
        for loose in (False, True):
            with self.subTest(loose_source=loose):
                base, gpu = self.inputs(str(loose), loose_source=loose, version_file=loose)
                base_before, gpu_before = tree_bytes(base), tree_bytes(gpu)
                combined = self.root / (str(loose) + "-combined")
                result = self.assemble(base, gpu, combined)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                records = combined / module.SOURCE_NAMESPACE
                for name in ("source-snapshot.zip", "source-snapshot.json", "source-provenance.json"):
                    self.assertEqual((combined / name).read_bytes(), (base / name).read_bytes(), name)
                    self.assertEqual((records / name).read_bytes(), (gpu / name).read_bytes(), name)
                self.assertEqual((records / "VERSION").read_text(encoding="utf-8-sig").strip(), self.version)
                with zipfile.ZipFile(gpu / "source-snapshot.zip") as archive:
                    self.assertEqual((records / "VERSION").read_bytes(), archive.read("host/VERSION"))
                self.assertEqual((records / "source").is_dir(), loose)
                self.assertEqual(tree_bytes(base), base_before)
                self.assertEqual(tree_bytes(gpu), gpu_before)
                output = self.root / (str(loose) + "-overlay")
                module.prepare(combined, output, combined=True)
                delivered = output / "LICENSES/plugins" / module.PLUGIN_ID
                self.assertEqual((delivered / "source-snapshot.zip").read_bytes(), (gpu / "source-snapshot.zip").read_bytes())
                self.assertEqual(len(list(output.rglob("source-snapshot.zip"))), 1)
                self.assertFalse((delivered / "LICENSES" / module.SOURCE_RECORDS_DIR).exists())

    def test_assembly_rejects_invalid_cuda_metadata_before_destination_creation(self):
        for kind in ("missing", "wrong-scope", "version", "loose-source", "base-plugin", "reserved-notices"):
            with self.subTest(kind=kind):
                base, gpu = self.inputs(kind, loose_source=True)
                if kind == "missing":
                    (gpu / "source-snapshot.json").unlink()
                elif kind == "wrong-scope":
                    def change(members):
                        exported = json.loads(members["host/source-export.json"])
                        exported["scope"] = "public"
                        members["host/source-export.json"] = encoded(exported)
                    change_archive(gpu, change)
                elif kind == "version":
                    (gpu / "VERSION").write_text("0.0.1", encoding="utf-8")
                elif kind == "loose-source":
                    (gpu / "source/cuda-only.py").write_bytes(b"different")
                elif kind == "base-plugin":
                    (base / PLUGIN).mkdir(parents=True)
                else:
                    (gpu / "LICENSES" / module.SOURCE_RECORDS_DIR).mkdir()
                before = tree_bytes(self.root)
                destination = self.root / (kind + "-missing-parent/combined")
                result = self.assemble(base, gpu, destination)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(destination.parent.exists())
                self.assertEqual(tree_bytes(self.root), before)

    def test_assembly_rejects_input_and_output_junctions(self):
        base, gpu = self.inputs()
        alias = self.root / "alias"
        self.junction(alias, gpu)
        output_alias = self.root / "output-alias"
        real_output_parent = self.root / "real-output"
        real_output_parent.mkdir()
        self.junction(output_alias, real_output_parent)
        for selected_gpu, destination in ((alias, self.root / "input-output"),
                                          (gpu, output_alias / "output")):
            result = self.assemble(base, selected_gpu, destination)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("junction", result.stdout + result.stderr)
            self.assertFalse(destination.exists())
        target = self.root / "target"
        target.mkdir()
        self.junction(base / "descendant-junction", target)
        destination = self.root / "descendant-output"
        result = self.assemble(base, gpu, destination)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("junction", result.stdout + result.stderr)
        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
