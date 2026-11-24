"""模型设置改动的源码打包与文案迁移边界，不加载 Qt/GPU。"""
import ast
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build/tools"))
from source_snapshot import is_excluded
from template_model_settings_messages import migrate


def translated(node):
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        raise AssertionError("该回归只允许迁移可见字面量，不应把列表拼接改成字符串")
    return ast.Call(func=ast.Name(id="tr", ctx=ast.Load()), args=[node], keywords=[]), node.value


ENGINE = types.SimpleNamespace(
    is_translation=lambda node: isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr",
    has_han=lambda node: any(isinstance(item, ast.Constant) and isinstance(item.value, str)
                             and re.search(r"[㐀-鿿]", item.value) for item in ast.walk(node)),
    translated=translated)


class ModelSettingsBuildInputs(unittest.TestCase):
    def test_translation_csv_is_in_corresponding_source_and_runtime(self):
        for relative in ("UmiOCR-data/i18n/runtime.csv", "UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/i18n.csv"):
            self.assertFalse(is_excluded(Path(relative), public=True), relative)
        self.assertTrue(is_excluded(Path("UmiOCR-data/plugins/win32_PaddleOCRVL_1_6/i18n.csv"), public=True))

    def migrate(self, source):
        temporary = tempfile.TemporaryDirectory(prefix="message-migration-")
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "example.py"
        path.write_text(source, encoding="utf-8")
        report = migrate(path, ENGINE)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        tree.body = [node for node in tree.body if not isinstance(node, ast.ImportFrom)]
        namespace = {"tr": lambda message, **values: message.format(**values)}
        exec(compile(tree, str(path), "exec"), namespace)
        return report, tree, namespace

    def test_standalone_json_documentation_is_not_executed_as_translation(self):
        report, _, namespace = self.migrate('''def value():
    """函数说明。"""
    '接口示例 {"code": 100}'
    return '可见状态'
''')
        self.assertEqual(namespace["value"](), "可见状态")
        self.assertEqual(report["templates"], ["可见状态"])

    def test_previous_documentation_migration_is_repaired(self):
        report, tree, namespace = self.migrate('''def value():
    tr('接口示例 {"code": 100}')
    return '可见状态'
''')
        self.assertEqual(namespace["value"](), "可见状态")
        self.assertEqual(report["restoredComments"], ['接口示例 {"code": 100}'])
        self.assertIsInstance(tree.body[0].body[0].value, ast.Constant)

    def test_list_concatenation_remains_a_list(self):
        report, _, namespace = self.migrate('''def value():
    return ['第一项'] + ['第二项']
''')
        self.assertEqual(namespace["value"](), ["第一项", "第二项"])
        self.assertEqual(report["templates"], ["第一项", "第二项"])


if __name__ == "__main__":
    unittest.main()
