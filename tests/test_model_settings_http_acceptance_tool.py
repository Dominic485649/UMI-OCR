"""Utility-only checks; these are NOT real GPU/package acceptance evidence."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("model_settings_http_acceptance_tool", ROOT / "build/tools/model_settings_http_acceptance.py")
TOOL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL
SPEC.loader.exec_module(TOOL)


class ToolUtilityTests(unittest.TestCase):
    def test_default_does_not_import_product_or_touch_paths(self):
        before = {name for name in sys.modules if name.startswith(("py_src", "PySide6"))}
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(TOOL, "validate_paths", side_effect=AssertionError("touched paths")), \
             patch.object(TOOL.subprocess, "Popen", side_effect=AssertionError("started worker")):
            code = TOOL.main(["--root", "missing-root", "--work", "missing-work", "--audit", "missing-audit", "--model-inputs", "missing.json"])
        self.assertEqual(code, 0)
        value = json.loads(output.getvalue())
        self.assertTrue(value["planOnly"])
        self.assertFalse(value["gpuExecuted"])
        self.assertEqual(before, {name for name in sys.modules if name.startswith(("py_src", "PySide6"))})

    def test_png_is_decodable_countable_rgb_and_cbz_has_two_pages(self):
        png = TOOL.countable_png(rows=3)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        offset, chunks = 8, {}
        while offset < len(png):
            length = struct.unpack(">I", png[offset:offset + 4])[0]
            kind, content = png[offset + 4:offset + 8], png[offset + 8:offset + 8 + length]
            crc = struct.unpack(">I", png[offset + 8 + length:offset + 12 + length])[0]
            self.assertEqual(crc, zlib.crc32(kind + content) & 0xffffffff)
            chunks[kind] = chunks.get(kind, b"") + content
            offset += length + 12
        width, height, depth, kind, *_ = struct.unpack(">IIBBBBB", chunks[b"IHDR"])
        self.assertEqual((depth, kind), (8, 2))
        pixels = zlib.decompress(chunks[b"IDAT"])
        self.assertEqual(len(pixels), height * (width * 3 + 1))
        self.assertIn(b"\x00\x00\x00", pixels)
        with zipfile.ZipFile(io.BytesIO(TOOL.png_cbz(png))) as archive:
            self.assertEqual(archive.namelist(), ["page-001.png", "page-002.png"])
            self.assertEqual(archive.read("page-001.png"), png)
        with self.assertRaises(TOOL.AcceptanceError):
            TOOL.countable_png(rows=61)

    def test_multipart_preserves_bytes_and_rejects_header_injection(self):
        body, content_type = TOOL.multipart({"json": '{"a":1}'}, "中文.png", b"\x00\xff", "image/png")
        self.assertIn(b"\x00\xff\r\n", body)
        self.assertIn("中文.png".encode(), body)
        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))
        with self.assertRaises(TOOL.AcceptanceError):
            TOOL.multipart({}, 'evil"\r\nX:a', b"x", "image/png")

    def test_client_refuses_foreign_urls(self):
        client = TOOL.HttpClient(12345, time.monotonic() + 10)
        self.assertEqual(client.local_url("/api/backends"), "http://127.0.0.1:12345/api/backends")
        for url in ("http://localhost:12345/", "https://127.0.0.1:12345/", "http://127.0.0.1:9/", "http://evil.invalid/", "http://user@127.0.0.1:12345/"):
            with self.subTest(url=url), self.assertRaises(TOOL.AcceptanceError):
                client.local_url(url)

    def test_client_uses_real_socket_and_disables_redirects(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "http://example.invalid/")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"code":100,"utilityOnly":true}')
            def log_message(self, *_args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = TOOL.HttpClient(server.server_port, time.monotonic() + 10)
            self.assertTrue(client.json("/api/backends")["utilityOnly"])
            with self.assertRaises(TOOL.AcceptanceError):
                client.call("/redirect")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_evidence_write_never_overwrites(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "build", prefix="http-tool-utility-") as temporary:
            path = Path(temporary) / "result.json"
            TOOL.write_json_new(path, {"first": True})
            with self.assertRaises(FileExistsError):
                TOOL.write_json_new(path, {"first": False})
            self.assertEqual(json.loads(path.read_text()), {"first": True})

    def test_canonical_trusted_bindings_are_8k_single_slot_and_never_http_fields(self):
        cuda, vl = "win32_CUDA", "win32_VL"
        prefix = f"pluginServices.{vl}.paddlevl."
        fields = {prefix + key for key in ("service.mainModel", "service.mmprojModel", "service.port",
                  "resources.contextLength", "resources.slots", "resources.maxOutputTokens")}
        fields.add(f"document.{vl}.pipeline.layoutModelDir")
        models = {"model": "trusted-main.gguf", "projector": "trusted-mmproj.gguf", "layout": "trusted-layout"}
        values = TOOL.trusted_overrides(cuda, vl, fields, models, 31999)
        self.assertEqual(values[prefix + "resources.contextLength"], 8192)
        self.assertEqual(values[prefix + "resources.slots"], 1)
        self.assertEqual(values[prefix + "service.mainModel"], models["model"])
        self.assertEqual(values[f"document.{vl}.pipeline.layoutModelDir"], models["layout"])
        self.assertFalse(any(key.endswith((".host", ".mode", ".serverExecutable", ".autoStart")) for key in values))
        with self.assertRaises(TOOL.AcceptanceError):
            TOOL.trusted_overrides(cuda, vl, fields - {prefix + "service.mmprojModel"}, models, 31999)

    def test_output_paths_must_be_new_disjoint_and_outside_candidate(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "build", prefix="http-tool-paths-") as temporary:
            parent = Path(temporary)
            candidate = parent / "candidate"
            candidate.mkdir()
            work, audit = parent / "work", parent / "audit"
            self.assertEqual(TOOL.validate_paths(candidate, work, audit), (candidate.resolve(), work.resolve(), audit.resolve()))
            for invalid_work, invalid_audit in ((work, work / "nested"), (candidate / "work", audit), (parent, audit)):
                with self.subTest(work=invalid_work), self.assertRaises(TOOL.AcceptanceError):
                    TOOL.validate_paths(candidate, invalid_work, invalid_audit)
            audit.mkdir()
            with self.assertRaises(TOOL.AcceptanceError):
                TOOL.validate_paths(candidate, work, audit)

    def test_kernel_job_only_terminates_its_new_test_child(self):
        import subprocess
        import os
        child = subprocess.Popen([sys.executable, "-I", "-B", "-X", "utf8", "-c", "import time; time.sleep(20)"], start_new_session=os.name != "nt")
        job = None
        try:
            job = TOOL.OwnedProcessJob(child)
            job.terminate()
            child.wait(timeout=5)
            self.assertIsNotNone(child.returncode)
        finally:
            if job:
                job.close()
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)

    def test_model_manifest_checks_all_four_hashes_without_modifying_inputs(self):
        import hashlib
        with tempfile.TemporaryDirectory(dir=ROOT / "build", prefix="http-tool-models-") as temporary:
            directory = Path(temporary)
            names = ("main.gguf", "mmproj.gguf", "inference.json", "inference.pdiparams")
            hashes = {}
            for name in names:
                path = directory / name
                path.write_bytes(("utility-only-" + name).encode())
                hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest = directory / "inputs.json"
            manifest.write_text(json.dumps({"sha256": hashes}), encoding="utf-8")
            result = TOOL.trusted_model_inputs(manifest)
            self.assertEqual(result["model"], str(directory / "main.gguf"))
            self.assertEqual(result["projector"], str(directory / "mmproj.gguf"))
            self.assertEqual(result["layout"], str(directory))
            self.assertEqual(len(result["verified"]), 4)
            before = (directory / "main.gguf").read_bytes()
            hashes[str(directory / "main.gguf")] = "0" * 64
            manifest.write_text(json.dumps({"sha256": hashes}), encoding="utf-8")
            with self.assertRaises(TOOL.AcceptanceError):
                TOOL.trusted_model_inputs(manifest)
            self.assertEqual((directory / "main.gguf").read_bytes(), before)

    def test_worker_command_uses_candidate_python_and_production_isolation_flags(self):
        import types
        executable = ROOT / "build/candidate/UmiOCR-data/runtime/python.exe"
        args = types.SimpleNamespace(model_inputs=ROOT / "build/trusted-inputs.json", deadline_seconds=1800)
        command = TOOL.production_worker_command(args, executable, ROOT / "build/candidate", ROOT / "build/work", ROOT / "build/audit-new", "nonce")
        self.assertEqual(command[:5], [str(executable), "-I", "-B", "-X", "utf8"])
        self.assertIn("--execute-gpu", command)
        self.assertEqual(command[-2:], ["--worker-token", "nonce"])
        self.assertNotEqual(command[0], sys.executable)
        with self.assertRaises(TOOL.AcceptanceError):
            TOOL.candidate_python(ROOT / "build/candidate-not-provided")

    def test_worker_temp_and_all_explicit_caches_are_under_new_work(self):
        import os
        work = ROOT / "build/not-created-environment-work"
        inherited = {"TEMP": "external-user-temp", "TMP": "external-user-temp", "CUDA_CACHE_PATH": "external-user-cuda",
                     "HF_HOME": "external-user-hf", "USERPROFILE": "external-user-home", "http_proxy": "http://external-proxy",
                     "UNRELATED_SECRET": "not-to-be-recorded"}
        before = dict(inherited)
        environment, overrides, paths = TOOL.isolated_worker_environment(work, inherited)
        self.assertEqual(inherited, before)
        self.assertTrue(all(TOOL.inside(path, work) for path in paths.values()))
        for key in ("TEMP", "TMP", "TMPDIR", "CUDA_CACHE_PATH", "HF_HOME", "PADDLE_HOME", "PADDLE_PDX_CACHE_HOME", "QML_DISK_CACHE_PATH"):
            self.assertEqual(environment[key], str(paths[key]))
        self.assertEqual(environment["HF_HUB_OFFLINE"], "1")
        self.assertEqual(environment["QML_DISABLE_DISK_CACHE"], "1")
        self.assertNotIn("http_proxy", environment)
        self.assertEqual(environment["UNRELATED_SECRET"], "not-to-be-recorded")
        self.assertNotIn("UNRELATED_SECRET", overrides)
        if os.name == "nt":
            self.assertEqual(environment["HOMEDRIVE"] + environment["HOMEPATH"], environment["USERPROFILE"])

    def test_isolated_temp_is_inherited_by_a_real_non_gpu_utility_child(self):
        import subprocess
        with tempfile.TemporaryDirectory(dir=ROOT / "build", prefix="http-tool-env-") as temporary:
            parent = Path(temporary)
            work = parent / "new-work"
            work.mkdir()
            outside = parent / "existing-cache-fixture"
            outside.mkdir()
            sentinel = outside / "preserve.txt"
            sentinel.write_text("preserve existing cache", encoding="utf-8")
            environment, overrides = TOOL.prepare_worker_environment(work)
            command = [sys.executable, "-I", "-B", "-X", "utf8", "-c",
                       "import json,os,tempfile; print(json.dumps({'temporary':tempfile.gettempdir(),'cuda':os.environ['CUDA_CACHE_PATH'],'hf':os.environ['HF_HOME']}))"]
            result = json.loads(subprocess.check_output(command, env=environment, timeout=5))
            self.assertTrue(TOOL.inside(result["temporary"], work))
            self.assertEqual(result["cuda"], overrides["CUDA_CACHE_PATH"])
            self.assertEqual(result["hf"], overrides["HF_HOME"])
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve existing cache")

    def test_deadline_is_bounded_before_execution(self):
        for seconds in (0, 119, 3601):
            with self.subTest(seconds=seconds), self.assertRaises(TOOL.AcceptanceError):
                TOOL.main(["--root", "r", "--work", "w", "--audit", "a", "--model-inputs", "m", "--deadline-seconds", str(seconds)])

    def test_countable_text_is_not_satisfied_by_failure_message(self):
        self.assertEqual(TOOL.require_countable({"data": [{"text": "12345"}]}, expected=1)["recognizedTokens"], 1)
        with self.assertRaises(TOOL.AcceptanceError):
            TOOL.require_countable({"code": 902, "data": "no recognized fixture"})


class PdfFixtureUtilityTests(unittest.TestCase):
    """仅工具输入/断言回归，模拟字节不是PDF结构或GPU推理通过证据。"""
    def setUp(self):
        import hashlib
        self.temporary = tempfile.TemporaryDirectory(prefix="http-pdf-tool-", dir=ROOT / "build/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "selected.pdf"
        self.source.write_bytes(b"%PDF-utility-fixture-only\n")
        self.manifest = self.root / "fixtures.json"
        self.definition = {"document": {"path": str(self.source),
            "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(), "pageRange": [2, 2],
            "expectedPages": [2], "size": [1100, 1500],
            "truth": [{"token": "PAGE2TOKEN%02d" % index} for index in range(22)]}}
        self.manifest.write_text(json.dumps(self.definition), encoding="utf-8")

    def test_fixture_is_pinned_and_adjacent(self):
        fixture = TOOL.trusted_document_fixture(self.manifest)
        self.assertEqual(len(fixture["tokens"]), 22)
        self.assertEqual(fixture["pageRange"], [2, 2])
        self.assertIsNone(TOOL.trusted_document_fixture(None))
        self.source.write_bytes(b"changed")
        with self.assertRaises(TOOL.AcceptanceError):
            TOOL.trusted_document_fixture(self.manifest)

    def test_pdf_metrics_reject_wrong_page_missing_text_and_unbounded_points(self):
        fixture = TOOL.trusted_document_fixture(self.manifest)
        block = {"content": " ".join(fixture["tokens"]), "polygon": [[0, 0], [1100, 0], [1100, 1500], [0, 1500]]}
        result = {"code": 100, "data": {"pages": [{"page": 2}], "blocks": [block]}}
        self.assertEqual(TOOL.pdf_http_metrics(result, fixture)["identifierHits"], 22)
        for invalid in (
                {"code": 100, "data": {"pages": [{"page": 1}], "blocks": [block]}},
                {"code": 100, "data": {"pages": [{"page": 2}], "blocks": [{**block, "content": fixture["tokens"][0]}]}},
                {"code": 100, "data": {"pages": [{"page": 2}], "blocks": [{**block, "polygon": [[0, -35], [1100, 0], [0, 1500]]}]}}):
            with self.subTest(invalid=invalid), self.assertRaises(TOOL.AcceptanceError):
                TOOL.pdf_http_metrics(invalid, fixture)

    def test_worker_command_forwards_pdf_manifest_and_pdf_mime(self):
        from types import SimpleNamespace
        args = SimpleNamespace(model_inputs=self.root / "models.json", deadline_seconds=1800, document_fixture=self.manifest)
        command = TOOL.production_worker_command(args, Path(sys.executable), self.root, self.root / "work", self.root / "audit", "token")
        self.assertEqual(command[command.index("--document-fixture") + 1], str(self.manifest))
        client = TOOL.HttpClient(12345, time.monotonic() + 5)
        with patch.object(client, "json", return_value={"code": 100}) as sent:
            client.upload("/api/document/upload", b"fixture", {}, filename="selected.pdf")
        self.assertIn(b"Content-Type: application/pdf", sent.call_args.kwargs["body"])


if __name__ == "__main__":
    unittest.main()
