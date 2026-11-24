"""使用真实便携 Python 测试无 source/ 的恢复脚本，不执行归档内容。"""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "build/windows/Restore-ReleaseArchive.ps1"
WORK = ROOT / "build/tmp/release-313-public-20261106-r1/restore-fixtures"
HOST = Path(os.environ["UMI_RESTORE_TEST_HOST_ROOT"]) if os.environ.get("UMI_RESTORE_TEST_HOST_ROOT") else None
spec = importlib.util.spec_from_file_location("minimal_restore_chunks", ROOT / "build/tools/chunked_files.py")
chunks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chunks)


@unittest.skipUnless(os.name == "nt" and HOST and (HOST / "UmiOCR-data/runtime/python.exe").is_file(), "需要具名 Windows 便携主程序夹具")
class MinimalRestoreTests(unittest.TestCase):
    def setUp(self):
        WORK.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=WORK)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.parts, self.output = self.root / "parts", self.root / "output"
        self.parts.mkdir()
        self.output.mkdir()
        self.archive = self.root / "Umi-OCR-Plugin_v3.1.3_Windows_x64_PaddleVL.tar.xz"
        with tarfile.open(self.archive, "w:xz") as archive:
            content = b"SYNTHETIC RESTORE FIXTURE: never execute archive contents\n"
            item = tarfile.TarInfo("fixture.txt")
            item.size = len(content)
            archive.addfile(item, io.BytesIO(content))
        item = chunks.split_file(self.archive, self.parts, self.archive.name, "archive", 64)
        self.index = {"schema_version": 1, "format": "umi-archive-chunks-v1", "files": [item]}
        self.save()

    def save(self):
        (self.parts / "archive-chunks.json").write_text(json.dumps(self.index), encoding="utf-8")

    def run_restore(self):
        return subprocess.run([shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-File", str(SCRIPT),
                               "-UmiOCRRoot", str(HOST), "-PartsDirectory", str(self.parts),
                               "-OutputDirectory", str(self.output)], cwd=self.parts,
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace", timeout=30)

    def test_real_restore_needs_no_source_tree_and_ignores_planted_import(self):
        self.assertFalse((HOST / "source").exists())
        (self.parts / "json.py").write_text("raise RuntimeError('UNTRUSTED IMPORT EXECUTED')\n", encoding="utf-8")
        result = self.run_restore()
        self.assertEqual(result.returncode, 0, result.stdout)
        restored = self.output / self.archive.name
        self.assertEqual(restored.read_bytes(), self.archive.read_bytes())
        self.assertEqual(restored.stat().st_nlink, 1)
        self.assertIn("RESTORED_AND_SHA256_VERIFIED", result.stdout)
        with tarfile.open(restored, "r:xz") as archive:
            self.assertEqual(archive.getnames(), ["fixture.txt"])

    def test_existing_output_is_never_overwritten(self):
        target = self.output / self.archive.name
        target.write_bytes(b"existing user data")
        result = self.run_restore()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_bytes(), b"existing user data")

    def test_wrong_same_length_part_hash_never_becomes_final_archive(self):
        part = self.parts / self.index["files"][0]["parts"][0]["path"]
        content = part.read_bytes()
        part.write_bytes(bytes([content[0] ^ 1]) + content[1:])
        result = self.run_restore()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.output / self.archive.name).exists())
        self.assertIn("SHA-256", result.stdout)

    def test_unknown_fields_boolean_sizes_and_path_traversal_fail_closed(self):
        original = json.loads(json.dumps(self.index))
        for change in ("unknown", "boolean", "traversal"):
            self.index = json.loads(json.dumps(original))
            if change == "unknown":
                self.index["unexpected"] = True
            elif change == "boolean":
                self.index["files"][0]["bytes"] = True
            else:
                self.index["files"][0]["path"] = "../outside.tar.xz"
            self.save()
            with self.subTest(change=change):
                self.assertNotEqual(self.run_restore().returncode, 0)
                self.assertFalse((self.output / self.archive.name).exists())
        self.assertFalse((self.root / "outside.tar.xz").exists())

    def test_duplicate_json_keys_are_rejected(self):
        (self.parts / "archive-chunks.json").write_text('{"schema_version":1,"schema_version":1,"format":"umi-archive-chunks-v1","files":[]}', encoding="utf-8")
        result = self.run_restore()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("重复JSON键", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
