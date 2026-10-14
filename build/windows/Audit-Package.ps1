[CmdletBinding()]
<#
.SYNOPSIS
    审计 Umi-OCR 发布产物：基础包 或 插件归档。

.DESCRIPTION
    2.7 起发布产物拆成两类，审计规则也随之分成两套：

      base   基础包。【必须】含界面/宿主/PDF/托盘的完整运行时闭包，
             【必须不含】任何 OCR 推理后端（CUDA、Paddle、模型）。
             注意这与 2.6 的规则完全相反：2.6 要求基础包里必须有
             paddlepaddle_gpu 和 PP-OCRv6 模型。

      plugin 插件归档。必须自带清单、依赖闭包与许可证，且清单声明的
             宿主 API 范围必须与本仓库的 HOST_API_VERSION 相容。

    两类都必须通过"禁止内容"检查：不得混入 PaddleOCR-VL 源码、
    llama.cpp、GGUF、mmproj 或 PP-DocLayoutV3 等未确认可再分发的内容。

.PARAMETER PackageRoot
    待审计的目录（解压后的形态）。

.PARAMETER Kind
    base 或 plugin 。省略时按目录内容自动判定。
#>
param(
    [Parameter(Mandatory = $true)][string]$PackageRoot,
    [ValidateSet("base", "plugin", "auto")][string]$Kind = "auto",
    [string]$CpuStagingRoot = "",
    [switch]$RequirePublicRelease,
    [switch]$LocalCandidate
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath $PackageRoot).Path
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$cpuEvidenceArgs = @()
if ($CpuStagingRoot) {
    $CpuStagingRoot = [IO.Path]::GetFullPath($CpuStagingRoot)
    if (-not (Test-Path -LiteralPath $CpuStagingRoot -PathType Container)) {
        Fail "CPU artifact evidence staging does not exist: $CpuStagingRoot"
    }
    else {
        $cpuEvidenceArgs = @("--cpu-staging-root", $CpuStagingRoot)
    }
}

$failures = New-Object System.Collections.Generic.List[string]
function Fail([string]$message) { $failures.Add($message) }
function Require([string]$relativePath, [string]$why) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $relativePath))) {
        Fail "缺少${why}: $relativePath"
    }
}
function RequireFile([string]$relativePath, [string]$why) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $relativePath) -PathType Leaf)) {
        Fail "缺少${why}: $relativePath"
    }
}

# ===================== 自动判定产物类型 =====================

if ($Kind -eq "auto") {
    if (Test-Path -LiteralPath (Join-Path $root "Umi-OCR.exe")) { $Kind = "base" }
    elseif (Get-ChildItem -Recurse -Filter "umi-plugin.json" -LiteralPath $root -ErrorAction SilentlyContinue) { $Kind = "plugin" }
    else { throw "无法判定产物类型：既没有 Umi-OCR.exe 也没有 umi-plugin.json 。请显式指定 -Kind 。" }
}
Write-Host "审计类型: $Kind"
Write-Host "审计目录: $root"

# Evidence is generated from the extracted artifact before the structural
# checks below.  A normal audit records unresolved legal gates; the explicit
# public-release mode turns those gates into a hard failure.
$evidenceKind = $null
if ($Kind -eq "base") { $evidenceKind = "base" }
elseif (Test-Path -LiteralPath (Join-Path $root "UmiOCR-data\plugins\win32_PaddleOCRv6_CPU\umi-plugin.json") -PathType Leaf) { $evidenceKind = "cpu" }
elseif (Test-Path -LiteralPath (Join-Path $root "UmiOCR-data\plugins\win32_PaddleOCRv6_CUDA\umi-plugin.json") -PathType Leaf) { $evidenceKind = "gpu" }
if ($evidenceKind) {
    $verifier = Join-Path $RepoRoot "build\tools\verify_release_evidence.py"
    $evidencePython = Join-Path $root "UmiOCR-data\runtime\python.exe"
    if (-not (Test-Path -LiteralPath $evidencePython -PathType Leaf)) {
        $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($pythonCommand) { $evidencePython = $pythonCommand.Source }
    }
    if (-not (Test-Path -LiteralPath $evidencePython -PathType Leaf)) {
        Fail "无法运行 artifact evidence verifier: portable/system Python 不存在"
    }
    elseif (-not (Test-Path -LiteralPath $verifier -PathType Leaf)) {
        Fail "缺少 artifact evidence verifier: $verifier"
    }
    elseif ($LocalCandidate) {
        $reportPath = Join-Path $root "LICENSES\RELEASE_EVIDENCE.json"
        if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
            Fail "local-candidate 缺少已生成的 LICENSES/RELEASE_EVIDENCE.json"
        }
        else {
            try {
                $candidateReport = Get-Content -Raw $reportPath | ConvertFrom-Json
                if (-not $candidateReport.local_candidate) { Fail "local-candidate evidence 未声明 local_candidate=true" }
                if ($candidateReport.public_prerelease_allowed) { Fail "local-candidate 不得声明 public_prerelease_allowed=true" }
                if (-not $candidateReport.source_delivery -or $candidateReport.source_delivery.status -ne "BLOCK") {
                    Fail "local-candidate 必须明确记录公开源码地址为 PENDING/BLOCK"
                }
            }
            catch { Fail "无法读取 local-candidate evidence: $($_.Exception.Message)" }
        }
    }
    else {
        $evidenceArgs = @(
            $verifier, "--repo-root", $RepoRoot, "--staging-root", $root,
            "--kind", $evidenceKind, "--cache-root", (Join-Path $RepoRoot "build\cache")
        )
        $evidenceArgs += $cpuEvidenceArgs
        if ($RequirePublicRelease) { $evidenceArgs += "--require-public-release" }
        & $evidencePython -I -S @evidenceArgs
        if ($LASTEXITCODE -ne 0) { Fail "artifact evidence verifier 未通过（kind=$evidenceKind）" }
    }
}

