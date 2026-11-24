"""只排除已审查的CUDA可选包装器；保留核心DLL、共享命名空间及原始许可。"""
from __future__ import annotations
import base64
import csv
from email.parser import BytesParser
import hashlib
import io
import json


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def projection(view, logical, prefix, rules, inspected, bounded_read):
    """只返回新增和移除清单；输入读取受预算约束，复制时由宿主再核摘要。"""
    if {r['path'] for r in rules} != {'nvidia/cublas/bin/nvblas64_12.dll', 'nvidia/cufft/bin/cufftw64_11.dll'} or len(rules) != 2:
        raise ValueError('CUDA包装器排除集合不符')
    additions, omitted, decisions = {}, set(), []
    def read(name):
        raw = bounded_read(view, prefix + '/' + name, 3 * 1024**2)
        checksum = digest(raw)
        if inspected.setdefault(name, checksum) != checksum:
            raise ValueError('CUDA包装器元数据检查期间变化')
        return raw
    for rule in rules:
        original_record = rule['originalRecord'].encode('utf-8')
        original_metadata = rule['originalMetadata'].encode('utf-8')
        if digest(original_record) != rule['recordSha256'] or digest(original_metadata) != rule['metadataSha256']:
            raise ValueError('CUDA包装器原始归属锁不符')
        old_dist = rule['dist']
        version = rule['version'] + '+umi.runtime.1'
        new_dist = old_dist.removesuffix('.dist-info') + '+umi.runtime.1.dist-info'
        package = rule['package'] + '/'
        if package not in {'nvidia/cublas/', 'nvidia/cufft/'} or rule['path'] != package + 'bin/' + rule['path'].split('/')[-1]:
            raise ValueError('CUDA包装器规则越过组件边界')
        old_present = old_dist + '/METADATA' in logical
        new_present = new_dist + '/METADATA' in logical
        if old_present == new_present:
            raise ValueError('CUDA包装器输入元数据缺失或重复')
        source_dist = old_dist if old_present else new_dist
        if any(n.startswith(old_dist.split('-')[0] + '-') and n.endswith('.dist-info/METADATA')
               and n not in {source_dist + '/METADATA'} for n in logical):
            raise ValueError('CUDA包装器出现未知发行版版本')
        rows = list(csv.reader(io.StringIO(original_record.decode('utf-8'))))
        if any(len(row) != 3 for row in rows) or len({r[0] for r in rows}) != len(rows):
            raise ValueError('CUDA原始RECORD格式错误')
        original_entries = {r[0]: (r[1], r[2]) for r in rows}
        changed_metadata = original_metadata.replace(('Version: ' + rule['version'] + '\n').encode(), ('Version: ' + version + '\n').encode(), 1)
        if changed_metadata == original_metadata:
            raise ValueError('CUDA版本字段未按预期修改')
        marker = json_bytes({'format': 'umi-cuda-wrapper-subset-v1', 'version': version,
                            'upstreamVersion': rule['version'], 'distribution': rule['distribution'],
                            'originalRecordSha256': rule['recordSha256'], 'excluded': [rule['path']],
                            'scope': '仅排除产品未用的可选兼容包装器；核心CUDA DLL、算法、精度和架构不变。原始许可保留，非完整官方wheel。'})
        source_metadata = read(source_dist + '/METADATA')
        expected_metadata = original_metadata if old_present else changed_metadata
        if source_metadata != expected_metadata:
            raise ValueError('CUDA包装器元数据与独立原始锁不符')
        metadata = BytesParser().parsebytes(source_metadata)
        if metadata['Name'] != rule['distribution'] or metadata['Version'] != (rule['version'] if old_present else version):
            raise ValueError('CUDA包装器发行版身份不符')
        # 共享命名空间仅在该发行版原始 RECORD 声明拥有时进入其派生 RECORD。
        # 新版 PEP 639 wheel 可能不拥有它；文件仍由总投影原样保留，不冒认归属。
        members = {n for n in logical if n.startswith((package, source_dist + '/'))
                   or n == 'nvidia/__init__.py' and n in original_entries}
        license_paths = {source_dist + '/License.txt', source_dist + '/licenses/License.txt'}
        if not set(rule['requiredFiles']) <= members or not license_paths.intersection(members):
            raise ValueError('CUDA核心DLL或许可缺失')
        if old_present and rule['path'] not in members:
            raise ValueError('CUDA包装器缺失但仍宣称完整原版身份')
        if not old_present and rule['path'] in members:
            raise ValueError('CUDA派生种子残留排除包装器')
        output_rows = []
        new_data = {new_dist + '/METADATA': changed_metadata, new_dist + '/UMI_RUNTIME_SUBSET.json': marker}
        for name in sorted(members):
            old_name = old_dist + name[len(source_dist):] if name.startswith(source_dist + '/') else name
            if name == source_dist + '/UMI_RUNTIME_SUBSET.json':
                if old_present or read(name) != marker:
                    raise ValueError('CUDA派生标识不符')
                continue
            if old_name not in original_entries:
                raise ValueError('CUDA发行版出现未知成员：' + name)
            checksum, size = original_entries[old_name]
            if name == source_dist + '/RECORD':
                continue
            if name == rule['path']:
                data = read(name)
                if len(data) != rule['bytes'] or digest(data) != rule['sha256']:
                    raise ValueError('CUDA可选包装器字节不符')
                omitted.add(name)
                continue
            target = new_dist + name[len(source_dist):] if name.startswith(source_dist + '/') else name
            if name.startswith(source_dist + '/'):
                data = read(name)
                if name != source_dist + '/METADATA':
                    new_data[target] = data
            else:
                data = None
            if name != source_dist + '/METADATA':
                if not checksum.startswith('sha256=') or not size.isdecimal():
                    raise ValueError('CUDA原始成员摘要/大小缺失')
                expected = base64.urlsafe_b64decode(checksum[7:] + '=' * (-len(checksum[7:]) % 4)).hex()
                if len(expected) != 64 or (data is not None and (digest(data) != expected or len(data) != int(size))):
                    raise ValueError('CUDA保留成员不符合原始RECORD')
                if inspected.setdefault(name, expected) != expected:
                    raise ValueError('CUDA保留成员存在冲突摘要')
                if data is None:
                    output_rows.append([target, checksum, size])
        for name, data in sorted(new_data.items()):
            checksum = 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode('ascii')
            output_rows.append([name, checksum, str(len(data))])
        output_rows.sort(key=lambda row: row[0])
        output_rows.append([new_dist + '/RECORD', '', ''])
        stream = io.StringIO(newline='')
        csv.writer(stream, lineterminator='\n').writerows(output_rows)
        new_data[new_dist + '/RECORD'] = stream.getvalue().encode('utf-8')
        source_record = read(source_dist + '/RECORD')
        if source_record != (original_record if old_present else new_data[new_dist + '/RECORD']):
            raise ValueError('CUDA原始或派生RECORD不符')
        if not old_present and source_dist + '/UMI_RUNTIME_SUBSET.json' not in members:
            raise ValueError('CUDA派生种子缺少身份标识')
        omitted.update(n for n in members if n.startswith(source_dist + '/'))
        if set(additions) & set(new_data):
            raise ValueError('CUDA派生元数据冲突')
        additions.update(new_data)
        decisions.append({'distribution': rule['distribution'], 'inputVersion': metadata['Version'],
                          'version': version, 'excluded': rule['path'], 'excludedBytes': rule['bytes'] if old_present else 0,
                          'status': 'PROJECTED_NOT_CONSUMER_ACCEPTED'})
    # 替换元数据和删除包装器均不得夺走其它发行版拥有的成员。
    budget = 0
    keys = {n.casefold() for n in omitted}
    for name in logical:
        if name.count('/') != 1 or not name.endswith('.dist-info/RECORD') or name in omitted:
            continue
        data = read(name)
        budget += len(data)
        if budget > 64 * 1024**2:
            raise ValueError('CUDA共享归属记录超过预算')
        rows = list(csv.reader(io.StringIO(data.decode('utf-8'))))
        if any(len(row) != 3 for row in rows) or any(row[0].casefold() in keys for row in rows):
            raise ValueError('CUDA排除成员存在共享归属或记录格式不符')
    return additions, omitted, decisions
