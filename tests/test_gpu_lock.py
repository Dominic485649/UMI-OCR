"""原生闭包绑定项目自有入口，且不受测试证据更新影响。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gpu_lock", ROOT / "build/tools/freeze_gpu_runtime.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GpuLockTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="umi-gpu-lock-", dir=ROOT / "build")
        self.plugin = Path(self.temporary.name)
        (self.plugin / "umi-plugin.json").write_text(json.dumps({"id": "custom", "version": "3.0.4"}), encoding="utf-8")
        (self.plugin / "native.dll").write_bytes(b"native fixture")
        (self.plugin / "api.py").write_text("# source", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def generate(self):
        module.generate(self.plugin)
        return json.loads((self.plugin / "runtime.lock.json").read_text("utf-8"))

    def test_evidence_and_cache_do_not_change_lock(self):
        self.generate()
        first = (self.plugin / "runtime.lock.json").read_bytes()
        (self.plugin / "gpu-e2e-evidence.json").write_text('{"tested":"new evidence"}', encoding="utf-8")
        cache = self.plugin / "__pycache__"
        cache.mkdir()
        (cache / "api.pyc").write_bytes(b"cache fixture")
        self.generate()
        self.assertEqual((self.plugin / "runtime.lock.json").read_bytes(), first)

    def test_only_project_worker_exe_is_locked(self):
        worker = self.plugin / "UmiOCR-CudaWorker.exe"
        worker.write_bytes(b"project launcher fixture")
        (self.plugin / "unrelated.exe").write_bytes(b"not a project launcher")
        vendor = self.plugin / "vendor/tools"
        vendor.mkdir(parents=True)
        (vendor / worker.name).write_bytes(b"not the project launcher location")
        record = self.generate()
        entries = {item["path"]: item["sha256"] for item in record["files"]}
        self.assertEqual(set(entries), {"native.dll", worker.name})
        self.assertEqual(entries[worker.name], hashlib.sha256(worker.read_bytes()).hexdigest())
        self.assertEqual(record["version"], "3.0.4")
        self.assertEqual(record["nativeBinaryCount"], 2)

    def test_worker_executable_bytes_are_bound(self):
        worker = self.plugin / "UmiOCR-CudaWorker.exe"
        worker.write_bytes(b"first launcher")
        first = self.generate()
        worker.write_bytes(b"second launcher")
        second = self.generate()
        self.assertNotEqual(first["files"], second["files"])


if __name__ == "__main__":
    unittest.main()
