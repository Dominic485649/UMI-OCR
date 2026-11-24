"""只核验本项目内的小型合成容器，不启动产品、模型或第三方代码。"""
import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build/tools"))
from audit_runtime_archives import audit
from merge_runtime import aggregate_runtime
from runtime_archive_layout import LayoutError

WORK = ROOT / "build/tmp/startup-small-files-20261028-r1/archive-audit-tests"


class RuntimeArchiveAuditTests(unittest.TestCase):
    def setUp(self):
        WORK.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="audit-", dir=WORK)
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        self.stage = self.project / "build/staging/candidate"
        self.data = self.stage / "UmiOCR-data"
        self.data.mkdir(parents=True)

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def aggregate(self, root, kind):
        return aggregate_runtime(root, kind=kind, project_root=self.project,
                                 occupancy_check=lambda unused: [])

    def host(self, data=None, name="py_src/run.py"):
        if data is None:
            data = b"raise RuntimeError('audit must never execute this source')\n"
        self.write(self.data / name, data)
        source = {"host/UmiOCR-data/" + name: hashlib.sha256(data).hexdigest()}
        self.write(self.stage / "source-snapshot.json", json.dumps(source).encode())
        self.aggregate(self.data, "host")
        return data

    def plugin(self, *, record=True):
        plugin = self.data / "plugins/example"
        data = b"VALUE = 'original wheel content'\n"
        self.write(plugin / "vendor/six.py", data)
        if record:
            checksum = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
            self.write(plugin / "vendor/six-1.0.dist-info/RECORD",
                       f"six.py,sha256={checksum},{len(data)}\n".encode())
            self.write(plugin / "vendor/six-1.0.dist-info/METADATA", b"Name: six\nVersion: 1.0\n")
        self.aggregate(plugin, "plugin")
        return plugin, data

    def test_loose_layout_is_not_archive_acceptance(self):
        self.assertEqual(audit(self.data)["status"], "NOT_INCLUDED")

    def test_host_original_source_is_bound_without_execution(self):
        data = self.host()
        report = audit(self.data)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["archived_paths"], ["py_src/run.py"])
        self.assertEqual(report["members"][0]["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(report["members"][0]["binding"], "canonical-host-source")
        self.assertFalse((self.data / "py_src/run.py").exists())

    def test_host_missing_or_different_source_is_rejected(self):
        self.host()
        path = self.stage / "source-snapshot.json"
        path.unlink()
        with self.assertRaisesRegex(LayoutError, "源码清单"):
            audit(self.data)
        path.write_text(json.dumps({"host/UmiOCR-data/py_src/run.py": "0" * 64}), encoding="utf-8")
        with self.assertRaisesRegex(LayoutError, "对应源码不一致"):
            audit(self.data)

    def test_third_party_is_bound_to_retained_record(self):
        plugin, data = self.plugin()
        hashes = {"vendor/six.py": hashlib.sha256(data).hexdigest()}
        report = audit(plugin, source_hashes=hashes)
        self.assertTrue(report["externalInputHashesVerified"])
        self.assertEqual(report["members"][0]["binding"], "retained-wheel-RECORD+external-input-hashes")

    def test_self_recorded_original_hash_is_not_third_party_provenance(self):
        plugin, unused = self.plugin(record=False)
        with self.assertRaisesRegex(LayoutError, "原wheel RECORD来源"):
            audit(plugin)

    def test_public_text_scan_reaches_archived_source(self):
        self.host(b"VALUE = 'private_sentinel'\n")
        self.assertEqual(audit(self.data)["status"], "PASS")
        with self.assertRaisesRegex(LayoutError, "容器源码内容"):
            audit(self.data, forbidden_text=["PRIVATE_SENTINEL"])

    def test_public_name_scan_reaches_directory_members(self):
        self.host(b"VALUE = 1\n", "py_src/blocked_dir/run.py")
        with self.assertRaisesRegex(LayoutError, "运行容器成员"):
            audit(self.data, forbidden_names=["blocked_dir"])

    def test_only_exact_retired_plugin_rejection_line_is_exempt(self):
        self.host(b"BLOCKED = {\n    'win32_PaddleOCRVL_1_6',\n}\n",
                  "py_src/plugins_controller/manifest.py")
        report = audit(self.data, forbidden_text=["PaddleOCRVL"])
        self.assertTrue(report["publicRulesApplied"])

    def test_retired_plugin_active_import_is_not_exempt(self):
        self.host(b"from win32_PaddleOCRVL_1_6 import something\n",
                  "py_src/plugins_controller/manifest.py")
        with self.assertRaisesRegex(LayoutError, "容器源码内容"):
            audit(self.data, forbidden_text=["PaddleOCRVL"])

    def test_generic_downloader_only_exempts_exact_format_literals(self):
        self.host('SUFFIX = ".gguf"\nMAGIC = b"GGUF"\nERROR = "下载内容不是 GGUF 模型。"\n'.encode("utf-8"),
                  "py_src/plugins_controller/model_downloads.py")
        self.assertEqual(audit(self.data, forbidden_text=["gguf"])["status"], "PASS")

    def test_downloader_does_not_exempt_active_plugin_import_or_model_url(self):
        from audit_runtime_archives import public_content
        for data in (b'from win32_PaddleOCRVL_1_6 import runtime\n',
                     b'URL = "https://example.com/private-model.gguf"\n'):
            with self.subTest(data=data), self.assertRaises(LayoutError):
                public_content("py_src/plugins_controller/model_downloads.py", data, ["PaddleOCRVL", "gguf"])
        with self.assertRaises(LayoutError):
            public_content("py_src/other.py", b'SUFFIX = ".gguf"\n', ["gguf"])

    def test_external_source_mismatch_is_rejected(self):
        plugin, unused = self.plugin()
        with self.assertRaises(LayoutError):
            audit(plugin, source_hashes={"vendor/six.py": "0" * 64})

    def test_missing_container_is_rejected_not_reported_loose(self):
        plugin, unused = self.plugin()
        (plugin / "vendor.zip").unlink()
        with self.assertRaises(LayoutError):
            audit(plugin)


if __name__ == "__main__":
    unittest.main(verbosity=2)
