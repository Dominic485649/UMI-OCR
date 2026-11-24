#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SourceRoot,
    [Parameter(Mandatory)][string]$SdkRecord,
    [Parameter(Mandatory)][string]$PythonRoot,
    [Parameter(Mandatory)][string]$NativeToolsRecord,
    [Parameter(Mandatory)][string]$GperfRecord,
    [Parameter(Mandatory)][string]$PythonToolsRecord,
    [Parameter(Mandatory)][string]$WorkRoot,
    [Parameter(Mandatory)][string]$AuditRoot,
    [ValidateRange(1,4)][int]$Jobs = 2
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$nativeRoot='E:\Umi-OCR-build\dependency-trim-20261114-r1'
function Plain([string]$Path) {
    $full=[IO.Path]::GetFullPath($Path)
    for ($node=$full; $node; $node=Split-Path -Parent $node) {
        if ((Test-Path -LiteralPath $node) -and ((Get-Item -Force -LiteralPath $node).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "拒绝链接原生路径：$node" }
    }
    return $full
}
foreach ($name in @('SourceRoot','SdkRecord','PythonRoot','NativeToolsRecord','GperfRecord','PythonToolsRecord','WorkRoot','AuditRoot')) { Set-Variable -Name $name -Value (Plain (Get-Variable -Name $name -ValueOnly)) }
if (-not $WorkRoot.StartsWith($nativeRoot+'\',[StringComparison]::OrdinalIgnoreCase)) { throw '构建限本轮独立工作根' }
if (-not $AuditRoot.StartsWith((Join-Path $repo 'build/audit')+'\',[StringComparison]::OrdinalIgnoreCase)) { throw '审计限本项目build/audit' }
foreach ($path in @($WorkRoot,$AuditRoot)) { if (Test-Path -LiteralPath $path) { throw "拒绝覆盖旧构建/审计：$path" } }
$sourceCmake=Join-Path $SourceRoot 'src/core/CMakeLists.txt'
if ((Get-FileHash -LiteralPath $sourceCmake -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'ff64fa94fee12e101e0befd2a3b92a2e65c643410bdae16cee0ba736556abe72') { throw 'QtWebEngine来源/无FFmpeg补丁不符' }
$patch=Join-Path $repo 'build/patches/qtwebengine-6.11.2-disable-ffmpeg.patch'
if ((Get-FileHash -LiteralPath $patch -Algorithm SHA256).Hash.ToLowerInvariant() -ne '238cac22228d98b2f3c648c026f1f07dae49abda02dda01b168c4b1f22d89d01') { throw '派生补丁本身变化，须重新审查其来源记录' }
$wrapper=Plain (Join-Path $repo 'build/tools/normalize_msvc_paths.py')
$wrapperSha256=(Get-FileHash -LiteralPath $wrapper -Algorithm SHA256).Hash.ToLowerInvariant()
if ($wrapperSha256 -ne '66379469e58114becc19fbfe459bc74011f098bfb6f0c3dca33e94ebc1ec4661') { throw 'MSVC路径包装器变化，须重做参数保持与原失败命令探针' }
$docCmake=Join-Path $SourceRoot 'src/core/api/CMakeLists.txt'
$docPatch=Join-Path $repo 'build/patches/qtwebengine-6.11.2-no-doc-target-guard.patch'
if ((Get-FileHash -LiteralPath $docCmake -Algorithm SHA256).Hash.ToLowerInvariant() -ne '2a8442f2ab6517e6800c59597d99210cc8c37be086c4a957c65bd1605dec7184' -or
    (Get-FileHash -LiteralPath $docPatch -Algorithm SHA256).Hash.ToLowerInvariant() -ne '91729f37343c48b7788113e446a5b8f8793c06430e5a58a0ff90580b71c87b1a') { throw '关闭文档的最小目标保护补丁身份不符' }
$nativeTools=Get-Content -Raw -LiteralPath $NativeToolsRecord | ConvertFrom-Json
$gperfTools=Get-Content -Raw -LiteralPath $GperfRecord | ConvertFrom-Json
$pythonTools=Get-Content -Raw -LiteralPath $PythonToolsRecord | ConvertFrom-Json
if ($nativeTools.status -ne 'FETCHED_GPERF_SOURCE_NOT_COMPILED' -or $gperfTools.status -ne 'COMPILED_GENERATOR_VERSION_VERIFIED' -or $pythonTools.status -ne 'VERIFIED_BUILD_TOOL_IMPORTS') { throw '生成工具/构建Python依赖没有通过输入与实际运行验证' }
$flex=Plain $nativeTools.winflexbison.'win_flex.exe'.path
$bison=Plain $nativeTools.winflexbison.'win_bison.exe'.path
$gperf=Plain $gperfTools.executable
$pythonSite=Plain $pythonTools.sitePackages
foreach ($item in @(@($flex,$nativeTools.winflexbison.'win_flex.exe'.sha256),@($bison,$nativeTools.winflexbison.'win_bison.exe'.sha256),@($gperf,$gperfTools.executableSha256))) {
    if ((Get-FileHash -LiteralPath $item[0] -Algorithm SHA256).Hash.ToLowerInvariant() -ne $item[1]) { throw '已验证生成工具发生改变' }
}
$sdk=Get-Content -Raw -LiteralPath $SdkRecord | ConvertFrom-Json
if ($sdk.status -ne 'SDK_COMPILED_NOT_RUNTIME_ACCEPTED' -or $sdk.qtVersion -ne '6.11.2') { throw '需要实际编译完成的匹配Qt SDK' }
$seed=Plain $sdk.installRoot
if (-not $seed.StartsWith($nativeRoot+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'SDK种子不在本轮工作根' }
$python=Join-Path $PythonRoot 'python.exe'
$version=(& $python -I -B -S -c 'import sys;print(sys.version)').Trim()
if ($LASTEXITCODE -ne 0 -or -not $version.StartsWith('3.13.16 ')) { throw '构建Python版本不符' }
$free=(Get-PSDrive -Name ([IO.Path]::GetPathRoot($WorkRoot).Substring(0,1))).Free
if ($free -lt 80GB) { throw 'WebEngine构建至少预留80GiB，不创建目录' }
$vswhere=Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$vs=(& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath).Trim()
if ($LASTEXITCODE -ne 0 -or -not $vs) { throw '未找到MSVC工具链' }
Import-Module (Join-Path $vs 'Common7/Tools/Microsoft.VisualStudio.DevShell.dll')
Enter-VsDevShell -VsInstallPath $vs -Arch x64 -HostArch x64 -SkipAutomaticLocation
$compiler=(Get-Command cl.exe).Source
$cmake=(Get-Command cmake.exe).Source
$ninja=(Get-Command ninja.exe).Source
if ((Get-FileHash -LiteralPath $compiler -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sdk.compilerSha256) { throw '当前编译器与Qt SDK不同' }
$build=Join-Path $WorkRoot 'cmake'; $install=Join-Path $WorkRoot 'install'; $temp=Join-Path $WorkRoot 'tmp'
New-Item -ItemType Directory -Path $WorkRoot,$AuditRoot,$temp,$install | Out-Null
$record=[ordered]@{ status='RUNNING'; startedUtc=[DateTime]::UtcNow.ToString('o'); sourceRoot=$SourceRoot; workRoot=$WorkRoot; installRoot=$install; qtVersion='6.11.2'; sdkRecord=$SdkRecord; sdkRecordSha256=(Get-FileHash -LiteralPath $SdkRecord -Algorithm SHA256).Hash.ToLowerInvariant(); patchSha256=(Get-FileHash -LiteralPath $patch -Algorithm SHA256).Hash.ToLowerInvariant(); pythonVersion=$version; compiler=$compiler; jobs=$Jobs; initialFreeBytes=$free; scope='新工作目录；保留沙箱、网页预览和Qt Quick，移除未用媒体/打印/扩展功能；编译不等于应用验收。' }
Copy-Item -LiteralPath $PSCommandPath -Destination (Join-Path $AuditRoot 'build-script.ps1')
$record.buildScriptSha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
$record.additionalPatch=@{path=$docPatch; sha256=(Get-FileHash -LiteralPath $docPatch -Algorithm SHA256).Hash.ToLowerInvariant(); target=$docCmake; targetSha256=(Get-FileHash -LiteralPath $docCmake -Algorithm SHA256).Hash.ToLowerInvariant()}
$record.generatorInputs=@{nativeRecord=$NativeToolsRecord; nativeRecordSha256=(Get-FileHash -LiteralPath $NativeToolsRecord -Algorithm SHA256).Hash.ToLowerInvariant(); gperfRecord=$GperfRecord; gperfRecordSha256=(Get-FileHash -LiteralPath $GperfRecord -Algorithm SHA256).Hash.ToLowerInvariant(); pythonRecord=$PythonToolsRecord; pythonRecordSha256=(Get-FileHash -LiteralPath $PythonToolsRecord -Algorithm SHA256).Hash.ToLowerInvariant(); pythonSite=$pythonSite}
$wrapperSnapshot=Join-Path $AuditRoot 'normalize_msvc_paths.py'
Copy-Item -LiteralPath $wrapper -Destination $wrapperSnapshot
if ((Get-FileHash -LiteralPath $wrapperSnapshot -Algorithm SHA256).Hash.ToLowerInvariant() -ne $wrapperSha256) { throw '包装器快照复制不符' }
$record.msvcPathWrapper=@{path=$wrapperSnapshot; sourcePath=$wrapper; sha256=$wrapperSha256; contract='规范化包含/源/输出路径，保留FI/Yc/Yu头文件搜索语义；仅映射已知showIncludes依赖前缀，不隐藏诊断、不改变代码、ABI或返回码；原失败PCH实际编译通过。'}
$old=@{}
foreach ($name in @('TEMP','TMP','PATH','VSLANG','PYTHONHOME','PYTHONPATH','PYTHONDONTWRITEBYTECODE','NINJAFLAGS','QTWEBENGINE_GN_THREADS')) { $old[$name]=[Environment]::GetEnvironmentVariable($name) }
try {
    if (@(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($seed+'\',[StringComparison]::OrdinalIgnoreCase) }).Count) { throw 'SDK种子仍有活动工具进程，不复制或终止进程' }
    $items=@(Get-ChildItem -LiteralPath $seed -Recurse -Force)
    if (@($items | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw 'SDK含链接，停止' }
    $files=@($items | Where-Object { -not $_.PSIsContainer })
    if ($files.Count -gt 100000 -or ($files | Measure-Object Length -Sum).Sum -gt 10GB) { throw 'SDK复制超过有限预算' }
    $binding=[ordered]@{}
    foreach ($file in $files) {
        $relative=[IO.Path]::GetRelativePath($seed,$file.FullName)
        $checksum=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $target=Join-Path $install $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        [IO.File]::Copy($file.FullName,$target,$false)
        if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $checksum) { throw "SDK复制不符：$relative" }
        $binding[$relative.Replace('\','/')]=$checksum
    }
    $binding | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $AuditRoot 'sdk-seed-payload.json') -Encoding utf8NoBOM
    $env:TEMP=$temp; $env:TMP=$temp; $env:PYTHONHOME=$PythonRoot; $env:PYTHONPATH=$pythonSite; $env:PYTHONDONTWRITEBYTECODE='1'
    $env:PATH=(Split-Path -Parent $flex)+';'+(Split-Path -Parent $gperf)+';'+$env:PATH
    $probe=(& $python -I -B -S -c 'import sys;sys.path.insert(0,sys.argv[1]);import html5lib,six,webencodings;print(html5lib.__version__,six.__version__)' $pythonSite | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $probe -ne '1.1 1.17.0') { throw '本轮构建Python生成依赖探针失败' }
    $record.pythonBuildToolsProbe=$probe
    # 外层CMake并行度不会限制内层Chromium Ninja，必须同时限制NINJAFLAGS。
    $env:NINJAFLAGS="-j$Jobs"; $env:QTWEBENGINE_GN_THREADS="$Jobs"; $env:VSLANG='1033'
    $options=[ordered]@{
        CMAKE_BUILD_TYPE='Release'; CMAKE_INSTALL_PREFIX=$install; CMAKE_PREFIX_PATH=$install
        CMAKE_MAKE_PROGRAM=$ninja; CMAKE_C_COMPILER=$compiler; CMAKE_CXX_COMPILER=$compiler
        CMAKE_MSVC_RUNTIME_LIBRARY='MultiThreadedDLL'; Python3_EXECUTABLE=$python
        FLEX_EXECUTABLE=$flex; BISON_EXECUTABLE=$bison; GPerf_EXECUTABLE=$gperf
        QT_BUILD_TESTS='OFF'; QT_BUILD_EXAMPLES='OFF'; QT_BUILD_DOCS='OFF'
        UMI_WEBENGINE_DISABLE_FFMPEG='ON'; UMI_WEBENGINE_MSVC_WRAPPER="$python -I -B $wrapperSnapshot"
        FEATURE_qtwebengine_build='ON'; FEATURE_qtwebengine_core_build='ON'
        FEATURE_qtwebengine_quick_build='ON'; FEATURE_qtwebengine_widgets_build='OFF'
        FEATURE_qtpdf_build='OFF'; FEATURE_qtpdf_widgets_build='OFF'; FEATURE_qtpdf_quick_build='OFF'
        FEATURE_webengine_webrtc='OFF'; FEATURE_webengine_printing_and_pdf='OFF'
        FEATURE_webengine_spellchecker='OFF'; FEATURE_webengine_extensions='OFF'
        FEATURE_webengine_developer_build='OFF'; FEATURE_webengine_jumbo_build='8'; FEATURE_webenginedriver='OFF'
    }
    $argv=@('-S',$SourceRoot,'-B',$build,'-G','Ninja')
    foreach ($key in $options.Keys) { $argv+="-D${key}=$(([string]$options[$key]).Replace('\','/'))" }
    $record.configureArgv=@($cmake)+$argv; $record.options=$options
    $record | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $AuditRoot 'inputs.json') -Encoding utf8NoBOM
    & $cmake @argv 2>&1 | Tee-Object -FilePath (Join-Path $AuditRoot 'configure.log')
    if ($LASTEXITCODE -ne 0) { throw '最小QtWebEngine配置失败' }
    Copy-Item -LiteralPath (Join-Path $build 'CMakeCache.txt') -Destination (Join-Path $AuditRoot 'CMakeCache.txt')
    & $cmake --build $build --target run_core_GnDone --parallel $Jobs 2>&1 | Tee-Object -FilePath (Join-Path $AuditRoot 'gn-generation.log')
    if ($LASTEXITCODE -ne 0) { throw '实际GN依赖图生成失败' }
    $argsFiles=@(Get-ChildItem -LiteralPath $build -Recurse -File -Filter 'args.gn')
    $coreArgs=@($argsFiles | Where-Object { $_.FullName -like '*\core\*' })
    if (-not $coreArgs.Count) { throw '没有实际生成的core GN参数，不能声称禁用FFmpeg' }
    foreach ($file in $coreArgs) {
        $text=Get-Content -Raw -LiteralPath $file.FullName
        if ($text -notmatch '(?m)^media_use_ffmpeg\s*=\s*false\s*$') { throw '实际GN参数未关闭media_use_ffmpeg' }
        if ($text -match '(?m)^use_webaudio_ffmpeg\s*=') { throw '仍设置了该版本未声明的旧WebAudio参数' }
        if ($text -notmatch '(?m)^cc_wrapper="[^"\r\n]*normalize_msvc_paths\.py"\s*$') { throw '实际GN未启用已核验的包含路径包装器' }
        Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $AuditRoot ('core-'+[Array]::IndexOf($coreArgs,$file)+'-args.gn'))
    }
    $gnTools=@(Get-ChildItem -LiteralPath $WorkRoot -Recurse -File -Filter 'gn.exe')
    if (-not $gnTools.Count) { throw '无法定位本轮实际GN工具来验证依赖图' }
    $gn=$gnTools[0].FullName
    foreach ($file in $coreArgs) {
        $number=[Array]::IndexOf($coreArgs,$file)
        $graphFile=Join-Path $AuditRoot "core-$number-dependencies.json"
        & $gn desc $file.Directory.FullName '//:qtwebengine' deps --all --format=json --fail-on-unused-args "--root=$SourceRoot/src/3rdparty/chromium" "--script-executable=$python" '--ignore-asserts=enable_extensions_core,enable_extensions' 2>&1 | Tee-Object -FilePath $graphFile
        if ($LASTEXITCODE -ne 0) { throw 'GN实际依赖图查询失败或存在未生效参数' }
        $graphText=Get-Content -Raw -LiteralPath $graphFile
        $null=$graphText | ConvertFrom-Json -Depth 20
        if ($graphText -match '//third_party/ffmpeg(?:/|:)') { throw '实际QtWebEngineCore闭包仍包含FFmpeg目标，停止编译' }
    }
    & $cmake --build $build --parallel $Jobs 2>&1 | Tee-Object -FilePath (Join-Path $AuditRoot 'compile.log')
    if ($LASTEXITCODE -ne 0) { throw '最小QtWebEngine编译失败' }
    & $cmake --install $build 2>&1 | Tee-Object -FilePath (Join-Path $AuditRoot 'install.log')
    if ($LASTEXITCODE -ne 0) { throw '最小QtWebEngine安装SDK失败' }
    $dll=Join-Path $install 'bin/Qt6WebEngineCore.dll'
    if (-not (Test-Path -LiteralPath $dll -PathType Leaf)) { throw '缺少实际QtWebEngineCore DLL' }
    if ((Get-FileHash -LiteralPath $wrapperSnapshot -Algorithm SHA256).Hash.ToLowerInvariant() -ne $wrapperSha256) { throw '编译包装器快照在构建期间改变' }
    if ((Get-FileHash -LiteralPath $sourceCmake -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'ff64fa94fee12e101e0befd2a3b92a2e65c643410bdae16cee0ba736556abe72') { throw '派生CMake输入在构建期间改变' }
    $record.status='COMPILED_NOT_APP_ACCEPTED'; $record.coreDll=@{ path=$dll; bytes=(Get-Item -LiteralPath $dll).Length; sha256=(Get-FileHash -LiteralPath $dll -Algorithm SHA256).Hash.ToLowerInvariant() }
    $record.gnArgsFiles=@($coreArgs.FullName)
} catch {
    $record.status='FAILED'; $record.error=$_.Exception.Message; throw
} finally {
    $record.finishedUtc=[DateTime]::UtcNow.ToString('o')
    $record | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $AuditRoot 'result.json') -Encoding utf8NoBOM
    foreach ($name in $old.Keys) { [Environment]::SetEnvironmentVariable($name,$old[$name],'Process') }
}
