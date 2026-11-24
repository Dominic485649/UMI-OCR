"""Targeted Windows transaction tests using new synthetic directories only.

Run with -I -B; --work selects a project-owned fixture root. No real release is
read, modified, launched or cleaned. Fixture cleanup never clears real attributes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
TOOLS = PROJECT / 'build/tools'
sys.path.insert(0, str(TOOLS))
import fixed_installation_update as update

WORK = PROJECT / 'build/tmp/fixed-installation-update-unit'
EVIDENCE = None


def put(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def binding(root):
    return {name: update.layout.sha256_file(path) for name, path in update.layout.tree_files(root).items()}


@unittest.skipUnless(os.name == 'nt', 'Windows native handle semantics required')
class FixedInstallationUpdateTests(unittest.TestCase):
    def setUp(self):
        WORK.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=WORK, prefix='fixed-update-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source, self.fixed, self.work = (self.root / name for name in ('source', 'fixed', 'transaction'))
        self.source.mkdir()
        self.fixed.mkdir()
        self.old = {
            'Umi-OCR.exe': b'old synthetic launcher',
            'pkg/changed.py': b'old synthetic module',
            'pkg/obsolete.py': b'retired synthetic module',
            'UmiOCR-data/runtime/QtOld.dll': b'retired synthetic native file',
        }
        self.new = {
            'Umi-OCR.exe': b'new synthetic launcher',
            'pkg/changed.py': b'new synthetic module',
            'new-directory/resource.txt': b'new resource',
        }
        self.state = {
            'UmiOCR-data/.settings': b'user configuration',
            'UmiOCR-data/logs/session.txt': b'user log',
            'UmiOCR-data/temp_doc/job.pdf': b'user task resource',
            'UmiOCR-data/plugins/fixture/models/a.gguf': b'synthetic model marker, not a model',
            'Umi-OCR-UIUnlock.dll': b'private synthetic binary marker',
            'local-extra.txt': b'unknown original content',
        }
        for name, content in self.old.items():
            put(self.fixed, name, content)
        for name, content in self.state.items():
            put(self.fixed, name, content)
        for name, content in self.new.items():
            put(self.source, name, content)
        put(self.source, 'UmiOCR-data/.settings', b'review-only configuration: never install')
        self.expected = {name: hashlib.sha256(content).hexdigest() for name, content in self.new.items()}
        self.old_owned = {name: hashlib.sha256(content).hexdigest() for name, content in self.old.items()}
        self.before = binding(self.fixed)
        self.process_checks = 0
        # Registered after TemporaryDirectory.cleanup, so LIFO cleanup exports
        # structured transaction evidence before removing only our fixture.
        self.addCleanup(self.save_evidence)

    def save_evidence(self):
        if EVIDENCE is None:
            return
        destination = EVIDENCE / self._testMethodName
        destination.mkdir()
        artifacts = {}
        for name in ('preview.json', 'transaction.jsonl', 'result.json'):
            path = self.work / name
            if path.is_file():
                data = path.read_bytes()
                with (destination / name).open('xb') as output:
                    output.write(data)
                artifacts[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        scenario = {'test': self.id(), 'syntheticOnly': True, 'realReleaseReadOrChanged': False,
                    'processCheckCalls': self.process_checks, 'artifacts': artifacts}
        with (destination / 'scenario.json').open('x', encoding='utf-8') as output:
            json.dump(scenario, output, ensure_ascii=False, indent=2)
            output.write('\n')

    def check(self):
        self.process_checks += 1

    def plan(self, **kw):
        values = dict(source=self.source, fixed=self.fixed, work=self.work, expected=self.expected,
                      old_owned=self.old_owned, before=self.before, check_processes=self.check)
        values.update(kw)
        return update.plan_update(**values)

    def apply(self, **kw):
        values = dict(source=self.source, fixed=self.fixed, work=self.work, expected=self.expected,
                      old_owned=self.old_owned, before=self.before, check_processes=self.check)
        values.update(kw)
        return update.update_files(**values)

    def assert_original(self):
        self.assertEqual(binding(self.fixed), self.before)

    def result(self):
        return json.loads((self.work / 'result.json').read_text('utf-8'))

    def test_readonly_preview_has_exact_retirement_and_preservation(self):
        plan = self.plan()
        self.assertEqual(set(plan['retire']), {'pkg/obsolete.py', 'UmiOCR-data/runtime/QtOld.dll'})
        self.assertEqual({row['path'] for row in plan['preserved']}, set(self.state))
        self.assertFalse(self.work.exists())
        self.assert_original()

    def test_success_retires_known_obsolete_payload_preserves_every_state_file(self):
        observed = []
        def preview(plan):
            self.assertEqual(json.loads((self.work / 'preview.json').read_text('utf-8')), plan)
            self.assert_original()
            observed.append(True)
        result = self.apply(preview_callback=preview)
        self.assertEqual(result['status'], 'COMMITTED')
        self.assertEqual(result['retiredFiles'], 2)
        self.assertEqual(result['backupFilesDeleted'], 4)
        self.assertEqual(result['previousPayloadFilesRemaining'], 0)
        self.assertEqual(binding(self.fixed), {**{name: self.before[name] for name in self.state}, **self.expected})
        self.assertEqual(observed, [True])
        self.assertGreater(self.process_checks, 10)
        self.assertFalse(result['userDataMoved'])
        self.assertEqual(result['userProcessesTerminated'], 0)
        self.assertEqual(result['readonlyAttributesCleared'], 0)
        events = [json.loads(line) for line in (self.work / 'transaction.jsonl').read_text('utf-8').splitlines()]
        kinds = [event['event'] for event in events]
        self.assertLess(kinds.index('ENTRY_GATED'), kinds.index('OLD_SAVED'))
        self.assertLess(kinds.index('COMMIT'), kinds.index('BACKUP_DELETE_INTENT'))
        self.assertEqual(kinds[-1], 'BATCH_END')
        for event in events:
            if event['event'] == 'BACKUP_DELETED':
                self.assertTrue(any(value['event'] == 'BACKUP_DELETE_INTENT' and value['path'] == event['path']
                                    for value in events[:events.index(event)]))

    def test_old_manifest_cannot_authorize_models_user_configuration_or_private_dll(self):
        old_owned = {**self.old_owned, **{name: self.before[name] for name in self.state}}
        result = self.apply(old_owned=old_owned)
        self.assertEqual(result['retiredFiles'], 3)  # only explicitly owned local-extra becomes program-owned
        for name, data in self.state.items():
            if name != 'local-extra.txt':
                self.assertEqual((self.fixed / name).read_bytes(), data)
        self.assertFalse((self.fixed / 'local-extra.txt').exists())

    def test_rollback_restores_retired_and_replaced_files_with_entry_gated(self):
        seen_retirement = []
        def fail(name):
            self.assertFalse((self.fixed / update.ENTRY).exists())
            if name == 'pkg/changed.py':
                self.assertFalse((self.fixed / 'UmiOCR-data/runtime/QtOld.dll').exists())
                seen_retirement.append(True)
                raise RuntimeError('synthetic failure after retirement and replacement')
        with self.assertRaisesRegex(update.UpdateBlocked, 'ROLLED_BACK'):
            self.apply(hook=fail)
        self.assertEqual(seen_retirement, [True])
        self.assert_original()
        self.assertEqual(self.result()['status'], 'ROLLED_BACK')
        self.assertTrue((self.work / 'payload/pkg/changed.py').exists())

    def test_unchanged_launcher_is_also_gated_and_restored(self):
        put(self.source, update.ENTRY, self.old[update.ENTRY])
        expected = {**self.expected, update.ENTRY: self.old_owned[update.ENTRY]}
        seen = []
        def observe(_name):
            seen.append(not (self.fixed / update.ENTRY).exists())
        result = self.apply(expected=expected, hook=observe)
        self.assertEqual(result['status'], 'COMMITTED')
        self.assertTrue(all(seen))
        self.assertEqual((self.fixed / update.ENTRY).read_bytes(), self.old[update.ENTRY])

    def test_post_entry_failure_regates_then_rolls_back(self):
        original = update._binding
        count = 0
        def injected(root, held=None):
            nonlocal count
            if Path(root) == self.fixed:
                count += 1
                if count == 4:
                    raise ValueError('synthetic final inventory failure')
            return original(root, held)
        with patch.object(update, '_binding', side_effect=injected):
            with self.assertRaisesRegex(update.UpdateBlocked, 'ROLLED_BACK'):
                self.apply()
        self.assert_original()
        self.assertEqual(self.result()['status'], 'ROLLED_BACK')

    def test_process_occupancy_before_preflight_stops_without_mutation(self):
        def busy():
            raise RuntimeError('synthetic active process')
        with self.assertRaisesRegex(RuntimeError, 'active process'):
            self.apply(check_processes=busy)
        self.assert_original()
        self.assertFalse(self.work.exists())

    def test_truthy_process_callback_is_also_a_blocker(self):
        with self.assertRaisesRegex(update.UpdateBlocked, 'occupants'):
            self.apply(check_processes=lambda: [{'ProcessId': 12345}])
        self.assert_original()

    def test_new_occupancy_stops_and_does_not_force_rollback_into_running_program(self):
        busy = False
        def check():
            if busy:
                raise RuntimeError('synthetic new process; do not terminate')
        def start(_name):
            nonlocal busy
            busy = True
        with self.assertRaisesRegex(update.UpdateBlocked, 'ROLLBACK_BLOCKED'):
            self.apply(check_processes=check, hook=start)
        self.assertEqual(self.result()['status'], 'ROLLBACK_BLOCKED')
        self.assertFalse((self.fixed / update.ENTRY).exists())
        self.assertTrue((self.work / 'previous' / update.ENTRY).exists())
        self.assertEqual(self.result()['userProcessesTerminated'], 0)

    def test_readonly_obsolete_file_blocks_without_clearing_attribute(self):
        path = self.fixed / 'pkg/obsolete.py'
        path.chmod(0o444)
        try:
            with self.assertRaises(PermissionError):
                self.apply()
            self.assertTrue(path.stat().st_file_attributes & 1)
            self.assert_original()
        finally:
            path.chmod(0o666)  # only this test's synthetic file

    def test_permission_failure_mid_transaction_rolls_back_prior_retirement(self):
        original = update._File.rename
        def injected(file, destination, checksum):
            if file.path == self.fixed / 'pkg/changed.py':
                raise PermissionError('synthetic rename denied')
            return original(file, destination, checksum)
        with patch.object(update._File, 'rename', injected):
            with self.assertRaisesRegex(update.UpdateBlocked, 'ROLLED_BACK'):
                self.apply()
        self.assert_original()

    def test_backup_cleanup_permission_failure_is_not_false_rollback_or_complete_cleanup(self):
        with patch.object(update._File, 'delete', side_effect=PermissionError('synthetic cleanup denied')):
            result = self.apply()
        self.assertEqual(result['status'], 'COMMITTED_CLEANUP_BLOCKED')
        self.assertEqual(result['backupFilesDeleted'], 0)
        self.assertEqual(result['previousPayloadFilesRemaining'], 4)
        self.assertTrue(result['cleanupBlocked'])
        self.assertFalse((self.fixed / 'pkg/obsolete.py').exists())
        self.assertEqual((self.fixed / update.ENTRY).read_bytes(), self.new[update.ENTRY])

    def test_existing_shared_read_handle_blocks_native_delete_access(self):
        api = update._native()
        handle = api.open(self.fixed / 'pkg/obsolete.py', 0x80000000, 1, 0x00200000)
        try:
            with self.assertRaises(OSError) as caught:
                self.apply()
            self.assertEqual(caught.exception.winerror, 32)
            self.assert_original()
        finally:
            api.close(handle)

    def test_exclusive_transaction_prevents_another_writer_or_deleter(self):
        attempts = []
        api = update._native()
        def hook(_name):
            if attempts:
                return
            for access in (0x40000000, 0x10000):
                with self.assertRaises(OSError) as caught:
                    handle = api.open(self.fixed / 'pkg/obsolete.py' if (self.fixed / 'pkg/obsolete.py').exists()
                                      else self.work / 'previous/UmiOCR-data/runtime/QtOld.dll', access, 7, 0x00200000)
                    api.close(handle)
                self.assertEqual(caught.exception.winerror, 32)
                attempts.append(access)
        result = self.apply(hook=hook)
        self.assertEqual(result['status'], 'COMMITTED')
        self.assertEqual(len(attempts), 2)

    def test_hardlinked_old_program_is_never_replaced_or_retired(self):
        os.link(self.fixed / 'pkg/obsolete.py', self.root / 'external-hardlink')
        with self.assertRaisesRegex(RuntimeError, 'Hard-linked'):
            self.apply()
        self.assertEqual((self.fixed / 'pkg/obsolete.py').read_bytes(), self.old['pkg/obsolete.py'])
        self.assertFalse(self.work.exists())

    def test_hardlinked_source_is_rejected(self):
        os.link(self.source / 'pkg/changed.py', self.root / 'source-hardlink')
        with self.assertRaisesRegex(RuntimeError, 'Hard-linked'):
            self.apply()
        self.assert_original()

    def test_junction_to_external_data_stops_without_following_or_moving_it(self):
        external = self.root / 'external-user-data'
        external.mkdir()
        put(external, 'sentinel.txt', b'never touched')
        junction = self.fixed / 'external-link'
        subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(junction), str(external)],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            with self.assertRaisesRegex(RuntimeError, 'Link/junction'):
                self.apply()
            self.assertEqual((external / 'sentinel.txt').read_bytes(), b'never touched')
            self.assertFalse(self.work.exists())
        finally:
            junction.rmdir()  # remove only the fixture junction, never its target

    def test_cross_inventory_case_alias_is_rejected(self):
        expected = dict(self.expected)
        expected['PKG/changed.py'] = expected.pop('pkg/changed.py')
        with self.assertRaisesRegex(ValueError, 'case alias'):
            self.apply(expected=expected)
        self.assert_original()

    def test_actual_root_case_alias_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'alias/casing'):
            self.apply(fixed=self.fixed.parent / 'FIXED')
        self.assert_original()

    def test_file_directory_shape_change_is_not_migrated(self):
        expected = {**self.expected, 'pkg/obsolete.py/child.txt': hashlib.sha256(b'x').hexdigest()}
        with self.assertRaisesRegex(ValueError, 'shape conflict'):
            self.apply(expected=expected)
        self.assert_original()

    def test_unknown_target_collision_stops_even_when_bytes_match_expected(self):
        put(self.source, 'local-extra.txt', self.state['local-extra.txt'])
        expected = {**self.expected, 'local-extra.txt': self.before['local-extra.txt']}
        with self.assertRaisesRegex(ValueError, 'unknown existing'):
            self.apply(expected=expected)
        self.assert_original()

    def test_modified_obsolete_owned_payload_is_a_blocker_not_a_delete(self):
        put(self.fixed, 'pkg/obsolete.py', b'customized existing code')
        before = binding(self.fixed)
        with self.assertRaisesRegex(ValueError, 'was modified'):
            self.apply(before=before)
        self.assertEqual(binding(self.fixed), before)
        self.assertFalse(self.work.exists())

    def test_modified_replacement_payload_is_a_blocker(self):
        put(self.fixed, 'pkg/changed.py', b'customized existing replacement target')
        before = binding(self.fixed)
        with self.assertRaisesRegex(ValueError, 'was modified'):
            self.apply(before=before)
        self.assertEqual(binding(self.fixed), before)

    def test_protected_new_expected_is_rejected_without_copying_review_settings(self):
        expected = {**self.expected, 'UmiOCR-data/.settings': update.layout.sha256_file(self.source / 'UmiOCR-data/.settings')}
        with self.assertRaisesRegex(ValueError, 'protected'):
            self.apply(expected=expected)
        self.assert_original()

    def test_new_model_weight_is_not_part_of_payload_update(self):
        put(self.source, 'models/new.gguf', b'synthetic weight marker')
        expected = {**self.expected, 'models/new.gguf': update.layout.sha256_file(self.source / 'models/new.gguf')}
        with self.assertRaisesRegex(ValueError, 'protected'):
            self.apply(expected=expected)
        self.assert_original()

    def test_program_models_python_namespace_is_not_confused_with_model_storage(self):
        name = 'UmiOCR-data/plugins/fixture/vendor/paddlex/inference/models/family/__init__.py'
        put(self.source, name, b'# synthetic code, not weights')
        expected = {**self.expected, name: update.layout.sha256_file(self.source / name)}
        result = self.apply(expected=expected)
        self.assertEqual(result['status'], 'COMMITTED')
        self.assertTrue((self.fixed / name).is_file())
        self.assertEqual((self.fixed / 'UmiOCR-data/plugins/fixture/models/a.gguf').read_bytes(),
                         self.state['UmiOCR-data/plugins/fixture/models/a.gguf'])

    def test_before_inventory_drift_stops_without_reverting_user_data(self):
        put(self.fixed, 'UmiOCR-data/.settings', b'user changed configuration')
        current = binding(self.fixed)
        with self.assertRaisesRegex(ValueError, 'before inventory'):
            self.apply()
        self.assertEqual(binding(self.fixed), current)

    def test_user_data_changed_after_preview_is_never_overwritten_or_migrated(self):
        def drift(_plan):
            put(self.fixed, 'UmiOCR-data/.settings', b'new user data during staging')
        with self.assertRaises(update.UpdateBlocked):
            self.apply(preview_callback=drift)
        self.assertEqual((self.fixed / 'UmiOCR-data/.settings').read_bytes(), b'new user data during staging')
        self.assertEqual((self.fixed / update.ENTRY).read_bytes(), self.old[update.ENTRY])
        self.assertFalse((self.work / 'previous' / update.ENTRY).exists())

    def test_unknown_file_appearing_during_transaction_is_preserved(self):
        def add(_name):
            put(self.fixed, 'new-user-file.txt', b'unknown concurrent user bytes')
        with self.assertRaises(update.UpdateBlocked):
            self.apply(hook=add)
        self.assertEqual((self.fixed / 'new-user-file.txt').read_bytes(), b'unknown concurrent user bytes')
        self.assertEqual((self.fixed / update.ENTRY).read_bytes(), self.old[update.ENTRY])
        self.assertEqual(self.result()['status'], 'ROLLBACK_BLOCKED')

    def test_work_reuse_and_root_overlap_are_rejected(self):
        self.work.mkdir()
        put(self.work, 'evidence.txt', b'existing evidence')
        with self.assertRaises(FileExistsError):
            self.apply()
        self.assertEqual((self.work / 'evidence.txt').read_bytes(), b'existing evidence')
        with self.assertRaisesRegex(ValueError, 'overlap'):
            self.apply(work=self.fixed / 'nested-work')
        self.assert_original()

    def test_source_drift_after_preview_is_a_nonmutating_failure(self):
        def drift(_plan):
            put(self.source, 'pkg/changed.py', b'wrong staged bytes')
        with self.assertRaisesRegex(update.UpdateBlocked, 'ROLLED_BACK'):
            self.apply(preview_callback=drift)
        self.assert_original()

    def full_expected(self):
        protected = ['UmiOCR-data/plugins/fixture/models/a.gguf', 'Umi-OCR-UIUnlock.dll']
        for name in protected:
            put(self.source, name, self.state[name])
        return {**self.expected, **{name: self.before[name] for name in protected}}

    def test_full_final_payload_separation_preserves_models_and_private_binary(self):
        full = self.full_expected()
        split = update.separate_protected_payload(self.source, self.fixed, full, self.before)
        self.assertEqual(split['finalExpected'], full)
        self.assertEqual(split['transactionExpected'], self.expected)
        self.assertEqual(len(split['protectedVerified']), 2)
        self.assertFalse(self.work.exists())
        self.assert_original()
        result = self.apply(expected=split['transactionExpected'],
                            old_owned={**self.old_owned, **{row['path']: row['sha256'] for row in split['protectedVerified']}})
        self.assertEqual(result['status'], 'COMMITTED')
        final = binding(self.fixed)
        self.assertTrue(all(final.get(name) == checksum for name, checksum in full.items()))
        for row in split['protectedVerified']:
            self.assertEqual((self.fixed / row['path']).read_bytes(), self.state[row['path']])

    def test_protected_separation_never_hides_missing_source_model(self):
        full = self.full_expected()
        (self.source / 'UmiOCR-data/plugins/fixture/models/a.gguf').unlink()
        with self.assertRaises(FileNotFoundError):
            update.separate_protected_payload(self.source, self.fixed, full, self.before)
        self.assert_original()
        self.assertFalse(self.work.exists())

    def test_protected_separation_never_hides_new_model_missing_from_before(self):
        full = self.full_expected()
        name = 'models/new.gguf'
        put(self.source, name, b'synthetic new model marker')
        full[name] = update.layout.sha256_file(self.source / name)
        with self.assertRaisesRegex(ValueError, 'new, missing or changed'):
            update.separate_protected_payload(self.source, self.fixed, full, self.before)
        self.assert_original()

    def test_protected_separation_checks_actual_source_bytes(self):
        full = self.full_expected()
        put(self.source, 'UmiOCR-data/plugins/fixture/models/a.gguf', b'changed source marker')
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
            update.separate_protected_payload(self.source, self.fixed, full, self.before)
        self.assert_original()

    def test_protected_separation_checks_actual_fixed_bytes(self):
        full = self.full_expected()
        put(self.fixed, 'UmiOCR-data/plugins/fixture/models/a.gguf', b'changed existing model marker')
        current = binding(self.fixed)
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
            update.separate_protected_payload(self.source, self.fixed, full, self.before)
        self.assertEqual(binding(self.fixed), current)

    def test_protected_separation_rejects_changed_expected_private_binary(self):
        full = self.full_expected()
        full['Umi-OCR-UIUnlock.dll'] = hashlib.sha256(b'changed private binary').hexdigest()
        with self.assertRaisesRegex(ValueError, 'new, missing or changed'):
            update.separate_protected_payload(self.source, self.fixed, full, self.before)
        self.assert_original()

    def test_protected_separation_does_not_allow_missing_fixed_model(self):
        full = self.full_expected()
        (self.fixed / 'UmiOCR-data/plugins/fixture/models/a.gguf').unlink()
        with self.assertRaises(FileNotFoundError):
            update.separate_protected_payload(self.source, self.fixed, full, self.before)
        self.assertFalse(self.work.exists())

    def test_preexisting_unexpected_staging_file_is_not_overwritten(self):
        def collision(_plan):
            put(self.work, 'payload/Umi-OCR.exe', b'unknown staging bytes')
        with self.assertRaises(FileExistsError):
            self.apply(preview_callback=collision)
        self.assertEqual((self.work / 'payload/Umi-OCR.exe').read_bytes(), b'unknown staging bytes')
        self.assert_original()

    def test_model_bin_and_noncode_configuration_remain_protected_despite_old_ownership(self):
        extras = {'model.bin': b'synthetic model bytes', 'settings.ini': b'user configuration'}
        for name, content in extras.items():
            put(self.fixed, name, content)
        before = binding(self.fixed)
        owned = {**self.old_owned, **{name: before[name] for name in extras}}
        result = self.apply(before=before, old_owned=owned)
        self.assertEqual(result['retiredFiles'], 2)
        for name, content in extras.items():
            self.assertEqual((self.fixed / name).read_bytes(), content)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--work', type=Path)
    parser.add_argument('--evidence', type=Path)
    options, remaining = parser.parse_known_args()
    if options.work:
        WORK = options.work
    WORK = update.layout.plain_path(WORK)
    if not any(WORK.is_relative_to(PROJECT / prefix) for prefix in ('build/tmp', 'build/audit')):
        parser.error('Fixture root must be within project build/tmp or build/audit')
    if options.evidence:
        EVIDENCE = update.layout.plain_path(options.evidence)
        if not EVIDENCE.is_relative_to(PROJECT):
            parser.error('Evidence must stay within this project')
        EVIDENCE.mkdir()  # new output only, never replace an earlier test run
    program = unittest.main(argv=[sys.argv[0], *remaining], verbosity=2, exit=False)
    result = program.result
    if EVIDENCE is not None:
        summary = {'status': 'PASS' if result.wasSuccessful() else 'FAIL', 'testsRun': result.testsRun,
                   'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped),
                   'toolSha256': update.layout.sha256_file(TOOLS / 'fixed_installation_update.py'),
                   'testsSha256': update.layout.sha256_file(Path(__file__)),
                   'realReleaseReadOrChanged': False,
                   'scenarios': {path.parent.name: update.layout.sha256_file(path)
                                 for path in sorted(EVIDENCE.glob('*/scenario.json'))}}
        with (EVIDENCE / 'unit-result.json').open('x', encoding='utf-8') as output:
            json.dump(summary, output, ensure_ascii=False, indent=2)
            output.write('\n')
    sys.exit(not result.wasSuccessful())
