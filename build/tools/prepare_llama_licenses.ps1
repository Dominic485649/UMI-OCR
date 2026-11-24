#requires -Version 7.0
[CmdletBinding()]
param([Parameter(Mandatory)][string]$Destination)
$ErrorActionPreference = 'Stop'
$Destination = [IO.Path]::GetFullPath($Destination)
$hostRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if (-not $Destination.StartsWith((Join-Path $hostRoot 'build\audit\') , [StringComparison]::OrdinalIgnoreCase)) { throw 'License snapshots must stay in this project audit directory.' }
if (Test-Path -LiteralPath $Destination) { throw "Use a new download directory: $Destination" }
New-Item -ItemType Directory -Path $Destination | Out-Null
$documents = @(
    @{ outputName='NVIDIA-CUDA-EULA.html'; url='https://docs.nvidia.com/cuda/eula/index.html' },
    @{ outputName='CUDA-release-notes.html'; url='https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html' },
    @{ outputName='MSVC-redistribution.html'; url='https://learn.microsoft.com/en-us/visualstudio/releases/2026/redistribution' },
    @{ outputName='MSVC-license.html'; url='https://visualstudio.microsoft.com/license-terms/vs2026-ga-community/' },
    @{ outputName='MSVC-Community-2026-license.docx'; url='https://visualstudio.microsoft.com/wp-content/uploads/2025/10/Visual_Studio_2026-License-Community_ENU.docx' },
    @{ outputName='CCCL-LICENSE.txt'; url='https://raw.githubusercontent.com/NVIDIA/cccl/v3.4.3/LICENSE' }
)
$index = @()
foreach ($document in $documents) {
    # Each untrusted document has its own new empty input directory.
    $subdir = [IO.Path]::GetFileNameWithoutExtension($document.outputName)
    $folder = Join-Path $Destination $subdir
    New-Item -ItemType Directory -Path $folder | Out-Null
    $file = Join-Path $folder $document.outputName
    Invoke-WebRequest -Uri $document.url -OutFile $file
    $index += [ordered]@{
        outputName=$document.outputName; url=$document.url
        path="$subdir/$($document.outputName)"; retrievedAt=(Get-Date -Format o)
        size=(Get-Item -LiteralPath $file).Length
        sha256=(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$index | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8NoBOM (Join-Path $Destination 'document-sources.json')
Write-Host "License/source snapshots ready: $Destination"
