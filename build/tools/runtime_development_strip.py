"""按经核对的 wheel 归属和精确字节外置开发文件，不改动输入树。"""
from __future__ import annotations

import base64
import csv
from email.parser import BytesParser
import hashlib
import io
import re
from pathlib import PurePosixPath


SHA = re.compile(r'[a-f0-9]{64}\Z')
DIST = re.compile(r'[a-z0-9_.+!-]+\.dist-info\Z')
TARGETS = frozenset(('base', 'cu126', 'cu129', 'vl-cu126', 'vl-cu129'))
ROLES = {
    'fonttools-cython-output': ('fonttools', ('fontTools/',), {'.c'}),
    'paddle-ap-kernel-compiler': ('paddlepaddle-gpu', ('paddle/apy/',), {'.py', '.h', '.cuh', ''}),
    'paddlex-point-cloud-compiler': ('paddlex', ('paddlex/ops/iou3d_nms/', 'paddlex/ops/voxel/'), {'.h', '.c', '.cc', '.cpp', '.cu'}),
    'scipy-linker-import-library': ('scipy', ('scipy/',), {'.a'}),
    'cuda-sdk-development': ('nvidia-cuda-runtime-cu12', ('nvidia/cuda_runtime/include/', 'nvidia/cuda_runtime/lib/x64/'), {'.h', '.hpp', '.lib'}),
}
MAX_FILE = 4 * 1024**2
MAX_EVIDENCE = 64 * 1024**2


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def row(raw):
    return {'bytes': len(raw), 'sha256': digest(raw)}


def module_name(name):
    return re.sub(r'[-_.]+', '-', name.casefold())


def records(raw):
    by_name = {}
    for line in csv.reader(io.StringIO(raw.decode('utf-8-sig'), newline='')):
        if len(line) != 3 or line[0].casefold() in by_name:
            raise ValueError('第三方 RECORD 含重复或无效成员')
        by_name[line[0].casefold()] = line
    return by_name


def wheel_hash(raw):
    return 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b'=').decode('ascii')


def bounded(view, name):
    path = view.disk_files.get(name)
    size = path.stat().st_size if path is not None else view.entries[name.casefold()]['bytes']
    if size < 0 or size > MAX_FILE:
        raise ValueError('开发材料超出单文件读取预算：' + name)
    raw = view.read_bytes(name)
    if len(raw) != size:
        raise ValueError('开发材料在读取时改变：' + name)
    return raw


def developer_role(path, kind):
    _, roots, suffixes = ROLES[kind]
    relative = PurePosixPath(path)
    leaf = relative.name
    scoped = ((path.startswith(roots) and relative.suffix in suffixes)
              or (kind == 'paddlex-point-cloud-compiler' and path == 'paddlex/ops/setup.py'))
    if (not scoped or any(part.upper().startswith(('LICENSE', 'LICENCE', 'COPYING', 'COPYRIGHT', 'NOTICE', 'AUTHORS', 'PATENTS'))
                          or part.casefold() in ('models', 'model', '__pycache__', 'record', 'metadata') for part in relative.parts)):
        return False
    if kind == 'paddle-ap-kernel-compiler' and not PurePosixPath(path).suffix:
        return leaf == '.apy_ignore'
    if kind == 'scipy-linker-import-library':
        return leaf.endswith('.dll.a')
    return True


