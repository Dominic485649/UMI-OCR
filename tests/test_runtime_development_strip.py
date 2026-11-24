"""开发文件裁剪、外置来源与原生锁的定向回归，不加载模型或 UI。"""
from __future__ import annotations

import csv
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'build/tools'))
import shared_runtime_projection as projection

D, F, L = projection.D, projection.F, projection.L
APY = 'paddle/apy/matmul_pass/matmul/tile.cuh'
AP_RECORD = 'paddlepaddle_gpu-3.3.1.dist-info/RECORD'
AP_LICENSE = 'paddle/apy/matmul_pass/matmul/LICENSE.h'
AP_RUNTIME = 'paddle/incubate/cc/compiler.py'


def csv_record(files):
    text = io.StringIO(newline='')
    csv.writer(text, lineterminator='\n').writerows(
        (name, D.wheel_hash(raw), len(raw)) for name, raw in files.items())
    return text.getvalue().encode('utf-8')


class RuntimeDevelopmentStripTests(unittest.TestCase):
    def setUp(self):
        parent = L.plain_path(ROOT / 'build/tmp')
        parent.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=parent, prefix='dev-strip-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.vendor = self.root / 'vendor'
        self.files = {APY: b'// APY compilation input\n', AP_LICENSE: b'license', AP_RUNTIME: b'# keep\n',
                      'paddle/apy/matmul_pass/matmul/unlisted.h': b'not locked; keep'}
        for name, raw in self.files.items():
            self.put(name, raw)
        self.metadata = b'Metadata-Version: 2.1\nName: paddlepaddle-gpu\nVersion: 3.3.1\n\n'
        self.put(AP_RECORD.replace('RECORD', 'METADATA'), self.metadata)
        self.original = csv_record(self.files)
        self.put(AP_RECORD, self.original)
        self.rule = {'targets': ['cu126', 'cu129'], 'dist': AP_RECORD.split('/')[0], 'name': 'paddlepaddle-gpu',
                     'version': '3.3.1', 'kind': 'paddle-ap-kernel-compiler', 'reason': '实验编译用模板',
                     'files': {APY: D.row(self.files[APY])}}

    def put(self, name, raw):
        path = self.vendor / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path

    def strip(self, *, target='cu126', rules=None):
        with L.load_layout(self.root) as view:
            return D.project(view, 'vendor', target, {'format': 'umi-runtime-development-strip-v1',
                                                     'rules': [self.rule] if rules is None else rules}, L.canonical_relative)

    def test_exact_cut_leaves_unlocked_templates_and_original_tree_intact(self):
        for target in ('cu126', 'cu129'):
            with self.subTest(target=target):
                removed, evidence, adjusted = self.strip(target=target)
                self.assertEqual(list(removed), ['vendor/' + APY])
                self.assertEqual(removed['vendor/' + APY]['owner'], AP_RECORD)
                self.assertEqual(evidence['development-files/vendor/' + APY], self.files[APY])
                self.assertEqual(evidence['development-originals/' + AP_RECORD], self.original)
                self.assertEqual(evidence['development-originals/' + AP_RECORD.replace('RECORD', 'METADATA')], self.metadata)
                retained = {name: value for name, value in self.files.items() if name != APY}
                self.assertEqual(adjusted, {'vendor/' + AP_RECORD: csv_record(retained)})
                self.assertEqual((self.vendor / APY).read_bytes(), self.files[APY])
                self.assertEqual((self.vendor / AP_RECORD).read_bytes(), self.original)
        self.assertEqual(self.strip(target='vl-cu126'), ({}, {}, {}))

    def test_rejects_missing_or_changed_development_member(self):
        self.put(APY, self.files[APY].replace(b'input', b'other'))
        with self.assertRaisesRegex(ValueError, '字节或原 wheel RECORD'):
            self.strip()
        (self.vendor / APY).unlink()
        with self.assertRaisesRegex(ValueError, '缺失'):
            self.strip()

    def test_rejects_metadata_and_record_mismatch(self):
        name = AP_RECORD.replace('RECORD', 'METADATA')
        self.put(name, self.metadata.replace(b'3.3.1', b'3.3.2'))
        with self.assertRaisesRegex(ValueError, '版本或名称不符'):
            self.strip()
        self.put(name, self.metadata)
        self.put(AP_RECORD, csv_record({APY: b'different upstream bytes'}))
        with self.assertRaisesRegex(ValueError, '字节或原 wheel RECORD'):
            self.strip()

    def test_rejects_duplicate_or_shared_record_ownership(self):
        with self.assertRaisesRegex(ValueError, '重复绑定'):
            self.strip(rules=[self.rule, self.rule])
        self.put('other-1.0.dist-info/RECORD', csv_record({APY.upper(): self.files[APY]}))
        with self.assertRaisesRegex(ValueError, '其它发行版拥有'):
            self.strip()

    def test_rejects_licence_and_runtime_even_if_exactly_locked(self):
        for name in (AP_LICENSE, AP_RUNTIME):
            with self.subTest(name=name):
                self.rule['files'] = {name: D.row(self.files[name])}
                with self.assertRaisesRegex(ValueError, '开发成员类型'):
                    self.strip()

    def test_linker_input_requires_library_header(self):
        library = 'scipy/stats/mean.dll.a'
        record = 'scipy-1.0.dist-info/RECORD'
        raw = b'MZ not a linker input'
        self.put(library, raw)
        self.put(record, csv_record({library: raw}))
        self.put(record.replace('RECORD', 'METADATA'), b'Name: scipy\nVersion: 1.0\n\n')
        rule = {'targets': ['vl-cu129'], 'dist': record.split('/')[0], 'name': 'scipy', 'version': '1.0',
                'kind': 'scipy-linker-import-library', 'reason': '只供链接', 'files': {library: D.row(raw)}}
        with self.assertRaisesRegex(ValueError, 'COFF 归档'):
            self.strip(target='vl-cu129', rules=[rule])

    def test_stored_zip_preserves_remaining_original_record_binding(self):
        view = SimpleNamespace(manifest={'archives': [{'path': 'vendor.zip', 'members': [
            {'logical_path': 'vendor/retained.py', 'source': {'record_path': 'vendor/' + AP_RECORD}},
        ]}]})
        self.assertEqual(projection.projected_containers(view, {'vendor/' + APY}), ({}, {}, set()))
        with self.assertRaisesRegex(ValueError, 'Stored ZIP 绑定的原始 RECORD'):
            projection.projected_containers(view, {'vendor/' + APY}, {'vendor/' + AP_RECORD})

    def test_full_file_lock_only_accepts_the_bound_record_change(self):
        removed, _, changed = self.strip()
        record = 'vendor/' + AP_RECORD
        projected = {record: changed[record]}
        old = {'files': [{'path': record, 'sha256': D.digest(self.original)},
                         {'path': 'vendor/' + APY, 'sha256': D.digest(self.files[APY])}]}
        for name in sorted(F.CORE_PROVIDERS):
            path = self.put(name.removeprefix('vendor/'), b'native-placeholder-not-loaded')
            projected[name] = path
            old['files'].append({'path': name, 'sha256': F.digest(path)})
        checks = {record: (self.original, changed[record])}
        result = F.project_lock(old, {}, set(), removed, projected, {}, record_changes=checks)
        self.assertEqual(result['files'][0], {'path': record, 'sha256': D.digest(changed[record])})
        self.assertEqual(result['nativeBinaryCount'], 2)
        with self.assertRaisesRegex(ValueError, '投影私有文件与原锁不一致'):
            F.project_lock(old, {}, set(), removed, projected, {})
        with self.assertRaisesRegex(ValueError, '原始 RECORD 字节'):
            F.project_lock(old, {}, set(), removed, projected, {}, record_changes={record: (b'other', changed[record])})
        with self.assertRaisesRegex(ValueError, '原始与派生字节'):
            F.project_lock(old, {}, set(), removed, projected, {}, record_changes={record: (self.original, b'not projected')})

    def test_real_lock_does_not_touch_the_existing_common_group(self):
        profile = L.read_json(projection.DEVELOPMENT_LOCK)
        self.assertTrue(profile['rules'])
        self.assertTrue(all(projection.S.common_owner(name.split('/')[0]) is None
                            for rule in profile['rules'] for name in rule['files']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
