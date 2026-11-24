"""生成明确标识的ModelScope下载派生wheel；原输入锁与下载接口不变。"""
from __future__ import annotations

import argparse
import base64
import csv
from datetime import datetime, timezone
from email.parser import BytesParser
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('modelscope_download_layout', Path(__file__).with_name('runtime_archive_layout.py'))
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)
UPSTREAM = '1.38.1'
VERSION = UPSTREAM + '+umi.download.1'
ORIGINAL_DIST = 'modelscope-' + UPSTREAM + '.dist-info'
DIST = 'modelscope-' + VERSION + '.dist-info'
FILENAME = 'modelscope-' + VERSION + '-py3-none-any.whl'
UPSTREAM_SHA256 = '7d65be96999144ca045386d27a8ea057b8777504c538d9755d60ec2c8906fe72'
SDIST_SHA256 = 'a81f3685b1545f52b415d88a763456416aa65170e622f9dcc02eadb3f8e1cfa0'
KEEP_HASHES = {
    'modelscope/__init__.py': 'd3c419b4380ebfce84b1ec5ea075b4e531c921a6bacaf5bcad244e1bb4b93a51',
    'modelscope/hub/__init__.py': 'e8632ed21213484a55b8f05aec35a0581604b82d20faff5ec7ccde69bf554479',
    'modelscope/hub/callback.py': 'f02fdc1c46a737ba4d8aa669cb2c47f7a45e35f7275f55a606ab63b9068d32e6',
    'modelscope/hub/constants.py': '59ca6204fd1184a5bc59e930a76744bb9c9a140d6d80deb0a1195611d01b185f',
    'modelscope/hub/errors.py': '94a59bf6aaacefee289a1aff1f1b2ba7c3a2a9318657fe98b78d531b00df0047',
    'modelscope/hub/snapshot_download.py': '7504d33c71dca00ddb526d0134eeca66c6ec4436533ad9305b654b4e840d617b',
    'modelscope/utils/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    'modelscope/utils/constant.py': '8bb5a23cc29ba1fcd64e7bcbacb1860dbdd7c82297004f4487e5ded62965d3a7',
    'modelscope/utils/logger.py': 'e43ac1a382c3057af73c627cee59e11efc75698dadcdeff95822ae5309c29c33',
    'modelscope/version.py': 'aea7ca81df11b51475a4cec11bd3c3380f1f4ce0ad2654a356e2685979470f2c',
}
SCOPE = '仅提供Umi-OCR使用的snapshot下载、环境桥接及异常兼容；不提供ModelScope模型框架、训练、数据集管理、上传、CLI或PyTorch分布式日志集成。保留下载参数及模型文件，不限制产品模型族。'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def read_archive(path, expected_hash, dist):
    """先查摘要和有限预算，再读取ZIP；标准RECORD和包边界均须吻合。"""
    path = L.plain_path(path)
    if L.sha256_file(path) != expected_hash:
        raise ValueError('ModelScope独立构件摘要不符')
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [L.canonical_relative(item.filename) for item in entries]
        if (len(entries) > 5000 or len({n.casefold() for n in names}) != len(names)
                or sum(item.file_size for item in entries) > 64 * 1024**2
                or any(item.file_size > 4 * 1024**2 or item.is_dir()
                       or ((item.external_attr >> 16) & 0o170000) not in {0, 0o100000} for item in entries)):
            raise ValueError('ModelScope构件成员类型、别名或预算不符')
        if any(not n.startswith(('modelscope/', dist + '/')) for n in names):
            raise ValueError('ModelScope构件越过包边界')
        if any(n.endswith(('/RECORD.jws', '/RECORD.p7s')) for n in names):
            raise ValueError('不将上游签名带入派生包')
        payload = {n: archive.read(n) for n in names}
    record = dist + '/RECORD'
    rows = list(csv.reader(io.StringIO(payload[record].decode('utf-8'))))
    if any(len(row) != 3 for row in rows) or len(rows) != len(names) or {row[0] for row in rows} != set(names):
        raise ValueError('ModelScope标准RECORD成员不符')
    for name, checksum, size in rows:
        if name == record:
            if checksum or size:
                raise ValueError('RECORD自身必须留空')
        else:
            data = payload[name]
            expected = 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode('ascii')
            if checksum != expected or size != str(len(data)):
                raise ValueError('ModelScope RECORD字节不符：' + name)
    if L.sha256_file(path) != expected_hash:
        raise ValueError('ModelScope构件在核验期间改变')
    return payload


