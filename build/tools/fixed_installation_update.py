"""Fail-closed Windows fixed-installation update with explicit old-payload retirement.

The caller supplies independently verified path/SHA256 mappings, not a directory
age heuristic. plan_update is read-only. update_files writes work/preview.json
before mutation, gates the launcher, and transacts replacement AND retirement.
Only owned program backups are deleted after commit. Work evidence is retained.

An ordinary exception rolls back while no process is using the installation.
A process/permission conflict during rollback leaves a gated, journalled recovery
scene instead of forcing writes. A hard interruption likewise requires explicit
journal reconciliation; this module does not claim power-loss atomicity.
"""
from __future__ import annotations

from contextlib import ExitStack
import ctypes as ct
from ctypes import wintypes as wt
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil

import runtime_archive_layout as layout

ENTRY = 'Umi-OCR.exe'
_STATE = frozenset({'.settings', '.pre_settings', '.plugins_state', 'themes.json',
                    'startup_error.log', 'logs', 'temp', 'temp_doc', '.download',
                    '.env', '.startup-benchmark.json', 'private', 'tasks', 'task_resources'})
_MODELS = frozenset({'model', 'models', 'model_cache'})
_WEIGHTS = frozenset({'.gguf', '.safetensors', '.onnx', '.pdparams', '.pdiparams',
                     '.pdmodel', '.pt', '.pth', '.engine', '.trt'})
_CODE = frozenset({'vendor', 'site-packages', 'py_src'})


def now():
    return datetime.now(timezone.utc).isoformat()


def preserved_reason(name):
    parts = tuple(part.casefold() for part in name.split('/'))
    if 'umi-ocr-uiunlock.dll' in parts:
        return 'PRIVATE_UI_UNLOCK'
    if any(part in _STATE for part in parts):
        return 'USER_STATE_OR_PRIVATE'
    if Path(name).suffix.casefold() in _WEIGHTS or parts[-1] in {'model.bin', 'pytorch_model.bin', 'consolidated.bin'}:
        return 'MODEL_WEIGHT'
    # Python packages also have models/ and config.json. These are program code
    # only inside an explicit code namespace, never plugin-root model storage.
    for index, part in enumerate(parts):
        if part in _MODELS and not _CODE.intersection(parts[:index]):
            return 'MODEL_STORAGE'
    if parts[-1] in {'settings.json', 'settings.ini', 'settings.toml', 'settings.yaml', 'settings.yml',
                     'config.json', 'config.ini', 'config.toml', 'config.yaml', 'config.yml'} and not _CODE.intersection(parts[:-1]):
        return 'USER_CONFIGURATION'
    return None


def _plain(path):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('Absolute local paths required')
    resolved = layout.plain_path(path)
    if str(resolved) != str(path):
        raise ValueError('Filesystem path alias/casing differs: ' + str(path))
    return path


def reject_aliases(*inventories):
    prefixes, leaves = {}, set()
    for inventory in inventories:
        for name in inventory:
            layout.canonical_relative(name)
            parts = name.split('/')
            for count in range(1, len(parts) + 1):
                prefix = '/'.join(parts[:count])
                old = prefixes.setdefault(prefix.casefold(), prefix)
                if old != prefix:
                    raise ValueError('Cross-inventory case alias: ' + old + ' / ' + prefix)
            leaves.add(name)
    for name in leaves:
        parts = name.split('/')
        if any('/'.join(parts[:count]) in leaves for count in range(1, len(parts))):
            raise ValueError('File/directory shape conflict: ' + name)


class UpdateBlocked(RuntimeError):
    """Transaction did not commit; inspect work/result.json before recovery."""


class _Basic(ct.Structure):
    _fields_ = [('CreationTime', ct.c_longlong), ('LastAccessTime', ct.c_longlong),
                ('LastWriteTime', ct.c_longlong), ('ChangeTime', ct.c_longlong),
                ('FileAttributes', wt.DWORD)]


class _Standard(ct.Structure):
    _fields_ = [('AllocationSize', ct.c_longlong), ('EndOfFile', ct.c_longlong),
                ('NumberOfLinks', wt.DWORD), ('DeletePending', ct.c_ubyte),
                ('Directory', ct.c_ubyte)]


