[CmdletBinding()]
# 构建 Umi-OCR 基础包。
#
# 基础包只含界面、插件宿主、任务队列、导入/导出、PDF 和托盘，
# 【不含任何 OCR 推理后端】——CUDA、PaddlePaddle、OCR 模型全部由
# 独立的 GPU OCR 插件归档提供，见 Build-GpuPlugin.ps1 。
#
# 依赖来自 build/requirements-base-windows.lock ，该锁由
# build/tools/split_lock.py 按实测依赖闭包从统一锁过滤派生。
param(
    [string]$StagingRoot = "",
    [string]$CacheRoot = "",
    [string]$OutputRoot = "",
    [string]$ReuseFromStagingRoot = "",
    [string]$CpuStagingRoot = "",
    [string]$ReleaseGates = "",
    [ValidateSet("loose", "stored")][string]$RuntimeLayout = "loose",
    [ValidateSet("minimal", "complete")][string]$DistributionLayout = "minimal",
    [string]$MinimalRoot = "",
    [string]$DistributionRecord = "",
    [string]$DerivedOpenCvWheel = "",
    [string]$DerivedQtBundle = "",
    [string]$DerivedQtLock = "",
    [string]$OfficialQtWheelhouse = "",
    [string]$OfficialQtReuseReceipt = "",
    [switch]$ReuseDependencies,
    [switch]$TrackedSourceOnly,
    [switch]$SkipTests,
    [switch]$Offline,
    [switch]$SkipScreenshotCapture,
    [switch]$SkipArchive,
    [switch]$LocalCandidate,
    [switch]$SharedRuntime
)

