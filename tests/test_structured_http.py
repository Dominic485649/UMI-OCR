"""结构化 HTTP 任务的快速完成、partial、取消与资源归属回归。"""
import argparse
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build/tools"))
from staging_smoke import configure_runtime
DATA_ROOT = None


class FakeManager:
    def __init__(self, complete=True, outside_asset=None):
        self.complete = complete
        self.outside_asset = outside_asset
        self.cancelled = []
        self.closed = 0

    def shutdown(self):
        self.closed += 1

    def addMissionList(self, info, items):
        self.info = info
        identifier = info["_reserved_msnID"]
        if self.complete:
            info["onStart"](info)
            asset_root = Path(items[0]["assetOutputRoot"])
            asset = self.outside_asset or asset_root / "preview.png"
            if not self.outside_asset:
                asset.write_bytes(b"PNG")
            result = {"code": 100, "text": "recognized", "markdown": f"![figure]({asset.as_uri()})",
                      "data": {"pages": [{"page": 1, "resources": [{"id": "asset-1", "path": str(asset), "uri": asset.as_uri()}]}]}}
            info["onPartial"]({"page": 1, "result": result, "warnings": [], "failed": False})
            info["onGet"](info, items[0], result)
            info["onEnd"](info, "[Success]")
        return identifier

    def stopMissionList(self, identifier):
        self.cancelled.append(identifier)
        self.info["onEnd"](self.info, "[Warning] Task stop.")


class StructuredHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        original = os.getcwd()
        cls.handles = configure_runtime(DATA_ROOT)
        sys.path[:0] = [str(ROOT / "UmiOCR-data"), str(ROOT / "UmiOCR-data/py_src/imports")]
        os.chdir(original)
        from PySide6.QtCore import QCoreApplication
        cls.app = QCoreApplication.instance() or QCoreApplication([])
        from py_src.server import doc_server
        cls.delay = doc_server.CallFunc.delay
        doc_server.CallFunc.delay = lambda *args, **kwargs: None
        from py_src.server import web_server, structured_document_server
        cls.web, cls.server = web_server, structured_document_server
        cls.original_root = cls.server.JOB_ROOT

    @classmethod
    def tearDownClass(cls):
        cls.server.JOB_ROOT = cls.original_root
        from py_src.server import doc_server
        doc_server.CallFunc.delay = cls.delay

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="structured-http-")
        self.server.JOB_ROOT = Path(self.temp.name) / "jobs"
        self.server.JOBS.clear()
        from py_src.server.request_budgets import ByteBudget
        self.server.BUDGET = ByteBudget(self.server.MAX_TOTAL_BYTES)
        self.manager = FakeManager()
        from py_src.server.backend_router import BackendSelection
        self.selection = BackendSelection(self.manager, "test-document", {}, True)
        self.patches = [patch.object(self.server, "select_backend", return_value=self.selection),
                        patch.object(self.server, "backend_options", return_value={"maxOutputTokens": {"default": 4096, "min": 256, "max": 65536, "isInt": True}})]
        for mock in self.patches:
            mock.start()

    def tearDown(self):
        for mock in reversed(self.patches):
            mock.stop()
        self.server.JOBS.clear()
        self.temp.cleanup()

    def request(self, method, path, *, data=None, body=b"", content_type="application/json"):
        if data is not None:
            body = json.dumps(data).encode()
        environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "QUERY_STRING": "",
                   "CONTENT_LENGTH": str(len(body)), "CONTENT_TYPE": content_type,
                   "SERVER_NAME": "localhost", "SERVER_PORT": "1224", "SERVER_PROTOCOL": "HTTP/1.1",
                   "REMOTE_ADDR": "127.0.0.1", "wsgi.version": (1, 0), "wsgi.url_scheme": "http",
                   "wsgi.input": io.BytesIO(body), "wsgi.errors": io.StringIO(),
                   "wsgi.multithread": True, "wsgi.multiprocess": False, "wsgi.run_once": False}
        status = {}
        def start_response(value, headers, exc_info=None):
            status["value"] = int(value.split()[0])
        stream = self.web.UmiWeb(environ, start_response)
        try:
            payload = b"".join(stream)
        finally:
            if hasattr(stream, "close"):
                stream.close()
        return status["value"], payload

    def upload(self, parameters=None, raw=b"test-pdf"):
        boundary = "model-settings-boundary"
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"json\"\r\n\r\n" +
                json.dumps(parameters or {}) + "\r\n" +
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"input.pdf\"\r\nContent-Type: application/pdf\r\n\r\n").encode() + raw + f"\r\n--{boundary}--\r\n".encode()
        status, payload = self.request("POST", "/api/document/upload", body=body,
                                       content_type=f"multipart/form-data; boundary={boundary}")
        self.assertEqual(status, 200, payload)
        return json.loads(payload)

    def test_immediate_completion_and_asset_urls(self):
        submitted = self.upload()
        self.assertEqual(submitted["code"], 100, submitted)
        identifier = submitted["jobId"]
        status, payload = self.request("POST", "/api/document/result", data={"jobId": identifier})
        result = json.loads(payload)
        self.assertEqual(result["state"], "succeeded", result)
        self.assertNotIn(str(self.server.JOB_ROOT), payload.decode())
        self.assertNotIn("file://", payload.decode())
        job = self.server.JOBS[identifier]
        asset_id = next(iter(job.assets))
        status, content = self.request("GET", f"/api/document/assets/{identifier}/{asset_id}")
        self.assertEqual((status, content), (200, b"PNG"))
        status, content = self.request("GET", f"/api/document/assets/{identifier}/not-owned")
        self.assertEqual(status, 404)

    def test_external_resource_is_not_published(self):
        outside = Path(self.temp.name) / "private.png"
        outside.write_bytes(b"secret")
        self.manager.outside_asset = outside
        identifier = self.upload()["jobId"]
        job = self.server.JOBS[identifier]
        self.assertFalse(job.assets)
        self.assertEqual(job.state, "partial")

    def test_cancel_targets_one_job(self):
        self.manager.complete = False
        identifier = self.upload()["jobId"]
        status, payload = self.request("POST", "/api/document/cancel", data={"jobId": identifier})
        self.assertEqual(json.loads(payload)["state"], "cancelled")
        self.assertEqual(self.manager.cancelled, [identifier])

    def test_reject_global_paths_and_invalid_page_range(self):
        for parameters in ({"options": {"service.serverExecutable": "x.exe"}},
                           {"pageRange": [1, 10000]}, {"taskTimeoutSeconds": True}):
            with self.subTest(parameters=parameters):
                self.assertNotEqual(self.upload(parameters)["code"], 100)

    def test_failed_upload_releases_reservation(self):
        result = self.upload(raw=b"")
        self.assertNotEqual(result["code"], 100)
        self.assertEqual(self.server.BUDGET.used, 0)
        self.assertFalse(self.server.JOBS)
        self.assertFalse(list(self.server.JOB_ROOT.glob("*")))

    def test_failed_admission_settles_and_cleanup_releases_once(self):
        self.manager.addMissionList = lambda *_: "[Error] busy"
        submitted = self.upload()
        self.assertNotEqual(submitted["code"], 100)
        job = next(iter(self.server.JOBS.values()))
        self.assertEqual(job.state, "failed")
        self.assertEqual(self.server.BUDGET.used, job.reserved_bytes)
        job.updated_at = 0
        self.server._cleanup()
        self.server._cleanup()
        self.assertFalse(self.server.JOBS)
        self.assertEqual(self.server.BUDGET.used, 0)

    def test_partial_only_export_preserves_completed_pages(self):
        self.manager.complete = False
        identifier = self.upload()["jobId"]
        job = self.server.JOBS[identifier]
        job._on_partial({"page": 2, "result": {"code": 100, "text": "second", "markdown": "# second"}})
        job._on_partial({"page": 1, "result": {"code": 100, "text": "first", "markdown": "# first"}})
        job.cancel()
        text, _, _ = job.export("txt")
        markdown, _, _ = job.export("md")
        self.assertEqual(text.decode(), "first\n\nsecond")
        self.assertEqual(markdown.decode(), "# first\n\n# second")
        document, _, _ = job.export("json")
        self.assertTrue(json.loads(document)["partial"])
        self.assertEqual(len(json.loads(document)["partialPages"]), 2)

    def test_zip_resources_are_relative_in_json_and_markdown(self):
        import zipfile
        identifier = self.upload()["jobId"]
        payload, _, _ = self.server.JOBS[identifier].export("zip")
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            self.assertNotIn("/api/document/assets/", archive.read("document.json").decode())
            self.assertNotIn("/api/document/assets/", archive.read("document.md").decode())
            self.assertIn("assets/", archive.read("document.json").decode())

    def test_legacy_mixed_admission_without_ocr_backend(self):
        from py_src.server import doc_server
        from py_src.mission.mission_ocr import MissionOCR
        def accept(info, *args):
            info["pageList"] = [0]
            return info["_reserved_msnID"]
        with patch.object(MissionOCR, "_api", None), patch.object(MissionOCR, "_apiKey", ""), \
             patch.object(MissionOCR, "getLocalOptions", return_value={}), \
             patch.object(doc_server.MissionDOC, "getDocInfo", return_value={"page_count": 1, "is_encrypted": False}), \
             patch.object(doc_server.MissionDOC, "addMission", side_effect=accept):
            unit = doc_server._DocUnit("directory", self.temp.name, "input.pdf", "input.pdf", "input",
                                       {"doc.extractionMode": "mixed"})
            self.assertTrue(unit._selection.private)
            self.assertIsNot(unit._selection.manager, MissionOCR)
            self.assertIsNone(unit._selection.manager._api)
            unit._onEnd({}, "[Success]")
            self.assertEqual(unit.state, "success")

    def test_full_page_render_is_rejected_before_allocation(self):
        import types
        from unittest.mock import Mock
        from py_src.mission.mission_doc import MissionDOC
        page = types.SimpleNamespace(rotation=0, rect=(0, 0, 10, 1000000),
                                     get_pixmap=Mock(side_effect=AssertionError("must not allocate")))
        fake_fitz = types.SimpleNamespace(Matrix=lambda *args: args, Identity=None)
        with patch.dict(sys.modules, {"fitz": fake_fitz}):
            with self.assertRaisesRegex(ValueError, "IMAGE_BUDGET_EXCEEDED"):
                MissionDOC.msnTask({"doc": [page], "argd": {"doc.extractionMode": "fullPage"}}, 0)
        page.get_pixmap.assert_not_called()

    def test_legacy_document_preserves_partial_ocr_warning(self):
        import types
        from unittest.mock import Mock
        from py_src.mission.mission_doc import MissionDOC
        image = {"type": 1, "transform": (1, 0, 0, 1, 0, 0), "image": b"image",
                 "bbox": [0, 0, 100, 100], "width": 100, "height": 100}
        page = types.SimpleNamespace(rotation=0, get_text=lambda *args, **kwargs: {"blocks": [image]})
        recognized = {"box": [[0, 0], [10, 0], [10, 10], [0, 10]], "text": "kept", "score": 1}
        manager = types.SimpleNamespace(addMissionWait=lambda *_: [{"xy": (0, 0), "scale_w": 1, "scale_h": 1,
                    "result": {"code": 100, "data": [recognized], "partial": True, "warnings": ["unfinished region"]}}])
        info = {"doc": [page], "argd": {"doc.extractionMode": "imageOnly"}, "ignoreArea": None,
                "tbpu": [], "ocrManager": manager}
        with patch.dict(sys.modules, {"fitz": types.SimpleNamespace(INFINITE_RECT=lambda: None)}), \
             patch.object(MissionDOC, "_minInterval", 0):
            result = MissionDOC.msnTask(info, 0)
        self.assertEqual(result["code"], 100)
        self.assertTrue(result["partial"])
        self.assertIn("unfinished region", result["warnings"][0])
        self.assertEqual(result["data"][0]["text"], "kept")

    def test_export_does_not_accept_client_path(self):
        identifier = self.upload()["jobId"]
        status, content = self.request("POST", "/api/document/download", data={"jobId": identifier, "format": "json"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(content)["text"], "recognized")
        status, content = self.request("POST", "/api/document/download", data={"jobId": "../private"})
        self.assertNotEqual(json.loads(content)["code"], 100)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True, type=Path)
    arguments, remaining = parser.parse_known_args()
    DATA_ROOT = arguments.data_root.resolve()
    unittest.main(argv=[sys.argv[0], *remaining])
