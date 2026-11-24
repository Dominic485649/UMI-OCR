"""Exercise the real DevTools GN block in tiny inert graphs, never a second Qt build."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import unittest

OPTIONS = None
MOJOM = '//extensions/common:mojom'
GUARD = '  if (enable_extensions_core) {\n    deps += [ "//extensions/common:mojom" ]\n  }\n'


def block(text):
    start = text.index('source_set("devtools_sources") {')
    opening = text.index('{', start)
    depth = 0
    for pos in range(opening, len(text)):
        depth += (text[pos] == '{') - (text[pos] == '}')
        if depth == 0:
            return text[start:pos + 1]
    raise ValueError('Unclosed DevTools source_set')


def members(text, field):
    match = re.search(r'\b' + field + r'\s*=\s*\[([^]]*)\]', text)
    if not match:
        raise ValueError('Missing ' + field)
    return re.findall(r'"([^"\n]+)"', match.group(1))


def write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as output:
        output.write(text)


def fixture(name, source_block, enabled):
    root = OPTIONS.work_dir / name
    root.mkdir(parents=True, exist_ok=False)
    write(root, '.gn', 'buildconfig = "//build/config.gn"\n')
    write(root, 'build/config.gn', 'declare_args() { enable_extensions_core = false }\n'
          'set_default_toolchain("//toolchain:default")\n'
          'set_defaults("source_set") { configs = [] }\n')
    write(root, 'toolchain/BUILD.gn', 'toolchain("default") {\n'
          '  tool("cxx") {\n    command = "echo {{source}}"\n'
          '    outputs = [ "{{target_out_dir}}/{{source_name_part}}.obj" ]\n  }\n'
          '  tool("stamp") { command = "echo {{output}}" }\n}\n')
    write(root, 'BUILD.gn', 'config("cpp20_config") {}\n' + source_block + '\n'
          'group("default") { deps = [ ":devtools_sources" ] }\n')
    for dep in members(OPTIONS.original_text_block, 'deps'):
        directory, sep, target = dep[2:].partition(':')
        target = target if sep else directory.rsplit('/', 1)[-1]
        content = ('assert(enable_extensions_core)\n' if dep == MOJOM else '')
        write(root, directory + '/BUILD.gn', content + 'group("' + target + '") {}\n')
    for source in members(source_block, 'sources'):
        # Empty placeholders exist only in this synthetic graph; no C++ is compiled.
        write(root, source[2:], '// Inert GN fixture; not the Chromium implementation.\n')
    commands = [
        [str(OPTIONS.gn), 'gen', str(root / 'out'), '--root=' + str(root),
         '--args=enable_extensions_core=' + str(enabled).lower(), '--fail-on-unused-args'],
        [str(OPTIONS.gn), 'desc', str(root / 'out'), '//:devtools_sources',
         '--root=' + str(root), '--format=json', '--fail-on-unused-args'],
    ]
    record = []
    for index, command in enumerate(commands):
        result = subprocess.run(command, cwd=str(OPTIONS.work_dir), capture_output=True,
                                text=True, encoding='utf-8', errors='strict')
        write(root, 'command-' + str(index) + '.json', json.dumps(command, indent=2))
        write(root, 'stdout-' + str(index) + '.log', result.stdout)
        write(root, 'stderr-' + str(index) + '.log', result.stderr)
        record.append({'command': command, 'returncode': result.returncode})
        if result.returncode:
            raise RuntimeError(name + ': ' + result.stdout + result.stderr)
    write(root, 'commands-result.json', json.dumps(record, indent=2))
    return json.loads(result.stdout)['//:devtools_sources']


class DevtoolsGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if OPTIONS is None:
            raise unittest.SkipTest('Supply reviewed templates, GN executable and fresh fixture directory')
        cls.original = OPTIONS.original.read_bytes().decode('utf-8')
        cls.patched = OPTIONS.patched.read_bytes().decode('utf-8')
        cls.before = block(cls.original)
        cls.after = block(cls.patched)
        OPTIONS.original_text_block = cls.before
        OPTIONS.work_dir.mkdir(parents=True, exist_ok=False)
        cls.old_enabled = fixture('original-enabled', cls.before, True)
        cls.new_enabled = fixture('patched-enabled', cls.after, True)
        cls.new_disabled = fixture('patched-disabled', cls.after, False)

    def test_only_the_reviewed_dependency_is_conditioned(self):
        expected = self.before.replace('    "//extensions/common:mojom",\n', '', 1)
        expected = expected.replace('  sources = [\n', GUARD + '  sources = [\n', 1)
        self.assertEqual(self.original.replace(self.before, expected, 1), self.patched)

    def test_existing_feature_import_is_unchanged(self):
        marker = 'import("//extensions/buildflags/buildflags.gni")'
        self.assertGreater(self.original.count(marker), 0)
        self.assertEqual(self.original.count(marker), self.patched.count(marker))

    def test_all_eighteen_devtools_sources_are_preserved(self):
        self.assertEqual(len(members(self.before, 'sources')), 18)
        self.assertEqual(members(self.before, 'sources'), members(self.after, 'sources'))

    def test_enabled_branch_retains_original_dependencies(self):
        self.assertIn(MOJOM, self.new_enabled['deps'])
        self.assertEqual(self.old_enabled['deps'], self.new_enabled['deps'])
        self.assertEqual(self.old_enabled['configs'], self.new_enabled['configs'])

    def test_disabled_branch_removes_only_extension_mojom(self):
        self.assertNotIn(MOJOM, self.new_disabled['deps'])
        self.assertEqual(sorted(self.new_disabled['deps']),
                         sorted(x for x in self.old_enabled['deps'] if x != MOJOM))
        self.assertEqual(self.new_disabled['configs'], self.old_enabled['configs'])

    def test_both_branches_retain_devtools_sources(self):
        # GN emits source-root-relative labels, stable across these separate fixture roots.
        self.assertEqual(self.old_enabled['sources'], self.new_enabled['sources'])
        self.assertEqual(self.old_enabled['sources'], self.new_disabled['sources'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for option in ['original', 'patched', 'gn', 'work-dir']:
        parser.add_argument('--' + option, type=Path, required=True)
    OPTIONS, remaining = parser.parse_known_args()
    for option in ['original', 'patched', 'gn', 'work_dir']:
        setattr(OPTIONS, option, getattr(OPTIONS, option).resolve())
    unittest.main(argv=[__file__] + remaining)
