"""Package source-built Qt/PySide into a pinned, separately derived runtime bundle.

Reads completed source/build/notice receipts. Copies only the actual QML/plugin
and PE import closure into a fresh project directory; never changes the SDK,
source trees, dependency seed, fixed installation, or application version.
The resulting bundle is an integration input, not runtime/release acceptance.
"""
from __future__ import annotations

import argparse
import base64
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
import zipfile


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


TOOLS = Path(__file__).resolve().parent
Q = load('_umi_derived_qt_projection', TOOLS / 'project_derived_qt.py')
L = Q.L
PE = load('_umi_qt_pe_imports', TOOLS / 'verify_release_evidence.py')
BUILD = TOOLS.parent
VERSION = '6.11.2+umi.qttrim.1'
WHEEL_HASHES = {
    'essentials': 'c8a29def77032773a30879f7f24415b5395ad08592d147c170824ef4c735dfc1',
    'addons': 'f449ea4431da20e7b86752cca8d166f93434516fe417f981c27e5f8e1b554407',
}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8') + b'\n'


def write_json(path, value):
    with path.open('xb') as stream:
        stream.write(encoded(value))


def checked(path, digest):
    path = L.plain_path(path)
    Q.require(path.is_file() and L.sha256_file(path) == digest, 'Pinned input changed: ' + str(path))
    return path


def receipt(path, statuses):
    path = L.plain_path(path)
    value = Q.file_json(path)
    Q.require(value.get('status') in statuses, 'No successful input receipt: ' + str(path))
    return value


def receipt_inventory(value, key, digest_key, root):
    path = checked(value[key], value[digest_key])
    result = Q.file_json(path)
    for name, entry in result.items():
        L.canonical_relative(name)
        Q._hash_info(entry)
    Q.require(0 < len(result) <= 100000, 'Unexpected input inventory size')
    return result


def qml_modules(policy, scan, sdk_files):
    available = {name.removeprefix('qml/').removesuffix('/qmldir') for name in sdk_files if name.startswith('qml/') and name.endswith('/qmldir')}
    allowed = set(policy['requiredQmlModules'])
    for item in scan:
        name = item.get('relativePath')
        if not name:
            continue
        name = L.canonical_relative(name.replace('\\', '/').strip('/'))
        if any(name == prefix or name.startswith(prefix + '/') for prefix in policy['excludedQmlPrefixes']):
            continue
        if name in available:
            allowed.add(name)
    Q.require(allowed <= available, 'Required QML module is absent from the rebuilt SDK: ' + ', '.join(sorted(allowed - available)))
    return allowed, available


def qml_member_selected(name, allowed, available):
    if not name.startswith('qml/'):
        return False
    relative = name.removeprefix('qml/')
    parts = relative.split('/')
    if any(part.startswith('+') for part in parts) and relative.startswith('QtQuick/Dialogs/quickimpl/qml/'):
        return False
    if Path(name).suffix.lower() in {'.qmltypes', '.pdb', '.lib', '.prl', '.cmake', '.h', '.cpp'}:
        return False
    parents = ['/'.join(parts[:index]) for index in range(len(parts) - 1, 0, -1)]
    owner = next((parent for parent in parents if parent in available), None)
    return owner in allowed


