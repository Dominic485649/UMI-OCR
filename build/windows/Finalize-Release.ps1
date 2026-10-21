[CmdletBinding(DefaultParameterSetName = "Finalize")]
<#
.SYNOPSIS
    Freeze a review product, or finalize that same tree behind the public gates.
.DESCRIPTION
    -Freeze writes only a new external integrity manifest, never approval/PASS.
    Finalize requires the original manifest and fresh explicit ReleaseGates.
    GPU input must already be the actual prepare_cuda_overlay.py install overlay.
    This entry never rebuilds, refreshes source/runtime, promotes local candidates,
    publishes source/tags/releases, or accepts a bypass for the existing gates.
#>
param(
    [Parameter(Mandatory = $true)][string]$PackageRoot,
    [Parameter(Mandatory = $true)][ValidateSet("base", "gpu")][string]$Kind,
    [Parameter(Mandatory = $true)][string]$FrozenManifest,
    [Parameter(Mandatory = $true, ParameterSetName = "Freeze")][switch]$Freeze,
    [Parameter(Mandatory = $true, ParameterSetName = "Finalize")][string]$ReleaseGates,
    [Parameter(ParameterSetName = "Finalize")][string]$OutputRoot = "",
    [string]$PythonExe = ""
)
$ErrorActionPreference = "Stop"
if ($PSVersionTable.PSVersion.Major -lt 7) { throw "PowerShell 7 is required." }
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../.."))
function Resolve-PlainPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { throw "An explicit non-empty path is required." }
    # 在任何文件探测前拒绝任意混合分隔符的 UNC/device 前缀。
    if ($Path -match '^[\\/]{2}') { throw "Network/device paths are not supported." }
    if ([IO.Path]::IsPathRooted($Path) -and -not [IO.Path]::IsPathFullyQualified($Path)) { throw "Drive-relative release paths are not supported." }
    if (-not [IO.Path]::IsPathFullyQualified($Path)) { $Path = Join-Path $RepoRoot $Path }
    # Check lexical prefixes before normalization can hide a junction + '..'.
    $root = [IO.Path]::GetPathRoot($Path)
    $node = $root
    foreach ($part in @('') + @($Path.Substring($root.Length) -split '[\\/]')) {
        if ($part) { $node = Join-Path $node $part }
        try { $item = Get-Item -Force -LiteralPath $node -ErrorAction Stop }
        catch [System.Management.Automation.ItemNotFoundException] { continue }
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Release paths must not contain links or junctions: $node" }
    }
    return [IO.Path]::GetFullPath($Path)
}
$PackageRoot = Resolve-PlainPath $PackageRoot
$build = Join-Path $RepoRoot "build"
if (-not $PackageRoot.StartsWith($build + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Product must stay under this repository's build/."
}
if (-not (Test-Path -LiteralPath $PackageRoot -PathType Container)) { throw "An already prepared product tree is required." }
$FrozenManifest = Resolve-PlainPath $FrozenManifest
if (-not $PythonExe) {
    if ($Kind -ne "base") { throw "GPU overlay finalization requires an explicit portable -PythonExe." }
    $PythonExe = Join-Path $PackageRoot "UmiOCR-data/runtime/python.exe"
}
$PythonExe = Resolve-PlainPath $PythonExe
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw "Portable Python does not exist: $PythonExe" }
$helperArgs = @(
    $(if ($Freeze) { "freeze" } else { "finalize" }),
    "--repo-root", $RepoRoot, "--package-root", $PackageRoot,
    "--kind", $Kind, "--frozen-manifest", $FrozenManifest
)
if (-not $Freeze) {
    $ReleaseGates = Resolve-PlainPath $ReleaseGates
    if (-not (Test-Path -LiteralPath $ReleaseGates -PathType Leaf)) { throw "An existing explicit -ReleaseGates JSON is required." }
    if (-not $OutputRoot) { $OutputRoot = Join-Path $RepoRoot "release" }
    $OutputRoot = Resolve-PlainPath $OutputRoot
    $helperArgs += @("--release-gates", $ReleaseGates, "--output-root", $OutputRoot)
}
& $PythonExe -I -B -S -X utf8 (Join-Path $RepoRoot "build/tools/finalize_release.py") @helperArgs
if ($LASTEXITCODE -ne 0) { throw "Release freeze/finalization failed; no formal archive was authorized." }
if ($Freeze) { Write-Host "Review product frozen without publication approval: $FrozenManifest" }
else { Write-Host "Existing public-release gates passed for the same immutable product: $PackageRoot" }
