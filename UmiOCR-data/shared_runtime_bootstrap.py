"""只读解析内容寻址的 Windows 运行组；不执行 .pth，也不搜索其它安装。"""
from __future__ import annotations

from collections import namedtuple
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import sysconfig
import zipfile


ABI = 'cp313-win_amd64'
BINDING_FORMAT = 'umi-shared-runtime-v1'
GROUP_FORMAT = 'umi-runtime-group-v1'
DIRECTORY = 'shared-runtime'
HOST_BINDING = 'shared-runtime.json'
GROUP_MANIFEST = 'group.json'
TIERS = {'12.6': 'cu126', '12.9': 'cu129'}
# 固定发行版的顶层所有权，不能把整个站点目录、一个别的插件或任意目录传给 worker。
COMMON = {
    'numpy': ('numpy', 'numpy.libs', 'numpy-*.dist-info'),
    'opencv-contrib-python': ('cv2', 'opencv_contrib_python-*.dist-info'),
    'pillow': ('PIL', 'pillow.libs', 'pillow-*.dist-info'),
    'six': ('six.py', 'six-*.dist-info'),
}
_BASENAMES = frozenset(('numpy', 'cv2', 'pil', 'six'))
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_DIST = re.compile(r'[a-z0-9_.+!-]+\.dist-info\Z')
_MAX_FILES = 20000
Group = namedtuple('Group', 'kind digest site files dll_dirs')


class SharedRuntimeError(RuntimeError):
    pass