def replace_once(data, original, replacement):
    if data.count(original) != 1:
        raise ValueError('固定ModelScope补丁输入形状变化')
    return data.replace(original, replacement)


def derive(original):
    for name, expected in KEEP_HASHES.items():
        if digest(original[name]) != expected:
            raise ValueError('已审查下载闭包的原始源码不符：' + name)
    payload = {name: original[name] for name in KEEP_HASHES}
    payload['modelscope/__init__.py'] = (
        b'# Copyright (c) Alibaba, Inc. and its affiliates.\n'
        b'# Umi-OCR derived download-only surface; full original source supplied separately.\n'
        b'from .version import __version__, __release_datetime__\n'
        b'from .hub.snapshot_download import snapshot_download, dataset_snapshot_download\n'
        b'__all__ = ["__version__", "__release_datetime__", "snapshot_download", "dataset_snapshot_download"]\n')
    hub = payload['modelscope/hub/__init__.py']
    for line in (b'from .commit_scheduler import CommitScheduler\n', b"    'CommitScheduler',\n"):
        hub = replace_once(hub, line, b'')
    payload['modelscope/hub/__init__.py'] = hub
    logger = payload['modelscope/utils/logger.py']
    logger = replace_once(logger,
        b"    if iutil.find_spec('torch') is not None:\n        from modelscope.utils.torch_utils import is_dist, is_master\n        torch_dist = is_dist()\n        is_worker0 = is_master()\n",
        b'    # Umi download-only profile: no PyTorch distributed runtime is provided.\n')
    logger = replace_once(logger,
        b"    if iutil.find_spec('torch') is not None:\n        from modelscope.utils.torch_utils import is_master\n        is_worker0 = is_master()\n    else:\n        is_worker0 = True\n",
        b'    is_worker0 = True  # Same behavior as upstream without torch.\n')
    payload['modelscope/utils/logger.py'] = logger
    payload['modelscope/version.py'] = replace_once(payload['modelscope/version.py'],
        ("__version__ = '" + UPSTREAM + "'").encode(), ("__version__ = '" + VERSION + "'").encode())
    metadata = BytesParser().parsebytes(original[ORIGINAL_DIST + '/METADATA'])
    if metadata['Name'] != 'modelscope' or metadata['Version'] != UPSTREAM:
        raise ValueError('上游ModelScope身份不符')
    # 未提供框架/数据集extras，不能继续宣告其额外API；基础下载依赖原样保留。
    header = ('Metadata-Version: 2.4\nName: modelscope\nVersion: ' + VERSION + '\n'
              'Summary: Umi-OCR derived ModelScope download compatibility surface\n')
    for key in ('Requires-Python', 'License', 'License-Expression', 'Home-page', 'Author', 'Author-email'):
        for value in metadata.get_all(key, []):
            header += key + ': ' + value + '\n'
    for requirement in metadata.get_all('Requires-Dist', []):
        if 'extra ==' not in requirement and 'extra==' not in requirement:
            header += 'Requires-Dist: ' + requirement + '\n'
    payload[DIST + '/METADATA'] = (header + '\n' + SCOPE + '\n').encode('utf-8')
    payload[DIST + '/WHEEL'] = b'Wheel-Version: 1.0\nGenerator: umi-modelscope-download-1\nRoot-Is-Purelib: true\nTag: py3-none-any\n'
    payload[DIST + '/top_level.txt'] = b'modelscope\n'
    licenses = {name: data for name, data in original.items() if name.startswith(ORIGINAL_DIST + '/')
                and ('license' in name.casefold() or 'notice' in name.casefold() or 'copying' in name.casefold())}
    if not licenses:
        raise ValueError('原始ModelScope许可缺失')
    for name, data in licenses.items():
        payload[DIST + name[len(ORIGINAL_DIST):]] = data
    payload[DIST + '/UMI_RUNTIME_PROFILE.json'] = json_bytes({
        'format': 'umi-modelscope-download-v1', 'distribution': 'modelscope', 'version': VERSION,
        'upstreamVersion': UPSTREAM, 'upstreamWheelSha256': UPSTREAM_SHA256,
        'sourceArchiveSha256': SDIST_SHA256, 'sourceUrl': 'https://pypi.org/project/modelscope/' + UPSTREAM + '/',
        'scope': SCOPE, 'modules': sorted(KEEP_HASHES),
        'sourceGuide': '完整原始源码、原wheel与派生工具随组件在运行包外独立提供，独立摘要绑定；本包不是官方完整ModelScope。'})
    rows = io.StringIO(newline='')
    writer = csv.writer(rows, lineterminator='\n')
    for name, data in sorted(payload.items()):
        writer.writerow([name, 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode(), len(data)])
    writer.writerow([DIST + '/RECORD', '', ''])
    payload[DIST + '/RECORD'] = rows.getvalue().encode('utf-8')
    return payload


