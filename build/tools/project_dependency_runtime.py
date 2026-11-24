"""从只读松散/Stored-ZIP输入生成新依赖根；显式派生OpenCV及本体图像子集。"""
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
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('projection_layout', Path(__file__).with_name('runtime_archive_layout.py'))
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def read_wheel(path, profile):
    """先核对独立锁，再验证标准RECORD；不执行下载构件中的代码。"""
    path = L.plain_path(path)
    if path.name != profile['filename'] or L.sha256_file(path) != profile['sha256']:
        raise ValueError('派生wheel文件名/独立锁摘要不符')
    with zipfile.ZipFile(path) as wheel:
        entries = wheel.infolist()
        names = [L.canonical_relative(item.filename) for item in entries]
        if (len(entries) > 20000 or len({name.casefold() for name in names}) != len(names)
                or sum(item.file_size for item in entries) > 128 * 1024**2
                or any(item.file_size > 64 * 1024**2 or item.is_dir()
                       or ((item.external_attr >> 16) & 0o170000) not in {0, 0o100000} for item in entries)):
            raise ValueError('派生wheel成员别名、类型或大小预算不符')
        dist = 'opencv_contrib_python-' + profile['version'] + '.dist-info'
        if any(not (name.startswith('cv2/') or name.startswith(dist + '/')) for name in names):
            raise ValueError('派生wheel越过指定包边界')
        record = dist + '/RECORD'
        rows = list(csv.reader(io.StringIO(wheel.read(record).decode('utf-8'))))
        if any(len(row) != 3 for row in rows) or len(rows) != len(names) or {row[0] for row in rows} != set(names):
            raise ValueError('派生wheel标准RECORD成员不符')
        payload = {name: wheel.read(name) for name in names}
        for name, checksum, size in rows:
            if name == record:
                if checksum or size:
                    raise ValueError('RECORD自身不得伪造摘要')
                continue
            data = payload[name]
            expected = 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode('ascii')
            if checksum != expected or size != str(len(data)):
                raise ValueError('派生wheel RECORD字节不符：' + name)
        metadata = BytesParser().parsebytes(payload[dist + '/METADATA'], headersonly=True)
        identity = json.loads(payload[dist + '/UMI_RUNTIME_PROFILE.json'])
        if (metadata['Name'] != 'opencv-contrib-python' or metadata['Version'] != profile['version']
                or identity.get('sourceCommit') != profile['sourceCommit']
                or identity.get('modules') != profile['modules']):
            raise ValueError('派生wheel元数据/功能/源码身份不符')
    if L.sha256_file(path) != profile['sha256']:
        raise ValueError('派生wheel在核验期间改变')
    return payload


def bounded_read(view, logical_name, limit):
    """松散输入只读有限字节，ZIP成员先查已核验大小；不先整文件读入再检查预算。"""
    logical_name = L.canonical_relative(logical_name)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise ValueError('派生输入读取预算必须是非负整数')
    entry = view.entries.get(logical_name.casefold())
    if entry is not None:
        if entry['bytes'] > limit:
            raise ValueError('派生输入读取超出有限预算：' + logical_name)
        data = view.read_bytes(logical_name)
    else:
        path = L.plain_path(view.disk_files[logical_name])
        with path.open('rb') as stream:
            data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('派生输入读取超出有限预算：' + logical_name)
    if entry is None and view.source_hashes is not None and logical_name in view.source_hashes:
        if digest(data) != view.source_hashes[logical_name]:
            raise L.LayoutError('Loose source differs from external source hashes')
    return data


