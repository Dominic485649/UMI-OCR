"""可选 UI 解锁的边界回归；不启动模型或网络服务，不读取私有实现源码。"""
from __future__ import annotations

import argparse
import ctypes
from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'UmiOCR-data'), str(ROOT / 'UmiOCR-data/py_src/imports')]
from py_src.utils import ui_unlock as unlock
from py_src.tag_pages import page_registry
from py_src.plugins_controller import plugins_controller as plugins

DLL = None


class UiUnlockTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='ui-unlock-')
        self.root = Path(self.temporary.name)
        self.saved_state = unlock._state
        unlock._state = None
        page_registry.resetPluginPageClasses()

    def tearDown(self):
        unlock._state = self.saved_state
        page_registry.resetPluginPageClasses()
        self.temporary.cleanup()

    def test_source_and_stored_root(self):
        self.assertEqual(unlock._program_root(ROOT / 'UmiOCR-data/py_src/utils/ui_unlock.py'), ROOT)
        self.assertEqual(unlock._program_root(ROOT / 'UmiOCR-data/app.zip/py_src/utils/ui_unlock.py'), ROOT)

    def test_missing_and_unknown_features(self):
        self.assertFalse(unlock.probe_ui_unlock(self.root).enabled)
        with patch.object(unlock, '_program_root', return_value=self.root), patch.dict(os.environ, {'UMI_UI_UNLOCK': '1'}):
            self.assertFalse(unlock.get_ui_unlock_state().enabled)
        self.assertFalse(unlock.is_ui_feature_enabled('unknown-feature'))
        self.assertTrue(unlock.is_ui_feature_enabled(''))

    def test_invalid_file_and_budget(self):
        path = self.root / unlock.DLL_NAME
        path.write_bytes(b'MZ-not-an-unlock-module')
        self.assertFalse(unlock.probe_ui_unlock(self.root).enabled)
        self.assertEqual(path.read_bytes(), b'MZ-not-an-unlock-module')
        path.write_bytes(b'x' * (unlock._MAX_DLL_BYTES + 1))
        self.assertEqual(unlock.probe_ui_unlock(self.root).reason, 'invalid')

    def test_hard_links_rejected(self):
        original = self.root / 'original'
        original.write_bytes(b'not-a-native-library')
        os.link(original, self.root / unlock.DLL_NAME)
        self.assertEqual(unlock.probe_ui_unlock(self.root).reason, 'invalid')

    @unittest.skipUnless(sys.platform == 'win32', 'Windows 专用文件共享/FFI边界')
    def test_hash_and_load_are_under_read_lock(self):
        path = self.root / unlock.DLL_NAME
        path.write_bytes(b'controlled-test-fixture')
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        original_loader = ctypes.WinDLL
        calls = []
        class Query:
            def __call__(self, abi):
                self.argtypes, self.restype
                return 1 if abi == 1 else 0
        module = SimpleNamespace(UmiUiUnlock_Query=Query())
        def loader(name, **kwargs):
            if name == 'kernel32':
                return original_loader(name, **kwargs)
            calls.append((name, kwargs))
            with self.assertRaises(PermissionError):
                path.write_bytes(b'replacement-must-fail')
            return module
        with patch.object(unlock, '_TRUSTED_DLL_SHA256', {checksum}), patch('ctypes.WinDLL', side_effect=loader):
            result = unlock.probe_ui_unlock(self.root)
        self.assertTrue(result.enabled)
        self.assertEqual(calls, [(str(path), {'winmode': 0x900})])
        self.assertEqual(path.read_bytes(), b'controlled-test-fixture')

    @unittest.skipUnless(sys.platform == 'win32', 'Windows 专用哈希门禁')
    def test_untrusted_bytes_never_execute(self):
        path = self.root / unlock.DLL_NAME
        path.write_bytes(b'unknown-dll-implementation')
        original_loader = ctypes.WinDLL
        def loader(name, **kwargs):
            self.assertEqual(name, 'kernel32', '未知 DLL 不得交给 LoadLibrary 执行')
            return original_loader(name, **kwargs)
        with patch('ctypes.WinDLL', side_effect=loader):
            self.assertEqual(unlock.probe_ui_unlock(self.root).reason, 'untrusted-content')

    def test_startup_result_cached(self):
        locked = unlock.UiUnlockState(False, 'missing')
        with patch.object(unlock, 'probe_ui_unlock', return_value=locked) as probe:
            self.assertIs(unlock.get_ui_unlock_state(), locked)
            probe.return_value = unlock.UiUnlockState(True, 'unlocked')
            self.assertIs(unlock.get_ui_unlock_state(), locked)
            self.assertEqual(probe.call_count, 1)

    def test_page_factory_and_cached_class_gated(self):
        calls = []
        class Controller:
            pass
        def factory():
            calls.append('resolve')
            return Controller
        page_registry.registerPluginPageClass('StructuredDocument', factory,
            requiredFeature=unlock.DOCUMENT_UI_FEATURE)
        unlock._state = unlock.UiUnlockState(False, 'missing')
        self.assertIsNone(page_registry.getPluginPageClass('StructuredDocument'))
        self.assertFalse(calls)
        self.assertTrue(page_registry.isPluginPageAvailable('BatchDOC'))
        self.assertTrue(page_registry.isPluginPageAvailable('ThirdPartyPage'))
        unlock._state = unlock.UiUnlockState(True, 'unlocked')
        self.assertIs(page_registry.getPluginPageClass('StructuredDocument'), Controller)
        self.assertEqual(calls, ['resolve'])
        unlock._state = unlock.UiUnlockState(False, 'missing')
        self.assertIsNone(page_registry.getPluginPageClass('StructuredDocument'))
        self.assertEqual(calls, ['resolve'])

    def test_plugin_document_and_ocr_stay_registered(self):
        plugin_id = 'win32_PaddleOCRVL_1_6'
        parent = self.root / 'plugins'
        directory = parent / plugin_id
        directory.mkdir(parents=True)
        (directory / '__init__.py').write_text('IMPORTED = True\n', encoding='utf-8')
        (directory / 'page.py').write_text('class View: pass\n', encoding='utf-8')
        (directory / 'Page.qml').write_text('import QtQuick 2.15\nItem {}\n', encoding='utf-8')
        manifest = {'schema_version': 1, 'id': plugin_id, 'name': 'UI fixture', 'version': '3.1.2',
                    'host_api': '>=2.9,<3.0', 'platform': ['*'], 'arch': ['*'],
                    'capabilities': [{'type': kind, 'entry': 'api:Api', 'config': {
                        'global_options': {'title': kind, 'type': 'group'},
                        'local_options': {'type': 'group'}}} for kind in ('ocr', 'document')],
                    'pages': [{'key': 'StructuredDocument', 'qml': 'Page.qml', 'controller': 'page:View'}]}
        (directory / 'umi-plugin.json').write_text(json.dumps(manifest), encoding='utf-8')
        controller = plugins._PluginsControllerClass()
        with patch.object(plugins, 'PLUGINS_PATH', str(parent)):
            for enabled in (False, True, False):
                unlock._state = unlock.UiUnlockState(enabled, 'unlocked' if enabled else 'missing')
                result = controller.init()
                self.assertFalse(result['errors'])
                self.assertIn(plugin_id, result['options']['document'])
                self.assertIn(plugin_id, result['options']['ocr'])
                self.assertEqual(bool(result['pages']), enabled)
                self.assertEqual(bool(result['plugins'][0]['pages']), enabled)
                self.assertEqual(result['uiFeatures']['documentUi'], enabled)
                self.assertNotIn(plugin_id, sys.modules, '发现和门控不应导入插件实现或模型')
            controller._rollback(controller.records[plugin_id])
            self.assertNotIn('StructuredDocument', page_registry.PluginPageClass)

    def test_private_source_selection(self):
        spec = importlib.util.spec_from_file_location('ui_source_boundary', ROOT / 'build/tools/source_snapshot.py')
        selector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(selector)
        for public in (False, True):
            for name in ('unlock.cpp', 'CMakeLists.txt', 'version.rc', 'build-r1/Release/Umi-OCR-UIUnlock.dll'):
                self.assertTrue(selector.is_excluded(Path('build/private/ui-unlock-v1') / name, public=public))
            self.assertFalse(selector.is_excluded(Path('UmiOCR-data/py_src/utils/ui_unlock.py'), public=public))
        self.assertNotIn('build/private', '\n'.join(path.as_posix() for path in selector.relative_entries(ROOT)))

    @unittest.skipUnless(sys.platform == 'win32', 'Windows x64 实际 DLL')
    def test_actual_private_dll(self):
        if DLL is None:
            self.skipTest('本次未传入实际私有 DLL；不把缺少产物算运行通过')
        self.assertEqual(DLL.name, unlock.DLL_NAME)
        result = unlock.probe_ui_unlock(DLL.parent)
        self.assertTrue(result.enabled, asdict(result))
        self.assertIn(result.sha256, unlock._TRUSTED_DLL_SHA256)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dll', type=Path)
    args = parser.parse_args()
    DLL = args.dll.resolve() if args.dll else None
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(UiUnlockTests))
    raise SystemExit(0 if result.wasSuccessful() else 1)
