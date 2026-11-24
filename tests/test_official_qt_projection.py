"""Inert official-wheel fixtures; never load Qt, download, pip-install or build."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / 'build/audit/dependency-trim-20261116-pip-r1/tmp'
spec = importlib.util.spec_from_file_location('official_qt_projection', ROOT / 'build/tools/official_qt_projection.py')
Q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(Q)


class OfficialQtProjectionTests(unittest.TestCase):
    def setUp(self):
        TMP.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='official-qt-unit-', dir=TMP)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.wheels = self.root / 'wheels'
        self.wheels.mkdir()
        self.site = self.root / 'new-site'
        self.lock = self.root / 'requirements.lock'
        self.policy = self.root / 'policy.json'
        self.qml = self.root / 'qml'
        self.qml.mkdir()
        (self.qml / 'Main.qml').write_text('import QtQuick\nItem {}\n', encoding='utf-8')
        self.trim = self.root / 'Trim-Qt.ps1'
        self.trim.write_bytes(b'# INERT fixture identity, never executed\n')
        self.manifest = self.root / 'manifest.json'
        self.input_receipt = self.root / 'input.json'
        self.receipt = self.root / 'result.json'
        self.config = {'qtVersion': '6.11.2', 'quickStyle': 'Basic', 'pythonExtensions': ['QtCore.pyd'],
                       'executables': ['QtWebEngineProcess.exe'], 'pluginFiles': ['platforms/qwindows.dll'],
                       'webEngineResources': ['icudtl.dat'], 'webEngineLocales': ['en-US'],
                       'requiredQmlModules': ['QtQuick'], 'excludedQmlPrefixes': ['Unused'],
                       'translationLocales': ['en'], 'removeDirectories': ['include']}
        self.policy.write_bytes(Q.encoded(self.config))
        self.runtime = {'qtVersion': '6.11.2', 'quickStyle': 'Basic', 'pythonExtensions': ['QtCore.pyd'],
                        'executables': ['QtWebEngineProcess.exe'], 'plugins': ['platforms/qwindows.dll'],
                        'webEngineResources': ['icudtl.dat'], 'webEngineLocales': ['en-US'],
                        'qmlModules': ['QtQuick'], 'rootDlls': ['qt6core.dll'], 'generatedUtc': 'fixture'}
        self.payloads = {dist: {} for dist in Q.DISTS}
        essential = {'PySide6/__init__.py', 'PySide6/QtCore.pyd', 'PySide6/Qt6Core.dll',
                     'PySide6/qmlimportscanner.exe', 'PySide6/Unused.pyd', 'PySide6/Unused.dll', 'PySide6/QtCore.pyi',
                     'PySide6/qml/QtQuick/qmldir', 'PySide6/qml/QtQuick/Foo.qml',
                     'PySide6/qml/Unused/qmldir', 'PySide6/qml/Unused/Foo.qml',
                     'PySide6/plugins/platforms/qwindows.dll', 'PySide6/plugins/unused.dll', 'PySide6/include/header.h'}
        addon = {'PySide6/QtWebEngineProcess.exe', 'PySide6/resources/icudtl.dat',
                 'PySide6/translations/qtwebengine_locales/en-US.pak'}
        for dist, names in (('pyside6-essentials', essential), ('pyside6-addons', addon),
                            ('shiboken6', {'shiboken6/__init__.py', 'shiboken6/Shiboken.pyd'})):
            for name in names:
                self.payloads[dist][name] = b'INERT fixture ' + name.encode() + b'\n'
        for dist in Q.DISTS:
            top = dist.replace('-', '_') + '-6.11.2.dist-info'
            self.payloads[dist].update({top + '/METADATA': ('Metadata-Version: 2.1\nName: ' + dist + '\nVersion: 6.11.2\n').encode(),
                                       top + '/WHEEL': b'Wheel-Version: 1.0\nTag: cp310-abi3-win_amd64\n',
                                       top + '/RECORD': b'EXACT ORIGINAL RECORD fixture, never regenerated\n'})
        self.write_wheels()

    def write_wheels(self, extra=None):
        rows = []
        for dist, payload in self.payloads.items():
            path = self.wheels / (dist.replace('-', '_') + '-6.11.2-cp310-abi3-win_amd64.whl')
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                with zipfile.ZipFile(path, 'w') as z:
                    # Shared directory entries in Addons and Essentials are legal.
                    if dist.startswith('pyside6'):
                        z.writestr('PySide6/', b'')
                    for name, data in sorted(payload.items()):
                        z.writestr(name, data)
                    if extra and extra[0] == dist:
                        name = extra[1]
                        if isinstance(name, str) and '\\' in name:
                            item = zipfile.ZipInfo('placeholder')
                            item.filename = name  # Avoid ZipInfo's Windows separator normalization.
                            name = item
                        z.writestr(name, extra[2])
            rows.append(dist + '==6.11.2 \\\n    --hash=sha256:' + Q.digest(path))
        self.lock.write_text('\n'.join(rows) + '\n', encoding='utf-8')

    def extract(self):
        return Q.extract(self.wheels, self.site, self.lock, self.input_receipt)

    def trimmed(self):
        self.extract()
        for name in ('qmlimportscanner.exe', 'Unused.pyd', 'Unused.dll', 'QtCore.pyi', 'plugins/unused.dll', 'include/header.h',
                     'qml/Unused/qmldir', 'qml/Unused/Foo.qml'):
            (self.site / 'PySide6' / name).unlink()
        self.manifest.write_bytes(Q.encoded(self.runtime))

    def seal(self):
        return Q.seal(self.site, self.lock, self.policy, self.qml, self.trim, self.manifest, self.input_receipt, self.receipt)

    def verify(self):
        return Q.verify(self.site, self.lock, self.policy, self.qml, self.trim, self.manifest, self.receipt)

    def test_success_seal_verify_preserves_metadata_and_compact_manifest(self):
        self.trimmed()
        original = (self.site / 'pyside6-6.11.2.dist-info/RECORD').read_bytes()
        record = self.seal()
        self.assertEqual(record['status'], 'SEALED_VERIFIED_NOT_APP_ACCEPTED')
        self.assertIn('PySide6/qmlimportscanner.exe', record['deleted'])
        self.assertEqual(len(record['binding']['wheels']), 4)
        self.assertIn('Main.qml', record['qmlInputs'])
        self.assertEqual(self.verify()['status'], 'REUSE_VERIFIED_NOT_APP_ACCEPTED')
        self.assertEqual(original, (self.site / 'pyside6-6.11.2.dist-info/RECORD').read_bytes())
        manifest = json.loads(self.manifest.read_bytes())
        self.assertNotIn('retained', manifest['officialQtProjection'])
        self.assertLess(self.manifest.stat().st_size, 4000)
        # Runtime caches alone are ignored, never other unknown payloads.
        (self.site / 'PySide6/__pycache__').mkdir()
        (self.site / 'PySide6/__pycache__/runtime.pyc').write_bytes(b'cache')
        self.verify()
        (self.site / 'PySide6/__pycache__/foreign.dll').write_bytes(b'not a cache')
        with self.assertRaisesRegex(Q.ProjectionError, 'runtime payload changed'):
            self.verify()

    def test_original_bytecode_is_excluded_not_falsely_reported_deleted(self):
        present = 'PySide6/support/__pycache__/__init__.cpython-310.pyc'
        absent = 'shiboken6/__pycache__/__init__.cpython-310.pyc'
        mandatory = 'PySide6/support/__pycache__/required.txt'
        self.payloads['pyside6-essentials'][present] = b'original wheel cache'
        self.payloads['pyside6-essentials'][mandatory] = b'not bytecode'
        self.payloads['shiboken6'][absent] = b'original shiboken cache'
        self.write_wheels()
        self.trimmed()
        (self.site / absent).unlink()
        record = self.seal()
        self.assertEqual(set(record['ignoredBytecode']), {present, absent})
        self.assertTrue((self.site / present).is_file())
        self.assertNotIn(present, record['deleted'])
        self.assertNotIn(absent, record['deleted'])
        self.assertIn(mandatory, record['retained'])
        self.verify()
        (self.site / mandatory).unlink()
        with self.assertRaises(Q.ProjectionError):
            self.verify()
    def test_hash_mismatch_before_destination_creation(self):
        path = next(self.wheels.glob('*.whl'))
        with path.open('ab') as stream:
            stream.write(b'changed')
        with self.assertRaisesRegex(Q.ProjectionError, 'SHA-256 mismatch'):
            self.extract()
        self.assertFalse(self.site.exists())

    def test_zip_escape_duplicate_and_unknown_namespace(self):
        for name in ('../outside', 'PySide6/../../outside', 'PySide6\\bad', 'elsewhere/data',
                     'PySide6/QtCore.pyd', 'PySide6/qtcore.pyd', 'PySide6/NUL.dll'):
            with self.subTest(name=name):
                self.write_wheels(('pyside6-essentials', name, b'inert'))
                with self.assertRaises(Q.ProjectionError):
                    self.extract()
                self.assertFalse(self.site.exists())

    def test_zip_link_and_cross_wheel_duplicate(self):
        item = zipfile.ZipInfo('PySide6/link')
        item.create_system = 3
        item.external_attr = (0o120777 << 16)
        self.write_wheels(('pyside6-essentials', item, b'outside'))
        with self.assertRaisesRegex(Q.ProjectionError, 'link/special'):
            self.extract()
        self.write_wheels(('pyside6-addons', 'PySide6/QtCore.pyd', b'inert'))
        with self.assertRaisesRegex(Q.ProjectionError, 'Duplicate/colliding'):
            self.extract()

    def test_identical_cross_wheel_members_merge_with_all_owners(self):
        shared_name = 'PySide6/shared.py'
        shared = b'INERT shared official member\n'
        owners = ['pyside6', 'pyside6-addons', 'pyside6-essentials']
        for dist in owners:
            self.payloads[dist][shared_name] = shared
        stub_name = 'PySide6/QtCore.pyi'
        self.payloads['pyside6'][stub_name] = self.payloads['pyside6-essentials'][stub_name]
        self.write_wheels()
        self.trimmed()
        self.assertEqual((self.site / shared_name).read_bytes(), shared)
        source = json.loads(self.input_receipt.read_bytes())
        self.assertEqual(source['members'][shared_name]['distributions'], owners)
        self.assertEqual(source['members'][stub_name]['distributions'], ['pyside6', 'pyside6-essentials'])
        record = self.seal()
        self.assertEqual(record['retained'][shared_name]['distributions'], owners)
        self.assertEqual(record['deleted'][stub_name]['distributions'], ['pyside6', 'pyside6-essentials'])
        self.verify()

    def test_shared_member_rule_still_rejects_aliases_directories_and_same_zip_duplicates(self):
        data = self.payloads['pyside6-essentials']['PySide6/QtCore.pyd']
        for dist, name, value in (
                ('pyside6-addons', 'PySide6/qtcore.pyd', data),
                ('pyside6-addons', 'PySide6/QtCore.pyd/', b''),
                ('pyside6-addons', 'PySide6/qml', b'file shadows directory'),
                ('pyside6-essentials', 'PySide6/QtCore.pyd', data)):
            with self.subTest(dist=dist, name=name):
                self.write_wheels((dist, name, value))
                with self.assertRaises(Q.ProjectionError):
                    self.extract()
                self.assertFalse(self.site.exists())

    def test_modified_retained_payload_and_unknown_added_payload_rejected(self):
        self.trimmed()
        path = self.site / 'PySide6/QtCore.pyd'
        before = path.read_bytes()
        path.write_bytes(b'modified')
        with self.assertRaisesRegex(Q.ProjectionError, 'retained payload changed'):
            self.seal()
        path.write_bytes(before)
        (self.site / 'PySide6/unknown.txt').write_bytes(b'unknown')
        with self.assertRaisesRegex(Q.ProjectionError, 'Unknown Qt payload'):
            self.seal()
        self.assertFalse(self.receipt.exists())

    def test_non_trimmable_deletion_is_rejected(self):
        self.trimmed()
        (self.site / 'shiboken6/__init__.py').unlink()
        with self.assertRaisesRegex(Q.ProjectionError, 'Non-trimmable'):
            self.seal()

    def test_legacy_manifest_fails_closed_without_rewriting_version(self):
        self.trimmed()
        self.runtime['qtVersion'] = '0.0.0'
        before = Q.encoded(self.runtime)
        self.manifest.write_bytes(before)
        with self.assertRaisesRegex(Q.ProjectionError, 'Legacy/unbound'):
            self.verify()
        self.assertEqual(self.manifest.read_bytes(), before)

    def test_policy_qml_tool_changes_and_tampered_manifest_payload(self):
        self.trimmed()
        self.seal()
        cases = ((self.policy, b'\n', 'policySha256'), (self.qml / 'Main.qml', b'// changed\n', 'qmlSha256'),
                 (self.trim, b'# changed\n', 'trimScriptSha256'),
                 (self.site / 'shiboken6/Shiboken.pyd', b'changed', 'runtime payload changed'))
        for path, addition, message in cases:
            with self.subTest(path=path):
                before = path.read_bytes()
                path.write_bytes(before + addition)
                with self.assertRaisesRegex(Q.ProjectionError, message):
                    self.verify()
                path.write_bytes(before)
        (self.site / 'PySide6/extra.dat').write_bytes(b'unknown')
        with self.assertRaisesRegex(Q.ProjectionError, 'runtime payload changed'):
            self.verify()
        (self.site / 'PySide6/extra.dat').unlink()
        record = json.loads(self.manifest.read_bytes())
        record['generatedUtc'] = 'changed'
        self.manifest.write_bytes(Q.encoded(record))
        with self.assertRaisesRegex(Q.ProjectionError, 'trim manifest changed'):
            self.verify()

    def test_outputs_never_overwrite_existing_audit_or_extraction(self):
        self.trimmed()
        self.seal()
        before = self.receipt.read_bytes()
        with self.assertRaisesRegex(Q.ProjectionError, 'overwrite'):
            self.seal()
        self.assertEqual(self.receipt.read_bytes(), before)
        with self.assertRaisesRegex(Q.ProjectionError, 'must be new'):
            self.extract()

    def test_original_sealed_audit_is_required_and_all_source_bindings_match(self):
        self.trimmed()
        self.seal()
        original_manifest = self.manifest.read_bytes()
        original_audit = self.receipt.read_bytes()
        for change in ('auditSha256', 'scannerSha256', 'scannerBytes'):
            with self.subTest(change=change):
                runtime = json.loads(original_manifest)
                binding = runtime['officialQtProjection']
                if change == 'auditSha256':
                    binding[change] = '0' * 64
                elif change == 'scannerSha256':
                    binding['scanner']['sha256'] = '0' * 64
                else:
                    binding['scanner']['bytes'] += 1
                self.manifest.write_bytes(Q.encoded(runtime))
                with self.assertRaisesRegex(Q.ProjectionError, 'sealed Qt audit'):
                    self.verify()
        self.manifest.write_bytes(original_manifest)
        self.receipt.write_bytes(original_audit + b'\n')
        with self.assertRaisesRegex(Q.ProjectionError, 'audit digest mismatch'):
            self.verify()
        self.receipt.unlink()
        with self.assertRaisesRegex(Q.ProjectionError, 'audit is missing'):
            self.verify()

    @unittest.skipUnless(__import__('os').name == 'nt', 'Windows drive-relative spelling')
    def test_standalone_rejects_drive_relative_path(self):
        with self.assertRaisesRegex(Q.ProjectionError, 'Drive-relative'):
            Q.plain('D:relative')

    def test_version_mismatch_is_not_repaired(self):
        self.trimmed()
        self.runtime['qtVersion'] = '0.0.0'
        self.manifest.write_bytes(Q.encoded(self.runtime))
        with self.assertRaisesRegex(Q.ProjectionError, 'version does not match'):
            self.seal()
        self.assertEqual(json.loads(self.manifest.read_bytes())['qtVersion'], '0.0.0')


if __name__ == '__main__':
    unittest.main(verbosity=2)