def find_distribution(view, names, prefix, name, version, inspected, optional=False):
    matches = []
    for relative in names:
        if relative.count('/') != 1 or not relative.endswith('.dist-info/METADATA'):
            continue
        logical_name = prefix + '/' + relative
        size = view.entries[logical_name.casefold()]['bytes'] if logical_name.casefold() in view.entries else view.disk_files[logical_name].stat().st_size
        if size > 3 * 1024**2:
            raise ValueError('发行版元数据超过有限预算')
        raw = bounded_read(view, logical_name, 3 * 1024**2)
        checksum = digest(raw)
        if inspected.setdefault(relative, checksum) != checksum:
            raise ValueError('发行版元数据在检查期间改变：' + relative)
        metadata = BytesParser().parsebytes(raw, headersonly=True)
        if (metadata.get('Name') or '').lower().replace('_', '-') == name:
            matches.append((relative.split('/')[0], metadata.get('Version')))
    if not matches and optional:
        return None, None
    allowed = {version} if isinstance(version, str) else set(version)
    if len(matches) != 1 or matches[0][1] not in allowed:
        raise ValueError('上游发行版缺失、重复或版本不符：' + name)
    return matches[0]


def seed_payload(view, logical, prefix, roots, inspected):
    """核验已知派生种子的完整包字节；版本字段或自声明RECORD不能单独证明来源。"""
    selected = [name for name in logical if name.startswith(roots)]
    if len(selected) > 20000:
        raise ValueError('派生种子包成员超出有限预算')
    payload, total = {}, 0
    for name in selected:
        data = bounded_read(view, prefix + '/' + name, min(64 * 1024**2, 128 * 1024**2 - total))
        total += len(data)
        if total > 128 * 1024**2:
            raise ValueError('派生种子包字节超出有限预算')
        checksum = digest(data)
        if inspected.setdefault(name, checksum) != checksum:
            raise ValueError('派生种子在检查期间改变：' + name)
        payload[name] = data
    return payload


def cuda_exclusions(view, logical, prefix, profile, inspected, sizes):
    """只排除显式版本/命名空间及已识别的pip开发命令；RECORD共享归属不丢失。"""
    rules = profile.get('cudaExcludedDistributions', [])
    if {rule['name'] for rule in rules} != {'bce-python-sdk', 'crc32c', 'future', 'psutil', 'pycryptodome'} or len(rules) != 5:
        raise ValueError('CUDA可选依赖排除规则不完整或重复')
    omitted, decisions, removed_owners = set(), [], set()
    def read(relative):
        if sizes[relative] > 3 * 1024**2:
            raise ValueError('可选依赖记录超过有限预算')
        data = bounded_read(view, prefix + '/' + relative, 3 * 1024**2)
        checksum = digest(data)
        if inspected.setdefault(relative, checksum) != checksum:
            raise ValueError('可选依赖输入在检查期间改变：' + relative)
        return data
    for rule in rules:
        packages = tuple(L.canonical_relative(package) + '/' for package in rule['packages'])
        if any('/' in package[:-1] for package in packages):
            raise ValueError('CUDA排除只接受明确的顶层包')
        dist, version = find_distribution(view, logical, prefix, rule['name'], rule['version'], inspected, optional=True)
        scripts = {L.canonical_relative(name): entry for name, entry in rule['scripts'].items()}
        for name in scripts:
            if not name.startswith('bin/') or not name.endswith('.exe') or name.count('/') != 1:
                raise ValueError('可选包命令不在显式开发工具边界')
        package_files = {name for name in logical if name.startswith(packages)}
        if dist is None:
            if package_files or set(scripts) & set(logical):
                raise ValueError('可选发行版元数据缺失但命名空间/命令残留：' + rule['name'])
            decisions.append({'name': rule['name'], 'status': 'ALREADY_ABSENT', 'files': 0})
            continue
        record = dist + '/RECORD'
        if record not in logical:
            raise ValueError('排除可选发行版前必须有RECORD：' + rule['name'])
        rows = list(csv.reader(io.StringIO(read(record).decode('utf-8'))))
        if any(len(row) != 3 for row in rows):
            raise ValueError('可选发行版RECORD格式错误')
        present = {row[0] for row in rows if row[0] in logical}
        selected = package_files | {name for name in logical if name.startswith(dist + '/')}
        if not package_files or not selected <= present or present - selected - set(scripts):
            raise ValueError('可选发行版文件归属超出明确命名空间或缺失：' + rule['name'])
        for name, entry in scripts.items():
            if name not in logical:
                continue
            raw = read(name)
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    main = archive.getinfo('__main__.py')
                    if main.file_size > 65536:
                        raise ValueError('pip开发命令入口超过预算')
                    code = archive.read(main).decode('utf-8')
            except (zipfile.BadZipFile, KeyError, UnicodeError) as exc:
                raise ValueError('不能识别可选包的pip开发命令：' + name) from exc
            if entry not in code.splitlines():
                raise ValueError('可选包开发命令入口与已核对规则不符：' + name)
            selected.add(name)
        if selected & omitted:
            raise ValueError('可选发行版之间存在重复归属')
        omitted.update(selected)
        removed_owners.add(dist)
        decisions.append({'name': rule['name'], 'version': version, 'status': 'EXCLUDED_NOT_CONSUMER_ACCEPTED',
                          'files': len(selected), 'bytes': sum(sizes[name] for name in selected),
                          'outsideRecordPathsNotFollowed': [row[0] for row in rows if row[0].startswith('../')]})
    # 其它发行版仍拥有任何目标文件时不能删除。外部脚本路径只记录，绝不沿../访问。
    budget = 0
    for record in (name for name in logical if name.count('/') == 1 and name.endswith('.dist-info/RECORD')):
        if record.split('/')[0] in removed_owners:
            continue
        budget += sizes[record]
        if budget > 128 * 1024**2:
            raise ValueError('发行版归属扫描超过有限预算')
        rows = csv.reader(io.StringIO(read(record).decode('utf-8')))
        if any(row and row[0] in omitted for row in rows):
            raise ValueError('待裁包文件仍被其它发行版拥有：' + record)
    return omitted, decisions


