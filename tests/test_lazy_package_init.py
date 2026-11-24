"""纯导出初始化器的严格转换和实际惰性导入边界。"""
import argparse
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('tested_lazy_init', ROOT / 'build/tools/lazy_package_init.py')
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)
WORK = ROOT / 'build/tmp/dependency-trim-20261114-r1/unit'


class LazyInitTests(unittest.TestCase):
    def test_preserves_license_alias_identity_and_all_without_eager_children(self):
        source = '\"\"\"公开导出。\"\"\"\n# SPDX-License-Identifier: BSD-3-Clause\nfrom .small import Keep as Alias\nfrom .heavy import Heavy\nfrom . import child\n__all__ = ["Alias", "Heavy", "child"]\n'
        derived, record = L.derive_lazy_init(source)
        self.assertIn('# SPDX-License-Identifier: BSD-3-Clause', derived)
        self.assertEqual(record['exports'], ['Alias', 'Heavy', 'child'])
        with tempfile.TemporaryDirectory(dir=WORK) as folder:
            package = Path(folder) / 'sample'
            package.mkdir()
            (package / '__init__.py').write_text(derived, encoding='utf-8')
            (package / 'small.py').write_text('class Keep: pass\n', encoding='utf-8')
            (package / 'heavy.py').write_text('raise RuntimeError("unused child loaded")\n', encoding='utf-8')
            (package / 'child.py').write_text('value = 42\n', encoding='utf-8')
            name = 'umi_lazy_fixture'
            try:
                spec = importlib.util.spec_from_file_location(name, package / '__init__.py')
                module = importlib.util.module_from_spec(spec)
                sys.modules[name] = module
                spec.loader.exec_module(module)
                self.assertNotIn(name + '.small', sys.modules)
                self.assertNotIn(name + '.heavy', sys.modules)
                self.assertIn('Alias', dir(module))
                value = module.Alias
                self.assertIs(value, sys.modules[name + '.small'].Keep)
                self.assertIs(module.Alias, value)
                self.assertEqual(module.child.value, 42)
                with self.assertRaises(AttributeError):
                    module.missing
                with self.assertRaisesRegex(RuntimeError, 'unused child loaded'):
                    module.Heavy
            finally:
                for key in list(sys.modules):
                    if key == name or key.startswith(name + '.'):
                        del sys.modules[key]

    def test_rejects_initialization_side_effects(self):
        with self.assertRaisesRegex(ValueError, '副作用'):
            L.derive_lazy_init('from .a import A\nsetup_registry()\n__all__=["A"]\n')

    def test_rejects_absolute_and_future_imports(self):
        for source in ('from x import A\n__all__=["A"]\n', 'from __future__ import annotations\nfrom .a import A\n__all__=["A"]\n'):
            with self.assertRaises(ValueError):
                L.derive_lazy_init(source)

    def test_rejects_star_exports_and_duplicates(self):
        for source in ('from .a import *\n__all__=[]\n', 'from .a import A\nfrom .b import A\n__all__=["A"]\n'):
            with self.assertRaises(ValueError):
                L.derive_lazy_init(source)

    def test_rejects_dynamic_or_unbound_public_exports(self):
        for source in ('from .a import A\n__all__=get_exports()\n', 'from .a import A\n__all__=["B"]\n', 'from .a import A\n__all__=["A","A"]\n'):
            with self.assertRaises(ValueError):
                L.derive_lazy_init(source)

    def test_rejects_auxiliary_namespace_collisions(self):
        with self.assertRaises(ValueError):
            L.derive_lazy_init('from .a import A as _umi_exports\n__all__=["_umi_exports"]\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--work', type=Path, default=WORK)
    args, remaining = parser.parse_known_args()
    WORK = args.work.resolve(strict=True)
    unittest.main(argv=[sys.argv[0], *remaining])
