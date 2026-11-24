"""从已审计的完整候选投影最简运行包；只改成员映射，不删除源树或重做 wheel。"""
from __future__ import annotations

import csv
from email.parser import BytesParser
import hashlib
import importlib.util
import io
import json
import mmap
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import zipfile


REPO = Path(__file__).resolve().parents[2]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


L = module('shared_layout', Path(__file__).with_name('runtime_archive_layout.py'))
S = module('shared_schema', REPO / 'UmiOCR-data/shared_runtime_bootstrap.py')
F = module('shared_gpu_lock', Path(__file__).with_name('freeze_gpu_runtime.py'))
V = module('shared_pe', Path(__file__).with_name('verify_release_evidence.py'))
D = module('shared_development', Path(__file__).with_name('runtime_development_strip.py'))
BASE_LOCK = REPO / 'build/requirements-base-windows.lock'
DEVELOPMENT_LOCK = REPO / 'build/runtime-development-strip.lock.json'
NUMPY_TOOLS = {'../../bin/f2py.exe', '../../bin/numpy-config.exe'}
DEVELOPMENT_ROOTS = {
    'numpy/_core/include/': {'.h', '.hpp'},
    'shiboken6/include/': {'.h', '.hpp'},
    'shiboken6/lib/cmake/': {'.cmake'},
    'PySide6/lib/cmake/': {'.cmake'},
    'pymupdf/mupdf-devel/include/': {'.h', '.hpp'},
    'nvidia/cufft/include/': {'.h', '.hpp'},
    'nvidia/cublas/include/': {'.h', '.hpp'},
    'nvidia/cuda_runtime/include/': {'.h', '.hpp'},
    'nvidia/cuda_runtime/lib/x64/': {'.lib'},
}
DEVELOPMENT_FILES = {'shiboken6/shiboken6.abi3.lib', 'PySide6/pyside6.abi3.lib', 'PySide6/pyside6qml.abi3.lib'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def row(source):
    if isinstance(source, bytes):
        return {'bytes': len(source), 'sha256': digest(source)}
    return {'bytes': source.stat().st_size, 'sha256': L.sha256_file(source)}


def development(name):
    return name in DEVELOPMENT_FILES or any(name.startswith(prefix) and PurePosixPath(name).suffix in suffixes
                                            for prefix, suffixes in DEVELOPMENT_ROOTS.items())


def locks(path):
    """核对四个目标 wheel 的原始来源锁；OpenCV 派生结果另由完整 RECORD/元数据和逐字节比对绑定。"""
    text = L.plain_path(path).read_text('utf-8-sig')
    matches = re.findall(r'^([A-Za-z0-9_.-]+)==([^\s]+)\s*\\\s*\n\s*--hash=sha256:([a-f0-9]{64})\s*$', text, re.M)
    target = [(name.casefold().replace('_', '-'), (version, sha)) for name, version, sha in matches
              if name.casefold().replace('_', '-') in S.COMMON]
    if len(target) != len(S.COMMON) or set(dict(target)) != S.COMMON.keys():
        raise ValueError('共享发行版上游 wheel 锁缺失、重复或格式不匹配')
    return dict(target)


def record_rows(raw):
    result = {}
    for fields in csv.reader(io.StringIO(raw.decode('utf-8-sig'))):
        if len(fields) != 3 or fields[0] in result:
            raise ValueError('发行版原始 RECORD 含错误或重复行')
        result[fields[0]] = fields[1:]
    return result


def _source(view, name):
    path = view.disk_files.get(name)
    if path is not None:
        return path
    if view.entries[name.casefold()]['bytes'] > 2 * 1024**2:
        raise ValueError('共享的 ZIP 源文件超过内存预算：' + name)
    return view.read_bytes(name)


def common_inventory(view, prefix, wheel_locks):
    paths = {}
    owners = {}
    keys = list(view.iter_files(prefix))
    for key in keys:
        name = key.removeprefix(prefix + '/')
        owner = S.common_owner(name.split('/')[0])
        if owner:
            paths[name] = _source(view, key)
            owners.setdefault(owner, set()).add(name)
    if set(owners) != S.COMMON.keys():
        raise ValueError('没有完整的四个通用发行版，不删除任何私有运行库')
    records, metadata, versions = {}, {}, {}
    for owner, files in sorted(owners.items()):
        info = [name for name in files if '/METADATA' in name and name.count('/') == 1 and name.endswith('/METADATA')]
        if len(info) != 1:
            raise ValueError('缺少唯一的发行版元数据：' + owner)
        metadata[owner] = info[0]
        m = BytesParser().parsebytes(view.read_bytes(prefix + '/' + info[0]), headersonly=True)
        version = m['Version']
        expected = wheel_locks[owner][0]
        if (m['Name'].casefold().replace('_', '-') != owner or not version
                or (version.split('+')[0] if owner == 'opencv-contrib-python' else version) != expected):
            raise ValueError('通用发行版元数据与原 wheel 锁不符：' + owner)
        requires = m.get_all('Requires-Dist', [])
        base = [req for req in requires if not re.search(r';\s*extra == "[a-z0-9-]+"\s*$', req)]
        if base != (['numpy==' + wheel_locks['numpy'][0]] if owner == 'opencv-contrib-python' else []):
            raise ValueError('通用发行版新增运行依赖，当前共享闭包不完整：' + owner)
        versions[owner] = version
        record = info[0].rsplit('/', 1)[0] + '/RECORD'
        raw = view.read_bytes(prefix + '/' + record)
        recorded = record_rows(raw)
        if not files <= recorded.keys() or (recorded.keys() & {x.removeprefix(prefix + '/') for x in keys}) != files:
            raise ValueError('发行版保留文件不等于其已安装 RECORD 的实际闭包：' + owner)
        records[owner] = (record, raw)
    # 其它发行版不得共享这些顶层文件，包含不同版本的 namespace 混装检查。
    for key in keys:
        rel = key.removeprefix(prefix + '/')
        if rel not in paths and rel.count('/') == 1 and rel.endswith('.dist-info/RECORD'):
            if record_rows(view.read_bytes(key)).keys() & paths.keys():
                raise ValueError('其它发行版仍拥有共有运行组成员：' + rel)
    return paths, records, versions


def matched(provider_files, provider_records, consumer_files, consumer_records, consumer_view):
    if provider_files.keys() != consumer_files.keys():
        raise ValueError('通用组发行版成员集合不同；不按文件名部分共享')
    exceptions = {}
    for name in sorted(provider_files):
        left, right = provider_files[name], consumer_files[name]
        if left == right:
            continue
        a, b = row(left), row(right)
        if a == b:
            continue
        numpy_name, original = provider_records['numpy']
        other_name, other = consumer_records['numpy']
        if name != numpy_name or name != other_name:
            raise ValueError('通用运行文件字节不匹配：' + name)
        x, y = record_rows(original), record_rows(other)
        differences = {key for key in x.keys() | y.keys() if x.get(key) != y.get(key)}
        # pip 的两个绝对 shebang 启动器均不在运行树；不能忽略其它 RECORD 差异。
        if (not differences <= NUMPY_TOOLS or x.keys() != y.keys()
                or any(key.rsplit('/', 1)[-1] in {p.rsplit('/', 1)[-1] for p in consumer_view.files()} for key in differences)):
            raise ValueError('NumPy RECORD 差异不只涉及未分发的开发启动器')
        exceptions[name] = {'provider': a, 'consumer': b, 'unshippedEntryPoints': sorted(differences)}
    return exceptions


def projected_containers(view, removed, changed_records=()):
    """仅重写受移动影响的 Stored ZIP；保留剩余条目的原始 RECORD 绑定。"""
    if view.manifest is None:
        return {}, {}, set()
    document = json.loads(json.dumps(view.manifest))
    rewritten, skipped, touched = {}, set(), False
    archives = []
    for original in document['archives']:
        name = original['path']
        gone = {m['logical_path'] for m in original['members'] if m['logical_path'] in removed}
        members = [m for m in original['members'] if m['logical_path'] not in gone]
        for m in members:
            record = m.get('source', {}).get('record_path')
            if record in changed_records or record in removed:
                raise ValueError('裁剪不得改变仍被 Stored ZIP 绑定的原始 RECORD：' + record)
        if not gone:
            archives.append(original)
            continue
        touched = True
        if gone - {s['logical_path'] for s in original['selections'] if s['kind'] == 'module'}:
            raise ValueError('不能拆分已封存的普通 Python package')
        if not members:
            skipped.add(name)
            continue
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED, allowZip64=False) as container:
            for m in members:
                item = zipfile.ZipInfo(m['member'], L.TIMESTAMP)
                item.create_system = 3
                is_directory = m['kind'] == 'directory'
                item.external_attr = ((stat.S_IFDIR | 0o755) if is_directory else (stat.S_IFREG | 0o644)) << 16
                if is_directory:
                    item.external_attr |= 0x10
                container.writestr(item, b'' if is_directory else view.read_bytes(m['logical_path']))
        raw = output.getvalue()
        if len(raw) > 16 * 1024**2:
            raise ValueError('重写的 Stored ZIP 超过内存预算')
        rewritten[name] = raw
        archives.append({**original, **row(raw), 'members': members,
                         'selections': [s for s in original['selections'] if s['logical_path'] not in gone]})
    if not touched:
        return {}, {}, set()
    document['archives'] = archives
    document['external'] = [r for r in document['external'] if not any(
        p == r['logical_path'] or p.startswith(r['logical_path'] + '/') for p in removed)]
    inventory = {m['logical_path']: {k: m[k] for k in ('bytes', 'sha256', 'source')}
                 for archive in archives for m in archive['members'] if m['kind'] == 'file'}
    raw = S.canonical_json({'schema_version': 1, 'files': inventory, 'source_binding': 'external-hashes-supplied'})
    document['inputs_manifest'] = {'path': L.INPUTS_NAME, **row(raw)}
    rewritten[L.MANIFEST_NAME] = S.canonical_json(document)
    return rewritten, {'projected/runtime-archive-inputs.json': raw}, skipped


