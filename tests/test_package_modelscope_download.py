"""ModelScope下载派生的有限输入、来源身份、标准RECORD与投影保护。"""
import base64
import csv
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('tested_modelscope_download', ROOT / 'build/tools/package_modelscope_download.py')
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
WORK = ROOT / 'build/tmp/dependency-trim-20261114-r1/unit'


def record(payload, dist):
    payload = {n: d for n, d in payload.items() if n != dist + '/RECORD'}
    rows = io.StringIO(newline='')
    writer = csv.writer(rows, lineterminator='\n')
    for name, data in sorted(payload.items()):
        writer.writerow([name, 'sha256=' + base64.urlsafe_b64encode(bytes.fromhex(M.digest(data))).rstrip(b'=').decode(), len(data)])
    writer.writerow([dist + '/RECORD', '', ''])
    return {**payload, dist + '/RECORD': rows.getvalue().encode()}


class ModelScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=WORK)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.original = {name: b'# retained\n' for name in M.KEEP_HASHES}
        self.original['modelscope/hub/__init__.py'] = b"from .commit_scheduler import CommitScheduler\n__all__ = [\n    'CommitScheduler',\n]\n"
        self.original['modelscope/utils/logger.py'] = (
            b"def get_logger():\n    torch_dist = False\n    is_worker0 = True\n"
            b"    if iutil.find_spec('torch') is not None:\n        from modelscope.utils.torch_utils import is_dist, is_master\n        torch_dist = is_dist()\n        is_worker0 = is_master()\n"
            b"def add_file_handler():\n    if iutil.find_spec('torch') is not None:\n        from modelscope.utils.torch_utils import is_master\n        is_worker0 = is_master()\n    else:\n        is_worker0 = True\n")
        self.original['modelscope/version.py'] = b"__version__ = '1.38.1'\n"
        self.original[M.ORIGINAL_DIST + '/METADATA'] = b'Name: modelscope\nVersion: 1.38.1\nLicense: Apache-2.0\nRequires-Dist: modelscope-hub>=0.0.7\nRequires-Dist: scipy; extra == "framework"\n\n'
        self.original[M.ORIGINAL_DIST + '/LICENSE'] = b'original copyright and license\n'
        self.original['modelscope/models/unused.py'] = b'# not a product root\n'
        patched = patch.object(M, 'KEEP_HASHES', {n: M.digest(self.original[n]) for n in M.KEEP_HASHES})
        patched.start()
        self.addCleanup(patched.stop)
        self.payload = M.derive(self.original)
        self.wheel = self.root / M.FILENAME
        self.write_wheel(self.payload)

    def write_wheel(self, payload):
        with zipfile.ZipFile(self.wheel, 'w') as z:
            for name, data in payload.items():
                z.writestr(name, data)
        self.profile = {'version': M.VERSION, 'filename': M.FILENAME, 'sha256': M.L.sha256_file(self.wheel)}

    def test_derivation_keeps_download_bytes_and_licenses(self):
        self.assertEqual(self.payload['modelscope/hub/snapshot_download.py'], self.original['modelscope/hub/snapshot_download.py'])
        self.assertEqual(self.payload[M.DIST + '/LICENSE'], self.original[M.ORIGINAL_DIST + '/LICENSE'])
        self.assertNotIn('modelscope/models/unused.py', self.payload)
        self.assertNotIn(b'torch_utils', self.payload['modelscope/utils/logger.py'])
        self.assertIn(M.VERSION.encode(), self.payload['modelscope/version.py'])
        self.assertIn(b'modelscope-hub>=0.0.7', self.payload[M.DIST + '/METADATA'])
        self.assertNotIn(b'scipy', self.payload[M.DIST + '/METADATA'])

    def test_standard_record_and_derived_identity(self):
        self.assertEqual(M.read_derived(self.wheel, self.profile), self.payload)

    def test_source_hash_mismatch_is_rejected(self):
        self.original['modelscope/hub/snapshot_download.py'] += b'# changed\n'
        with self.assertRaisesRegex(ValueError, '原始源码'):
            M.derive(self.original)

    def test_bad_patch_shape_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '形状'):
            M.replace_once(b'aa', b'a', b'b')

    def test_missing_original_license_is_rejected(self):
        del self.original[M.ORIGINAL_DIST + '/LICENSE']
        with self.assertRaisesRegex(ValueError, '许可'):
            M.derive(self.original)

    def test_bad_independent_hash_is_rejected(self):
        self.profile['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, '摘要'):
            M.read_derived(self.wheel, self.profile)

    def test_record_mismatch_is_rejected(self):
        broken = dict(self.payload)
        broken['modelscope/hub/errors.py'] += b'# changed\n'
        self.write_wheel(broken)
        with self.assertRaisesRegex(ValueError, 'RECORD字节'):
            M.read_derived(self.wheel, self.profile)

    def test_path_traversal_is_rejected(self):
        self.write_wheel(record({**self.payload, '../outside.py': b'x'}, M.DIST))
        with self.assertRaises((ValueError, M.L.LayoutError)):
            M.read_derived(self.wheel, self.profile)

    def test_unexpected_package_and_case_alias_are_rejected(self):
        for extra in ('other/x.py', 'MODELSCOPE/__init__.py'):
            with self.subTest(extra=extra):
                self.write_wheel(record({**self.payload, extra: b'x'}, M.DIST))
                with self.assertRaises(ValueError):
                    M.read_derived(self.wheel, self.profile)

    def test_extra_model_module_even_with_valid_record_is_rejected(self):
        self.write_wheel(record({**self.payload, 'modelscope/models/extra.py': b'x'}, M.DIST))
        with self.assertRaisesRegex(ValueError, '闭包'):
            M.read_derived(self.wheel, self.profile)

    def test_projection_plan_does_not_write_or_modify_inputs(self):
        logical = set(self.original)
        inspected = {}
        read = lambda view, name, limit: self.original[name.removeprefix('vendor/')]
        before = dict(self.original)
        additions, omitted, receipt = M.project_replacement(None, logical, 'vendor', self.profile, self.wheel, inspected, read)
        self.assertEqual(additions, self.payload)
        self.assertEqual(omitted, logical)
        self.assertEqual(before, self.original)
        self.assertEqual(receipt['inputVersion'], M.UPSTREAM)
        self.assertEqual(set(inspected), logical)

    def test_derived_seed_requires_exact_payload(self):
        actual = dict(self.payload)
        read = lambda view, name, limit: actual[name.removeprefix('vendor/')]
        M.project_replacement(None, set(actual), 'vendor', self.profile, self.wheel, {}, read)
        actual['modelscope/hub/errors.py'] += b'x'
        with self.assertRaisesRegex(ValueError, '完整载荷'):
            M.project_replacement(None, set(actual), 'vendor', self.profile, self.wheel, {}, read)

    def test_other_distribution_shared_member_is_rejected(self):
        actual = {**self.original, 'other-1.dist-info/RECORD': b'modelscope/hub/errors.py,,\n'}
        read = lambda view, name, limit: actual[name.removeprefix('vendor/')]
        with self.assertRaisesRegex(ValueError, '共享归属'):
            M.project_replacement(None, set(actual), 'vendor', self.profile, self.wheel, {}, read)

    def test_torch_runtime_is_not_silently_accepted(self):
        with self.assertRaisesRegex(ValueError, 'PyTorch'):
            M.project_replacement(None, set(self.original) | {'torch/__init__.py'}, 'vendor', self.profile, self.wheel, {}, None)


if __name__ == '__main__':
    WORK.mkdir(parents=True, exist_ok=True)
    unittest.main()
