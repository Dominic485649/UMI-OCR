"""依赖投影的来源保护、派生身份、RECORD和Stored-ZIP恢复定向测试。"""
import argparse
import base64
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

P = load('tested_dependency_projection', ROOT / 'build/tools/project_dependency_runtime.py')
M = load('fixture_runtime_archive_merge', ROOT / 'build/tools/merge_runtime.py')
N = load('tested_derived_component_notice', ROOT / 'build/tools/generate_third_party_components.py')
V = load('tested_derived_opencv_evidence', ROOT / 'build/tools/verify_release_evidence.py')
S = load('tested_dependency_source_boundary', ROOT / 'build/tools/source_snapshot.py')
WORK = ROOT / 'build/tmp/dependency-trim-20261114-r1/unit'


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=WORK)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.audit = self.root / 'build/audit'
        self.audit.mkdir(parents=True)
        self.source = self.root / 'build/input'
        self.site = self.source / 'site-packages'
        self.site.mkdir(parents=True)
        self.output = self.root / 'build/output'
        self.receipt = self.audit / 'projection.json'
        self.profile = json.loads((ROOT / 'build/runtime-subsets-windows.json').read_text('utf-8'))
        self.profile_path = self.root / 'profile.json'
        self.wheel = self.root / self.profile['opencv']['filename']
        self.file('cv2/old.pyd', b'old binary')
        self.file('opencv_contrib_python-4.10.0.84.dist-info/METADATA', b'Name: opencv-contrib-python\nVersion: 4.10.0.84\n')
        self.file('imagecodecs-2026.8.16.dist-info/METADATA', b'Name: imagecodecs\nVersion: 2026.8.16\n\nOriginal copyright/body\n:Version: 2026.8.16\n')
        self.file('imagecodecs-2026.8.16.dist-info/LICENSE', b'Original license')
        self.file('imagecodecs-2026.8.16.dist-info/RECORD', b'original-record')
        self.file('imagecodecs/__init__.py', b'# original lazy loader\n')
        for name in ('_jpegxl', '_jpegxr', '_shared', '_shared_cython', '_unused'):
            self.file('imagecodecs/' + name + '.pyd', name.encode('ascii'))
        self.file('bottle.py', b'# bottle\n')
        self.file('six.py', b'# six\n')
        self.make_wheel()
        self.profile_path.write_text(json.dumps(self.profile), encoding='utf-8')
        self.root_patch = patch.object(P, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def file(self, name, data):
        path = self.site / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def make_wheel(self, bad_record=False, extra=None):
        cv = self.profile['opencv']
        dist = 'opencv_contrib_python-' + cv['version'] + '.dist-info'
        cv['nativeSha256'] = hashlib.sha256(b'new binary').hexdigest()
        payload = {'cv2/python-3.13/cv2.cp313-win_amd64.pyd': b'new binary', dist + '/METADATA': ('Name: opencv-contrib-python\nVersion: ' + cv['version'] + '\n').encode(),
                   dist + '/licenses/OpenCV-LICENSE': b'Original OpenCV license',
                   dist + '/licenses/libwebp-COPYING': b'Original WebP copyright',
                   dist + '/UMI_RUNTIME_PROFILE.json': json.dumps({'sourceCommit': cv['sourceCommit'], 'modules': cv['modules'],
                       'version': cv['version'], 'nativeSha256': cv['nativeSha256'],
                       'sourceUrl': 'https://github.com/opencv/opencv/tree/' + cv['sourceCommit']}).encode()}
        if extra:
            payload[extra] = b'bad'
        rows = io.StringIO(newline='')
        writer = csv.writer(rows, lineterminator='\n')
        for name, data in sorted(payload.items()):
            checksum = 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
            writer.writerow([name, checksum, str(len(data) + int(bad_record))])
        writer.writerow([dist + '/RECORD', '', ''])
        payload[dist + '/RECORD'] = rows.getvalue().encode()
        with zipfile.ZipFile(self.wheel, 'w') as wheel:
            for name, data in payload.items():
                wheel.writestr(name, data)
        cv['sha256'] = P.L.sha256_file(self.wheel)

    def run_projection(self):
        return P.project(self.source, self.output, self.profile_path, self.wheel, self.receipt, 'host')

    def test_derives_only_named_packages_and_preserves_source_and_licenses(self):
        before = {name: P.L.sha256_file(path) for name, path in P.L.tree_files(self.source).items()}
        result = self.run_projection()
        self.assertFalse((self.output / 'cv2/old.pyd').exists())
        self.assertEqual((self.output / 'cv2/python-3.13/cv2.cp313-win_amd64.pyd').read_bytes(), b'new binary')
        self.assertFalse((self.output / 'imagecodecs/_unused.pyd').exists())
        dist = self.output / 'imagecodecs-2026.8.16+umi.jxlxr.1.dist-info'
        self.assertEqual((dist / 'LICENSE').read_bytes(), b'Original license')
        self.assertIn(b'Version: 2026.8.16+umi.jxlxr.1', (dist / 'METADATA').read_bytes())
        self.assertEqual(before, {name: P.L.sha256_file(path) for name, path in P.L.tree_files(self.source).items()})
        self.assertEqual(result['status'], 'PROJECTED_NOT_COMPONENT_ACCEPTED')
        for name, checksum, size in csv.reader(io.StringIO((dist / 'RECORD').read_text('utf-8'))):
            if name.endswith('/RECORD'):
                self.assertFalse(checksum or size)
            else:
                data = (self.output / name).read_bytes()
                self.assertEqual(int(size), len(data))
                self.assertEqual(checksum, 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode())

    def test_bounded_loose_read_preserves_limits_and_external_hashes(self):
        with P.L.load_layout(self.source) as view:
            with patch.object(view, 'read_bytes', side_effect=AssertionError('不得整文件读取')):
                self.assertEqual(P.bounded_read(view, 'site-packages/six.py', 6), b'# six\n')
                with self.assertRaisesRegex(ValueError, '超出有限预算'):
                    P.bounded_read(view, 'site-packages/six.py', 5)
                for limit in (-1, True, 1.5):
                    with self.assertRaisesRegex(ValueError, '非负整数'):
                        P.bounded_read(view, 'site-packages/six.py', limit)
                view.source_hashes = {'site-packages/six.py': '0' * 64}
                with self.assertRaisesRegex(P.L.LayoutError, 'external source hashes'):
                    P.bounded_read(view, 'site-packages/six.py', 6)

    def test_bounded_loose_read_never_requests_more_than_budget_plus_one(self):
        class ObservedStream(io.BytesIO):
            def read(stream, size=-1):
                self.assertEqual(size, 5)
                return super().read(size)
        with P.L.load_layout(self.source) as view:
            with patch.object(Path, 'open', return_value=ObservedStream(b'123456789')):
                with self.assertRaisesRegex(ValueError, '超出有限预算'):
                    P.bounded_read(view, 'site-packages/six.py', 4)

    def test_bounded_zip_read_rejects_size_before_reading(self):
        policy = {'schema_version': 1, 'kind': 'host', 'archives': [
            {'path': 'dependencies.zip', 'source_prefix': 'site-packages',
             'packages': [], 'modules': ['bottle.py', 'six.py']}]}
        M.aggregate_runtime(self.source, kind='host', policy=policy, project_root=self.root, occupancy_check=lambda _: [])
        with P.L.load_layout(self.source) as view:
            with patch.object(view, 'read_bytes', wraps=view.read_bytes) as reader:
                with self.assertRaisesRegex(ValueError, '超出有限预算'):
                    P.bounded_read(view, 'site-packages/six.py', 5)
                reader.assert_not_called()
                self.assertEqual(P.bounded_read(view, 'site-packages/six.py', 6), b'# six\n')
                reader.assert_called_once_with('site-packages/six.py')

    def test_imagecodecs_auxiliary_metadata_is_bounded_before_output(self):
        self.file('imagecodecs-2026.8.16.dist-info/LICENSE', b'x' * (3 * 1024**2 + 1))
        with self.assertRaisesRegex(ValueError, '超出有限预算'):
            self.run_projection()
        self.assertFalse(self.output.exists())

    def test_cuda_record_growth_after_size_snapshot_is_bounded(self):
        self.prepare_cuda()
        original = P.bounded_read
        mutated = False
        def grow_record(view, name, limit):
            nonlocal mutated
            if name == 'vendor/psutil-7.2.2.dist-info/RECORD':
                mutated = True
                self.file('psutil-7.2.2.dist-info/RECORD', b'x' * (limit + 1))
            return original(view, name, limit)
        with patch.object(P, 'bounded_read', side_effect=grow_record):
            with self.assertRaisesRegex(ValueError, '超出有限预算'):
                self.run_cuda_projection()
        self.assertTrue(mutated)
        self.assertFalse(self.output.exists())

    def make_development_script(self, component, name, *, suffix=''):
        rule = self.profile['developmentScripts'][component][name]
        code = (rule['entry'] + '\n').encode('utf-8')
        rule['mainSha256'] = P.digest(code)
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w') as archive:
            archive.writestr('__main__.py', code + suffix.encode('utf-8'))
        self.file(name, raw.getvalue())
        self.profile_path.write_text(json.dumps(self.profile), encoding='utf-8')

    def test_host_development_scripts_do_not_remove_library_or_unknown_commands(self):
        self.make_development_script('host', 'bin/pyftsubset.exe')
        self.file('fontTools/subset/__init__.py', b'# runtime API stays\n')
        self.file('bin/not-reviewed.exe', b'keep unknown input')
        result = self.run_projection()
        self.assertFalse((self.output / 'bin/pyftsubset.exe').exists())
        self.assertEqual((self.output / 'fontTools/subset/__init__.py').read_bytes(), b'# runtime API stays\n')
        self.assertEqual((self.output / 'bin/not-reviewed.exe').read_bytes(), b'keep unknown input')
        self.assertEqual([x['path'] for x in result['excludedDevelopmentScripts']], ['bin/pyftsubset.exe'])
        self.assertTrue((self.site / 'bin/pyftsubset.exe').exists())

    def test_cuda_development_script_exclusion_is_component_specific(self):
        self.prepare_cuda()
        self.make_development_script('cuda', 'bin/fleetrun.exe')
        self.file('bin/pyftsubset.exe', b'not a CUDA rule')
        self.file('paddle/distributed/__init__.py', b'# lazy API stays\n')
        result = self.run_cuda_projection()
        self.assertFalse((self.output / 'bin/fleetrun.exe').exists())
        self.assertTrue((self.output / 'bin/pyftsubset.exe').exists())
        self.assertTrue((self.output / 'paddle/distributed/__init__.py').exists())
        self.assertEqual([x['path'] for x in result['excludedDevelopmentScripts']], ['bin/fleetrun.exe'])

    def test_development_script_requires_full_entry_digest_not_only_import(self):
        self.make_development_script('host', 'bin/pyftsubset.exe', suffix='# changed entry\n')
        with self.assertRaisesRegex(ValueError, '完整入口与审查摘要不符'):
            self.run_projection()
        self.assertFalse(self.output.exists())

    def test_development_script_rule_cannot_target_library_file(self):
        self.profile['developmentScripts']['host']['fontTools/library.exe'] = {'entry': 'unused', 'mainSha256': '0'*64}
        self.profile_path.write_text(json.dumps(self.profile), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '越过bin启动器边界'):
            self.run_projection()
        self.assertFalse(self.output.exists())

    def prepare_reuse(self, archived=False):
        first = self.run_projection()
        golden = {name: value for name, value in first['outputFiles'].items()
                  if name.startswith(('imagecodecs/', 'imagecodecs-'))}
        # 合成夹具有自己的独立预期摘要，不冒充生产imagecodecs锁。
        self.profile['imagecodecs']['derivedPayloadSha256'] = P.digest(P.json_bytes(golden))
        self.profile_path.write_text(json.dumps(self.profile), encoding='utf-8')
        previous = self.output
        self.source = self.root / 'build/reuse-input'
        self.site = self.source / 'site-packages'
        shutil.copytree(previous, self.site)
        self.output = self.root / 'build/reused-output'
        self.receipt = self.audit / 'reuse.json'
        if archived:
            policy = {'schema_version': 1, 'kind': 'host', 'archives': [
                {'path': 'dependencies.zip', 'source_prefix': 'site-packages',
                 'packages': [], 'modules': ['bottle.py', 'six.py']}]}
            M.aggregate_runtime(self.source, kind='host', policy=policy, project_root=self.root, occupancy_check=lambda _: [])
        return first

    def test_known_derived_loose_seed_is_idempotent(self):
        first = self.prepare_reuse()
        reused = self.run_projection()
        self.assertEqual(reused['outputFiles'], first['outputFiles'])
        self.assertEqual(reused['inputVersions']['opencv-contrib-python'], self.profile['opencv']['version'])
        self.assertEqual(reused['inputVersions']['imagecodecs'], self.profile['imagecodecs']['version'])

    def test_known_derived_stored_seed_is_idempotent(self):
        first = self.prepare_reuse(archived=True)
        reused = self.run_projection()
        self.assertEqual(reused['sourceLayout']['mode'], 'archived')
        self.assertEqual(reused['outputFiles'], first['outputFiles'])

    def test_derived_opencv_requires_exact_locked_wheel_payload(self):
        self.prepare_reuse()
        self.file('cv2/python-3.13/cv2.cp313-win_amd64.pyd', b'changed binary')
        with self.assertRaisesRegex(ValueError, '独立锁wheel的完整载荷'):
            self.run_projection()
        self.assertFalse(self.output.exists())

    def test_derived_imagecodecs_record_cannot_replace_independent_payload_lock(self):
        self.prepare_reuse()
        self.file('imagecodecs/_jpegxl.pyd', b'changed codec')
        dist = 'imagecodecs-' + self.profile['imagecodecs']['version'] + '.dist-info'
        record = self.site / dist / 'RECORD'
        rows = list(csv.reader(io.StringIO(record.read_text('utf-8'))))
        for row in rows:
            if row[0] == 'imagecodecs/_jpegxl.pyd':
                row[1:] = ['sha256=' + base64.urlsafe_b64encode(hashlib.sha256(b'changed codec').digest()).rstrip(b'=').decode(), str(len(b'changed codec'))]
        stream = io.StringIO(newline='')
        csv.writer(stream, lineterminator='\n').writerows(rows)
        record.write_text(stream.getvalue(), encoding='utf-8', newline='')
        with self.assertRaisesRegex(ValueError, '独立子集载荷摘要'):
            self.run_projection()
        self.assertFalse(self.output.exists())

    def test_unknown_derived_version_and_extra_seed_file_fail_closed(self):
        self.prepare_reuse()
        dist = 'opencv_contrib_python-' + self.profile['opencv']['version'] + '.dist-info'
        metadata = self.site / dist / 'METADATA'
        original = metadata.read_bytes()
        metadata.write_bytes(original.replace(self.profile['opencv']['version'].encode(), b'4.10.0.84+unknown'))
        with self.assertRaisesRegex(ValueError, '版本不符'):
            self.run_projection()
        metadata.write_bytes(original)
        self.file('cv2/unreviewed.py', b'# unreviewed\n')
        with self.assertRaisesRegex(ValueError, '完整载荷不符'):
            self.run_projection()
        self.assertFalse(self.output.exists())

    def test_restores_bottle_and_six_from_verified_stored_zip(self):
        policy = {'schema_version': 1, 'kind': 'host', 'archives': [
            {'path': 'dependencies.zip', 'source_prefix': 'site-packages', 'packages': [], 'modules': ['bottle.py', 'six.py']}]}
        M.aggregate_runtime(self.source, kind='host', policy=policy, project_root=self.root, occupancy_check=lambda _: [])
        self.assertFalse((self.site / 'bottle.py').exists())
        result = self.run_projection()
        self.assertEqual((self.output / 'bottle.py').read_bytes(), b'# bottle\n')
        self.assertEqual((self.output / 'six.py').read_bytes(), b'# six\n')
        self.assertEqual(result['sourceLayout']['mode'], 'archived')

    def test_externalized_inventory_requires_exact_original_digest(self):
        policy = {'schema_version': 1, 'kind': 'host', 'archives': [
            {'path': 'dependencies.zip', 'source_prefix': 'site-packages', 'packages': [], 'modules': ['bottle.py', 'six.py']}]}
        M.aggregate_runtime(self.source, kind='host', policy=policy, project_root=self.root, occupancy_check=lambda _: [])
        inventory = self.source / 'runtime-archive-inputs.json'
        original_digest = P.L.sha256_file(inventory)
        inventory.unlink()
        with self.assertRaisesRegex(P.L.LayoutError, 'Missing original input'):
            P.L.load_layout(self.source)
        with P.L.load_layout(self.source, recover_externalized_inputs=True) as view:
            self.assertEqual(view.recovered_input_inventory['sha256'], original_digest)
            self.assertEqual(view.read_bytes('site-packages/bottle.py'), b'# bottle\n')
        self.assertFalse(inventory.exists())
        manifest = self.source / 'runtime-archives.json'
        data = json.loads(manifest.read_text('utf-8'))
        data['inputs_manifest']['sha256'] = '0' * 64
        manifest.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(P.L.LayoutError, 'exact digest recovery failed'):
            P.L.load_layout(self.source, recover_externalized_inputs=True)

    def test_present_but_corrupt_inventory_is_never_recovered_over(self):
        policy = {'schema_version': 1, 'kind': 'host', 'archives': [
            {'path': 'dependencies.zip', 'source_prefix': 'site-packages', 'packages': [], 'modules': ['bottle.py', 'six.py']}]}
        M.aggregate_runtime(self.source, kind='host', policy=policy, project_root=self.root, occupancy_check=lambda _: [])
        (self.source / 'runtime-archive-inputs.json').write_bytes(b'changed')
        with self.assertRaisesRegex(P.L.LayoutError, 'Changed original input'):
            P.L.load_layout(self.source, recover_externalized_inputs=True)

    def test_independent_artifact_hash_is_required_before_output_creation(self):
        with self.wheel.open('ab') as stream:
            stream.write(b'changed')
        with self.assertRaisesRegex(ValueError, '独立锁摘要'):
            self.run_projection()
        self.assertFalse(self.output.exists())

    def test_standard_record_and_namespace_are_checked(self):
        self.make_wheel(bad_record=True)
        self.profile_path.write_text(json.dumps(self.profile), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'RECORD字节'):
            self.run_projection()
        self.assertFalse(self.output.exists())
        self.make_wheel(extra='other/package.py')
        self.profile_path.write_text(json.dumps(self.profile), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '包边界'):
            self.run_projection()

    def test_missing_required_codec_and_ambiguous_abi_fail_closed(self):
        (self.site / 'imagecodecs/_jpegxl.pyd').unlink()
        with self.assertRaisesRegex(ValueError, '扩展缺失'):
            self.run_projection()
        self.assertFalse(self.output.exists())
        self.file('imagecodecs/_jpegxl.pyd', b'x')
        self.file('imagecodecs/_jpegxl.cp313.pyd', b'x')
        with self.assertRaisesRegex(ValueError, 'ABI不唯一'):
            self.run_projection()

    def test_existing_or_nested_output_is_not_overwritten(self):
        self.output.mkdir()
        marker = self.output / 'user.txt'
        marker.write_bytes(b'preserve')
        with self.assertRaises(FileExistsError):
            self.run_projection()
        self.assertEqual(marker.read_bytes(), b'preserve')
        with self.assertRaisesRegex(ValueError, '嵌套'):
            P.project(self.source, self.source / 'nested', self.profile_path, self.wheel, self.receipt, 'host')

    def test_version_and_path_injection_are_rejected_before_writes(self):
        self.profile['imagecodecs']['version'] = '../../escape'
        self.profile_path.write_text(json.dumps(self.profile), encoding='utf-8')
        with self.assertRaises((ValueError, P.L.LayoutError)):
            self.run_projection()
        self.assertFalse(self.output.exists())

    def test_notice_reports_derived_identity_instead_of_upstream_pin(self):
        self.run_projection()
        lock = self.root / 'requirements.lock'
        lock.write_text('opencv-contrib-python==4.10.0.84\nimagecodecs==2026.8.16\n', encoding='utf-8')
        text = N.section('组件', lock, self.output)
        self.assertIn('4.10.0.84+umi.coreimg.1（派生；原始输入锁：4.10.0.84）', text)
        self.assertIn('2026.8.16+umi.jxlxr.1（派生；原始输入锁：2026.8.16）', text)
        self.assertIn('https://github.com/opencv/opencv/tree/', text)
        profile = self.output / ('opencv_contrib_python-' + self.profile['opencv']['version'] + '.dist-info/UMI_RUNTIME_PROFILE.json')
        profile.unlink()
        with self.assertRaisesRegex(RuntimeError, 'without an explicit derived profile'):
            N.section('组件', lock, self.output)

    def test_derived_evidence_rejects_changed_native_and_false_source_identity(self):
        self.run_projection()
        original_load = V.load_json
        def load_evidence(path):
            if path == ROOT / 'build/runtime-subsets-windows.json':
                return self.profile
            return original_load(path)
        with patch.object(V, 'load_json', side_effect=load_evidence):
            evidence = V.verify_opencv(self.root, self.output)
            self.assertEqual(evidence['status'], 'PASS', evidence['blockers'])
            binary = self.output / 'cv2/python-3.13/cv2.cp313-win_amd64.pyd'
            binary.write_bytes(b'changed binary')
            blocked = V.verify_opencv(self.root, self.output)
            self.assertEqual(blocked['status'], 'BLOCK')
            binary.write_bytes(b'new binary')
            profile_path = self.output / ('opencv_contrib_python-' + self.profile['opencv']['version'] + '.dist-info/UMI_RUNTIME_PROFILE.json')
            data = json.loads(profile_path.read_text('utf-8'))
            data['sourceCommit'] = '0' * 40
            profile_path.write_text(json.dumps(data), encoding='utf-8')
            self.assertEqual(V.verify_opencv(self.root, self.output)['status'], 'BLOCK')

    def test_public_source_includes_only_reviewed_patches_and_subset_lock(self):
        self.assertFalse(S.is_excluded(Path('build/runtime-subsets-windows.json'), public=True))
        for name in S.PUBLIC_BUILD_PATCHES:
            self.assertFalse(S.is_excluded(Path('build/patches') / name, public=True))
        for name in ('build/private/ui-unlock-v1/secret.cpp', 'build/audit/private.json',
                     'build/patches/unreviewed.patch', 'build/tmp/input.py'):
            self.assertTrue(S.is_excluded(Path(name), public=True))

    def test_metadata_changed_after_derivation_cannot_be_bound_to_old_output(self):
        metadata_path = self.site / 'imagecodecs-2026.8.16.dist-info/METADATA'
        original_sha = P.L.sha256_file
        mutated = False
        def changed_sha(path):
            nonlocal mutated
            if Path(path) == metadata_path and not mutated:
                mutated = True
                metadata_path.write_bytes(metadata_path.read_bytes() + b'changed after derivation\n')
            return original_sha(path)
        with patch.object(P.L, 'sha256_file', side_effect=changed_sha):
            with self.assertRaisesRegex(ValueError, '输入在复制期间改变'):
                self.run_projection()
        self.assertTrue(mutated)
        self.assertFalse(self.receipt.exists())

    def prepare_cuda(self):
        vendor = self.source / 'vendor'
        self.site.rename(vendor)
        self.site = vendor
        for rule in self.profile['cudaExcludedDistributions']:
            dist = rule['name'].replace('-', '_') + '-' + rule['version'] + '.dist-info'
            payload = {package + '/__init__.py': b'# optional fixture\n' for package in rule['packages']}
            payload[dist + '/METADATA'] = ('Name: ' + rule['name'] + '\nVersion: ' + rule['version'] + '\n').encode()
            payload[dist + '/LICENSE'] = b'original optional-package license'
            for name, entry in rule['scripts'].items():
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, 'w') as archive:
                    archive.writestr('__main__.py', entry + '\n')
                payload[name] = stream.getvalue()
            rows = io.StringIO(newline='')
            writer = csv.writer(rows, lineterminator='\n')
            for name, data in sorted(payload.items()):
                writer.writerow([name, 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode(), len(data)])
                self.file(name, data)
            writer.writerow([dist + '/RECORD', '', ''])
            self.file(dist + '/RECORD', rows.getvalue().encode())

    def run_cuda_projection(self):
        return P.project(self.source, self.output, self.profile_path, self.wheel, self.receipt, 'cuda')

    def test_cuda_excludes_only_explicit_packages_and_recognized_commands(self):
        self.prepare_cuda()
        before = {name: P.L.sha256_file(path) for name, path in P.L.tree_files(self.source).items()}
        result = self.run_cuda_projection()
        self.assertEqual(len(result['excludedDistributions']), 5)
        for rule in self.profile['cudaExcludedDistributions']:
            for name in [*rule['packages'], *rule['scripts']]:
                self.assertFalse((self.output / name).exists())
        self.assertEqual((self.output / 'bottle.py').read_bytes(), b'# bottle\n')
        self.assertTrue((self.output / 'imagecodecs/_unused.pyd').exists())  # CUDA规则不裁其它组件的图像库。
        self.assertEqual(before, {name: P.L.sha256_file(path) for name, path in P.L.tree_files(self.source).items()})
        previous = result['outputFiles']
        shutil.copytree(self.output, self.root / 'build/cuda-reuse/vendor')
        self.source = self.root / 'build/cuda-reuse'
        self.output = self.root / 'build/cuda-reused-output'
        self.receipt = self.audit / 'cuda-reuse.json'
        reused = self.run_cuda_projection()
        self.assertEqual(previous, reused['outputFiles'])
        self.assertTrue(all(row['status'] == 'ALREADY_ABSENT' for row in reused['excludedDistributions']))

    def test_cuda_shared_record_owner_blocks_exclusion(self):
        self.prepare_cuda()
        self.file('retained-1.dist-info/RECORD', b'baidubce/__init__.py,,\n')
        with self.assertRaisesRegex(ValueError, '仍被其它发行版拥有'):
            self.run_cuda_projection()
        self.assertFalse(self.output.exists())

    def test_cuda_missing_metadata_with_remaining_package_fails_closed(self):
        self.prepare_cuda()
        (self.site / 'psutil-7.2.2.dist-info/METADATA').unlink()
        with self.assertRaisesRegex(ValueError, '元数据缺失但命名空间/命令残留'):
            self.run_cuda_projection()
        self.assertFalse(self.output.exists())

    def test_cuda_unknown_optional_version_and_unrecognized_script_fail_closed(self):
        self.prepare_cuda()
        self.file('psutil-7.2.2.dist-info/METADATA', b'Name: psutil\nVersion: 99.0\n')
        with self.assertRaisesRegex(ValueError, '版本不符'):
            self.run_cuda_projection()
        self.file('psutil-7.2.2.dist-info/METADATA', b'Name: psutil\nVersion: 7.2.2\n')
        self.file('bin/crc32c.exe', b'unrecognized command')
        with self.assertRaisesRegex(ValueError, '不能识别可选包的pip开发命令'):
            self.run_cuda_projection()
        self.assertFalse(self.output.exists())

    def test_cuda_input_lock_generator_policy_and_projection_are_synchronized(self):
        splitter = load('tested_projection_splitter', ROOT / 'build/tools/split_lock.py')
        _, original = splitter.parseLock((ROOT / 'build/requirements-windows-cu126.lock').read_text('utf-8'))
        _, runtime = splitter.parseLock((ROOT / 'build/requirements-gpu-plugin-windows-cu126.lock').read_text('utf-8'))
        omitted = {row['name'] for row in self.profile['cudaExcludedDistributions']}
        self.assertEqual(splitter.GPU_RUNTIME_EXCLUSIONS, omitted | {'aistudio-sdk'})
        self.assertFalse({name for name, _ in runtime} & omitted)
        originals = dict(original)
        for name, block in runtime:
            self.assertEqual(block, originals[name])
        for name in omitted:
            self.assertIn(name, originals)
        policy = json.loads((ROOT / 'build/windows/runtime_archives_cuda.json').read_text('utf-8'))
        self.assertNotIn('future', policy['archives'][0]['packages'])

    def test_corrupt_stored_zip_is_not_ignored(self):
        (self.source / 'dependencies.zip').write_bytes(b'not-a-valid-archive')
        with self.assertRaises(P.L.LayoutError):
            self.run_projection()
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--work', type=Path, default=WORK)
    args, remaining = parser.parse_known_args()
    WORK = args.work.resolve(strict=True)
    unittest.main(argv=[sys.argv[0], *remaining])