class _Id(ct.Structure):
    _fields_ = [('VolumeSerialNumber', ct.c_ulonglong), ('Identifier', ct.c_ubyte * 16)]


class _Rename(ct.Structure):
    # FILE_RENAME_INFO's BOOLEAN/DWORD union occupies four bytes; HANDLE aligns.
    _fields_ = [('Flags', wt.DWORD), ('RootDirectory', wt.HANDLE),
                ('FileNameLength', wt.DWORD), ('FileName', wt.WCHAR * 1)]


class _Disposition(ct.Structure):
    _fields_ = [('DeleteFile', ct.c_ubyte)]


class _Windows:
    def __init__(self):
        if os.name != 'nt':
            raise OSError('Fixed-installation mutation requires Windows native handles')
        self.k = ct.WinDLL('kernel32', use_last_error=True)
        signatures = {
            'CreateFileW': ([wt.LPCWSTR, wt.DWORD, wt.DWORD, ct.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE], wt.HANDLE),
            'CloseHandle': ([wt.HANDLE], wt.BOOL),
            'GetFinalPathNameByHandleW': ([wt.HANDLE, wt.LPWSTR, wt.DWORD, wt.DWORD], wt.DWORD),
            'GetFileInformationByHandleEx': ([wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD], wt.BOOL),
            'SetFileInformationByHandle': ([wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD], wt.BOOL),
            'SetFilePointerEx': ([wt.HANDLE, ct.c_longlong, ct.c_void_p, wt.DWORD], wt.BOOL),
            'ReadFile': ([wt.HANDLE, ct.c_void_p, wt.DWORD, ct.POINTER(wt.DWORD), ct.c_void_p], wt.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.k, name)
            function.argtypes, function.restype = arguments, result

    def checked(self, value):
        if not value:
            raise ct.WinError(ct.get_last_error())

    def open(self, path, access, share, flags):
        handle = self.k.CreateFileW(str(path), access, share, None, 3, flags, None)
        if handle == ct.c_void_p(-1).value:
            raise ct.WinError(ct.get_last_error())
        return handle

    def query(self, handle, kind, cls):
        value = cls()
        self.checked(self.k.GetFileInformationByHandleEx(handle, kind, ct.byref(value), ct.sizeof(value)))
        return value

    def final_path(self, handle):
        size = self.k.GetFinalPathNameByHandleW(handle, None, 0, 0)
        if not size or size > 32768:
            raise ValueError('Cannot resolve bounded native handle path')
        value = ct.create_unicode_buffer(size + 1)
        count = self.k.GetFinalPathNameByHandleW(handle, value, len(value), 0)
        if not count or count >= len(value) or value.value.startswith('\\\\?\\UNC\\'):
            raise ValueError('Invalid native handle path')
        return value.value.removeprefix('\\\\?\\')

    def close(self, handle):
        self.checked(self.k.CloseHandle(handle))


_NATIVE = None


def _native():
    global _NATIVE
    if _NATIVE is None:
        _NATIVE = _Windows()
    return _NATIVE


class _Directories:
    """Pin every lexical ancestor against deletion/replacement; no junctions."""
    def __init__(self, stack):
        self.stack, self.held = stack, {}

    def hold(self, directory):
        api = _native()
        for path in [*reversed(directory.parents), directory]:
            if path in self.held:
                continue
            layout.reject_link(path)
            handle = api.open(path, 1 | 0x80, 3, 0x00200000 | 0x02000000)
            self.stack.callback(api.close, handle)
            info = api.query(handle, 0, _Basic)
            if info.FileAttributes & 0x400 or not info.FileAttributes & 0x10 or api.final_path(handle) != str(path):
                raise ValueError('Ancestor identity/link/alias mismatch: ' + str(path))
            self.held[path] = handle


class _File:
    def __init__(self, path, *, mutate=False):
        self.path, self.mutate, self.handle = _plain(path), mutate, None

    def __enter__(self):
        api = _native()
        # Mutation handles are fully exclusive. Read leases deny write/delete.
        self.handle = api.open(self.path, 0x80000000 | 0x80 | (0x10000 if self.mutate else 0),
                               0 if self.mutate else 1, 0x00200000 | 0x08000000)
        try:
            self.identity()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_):
        if self.handle is not None:
            _native().close(self.handle)
            self.handle = None

    def identity(self):
        api = _native()
        basic = api.query(self.handle, 0, _Basic)
        standard = api.query(self.handle, 1, _Standard)
        identity = api.query(self.handle, 18, _Id)
        if basic.FileAttributes & 0x400 or standard.Directory or standard.NumberOfLinks != 1 or standard.DeletePending:
            raise ValueError('Link/hardlink/nonregular/delete-pending file: ' + str(self.path))
        if api.final_path(self.handle) != str(self.path):
            raise ValueError('Native file path alias: ' + str(self.path))
        if self.mutate and basic.FileAttributes & 1:
            raise PermissionError('Readonly program file preserved; attributes are not cleared: ' + str(self.path))
        return {'size': standard.EndOfFile, 'mtime': basic.LastWriteTime,
                'device': identity.VolumeSerialNumber,
                'inode': int.from_bytes(bytes(identity.Identifier), 'little'),
                'attributes': basic.FileAttributes}

    def digest(self):
        api = _native()
        before = self.identity()
        api.checked(api.k.SetFilePointerEx(self.handle, 0, None, 0))
        checksum, buffer, count = hashlib.sha256(), ct.create_string_buffer(1024 * 1024), wt.DWORD()
        view = memoryview(buffer).cast('B')
        while True:
            api.checked(api.k.ReadFile(self.handle, buffer, len(buffer), ct.byref(count), None))
            if not count.value:
                break
            checksum.update(view[:count.value])
        if self.identity() != before:
            raise ValueError('File changed while hashing: ' + str(self.path))
        return checksum.hexdigest()

    def verify(self, checksum):
        if self.digest() != checksum:
            raise ValueError('Owned file SHA256 mismatch: ' + str(self.path))

    def rename(self, destination, checksum):
        if not self.mutate:
            raise ValueError('Read lease cannot rename')
        self.verify(checksum)
        destination = _plain(destination)
        encoded = str(destination).encode('utf-16-le')
        offset = _Rename.FileName.offset
        buffer = ct.create_string_buffer(max(ct.sizeof(_Rename), offset + len(encoded) + 2))
        info = ct.cast(buffer, ct.POINTER(_Rename)).contents
        info.Flags, info.RootDirectory, info.FileNameLength = 0, None, len(encoded)
        ct.memmove(ct.addressof(buffer) + offset, encoded, len(encoded))
        api = _native()
        api.checked(api.k.SetFileInformationByHandle(self.handle, 3, buffer, len(buffer)))
        # The same exclusive handle still owns the same bytes. Record the new
        # location before any further fallible I/O, so rollback state is exact.
        self.path = destination

    def delete(self, checksum):
        if not self.mutate:
            raise ValueError('Read lease cannot delete')
        self.verify(checksum)
        value, api = _Disposition(1), _native()
        api.checked(api.k.SetFileInformationByHandle(self.handle, 4, ct.byref(value), ct.sizeof(value)))
        api.close(self.handle)
        self.handle = None
        try:
            self.path.lstat()
        except FileNotFoundError:
            return
        raise UpdateBlocked('Backup path reappeared after deletion; replacement preserved')