def canonical_json(document):
    return (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def _duplicate_free(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SharedRuntimeError('共享运行时清单含重复字段')
        result[key] = value
    return result


def plain(path, *, directory=False):
    """在实际读取前逐级拒绝 reparse point（包括 junction）和文件别名。"""
    path = Path(path).absolute()
    if not path.anchor or str(path).startswith(('\\\\', '//')) or '..' in path.parts:
        raise SharedRuntimeError('共享运行时路径越界')
    for node in (*reversed(path.parents), path):
        info = node.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise SharedRuntimeError(f'共享运行时路径不允许链接：{node}')
        if node != path or directory:
            if not stat.S_ISDIR(info.st_mode):
                raise SharedRuntimeError(f'共享运行时目录无效：{node}')
        elif not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
            raise SharedRuntimeError(f'共享运行时文件无效：{node}')
    return path


def read_json(path, limit=4 * 1024**2):
    path = plain(path)
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise SharedRuntimeError(f'共享运行时清单过大：{path.name}')
    try:
        return raw, json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_duplicate_free)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise SharedRuntimeError(f'共享运行时清单无法解析：{path.name}') from exc


def relative(value):
    if not isinstance(value, str) or len(value) > 512:
        raise SharedRuntimeError('共享运行时成员路径无效')
    parts = value.split('/')
    if any(not part or part[-1:] in ('.', ' ') or part in {'.', '..'}
           or any(c in '<>:"\\|?*' or ord(c) < 32 for c in part)
           or re.fullmatch(r'(?:CON|NUL|AUX|PRN|(?:COM|LPT)[1-9¹²³])', part.split('.')[0], re.I)
           for part in parts):
        raise SharedRuntimeError(f'共享运行时成员路径无效：{value}')
    return value


def common_owner(top):
    for owner, patterns in COMMON.items():
        for pattern in patterns:
            if ('*' not in pattern and top == pattern or '*' in pattern
                    and top.startswith(pattern.split('*')[0]) and _DIST.fullmatch(top)):
                return owner
    return None


def validate_binding(value, *, host=False, tier=None):
    if (not isinstance(value, dict) or set(value) != {'format', 'abi', 'groups'}
            or value['format'] != BINDING_FORMAT or value['abi'] != ABI
            or not isinstance(value['groups'], list) or not 1 <= len(value['groups']) <= 2):
        raise SharedRuntimeError('共享运行时清单版本或 Windows x64 / CPython 3.13 ABI 不匹配')
    kinds, digests = set(), set()
    for item in value['groups']:
        if not isinstance(item, dict) or set(item) != {'kind', 'sha256'}:
            raise SharedRuntimeError('共享运行时组引用无效')
        kind, digest = item['kind'], item['sha256']
        allowed = ('common',) if host else ('common', *TIERS.values()) if tier is None else ('common', tier)
        if (kind not in allowed or kind in kinds or not isinstance(digest, str)
                or not _SHA.fullmatch(digest) or digest in digests):
            raise SharedRuntimeError('共享运行时组摘要、种类或 CUDA 档位不匹配')
        kinds.add(kind)
        digests.add(digest)
    if len(kinds - {'common'}) > 1:
        raise SharedRuntimeError('同一 worker 不允许挂载两个 CUDA 档位')
    return value['groups']


def runtime_dll_dirs(files, kind):
    """仅注册已封存目录；Paddle 与其相对 nvidia 路径须留在同一导入根。"""
    parents = {PurePosixPath(name).parent.as_posix() for name in files if name.lower().endswith('.dll')}
    if kind == 'common':
        return sorted(p for p in parents if p.endswith('.libs'))
    return sorted(p for p in parents if p in ('paddle/base', 'paddle/libs')
                  or re.fullmatch(r'nvidia/[a-z0-9_]+/bin', p))


def _file_allowed(name, kind):
    parts = name.split('/')
    top = parts[0]
    if (parts[-1].casefold().endswith(('.pth', '.pyc', '.pyo', '.exe', '.lnk'))
            or '__pycache__' in (p.casefold() for p in parts)):
        return False
    if kind == 'common':
        return common_owner(top) is not None
    return (top in ('paddle', 'nvidia', 'paddle.libs') or _DIST.fullmatch(top)
            and top.startswith(('paddlepaddle_gpu-', 'nvidia_')))


def group_document(kind, files):
    """统一构建和加载使用的成员定义，独立于放置路径和安装时间。"""
    if kind not in ('common', *TIERS.values()) or not isinstance(files, dict) or not 0 < len(files) <= _MAX_FILES:
        raise SharedRuntimeError('共享运行时组种类或成员数量无效')
    seen = set()
    total = 0
    for name, row in files.items():
        relative(name)
        if (name.casefold() in seen or not _file_allowed(name, kind) or not isinstance(row, dict)
                or set(row) != {'bytes', 'sha256'} or type(row['bytes']) is not int or not 0 <= row['bytes'] <= 2 * 1024**3
                or not isinstance(row['sha256'], str) or not _SHA.fullmatch(row['sha256'])):
            raise SharedRuntimeError(f'共享运行时成员无效：{name}')
        seen.add(name.casefold())
        total += row['bytes']
    required = {'numpy/__init__.py', 'cv2/__init__.py', 'PIL/__init__.py', 'six.py'} if kind == 'common' else {
        'paddle/__init__.py', 'paddle/base/libpaddle.pyd', 'paddle/libs/phi.dll'}
    if not required <= files.keys() or total > (256 * 1024**2 if kind == 'common' else 7 * 1024**3):
        raise SharedRuntimeError('共享运行时缺少完整导入根或超出容量上限')
    return {'format': GROUP_FORMAT, 'abi': ABI, 'kind': kind, 'files': files, 'dllDirectories': runtime_dll_dirs(files, kind)}


def _signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def file_record(path):
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or getattr(before, 'st_file_attributes', 0) & 0x400
            or before.st_nlink > 1):
        raise SharedRuntimeError(f'运行组成员不是普通独立文件：{path}')
    with path.open('rb') as stream:
        opened = _signature(os.fstat(stream.fileno()))
        if opened[2] != before.st_size:
            raise SharedRuntimeError(f'运行组成员打开时改变：{path}')
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if _signature(os.fstat(stream.fileno())) != opened or _signature(path.lstat()) != _signature(before):
            raise SharedRuntimeError(f'运行组成员读取时改变：{path}')
    return {'bytes': before.st_size, 'sha256': digest}


