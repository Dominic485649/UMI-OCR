"""Synthetic projection/RECORD/path tests; deliberately not native Qt acceptance."""
import base64
import csv
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('project_derived_qt', ROOT / 'build/tools/project_derived_qt.py')
Q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(Q)
VERSION = '6.11.2+umi.qttrim.1'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8') + b'\n'


def info(value):
    return {'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}


class DerivedQtProjectionTests(unittest.TestCase):
    def setUp(self):
        # All disposable fixtures are owned by this test; no fixture program is
        # executed and no external process can be launched from their contents.
        self.temp = tempfile.TemporaryDirectory(prefix='derived-qt-unit-', dir=ROOT / 'build/tmp')
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.policy_path = ROOT / 'build/qt-runtime-whitelist.json'
        self.policy = json.loads(self.policy_path.read_text('utf-8'))
        self.bundle = self.root / 'derived-qt.zip'
        self.lock = self.root / 'derived-qt.lock.json'
        self.runtime = {
            'qtVersion': '6.11.2', 'quickStyle': 'Basic',
            'pythonExtensions': self.policy['pythonExtensions'], 'executables': self.policy['executables'],
            'webEngineResources': self.policy['webEngineResources'], 'webEngineLocales': self.policy['webEngineLocales'],
            'plugins': self.policy['pluginFiles'], 'qmlModules': self.policy['requiredQmlModules'],
            'rootDlls': ['Qt6Core.dll'],
        }
        self.receipts = {name: 'a' * 64 for name in Q.PROFILE_REQUIRED_INPUTS}
        self.source_commit = 'b' * 40  # Synthetic identity; no fixture binary executes.
        self.payload = {
            Q.RUNTIME: encoded(self.runtime), Q.DERIVATION: encoded({'qtVersion': '6.11.2', 'derivedVersion': VERSION,
                'inputRecords': self.receipts, 'pysideSourceCommit': self.source_commit, 'syntheticFixture': True})}
        paths = {'PySide6/__init__.py', 'shiboken6/__init__.py', 'shiboken6/Shiboken.pyd', 'shiboken6/shiboken6.abi3.dll', 'PySide6/Qt6Core.dll'}
        paths |= {'PySide6/' + name for name in self.policy['pythonExtensions'] + self.policy['executables']}
        paths |= {'PySide6/plugins/' + name for name in self.policy['pluginFiles']}
        paths |= {'PySide6/qml/' + name + '/qmldir' for name in self.policy['requiredQmlModules']}
        paths |= {'PySide6/resources/' + name for name in self.policy['webEngineResources']}
        paths |= {'PySide6/translations/qtwebengine_locales/' + name + '.pak' for name in self.policy['webEngineLocales']}
        for path in paths:
            self.payload['site-packages/' + path] = b'SYNTHETIC_NOT_EXECUTABLE\n'
        self.make_distributions()
        self.write_bundle()

    def make_distributions(self):
        for path in list(self.payload):
            if path.startswith('site-packages/') and '.dist-info/' in path:
                del self.payload[path]
        dependencies = {'pyside6': ['shiboken6', 'pyside6-essentials', 'pyside6-addons'],
                        'pyside6-essentials': ['shiboken6'], 'pyside6-addons': ['shiboken6', 'pyside6-essentials'], 'shiboken6': []}
        for dist in sorted(Q.DISTRIBUTIONS):
            top = dist.replace('-', '_') + '-' + VERSION + '.dist-info'
            metadata = 'Metadata-Version: 2.1\nName: ' + dist + '\nVersion: ' + VERSION + '\n'
            metadata += ''.join('Requires-Dist: ' + name + '==' + VERSION + '\n' for name in dependencies[dist])
            self.payload['site-packages/' + top + '/METADATA'] = metadata.encode()
            self.payload['site-packages/' + top + '/WHEEL'] = b'Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: cp310-abi3-win_amd64\n'
            self.payload['site-packages/' + top + '/' + Q.PROFILE] = encoded({
                'format': Q.PROFILE_FORMAT, 'distribution': dist, 'version': VERSION, 'upstreamVersion': '6.11.2',
                'sourceCommit': self.source_commit, 'inputRecords': self.receipts,
                'sourceUrl': 'https://code.qt.io/pyside/pyside-setup.git/tree/?id=' + self.source_commit})
        self.rebuild_records()

    def rebuild_records(self):
        for path in list(self.payload):
            if path.endswith('.dist-info/RECORD'):
                del self.payload[path]
        groups = {name: [] for name in Q.DISTRIBUTIONS}
        for full, data in self.payload.items():
            if not full.startswith('site-packages/'):
                continue
            name = full.removeprefix('site-packages/')
            top = name.split('/')[0]
            if top.endswith('.dist-info'):
                owner = Q.normalized(top.split('-' + VERSION)[0])
            elif top == 'shiboken6':
                owner = 'shiboken6'
            else:
                owner = 'pyside6-essentials'
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
            groups[owner].append([name, 'sha256=' + digest, str(len(data))])
        for owner, rows in groups.items():
            record = owner.replace('-', '_') + '-' + VERSION + '.dist-info/RECORD'
            output = io.StringIO(newline='')
            writer = csv.writer(output, lineterminator='\n')
            writer.writerows(sorted(rows))
            writer.writerow([record, '', ''])
            self.payload['site-packages/' + record] = output.getvalue().encode()

    def write_bundle(self, extra=None):
        manifest = encoded({'format': Q.PAYLOAD_FORMAT, 'derivedVersion': VERSION,
                            'files': {path: info(data) for path, data in self.payload.items()}})
        with zipfile.ZipFile(self.bundle, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path, data in self.payload.items():
                archive.writestr(path, data)
            archive.writestr(Q.MANIFEST, manifest)
            if extra:
                for path, data in extra.items():
                    archive.writestr(path, data)
        lock = {'format': Q.FORMAT, 'qtVersion': '6.11.2', 'derivedVersion': VERSION,
                'whitelistSha256': Q.L.sha256_file(self.policy_path), 'inputRecords': self.receipts,
                'payloadManifestSha256': hashlib.sha256(manifest).hexdigest(),
                'archive': {'name': self.bundle.name, **info(self.bundle.read_bytes())}}
        self.lock.write_bytes(encoded(lock))

    def inspect(self):
        return Q.inspect_bundle(self.bundle, self.lock, self.policy_path)

    def source(self):
        root = self.root / 'original-site'
        root.mkdir()
        for dist in Q.DISTRIBUTIONS:
            directory = root / (dist.replace('-', '_') + '-6.11.2.dist-info')
            directory.mkdir()
            (directory / 'METADATA').write_text('Name: ' + dist + '\nVersion: 6.11.2\n', encoding='utf-8')
            (directory / 'RECORD').write_text('', encoding='utf-8')
        (root / 'PySide6').mkdir()
        (root / 'PySide6/old-unused.pyd').write_bytes(b'OLD-INPUT-DO-NOT-OVERWRITE')
        (root / 'shiboken6').mkdir()
        (root / 'shiboken6/old.dll').write_bytes(b'OLD-SHIBOKEN')
        (root / 'sample').mkdir()
        (root / 'sample/value.py').write_bytes(b'VALUE = 42\n')
        return root

    def project(self, source, destination=None):
        return Q.project(source, destination or self.root / 'new-site', self.bundle, self.lock, self.policy_path,
                         self.root / 'runtime.json', self.root / 'receipt.json')

    def test_valid_integrity_is_not_native_acceptance(self):
        result = self.inspect()
        self.assertEqual(result['status'], 'BUNDLE_INTEGRITY_VERIFIED_NOT_APP_ACCEPTED')
        self.assertEqual(result['derivedVersion'], VERSION)

    def test_project_replaces_whole_qt_preserves_source_and_other_dependencies(self):
        source = self.source()
        before = {name: Q.L.sha256_file(path) for name, path in Q.L.tree_files(source).items()}
        result = self.project(source)
        self.assertEqual(result['status'], 'PROJECTED_VERIFIED_NOT_APP_ACCEPTED')
        self.assertEqual(result['runtimeAcceptance'], 'NOT_RUN')
        self.assertFalse((self.root / 'new-site/PySide6/old-unused.pyd').exists())
        self.assertEqual((self.root / 'new-site/sample/value.py').read_bytes(), b'VALUE = 42\n')
        self.assertTrue((self.root / 'new-site/shiboken6/Shiboken.pyd').is_file())
        self.assertEqual(before, {name: Q.L.sha256_file(path) for name, path in Q.L.tree_files(source).items()})
        self.assertFalse((self.root / 'new-site/bin').exists())

    def test_refuse_existing_destination(self):
        source = self.source()
        destination = self.root / 'new-site'
        destination.mkdir()
        with self.assertRaisesRegex(Q.Error, 'existing/overlapping'):
            self.project(source, destination)
        self.assertFalse((self.root / 'receipt.json').exists())

    def test_refuse_in_place_projection(self):
        source = self.source()
        with self.assertRaisesRegex(Q.Error, 'existing/overlapping'):
            self.project(source, source)

    def test_missing_runtime_profile_rejected(self):
        path = 'site-packages/pyside6-' + VERSION + '.dist-info/' + Q.PROFILE
        del self.payload[path]
        self.rebuild_records()
        self.write_bundle()
        with self.assertRaisesRegex(Q.Error, 'exactly one runtime profile'):
            self.inspect()

    def test_duplicate_runtime_markers_rejected(self):
        root = 'site-packages/pyside6-' + VERSION + '.dist-info/'
        self.payload[root + 'UMI_RUNTIME_SUBSET.json'] = self.payload[root + Q.PROFILE]
        self.rebuild_records()
        self.write_bundle()
        with self.assertRaisesRegex(Q.Error, 'exactly one runtime profile'):
            self.inspect()

    def test_rehashed_profile_cannot_replace_source_receipt(self):
        path = 'site-packages/pyside6-' + VERSION + '.dist-info/' + Q.PROFILE
        profile = json.loads(self.payload[path])
        profile['inputRecords']['source'] = 'c' * 64
        self.payload[path] = encoded(profile)
        self.rebuild_records()
        self.write_bundle()
        with self.assertRaisesRegex(Q.Error, 'source/build bindings mismatch'):
            self.inspect()

    def test_rehashed_profile_cannot_replace_source_commit(self):
        path = 'site-packages/pyside6-' + VERSION + '.dist-info/' + Q.PROFILE
        profile = json.loads(self.payload[path])
        profile['sourceCommit'] = 'c' * 40
        self.payload[path] = encoded(profile)
        self.rebuild_records()
        self.write_bundle()
        with self.assertRaisesRegex(Q.Error, 'source/build bindings mismatch'):
            self.inspect()

    def test_archive_digest_required(self):
        with self.bundle.open('ab') as stream:
            stream.write(b'tamper')
        with self.assertRaisesRegex(Q.Error, 'Archive name/size'):
            self.inspect()

    def test_policy_digest_required(self):
        value = json.loads(self.lock.read_bytes())
        value['whitelistSha256'] = '0' * 64
        self.lock.write_bytes(encoded(value))
        with self.assertRaisesRegex(Q.Error, 'whitelist input changed'):
            self.inspect()

    def test_traversal_zip_member_rejected(self):
        self.write_bundle({'site-packages/../escape.txt': b'bad'})
        with self.assertRaisesRegex(Q.Error, 'Unsafe relative'):
            self.inspect()

    def test_case_collision_rejected(self):
        self.write_bundle({'SITE-PACKAGES/PySide6/QtCore.pyd': b'bad'})
        with self.assertRaisesRegex(Q.Error, 'Duplicate/colliding'):
            self.inspect()

    def test_unlisted_zip_member_rejected(self):
        self.write_bundle({'site-packages/PySide6/unlisted.txt': b'bad'})
        with self.assertRaisesRegex(Q.Error, 'member sets differ'):
            self.inspect()

    def test_forged_record_rejected_after_rehashing_bundle(self):
        path = 'site-packages/pyside6_essentials-' + VERSION + '.dist-info/RECORD'
        self.payload[path] = self.payload[path].replace(b'sha256=', b'sha512=', 1)
        self.write_bundle()
        with self.assertRaisesRegex(Q.Error, 'RECORD digest/size'):
            self.inspect()

    def test_unowned_payload_rejected(self):
        self.payload['site-packages/PySide6/orphan.txt'] = b'orphan'
        self.write_bundle()
        with self.assertRaisesRegex(Q.Error, 'undeclared distribution files'):
            self.inspect()

    def test_official_version_cannot_label_derived_payload(self):
        path = 'site-packages/pyside6-' + VERSION + '.dist-info/METADATA'
        self.payload[path] = self.payload[path].replace(('Version: ' + VERSION).encode(), b'Version: 6.11.2')
        self.rebuild_records()
        self.write_bundle()
        with self.assertRaisesRegex(Q.Error, 'distribution identity'):
            self.inspect()

    def test_missing_required_binding_rejected(self):
        del self.payload['site-packages/PySide6/QtWebEngineCore.pyd']
        self.rebuild_records()
        self.write_bundle()
        with self.assertRaisesRegex(Q.Error, 'bindings do not match'):
            self.inspect()

    def test_development_executable_rejected(self):
        self.payload['site-packages/PySide6/qmlimportscanner.exe'] = b'BUILD-TOOL-NOT-RUNTIME'
        self.rebuild_records()
        self.write_bundle()
        with self.assertRaisesRegex(Q.Error, 'Unexpected runtime executable'):
            self.inspect()

    def test_other_distribution_ownership_protects_qt_extension(self):
        source = self.source()
        dist = source / 'thirdparty-1.dist-info'
        dist.mkdir()
        (dist / 'METADATA').write_text('Name: thirdparty\nVersion: 1\n', encoding='utf-8')
        (dist / 'RECORD').write_text('PySide6/old-unused.pyd,,\n', encoding='utf-8')
        with self.assertRaisesRegex(Q.Error, 'Non-Qt distribution owns'):
            self.project(source)
        self.assertFalse((self.root / 'new-site').exists())

    def test_hardlinked_source_rejected(self):
        source = self.source()
        os.link(source / 'sample/value.py', source / 'sample/alias.py')
        with self.assertRaisesRegex(Q.Error, 'Hard-linked'):
            self.project(source)
        self.assertFalse((self.root / 'new-site').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
