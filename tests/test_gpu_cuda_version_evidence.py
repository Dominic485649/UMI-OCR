"""隔离 mock 许可门禁：旧 CUDA 证据不得自动授权新运行库。"""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cuda_version_evidence_test", ROOT / "build/tools/verify_release_evidence.py")
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class CudaVersionEvidenceTests(unittest.TestCase):
    def verify(self, version):
        with tempfile.TemporaryDirectory(prefix="cuda-evidence-", dir=ROOT / "build") as directory:
            root = Path(directory)
            vendor = root / "vendor"
            binary = vendor / "nvidia/cublas/bin/cublas64_12.dll"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"mock CUDA binary; never executed")
            snapshot = {"verified": True, "path": "legacy-eula.html", "sha256": "1" * 64}
            with patch.object(M, "cuda_eula_snapshot", return_value=snapshot), patch.object(M, "scan_pe_import_tables", return_value={"import_tables": [], "scan_errors": []}):
                return M.verify_nvidia(root, vendor, cuda_version=version)

    def test_new_runtime_never_inherits_old_redistribution_approval(self):
        result = self.verify("12.9")
        self.assertEqual(result["status"], "BLOCK")
        self.assertEqual(result["applicable_cuda_version"], "12.9")
        item = result["files"][0]
        self.assertFalse(item["redistribution_allowed"])
        self.assertEqual(item["applicable_cuda_version"], "12.9")
        self.assertTrue(item["evidence"]["snapshot"]["snapshot_integrity_verified"])
        self.assertFalse(item["evidence"]["snapshot"]["verified"])
        self.assertEqual(item["evidence"]["snapshot"]["legacy_cuda_scope"], "12.6")
        self.assertIn("12.9", item["reason"])

    def test_legacy_component_keeps_its_existing_evidence_scope(self):
        result = self.verify("12.6")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["applicable_cuda_version"], "12.6")
        self.assertTrue(result["files"][0]["redistribution_allowed"])


if __name__ == "__main__":
    unittest.main()
