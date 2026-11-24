#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SourceRoot,
    [Parameter(Mandatory)][string]$PythonRoot,
    [Parameter(Mandatory)][string]$NumpySitePackages,
    [Parameter(Mandatory)][string]$WorkRoot,
    [Parameter(Mandatory)][string]$AuditRoot,
    [Parameter(Mandatory)][string]$NasmExecutable,
    [ValidateRange(1,4)][int]$Jobs = 2
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
function Plain([string]$Value) {
    $full = [IO.Path]::GetFullPath($Value)
    foreach ($node in @($full) + @(for ($parent = Split-Path -Parent $full; $parent; $parent = Split-Path -Parent $parent) { $parent })) {
        if ((Test-Path -LiteralPath $node) -and ((Get-Item -Force -LiteralPath $node).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "拒绝链接原生工作路径：$node" }
    }
    return $full
}
$SourceRoot = Plain $SourceRoot
$PythonRoot = Plain $PythonRoot
$NumpySitePackages = Plain $NumpySitePackages
$NasmExecutable = Plain $NasmExecutable
if (-not (Test-Path -LiteralPath $NasmExecutable -PathType Leaf) -or
    (Get-FileHash -LiteralPath $NasmExecutable -Algorithm SHA256).Hash.ToLowerInvariant() -ne '04ec2385879f7e1c45dbe76c4020970555de48eeb97c23f59620ede061328f51') { throw '须使用已核验摘要的便携NASM3.02，以保留JPEG SIMD' }
$nasmVersion = (& $NasmExecutable -v).Trim()
if ($LASTEXITCODE -ne 0 -or -not $nasmVersion.StartsWith('NASM version 3.02 ')) { throw '实际NASM版本不符' }
$WorkRoot = Plain $WorkRoot
$AuditRoot = Plain $AuditRoot
$allowed = @((Join-Path $repo 'build'), 'E:\Umi-OCR-build\dependency-trim-20261114-r1')
if (-not @($allowed | Where-Object { $WorkRoot.StartsWith($_ + '\', [StringComparison]::OrdinalIgnoreCase) }).Count) { throw '原生构建必须位于本轮批准工作根内' }
if (-not $AuditRoot.StartsWith((Join-Path $repo 'build/audit') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '审计输出必须位于本项目build/audit内' }
foreach ($path in @($WorkRoot, $AuditRoot)) { if (Test-Path -LiteralPath $path) { throw "只允许新构建/审计目录：$path" } }
$head = (& git -C $SourceRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $head -ne '71d3237a093b60a27601c20e9ee6c3e52154e8b1') { throw 'OpenCV源码提交不符' }
$dirty = @(& git -C $SourceRoot status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0 -or $dirty.Count) { throw 'OpenCV受控源码已变更，不以原始构建冒充' }
$python = Join-Path $PythonRoot 'python.exe'
$headers = Join-Path $PythonRoot 'include'
$pythonLib = Join-Path $PythonRoot 'libs/python313.lib'
$numpyHeaders = Join-Path $NumpySitePackages 'numpy/_core/include'
foreach ($path in @($python, (Join-Path $headers 'Python.h'), $pythonLib, (Join-Path $numpyHeaders 'numpy/arrayobject.h'))) { if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "缺少明确构建输入：$path" } }
$version = (& $python -I -B -S -c 'import sys;print(sys.version)').Trim()
if ($LASTEXITCODE -ne 0 -or -not $version.StartsWith('3.13.16 ')) { throw '须使用匹配目标的Python 3.13.16便携SDK' }
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$vs = (& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath).Trim()
if ($LASTEXITCODE -ne 0 -or -not $vs) { throw '未找到可用MSVC x64工具链' }
Import-Module (Join-Path $vs 'Common7/Tools/Microsoft.VisualStudio.DevShell.dll')
Enter-VsDevShell -VsInstallPath $vs -Arch x64 -HostArch x64 -SkipAutomaticLocation
$cmake = (Get-Command cmake.exe).Source
$ninja = (Get-Command ninja.exe).Source
$cl = (Get-Command cl.exe).Source
$build = Join-Path $WorkRoot 'cmake'
$install = Join-Path $WorkRoot 'install'
$temp = Join-Path $WorkRoot 'tmp'
New-Item -ItemType Directory -Path $WorkRoot,$AuditRoot,$temp | Out-Null
$options = [ordered]@{
    CMAKE_BUILD_TYPE='Release'; CMAKE_MAKE_PROGRAM=$ninja; CMAKE_INSTALL_PREFIX=$install
    CMAKE_POLICY_VERSION_MINIMUM='3.5'; CMAKE_MSVC_RUNTIME_LIBRARY='MultiThreaded'
    CMAKE_ASM_NASM_COMPILER=$NasmExecutable; ENABLE_LIBJPEG_TURBO_SIMD='ON'
    BUILD_LIST='core,imgproc,imgcodecs,python3'; BUILD_SHARED_LIBS='OFF'; BUILD_WITH_STATIC_CRT='ON'
    BUILD_TESTS='OFF'; BUILD_PERF_TESTS='OFF'; BUILD_EXAMPLES='OFF'; BUILD_DOCS='OFF'; BUILD_opencv_apps='OFF'
    BUILD_opencv_python2='OFF'; BUILD_opencv_python3='ON'; OPENCV_PYTHON3_VERSION='3.13.16'; PYTHON3_LIMITED_API='OFF'
    PYTHON3_EXECUTABLE=$python; PYTHON3_INCLUDE_DIR=$headers; PYTHON3_LIBRARY=$pythonLib; PYTHON3_LIBRARIES=$pythonLib
    PYTHON3_NUMPY_INCLUDE_DIRS=$numpyHeaders; PYTHON3_NUMPY_VERSION='2.3.5'; OPENCV_PYTHON_INSTALL_PATH='python'
    WITH_FFMPEG='OFF'; WITH_GSTREAMER='OFF'; WITH_MSMF='OFF'; WITH_DSHOW='OFF'; WITH_V4L='OFF'
    WITH_OPENNI='OFF'; WITH_OPENNI2='OFF'; WITH_QT='OFF'; WITH_GTK='OFF'; WITH_VTK='OFF'; WITH_WIN32UI='OFF'
    WITH_CUDA='OFF'; WITH_CUDNN='OFF'; WITH_OPENCL='OFF'; WITH_OPENCL_D3D11_NV='OFF'
    WITH_IPP='OFF'; WITH_ITT='OFF'; WITH_TBB='OFF'; WITH_OPENVINO='OFF'; WITH_ADE='OFF'; BUILD_opencv_gapi='OFF'
    OPENCV_ENABLE_NONFREE='OFF'; OPENCV_GENERATE_PKGCONFIG='OFF'; INSTALL_C_EXAMPLES='OFF'; INSTALL_PYTHON_EXAMPLES='OFF'
    ENABLE_LTO='ON'; OPENCV_DOWNLOAD_PATH=(Join-Path $WorkRoot 'download-cache')
}
$configure = @('-S',$SourceRoot,'-B',$build,'-G','Ninja')
foreach ($key in $options.Keys) { $configure += "-D${key}=$(([string]$options[$key]).Replace('\','/'))" }
$buildArgs = @('--build',$build,'--target','opencv_python3','--parallel',"$Jobs")
$oldEnvironment = @{}
foreach ($name in @('TEMP','TMP','PYTHONDONTWRITEBYTECODE','PYTHONNOUSERSITE','PYTHONPATH','PYTHONHOME')) { $oldEnvironment[$name] = [Environment]::GetEnvironmentVariable($name) }
$record = [ordered]@{
    status='RUNNING'; startedUtc=[DateTime]::UtcNow.ToString('o'); sourceRoot=$SourceRoot; sourceCommit=$head
    pythonVersion=$version; numpyHeaders=$numpyHeaders; options=$options; jobs=$Jobs; compiler=$cl
    nasmExecutable=$NasmExecutable; nasmVersion=$nasmVersion; nasmSha256=(Get-FileHash -LiteralPath $NasmExecutable -Algorithm SHA256).Hash.ToLowerInvariant()
    cmake=$cmake; cmakeVersion=(& $cmake --version) -join "`n"; ninja=$ninja; workRoot=$WorkRoot; installRoot=$install
    sourceChanged=$false; target='Windows x64 CPython 3.13'; cxxBaseline='OpenCV upstream default; no language-standard override'
    configureArgv=@($cmake)+$configure; buildArgv=@($cmake)+$buildArgs
    boundary='仅新原生构建目录；不替换固定安装、不运行模型、不修改系统工具链或全局环境；编译完成不代表运行验收通过。'
}
Copy-Item -LiteralPath $PSCommandPath -Destination (Join-Path $AuditRoot 'build-script.ps1')
$record.buildScriptSha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
$record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $AuditRoot 'inputs.json') -Encoding utf8NoBOM
try {
    $env:TEMP=$temp; $env:TMP=$temp; $env:PYTHONDONTWRITEBYTECODE='1'; $env:PYTHONNOUSERSITE='1'
    $env:PYTHONPATH=$NumpySitePackages; $env:PYTHONHOME=$PythonRoot
    & $cmake @configure 2>&1 | Tee-Object -FilePath (Join-Path $AuditRoot 'configure.log')
    if ($LASTEXITCODE -ne 0) { throw '最小OpenCV配置失败，保留日志，不覆盖/强制重跑该目录' }
    & $cmake @buildArgs 2>&1 | Tee-Object -FilePath (Join-Path $AuditRoot 'compile.log')
    if ($LASTEXITCODE -ne 0) { throw '最小OpenCV编译失败' }
    & $cmake --install $build --component python 2>&1 | Tee-Object -FilePath (Join-Path $AuditRoot 'install.log')
    if ($LASTEXITCODE -ne 0) { throw 'OpenCV Python构件安装失败' }
    $binaries = @(Get-ChildItem -LiteralPath (Join-Path $install 'python') -Recurse -File -Filter '*.pyd')
    if ($binaries.Count -ne 1) { throw '最小OpenCV应生成唯一Python绑定构件' }
    $after = @(& git -C $SourceRoot status --porcelain --untracked-files=no)
    if ($LASTEXITCODE -ne 0 -or $after.Count) { throw '编译期间OpenCV原始源码变更' }
    $record.status='COMPILED_NOT_RUNTIME_ACCEPTED'
    $record.binaries=@($binaries | ForEach-Object { @{path=$_.FullName; bytes=$_.Length; sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()} })
    Copy-Item -LiteralPath (Join-Path $build 'CMakeCache.txt') -Destination (Join-Path $AuditRoot 'CMakeCache.txt')
} catch {
    $record.status='FAILED'; $record.error=$_.Exception.Message
    throw
} finally {
    $record.finishedUtc=[DateTime]::UtcNow.ToString('o')
    $record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $AuditRoot 'result.json') -Encoding utf8NoBOM
    foreach ($name in $oldEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name,$oldEnvironment[$name],'Process') }
}