$ErrorActionPreference = "Stop"
if ($SharedRuntime -and ($DistributionLayout -ne 'minimal' -or $ReleaseGates -or (-not $LocalCandidate -and -not $SkipArchive))) {
    throw '共享运行时目前仅支持本地最简候选，不能绕过正式分发门禁。'
}
$UseDerivedQt = -not [string]::IsNullOrWhiteSpace($DerivedQtBundle)
if ($UseDerivedQt -xor (-not [string]::IsNullOrWhiteSpace($DerivedQtLock))) {
    throw "Provide -DerivedQtBundle and -DerivedQtLock together."
}
$UseOfficialQt = -not [string]::IsNullOrWhiteSpace($OfficialQtWheelhouse)
if ($UseOfficialQt -and $UseDerivedQt) { throw '-OfficialQtWheelhouse is mutually exclusive with -DerivedQtBundle/-DerivedQtLock.' }
if ($LocalCandidate -and $ReleaseGates) { throw "-LocalCandidate is mutually exclusive with -ReleaseGates." }
if (-not $LocalCandidate -and -not $SkipArchive -and [string]::IsNullOrWhiteSpace($ReleaseGates)) {
    throw "Formal archives require an explicit -ReleaseGates JSON input. Use a new noncandidate staging with -SkipArchive for review preparation."
}
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$sourceSelectionArgs = @()
if ($TrackedSourceOnly) { $sourceSelectionArgs += '--tracked-only' }
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
$About = Get-Content -Raw (Join-Path $RepoRoot "UmiOCR-data\about.json") | ConvertFrom-Json
$Version = "$($About.version.major).$($About.version.minor).$($About.version.patch)"
$VersionLabel = if ($About.version.prerelease) {
    "$Version-$($About.version.prerelease).$($About.version.prereleaseNumber)"
} else {
    $Version
}
$UseDefaultStaging = [string]::IsNullOrWhiteSpace($StagingRoot)
# 基础包不再绑定 CUDA，因此目录名去掉 CUDA12.6 后缀。
if ($UseDefaultStaging) { $StagingRoot = Join-Path $RepoRoot "build\staging\$Version-base-$([guid]::NewGuid().ToString('N'))" }
if (-not $CacheRoot) { $CacheRoot = Join-Path $RepoRoot "build\cache" }
if (-not $OutputRoot) { $OutputRoot = Join-Path $RepoRoot "release" }
$StagingRoot = Resolve-BuildPath $StagingRoot
$CacheRoot = Resolve-BuildPath $CacheRoot
$OutputRoot = Resolve-BuildPath $OutputRoot
$ReuseFromStagingRoot = if ($ReuseFromStagingRoot) { Resolve-BuildPath $ReuseFromStagingRoot } else { "" }
$CpuStagingRoot = if ($CpuStagingRoot) { Resolve-BuildPath $CpuStagingRoot } else { "" }
if ($UseDerivedQt) {
    $DerivedQtBundle = Resolve-BuildPath $DerivedQtBundle
    $DerivedQtLock = Resolve-BuildPath $DerivedQtLock
    foreach ($inputPath in @($DerivedQtBundle, $DerivedQtLock)) {
        if (-not (Test-Path -LiteralPath $inputPath -PathType Leaf)) { throw "Derived Qt input does not exist: $inputPath" }
    }
}
if ($UseOfficialQt) {
    $OfficialQtWheelhouse = Resolve-BuildPath $OfficialQtWheelhouse
    if (-not (Test-Path -LiteralPath $OfficialQtWheelhouse -PathType Container)) { throw 'Official Qt wheelhouse does not exist.' }
}
if ($OfficialQtReuseReceipt) {
    $OfficialQtReuseReceipt = Resolve-BuildPath $OfficialQtReuseReceipt
    if (-not (Test-Path -LiteralPath $OfficialQtReuseReceipt -PathType Leaf)) { throw 'Official Qt reuse receipt does not exist.' }
}
if ($CpuStagingRoot -and -not (Test-Path -LiteralPath $CpuStagingRoot -PathType Container)) {
    throw "CPU evidence staging does not exist: $CpuStagingRoot"
}
$cpuEvidenceArgs = if ($CpuStagingRoot) { @("--cpu-staging-root", $CpuStagingRoot) } else { @() }
$BuildRoot = [IO.Path]::GetFullPath((Join-Path $RepoRoot "build"))
$DataRoot = Join-Path $StagingRoot "UmiOCR-data"
$RuntimeRoot = Join-Path $DataRoot "runtime"
$SitePackages = Join-Path $DataRoot "site-packages"
$Lock = Get-Content -Raw (Join-Path $RepoRoot "build\sources-windows-cu126.lock.json") | ConvertFrom-Json
if (-not $StagingRoot.StartsWith($BuildRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Staging must stay under build/: $StagingRoot" }
if (Test-Path -LiteralPath $StagingRoot) { throw "Use a new staging directory; existing candidates are never removed: $StagingRoot" }
for ($ancestor = Split-Path -Parent $StagingRoot; $ancestor; $ancestor = Split-Path -Parent $ancestor) {
    if ((Test-Path -LiteralPath $ancestor) -and ((Get-Item -Force -LiteralPath $ancestor).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Staging ancestors must not be links: $ancestor" }
}
if ($Offline -and -not $ReuseDependencies) { throw "Offline builds require -ReuseDependencies and a local runtime seed." }
if ($ReuseDependencies) {
    if (-not $ReuseFromStagingRoot) { throw "A new staging directory requires -ReuseFromStagingRoot." }
    if ($StagingRoot.StartsWith($ReuseFromStagingRoot.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Staging must not be inside its read-only seed." }
    $reuseInputs = @("UmiOCR-data/runtime/python.exe", "UmiOCR-data/site-packages")
    if (-not $UseDerivedQt -and -not $UseOfficialQt) { $reuseInputs += "UmiOCR-data/qt-runtime-whitelist.json" }
    foreach ($relative in $reuseInputs) {
        if (-not (Test-Path -LiteralPath (Join-Path $ReuseFromStagingRoot $relative))) { throw "Offline reuse input is missing: $relative" }
    }
}

# 原始requirements锁仍描述上游输入；派生构件使用自己的独立摘要，不沿用官方wheel哈希。
$SubsetProfile = Join-Path $RepoRoot 'build/runtime-subsets-windows.json'
$subset = Get-Content -Raw -LiteralPath $SubsetProfile | ConvertFrom-Json
if (-not $DerivedOpenCvWheel) { $DerivedOpenCvWheel = Join-Path $CacheRoot ('derived/opencv/' + $subset.opencv.filename) }
$DerivedOpenCvWheel = Resolve-BuildPath $DerivedOpenCvWheel
if (-not (Test-Path -LiteralPath $DerivedOpenCvWheel -PathType Leaf) -or
    (Get-FileHash -LiteralPath $DerivedOpenCvWheel -Algorithm SHA256).Hash.ToLowerInvariant() -ne $subset.opencv.sha256) {
    throw '缺少固定摘要的OpenCV派生wheel。先用build_minimal_opencv.ps1/package_minimal_opencv.py构建，并显式传入-DerivedOpenCvWheel；不回退到完整官方wheel。'
}

function Remove-BuildTree([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($StagingRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a path outside this new staging directory: $full"
    }
    if (Test-Path -LiteralPath $full) {
        $occupied = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($full.TrimEnd('\','/') + '\',[StringComparison]::OrdinalIgnoreCase) })
        if ($occupied.Count) { throw "新候选目录仍有活动进程，须正常退出后才能替换：$full" }
        $links = @(Get-ChildItem -LiteralPath $full -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })
        if ($links.Count) { throw "候选目录包含链接，停止替换：$full" }
        Remove-Item -Recurse -Force -LiteralPath $full
    }
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
        if ($LASTEXITCODE -ne 0) { throw "Download failed: $Url" }
    }
    $hash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLower()
    if ($hash -ne $Asset.sha256) { throw "SHA256 mismatch: $target" }
    if ((Get-Item -LiteralPath $target).Length -ne $Asset.size) { throw "Size mismatch: $target" }
    return $target
}

function Expand-Zip([string]$Archive, [string]$Destination) {
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $zip = [IO.Path]::ChangeExtension($Archive, ".zip")
    if ($zip -ne $Archive) { Copy-Item -Force -LiteralPath $Archive -Destination $zip }
    Expand-Archive -Force -LiteralPath $zip -DestinationPath $Destination
    if ($zip -ne $Archive) { Remove-Item -LiteralPath $zip }
}

function Remove-PortableState([string]$PortableDataRoot) {
    foreach ($name in ".settings", ".pre_settings", "themes.json", "startup_error.log", "logs", "temp", "temp_doc") {
        $path = Join-Path $PortableDataRoot $name
        if (Test-Path -LiteralPath $path) { Remove-Item -Recurse -Force -LiteralPath $path }
    }
    Get-ChildItem -Recurse -Directory -Force -LiteralPath $PortableDataRoot -Filter "__pycache__" |
        Sort-Object { $_.FullName.Length } -Descending |
        Remove-Item -Recurse -Force
    Get-ChildItem -Recurse -File -Force -LiteralPath $PortableDataRoot -Filter "*.pyc" |
        Remove-Item -Force
}

function Copy-ReleaseSource([string]$Destination) {
    $full = [IO.Path]::GetFullPath($Destination)
    if (-not $full.StartsWith($StagingRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to create source mirror outside staging: $full"
    }
    if (Test-Path -LiteralPath $full) { Remove-Item -Recurse -Force -LiteralPath $full }
    & $python -I -S (Join-Path $RepoRoot "build/tools/source_snapshot.py") --repo-root $RepoRoot --mirror-dir $full @sourceSelectionArgs
    if ($LASTEXITCODE -ne 0) { throw "Public corresponding-source selection failed." }
    $thirdPartyRoot = Join-Path $full "third_party"
    foreach ($asset in @($Lock.thirdPartySources)) {
        if ($null -eq $asset) { continue }
        $archive = Get-LockedFile $asset (Join-Path $CacheRoot "sources") $asset.url
        New-Item -ItemType Directory -Force -Path $thirdPartyRoot | Out-Null
        Copy-Item -Force -LiteralPath $archive -Destination (Join-Path $thirdPartyRoot $asset.name)
    }
    $required = @(
        "COPYING",
        "LICENSE",
        "LICENSES\COMBINED_DISTRIBUTION.md",
        "LICENSES\PyMuPDF-AGPL-3.0.txt",
        "LICENSES\THIRD_PARTY_NOTICES.md",
        "LICENSES\THIRD_PARTY_COMPONENTS.md", "LICENSES\Apache-2.0.txt",
        "LICENSES\runtime-vendor-lock.json", "LICENSES\opencv-artifact.json", "LICENSES\ffmpeg-build.json",
        "LICENSES\RELEASE_EVIDENCE.json", "LICENSES\RELEASE_EVIDENCE.md",
        "LICENSES\evidence\nvidia\cuda-toolkit-eula-2026-08-07.html",
        "LICENSES\LGPL-2.1.txt",
        "LICENSES\LGPL-3.0.txt",
        "LICENSES\GPL-3.0.txt",
        "build\requirements-windows-cu126.lock",
        "build\requirements-base-windows.lock",
        "build\requirements-gpu-plugin-windows-cu126.lock",
        "build\sources-windows-cu126.lock.json",
        "build\tools\split_lock.py",
        "build\runtime-subsets-windows.json",
        "build\tools\project_dependency_runtime.py",
        "build\tools\build_minimal_opencv.ps1",
        "build\tools\package_minimal_opencv.py",
        "build\tools\generate_third_party_components.py",
        "build\tools\verify_release_evidence.py",
        "build\tools\release_gate_inputs.py",
        "build\tools\finalize_release.py",
        "build\windows\Finalize-Release.ps1",
        "build\windows\Audit-Package.ps1",
        "build\windows\Build-Release.ps1",
        "build\windows\Build-GpuPlugin.ps1",
        "build\tools\source_snapshot.py",
        "build\tools\prepare_products.py",
        "build\tools\package_tar_xz.py",
        "UmiOCR-data\runtime_archive_bootstrap.py",
        "UmiOCR-data\py_src\plugins_controller\services.py",
        "UmiOCR-data\py_src\server\http_utils.py",
        "UmiOCR-data\py_src\ocr\score.py",
        "LICENSES\markdown-preview\manifest.json",
        "LICENSES\QtWebEngine\manifest.json",
        "LICENSES\QtWebEngine\third-party-notices.zip",
        "third_party\qtwebengine-everywhere-src-6.11.2.tar.xz",
        "third_party\pymupdf-1.28.0.tar.gz",
        "third_party\ffmpeg-4.4.4.tar.xz"
    )
    foreach ($relative in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $full $relative))) {
            throw "Corresponding source is missing: $relative"
        }
    }
}

foreach ($asset in @($Lock.thirdPartySources)) {
    if ($null -ne $asset) { $null = Get-LockedFile $asset (Join-Path $CacheRoot "sources") $asset.url }
}
$python = Join-Path $RuntimeRoot "python.exe"
if (-not $ReuseDependencies) {
    New-Item -ItemType Directory -Force -Path $DataRoot,$RuntimeRoot,$SitePackages,$OutputRoot | Out-Null
    $pythonAsset = $Lock.runtime | Where-Object name -Like "python-*-embed-amd64.zip"
    $pipAsset = $Lock.runtime | Where-Object name -Like "pip-*.whl"
    $pythonArchive = Get-LockedFile $pythonAsset $CacheRoot $pythonAsset.url
    $pipArchive = Get-LockedFile $pipAsset $CacheRoot $pipAsset.url
    Expand-Zip $pythonArchive $RuntimeRoot
    $pipBootstrap = Join-Path $CacheRoot "pip-bootstrap"
    if (-not (Test-Path -LiteralPath (Join-Path $pipBootstrap "pip\__init__.py"))) {
        $pipBootstrap = Join-Path $StagingRoot ".build/pip-bootstrap"
        Expand-Zip $pipArchive $pipBootstrap
    }
    $pipRunner = Join-Path $RepoRoot "build\tools\run_pip.py"
    $requirements = Join-Path $RepoRoot "build\requirements-base-windows.lock"
    & $python -I -S $pipRunner $pipBootstrap install --require-hashes --no-deps --no-compile --target $SitePackages -r $requirements
    if ($LASTEXITCODE -ne 0) { throw "Locked dependency installation failed." }
} elseif (-not (Test-Path -LiteralPath $python)) {
    if (-not $ReuseFromStagingRoot) {
        throw "Cannot reuse dependencies because staging runtime is missing. Provide -ReuseFromStagingRoot for a clean destination."
    }
    $seedData = Join-Path $ReuseFromStagingRoot "UmiOCR-data"
    $seedRuntime = Join-Path $seedData "runtime"
    $seedSitePackages = Join-Path $seedData "site-packages"
    foreach ($seed in @($seedRuntime, $seedSitePackages)) {
        if (-not (Test-Path -LiteralPath $seed -PathType Container)) {
            throw "Reuse source is missing a runtime closure directory: $seed"
        }
    }
    New-Item -ItemType Directory -Force -Path $DataRoot,$RuntimeRoot | Out-Null
    Copy-Item -Recurse -Force -Path (Join-Path $seedRuntime "*") -Destination $RuntimeRoot
    # 新依赖根通过经核验的逻辑视图生成，包含dependencies.zip中的bottle/six。
    $dependencyInputRoot = $seedData
    if (-not $UseDerivedQt -and -not $UseOfficialQt) {
        $seedQtManifest = Join-Path $seedData "qt-runtime-whitelist.json"
        if (-not (Test-Path -LiteralPath $seedQtManifest -PathType Leaf)) {
            throw "Reuse source is missing the trimmed Qt runtime manifest: $seedQtManifest"
        }
        Copy-Item -Force -LiteralPath $seedQtManifest -Destination (Join-Path $DataRoot "qt-runtime-whitelist.json")
    }
}

# 新装上游依赖和归档种子共用同一派生入口；不能只在诊断覆盖层删文件。
if (-not $ReuseDependencies) { $dependencyInputRoot = $DataRoot }
$projectionAudit = Join-Path $RepoRoot ('build/audit/dependency-projection-host-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $projectionAudit | Out-Null
$projectionTarget = if ($ReuseDependencies -and -not $UseDerivedQt) { $SitePackages } else { Join-Path $StagingRoot '.build/projected-site-packages' }
& $python -I -B -S (Join-Path $RepoRoot 'build/tools/project_dependency_runtime.py') `
    --source-root $dependencyInputRoot --destination $projectionTarget --profile $SubsetProfile `
    --opencv-wheel $DerivedOpenCvWheel --receipt (Join-Path $projectionAudit 'result.json') --component host
if ($LASTEXITCODE -ne 0) { throw '本体依赖派生失败，不会使用未裁切的旧载荷继续构建。' }
if ($UseDerivedQt) {
    # 通用依赖投影先形成只读的扁平输入；Qt 工具整体替换四发行版，直接写最终路径。
    # 新清单来自已核验 bundle，绝不复制种子的旧 Qt 清单或重用上游 wheel 摘要。
    if (Test-Path -LiteralPath $SitePackages) { Remove-BuildTree $SitePackages }
    & $python -I -B -S (Join-Path $RepoRoot 'build/tools/project_derived_qt.py') `
        --source-root $projectionTarget --destination-root $SitePackages `
        --bundle $DerivedQtBundle --lock $DerivedQtLock `
        --whitelist (Join-Path $RepoRoot 'build/qt-runtime-whitelist.json') `
        --manifest-output (Join-Path $DataRoot 'qt-runtime-whitelist.json') `
        --receipt (Join-Path $projectionAudit 'derived-qt-result.json')
    if ($LASTEXITCODE -ne 0) { throw 'Derived Qt projection failed; do not fall back to seed Qt or its manifest.' }
} elseif (-not $ReuseDependencies) {
    Remove-BuildTree $SitePackages
    Move-Item -LiteralPath $projectionTarget -Destination $SitePackages
}

if ($UseOfficialQt) {
    # Extract locked wheels without pip and without modifying their original RECORDs.
    # The two PySide wheels share one namespace; replace its merged tree once.
    $officialQtRoot = Join-Path $StagingRoot '.build/official-qt'
    & $python -I -B -S (Join-Path $RepoRoot 'build/tools/official_qt_projection.py') extract `
        --wheelhouse $OfficialQtWheelhouse --destination $officialQtRoot `
        --lock (Join-Path $RepoRoot 'build/requirements-base-windows.lock') `
        --receipt (Join-Path $projectionAudit 'official-qt-input.json')
    if ($LASTEXITCODE -ne 0) { throw 'Official Qt wheel extraction failed; do not reuse seed Qt.' }
    $qtRoots = @(Get-ChildItem -LiteralPath $SitePackages -Force | Where-Object {
        $_.Name -in @('PySide6', 'shiboken6') -or $_.Name -match '^(pyside6(?:[-_]addons|[-_]essentials)?|shiboken6)-.+\.dist-info$'
    })
    foreach ($qtRoot in $qtRoots) { Remove-BuildTree $qtRoot.FullName }
    foreach ($qtRoot in @(Get-ChildItem -LiteralPath $officialQtRoot -Directory)) {
        Move-Item -LiteralPath $qtRoot.FullName -Destination $SitePackages
    }
}

function Write-LocalCandidateSourceNotice([string]$Destination) {
    $snapshotRoot = Join-Path $StagingRoot ".build/source-snapshot"
    $sourceRoot = Join-Path $StagingRoot "source"
    Copy-Item -Force -LiteralPath (Join-Path $StagingRoot "LICENSES/RELEASE_EVIDENCE.json") -Destination (Join-Path $sourceRoot "LICENSES/RELEASE_EVIDENCE.json")
    & $python -I -S (Join-Path $RepoRoot "build/tools/source_snapshot.py") --repo-root $RepoRoot --mirror-source $sourceRoot --output-dir $snapshotRoot
    if ($LASTEXITCODE -ne 0) { throw "Current public source snapshot failed." }
    @"
# Umi-OCR $Version local candidate source

source-snapshot.zip contains the exact current public sources and locked corresponding-source materials.
source-snapshot.json records each member hash; source-provenance.json records version and archive hash.
Public source publication and current-artifact E2E remain pending. This is not a public release.
"@ | Set-Content -Encoding utf8 (Join-Path $Destination "SOURCE-CODE.md")
    foreach($name in @("source-snapshot.zip","source-snapshot.json","source-provenance.json")) {
        $snapshot=Join-Path $snapshotRoot $name
        if(-not (Test-Path -LiteralPath $snapshot)) { throw "Generate the frozen source snapshot first: $snapshot" }
        Copy-Item -Force -LiteralPath $snapshot -Destination $Destination
    }
}

function Mark-LocalCandidateEvidence {
    $reportPath = Join-Path $StagingRoot "LICENSES\RELEASE_EVIDENCE.json"
    if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) { throw "Release evidence report is missing: $reportPath" }
    $report = Get-Content -Raw $reportPath | ConvertFrom-Json
    $report | Add-Member -NotePropertyName local_candidate -NotePropertyValue $true -Force
    $report | Add-Member -NotePropertyName source_delivery -NotePropertyValue ([pscustomobject]@{
        status = "BLOCK"
        public_source_url = "PENDING"
        source_tree = "source-snapshot.zip; exact file hashes and local parent revisions included"
        reason = "No user-owned public $Version source repository is available yet."
    }) -Force
    $report.public_prerelease_allowed = $false
    $report.gates | Add-Member -NotePropertyName current_source_e2e -NotePropertyValue "BLOCK" -Force
    $report | Add-Member -NotePropertyName current_source_validation -NotePropertyValue ([pscustomobject]@{
        status = "NOT_RUN"; reason = "Static build/audit is not current-artifact E2E. Historical evidence is not current acceptance."
    }) -Force
    $report | ConvertTo-Json -Depth 20 | Set-Content -Encoding utf8 $reportPath
    Add-Content -Encoding utf8 (Join-Path $StagingRoot "LICENSES/RELEASE_EVIDENCE.md") "`nCurrent-source/current-artifact E2E: BLOCK (not run). Historical PASS rows are not current acceptance."
}
& $python -I -S (Join-Path $RepoRoot "build/tools/source_snapshot.py") --repo-root $RepoRoot --data-dir $DataRoot @sourceSelectionArgs
if ($LASTEXITCODE -ne 0) { throw "Current public host source copy failed." }
# GPU OCR 插件随独立归档分发，不进基础包。它的源码仍然会通过
# Copy-ReleaseSource 进入 source/ 镜像，满足 AGPL 的对应源码义务。
$bundledPlugin = Join-Path $DataRoot "plugins\win32_PaddleOCRv6_CUDA"
if (Test-Path -LiteralPath $bundledPlugin) { Remove-Item -Recurse -Force -LiteralPath $bundledPlugin }
Copy-Item -Force -LiteralPath (Join-Path $RepoRoot "COPYING") -Destination $StagingRoot
Copy-Item -Force -LiteralPath (Join-Path $RepoRoot "LICENSE") -Destination $StagingRoot
Copy-Item -Recurse -Force -LiteralPath (Join-Path $RepoRoot "LICENSES") -Destination $StagingRoot
$historicalInventory = Join-Path $StagingRoot "LICENSES/archive-manifest.json"
if (Test-Path -LiteralPath $historicalInventory) { Remove-Item -LiteralPath $historicalInventory }
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

# PaddleX 补丁、可选模型剥离和 PaddleX 配置裁剪都随 Paddle 一起
# 迁到了 Build-GpuPlugin.ps1 ：基础包里已经没有 paddle / paddlex 。
$qtManifest = Join-Path $DataRoot "qt-runtime-whitelist.json"
$qmlScanner = Join-Path $SitePackages "PySide6\qmlimportscanner.exe"
if ($UseDerivedQt) {
    $qtProjection = Get-Content -Raw -LiteralPath (Join-Path $projectionAudit 'derived-qt-result.json') | ConvertFrom-Json
    if ($qtProjection.status -ne 'PROJECTED_VERIFIED_NOT_APP_ACCEPTED' -or
        $qtProjection.runtimeManifestSha256 -ne (Get-FileHash -LiteralPath $qtManifest -Algorithm SHA256).Hash.ToLowerInvariant() -or
        $qtProjection.archiveSha256 -ne (Get-FileHash -LiteralPath $DerivedQtBundle -Algorithm SHA256).Hash.ToLowerInvariant() -or
        $qtProjection.lockSha256 -ne (Get-FileHash -LiteralPath $DerivedQtLock -Algorithm SHA256).Hash.ToLowerInvariant()) {
        throw 'Derived Qt projection binding changed; refuse a stale Qt manifest.'
    }
    Write-Host 'Using verified derived Qt and its exact projected runtime manifest; native/application gates remain separate.'
} elseif ($UseOfficialQt) {
    & (Join-Path $RepoRoot "build\windows\Trim-Qt.ps1") `
        -SitePackagesRoot $SitePackages `
        -QmlSourceRoot (Join-Path $DataRoot "qt_res\qml") `
        -ManifestPath $qtManifest
    if ($LASTEXITCODE -ne 0) { throw "Qt runtime trimming failed." }
    & $python -I -B -S (Join-Path $RepoRoot 'build/tools/official_qt_projection.py') seal `
        --site $SitePackages --lock (Join-Path $RepoRoot 'build/requirements-base-windows.lock') `
        --policy (Join-Path $RepoRoot 'build/qt-runtime-whitelist.json') --qml (Join-Path $DataRoot 'qt_res/qml') `
        --trim-script (Join-Path $RepoRoot 'build/windows/Trim-Qt.ps1') --manifest $qtManifest `
        --extraction-receipt (Join-Path $projectionAudit 'official-qt-input.json') `
        --receipt (Join-Path $projectionAudit 'official-qt-result.json')
    if ($LASTEXITCODE -ne 0) { throw 'Official Qt sealing failed; the trim manifest is not reusable.' }
} elseif (Test-Path -LiteralPath $qtManifest) {
    if ([string]::IsNullOrWhiteSpace($OfficialQtReuseReceipt)) { throw 'Qt reuse needs -OfficialQtReuseReceipt, or provide -OfficialQtWheelhouse for a fresh trim.' }
    & $python -I -B -S (Join-Path $RepoRoot 'build/tools/official_qt_projection.py') verify `
        --site $SitePackages --lock (Join-Path $RepoRoot 'build/requirements-base-windows.lock') `
        --policy (Join-Path $RepoRoot 'build/qt-runtime-whitelist.json') --qml (Join-Path $DataRoot 'qt_res/qml') `
        --trim-script (Join-Path $RepoRoot 'build/windows/Trim-Qt.ps1') --manifest $qtManifest `
        --source-receipt $OfficialQtReuseReceipt --receipt (Join-Path $projectionAudit 'official-qt-reuse-result.json')
    if ($LASTEXITCODE -ne 0) { throw 'Qt reuse verification failed; provide -OfficialQtWheelhouse for a fresh trim.' }
} else {
    # A complete scanner alone is not evidence of the installed wheel provenance.
    throw 'Official Qt provenance is missing; provide -OfficialQtWheelhouse, even when qmlimportscanner.exe exists.'
}

# OCR 模型随 GPU OCR 插件归档分发，基础包不含任何模型。见 Build-GpuPlugin.ps1 。

$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path -LiteralPath $vswhere)) { throw "vswhere.exe not found." }
$vs = & $vswhere -latest -products * -version "[18.0,19.0)" -property installationPath
if (-not $vs) { throw "Visual Studio 2026 was not found." }
$launcherBuild = Join-Path $StagingRoot ".build/pystand"
$qtPolicy = Get-Content -Raw (Join-Path $RepoRoot "build/qt-runtime-whitelist.json") | ConvertFrom-Json
$qtCore = Get-Item -LiteralPath (Join-Path $SitePackages "PySide6/Qt6Core.dll")
if ($qtCore.VersionInfo.FileVersion -notlike "$($qtPolicy.qtVersion)*") { throw "Qt runtime does not match the current whitelist: $($qtCore.VersionInfo.FileVersion)" }
$qtRecord = Get-Content -Raw $qtManifest | ConvertFrom-Json
if ($UseDerivedQt) {
    if ($qtRecord.qtVersion -ne $qtPolicy.qtVersion) { throw 'Derived Qt manifest version does not match the current whitelist.' }
    # 保留 bundle 中已按摘要绑定的原始清单字节，不用版本重写掩盖不匹配。
} else {
    if ($qtRecord.qtVersion -ne $qtPolicy.qtVersion) { throw 'Official Qt manifest version does not match the current whitelist.' }
    # A verified manifest is immutable here; never repair a stale version label.
}

cmake.exe -S (Join-Path $RepoRoot "build\windows\PyStand") -B $launcherBuild -G "Visual Studio 18 2026" -A x64 "-DCMAKE_SYSTEM_VERSION=10.0.28000.0" "-DUMIOCR_VERSION=$Version"
if ($LASTEXITCODE -ne 0) { throw "PyStand configure failed." }
cmake.exe --build $launcherBuild --config Release --parallel
if ($LASTEXITCODE -ne 0) { throw "PyStand build failed." }
Copy-Item -Force -LiteralPath (Join-Path $launcherBuild "Release\Umi-OCR.exe") -Destination (Join-Path $StagingRoot "Umi-OCR.exe")

$hdrBuild = Join-Path $StagingRoot ".build/hdr_capture"
cmake.exe -S (Join-Path $RepoRoot "build\windows\HdrCapture") -B $hdrBuild -G "Visual Studio 18 2026" -A x64 "-DCMAKE_SYSTEM_VERSION=10.0.28000.0" "-DUMIOCR_VERSION=$Version"
if ($LASTEXITCODE -ne 0) { throw "HDR capture configure failed." }
cmake.exe --build $hdrBuild --config Release --parallel
if ($LASTEXITCODE -ne 0) { throw "HDR capture build failed." }
$nativeRoot = Join-Path $DataRoot "native"
New-Item -ItemType Directory -Force -Path $nativeRoot | Out-Null
Copy-Item -Force -LiteralPath (Join-Path $hdrBuild "Release\UmiOCR-HdrCapture.dll") -Destination $nativeRoot

# 小文件优化只改变容器布局，不按后缀或 tests/src 等目录名删减依赖。
# 依赖种子的既有裁剪来自其独立构建记录，本次保留全部输入文件。

# Umi-OCR does not use OpenCV video I/O. Its bundled FFmpeg backend is a
# static LGPL build, so keep this optional feature out of the public closure.
$ffmpegBackends = @(Get-ChildItem -LiteralPath (Join-Path $SitePackages "cv2") -File -Filter "opencv_videoio_ffmpeg*.dll" -ErrorAction SilentlyContinue)
foreach ($backend in $ffmpegBackends) { Remove-Item -Force -LiteralPath $backend.FullName }
if ($ffmpegBackends.Count) { Write-Host "Excluded $($ffmpegBackends.Count) optional OpenCV FFmpeg videoio backend(s)." }

$componentNotice = Join-Path $StagingRoot "LICENSES\THIRD_PARTY_COMPONENTS.md"
& (Join-Path $RuntimeRoot "python.exe") (Join-Path $RepoRoot "build\tools\generate_third_party_components.py") `
    --base-lock (Join-Path $RepoRoot "build\requirements-base-windows.lock") `
    --base-site-packages $SitePackages `
    --output $componentNotice
if ($LASTEXITCODE -ne 0) { throw "Third-party component notice generation failed." }

# Only shipped runtime files belong in the lock.  Temporary compiler output
# under .build is removed before release and must not become a required DLL.
$dlls = Get-ChildItem -Recurse -File $DataRoot -Filter "*.dll" | ForEach-Object {
    [pscustomobject]@{
        path = [IO.Path]::GetRelativePath($StagingRoot, $_.FullName).Replace("\", "/")
        version = $_.VersionInfo.FileVersion
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLower()
    }
}
$dlls | ConvertTo-Json -Depth 3 | Set-Content -Encoding utf8 (Join-Path $DataRoot "native-dlls.lock.json")

& $python (Join-Path $RepoRoot "build\tools\verify_release_evidence.py") `
    --repo-root $RepoRoot --staging-root $StagingRoot --kind base --cache-root $CacheRoot @cpuEvidenceArgs
if ($LASTEXITCODE -ne 0) { throw "Release evidence verification failed." }

if (-not $SkipTests) {
    # 基础包只跑 base 档：此时还没有任何 OCR 后端，这正是要验证的状态。
    $testArgs = @{ StagingRoot = $StagingRoot; Kind = "base" }
    if ($SkipScreenshotCapture) { $testArgs.SkipScreenshotCapture = $true }
    & (Join-Path $RepoRoot "build\windows\Test-Release.ps1") @testArgs
    if ($LASTEXITCODE -ne 0) { throw "Release regression suite failed." }
}
Remove-PortableState $DataRoot
Copy-ReleaseSource (Join-Path $StagingRoot "source")
$evidenceNames = @(
    "Apache-2.0.txt", "THIRD_PARTY_COMPONENTS.md", "THIRD_PARTY_NOTICES.md",
    "runtime-vendor-lock.json", "model-rights.json", "cuda-redistributable.json",
    "cudnn-redistributable.json", "opencv-artifact.json", "ffmpeg-build.json", "mpl-components.json",
    "agpl-integration.json", "cpu-document-gates.json", "RELEASE_EVIDENCE.json",
    "RELEASE_EVIDENCE.md"
)
foreach ($name in $evidenceNames) {
    $sourceEvidence = Join-Path $StagingRoot "LICENSES\$name"
    if (Test-Path -LiteralPath $sourceEvidence -PathType Leaf) {
        Copy-Item -Force -LiteralPath $sourceEvidence -Destination (Join-Path $StagingRoot "source\LICENSES\$name")
    }
}
# Re-run after the source mirror exists so the FFmpeg source-presence result is
# based on the exact release tree, not only on the local cache.
& $python (Join-Path $RepoRoot "build\tools\verify_release_evidence.py") `
    --repo-root $RepoRoot --staging-root $StagingRoot --kind base --cache-root $CacheRoot @cpuEvidenceArgs
if ($LASTEXITCODE -ne 0) { throw "Release evidence verification failed." }
foreach ($name in $evidenceNames) {
    $sourceEvidence = Join-Path $StagingRoot "LICENSES\$name"
    if (Test-Path -LiteralPath $sourceEvidence -PathType Leaf) {
        Copy-Item -Force -LiteralPath $sourceEvidence -Destination (Join-Path $StagingRoot "source\LICENSES\$name")
    }
}

if ($LocalCandidate) {
    # 完整工作布局保留对应源码供后续审计；最简运行包由独立转换阶段生成。
    # 本地源码快照不等于公开源码已发布，公开可用性仍保持明确BLOCK。
    Set-Content -Encoding utf8NoBOM -LiteralPath (Join-Path $StagingRoot 'VERSION') -Value $Version
    Mark-LocalCandidateEvidence
    Write-LocalCandidateSourceNotice $StagingRoot
    # 完整对应源码必须留到包审计之后；提前删除会让离线预览源码门禁失败。
}
else {
    Copy-Item -LiteralPath (Join-Path $RepoRoot "SOURCE-CODE.md") -Destination $StagingRoot
    Set-Content -Encoding utf8 -LiteralPath (Join-Path $StagingRoot "VERSION") -Value $Version
    $snapshotRoot = Join-Path $StagingRoot ".build/source-snapshot"
    & $python -I -S (Join-Path $RepoRoot "build/tools/source_snapshot.py") --repo-root $RepoRoot --mirror-source (Join-Path $StagingRoot "source") --output-dir $snapshotRoot
    if ($LASTEXITCODE -ne 0) { throw "Public source snapshot failed." }
    foreach ($name in @("source-snapshot.zip", "source-snapshot.json", "source-provenance.json")) {
        Copy-Item -LiteralPath (Join-Path $snapshotRoot $name) -Destination $StagingRoot
    }
}
# 在源码记录齐备、所有运行状态清理之后聚合，冻结/归档之后不再改布局。
if ($RuntimeLayout -eq "stored") {
    & $python -I -B -S -X utf8 (Join-Path $RepoRoot "build/tools/merge_runtime.py") $DataRoot `
        --kind host --policy (Join-Path $RepoRoot "build/windows/runtime_archives_host.json") --project-root $RepoRoot
    if ($LASTEXITCODE -ne 0) { throw "Host Stored-ZIP aggregation failed." }
    & $python -I -B -S -X utf8 (Join-Path $RepoRoot "build/tools/audit_runtime_archives.py") --root $DataRoot
    if ($LASTEXITCODE -ne 0) { throw "Host Stored-ZIP source verification failed." }
}
Remove-BuildTree (Join-Path $StagingRoot ".build")
$distributionArgs = @{}
$archiveRoot = $StagingRoot
function Initialize-MinimalBase {
    if ($DistributionLayout -ne "minimal") { return }
    if (-not $MinimalRoot) { $MinimalRoot = "$StagingRoot-runtime" }
    $MinimalRoot = Resolve-BuildPath $MinimalRoot
    if (-not $DistributionRecord) { $DistributionRecord = Join-Path $BuildRoot "audit/minimal-base-$([guid]::NewGuid().ToString('N')).json" }
    $DistributionRecord = Resolve-BuildPath $DistributionRecord
    $sharedArgs = @()
    if ($SharedRuntime) { $sharedArgs = @('--shared-runtime') }
    & $python -I -B (Join-Path $RepoRoot "build/tools/prepare_minimal_distribution.py") prepare --component base --root $StagingRoot --output $MinimalRoot --report $DistributionRecord @sharedArgs
    if ($LASTEXITCODE -ne 0) { throw "最简运行包及外置源码绑定失败。" }
    $script:archiveRoot = $MinimalRoot
    $script:distributionArgs.DistributionRecord = $DistributionRecord
    Write-Host "最简运行目录：$MinimalRoot；源码与证据保留在：$StagingRoot；清单：$DistributionRecord"
}
if ($LocalCandidate) {
    & (Join-Path $RepoRoot "build\windows\Audit-Package.ps1") -PackageRoot $StagingRoot -Kind base -CpuStagingRoot $CpuStagingRoot -LocalCandidate
    if ($LASTEXITCODE -ne 0) { throw "Package audit failed." }
    Initialize-MinimalBase
    if (-not $SkipArchive) {
        $archive = Join-Path $OutputRoot "Umi-OCR_v${VersionLabel}-local-candidate_Windows_x64.tar.xz"
        & $python -I -S (Join-Path $RepoRoot "build/tools/package_tar_xz.py") create --root $archiveRoot --output $archive --integrity-output "$archive.integrity.json"
        if ($LASTEXITCODE -ne 0) { throw "tar.xz candidate packaging or integrity verification failed." }
        Write-Host "Local-candidate archive (not a public release): $archive"
    }
}
elseif ($SkipArchive) {
    # A fresh noncandidate tree can be reviewed before public main/tag exists.
    # This audit records real BLOCKs; it does not grant public-release status.
    $auditArgs = @{ PackageRoot = $StagingRoot; Kind = "base"; CpuStagingRoot = $CpuStagingRoot }
    if ($ReleaseGates) { $auditArgs.ReleaseGates = $ReleaseGates }
    & (Join-Path $RepoRoot "build/windows/Audit-Package.ps1") @auditArgs
    if ($LASTEXITCODE -ne 0) { throw "Prepared base package audit failed." }
    Initialize-MinimalBase
    Write-Host "Noncandidate base prepared without a formal archive; source/current gates may remain BLOCK."
    Write-Host "Freeze the same product after real evidence/payload is fixed; do not rerun the Builder over it."
}
else {
    # The shared restricted entry forwards ReleaseGates to Audit-Package
    # -RequirePublicRelease and verify_release_evidence --release-gates
    # --require-public-release, and preserves this exact source/payload tree.
    Initialize-MinimalBase
    $frozen = Join-Path $BuildRoot "audit/frozen-base-$([guid]::NewGuid().ToString('N')).json"
    $finalizer = Join-Path $RepoRoot "build/windows/Finalize-Release.ps1"
    & $finalizer -PackageRoot $StagingRoot -Kind base -PythonExe $python -FrozenManifest $frozen -Freeze
    & $finalizer -PackageRoot $StagingRoot -Kind base -PythonExe $python -FrozenManifest $frozen -ReleaseGates $ReleaseGates -OutputRoot $OutputRoot @distributionArgs
}

Write-Host "Release staging ready: $StagingRoot"
