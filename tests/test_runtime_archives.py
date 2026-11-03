"""Standard-library-only Stored-ZIP contract tests; never load OCR/Qt/models.

All fixtures belong to build/tmp, not the system temp/home or a real candidate.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import importlib
import importlib.resources
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def adjacent(name):
    spec = importlib.util.spec_from_file_location("runtime_archive_test_" + name, ROOT / "build/tools" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


merge = adjacent("merge_runtime")
layout = merge.layout


class RuntimeArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = ROOT / "build/tmp"
        layout.plain_path(temporary)
        temporary.mkdir(parents=True, exist_ok=True)
        cls.scratch = Path(tempfile.mkdtemp(prefix="runtime-archives-tests-", dir=temporary))
        cls.counter = 0

    @classmethod
    def tearDownClass(cls):
        # Only this suite's small, owned fixtures; never stop a process or cross
        # a reparse point while cleaning them up.
        layout.tree_files(cls.scratch)
        if merge.running_processes(cls.scratch):
            raise RuntimeError("Fixture root became occupied; preserving it for review")
        shutil.rmtree(cls.scratch)

    def setUp(self):
        type(self).counter += 1
        self.project = self.scratch / str(self.counter) / "project"
        (self.project / "build").mkdir(parents=True)
        self.root = self.project / "build/candidate"
        self.root.mkdir()

    def write(self, name, data, root=None):
        path = (self.root if root is None else root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
        return path

    def policy(self, *, packages=(), modules=(), prefix="vendor", archive="vendor.zip", kind="plugin"):
        return {"schema_version": 1, "kind": kind, "archives": [
            {"path": archive, "source_prefix": prefix, "packages": list(packages), "modules": list(modules)}]}

    def aggregate(self, policy=None, **kwargs):
        return merge.aggregate_runtime(self.root, kind=kwargs.pop("kind", "plugin"), policy=policy,
                                       project_root=self.project, occupancy_check=kwargs.pop("occupancy_check", lambda _root: []), **kwargs)

    def package(self):
        self.original = {
            "vendor/archivetest_fixture/__init__.py": b'"""Unmodified docstring."""\nfrom __future__ import annotations\nfrom .value import VALUE\n',
            "vendor/archivetest_fixture/value.py": b"VALUE = 42\n",
            "vendor/archivetest_fixture/data.json": b'{"resource": "original bytes"}\n',
            "vendor/archivetest_fixture/tests/test_value.py": b"# retained, not trimmed\n",
            "vendor/archivetest_fixture/LICENSE": b"Original package license\n",
            "vendor/archivetest_fixture/py.typed": b"",
            "vendor/archivetest_fixture/.keep": b"",
        }
        for name, data in self.original.items():
            self.write(name, data)
        return self.policy(packages=["archivetest_fixture"])

    def test_cli_accepts_explicit_component_project_root(self):
        self.write("vendor/six.py", "VALUE = 1\n")
        with patch.object(merge, "running_processes", return_value=[]), patch("sys.stdout", new=io.StringIO()):
            code = merge.main([str(self.root), "--kind", "plugin", "--project-root", str(self.project)])
        self.assertEqual(code, 0)
        self.assertTrue((self.root / "vendor.zip").is_file())
        self.assertFalse((self.root / "vendor/six.py").exists())

    def test_nested_freeze_description_does_not_freeze_a_candidate(self):
        policy = self.package()
        record = {"status": "PREPARED_NOT_FROZEN", "description": {
            "purpose": "immutable-review-product-not-approval", "package_root": str(self.root)}}
        self.write("build/audit/prepared.json", json.dumps(record), root=self.project)
        self.aggregate(policy)
        self.assertTrue((self.root / "vendor.zip").is_file())

    def test_actual_overlapping_freeze_is_rejected_without_writes(self):
        policy = self.package()
        self.write("build/audit/frozen.json", json.dumps({
            "purpose": "immutable-review-product-not-approval", "package_root": str(self.root)}), root=self.project)
        with self.assertRaisesRegex(LayoutError, "already frozen"):
            self.aggregate(policy)
        self.assert_no_assembly()

    def test_malformed_actual_freeze_still_fails_closed(self):
        policy = self.package()
        self.write("build/audit/frozen.json", json.dumps({
            "purpose": "immutable-review-product-not-approval"}), root=self.project)
        with self.assertRaisesRegex(LayoutError, "Invalid existing freeze"):
            self.aggregate(policy)
        self.assert_no_assembly()

    def external_hashes(self):
        return {name: layout.sha256_bytes(data) for name, data in self.original.items()}

    def manifest(self):
        return layout.read_json(self.root / layout.MANIFEST_NAME)

    def save_manifest(self, value):
        (self.root / layout.MANIFEST_NAME).write_text(json.dumps(value), encoding="utf-8")

    def rewrite_zip(self, mutate):
        path = self.root / "vendor.zip"
        with zipfile.ZipFile(path) as container:
            entries = [(info, container.read(info)) for info in container.infolist()]
        entries = mutate(entries)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(path, "w") as container:
                for info, data in entries:
                    container.writestr(info, data)
        document = self.manifest()
        document["archives"][0].update({"bytes": path.stat().st_size, "sha256": layout.sha256_file(path)})
        self.save_manifest(document)

    def assert_no_assembly(self):
        for name in (layout.MANIFEST_NAME, layout.INPUTS_NAME, layout.MARKER_NAME, "vendor.zip", "app.zip", "dependencies.zip"):
            self.assertFalse((self.root / name).exists(), name)

    def test_raw_sources_data_licenses_tests_and_manifest_are_preserved(self):
        policy = self.package()
        plugin_manifest = self.write("umi-plugin.json", '{"runtime":{"vendor_dirs":[]}}\n').read_bytes()
        result = self.aggregate(policy, source_hashes=self.external_hashes())
        self.assertEqual((self.root / "umi-plugin.json").read_bytes(), plugin_manifest)
        self.assertNotIn("worker_archives", plugin_manifest.decode())
        with layout.load_layout(self.root, source_hashes=self.external_hashes()) as view:
            self.assertEqual(set(view.files("vendor")), set(self.original))
            for name, data in self.original.items():
                self.assertEqual(view.read_bytes(name), data)
                self.assertFalse((self.root / name).exists())
        self.assertTrue(all(not path.name.endswith(".pyc") for path in self.root.rglob("*")))
        with zipfile.ZipFile(self.root / "vendor.zip") as container:
            self.assertEqual(container.namelist(), sorted(container.namelist()))
            for info in container.infolist():
                self.assertEqual(info.date_time, layout.TIMESTAMP)
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED)
        self.assertEqual(result["resources"], "Qt/QML/RCC and real-path resources remain external; RCC not generated")

    def test_real_zipimport_and_resource_read_without_extraction(self):
        self.aggregate(self.package())
        before = set(layout.tree_files(self.root))
        sys.path.insert(0, str(self.root / "vendor.zip"))
        try:
            package = importlib.import_module("archivetest_fixture")
            self.assertEqual(package.VALUE, 42)
            self.assertIn("vendor.zip", package.__file__)
            self.assertEqual(importlib.resources.files(package).joinpath("data.json").read_bytes(), self.original["vendor/archivetest_fixture/data.json"])
        finally:
            sys.path.remove(str(self.root / "vendor.zip"))
            for name in list(sys.modules):
                if name.startswith("archivetest_fixture"):
                    del sys.modules[name]
            for name in list(sys.path_importer_cache):
                if str(self.root) in name:
                    del sys.path_importer_cache[name]
            importlib.invalidate_caches()
        self.assertEqual(set(layout.tree_files(self.root)), before)

    def test_host_namespace_has_explicit_directory_entries(self):
        self.write("py_src/umi_archive_fixture/value.py", "VALUE = 17\n")
        self.aggregate(self.policy(packages=["py_src"], prefix="", archive="app.zip", kind="host"), kind="host")
        with zipfile.ZipFile(self.root / "app.zip") as container:
            self.assertIn("py_src/", container.namelist())
            self.assertIn("py_src/umi_archive_fixture/", container.namelist())
        sys.path.insert(0, str(self.root / "app.zip"))
        try:
            module = importlib.import_module("py_src.umi_archive_fixture.value")
            self.assertEqual(module.VALUE, 17)
        finally:
            sys.path.remove(str(self.root / "app.zip"))
            for name in list(sys.modules):
                if name == "py_src" or name.startswith("py_src.umi_archive_fixture"):
                    del sys.modules[name]
            for name in list(sys.path_importer_cache):
                if str(self.root) in name:
                    del sys.path_importer_cache[name]
            importlib.invalidate_caches()

    def test_zip_bytes_are_reproducible_across_roots_and_source_times(self):
        policy = self.package()
        self.aggregate(policy)
        first = (self.root / "vendor.zip").read_bytes()
        self.root = self.project / "build/another-candidate"
        self.root.mkdir()
        for name, data in reversed(list(self.original.items())):
            path = self.write(name, data)
            os.utime(path, (1234567890, 1234567890))
        self.aggregate(policy)
        self.assertEqual((self.root / "vendor.zip").read_bytes(), first)

    def test_default_plugin_policy_keeps_unknown_native_models_and_metadata_external(self):
        self.write("vendor/six.py", "VALUE = 1\n")
        originals = {"vendor/paddle/native.pyd": b"native", "vendor/paddle/__init__.py": b"# external\n",
                     "vendor/unknown/a.py": b"# unknown\n", "models/weight.gguf": b"do not read models",
                     "vendor/example-1.dist-info/LICENSE": b"license", "StructuredDocument.qml": b"Item {}"}
        for name, data in originals.items():
            self.write(name, data)
        original_read = Path.read_bytes
        def no_model_reads(path):
            if path.suffix == ".gguf":
                raise AssertionError("Aggregation must not read model weights")
            return original_read(path)
        with patch.object(Path, "read_bytes", no_model_reads):
            result = self.aggregate()
        for name, data in originals.items():
            self.assertEqual((self.root / name).read_bytes(), data)
        self.assertIn({"logical_path": "vendor/unknown", "reason": "not-allowlisted"}, result["external"])

    def test_whole_package_with_native_cache_or_unknown_files_is_rejected_without_writes(self):
        for suffix in ("native.pyd", "weights.gguf", "__pycache__/value.pyc", "unknown.unapproved", "font.ttf", "view.qml"):
            with self.subTest(suffix=suffix):
                policy = self.package()
                path = self.write("vendor/archivetest_fixture/" + suffix, b"not relocated")
                with self.assertRaises(LayoutError):
                    self.aggregate(policy)
                self.assert_no_assembly()
                self.assertEqual(path.read_bytes(), b"not relocated")
                path.unlink()
                if path.parent.name == "__pycache__":
                    path.parent.rmdir()

    def test_explicit_policy_cannot_relocate_known_real_path_native_packages(self):
        self.write("vendor/paddle/__init__.py", "# retained\n")
        with self.assertRaises(LayoutError):
            self.aggregate(self.policy(packages=["paddle"]))
        self.assert_no_assembly()

    def test_nonallowlisted_files_are_not_deleted(self):
        self.write("vendor/six.py", "VALUE = 1\n")
        extra = self.write("vendor/a.py", "# keep\n")
        self.aggregate(self.policy(modules=["six.py"]))
        self.assertEqual(extra.read_bytes(), b"# keep\n")

    def test_source_hashes_must_cover_all_selected_files_and_match(self):
        policy = self.package()
        for hashes in ({}, {**self.external_hashes(), "vendor/archivetest_fixture/value.py": "0" * 64}):
            with self.subTest(hashes=bool(hashes)), self.assertRaises(LayoutError):
                self.aggregate(policy, source_hashes=hashes)
            self.assert_no_assembly()

    def test_external_source_manifest_is_supported_but_self_evidence_is_rejected(self):
        policy = self.package()
        internal = self.write("source-map.json", json.dumps({"sourceHashes": self.external_hashes()}))
        with self.assertRaises(LayoutError):
            self.aggregate(policy, source_manifest=internal)
        external = self.project / "build/source-map.json"
        external.write_bytes(internal.read_bytes())
        self.aggregate(policy, source_manifest=external)
        self.assertEqual(layout.verify_layout(self.root, source_hashes=self.external_hashes())["source_binding"], "external-hashes-verified")

    def test_input_manifest_is_not_claimed_as_external_provenance(self):
        self.aggregate(self.package())
        self.assertEqual(layout.verify_layout(self.root)["source_binding"], "not-proven-by-layout")
        inventory = layout.read_json(self.root / layout.INPUTS_NAME)
        self.assertEqual(inventory["source_binding"], "self-recorded-not-external-source-proof")

    def test_original_wheel_record_csv_ownership_is_retained_and_verified(self):
        policy = self.package()
        name = "vendor/archivetest_fixture/commas,data.csv"
        self.original[name] = b"a,b\n"
        self.write(name, self.original[name])
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        for logical, data in self.original.items():
            checksum = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            writer.writerow([logical.removeprefix("vendor/"), "sha256=" + checksum, str(len(data))])
        record = self.write("vendor/fixture-1.dist-info/RECORD", stream.getvalue())
        before = record.read_bytes()
        document = self.aggregate(policy)
        self.assertEqual(record.read_bytes(), before)
        files = [entry for entry in document["archives"][0]["members"] if entry["kind"] == "file"]
        self.assertTrue(all(entry["source"]["record_owner"] == "fixture-1.dist-info" for entry in files))
        layout.verify_layout(self.root)
        record.write_bytes(before + b"tampered,,\n")
        with self.assertRaises(LayoutError):
            layout.verify_layout(self.root)

    def test_changed_original_wheel_record_content_is_rejected_before_any_deletion(self):
        self.write("vendor/six.py", "VALUE = 2\n")
        self.write("vendor/six-1.dist-info/RECORD", "six.py,sha256=AAAA,10\n")
        with self.assertRaises(LayoutError):
            self.aggregate(self.policy(modules=["six.py"]))
        self.assert_no_assembly()
        self.assertTrue((self.root / "vendor/six.py").is_file())

    def test_reusable_reader_does_not_rescan_or_rehash_archive_per_file(self):
        self.aggregate(self.package())
        with layout.load_layout(self.root) as view:
            with patch.object(layout, "tree_files", side_effect=AssertionError("rescan")), patch.object(layout, "sha256_file", side_effect=AssertionError("rehash")), patch.object(zipfile, "ZipFile", side_effect=AssertionError("reparse")):
                for name, data in self.original.items():
                    self.assertEqual(view.read_bytes(name), data)
                self.assertEqual(len(view.files("vendor")), len(self.original))
        with self.assertRaises(LayoutError):
            view.read_bytes(next(iter(self.original)))

    def test_reader_rejects_container_changed_after_constructor(self):
        self.aggregate(self.package())
        with layout.load_layout(self.root) as view:
            path = self.root / "vendor.zip"
            with path.open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaises(LayoutError):
                view.read_bytes(next(iter(self.original)))

    def test_loose_legacy_view_and_missing_manifest_fail_closed_for_runtime_zip(self):
        self.write("a.py", "# loose\n")
        with layout.load_layout(self.root) as view:
            self.assertEqual(view.files(), ("a.py",))
            self.assertEqual(view.read_bytes("a.py"), b"# loose\n")
        self.write("vendor.zip", b"not a container")
        with self.assertRaises(LayoutError):
            layout.verify_layout(self.root)

    def test_missing_corrupt_and_undeclared_containers_are_rejected(self):
        self.aggregate(self.package())
        path = self.root / "vendor.zip"
        data = path.read_bytes()
        path.unlink()
        with self.assertRaises(LayoutError):
            layout.verify_layout(self.root)
        path.write_bytes(data + b"corrupt")
        with self.assertRaises(LayoutError):
            layout.verify_layout(self.root)
        path.write_bytes(data)
        self.write("app.zip", b"undeclared")
        with self.assertRaises(LayoutError):
            layout.verify_layout(self.root)

    def test_disk_shadow_and_new_files_in_relocated_whole_package_fail_closed(self):
        self.aggregate(self.package())
        for name in ("vendor/archivetest_fixture/value.py", "vendor/archivetest_fixture/new.py", "archivetest_fixture/__init__.py"):
            with self.subTest(name=name):
                path = self.write(name, "# shadow\n")
                with self.assertRaises(LayoutError):
                    layout.verify_layout(self.root)
                path.unlink()
                if not any(path.parent.iterdir()):
                    path.parent.rmdir()

    def test_single_module_loose_bytecode_shadow_is_rejected(self):
        self.write("vendor/six.py", "VALUE = 1\n")
        self.aggregate(self.policy(modules=["six.py"]))
        self.write("vendor/six.pyc", b"old bytecode")
        with self.assertRaises(LayoutError):
            layout.verify_layout(self.root)

    def test_duplicate_case_escape_and_noncanonical_zip_members_are_rejected(self):
        self.aggregate(self.package())
        original = (self.root / "vendor.zip").read_bytes()
        original_manifest = (self.root / layout.MANIFEST_NAME).read_bytes()
        for name in ("archivetest_fixture/value.py", "ARCHIVETEST_FIXTURE/value.py", "../escape.py", "bad\\path.py", "/absolute.py"):
            with self.subTest(name=name):
                (self.root / "vendor.zip").write_bytes(original)
                (self.root / layout.MANIFEST_NAME).write_bytes(original_manifest)
                self.rewrite_zip(lambda entries: entries + [(zipfile.ZipInfo(name, layout.TIMESTAMP), b"# bad\n")])
                with self.assertRaises(LayoutError):
                    layout.verify_layout(self.root)

    def test_deflate_wrong_timestamp_and_symlink_members_are_rejected_even_with_new_container_hash(self):
        self.aggregate(self.package())
        original = (self.root / "vendor.zip").read_bytes()
        original_manifest = (self.root / layout.MANIFEST_NAME).read_bytes()
        for mutation in ("deflate", "time", "link"):
            with self.subTest(mutation=mutation):
                (self.root / "vendor.zip").write_bytes(original)
                (self.root / layout.MANIFEST_NAME).write_bytes(original_manifest)
                def mutate(entries):
                    info, data = next((info, data) for info, data in entries if not info.is_dir())
                    if mutation == "deflate":
                        info.compress_type = zipfile.ZIP_DEFLATED
                    elif mutation == "time":
                        info.date_time = (2020, 1, 1, 0, 0, 0)
                    else:
                        info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    return entries
                self.rewrite_zip(mutate)
                with self.assertRaises(LayoutError):
                    layout.verify_layout(self.root)

    def test_member_hash_manifest_input_inventory_and_json_duplicates_are_checked(self):
        self.aggregate(self.package())
        original = (self.root / layout.MANIFEST_NAME).read_bytes()
        document = self.manifest()
        entry = next(entry for entry in document["archives"][0]["members"] if entry["kind"] == "file")
        entry["sha256"] = "0" * 64
        self.save_manifest(document)
        with self.assertRaises(LayoutError):
            layout.verify_layout(self.root)
        (self.root / layout.MANIFEST_NAME).write_bytes(original)
        with (self.root / layout.INPUTS_NAME).open("ab") as stream:
            stream.write(b" ")
        with self.assertRaises(LayoutError):
            layout.verify_layout(self.root)
        (self.root / layout.MANIFEST_NAME).write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        with self.assertRaises(LayoutError):
            layout.verify_layout(self.root)

    def test_invalid_paths_policy_collisions_and_overlaps_fail_before_writes(self):
        self.write("vendor/six.py", "VALUE = 1\n")
        for name in ("../six.py", "six.py/", "C:/six.py", "CON.py", "bad\\six.py"):
            with self.subTest(name=name), self.assertRaises(LayoutError):
                self.aggregate(self.policy(modules=[name]))
            self.assert_no_assembly()
        policy = self.policy(modules=["six.py", "six.py"])
        with self.assertRaises(LayoutError):
            self.aggregate(policy)
        self.assert_no_assembly()

    def test_preexisting_archive_record_or_claim_refuses_reentry(self):
        policy = self.package()
        for name in ("vendor.zip", "unknown.zip", "archive-layout.json", layout.MANIFEST_NAME, layout.INPUTS_NAME, layout.MARKER_NAME):
            with self.subTest(name=name):
                path = self.write(name, b"preexisting")
                with self.assertRaises(LayoutError):
                    self.aggregate(policy)
                self.assertEqual(path.read_bytes(), b"preexisting")
                path.unlink()
        self.aggregate(policy)
        with self.assertRaises(LayoutError):
            self.aggregate(policy)

    def test_release_seed_frozen_and_external_freeze_records_are_rejected(self):
        policy = self.package()
        original = self.root
        for relative in ("release/candidate", "build/seed/candidate", "build/frozen-candidate"):
            with self.subTest(relative=relative):
                self.root = self.project / relative
                self.root.mkdir(parents=True)
                with self.assertRaises(LayoutError):
                    self.aggregate(policy)
                self.assert_no_assembly()
        self.root = original
        audit = self.project / "build/audit"
        audit.mkdir()
        (audit / "not-named-freeze.json").write_text(json.dumps({"purpose": "immutable-review-product-not-approval", "package_root": str(self.root)}), encoding="utf-8")
        with self.assertRaises(LayoutError):
            self.aggregate(policy)
        self.assert_no_assembly()

    def test_occupied_candidate_is_rejected_without_killing_or_writing(self):
        policy = self.package()
        with self.assertRaises(LayoutError):
            self.aggregate(policy, occupancy_check=lambda _root: [{"pid": 123, "executable": "fixture"}])
        self.assert_no_assembly()

    def test_hardlink_and_junction_inputs_are_rejected_before_writes(self):
        policy = self.package()
        target = self.write("outside.py", "# owned fixture\n", root=self.project / "build")
        link = self.root / "vendor/hardlink.py"
        os.link(target, link)
        with self.assertRaises(LayoutError):
            self.aggregate(policy)
        self.assert_no_assembly()
        link.unlink()
        junction = self.root / "linked"
        outside = self.project / "build/outside"
        outside.mkdir()
        if os.name == "nt":
            subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)], capture_output=True, check=True)
        else:
            junction.symlink_to(outside, target_is_directory=True)
        try:
            with self.assertRaises(LayoutError):
                self.aggregate(policy)
            self.assert_no_assembly()
        finally:
            if os.name == "nt":
                junction.rmdir()
            else:
                junction.unlink()
        self.assertTrue(outside.is_dir())

    def test_all_archives_preflight_before_any_source_is_deleted(self):
        self.write("vendor/six.py", "VALUE = 1\n")
        self.write("vendor/badpkg/__init__.py", "# unchanged\n")
        self.write("vendor/badpkg/native.pyd", b"native")
        policy = self.policy(modules=["six.py"])
        policy["archives"].append({"path": "zbad.zip", "source_prefix": "vendor", "packages": ["badpkg"]})
        with self.assertRaises(LayoutError):
            self.aggregate(policy)
        self.assert_no_assembly()
        self.assertEqual((self.root / "vendor/six.py").read_bytes(), b"VALUE = 1\n")

    def test_changed_input_before_commit_is_not_deleted_or_overwritten(self):
        policy = self.package()
        calls = 0
        def occupancy(_root):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.write("vendor/archivetest_fixture/value.py", "VALUE = 99\n")
            return []
        with self.assertRaises(LayoutError):
            self.aggregate(policy, occupancy_check=occupancy)
        self.assertTrue(all((self.root / name).exists() for name in self.original))
        self.assertEqual((self.root / "vendor/archivetest_fixture/value.py").read_bytes(), b"VALUE = 99\n")
        self.assertEqual(layout.read_json(self.root / layout.MARKER_NAME)["state"], "failed")
        with self.assertRaises(LayoutError):
            layout.verify_layout(self.root)

    def test_unexpected_unlink_failure_restores_already_removed_inputs(self):
        policy = self.package()
        original_unlink = Path.unlink
        count = 0
        def fail_once(path, *args, **kwargs):
            nonlocal count
            if path.as_posix().endswith("archivetest_fixture/value.py"):
                count += 1
                if count == 1:
                    raise PermissionError("fixture simulated lock")
            return original_unlink(path, *args, **kwargs)
        with patch.object(Path, "unlink", fail_once), self.assertRaises(PermissionError):
            self.aggregate(policy)
        for name, data in self.original.items():
            self.assertEqual((self.root / name).read_bytes(), data)
        self.assertEqual(layout.read_json(self.root / layout.MARKER_NAME)["state"], "failed")
        self.assertTrue((self.root / layout.INPUTS_NAME).is_file())
        self.assertFalse((self.root / "vendor.zip").exists())

    def test_empty_package_directories_are_preserved_but_empty_caches_are_rejected(self):
        policy = self.package()
        empty = self.root / "vendor/archivetest_fixture/empty-data"
        empty.mkdir()
        cache = self.root / "vendor/archivetest_fixture/__pycache__"
        cache.mkdir()
        with self.assertRaisesRegex(LayoutError, "cache/native/model/state"):
            self.aggregate(policy)
        self.assert_no_assembly()
        cache.rmdir()
        document = self.aggregate(policy)
        entry = next(item for item in document["archives"][0]["members"] if item["member"] == "archivetest_fixture/empty-data/")
        self.assertEqual(entry["logical_path"], "vendor/archivetest_fixture/empty-data")
        self.assertEqual(entry["sha256"], layout.EMPTY_SHA256)
        self.assertEqual(entry["bytes"], 0)
        self.assertFalse(empty.exists())
        layout.verify_layout(self.root, source_hashes=self.external_hashes())

    def test_reader_rejects_native_model_bytecode_or_metadata_members_from_forged_manifest(self):
        self.aggregate(self.package())
        original_zip = (self.root / "vendor.zip").read_bytes()
        original_manifest = (self.root / layout.MANIFEST_NAME).read_bytes()
        for target in ("archivetest_fixture/native.pyd", "archivetest_fixture/weights.gguf", "archivetest_fixture/old.pyc",
                       "archivetest_fixture/__pycache__/value.py", "archivetest_fixture/extra.dist-info/RECORD"):
            with self.subTest(target=target):
                (self.root / "vendor.zip").write_bytes(original_zip)
                (self.root / layout.MANIFEST_NAME).write_bytes(original_manifest)
                def mutate(entries):
                    for info, _data in entries:
                        if info.filename == "archivetest_fixture/value.py":
                            info.filename = target
                    return sorted(entries, key=lambda pair: pair[0].filename)
                self.rewrite_zip(mutate)
                document = self.manifest()
                entry = next(item for item in document["archives"][0]["members"] if item["member"] == "archivetest_fixture/value.py")
                entry["member"] = target
                entry["logical_path"] = "vendor/" + target
                entry["source"]["logical_path"] = entry["logical_path"]
                document["archives"][0]["members"].sort(key=lambda item: item["member"])
                self.save_manifest(document)
                with self.assertRaisesRegex(LayoutError, "must remain external"):
                    layout.verify_layout(self.root)

    def test_directory_entries_must_stay_inside_declared_whole_package_closure(self):
        self.aggregate(self.package())
        info = zipfile.ZipInfo("unrelated/", layout.TIMESTAMP)
        info.create_system = 3
        info.external_attr = (stat.S_IFDIR | 0o755) << 16 | 0x10
        self.rewrite_zip(lambda entries: sorted(entries + [(info, b"")], key=lambda pair: pair[0].filename))
        document = self.manifest()
        document["archives"][0]["members"].append({"kind": "directory", "logical_path": "vendor/unrelated", "member": "unrelated/", "bytes": 0,
                                                   "sha256": layout.EMPTY_SHA256,
                                                   "source": {"logical_path": "vendor/unrelated", "sha256": layout.EMPTY_SHA256, "record_owner": None, "record_path": None}})
        document["archives"][0]["members"].sort(key=lambda item: item["member"])
        self.save_manifest(document)
        with self.assertRaisesRegex(LayoutError, "outside its selected package"):
            layout.verify_layout(self.root)

    def test_reserved_case_unknown_root_zip_and_failed_marker_are_rejected(self):
        self.aggregate(self.package())
        (self.root / "vendor.zip").rename(self.root / "Vendor.zip")
        with self.assertRaisesRegex(LayoutError, "Noncanonical case"):
            layout.verify_layout(self.root)
        (self.root / "Vendor.zip").rename(self.root / "vendor.zip")
        extra = self.write("extra.zip", b"undeclared")
        with self.assertRaisesRegex(LayoutError, "Undeclared/missing"):
            layout.verify_layout(self.root)
        extra.unlink()
        marker = layout.read_json(self.root / layout.MARKER_NAME)
        marker["state"] = "failed"
        (self.root / layout.MARKER_NAME).write_text(json.dumps(marker), encoding="utf-8")
        with self.assertRaisesRegex(LayoutError, "assembly marker"):
            layout.verify_layout(self.root)

    def test_constructor_failure_closes_every_open_archive_handle(self):
        self.aggregate(self.package())
        opened = []
        real_zip = zipfile.ZipFile
        def capture(*args, **kwargs):
            container = real_zip(*args, **kwargs)
            opened.append(container)
            return container
        with patch.object(zipfile, "ZipFile", capture), patch.object(layout, "verify_archive", side_effect=LayoutError("fixture verification failure")):
            with self.assertRaisesRegex(LayoutError, "fixture verification"):
                layout.load_layout(self.root)
        self.assertTrue(opened)
        self.assertTrue(all(container.fp is None for container in opened))
        (self.root / "vendor.zip").rename(self.root / "closed.zip")

    def test_external_hashes_bind_whole_package_member_set_not_only_existing_members(self):
        policy = self.package()
        hashes = {**self.external_hashes(), "vendor/archivetest_fixture/missing.py": "0" * 64}
        with self.assertRaisesRegex(LayoutError, "Whole package member set"):
            self.aggregate(policy, source_hashes=hashes)
        self.assert_no_assembly()
        self.aggregate(policy)
        with self.assertRaisesRegex(LayoutError, "Whole package differs"):
            layout.verify_layout(self.root, source_hashes=hashes)

    def test_self_consistent_rewritten_layout_still_requires_external_source_proof(self):
        self.aggregate(self.package())
        original_hashes = self.external_hashes()
        replacement = b"VALUE = 99\n"
        def mutate(entries):
            return [(info, replacement if info.filename == "archivetest_fixture/value.py" else data) for info, data in entries]
        self.rewrite_zip(mutate)
        document = self.manifest()
        entry = next(item for item in document["archives"][0]["members"] if item["member"] == "archivetest_fixture/value.py")
        entry.update({"bytes": len(replacement), "sha256": layout.sha256_bytes(replacement)})
        entry["source"]["sha256"] = entry["sha256"]
        inventory = layout.read_json(self.root / layout.INPUTS_NAME)
        inventory["files"][entry["logical_path"]] = {"bytes": entry["bytes"], "sha256": entry["sha256"], "source": entry["source"]}
        (self.root / layout.INPUTS_NAME).write_text(json.dumps(inventory), encoding="utf-8")
        document["inputs_manifest"].update({"bytes": (self.root / layout.INPUTS_NAME).stat().st_size,
                                            "sha256": layout.sha256_file(self.root / layout.INPUTS_NAME)})
        self.save_manifest(document)
        self.assertEqual(layout.verify_layout(self.root)["source_binding"], "not-proven-by-layout")
        with self.assertRaisesRegex(LayoutError, "externally supplied source"):
            layout.verify_layout(self.root, source_hashes=original_hashes)

    def test_host_product_entry_points_cannot_be_added_to_policy(self):
        self.write("main.py", "# entry point stays loose\n")
        policy = self.policy(modules=["main.py"], prefix="", archive="app.zip", kind="host")
        with self.assertRaisesRegex(LayoutError, "entry points stay loose"):
            self.aggregate(policy, kind="host")
        self.assert_no_assembly()


LayoutError = layout.LayoutError

if __name__ == "__main__":
    unittest.main(verbosity=2)
