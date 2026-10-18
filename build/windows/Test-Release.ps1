[CmdletBinding()]
<#
.SYNOPSIS
    发布回归套件。

.DESCRIPTION
    2.7 起 OCR 推理不在基础包里，回归也随之分成两档：

      base      只测基础包：Qt/QML 闭包、图像解码、文件导入、可移植设置、
                截图坐标、HDR、插件契约。【不需要】任何 OCR 后端 ——
                基础包能在零后端状态下正常启动与运行，正是本次要验证的新能力。

      combined  基础包 + 已解压的 GPU OCR 插件：在 base 之上补充 OCR 工作流、
                HTTP/CLI OCR、UVDoc 坐标、可选模型剥离与启动惰性检查。

.PARAMETER Kind
    base 或 combined 。省略时按插件目录是否存在自动判定。
#>
param(
    [string]$StagingRoot = "",
    [string]$Device = "gpu:0",
    [ValidateSet("base", "combined", "auto")][string]$Kind = "auto",
    [switch]$SkipScreenshotCapture
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $StagingRoot) {
    $StagingRoot = Join-Path $RepoRoot "build\staging\Umi-OCR_Windows_x64"
}
$StagingRoot = (Resolve-Path -LiteralPath $StagingRoot).Path
$DataRoot = Join-Path $StagingRoot "UmiOCR-data"
$Python = Join-Path $DataRoot "runtime\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { throw "Portable Python is missing: $Python" }
if (-not (Test-Path -LiteralPath (Join-Path $StagingRoot "Umi-OCR.exe"))) {
    throw "Umi-OCR.exe is missing: $StagingRoot"
}

$PluginRoot = Join-Path $DataRoot "plugins\win32_PaddleOCRv6_CUDA"
if ($Kind -eq "auto") {
    $Kind = if (Test-Path -LiteralPath (Join-Path $PluginRoot "umi-plugin.json")) { "combined" } else { "base" }
}
Write-Host "Regression tier: $Kind"

function Invoke-PortablePython([string]$Script, [string[]]$TestArguments = @()) {
    # -I ignores PYTHON* environment variables, so use -B explicitly.
    & $Python -B -I -S -X utf8 (Join-Path $RepoRoot $Script) @TestArguments
    if ($LASTEXITCODE -ne 0) { throw "Release test failed: $Script" }
}

# ===================== 基础档（无 OCR 后端）=====================

Invoke-PortablePython "tests\test_plugin_contract.py"
Invoke-PortablePython "tests\test_mission_runtime.py" @($DataRoot)
Invoke-PortablePython "tests\test_plugin_services.py" @($DataRoot)
Invoke-PortablePython "tests\test_optional_backend_configs.py" @($DataRoot)
Invoke-PortablePython "tests\test_utf8_runtime.py" @($DataRoot, (Join-Path $StagingRoot "Umi-OCR.exe"))
Invoke-PortablePython "tests\test_http_api.py" @("--data-root", $DataRoot, "--packaged")
Invoke-PortablePython "build\tools\qt_startup_smoke.py" @($DataRoot, (Join-Path $StagingRoot "Umi-OCR.exe"))
Invoke-PortablePython "tests\test_qt_runtime.py" @($DataRoot)
Invoke-PortablePython "tests\test_image_viewer_qml.py" @($DataRoot)
Invoke-PortablePython "tests\test_image_decoder.py" @($DataRoot)
Invoke-PortablePython "tests\test_file_import.py" @($DataRoot)
Invoke-PortablePython "tests\test_portable_settings.py" @($DataRoot)
Invoke-PortablePython "tests\test_capture_geometry.py"
Invoke-PortablePython "tests\test_hdr_shader.py" @((Join-Path $DataRoot "native\UmiOCR-HdrCapture.dll"))
if (-not $SkipScreenshotCapture) {
    Invoke-PortablePython "tests\test_screenshot_capture.py" @($DataRoot)
}

if ($Kind -eq "base") {
    Write-Host "Base regression suite passed (no OCR backend installed): $StagingRoot"
    return
}

# ===================== 联合档（基础包 + GPU OCR 插件）=====================

# 该测试在临时目录里自建样本，不需要传入路径。
Invoke-PortablePython "tests\test_optional_model_strip.py"
Invoke-PortablePython "tests\test_cuda_worker_client.py" @($DataRoot)
Invoke-PortablePython "build\tools\staging_smoke.py" @($DataRoot, "--device", $Device)
Invoke-PortablePython "tests\test_startup_runtime.py" @($DataRoot)
Invoke-PortablePython "tests\test_uvdoc_coordinates.py" @($DataRoot)
Invoke-PortablePython "tests\test_ocr_workflows.py" @($DataRoot, "--device", $Device)
Invoke-PortablePython "tests\test_http_cli.py" @($StagingRoot)

Write-Host "Combined regression suite passed (base + GPU OCR plugin): $StagingRoot"