def read_derived(path, profile):
    if path.name != FILENAME or profile['version'] != VERSION or profile['filename'] != FILENAME:
        raise ValueError('ModelScope派生版本或文件名不符')
    payload = read_archive(path, profile['sha256'], DIST)
    marker = json.loads(payload[DIST + '/UMI_RUNTIME_PROFILE.json'])
    metadata = BytesParser().parsebytes(payload[DIST + '/METADATA'])
    if (marker.get('format') != 'umi-modelscope-download-v1' or marker.get('version') != VERSION
            or marker.get('modules') != sorted(KEEP_HASHES) or marker.get('upstreamWheelSha256') != UPSTREAM_SHA256
            or metadata['Name'] != 'modelscope' or metadata['Version'] != VERSION
            or {n for n in payload if n.startswith('modelscope/')} != set(KEEP_HASHES)):
        raise ValueError('ModelScope派生身份或下载闭包不符')
    return payload


def project_replacement(view, logical, prefix, profile, wheel, inspected, bounded_read):
    """主投影器调用：仅产生替换计划，不修改输入或写入目录。"""
    payload = read_derived(wheel, profile)
    if any(n == 'torch.py' or n.startswith(('torch/', 'torch-')) for n in logical):
        raise ValueError('下载派生配置不接受未审查的PyTorch运行根')
    matches = [n for n in logical if n.startswith('modelscope-') and n.endswith('.dist-info/METADATA') and n.count('/') == 1]
    if len(matches) != 1:
        raise ValueError('ModelScope输入发行版缺失或重复')
    dist = matches[0].split('/')[0]
    roots = ('modelscope/', dist + '/')
    selected = {n for n in logical if n.startswith(roots)}
    if len(selected) > 5000:
        raise ValueError('ModelScope输入成员超出预算')
    original, total = {}, 0
    for name in sorted(selected):
        data = bounded_read(view, prefix + '/' + name, min(4 * 1024**2, 64 * 1024**2 - total))
        total += len(data)
        checksum = digest(data)
        if inspected.setdefault(name, checksum) != checksum:
            raise ValueError('ModelScope投影输入改变')
        original[name] = data
    # 其它发行版拥有同一成员时拒绝替换，避免破坏插件私有共享闭包。
    record_budget = 0
    for name in logical:
        if name.count('/') != 1 or not name.endswith('.dist-info/RECORD') or name.startswith(dist + '/'):
            continue
        data = bounded_read(view, prefix + '/' + name, 3 * 1024**2)
        record_budget += len(data)
        if record_budget > 64 * 1024**2:
            raise ValueError('共享归属记录超过预算')
        checksum = digest(data)
        if inspected.setdefault(name, checksum) != checksum:
            raise ValueError('共享归属记录在检查期间改变')
        rows = list(csv.reader(io.StringIO(data.decode('utf-8'))))
        if any(len(row) != 3 for row in rows):
            raise ValueError('共享归属RECORD格式不符')
        selected_keys = {n.casefold() for n in selected}
        if any(row[0].casefold() in selected_keys for row in rows):
            raise ValueError('ModelScope成员存在其它发行版共享归属')
    metadata = BytesParser().parsebytes(original[matches[0]])
    if metadata['Name'] != 'modelscope' or metadata['Version'] not in {UPSTREAM, VERSION}:
        raise ValueError('ModelScope输入版本不符')
    if metadata['Version'] == VERSION:
        if original != payload:
            raise ValueError('派生ModelScope种子与独立构件完整载荷不符')
    else:
        if derive(original) != payload:
            raise ValueError('上游ModelScope输入与固定派生构件不符')
    return payload, selected, {'inputVersion': metadata['Version'], 'version': VERSION,
        'wheelSha256': profile['sha256'], 'inputFiles': len(selected), 'outputFiles': len(payload),
        'scope': SCOPE, 'status': 'PROJECTED_NOT_CONSUMER_ACCEPTED'}