def development_scripts(view, logical, prefix, profile, component, inspected):
    """只裁显式pip命令启动器；不裁其Python库API或Qt原生运行工具。"""
    rules = profile['developmentScripts'][component]
    omitted, decisions = set(), []
    for name, rule in rules.items():
        L.canonical_relative(name)
        if not name.startswith('bin/') or not name.endswith('.exe') or name.count('/') != 1:
            raise ValueError('开发命令越过bin启动器边界')
        if name not in logical:
            continue  # 已知投影种子可幂等复用，不补回已移除启动器。
        raw = bounded_read(view, prefix + '/' + name, 3 * 1024**2)
        checksum = digest(raw)
        if inspected.setdefault(name, checksum) != checksum:
            raise ValueError('开发命令输入在检查期间改变：' + name)
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                main = archive.getinfo('__main__.py')
                if main.file_size > 65536:
                    raise ValueError('开发命令入口超过预算')
                code = archive.read(main)
        except (zipfile.BadZipFile, KeyError) as exc:
            raise ValueError('不能识别已审查的pip开发命令：' + name) from exc
        if digest(code) != rule['mainSha256'] or rule['entry'] not in code.decode('utf-8').splitlines():
            raise ValueError('开发命令完整入口与审查摘要不符：' + name)
        omitted.add(name)
        decisions.append({'path': name, 'bytes': len(raw), 'sha256': checksum,
                          'mainSha256': rule['mainSha256'], 'entry': rule['entry']})
    return omitted, decisions


