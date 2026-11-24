"""Locked official-wheel Qt projection and fail-closed trim reuse (stdlib only).

Run with Python -I. Extraction never installs wheels or edits their RECORDs.
Large member inventories live in external, exclusive-created audit records, not
in the runtime manifest. This is provenance verification, not native acceptance.
"""
from __future__ import annotations

import argparse
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import zipfile

SCHEMA = 'umi-official-qt-projection-v1'
DISTS = ('pyside6', 'pyside6-addons', 'pyside6-essentials', 'shiboken6')
PACKAGES = ('PySide6', 'shiboken6')
MAX_MEMBER = 1024**3
MAX_TOTAL = 4 * 1024**3
MAX_FILES = 100000
SHA = re.compile(r'[0-9a-f]{64}\Z')


class ProjectionError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise ProjectionError(message)


def normalized(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def plain(path):
    supplied = Path(path)
    require(not supplied.drive or supplied.is_absolute(), 'Drive-relative paths are forbidden')
    path = Path(os.path.abspath(path))
    require(not str(path).startswith(('\\\\', '//')), 'Network/device paths are forbidden')
    for node in (*reversed(path.parents), path):
        if node.exists() or node.is_symlink():
            attr = node.lstat()
            require(not stat.S_ISLNK(attr.st_mode) and not getattr(attr, 'st_file_attributes', 0) & 0x400,
                    'Links/junctions are forbidden: ' + str(node))
            require(not stat.S_ISREG(attr.st_mode) or attr.st_nlink == 1, 'Hardlinks are forbidden: ' + str(node))
    return path


def relative(name):
    require(isinstance(name, str) and name and '\\' not in name and ':' not in name and not name.startswith('/'),
            'Unsafe member path: ' + repr(name))
    parts = name.split('/')
    require(all(p and p not in ('.', '..') and p.rstrip(' .') == p and not any(ord(c) < 32 for c in p)
                and not re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', p) for p in parts),
            'Unsafe member path: ' + repr(name))
    return name


def digest(path):
    with plain(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')


def stable(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def json_file(path):
    path = plain(path)
    require(path.stat().st_size <= 64 * 1024**2, 'JSON exceeds budget')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(path.read_text('utf-8-sig'), object_pairs_hook=unique)


def write_new(path, value):
    path = plain(path)
    require(not path.exists(), 'Refusing to overwrite audit/output: ' + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(encoded(value))


def locked(lock):
    text = plain(lock).read_text('utf-8').replace('\\\n', ' ')
    found = {}
    for line in text.splitlines():
        match = re.fullmatch(r'\s*([A-Za-z0-9_.-]+)==([^\s]+)\s+--hash=sha256:([0-9a-f]{64})\s*', line)
        if match and normalized(match[1]) in DISTS:
            dist = normalized(match[1])
            require(dist not in found, 'Duplicate Qt lock entry')
            found[dist] = {'version': match[2], 'sha256': match[3]}
    require(set(found) == set(DISTS), 'Lock must pin all four official Qt distributions with one SHA-256 each')
    return found


def roots(pins):
    return set(PACKAGES) | {d.replace('-', '_') + '-' + pins[d]['version'] + '.dist-info' for d in DISTS}


def tree(root, *, ignore_cache=False):
    root = plain(root)
    require(root.is_dir(), 'Missing tree: ' + str(root))
    result, folded = {}, set()
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            node = plain(Path(base) / name)
            rel = relative(node.relative_to(root).as_posix())
            require(rel.casefold() not in folded, 'Case-colliding tree paths: ' + rel)
            folded.add(rel.casefold())
            if node.is_file() and not (ignore_cache and node.suffix.lower() == '.pyc'):
                result[rel] = {'sha256': digest(node), 'bytes': node.stat().st_size}
    return dict(sorted(result.items()))


def runtime_tree(site, pins):
    site = plain(site)
    allowed = roots(pins)
    actual = set()
    for node in site.iterdir():
        n = normalized(node.name)
        if node.name in PACKAGES or any(n.startswith(d + '-') and n.endswith('-dist-info') for d in DISTS):
            require(node.name in allowed and node.is_dir(), 'Unexpected Qt distribution root: ' + node.name)
            actual.add(node.name)
    require(actual == allowed, 'Missing one of the six Qt package/metadata roots')
    result = {}
    for name in sorted(allowed):
        for rel, entry in tree(site / name, ignore_cache=True).items():
            result[name + '/' + rel] = entry
    return dict(sorted(result.items()))


def inputs(policy, qml, lock, trim_script):
    config = json_file(policy)
    pins = locked(lock)
    require(all(p['version'] == config['qtVersion'] for p in pins.values()), 'Policy and official Qt lock version mismatch')
    return config, pins, {'policySha256': digest(policy), 'qmlSha256': stable(tree(qml)),
                         'lockSha256': digest(lock), 'trimScriptSha256': digest(trim_script),
                         'projectionToolSha256': digest(__file__)}


def extract(wheelhouse, destination, lock, receipt):
    wheelhouse, destination, receipt = map(plain, (wheelhouse, destination, receipt))
    require(not destination.exists() and not receipt.exists(), 'Extraction directory/audit must be new')
    pins = locked(lock)
    selected = {}
    for path in wheelhouse.iterdir():
        if path.suffix.lower() != '.whl':
            continue
        dist = normalized(path.name.split('-')[0])
        if dist in DISTS:
            require(dist not in selected, 'Duplicate wheel for ' + dist)
            selected[dist] = plain(path)
    require(set(selected) == set(DISTS), 'Official wheelhouse needs all four Qt wheels')
    members, directories, identities, file_keys, spellings = {}, set(), [], set(), {}
    # Validate every archive before creating the destination. Streaming keeps large
    # official DLLs out of memory; exact member bytes are hashed again on output.
    for dist in DISTS:
        path = selected[dist]
        pin = pins[dist]
        require(digest(path) == pin['sha256'], 'Official wheel SHA-256 mismatch: ' + path.name)
        parts = path.name[:-4].split('-')
        require(len(parts) in (5, 6) and parts[1] == pin['version'] and parts[-1] == 'win_amd64', 'Wheel version/platform mismatch')
        info_root = dist.replace('-', '_') + '-' + pin['version'] + '.dist-info'
        own, local, total = {}, set(), 0
        with zipfile.ZipFile(path) as archive:
            require(len(archive.infolist()) <= MAX_FILES, 'Wheel member count exceeds budget')
            for item in archive.infolist():
                require(item.orig_filename == item.filename, 'Truncated/noncanonical wheel member')
                name = relative(item.filename[:-1] if item.is_dir() else item.filename)
                key = name.casefold()
                require(key not in local, 'Duplicate wheel member: ' + name)
                local.add(key)
                path_parts = name.split('/')
                for i in range(1, len(path_parts) + 1):
                    prefix = '/'.join(path_parts[:i])
                    require(spellings.setdefault(prefix.casefold(), prefix) == prefix,
                            'Case-colliding wheel directory/member: ' + prefix)
                mode = item.external_attr >> 16
                require(not stat.S_ISLNK(mode) and stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR), 'Wheel link/special member')
                require(not item.flag_bits & 1, 'Encrypted wheel member')
                top = name.split('/')[0]
                packages = {'shiboken6'} if dist == 'shiboken6' else {'PySide6'}
                require(top in packages | {info_root}, 'Wheel member outside Qt namespace: ' + name)
                if item.is_dir():
                    require(key not in file_keys, 'File/directory collision')
                    directories.add(key)
                    continue
                require(key not in directories and (key not in file_keys or name in members),
                        'Duplicate/colliding wheel member: ' + name)
                require(0 <= item.file_size <= MAX_MEMBER, 'Wheel member exceeds budget')
                total += item.file_size
                require(total <= MAX_TOTAL, 'Wheel expands beyond budget')
                with archive.open(item) as stream:
                    sha = hashlib.file_digest(stream, 'sha256').hexdigest()
                if name in members:
                    shared = members[name]
                    require(shared['sha256'] == sha and shared['bytes'] == item.file_size,
                            'Duplicate/colliding wheel member has different content: ' + name)
                    shared['distributions'].append(dist)
                    own[name] = shared
                else:
                    own[name] = {'sha256': sha, 'bytes': item.file_size, 'distribution': dist, 'distributions': [dist]}
                file_keys.add(key)
            for needed in ('METADATA', 'WHEEL', 'RECORD'):
                require(info_root + '/' + needed in own, 'Wheel metadata missing: ' + needed)
            meta = BytesParser().parsebytes(archive.read(info_root + '/METADATA'))
            require(len(meta.get_all('Name', [])) == len(meta.get_all('Version', [])) == 1
                    and normalized(meta['Name']) == dist and meta['Version'] == pin['version'], 'Wheel METADATA identity mismatch')
        members.update(own)
        identities.append({'distribution': dist, 'version': pin['version'], 'filename': path.name,
                           'sha256': pin['sha256'], 'bytes': path.stat().st_size})
    for name in members:
        parts = name.split('/')
        require(not any('/'.join(parts[:i]).casefold() in file_keys for i in range(1, len(parts))), 'Wheel file/parent collision')
    destination.mkdir(parents=True)
    for dist in DISTS:
        with zipfile.ZipFile(selected[dist]) as archive:
            for name, entry in members.items():
                if entry['distribution'] != dist:
                    continue
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
                require(digest(target) == entry['sha256'], 'Extracted member changed')
    write_new(receipt, {'schema': SCHEMA, 'phase': 'extracted', 'lockSha256': digest(lock),
                        'wheels': identities, 'members': members, 'destination': str(destination),
                        'projectionToolSha256': digest(__file__)})
    return {'roots': sorted(roots(pins)), 'wheels': identities}


def check_manifest(runtime, policy, files):
    require(runtime.get('qtVersion') == policy['qtVersion'], 'Qt manifest version does not match policy')
    require(runtime.get('quickStyle') == policy['quickStyle'], 'Qt manifest quick style mismatch')
    for output, key in (('pythonExtensions', 'pythonExtensions'), ('executables', 'executables'),
                        ('plugins', 'pluginFiles'), ('webEngineResources', 'webEngineResources'), ('webEngineLocales', 'webEngineLocales')):
        require(sorted(runtime.get(output, [])) == sorted(policy[key]), 'Qt manifest policy mismatch: ' + key)
    modules = runtime.get('qmlModules', [])
    require(isinstance(modules, list) and len(modules) == len(set(modules)) and set(policy['requiredQmlModules']) <= set(modules), 'Missing required QML module')
    for name in modules + runtime.get('rootDlls', []):
        relative(name)
    require(not any(m == p or m.startswith(p + '/') for m in modules for p in policy['excludedQmlPrefixes']), 'Excluded QML module')
    required = {'PySide6/' + n for n in policy['pythonExtensions'] + policy['executables'] + runtime.get('rootDlls', [])}
    required |= {'PySide6/plugins/' + n for n in policy['pluginFiles']}
    required |= {'PySide6/resources/' + n for n in policy['webEngineResources']}
    required |= {'PySide6/translations/qtwebengine_locales/' + n + '.pak' for n in policy['webEngineLocales']}
    required |= {'PySide6/qml/' + n + '/qmldir' for n in modules}
    require({n.casefold() for n in required} <= {n.casefold() for n in files}, 'Declared required Qt runtime member is missing')
    def direct(prefix, suffix):
        return {n[len(prefix):] for n in files if n.startswith(prefix) and '/' not in n[len(prefix):] and n.lower().endswith(suffix)}
    require(direct('PySide6/', '.pyd') == set(policy['pythonExtensions']), 'Actual Qt Python extension whitelist mismatch')
    require(direct('PySide6/', '.exe') == set(policy['executables']), 'Actual Qt executable whitelist mismatch')
    require({n.lower() for n in direct('PySide6/', '.dll')} == set(runtime.get('rootDlls', [])), 'Actual Qt DLL closure differs from manifest')
    require({n.removeprefix('PySide6/plugins/') for n in files if n.startswith('PySide6/plugins/')} == set(policy['pluginFiles']), 'Actual Qt plugins differ from policy')


def deletion_allowed(name, policy, runtime, original):
    if not name.startswith('PySide6/'):
        return False
    rel = name.removeprefix('PySide6/')
    parts = rel.split('/')
    if parts[0] in policy['removeDirectories']:
        return True
    if len(parts) == 1:
        low = rel.lower()
        return low.endswith(('.dll', '.pyi')) or (low.endswith('.pyd') and rel not in policy['pythonExtensions']) or (low.endswith('.exe') and rel not in policy['executables'])
    if parts[0] == 'plugins':
        return '/'.join(parts[1:]) not in policy['pluginFiles']
    if parts[0] == 'resources' and len(parts) == 2:
        return parts[1] not in policy['webEngineResources']
    if parts[0] == 'translations':
        if len(parts) == 2:
            return not any(parts[1] == stem + '_' + locale + '.qm' for stem in ('qt', 'qtbase', 'qtdeclarative', 'qtwebengine') for locale in policy['translationLocales'])
        return len(parts) == 3 and parts[1] == 'qtwebengine_locales' and Path(parts[2]).stem not in policy['webEngineLocales']
    if parts[0] == 'qml':
        qrel = '/'.join(parts[1:])
        if qrel.startswith('QtQuick/Dialogs/quickimpl/qml/') and qrel.split('/')[4].startswith('+'):
            return True
        # Same module-directory deletion boundary as Trim-Qt, not an extension
        # whitelist: arbitrary non-module QML files remain mandatory.
        for i in range(1, len(parts) - 1):
            module = '/'.join(parts[1:i + 1])
            if 'PySide6/qml/' + module + '/qmldir' in original and not any(m == module or m.startswith(module + '/') for m in runtime['qmlModules']):
                return True
    return False


def wheel_binding(wheels, pins):
    require(isinstance(wheels, list) and len(wheels) == 4, 'Missing official wheel identities')
    require({w.get('distribution') for w in wheels} == set(DISTS), 'Invalid official wheel identities')
    for w in wheels:
        pin = pins[w['distribution']]
        require(w.get('version') == pin['version'] and w.get('sha256') == pin['sha256'], 'Official wheel binding differs from lock')
        relative(w.get('filename'))


def audit_path(path):
    path = plain(path)
    audit_root = plain(Path(__file__).resolve().parents[2] / 'build/audit')
    require(path.is_relative_to(audit_root), 'Official Qt audit must stay in this project build/audit')
    return path


def seal(site, lock, policy, qml, trim_script, manifest, extraction_receipt, receipt):
    receipt = audit_path(receipt)
    require(not receipt.exists(), 'Refusing to overwrite audit/output')
    config, pins, bindings = inputs(policy, qml, lock, trim_script)
    source = json_file(extraction_receipt)
    require(source.get('schema') == SCHEMA and source.get('phase') == 'extracted'
            and source.get('lockSha256') == bindings['lockSha256']
            and source.get('projectionToolSha256') == bindings['projectionToolSha256'], 'Unbound official extraction receipt')
    wheel_binding(source.get('wheels'), pins)
    actual = runtime_tree(site, pins)
    original = source['members']
    runtime = json_file(manifest)
    require('officialQtProjection' not in runtime, 'Manifest already sealed')
    check_manifest(runtime, config, actual)
    require(actual.keys() <= original.keys(), 'Unknown Qt payload added after extraction')
    for name, entry in actual.items():
        require(entry == {k: original[name][k] for k in ('sha256', 'bytes')}, 'Official retained payload changed: ' + name)
    # 原 wheel 自带的字节码与运行时缓存统一排除出载荷指纹。
    # 排除不等于已删除；保留原始来源身份，不把仍在盘上的缓存记为删除。
    ignored_bytecode = {n: entry for n, entry in original.items() if Path(n).suffix.lower() == '.pyc'}
    removed = sorted(original.keys() - actual.keys() - ignored_bytecode.keys())
    for name in removed:
        require(deletion_allowed(name, config, runtime, original), 'Non-trimmable official member deleted: ' + name)
    scanner = original.get('PySide6/qmlimportscanner.exe')
    require(scanner is not None, 'Official scanner identity is missing')
    binding = dict(bindings, wheels=source['wheels'], scanner={k: scanner[k] for k in ('sha256', 'bytes', 'distribution')},
                   runtimeSha256=stable(actual), trimManifestSha256=stable(runtime))
    audit = {'schema': SCHEMA, 'phase': 'sealed', 'status': 'SEALED_VERIFIED_NOT_APP_ACCEPTED',
             'runtimeAcceptance': 'NOT_RUN', 'publicReleaseAllowed': False,
             'binding': binding, 'policy': config, 'qmlInputs': tree(qml),
             'retained': {n: original[n] for n in actual}, 'ignoredBytecode': ignored_bytecode,
             'deleted': {n: original[n] for n in removed}, 'inputReceiptSha256': digest(extraction_receipt)}
    write_new(receipt, audit)
    runtime['officialQtProjection'] = dict(binding, schema=SCHEMA, auditSha256=digest(receipt))
    # The original trim manifest is the sole intentional mutable output. Its
    # semantic pre-seal contents are bound; no wheel file or RECORD is rewritten.
    plain(manifest).write_bytes(encoded(runtime))
    return audit


def verify(site, lock, policy, qml, trim_script, manifest, source_receipt, receipt=None):
    if receipt:
        require(not plain(receipt).exists(), 'Refusing to overwrite audit/output')
    config, pins, expected = inputs(policy, qml, lock, trim_script)
    runtime = json_file(manifest)
    binding = runtime.get('officialQtProjection', {})
    require(binding.get('schema') == SCHEMA, 'Legacy/unbound Qt manifest; provide -OfficialQtWheelhouse for a fresh trim')
    for key, value in expected.items():
        require(binding.get(key) == value, 'Qt reuse binding changed: ' + key)
    wheel_binding(binding.get('wheels'), pins)
    scanner = binding.get('scanner', {})
    require(scanner.get('distribution') in DISTS and isinstance(scanner.get('sha256'), str) and SHA.fullmatch(scanner['sha256'])
            and type(scanner.get('bytes')) is int and scanner['bytes'] > 0, 'Missing scanner source binding')
    require(isinstance(binding.get('auditSha256'), str) and SHA.fullmatch(binding['auditSha256']), 'Missing external audit binding')
    original_audit = audit_path(source_receipt)
    require(original_audit.is_file(), 'Original sealed Qt audit is missing; provide -OfficialQtWheelhouse')
    require(digest(original_audit) == binding['auditSha256'], 'Original sealed Qt audit digest mismatch')
    sealed = json_file(original_audit)
    expected_binding = {k: v for k, v in binding.items() if k not in ('schema', 'auditSha256')}
    require(sealed.get('schema') == SCHEMA and sealed.get('phase') == 'sealed'
            and sealed.get('status') == 'SEALED_VERIFIED_NOT_APP_ACCEPTED'
            and sealed.get('binding') == expected_binding, 'Original sealed Qt audit binding mismatch')
    actual = runtime_tree(site, pins)
    check_manifest(runtime, config, actual)
    require(binding.get('runtimeSha256') == stable(actual), 'Actual Qt runtime payload changed')
    del runtime['officialQtProjection']
    require(binding.get('trimManifestSha256') == stable(runtime), 'Qt trim manifest changed')
    result = {'schema': SCHEMA, 'status': 'REUSE_VERIFIED_NOT_APP_ACCEPTED', 'binding': binding,
              'runtimeAcceptance': 'NOT_RUN', 'publicReleaseAllowed': False}
    if receipt:
        write_new(receipt, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('extract')
    for name in ('wheelhouse', 'destination', 'lock', 'receipt'):
        p.add_argument('--' + name, required=True)
    for command in ('seal', 'verify'):
        p = sub.add_parser(command)
        for name in ('site', 'lock', 'policy', 'qml', 'trim-script', 'manifest', 'receipt'):
            p.add_argument('--' + name, required=True)
        if command == 'seal':
            p.add_argument('--extraction-receipt', required=True)
        else:
            p.add_argument('--source-receipt', required=True)
    args = vars(parser.parse_args())
    command = args.pop('command')
    try:
        result = globals()[command](**{k.replace('-', '_'): v for k, v in args.items()})
        print(json.dumps({'status': result.get('status', 'EXTRACTED_VERIFIED'), 'schema': SCHEMA}))
    except (ProjectionError, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        parser.exit(1, 'Official Qt projection failed: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
