"""Verify and project an explicitly locked source-built Qt/PySide runtime.

Never overlays an existing dependency tree. The original dependency root, bundle,
and lock stay read-only. All four Qt binding distributions are replaced together,
with complete new RECORD inventories; unrelated dependencies are copied unchanged.
This transformation is not application acceptance or public-release authorization.
Run this entry point using Python -I.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
from email.parser import BytesParser
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import stat
import sys
import zipfile

_SPEC = importlib.util.spec_from_file_location('_qt_runtime_layout', Path(__file__).with_name('runtime_archive_layout.py'))
L = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(L)
Error = L.LayoutError
FORMAT = 'umi-derived-qt-bundle-v1'
PAYLOAD_FORMAT = 'umi-derived-qt-payload-v1'
MANIFEST = 'payload-manifest.json'
RUNTIME = 'qt-runtime-whitelist.json'
DERIVATION = 'qt-derivation.json'
PROFILE = 'UMI_RUNTIME_PROFILE.json'
PROFILE_FORMAT = 'umi-source-built-qt-runtime-v1'
PROFILE_REQUIRED_INPUTS = frozenset({'pyside', 'shiboken', 'webengine', 'source', 'notices', 'crt', 'qtWhitelist'})
DISTRIBUTIONS = frozenset({'pyside6', 'pyside6-essentials', 'pyside6-addons', 'shiboken6'})
PACKAGES = frozenset({'PySide6', 'shiboken6'})
MAX_MEMBER = 768 * 1024**2
MAX_TOTAL = 2 * 1024**3
MAX_FILES = 25000
JSON_LIMIT = 16 * 1024**2
SHA = re.compile(r'[0-9a-f]{64}\Z')


def normalized(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def parse_json(data):
    if len(data) > JSON_LIMIT:
        raise Error('JSON input exceeds budget')
    try:
        return json.loads(data.decode('utf-8-sig'), object_pairs_hook=L._json_object)
    except (UnicodeError, ValueError) as exc:
        raise Error('Invalid JSON input') from exc


def file_json(path):
    path = L.plain_path(path)
    if path.stat().st_size > JSON_LIMIT:
        raise Error('JSON input exceeds budget')
    return parse_json(path.read_bytes())


def require(condition, message):
    if not condition:
        raise Error(message)


def _hash_info(entry):
    require(isinstance(entry, dict) and type(entry.get('bytes')) is int and 0 <= entry['bytes'] <= MAX_MEMBER,
            'Invalid payload byte count')
    require(isinstance(entry.get('sha256'), str) and SHA.fullmatch(entry['sha256']), 'Invalid payload digest')


def _metadata(data):
    require(len(data) <= 1024**2, 'Distribution metadata exceeds budget')
    value = BytesParser().parsebytes(data)
    require(len(value.get_all('Name', [])) == 1 and len(value.get_all('Version', [])) == 1, 'Ambiguous distribution identity')
    return value


def _check_records(zf, files, version, derivation):
    site = {name.removeprefix('site-packages/'): info for name, info in files.items() if name.startswith('site-packages/')}
    infos = {name.split('/')[0] for name in site if name.split('/')[0].endswith('.dist-info')}
    require(len(infos) == 4, 'Derived Qt bundle must contain exactly four dist-info directories')
    found, owners = set(), {}
    expected_dependencies = {
        'pyside6': {'shiboken6', 'pyside6-essentials', 'pyside6-addons'},
        'pyside6-essentials': {'shiboken6'},
        'pyside6-addons': {'shiboken6', 'pyside6-essentials'},
        'shiboken6': set(),
    }
    for info in sorted(infos):
        meta_name = info + '/METADATA'
        record_name = info + '/RECORD'
        wheel_name = info + '/WHEEL'
        require({meta_name, record_name, wheel_name} <= site.keys(), 'Missing derived distribution metadata')
        metadata = _metadata(zf.read('site-packages/' + meta_name))
        dist = normalized(metadata['Name'])
        require(dist in DISTRIBUTIONS and dist not in found and metadata['Version'] == version,
                'Invalid, duplicate, or mismatched derived distribution identity')
        require(info == dist.replace('-', '_') + '-' + version + '.dist-info', 'Noncanonical dist-info directory')
        markers = [info + '/' + name for name in (PROFILE, 'UMI_RUNTIME_SUBSET.json') if info + '/' + name in site]
        require(markers == [info + '/' + PROFILE], 'Derived Qt distribution needs exactly one runtime profile marker')
        profile = parse_json(zf.read('site-packages/' + markers[0]))
        require(isinstance(profile, dict) and profile.get('format') == PROFILE_FORMAT
                and profile.get('distribution') == dist and profile.get('version') == version
                and profile.get('upstreamVersion') == version.split('+', 1)[0], 'Derived Qt runtime profile identity mismatch')
        require(profile.get('inputRecords') == derivation['inputRecords']
                and profile.get('sourceCommit') == derivation['pysideSourceCommit']
                and profile.get('sourceUrl') == 'https://code.qt.io/pyside/pyside-setup.git/tree/?id=' + derivation['pysideSourceCommit'],
                'Derived Qt runtime profile source/build bindings mismatch')
        dependencies = metadata.get_all('Requires-Dist', [])
        expected = {name + '==' + version for name in expected_dependencies[dist]}
        actual = {re.sub(r'[\s()]', '', value).replace('_', '-').lower() for value in dependencies}
        require(actual == expected and len(dependencies) == len(expected), 'Derived binding dependency versions are not exact')
        found.add(dist)
        wheel = zf.read('site-packages/' + wheel_name).decode('utf-8')
        require('Root-Is-Purelib: false' in wheel and 'Tag: cp310-abi3-win_amd64' in wheel, 'Unexpected derived wheel ABI tag')
        rows = csv.reader(io.StringIO(zf.read('site-packages/' + record_name).decode('utf-8'), newline=''))
        own_record = False
        for row in rows:
            require(len(row) == 3, 'Invalid derived RECORD row')
            name, digest, size = row
            L.canonical_relative(name)
            require(name in site and name not in owners, 'Missing, duplicate, or multiply owned RECORD member: ' + name)
            owners[name] = dist
            if name == record_name:
                require(not digest and not size, 'RECORD must have its canonical unhashed self row')
                own_record = True
            else:
                expected_digest = 'sha256=' + base64.urlsafe_b64encode(bytes.fromhex(site[name]['sha256'])).rstrip(b'=').decode('ascii')
                require(digest == expected_digest and size == str(site[name]['bytes']), 'Derived RECORD digest/size mismatch: ' + name)
        require(own_record, 'RECORD is missing its self row')
    require(found == DISTRIBUTIONS and owners.keys() == site.keys(), 'Qt bundle has undeclared distribution files')
    for name, owner in owners.items():
        top = name.split('/')[0]
        require(top in PACKAGES or top in infos, 'Qt bundle contains a non-Qt namespace: ' + name)
        if top == 'shiboken6':
            require(owner == 'shiboken6', 'Shiboken file owned by another distribution')
        elif top == 'PySide6':
            require(owner in {'pyside6-essentials', 'pyside6-addons'}, 'Invalid PySide file owner')
        else:
            require(top.startswith(owner.replace('-', '_') + '-'), 'Cross-owned dist-info member')
    return site


def _check_runtime(files, runtime, policy):
    require(runtime.get('qtVersion') == policy['qtVersion'] and runtime.get('quickStyle') == policy['quickStyle'], 'Qt runtime policy mismatch')
    for output_key, policy_key in (('pythonExtensions', 'pythonExtensions'), ('executables', 'executables'),
                                   ('webEngineResources', 'webEngineResources'), ('webEngineLocales', 'webEngineLocales'),
                                   ('plugins', 'pluginFiles')):
        require(sorted(runtime.get(output_key, [])) == sorted(policy[policy_key]), 'Qt runtime whitelist differs: ' + output_key)
    require(set(policy['requiredQmlModules']) <= set(runtime.get('qmlModules', [])), 'Required QML module omitted')
    names = {name.removeprefix('site-packages/') for name in files if name.startswith('site-packages/')}
    folded = {name.casefold() for name in names}
    actual_pyds = {name.split('/')[1] for name in names if name.startswith('PySide6/') and name.count('/') == 1 and name.endswith('.pyd')}
    require(actual_pyds == set(policy['pythonExtensions']), 'Actual PySide bindings do not match the whitelist')
    required = {'PySide6/' + name for name in policy['pythonExtensions'] + policy['executables']}
    required |= {'PySide6/resources/' + name for name in policy['webEngineResources']}
    required |= {'PySide6/translations/qtwebengine_locales/' + locale + '.pak' for locale in policy['webEngineLocales']}
    required |= {'PySide6/plugins/' + name for name in policy['pluginFiles']}
    required |= {'PySide6/qml/' + name + '/qmldir' for name in runtime['qmlModules']}
    required |= {'PySide6/' + name for name in runtime.get('rootDlls', [])}
    required |= {'PySide6/__init__.py', 'shiboken6/__init__.py', 'shiboken6/Shiboken.pyd', 'shiboken6/shiboken6.abi3.dll'}
    require({name.casefold() for name in required} <= folded, 'A declared Qt runtime file is absent')
    for name in names:
        parts = name.split('/')
        require(not name.endswith(('.pth', '.pyi', '.pyc', '.pyo', '.lib', '.pdb')) and '__pycache__' not in parts, 'Development/cache input in runtime bundle: ' + name)
        if name.lower().endswith('.exe'):
            require(name in {'PySide6/' + item for item in policy['executables']}, 'Unexpected runtime executable: ' + name)
        if parts[0] == 'PySide6' and len(parts) > 1:
            require(parts[1] not in policy['removeDirectories'], 'Excluded development directory in bundle')
        if name.startswith('PySide6/qml/'):
            rel = name.removeprefix('PySide6/qml/')
            require(not any(rel == prefix or rel.startswith(prefix + '/') for prefix in policy['excludedQmlPrefixes']), 'Excluded QML style in bundle')


@contextmanager
def verified_bundle(bundle, lock_path, whitelist_path):
    bundle, lock_path, whitelist_path = map(L.plain_path, (bundle, lock_path, whitelist_path))
    lock, policy = file_json(lock_path), file_json(whitelist_path)
    require(lock.get('format') == FORMAT and lock.get('qtVersion') == policy.get('qtVersion'), 'Unsupported bundle lock or Qt version')
    version = lock.get('derivedVersion', '')
    require(re.fullmatch(re.escape(policy['qtVersion']) + r'\+umi\.qttrim\.[1-9][0-9]*', version), 'A distinct Qt-derived version is required')
    require(lock.get('whitelistSha256') == L.sha256_file(whitelist_path), 'Qt whitelist input changed')
    _hash_info(lock.get('archive'))
    require(bundle.name == lock['archive'].get('name') and bundle.stat().st_size == lock['archive']['bytes'], 'Archive name/size mismatch')
    with bundle.open('rb') as raw:
        require(hashlib.file_digest(raw, 'sha256').hexdigest() == lock['archive']['sha256'], 'Archive SHA-256 mismatch')
        raw.seek(0)
        with zipfile.ZipFile(raw) as zf:
            infos = zf.infolist()
            require(0 < len(infos) <= MAX_FILES, 'Bundle file count exceeds budget')
            index, folded, total = {}, set(), 0
            for info in infos:
                name = L.canonical_relative(info.filename)
                mode = info.external_attr >> 16
                require(not info.is_dir() and (not stat.S_IFMT(mode) or stat.S_ISREG(mode)) and not info.flag_bits & 1,
                        'Directory, link, special or encrypted ZIP member')
                require(info.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}, 'Unsupported ZIP compression')
                require(name.casefold() not in folded and info.file_size <= MAX_MEMBER, 'Duplicate/colliding or oversized member')
                folded.add(name.casefold())
                require(name in {MANIFEST, RUNTIME, DERIVATION} or name.startswith('site-packages/'), 'Unexpected bundle namespace')
                if name in {MANIFEST, RUNTIME, DERIVATION} or '.dist-info/' in name:
                    require(info.file_size <= JSON_LIMIT, 'Bundle metadata exceeds budget')
                index[name] = info
                total += info.file_size
            require(total <= MAX_TOTAL and {MANIFEST, RUNTIME, DERIVATION} <= index.keys(), 'Incomplete or oversized bundle')
            require(index[MANIFEST].file_size <= JSON_LIMIT, 'Payload manifest exceeds budget')
            manifest_bytes = zf.read(MANIFEST)
            require(L.sha256_bytes(manifest_bytes) == lock.get('payloadManifestSha256'), 'Payload manifest changed')
            manifest = parse_json(manifest_bytes)
            require(manifest.get('format') == PAYLOAD_FORMAT and manifest.get('derivedVersion') == version, 'Payload format/version mismatch')
            files = manifest.get('files', {})
            require(isinstance(files, dict) and set(files) == set(index) - {MANIFEST}, 'Manifest and ZIP member sets differ')
            for name, entry in files.items():
                _hash_info(entry)
                require(index[name].file_size == entry['bytes'], 'ZIP and manifest sizes differ')
                with zf.open(name) as stream:
                    actual = hashlib.file_digest(stream, 'sha256').hexdigest()
                require(actual == entry['sha256'], 'Payload hash mismatch: ' + name)
            runtime = parse_json(zf.read(RUNTIME))
            derivation = parse_json(zf.read(DERIVATION))
            require(derivation.get('derivedVersion') == version and derivation.get('qtVersion') == policy['qtVersion'], 'Derived identity mismatch')
            require(derivation.get('inputRecords') == lock.get('inputRecords') and isinstance(lock.get('inputRecords'), dict)
                    and PROFILE_REQUIRED_INPUTS <= lock['inputRecords'].keys(), 'Missing bound build/source receipts')
            source_commit = derivation.get('pysideSourceCommit')
            require(isinstance(source_commit, str) and re.fullmatch(r'[0-9a-f]{40}', source_commit), 'Missing derived PySide source commit')
            for label, digest in lock['inputRecords'].items():
                require(isinstance(label, str) and isinstance(digest, str) and SHA.fullmatch(digest), 'Invalid source/build receipt binding')
            _check_records(zf, files, version, derivation)
            _check_runtime(files, runtime, policy)
            yield zf, lock, manifest, runtime


def inspect_bundle(bundle, lock, whitelist):
    with verified_bundle(bundle, lock, whitelist) as (_, pinned, manifest, runtime):
        return {'status': 'BUNDLE_INTEGRITY_VERIFIED_NOT_APP_ACCEPTED', 'archiveSha256': pinned['archive']['sha256'],
                'derivedVersion': pinned['derivedVersion'], 'payloadFiles': len(manifest['files']), 'runtime': runtime}


def _old_qt_tops(source_files):
    tops, distributions = set(PACKAGES), set()
    for name, path in source_files.items():
        if name.count('/') != 1 or not name.endswith('.dist-info/METADATA'):
            continue
        require(path.stat().st_size <= 1024**2, 'Source distribution metadata exceeds budget')
        metadata = _metadata(path.read_bytes())
        dist = normalized(metadata['Name'])
        if dist in DISTRIBUTIONS:
            require(dist not in distributions, 'Multiple existing Qt distribution versions')
            distributions.add(dist)
            tops.add(name.split('/')[0])
    require(distributions == DISTRIBUTIONS, 'Original dependency root must identify all four Qt distributions')
    for name, path in source_files.items():
        if name.count('/') != 1 or not name.endswith('.dist-info/RECORD') or name.split('/')[0] in tops:
            continue
        require(path.stat().st_size <= JSON_LIMIT, 'Source RECORD exceeds budget')
        for row in csv.reader(io.StringIO(path.read_text('utf-8'), newline='')):
            require(len(row) == 3, 'Malformed unrelated source RECORD')
            require(row[0].split('/')[0].casefold() not in {top.casefold() for top in tops}, 'Non-Qt distribution owns files being replaced')
    return tops


def project(source, destination, bundle, lock, whitelist, manifest_output, receipt):
    source, destination, manifest_output, receipt = map(L.plain_path, (source, destination, manifest_output, receipt))
    project_build = Path(__file__).resolve().parents[1]
    for path in (destination, manifest_output, receipt):
        require(path.is_relative_to(project_build) and path != project_build, 'Output must stay in this project build tree')
        require(not path.exists() and not path.is_relative_to(source) and not source.is_relative_to(path), 'Refuse existing/overlapping source and output paths')
        require(path.parent.is_dir(), 'Output parent must already exist')
    require(manifest_output != receipt and not manifest_output.is_relative_to(destination) and not receipt.is_relative_to(destination), 'Outputs overlap')
    report = {'status': 'RUNNING', 'startedUtc': datetime.now(timezone.utc).isoformat(), 'source': str(source), 'destination': str(destination),
              'bundle': str(L.plain_path(bundle)), 'lockSha256': L.sha256_file(L.plain_path(lock)),
              'producerSha256': L.sha256_file(Path(__file__)), 'runtimeAcceptance': 'NOT_RUN', 'publicReleaseAllowed': False}
    try:
        with verified_bundle(bundle, lock, whitelist) as (zf, pinned, payload, runtime):
            source_files = L.tree_files(source)
            require(len(source_files) <= 200000 and sum(p.stat().st_size for p in source_files.values()) <= 4 * 1024**3, 'Source dependency inventory exceeds budget')
            old_tops = _old_qt_tops(source_files)
            retained = {name: path for name, path in source_files.items() if name.split('/')[0] not in old_tops}
            new_files = {name.removeprefix('site-packages/'): entry for name, entry in payload['files'].items() if name.startswith('site-packages/')}
            require(not ({name.casefold() for name in retained} & {name.casefold() for name in new_files}), 'Derived payload collides with unrelated dependencies')
            destination.mkdir()
            old_hashes = {}
            for name, path in sorted(retained.items()):
                L.plain_path(path)
                checksum = L.sha256_file(path)
                target = L.plain_path(destination / name)
                target.parent.mkdir(parents=True, exist_ok=True)
                with path.open('rb') as input_stream, target.open('xb') as output_stream:
                    shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
                require(L.sha256_file(target) == checksum, 'Source file changed during projection')
                old_hashes[name] = checksum
            for name, entry in sorted(new_files.items()):
                target = L.plain_path(destination / name)
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open('site-packages/' + name) as input_stream, target.open('xb') as output_stream:
                    shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
                require(target.stat().st_size == entry['bytes'] and L.sha256_file(target) == entry['sha256'], 'Extracted derived file changed')
            require(set(L.tree_files(destination)) == set(retained) | set(new_files), 'Final dependency inventory mismatch')
            require(set(L.tree_files(source)) == set(source_files) and all(L.sha256_file(source_files[name]) == digest for name, digest in old_hashes.items()), 'Original dependency input changed while projecting')
            with manifest_output.open('xb') as output_stream:
                output_stream.write(zf.read(RUNTIME))
            report.update(status='PROJECTED_VERIFIED_NOT_APP_ACCEPTED', archiveSha256=pinned['archive']['sha256'],
                          derivedVersion=pinned['derivedVersion'], replacedDistributions=sorted(DISTRIBUTIONS),
                          omittedOriginalFiles=len(source_files) - len(retained), retainedFiles=len(retained), derivedFiles=len(new_files),
                          runtimeManifest=str(manifest_output), runtimeManifestSha256=L.sha256_file(manifest_output))
    except Exception as exc:
        report.update(status='FAILED', error=type(exc).__name__ + ': ' + str(exc))
        raise
    finally:
        report['finishedUtc'] = datetime.now(timezone.utc).isoformat()
        with receipt.open('x', encoding='utf-8') as output_stream:
            json.dump(report, output_stream, ensure_ascii=False, indent=2)
            output_stream.write('\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--lock', type=Path, required=True)
    parser.add_argument('--whitelist', type=Path, default=Path(__file__).resolve().parents[1] / 'qt-runtime-whitelist.json')
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--destination-root', type=Path)
    parser.add_argument('--manifest-output', type=Path)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    if not sys.flags.isolated:
        parser.error('Run using Python -I')
    if args.verify_only:
        require(not any((args.source_root, args.destination_root, args.manifest_output, args.receipt)), 'Verification does not accept projection outputs')
        result = inspect_bundle(args.bundle, args.lock, args.whitelist)
    else:
        if not all((args.source_root, args.destination_root, args.manifest_output, args.receipt)):
            parser.error('Projection requires source-root, destination-root, manifest-output, and receipt')
        result = project(args.source_root, args.destination_root, args.bundle, args.lock, args.whitelist, args.manifest_output, args.receipt)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
