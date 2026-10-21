[CmdletBinding()]
<#
.SYNOPSIS
    构建 Umi-OCR GPU OCR 插件归档（PP-OCRv6 + CUDA 12.6）。

.DESCRIPTION
    产物是一个自包含的 tar.xz，完整解包到 Umi-OCR 本体根目录即可使用：

        Umi-OCR/
        └── UmiOCR-data/plugins/win32_PaddleOCRv6_CUDA/
            ├── umi-plugin.json      清单
            ├── *.py                 适配器与健康检查
            ├── models/              PP-OCRv6 等推理模型
            ├── vendor/              私有 Python 闭包（paddle / nvidia / cv2 ...）
            └── runtime.lock.json    原生二进制哈希锁

    用户【不需要】手动 pip install ：vendor 仅由独立 worker 加载，不挂入宿主。

    依赖来自 build/requirements-gpu-plugin-windows-cu126.lock ，由
    build/tools/split_lock.py 按实测闭包从统一锁过滤派生（版本与哈希不变）。
#>
param(
    [string]$StagingRoot = "",
    [string]$CacheRoot = "",
    [string]$OutputRoot = "",
    [string]$BaseStagingRoot = "",
    [string]$ReuseVendorFromStagingRoot = "",
    [string]$CpuStagingRoot = "",
    [string]$ReleaseGates = "",
    [string]$OverlayRoot = "",
    [switch]$ReuseDependencies,
    [switch]$SkipModels,
    [switch]$ReuseModels,
    [switch]$Offline,
    [switch]$SkipArchive,
    [switch]$LocalCandidate
)

