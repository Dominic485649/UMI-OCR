"""Execute real host-build AST branches on inert Qt fixtures; never build or load Qt."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest import mock

QT_TMP = Path(__file__).resolve().parents[1] / 'build/audit/dependency-trim-20261116-pip-r1/tmp'

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / 'build/windows/Build-Release.ps1'
PWSH = shutil.which('pwsh')
spec = importlib.util.spec_from_file_location('_host_qt_fixtures', ROOT / 'tests/test_project_derived_qt.py')
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)

PROBE = r'''
param([string]$Source, [string]$Config, [string]$Mode)
$ErrorActionPreference = 'Stop'
$cfg = Get-Content -Raw -LiteralPath $Config | ConvertFrom-Json
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Actual host build script did not parse.' }
function Find-Root([string]$Pattern) {
    $found=@($ast.EndBlock.Statements | Where-Object { $_.Extent.Text -match $Pattern })
    if ($found.Count -ne 1) { throw "Expected one actual root statement: $Pattern; got $($found.Count)" }
    return $found[0].Extent.Text
}
foreach ($name in @('Resolve-BuildPath','Remove-BuildTree')) {
    $definitions=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$false))
    if ($definitions.Count -ne 1) { throw 'Expected actual build helper.' }
    . ([scriptblock]::Create($definitions[0].Extent.Text))
}
$RepoRoot=$cfg.repo
$StagingRoot=$cfg.stage
$DataRoot=Join-Path $StagingRoot 'UmiOCR-data'
$SitePackages=Join-Path $DataRoot 'site-packages'
$DerivedQtBundle=$cfg.bundle
$DerivedQtLock=$cfg.lock
$OfficialQtWheelhouse=$cfg.wheelhouse
$OfficialQtReuseReceipt=$cfg.reuseReceipt
$UseOfficialQt=-not [string]::IsNullOrWhiteSpace($OfficialQtWheelhouse)
$ReuseDependencies=[bool]$cfg.reuse
$ReuseFromStagingRoot=$cfg.seed
$seedData=Join-Path $ReuseFromStagingRoot 'UmiOCR-data'
$projectionTarget=$cfg.source
$projectionAudit=$cfg.audit
$python=$cfg.python
. ([scriptblock]::Create((Find-Root '^\$UseDerivedQt\s*=')))
. ([scriptblock]::Create((Find-Root '^if\s*\(\$UseDerivedQt -xor ')))
if ($Mode -eq 'paths') {
    . ([scriptblock]::Create((Find-Root '(?s)^if \(\$UseDerivedQt\).*\$DerivedQtBundle = Resolve-BuildPath')))
} elseif ($Mode -eq 'reuse') {
    . ([scriptblock]::Create((Find-Root '^if \(\$ReuseDependencies\)')))
    $seedBranch=@($ast.FindAll({param($node) $node -is [Management.Automation.Language.IfStatementAst] -and
        $node.Extent.Text -match '(?s)^if \(-not \$UseDerivedQt -and -not \$UseOfficialQt\).*\$seedQtManifest ='},$false))
    if ($seedBranch.Count -ne 1) { throw 'Expected the actual conditional seed manifest copy.' }
    . ([scriptblock]::Create($seedBranch[0].Extent.Text))
} elseif ($Mode -eq 'target') {
    . ([scriptblock]::Create((Find-Root '^\$projectionTarget\s*=')))
} elseif ($Mode -eq 'project') {
    . ([scriptblock]::Create((Find-Root '(?s)^if \(\$UseDerivedQt\).*project_derived_qt\.py')))
} elseif ($Mode -eq 'official-project') {
    . ([scriptblock]::Create((Find-Root '(?s)^if \(\$UseOfficialQt\).*official_qt_projection\.py.*extract')))
} elseif ($Mode -in @('qt-selection','qt-version')) {
    . ([scriptblock]::Create((Find-Root '^\$qtManifest\s*=')))
    if ($Mode -eq 'qt-selection') {
        . ([scriptblock]::Create((Find-Root '^\$qmlScanner\s*=')))
        . ([scriptblock]::Create((Find-Root '(?s)^if \(\$UseDerivedQt\).*Derived Qt projection binding changed')))
    } else {
        . ([scriptblock]::Create((Find-Root '^\$qtPolicy\s*=')))
        . ([scriptblock]::Create((Find-Root '^\$qtRecord\s*=')))
        . ([scriptblock]::Create((Find-Root '(?s)^if \(\$UseDerivedQt\).*Derived Qt manifest version does not match')))
    }
} elseif ($Mode -ne 'pair') { throw 'Unexpected mode.' }
$result=@{useDerived=$UseDerivedQt;projectionTarget=$projectionTarget;manifestExists=(Test-Path -LiteralPath (Join-Path $DataRoot 'qt-runtime-whitelist.json'))}
Write-Output ('PROBE_RESULT=' + (ConvertTo-Json -InputObject $result -Compress))
'''


@unittest.skipUnless(os.name == 'nt' and PWSH, 'Windows and PowerShell 7 required')
class HostBuildDerivedQtTests(unittest.TestCase):
    def setUp(self):
        self.fixture = F.DerivedQtProjectionTests()
        QT_TMP.mkdir(parents=True, exist_ok=True)
        temp_factory = F.tempfile.TemporaryDirectory
        with mock.patch.object(F.tempfile, 'TemporaryDirectory', side_effect=lambda **kw: temp_factory(prefix=kw['prefix'], dir=QT_TMP)):
            self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.source = self.fixture.source()
        self.stage = self.root / 'new-host-stage'
        self.data = self.stage / 'UmiOCR-data'
        self.data.mkdir(parents=True)
        self.site = self.data / 'site-packages'
        self.manifest = self.data / 'qt-runtime-whitelist.json'
        self.audit = self.root / 'build-audit'
        self.audit.mkdir()
        self.seed = self.root / 'readonly-seed'
        seed_data = self.seed / 'UmiOCR-data'
        (seed_data / 'runtime').mkdir(parents=True)
        (seed_data / 'runtime/python.exe').write_bytes(b'INERT_NOT_EXECUTABLE')
        (seed_data / 'site-packages').mkdir()
        self.old_manifest = seed_data / 'qt-runtime-whitelist.json'
        self.old_manifest.write_bytes(b'OLD_SEED_MANIFEST_NOT_DERIVED\n')
        self.driver = self.root / 'probe.ps1'
        self.driver.write_text(PROBE, encoding='utf-8')
        self.config = {'repo': str(ROOT), 'stage': str(self.stage), 'bundle': str(self.fixture.bundle),
                       'lock': str(self.fixture.lock), 'reuse': True, 'seed': str(self.seed),
                       'source': str(self.source), 'audit': str(self.audit), 'python': sys.executable}

    def run_probe(self, mode, success=True, **changes):
        inputs = self.root / 'probe-inputs.json'
        inputs.write_text(json.dumps(dict(self.config, **changes)), encoding='utf-8')
        completed = subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-File', str(self.driver),
                                    '-Source', str(BUILDER), '-Config', str(inputs), '-Mode', mode],
                                   cwd=ROOT, capture_output=True, encoding='utf-8', timeout=90)
        if success:
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            rows = [line.removeprefix('PROBE_RESULT=') for line in completed.stdout.splitlines() if line.startswith('PROBE_RESULT=')]
            self.assertEqual(len(rows), 1, completed.stdout)
            return json.loads(rows[0])
        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn('ParserError', completed.stdout + completed.stderr)
        return completed.stdout + completed.stderr

    def test_absent_pair_preserves_default_and_lone_parameter_rejects_before_build(self):
        for empty in ('', '   '):
            self.assertFalse(self.run_probe('pair', bundle=empty, lock=empty)['useDerived'])
        untouched = self.root / 'must-not-create'
        for option, value in (('-DerivedQtBundle', self.fixture.bundle), ('-DerivedQtLock', self.fixture.lock)):
            completed = subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-File', str(BUILDER),
                                        '-StagingRoot', str(untouched), '-SkipArchive', option, str(value)],
                                       cwd=ROOT, capture_output=True, encoding='utf-8', timeout=30)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn('Provide -DerivedQtBundle and -DerivedQtLock together', completed.stdout + completed.stderr)
            self.assertFalse(untouched.exists())

    def test_paired_paths_use_existing_plain_path_guards(self):
        self.assertTrue(self.run_probe('paths')['useDerived'])
        self.assertIn('Derived Qt input does not exist', self.run_probe('paths', success=False, bundle=str(self.root / 'missing.zip')))
        self.assertIn('Network/device', self.run_probe('paths', success=False, bundle='\\\\server\\share\\bundle.zip'))
        self.assertFalse(self.site.exists())

    def test_derived_reuse_does_not_require_or_copy_old_manifest(self):
        before = self.old_manifest.read_bytes()
        self.assertFalse(self.run_probe('reuse')['manifestExists'])
        self.assertEqual(self.old_manifest.read_bytes(), before)
        self.old_manifest.unlink()  # Only this test's inert, owned fixture.
        self.assertFalse(self.run_probe('reuse')['manifestExists'])

    def test_legacy_reuse_keeps_manifest_requirement_and_original_bytes(self):
        self.assertTrue(self.run_probe('reuse', bundle='', lock='')['manifestExists'])
        self.assertEqual(self.manifest.read_bytes(), self.old_manifest.read_bytes())
        self.old_manifest.unlink()
        self.assertIn('Offline reuse input is missing', self.run_probe('reuse', success=False, bundle='', lock=''))

    def test_projection_target_is_intermediate_only_when_needed(self):
        for reuse in (False, True):
            for derived in (False, True):
                values = {} if derived else {'bundle': '', 'lock': ''}
                observed = self.run_probe('target', reuse=reuse, **values)
                expected = self.site if reuse and not derived else self.stage / '.build/projected-site-packages'
                self.assertEqual(Path(observed['projectionTarget']), expected)

    def assert_actual_projection(self, reuse):
        before = {name: F.Q.L.sha256_file(path) for name, path in F.Q.L.tree_files(self.source).items()}
        if not reuse:
            self.site.mkdir()
            (self.site / 'old-pip-site.txt').write_bytes(b'Owned disposable fresh-staging input')
        self.run_probe('project', reuse=reuse)
        record = json.loads((self.audit / 'derived-qt-result.json').read_text('utf-8'))
        self.assertEqual(record['status'], 'PROJECTED_VERIFIED_NOT_APP_ACCEPTED')
        self.assertEqual(Path(record['destination']), self.site)
        self.assertEqual(record['runtimeAcceptance'], 'NOT_RUN')
        self.assertFalse(record['publicReleaseAllowed'])
        self.assertEqual(self.manifest.read_bytes(), self.fixture.payload[F.Q.RUNTIME])
        self.assertFalse((self.site / 'PySide6/old-unused.pyd').exists())
        self.assertEqual((self.site / 'sample/value.py').read_bytes(), b'VALUE = 42\n')
        self.assertFalse((self.site / 'old-pip-site.txt').exists())
        self.assertEqual(before, {name: F.Q.L.sha256_file(path) for name, path in F.Q.L.tree_files(self.source).items()})
        self.run_probe('qt-selection', reuse=reuse)
        self.run_probe('qt-version', reuse=reuse)
        self.assertEqual(self.manifest.read_bytes(), self.fixture.payload[F.Q.RUNTIME])
        self.assertEqual(self.old_manifest.read_bytes(), b'OLD_SEED_MANIFEST_NOT_DERIVED\n')

    def test_real_projector_handles_reused_dependencies_without_old_qt(self):
        self.assert_actual_projection(True)

    def test_real_projector_replaces_only_fresh_pip_site(self):
        self.assert_actual_projection(False)

    def test_invalid_bundle_fails_without_fallback_or_seed_mutation(self):
        before = F.Q.L.sha256_file(self.source / 'PySide6/old-unused.pyd')
        self.run_probe('reuse')
        with self.fixture.bundle.open('ab') as stream:
            stream.write(b'INVALID_TRAILING_BYTES')
        self.assertIn('Derived Qt projection failed', self.run_probe('project', success=False))
        self.assertFalse(self.manifest.exists())
        self.assertFalse(self.site.exists())
        self.assertEqual(F.Q.L.sha256_file(self.source / 'PySide6/old-unused.pyd'), before)
        self.assertEqual(json.loads((self.audit / 'derived-qt-result.json').read_text())['status'], 'FAILED')

    def test_real_profile_gate_rejects_rehashed_unbound_source_marker(self):
        key = next(name for name in self.fixture.payload if name.endswith('/' + F.Q.PROFILE))
        marker = json.loads(self.fixture.payload[key])
        marker['inputRecords']['source'] = 'c' * 64
        self.fixture.payload[key] = F.encoded(marker)
        self.fixture.rebuild_records()
        self.fixture.write_bundle()
        self.assertIn('Derived Qt projection failed', self.run_probe('project', success=False))
        self.assertFalse(self.manifest.exists())
        self.assertFalse(self.site.exists())

    def test_post_projection_manifest_tampering_is_not_legacy_reuse(self):
        self.run_probe('project')
        changed = b'{"qtVersion":"6.11.2"}\n'
        self.manifest.write_bytes(changed)
        self.assertIn('refuse a stale Qt manifest', self.run_probe('qt-selection', success=False))
        self.assertEqual(self.manifest.read_bytes(), changed)

    def test_mismatched_derived_version_is_not_silently_rewritten(self):
        changed = b'{"qtVersion":"0.0.0"}\n'
        self.manifest.write_bytes(changed)
        self.assertIn('manifest version does not match', self.run_probe('qt-version', success=False))
        self.assertEqual(self.manifest.read_bytes(), changed)

    def test_derived_inputs_do_not_bypass_formal_release_gate(self):
        untouched = self.root / 'no-formal-build'
        completed = subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-File', str(BUILDER),
                                    '-StagingRoot', str(untouched), '-DerivedQtBundle', str(self.fixture.bundle),
                                    '-DerivedQtLock', str(self.fixture.lock)],
                                   cwd=ROOT, capture_output=True, encoding='utf-8', timeout=30)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn('Formal archives require an explicit -ReleaseGates', completed.stdout + completed.stderr)
        self.assertFalse(untouched.exists())


    def official_fixture(self):
        spec = importlib.util.spec_from_file_location('_official_qt_fixture', ROOT / 'tests/test_official_qt_projection.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fixture = module.OfficialQtProjectionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        repo = fixture.root / 'inert-repo'
        for relative in ('build/tools/official_qt_projection.py',):
            target = repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        for source, relative in ((fixture.lock, 'build/requirements-base-windows.lock'),
                                 (fixture.policy, 'build/qt-runtime-whitelist.json'),
                                 (fixture.trim, 'build/windows/Trim-Qt.ps1')):
            target = repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        fixture.lock = repo / 'build/requirements-base-windows.lock'
        fixture.policy = repo / 'build/qt-runtime-whitelist.json'
        fixture.trim = repo / 'build/windows/Trim-Qt.ps1'
        fixture.receipt = repo / 'build/audit/official-qt-result.json'
        fixture.site = self.site
        fixture.manifest = self.manifest
        shutil.copytree(fixture.qml, self.data / 'qt_res/qml')
        fixture.qml = self.data / 'qt_res/qml'
        self.config.update(repo=str(repo), bundle='', lock='', wheelhouse='', reuseReceipt=str(fixture.receipt))
        return fixture

    def test_official_parameter_is_exclusive_before_build(self):
        untouched = self.root / 'never-start'
        completed = subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-File', str(BUILDER),
                                    '-StagingRoot', str(untouched), '-SkipArchive',
                                    '-DerivedQtBundle', str(self.fixture.bundle), '-DerivedQtLock', str(self.fixture.lock),
                                    '-OfficialQtWheelhouse', str(self.root)], cwd=ROOT, capture_output=True, encoding='utf-8', timeout=30)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn('mutually exclusive', completed.stdout + completed.stderr)
        self.assertFalse(untouched.exists())

    def test_official_reuse_needs_no_old_manifest_and_does_not_copy_it(self):
        self.old_manifest.unlink()
        observed = self.run_probe('reuse', bundle='', lock='', wheelhouse=str(self.root))
        self.assertFalse(observed['manifestExists'])

    def test_official_extraction_replaces_only_new_candidate_qt(self):
        fixture = self.official_fixture()
        self.site.mkdir()
        (self.site / 'sample').mkdir()
        (self.site / 'sample/unchanged.txt').write_bytes(b'unrelated')
        for name in ('PySide6', 'shiboken6', 'pyside6-0.0.0.dist-info'):
            (self.site / name).mkdir()
            (self.site / name / 'old.txt').write_bytes(b'old candidate fixture')
        self.run_probe('official-project', wheelhouse=str(fixture.wheels))
        self.assertEqual((self.site / 'sample/unchanged.txt').read_bytes(), b'unrelated')
        self.assertFalse((self.site / 'pyside6-0.0.0.dist-info').exists())
        self.assertTrue((self.site / 'PySide6/qmlimportscanner.exe').is_file())
        record = json.loads((self.audit / 'official-qt-input.json').read_bytes())
        self.assertEqual(len(record['wheels']), 4)
        self.assertEqual((self.site / 'pyside6-6.11.2.dist-info/RECORD').read_bytes(),
                         fixture.payloads['pyside6']['pyside6-6.11.2.dist-info/RECORD'])
        self.assertEqual(self.old_manifest.read_bytes(), b'OLD_SEED_MANIFEST_NOT_DERIVED\n')

    def test_full_scanner_cannot_generate_unbound_success_manifest(self):
        self.site.mkdir()
        (self.site / 'PySide6').mkdir()
        (self.site / 'PySide6/qmlimportscanner.exe').write_bytes(b'INERT NEVER EXECUTED')
        self.assertIn('provide -OfficialQtWheelhouse', self.run_probe('qt-selection', success=False, bundle='', lock=''))
        self.assertFalse(self.manifest.exists())

    def test_legacy_manifest_rejected_and_new_manifest_reused_without_wheelhouse(self):
        fixture = self.official_fixture()
        fixture.trimmed()
        before = self.manifest.read_bytes()
        self.assertIn('provide -OfficialQtWheelhouse', self.run_probe('qt-selection', success=False))
        self.assertEqual(self.manifest.read_bytes(), before)
        fixture.seal()
        before = self.manifest.read_bytes()
        self.run_probe('qt-selection')
        self.run_probe('qt-version')
        self.assertEqual(self.manifest.read_bytes(), before)
        result = json.loads((self.audit / 'official-qt-reuse-result.json').read_bytes())
        self.assertEqual(result['status'], 'REUSE_VERIFIED_NOT_APP_ACCEPTED')


if __name__ == '__main__':
    unittest.main(verbosity=2)
