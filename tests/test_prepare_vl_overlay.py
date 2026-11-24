"""VL 安装 overlay 保留对应源码且不覆盖主程序元数据。"""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build/tools"))
import prepare_vl_overlay as tool


class VlOverlayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="vl-overlay-", dir=ROOT / "build/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.stage = self.root / "staging"
        self.plugin = self.stage / "UmiOCR-data/plugins" / tool.PLUGIN
        self.plugin.mkdir(parents=True)
        self.manifest = {"id": tool.PLUGIN, "version": "3.1.0"}
        (self.plugin / "umi-plugin.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        (self.plugin / "runtime.py").write_text("# source\n", encoding="utf-8")
        source = self.stage / "source"
        for relative in ("Build-Plugin.ps1", "VERSION", "requirements.lock", "SOURCE-CODE.md",
                         "tools/bundle_llama_runtime.py", tool.PLUGIN + "/runtime.py", tool.PLUGIN + "/umi-plugin.json"):
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("source\n", encoding="utf-8")
        (source / "VERSION").write_text("3.1.0\n", encoding="utf-8")
        (source / tool.PLUGIN / "umi-plugin.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        (self.stage / "LICENSES").mkdir()
        (self.stage / "LICENSES/NOTICE.md").write_text("license", encoding="utf-8")

    def test_new_overlay_has_only_plugin_and_namespaced_license_roots(self):
        output = self.root / "overlay"
        report = tool.preserve(self.stage, output, overlay=True)
        self.assertEqual({path.name for path in output.iterdir()}, {"UmiOCR-data", "LICENSES"})
        self.assertEqual(report["version"], "3.1.0")
        records = output / "LICENSES/plugins" / tool.PLUGIN / "source-records"
        self.assertEqual((records / "VERSION").read_text(), "3.1.0\n")
        self.assertEqual(tool.digest(records / "Build-Plugin.ps1"), tool.digest(self.stage / "source/Build-Plugin.ps1"))
        self.assertFalse(report["publicReleaseAuthorized"])
        with self.assertRaises(FileExistsError):
            tool.preserve(self.stage, output, overlay=True)

    def test_retention_does_not_change_host_metadata(self):
        output = self.root / "combined"
        (output / "UmiOCR-data/plugins").mkdir(parents=True)
        shutil.copytree(self.plugin, output / "UmiOCR-data/plugins" / tool.PLUGIN)
        (output / "VERSION").write_text("9.0.0\n", encoding="utf-8")
        (output / "SOURCE-CODE.md").write_text("host-source", encoding="utf-8")
        tool.preserve(self.stage, output)
        self.assertEqual((output / "VERSION").read_text(), "9.0.0\n")
        self.assertEqual((output / "SOURCE-CODE.md").read_text(), "host-source")
        with self.assertRaises(FileExistsError):
            tool.preserve(self.stage, output)

    def test_mismatched_corresponding_source_fails_before_output(self):
        (self.stage / "source/VERSION").write_text("3.0.0\n", encoding="utf-8")
        output = self.root / "overlay"
        with self.assertRaises(ValueError):
            tool.preserve(self.stage, output, overlay=True)
        self.assertFalse(output.exists())

    def test_retention_rejects_link_in_namespaced_license_ancestors(self):
        output = self.root / "combined"
        (output / "UmiOCR-data/plugins").mkdir(parents=True)
        shutil.copytree(self.plugin, output / "UmiOCR-data/plugins" / tool.PLUGIN)
        license_root = output / "LICENSES"
        license_root.mkdir()
        with patch.object(Path, "is_junction", lambda path: path == license_root):
            with self.assertRaises(ValueError):
                tool.preserve(self.stage, output)
        self.assertFalse((license_root / "plugins").exists())

    def test_links_are_rejected(self):
        with patch.object(Path, "is_junction", return_value=True):
            with self.assertRaises(ValueError):
                tool.preserve(self.stage, self.root / "overlay", overlay=True)


if __name__ == "__main__":
    unittest.main()