def project(source_root, destination, profile_path, wheel, receipt, component, modelscope_wheel=None, inheritance_profile=None):
    source_root, destination, profile_path, wheel, receipt = map(L.plain_path, (source_root, destination, profile_path, wheel, receipt))
    if destination.exists() or receipt.exists():
        raise FileExistsError('依赖投影只接受全新目录和外置回执')
    if destination.is_relative_to(source_root) or source_root.is_relative_to(destination):
        raise ValueError('依赖输入输出不得嵌套')
    if not destination.is_relative_to(ROOT / 'build') or not receipt.is_relative_to(ROOT / 'build/audit'):
        raise ValueError('输出限本项目build；审计限build/audit')
    if receipt.is_relative_to(destination):
        raise ValueError('完整审计不得放入运行依赖根')
    if component not in {'host', 'cuda'}:
        raise ValueError('这里只实现本体/CUDA；PaddleVL须在其授权项目中生成')
    profile = L.read_json(profile_path)
    if profile.get('format') != 'umi-dependency-subsets-v1' or profile.get('target') != 'Windows-x64-cp313':
        raise ValueError('依赖子集配置格式/目标不符')
    additions = read_wheel(wheel, profile['opencv'])
    prefix = 'site-packages' if component == 'host' else 'vendor'
    with L.load_layout(source_root, recover_externalized_inputs=True) as view:
        logical = {name[len(prefix) + 1:]: name for name in view.files(prefix)}
        if not logical or len(logical) > 100000:
            raise ValueError('依赖输入为空或超出数量预算')
        sizes = {relative: (view.entries[name.casefold()]['bytes'] if name.casefold() in view.entries else view.disk_files[name].stat().st_size)
                 for relative, name in logical.items()}
        if sum(sizes.values()) > 10 * 1024**3 or max(sizes.values()) > 1024**3:
            raise ValueError('依赖输入超出有限大小预算')
        inspected = {}
        cv = profile['opencv']
        opencv_dist, cv_input_version = find_distribution(
            view, logical, prefix, 'opencv-contrib-python', (cv['upstreamVersion'], cv['version']), inspected)
        if cv_input_version == cv['version']:
            actual = seed_payload(view, logical, prefix, ('cv2/', opencv_dist + '/'), inspected)
            if actual != additions:
                raise ValueError('派生OpenCV种子与独立锁wheel的完整载荷不符')
        omitted = {name for name in logical if name.startswith(('cv2/', opencv_dist + '/'))}
        image_dist = new_image_dist = image_input_version = None
        if component == 'host':
            image = profile['imagecodecs']
            keep = set(image['extensions'])
            if keep != {'_jpegxl', '_jpegxr', '_shared', '_shared_cython'}:
                raise ValueError('未验收的图像扩展集合')
            image_dist, image_input_version = find_distribution(
                view, logical, prefix, 'imagecodecs', (image['upstreamVersion'], image['version']), inspected)
            if image_input_version == image['version']:
                actual = seed_payload(view, logical, prefix, ('imagecodecs/', image_dist + '/'), inspected)
                binding = {name: {'bytes': len(data), 'sha256': digest(data)} for name, data in actual.items()}
                if digest(json_bytes(binding)) != image.get('derivedPayloadSha256'):
                    raise ValueError('派生imagecodecs种子与独立子集载荷摘要不符')
            new_image_dist = 'imagecodecs-' + image['version'] + '.dist-info'
            extensions = [name for name in logical if name.startswith('imagecodecs/') and name.endswith('.pyd')]
            found = [Path(name).name.split('.')[0] for name in extensions if Path(name).name.split('.')[0] in keep]
            if len(found) != len(keep) or set(found) != keep:
                raise ValueError('要求保留的图像扩展缺失或ABI不唯一')
            omitted.update(name for name in extensions if Path(name).name.split('.')[0] not in keep)
            omitted.update(name for name in logical if name.startswith(image_dist + '/'))
            for relative in logical:
                if not relative.startswith(image_dist + '/') or relative.endswith('/RECORD'):
                    continue
                suffix = relative[len(image_dist):]
                if suffix in {'/RECORD.jws', '/RECORD.p7s'}:
                    raise ValueError('不能把上游签名冒充派生载荷签名')
                data = bounded_read(view, prefix + '/' + relative, 3 * 1024**2)
                checksum = digest(data)
                if inspected.setdefault(relative, checksum) != checksum:
                    raise ValueError('派生输入在检查期间改变：' + relative)
                if suffix == '/METADATA':
                    original = ('Version: ' + image_input_version).encode('ascii')
                    # RST正文也含:Version:字段；只修改邮件头中的真实版本，不改原正文。
                    separator = b'\r\n\r\n' if b'\r\n\r\n' in data else b'\n\n'
                    header, delimiter, body = data.partition(separator)
                    lines = header.splitlines(keepends=True)
                    matches = [index for index, line in enumerate(lines) if line.rstrip(b'\r\n') == original]
                    if len(matches) != 1:
                        raise ValueError('imagecodecs原始版本字段格式不唯一')
                    index = matches[0]
                    lines[index] = lines[index].replace(original, ('Version: ' + image['version']).encode('ascii'), 1)
                    data = b''.join(lines) + delimiter + body
                additions[new_image_dist + suffix] = data
            additions[new_image_dist + '/UMI_RUNTIME_SUBSET.json'] = json_bytes({
                'format': 'umi-imagecodecs-subset-v1', 'upstreamVersion': image['upstreamVersion'],
                'version': image['version'], 'extensions': sorted(keep), 'scope': image['scope'],
                'sourceGuide': '原始wheel/源码锁和逐文件转换回执随组件在运行包外独立提供；不是官方完整wheel。'})
        excluded_distributions = []
        derived_modelscope = None
        native_wrappers = []
        if component == 'cuda':
            optional_files, excluded_distributions = cuda_exclusions(view, logical, prefix, profile, inspected, sizes)
            omitted.update(optional_files)
            if modelscope_wheel is not None:
                ms_spec = importlib.util.spec_from_file_location('projection_modelscope_download', Path(__file__).with_name('package_modelscope_download.py'))
                ms = importlib.util.module_from_spec(ms_spec)
                ms_spec.loader.exec_module(ms)
                ms_payload, ms_omitted, derived_modelscope = ms.project_replacement(
                    view, logical, prefix, profile['modelscope'], L.plain_path(modelscope_wheel), inspected, bounded_read)
                if set(additions) & set(ms_payload):
                    raise ValueError('ModelScope与其它派生构件冲突')
                additions.update(ms_payload)
                omitted.update(ms_omitted)
                native_spec = importlib.util.spec_from_file_location('projection_cuda_wrappers', Path(__file__).with_name('project_cuda_native_wrappers.py'))
                native = importlib.util.module_from_spec(native_spec)
                native_spec.loader.exec_module(native)
                native_payload, native_omitted, native_wrappers = native.projection(
                    view, logical, prefix, profile['cudaNativeWrappers'], inspected, bounded_read)
                if set(additions) & set(native_payload):
                    raise ValueError('CUDA包装器派生元数据与其它构件冲突')
                additions.update(native_payload)
                omitted.update(native_omitted)
        command_files, excluded_scripts = development_scripts(view, logical, prefix, profile, component, inspected)
        omitted.update(command_files)
        inherited_projection = None
        if inheritance_profile is not None:
            if component != 'cuda':
                raise ValueError('精确 GPU 继承锁不能用于本体')
            inherited_spec = importlib.util.spec_from_file_location('copy_time_inheritance', Path(__file__).with_name('project_inherited_runtime.py'))
            inherited = importlib.util.module_from_spec(inherited_spec)
            inherited_spec.loader.exec_module(inherited)
            inherited_omitted, inherited_projection = inherited.copy_time_omissions(
                view, logical, prefix, L.plain_path(inheritance_profile), inspected, sizes)
            omitted.update(inherited_omitted)
        selected = set(logical) - omitted
        if {name.casefold() for name in selected} & {name.casefold() for name in additions}:
            raise ValueError('派生构件与保留依赖文件冲突')
        expected_names = selected | set(additions)
        for name in expected_names:
            L.canonical_relative(name)
        if len({name.casefold() for name in expected_names}) != len(expected_names):
            raise ValueError('派生载荷存在大小写别名')
        destination.mkdir(parents=True)
        input_binding, output_binding = {}, {}
        for relative, logical_name in sorted(logical.items()):
            target = destination / relative
            if logical_name in view.disk_files:
                source = view.disk_files[logical_name]
                checksum = L.sha256_file(source)
                if relative in selected:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    if L.sha256_file(target) != checksum or L.sha256_file(source) != checksum:
                        raise ValueError('松散输入在复制期间改变：' + relative)
            else:
                data = view.read_bytes(logical_name)
                checksum = digest(data)
                if relative in selected:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open('xb') as stream:
                        stream.write(data)
                    if L.sha256_file(target) != checksum:
                        raise ValueError('容器成员恢复字节不符：' + relative)
            if relative in inspected and checksum != inspected[relative]:
                raise ValueError('已检查/派生的输入在复制期间改变：' + relative)
            input_binding[relative] = {'bytes': sizes[relative], 'sha256': checksum}
            if relative in selected:
                output_binding[relative] = input_binding[relative]
        for relative, data in sorted(additions.items()):
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(data)
            output_binding[relative] = {'bytes': len(data), 'sha256': digest(data)}
        if image_dist:
            record_name = new_image_dist + '/RECORD'
            rows = io.StringIO(newline='')
            writer = csv.writer(rows, lineterminator='\n')
            for name, value in sorted(output_binding.items()):
                if name.startswith(('imagecodecs/', new_image_dist + '/')):
                    writer.writerow([name, 'sha256=' + base64.urlsafe_b64encode(bytes.fromhex(value['sha256'])).rstrip(b'=').decode('ascii'), value['bytes']])
            writer.writerow([record_name, '', ''])
            data = rows.getvalue().encode('utf-8')
            with (destination / record_name).open('xb') as stream:
                stream.write(data)
            output_binding[record_name] = {'bytes': len(data), 'sha256': digest(data)}
        # 不允许在新目录留下丢失的瓶子/six等Stored-ZIP依赖或不在清单中的额外文件。
        actual = L.tree_files(destination)
        if set(actual) != set(output_binding):
            raise ValueError('投影载荷与最终成员清单不符')
        for relative, path in actual.items():
            if L.sha256_file(path) != output_binding[relative]['sha256']:
                raise ValueError('最终载荷校验失败：' + relative)
        result = {'status': 'PROJECTED_NOT_COMPONENT_ACCEPTED', 'createdUtc': datetime.now(timezone.utc).isoformat(),
                  'component': component, 'source': str(source_root), 'destination': str(destination),
                  'producerSha256': L.sha256_file(Path(__file__)), 'profileSha256': L.sha256_file(profile_path),
                  'opencvWheelSha256': profile['opencv']['sha256'], 'sourceLayout': view.summary(),
                  'inputVersions': {'opencv-contrib-python': cv_input_version, 'imagecodecs': image_input_version},
                  'derivedSeedVerification': '已知派生OpenCV逐成员匹配独立wheel；派生imagecodecs完整成员/字节摘要匹配独立子集锁。未知版本或仅改版本字段不接纳。',
                  'recoveredInputInventory': getattr(view, 'recovered_input_inventory', None),
                  'inputFiles': input_binding, 'outputFiles': output_binding, 'omittedFiles': sorted(omitted),
                  'excludedDistributions': excluded_distributions, 'excludedDevelopmentScripts': excluded_scripts,
                  'derivedModelScope': derived_modelscope, 'derivedCudaWrappers': native_wrappers,
                  'inheritedProjectionAtCopy': inherited_projection,
                  'inputBytes': sum(sizes.values()), 'outputBytes': sum(row['bytes'] for row in output_binding.values()),
                  'sourceModified': False, 'fixedInstallationChanged': False,
                  'boundary': '转换回执不单独证明上游来源；原始输入锁/归档绑定和组件定向验收必须另行保留。插件不依赖宿主私有numpy/Paddle。'}
    with receipt.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--profile', type=Path, default=ROOT / 'build/runtime-subsets-windows.json')
    parser.add_argument('--opencv-wheel', type=Path, required=True)
    parser.add_argument('--modelscope-wheel', type=Path)
    parser.add_argument('--inheritance-profile', type=Path)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--component', choices=['host', 'cuda'], required=True)
    args = parser.parse_args()
    if args.component == 'cuda' and args.modelscope_wheel is None:
        parser.error('CUDA正式投影必须提供独立锁定的--modelscope-wheel')
    result = project(args.source_root, args.destination, args.profile, args.opencv_wheel, args.receipt, args.component, args.modelscope_wheel, args.inheritance_profile)
    print(json.dumps({key: value for key, value in result.items() if key not in {'inputFiles', 'outputFiles', 'omittedFiles'}}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
