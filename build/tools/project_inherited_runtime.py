"""按精确锁继承已核验的运行闭包；只移动新构建的已知多余成员，不按名称推断删除。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import zipfile


def adjacent(name):
    spec = importlib.util.spec_from_file_location('inherited_' + name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


L = adjacent('runtime_archive_layout')
M = adjacent('merge_runtime')
# 复用项目的 Windows 独占句柄实现；不更改权限、只读属性，也不按路径替换已打开对象。
sys.path.insert(0, str(Path(__file__).resolve().parent))
F = adjacent('fixed_installation_update')
FORMAT = 'umi-exact-inherited-gpu-runtime-v1'
IDS = {'cuda': 'win32_PaddleOCRv6_CUDA', 'vl': 'win32_PaddleOCRVL_1_6'}
MARKER = 'runtime-subset.json'


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def write_new(path, value):
    with L.plain_path(path).open('xb') as stream:
        stream.write(json_bytes(value))
        stream.flush()
        os.fsync(stream.fileno())


def read_bounded(path, budget):
    path = L.plain_path(path)
    with path.open('rb') as stream:
        raw = stream.read(budget + 1)
    if len(raw) > budget:
        raise ValueError('锁或来源记录超过读取预算')
    return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=L._json_object), hashlib.sha256(raw).hexdigest()


def binding(files):
    return {name: {'sha256': L.sha256_file(path), 'bytes': path.stat().st_size}
            for name, path in sorted(files.items())}


def tree_digest(rows):
    return hashlib.sha256(json_bytes(rows)).hexdigest()


def profile_inputs(profile_path, component):
    profile, checksum = read_bounded(profile_path, 16 * 1024**2)
    if profile.get('format') != FORMAT or profile.get('component') != component:
        raise ValueError('精确继承锁的组件或格式不符')
    inputs, omissions, retained = (profile.get(key) for key in ('inputFiles', 'excludedFiles', 'retainedFiles'))
    if (not isinstance(inputs, dict) or not 1 <= len(inputs) <= 60000 or not isinstance(omissions, dict)
            or not isinstance(retained, list) or len(retained) != len(set(retained))
            or set(inputs) != set(retained) | set(omissions) or set(retained) & set(omissions)
            or len({name.casefold() for name in inputs}) != len(inputs)):
        raise ValueError('精确继承锁的成员集合无效、重复或重叠')
    for name, row in inputs.items():
        L.canonical_relative(name)
        if (not isinstance(row, dict) or set(row) != {'sha256', 'bytes'}
                or not isinstance(row['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', row['sha256'])
                or type(row['bytes']) is not int or not 0 <= row['bytes'] <= 4 * 1024**3):
            raise ValueError('精确继承锁的逐文件摘要或大小无效：' + name)
    if sum(row['bytes'] for row in inputs.values()) > 12 * 1024**3:
        raise ValueError('精确继承输入字节超过预算')
    launchers = profile.get('developmentLaunchers', {})
    if (not isinstance(launchers, dict) or set(launchers) - {'bin/distro.exe'}
            or launchers and component != 'vl' or not launchers.keys() <= omissions.keys()):
        raise ValueError('开发入口的例外必须是已审阅的具名 Distro 命令')
    for rule in launchers.values():
        if rule != {'entry': 'from distro.distro import main', 'mainSha256': '03d2124eba7cdebccb8e7332f4b25dbf8f5b1d917647f6ce99dd8e1e2446059a'}:
            raise ValueError('开发入口的例外摘要或入口不符')
    native = {name for name in inputs if Path(name).suffix.casefold() in {'.dll', '.pyd', '.exe'} and name not in launchers}
    if set(profile.get('nativeCodeMustRemain', [])) != native or not native <= set(retained):
        raise ValueError('不得移出或漏记 GPU/依赖原生代码')
    for name, reason in omissions.items():
        leaf = Path(name).name.upper()
        parts = name.split('/')
        if (not isinstance(reason, str) or not reason.strip()
                or leaf.startswith(('LICENSE', 'LICENCE', 'COPYING', 'COPYRIGHT', 'NOTICE', 'AUTHORS', 'PATENTS'))
                or len(parts) == 2 and parts[0].endswith('.dist-info') and parts[1] in {'METADATA', 'RECORD'}):
            raise ValueError('不能移出版权、许可或原始发行版记录：' + name)
    return profile, checksum


def copy_time_omissions(view, logical, prefix, profile_path, inspected, sizes):
    """只跳过原始字节已匹配的明确成员；补丁会改变的成员留给最终闭包验证。"""
    profile, checksum = profile_inputs(profile_path, 'cuda')
    omitted, deferred = set(), []
    for name in sorted(set(profile['excludedFiles']) & logical.keys()):
        expected = profile['inputFiles'][name]
        source_name = logical[name]
        if sizes[name] != expected['bytes']:
            deferred.append(name)
            continue
        if source_name in view.disk_files:
            actual = L.sha256_file(view.disk_files[source_name])
        else:
            entry = view.entries[source_name.casefold()]
            actual = entry['sha256']
        if actual != expected['sha256']:
            deferred.append(name)
            continue
        if inspected.setdefault(name, actual) != actual:
            raise ValueError('精确复制排除与已检查来源发生冲突')
        omitted.add(name)
    return omitted, {'profileSha256': checksum, 'omittedAtCopy': sorted(omitted),
                     'deferredToFinalProjection': deferred,
                     'scope': '原始种子不变，最终保留集合与 GPU 库字节仍须在补丁后独立验证。'}


def project(vendor, profile_path, ownership_receipt, project_root, work, component, *, occupancy_check=None):
    """已排除成员可以在种子中缺席；保留集合、其字节及未知项始终严格检查。"""
    vendor, profile_path, ownership_receipt, project_root, work = map(
        L.plain_path, (vendor, profile_path, ownership_receipt, project_root, work))
    stage = project_root / 'build/staging'
    audit = project_root / 'build/audit'
    if (not vendor.is_relative_to(stage) or vendor.parts[-1] != 'vendor'
            or vendor.parent.name != IDS[component] or not work.is_relative_to(audit)
            or work.exists() or not work.parent.is_dir()):
        raise ValueError('只允许项目 build/staging 的新候选与新 build/audit 工作目录')
    plugin = vendor.parent
    candidate = plugin.parents[2]
    if not candidate.is_relative_to(stage) or any('seed' in part.casefold() or 'frozen' in part.casefold()
                                                 for part in candidate.relative_to(stage).parts):
        raise ValueError('不能修改种子或冻结树')
    if any((plugin / name).exists() for name in ('runtime.lock.json', MARKER, 'runtime-archives.json')):
        raise ValueError('已冻结、聚合或已执行过继承的候选不得再次修改')
    owner, owner_sha = read_bounded(ownership_receipt, 32 * 1024**2)
    destination = L.plain_path(owner.get('destination', ''))
    moved_projection = candidate / '.build/projected-vendor'
    if (owner.get('status') not in {'PROJECTED_NOT_COMPONENT_ACCEPTED', 'PROJECTED_NOT_CONSUMER_ACCEPTED'}
            or owner.get('sourceModified') is not False
            or not (destination == vendor or destination == moved_projection and not destination.exists())
            or not isinstance(owner.get('outputFiles'), dict) or not owner['outputFiles']
            or vendor.is_relative_to(L.plain_path(owner['source']))):
        raise ValueError('缺少此新候选的实际投影所有权回执')
    manifest, _ = read_bounded(plugin / 'umi-plugin.json', 64 * 1024)
    if manifest.get('id') != IDS[component]:
        raise ValueError('候选插件身份不符')
    profile, profile_sha = profile_inputs(profile_path, component)
    inputs, omitted_names, retained = profile['inputFiles'], set(profile['excludedFiles']), set(profile['retainedFiles'])
    files = L.tree_files(vendor)
    if not retained <= files.keys() or files.keys() - inputs.keys():
        raise ValueError('候选缺失保留成员或含未知输入；不自动放宽精确锁')
    check = occupancy_check or M.running_processes
    M.PROJECT_ROOT = project_root
    if check(candidate):
        raise ValueError('候选正在运行，须由用户正常退出')
    actual = binding(files)
    if any(actual[name] != inputs[name] for name in actual):
        raise ValueError('候选与精确输入锁的字节不符')
    for name, rule in profile.get('developmentLaunchers', {}).items():
        if name not in files:
            continue
        if inputs[name]['bytes'] > 3 * 1024**2:
            raise ValueError('开发入口大小超过预算')
        with zipfile.ZipFile(files[name]) as archive:
            info = archive.getinfo('__main__.py')
            if info.file_size > 65536:
                raise ValueError('开发入口代码超过预算')
            code = archive.read(info)
        if hashlib.sha256(code).hexdigest() != rule['mainSha256'] or rule['entry'] not in code.decode('utf-8').splitlines():
            raise ValueError('开发入口原始内嵌代码不符')
    if L.sha256_file(profile_path) != profile_sha or L.sha256_file(ownership_receipt) != owner_sha:
        raise ValueError('输入锁或所有权回执在核对期间改变')
    removed = {name: actual[name] for name in sorted(files.keys() & omitted_names)}
    expected = {name: inputs[name] for name in sorted(retained)}
    work.mkdir()
    hold = work / 'omitted-original-inputs'
    hold.mkdir()
    preview = {'status': 'EXACT_PROJECTION_PREVIEW_NOT_ACCEPTANCE', 'component': component,
               'candidate': str(candidate), 'vendor': str(vendor), 'profile': str(profile_path),
               'profileSha256': profile_sha, 'ownershipReceipt': str(ownership_receipt), 'ownershipSha256': owner_sha,
               'inputFiles': actual, 'expectedOutputFiles': expected, 'moveToExternalAudit': removed,
               'alreadyAbsentExcludedFiles': sorted(omitted_names - actual.keys()),
               'nativeCodeRetained': len(profile['nativeCodeMustRemain']),
               'sourceSeedChanged': False, 'userModelsOrFixedInstallationChanged': False}
    write_new(work / 'preview.json', preview)
    if check(candidate):
        raise ValueError('候选在写入前已被占用，停止')
    moved = []
    # 每步意图与结果独立持久化；失败后保留新候选及原始字节，不重用半投影树。
    with (work / 'moves.jsonl').open('xb') as journal:
        def event(value):
            journal.write(json_bytes(value).replace(b'\n', b'') + b'\n')
            journal.flush()
            os.fsync(journal.fileno())
        for name, row in removed.items():
            source = L.plain_path(vendor / name)
            target = L.plain_path(hold / name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with F._File(source, mutate=True) as file:
                file.verify(row['sha256'])
                event({'intent': name, 'sha256': row['sha256'], 'identity': file.identity()})
                file.rename(target, row['sha256'])
                event({'moved': name, 'identity': file.identity()})
            moved.append(name)
    after = binding(L.tree_files(vendor))
    external = binding(L.tree_files(hold))
    if after != expected or external != removed or L.sha256_file(profile_path) != profile_sha:
        raise ValueError('投影后运行集合、外置原件或精确锁发生变化')
    marker = {'format': FORMAT, 'component': component, 'profileSha256': profile_sha,
              'logicalVendorBinding': tree_digest(after), 'retainedFiles': len(after), 'omittedFiles': len(omitted_names),
              'scope': profile['notice'], 'originalDistributionRecordsPreserved': True,
              'nativeCodeBytesUnchangedByProjection': True}
    write_new(plugin / MARKER, marker)
    result = {**preview, 'status': 'EXACT_PROJECTED_NOT_CONSUMER_ACCEPTED',
              'createdUtc': datetime.now(timezone.utc).isoformat(), 'outputFiles': after,
              'omittedOriginalsRoot': str(hold), 'movedFiles': len(moved),
              'movedBytes': sum(row['bytes'] for row in removed.values()),
              'markerSha256': L.sha256_file(plugin / MARKER), 'producerSha256': L.sha256_file(__file__),
              'publicReleaseAuthorized': False}
    write_new(work / 'result.json', result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('vendor', 'profile', 'ownership-receipt', 'project-root', 'work'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--component', choices=tuple(IDS), required=True)
    args = p.parse_args()
    value = project(args.vendor, args.profile, args.ownership_receipt, args.project_root, args.work, args.component)
    print(json.dumps({key: value[key] for key in ('status', 'component', 'movedFiles', 'movedBytes', 'nativeCodeRetained')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
