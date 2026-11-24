import argparse
import importlib.util
import struct
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build" / "tools"))
from staging_smoke import configure_runtime


HEAVY_MODULES = {"paddle", "paddleocr", "cv2", "numpy", "PIL", "fitz"}


def _loaded_heavy_modules():
    return {name for name in HEAVY_MODULES if name in sys.modules}


class _FakeProcess:
    def poll(self):
        return None


class _FakeWorker:
    def __init__(self):
        self.process = None
        self.starts = []
        self.stops = 0

    def start(self, config, timeout=None):
        if self.process is not None:
            self.stops += 1
        self.starts.append(dict(config))
        self.process = _FakeProcess()
        return {"ok": True, "status": "loaded"}

    def stop(self):
        if self.process is not None:
            self.stops += 1
        self.process = None


class _DeferredThread:
    def __init__(self, target, **_kwargs):
        self._target = target
        self._alive = False

    def start(self):
        self._alive = True

    def is_alive(self):
        return self._alive

    def run(self):
        self._target()
        self._alive = False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_root", type=Path)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    handles = configure_runtime(data_root)
    executable = data_root.parent / "Umi-OCR.exe"
    with executable.open("rb") as stream:
        stream.seek(0x3C)
        pe_offset = struct.unpack("<I", stream.read(4))[0]
        stream.seek(pe_offset + 24 + 68)
        assert struct.unpack("<H", stream.read(2))[0] == 2, (
            "Umi-OCR.exe must use the Windows GUI subsystem."
        )

    main_spec = importlib.util.spec_from_file_location(
        "umi_embedded_main", data_root / "main.py"
    )
    embedded_main = importlib.util.module_from_spec(main_spec)
    main_spec.loader.exec_module(embedded_main)
    original_popen = subprocess.Popen
    embedded_main.installNoConsoleSubprocess()
    wrapped_popen = subprocess.Popen
    assert issubclass(wrapped_popen, original_popen)
    with patch.object(original_popen, "__init__", return_value=None) as init:
        wrapped_popen(["where", "ccache"])
    assert init.call_args.kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW
    subprocess.Popen = original_popen

    from win32_PaddleOCRv6_CUDA import Api as api_factory
    from win32_PaddleOCRv6_CUDA.config import default_preprocess_threads
    from py_src.image_controller import image_provider
    from py_src.mission import doc_preview_connector
    from py_src.tag_pages import tag_pages_connector
    from py_src.utils import global_configs_connector

    assert not _loaded_heavy_modules(), _loaded_heavy_modules()
    assert default_preprocess_threads(4) == 4
    assert default_preprocess_threads(6) == 2
    assert default_preprocess_threads(16) == 12

    workers = []

    def make_worker():
        worker = _FakeWorker()
        workers.append(worker)
        return worker

    with patch("win32_PaddleOCRv6_CUDA.api._WorkerClient", side_effect=make_worker):
        api = api_factory({"device": "gpu:0", "preprocessThreads": 2})
        assert not _loaded_heavy_modules(), _loaded_heavy_modules()
        assert api.warmup({"taskType": "screenshot"}).startswith("[Success]")
        api._warmup_thread.join(10)
        assert len(workers) == 1 and len(workers[0].starts) == 1
        assert api.get_status()["state"] == "loaded"
        assert api.start({"taskType": "screenshot"}) == ""
        assert len(workers[0].starts) == 1
        assert api.start({"taskType": "document"}) == ""
        assert len(workers[0].starts) == 2 and workers[0].stops >= 1
        assert api.start({"taskType": "batch"}) == ""
        assert len(workers[0].starts) == 2
        assert api.release().startswith("[Success]")
        assert api.get_status()["state"] == "unloaded"

    foreground_workers = []

    def make_foreground_worker():
        worker = _FakeWorker()
        foreground_workers.append(worker)
        return worker

    with patch("win32_PaddleOCRv6_CUDA.api._WorkerClient", side_effect=make_foreground_worker), patch(
        "win32_PaddleOCRv6_CUDA.api.threading.Thread", _DeferredThread
    ):
        foreground_api = api_factory({"device": "gpu:0", "preprocessThreads": 2})
        foreground_api.warmup({"taskType": "screenshot"})
        deferred = foreground_api._warmup_thread
        assert foreground_api.start({"taskType": "document"}) == ""
        deferred.run()
        assert foreground_workers and foreground_workers[0].starts
        assert any(item["useDocUnwarping"] is True for item in foreground_workers[0].starts)
        foreground_api.stop()

    from py_src.platform.win32.win32_api import Api as WindowsApi

    with patch("subprocess.Popen") as popen:
        WindowsApi.runNewProcess("relative app.exe", '--force "two words"')
    argv = popen.call_args.args[0]
    kwargs = popen.call_args.kwargs
    assert argv == ["relative app.exe", "--force", "two words"]
    assert kwargs["shell"] is False
    assert kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW

    assert image_provider and doc_preview_connector and tag_pages_connector
    assert global_configs_connector
    del handles
    print("Startup laziness, warmup reuse, preprocess defaults and no-console tests passed.")


if __name__ == "__main__":
    main()
