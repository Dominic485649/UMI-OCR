[CmdletBinding()]
param(
    [string]$Destination = "",
    [string]$BaseStagingRoot = "",
    [string]$GpuStagingRoot = "",
    [string]$CpuStagingRoot = "",
    [string]$VlStagingRoot = ""
)
$ErrorActionPreference = "Stop"
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../.."))
$About = Get-Content -Raw (Join-Path $RepoRoot "UmiOCR-data/about.json") | ConvertFrom-Json
$Version = "$($About.version.major).$($About.version.minor).$($About.version.patch)"
function Resolve-RepoPath([string]$Path) {
    if ([IO.Path]::IsPathRooted($Path)) { return [IO.Path]::GetFullPath($Path) }
    return [IO.Path]::GetFullPath((Join-Path $RepoRoot $Path))
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
for ($ancestor = Split-Path -Parent $Destination; $ancestor; $ancestor = Split-Path -Parent $ancestor) {
    if ((Test-Path -LiteralPath $ancestor) -and ((Get-Item -Force -LiteralPath $ancestor).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Candidate ancestors must not be links: $ancestor" }
}
$baseAboutPath = Join-Path $BaseStagingRoot "UmiOCR-data/about.json"
if (-not (Test-Path -LiteralPath $baseAboutPath -PathType Leaf)) { throw "Build the current base staging first: $baseAboutPath" }
$baseAbout = Get-Content -Raw $baseAboutPath | ConvertFrom-Json
if ("$($baseAbout.version.major).$($baseAbout.version.minor).$($baseAbout.version.patch)" -ne $Version) { throw "Base staging does not match current about.json version: $Version" }
foreach ($name in @("source-snapshot.zip", "source-snapshot.json", "source-provenance.json")) {
    if (-not (Test-Path -LiteralPath (Join-Path $BaseStagingRoot $name) -PathType Leaf)) { throw "Base staging lacks current source delivery: $name" }
}
$plugins = @(@{ name = "win32_PaddleOCRv6_CUDA"; built = $GpuStagingRoot })
if ($CpuStagingRoot) { $plugins += @{ name = "win32_PaddleOCRv6_CPU"; built = (Resolve-RepoPath $CpuStagingRoot) } }
if ($VlStagingRoot) { $plugins += @{ name = "win32_PaddleOCRVL_1_6"; built = (Resolve-RepoPath $VlStagingRoot) } }
foreach ($entry in $plugins) {
    $source = Join-Path $entry.built "UmiOCR-data/plugins/$($entry.name)"
    $manifestPath = Join-Path $source "umi-plugin.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw "Selected plugin staging is missing: $manifestPath" }
    if ((Get-Content -Raw $manifestPath | ConvertFrom-Json).version -ne $Version) { throw "Selected plugin staging version does not match $Version" }
    if (-not (Test-Path -LiteralPath (Join-Path $entry.built "LICENSES") -PathType Container)) { throw "Selected plugin staging lacks licenses: $($entry.built)" }
    if ($Destination.StartsWith($entry.built.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Destination must not be inside an input staging tree." }
}
if ($Destination.StartsWith($BaseStagingRoot.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Destination must not be inside the base staging tree." }
# Inputs are already built from current source; do not silently refresh files
# over their locks/evidence. Assembly is copy integrity, not current E2E.
Copy-Item -Recurse -LiteralPath $BaseStagingRoot -Destination $Destination
$data = Join-Path $Destination "UmiOCR-data"
foreach ($entry in $plugins) {
    $target = Join-Path $data "plugins/$($entry.name)"
    if (Test-Path -LiteralPath $target) { throw "Base staging unexpectedly contains a selected inference plugin: $target" }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item -Recurse -LiteralPath (Join-Path $entry.built "UmiOCR-data/plugins/$($entry.name)") -Destination $target
    $license = Join-Path $Destination "LICENSES/plugins/$($entry.name)"
    New-Item -ItemType Directory -Force -Path $license | Out-Null
    Copy-Item -Recurse -Path (Join-Path $entry.built "LICENSES/*") -Destination $license
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
