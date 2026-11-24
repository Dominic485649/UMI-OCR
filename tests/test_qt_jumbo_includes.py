"""Focused tests for the supplied patched Chromium jumbo generator; no Qt launch."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = None


class JumboIncludePathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if GENERATOR is None:
            raise unittest.SkipTest('Pass --generator with the reviewed patched source file')
        spec = importlib.util.spec_from_file_location('_tested_qt_jumbo_generator', GENERATOR)
        cls.J = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.J)

    def test_short_relative_include_is_unchanged(self):
        with mock.patch.object(self.J.os, 'getcwd', return_value='E:\\short'):
            self.assertEqual(self.J.include_path('../source/file.cc'), '../source/file.cc')

    def test_long_relative_include_becomes_same_canonical_file(self):
        cwd = 'E:\\' + '\\'.join(['nested' * 8] * 4)
        token = '../../../../source/' + 'long_' * 12 + '.cc'
        expected = os.path.normpath(os.path.join(cwd, token)).replace('\\', '/')
        self.assertGreaterEqual(len(os.path.join(cwd, token)), 260)
        with mock.patch.object(self.J.os, 'getcwd', return_value=cwd):
            self.assertEqual(self.J.include_path(token), expected)

    def test_boundary_259_keeps_relative_260_normalizes(self):
        cwd = 'E:\\build'
        base = '../source/'
        short = base + 'x' * (259 - len(os.path.join(cwd, base)))
        long = short + 'x'
        with mock.patch.object(self.J.os, 'getcwd', return_value=cwd):
            self.assertEqual(self.J.include_path(short), short)
            self.assertEqual(self.J.include_path(long), os.path.normpath(os.path.join(cwd, long)).replace('\\', '/'))

    def test_other_platform_preserves_original_tokens(self):
        token = '../' * 100 + 'file.cc'
        with mock.patch.object(self.J.os, 'name', 'posix'):
            self.assertEqual(self.J.include_path(token), token)

    def test_normalized_absolute_include_does_not_change(self):
        token = 'E:/source/file.cc'
        self.assertEqual(self.J.include_path(token), token)

    def test_chunks_and_original_input_identity_are_preserved(self):
        with tempfile.TemporaryDirectory(prefix='qt-jumbo-unit-', dir=ROOT / 'build/tmp') as temporary:
            outputs = [str(Path(temporary) / ('unit_' + str(i) + '.cc')) for i in range(2)]
            cwd = 'E:\\' + '\\'.join(['nested' * 8] * 4)
            inputs = ['../../../../source/' + 'long_' * 12 + str(i) + '.cc' for i in range(8)]
            expected_stops = self.J.generate_chunk_stops(inputs, len(outputs), True)
            used_inputs, used_outputs = set(), set()
            with mock.patch.object(self.J.os, 'getcwd', return_value=cwd):
                self.J.write_jumbo_files(inputs, outputs, used_inputs, used_outputs)
            self.assertEqual(used_inputs, set(inputs))
            self.assertEqual(used_outputs, set(outputs))
            start = 0
            for output, stop in zip(outputs, expected_stops):
                emitted = re.findall(r'^#include "([^"]+)"$', Path(output).read_text(), re.M)
                expected = [os.path.normpath(os.path.join(cwd, name)).replace('\\', '/') for name in inputs[start:stop]]
                self.assertEqual(emitted, expected)
                start = stop
            mtimes = [Path(output).stat().st_mtime_ns for output in outputs]
            with mock.patch.object(self.J.os, 'getcwd', return_value=cwd):
                self.J.write_jumbo_files(inputs, outputs, set(), set())
            self.assertEqual([Path(output).stat().st_mtime_ns for output in outputs], mtimes)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--generator', type=Path, required=True)
    options, remaining = parser.parse_known_args()
    GENERATOR = options.generator.resolve(strict=True)
    unittest.main(argv=[__file__, *remaining], verbosity=2)
