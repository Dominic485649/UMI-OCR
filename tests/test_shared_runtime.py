"""共享运行组的契约、失败隔离和已安装消费者保留。"""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'UmiOCR-data'), str(ROOT / 'build/tools')]
import shared_runtime_bootstrap as runtime
import fixed_installation_update as fixed
import shared_runtime_projection as projection


class SharedRuntimeTests(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory(prefix='umi-shared-')
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)
        self.data = self.root / 'UmiOCR-data'
        self.payload = {'numpy/__init__.py': b'numpy', 'cv2/__init__.py': b'opencv',
                        'PIL/__init__.py': b'pillow', 'six.py': b'six', 'numpy.libs/core.dll': b'native'}
        self.ref, self.group_root = self.assemble('common', self.payload)
        self.binding = {'format': runtime.BINDING_FORMAT, 'abi': runtime.ABI, 'groups': [self.ref]}

    def assemble(self, kind, files):
        raw = runtime.canonical_json(runtime.group_document(kind, {k: projection.row(v) for k, v in files.items()}))
        digest = hashlib.sha256(raw).hexdigest()
        root = self.data / runtime.DIRECTORY / digest
        root.mkdir(parents=True)
        (root / runtime.GROUP_MANIFEST).write_bytes(raw)
        for k, value in files.items():
            p = root / 'site-packages' / k
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(value)
        return {'kind': kind, 'sha256': digest}, root

    def test_exact_reads_and_shadow(self):
        group = runtime.read_group(self.data, self.ref)
        self.assertEqual(set(group.files), set(self.payload))
        self.assertEqual(group.dll_dirs, (group.site / 'numpy.libs',))
        plugin = self.root / 'stale-vendor'
        plugin.mkdir()
        (plugin / 'NumPy.cp313-win_amd64.pyd').write_bytes(b'stale-private')
        with self.assertRaisesRegex(runtime.SharedRuntimeError, '旧散文件'):
            runtime.reject_shadows([group], [plugin])

    def test_in_place_upgrade_keeps_inactive_bytecode(self):
        group = runtime.read_group(self.data, self.ref)
        loose = self.data / 'site-packages'
        cache = loose / 'numpy' / '_core' / '__pycache__'
        cache.mkdir(parents=True)
        residue = cache / '__init__.cpython-313.pyc'
        residue.write_bytes(b'previous-launch cache')
        (loose / 'numpy-2.3.5.dist-info').mkdir()
        runtime.reject_shadows([group], [loose])
        self.assertTrue(residue.is_file())
        (loose / 'numpy' / '__init__.py').write_bytes(b'active duplicate')
        with self.assertRaisesRegex(runtime.SharedRuntimeError, '旧散文件'):
            runtime.reject_shadows([group], [loose])

    def test_corruption_and_unexpected_file(self):
        extra = self.group_root / 'site-packages/stray.pth'
        extra.write_bytes(b'not a runtime member')
        with self.assertRaises(runtime.SharedRuntimeError):
            runtime.read_group(self.data, self.ref)
        extra.unlink()
        (self.group_root / 'site-packages/six.py').write_bytes(b'BAD')
        with self.assertRaisesRegex(runtime.SharedRuntimeError, '损坏'):
            runtime.read_group(self.data, self.ref)

    def test_missing_member_and_outside_identity(self):
        (self.group_root / 'site-packages/six.py').unlink()
        with self.assertRaisesRegex(runtime.SharedRuntimeError, '缺少'):
            runtime.read_group(self.data, self.ref)
        with self.assertRaises(runtime.SharedRuntimeError):
            runtime.read_group(self.data, {'kind': 'common', 'sha256': '../other-provider'})
        with self.assertRaises(runtime.SharedRuntimeError):
            runtime.relative('numpy/bad:name')
        with self.assertRaises(runtime.SharedRuntimeError):
            runtime.relative('numpy/CON.py')
        with self.assertRaises(runtime.SharedRuntimeError):
            runtime.validate_binding({**self.binding, 'abi': 'cp312-win_amd64'})

    def test_same_tier_only_and_conflicting_dlls(self):
        gpu, _ = self.assemble('cu129', {'paddle/__init__.py': b'paddle', 'paddle/base/libpaddle.pyd': b'core',
                                        'paddle/libs/phi.dll': b'phi', 'nvidia/example/bin/core.dll': b'different'})
        binding = {**self.binding, 'groups': [self.ref, gpu]}
        with self.assertRaises(runtime.SharedRuntimeError):
            runtime.validate_binding(binding, tier='cu126')
        with self.assertRaises(runtime.SharedRuntimeError):
            runtime.validate_binding(binding, host=True)
        consumer = [runtime.read_group(self.data, x) for x in runtime.validate_binding(binding, tier='cu129')]
        with self.assertRaisesRegex(runtime.SharedRuntimeError, '同名 DLL'):
            runtime.dll_paths(consumer)

    def test_reparse_rejected(self):
        path = self.group_root / 'site-packages/six.py'
        path.unlink()
        target = self.root / 'outside.py'
        target.write_bytes(self.payload['six.py'])
        try:
            os.symlink(target, path)
        except OSError as exc:
            self.skipTest(f'系统不允许测试进程创建符号链接：{exc}')
        with self.assertRaisesRegex(runtime.SharedRuntimeError, '链接'):
            runtime.read_group(self.data, self.ref)

    def test_live_reference_keeps_provider(self):
        prefix = 'UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/umi-plugin.json'
        manifest = self.root / prefix
        manifest.parent.mkdir(parents=True)
        manifest.write_bytes(runtime.canonical_json({'runtime': {'shared_runtime': self.binding}}))
        files = {path.relative_to(self.root).as_posix(): projection.row(path)['sha256']
                 for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(fixed._shared_ownership(self.root, self.root, {}, {}, files), set(files) - {prefix})
        self.assertEqual(fixed._shared_ownership(self.root, self.root, {}, {prefix: files[prefix]}, files), set())
        same_digest_file = next(name for name in files if name.endswith('/six.py'))
        with self.assertRaisesRegex(ValueError, '不在原内容地址下覆盖'):
            fixed._shared_ownership(self.root, self.root, {same_digest_file: 'a' * 64}, {}, files)

    def test_original_record_difference_is_narrow(self):
        name = 'numpy-2.3.5.dist-info/RECORD'
        raw = b'../../bin/f2py.exe,sha256=A,1\nmodule.py,sha256=Z,1\n'
        good = raw.replace(b'sha256=A', b'sha256=B')
        bad = raw.replace(b'sha256=Z', b'sha256=B')

        class View:
            def files(self):
                return ('vendor/module.py',)

        receiver = lambda content: projection.matched({name: raw}, {'numpy': (name, raw)},
                                                        {name: content}, {'numpy': (name, content)}, View())
        self.assertEqual(receiver(good)[name]['unshippedEntryPoints'], ['../../bin/f2py.exe'])
        with self.assertRaises(ValueError):
            receiver(bad)


if __name__ == '__main__':
    unittest.main(verbosity=2)