def native_imports(paths, runtime):
    records, dlls = {}, {}
    for name, source in paths.items():
        if not name.lower().endswith(('.dll', '.pyd')):
            continue
        if not isinstance(source, Path):
            raise ValueError('共享原生组件不能来自 ZIP')
        with source.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as pe:
            if struct.unpack_from('<H', pe, struct.unpack_from('<I', pe, 0x3c)[0] + 4)[0] != 0x8664:
                raise ValueError('共享原生组件不是 Windows AMD64：' + name)
            records[name] = V.pe_import_tables(pe)
        if name.lower().endswith('.dll'):
            basename = PurePosixPath(name).name.casefold()
            value = row(source)
            if dlls.setdefault(basename, value) != value:
                raise ValueError('共有运行组有冲突的原生 DLL：' + basename)
    # 同一目录、显式 .libs、宿主 CPython 或 Windows 系统提供者；不查询 PATH。
    import os
    system = Path(os.environ['SystemRoot']) / 'System32'
    for name, imports in records.items():
        for dll in set(imports['normal_imports'] + imports['delay_imports']):
            if (re.fullmatch(r'(?:api|ext)-ms-[a-z0-9-]+\.dll', dll) or dll in dlls
                    or '/' not in dll and '\\' not in dll and ((runtime / dll).is_file() or (system / dll).is_file())):
                continue
            raise ValueError(f'共享原生闭包缺少声明或系统 DLL：{name} → {dll}')
    return records


