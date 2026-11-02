"""请求捕获当前后端与能力隔离，不依赖 Qt 或真实模型。"""
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "UmiOCR-data"))
with patch.dict(sys.modules, {"umi_log": types.SimpleNamespace(logger=Mock())}):
    from py_src.server import backend_router
from py_src.mission.backend_runtime import RuntimeCoordinator


class BackendRouterTests(unittest.TestCase):
    def test_current_uses_immutable_handle_not_racing_gui_key(self):
        pool = RuntimeCoordinator()
        handle = pool.handle("ocr", "first", {"device": "gpu:0"}, lambda *_: None)
        current = types.SimpleNamespace(_api=handle, _apiKey="second", _deferAdmissions=False)
        schema = {"longSide": {"default": 4000}}
        registry = types.SimpleNamespace(has=lambda key: key == "first", localOptions=lambda key: schema)
        captured = []
        module = types.ModuleType("py_src.mission.mission_ocr")
        module.createMissionOcr = lambda key, config: captured.append((key, config)) or object()
        with patch.object(backend_router, "current_manager", return_value=current), \
             patch.object(backend_router, "getCapabilityRegistry", return_value=registry), \
             patch.dict(sys.modules, {module.__name__: module}):
            selected = backend_router.select_backend("ocr")
        self.assertEqual(selected.backend_id, "first")
        self.assertEqual(captured, [("first", {"device": "gpu:0"})])
        self.assertEqual(current._apiKey, "second")
        self.assertTrue(selected.private)
        self.assertEqual(selected.local_options, schema)
        schema["longSide"]["default"] = 999
        self.assertEqual(selected.local_options["longSide"]["default"], 4000)

    def test_unconfigured_current_is_frozen_without_borrowing_gui_manager(self):
        current = types.SimpleNamespace(_api=None, _apiKey="", _deferAdmissions=False)
        private = types.SimpleNamespace(shutdown=Mock())
        module = types.ModuleType("py_src.mission.mission_ocr")
        module.createMissionOcr = Mock(return_value=private)
        with patch.object(backend_router, "current_manager", return_value=current), \
             patch.dict(sys.modules, {module.__name__: module}):
            selected = backend_router.select_backend("ocr")
        current._apiKey = "later-selection"
        self.assertIs(selected.manager, private)
        self.assertTrue(selected.private)
        self.assertEqual(selected.backend_id, "")
        self.assertEqual(selected.local_options, {})
        module.createMissionOcr.assert_called_once_with("", {})
        selected.close()
        private.shutdown.assert_called_once()

    def test_explicit_backend_must_have_requested_capability(self):
        current = types.SimpleNamespace(_api=None, _apiKey="", _deferAdmissions=False)
        registry = types.SimpleNamespace(has=lambda key: False)
        with patch.object(backend_router, "current_manager", return_value=current), \
             patch.object(backend_router, "getCapabilityRegistry", return_value=registry):
            with self.assertRaises(ValueError):
                backend_router.select_backend("document", "ocr-only")


if __name__ == "__main__":
    unittest.main()