def distribution_metadata(version, input_records, source_commit):
    Q.require(version == VERSION and re.fullmatch(r'[0-9a-f]{40}', source_commit), 'Derived metadata requires the pinned source identity')
    Q.require(isinstance(input_records, dict) and Q.PROFILE_REQUIRED_INPUTS <= input_records.keys()
              and all(isinstance(name, str) and isinstance(value, str) and Q.SHA.fullmatch(value)
                      for name, value in input_records.items()), 'Derived metadata requires complete source/build input bindings')
    dependencies = {
        'pyside6': ['shiboken6', 'pyside6-essentials', 'pyside6-addons'],
        'pyside6-essentials': ['shiboken6'],
        'pyside6-addons': ['shiboken6', 'pyside6-essentials'],
        'shiboken6': [],
    }
    result = {}
    for name in sorted(Q.DISTRIBUTIONS):
        top = name.replace('-', '_') + '-' + version + '.dist-info'
        text = ('Metadata-Version: 2.1\nName: ' + name + '\nVersion: ' + version
                + '\nSummary: Umi-OCR source-built Qt 6.11.2 runtime subset (not an upstream wheel)'
                + '\nRequires-Python: >=3.13.16,<3.14\nLicense: See retained original component notices'
                + '\nX-UMI-Upstream-Version: 6.11.2\nX-UMI-Derivation: source-built-qt-runtime-subset\n')
        text += ''.join('Requires-Dist: ' + dependency + '==' + version + '\n' for dependency in dependencies[name])
        result[top + '/METADATA'] = text.encode('utf-8')
        result[top + '/WHEEL'] = b'Wheel-Version: 1.0\nGenerator: Umi-OCR source-built Qt runtime bundler\nRoot-Is-Purelib: false\nTag: cp310-abi3-win_amd64\n'
        result[top + '/' + Q.PROFILE] = encoded({
            'format': Q.PROFILE_FORMAT, 'distribution': name, 'version': version, 'upstreamVersion': '6.11.2',
            'sourceCommit': source_commit, 'sourceUrl': 'https://code.qt.io/pyside/pyside-setup.git/tree/?id=' + source_commit,
            'inputRecords': dict(input_records),
            'scope': 'Source-built Qt/PySide runtime subset, not an upstream wheel. Native/application acceptance is recorded separately.',
            'sourceGuide': 'Complete corresponding source, patches and build/source receipts are separate delivery material, bound by these input-record hashes.'})
    return result


def owner(name):
    top = name.split('/')[0]
    if top.endswith('.dist-info'):
        return Q.normalized(top.split('-' + VERSION)[0])
    if top == 'shiboken6':
        return 'shiboken6'
    if name.startswith(('PySide6/resources/', 'PySide6/translations/qtwebengine', 'PySide6/qml/QtWebEngine/')) or Path(name).name.startswith(('QtWebEngine', 'Qt6WebEngine')):
        return 'pyside6-addons'
    return 'pyside6-essentials'


def runtime_notice_index(index):
    """Keep original legal material; leave GN/parser diagnostics in external audit."""
    entries = []
    for entry in index['entries']:
        public = {key: entry[key] for key in ('component', 'module', 'license', 'url', 'originalMetadata', 'originalTexts') if key in entry}
        headers = [{'source': item['origin']['source'], 'text': item['originalHeader']}
                   for item in entry.get('evidence', []) if 'originalHeader' in item]
        if headers:
            public['originalCopyrightHeaders'] = headers
        entries.append(public)
    return {'format': 'umi-qt-original-notices-runtime-v1', 'entries': entries,
            'scope': 'Unmodified upstream copyright/license material, including a conservative source-notice superset. This index does not change the original licenses.',
            'correspondingSource': 'Complete corresponding source and build/source audit records are separate delivery material.'}


