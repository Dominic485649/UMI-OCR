#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SourceRoot,
    [Parameter(Mandatory)][string]$WorkRoot,
    [Parameter(Mandatory)][string]$AuditRoot,
    [Parameter(Mandatory)][string]$CudaRoot,
    [ValidateRange(1,4)][int]$Jobs = 4
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$commit = '74bca3950054eed1795f525cb9cf06bfe796492d'
$hostRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
function Assert-Within([string]$Path, [string]$Parent) {
    if (-not $Path.StartsWith($Parent + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "Path outside work boundary: $Path" }
    $cursor = $Path
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -Force -LiteralPath $cursor).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse point in work path: $cursor" }
        }
        $cursor = Split-Path -Parent $cursor
    }
}
$SourceRoot = [IO.Path]::GetFullPath($SourceRoot)
$WorkRoot = [IO.Path]::GetFullPath($WorkRoot)
$AuditRoot = [IO.Path]::GetFullPath($AuditRoot)
$CudaRoot = [IO.Path]::GetFullPath($CudaRoot)
Assert-Within $WorkRoot (Join-Path $hostRoot 'build\staging')
Assert-Within $AuditRoot (Join-Path $hostRoot 'build\audit')
foreach ($path in @($WorkRoot, $AuditRoot)) {
    if (Test-Path -LiteralPath $path) { throw "Use a new work/audit directory; no overwrite or cleanup: $path" }
}
$head = (& git -C $SourceRoot rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $head -ne $commit) { throw "Unexpected source HEAD: $head" }
$changes = & git -C $SourceRoot status --porcelain --untracked-files=no
if ($LASTEXITCODE -ne 0 -or $changes) { throw 'Tracked llama.cpp source must match the fixed commit.' }
$nvcc = Join-Path $CudaRoot 'bin\nvcc.exe'
$nvccVersion = (& $nvcc --version) -join "`n"
if ($LASTEXITCODE -ne 0 -or $nvccVersion -notmatch 'V13\.4\.92\b') { throw 'CUDA 13.4.92 is required.' }
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$vs = (& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath).Trim()
if ($LASTEXITCODE -ne 0 -or -not $vs) { throw 'MSVC x64 installation not found.' }
Import-Module (Join-Path $vs 'Common7\Tools\Microsoft.VisualStudio.DevShell.dll')
Enter-VsDevShell -VsInstallPath $vs -Arch x64 -HostArch x64 -SkipAutomaticLocation
$cmake = (Get-Command cmake.exe -ErrorAction Stop).Source
$ninja = (Get-Command ninja.exe -ErrorAction Stop).Source
$cl = (Get-Command cl.exe -ErrorAction Stop).Source
$build = Join-Path $WorkRoot 'cmake'
$architectures = @('75','80','86','89','90','120a','121a')
$options = [ordered]@{
    CMAKE_BUILD_TYPE='Release'; CMAKE_MAKE_PROGRAM=$ninja; CMAKE_CUDA_COMPILER=$nvcc
    CUDAToolkit_ROOT=$CudaRoot; CMAKE_CUDA_ARCHITECTURES=($architectures -join ';')
    BUILD_SHARED_LIBS='ON'; GGML_CUDA='ON'; GGML_NATIVE='OFF'; GGML_BACKEND_DL='OFF'
    GGML_CCACHE='OFF'; GGML_OPENMP_FETCH='OFF'; GGML_CUDA_NCCL='OFF'
    LLAMA_BUILD_COMMON='ON'; LLAMA_BUILD_TOOLS='ON'; LLAMA_BUILD_SERVER='ON'
    LLAMA_BUILD_APP='OFF'; LLAMA_BUILD_TESTS='OFF'; LLAMA_BUILD_EXAMPLES='OFF'
    LLAMA_BUILD_UI='OFF'; LLAMA_USE_PREBUILT_UI='OFF'; LLAMA_UI_GZIP='OFF'; LLAMA_CONNECT='OFF'
    LLAMA_OPENSSL='OFF'; LLAMA_BUILD_BORINGSSL='OFF'; LLAMA_BUILD_LIBRESSL='OFF'; LLAMA_LLGUIDANCE='OFF'
    FETCHCONTENT_FULLY_DISCONNECTED='ON'; FETCHCONTENT_UPDATES_DISCONNECTED='ON'
}
$configureArgs = @('-S', $SourceRoot, '-B', $build, '-G', 'Ninja')
foreach ($key in $options.Keys) { $configureArgs += "-D${key}=$($options[$key])" }
$buildArgs = @('--build', $build, '--target', 'llama-server', '--parallel', "$Jobs")
New-Item -ItemType Directory -Path $WorkRoot,$AuditRoot | Out-Null
$tempRoot = Join-Path $WorkRoot 'tmp'
New-Item -ItemType Directory -Path $tempRoot | Out-Null
$previousTemp, $previousTmp = $env:TEMP, $env:TMP
$env:TEMP = $tempRoot
$env:TMP = $tempRoot
Start-Transcript -Path (Join-Path $AuditRoot 'build-transcript.log') -UseMinimalHeader | Out-Null
try {
    Copy-Item -LiteralPath $PSCommandPath -Destination (Join-Path $AuditRoot 'build_bundled_llama.ps1')
    $archive = Join-Path $AuditRoot "llama.cpp-$commit.tar"
    & git -C $SourceRoot archive --format=tar "--output=$archive" $commit
    if ($LASTEXITCODE -ne 0) { throw 'Source archive failed.' }
    [ordered]@{
        schemaVersion=1; commit=$commit; cudaToolkit='13.4.92'; architectures=$architectures; buildOptions=$options
        sourceRoot=$SourceRoot; sourceArchive=[IO.Path]::GetFileName($archive)
        sourceArchiveSha256=(Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
        sourceTrackedStatusBefore=@($changes); nvccVersion=$nvccVersion; msvc=$cl; vsInstall=$vs
        cmake=$cmake; cmakeVersion=(& $cmake --version) -join "`n"; ninja=$ninja
        configureArgv=@($cmake)+$configureArgs; buildArgv=@($cmake)+$buildArgs; jobs=$Jobs
        temporaryRoot=$tempRoot
        startedAt=(Get-Date -Format o); cxxBaseline='C++17 (upstream targets; no standard override)'
    } | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8NoBOM (Join-Path $AuditRoot 'build-inputs.json')
    & $cmake @configureArgs 2>&1 | Tee-Object -FilePath (Join-Path $AuditRoot 'configure.log')
    if ($LASTEXITCODE -ne 0) { throw 'llama.cpp configure failed; no dependency downloads are authorized.' }
    & $cmake @buildArgs 2>&1 | Tee-Object -FilePath (Join-Path $AuditRoot 'compile.log')
    if ($LASTEXITCODE -ne 0) { throw 'llama-server build failed.' }
    $after = & git -C $SourceRoot status --porcelain --untracked-files=no
    if ($LASTEXITCODE -ne 0 -or $after -or (& git -C $SourceRoot rev-parse HEAD).Trim() -ne $commit) { throw 'Source changed during build.' }
    Copy-Item -LiteralPath (Join-Path $build 'CMakeCache.txt') -Destination $AuditRoot
    [ordered]@{ completedAt=(Get-Date -Format o); target='llama-server'; exitCode=0; sourceTrackedStatusAfter=@($after) } | ConvertTo-Json | Set-Content -Encoding utf8NoBOM (Join-Path $AuditRoot 'build-result.json')
    Write-Host "Fresh build ready: $build"
} finally {
    Stop-Transcript | Out-Null
    $env:TEMP = $previousTemp
    $env:TMP = $previousTmp
}