# ===================== 通用：禁止内容 =====================
# 名字用拼接构造，避免本脚本自身被内容扫描判为违规。

$nameDash = "Paddle" + "OCR" + "-" + "VL"
$nameCompact = "Paddle" + "OCR" + "VL"
$nameShort = "Paddle" + "VL"
$layout = "PP" + "-Doc" + "Layout" + "V3"
$server = "llama" + "." + "cpp"
$serverExe = "llama" + "-server.exe"
$modelBinarySuffix = "gg" + "uf"
$projectionBinarySuffix = "mm" + "proj"

$forbiddenNames = @(
    ("*." + $modelBinarySuffix),
    ("*." + $projectionBinarySuffix),
    $serverExe,
    $server,
    "$layout*",
    "*PP-OCRv2*",
    "*PP-OCRv3*",
    "*PP-OCRv4*",
    "*PP-OCRv5*",
    "*PP-OCRv6_small*",
    "*PP-OCRv6_tiny*",
    "*directml*",
    "*.lib",
    "*.exp",
    "*.pdb",
    "*.pyc",
    "*.pyi",
    "*.pyx",
    "*.pxd",
    "__pycache__"
)
if ($evidenceKind -ne "cpu") { $forbiddenNames += "*onnxruntime*" }
# document 插件会在自己的清单、源码和故障提示中说明外部 VLM 服务。
# 这不是把模型或服务端混入归档。基础包则完全不应含这类源码；只有
# 基础包使用名称规则和源码文本扫描。二进制/模型规则始终对两类产物生效。
if ($Kind -eq "base") {
    $forbiddenNames += @(
        "*$nameDash*",
        "*$nameCompact*",
        "*$nameShort*",
        ("win32_" + $nameCompact + "_1_6")
    )
}
$nameViolations = foreach ($pattern in $forbiddenNames) {
    Get-ChildItem -Recurse -Force -LiteralPath $root -Filter $pattern -ErrorAction SilentlyContinue
}
foreach ($item in ($nameViolations.FullName | Select-Object -Unique)) {
    Fail "禁止的发布内容: $item"
}