def package(args):
    output = L.plain_path(args.output)
    Q.require(output.is_relative_to(BUILD) and not output.exists() and output.parent.is_dir(), 'Use a fresh output under the project build root')
    policy_path = L.plain_path(args.whitelist)
    policy = Q.file_json(policy_path)
    Q.require(policy['qtVersion'] == '6.11.2' and len(policy['pythonExtensions']) == 12, 'Re-review changed Qt baseline/whitelist')
    paths = {name: L.plain_path(getattr(args, name + '_record')) for name in ('pyside', 'shiboken', 'webengine', 'source', 'notices', 'crt')}
    for path in paths.values():
        Q.require(not path.is_relative_to(output), 'Input/output overlap')
    pyside = receipt(paths['pyside'], {'BINDINGS_COMPILED_NOT_RUNTIME_ACCEPTED'})
    shiboken = receipt(paths['shiboken'], {'BINDINGS_COMPILED_NOT_RUNTIME_ACCEPTED'})
    web = receipt(paths['webengine'], {'COMPILED_FROM_INTERRUPTED_CACHE_NOT_APP_ACCEPTED', 'COMPILED_NOT_APP_ACCEPTED'})
    source = receipt(paths['source'], {'SOURCE_INPUTS_VERIFIED_WITH_EXPLICIT_UPSTREAM_LINKS'})
    notices = receipt(paths['notices'], {'NOTICE_INPUTS_COLLECTED_WITH_EXPLICIT_MAPPINGS_REVIEW_REQUIRED', 'NOTICE_INPUTS_COLLECTED_REVIEW_REQUIRED'})
    crt = receipt(paths['crt'], {'OFFICIAL_TERMS_AND_RELEASE_CRT_BOUND_ENTITLEMENT_NOT_ASSERTED'})
    Q.require(pyside['component'] == 'PySide' and shiboken['component'] == 'Shiboken', 'Mismatched binding build phases')
    Q.require(pyside['derivedVersion'] == shiboken['derivedVersion'] == VERSION and not pyside['sourceChanged'] and not shiboken['sourceChanged'], 'Derived source/version changed')
    Q.require(pyside['sourceCommit'] == shiboken['sourceCommit'] == '24627cd36e1593adf22eb1f2950e4248e7bcc1ec', 'PySide source pin differs')
    Q.require(pyside['qtBuildRecordSha256'] == L.sha256_file(paths['webengine']) and pyside['shibokenRecord'] == str(paths['shiboken']), 'PySide was not built against these Qt/Shiboken inputs')
    Q.require(pyside['whitelistSha256'] == L.sha256_file(policy_path), 'Binding build used another whitelist')
    Q.require(not notices.get('errors') and notices['sourceRecordSha256'] == L.sha256_file(paths['source']), 'Notice source chain is incomplete')
    sdk = L.plain_path(pyside['qtSdkRoot'])
    Q.require(sdk == L.plain_path(web['installRoot']), 'Native Qt and binding SDK roots differ')
    sb_root, py_root = map(L.plain_path, (shiboken['installRoot'], pyside['installRoot']))
    sdk_files = receipt_inventory(pyside, 'qtSdkInputManifest', 'qtSdkInputManifestSha256', sdk)
    py_files = receipt_inventory(pyside, 'installedPayloadManifest', 'installedPayloadManifestSha256', py_root)
    sb_files = receipt_inventory(shiboken, 'installedPayloadManifest', 'installedPayloadManifestSha256', sb_root)
    for name, entry in web['outputs'].items():
        checked(sdk / name, entry['sha256'])
    output.mkdir()
    stage = output / 'payload'
    site = stage / 'site-packages'
    site.mkdir(parents=True)
    report = {'status': 'RUNNING', 'startedUtc': datetime.now(timezone.utc).isoformat(),
              'producerSha256': L.sha256_file(Path(__file__)), 'projectionToolSha256': L.sha256_file(TOOLS / 'project_derived_qt.py'),
              'derivedVersion': VERSION, 'qtVersion': '6.11.2', 'runtimeAcceptance': 'NOT_RUN', 'publicReleaseAllowed': False,
              'boundary': 'Fresh derived bundle of pinned source-built libraries, unchanged same-version translation data and original release CRT; not a clean Qt rebuild or application acceptance.'}
    origins, file_sources = {}, {}
    bound_records = {name: L.sha256_file(path) for name, path in paths.items()}
    bound_records['qtWhitelist'] = L.sha256_file(policy_path)

    def put_bytes(name, data, origin):
        L.canonical_relative(name)
        Q.require(name not in origins and len(data) <= Q.MAX_MEMBER, 'Duplicate or oversized output: ' + name)
        target = L.plain_path(site / name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(data)
        origins[name] = dict(origin, sha256=L.sha256_file(target), bytes=target.stat().st_size)

    def put_file(name, path, entry, origin_kind):
        L.canonical_relative(name)
        path = checked(path, entry['sha256'])
        Q.require(path.stat().st_size == entry['bytes'] and name not in origins, 'Input size or output collision: ' + name)
        target = L.plain_path(site / name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with path.open('rb') as input_stream, target.open('xb') as output_stream:
            shutil.copyfileobj(input_stream, output_stream, 1024 * 1024)
        Q.require(L.sha256_file(target) == entry['sha256'], 'Copied runtime member changed')
        origins[name] = {'kind': origin_kind, 'source': str(path), 'sha256': entry['sha256'], 'bytes': entry['bytes']}
        file_sources[name] = path

    try:
        for package_name, root, inventory in (('PySide6', py_root, py_files), ('shiboken6', sb_root, sb_files)):
            prefix = 'site-packages/' + package_name + '/'
            for name, entry in inventory.items():
                if not name.startswith(prefix):
                    continue
                rel = name.removeprefix('site-packages/')
                parts = rel.split('/')
                if len(parts) > 1 and (parts[1] in policy['removeDirectories'] or '__pycache__' in parts):
                    continue
                if Path(name).suffix.lower() in {'.pyi', '.pyc', '.pyo', '.pdb', '.lib'}:
                    continue
                put_file(rel, root / name, entry, 'source-built-python-binding')
        for name in ('pyside6.abi3.dll', 'pyside6qml.abi3.dll'):
            put_file('PySide6/' + name, py_root / 'bin' / name, py_files['bin/' + name], 'source-built-binding-library')
        put_file('shiboken6/shiboken6.abi3.dll', sb_root / 'bin/shiboken6.abi3.dll', sb_files['bin/shiboken6.abi3.dll'], 'source-built-binding-library')
        put_bytes('PySide6/qt.conf', b'[Paths]\nPrefix=.\nLibraryExecutables=.\n', {'kind': 'generated-runtime-relocation-config'})
        for name in policy['executables']:
            put_file('PySide6/' + name, sdk / 'bin' / name, sdk_files['bin/' + name], 'source-built-Qt-helper')
        for name in policy['pluginFiles']:
            put_file('PySide6/plugins/' + name, sdk / 'plugins' / name, sdk_files['plugins/' + name], 'source-built-Qt-plugin')
        for name in policy['webEngineResources']:
            put_file('PySide6/resources/' + name, sdk / 'resources' / name, sdk_files['resources/' + name], 'source-built-WebEngine-resource')
        for locale in policy['webEngineLocales']:
            name = 'translations/qtwebengine_locales/' + locale + '.pak'
            put_file('PySide6/' + name, sdk / name, sdk_files[name], 'source-built-WebEngine-locale')
        scanner = checked(sdk / 'bin/qmlimportscanner.exe', sdk_files['bin/qmlimportscanner.exe']['sha256'])
        qml_source = L.plain_path(args.qml_source)
        qml_inputs = {name: L.sha256_file(path) for name, path in L.tree_files(qml_source).items()}
        scan_command = [str(scanner), '-rootPath', str(qml_source), '-importPath', str(sdk / 'qml')]
        completed = subprocess.run(scan_command, cwd=str(output), capture_output=True, timeout=180, check=False)
        (output / 'qml-scan.stdout.json').write_bytes(completed.stdout)
        (output / 'qml-scan.stderr.txt').write_bytes(completed.stderr)
        Q.require(completed.returncode == 0 and len(completed.stdout) <= Q.JSON_LIMIT, 'Rebuilt QML scanner failed')
        scan = Q.parse_json(completed.stdout)
        Q.require(isinstance(scan, list) and len(scan) <= 2000, 'Invalid QML scanner result')
        allowed, available = qml_modules(policy, scan, sdk_files)
        for name, entry in sdk_files.items():
            if qml_member_selected(name, allowed, available):
                put_file('PySide6/' + name, sdk / name, entry, 'source-built-Qt-QML-closure')
        write_json(output / 'qml-source-inputs.json', qml_inputs)
        report['qmlScanner'] = {'path': str(scanner), 'sha256': sdk_files['bin/qmlimportscanner.exe']['sha256'],
                                'argv': scan_command, 'qmlSourceInputsSha256': L.sha256_file(output / 'qml-source-inputs.json')}
        locale_pattern = '|'.join(re.escape(name) for name in policy['translationLocales'])
        translation_pattern = re.compile(r'PySide6/translations/(?:qt|qtbase|qtdeclarative|qtwebengine)_(?:' + locale_pattern + r')\.qm\Z')
        reused_translations = []
        for kind in ('essentials', 'addons'):
            wheel = checked(getattr(args, kind + '_wheel'), WHEEL_HASHES[kind])
            bound_records['translation-' + kind + '-wheel'] = WHEEL_HASHES[kind]
            with zipfile.ZipFile(wheel) as archive:
                seen = set()
                for member in archive.infolist():
                    if not translation_pattern.fullmatch(member.filename):
                        continue
                    Q.require(member.filename not in seen and member.file_size <= 2 * 1024**2 and not member.is_dir(), 'Unexpected translation member')
                    seen.add(member.filename)
                    data = archive.read(member)
                    put_bytes(member.filename, data, {'kind': 'unchanged-6.11.2-translation-data', 'wheel': str(wheel), 'wheelSha256': WHEEL_HASHES[kind], 'member': member.filename})
                    reused_translations.append(member.filename)
        Q.require(reused_translations, 'No locked translation data selected')
        report['translationReuseBoundary'] = {'members': reused_translations, 'note': 'Same-version non-code .qm data copied from pinned upstream wheels, not described as rebuilt or official derived binding binaries.'}
        candidates = {}
        for name, entry in sdk_files.items():
            if name.startswith('bin/') and name.count('/') == 1 and name.lower().endswith('.dll'):
                candidates[Path(name).name.casefold()] = (sdk / name, entry, 'source-built-Qt-library')
        for entry in crt['crtFiles']:
            Q.require(entry['signatureStatus'] == 'Valid' and entry['version'] == '14.51.36247.0', 'Unverified CRT input')
            candidates[entry['name'].casefold()] = (Path(entry['path']), entry, 'original-Microsoft-release-CRT')
        installed_dlls = {Path(name).name.casefold(): name for name in origins if name.lower().endswith('.dll') and name.count('/') == 1}
        queue = [name for name in origins if Path(name).suffix.lower() in {'.pyd', '.dll', '.exe'}]
        visited, native_edges, external = set(), {}, {}
        python_root = L.plain_path(Path(pyside['python']).parent)
        system_root = L.plain_path(Path(os.environ['SystemRoot']) / 'System32')
        while queue:
            name = queue.pop()
            if name in visited:
                continue
            visited.add(name)
            data = (site / name).read_bytes()
            Q.require(len(data) <= Q.MAX_MEMBER and data[:2] == b'MZ', 'Invalid native runtime file')
            pe_offset = struct.unpack_from('<I', data, 0x3c)[0]
            Q.require(pe_offset + 6 <= len(data) and struct.unpack_from('<H', data, pe_offset + 4)[0] == 0x8664, 'A runtime binary is not Windows x64')
            imports = PE.pe_import_tables(data)
            native_edges[name] = imports
            for dependency in set(imports['normal_imports'] + imports['delay_imports']):
                dependency = dependency.casefold()
                L.canonical_relative(dependency)
                Q.require('/' not in dependency, 'Non-basename PE import')
                if dependency in installed_dlls:
                    queue.append(installed_dlls[dependency])
                elif dependency in candidates:
                    path, entry, kind = candidates[dependency]
                    destination = 'PySide6/' + path.name
                    put_file(destination, path, entry, kind)
                    installed_dlls[dependency] = destination
                    queue.append(destination)
                elif dependency in {'python3.dll', 'python313.dll'}:
                    path = L.plain_path(python_root / dependency)
                    Q.require(path.is_file(), 'Required host Python ABI library absent')
                    external[dependency] = {'kind': 'host-Python-runtime', 'path': str(path), 'sha256': L.sha256_file(path)}
                elif dependency.startswith(('api-ms-win-', 'ext-ms-win-')):
                    external[dependency] = {'kind': 'Windows-API-set-contract'}
                elif (system_root / dependency).is_file():
                    external[dependency] = {'kind': 'Windows-system-library', 'path': str(system_root / dependency)}
                else:
                    raise Q.Error('Unresolved normal/delay PE dependency: ' + name + ' -> ' + dependency)
        write_json(output / 'native-import-closure.json', {'imports': native_edges, 'externalPlatformDependencies': external})
        notice_root = L.plain_path(notices['noticesRoot'])
        checked(notice_root / 'NOTICE-INDEX.json', notices['noticesIndexSha256'])
        notice_inputs = checked(paths['notices'].parent / 'notice-source-inputs.json', notices['sourceInputsSha256'])
        for path, entry in Q.file_json(notice_inputs).items():
            checked(path, entry['sha256'])
        notice_files = L.tree_files(notice_root)
        notice_index = Q.file_json(notice_root / 'NOTICE-INDEX.json')
        def verify_notice_references(value):
            if isinstance(value, dict):
                if 'text' in value:
                    relative = L.canonical_relative(value['text'])
                    Q.require(relative in notice_files, 'An indexed original notice is absent')
                    checked(notice_files[relative], value['sha256'])
                for child in value.values():
                    verify_notice_references(child)
            elif isinstance(value, list):
                for child in value:
                    verify_notice_references(child)
        verify_notice_references(notice_index)
        for name, path in notice_files.items():
            digest = L.sha256_file(path)
            Q.require(name == 'NOTICE-INDEX.json' or (name.startswith('texts/') and Path(name).stem == digest), 'Notice object no longer matches its content address')
            if name == 'NOTICE-INDEX.json':
                put_bytes('PySide6/QtLicenseNotices/' + name, encoded(runtime_notice_index(notice_index)),
                          {'kind': 'runtime-legal-index-without-internal-audit', 'sourceIndexSha256': digest})
            else:
                put_file('PySide6/QtLicenseNotices/' + name, path, {'sha256': digest, 'bytes': path.stat().st_size}, 'original-Qt-third-party-notices')
        microsoft_sources = {}
        # Preserve the authoritative Word license (automatic numbering included),
        # plus its bounded reading view and the official redistribution-list text.
        for label, entry in {'community-original': crt['originals']['license-docx'],
                             'community-text-view': crt['plainTexts']['license-docx'],
                             'redistribution-list': crt['plainTexts']['redistribution']}.items():
            path = checked(entry['path'], entry['sha256'])
            suffix = '.docx' if label == 'community-original' else '.txt'
            name = 'PySide6/QtLicenseNotices/Microsoft/' + label + suffix
            put_file(name, path, entry, 'official-Microsoft-license-material')
            microsoft_sources[label] = {'member': name, 'sha256': entry['sha256']}
        put_bytes('PySide6/QtLicenseNotices/Microsoft/SOURCES.json', encoded({'sources': microsoft_sources,
                  'officialUrls': {key: value['url'] for key, value in crt['originals'].items()},
                  'eligibility': 'Not asserted; applicable license conditions and valid entitlement remain required.',
                  'textViewBoundary': crt.get('textViewBoundary', '')}), {'kind': 'license-source-reference'})
        identity = {'format': 'umi-derived-qt-identity-v1', 'qtVersion': '6.11.2', 'derivedVersion': VERSION,
                    'sourceCommit': pyside['sourceCommit'], 'bindingModules': policy['pythonExtensions'],
                    'description': 'Source-built runtime subset; not a repackaged official PySide wheel. Original licenses retained in QtLicenseNotices.',
                    'correspondingSource': 'Complete corresponding source, patches and build inputs are separate delivery material and must accompany any redistribution.'}
        put_bytes('PySide6/UMI_DERIVED_BUILD.json', encoded(identity), {'kind': 'derived-package-identity'})
        for name, data in distribution_metadata(VERSION, bound_records, pyside['sourceCommit']).items():
            put_bytes(name, data, {'kind': 'new-derived-distribution-metadata'})
        groups = {name: [] for name in Q.DISTRIBUTIONS}
        for name, entry in origins.items():
            digest = base64.urlsafe_b64encode(bytes.fromhex(entry['sha256'])).rstrip(b'=').decode('ascii')
            groups[owner(name)].append([name, 'sha256=' + digest, str(entry['bytes'])])
        for distribution, rows in groups.items():
            record_name = distribution.replace('-', '_') + '-' + VERSION + '.dist-info/RECORD'
            buffer = io.StringIO(newline='')
            writer = csv.writer(buffer, lineterminator='\n')
            writer.writerows(sorted(rows))
            writer.writerow([record_name, '', ''])
            put_bytes(record_name, buffer.getvalue().encode('utf-8'), {'kind': 'new-complete-derived-RECORD'})
        runtime = {'qtVersion': policy['qtVersion'], 'quickStyle': policy['quickStyle'], 'scanner': 'source-built SDK qmlimportscanner (build-only)',
                   'qmlModules': sorted(allowed), 'pythonExtensions': policy['pythonExtensions'], 'executables': policy['executables'],
                   'webEngineResources': policy['webEngineResources'], 'webEngineLocales': policy['webEngineLocales'], 'plugins': policy['pluginFiles'],
                   'rootDlls': sorted(Path(name).name for name in origins if name.startswith('PySide6/') and name.count('/') == 1 and name.lower().endswith('.dll')),
                   'derivedVersion': VERSION}
        write_json(stage / Q.RUNTIME, runtime)
        derivation = {'qtVersion': '6.11.2', 'derivedVersion': VERSION, 'pysideSourceCommit': pyside['sourceCommit'],
                      'inputRecords': bound_records, 'runtimeAcceptance': 'NOT_RUN',
                      'publicReleaseAllowed': False, 'nativeReuseBoundary': web.get('reuseBoundary', 'See native build receipt'),
                      'licenseBoundary': 'Original notices and explicit mappings retained; this is not legal clearance or publication approval.'}
        write_json(stage / Q.DERIVATION, derivation)
        files = {name: {'sha256': L.sha256_file(path), 'bytes': path.stat().st_size} for name, path in L.tree_files(stage).items()}
        write_json(stage / Q.MANIFEST, {'format': Q.PAYLOAD_FORMAT, 'derivedVersion': VERSION, 'files': files})
        write_json(output / 'origin-inventory.json', origins)
        for name, path in file_sources.items():
            checked(path, origins[name]['sha256'])
        Q.require({name: L.sha256_file(path) for name, path in L.tree_files(qml_source).items()} == qml_inputs, 'Application QML changed while packaging')
        archive = output / ('QtRuntime-' + VERSION + '-Windows_x64.zip')
        with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as target:
            for name, path in sorted(L.tree_files(stage).items()):
                item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                item.compress_type = zipfile.ZIP_DEFLATED
                item.external_attr = (stat.S_IFREG | 0o644) << 16
                with path.open('rb') as input_stream, target.open(item, 'w', force_zip64=True) as output_stream:
                    shutil.copyfileobj(input_stream, output_stream, 1024 * 1024)
        lock = output / 'derived-qt.lock.json'
        write_json(lock, {'format': Q.FORMAT, 'qtVersion': '6.11.2', 'derivedVersion': VERSION,
                          'archive': {'name': archive.name, 'sha256': L.sha256_file(archive), 'bytes': archive.stat().st_size},
                          'payloadManifestSha256': L.sha256_file(stage / Q.MANIFEST), 'whitelistSha256': L.sha256_file(policy_path), 'inputRecords': bound_records})
        inspection = Q.inspect_bundle(archive, lock, policy_path)
        report.update(status='DERIVED_QT_BUNDLE_VERIFIED_NOT_APP_ACCEPTED', bundle=str(archive), bundleSha256=L.sha256_file(archive),
                      bundleBytes=archive.stat().st_size, lock=str(lock), lockSha256=L.sha256_file(lock),
                      sitePackages=str(site), runtimeManifest=str(stage / Q.RUNTIME), payloadFiles=inspection['payloadFiles'],
                      origins=str(output / 'origin-inventory.json'), originsSha256=L.sha256_file(output / 'origin-inventory.json'),
                      nativeClosureSha256=L.sha256_file(output / 'native-import-closure.json'), inputRecords=bound_records)
    except Exception as exc:
        report.update(status='FAILED', error=type(exc).__name__ + ': ' + str(exc))
        raise
    finally:
        report['finishedUtc'] = datetime.now(timezone.utc).isoformat()
        write_json(output / 'result.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('pyside', 'shiboken', 'webengine', 'source', 'notices', 'crt'):
        parser.add_argument('--' + name + '-record', type=Path, required=True)
    parser.add_argument('--whitelist', type=Path, default=BUILD / 'qt-runtime-whitelist.json')
    parser.add_argument('--essentials-wheel', type=Path, required=True)
    parser.add_argument('--addons-wheel', type=Path, required=True)
    parser.add_argument('--qml-source', type=Path, default=BUILD.parent / 'UmiOCR-data/qt_res/qml')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not sys.flags.isolated:
        parser.error('Run using Python -I')
    print(json.dumps(package(args), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
