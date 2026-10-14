[CmdletBinding()]
param([string]$CacheRoot = "")

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $CacheRoot) { $CacheRoot = Join-Path $RepoRoot "build\cache" }
$python = Join-Path $CacheRoot "python-31316\python.exe"
$pipBootstrap = Join-Path $CacheRoot "pip-bootstrap"
$report = Join-Path $CacheRoot "windows-cu126-report.json"
$cudnnReport = Join-Path $CacheRoot "windows-cu126-cudnn-9.9-report.json"
if (-not (Test-Path -LiteralPath $python)) { throw "Bootstrap embedded Python first." }
& $python -I -S (Join-Path $RepoRoot "build\tools\run_pip.py") $pipBootstrap install --dry-run --ignore-installed --report $report --only-binary=:all: -r (Join-Path $RepoRoot "build\requirements-windows-cu126.in") -c (Join-Path $RepoRoot "build\constraints-inference-windows.txt")
if ($LASTEXITCODE -ne 0) { throw "Dependency resolution failed." }
& $python -I -S (Join-Path $RepoRoot "build\tools\run_pip.py") $pipBootstrap install --dry-run --ignore-installed --report $cudnnReport --only-binary=:all: --no-deps nvidia-cudnn-cu12==9.9.0.52
if ($LASTEXITCODE -ne 0) { throw "cuDNN 9.9 compatibility resolution failed." }
& $python -I -S (Join-Path $RepoRoot "build\tools\report_to_lock.py") $report (Join-Path $RepoRoot "build\requirements-windows-cu126.lock") $cudnnReport