def project(root, component, runtime, *, host_stage=None):
    """返回 (最简运行成员, 外置输入证据, 投影回执)。不能把未验的 GPU 闭包当公共包拆出。"""
    root = L.plain_path(root)
    if component == 'base':
        if host_stage is not None:
            raise ValueError('本体共享组由自身的已审计闭包提供')
        host_stage = root
    elif component not in ('cuda', 'vl') or host_stage is None:
        raise ValueError('插件精简分包必须绑定本轮已构建的本体')
    host = L.plain_path(host_stage) / 'UmiOCR-data'
    wp = locks(BASE_LOCK)
    plugin_id = {'cuda': 'win32_PaddleOCRv6_CUDA', 'vl': 'win32_PaddleOCRVL_1_6'}.get(component)
    part = 'UmiOCR-data' + ('/plugins/' + plugin_id if plugin_id else '')
    sub = 'vendor' if plugin_id else 'site-packages'
    part_path = root / part
    profile_path = L.plain_path(DEVELOPMENT_LOCK)
    profile_sha = L.sha256_file(profile_path)
    profile = L.read_json(profile_path)
    if plugin_id:
        tier = S.TIERS.get(L.read_json(part_path / 'cuda-support.json').get('cuda_version'))
        if tier is None:
            raise ValueError('开发材料裁剪须绑定实际 CUDA 档位')
        target = tier if component == 'cuda' else 'vl-' + tier
    else:
        target = 'base'
    with L.load_layout(host) as host_view, L.load_layout(part_path) as view:
        host_files, host_records, versions = common_inventory(host_view, 'site-packages', wp)
        host_dev, host_sources, host_metadata = D.project(host_view, 'site-packages', 'base', profile, L.canonical_relative)
        dev_names, dev_sources, dev_metadata = (D.project(view, sub, target, profile, L.canonical_relative)
                                                 if plugin_id else (host_dev, host_sources, host_metadata))
        # 已交付的 CUDA 3.1.1 引用精确的通用组摘要。保留 NumPy 的两份生成 C 文件和
        # 现有 RECORD，避免为约 15 KiB 的裁剪让旧插件失配或重复制发整个通用组。
        if any(name.removeprefix('site-packages/') in host_files for name in host_dev):
            raise ValueError('不在现有通用组中应用私有开发材料裁剪规则')
        shared = {p: source for p, source in host_files.items() if not development(p)}
        imports = native_imports(shared, host / 'runtime')
        group = S.group_document('common', {p: row(source) for p, source in shared.items()})
        group_raw = S.canonical_json(group)
        ref = {'kind': 'common', 'sha256': digest(group_raw)}
        binding = {'format': S.BINDING_FORMAT, 'abi': S.ABI, 'groups': [ref]}
        exceptions = {}
        if plugin_id:
            wc = locks(part_path / 'runtime-requirements.lock')
            if wc != wp:
                raise ValueError('本体和插件的通用 wheel 源锁不一致')
            provided, records, consumer_versions = common_inventory(view, sub, wc)
            if consumer_versions != versions:
                raise ValueError('已安装通用发行版版本不同，不删除私有依赖')
            exceptions = matched(host_files, host_records, provided, records, view)
        else:
            provided, records = host_files, host_records
        shared_names = {sub + '/' + name for name in provided}
        dev = {name for name in view.iter_files(sub) if development(name.removeprefix(sub + '/'))} | dev_names.keys()
        removed = shared_names | dev
        changes = {name: (dev_sources['development-originals/' + name.removeprefix(sub + '/')], raw)
                   for name, raw in dev_metadata.items() if name not in removed}
        rewrite, evidence, dropped_archives = projected_containers(view, removed, changes)
        evidence.update(dev_sources)
        for name, raw in records.values():
            evidence['original-records/' + name] = raw
        rewrite.update({name: after for name, (_, after) in changes.items()})
        dev_rows = {name: dev_names[name] if name in dev_names else row(_source(view, name)) for name in sorted(dev)}
        projection = dict(runtime)
        for name in removed | dropped_archives:
            projection.pop(part + '/' + name, None)
        for name, raw in rewrite.items():
            projection[part + '/' + name] = raw
        if plugin_id:
            manifest = L.read_json(part_path / 'umi-plugin.json')
            if manifest['id'] != plugin_id or 'shared_runtime' in manifest['runtime']:
                raise ValueError('投影仅接受未拆分的独立插件候选')
            manifest['host_api'] = '>=2.10,<3.0'
            manifest['runtime']['shared_runtime'] = binding
            projection[part + '/umi-plugin.json'] = S.canonical_json(manifest)
            projection[part + '/runtime.lock.json'] = S.canonical_json(F.project_lock(
                L.read_json(part_path / 'runtime.lock.json'), binding, shared_names, dev | dropped_archives,
                {name.removeprefix(part + '/'): source for name, source in projection.items() if name.startswith(part + '/')},
                group, record_changes=changes))
        else:
            group_part = f'{part}/{S.DIRECTORY}/{ref["sha256"]}'
            for name, source in shared.items():
                projection[group_part + '/site-packages/' + name] = source
            projection[group_part + '/' + S.GROUP_MANIFEST] = group_raw
            projection[part + '/' + S.HOST_BINDING] = S.canonical_json(binding)
            lock_name = part + '/native-dlls.lock.json'
            updated = []
            for item in L.read_json(root / lock_name):
                logical = item['path'].removeprefix(part + '/')
                if logical in dev:
                    raise ValueError('开发裁剪不能移除原生运行库')
                if logical in shared_names:
                    name = logical.removeprefix(sub + '/')
                    if item['sha256'] != group['files'][name]['sha256']:
                        raise ValueError('共享组与本体原生运行锁不符')
                    item = {**item, 'path': group_part + '/site-packages/' + name}
                updated.append(item)
            projection[lock_name] = S.canonical_json(updated)
        if L.sha256_file(profile_path) != profile_sha:
            raise ValueError('开发材料裁剪锁在投影期间改变')
        inspection = {'format': 'umi-shared-runtime-projection-v1', 'component': component, 'binding': binding,
                      'wheelLocks': wp, 'versions': versions, 'originalRecords': {v[0]: row(v[1]) for v in records.values()},
                      'semanticRecordDifferences': exceptions, 'sharedFiles': group['files'], 'removedDevelopment': dev_rows,
                      'developmentProfileSha256': profile_sha, 'developmentTarget': target,
                      'adjustedRecordFiles': {name: {'original': row(before), 'projected': row(after)}
                                              for name, (before, after) in sorted(changes.items())},
                      'normalAndDelayImports': imports, 'runtimeRewritten': sorted(rewrite),
                      'excludedPhysicalArchives': sorted(dropped_archives), 'publicReleaseAuthorized': False}
        evidence['shared-runtime-projection.json'] = S.canonical_json(inspection)
        return projection, evidence, inspection


