"""布局统计只读边界与Windows分配空间接口的定向验证。"""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build/tmp/startup-small-files-20261028-r1/layout-tests"
spec = importlib.util.spec_from_file_location("layout_measurement", ROOT / "build/tools/measure_runtime_layout.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RuntimeLayoutMeasurementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        WORK.mkdir(parents=True, exist_ok=True)
        if WORK.resolve() != WORK.absolute():
            raise ValueError("只允许本项目非链接临时目录")

    def test_file_counts_areas_and_content_unchanged(self):
        with tempfile.TemporaryDirectory(dir=WORK) as temporary:
            root = Path(temporary)
            files = {"UmiOCR-data/py_src/a.py": b"x", "UmiOCR-data/plugins/demo/vendor/b.py": b"a" * 65536,
                     "UmiOCR-data/plugins/demo/model.bin": b"b" * 65537, "LICENSES/notice.txt": b"license"}
            for name, content in files.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            result = module.measure(root)
            self.assertEqual(result["total"]["files"], 4)
            self.assertEqual(result["total"]["smallFiles64KiB"], 3)
            self.assertEqual(result["total"]["pythonFiles"], 2)
            self.assertEqual(result["total"]["logicalBytes"], sum(map(len, files.values())))
            self.assertEqual(result["areas"]["UmiOCR-data/plugins/demo"]["files"], 2)
            for name, content in files.items():
                self.assertEqual((root / name).read_bytes(), content)
            self.assertEqual(sum(p.is_file() for p in root.rglob("*")), 4)
            if os.name == "nt":
                self.assertEqual(result["total"]["allocationUnavailable"], 0)
                self.assertGreaterEqual(result["total"]["allocatedBytes"], 0)

    def test_package_mode_and_empty_tree(self):
        with tempfile.TemporaryDirectory(dir=WORK) as temporary:
            root = Path(temporary)
            self.assertEqual(module.measure(root)["total"]["files"], 0)
            (root / "demo").mkdir()
            (root / "demo/py.typed").write_bytes(b"")
            (root / "demo/a.py").write_bytes(b"pass\n")
            self.assertEqual(module.measure(root, packages=True)["areas"]["demo"]["files"], 2)

    def test_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory(dir=WORK) as temporary:
            root = Path(temporary)
            (root / "target").write_bytes(b"secret")
            try:
                (root / "link").symlink_to(root / "target")
            except OSError:
                self.skipTest("当前账户不能创建符号链接；未改权限")
            with self.assertRaises(ValueError):
                module.measure(root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
