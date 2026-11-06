"""最简运行包与外置材料绑定的定向回归。"""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("minimal_fixture", ROOT / "build/tools/prepare_minimal_distribution.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
WORK = ROOT / "build/tmp/minimal-313-20261105-r1/distribution-fixtures"


class MinimalDistributionTests(unittest.TestCase):
    def setUp(self):
        WORK.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=WORK)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.complete = self.root / "complete"
        self.complete.mkdir()
        self.output = self.root / "runtime"
        self.report = self.root / "record.json"

    def put(self, name, value, root=None):
        path = (root or self.complete) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else value.encode("utf-8"))

    def fixture(self, component="base"):
        if component == "base":
            self.put("Umi-OCR.exe", b"launcher")
            self.put("UmiOCR-data/about.json", json.dumps({"version": {"major": 3, "minor": 1, "patch": 3}}))
            self.put("UmiOCR-data/runtime/python.exe", b"runtime")
            self.put("UmiOCR-data/runtime-archives.json", "{}")
            self.put("UmiOCR-data/runtime-archive-inputs.json", "{}")
            metadata = self.complete
        else:
            plugin = m.IDS[component]
            self.put("UmiOCR-data/plugins/" + plugin + "/umi-plugin.json", json.dumps({"id": plugin, "version": "3.1.3"}))
            self.put("UmiOCR-data/plugins/" + plugin + "/worker.py", b"print('worker')")
            metadata = self.complete / "LICENSES/plugins" / plugin
        for name, value in (("COPYING", "AGPL original"), ("LICENSE", "MIT original"),
                            ("source/program.py", "original source"), ("source-snapshot.zip", b"frozen zip"),
                            ("LICENSES/Apache-2.0.txt", "Apache original"),
                            ("LICENSES/markdown-preview/markdown-it/LICENSE", "npm MIT copyright original"),
                            ("LICENSES/RELEASE_EVIDENCE.json", "{}"),
                            ("LICENSES/RELEASE_EVIDENCE.md", "audit only")):
            self.put(name, value, metadata)
        return metadata

    def test_runtime_has_no_embedded_source_or_audit_and_preserves_runtime(self):
        self.fixture()
        before = m.payload(self.complete)
        result = m.prepare(self.complete, self.output, "base", self.report)
        self.assertEqual(m.payload(self.complete), before)
        self.assertEqual(m.verify(self.report)["runtimePayload"], result["runtimePayload"])
        names = set(result["runtimePayload"])
        self.assertFalse(any(name.startswith(("source", "LICENSES/")) or "EVIDENCE" in name for name in names))
        self.assertNotIn("UmiOCR-data/runtime-archive-inputs.json", names)
        self.assertIn("UmiOCR-data/runtime-archives.json", names)
        self.assertEqual((self.output / "COPYING").read_text(), "AGPL original")
        notices = (self.output / "THIRD_PARTY_NOTICES.txt").read_text("utf-8")
        self.assertIn("Apache original", notices)
        self.assertIn("npm MIT copyright original", notices)

    def test_plugin_notices_stay_in_plugin_namespace(self):
        self.fixture("cuda")
        result = m.prepare(self.complete, self.output, "cuda", self.report)
        prefix = "UmiOCR-data/plugins/" + m.IDS["cuda"] + "/"
        self.assertTrue(all(name.startswith(prefix) for name in result["runtimePayload"]))
        self.assertFalse((self.output / "COPYING").exists())
        m.verify(self.report)

    def test_unknown_root_and_mixed_plugin_payload_fail_closed(self):
        self.fixture()
        self.put("unclassified.bin", b"unknown")
        with self.assertRaises(ValueError):
            m.prepare(self.complete, self.output, "base", self.report)
        self.assertFalse(self.output.exists())
        (self.complete / "unclassified.bin").unlink()
        self.put("UmiOCR-data/plugins/other/worker.py", "pass")
        with self.assertRaises(ValueError):
            m.prepare(self.complete, self.output, "base", self.report)

    def test_changed_execution_or_external_source_is_rejected(self):
        self.fixture()
        m.prepare(self.complete, self.output, "base", self.report)
        self.put("UmiOCR-data/runtime/python.exe", b"changed", self.output)
        with self.assertRaises(ValueError):
            m.verify(self.report)
        self.put("UmiOCR-data/runtime/python.exe", b"runtime", self.output)
        self.put("source/program.py", "changed source")
        with self.assertRaises(ValueError):
            m.verify(self.report)

    def test_existing_outputs_links_and_running_inputs_are_rejected(self):
        self.fixture()
        with mock.patch.object(m.merge, "running_processes", return_value=[{"pid": 1}]), self.assertRaises(ValueError):
            m.prepare(self.complete, self.output, "base", self.report)
        self.output.mkdir()
        with self.assertRaises(ValueError):
            m.prepare(self.complete, self.output, "base", self.report)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_vl_external_source_and_legal_materials_are_bound_without_copying_runtime(self):
        original = self.fixture("vl")
        import shutil
        external = self.root / "complete-materials"
        shutil.copytree(original, external)
        self.put("VERSION", "3.1.3\n", external)
        self.put("source/native-source.txt", "locked native corresponding source", external)
        result = m.prepare(self.complete, self.output, "vl", self.report, metadata_root=external)
        self.assertEqual(result["metadataRoot"], str(external))
        self.assertIn("source/native-source.txt", result["externalMetadataPayload"])
        m.verify(self.report)
        self.put("source/native-source.txt", "changed", external)
        with self.assertRaisesRegex(ValueError, "外置对应源码"):
            m.verify(self.report)

    def test_external_materials_cannot_change_identity_or_replace_original_license(self):
        original = self.fixture("vl")
        import shutil
        external = self.root / "complete-materials"
        shutil.copytree(original, external)
        self.put("VERSION", "3.1.2\n", external)
        with self.assertRaisesRegex(ValueError, "版本"):
            m.prepare(self.complete, self.output, "vl", self.report, metadata_root=external)
        self.put("VERSION", "3.1.3\n", external)
        self.put("LICENSE", "different license", external)
        with self.assertRaisesRegex(ValueError, "原始许可"):
            m.prepare(self.complete, self.output, "vl", self.report, metadata_root=external)
        with self.assertRaisesRegex(ValueError, "只有独立"):
            m.external_metadata(original, external, "base", "3.1.3")
        self.assertFalse(self.output.exists())

    def test_real_archives_separate_runtime_and_source(self):
        self.fixture()
        record = m.prepare(self.complete, self.output, "base", self.report)
        source = self.root / record["correspondingSourceArchiveName"]
        result = m.package(self.report, self.root / "runtime.tar.xz", source)
        self.assertFalse(result["formalRelease"])
        import tarfile
        with tarfile.open(self.root / "runtime.tar.xz", "r:xz") as archive:
            self.assertFalse(any(name.startswith("source/") for name in archive.getnames()))
        with tarfile.open(source, "r:xz") as archive:
            names = archive.getnames()
            self.assertIn("source/program.py", names)
            self.assertNotIn("Umi-OCR.exe", names)
            self.assertFalse(any(name.startswith("UmiOCR-data/") for name in names))
        with self.assertRaises(FileExistsError):
            m.package(self.report, self.root / "runtime.tar.xz", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