$forbiddenText = @($nameDash, $nameCompact, $nameShort, $layout, $server, $modelBinarySuffix, $projectionBinarySuffix)
if ($Kind -eq "base") {
    # 文档和许可证可以说明外部模型/服务；只检查会进入基础运行路径的
    # 代码和清单，避免把只读调研文档误判为打包载荷。
    $textExtensions = @(".py", ".qml", ".json", ".yaml", ".yml", ".toml", ".ini")
    foreach ($file in Get-ChildItem -Recurse -File -LiteralPath $root) {
        $relative = [IO.Path]::GetRelativePath($root, $file.FullName).Replace("\", "/")
        if ($relative -like "LICENSES/*" -or $relative -like "source/*") { continue }
        # These root manifests describe the inert source ZIP, not executable runtime payload.
        if ($relative -in @("source-snapshot.json", "source-provenance.json")) { continue }
        if ($textExtensions -notcontains $file.Extension.ToLower()) { continue }
        $contents = [string](Get-Content -Raw -LiteralPath $file.FullName)
        if ($relative -eq "UmiOCR-data/py_src/plugins_controller/manifest.py") {
            # The host names this exact old id to reject its incompatible
            # implementation.  Exempt only that standalone set-entry line;
            # actual imports, service paths and model binaries remain banned.
            $contents = ($contents -split "`r?`n" | Where-Object {
                $_ -notmatch '^\s*["'']win32_PaddleOCRVL_1_6["''],?\s*$'
            }) -join "`n"
        }
        foreach ($term in $forbiddenText) {
            if (([string]$contents).IndexOf($term, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                Fail "禁止的基础包源码内容: $($file.FullName) 命中 $term"
                break
            }
        }
    }
}

# ===================== 通用：许可证 =====================

function Test-Licenses([string[]]$paths) {
    foreach ($relativePath in $paths) { RequireFile $relativePath "许可证或对应源码文件" }
}

# ===================== 基础包审计 =====================

function Invoke-BaseAudit {
    $sitePackages = Join-Path $root "UmiOCR-data\site-packages"

    # --- 1. 基础包【不得】含任何 OCR 推理后端 ---------------------------
    # 这三条与 2.6 的断言完全相反，是本次迁移的核心验收点。
    $gpuDist = Get-ChildItem -Recurse -Directory -LiteralPath $root -Filter "paddlepaddle_gpu-*.dist-info" -ErrorAction SilentlyContinue
    if ($gpuDist) { Fail "基础包中出现 paddlepaddle-gpu，应只存在于 GPU OCR 插件归档: $($gpuDist.FullName -join ', ')" }
    $cpuDist = Get-ChildItem -Recurse -Directory -LiteralPath $root -Filter "paddlepaddle-*.dist-info" -ErrorAction SilentlyContinue |
        Where-Object Name -NotLike "paddlepaddle_gpu-*"
    if ($cpuDist) { Fail "基础包中出现 CPU paddlepaddle: $($cpuDist.FullName)" }

    # 注意 cv2 【不在】此列：py_src/utils/image_decoder.py 模块级 import cv2 ，
    # 二维码与 HTTP 服务都依赖它，它是基础包的真实依赖而非 OCR 后端依赖。
    foreach ($name in "paddle", "paddlex", "paddleocr", "nvidia") {
        $path = Join-Path $sitePackages $name
        if (Test-Path -LiteralPath $path) {
            Fail "基础包中出现 OCR 后端依赖，应迁至插件 vendor: UmiOCR-data\site-packages\$name"
        }
    }
    $models = Get-ChildItem -Recurse -File -LiteralPath $root -Filter "inference.pdiparams" -ErrorAction SilentlyContinue
    if ($models) { Fail "基础包中出现 OCR 模型权重: $($models.FullName -join ', ')" }
    $bundledPlugins = Get-ChildItem -Directory -LiteralPath (Join-Path $root "UmiOCR-data\plugins") -ErrorAction SilentlyContinue
    if ($bundledPlugins) {
        Fail "基础包中预置了插件目录，插件必须由用户单独解压: $($bundledPlugins.Name -join ', ')"
    }

    # --- 2. 基础包必需的运行时闭包 --------------------------------------
    $requiredRuntime = @(
        "Umi-OCR.exe",
        "UmiOCR-data\main.py",
        "UmiOCR-data\about.json",
        "UmiOCR-data\native-dlls.lock.json",
        "UmiOCR-data\qt-runtime-whitelist.json",
        "UmiOCR-data\runtime\python.exe",
        "UmiOCR-data\native\UmiOCR-HdrCapture.dll",
        "UmiOCR-data\qt_res\images\icons\umiocr.ico",
        "UmiOCR-data\qt_res\qml\Main.qml",
        "UmiOCR-data\qt_res\qml\MainWindow\SystemTray.qml",
        # 插件契约 v2 的宿主实现，缺任何一个都会让插件无法被发现
        "UmiOCR-data\py_src\plugins_controller\plugins_controller.py",
        "UmiOCR-data\py_src\plugins_controller\manifest.py",
        "UmiOCR-data\py_src\plugins_controller\capabilities.py",
        "UmiOCR-data\py_src\plugins_controller\host_api.py",
        "UmiOCR-data\py_src\tag_pages\page_registry.py",
        "UmiOCR-data\py_src\ocr\api\__init__.py",
        "UmiOCR-data\py_src\document\api\__init__.py",
        "UmiOCR-data\py_src\mission\mission_document.py",
        "UmiOCR-data\qt_res\qml\ApiManager\OcrManager.qml",
        "UmiOCR-data\qt_res\qml\ApiManager\DocumentManager.qml",
        # Qt 运行时
        "UmiOCR-data\site-packages\PySide6\QtWidgets.pyd",
        "UmiOCR-data\site-packages\PySide6\Qt6Widgets.dll",
        "UmiOCR-data\site-packages\PySide6\qml\Qt\labs\platform\qmldir",
        "UmiOCR-data\site-packages\PySide6\qml\Qt\labs\platform\labsplatformplugin.dll",
        "UmiOCR-data\site-packages\PySide6\plugins\platforms\qwindows.dll",
        "UmiOCR-data\site-packages\PySide6\plugins\imageformats\qico.dll",
        "UmiOCR-data\site-packages\PySide6\plugins\styles\qmodernwindowsstyle.dll"
    )
    foreach ($relativePath in $requiredRuntime) { RequireFile $relativePath "基础包运行时闭包文件" }

    # 基础包必需的第三方发行版
    # 与 py_src 的实际 import 集合一一对应，见 build/tools/measure_closure.py 的扫描结果。
    foreach ($pattern in "pymupdf-*.dist-info", "imagecodecs-*.dist-info", "pillow-*.dist-info",
                          "numpy-*.dist-info", "bottle-*.dist-info", "zxing_cpp-*.dist-info",
                          "opencv_contrib_python-*.dist-info", "psutil-*.dist-info",
                          "pynput-*.dist-info", "PySide6-*.dist-info") {
        if (-not (Get-ChildItem -Directory -LiteralPath $sitePackages -Filter $pattern -ErrorAction SilentlyContinue)) {
            Fail "基础包缺少必需发行版: $pattern"
        }
    }

    # --- 3. 许可证与对应源码 --------------------------------------------
    $baseLicenseFiles = @(
        "COPYING",
        "LICENSE",
        "LICENSES\COMBINED_DISTRIBUTION.md",
        "LICENSES\PyMuPDF-AGPL-3.0.txt",
        "LICENSES\Apache-2.0.txt",
        "LICENSES\THIRD_PARTY_NOTICES.md",
        "LICENSES\THIRD_PARTY_COMPONENTS.md",
        "LICENSES\runtime-vendor-lock.json",
        "LICENSES\opencv-artifact.json",
        "LICENSES\ffmpeg-build.json",
        "LICENSES\evidence\nvidia\cuda-toolkit-eula-2026-08-07.html",
        "LICENSES\evidence\nvidia\cudnn-sla-2026-08-09.html",
        "LICENSES\RELEASE_EVIDENCE.json",
        "LICENSES\RELEASE_EVIDENCE.md",
        "LICENSES\LGPL-2.1.txt",
        "LICENSES\LGPL-3.0.txt",
        "LICENSES\GPL-3.0.txt"
    )
    if (-not $LocalCandidate) {
        $baseLicenseFiles += @(
        "source\COPYING",
        "source\LICENSE",
        "source\LICENSES\COMBINED_DISTRIBUTION.md",
        "source\LICENSES\PyMuPDF-AGPL-3.0.txt",
        "source\LICENSES\Apache-2.0.txt",
        "source\LICENSES\THIRD_PARTY_NOTICES.md",
        "source\LICENSES\THIRD_PARTY_COMPONENTS.md",
        "source\LICENSES\runtime-vendor-lock.json",
        "source\LICENSES\opencv-artifact.json",
        "source\LICENSES\ffmpeg-build.json",
        "source\LICENSES\evidence\nvidia\cuda-toolkit-eula-2026-08-07.html",
        "source\LICENSES\evidence\nvidia\cudnn-sla-2026-08-09.html",
        "source\LICENSES\RELEASE_EVIDENCE.json",
        "source\LICENSES\RELEASE_EVIDENCE.md",
        "source\LICENSES\LGPL-2.1.txt",
        "source\LICENSES\LGPL-3.0.txt",
        "source\LICENSES\GPL-3.0.txt",
        "source\build\requirements-base-windows.lock",
        "source\build\requirements-gpu-plugin-windows-cu126.lock",
        "source\build\sources-windows-cu126.lock.json",
        "source\build\tools\split_lock.py",
        "source\build\tools\generate_third_party_components.py",
        "source\build\windows\Audit-Package.ps1",
        "source\build\windows\Build-Release.ps1",
        "source\build\windows\Build-GpuPlugin.ps1",
        "source\docs\PLUGIN_API.md"
        )
    }
    else {
        $baseLicenseFiles += "SOURCE-CODE.md"
    }
    Test-Licenses $baseLicenseFiles
    if (-not $LocalCandidate) {
    # GPU 插件的源码即使不随基础包分发，也必须出现在对应源码镜像里
    RequireFile "source\UmiOCR-data\plugins\win32_PaddleOCRv6_CUDA\api.py" "GPU 插件对应源码"
    RequireFile "source\UmiOCR-data\plugins\win32_PaddleOCRv6_CUDA\worker.py" "GPU worker 对应源码"
    }

    # --- 4. Qt 运行时闭包清单 -------------------------------------------
    $qtManifestPath = Join-Path $root "UmiOCR-data\qt-runtime-whitelist.json"
    if (Test-Path -LiteralPath $qtManifestPath) {
        $qtManifest = Get-Content -Raw $qtManifestPath | ConvertFrom-Json
        $pysideRoot = Join-Path $sitePackages "PySide6"
        foreach ($relative in @($qtManifest.pythonExtensions)) {
            if (-not (Test-Path -LiteralPath (Join-Path $pysideRoot $relative) -PathType Leaf)) {
                Fail "Qt Python 扩展缺失: $relative"
            }
        }
        foreach ($relative in @($qtManifest.plugins)) {
            if (-not (Test-Path -LiteralPath (Join-Path $pysideRoot (Join-Path "plugins" $relative)) -PathType Leaf)) {
                Fail "Qt 插件缺失: $relative"
            }
        }
        foreach ($relative in @($qtManifest.qmlModules)) {
            if (-not (Test-Path -LiteralPath (Join-Path $pysideRoot (Join-Path "qml" (Join-Path $relative "qmldir"))) -PathType Leaf)) {
                Fail "Qt QML 模块缺失: $relative"
            }
        }
        foreach ($name in @($qtManifest.rootDlls)) {
            if (-not (Test-Path -LiteralPath (Join-Path $pysideRoot $name) -PathType Leaf)) {
                Fail "Qt DLL 闭包缺失: $name"
            }
        }
    }

    # --- 5. 原生 DLL 哈希锁 ---------------------------------------------
    $nativeLockPath = Join-Path $root "UmiOCR-data\native-dlls.lock.json"
    if (Test-Path -LiteralPath $nativeLockPath) {
        $nativeLock = @(Get-Content -Raw $nativeLockPath | ConvertFrom-Json)
        if ($nativeLock.Count -eq 0) { Fail "原生 DLL 锁为空。" }
        foreach ($entry in $nativeLock) {
            $path = Join-Path $root ([string]$entry.path).Replace("/", "\")
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Fail "锁定的 DLL 缺失: $($entry.path)"; continue }
            if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower() -ne $entry.sha256) {
                Fail "锁定的 DLL 哈希不匹配: $($entry.path)"
            }
        }
    }

    # --- 6. 第三方对应源码完整性 ----------------------------------------
    $sourceLockPath = Join-Path $root "source\build\sources-windows-cu126.lock.json"
    if ($LocalCandidate) { $sourceLockPath = $null }
    if (-not $LocalCandidate -and (Test-Path -LiteralPath $sourceLockPath)) {
        $sourceLock = Get-Content -Raw $sourceLockPath | ConvertFrom-Json
        $thirdPartySources = @($sourceLock.thirdPartySources | Where-Object { $null -ne $_ })
        if ($thirdPartySources.Count -eq 0) { Fail "对应源码锁中没有第三方源码条目。" }
        foreach ($asset in $thirdPartySources) {
            $artifact = Join-Path (Join-Path $root "source\third_party") $asset.name
            if (-not (Test-Path -LiteralPath $artifact -PathType Leaf)) { Fail "第三方对应源码缺失: $artifact"; continue }
            $hash = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLower()
            if ($hash -ne $asset.sha256 -or (Get-Item -LiteralPath $artifact).Length -ne [int64]$asset.size) {
                Fail "第三方对应源码完整性校验失败: $artifact"
            }
        }
    }

    # --- 7. 版本一致性 ---------------------------------------------------
    $aboutPath = Join-Path $root "UmiOCR-data\about.json"
    if (Test-Path -LiteralPath $aboutPath) {
        $about = Get-Content -Raw $aboutPath | ConvertFrom-Json
        $productVersion = "$($about.version.major).$($about.version.minor).$($about.version.patch)"
        $fileVersion = "$productVersion.0"
        foreach ($relativePath in @("Umi-OCR.exe", "UmiOCR-data\native\UmiOCR-HdrCapture.dll")) {
            $target = Join-Path $root $relativePath
            if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { continue }
            $versionInfo = (Get-Item -LiteralPath $target).VersionInfo
            if ($versionInfo.FileVersion -ne $fileVersion -or $versionInfo.ProductVersion -ne $productVersion) {
                Fail "原生版本号不一致: $relativePath 期望 $fileVersion/$productVersion，实际 $($versionInfo.FileVersion)/$($versionInfo.ProductVersion)"
            }
        }
    }

    # --- 8. 不得残留可移植用户状态 ---------------------------------------
    $dataRoot = Join-Path $root "UmiOCR-data"
    foreach ($name in ".settings", ".pre_settings", "themes.json", "startup_error.log", "logs", "temp", "temp_doc") {
        if (Test-Path -LiteralPath (Join-Path $dataRoot $name)) { Fail "发布包中残留用户状态: UmiOCR-data\$name" }
    }
    if (Test-Path -LiteralPath (Join-Path $dataRoot "plugins\.plugins_state")) {
        Fail "发布包中残留插件启用状态: UmiOCR-data\plugins\.plugins_state"
    }

    # --- 9. 非运行时测试目录 ---------------------------------------------
    $runtimeTestDirs = Get-ChildItem -Recurse -Directory -LiteralPath $sitePackages -ErrorAction SilentlyContinue |
        Where-Object Name -In "test", "tests"
    if ($runtimeTestDirs) { Fail "残留非运行时测试目录: $($runtimeTestDirs.FullName -join ', ')" }
}

# ===================== 插件归档审计 =====================

function Invoke-PluginAudit {
    $pluginsRoot = Join-Path $root "UmiOCR-data\plugins"
    $manifests = if (Test-Path -LiteralPath $pluginsRoot -PathType Container) {
        @(Get-ChildItem -Directory -LiteralPath $pluginsRoot | ForEach-Object {
            Get-Item -LiteralPath (Join-Path $_.FullName "umi-plugin.json") -ErrorAction SilentlyContinue
        })
    } else {
        @()
    }
    if ($manifests.Count -eq 0) { Fail "插件归档中没有 umi-plugin.json 。"; return }

    # 宿主契约版本从仓库源码读取，保证审计与实现不会各说各话
    $hostApiSource = Get-Content -Raw (Join-Path $RepoRoot "UmiOCR-data\py_src\plugins_controller\host_api.py")
    if ($hostApiSource -notmatch 'HOST_API_VERSION\s*=\s*"([^"]+)"') { throw "无法从 host_api.py 读取 HOST_API_VERSION 。" }
    $hostApi = [version]("$($Matches[1])" + ".0")
    Write-Host "宿主 API 版本: $($Matches[1])"

    foreach ($manifestFile in $manifests) {
        $pluginDir = $manifestFile.Directory.FullName
        $pluginId = $manifestFile.Directory.Name
        Write-Host "  插件: $pluginId"
        $manifest = Get-Content -Raw $manifestFile.FullName | ConvertFrom-Json

        if ($manifest.schema_version -ne 1) { Fail "[$pluginId] 不支持的 schema_version: $($manifest.schema_version)" }
        if ($manifest.id -ne $pluginId) { Fail "[$pluginId] 清单 id ($($manifest.id)) 与目录名不一致" }
        if (-not $manifest.version) { Fail "[$pluginId] 清单缺少 version" }
        if (-not $manifest.license) { Fail "[$pluginId] 清单缺少 license" }
        if (-not $manifest.capabilities) { Fail "[$pluginId] 清单未声明 capabilities" }
        if ($manifest.i18n -and -not (Test-Path -LiteralPath (Join-Path $pluginDir $manifest.i18n) -PathType Leaf)) {
            Fail "[$pluginId] 清单声明的 i18n 文件不存在: $($manifest.i18n)"
        }

        # 宿主 API 兼容性：清单声明的范围必须包含当前宿主版本
        $range = [string]$manifest.host_api
        if ($range -and $range -ne "*") {
            foreach ($clause in $range.Split(",")) {
                $clause = $clause.Trim()
                if ($clause -notmatch '^(>=|<=|==|!=|>|<)?\s*([0-9][0-9.]*)$') {
                    Fail "[$pluginId] host_api 子句无法解析: $clause"
                    continue
                }
                $op = if ($Matches[1]) { $Matches[1] } else { "==" }
                $target = [version]("$($Matches[2])".TrimEnd(".") + ".0")
                $ok = switch ($op) {
                    ">=" { $hostApi -ge $target }
                    "<=" { $hostApi -le $target }
                    ">"  { $hostApi -gt $target }
                    "<"  { $hostApi -lt $target }
                    "!=" { $hostApi -ne $target }
                    default { $hostApi -eq $target }
                }
                if (-not $ok) { Fail "[$pluginId] 清单要求 host_api $range，与宿主 $hostApi 不相容" }
            }
        }

        # 能力入口所在模块必须真实存在
        foreach ($capability in @($manifest.capabilities | Where-Object { $null -ne $_ })) {
            if (-not $capability.type) { Fail "[$pluginId] capability 缺少 type" }
            $entry = [string]$capability.entry
            if ($entry -notmatch '^([^:]*):(.+)$') { Fail "[$pluginId] 入口引用非法: $entry"; continue }
            $module = $Matches[1]
            $modulePath = if ($module) { Join-Path $pluginDir ($module.Replace(".", "\") + ".py") } else { Join-Path $pluginDir "__init__.py" }
            if (-not (Test-Path -LiteralPath $modulePath -PathType Leaf)) {
                Fail "[$pluginId] 能力入口模块不存在: $modulePath"
            }
        }

        # 插件页 QML 必须存在。
        # 注意 @($null) 会产出一个含 $null 的单元素数组，因此可选字段一律
        # 先过滤掉 $null ，否则清单没有 pages 时会空转一次并误报。
        foreach ($page in @($manifest.pages | Where-Object { $null -ne $_ })) {
            if (-not (Test-Path -LiteralPath (Join-Path $pluginDir $page.qml) -PathType Leaf)) {
                Fail "[$pluginId] 插件页 QML 不存在: $($page.qml)"
            }
        }

        # 私有运行时：vendor 与 DLL 目录必须真实存在，否则用户解压后必然失败
        foreach ($vendor in @($manifest.runtime.vendor_dirs)) {
            if (-not $vendor) { continue }
            if (-not (Test-Path -LiteralPath (Join-Path $pluginDir $vendor) -PathType Container)) {
                Fail "[$pluginId] 声明的 vendor 目录不存在: $vendor"
            }
        }
        foreach ($dllDir in @($manifest.runtime.dll_dirs)) {
            if (-not $dllDir) { continue }
            $full = Join-Path $pluginDir $dllDir
            if (-not (Get-Item -Path $full -ErrorAction SilentlyContinue)) {
                Fail "[$pluginId] 声明的 DLL 目录不存在: $dllDir"
            }
        }
        $vendorDirs = @($manifest.runtime.vendor_dirs | Where-Object { $null -ne $_ -and $_ })
        if ($vendorDirs.Count -gt 0 -and -not (Test-Path -LiteralPath (Join-Path $pluginDir "runtime-requirements.lock") -PathType Leaf)) {
            Fail "[$pluginId] 私有 vendor 闭包缺少 runtime-requirements.lock"
        }
        if ($pluginId -eq "win32_PaddleOCRv6_CUDA") {
            $aistudio = Get-ChildItem -LiteralPath (Join-Path $pluginDir "vendor") -Filter "aistudio_sdk*" -ErrorAction SilentlyContinue
            if ($aistudio) { Fail "[$pluginId] 禁止携带无再分发许可证的 aistudio-sdk" }
        }

        # 依赖闭包锁：逐项校验存在性与哈希
        $closureName = [string]$manifest.runtime.closure_lock
        if ($closureName) {
            $closurePath = Join-Path $pluginDir $closureName
            if (-not (Test-Path -LiteralPath $closurePath -PathType Leaf)) {
                Fail "[$pluginId] 依赖闭包锁不存在: $closureName"
            }
            else {
                $closure = Get-Content -Raw $closurePath | ConvertFrom-Json
                if (@($closure.files).Count -eq 0) { Fail "[$pluginId] 依赖闭包锁为空" }
                foreach ($entry in @($closure.files)) {
                    $target = Join-Path $pluginDir ([string]$entry.path).Replace("/", "\")
                    if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
                        Fail "[$pluginId] 闭包文件缺失: $($entry.path)"
                        continue
                    }
                    if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLower() -ne $entry.sha256) {
                        Fail "[$pluginId] 闭包文件哈希不匹配: $($entry.path)"
                    }
                }
            }
        }

        # 许可证与对应源码
        $pluginLicenseFiles = @(
            "COPYING", "LICENSE", "NOTICE.md",
            "LICENSES\THIRD_PARTY_NOTICES.md",
            "LICENSES\LGPL-2.1.txt", "LICENSES\LGPL-3.0.txt", "LICENSES\GPL-3.0.txt"
        )
        if ($pluginId -ne "win32_PaddleOCRv6_CPU") { $pluginLicenseFiles += "LICENSES\THIRD_PARTY_COMPONENTS.md" }
        foreach ($name in $pluginLicenseFiles) {
            if (-not (Test-Path -LiteralPath (Join-Path $root $name) -PathType Leaf)) {
                Fail "插件归档缺少 $name"
            }
        }

        $packagedSourceRequired = -not ($LocalCandidate -and $pluginId -eq "win32_PaddleOCRv6_CUDA")
        # 对应源码不是只放在公开仓库里的链接。归档必须保留插件适配器、
        # 构建入口和依赖锁；GPU 插件使用主仓库布局，独立插件使用自身布局。
        $sourceRoot = Join-Path $root "source"
        if ($packagedSourceRequired -and -not (Test-Path -LiteralPath $sourceRoot -PathType Container)) {
            Fail "[$pluginId] 插件归档缺少 source 对应源码镜像"
        }
        elseif ($packagedSourceRequired) {
            $sourceLicenseFiles = @("COPYING", "LICENSE")
            if ($pluginId -eq "win32_PaddleOCRv6_CPU") {
                $sourceLicenseFiles += @(
                    "LICENSES\Apache-2.0.txt", "LICENSES\MPL-2.0.txt",
                    "LICENSES\LGPL-2.1.txt", "LICENSES\LGPL-3.0.txt", "LICENSES\GPL-3.0.txt",
                    "LICENSES\THIRD_PARTY_NOTICES.md"
                )
            }
            else {
                $sourceLicenseFiles += @(
                    "LICENSES\THIRD_PARTY_COMPONENTS.md",
                    "LICENSES\PyMuPDF-AGPL-3.0.txt"
                )
            }
            foreach ($name in $sourceLicenseFiles) {
                if ($packagedSourceRequired -and -not (Test-Path -LiteralPath (Join-Path $sourceRoot $name) -PathType Leaf)) {
                    Fail "[$pluginId] 对应源码镜像缺少 $name"
                }
            }
            $sourcePluginCandidates = @(
                (Join-Path $sourceRoot "UmiOCR-data\plugins\$pluginId\umi-plugin.json"),
                (Join-Path $sourceRoot "$pluginId\umi-plugin.json")
            )
            if (-not ($sourcePluginCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })) {
                Fail "[$pluginId] 对应源码镜像缺少插件清单"
            }
            if (-not (Get-ChildItem -Recurse -File -LiteralPath $sourceRoot -Filter "*.ps1" -ErrorAction SilentlyContinue)) {
                Fail "[$pluginId] 对应源码镜像缺少构建脚本"
            }
            if (-not (Get-ChildItem -Recurse -File -LiteralPath $sourceRoot -Filter "*.lock*" -ErrorAction SilentlyContinue)) {
                Fail "[$pluginId] 对应源码镜像缺少依赖锁"
            }
        }
        elseif ($pluginId -eq "win32_PaddleOCRv6_CUDA") {
            RequireFile "SOURCE-CODE.md" "GPU local-candidate 源码声明"
        }

        # GPU OCR 插件专有：模型与 CUDA 闭包必须齐全
        if ($pluginId -eq "win32_PaddleOCRv6_CUDA") {
            foreach ($name in "LICENSES\Apache-2.0.txt", "LICENSES\model-rights.json",
                               "LICENSES\runtime-vendor-lock.json", "LICENSES\cuda-redistributable.json",
                               "LICENSES\cudnn-redistributable.json", "LICENSES\opencv-artifact.json", "LICENSES\ffmpeg-build.json",
                               "LICENSES\gpu-e2e-evidence.json",
                               "LICENSES\mpl-components.json", "LICENSES\agpl-integration.json",
                               "LICENSES\cpu-document-gates.json", "LICENSES\RELEASE_EVIDENCE.json",
                               "LICENSES\RELEASE_EVIDENCE.md", "LICENSES\evidence\nvidia\cuda-toolkit-eula-2026-08-07.html", "LICENSES\evidence\nvidia\cudnn-sla-2026-08-09.html") {
                if (-not (Test-Path -LiteralPath (Join-Path $root $name) -PathType Leaf)) {
                    Fail "[$pluginId] 缺少 artifact evidence: $name"
                }
                if ($packagedSourceRequired -and -not (Test-Path -LiteralPath (Join-Path $sourceRoot $name) -PathType Leaf)) {
                    Fail "[$pluginId] 对应源码镜像缺少 artifact evidence: $name"
                }
            }
            $gpuSourceLock = Join-Path $sourceRoot "build\sources-windows-cu126.lock.json"
            $ffmpegSource = Join-Path $sourceRoot "third_party\ffmpeg-4.4.4.tar.xz"
            if ($packagedSourceRequired -and -not (Test-Path -LiteralPath $gpuSourceLock -PathType Leaf)) {
                Fail "[$pluginId] 对应源码镜像缺少 source lock"
            }
            elseif ($packagedSourceRequired -and -not (Test-Path -LiteralPath $ffmpegSource -PathType Leaf)) {
                Fail "[$pluginId] 对应源码镜像缺少 FFmpeg source archive"
            }
            elseif ($packagedSourceRequired) {
                $sourceLock = Get-Content -Raw $gpuSourceLock | ConvertFrom-Json
                $asset = @($sourceLock.thirdPartySources | Where-Object { $_.name -eq "ffmpeg-4.4.4.tar.xz" }) | Select-Object -First 1
                if (-not $asset -or (Get-FileHash -LiteralPath $ffmpegSource -Algorithm SHA256).Hash.ToLower() -ne $asset.sha256) {
                    Fail "[$pluginId] FFmpeg source archive hash does not match source lock"
                }
            }
            foreach ($model in "PP-OCRv6_medium_det_infer", "PP-OCRv6_medium_rec_infer",
                               "UVDoc_grid_infer", "PP-LCNet_x1_0_doc_ori_infer",
                               "PP-LCNet_x1_0_textline_ori_infer") {
                if (-not (Test-Path -LiteralPath (Join-Path $pluginDir "models\$model\inference.json") -PathType Leaf)) {
                    Fail "[$pluginId] 缺少模型: models\$model"
                }
            }
            if (-not (Get-ChildItem -Recurse -Directory -LiteralPath $pluginDir -Filter "paddlepaddle_gpu-*.dist-info" -ErrorAction SilentlyContinue)) {
                Fail "[$pluginId] vendor 中缺少 paddlepaddle-gpu"
            }
        }
        # CPU OCR 插件专有：只允许离线 ONNX Runtime CPU 五模型闭包；
        # 具体模型、运行时、源码形式和真实 E2E 均由 artifact verifier 复核。
        elseif ($pluginId -eq "win32_PaddleOCRv6_CPU") {
            $cpuModels = @(
                "PP-LCNet_x1_0_doc_ori", "UVDoc", "PP-LCNet_x1_0_textline_ori",
                "PP-OCRv6_medium_det", "PP-OCRv6_medium_rec"
            )
            foreach ($model in $cpuModels) {
                foreach ($name in "inference.onnx", "README.md", "huggingface-api.json") {
                    if (-not (Test-Path -LiteralPath (Join-Path $pluginDir "models\$model\$name") -PathType Leaf)) {
                        Fail "[$pluginId] 缺少已锁定的 ONNX 模型证据: models\$model\$name"
                    }
                }
            }
            foreach ($name in "model-rights.json", "paddlex-offline-patch.json", "e2e-evidence.json", "runtime-requirements.lock", "runtime.lock.json") {
                if (-not (Test-Path -LiteralPath (Join-Path $pluginDir $name) -PathType Leaf)) {
                    Fail "[$pluginId] 缺少 CPU 运行时/模型证据: $name"
                }
            }
            $vendorRoot = Join-Path $pluginDir "vendor"
            foreach ($pattern in "onnxruntime-*.dist-info", "paddleocr-*.dist-info", "paddlex-*.dist-info", "opencv_contrib_python-*.dist-info") {
                if (-not (Get-ChildItem -Directory -LiteralPath $vendorRoot -Filter $pattern -ErrorAction SilentlyContinue)) {
                    Fail "[$pluginId] 缺少 CPU 运行时发行版: $pattern"
                }
            }
            $forbiddenCpuArtifacts = @("paddle", "paddlepaddle*", "aistudio_sdk*", "huggingface_hub*", "modelscope*", "nvidia*", "*cuda*", "*cudnn*", "*nvinfer*", "*directml*")
            foreach ($pattern in $forbiddenCpuArtifacts) {
                $matches = Get-ChildItem -Recurse -Force -LiteralPath $vendorRoot -ErrorAction SilentlyContinue | Where-Object { $_.Name -like $pattern }
                if ($matches) {
                    Fail "[$pluginId] CPU vendor 包含禁止的推理运行时/下载客户端: $($matches.FullName -join ', ')"
                }
            }
            $cpuEvidence = @(
                "LICENSES\Apache-2.0.txt", "LICENSES\MPL-2.0.txt", "LICENSES\LGPL-2.1.txt", "LICENSES\LGPL-3.0.txt", "LICENSES\GPL-3.0.txt",
                "LICENSES\runtime-vendor-lock.json", "LICENSES\model-rights.json", "LICENSES\opencv-artifact.json", "LICENSES\ffmpeg-build.json",
                "LICENSES\mpl-components.json", "LICENSES\cpu-copyleft-components.json", "LICENSES\cpu-e2e-evidence.json", "LICENSES\cpu-source-mirror.json",
                "LICENSES\cuda-redistributable.json", "LICENSES\cudnn-redistributable.json", "LICENSES\agpl-integration.json", "LICENSES\cpu-document-gates.json",
                "LICENSES\RELEASE_EVIDENCE.json", "LICENSES\RELEASE_EVIDENCE.md"
            )
            foreach ($name in $cpuEvidence) {
                if (-not (Test-Path -LiteralPath (Join-Path $root $name) -PathType Leaf)) { Fail "[$pluginId] 缺少 artifact evidence: $name" }
                if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot $name) -PathType Leaf)) { Fail "[$pluginId] 对应源码镜像缺少 artifact evidence: $name" }
            }
            foreach ($name in "cpu-source-closure.json", "third_party\certifi-2026.7.22.tar.gz", "third_party\python_bidi-0.6.11.tar.gz", "third_party\geos-3.13.1.tar.bz2",
                               "third_party\pypdfium2-5.12.1-py3-none-win_amd64.whl", "third_party\pypdfium2-5.12.1.tar.gz",
                               "third_party\pypdfium2-pypi-5.12.1.json", "third_party\pypdfium2-pypi-wheel-provenance-5.12.1.json",
                               "third_party\pypdfium2-release-5.12.1.github.json", "third_party\pypdfium2-wheel-source-4a2636051ff4a841966be01484f4a70b4309b55c.github.json",
                               "third_party\pypdfium2-tag-5.12.1.github.json", "third_party\pdfium-binaries-chromium-7947.github.json",
                               "third_party\pdfium-binaries-commit-a068e5317bb780d0afdf00d8b341938d9f36d2fe.github.json", "third_party\pdfium-win-x64.tgz",
                               "tools\patch_paddlex_cpu_offline.py", "tools\generate_cpu_model_rights.py", "tools\generate_cpu_runtime_requirements.py",
                               "tools\generate_cpu_source_closure.py", "tools\generate_runtime_lock.py", "tools\run_cpu_e2e.py") {
                if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot $name) -PathType Leaf)) {
                    Fail "[$pluginId] 对应源码镜像缺少 CPU 闭包文件: $name"
                }
            }
            $cpuReportPath = Join-Path $root "LICENSES\RELEASE_EVIDENCE.json"
            if (Test-Path -LiteralPath $cpuReportPath -PathType Leaf) {
                $cpuReport = Get-Content -Raw $cpuReportPath | ConvertFrom-Json
                $expectedGates = @{ runtime_vendor = "PASS"; paddle_models = "PASS"; opencv = "PASS"; mpl = "PASS"; cpu_ocr = "PASS"; cuda = "NOT_INCLUDED"; cudnn = "NOT_INCLUDED"; ffmpeg = "NOT_INCLUDED"; agpl_nvidia = "NOT_INCLUDED"; document_models = "NOT_INCLUDED" }
                if ($cpuReport.artifact_kind -ne "cpu" -or (-not $LocalCandidate -and -not $cpuReport.public_prerelease_allowed)) {
                    Fail "[$pluginId] CPU release evidence 未声明可公开的独立 CPU artifact"
                }
                foreach ($gate in $expectedGates.Keys) {
                    if ($cpuReport.gates.$gate -ne $expectedGates[$gate]) { Fail "[$pluginId] CPU evidence gate 不匹配: $gate" }
                }
            }
        }
    }
}

# ===================== 执行 =====================

switch ($Kind) {
    "base" { Invoke-BaseAudit }
    "plugin" { Invoke-PluginAudit }
}

if ($failures.Count -gt 0) {
    Write-Host ""
    Write-Host "审计未通过，共 $($failures.Count) 项：" -ForegroundColor Red
    foreach ($item in $failures) { Write-Host "  - $item" -ForegroundColor Red }
    exit 1
}
Write-Host ""
if ($Kind -eq "base") {
    Write-Host "基础包审计通过：运行时闭包完整、无任何 OCR 推理后端、许可证与对应源码齐备。"
}
else {
    Write-Host "插件归档审计通过：清单合法、宿主 API 相容、依赖闭包完整、许可证齐备。"
}
# Do not leak a previous native command's exit status into the caller when
# this script's own audit has succeeded.
exit 0