def _binding(root, held=None):
    held = held or {}
    result = {}
    for name, path in layout.tree_files(root).items():
        if path in held:
            result[name] = held[path].digest()
        else:
            with _File(path) as file:
                result[name] = file.digest()
    return result


def _check(callback):
    if callback():
        raise UpdateBlocked('Process callback reported occupants; no process is terminated')


def _paths(source, fixed, work):
    source, fixed, work = map(_plain, (source, fixed, work))
    paths = (source, fixed, work)
    for index, path in enumerate(paths):
        if any(path == other or path.is_relative_to(other) or other.is_relative_to(path)
               for other in paths[index + 1:]):
            raise ValueError('Source/fixed/work roots overlap')
    if not source.is_dir() or not fixed.is_dir() or not work.parent.is_dir():
        raise ValueError('Source/fixed/work parent must be existing plain directories')
    if work.exists():
        raise FileExistsError('Work directory must be new; never overwrite recovery evidence')
    if fixed.stat().st_dev != work.parent.stat().st_dev:
        raise ValueError('Transaction backup must be on the fixed-installation volume')
    return source, fixed, work


def separate_protected_payload(source, fixed, full_expected, before):
    """Read-only separation for a full final payload that also inventories models.

    Never silently drop a missing/new/changed protected file. Each protected
    member must already exist in fixed AND source, have the same independently
    expected SHA256 as before, and pass fresh native read-lease hashing in both.

    Pass result['transactionExpected'] to update_files. Preserve the original
    result['finalExpected'] for final full-payload verification; stripping a file
    from the WRITE plan does not strip it from final acceptance. The historical
    old_owned inventory need not be filtered: protected old-owned leaves cannot
    be retired by update_files either.
    """
    source, fixed = map(_plain, (source, fixed))
    full_expected = layout.normalize_source_hashes(full_expected)
    before = layout.normalize_source_hashes(before)
    if full_expected is None or before is None:
        raise ValueError('Explicit full-expected and before mappings required')
    reject_aliases(full_expected, before)
    transaction, verified = {}, []
    for name, checksum in full_expected.items():
        reason = preserved_reason(name)
        if not reason:
            transaction[name] = checksum
            continue
        if before.get(name) != checksum:
            raise ValueError('Protected payload is new, missing or changed; not filtered: ' + name)
        for root in (source, fixed):
            with _File(root / name) as file:
                file.verify(checksum)
        verified.append({'path': name, 'sha256': checksum, 'reason': reason,
                         'verifiedInSourceAndFixed': True, 'action': 'PRESERVE_IN_PLACE'})
    return {'transactionExpected': transaction, 'protectedVerified': verified,
            'finalExpected': dict(full_expected)}


