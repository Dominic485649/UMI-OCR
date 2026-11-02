"""验证worker代次隔离、原生入口、UTF-8协议和启动状态快照。"""

import argparse
import importlib.util
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("data_root", nargs="?", type=Path, default=ROOT / "UmiOCR-data")
args = parser.parse_args()
sys.path.insert(0, str(args.data_root.resolve() / "plugins"))
from win32_PaddleOCRv6_CUDA import api as api_module
from win32_PaddleOCRv6_CUDA.api import _WorkerClient


def test_restart_response_isolation():
    ready = threading.Event()
    release = threading.Event()

    class OldStream:
        def __iter__(self):
            ready.set()
            assert release.wait(3)
            yield '{"ok":true,"old_worker":true}\n'

    client = _WorkerClient()
    client.process = SimpleNamespace(stdout=OldStream())
    old_responses = client.responses
    thread = threading.Thread(target=client._read, args=(client.process.stdout, old_responses))
    thread.start()
    try:
        assert ready.wait(1)
        client.responses = queue.Queue()
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()
    assert client.responses.empty(), "旧worker响应或EOF污染了新代次队列"
    assert old_responses.get_nowait()["old_worker"] is True
    assert old_responses.get_nowait()["ok"] is False


def test_worker_launch_uses_utf8():
    client = _WorkerClient()
    with (
        patch.dict(os.environ, {"PYTHONUTF8": "0", "PYTHONIOENCODING": "gbk", "UMI_UTF8_TEST": "keep"}),
        patch.object(api_module.Path, "is_file", return_value=True),
        patch.object(api_module.tempfile, "NamedTemporaryFile") as stderr_file,
        patch.object(api_module.subprocess, "Popen") as popen,
        patch.object(api_module.threading, "Thread"),
        patch.object(client, "request", return_value={"ok": True}),
    ):
        popen.return_value.poll.return_value = 0
        try:
            assert client.start({}, timeout=1) == {"ok": True}
            command = popen.call_args.args[0]
            options = popen.call_args.kwargs
            assert command == [str(api_module.WORKER_LAUNCHER)]
            assert options["cwd"] == str(api_module.PLUGIN_DIR)
            assert options["shell"] is False
            assert options["env"] is not os.environ
            assert options["env"]["PYTHONUTF8"] == "1"
            assert options["env"]["PYTHONIOENCODING"] == "utf-8"
            assert options["env"]["UMI_UTF8_TEST"] == "keep"
            assert os.environ["PYTHONUTF8"] == "0"
            assert os.environ["PYTHONIOENCODING"] == "gbk"
            assert options["text"] is True and options["encoding"] == "utf-8"
            assert options["stdin"] == subprocess.PIPE
            assert options["stdout"] == subprocess.PIPE
            assert options["stderr"] is stderr_file.return_value
        finally:
            client.stop()


def test_missing_launcher_does_not_fall_back():
    client = _WorkerClient()
    with patch.object(api_module, "WORKER_LAUNCHER", SimpleNamespace(is_file=lambda: False)), patch.object(api_module.subprocess, "Popen") as popen:
        try:
            client.start({}, timeout=180)
            raise AssertionError("缺少原生入口时不应启动备用解释器")
        except FileNotFoundError:
            pass
        popen.assert_not_called()


def test_eof_is_a_response_not_a_timeout():
    client = _WorkerClient()
    client.process = SimpleNamespace(stdin=io.StringIO(), poll=lambda: None)
    client._read(io.StringIO(), client.responses)
    response = client.request({"op": "start"}, timeout=180)
    assert response["ok"] is False and "stream closed" in response["error"]
    client.process = None


def test_failed_spawn_closes_stderr():
    client = _WorkerClient()
    diagnostic = io.StringIO()
    client.stderr_file = diagnostic
    client.stop()
    assert diagnostic.closed and client.stderr_file is None


