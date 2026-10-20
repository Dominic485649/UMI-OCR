import argparse
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "build" / "tools"
DATA_ROOT = ROOT / "build" / "staging" / "281-base-current" / "UmiOCR-data"
SOURCE_ROOT = ROOT / "UmiOCR-data"
sys.path.insert(0, str(TOOLS_DIR))
from staging_smoke import configure_runtime


class HttpApiWsgiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_cwd = os.getcwd()
        cls.runtime_handles = configure_runtime(DATA_ROOT)
        os.chdir(cls.original_cwd)
        if SOURCE_ROOT:
            sys.path[:0] = [str(SOURCE_ROOT), str(SOURCE_ROOT / "py_src" / "imports")]
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="umi-http-api-")

        from py_src.server import doc_server

        cls.doc_server = doc_server
        cls.original_upload_dir = doc_server.UPLOAD_DIR
        cls.original_delay = doc_server.CallFunc.delay
        doc_server.UPLOAD_DIR = str(Path(cls.temp_dir.name) / "uploads")
        doc_server.CallFunc.delay = lambda *args, **kwargs: None

        from py_src.server import web_server

        cls.web_server = web_server

    @classmethod
    def tearDownClass(cls):
        with cls.doc_server._DocUnitManager._lock:
            cls.doc_server._DocUnitManager.doc_units.clear()
        cls.doc_server.UPLOAD_DIR = cls.original_upload_dir
        cls.doc_server.CallFunc.delay = cls.original_delay
        os.chdir(cls.original_cwd)
        cls.temp_dir.cleanup()
        cls.runtime_handles.clear()

    def request(
        self,
        method,
        path,
        payload=None,
        body=None,
        headers=None,
        remote="127.0.0.1",
        content_length=None,
    ):
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers = {"Content-Type": "application/json", **(headers or {})}
        elif body is None:
            body = b""
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": "",
            "CONTENT_LENGTH": str(len(body) if content_length is None else content_length),
            "CONTENT_TYPE": "",
            "SERVER_NAME": "localhost",
            "SERVER_PORT": "1224",
            "SERVER_PROTOCOL": "HTTP/1.1",
            "REMOTE_ADDR": remote,
            "wsgi.version": (1, 0),
            "wsgi.url_scheme": "http",
            "wsgi.input": io.BytesIO(body),
            "wsgi.errors": io.StringIO(),
            "wsgi.multithread": False,
            "wsgi.multiprocess": False,
            "wsgi.run_once": False,
        }
        for key, value in (headers or {}).items():
            if key.lower() == "content-type":
                environ["CONTENT_TYPE"] = value
            else:
                environ["HTTP_" + key.upper().replace("-", "_")] = value
        result = {}

        def start_response(status, response_headers, exc_info=None):
            result["status"] = int(status.split(" ", 1)[0])
            result["headers"] = dict(response_headers)

        chunks = self.web_server.UmiWeb(environ, start_response)
        try:
            result["body"] = b"".join(chunks)
        finally:
            close = getattr(chunks, "close", None)
            if close:
                close()
        return result

    @staticmethod
    def json_body(response):
        return json.loads(response["body"].decode("utf-8"))

    def test_route_inventory(self):
        actual = {(route.method, route.rule) for route in self.web_server.UmiWeb.routes}
        expected = {
            ("GET", "/"),
            ("GET", "/umiocr"),
            ("POST", "/argv"),
            ("GET", "/api/ocr/get_options"),
            ("POST", "/api/ocr"),
            ("POST", "/api/qrcode"),
            ("GET", "/api/doc/get_options"),
            ("POST", "/api/doc/upload"),
            ("POST", "/api/doc/result"),
            ("POST", "/api/doc/download"),
            ("GET", "/api/doc/download/<id>/<download_name>"),
            ("GET", "/api/doc/clear/<id>"),
        }
        self.assertTrue(expected <= actual, expected - actual)

    def test_request_size_limit_runs_before_route(self):
        from py_src.server import qrcode_server

        with patch.object(qrcode_server.MissionQRCode, "addMissionWait") as mission:
            response = self.request(
                "POST",
                "/api/qrcode",
                body=b"{}",
                headers={"Content-Type": "application/json"},
                content_length=self.web_server.MAX_REQUEST_SIZE + 1,
            )
        self.assertEqual(response["status"], 413)
        mission.assert_not_called()

    def test_preflight_never_dispatches_post(self):
        with patch.object(self.web_server.CmdServer, "execute", return_value="called") as execute:
            response = self.request(
                "OPTIONS",
                "/argv",
                body=b"",
                headers={
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                },
            )
        self.assertEqual(response["status"], 204)
        self.assertEqual(response["body"], b"")
        self.assertEqual(execute.call_count, 0)
        self.assertEqual(response["headers"]["Access-Control-Allow-Origin"], "*")

    def test_argv_loopback_authorization_and_input_shape(self):
        with patch.object(self.web_server.CmdServer, "execute", return_value="ok") as execute:
            local = self.request("POST", "/argv", payload=["--show"])
            ipv6_local = self.request("POST", "/argv", payload=["--hide"], remote="::1")
            remote = self.request("POST", "/argv", payload=["--quit"], remote="192.0.2.4")
            invalid = self.request("POST", "/argv", payload={"command": "--quit"})
        self.assertEqual(local["status"], 200)
        self.assertEqual(ipv6_local["status"], 200)
        self.assertEqual(remote["status"], 401)
        self.assertEqual(invalid["status"], 400)
        self.assertEqual(execute.call_count, 2)
        self.assertEqual(execute.call_args_list[0].args[0], ["--show"])

    def test_browser_origin_cannot_invoke_local_commands(self):
        with patch.object(self.web_server.CmdServer, "execute", return_value="ok") as execute:
            foreign = self.request(
                "POST", "/argv", payload=["--quit"], headers={"Origin": "https://example.org"}
            )
            opaque = self.request(
                "POST", "/argv", payload=["--quit"], headers={"Origin": "null"}
            )
            local = self.request(
                "POST", "/argv", payload=["--show"], headers={"Origin": "http://localhost:1224"}
            )
            cli = self.request("POST", "/argv", payload=["--show"])
        self.assertEqual(foreign["status"], 403)
        self.assertEqual(opaque["status"], 403)
        self.assertEqual(local["status"], 200)
        self.assertEqual(cli["status"], 200)
        self.assertEqual(execute.call_count, 2)

    def test_ocr_json_options_base64_and_success(self):
        from py_src.server import ocr_server

        options = {
            "ocr.preset": {"default": "custom"},
            "tbpu.ignoreArea": {"default": []},
            "data.format": {"default": "dict"},
        }
        result = {"code": 100, "data": [{"text": "mock"}]}
        with patch.object(ocr_server, "get_ocr_options", return_value=options):
            with patch.object(ocr_server.MissionOCR, "addMissionWait", return_value=[{"result": result}]) as mission:
                invalid_json = self.request(
                    "POST", "/api/ocr", body=b"{", headers={"Content-Type": "application/json"}
                )
                invalid_root = self.request("POST", "/api/ocr", payload=["base64"])
                invalid_base64 = self.request("POST", "/api/ocr", payload={"base64": "%%%"})
                invalid_options = self.request(
                    "POST", "/api/ocr", payload={"base64": "aGVsbG8=", "options": []}
                )
                success = self.request("POST", "/api/ocr", payload={"base64": "aGVsbG8="})
        self.assertEqual(self.json_body(invalid_json)["code"], 800)
        self.assertEqual(self.json_body(invalid_root)["code"], 805)
        self.assertEqual(self.json_body(invalid_base64)["code"], 805)
        self.assertEqual(self.json_body(invalid_options)["code"], 803)
        self.assertEqual(self.json_body(success)["code"], 100)
        mission.assert_called_once()

    def test_qrcode_json_options_base64_and_success(self):
        from py_src.server import qrcode_server

        result = {"code": 100, "data": []}
        with patch.object(qrcode_server.MissionQRCode, "addMissionWait", return_value=[{"result": result}]) as mission:
            invalid_root = self.request("POST", "/api/qrcode", payload=["base64"])
            invalid_base64 = self.request("POST", "/api/qrcode", payload={"base64": "%%%"})
            invalid_options = self.request(
                "POST", "/api/qrcode", payload={"base64": "aGVsbG8=", "options": []}
            )
            success = self.request("POST", "/api/qrcode", payload={"base64": "aGVsbG8="})
        self.assertEqual(self.json_body(invalid_root)["code"], 803)
        self.assertEqual(self.json_body(invalid_base64)["code"], 803)
        self.assertEqual(self.json_body(invalid_options)["code"], 803)
        self.assertEqual(self.json_body(success)["code"], 100)
        mission.assert_called_once()

    def test_qrcode_text_generation(self):
        from py_src.server import qrcode_server

        image = __import__("PIL.Image", fromlist=["Image"]).new("RGB", (2, 2))
        with patch.object(qrcode_server.MissionQRCode, "createImage", return_value=image) as create:
            response = self.request("POST", "/api/qrcode", payload={"text": "test"})
        body = self.json_body(response)
        self.assertEqual(body["code"], 100)
        self.assertTrue(body["data"])
        create.assert_called_once()

    def test_document_invalid_options_do_not_leave_uploaded_files(self):
        boundary = "umi-http-test-boundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="test.pdf"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
            "%PDF-1.4\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="json"\r\n\r\n'
            '{"tbpu.ignoreArea":[[]]}\r\n'
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        response = self.request(
            "POST",
            "/api/doc/upload",
            body=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        self.assertEqual(self.json_body(response)["code"], 107)
        self.assertEqual(list(Path(self.doc_server.UPLOAD_DIR).iterdir()), [])

    def test_document_upload_filename_cannot_escape_task_directory(self):
        root = Path(self.doc_server.UPLOAD_DIR)
        victim_dir = root / "victim"
        victim_dir.mkdir()
        victim = victim_dir / "secret.pdf"
        victim.write_bytes(b"keep this file")
        boundary = "umi-http-path-boundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="..\\victim\\secret.pdf"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
            "%PDF-mock\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        mock_error = self.doc_server.DocUnitError({"code": 299, "data": "mock stop"})
        try:
            with patch.object(self.doc_server, "_DocUnit", side_effect=mock_error):
                response = self.request(
                    "POST",
                    "/api/doc/upload",
                    body=body,
                    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                )
            self.assertEqual(self.json_body(response)["code"], 299)
            self.assertEqual(victim.read_bytes(), b"keep this file")
            self.assertEqual(list(victim_dir.iterdir()), [victim])
        finally:
            import shutil

            shutil.rmtree(victim_dir, ignore_errors=True)

    def test_missing_document_download_and_clear_and_traversal(self):
        upload_root = Path(self.doc_server.UPLOAD_DIR)
        before = list(upload_root.iterdir())
        bad_result = self.request("POST", "/api/doc/result", payload=["id"])
        missing_download = self.request("POST", "/api/doc/download", payload={"id": "missing"})
        missing_clear = self.request("GET", "/api/doc/clear/missing")
        self.assertEqual(self.json_body(bad_result)["code"], 104)
        self.assertEqual(self.json_body(missing_download)["code"], 103)
        self.assertEqual(self.json_body(missing_clear)["code"], 101)
        self.assertEqual(list(upload_root.iterdir()), before)

        outside = upload_root.parent / "outside-secret.txt"
        outside.write_text("do not serve", encoding="utf-8")
        try:
            traversal = self.request("GET", "/api/doc/download/../outside-secret.txt")
            self.assertEqual(traversal["status"], 403)
            self.assertNotIn(b"do not serve", traversal["body"])
        finally:
            outside.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--packaged", action="store_true", help="Test only the staged source, not the checkout")
    args, remaining = parser.parse_known_args()
    DATA_ROOT = args.data_root.resolve()
    SOURCE_ROOT = None if args.packaged else args.source_root.resolve()
    unittest.main(argv=[sys.argv[0], *remaining])
