"""QtCore-only 核验原生驱动的便携依赖与内嵌别名门禁，不创建窗口。"""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "tests/test_settings_center_native_ui.py"


def run(data):
    packages = data.resolve(strict=True) / "site-packages"
    sys.path.insert(0, str(packages))
    handle = os.add_dll_directory(str(packages / "PySide6"))
    from PySide6 import QtCore
    spec = importlib.util.spec_from_file_location("native_provenance_driver", DRIVER)
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    owner = packages / "shiboken6/Shiboken.pyd"
    dependencies = {str(owner): driver.sha256(owner)}

    class ProvenanceTests(unittest.TestCase):
        def test_real_embedded_aliases_and_binary_owner(self):
            result = driver.qt_dependency_sources(packages, dependencies)
            record = result["embedded_modules"]["PySide6.support.feature"]
            self.assertEqual(record["canonical_module"], "shibokensupport.feature")
            self.assertEqual(record["virtual_file"], "shibokensupport/feature.py")
            self.assertEqual(len(record["embedded_source_sha256"]), 64)
            self.assertEqual(result["embedded_owner"]["sha256"], dependencies[str(owner)])
            self.assertIn("PySide6.QtCore", result["file_modules"])

        def test_unrelated_relative_module_is_rejected(self):
            fake = ModuleType("PySide6.untrusted")
            fake.__file__ = "untrusted/module.py"
            with mock.patch.dict(sys.modules, {fake.__name__: fake}):
                with self.assertRaisesRegex(AssertionError, "不是已核对的内嵌模块"):
                    driver.qt_dependency_sources(packages, dependencies)

        def test_canonical_identity_cannot_be_spoofed(self):
            fake = ModuleType("shibokensupport.feature")
            fake.__file__ = "shibokensupport/feature.py"
            fake.__loader__ = sys.modules["shibokensupport"].__loader__
            with mock.patch.dict(sys.modules, {"PySide6.support.feature": fake}):
                with self.assertRaises(AssertionError):
                    driver.qt_dependency_sources(packages, dependencies)

        def test_wrong_loader_is_rejected(self):
            feature = sys.modules["shibokensupport.feature"]
            with mock.patch.object(feature, "__loader__", object()):
                with self.assertRaises(AssertionError):
                    driver.qt_dependency_sources(packages, dependencies)

        def test_changed_binary_hash_is_rejected(self):
            with self.assertRaisesRegex(AssertionError, "哈希已改变"):
                driver.qt_dependency_sources(packages, {str(owner): "0" * 64})

        def test_external_absolute_origin_is_rejected(self):
            fake = ModuleType("PySide6.untrusted")
            fake.__file__ = str(ROOT / "tests/untrusted-qt.py")
            with mock.patch.dict(sys.modules, {fake.__name__: fake}):
                with self.assertRaisesRegex(AssertionError, "不是指定只读便携依赖"):
                    driver.qt_dependency_sources(packages, dependencies)

    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ProvenanceTests))
    assert "PySide6.QtGui" not in sys.modules and "PySide6.QtWidgets" not in sys.modules
    assert not {"paddle", "torch", "paddlex", "paddleocr"}.intersection(sys.modules)
    print("仅QtCore，Qt版本=" + QtCore.qVersion() + "；未创建窗口或导入推理库。")
    del handle
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", type=Path)
    raise SystemExit(run(parser.parse_args().data_root))