def _shared_ownership(source, fixed, expected, old_owned, before):
    """保留仍被现有消费者精确引用的组；内容地址下不允许替换字节。"""
    group_prefix = 'UmiOCR-data/shared-runtime/'
    host_binding = 'UmiOCR-data/shared-runtime.json'
    if host_binding not in expected and not any(n.startswith(group_prefix) for n in (*expected, *before)):
        return set()
    import importlib.util

    loader = layout.plain_path(Path(__file__).resolve().parents[2] / 'UmiOCR-data/shared_runtime_bootstrap.py')
    spec = importlib.util.spec_from_file_location('fixed_shared_schema', loader)
    shared = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shared)
    for name, value in expected.items():
        if name.startswith(group_prefix) and name in before and before[name] != value:
            raise ValueError('不在原内容地址下覆盖共享运行时：' + name)
    references = {}
    for name in expected.keys() | before.keys():
        if name != host_binding and not (name.startswith('UmiOCR-data/plugins/') and name.count('/') == 3
                                         and name.endswith('/umi-plugin.json')):
            continue
        if name not in expected and name in old_owned and not preserved_reason(name):
            continue  # 消费者本身在安全退役范围，不再持有引用。
        _, value = shared.read_json((source if name in expected else fixed) / name, 256 * 1024)
        host = name == host_binding
        binding = value if host else value.get('runtime', {}).get('shared_runtime')
        if binding is None:
            continue
        for ref in shared.validate_binding(binding, host=host):
            key = ref['sha256']
            if references.setdefault(key, ref) != ref:
                raise ValueError('已安装共享运行组的种类冲突')
    retained = set()
    for digest, ref in references.items():
        prefix = group_prefix + digest + '/'
        proposed = {n: d for n, d in expected.items() if n.startswith(prefix)}
        actual = shared.read_group((source if proposed else fixed) / 'UmiOCR-data', ref)
        members = {prefix + 'site-packages/' + name: row['sha256'] for name, row in actual.files.items()}
        members[prefix + shared.GROUP_MANIFEST] = digest
        if proposed:
            if proposed != members:
                raise ValueError('新版本提供的共享组不完整：' + digest)
        elif any(before.get(n) != d for n, d in members.items()):
            raise ValueError('存在消费者的共享组与原安装摘要不匹配：' + digest)
        else:
            retained.update(members)
    return retained


