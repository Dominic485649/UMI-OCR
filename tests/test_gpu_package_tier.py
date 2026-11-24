"""GPU 档位、运行记录与发布文件名的定向回归；不加载 Paddle。"""
import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'build/tools'
PLUGIN = ROOT / 'UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA'
sys.path.insert(0, str(TOOLS))
import gpu_package_tier as tier
import reviewed_gpu_seed as seed


def load_config():
    pkg = types.ModuleType('cuda_tier_fixture')
    pkg.__path__ = [str(PLUGIN)]
    sys.modules[pkg.__name__] = pkg
    return importlib.import_module(pkg.__name__ + '.config')


class PackageTierTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='gpu-package-tier-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()

    def fixture(self, kind, actual, version='3.0.8'):
        path = self.root / 'UmiOCR-data/plugins' / tier.IDS[kind]
        path.mkdir(parents=True, exist_ok=True)
        support = (ROOT / 'build' / f'cuda-support-{actual}.lock.json').read_bytes()
        (path / 'cuda-support.json').write_bytes(support)
        checksum = hashlib.sha256(support).hexdigest()
        if kind == 'cuda':
            frozen = {'pluginId': tier.IDS[kind], 'version': version, 'gpuSupportSha256': checksum,
                      'lock': f'build/requirements-gpu-plugin-windows-{actual}.lock'}
        else:
            frozen = {'pluginId': tier.IDS[kind], 'files': [{'path': 'cuda-support.json', 'sha256': checksum}]}
        (path / 'runtime.lock.json').write_text(json.dumps(frozen), encoding='utf-8')
        return path, frozen

    def test_independent_runtime_and_source_names(self):
        cuda_version = json.loads((PLUGIN / 'umi-plugin.json').read_bytes())['version']
        for kind, label, version in (('cuda', 'CUDA', cuda_version), ('vl', 'PaddleVL', '3.2.0')):
            for value, suffix in (('cu126', ''), ('cu129', '_RTX50')):
                with self.subTest(kind=kind, value=value):
                    self.fixture(kind, value, version)
                    actual = tier.tier(self.root, kind, version)
                    self.assertEqual(actual, value)
                    self.assertEqual(tier.runtime_archive_name(kind, version, actual),
                                     f'Umi-OCR-Plugin_v{version}_Windows_x64_{label}{suffix}.tar.xz')
                    self.assertEqual(tier.source_archive_name(kind, version, actual),
                                     f'Umi-OCR-Plugin_{kind}_v{version}{suffix}_CorrespondingSource.tar.xz')

    def test_historical_names_are_not_reinterpreted(self):
        for kind, version in (('cuda', '3.0.7'), ('vl', '3.1.5')):
            self.fixture(kind, 'cu129')
            self.assertIsNone(tier.tier(self.root, kind, version))

    def test_cuda_wrong_requirements_or_changed_support_fail_closed(self):
        path, frozen = self.fixture('cuda', 'cu129')
        frozen['lock'] = 'build/requirements-gpu-plugin-windows-cu126.lock'
        (path / 'runtime.lock.json').write_text(json.dumps(frozen), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '运行锁不匹配'):
            tier.tier(self.root, 'cuda', '3.0.8')
        path, _ = self.fixture('cuda', 'cu129')
        (path / 'cuda-support.json').write_bytes((ROOT / 'build/cuda-support-cu126.lock.json').read_bytes())
        with self.assertRaisesRegex(ValueError, '运行锁不匹配'):
            tier.tier(self.root, 'cuda', '3.0.8')

    def test_vl_rejects_duplicate_support_entry(self):
        path, frozen = self.fixture('vl', 'cu126')
        frozen['files'] *= 2
        (path / 'runtime.lock.json').write_text(json.dumps(frozen), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '运行锁不匹配'):
            tier.tier(self.root, 'vl', '3.1.6')

    def test_config_displays_sealed_hardware_without_importing_worker(self):
        config = load_config()
        for value, display in (('cu126', '12.6'), ('cu129', '12.9')):
            path, _ = self.fixture('cuda', value)
            description = config.installed_hardware(path)['hardware']
            selection = 'cuda' + display.replace('.', '')
            self.assertEqual(description['optionsList'], [[selection, 'NVIDIA CUDA ' + display]])
            self.assertEqual(description['default'], selection)
        (path / 'cuda-support.json').write_bytes(b'{}')
        self.assertEqual(config.installed_hardware(path), {})
        self.assertNotIn('paddle', sys.modules)

    def test_reviewed_seed_locks_cannot_be_mixed(self):
        lock = ROOT / 'build/runtime-seed-windows-cu126.lock.json'
        requirements = ROOT / 'build/requirements-gpu-plugin-windows-cu126.lock'
        sources = ROOT / 'build/sources-windows-cu126.lock.json'
        for kind in tier.IDS:
            row, _, _ = seed.reviewed_row(lock, kind, requirements, sources)
            self.assertEqual(row['id'], tier.IDS[kind])
            with self.assertRaisesRegex(ValueError, '不匹配审定'):
                seed.reviewed_row(lock, kind, requirements, ROOT / 'build/sources-windows-cu129.lock.json')
            with self.assertRaisesRegex(ValueError, '不匹配审定'):
                seed.reviewed_row(lock, kind, ROOT / 'build/requirements-gpu-plugin-windows-cu129.lock', sources)

    def test_wrong_archive_never_writes_payload(self):
        file = self.root / 'Umi-OCR-Plugin_v3.0.8_Windows_x64_CUDA.tar.xz'
        file.write_bytes(b'xz is not proof of identity')
        target = self.root / 'new'
        with self.assertRaisesRegex(ValueError, '归档大小或 SHA-256'):
            seed.restore(file, target, 'cuda', {'archiveBytes': file.stat().st_size, 'archiveSha256': '0' * 64})
        self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