def verify_installation(root, component):
    """审计已从最终归档组装的实际运行闭包；不重新颁发来源或发布证明。"""
    data = L.plain_path(root) / 'UmiOCR-data'
    if component == 'base':
        part, kind = data, 'host'
    else:
        ids = {'cuda': 'win32_PaddleOCRv6_CUDA', 'vl': 'win32_PaddleOCRVL_1_6'}
        part, kind = data / 'plugins' / ids[component], 'plugin'
    with L.load_layout(part, recover_externalized_inputs=True) as view:
        archives = [part / name for name in view.archives]
        if kind == 'host':
            groups = S.host_groups(data, archives)
            if not (data / 'shared_runtime_bootstrap.py').is_file():
                raise ValueError('共享宿主缺少独立运行引导程序')
            rows = L.read_json(data / 'native-dlls.lock.json')
            native_root = Path(root)
        else:
            groups = S.plugin_groups(part, archives=archives)
            lock = L.read_json(part / 'runtime.lock.json')
            rows, native_root = lock['files'], part
            S.dll_paths(groups, private=S.private_dll_paths(part / 'vendor'))
            seen = {row['path']: row['sha256'] for row in [*rows, *lock['sharedNative']]}
            support = L.read_json(part / 'cuda-support.json')
            if {row['path'] for row in support['providers']} != F.CORE_PROVIDERS or any(
                    seen.get(row['path']) != row['sha256'] for row in support['providers']):
                raise ValueError('新闭包的核心与原生架构覆盖证明不匹配')
            if component == 'cuda' and (part / 'notices/third-party-notices.zip').exists():
                raise ValueError('CUDA 运行包带入了未使用的 Qt WebEngine 声明归档')
        if not groups:
            raise ValueError('没有已封存的共享运行组')
        names = set()
        for entry in rows:
            name = L.canonical_relative(entry['path'])
            path = L.plain_path(native_root / name)
            if name.casefold() in names or L.sha256_file(path) != entry['sha256']:
                raise ValueError('实际重装运行项与锁定载荷不同：' + name)
            names.add(name.casefold())
        return {'status': 'PASS', 'scope': 'INSTALLED_SHARED_AND_PRIVATE_RUNTIME_BYTES_ONLY',
                'component': component, 'groups': [group.digest for group in groups],
                'sharedCounts': [len(group.files) for group in groups], 'lockedPrivateOrHostFiles': len(names),
                'storedArchives': list(view.archives), 'publicReleaseAuthorized': False}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=verify_installation.__doc__)
    parser.add_argument('--installed-root', required=True, type=Path)
    parser.add_argument('--component', required=True, choices=('base', 'cuda', 'vl'))
    args = parser.parse_args()
    print(json.dumps(verify_installation(args.installed_root, args.component), ensure_ascii=False))
