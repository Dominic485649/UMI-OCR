"""Focused runtime-selection and derived-metadata tests, not native acceptance."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('package_trimmed_qt', ROOT / 'build/tools/package_trimmed_qt.py')
P = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = P
spec.loader.exec_module(P)
NOTICES = P.load('_qt_actual_component_section', ROOT / 'build/tools/generate_third_party_components.py')
# Synthetic non-executable fixtures only; production packaging reads real receipts.
INPUT_RECORDS = {name: 'a' * 64 for name in P.Q.PROFILE_REQUIRED_INPUTS}
SOURCE_COMMIT = 'b' * 40


class QtBundleSelectionTests(unittest.TestCase):
    def policy(self):
        return {'requiredQmlModules': ['QtQuick', 'QtQuick/Controls/Basic'],
                'excludedQmlPrefixes': ['QtQuick/Controls/Fusion']}

    def test_required_and_scanned_modules_form_explicit_closure(self):
        inventory = {name: {} for name in ['qml/QtQuick/qmldir', 'qml/QtQuick/Controls/Basic/qmldir',
                                           'qml/QtQuick/Layouts/qmldir', 'qml/QtQuick/Controls/Fusion/qmldir']}
        scan = [{'relativePath': 'QtQuick/Layouts'}, {'relativePath': 'QtQuick/Controls/Fusion'}]
        allowed, available = P.qml_modules(self.policy(), scan, inventory)
        self.assertEqual(allowed, {'QtQuick', 'QtQuick/Controls/Basic', 'QtQuick/Layouts'})
        self.assertIn('QtQuick/Controls/Fusion', available)

    def test_missing_required_module_fails_instead_of_cutting_functionality(self):
        with self.assertRaisesRegex(P.Q.Error, 'Required QML module is absent'):
            P.qml_modules(self.policy(), [], {'qml/QtQuick/qmldir': {}})

    def test_nested_unselected_module_not_rescued_by_selected_parent(self):
        allowed = {'QtQuick'}
        available = {'QtQuick', 'QtQuick/Unused'}
        self.assertTrue(P.qml_member_selected('qml/QtQuick/qmldir', allowed, available))
        self.assertTrue(P.qml_member_selected('qml/QtQuick/assets/view.qml', allowed, available))
        self.assertFalse(P.qml_member_selected('qml/QtQuick/Unused/Widget.qml', allowed, available))

    def test_dialog_style_selectors_match_existing_runtime_policy(self):
        modules = {'QtQuick/Dialogs/quickimpl'}
        self.assertFalse(P.qml_member_selected('qml/QtQuick/Dialogs/quickimpl/qml/+Material/FileDialog.qml', modules, modules))
        self.assertTrue(P.qml_member_selected('qml/QtQuick/Dialogs/quickimpl/qml/FileDialog.qml', modules, modules))

    def test_development_qml_type_metadata_not_packaged(self):
        modules = {'QtQuick'}
        self.assertFalse(P.qml_member_selected('qml/QtQuick/plugins.qmltypes', modules, modules))
        self.assertTrue(P.qml_member_selected('qml/QtQuick/qtquick2plugin.dll', modules, modules))

    def test_unsafe_scanner_path_rejected(self):
        with self.assertRaisesRegex(P.Q.Error, 'Unsafe relative path'):
            P.qml_modules(self.policy(), [{'relativePath': '../outside'}], {})

    def test_all_four_metadata_identities_are_derived_and_exact(self):
        result = P.distribution_metadata(P.VERSION, INPUT_RECORDS, SOURCE_COMMIT)
        self.assertEqual(len(result), 12)
        for name, content in result.items():
            self.assertIn(P.VERSION, name)
            if name.endswith('/METADATA'):
                metadata = P.Q._metadata(content)
                self.assertEqual(metadata['Version'], P.VERSION)
                self.assertIn('not an upstream wheel', metadata['Summary'])
                for dependency in metadata.get_all('Requires-Dist', []):
                    self.assertTrue(dependency.endswith('==' + P.VERSION))
            elif name.endswith('/WHEEL'):
                self.assertIn(b'Tag: cp310-abi3-win_amd64', content)
            else:
                profile = json.loads(content)
                self.assertTrue(name.endswith('/' + P.Q.PROFILE))
                self.assertEqual(profile['version'], P.VERSION)
                self.assertEqual(profile['sourceCommit'], SOURCE_COMMIT)
                self.assertEqual(profile['inputRecords'], INPUT_RECORDS)
                self.assertEqual(P.owner(name), profile['distribution'])

    def component_notice_fixture(self):
        temporary = tempfile.TemporaryDirectory(prefix='qt-component-notice-test-', dir=ROOT / 'build/tmp')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        site = root / 'site-packages'
        site.mkdir()
        for name, data in P.distribution_metadata(P.VERSION, INPUT_RECORDS, SOURCE_COMMIT).items():
            target = site / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        lock = root / 'original-qt-input.lock'
        lock.write_text(''.join(name + '==6.11.2\n' for name in sorted(P.Q.DISTRIBUTIONS)), encoding='utf-8')
        return site, lock

    def test_actual_component_section_accepts_all_four_derived_profiles(self):
        site, lock = self.component_notice_fixture()
        before = lock.read_bytes()
        section = NOTICES.section('Synthetic Qt integration fixture', lock, site)
        for distribution in P.Q.DISTRIBUTIONS:
            self.assertIn('| ' + distribution + ' | ' + P.VERSION + '（派生；原始输入锁：6.11.2）', section)
        self.assertEqual(section.count('https://code.qt.io/pyside/pyside-setup.git/tree/?id=' + SOURCE_COMMIT), 4)
        self.assertEqual(lock.read_bytes(), before)

    def test_actual_component_section_rejects_missing_profile(self):
        site, lock = self.component_notice_fixture()
        next(site.glob('*/' + P.Q.PROFILE)).unlink()
        with self.assertRaisesRegex(RuntimeError, 'without an explicit derived profile'):
            NOTICES.section('Synthetic missing marker', lock, site)

    def test_actual_component_section_rejects_duplicate_profiles(self):
        site, lock = self.component_notice_fixture()
        marker = next(site.glob('*/' + P.Q.PROFILE))
        marker.with_name('UMI_RUNTIME_SUBSET.json').write_bytes(marker.read_bytes())
        with self.assertRaisesRegex(RuntimeError, 'without an explicit derived profile'):
            NOTICES.section('Synthetic duplicate marker', lock, site)

    def test_actual_component_section_rejects_wrong_profile_version(self):
        site, lock = self.component_notice_fixture()
        marker = next(site.glob('*/' + P.Q.PROFILE))
        value = json.loads(marker.read_bytes())
        value['version'] = '6.11.2'
        marker.write_bytes(P.encoded(value))
        with self.assertRaisesRegex(RuntimeError, 'does not match the upstream input pin'):
            NOTICES.section('Synthetic wrong marker version', lock, site)

    def test_metadata_rejects_incomplete_source_build_bindings(self):
        incomplete = dict(INPUT_RECORDS)
        del incomplete['source']
        with self.assertRaisesRegex(P.Q.Error, 'complete source/build input bindings'):
            P.distribution_metadata(P.VERSION, incomplete, SOURCE_COMMIT)
        with self.assertRaisesRegex(P.Q.Error, 'pinned source identity'):
            P.distribution_metadata(P.VERSION, INPUT_RECORDS, 'not-a-commit')

    def test_runtime_notices_keep_originals_without_internal_audit(self):
        original = {'source': 'LICENSE', 'sha256': 'a' * 64, 'bytes': 100, 'text': 'texts/license.txt'}
        index = {'explicitSourceMappings': ['INTERNAL_DIAGNOSTIC'], 'relaxedOriginalJson': ['INTERNAL_PARSER_DETAIL'],
                 'entries': [{'component': 'Chromium proto', 'selection': 'INTERNAL_GN_SELECTION', 'originalTexts': [original],
                              'evidence': [{'origin': {'source': 'test.proto', 'sha256': 'b' * 64},
                                            'originalHeader': '// Copyright 2020 The Chromium Authors\n'}]}]}
        runtime = P.runtime_notice_index(index)
        encoded = P.encoded(runtime)
        self.assertNotIn(b'INTERNAL_', encoded)
        entry = runtime['entries'][0]
        self.assertEqual(entry['originalTexts'], [original])
        self.assertEqual(entry['originalCopyrightHeaders'][0]['text'], '// Copyright 2020 The Chromium Authors\n')
        self.assertEqual(index['explicitSourceMappings'], ['INTERNAL_DIAGNOSTIC'])

    def test_shiboken_and_webengine_ownership(self):
        self.assertEqual(P.owner('shiboken6/Shiboken.pyd'), 'shiboken6')
        self.assertEqual(P.owner('PySide6/QtWebEngineCore.pyd'), 'pyside6-addons')
        self.assertEqual(P.owner('PySide6/Qt6WebEngineCore.dll'), 'pyside6-addons')
        self.assertEqual(P.owner('PySide6/resources/icudtl.dat'), 'pyside6-addons')
        self.assertEqual(P.owner('PySide6/QtCore.pyd'), 'pyside6-essentials')


if __name__ == '__main__':
    unittest.main(verbosity=2)
