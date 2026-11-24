# 还原本发行页的原始字节分卷；本脚本自身即恢复工具源码（AGPL-3.0-or-later）。
# 只需已解压主程序的便携 Python，不依赖已从最简包移出的 source/ 或系统 Python。
[CmdletBinding()]
param(
    [string]$UmiOCRRoot = $PSScriptRoot,
    [string]$OutputDirectory = $PSScriptRoot,
    [string]$PartsDirectory = $PSScriptRoot
)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw '需要 PowerShell 7。' }
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
$PartsDirectory = Assert-PlainPath $PartsDirectory
$python = Assert-PlainPath (Join-Path $UmiOCRRoot 'UmiOCR-data/runtime/python.exe')
if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or
    -not (Test-Path -LiteralPath $OutputDirectory -PathType Container) -or
    -not (Test-Path -LiteralPath $PartsDirectory -PathType Container)) {
    throw '请先解压主程序，完整下载本页分卷及 archive-chunks.json，并选择已有输出目录。'
}
# -I 隔离归档所在目录，代码内嵌且只使用标准库，不从下载目录导入模块。
$restore = @'
import hashlib, json, os, re, shutil, stat, sys, uuid
from pathlib import Path

BUFFER = 1024 * 1024

def require(value, message):
    if not value:
        raise ValueError(message)

def plain(path):
    path = Path(path).absolute()
    require(not str(path).startswith(('\\\\', '//')) and '..' not in path.parts, '不安全路径')
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & 0x400), '拒绝链接或重解析点')
        require(not stat.S_ISREG(info.st_mode) or info.st_nlink == 1, '拒绝硬链接')
    return path

def object_pairs(pairs):
    result = {}
    for name, value in pairs:
        require(name not in result, '索引存在重复JSON键')
        result[name] = value
    return result

def fields(value, names):
    require(type(value) is dict and set(value) == set(names), '索引字段无效或含未知字段')

def integer(value, maximum):
    require(type(value) is int and 0 < value <= maximum, '无效大小或超过预算')
    return value

def checksum(value):
    require(type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value), '无效SHA-256')
    return value

def filename(value):
    require(type(value) is str and value and value not in ('.', '..') and value[-1] not in (' ', '.'), '无效文件名')
    require(not any(ord(c) < 32 or c in '<>:"/\\|?*' for c in value), '文件名不允许目录或控制字符')
    require(not re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])', value.split('.')[0], re.I), 'Windows保留文件名')
    return value

root, output = plain(sys.argv[1]), plain(sys.argv[2])
require(root.is_dir() and output.is_dir(), '输入/输出目录不存在')
index_path = plain(root / 'archive-chunks.json')
require(index_path.is_file() and index_path.stat().st_size <= 1024 * 1024, '缺少索引或索引过大')
index = json.loads(index_path.read_text('utf-8-sig'), object_pairs_hook=object_pairs)
fields(index, ('schema_version', 'format', 'files'))
require(type(index['schema_version']) is int and index['schema_version'] == 1 and index['format'] == 'umi-archive-chunks-v1', '索引用途或版本无效')
require(type(index['files']) is list and 0 < len(index['files']) <= 8, '文件数量无效')
seen, all_parts, total = set(), set(), 0
for item in index['files']:
    fields(item, ('path', 'bytes', 'sha256', 'parts'))
    name = filename(item['path'])
    require(name.endswith('.tar.xz') and name.casefold() not in seen, '归档文件名重复或非tar.xz')
    seen.add(name.casefold())
    total += integer(item['bytes'], 16 * 1024**3)
    checksum(item['sha256'])
    require(type(item['parts']) is list and 0 < len(item['parts']) <= 256, '分卷数量无效')
    sizes = []
    for number, part in enumerate(item['parts'], 1):
        fields(part, ('path', 'bytes', 'sha256'))
        require(filename(part['path']) == f'{name}.{number:03d}' and part['path'].casefold() not in all_parts, '分卷身份/顺序无效')
        all_parts.add(part['path'].casefold())
        sizes.append(integer(part['bytes'], 1536 * 1024**2))
        checksum(part['sha256'])
        source = plain(root / part['path'])
        require(source.is_file() and source.stat().st_size == part['bytes'], '分卷缺失或长度错误：' + part['path'])
    require(sum(sizes) == item['bytes'] and all(n == sizes[0] for n in sizes[:-1]) and sizes[-1] <= sizes[0], '分卷长度关系错误')
    require(not plain(output / name).exists(), '目标已存在，拒绝覆盖：' + name)
require(total <= 32 * 1024**3, '归档总大小超过预算')
require(shutil.disk_usage(output).free >= total + 64 * 1024**2, '输出空间不足')
for item in index['files']:
    target = plain(output / item['path'])
    temporary = output / ('.' + item['path'] + '.restore-' + uuid.uuid4().hex + '.partial')
    whole, written = hashlib.sha256(), 0
    try:
        with temporary.open('xb') as destination:
            for part in item['parts']:
                source = plain(root / part['path'])
                digest, count = hashlib.sha256(), 0
                with source.open('rb') as incoming:
                    while chunk := incoming.read(BUFFER):
                        count += len(chunk)
                        require(count <= part['bytes'], '分卷超出声明长度')
                        destination.write(chunk)
                        digest.update(chunk)
                        whole.update(chunk)
                require(count == part['bytes'] and digest.hexdigest() == part['sha256'], '分卷SHA-256错误：' + part['path'])
                written += count
            destination.flush()
            os.fsync(destination.fileno())
        require(written == item['bytes'] and whole.hexdigest() == item['sha256'], '完整归档SHA-256错误')
        plain(target)
        os.link(temporary, target)
        temporary.unlink()
        print(json.dumps({'status': 'RESTORED_AND_SHA256_VERIFIED', 'archive': str(target), 'bytes': written, 'sha256': whole.hexdigest()}, ensure_ascii=False))
    except Exception:
        if temporary.exists():
            print('未完成的自有暂存保留用于诊断：' + str(temporary), file=sys.stderr)
        raise
'@
& $python -I -B -X utf8 -c $restore $PartsDirectory $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw '恢复失败；请检查分卷、摘要、可用空间及目标冲突。现存文件不会被覆盖。' }
