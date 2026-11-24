"""原生模块运行子集的无损选择、来源保持和路径边界定向测试。"""
import argparse
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('tested_runtime_subset', ROOT / 'build/tools/runtime_subset.py')
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)
WORK = ROOT / 'build/tmp/dependency-trim-20261114-r1/unit'


class SubsetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=WORK)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.destination = self.root / 'subset'

    def file(self, name, data=b'x'):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_selects_native_modules_and_preserves_helpers_and_originals(self):
        self.file('__init__.py', b'helper')
        self.file('data/profile.json', b'{}')
        self.file('_shared.pyd', b'common')
        self.file('_jpegxl.cp313-win_amd64.pyd', b'jxl')
        self.file('_unused.pyd', b'unused codec')
        before = {p.relative_to(self.source).as_posix(): S.sha(p) for p in self.source.rglob('*') if p.is_file()}
        record = S.native_module_subset(self.source, self.destination, {'_shared', '_jpegxl'})
        self.assertEqual(record['inputBytes'] - record['outputBytes'], len(b'unused codec'))
        self.assertEqual(record['omittedBytes'], len(b'unused codec'))
        self.assertFalse((self.destination / '_unused.pyd').exists())
        self.assertTrue((self.destination / 'data/profile.json').is_file())
        self.assertEqual(before, {p.relative_to(self.source).as_posix(): S.sha(p) for p in self.source.rglob('*') if p.is_file()})
        self.assertEqual(record['status'], 'PROJECTED_NOT_RUNTIME_ACCEPTED')

    def test_missing_extension_fails_before_output_creation(self):
        self.file('_shared.pyd')
        with self.assertRaisesRegex(ValueError, '扩展缺失'):
            S.native_module_subset(self.source, self.destination, {'_missing'})
        self.assertFalse(self.destination.exists())

    def test_existing_destination_is_never_overwritten(self):
        self.file('_shared.pyd')
        self.destination.mkdir()
        marker = self.destination / 'user.txt'
        marker.write_text('preserve', encoding='utf-8')
        with self.assertRaises(ValueError):
            S.native_module_subset(self.source, self.destination, {'_shared'})
        self.assertEqual(marker.read_text('utf-8'), 'preserve')

    def test_nested_paths_and_module_path_traversal_are_rejected(self):
        self.file('_shared.pyd')
        with self.assertRaises(ValueError):
            S.native_module_subset(self.source, self.source / 'nested', {'_shared'})
        with self.assertRaises(ValueError):
            S.native_module_subset(self.source, self.destination, {'../_shared'})

    def test_ambiguous_abi_binaries_are_rejected(self):
        self.file('_shared.pyd')
        self.file('_shared.cp313-win_amd64.pyd')
        with self.assertRaisesRegex(ValueError, '多个原生构件'):
            S.native_module_subset(self.source, self.destination, {'_shared'})
        self.assertFalse(self.destination.exists())

    def test_link_is_rejected_before_copy(self):
        self.file('_shared.pyd')
        original = Path.is_symlink
        with patch.object(Path, 'is_symlink', lambda p: p == self.source or original(p)):
            with self.assertRaisesRegex(ValueError, '拒绝链接'):
                S.native_module_subset(self.source, self.destination, {'_shared'})
        self.assertFalse(self.destination.exists())

    def test_receipt_is_append_only(self):
        receipt = self.root / 'receipt.json'
        S.write_receipt(receipt, {'status': 'NOT_RUNTIME_ACCEPTED'})
        with self.assertRaises(FileExistsError):
            S.write_receipt(receipt, {'status': 'PASS'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--work', type=Path, default=WORK)
    args, remaining = parser.parse_known_args()
    WORK = args.work.resolve(strict=True)
    unittest.main(argv=[sys.argv[0], *remaining])