def test_api_startup_is_an_independent_snapshot():
    startup = {"pid": 12, "native_code_page": 65001, "model_names": ["det", "rec"]}
    worker = Mock()
    worker.process.poll.return_value = None
    worker.start.return_value = {"ok": True, "startup": startup}
    with patch.object(api_module, "_WorkerClient", return_value=worker):
        api = api_module.Api({"device": "gpu:0"})
        assert api.get_status()["startup"] == {}
        assert api.start({"taskType": "document"}) == ""
        startup["model_names"].append("not copied")
        snapshot = api.get_status()["startup"]
        assert snapshot["model_names"] == ["det", "rec"]
        snapshot["model_names"].append("caller change")
        assert api.get_status()["startup"]["model_names"] == ["det", "rec"]
        worker.start.side_effect = RuntimeError("expected startup failure")
        assert api.start({"taskType": "screenshot"}).startswith("[Error]")
        assert api.get_status()["startup"] == {}
        worker.start.side_effect = None
        assert api.start({"taskType": "document"}) == ""
        api.release()
        assert api.get_status()["startup"] == {}


def test_startup_metadata_does_not_load_inference():
    spec = importlib.util.spec_from_file_location("cuda_worker_metadata_test", api_module.WORKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    kernel32 = SimpleNamespace(GetACP=Mock(return_value=65001), GetModuleFileNameW=Mock())

    def module_name(_handle, buffer, _capacity):
        buffer.value = "C:\\test\\runtime\\python313.dll"
        return len(buffer.value)

    kernel32.GetModuleFileNameW.side_effect = module_name
    config = api_module.Api._normalize_config({"taskType": "document"})
    import ctypes
    with patch.object(ctypes, "WinDLL", return_value=kernel32):
        info = module.startup_info(config)
        assert info["model_names"] == ["PP-LCNet_x1_0_doc_ori", "UVDoc", "PP-LCNet_x1_0_textline_ori", "PP-OCRv6_medium_det", "PP-OCRv6_medium_rec"]
        assert info["pid"] == os.getpid() and info["native_code_page"] == 65001
        assert info["python_utf8_mode"] is True
        assert info["python_dll"] == "C:\\test\\runtime\\python313.dll"
        kernel32.GetACP.return_value = 936
        try:
            module.startup_info(config)
            raise AssertionError("原生ACP936必须在初始化Paddle之前失败")
        except RuntimeError as exc:
            assert "UTF-8" in str(exc)
    assert not any(name in sys.modules for name in ("paddle", "paddleocr", "cv2", "numpy"))


def test_direct_worker_protocol_uses_utf8():
    text = "中文路径与识别结果：😀𠮷"
    diagnostic = "stderr 诊断：😀𠮷"
    probe = """
import runpy
import sys
for stream in (sys.stdin, sys.stdout, sys.stderr):
    stream.reconfigure(encoding="gbk")
runpy.run_path(sys.argv[1], run_name="__main__")
sys.stderr.write(sys.argv[2] + "\\n")
assert not any(name in sys.modules for name in ("paddle", "paddleocr", "cv2", "numpy"))
"""
    requests = [{"op": text}, {"op": "stop"}]
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-S", "-X", "utf8", "-c", probe, str(api_module.WORKER), diagnostic],
        input="".join(json.dumps(request, ensure_ascii=False) + "\n" for request in requests),
        cwd=ROOT, env=dict(os.environ, PYTHONUTF8="0", PYTHONIOENCODING="gbk"),
        text=True, encoding="utf-8", errors="strict", capture_output=True,
        check=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert responses == [
        {"ok": False, "error": "unknown worker operation: " + text, "errorType": "INFERENCE_FAILED"},
        {"ok": True, "status": "stopped"},
    ], responses
    assert result.stderr == diagnostic + "\n"


def main():
    tests = [test_restart_response_isolation, test_worker_launch_uses_utf8, test_missing_launcher_does_not_fall_back, test_eof_is_a_response_not_a_timeout, test_failed_spawn_closes_stderr, test_api_startup_is_an_independent_snapshot, test_startup_metadata_does_not_load_inference, test_direct_worker_protocol_uses_utf8]
    for test in tests:
        test()
    print(f"CUDA worker source: {api_module.__file__}")
    print(f"CUDA worker startup/protocol regressions passed: {len(tests)} tests; no inference dependencies loaded.")


if __name__ == "__main__":
    main()