def plan_update(source, fixed, work, expected, old_owned, before, check_processes):
    """Read-only preview with canonical relative-path/SHA256 maps.

    old_owned MUST be the previous independently verified final payload, never a
    scan relabelled as ownership. Protected state remains protected even if a
    historical producer incorrectly included it in that payload inventory.
    """
    source, fixed, work = _paths(source, fixed, work)
    expected, old_owned, before = map(layout.normalize_source_hashes, (expected, old_owned, before))
    if any(value is None for value in (expected, old_owned, before)):
        raise ValueError('Explicit expected, previous verified ownership, and before mappings required')
    reject_aliases(expected, old_owned, before)
    if ENTRY not in expected or ENTRY not in before or old_owned.get(ENTRY) != before[ENTRY]:
        raise ValueError('Launcher requires old ownership and new payload binding')
    _check(check_processes)
    if _binding(fixed) != before:
        raise ValueError('Fixed installation differs from the supplied before inventory')
    source_files = layout.tree_files(source)
    reject_aliases(expected, source_files)
    for name, checksum in expected.items():
        if preserved_reason(name):
            raise ValueError('New payload attempts to own protected user/model/private state: ' + name)
        if name not in source_files:
            raise ValueError('Missing source payload: ' + name)
        target = _plain(fixed / name)
        if target.exists() and (name not in before or not target.is_file()):
            raise ValueError('Existing target has no exact before ownership key: ' + name)
        with _File(source_files[name]) as file:
            file.verify(checksum)
    retained_shared = _shared_ownership(source, fixed, expected, old_owned, before)
    changes, retired, preserved = [], [], []
    for name, checksum in before.items():
        reason = 'SHARED_RUNTIME_IN_USE' if name in retained_shared else preserved_reason(name)
        if name in expected:
            if name not in old_owned:
                raise ValueError('New payload conflicts with an unknown existing file: ' + name)
            if old_owned[name] != checksum:
                raise ValueError('Existing owned payload was modified: ' + name)
            if checksum != expected[name]:
                changes.append(name)
        elif reason or name not in old_owned:
            preserved.append({'path': name, 'sha256': checksum, 'reason': reason or 'UNKNOWN_NOT_OWNED'})
        elif old_owned[name] != checksum:
            raise ValueError('Obsolete owned payload was modified; preserved, update stopped: ' + name)
        else:
            retired.append(name)
    changes.extend(name for name in expected if name not in before)
    touched = sorted(set(changes) | set(retired) | {ENTRY})
    for name in touched:
        if name in before:
            with _File(fixed / name, mutate=True) as file:
                file.verify(before[name])
    _check(check_processes)
    return {'status': 'PREVIEW_NOT_MUTATED', 'createdUtc': now(), 'source': str(source),
            'fixed': str(fixed), 'work': str(work), 'expected': expected, 'oldOwned': old_owned,
            'before': before, 'changes': sorted(changes), 'retire': sorted(retired),
            'preserved': preserved,
            'retiredLogicalBytes': sum((fixed / name).stat().st_size for name in retired),
            'boundary': 'Only exact old-owned program leaves may be replaced/retired. User state and unknown files remain in place. No process termination, readonly clearing, directory shape migration, links or hardlinks.'}


def _write_new(path, value):
    with path.open('x', encoding='utf-8') as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())


