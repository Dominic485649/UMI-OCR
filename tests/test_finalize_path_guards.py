"""执行实际PowerShell路径函数和GPU默认分支；不构建、不访问网络或执行解释器。"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")
SCRIPTS = (
    ("Build-Release.ps1", "Resolve-BuildPath"),
    ("Build-GpuPlugin.ps1", "Resolve-BuildPath"),
    ("Finalize-Release.ps1", "Resolve-PlainPath"),
)
PROBE = r'''
param([string]$Source, [string]$FunctionName, [string]$FixtureRoot, [string]$Cases, [string]$Mode)
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Source, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'PowerShell source did not parse.' }
$definitions = @($ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $FunctionName }, $false))
if ($definitions.Count -ne 1) { throw 'Expected exactly one actual path function.' }
. ([scriptblock]::Create($definitions[0].Extent.Text))
$RepoRoot = $FixtureRoot
$global:ProbeCount = 0
$global:BlockedPath = ''
function Get-Item {
    [CmdletBinding()]
    param([string]$LiteralPath, [switch]$Force)
    $global:ProbeCount++
    $attributes = if ($LiteralPath -eq $global:BlockedPath) { [IO.FileAttributes]::ReparsePoint } else { [IO.FileAttributes]::Directory }
    [pscustomobject]@{ Attributes = $attributes }
}
$results = @()
if ($Mode -eq 'paths') {
    $inputs = Get-Content -LiteralPath $Cases -Raw -Encoding utf8 | ConvertFrom-Json -NoEnumerate
    foreach ($path in $inputs) {
        $global:ProbeCount = 0
        try {
            $value = & $FunctionName $path
            $results += [pscustomobject]@{ path=$path; accepted=$true; value=$value; probes=$global:ProbeCount; error=$null }
        } catch {
            $results += [pscustomobject]@{ path=$path; accepted=$false; value=$null; probes=$global:ProbeCount; error=$_.Exception.Message }
        }
    }
} elseif ($Mode -eq 'lexical-link') {
    $global:BlockedPath = Join-Path $FixtureRoot 'blocked'
    try {
        $value = & $FunctionName (Join-Path $global:BlockedPath '../leaf')
        $results += [pscustomobject]@{ accepted=$true; value=$value; error=$null }
    } catch { $results += [pscustomobject]@{ accepted=$false; value=$null; error=$_.Exception.Message } }
} elseif ($Mode -in @('gpu-default', 'gpu-explicit', 'gpu-runtime-child')) {
    if ($Mode -eq 'gpu-runtime-child') {
        $BaseStagingRoot = Join-Path $FixtureRoot 'plain-base'
        $global:BlockedPath = Join-Path $BaseStagingRoot 'UmiOCR-data/runtime'
        $statements = @($ast.EndBlock.Statements | Where-Object { $_ -is [System.Management.Automation.Language.AssignmentStatementAst] -and $_.Left.Extent.Text -ieq '$basePython' })
        if ($statements.Count -ne 1) { throw 'Expected exactly one actual basePython assignment.' }
    } else {
        $BaseStagingRoot = if ($Mode -eq 'gpu-explicit') { Join-Path $FixtureRoot 'build/staging/Umi-OCR_Windows_x64' } else { '' }
        $global:BlockedPath = Join-Path $FixtureRoot 'build/staging/Umi-OCR_Windows_x64'
        $statements = @($ast.EndBlock.Statements | Where-Object { $_.Extent.Text -match '^if\s*\(-not\s+\$BaseStagingRoot\)' -or ($_.Extent.Text -match '^\$BaseStagingRoot\s*=' ) })
        if (-not $statements.Count) { throw 'Actual BaseStagingRoot selection not found.' }
    }
    try {
        foreach ($statement in $statements) { . ([scriptblock]::Create($statement.Extent.Text)) }
        $results += [pscustomobject]@{ accepted=$true; probes=$global:ProbeCount; error=$null }
    } catch { $results += [pscustomobject]@{ accepted=$false; probes=$global:ProbeCount; error=$_.Exception.Message } }
} else { throw 'Unknown probe mode.' }
ConvertTo-Json -InputObject @($results) -Depth 4 -Compress
'''


@unittest.skipUnless(os.name == "nt" and PWSH, "Windows PowerShell 7 path semantics required")
class FinalizePathGuards(unittest.TestCase):
    def probe(self, script, function, *, cases=(), mode="paths"):
        with tempfile.TemporaryDirectory(prefix="umi-release-path-guards-") as directory:
            root = Path(directory)
            driver = root / "probe.ps1"
            inputs = root / "paths.json"
            driver.write_text(PROBE, encoding="utf-8")
            inputs.write_text(json.dumps(list(cases)), encoding="utf-8")
            process = subprocess.run(
                [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(driver),
                 "-Source", str(ROOT / "build/windows" / script), "-FunctionName", function,
                 "-FixtureRoot", str(root), "-Cases", str(inputs), "-Mode", mode],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            result = json.loads(process.stdout)
            self.assertIsInstance(result, list)
            return result

    def test_network_and_device_prefixes_are_rejected_before_probe(self):
        cases = [a + b + tail for a in ("/", "\\") for b in ("/", "\\")
                 for tail in ("server/share/python.exe", "?/C:/Windows/python.exe", "./pipe/name")]
        for script, function in SCRIPTS:
            for result in self.probe(script, function, cases=cases):
                with self.subTest(script=script, path=result["path"]):
                    self.assertIs(result["accepted"], False)
                    self.assertEqual(result["probes"], 0)
                    self.assertIn("Network/device", result["error"])

    def test_drive_relative_blank_and_root_relative_paths_are_rejected_before_probe(self):
        for script, function in SCRIPTS:
            for result in self.probe(script, function, cases=("C:relative", "\\relative", "/relative", "", "   ")):
                with self.subTest(script=script, path=result["path"]):
                    self.assertIs(result["accepted"], False)
                    self.assertEqual(result["probes"], 0)

    def test_ordinary_local_paths_remain_supported(self):
        for script, function in SCRIPTS:
            for result in self.probe(script, function, cases=("build/artifacts/ordinary", "build\\audit\\ordinary.json")):
                with self.subTest(script=script, path=result["path"]):
                    self.assertIs(result["accepted"], True, result["error"])
                    self.assertGreater(result["probes"], 0)
                    self.assertTrue(Path(result["value"]).is_absolute())

    def test_lexical_junction_before_parent_segment_is_still_rejected(self):
        for script, function in SCRIPTS:
            with self.subTest(script=script):
                result, = self.probe(script, function, mode="lexical-link")
                self.assertIs(result["accepted"], False)
                self.assertIn("links or junctions", result["error"])

    def test_gpu_default_and_explicit_base_staging_share_same_guard(self):
        for mode in ("gpu-default", "gpu-explicit"):
            with self.subTest(mode=mode):
                result, = self.probe("Build-GpuPlugin.ps1", "Resolve-BuildPath", mode=mode)
                self.assertIs(result["accepted"], False)
                self.assertIn("links or junctions", result["error"])

    def test_gpu_interpreter_checks_its_runtime_child_path(self):
        result, = self.probe("Build-GpuPlugin.ps1", "Resolve-BuildPath", mode="gpu-runtime-child")
        self.assertIs(result["accepted"], False)
        self.assertIn("links or junctions", result["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