def package(upstream, sdist, output, receipt):
    upstream, sdist, output, receipt = map(L.plain_path, (upstream, sdist, output, receipt))
    if not output.is_relative_to(ROOT / 'build') or not receipt.is_relative_to(ROOT / 'build/audit'):
        raise ValueError('派生产物和审计必须位于项目工作根')
    if output.exists() or receipt.exists() or receipt.is_relative_to(output):
        raise ValueError('只允许全新且与审计分离的构件目录')
    if L.sha256_file(sdist) != SDIST_SHA256:
        raise ValueError('完整源码归档摘要不符')
    original = read_archive(upstream, UPSTREAM_SHA256, ORIGINAL_DIST)
    payload = derive(original)
    output.mkdir(parents=True)
    archive = output / FILENAME
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as wheel:
        for name, data in sorted(payload.items()):
            entry = zipfile.ZipInfo(name, date_time=(2026, 7, 6, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            wheel.writestr(entry, data, compresslevel=6)
    profile = {'filename': FILENAME, 'sha256': L.sha256_file(archive), 'version': VERSION, 'upstreamVersion': UPSTREAM}
    if read_derived(archive, profile) != payload:
        raise ValueError('派生构件回读不符')
    result = {'status': 'PACKAGED_NOT_RUNTIME_ACCEPTED', 'createdUtc': datetime.now(timezone.utc).isoformat(),
              'producerSha256': L.sha256_file(Path(__file__)), 'wheel': str(archive), 'profile': profile,
              'upstreamWheel': str(upstream), 'upstreamWheelSha256': UPSTREAM_SHA256,
              'sourceArchive': str(sdist), 'sourceArchiveSha256': SDIST_SHA256,
              'inputBytes': sum(map(len, original.values())), 'outputBytes': sum(map(len, payload.values())),
              'inputFiles': {n: {'sha256': digest(d), 'bytes': len(d)} for n, d in original.items()},
              'outputFiles': {n: {'sha256': digest(d), 'bytes': len(d)} for n, d in payload.items()},
              'fixedInstallationChanged': False}
    with receipt.open('x', encoding='utf-8') as stream:
        stream.write(json_bytes(result).decode('utf-8'))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('upstream', 'sdist', 'output', 'receipt'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    record = package(args.upstream, args.sdist, args.output, args.receipt)
    print(json.dumps({k: v for k, v in record.items() if k not in {'inputFiles', 'outputFiles'}}, ensure_ascii=False, indent=2))