$ErrorActionPreference = "Stop"
if ($LocalCandidate -and $ReleaseGates) { throw "-LocalCandidate is mutually exclusive with -ReleaseGates." }
if (-not $LocalCandidate -and -not $SkipArchive -and [string]::IsNullOrWhiteSpace($ReleaseGates)) {
    throw "Formal archives require an explicit -ReleaseGates JSON input. Use a new noncandidate staging with -SkipArchive for review preparation."
}
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
function Resolve-BuildPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { throw "Build paths must not be blank." }
    # 在任何文件探测前拒绝任意混合分隔符的 UNC/device 前缀。
    if ($Path -match '^[\\/]{2}') { throw "Network/device build paths are not supported." }
    if ([IO.Path]::IsPathRooted($Path) -and -not [IO.Path]::IsPathFullyQualified($Path)) { throw "Drive-relative build paths are not supported." }
    if (-not [IO.Path]::IsPathFullyQualified($Path)) { $Path = Join-Path $RepoRoot $Path }
    $root = [IO.Path]::GetPathRoot($Path)
    $node = $root
    foreach ($part in @('') + @($Path.Substring($root.Length) -split '[\\/]')) {
        if ($part) { $node = Join-Path $node $part }
        try { $item = Get-Item -Force -LiteralPath $node -ErrorAction Stop }
        catch [System.Management.Automation.ItemNotFoundException] { continue }
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Build paths must not contain links or junctions: $node" }
    }
    return [IO.Path]::GetFullPath($Path)
}
if ($ReleaseGates) {
    $ReleaseGates = Resolve-BuildPath $ReleaseGates
    $auditRoot = Join-Path $RepoRoot "build/audit"
    if (-not $ReleaseGates.StartsWith($auditRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetExtension($ReleaseGates) -ne ".json" -or -not (Test-Path -LiteralPath $ReleaseGates -PathType Leaf)) {
        throw "-ReleaseGates must name an existing JSON file under this repository's build/audit/."
    }
}
$PluginId = "win32_PaddleOCRv6_CUDA"
$PluginSource = Join-Path $RepoRoot "UmiOCR-data\plugins\$PluginId"
$Manifest = Get-Content -Raw (Join-Path $PluginSource "umi-plugin.json") | ConvertFrom-Json
$About = Get-Content -Raw (Join-Path $RepoRoot "UmiOCR-data/about.json") | ConvertFrom-Json
$Version = "$($About.version.major).$($About.version.minor).$($About.version.patch)"
if ([string]$Manifest.version -ne $Version) { throw "CUDA manifest version must match about.json: $Version" }
$Lock = Get-Content -Raw (Join-Path $RepoRoot "build\sources-windows-cu126.lock.json") | ConvertFrom-Json

if (-not $StagingRoot) { $StagingRoot = Join-Path $RepoRoot "build\staging\$Version-gpu-$([guid]::NewGuid().ToString('N'))" }
if (-not $CacheRoot) { $CacheRoot = Join-Path $RepoRoot "build\cache" }
if (-not $OutputRoot) { $OutputRoot = Join-Path $RepoRoot "release" }
$StagingRoot = Resolve-BuildPath $StagingRoot
$CacheRoot = Resolve-BuildPath $CacheRoot
$OutputRoot = Resolve-BuildPath $OutputRoot
if (-not $BaseStagingRoot) { $BaseStagingRoot = Join-Path $RepoRoot "build\staging\Umi-OCR_Windows_x64" }
$BaseStagingRoot = Resolve-BuildPath $BaseStagingRoot
$ReuseVendorFromStagingRoot = if ($ReuseVendorFromStagingRoot) { Resolve-BuildPath $ReuseVendorFromStagingRoot } else { "" }
$CpuStagingRoot = if ($CpuStagingRoot) { Resolve-BuildPath $CpuStagingRoot } else { "" }
$BuildRoot = [IO.Path]::GetFullPath((Join-Path $RepoRoot "build"))
# Preparation normally keeps only the independent staging. Do not duplicate a
# multi-GB vendor before real GPU evidence/source materials are fixed. An
# explicit OverlayRoot opts into the additional immutable review product.
$PrepareOverlay = (-not $SkipArchive) -or -not [string]::IsNullOrWhiteSpace($OverlayRoot)
if ($LocalCandidate -and $SkipArchive -and $PrepareOverlay) { throw "An explicit -OverlayRoot with -SkipArchive requires noncandidate preparation." }
if (-not $OverlayRoot) { $OverlayRoot = Join-Path $BuildRoot "artifacts/cuda-overlay-$([guid]::NewGuid().ToString('N'))" }
$OverlayRoot = Resolve-BuildPath $OverlayRoot
$artifactRoot = Join-Path $BuildRoot "artifacts"
if (-not $OverlayRoot.StartsWith($artifactRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "CUDA overlay must stay under build/artifacts/." }
if (Test-Path -LiteralPath $OverlayRoot) { throw "Use a new CUDA overlay directory: $OverlayRoot" }
foreach ($inputRoot in @($StagingRoot, $BaseStagingRoot, $ReuseVendorFromStagingRoot) | Where-Object { $_ }) {
    if ($OverlayRoot -eq $inputRoot -or
        $OverlayRoot.StartsWith($inputRoot.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
        $inputRoot.StartsWith($OverlayRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "CUDA overlay must be disjoint from its staging/runtime/seed inputs."
    }
}

if (-not $StagingRoot.StartsWith($BuildRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Staging must stay under build/: $StagingRoot" }
if (Test-Path -LiteralPath $StagingRoot) { throw "Use a new staging directory; existing candidates are never removed: $StagingRoot" }
for ($ancestor = Split-Path -Parent $StagingRoot; $ancestor; $ancestor = Split-Path -Parent $ancestor) {
    if ((Test-Path -LiteralPath $ancestor) -and ((Get-Item -Force -LiteralPath $ancestor).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Staging ancestors must not be links: $ancestor" }
}
if ($Offline -and -not $ReuseDependencies) { throw "Offline builds require -ReuseDependencies." }
if ($ReuseDependencies) {
    if (-not $ReuseVendorFromStagingRoot) { throw "A new staging directory requires -ReuseVendorFromStagingRoot." }
    if ($StagingRoot.StartsWith($ReuseVendorFromStagingRoot.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Staging must not be inside its read-only seed." }
    if (-not (Test-Path -LiteralPath (Join-Path $ReuseVendorFromStagingRoot "UmiOCR-data/plugins/$PluginId/vendor") -PathType Container)) { throw "Offline GPU vendor seed is missing." }
}
if ($Offline -and (-not $ReuseModels -or -not $SkipModels)) { throw "Offline GPU builds require -ReuseModels -SkipModels; models are copied, never downloaded or derived." }
if ($ReuseModels -and -not $SkipModels) { throw "Use -SkipModels with -ReuseModels to avoid modifying the seed model payload." }
if ($SkipModels -and -not $ReuseModels) { throw "A new staging directory with -SkipModels requires -ReuseModels." }
if ($ReuseModels -and -not (Test-Path -LiteralPath (Join-Path $ReuseVendorFromStagingRoot "UmiOCR-data/plugins/$PluginId/models") -PathType Container)) { throw "Offline GPU model seed is missing." }

$cpuEvidenceArgs = @()
if ($CpuStagingRoot) {
    if (-not (Test-Path -LiteralPath $CpuStagingRoot -PathType Container)) {
        throw "CPU artifact evidence staging does not exist: $CpuStagingRoot"
    }
    $cpuEvidenceArgs = @("--cpu-staging-root", $CpuStagingRoot)
}

$PluginRoot = Join-Path $StagingRoot "UmiOCR-data\plugins\$PluginId"
$VendorRoot = Join-Path $PluginRoot "vendor"
$ModelsRoot = Join-Path $PluginRoot "models"

function Remove-BuildTree([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($StagingRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a path outside this new staging directory: $full"
    }
    if (Test-Path -LiteralPath $full) { Remove-Item -Recurse -Force -LiteralPath $full }
}

function Copy-GpuPluginSource([string]$Destination) {
    $full = [IO.Path]::GetFullPath($Destination)
    if (-not $full.StartsWith($StagingRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to create source mirror outside staging: $full"
    }
    if (Test-Path -LiteralPath $full) { Remove-Item -Recurse -Force -LiteralPath $full }
    & $basePython -I -S (Join-Path $RepoRoot "build/tools/export_cuda_source.py") --repo-root $RepoRoot --output-dir $full --source-cache (Join-Path $CacheRoot "sources")
    if ($LASTEXITCODE -ne 0) { throw "Public CUDA source export failed." }
}

function Get-LockedFile($Asset, [string]$Directory, [string]$Url) {
    New-Item -ItemType Directory -Force -Path $Directory | Out-Null
    if ([IO.Path]::GetFileName([string]$Asset.name) -ne $Asset.name -or [string]$Asset.name -match '[:\\/]') { throw "Unsafe locked filename: $($Asset.name)" }
    $target = Join-Path $Directory $Asset.name
    $valid = (Test-Path -LiteralPath $target) -and
        ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLower() -eq $Asset.sha256)
    if (-not $valid) {
        if ($Offline) { throw "Offline locked input is missing or hash-mismatched: $target" }
        curl.exe --retry 5 --retry-delay 2 --retry-all-errors -fL $Url -o $target
        if ($LASTEXITCODE -ne 0) { throw "下载失败: $Url" }
    }
    $hash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLower()
    if ($hash -ne $Asset.sha256) { throw "SHA256 不匹配: $target" }
    if ((Get-Item -LiteralPath $target).Length -ne $Asset.size) { throw "大小不匹配: $target" }
    return $target
}

function Write-LocalCandidateSourceNotice([string]$Destination) {
    $snapshotRoot = Join-Path $StagingRoot ".build/source-snapshot"
    $sourceRoot = Join-Path $StagingRoot "source"
    Copy-Item -Force -LiteralPath (Join-Path $StagingRoot "LICENSES/RELEASE_EVIDENCE.json") -Destination (Join-Path $sourceRoot "LICENSES/RELEASE_EVIDENCE.json")
    & $basePython -I -S (Join-Path $RepoRoot "build/tools/source_snapshot.py") --repo-root $RepoRoot --mirror-source $sourceRoot --output-dir $snapshotRoot
    if ($LASTEXITCODE -ne 0) { throw "Current CUDA source snapshot failed." }
    foreach ($name in @("source-snapshot.zip", "source-snapshot.json", "source-provenance.json")) { Copy-Item -LiteralPath (Join-Path $snapshotRoot $name) -Destination $Destination }
    $commit = (& git -C $RepoRoot rev-parse HEAD).Trim()
    $tag = & git -C $RepoRoot describe --tags --exact-match HEAD 2>$null
    if ($tag) { $tag = $tag.Trim() }
    if (-not $tag) { $tag = "v$Version (local tag pending at build time)" }
    $lockPath = Join-Path $RepoRoot "build\sources-windows-cu126.lock.json"
    $lockHash = (Get-FileHash -LiteralPath $lockPath -Algorithm SHA256).Hash.ToLower()
    @"
# Umi-OCR GPU OCR $Version local-candidate source notice

The exact current source and locked archives are included in source-snapshot.zip. The corresponding
GPU plugin source is identified precisely below; public source availability is
**PENDING**, so the release evidence keeps the public-release gate **BLOCK**.

- Product/plugin: Umi-OCR PP-OCRv6 CUDA $Version
- Local Git commit: $commit
- Local tag: $tag
- Upstream repository (reference only): https://github.com/hiroi-sora/Umi-OCR
- Public source URL: **PENDING** (no user-owned $Version remote is published)
- Build entry: build/windows/Build-GpuPlugin.ps1 -LocalCandidate
- Dependency/source lock: build/sources-windows-cu126.lock.json
- Lock SHA-256: $lockHash
- Third-party source archives: exact URLs, revisions, sizes, and SHA-256 values
  are recorded by that lock; modified files are recorded in NOTICE/evidence.

Licenses, COPYING, LICENSE, full LICENSES/, and third-party notices remain in
the archive. This local candidate is not a public release.
"@ | Set-Content -Encoding utf8 (Join-Path $Destination "SOURCE-CODE.md")
}

function Mark-LocalCandidateEvidence {
    $reportPath = Join-Path $StagingRoot "LICENSES\RELEASE_EVIDENCE.json"
    if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) { throw "Release evidence report is missing: $reportPath" }
    $report = Get-Content -Raw $reportPath | ConvertFrom-Json
    $report | Add-Member -NotePropertyName local_candidate -NotePropertyValue $true -Force
    $report | Add-Member -NotePropertyName source_delivery -NotePropertyValue ([pscustomobject]@{
        status = "BLOCK"
        public_source_url = "PENDING"
        source_tree = "source-snapshot.zip contains exact current CUDA sources and locked corresponding-source materials"
        reason = "No user-owned public $Version source repository is available yet."
    }) -Force
    $report.public_prerelease_allowed = $false
    $report.gates | Add-Member -NotePropertyName gpu_ocr_e2e -NotePropertyValue "BLOCK" -Force
    $report.gates | Add-Member -NotePropertyName current_source_e2e -NotePropertyValue "BLOCK" -Force
    $report | Add-Member -NotePropertyName current_source_validation -NotePropertyValue ([pscustomobject]@{
        status = "NOT_RUN"; reason = "Historical GPU evidence is not current-source/current-artifact E2E acceptance."
    }) -Force
    Add-Content -Encoding utf8 (Join-Path $StagingRoot "LICENSES/RELEASE_EVIDENCE.md") "`nCurrent-source/current-artifact GPU E2E: BLOCK (not run). Historical PASS rows are not current acceptance."
    $report | ConvertTo-Json -Depth 20 | Set-Content -Encoding utf8 $reportPath
}

# PaddleX 自带大量本发行版不支持的模型配置。它们会让用户在界面上看到
# 实际不存在的模型，也可能触发联网下载，因此必须裁掉。
function Remove-UnsupportedPaddleXConfigs([string]$VendorPath) {
    $configsRoot = Join-Path $VendorPath "paddlex\configs"
    if (-not (Test-Path -LiteralPath $configsRoot)) { throw "PaddleX configs 目录缺失: $configsRoot" }
    $documentLayout = "PP" + "-Doc" + "Layout" + "V3"
    $patterns = @("$documentLayout*", "*PP-OCRv2*", "*PP-OCRv3*", "*PP-OCRv4*", "*PP-OCRv5*",
                  "*PP-OCRv6_small*", "*PP-OCRv6_tiny*")
    $removed = Get-ChildItem -Recurse -File -LiteralPath $configsRoot | Where-Object {
        $name = $_.Name
        $patterns.Where({ $name -like $_ }, "First").Count -gt 0
    }
    foreach ($file in $removed) { Remove-Item -Force -LiteralPath $file.FullName }
    Write-Host "裁掉 $($removed.Count) 个不支持的 PaddleX 模型配置。"
}

function Remove-NonRuntimeFiles([string]$VendorPath) {
    $removedFiles = 0
    $removedBytes = [int64]0
    $allowedRoot = [IO.Path]::GetFullPath($VendorPath) + [IO.Path]::DirectorySeparatorChar

    $directories = @(
        Get-ChildItem -Recurse -Directory -LiteralPath (Join-Path $VendorPath "nvidia") -Filter "include" -ErrorAction SilentlyContinue
        Get-Item -LiteralPath (Join-Path $VendorPath "paddle\include") -ErrorAction SilentlyContinue
    )
    foreach ($directory in $directories) {
        $full = [IO.Path]::GetFullPath($directory.FullName)
        if (-not $full.StartsWith($allowedRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "拒绝裁剪 vendor 之外的路径: $full"
        }
        $files = Get-ChildItem -Recurse -File -Force -LiteralPath $full
        $removedFiles += $files.Count
        $removedBytes += [int64](($files | Measure-Object Length -Sum).Sum)
        Remove-Item -Recurse -Force -LiteralPath $full
    }

    $developmentFiles = Get-ChildItem -Recurse -File -Force -LiteralPath $VendorPath |
        Where-Object Extension -In ".lib", ".exp", ".pdb", ".pyi", ".pyx", ".pxd"
    foreach ($file in $developmentFiles) {
        $removedFiles += 1
        $removedBytes += [int64]$file.Length
        Remove-Item -Force -LiteralPath $file.FullName
    }

    $testDirs = Get-ChildItem -Recurse -Directory -Force -LiteralPath $VendorPath |
        Where-Object Name -In "test", "tests" |
        Sort-Object { $_.FullName.Length } -Descending
    foreach ($directory in $testDirs) {
        if (-not (Test-Path -LiteralPath $directory.FullName)) { continue }
        $files = Get-ChildItem -Recurse -File -Force -LiteralPath $directory.FullName
        $removedFiles += $files.Count
        $removedBytes += [int64](($files | Measure-Object Length -Sum).Sum)
        Remove-Item -Recurse -Force -LiteralPath $directory.FullName
    }

    Get-ChildItem -Recurse -Directory -Force -LiteralPath $StagingRoot -Filter "__pycache__" |
        Sort-Object { $_.FullName.Length } -Descending |
        ForEach-Object {
            if (Test-Path -LiteralPath $_.FullName) {
                $files = Get-ChildItem -Recurse -File -Force -LiteralPath $_.FullName
                $removedFiles += $files.Count
                $removedBytes += [int64](($files | Measure-Object Length -Sum).Sum)
                Remove-Item -Recurse -Force -LiteralPath $_.FullName
            }
        }
    Get-ChildItem -Recurse -Directory -Force -LiteralPath $VendorPath -Filter "src" |
        Sort-Object { $_.FullName.Length } -Descending |
        ForEach-Object {
            if (Test-Path -LiteralPath $_.FullName) {
                $full = [IO.Path]::GetFullPath($_.FullName)
                if (-not $full.StartsWith($allowedRoot, [StringComparison]::OrdinalIgnoreCase)) {
                    throw "Refusing to trim src outside vendor: $full"
                }
                $files = Get-ChildItem -Recurse -File -Force -LiteralPath $full
                $removedFiles += $files.Count
                $removedBytes += [int64](($files | Measure-Object Length -Sum).Sum)
                Remove-Item -Recurse -Force -LiteralPath $full
            }
        }
    Write-Host "裁掉 $removedFiles 个非运行时文件（$([math]::Round($removedBytes / 1MB, 2)) MiB）。"
}

# ===================== 1. 安装私有依赖闭包 =====================

$basePython = Resolve-BuildPath (Join-Path $BaseStagingRoot "UmiOCR-data\runtime\python.exe")
if (-not (Test-Path -LiteralPath $basePython -PathType Leaf)) {
    throw "需要先构建基础包以提供可移植 Python：$basePython 不存在。请先运行 Build-Release.ps1 或指定 -BaseStagingRoot。"
}

foreach ($asset in @($Lock.thirdPartySources)) {
    if ($null -ne $asset) { $null = Get-LockedFile $asset (Join-Path $CacheRoot "sources") $asset.url }
}
if (-not $ReuseDependencies) {
    New-Item -ItemType Directory -Force -Path $PluginRoot, $VendorRoot, $OutputRoot | Out-Null
    $pipBootstrap = Join-Path $CacheRoot "pip-bootstrap"
    if (-not (Test-Path -LiteralPath (Join-Path $pipBootstrap "pip\__init__.py"))) {
        throw "pip bootstrap 缺失：$pipBootstrap 。请先运行一次完整的 Build-Release.ps1 。"
    }
    $pipRunner = Join-Path $RepoRoot "build\tools\run_pip.py"
    $requirements = Join-Path $RepoRoot "build\requirements-gpu-plugin-windows-cu126.lock"
    & $basePython -I -S $pipRunner $pipBootstrap install --require-hashes --no-deps --no-compile --target $VendorRoot -r $requirements
    if ($LASTEXITCODE -ne 0) { throw "插件依赖安装失败。" }
}
elseif (-not (Test-Path -LiteralPath $VendorRoot)) {
    if (-not $ReuseVendorFromStagingRoot) {
        throw "无法复用依赖：vendor 目录不存在。请指定 -ReuseVendorFromStagingRoot 作为只读种子。"
    }
    $seedVendor = Join-Path $ReuseVendorFromStagingRoot "UmiOCR-data\plugins\$PluginId\vendor"
    if (-not (Test-Path -LiteralPath $seedVendor -PathType Container)) {
        throw "复用依赖种子缺少 vendor 目录: $seedVendor"
    }
    New-Item -ItemType Directory -Force -Path $VendorRoot | Out-Null
    Copy-Item -Recurse -Force -Path (Join-Path $seedVendor "*") -Destination $VendorRoot
}

# ===================== 2. 插件源码 =====================

& $basePython -I -S (Join-Path $RepoRoot "build/tools/source_snapshot.py") --repo-root $RepoRoot --plugin-dir $PluginRoot
if ($LASTEXITCODE -ne 0) { throw "Current public CUDA source copy failed." }
Copy-Item -Force -LiteralPath (Join-Path $RepoRoot "build\requirements-gpu-plugin-windows-cu126.lock") `
    -Destination (Join-Path $PluginRoot "runtime-requirements.lock")

# ===================== 3. PaddleX 补丁与裁剪 =====================

& $basePython -I -S (Join-Path $RepoRoot "build\tools\patch_paddlex_3_7_2.py") $VendorRoot
if ($LASTEXITCODE -ne 0) { throw "PaddleX 兼容补丁失败。" }
& $basePython -I -S (Join-Path $RepoRoot "build\tools\strip_optional_models_3_7.py") $VendorRoot
if ($LASTEXITCODE -ne 0) { throw "可选模型剥离失败。" }
Remove-UnsupportedPaddleXConfigs $VendorRoot

# ===================== 4. 模型 =====================

if ($ReuseModels) {
    $seedModels = Join-Path $ReuseVendorFromStagingRoot "UmiOCR-data/plugins/$PluginId/models"
    New-Item -ItemType Directory -Force -Path $ModelsRoot | Out-Null
    Copy-Item -Recurse -Force -Path (Join-Path $seedModels "*") -Destination $ModelsRoot
}
if (-not $SkipModels) {
    $modelCache = Join-Path $CacheRoot "models"
    New-Item -ItemType Directory -Force -Path $ModelsRoot | Out-Null
    foreach ($asset in $Lock.models) {
        $archive = Get-LockedFile $asset $modelCache ($Lock.modelBaseUrl + $asset.name)
        tar.exe -xf $archive -C $ModelsRoot
        if ($LASTEXITCODE -ne 0) { throw "模型解包失败: $($asset.name)" }
    }
    $uvdoc = Join-Path $ModelsRoot "UVDoc_infer"
    $uvdocGrid = Join-Path $ModelsRoot "UVDoc_grid_infer"
    & $basePython -I -S (Join-Path $RepoRoot "build\tools\derive_uvdoc_grid_model.py") $uvdoc $uvdocGrid
    if ($LASTEXITCODE -ne 0) { throw "UVDoc grid 模型派生失败。" }
    Remove-Item -Recurse -Force -LiteralPath $uvdoc
}

# ===================== 5. 裁剪非运行时文件 =====================

Remove-NonRuntimeFiles $VendorRoot

# Umi-OCR does not expose OpenCV video I/O. The bundled FFmpeg backend lacks
# a closed source/configuration record, so keep this optional DLL out of the
# public artifact rather than infer that its linkage is compliant.
$ffmpegBackends = @(Get-ChildItem -LiteralPath (Join-Path $VendorRoot "cv2") -File -Filter "opencv_videoio_ffmpeg*.dll" -ErrorAction SilentlyContinue)
foreach ($backend in $ffmpegBackends) { Remove-Item -Force -LiteralPath $backend.FullName }
if ($ffmpegBackends.Count) { Write-Host "Excluded $($ffmpegBackends.Count) optional OpenCV FFmpeg videoio backend(s)." }

# CUDA 12.6 Attachment A does not list the distinct cuSolverMg runtime.
# Keep this exact filename out of every rebuilt public GPU vendor closure.
$excludedCudaDll = Join-Path $VendorRoot "nvidia\cusolver\bin\cusolverMg64_11.dll"
if (Test-Path -LiteralPath $excludedCudaDll) {
    Remove-Item -Force -LiteralPath $excludedCudaDll
    Write-Host "Excluded unlisted CUDA binary: $excludedCudaDll"
}

# ===================== 6. 依赖闭包锁 =====================
# 只对原生二进制（dll / pyd）做哈希：它们是完整性与安全性的关键，
# 逐个哈希上万个 .py 既拖慢构建也拖慢用户端校验。

& $basePython -B -I -S (Join-Path $RepoRoot "build/tools/freeze_gpu_runtime.py") $PluginRoot
if ($LASTEXITCODE -ne 0) { throw "GPU native closure lock generation failed." }

# ===================== 7. 许可证 =====================

Copy-Item -Force -LiteralPath (Join-Path $RepoRoot "COPYING") -Destination $StagingRoot
Copy-Item -Force -LiteralPath (Join-Path $RepoRoot "LICENSE") -Destination $StagingRoot
Copy-Item -Recurse -Force -LiteralPath (Join-Path $RepoRoot "LICENSES") -Destination $StagingRoot
$historicalInventory = Join-Path $StagingRoot "LICENSES/archive-manifest.json"
if (Test-Path -LiteralPath $historicalInventory) { Remove-Item -LiteralPath $historicalInventory }

$componentNotice = Join-Path $StagingRoot "LICENSES\THIRD_PARTY_COMPONENTS.md"
& $basePython (Join-Path $RepoRoot "build\tools\generate_third_party_components.py") `
    --gpu-lock (Join-Path $RepoRoot "build\requirements-gpu-plugin-windows-cu126.lock") `
    --gpu-site-packages $VendorRoot `
    --output $componentNotice
if ($LASTEXITCODE -ne 0) { throw "Third-party component notice generation failed." }

$modelRows = foreach ($asset in $Lock.models) {
    "| $($asset.name) | $([math]::Round($asset.size / 1MB, 1)) MiB | ``$($asset.sha256)`` |"
}
@"
# Umi-OCR GPU OCR 插件 分发声明

本归档包含：

1. **插件适配器源码**（``UmiOCR-data/plugins/$PluginId/*.py``）
   —— AGPL-3.0-or-later，见 ``COPYING``。
2. **第三方 Python 依赖闭包**（``vendor/``）
   —— 各依赖保留其自身许可证与元数据；PaddleX 的本地补丁见
      ``build/tools/patch_paddlex_3_7_2.py``，修改记录见 ``LICENSES/runtime-vendor-lock.json``。
      版本与哈希见 ``build/requirements-gpu-plugin-windows-cu126.lock``。
3. **推理模型**（``models/``）
   —— 来源：``$($Lock.modelBaseUrl)``

## 模型清单

| 文件 | 大小 | SHA-256 |
| --- | --- | --- |
$($modelRows -join "`n")

``UVDoc_grid_infer`` 由 ``UVDoc_infer`` 经 ``build/tools/derive_uvdoc_grid_model.py``
本地派生，不是独立下载的第三方产物。

## Artifact-driven evidence

The five model records in ``LICENSES/model-rights.json`` are matched against
the locked PaddlePaddle Hugging Face revisions and local ``inference.pdiparams``
SHA-256 values. They are Apache-2.0 and may be redistributed when those hashes
remain unchanged. ``UVDoc_grid_infer`` is a modified derived directory; keep
its modification notice with the archive.

The release evidence report also records the proprietary CUDA/cuDNN terms,
the separate GPU-worker process boundary, FFmpeg source/build closure, MPL
file-level source obligations, and the CPU/document artifact gates. A local
staging artifact is not a public release while any report gate is BLOCK.

## 商标

Umi-OCR 的原始项目、名称与图标出处为 hiroi-sora/Umi-OCR。
本插件保留原作者署名，不主张任何商标权利，也不宣称获得商标授权。
"@ | Set-Content -Encoding utf8 (Join-Path $StagingRoot "NOTICE.md")

# 与归档一同交付插件适配器和构建此闭包所用的源码、脚本、锁文件。
# 第三方/模型再分发的独立许可问题仍由 NOTICE.md 的发布禁令约束。
Copy-GpuPluginSource (Join-Path $StagingRoot "source")
$evidenceNames = @(
    "Apache-2.0.txt", "THIRD_PARTY_COMPONENTS.md", "THIRD_PARTY_NOTICES.md",
    "model-rights.json", "runtime-vendor-lock.json", "cuda-redistributable.json",
    "cudnn-redistributable.json", "opencv-artifact.json", "ffmpeg-build.json", "gpu-e2e-evidence.json", "mpl-components.json",
    "agpl-integration.json", "cpu-document-gates.json", "RELEASE_EVIDENCE.json",
    "RELEASE_EVIDENCE.md"
)
foreach ($name in $evidenceNames) {
    $sourceEvidence = Join-Path $StagingRoot "LICENSES\$name"
    if (Test-Path -LiteralPath $sourceEvidence -PathType Leaf) {
        Copy-Item -Force -LiteralPath $sourceEvidence -Destination (Join-Path $StagingRoot "source\LICENSES\$name")
    }
}

# Generate the evidence from the actual staging artifact. Normal staging is
# allowed to remain a local validation result while unresolved gates are shown.
& $basePython (Join-Path $RepoRoot "build\tools\verify_release_evidence.py") `
    --repo-root $RepoRoot --staging-root $StagingRoot --kind gpu --cache-root $CacheRoot @cpuEvidenceArgs
if ($LASTEXITCODE -ne 0) { throw "Release evidence verification failed." }

# The verifier may have created or refreshed evidence files, so refresh the
# corresponding-source mirror after generation.
Copy-GpuPluginSource (Join-Path $StagingRoot "source")
foreach ($name in $evidenceNames) {
    $sourceEvidence = Join-Path $StagingRoot "LICENSES\$name"
    if (Test-Path -LiteralPath $sourceEvidence -PathType Leaf) {
        Copy-Item -Force -LiteralPath $sourceEvidence -Destination (Join-Path $StagingRoot "source\LICENSES\$name")
    }
}

if ($LocalCandidate) {
    Mark-LocalCandidateEvidence
    Write-LocalCandidateSourceNotice $StagingRoot
    Remove-BuildTree (Join-Path $StagingRoot "source")
    Remove-BuildTree (Join-Path $StagingRoot ".build")
}
else {
    Copy-Item -LiteralPath (Join-Path $RepoRoot "SOURCE-CODE.md") -Destination $StagingRoot
    Set-Content -Encoding utf8 -LiteralPath (Join-Path $StagingRoot "VERSION") -Value $Version
    $snapshotRoot = Join-Path $StagingRoot ".build/source-snapshot"
    & $basePython -I -S (Join-Path $RepoRoot "build/tools/source_snapshot.py") --repo-root $RepoRoot --mirror-source (Join-Path $StagingRoot "source") --output-dir $snapshotRoot
    if ($LASTEXITCODE -ne 0) { throw "Public CUDA source snapshot failed." }
    foreach ($name in @("source-snapshot.zip", "source-snapshot.json", "source-provenance.json")) {
        Copy-Item -LiteralPath (Join-Path $snapshotRoot $name) -Destination $StagingRoot
    }
    Remove-BuildTree (Join-Path $StagingRoot ".build")
}

# ===================== 8. 审计与打包 =====================

$previousPath = $env:PATH
try {
    # The independent staging is structurally audited, but its binding is NOT
    # the binding of the install overlay that will actually be delivered.
    $env:PATH = "$(Split-Path -Parent $basePython);$previousPath"
    if ($LocalCandidate) {
        & (Join-Path $RepoRoot "build\windows\Audit-Package.ps1") -PackageRoot $StagingRoot -Kind plugin -CpuStagingRoot $CpuStagingRoot -LocalCandidate
    }
    else {
        $stagingAuditArgs = @{ PackageRoot = $StagingRoot; Kind = "plugin"; CpuStagingRoot = $CpuStagingRoot }
        if ($ReleaseGates -and -not $PrepareOverlay) { $stagingAuditArgs.ReleaseGates = $ReleaseGates }
        & (Join-Path $RepoRoot "build/windows/Audit-Package.ps1") @stagingAuditArgs
    }
    if ($LASTEXITCODE -ne 0) { throw "插件 staging 审计失败。" }

    if ($PrepareOverlay) {
        & $basePython -B -I -S (Join-Path $RepoRoot "build/tools/prepare_cuda_overlay.py") --staging-root $StagingRoot --output-dir $OverlayRoot
        if ($LASTEXITCODE -ne 0) { throw "CUDA install overlay preparation failed." }
        if (-not $LocalCandidate) {
            if ($SkipArchive) {
                $auditArgs = @{ PackageRoot = $OverlayRoot; Kind = "plugin"; CpuStagingRoot = $CpuStagingRoot }
                if ($ReleaseGates) { $auditArgs.ReleaseGates = $ReleaseGates }
                & (Join-Path $RepoRoot "build/windows/Audit-Package.ps1") @auditArgs
                if ($LASTEXITCODE -ne 0) { throw "Prepared CUDA overlay audit failed." }
                Write-Host "Noncandidate CUDA overlay prepared without a formal archive; source/current gates may remain BLOCK: $OverlayRoot"
                Write-Host "Freeze this actual overlay only after its real evidence/payload is fixed; do not rerun the Builder over it."
            }
            else {
                # Only the shared restricted entry can make a formal archive.
                # It forwards ReleaseGates to Audit-Package -RequirePublicRelease
                # and verify_release_evidence --release-gates --require-public-release
                # for this SAME overlay; it never refreshes source or runtime.
                $frozen = Join-Path $BuildRoot "audit/frozen-gpu-$([guid]::NewGuid().ToString('N')).json"
                $finalizer = Join-Path $RepoRoot "build/windows/Finalize-Release.ps1"
                & $finalizer -PackageRoot $OverlayRoot -Kind gpu -PythonExe $basePython -FrozenManifest $frozen -Freeze
                & $finalizer -PackageRoot $OverlayRoot -Kind gpu -PythonExe $basePython -FrozenManifest $frozen -ReleaseGates $ReleaseGates -OutputRoot $OutputRoot
            }
        }
        else {
            $archive = Join-Path $OutputRoot "Umi-OCR-Plugin_GPU-OCR_v${Version}-local-candidate_Windows_x64_CUDA12.6.tar.xz"
            & $basePython -I -S (Join-Path $RepoRoot "build/tools/package_tar_xz.py") create --root $OverlayRoot --output $archive --integrity-output "$archive.integrity.json"
            if ($LASTEXITCODE -ne 0) { throw "tar.xz candidate packaging or integrity verification failed." }
            Write-Host "Local-candidate archive (not a public release): $archive"
        }
        Write-Host "CUDA install overlay: $OverlayRoot"
    }
}
finally { $env:PATH = $previousPath }

Write-Host "GPU OCR 插件构建完成: $StagingRoot"
