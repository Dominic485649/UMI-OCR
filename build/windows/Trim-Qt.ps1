[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$SitePackagesRoot,
    [Parameter(Mandatory = $true)][string]$QmlSourceRoot,
    [Parameter(Mandatory = $true)][string]$ManifestPath,
    [string]$WhitelistPath = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $WhitelistPath) { $WhitelistPath = Join-Path $RepoRoot "build\qt-runtime-whitelist.json" }
$sitePackages = (Resolve-Path -LiteralPath $SitePackagesRoot).Path
$qmlSource = (Resolve-Path -LiteralPath $QmlSourceRoot).Path
$pysideRoot = (Resolve-Path -LiteralPath (Join-Path $sitePackages "PySide6")).Path
$qmlRoot = (Resolve-Path -LiteralPath (Join-Path $pysideRoot "qml")).Path
$pluginsRoot = (Resolve-Path -LiteralPath (Join-Path $pysideRoot "plugins")).Path
$config = Get-Content -Raw -LiteralPath $WhitelistPath | ConvertFrom-Json
$removedFiles = 0
$removedBytes = [int64]0

function Remove-PySideItem([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($pysideRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a path outside PySide6: $full"
    }
    if (-not (Test-Path -LiteralPath $full)) { return }
    $item = Get-Item -Force -LiteralPath $full
    if ($item.PSIsContainer) {
        $files = Get-ChildItem -Recurse -Force -File -LiteralPath $full
        $script:removedFiles += $files.Count
        $script:removedBytes += [int64](($files | Measure-Object Length -Sum).Sum)
        Remove-Item -Recurse -Force -LiteralPath $full
    } else {
        $script:removedFiles += 1
        $script:removedBytes += [int64]$item.Length
        Remove-Item -Force -LiteralPath $full
    }
}

function Remove-EmptyDirectories([string]$Root) {
    Get-ChildItem -Recurse -Directory -Force -LiteralPath $Root |
        Sort-Object { $_.FullName.Length } -Descending |
        Where-Object { -not (Get-ChildItem -Force -LiteralPath $_.FullName) } |
        ForEach-Object { Remove-PySideItem $_.FullName }
}

$scanner = Join-Path $pysideRoot "qmlimportscanner.exe"
if (-not (Test-Path -LiteralPath $scanner)) { throw "qmlimportscanner.exe is missing: $scanner" }
$scanOutput = & $scanner -rootPath $qmlSource -importPath $qmlRoot
if ($LASTEXITCODE -ne 0) { throw "qmlimportscanner failed." }
$scan = $scanOutput | ConvertFrom-Json

$excluded = @($config.excludedQmlPrefixes | ForEach-Object { $_.Replace("\", "/").TrimEnd("/") })
$allowedQml = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($item in $scan) {
    if (-not $item.relativePath) { continue }
    $relative = ([string]$item.relativePath).Replace("\", "/").Trim("/")
    $isExcluded = $false
    foreach ($prefix in $excluded) {
        if ($relative -eq $prefix -or $relative.StartsWith($prefix + "/", [StringComparison]::OrdinalIgnoreCase)) {
            $isExcluded = $true
            break
        }
    }
    if (-not $isExcluded) { [void]$allowedQml.Add($relative) }
}
foreach ($relative in $config.requiredQmlModules) {
    [void]$allowedQml.Add(([string]$relative).Replace("\", "/").Trim("/"))
}

$moduleDirs = Get-ChildItem -Recurse -Directory -LiteralPath $qmlRoot |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "qmldir") } |
    Sort-Object { $_.FullName.Length } -Descending
foreach ($directory in $moduleDirs) {
    if (-not (Test-Path -LiteralPath $directory.FullName)) { continue }
    $relative = [IO.Path]::GetRelativePath($qmlRoot, $directory.FullName).Replace("\", "/")
    if ($allowedQml.Contains($relative)) { continue }
    $hasAllowedChild = $false
    foreach ($allowed in $allowedQml) {
        if ($allowed.StartsWith($relative + "/", [StringComparison]::OrdinalIgnoreCase)) {
            $hasAllowedChild = $true
            break
        }
    }
    if (-not $hasAllowedChild) { Remove-PySideItem $directory.FullName }
}

$dialogStyles = Join-Path $qmlRoot "QtQuick\Dialogs\quickimpl\qml"
if (Test-Path -LiteralPath $dialogStyles) {
    Get-ChildItem -Directory -LiteralPath $dialogStyles -Filter "+*" |
        ForEach-Object { Remove-PySideItem $_.FullName }
}
Remove-EmptyDirectories $qmlRoot

$allowedPlugins = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($relative in $config.pluginFiles) {
    [void]$allowedPlugins.Add(([string]$relative).Replace("\", "/").Trim("/"))
}
Get-ChildItem -Recurse -File -LiteralPath $pluginsRoot | ForEach-Object {
    $relative = [IO.Path]::GetRelativePath($pluginsRoot, $_.FullName).Replace("\", "/")
    if (-not $allowedPlugins.Contains($relative)) { Remove-PySideItem $_.FullName }
}
Remove-EmptyDirectories $pluginsRoot

foreach ($directory in $config.removeDirectories) {
    Remove-PySideItem (Join-Path $pysideRoot ([string]$directory))
}

$translations = Join-Path $pysideRoot "translations"
if (Test-Path -LiteralPath $translations) {
    $localePattern = ($config.translationLocales | ForEach-Object { [regex]::Escape([string]$_) }) -join "|"
    Get-ChildItem -File -LiteralPath $translations | ForEach-Object {
        if ($_.Name -notmatch "^(qt|qtbase|qtdeclarative)_($localePattern)\.qm$") {
            Remove-PySideItem $_.FullName
        }
    }
}

$allowedExtensions = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
foreach ($name in $config.pythonExtensions) { [void]$allowedExtensions.Add([string]$name) }
Get-ChildItem -File -LiteralPath $pysideRoot -Filter "*.pyd" | ForEach-Object {
    if (-not $allowedExtensions.Contains($_.Name)) { Remove-PySideItem $_.FullName }
}
Get-ChildItem -File -LiteralPath $pysideRoot -Filter "*.pyi" | ForEach-Object { Remove-PySideItem $_.FullName }
Get-ChildItem -File -LiteralPath $pysideRoot -Filter "*.exe" | ForEach-Object { Remove-PySideItem $_.FullName }

$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path -LiteralPath $vswhere)) { throw "vswhere.exe not found." }
$vs = & $vswhere -latest -products * -version "[18.0,19.0)" -property installationPath
if (-not $vs) { throw "Visual Studio 2026 was not found." }
$msvc = Get-ChildItem -Directory -LiteralPath (Join-Path $vs "VC\Tools\MSVC") |
    Sort-Object Name -Descending | Select-Object -First 1
$dumpbin = Join-Path $msvc.FullName "bin\Hostx64\x64\dumpbin.exe"
if (-not (Test-Path -LiteralPath $dumpbin)) { throw "dumpbin.exe not found: $dumpbin" }

$rootDlls = @{}
Get-ChildItem -File -LiteralPath $pysideRoot -Filter "*.dll" | ForEach-Object {
    $rootDlls[$_.Name.ToLowerInvariant()] = $_.FullName
}
$dependencyRoots = [Collections.Generic.Queue[string]]::new()
foreach ($name in $config.pythonExtensions) {
    $path = Join-Path $pysideRoot ([string]$name)
    if (-not (Test-Path -LiteralPath $path)) { throw "Required PySide6 extension is missing: $path" }
    $dependencyRoots.Enqueue($path)
}
Get-ChildItem -Recurse -File -LiteralPath $qmlRoot,$pluginsRoot -Filter "*.dll" |
    ForEach-Object { $dependencyRoots.Enqueue($_.FullName) }

$visitedBinaries = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
$keptRootDlls = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
while ($dependencyRoots.Count -gt 0) {
    $binary = $dependencyRoots.Dequeue()
    if (-not $visitedBinaries.Add($binary)) { continue }
    $lines = & $dumpbin /nologo /dependents $binary
    if ($LASTEXITCODE -ne 0) { throw "dumpbin failed for $binary" }
    foreach ($line in $lines) {
        if ($line -notmatch "^\s+([A-Za-z0-9_.+\-]+\.dll)\s*$") { continue }
        $name = $Matches[1].ToLowerInvariant()
        if ($rootDlls.ContainsKey($name) -and $keptRootDlls.Add($name)) {
            $dependencyRoots.Enqueue($rootDlls[$name])
        }
    }
}
Get-ChildItem -File -LiteralPath $pysideRoot -Filter "*.dll" | ForEach-Object {
    if (-not $keptRootDlls.Contains($_.Name)) { Remove-PySideItem $_.FullName }
}

$manifest = [ordered]@{
    generatedUtc = [DateTime]::UtcNow.ToString("o")
    qtVersion = [string]$config.qtVersion
    quickStyle = [string]$config.quickStyle
    scanner = "PySide6/qmlimportscanner.exe"
    qmlModules = @($allowedQml | Sort-Object)
    pythonExtensions = @($config.pythonExtensions)
    plugins = @($config.pluginFiles)
    rootDlls = @($keptRootDlls | Sort-Object)
    removedFiles = $removedFiles
    removedMiB = [math]::Round($removedBytes / 1MB, 2)
}
$manifestDir = Split-Path -Parent ([IO.Path]::GetFullPath($ManifestPath))
New-Item -ItemType Directory -Force -Path $manifestDir | Out-Null
$manifest | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 -LiteralPath $ManifestPath
Write-Host "Qt runtime trimmed: $removedFiles files, $([math]::Round($removedBytes / 1MB, 2)) MiB removed."
