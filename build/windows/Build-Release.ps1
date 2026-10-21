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
    [switch]$ReuseDependencies,
    [switch]$SkipTests,
    [switch]$Offline,
    [switch]$SkipScreenshotCapture,
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
    foreach ($relative in @("UmiOCR-data/runtime/python.exe", "UmiOCR-data/site-packages", "UmiOCR-data/qt-runtime-whitelist.json")) {
        if (-not (Test-Path -LiteralPath (Join-Path $ReuseFromStagingRoot $relative))) { throw "Offline reuse input is missing: $relative" }
    }
}

function Remove-BuildTree([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($StagingRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a path outside this new staging directory: $full"
    }
    if (Test-Path -LiteralPath $full) { Remove-Item -Recurse -Force -LiteralPath $full }
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

function Remove-NonRuntimeFiles([string]$SitePackagesRoot, [string]$PortableDataRoot) {
    $removedFiles = 0
    $removedBytes = [int64]0
    $allowedRoot = [IO.Path]::GetFullPath($SitePackagesRoot) + [IO.Path]::DirectorySeparatorChar

    # nvidia / paddle 的头文件目录只会出现在 GPU 插件的 vendor 里；
    # 这里保留探测是为了让本函数在两条产线上都能复用。
    $directories = @(
        Get-ChildItem -Recurse -Directory -LiteralPath (Join-Path $SitePackagesRoot "nvidia") -Filter "include" -ErrorAction SilentlyContinue
        Get-Item -LiteralPath (Join-Path $SitePackagesRoot "paddle\include") -ErrorAction SilentlyContinue
    )
    foreach ($directory in $directories) {
        $full = [IO.Path]::GetFullPath($directory.FullName)
        if (-not $full.StartsWith($allowedRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to trim outside site-packages: $full"
        }
        $files = Get-ChildItem -Recurse -File -Force -LiteralPath $full
        $removedFiles += $files.Count
        $removedBytes += [int64](($files | Measure-Object Length -Sum).Sum)
        Remove-Item -Recurse -Force -LiteralPath $full
    }

    $developmentFiles = Get-ChildItem -Recurse -File -Force -LiteralPath $SitePackagesRoot |
        Where-Object Extension -In ".lib", ".exp", ".pdb", ".pyi", ".pyx", ".pxd"
    foreach ($file in $developmentFiles) {
        $removedFiles += 1
        $removedBytes += [int64]$file.Length
        Remove-Item -Force -LiteralPath $file.FullName
    }

    $testDirs = Get-ChildItem -Recurse -Directory -Force -LiteralPath $SitePackagesRoot |
        Where-Object Name -In "test", "tests" |
        Sort-Object { $_.FullName.Length } -Descending
    foreach ($directory in $testDirs) {
        if (-not (Test-Path -LiteralPath $directory.FullName)) { continue }
        $files = Get-ChildItem -Recurse -File -Force -LiteralPath $directory.FullName
        $removedFiles += $files.Count
        $removedBytes += [int64](($files | Measure-Object Length -Sum).Sum)
        Remove-Item -Recurse -Force -LiteralPath $directory.FullName
    }

    $bytecodeDirs = Get-ChildItem -Recurse -Directory -Force -LiteralPath $PortableDataRoot -Filter "__pycache__" |
        Sort-Object { $_.FullName.Length } -Descending
    foreach ($directory in $bytecodeDirs) {
        if (-not (Test-Path -LiteralPath $directory.FullName)) { continue }
        $files = Get-ChildItem -Recurse -File -Force -LiteralPath $directory.FullName
        $removedFiles += $files.Count
        $removedBytes += [int64](($files | Measure-Object Length -Sum).Sum)
        Remove-Item -Recurse -Force -LiteralPath $directory.FullName
    }

    # Do not ship third-party development trees named src/ in the base
    # runtime (for example NumPy's f2py source helpers). They are not used by
    # Umi-OCR and the local-candidate source policy forbids them in the base
    # package just like a complete source/ mirror.
    $sourceDirs = @(
        Get-ChildItem -Recurse -Directory -Force -LiteralPath $SitePackagesRoot -Filter "src" -ErrorAction SilentlyContinue
        Get-ChildItem -Recurse -Directory -Force -LiteralPath $PortableDataRoot -Filter "src" -ErrorAction SilentlyContinue
    ) | Sort-Object { $_.FullName.Length } -Descending
    foreach ($directory in $sourceDirs) {
        if (-not (Test-Path -LiteralPath $directory.FullName)) { continue }
        $full = [IO.Path]::GetFullPath($directory.FullName)
        if (-not $full.StartsWith($allowedRoot, [StringComparison]::OrdinalIgnoreCase) -and
            -not $full.StartsWith([IO.Path]::GetFullPath($PortableDataRoot) + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to trim src outside the portable build roots: $full"
        }
        $files = Get-ChildItem -Recurse -File -Force -LiteralPath $full
        $removedFiles += $files.Count
        $removedBytes += [int64](($files | Measure-Object Length -Sum).Sum)
        Remove-Item -Recurse -Force -LiteralPath $full
    }
    Write-Host "Trimmed $removedFiles non-runtime files ($([math]::Round($removedBytes / 1MB, 2)) MiB)."
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
    & $python -I -S (Join-Path $RepoRoot "build/tools/source_snapshot.py") --repo-root $RepoRoot --mirror-dir $full
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
        "UmiOCR-data\py_src\plugins_controller\services.py",
        "UmiOCR-data\py_src\server\http_utils.py",
        "UmiOCR-data\py_src\ocr\score.py",
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
    New-Item -ItemType Directory -Force -Path $DataRoot,$RuntimeRoot,$SitePackages | Out-Null
    Copy-Item -Recurse -Force -Path (Join-Path $seedRuntime "*") -Destination $RuntimeRoot
    Copy-Item -Recurse -Force -Path (Join-Path $seedSitePackages "*") -Destination $SitePackages
    $seedQtManifest = Join-Path $seedData "qt-runtime-whitelist.json"
    if (-not (Test-Path -LiteralPath $seedQtManifest -PathType Leaf)) {
        throw "Reuse source is missing the trimmed Qt runtime manifest: $seedQtManifest"
    }
    Copy-Item -Force -LiteralPath $seedQtManifest -Destination (Join-Path $DataRoot "qt-runtime-whitelist.json")
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
& $python -I -S (Join-Path $RepoRoot "build/tools/source_snapshot.py") --repo-root $RepoRoot --data-dir $DataRoot
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
if (Test-Path -LiteralPath $qmlScanner) {
    & (Join-Path $RepoRoot "build\windows\Trim-Qt.ps1") `
        -SitePackagesRoot $SitePackages `
        -QmlSourceRoot (Join-Path $DataRoot "qt_res\qml") `
        -ManifestPath $qtManifest
    if ($LASTEXITCODE -ne 0) { throw "Qt runtime trimming failed." }
} elseif ($ReuseDependencies -and (Test-Path -LiteralPath $qtManifest)) {
    Write-Host "Reusing an already-trimmed Qt runtime. Use a clean build after Qt/QML import changes."
} else {
    throw "Qt runtime is incomplete and has no reusable trim manifest."
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
$qtRecord.qtVersion = $qtPolicy.qtVersion
$qtRecord | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 $qtManifest

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

Remove-NonRuntimeFiles $SitePackages $DataRoot

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
    # The verifier ran while the complete local source mirror was present. The
    # candidate artifact deliberately ships only licenses/notices plus a precise
    # source notice, so public-source availability remains an explicit BLOCK.
    Mark-LocalCandidateEvidence
    Write-LocalCandidateSourceNotice $StagingRoot
    Remove-BuildTree (Join-Path $StagingRoot "source")
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
Remove-BuildTree (Join-Path $StagingRoot ".build")
if ($LocalCandidate) {
    & (Join-Path $RepoRoot "build\windows\Audit-Package.ps1") -PackageRoot $StagingRoot -Kind base -CpuStagingRoot $CpuStagingRoot -LocalCandidate
    if ($LASTEXITCODE -ne 0) { throw "Package audit failed." }
    if (-not $SkipArchive) {
        $archive = Join-Path $OutputRoot "Umi-OCR_v${VersionLabel}-local-candidate_Windows_x64.tar.xz"
        & $python -I -S (Join-Path $RepoRoot "build/tools/package_tar_xz.py") create --root $StagingRoot --output $archive --integrity-output "$archive.integrity.json"
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
    Write-Host "Noncandidate base prepared without a formal archive; source/current gates may remain BLOCK."
    Write-Host "Freeze the same product after real evidence/payload is fixed; do not rerun the Builder over it."
}
else {
    # The shared restricted entry forwards ReleaseGates to Audit-Package
    # -RequirePublicRelease and verify_release_evidence --release-gates
    # --require-public-release, and preserves this exact source/payload tree.
    $frozen = Join-Path $BuildRoot "audit/frozen-base-$([guid]::NewGuid().ToString('N')).json"
    $finalizer = Join-Path $RepoRoot "build/windows/Finalize-Release.ps1"
    & $finalizer -PackageRoot $StagingRoot -Kind base -PythonExe $python -FrozenManifest $frozen -Freeze
    & $finalizer -PackageRoot $StagingRoot -Kind base -PythonExe $python -FrozenManifest $frozen -ReleaseGates $ReleaseGates -OutputRoot $OutputRoot
}

Write-Host "Release staging ready: $StagingRoot"
