"""原生核心来源门禁的定向合成测试，不导入或执行被测运行包。"""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('pymupdf_gate_test', ROOT / 'build/tools/verify_release_evidence.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class MuPdfSourceGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.stage = Path(self.temporary.name)
        self.vendor = self.stage / 'UmiOCR-data/site-packages'
        self.vendor.mkdir(parents=True)

    def gate(self):
        return M.verify_pymupdf_corresponding_source(self.stage, self.vendor)

    def test_absent_component_is_not_included(self):
        self.assertEqual(self.gate()['status'], 'NOT_INCLUDED')

    def test_missing_native_file_cannot_pass(self):
        (self.vendor / 'pymupdf').mkdir()
        result = self.gate()
        self.assertEqual(result['status'], 'BLOCK')
        self.assertIsNone(result['native_extension'])
        self.assertIsNone(result['observed_native_core_version'])

    def test_known_wheel_is_blocked_despite_matching_binding_sdist(self):
        native = self.vendor / 'pymupdf/_mupdf.pyd'
        native.parent.mkdir()
        native.write_bytes(b'fixture, not executable')
        source = self.stage / 'source/third_party/pymupdf-1.28.0.tar.gz'
        source.parent.mkdir(parents=True)
        source.write_bytes(b'existence alone is not correspondence')
        with patch.object(M, 'file_record', return_value={
                'artifact_path': 'UmiOCR-data/site-packages/pymupdf/_mupdf.pyd',
                'SHA256': '000d93f313bd541de0a302e3c17b8a4ce51afe788c6062b225b2d02d52cea7ec'}):
            result = self.gate()
        self.assertEqual(result['status'], 'BLOCK')
        self.assertTrue(result['known_unbound_native_artifact'])
        self.assertEqual(result['observed_native_core_version'], '1.29.0')
        self.assertFalse(result['verified'])

    def test_unknown_native_does_not_inherit_version_or_source(self):
        native = self.vendor / 'pymupdf/_mupdf.pyd'
        native.parent.mkdir()
        native.write_bytes(b'unknown native fixture')
        result = self.gate()
        self.assertEqual(result['status'], 'BLOCK')
        self.assertFalse(result['known_unbound_native_artifact'])
        self.assertIsNone(result['observed_native_core_version'])

    def test_metadata_only_and_legacy_namespace_cannot_hide_component(self):
        for name in ('pymupdf-1.28.0.dist-info', 'fitz'):
            with self.subTest(name=name):
                target = self.vendor / name
                target.mkdir()
                self.assertEqual(self.gate()['status'], 'BLOCK')
                target.rmdir()

    def test_source_block_vetoes_otherwise_verified_publication(self):
        gates = {
            'source_delivery': {'status': 'PASS', 'verified': True},
            'current_source_e2e': {'status': 'PASS', 'verified': True, 'publication_authorized': True},
            'pymupdf_corresponding_source': {'status': 'BLOCK'},
        }
        self.assertFalse(M.public_release_allowed(gates))
        self.assertIn('pymupdf-corresponding-source.json', M.report_markdown('base', gates))
        gates['pymupdf_corresponding_source'] = {'status': 'NOT_INCLUDED'}
        self.assertTrue(M.public_release_allowed(gates))


if __name__ == '__main__':
    unittest.main()
