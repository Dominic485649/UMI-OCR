"""MSVC编译包含路径包装器的参数保持与Windows路径边界。"""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('tested_msvc_path_wrapper', ROOT / 'build/tools/normalize_msvc_paths.py')
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)


class MsvcIncludePathTests(unittest.TestCase):
    def test_relative_and_absolute_attached_include_paths(self):
        self.assertEqual(W.normalize(['/I../src', '-Igen', '/IC:/sdk/include'], 'E:/work/build'),
                         ['/IE:\\work\\src', '-IE:\\work\\build\\gen', '/IC:\\sdk\\include'])

    def test_separate_include_and_spaces_are_preserved_as_single_arguments(self):
        self.assertEqual(W.normalize(['/I', '../source with spaces', '-I', 'C:/Program Files/SDK'], 'E:/work/build'),
                         ['/I', 'E:\\work\\source with spaces', '-I', 'C:\\Program Files\\SDK'])

    def test_all_nonpath_flags_are_unchanged(self):
        original = ['/c', '/DNAME=../value', '/std:c++20', '/MD', '/Yuoriginal_header.h', '/showIncludes', '@compile.rsp']
        self.assertEqual(W.normalize(original, 'E:/work/build'), original)

    def test_source_object_pdb_and_pch_paths_are_normalized(self):
        self.assertEqual(W.normalize(['../src/main.cc', '/Foobj/x.obj', '/Fdobj/x.pdb', '/Fpobj/pre.pch'], 'E:/work/build'),
                         ['E:\\work\\src\\main.cc', '/FoE:\\work\\build\\obj\\x.obj', '/FdE:\\work\\build\\obj\\x.pdb', '/FpE:\\work\\build\\obj\\pre.pch'])

    def test_forced_include_and_pch_header_tokens_keep_include_search_semantics(self):
        original = ['/FIbuild/precompile.h', '/FI', 'build/precompile.h', '/FI', 'forced_source.cc', '/Yubuild/precompile.h', '/Ycbuild/precompile.h']
        self.assertEqual(W.normalize(original, 'E:/work/build'), original)

    def test_absolute_source_and_separate_output_paths(self):
        self.assertEqual(W.normalize(['C:/source tree/main.cpp', '/Fo', 'obj/main.obj'], 'E:/work/build'),
                         ['C:\\source tree\\main.cpp', '/Fo', 'E:\\work\\build\\obj\\main.obj'])

    def test_localized_include_prefix_preserves_utf8_path_and_whitespace(self):
        path = '  E:\\源码\\头文件.h\r\n'.encode('utf-8')
        self.assertEqual(W.dependency_output('注意: 包含文件:'.encode('utf-8') + path), b'Note: including file:' + path)

    def test_localized_include_prefix_preserves_gbk_bytes(self):
        line = '注意: 包含文件:  E:\\SDK\\header.h\r\n'.encode('gbk')
        self.assertEqual(W.dependency_output(line), b'Note: including file:  E:\\SDK\\header.h\r\n')

    def test_error_and_unrelated_output_are_not_hidden_or_translated(self):
        for line in (b'Note: including file: E:\\x.h\n', 'file.cc: fatal error C1083: 无法打开文件\r\n'.encode('utf-8'), b'plain output\r\n'):
            self.assertEqual(W.dependency_output(line), line)

    def test_missing_separate_include_value_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '缺少路径'):
            W.normalize(['/c', 'x.cc', '/I'], 'E:/work/build')


if __name__ == '__main__':
    unittest.main(verbosity=2)
