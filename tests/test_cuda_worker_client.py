"""Worker restarts and UTF-8 protocol boundaries must remain isolated."""

import argparse
import inspect
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import patch


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
    # Permit the regression to demonstrate the prior implementation's failure.
    args = (client.process.stdout, old_responses) if len(inspect.signature(client._read).parameters) else ()
    thread = threading.Thread(target=client._read, args=args)
    thread.start()
    try:
        assert ready.wait(1)
        client.responses = queue.Queue()
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()
    assert client.responses.empty(), "old worker response polluted the restarted worker queue"
    assert old_responses.get_nowait()["old_worker"] is True


def test_worker_launch_uses_utf8():
    client = _WorkerClient()
    with (
        patch.dict(os.environ, {"PYTHONUTF8": "0", "PYTHONIOENCODING": "gbk", "UMI_UTF8_TEST": "keep"}),
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
            assert command[1:4] == ["-X", "utf8", "-u"]
            assert Path(command[-1]) == api_module.WORKER
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


def test_direct_worker_protocol_uses_utf8():
    text = "中文路径与识别结果：😀𠮷"
    diagnostic = "stderr 诊断：😀𠮷"
    # Isolate imports, then explicitly recreate hostile legacy streams. This
    # exercises the worker's direct-entry boundary even on a UTF-8 Windows ACP.
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
        cwd=ROOT,
        env=dict(os.environ, PYTHONUTF8="0", PYTHONIOENCODING="gbk"),
        text=True,
        encoding="utf-8",
        errors="strict",
        capture_output=True,
        check=True,
        timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert [json.loads(line) for line in result.stdout.splitlines()] == [
        {"ok": False, "error": "unknown worker operation: " + text},
        {"ok": True, "status": "stopped"},
    ]
    assert result.stderr == diagnostic + "\n", "diagnostics must not enter the JSON stdout stream"


def main():
    test_restart_response_isolation()
    test_worker_launch_uses_utf8()
    test_direct_worker_protocol_uses_utf8()
    print(f"CUDA worker source: {api_module.__file__}")
    print("CUDA worker restart isolation and UTF-8 protocol regressions passed.")


if __name__ == "__main__":
    main()
