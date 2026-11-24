"""Stream a reviewed cu126 package into a fresh candidate; reuse vendor bytes, not old program code."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runtime_archive_layout as layout

IDS = {'cuda': 'win32_PaddleOCRv6_CUDA', 'vl': 'win32_PaddleOCRVL_1_6'}
CORE = {'vendor/paddle/base/libpaddle.pyd', 'vendor/paddle/libs/phi.dll'}
LAYOUT_FILES = {'runtime-archives.json', 'vendor.zip'}
MIN_RESERVE = 10 * 1024**3
REPO_LIMIT = 300 * 1024**3
BUDGET_MARGIN = 128 * 1024**2


def read_json(path, limit):
    with layout.plain_path(path).open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f'JSON 输入超过预算：{path}')
    return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=layout._json_object), hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    with layout.plain_path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, sort_keys=True, ensure_ascii=False, indent=2)
        stream.write('\n')


def reviewed_row(lock, component, requirements, sources):
    rules, sha = read_json(lock, 64 * 1024)
    row = rules['components'][component]
    if (rules.get('format') != 'umi-reviewed-cu126-runtime-seed-v1'
            or rules.get('platform') != 'windows-x64-cp313' or rules.get('cudaVersion') != '12.6'
            or not re.fullmatch('[0-9a-f]{64}', rules['baselineReceiptSha256'])
            or row['id'] != IDS[component] or not re.fullmatch(r'\d+\.\d+\.\d+', row['version'])
            or any(type(row[key]) is not int or not 1 <= row[key] <= 6 * 1024**3 for key in ('archiveBytes', 'runtimeBytes'))
            or any(not re.fullmatch('[0-9a-f]{64}', row[key])
                   for key in ('archiveSha256', 'layoutSha256', 'originalRequirementsSha256'))
            or layout.sha256_file(layout.plain_path(requirements)) != rules['requirementsSha256']
            or layout.sha256_file(layout.plain_path(sources)) != rules['sourcesSha256']):
        raise ValueError('不匹配审定的 Windows x64 / CPython 3.13 / cu126 依赖及来源')
    return row, sha, rules['baselineReceiptSha256']


def recover_input_inventory(plugin):
    # 从已核验的 Stored-ZIP 成员和 RECORD 重现原始外置清单，不能将其当作新上游来源。
    with layout.load_layout(plugin, recover_externalized_inputs=True) as view:
        if set(view.archives) != {'vendor.zip'} or not view.recovered_input_inventory:
            raise ValueError('普通档必须继承已验证的 Stored-ZIP 及原始输入清单')
        files = {entry['logical_path']: {key: entry[key] for key in ('bytes', 'sha256', 'source')}
                 for entry in view.entries.values()}
        expected = view.recovered_input_inventory
    for source in ('external-hashes-supplied', 'self-recorded-not-external-source-proof'):
        raw = (json.dumps({'schema_version': 1, 'files': files, 'source_binding': source},
                          ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
        if expected == {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}:
            with (plugin / layout.INPUTS_NAME).open('xb') as stream:
                stream.write(raw)
            return expected
    raise ValueError('恢复后输入清单与原始摘要不符')


def restore(archive, destination, component, row, *, inspected=None, free_check=None):
    """仅复制指定成员；完整归档在同一个只读打开的文件上预先校验。"""
    archive = layout.plain_path(archive)
    prefix = f'UmiOCR-data/plugins/{IDS[component]}/'
    copy_meta = CORE | {'runtime-requirements.lock'}
    if inspected is not None:
        if destination.exists():
            raise FileExistsError(destination)
    elif any((destination / name).exists() for name in LAYOUT_FILES | {layout.INPUTS_NAME, 'vendor', 'models'}):
        raise ValueError('已存在运行时或模型，不在旧候选上覆盖')
    copied, seen, meta = {}, set(), {}
    with archive.open('rb') as source:
        if archive.stat().st_size != row['archiveBytes'] or hashlib.file_digest(source, 'sha256').hexdigest() != row['archiveSha256']:
            raise ValueError('精简基线归档大小或 SHA-256 不符，拒绝恢复')
        source.seek(0)
        if inspected is not None:
            destination.mkdir(exist_ok=False)
        size = 0
        with tarfile.open(fileobj=source, mode='r|xz') as payload:
            for member in payload:
                name = layout.canonical_relative(member.name.removeprefix('./').rstrip('/'))
                if len(seen) >= 30000 or name.casefold() in seen:
                    raise ValueError('归档成员过多或出现重复/大小写别名')
                seen.add(name.casefold())
                if member.isdir():
                    if not (name.startswith(prefix) or prefix.startswith(name + '/')):
                        raise ValueError('普通档基线不是单组件归档')
                    continue
                if not member.isfile() or not name.startswith(prefix):
                    raise ValueError(f'普通档基线成员不属于目的组件：{name}')
                relative = name[len(prefix):]
                size += member.size
                if size > row['runtimeBytes'] or not 0 <= member.size <= 2 * 1024**3:
                    raise ValueError('普通档基线解包字节超过已审定值')
                selected = relative in copy_meta if inspected is not None else (
                    relative in LAYOUT_FILES or relative.startswith('vendor/')
                    or component == 'cuda' and relative.startswith('models/'))
                if not (selected or inspected is not None or relative in {'umi-plugin.json', 'runtime-requirements.lock'}):
                    continue
                digest = hashlib.sha256()
                target = layout.plain_path(destination / relative) if selected else None
                if target is not None:
                    if free_check:
                        free_check(member.size)
                    target.parent.mkdir(parents=True, exist_ok=True)
                data = payload.extractfile(member)
                if data is None:
                    raise ValueError(f'归档成员不能读取：{name}')
                with data:
                    if target is not None:
                        with target.open('xb') as output:
                            while block := data.read(1024**2):
                                digest.update(block)
                                output.write(block)
                        if target.stat().st_size != member.size or layout.sha256_file(target) != digest.hexdigest():
                            raise ValueError(f'候选落盘摘要不符：{name}')
                        copied[relative] = {'bytes': member.size, 'sha256': digest.hexdigest()}
                    elif relative == 'umi-plugin.json':
                        if member.size > 64 * 1024:
                            raise ValueError('基线插件清单超出预算')
                        raw = data.read()
                        digest.update(raw)
                        manifest = json.loads(raw.decode('utf-8-sig'))
                        if manifest['id'] != row['id'] or manifest['version'] != row['version']:
                            raise ValueError('基线插件身份不符')
                    else:
                        while block := data.read(1024**2):
                            digest.update(block)
                actual = digest.hexdigest()
                if inspected is not None and inspected.get(name) != actual:
                    raise ValueError(f'基线归档与独立最终所有权不符：{name}')
                if relative in {'umi-plugin.json', 'runtime-archives.json', 'runtime-requirements.lock'}:
                    meta[relative] = actual
        if size != row['runtimeBytes'] or not {'umi-plugin.json', 'runtime-archives.json', 'runtime-requirements.lock'} <= meta.keys():
            raise ValueError('普通档基线逻辑字节或元数据清单不符')
        if (meta['runtime-archives.json'] != row['layoutSha256']
                or meta['runtime-requirements.lock'] != row['originalRequirementsSha256']):
            raise ValueError('普通档基线布局或原始依赖记录不符')
        if inspected is None:
            required = CORE | LAYOUT_FILES
            if required - copied.keys():
                raise ValueError('精简种子缺少依赖、核心 DLL 或 Stored-ZIP')
            inventory = recover_input_inventory(destination)
            copied[layout.INPUTS_NAME] = inventory
        elif copy_meta - copied.keys():
            raise ValueError('未找到需核对的核心 DLL 或依赖锁')
        source.seek(0)
        if hashlib.file_digest(source, 'sha256').hexdigest() != row['archiveSha256']:
            raise ValueError('精简基线归档在读取期间改变')
    return copied, meta


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('archive', 'destination', 'lock', 'requirements', 'sources', 'project', 'report'):
        p.add_argument('--' + key, type=Path, required=True)
    p.add_argument('--component', choices=IDS, required=True)
    p.add_argument('--allocated-bytes', type=int, required=True, help='本阶段写入前实测的双仓分配空间')
    p.add_argument('--inspect-baseline', type=Path, help='只提取核心用于架构核对，并与独立原所有权逐文件比较')
    args = p.parse_args()
    archive, dest, project, report = map(layout.plain_path, (args.archive, args.destination, args.project, args.report))
    component = args.component
    row, lock_sha, baseline_sha = reviewed_row(args.lock, component, args.requirements, args.sources)
    inspected = None
    if args.inspect_baseline is not None:
        proof, actual = read_json(args.inspect_baseline, 16 * 1024**2)
        if actual != baseline_sha or proof['status'] != 'FIXED_INSTALL_UPDATED_PAYLOAD_AND_USER_STATE_VERIFIED':
            raise ValueError('不是本轮锁定的历史终态载荷')
        inspected = proof['finalPayload']
    valid_dest = (dest.is_relative_to(project / 'build/tmp') if inspected is not None else
                  dest.is_relative_to(project / 'build/staging') and dest.parts[-3:] == ('UmiOCR-data', 'plugins', IDS[component]))
    if (not valid_dest or report.exists() or not report.is_relative_to(project / 'build/audit')
            or not report.parent.is_dir() or archive.is_relative_to(dest) or report.is_relative_to(dest)):
        raise ValueError('仅接受当前项目内独立的新候选或诊断根与审计记录')
    growth = (1024 * 1024**2 if inspected is not None else row['runtimeBytes']) + BUDGET_MARGIN

    def free_check(need):
        if shutil.disk_usage(project).free < MIN_RESERVE + need:
            raise OSError('D 盘 10 GiB 保留线：停止扩大候选')

    if not 0 < args.allocated_bytes <= REPO_LIMIT - growth:
        raise OSError('双仓 300 GiB 预算不足，停止恢复精简种子')
    free_check(growth)
    assert sys.flags.isolated and sys.flags.dont_write_bytecode
    copied, meta = restore(archive, dest, component, row, inspected=inspected, free_check=free_check)
    result = {'status': 'BASELINE_INSPECTED' if inspected is not None else 'BYTE_EXACT_CU126_SEED_RESTORED',
              'component': component, 'cudaVersion': '12.6', 'archive': str(archive),
              'archiveSha256': row['archiveSha256'], 'seedLockSha256': lock_sha, 'seedVersion': row['version'],
              'historicalOwnershipCompared': inspected is not None, 'baselineMetadataSha256': meta,
              'destination': str(dest), 'copied': copied, 'reappliedPaddleXPatch': False,
              'candidateAccepted': False, 'publicReleaseAuthorized': False}
    write_json(report, result)
    if inspected is None:
        marker = {'format': 'umi-gpu-vendor-reused-from-reviewed-seed-v1', 'component': component,
                  'cudaVersion': '12.6', 'profileSha256': lock_sha, 'archiveSha256': row['archiveSha256'],
                  'seedVersion': row['version'], 'seedReceiptSha256': layout.sha256_file(report),
                  'scope': '逐成员继承精简依赖及原始许可；不复用旧适配器、启动器或版本。'}
        write_json(dest / 'runtime-subset.json', marker)
    print(f'{result["status"]}: {component}, {len(copied)} files')


if __name__ == '__main__':
    main()
