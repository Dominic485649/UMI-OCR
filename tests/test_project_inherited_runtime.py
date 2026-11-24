"""精确继承投影的成员、来源、原生代码、许可与运行中目录保护测试。"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('tested_inherited_runtime', ROOT / 'build/tools/project_inherited_runtime.py')
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
WORK = ROOT / 'build/tmp/gpu-compat-20261118-inheritance-unit'


class InheritedProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=WORK)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vendor = self.root / 'build/staging/fresh/UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/vendor'
        self.vendor.mkdir(parents=True)
        self.audit = self.root / 'build/audit'
        self.audit.mkdir()
        self.work = self.audit / 'exact'
        self.profile_path = self.root / 'inherit.lock.json'
        self.owner = self.audit / 'seed.json'
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'immutable-input').write_bytes(b'original readonly seed')
        self.file('package/__init__.py', b'original runtime')
        self.file('package/include/needed.h', b'needed runtime header, not removed by directory name')
        self.file('package/tests/runtime_helper.py', b'production helper, not removed by directory name')
        self.file('package/tests/retired.py', b'old baseline explicitly omitted this exact member')
        self.file('package/loader.pyd', b'exact locked native fixture')
        self.file('package-1.dist-info/METADATA', b'Name: package\nVersion: 1\n')
        self.file('package-1.dist-info/RECORD', b'original record remains unchanged')
        self.file('package-1.dist-info/LICENSE', b'original license')
        P.write_new(self.vendor.parent / 'umi-plugin.json', {'id': 'win32_PaddleOCRv6_CUDA', 'version': '3.0.7'})
        inputs = P.binding(P.L.tree_files(self.vendor))
        omitted = {'package/tests/retired.py': '精确排除，非目录规则'}
        self.profile = {'format': P.FORMAT, 'component': 'cuda', 'inputFiles': inputs,
                        'excludedFiles': omitted, 'retainedFiles': sorted(inputs.keys() - omitted.keys()),
                        'nativeCodeMustRemain': ['package/loader.pyd'], 'notice': '本轮应用子集，原始 RECORD 不是完整 wheel 声明。'}
        self.save_profile()
        P.write_new(self.owner, {'status': 'PROJECTED_NOT_COMPONENT_ACCEPTED', 'sourceModified': False,
                                'source': str(self.source), 'destination': str(self.vendor), 'outputFiles': inputs})

    def file(self, name, data):
        target = self.vendor / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def save_profile(self):
        self.profile_path.write_bytes(P.json_bytes(self.profile))

    def run_projection(self, **kwargs):
        return P.project(self.vendor, self.profile_path, self.owner, self.root, self.work, 'cuda',
                         occupancy_check=kwargs.get('occupancy_check', lambda _: []))

    def test_exact_members_only_originals_externalized_and_seed_unchanged(self):
        source_before = P.binding(P.L.tree_files(self.source))
        result = self.run_projection()
        self.assertEqual(result['status'], 'EXACT_PROJECTED_NOT_CONSUMER_ACCEPTED')
        self.assertEqual(result['movedFiles'], 1)
        self.assertEqual(P.binding(P.L.tree_files(self.source)), source_before)
        self.assertFalse((self.vendor / 'package/tests/retired.py').exists())
        self.assertTrue((self.work / 'omitted-original-inputs/package/tests/retired.py').is_file())
        self.assertTrue((self.vendor / 'package/tests/runtime_helper.py').is_file())
        self.assertTrue((self.vendor / 'package/include/needed.h').is_file())
        self.assertEqual((self.vendor / 'package-1.dist-info/RECORD').read_bytes(), b'original record remains unchanged')
        self.assertEqual((self.vendor / 'package-1.dist-info/LICENSE').read_bytes(), b'original license')
        self.assertTrue((self.vendor.parent / P.MARKER).is_file())

    def test_known_absent_exclusion_can_be_reused_without_restoring_it(self):
        (self.vendor / 'package/tests/retired.py').unlink()
        result = self.run_projection()
        self.assertEqual(result['movedFiles'], 0)
        self.assertEqual(result['alreadyAbsentExcludedFiles'], ['package/tests/retired.py'])

    def test_unknown_member_is_not_pruned_by_name(self):
        self.file('package/tests/unknown.py', b'must not silently remove')
        with self.assertRaisesRegex(ValueError, '未知输入'):
            self.run_projection()
        self.assertFalse(self.work.exists())
        self.assertTrue((self.vendor / 'package/tests/unknown.py').is_file())

    def test_changed_known_input_fails_before_mutation(self):
        self.file('package/tests/retired.py', b'changed input')
        with self.assertRaisesRegex(ValueError, '字节不符'):
            self.run_projection()
        self.assertFalse(self.work.exists())

    def test_missing_retained_runtime_fails(self):
        (self.vendor / 'package/include/needed.h').unlink()
        with self.assertRaisesRegex(ValueError, '缺失保留成员'):
            self.run_projection()

    def test_native_library_cannot_be_omitted_even_with_changed_profile(self):
        name = 'package/loader.pyd'
        self.profile['excludedFiles'][name] = 'not allowed'
        self.profile['retainedFiles'].remove(name)
        self.save_profile()
        with self.assertRaisesRegex(ValueError, '原生代码'):
            self.run_projection()
        self.assertFalse(self.work.exists())

    def test_copyright_metadata_and_record_cannot_be_externalized(self):
        for leaf in ('LICENSE', 'METADATA', 'RECORD'):
            with self.subTest(leaf=leaf):
                original = json.loads(json.dumps(self.profile))
                name = 'package-1.dist-info/' + leaf
                self.profile['excludedFiles'][name] = 'not allowed'
                self.profile['retainedFiles'].remove(name)
                self.save_profile()
                with self.assertRaisesRegex(ValueError, '版权、许可或原始发行版记录'):
                    self.run_projection()
                self.profile = original
        self.assertFalse(self.work.exists())

    def test_owned_projection_receipt_required(self):
        value = json.loads(self.owner.read_text('utf-8'))
        value['destination'] = str(self.source)
        self.owner.write_bytes(P.json_bytes(value))
        with self.assertRaisesRegex(ValueError, '所有权回执'):
            self.run_projection()
        self.assertFalse(self.work.exists())

    def test_running_candidate_stops_without_termination(self):
        with self.assertRaisesRegex(ValueError, '正在运行'):
            self.run_projection(occupancy_check=lambda _: [{'pid': 1234}])
        self.assertFalse(self.work.exists())

    def test_existing_lock_or_marker_blocks_repeat_mutation(self):
        for name in ('runtime.lock.json', P.MARKER, 'runtime-archives.json'):
            with self.subTest(name=name):
                target = self.vendor.parent / name
                target.write_bytes(b'locked')
                with self.assertRaisesRegex(ValueError, '不得再次修改'):
                    self.run_projection()
                target.unlink()
        self.assertFalse(self.work.exists())

    def test_real_windows_read_lease_blocks_move_and_preserves_original(self):
        name = 'package/tests/retired.py'
        with P.F._File(self.vendor / name):
            with self.assertRaises(OSError):
                self.run_projection()
        self.assertTrue((self.vendor / name).is_file())
        self.assertFalse((self.vendor.parent / P.MARKER).exists())
        self.assertFalse((self.work / 'result.json').exists())

    def test_unsafe_case_alias_and_parent_traversal_are_rejected(self):
        for name in ('../outside.py', 'Package/__init__.py'):
            with self.subTest(name=name):
                original = json.loads(json.dumps(self.profile))
                self.profile['inputFiles'][name] = {'sha256': '0' * 64, 'bytes': 0}
                self.profile['retainedFiles'].append(name)
                self.save_profile()
                with self.assertRaises((ValueError, P.L.LayoutError)):
                    self.run_projection()
                self.profile = original

    def test_copy_filter_verifies_bytes_and_keeps_unknown_or_patched_members(self):
        with P.L.load_layout(self.vendor.parent) as view:
            logical = {name[7:]: name for name in view.files('vendor')}
            sizes = {name: (self.vendor / name).stat().st_size for name in logical}
            inspected = {}
            omitted, report = P.copy_time_omissions(view, logical, 'vendor', self.profile_path, inspected, sizes)
            self.assertEqual(omitted, {'package/tests/retired.py'})
            self.assertEqual(report['deferredToFinalProjection'], [])
            self.file('package/tests/retired.py', b'changed by an earlier patch')
            sizes['package/tests/retired.py'] = (self.vendor / 'package/tests/retired.py').stat().st_size
            omitted, report = P.copy_time_omissions(view, logical, 'vendor', self.profile_path, {}, sizes)
            self.assertEqual(omitted, set())
            self.assertEqual(report['deferredToFinalProjection'], ['package/tests/retired.py'])

    def test_bounded_profile_json_read_does_not_reload_file(self):
        with patch.object(P.L, 'read_json', side_effect=AssertionError('不得再次无界读取')):
            value, _ = P.read_bounded(self.profile_path, self.profile_path.stat().st_size)
            self.assertEqual(value['format'], P.FORMAT)
        with self.assertRaisesRegex(ValueError, '预算'):
            P.read_bounded(self.profile_path, 10)

    def test_new_development_exception_cannot_hide_arbitrary_executable(self):
        self.profile['developmentLaunchers'] = {'bin/unknown.exe': {'entry': 'unknown', 'mainSha256': '0' * 64}}
        self.save_profile()
        with self.assertRaisesRegex(ValueError, '开发入口的例外'):
            self.run_projection()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--work', type=Path, default=WORK)
    args, remaining = parser.parse_known_args()
    WORK = args.work
    WORK.mkdir(parents=True, exist_ok=True)
    unittest.main(argv=[sys.argv[0], *remaining])
