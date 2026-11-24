"""CUDA预热参数回归；只使用假worker，不导入Qt或推理栈、不启动原生进程。"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class FakeProcess:
    def poll(self):
        return None


class FakeWorker:
    def __init__(self):
        self.process = None
        self.starts = []

    def start(self, config, timeout=None):
        self.starts.append(dict(config))
        self.process = FakeProcess()
        return {"ok": True}

    def stop(self):
        self.process = None


class DeferredThread:
    def __init__(self, target, **kwargs):
        self.target = target
        self.alive = False

    def start(self):
        self.alive = True

    def is_alive(self):
        return self.alive

    def run(self):
        try:
            self.target()
        finally:
            self.alive = False


class WarmupTests(unittest.TestCase):
    module = None

    def setUp(self):
        self.workers = []
        self.apis = []

        def make_worker():
            worker = FakeWorker()
            self.workers.append(worker)
            return worker

        worker_patch = patch.object(self.module, "_WorkerClient", side_effect=make_worker)
        worker_patch.start()
        self.addCleanup(worker_patch.stop)
        self.addCleanup(lambda: [api.stop() for api in self.apis])

    def make_api(self, options):
        api = self.module.Api(options)
        self.apis.append(api)
        return api

    def warm(self, api, options):
        self.assertTrue(api.warmup(options).startswith("[Success]"))
        api._warmup_thread.join(10)
        self.assertFalse(api._warmup_thread.is_alive())
        self.assertEqual(api.get_status()["state"], "loaded")
        return self.workers[-1].starts[-1]

    def test_constructor_device_is_preserved(self):
        config = self.warm(self.make_api({"device": "gpu:7"}), {"taskType": "screenshot"})
        self.assertEqual(config["device"], "gpu:7")

    def test_constructor_preprocess_threads_are_preserved(self):
        config = self.warm(self.make_api({"preprocessThreads": 2}), {"taskType": "screenshot"})
        self.assertEqual(config["preprocessThreads"], 2)

    def test_document_warmup_preserves_task_category(self):
        api = self.make_api({"preprocessThreads": 2})
        config = self.warm(api, {"taskType": "document"})
        self.assertTrue(config["useDocUnwarping"])
        self.assertEqual(api.start({"taskType": "document"}), "")
        self.assertEqual(len(self.workers[0].starts), 1)

    def test_batch_warmup_preserves_task_category(self):
        api = self.make_api({"preprocessThreads": 2})
        config = self.warm(api, {"taskType": "batch"})
        self.assertTrue(config["useDocUnwarping"])
        self.assertEqual(api.start({"taskType": "batch"}), "")
        self.assertEqual(len(self.workers[0].starts), 1)

    def test_screenshot_start_reuses_warmup(self):
        api = self.make_api({"preprocessThreads": 2})
        self.warm(api, {"taskType": "screenshot"})
        self.assertEqual(api.start({"taskType": "screenshot"}), "")
        self.assertEqual(len(self.workers[0].starts), 1)

    def test_existing_foreground_configuration_needs_no_warmup_thread(self):
        api = self.make_api({"device": "gpu:3", "preprocessThreads": 2})
        self.assertEqual(api.start({"taskType": "document"}), "")
        self.assertTrue(api.warmup({"taskType": "document"}).startswith("[Success]"))
        self.assertIsNone(api._warmup_thread)
        self.assertEqual(len(self.workers[0].starts), 1)

    def test_explicit_overrides_win_without_changing_constructor_options(self):
        options = {"device": "gpu:4", "preprocessThreads": 2, "longSide": 2000}
        api = self.make_api(options)
        config = self.warm(api, {"device": "gpu:5", "preprocessThreads": 3, "longSide": 3200})
        self.assertEqual((config["device"], config["preprocessThreads"], config["longSide"]), ("gpu:5", 3, 3200))
        self.assertEqual(api._globalArgd, options)

    def test_background_request_keeps_its_input_snapshot(self):
        api = self.make_api({"preprocessThreads": 2})
        options = {"taskType": "document", "longSide": 2800}
        with patch.object(self.module.threading, "Thread", DeferredThread):
            self.assertTrue(api.warmup(options).startswith("[Success]"))
            options.update(taskType="screenshot", longSide=5000)
            api._warmup_thread.run()
        config = self.workers[0].starts[-1]
        self.assertEqual(config["longSide"], 2800)
        self.assertTrue(config["useDocUnwarping"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-root", type=Path, default=ROOT / "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA")
    args = parser.parse_args()
    plugin = args.plugin_root.resolve(strict=True)
    package = "cuda_warmup_test_plugin"
    spec = importlib.util.spec_from_file_location(package, plugin / "__init__.py", submodule_search_locations=[str(plugin)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    module.Api({"device": "gpu:0"})
    WarmupTests.module = sys.modules[package + ".api"]
    if Path(WarmupTests.module.__file__).resolve() != plugin / "api.py":
        raise RuntimeError("未从指定插件读取实际适配器")
    print("CUDA warmup source:", WarmupTests.module.__file__)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(WarmupTests))
    if any(name in sys.modules for name in ("paddle", "paddleocr", "paddlex", "onnxruntime", "PySide6")):
        raise RuntimeError("轻量预热回归不得加载Qt或推理栈")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
