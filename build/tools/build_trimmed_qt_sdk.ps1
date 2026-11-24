#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SourceRoot,
    [Parameter(Mandatory)][string]$PythonRoot,
    [Parameter(Mandatory)][string]$WorkRoot,
    [Parameter(Mandatory)][string]$AuditRoot,
    [string]$ReuseBaseSdkRoot = '',
    [string]$ReuseBaseSdkRecord = '',
    [ValidateRange(1,4)][int]$Jobs = 2
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
function Plain([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    for ($item = $full; $item; $item = Split-Path -Parent $item) {
        if ((Test-Path -LiteralPath $item) -and ((Get-Item -Force -LiteralPath $item).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "拒绝链接路径：$item" }
    }
    return $full
}
$SourceRoot = Plain $SourceRoot; $PythonRoot = Plain $PythonRoot
$WorkRoot = Plain $WorkRoot; $AuditRoot = Plain $AuditRoot
$nativeRoot = 'E:\Umi-OCR-build\dependency-trim-20261114-r1'
if (-not $WorkRoot.StartsWith($nativeRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Qt SDK构建限本轮独立工作根' }
if (-not $AuditRoot.StartsWith((Join-Path $repo 'build/audit') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '审计限本项目build/audit' }
foreach ($path in @($WorkRoot,$AuditRoot)) { if (Test-Path -LiteralPath $path) { throw "拒绝覆盖旧构建/审计：$path" } }
# 保留实际PySide绑定所需的Qt公开API；这里先建立一致的SDK，WebEngine另行裁切。
$pins = [ordered]@{
    qtbase='ef55f427f2c8b410d34f8a7681020a3000cf6866'
    qtshadertools='c70b59ea4a47ccbee7e0d0353b9e91d719120bfd'
    qtdeclarative='4e3399c26ec57246c08de019cfcbda8d23604cfa'
    qtwebchannel='4d6a7ec14efc38ed09e55403b0843719539d162a'
    qtsvg='17ca512f903f935282ebeca496aac5d11ba4199a'
    qtimageformats='47b6139dda3b84d1d3ec15caf8d04eff8d744c8d'
    qt5compat='abebcdb4964aa1f9ca01b97d793ed57d305d2a66'
}
foreach ($name in $pins.Keys) {
    $source = Plain (Join-Path $SourceRoot "$name-6.11.2")
    $head = (& git -C $source rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $head -ne $pins[$name]) { throw "$name 固定提交不符" }
    $dirty = @(& git -C $source status --porcelain --untracked-files=no)
    if ($LASTEXITCODE -ne 0 -or $dirty.Count) { throw "$name 受控源码有变化" }
}
$reuseRecord = $null
if ($ReuseBaseSdkRoot -or $ReuseBaseSdkRecord) {
    if (-not $ReuseBaseSdkRoot -or -not $ReuseBaseSdkRecord) { throw '复用SDK必须同时指定原目录和真实构建记录' }
    $ReuseBaseSdkRoot = Plain $ReuseBaseSdkRoot; $ReuseBaseSdkRecord = Plain $ReuseBaseSdkRecord
    if (-not $ReuseBaseSdkRoot.StartsWith($nativeRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or -not (Test-Path -LiteralPath $ReuseBaseSdkRoot -PathType Container)) { throw '复用仅限本轮独立原生工作根的SDK' }
    $reuseRecord = Get-Content -Raw -LiteralPath $ReuseBaseSdkRecord | ConvertFrom-Json
    if ($reuseRecord.installRoot -ne $ReuseBaseSdkRoot -or $reuseRecord.qtVersion -ne '6.11.2') { throw '复用SDK身份与原记录不符' }
    if (@($reuseRecord.modules).Count -ne 2) { throw '只支持复用已完成的QtBase和ShaderTools SDK，不猜测其它部分完成状态' }
    foreach ($name in @('qtbase','qtshadertools')) {
        $entry = @($reuseRecord.modules | Where-Object module -eq $name)
        if ($entry.Count -ne 1 -or $entry[0].commit -ne $pins[$name] -or $entry[0].status -ne 'SDK_COMPILED_NOT_RUNTIME_ACCEPTED') { throw "$name 没有匹配的真实编译记录" }
    }
}
$python = Join-Path $PythonRoot 'python.exe'
$version = (& $python -I -B -S -c 'import sys;print(sys.version)').Trim()
if ($LASTEXITCODE -ne 0 -or -not $version.StartsWith('3.13.16 ')) { throw 'Qt构建工具使用匹配的固定Python SDK' }
$free = (Get-PSDrive -Name ([IO.Path]::GetPathRoot($WorkRoot).Substring(0,1))).Free
if ($free -lt 40GB) { throw 'Qt SDK构建预留至少40GiB，不创建构建目录' }
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$vs = (& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath).Trim()
if ($LASTEXITCODE -ne 0 -or -not $vs) { throw '缺少MSVC工具链' }
Import-Module (Join-Path $vs 'Common7/Tools/Microsoft.VisualStudio.DevShell.dll')
Enter-VsDevShell -VsInstallPath $vs -Arch x64 -HostArch x64 -SkipAutomaticLocation
$cmake = (Get-Command cmake.exe).Source
$ninja = (Get-Command ninja.exe).Source
$compiler = (Get-Command cl.exe).Source
if ($compiler -notlike '*14.51.36231*') { throw '未实际选择本轮已核对的MSVC14.51.36231工具链' }
$install = Join-Path $WorkRoot 'install'
$temp = Join-Path $WorkRoot 'tmp'
New-Item -ItemType Directory -Path $WorkRoot,$AuditRoot,$temp | Out-Null
$record = [ordered]@{
    status='RUNNING'; startedUtc=[DateTime]::UtcNow.ToString('o'); qtVersion='6.11.2'
    sources=$pins; sourceRoot=$SourceRoot; workRoot=$WorkRoot; installRoot=$install
    compiler=$compiler; compilerSha256=(Get-FileHash -LiteralPath $compiler -Algorithm SHA256).Hash.ToLowerInvariant()
    cmake=$cmake; cmakeVersion=(& $cmake --version) -join "`n"; ninja=$ninja
    python=$python; pythonVersion=$version; jobs=$Jobs; initialFreeBytes=$free
    modules=@(); boundary='只生成新SDK；不修改系统环境或固定安装；不代表WebEngine已禁用FFmpeg或运行包通过。'
}
Copy-Item -LiteralPath $PSCommandPath -Destination (Join-Path $AuditRoot 'build-script.ps1')
$record.buildScriptSha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
$old = @{}
foreach ($name in @('TEMP','TMP','PYTHONDONTWRITEBYTECODE','PYTHONHOME','PYTHONPATH')) { $old[$name]=[Environment]::GetEnvironmentVariable($name) }
try {
    $env:TEMP=$temp; $env:TMP=$temp; $env:PYTHONDONTWRITEBYTECODE='1'
    $env:PYTHONHOME=$PythonRoot; $env:PYTHONPATH=''
    if ($reuseRecord) {
        if ($reuseRecord.compilerSha256 -ne $record.compilerSha256) { throw '复用SDK与当前编译器字节不同' }
        $processes = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($ReuseBaseSdkRoot + '\', [StringComparison]::OrdinalIgnoreCase) })
        if ($processes.Count) { throw '复用SDK有活动工具进程，停止复制，不终止进程' }
        $items = @(Get-ChildItem -LiteralPath $ReuseBaseSdkRoot -Force -Recurse)
        if (@($items | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw '复用SDK含链接，拒绝复制' }
        $sourceFiles = @($items | Where-Object { -not $_.PSIsContainer })
        if (-not $sourceFiles.Count -or $sourceFiles.Count -gt 100000 -or ($sourceFiles | Measure-Object -Property Length -Sum).Sum -gt 10GB) { throw '复用SDK文件数量/大小超过预算' }
        $binding = [ordered]@{}
        New-Item -ItemType Directory -Path $install | Out-Null
        foreach ($file in $sourceFiles) {
            $relative = [IO.Path]::GetRelativePath($ReuseBaseSdkRoot, $file.FullName)
            $checksum = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            $destination = Join-Path $install $relative
            New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
            [IO.File]::Copy($file.FullName, $destination, $false)
            if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant() -ne $checksum) { throw "复用SDK复制不符：$relative" }
            $binding[$relative.Replace('\','/')] = $checksum
        }
        $binding | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $AuditRoot 'reused-sdk-payload.json') -Encoding utf8NoBOM
        $record.reusedSdk = @{ source=$ReuseBaseSdkRoot; destination=$install; record=$ReuseBaseSdkRecord; recordSha256=(Get-FileHash -LiteralPath $ReuseBaseSdkRecord -Algorithm SHA256).Hash.ToLowerInvariant(); files=$sourceFiles.Count; scope='只逐字节复用本轮已编译的QtBase和ShaderTools，不声称本次重新编译；新模块在全新目录构建。' }
    }
    foreach ($name in $pins.Keys) {
        if ($reuseRecord -and $name -in @('qtbase','qtshadertools')) { continue }
        $source = Join-Path $SourceRoot "$name-6.11.2"
        $build = Join-Path $WorkRoot $name
        $moduleAudit = Join-Path $AuditRoot $name
        New-Item -ItemType Directory -Path $moduleAudit | Out-Null
        $options = [ordered]@{
            CMAKE_BUILD_TYPE='Release'; CMAKE_INSTALL_PREFIX=$install; CMAKE_PREFIX_PATH=$install
            CMAKE_MAKE_PROGRAM=$ninja; CMAKE_C_COMPILER=$compiler; CMAKE_CXX_COMPILER=$compiler
            CMAKE_MSVC_RUNTIME_LIBRARY='MultiThreadedDLL'; BUILD_SHARED_LIBS='ON'
            QT_BUILD_TESTS='OFF'; QT_BUILD_EXAMPLES='OFF'; QT_BUILD_BENCHMARKS='OFF'
            QT_BUILD_MANUAL_TESTS='OFF'; QT_BUILD_DOCS='OFF'; Python3_EXECUTABLE=$python
        }
        if ($name -eq 'qtbase') { $options.QT_FEATURE_sql='OFF'; $options.QT_FEATURE_testlib='OFF' }
        if ($name -eq 'qtdeclarative') {
            $options.FEATURE_quickcontrols2_basic='ON'
            foreach ($style in @('fusion','imagine','material','universal','fluentwinui3','stylekit','macos','ios','windows')) { $options["FEATURE_quickcontrols2_$style"]='OFF' }
        }
        $argv=@('-S',$source,'-B',$build,'-G','Ninja')
        foreach ($key in $options.Keys) { $argv += "-D${key}=$(([string]$options[$key]).Replace('\','/'))" }
        $moduleRecord=[ordered]@{module=$name; commit=$pins[$name]; configureArgv=@($cmake)+$argv; startedUtc=[DateTime]::UtcNow.ToString('o'); status='RUNNING'}
        $moduleRecord | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $moduleAudit 'inputs.json') -Encoding utf8NoBOM
        & $cmake @argv 2>&1 | Tee-Object -FilePath (Join-Path $moduleAudit 'configure.log')
        if ($LASTEXITCODE -ne 0) { throw "$name 配置失败" }
        Copy-Item -LiteralPath (Join-Path $build 'CMakeCache.txt') -Destination (Join-Path $moduleAudit 'CMakeCache.txt')
        & $cmake --build $build --parallel $Jobs 2>&1 | Tee-Object -FilePath (Join-Path $moduleAudit 'compile.log')
        if ($LASTEXITCODE -ne 0) { throw "$name 编译失败" }
        & $cmake --install $build 2>&1 | Tee-Object -FilePath (Join-Path $moduleAudit 'install.log')
        if ($LASTEXITCODE -ne 0) { throw "$name 安装SDK失败" }
        $dirty=@(& git -C $source status --porcelain --untracked-files=no)
        if ($LASTEXITCODE -ne 0 -or $dirty.Count) { throw "$name 构建期间受控源码发生变化" }
        $moduleRecord.status='SDK_COMPILED_NOT_RUNTIME_ACCEPTED'
        $moduleRecord.finishedUtc=[DateTime]::UtcNow.ToString('o')
        $moduleRecord | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $moduleAudit 'result.json') -Encoding utf8NoBOM
        $record.modules+=@($moduleRecord)
    }
    $record.status='SDK_COMPILED_NOT_RUNTIME_ACCEPTED'
} catch {
    $record.status='FAILED'; $record.error=$_.Exception.Message
    throw
} finally {
    $record.finishedUtc=[DateTime]::UtcNow.ToString('o')
    $record | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $AuditRoot 'result.json') -Encoding utf8NoBOM
    foreach ($name in $old.Keys) { [Environment]::SetEnvironmentVariable($name,$old[$name],'Process') }
}
