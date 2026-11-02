"""重装工具的微型合成tar.xz正反例，不运行产品或模型。"""
import hashlib
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("review_archive_install", ROOT / "build/tools/reinstall_review_archives.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
WORK = ROOT / "build/tmp/startup-small-files-20261028-r1/review-install-fixtures"


class ReviewArchiveInstallTests(unittest.TestCase):
    def setUp(self):
        WORK.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="fixture-", dir=WORK)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def archive(self, name="data/value.txt", data=b"original bytes", *, symlink=False):
        path = self.root / "fixture.tar.xz"
        with tarfile.open(path, "w:xz") as archive:
            info = tarfile.TarInfo(name)
            if symlink:
                info.type = tarfile.SYMTYPE
                info.linkname = "../outside"
                archive.addfile(info)
            else:
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return path

    def test_real_archive_restores_exact_payload_in_new_directory(self):
        path = self.archive()
        output = self.root / "fresh"
        expected = {"data/value.txt": hashlib.sha256(b"original bytes").hexdigest()}
        result = module.safe_extract(path, output, expected)
        self.assertTrue(result["payloadVerified"])
        self.assertEqual((output / "data/value.txt").read_bytes(), b"original bytes")
        with self.assertRaises(FileExistsError):
            module.safe_extract(path, output, expected)

    def test_mismatch_and_missing_input_members_are_rejected(self):
        path = self.archive()
        for index, expected in enumerate(({"data/value.txt": "0" * 64},
                                           {"other.txt": hashlib.sha256(b"original bytes").hexdigest()})):
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                module.safe_extract(path, self.root / ("fresh" + str(index)), expected)

    def test_escape_is_rejected_without_writing_outside(self):
        path = self.archive("../outside.txt")
        with self.assertRaises((ValueError, RuntimeError)):
            module.safe_extract(path, self.root / "fresh", {"value.txt": "0" * 64})
        self.assertFalse((self.root / "outside.txt").exists())

    def test_links_are_rejected_not_materialized(self):
        path = self.archive("link", symlink=True)
        with self.assertRaises(ValueError):
            module.safe_extract(path, self.root / "fresh", {"link": "0" * 64})
        self.assertFalse((self.root / "fresh/link").exists())

    def test_fast_encoder_preserves_payload_and_rejects_nested_output(self):
        spec = importlib.util.spec_from_file_location("fast_review_fixture", ROOT / "build/tools/package_local_review_fast.py")
        fast = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fast)
        source = self.root / "source"
        source.mkdir()
        data = b"VALUE = 42\n"
        (source / "value.py").write_bytes(data)
        with self.assertRaises(ValueError):
            fast.create_fast_archive(source, source / "bad.tar.xz")
        self.assertFalse((source / "bad.tar.xz").exists())
        archive = self.root / "fast.tar.xz"
        result = fast.create_fast_archive(source, archive)
        self.assertEqual(result["compression_preset"], 1)
        expected = {"value.py": hashlib.sha256(data).hexdigest()}
        self.assertTrue(module.safe_extract(archive, self.root / "restored", expected)["payloadVerified"])
        with self.assertRaises(FileExistsError):
            fast.create_fast_archive(source, archive)
        self.assertFalse(list(self.root.glob("*.tar")))

    def test_result_is_published_only_after_complete_write(self):
        output = self.root / "audit"
        output.mkdir()
        module.write_result(output, {"status": "PASS", "value": 42})
        self.assertEqual(module.layout.read_json(output / "result.json")["value"], 42)
        self.assertFalse((output / "result.incomplete.json").exists())

    def test_disk_write_failure_does_not_publish_formal_pass(self):
        from unittest import mock
        output = self.root / "audit"
        output.mkdir()
        with mock.patch.object(module.json, "dump", side_effect=OSError(28, "simulated disk full")):
            with self.assertRaises(OSError):
                module.write_result(output, {"status": "PASS"})
        self.assertFalse((output / "result.json").exists())
        self.assertTrue((output / "result.incomplete.json").exists())

    def test_explicit_task_root_is_separate_from_historical_default(self):
        from unittest import mock
        repository = self.root / "repository"
        task = repository / "build/tmp/new-local-update"
        old = repository / "build/tmp/startup-small-files-20261028-r1"
        task.mkdir(parents=True)
        old.mkdir()
        with mock.patch.object(module, "ROOT", repository):
            self.assertEqual(module.installation_work_root(task), task)
            self.assertEqual(module.installation_work_root(), old)

    def test_work_root_rejects_parent_nested_and_external_directories(self):
        from unittest import mock
        repository = self.root / "repository"
        boundary = repository / "build/tmp"
        nested = boundary / "task/nested"
        nested.mkdir(parents=True)
        outside = self.root / "outside"
        outside.mkdir()
        with mock.patch.object(module, "ROOT", repository):
            for path in (boundary, nested, outside, boundary / "missing"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    module.installation_work_root(path)

    def test_capacity_failure_precedes_target_creation(self):
        from types import SimpleNamespace
        from unittest import mock
        source = self.root / "source"
        source.mkdir()
        (source / "value.txt").write_bytes(b"data")
        records = {"base": (None, {"inputRoot": str(source),
                   "payload": {"value.txt": hashlib.sha256(b"data").hexdigest()}}, None)}
        target = self.root / "new-install"
        with mock.patch("shutil.disk_usage", return_value=SimpleNamespace(free=0)):
            with self.assertRaises(OSError) as error:
                module.verify_install_capacity(records, target)
        self.assertEqual(error.exception.errno, 28)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