def project(view, prefix, target, rules, canonical_relative):
    """返回明确的逻辑路径排除项、原材料、运行元数据及可审计决定。"""
    if (target not in TARGETS or prefix != ('site-packages' if target == 'base' else 'vendor')
            or not isinstance(rules, dict) or set(rules) != {'format', 'rules'}
            or rules['format'] != 'umi-runtime-development-strip-v1'
            or not isinstance(rules['rules'], list) or len(rules['rules']) > 64):
        raise ValueError('运行时开发材料裁剪锁格式无效')
    names = {key.removeprefix(prefix + '/') for key in view.iter_files(prefix)}
    owners, originals, removed, evidence, adjusted = {}, {}, {}, {}, {}
    dist_targets = set()
    material_bytes = 0

    def retain(path, raw):
        nonlocal material_bytes
        if path in evidence:
            raise ValueError('裁剪来源路径重复：' + path)
        material_bytes += len(raw)
        if material_bytes > MAX_EVIDENCE:
            raise ValueError('裁剪来源材料超过读取预算')
        evidence[path] = raw

    for rule in rules['rules']:
        if (not isinstance(rule, dict) or set(rule) != {'targets', 'dist', 'name', 'version', 'kind', 'reason', 'files'}
                or not all(isinstance(rule[k], str) and rule[k] for k in ('name', 'dist', 'kind', 'version', 'reason'))
                or not isinstance(rule['targets'], list) or not rule['targets']
                or any(not isinstance(t, str) or t not in TARGETS for t in rule['targets'])
                or len(set(rule['targets'])) != len(rule['targets']) or rule['kind'] not in ROLES
                or rule['name'] != ROLES[rule['kind']][0] or not DIST.fullmatch(rule['dist'])
                or not isinstance(rule['files'], dict) or not 1 <= len(rule['files']) <= 256):
            raise ValueError('运行时开发材料裁剪规则不完整')
        dist, version = rule['dist'], rule['version']
        keys = {(t, dist) for t in rule['targets']}
        if dist_targets & keys:
            raise ValueError('裁剪规则重复绑定相同档位和发行版：' + dist)
        dist_targets.update(keys)
        if target not in rule['targets']:
            continue
        owner = dist + '/RECORD'
        metadata = dist + '/METADATA'
        if owner not in names or metadata not in names:
            raise ValueError('已裁剪发行版身份不匹配：' + dist)
        meta_raw = bounded(view, prefix + '/' + metadata)
        header = BytesParser().parsebytes(meta_raw, headersonly=True)
        declared = header.get_all('Name', [])
        if (len(declared) != 1 or module_name(declared[0]) != rule['name'] or header.get_all('Version') != [version]):
            raise ValueError('已裁剪发行版版本或名称不符：' + dist)
        record_raw = bounded(view, prefix + '/' + owner)
        entries = records(record_raw)
        originals[owner] = (record_raw, entries)
        retain('development-originals/' + owner, record_raw)
        retain('development-originals/' + metadata, meta_raw)
        for name, expected in rule['files'].items():
            canonical_relative(name)
            if (not developer_role(name, rule['kind']) or not isinstance(expected, dict)
                    or set(expected) != {'bytes', 'sha256'} or type(expected['bytes']) is not int
                    or not 0 <= expected['bytes'] <= MAX_FILE or not isinstance(expected['sha256'], str)
                    or not SHA.fullmatch(expected['sha256'])):
                raise ValueError('未核对的开发成员类型或摘要：' + name)
            if name not in names or name.casefold() in owners:
                raise ValueError('锁定开发成员缺失或被重复裁剪：' + name)
            if rule['kind'] == 'fonttools-cython-output':
                stem = name.removesuffix('.c')
                if not any(n.casefold() in entries and (n == stem + '.py' or
                           (n.startswith(stem + '.') and n.endswith('.pyd'))) for n in names):
                    raise ValueError('FontTools 生成 C 文件没有仍保留的运行实现：' + name)
            raw = bounded(view, prefix + '/' + name)
            if row(raw) != expected or entries.get(name.casefold()) != [name, wheel_hash(raw), str(len(raw))]:
                raise ValueError('开发材料字节或原 wheel RECORD 归属不符：' + name)
            if rule['kind'] in ('scipy-linker-import-library', 'cuda-sdk-development') and name.endswith(('.a', '.lib')) and not raw.startswith(b'!<arch>\n'):
                raise ValueError('开发链接库不是已核对的 COFF 归档：' + name)
            owners[name.casefold()] = owner
            removed[prefix + '/' + name] = {**expected, 'owner': owner, 'reason': rule['reason'], 'kind': rule['kind']}
            retain('development-files/' + prefix + '/' + name, raw)

    if not removed:
        return removed, evidence, adjusted
    scanned = 0
    for name in sorted(n for n in names if n.count('/') == 1 and n.endswith('.dist-info/RECORD')):
        raw, entries = originals.get(name, (None, None))
        if entries is None:
            raw = bounded(view, prefix + '/' + name)
            entries = records(raw)
        scanned += len(raw)
        if scanned > MAX_EVIDENCE:
            raise ValueError('全发行版归属检查超出读取预算')
        if any(owners[k] != name for k in entries.keys() & owners.keys()):
            raise ValueError('开发成员还被其它发行版拥有：' + name)
        dropped = {key for key, value in owners.items() if value == name}
        if dropped:
            output = io.StringIO(newline='')
            writer = csv.writer(output, lineterminator='\n')
            writer.writerows(line for key, line in entries.items() if key not in dropped)
            adjusted[prefix + '/' + name] = output.getvalue().encode('utf-8')
    return removed, evidence, adjusted
