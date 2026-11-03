# 恢复发行归档分卷。将分卷、archive-chunks.json及本脚本放在一起。
# UmiOCRRoot指向已解压的主程序目录；复用其便携Python和随附对应源码工具，无需系统Python。
[CmdletBinding()]
param(
    [string]$UmiOCRRoot = $PSScriptRoot,
    [string]$OutputDirectory = $PSScriptRoot
)
$ErrorActionPreference = 'Stop'

function Assert-PlainPath([string]$Path) {
    if ($Path -match '^[\\/]{2}') { throw '不支持网络或设备路径。' }
    $full = [IO.Path]::GetFullPath($Path)
    for ($current = $full; $current; $current = Split-Path -Parent $current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -Force -LiteralPath $current
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
                $item.LinkType -in @('HardLink', 'SymbolicLink', 'Junction')) {
                throw "拒绝链接或重解析点：$current"
            }
        }
    }
    return $full
}

$UmiOCRRoot = Assert-PlainPath $UmiOCRRoot
$OutputDirectory = Assert-PlainPath $OutputDirectory
$inputRoot = Assert-PlainPath $PSScriptRoot
$python = Assert-PlainPath (Join-Path $UmiOCRRoot 'UmiOCR-data/runtime/python.exe')
$tool = Assert-PlainPath (Join-Path $UmiOCRRoot 'source/build/tools/chunked_files.py')
$index = Assert-PlainPath (Join-Path $inputRoot 'archive-chunks.json')
if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or
    -not (Test-Path -LiteralPath $tool -PathType Leaf) -or
    -not (Test-Path -LiteralPath $index -PathType Leaf) -or
    -not (Test-Path -LiteralPath $OutputDirectory -PathType Container)) {
    throw '缺少主程序便携Python、对应源码工具、分卷索引或已有输出目录。请先解压本次主程序，并完整下载分卷及索引。'
}
& $python -I -B -X utf8 $tool restore --root $inputRoot --purpose archive --output $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw '恢复失败；请检查分卷是否齐全、哈希是否正确及目标是否已存在。现存文件不会被覆盖。' }
