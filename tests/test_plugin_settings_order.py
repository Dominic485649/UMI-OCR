"""只执行真实 PluginRecord 元数据代码，不导入插件服务或推理依赖。"""
import ast
import math
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "UmiOCR-data/py_src/plugins_controller/plugins_controller.py"


class PluginSettingsOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
        node = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "PluginRecord")
        namespace = {"math": math, "STATE_INVALID": "invalid"}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"), namespace)
        cls.record_type = namespace["PluginRecord"]

    def record(self, capabilities, state="ready"):
        record = self.record_type("arbitrary-plugin-id", "not-accessed")
        record.state = state
        record.manifest = SimpleNamespace(toDict=lambda: {"name": "任意显示名", "capabilities": [cap.type for cap in capabilities]}, capabilities=capabilities)
        return record

    def test_valid_order_is_available_even_when_disabled(self):
        for state in ("ready", "disabled", "incompatible", "unhealthy"):
            record = self.record([SimpleNamespace(type="ocr", meta={"settingsOrder": 10})], state)
            self.assertEqual(record.toDict()["settingsOrder"], 10)
            self.assertEqual(record.toDict()["state"], state)

    def test_invalid_order_does_not_become_an_implicit_priority(self):
        for value in (None, True, False, "10", [], {}, float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=value):
                record = self.record([SimpleNamespace(type="ocr", meta={"settingsOrder": value})])
                self.assertNotIn("settingsOrder", record.toDict())

    def test_multiple_ocr_orders_use_the_smallest_finite_number(self):
        record = self.record([SimpleNamespace(type="ocr", meta={"settingsOrder": value}) for value in (20, 10.5, 15)])
        self.assertEqual(record.toDict()["settingsOrder"], 10.5)

    def test_unrelated_capability_cannot_promote_its_plugin(self):
        record = self.record([SimpleNamespace(type="document", meta={"settingsOrder": -100}), SimpleNamespace(type="ocr", meta={"settingsOrder": 20})])
        self.assertEqual(record.toDict()["settingsOrder"], 20)
        self.assertNotIn("settingsOrder", self.record([]).toDict())

    def test_invalid_manifest_remains_visible_without_a_fake_order(self):
        record = self.record_type("invalid-plugin", "not-accessed")
        info = record.toDict()
        self.assertEqual(info["state"], "invalid")
        self.assertEqual(info["name"], "invalid-plugin")
        self.assertNotIn("settingsOrder", info)
        self.assertFalse(info["legacy"])


if __name__ == "__main__":
    unittest.main()
