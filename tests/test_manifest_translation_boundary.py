"""宿主诊断与插件显示文案使用各自译器，不让局部 callback 遮蔽宿主 tr。"""
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "UmiOCR-data"))
with patch.dict(sys.modules, {"umi_log": types.SimpleNamespace(logger=Mock())}):
    from py_src.plugins_controller import manifest


class ManifestTranslationBoundary(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="manifest-translation-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.host = patch.object(manifest, "tr", side_effect=lambda template, **values: "host:" + template.format(**values))
        self.host.start()
        self.addCleanup(self.host.stop)

    def load(self, value):
        (self.root / "umi-plugin.json").write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return manifest.loadManifest("test", str(self.root), translator=lambda text: "plugin:" + text)

    def test_invalid_manifest_before_callback_definition_uses_host_translator(self):
        for value in ([], {}, {"schema_version": 1}, {"schema_version": 1, "id": "other"}):
            with self.subTest(value=value):
                parsed, error = self.load(value)
                self.assertIsNone(parsed)
                self.assertTrue(error.startswith("host:"), error)

    def test_later_validation_does_not_look_in_plugin_catalogue(self):
        parsed, error = self.load({"schema_version": 1, "id": "test", "version": "3.1.0", "capabilities": ["invalid"]})
        self.assertIsNone(parsed)
        self.assertTrue(error.startswith("host:"), error)

    def test_plugin_metadata_and_inline_display_use_plugin_translator(self):
        parsed, error = self.load({"schema_version": 1, "id": "test", "version": "3.1.0",
            "name": "Product", "description": "Description", "capabilities": [{"type": "ocr", "entry": "api:Api",
            "config": {"title": "模型", "default": "machine", "nameFilters": ["模型 (*.gguf)"],
                       "optionsList": [["id", "显示"]]}}]})
        self.assertEqual(error, "")
        self.assertEqual(parsed.name, "plugin:Product")
        self.assertEqual(parsed.description, "plugin:Description")
        self.assertEqual(parsed.capabilities[0].config["title"], "plugin:模型")
        self.assertEqual(parsed.capabilities[0].config["default"], "machine")
        self.assertEqual(parsed.capabilities[0].config["nameFilters"], ["plugin:模型 (*.gguf)"])
        self.assertEqual(parsed.capabilities[0].config["optionsList"], [["id", "plugin:显示"]])


if __name__ == "__main__":
    unittest.main()
