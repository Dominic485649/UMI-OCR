#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$WorkRoot,
    [Parameter(Mandatory)][string]$AuditRoot,
    [Parameter(Mandatory)][string]$SourceRoot,
    [Parameter(Mandatory)][string]$CudaRoot,
    [Parameter(Mandatory)][string]$MsvcRedist,
    [Parameter(Mandatory)][string]$Python
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$hostRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$pluginRoot = [IO.Path]::GetFullPath((Join-Path $hostRoot '..\Umi-OCR-Plugin'))
$WorkRoot = [IO.Path]::GetFullPath($WorkRoot)
$AuditRoot = [IO.Path]::GetFullPath($AuditRoot)
if (-not $WorkRoot.StartsWith((Join-Path $hostRoot 'build\staging\'), [StringComparison]::OrdinalIgnoreCase) -or
    -not $AuditRoot.StartsWith((Join-Path $hostRoot 'build\audit\'), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Work/audit paths must stay in this host project.'
}
$result = Join-Path $AuditRoot 'build-result.json'
if (-not (Test-Path -LiteralPath $result -PathType Leaf)) { throw 'Fresh build is not finished. This entry does not poll or wait.' }
$runtime = Join-Path $WorkRoot 'resources\llama.cpp'
$probeAudit = Join-Path $AuditRoot 'package-probe'
$protectedOutputs = @($runtime, $probeAudit, (Join-Path $AuditRoot 'delivery-result.json'), (Join-Path $AuditRoot 'assemble.log'), (Join-Path $AuditRoot 'manifest-validation.log'), (Join-Path $AuditRoot 'package-probe.log'), (Join-Path $AuditRoot 'packaging-tool-hashes.json'), (Join-Path $AuditRoot 'finish_bundled_llama.ps1'))
foreach ($path in $protectedOutputs) {
    if (Test-Path -LiteralPath $path) { throw "No overwrite of an earlier attempt: $path" }
}
$bundleTool = Join-Path $pluginRoot 'tools\bundle_llama_runtime.py'
$probeTool = Join-Path $PSScriptRoot 'probe_bundled_llama.py'
$tools = @($bundleTool, $probeTool, $PSCommandPath, (Join-Path $pluginRoot 'Build-Plugin.ps1'), (Join-Path $pluginRoot 'tests\test_bundle_llama_runtime.py'))
$tools | ForEach-Object {
    [ordered]@{ path=$_; size=(Get-Item -LiteralPath $_).Length; sha256=(Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash.ToLowerInvariant() }
} | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8NoBOM (Join-Path $AuditRoot 'packaging-tool-hashes.json')
Copy-Item -LiteralPath $PSCommandPath -Destination (Join-Path $AuditRoot 'finish_bundled_llama.ps1')
& $Python -I -B $bundleTool --assemble --source-root $SourceRoot --audit-root $AuditRoot --build-root (Join-Path $WorkRoot 'cmake') --cuda-root $CudaRoot --msvc-redist $MsvcRedist --license-root (Join-Path $AuditRoot 'license-snapshots') --destination $runtime 2>&1 | Tee-Object -FilePath (Join-Path $AuditRoot 'assemble.log')
if ($LASTEXITCODE -ne 0) { throw 'Runtime assembly failed; evidence/partial output retained without cleanup.' }
& $Python -I -B $bundleTool --validate $runtime 2>&1 | Tee-Object -FilePath (Join-Path $AuditRoot 'manifest-validation.log')
if ($LASTEXITCODE -ne 0) { throw 'Runtime manifest/closure validation failed.' }
& $Python -I -B $probeTool --runtime $runtime --audit $probeAudit --cuobjdump (Join-Path $CudaRoot 'bin\cuobjdump.exe') 2>&1 | Tee-Object -FilePath (Join-Path $AuditRoot 'package-probe.log')
if ($LASTEXITCODE -ne 0) { throw 'Model-free package probe failed; no inference or external-service fallback was attempted.' }
$manifest = Join-Path $runtime 'runtime-manifest.json'
[ordered]@{
    completedAt=(Get-Date -Format o); runtime=$runtime
    manifestSha256=(Get-FileHash -LiteralPath $manifest -Algorithm SHA256).Hash.ToLowerInvariant()
    buildResult=$result; probeResult=(Join-Path $probeAudit 'probe-result.json')
    validationScope='Fresh compile, static PE/manifest/source/license closure, isolated child PATH --version/--help/--list-devices, loaded-module file paths, SASS/PTX architecture presence.'
    notValidated=@('Model inference', 'Other GPU hardware', 'Older driver branches', 'Combined plugin build/install', 'Public redistribution approval')
} | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8NoBOM (Join-Path $AuditRoot 'delivery-result.json')
Write-Host "Bundled llama.cpp runtime ready: $runtime"
