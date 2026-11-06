"""模型直链下载的有限夹具：不联网、不下载真实权重、不运行推理。"""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build/tmp/minimal-313-20261105-r1/download-fixtures"
spec = importlib.util.spec_from_file_location("model_download_fixture", ROOT / "UmiOCR-data/py_src/plugins_controller/model_downloads.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Response(io.BytesIO):
    status = 200
    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = headers if headers is not None else {"Content-Length": str(len(data))}
    def geturl(self):
        return "https://huggingface.co/locked/model.gguf"


class ModelDownloadTests(unittest.TestCase):
    def setUp(self):
        WORK.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=WORK)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "user-install/UmiOCR-data/plugins/example"
        self.root.mkdir(parents=True)
        self.data = b"GGUF" + b"\0" * 128
        self.resource = {"title": "测试模型", "kind": "file", "destination": "model.gguf",
            "files": [self.file("model.gguf", self.data)]}
        self.cancel = threading.Event()
        self.events = []

    def file(self, name, data):
        return {"name": name, "url": "https://huggingface.co/locked/" + name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def run_download(self, resource=None, response=None):
        opener = mock.Mock()
        opener.open.return_value = response or Response(self.data)
        return m.download_resource(self.root, resource or self.resource, self.cancel,
            lambda *event: self.events.append(event), opener=opener)

    def test_installs_under_actual_user_plugin_root_and_reuses_verified_file(self):
        result = self.run_download()
        target = self.root / "model/model.gguf"
        self.assertEqual(Path(result["path"]), target)
        self.assertEqual(target.read_bytes(), self.data)
        self.assertEqual(target.stat().st_nlink, 1)
        self.assertFalse(list((self.root / "model").glob(".download-*")))
        self.assertEqual(self.events[-1], (len(self.data), len(self.data)))
        with mock.patch.object(m.urllib.request, "build_opener", side_effect=AssertionError("不得触网")):
            self.assertTrue(m.download_resource(self.root, self.resource, self.cancel, lambda *_: None)["reused"])

    def test_existing_user_model_is_not_overwritten(self):
        target = self.root / "model/model.gguf"
        target.parent.mkdir()
        target.write_bytes(b"user data")
        with self.assertRaises(m.DownloadError):
            self.run_download()
        self.assertEqual(target.read_bytes(), b"user data")

    def test_hash_size_html_and_invalid_gguf_fail_without_publishing(self):
        for data, headers in ((b"bad", {}), (self.data[:-1], {}), (self.data + b"x", {}),
                              (b"<html>bad</html>", {}), (self.data, {"Content-Length": "1"})):
            with self.subTest(data=data[:8]), self.assertRaises(m.DownloadError):
                self.run_download(response=Response(data, headers))
            self.assertFalse((self.root / "model/model.gguf").exists())
            self.assertFalse(list((self.root / "model").glob(".download-*")))
        invalid = copy.deepcopy(self.resource)
        data = b"HTML" + b"x" * 8
        invalid["files"] = [self.file("model.gguf", data)]
        with self.assertRaises(m.DownloadError):
            self.run_download(invalid, Response(data))

    def test_cancel_and_network_failure_leave_no_partial_model(self):
        self.cancel.set()
        with self.assertRaises(m.DownloadCancelled):
            self.run_download()
        self.cancel.clear()
        opener = mock.Mock()
        opener.open.side_effect = TimeoutError("受控断网")
        with self.assertRaises(TimeoutError):
            m.download_resource(self.root, self.resource, self.cancel, lambda *_: None, opener=opener)
        self.assertFalse((self.root / "model/model.gguf").exists())
        self.assertFalse(list((self.root / "model").glob(".download-*")))

    def test_directory_model_appears_only_after_all_files_validate(self):
        data = {"inference.json": b'{"valid":true}', "inference.pdiparams": b"weights", "inference.yml": b"name: layout"}
        resource = {"kind": "directory", "destination": "PP-DocLayoutV3", "files": [self.file(name, value) for name, value in data.items()]}
        opener = mock.Mock()
        def open_file(request, timeout):
            self.assertFalse((self.root / "model/PP-DocLayoutV3").exists())
            return Response(data[request.full_url.rsplit("/", 1)[1]])
        opener.open.side_effect = open_file
        result = m.download_resource(self.root, resource, self.cancel, lambda *_: None, opener=opener)
        for name, value in data.items():
            self.assertEqual((Path(result["path"]) / name).read_bytes(), value)

    def test_traversal_reserved_paths_http_and_unpinned_hash_are_rejected(self):
        for name in ("../outside", "/outside", "a//b", "C:/outside", "a\\b", "CON", "name. "):
            bad = copy.deepcopy(self.resource)
            bad["destination"] = name
            with self.subTest(name=name), self.assertRaises(m.DownloadError):
                self.run_download(bad)
        for field, value in (("url", "http://example.com/model.gguf"), ("url", "https://user:pass@example.com/a"), ("sha256", "0"), ("bytes", -1)):
            bad = copy.deepcopy(self.resource)
            bad["files"][0][field] = value
            with self.subTest(field=field), self.assertRaises(m.DownloadError):
                self.run_download(bad)

    def test_read_only_target_and_disk_shortage_do_not_fallback(self):
        with mock.patch.object(m.shutil, "disk_usage", return_value=mock.Mock(free=0)), self.assertRaises(m.DownloadError):
            self.run_download()
        with mock.patch.object(Path, "mkdir", side_effect=PermissionError("只读")), self.assertRaises(PermissionError):
            self.run_download()
        self.assertFalse((self.root / "model/model.gguf").exists())

    def test_redirect_rejects_http_and_unrelated_hosts(self):
        handler = m.SecureRedirect()
        request = urllib.request.Request("https://huggingface.co/repository/model")
        for url in ("http://huggingface.co/file", "https://example.com/file", "https://huggingface.co.evil.test/file"):
            with self.subTest(url=url), self.assertRaises(m.DownloadError):
                handler.redirect_request(request, None, 302, "", {}, url)
        self.assertEqual(handler.redirect_request(request, None, 302, "", {}, "https://cas-bridge.xethub.hf.co/model").full_url,
                         "https://cas-bridge.xethub.hf.co/model")

    def test_manager_deduplicates_and_cancels_by_request(self):
        queued, events = [], []
        manager = m.DownloadManager(lambda plugin: (self.root, {"main": self.resource}), lambda *event: events.append(event), queued.append)
        manager.start("first", "plugin", "main")
        manager.start("second", "plugin", "main")
        self.assertEqual(len(queued), 1)
        self.assertEqual(events[-1][1]["state"], "failed")
        manager.cancel("first")
        queued.pop()()
        self.assertEqual(events[-1][1]["state"], "cancelled")
        manager.close()
        manager.start("third", "plugin", "main")
        self.assertEqual(events[-1][1]["state"], "failed")

    def test_hardlink_and_junction_targets_are_rejected(self):
        import os
        target = self.root / "model"
        target.mkdir()
        outside = self.root.parent / "original.gguf"
        outside.write_bytes(self.data)
        os.link(outside, target / "model.gguf")
        with self.assertRaises(m.DownloadError):
            self.run_download()
        (target / "model.gguf").unlink()
        target.rmdir()
        if os.name == "nt":
            import subprocess
            result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(target), str(self.root.parent)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            try:
                with self.assertRaises(m.DownloadError):
                    self.run_download()
            finally:
                target.rmdir()
        self.assertEqual(outside.read_bytes(), self.data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
