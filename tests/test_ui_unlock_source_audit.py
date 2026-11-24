"""允许精确宿主策略声明，不放宽纯本体对插件实现/导入/模型路径的边界。"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'build/tools'))
from audit_runtime_archives import public_content
from runtime_archive_layout import LayoutError


class SourceAuditTests(unittest.TestCase):
    def test_exact_host_declarations(self):
        declaration = b'ID = (\n    "win32_PaddleOCRVL_1_6"\n)\n'
        for name in ('py_src/plugins_controller/manifest.py', 'py_src/utils/ui_unlock.py'):
            public_content(name, declaration, ['PaddleOCRVL'])
            with self.assertRaises(LayoutError):
                public_content(name, declaration + b'import PaddleOCRVL\n', ['PaddleOCRVL'])
            with self.assertRaises(LayoutError):
                public_content(name, b'path = "win32_PaddleOCRVL_1_6/worker.py"\n', ['PaddleOCRVL'])

    def test_other_paths_still_rejected(self):
        for name in ('py_src/other/ui_unlock.py', 'py_src/worker.py', 'py_src/plugins_controller/other.py'):
            with self.assertRaises(LayoutError):
                public_content(name, b'ID = (\n    "win32_PaddleOCRVL_1_6"\n)\n', ['PaddleOCRVL'])

    def test_actual_host_policy_is_not_plugin_implementation(self):
        path = ROOT / 'UmiOCR-data/py_src/utils/ui_unlock.py'
        terms = ['PaddleOCR-VL', 'PaddleOCRVL', 'PaddleVL', 'PP-DocLayoutV3', 'llama.cpp', 'gguf', 'mmproj']
        public_content('py_src/utils/ui_unlock.py', path.read_bytes(), terms)
        qml = ROOT / 'UmiOCR-data/qt_res/qml/Configs/GlobalConfigs.qml'
        public_content('qt_res/qml/Configs/GlobalConfigs.qml', qml.read_bytes(), terms)


if __name__ == '__main__':
    unittest.main()
