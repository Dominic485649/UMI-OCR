"""托盘验收的退出前 HTTP 就绪回归，不启动 GUI 或修改设置。"""
import importlib.util
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import Mock, patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tray_readiness_test", ROOT / "tests/test_windows_tray.py")
tray = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tray)


class Response:
    def __init__(self, body=b"Umi-OCR v3.0.2", status=200):
        self.body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.body[:limit]


class ReadinessTests(TestCase):
    def probe(self, opener, process=None, timeout=2):
        return tray.wait_http_ready(opener, "http://127.0.0.1:12345", process or Mock(poll=Mock(return_value=None)), "3.0.2", timeout)

    def test_success_requires_actual_identity_response(self):
        opener = Mock(open=Mock(return_value=Response()))
        result = self.probe(opener)
        self.assertEqual(result, {"ready": True, "status": 200, "identity": "Umi-OCR v3.0.2", "attempts": 1})
        self.assertEqual(opener.open.call_args.args, ("http://127.0.0.1:12345/umiocr",))

    def test_transient_connection_failure_retries_before_quit(self):
        opener = Mock(open=Mock(side_effect=[urllib.error.URLError("refused"), Response()]))
        with patch.object(tray.time, "sleep"):
            result = self.probe(opener)
        self.assertTrue(result["ready"])
        self.assertEqual(result["attempts"], 2)

    def test_wrong_service_or_version_cannot_pass(self):
        for body in (b"Other service v3.0.2", b"Umi-OCR v3.0.20", b"Umi-OCR v3.0.1"):
            with self.subTest(body=body):
                opener = Mock(open=Mock(return_value=Response(body)))
                with self.assertRaisesRegex(RuntimeError, "Unexpected Umi-OCR"):
                    self.probe(opener)
                self.assertEqual(opener.open.call_count, 1)

    def test_exited_child_is_not_ready(self):
        opener = Mock()
        with self.assertRaisesRegex(RuntimeError, "exited before HTTP readiness"):
            self.probe(opener, Mock(poll=Mock(return_value=1)))
        opener.open.assert_not_called()

    def test_timeout_never_fabricates_readiness(self):
        opener = Mock(open=Mock(side_effect=urllib.error.URLError("refused")))
        with patch.object(tray.time, "monotonic", side_effect=[0, 0, 3, 3]), patch.object(tray.time, "sleep"):
            with self.assertRaisesRegex(TimeoutError, "HTTP readiness timed out"):
                self.probe(opener)
        self.assertEqual(opener.open.call_count, 1)


if __name__ == "__main__":
    main(verbosity=2)