def update_files(source, fixed, work, expected, old_owned, before, check_processes,
                 *, hook=None, preview_callback=None):
    """Apply a new payload; no mutation of the actual installation by mere import.

    hook(name) is an optional failure-injection/observation callback after each
    non-launcher operation. It is not a bypass for process or ownership guards.
    """
    plan = plan_update(source, fixed, work, expected, old_owned, before, check_processes)
    source, fixed, work = map(Path, (plan['source'], plan['fixed'], plan['work']))
    expected, before = plan['expected'], plan['before']
    reserve = sum((source / name).stat().st_size for name in plan['changes']) + 512 * 1024**2
    if shutil.disk_usage(work.parent).free < reserve:
        raise OSError('Insufficient transaction staging space plus 512 MiB margin')
    report = {'status': 'PREPARING', 'startedUtc': now(), 'source': str(source), 'fixed': str(fixed),
              'work': str(work), 'replacedOrAddedFiles': 0, 'retiredFiles': 0,
              'preservedFiles': len(plan['preserved']), 'userDataMoved': False,
              'userProcessesTerminated': 0, 'readonlyAttributesCleared': 0,
              'backupFilesDeleted': 0, 'cleanupBlocked': [], 'createdDirectoriesRemoved': 0}
    with ExitStack() as stack:
        directories = _Directories(stack)
        for root in (source, fixed, work.parent):
            directories.hold(root)
        _check(check_processes)
        work.mkdir()
        directories.hold(work)
        _write_new(work / 'preview.json', plan)
        report['previewSha256'] = layout.sha256_file(work / 'preview.json')
        print(json.dumps({'preview': str(work / 'preview.json'), 'previewSha256': report['previewSha256'],
                          'changedFiles': len(plan['changes']), 'retiredFiles': len(plan['retire']),
                          'preservedFiles': len(plan['preserved'])}, ensure_ascii=False), flush=True)
        # The preview is durable and observable before staging or any rename/delete.
        if preview_callback:
            preview_callback(plan)
        journal = stack.enter_context((work / 'transaction.jsonl').open('x', encoding='utf-8'))
        def event(kind, **values):
            journal.write(json.dumps({'atUtc': now(), 'event': kind, **values}, ensure_ascii=False) + '\n')
            journal.flush()
            os.fsync(journal.fileno())
        stage, previous = work / 'payload', work / 'previous'
        stage.mkdir()
        previous.mkdir()
        directories.hold(stage)
        directories.hold(previous)
        old_handles, new_handles, moved_old, installed = {}, {}, [], []
        created = []
        committed = False
        entry_restored = False
        def ensure(directory, root):
            missing = []
            current = directory
            while current != root and not current.exists():
                missing.append(current)
                current = current.parent
            _plain(current)
            for value in reversed(missing):
                _check(check_processes)
                value.mkdir()
                if value.is_relative_to(fixed):
                    created.append(value)
                directories.hold(value)
            directories.hold(directory)
        def rename(file, destination, checksum, kind, name):
            _check(check_processes)
            event(kind + '_INTENT', path=name, source=str(file.path), destination=str(destination), sha256=checksum,
                  identity=file.identity())
            file.rename(destination, checksum)
        try:
            for name in plan['changes']:
                destination = stage / name
                ensure(destination.parent, stage)
                directories.hold((source / name).parent)
                with _File(source / name) as file:
                    file.verify(expected[name])
                    # Exclusive creation cannot follow a planted stage symlink or
                    # overwrite an unexpected file. Parent handles pin the path.
                    with (source / name).open('rb') as incoming, destination.open('xb') as outgoing:
                        shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
                        outgoing.flush()
                        os.fsync(outgoing.fileno())
                    file.verify(expected[name])
                new_handles[name] = stack.enter_context(_File(destination, mutate=True))
                new_handles[name].verify(expected[name])
            touched = sorted(set(plan['changes']) | set(plan['retire']) | {ENTRY})
            for name in touched:
                if name in before:
                    directories.hold((fixed / name).parent)
                    old_handles[name] = stack.enter_context(_File(fixed / name, mutate=True))
                    old_handles[name].verify(before[name])
                ensure((previous / name).parent, previous)
            # All old mutation leaves are now exclusively locked before entry gating.
            held = {file.path: file for file in old_handles.values()}
            if _binding(fixed, held) != before:
                raise ValueError('Installation changed after preview; no entry gating')
            rename(old_handles[ENTRY], previous / ENTRY, before[ENTRY], 'GATE_ENTRY', ENTRY)
            moved_old.append(ENTRY)
            event('ENTRY_GATED', path=ENTRY)
            order = lambda name: (0 if name in expected and name.startswith('UmiOCR-data/shared-runtime/') else 1, name)
            for name in sorted((set(plan['changes']) | set(plan['retire'])) - {ENTRY}, key=order):
                if name in old_handles:
                    rename(old_handles[name], previous / name, before[name], 'SAVE_OLD', name)
                    moved_old.append(name)
                    event('OLD_SAVED', path=name)
                if name in new_handles:
                    ensure((fixed / name).parent, fixed)
                    rename(new_handles[name], fixed / name, expected[name], 'INSTALL_NEW', name)
                    installed.append(name)
                    event('NEW_INSTALLED', path=name)
                if hook:
                    hook(name)
            combined = {name: checksum for name, checksum in before.items()
                        if name not in set(plan['retire']) and name not in expected}
            combined.update(expected)
            combined.pop(ENTRY)
            held = {file.path: file for file in new_handles.values()}
            if _binding(fixed, held) != combined:
                raise ValueError('New payload or preserved files differ before launcher commit')
            entry_file = new_handles[ENTRY] if ENTRY in new_handles else old_handles[ENTRY]
            rename(entry_file, fixed / ENTRY, expected[ENTRY], 'RESTORE_ENTRY', ENTRY)
            if ENTRY in new_handles:
                installed.append(ENTRY)
            else:
                moved_old.remove(ENTRY)
            entry_restored = True
            event('ENTRY_RESTORED', path=ENTRY)
            held = {file.path: file for file in [*old_handles.values(), *new_handles.values()]}
            combined[ENTRY] = expected[ENTRY]
            if _binding(fixed, held) != combined:
                raise ValueError('Final installed/preserved inventory mismatch')
            _check(check_processes)
            event('COMMIT', payloadFiles=len(expected), retiredFiles=len(plan['retire']))
            committed = True
            report.update(status='COMMITTED', replacedOrAddedFiles=len(plan['changes']),
                          retiredFiles=len(plan['retire']), retiredLogicalBytes=plan['retiredLogicalBytes'],
                          allPayloadHashesMatch=True, allPreservedHashesUnchanged=True,
                          launcherRestoredLast=True)
        except BaseException as error:
            report['error'] = type(error).__name__ + ': ' + str(error)
            # No forced rollback into an occupied directory. Keep all backup files.
            try:
                _check(check_processes)
                # If final checks failed after restoration, re-gate the entry first.
                if ENTRY in installed:
                    rename(new_handles[ENTRY], stage / ENTRY, expected[ENTRY], 'ROLLBACK_GATE', ENTRY)
                    installed.remove(ENTRY)
                elif entry_restored and ENTRY not in moved_old and ENTRY in old_handles:
                    rename(old_handles[ENTRY], previous / ENTRY, before[ENTRY], 'ROLLBACK_GATE', ENTRY)
                    moved_old.append(ENTRY)
                for name in reversed(installed):
                    rename(new_handles[name], stage / name, expected[name], 'ROLLBACK_NEW', name)
                    event('ROLLBACK_NEW_SAVED', path=name)
                for name in reversed([name for name in moved_old if name != ENTRY]):
                    rename(old_handles[name], fixed / name, before[name], 'ROLLBACK_OLD', name)
                    event('ROLLBACK_OLD_RESTORED', path=name)
                if ENTRY in moved_old:
                    rename(old_handles[ENTRY], fixed / ENTRY, before[ENTRY], 'ROLLBACK_ENTRY', ENTRY)
                held = {file.path: file for file in [*old_handles.values(), *new_handles.values()]}
                if _binding(fixed, held) != before:
                    raise UpdateBlocked('Rollback inventory is not the original before inventory')
                report['status'] = 'ROLLED_BACK'
                event('ROLLBACK_COMPLETE')
            except BaseException as rollback_error:
                report.update(status='ROLLBACK_BLOCKED', rollbackError=type(rollback_error).__name__ + ': ' + str(rollback_error))
                event('ROLLBACK_BLOCKED', error=report['rollbackError'])
            report['finishedUtc'] = now()
            _write_new(work / 'result.json', report)
            raise UpdateBlocked(report['status'] + ': ' + report['error'] + '; evidence=' + str(work)) from error
        if committed:
            # Commit is final. Cleanup errors do not falsely claim rollback/successful deletion.
            for name in moved_old:
                file = old_handles[name]
                try:
                    _check(check_processes)
                    event('BACKUP_DELETE_INTENT', path=name, backup=str(file.path), sha256=before[name], identity=file.identity())
                    file.delete(before[name])
                    report['backupFilesDeleted'] += 1
                    event('BACKUP_DELETED', path=name)
                except (OSError, ValueError, RuntimeError) as error:
                    report['cleanupBlocked'].append({'path': name, 'error': type(error).__name__ + ': ' + str(error)})
                    break
            if report['cleanupBlocked']:
                report['status'] = 'COMMITTED_CLEANUP_BLOCKED'
            report.update(finishedUtc=now(), workRetainedForEvidence=True,
                          previousPayloadFilesRemaining=len(moved_old) - report['backupFilesDeleted'])
            event('BATCH_END', status=report['status'], backupFilesDeleted=report['backupFilesDeleted'])
            _write_new(work / 'result.json', report)
    return report