def read_group(data_root, ref, *, verify_bytes=True):
    # 调用者先校验 ref；本函数也独立拒绝携带路径的引用。
    validate_binding({'format': BINDING_FORMAT, 'abi': ABI, 'groups': [ref]})
    kind, digest = ref['kind'], ref['sha256']
    root = plain(Path(data_root) / DIRECTORY / digest, directory=True)
    with os.scandir(root) as items:
        if {item.name for item in items} != {GROUP_MANIFEST, 'site-packages'}:
            raise SharedRuntimeError(f'共享运行时组有额外成员：{digest[:12]}')
    raw, record = read_json(root / GROUP_MANIFEST)
    if hashlib.sha256(raw).hexdigest() != digest or not isinstance(record, dict):
        raise SharedRuntimeError(f'共享运行时组清单摘要不匹配：{digest[:12]}')
    files = record.get('files')
    if record != group_document(kind, files):
        raise SharedRuntimeError('共享运行时组的 ABI、种类或 DLL 目录与引用不匹配')
    site = plain(root / 'site-packages', directory=True)
    directories = {parent.as_posix() for name in files for parent in PurePosixPath(name).parents if parent.as_posix() != '.'}
    pending, seen, seen_dirs = [site], set(), set()
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as items:
            for item in items:
                path = Path(item.path)
                name = path.relative_to(site).as_posix()
                info = item.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise SharedRuntimeError(f'共享运行时组含链接：{name}')
                if stat.S_ISDIR(info.st_mode) and name in directories and name not in seen_dirs:
                    seen_dirs.add(name)
                    pending.append(path)
                elif (not stat.S_ISREG(info.st_mode) or info.st_nlink > 1 or name in seen or name not in files
                      or info.st_size != files[name]['bytes'] or verify_bytes and file_record(path) != files[name]):
                    raise SharedRuntimeError(f'共享运行时成员缺失、冲突或内容损坏：{name}')
                else:
                    seen.add(name)
    if seen != files.keys() or seen_dirs != directories:
        raise SharedRuntimeError(f'共享运行时组缺少声明成员：{digest[:12]}')
    return Group(kind, digest, site, files, tuple(site / p for p in record['dllDirectories']))


def load_groups(data_root, binding, *, host=False, tier=None, verify_bytes=True):
    refs = validate_binding(binding, host=host, tier=tier)
    if sys.implementation.cache_tag != 'cpython-313' or sysconfig.get_platform() != 'win-amd64':
        raise SharedRuntimeError('共享运行时需要本体的 Windows x64 / CPython 3.13')
    groups = []
    for ref in refs:
        try:
            groups.append(read_group(data_root, ref, verify_bytes=verify_bytes))
        except OSError as exc:
            raise SharedRuntimeError(f'缺少或不能读取共享运行时 {ref["kind"]}（{ref["sha256"][:12]}），请重新安装配套归档') from exc
    return tuple(groups)


def _shadow(top, groups):
    top = top.casefold()
    module = top.split('.')[0]
    for group in groups:
        if group.kind == 'common' and (module in _BASENAMES or common_owner(top)):
            return True
        if group.kind != 'common' and (module in ('paddle', 'nvidia') or _DIST.fullmatch(top)
                                      and top.startswith(('paddlepaddle_gpu-', 'nvidia_'))):
            return True
    return False


def _inactive_package_directory(path):
    """原地升级会留下空目录和历史 __pycache__；没有源文件时它们不是可导入包。"""
    count = 0
    pending = [path]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as items:
            for item in items:
                count += 1
                info = item.stat(follow_symlinks=False)
                if count > 4096 or stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    return False
                if stat.S_ISDIR(info.st_mode) and directory.name != '__pycache__':
                    pending.append(Path(item.path))
                elif (not stat.S_ISREG(info.st_mode) or directory.name != '__pycache__'
                      or not re.fullmatch(r'.+\.cpython-313(?:\.opt-[12])?\.pyc', item.name)):
                    return False
    return True


def reject_shadows(groups, roots=(), archives=()):
    """拒绝覆盖解包残留；不依赖 sys.path 顺序让两个版本碰运气。"""
    if not groups:
        return
    for path in roots:
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        with os.scandir(plain(path, directory=True)) as items:
            for item in items:
                if not _shadow(item.name, groups):
                    continue
                if (item.name != 'six.py' and common_owner(item.name) and item.is_dir(follow_symlinks=False)
                        and _inactive_package_directory(plain(Path(item.path), directory=True))):
                    continue  # 保留用户的惰性缓存，不视作第二份可导入发行版。
                raise SharedRuntimeError(f'旧散文件与共享运行时冲突：{item.name}；请干净重装')
    for path in archives:
        with zipfile.ZipFile(plain(path)) as archive:
            if any(_shadow(info.filename.split('/')[0], groups) for info in archive.infolist()):
                raise SharedRuntimeError(f'私有容器与共享运行时冲突：{Path(path).name}')


