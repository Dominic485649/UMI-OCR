[CmdletBinding()]
param(
    [string]$Destination = "",
    [string]$BaseStagingRoot = "",
    [string]$GpuStagingRoot = "",
    [string]$CpuStagingRoot = "",
    [string]$VlStagingRoot = "",
    [string]$PythonExe = ""
)
$ErrorActionPreference = "Stop"
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../.."))
$About = Get-Content -Raw (Join-Path $RepoRoot "UmiOCR-data/about.json") | ConvertFrom-Json
$Version = "$($About.version.major).$($About.version.minor).$($About.version.patch)"
function Assert-NoLinks([string]$Path, [switch]$Tree) {
    # Check lexical prefixes before GetFullPath can hide a junction followed by '..'.
    $root = [IO.Path]::GetPathRoot($Path)
    $node = $root
    foreach ($part in @('') + @($Path.Substring($root.Length) -split '[\\/]')) {
        if ($part) { $node = Join-Path $node $part }
        try { $item = Get-Item -Force -LiteralPath $node -ErrorAction Stop }
        catch [System.Management.Automation.ItemNotFoundException] { continue }
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Candidate paths must not contain links or junctions: $node" }
    }
    if ($Tree) {
        if (-not (Test-Path -LiteralPath $Path -PathType Container)) { throw "Input staging directory is missing: $Path" }
        $pending = [Collections.Generic.Stack[object]]::new()
        $pending.Push((Get-Item -Force -LiteralPath $Path))
        while ($pending.Count) {
            $item = $pending.Pop()
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Input staging contains a link or junction: $($item.FullName)" }
            if ($item.PSIsContainer) {
                foreach ($child in Get-ChildItem -Force -LiteralPath $item.FullName) { $pending.Push($child) }
            }
        }
    }
}
function Resolve-RepoPath([string]$Path) {
    if (-not [IO.Path]::IsPathRooted($Path)) { $Path = Join-Path $RepoRoot $Path }
    Assert-NoLinks $Path
    return [IO.Path]::GetFullPath($Path)
}
if (-not $Destination) { $Destination = "build/artifacts/$Version-final/complete" }
if (-not $BaseStagingRoot) { $BaseStagingRoot = "build/staging/$Version-base-current" }
if (-not $GpuStagingRoot) { $GpuStagingRoot = "build/staging/$Version-gpu-current" }
$Destination = Resolve-RepoPath $Destination
$BaseStagingRoot = Resolve-RepoPath $BaseStagingRoot
$GpuStagingRoot = Resolve-RepoPath $GpuStagingRoot
$BuildRoot = Join-Path $RepoRoot "build"
if (-not $Destination.StartsWith($BuildRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Candidate must stay inside build/" }
if (Test-Path -LiteralPath $Destination) { throw "Use a new candidate directory: $Destination" }
Assert-NoLinks $BaseStagingRoot -Tree
$baseAboutPath = Join-Path $BaseStagingRoot "UmiOCR-data/about.json"
if (-not (Test-Path -LiteralPath $baseAboutPath -PathType Leaf)) { throw "Build the current base staging first: $baseAboutPath" }
$baseAbout = Get-Content -Raw $baseAboutPath | ConvertFrom-Json
if ("$($baseAbout.version.major).$($baseAbout.version.minor).$($baseAbout.version.patch)" -ne $Version) { throw "Base staging does not match current about.json version: $Version" }
foreach ($name in @("source-snapshot.zip", "source-snapshot.json", "source-provenance.json")) {
    if (-not (Test-Path -LiteralPath (Join-Path $BaseStagingRoot $name) -PathType Leaf)) { throw "Base staging lacks current source delivery: $name" }
}
$CudaPluginId = "win32_PaddleOCRv6_CUDA"
$CudaSourceRecordsDir = "source-records"
$plugins = @(@{ name = $CudaPluginId; built = $GpuStagingRoot })
if ($CpuStagingRoot) { $plugins += @{ name = "win32_PaddleOCRv6_CPU"; built = (Resolve-RepoPath $CpuStagingRoot) } }
if ($VlStagingRoot) { $plugins += @{ name = "win32_PaddleOCRVL_1_6"; built = (Resolve-RepoPath $VlStagingRoot) } }
foreach ($entry in $plugins) {
    Assert-NoLinks $entry.built -Tree
    $source = Join-Path $entry.built "UmiOCR-data/plugins/$($entry.name)"
    $manifestPath = Join-Path $source "umi-plugin.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw "Selected plugin staging is missing: $manifestPath" }
    if ((Get-Content -Raw $manifestPath | ConvertFrom-Json).version -ne $Version) { throw "Selected plugin staging version does not match $Version" }
    if (-not (Test-Path -LiteralPath (Join-Path $entry.built "LICENSES") -PathType Container)) { throw "Selected plugin staging lacks licenses: $($entry.built)" }
    if ($Destination.StartsWith($entry.built.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Destination must not be inside an input staging tree." }
    foreach ($relative in @("UmiOCR-data/plugins/$($entry.name)", "LICENSES/plugins/$($entry.name)")) {
        if (Test-Path -LiteralPath (Join-Path $BaseStagingRoot $relative)) { throw "Base staging unexpectedly contains a selected inference plugin or its licenses: $relative" }
    }
}
if ($Destination.StartsWith($BaseStagingRoot.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Destination must not be inside the base staging tree." }
if (Test-Path -LiteralPath (Join-Path $GpuStagingRoot "LICENSES/$CudaSourceRecordsDir")) { throw "GPU notices use the reserved CUDA source-records directory." }
# Reuse the overlay's read-only identity/hash/version checks BEFORE creating any
# output. No PATH Python fallback; an explicit interpreter is useful for fixtures.
if (-not $PythonExe) { $PythonExe = Join-Path $BaseStagingRoot "UmiOCR-data/runtime/python.exe" }
$PythonExe = Resolve-RepoPath $PythonExe
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw "Portable Python is required for CUDA source preflight: $PythonExe" }
$cudaPlan = & $PythonExe -I -B -S (Join-Path $RepoRoot "build/tools/prepare_cuda_overlay.py") --staging-root $GpuStagingRoot --validate-only
if ($LASTEXITCODE -ne 0) { throw "CUDA source preflight failed; no candidate was created." }
$cudaSource = $cudaPlan | ConvertFrom-Json
if ($cudaSource.version -ne $Version) { throw "CUDA source records do not match current version: $Version" }
# Inputs are already built from current source; do not silently refresh files
# over their locks/evidence. Assembly is copy integrity, not current E2E.
Copy-Item -Recurse -LiteralPath $BaseStagingRoot -Destination $Destination
$data = Join-Path $Destination "UmiOCR-data"
foreach ($entry in $plugins) {
    $target = Join-Path $data "plugins/$($entry.name)"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item -Recurse -LiteralPath (Join-Path $entry.built "UmiOCR-data/plugins/$($entry.name)") -Destination $target
    $license = Join-Path $Destination "LICENSES/plugins/$($entry.name)"
    New-Item -ItemType Directory -Force -Path $license | Out-Null
    Get-ChildItem -Force -LiteralPath (Join-Path $entry.built "LICENSES") | Copy-Item -Recurse -Destination $license
    if ($entry.name -eq $CudaPluginId) {
        $retained = Join-Path $license $CudaSourceRecordsDir
        New-Item -ItemType Directory -Path $retained | Out-Null
        foreach ($name in $cudaSource.source_records) {
            $sourceRecord = Join-Path $entry.built $name
            if ($name -eq "VERSION" -and -not (Test-Path -LiteralPath $sourceRecord -PathType Leaf)) {
                # The validated ZIP's VERSION may be the only copy in a local build.
                [IO.File]::WriteAllBytes((Join-Path $retained $name), [Convert]::FromBase64String($cudaSource.version_base64))
            }
            else { Copy-Item -Recurse -LiteralPath $sourceRecord -Destination (Join-Path $retained $name) }
        }
    }
}
Set-Content -Encoding utf8 -LiteralPath (Join-Path $Destination "VERSION") -Value $Version
[pscustomobject]@{
    version = $Version
    scope = $(if ($CpuStagingRoot -or $VlStagingRoot) { "public-plus-explicit-development" } else { "public-base-and-cuda" })
    current_source_e2e = "NOT_RUN"
    public_release_allowed = $false
    inputs = @($BaseStagingRoot) + @($plugins | ForEach-Object { $_.built })
} | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $Destination "assembly.json")
Write-Host "Local base/CUDA candidate assembled; current-artifact E2E remains pending: $Destination"