def private_dll_paths(vendor):
    """从已存在的私有 Paddle/CUDA 根提取本进程允许的具体目录。"""
    vendor = Path(vendor)
    paths = [vendor / 'paddle/base', vendor / 'paddle/libs']
    nvidia = vendor / 'nvidia'
    if nvidia.is_dir():
        paths.extend(package / 'bin' for package in sorted(plain(nvidia, directory=True).iterdir()) if package.is_dir())
    return tuple(plain(p, directory=True) for p in paths if p.is_dir())


def dll_paths(groups, *, private=()):
    """各 worker 只接收自己已核对的目录；拒绝内容不同的同名 DLL。"""
    names = {}
    def check(name, digest):
        old = names.setdefault(name.casefold(), digest)
        if old != digest:
            raise SharedRuntimeError(f'同一进程的运行时含不同内容的同名 DLL：{name}')
    for group in groups:
        for name, row in group.files.items():
            if name.lower().endswith('.dll'):
                check(name.rsplit('/', 1)[-1], row['sha256'])
    # 常见路径只做文件名比对；仅重复时哈希大私有库，避免每次启动读数 GiB。
    private_seen = {}
    for directory in private:
        for path in directory.glob('*.dll'):
            key = path.name.casefold()
            if key in private_seen:
                check(path.name, file_record(private_seen[key])['sha256'])
            if key in names:
                check(path.name, file_record(plain(path))['sha256'])
            private_seen[key] = path
    return tuple(dict.fromkeys([*(p for group in groups for p in group.dll_dirs), *private]))


def host_groups(data_root, archives):
    data_root = Path(data_root)
    try:
        (data_root / HOST_BINDING).lstat()
    except FileNotFoundError:
        return ()  # 源码和旧完整程序仍按原导入根启动，不自动发现共享目录。
    _, binding = read_json(data_root / HOST_BINDING, 65536)
    groups = load_groups(data_root, binding, host=True)
    reject_shadows(groups, [data_root, data_root / 'site-packages'], archives)
    return groups


def plugin_groups(plugin, *, archives=(), verify_bytes=True):
    plugin = plain(plugin, directory=True)
    if plugin.parent.name != 'plugins' or plugin.parent.parent.name != 'UmiOCR-data':
        raise SharedRuntimeError('共享 worker 必须安装在本体的 plugins 目录中')
    _, manifest = read_json(plugin / 'umi-plugin.json', 256 * 1024)
    binding = manifest['runtime']['shared_runtime']
    support_raw, support = read_json(plugin / 'cuda-support.json', 64 * 1024)
    tier = TIERS.get(support.get('cuda_version'))
    if tier is None:
        raise SharedRuntimeError('无法识别 worker 的 CUDA 运行档位')
    _, lock = read_json(plugin / 'runtime.lock.json', 8 * 1024**2)
    support_sha = hashlib.sha256(support_raw).hexdigest()
    sealed_support = lock.get('gpuSupportSha256') or next((row['sha256'] for row in lock.get('files', [])
                                                              if row.get('path') == 'cuda-support.json'), None)
    if (lock.get('sharedRuntime') != binding or lock.get('pluginId') != plugin.name
            or manifest.get('id') != plugin.name or support_sha != sealed_support):
        raise SharedRuntimeError('插件清单的共享引用或覆盖声明与原生运行锁不符')
    groups = load_groups(plugin.parent.parent, binding, tier=tier, verify_bytes=verify_bytes)
    vendor = plugin / 'vendor'
    reject_shadows(groups, [plugin, vendor], archives)
    by_digest = {group.digest: group for group in groups}
    for row in lock.get('sharedNative', []):
        target = by_digest.get(row.get('groupSha256'))
        if (target is None or row.get('path') != 'vendor/' + row['member']
                or target.files.get(row['member'], {}).get('sha256') != row['sha256']):
            raise SharedRuntimeError('插件的共享原生提供者不满足运行锁')
    for group in groups:
        if group.kind == 'common':
            continue
        providers = {row['path'].removeprefix('vendor/'): row['sha256'] for row in support['providers']}
        if set(providers) != {'paddle/base/libpaddle.pyd', 'paddle/libs/phi.dll'} or any(
                group.files.get(name, {}).get('sha256') != digest for name, digest in providers.items()):
            raise SharedRuntimeError('共享的 Paddle 核心字节与插件 CUDA 覆盖声明不符')
    return groups
