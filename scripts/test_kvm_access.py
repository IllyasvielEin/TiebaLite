"""Mocked KVM lifecycle/security tests. No test touches /dev/kvm or executes sudo."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

import kvm_access as kvm

ORIGINAL = '# file: /dev/kvm\n# owner: 0\n# group: 993\nuser::rw-\ngroup::rw-\nother::---\n\n'
GRANTED = ('# file: /dev/kvm\n# owner: 0\n# group: 993\nuser::rw-\nuser:1001:rw-\n'
           'group::rw-\nmask::rw-\nother::---\n\n')


class FakeHost:
    def __init__(self):
        self.runner_uid = 1001
        self.acl_text = ORIGINAL
        self.accessible = False
        self.info = dict(dev=7, ino=83, rdev=os.makedev(10, 232), uid=0, gid=993,
                         mode=0o660, major=10, minor=232)
        self.calls = []
        self.grant_error = False
        self.restore_error = False
        self.bad_restore = False
        self.access_error = False

    def uid(self):
        return self.runner_uid

    def groups(self):
        return [4, 100, 118, 999, 1001]

    def device(self):
        return self.info.copy()

    def access(self):
        return self.accessible

    def tools(self):
        self.calls.append('tools')

    def acl(self):
        return self.acl_text

    def grant(self):
        self.calls.append('grant')
        self.acl_text = GRANTED
        self.accessible = not self.access_error
        if self.grant_error:
            raise kvm.Blocked('mock_grant_failed')

    def restore(self, text):
        self.calls.append(('restore', text))
        if self.restore_error:
            raise kvm.Blocked('mock_restore_failed')
        if not self.bad_restore:
            self.acl_text = text
            self.accessible = False


class KvmAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = dict(RUNNER_TEMP=self.temp.name, GITHUB_RUN_ID='12345',
                        GITHUB_RUN_ATTEMPT='1', SMOKE_API='37', ALLOW_KVM_ACCESS='true',
                        GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_REF='refs/heads/4.0-dev',
                        DEFAULT_BRANCH='4.0-dev')
        self.host = FakeHost()
        self.state = Path(self.temp.name) / kvm.STATE_NAME
        # Fail loudly if any test accidentally reaches the real privileged/device boundary.
        for method in ('device', 'access', 'grant', 'restore', 'acl', 'tools'):
            patcher = mock.patch.object(kvm.Host, method, side_effect=AssertionError('Real host access forbidden'))
            patcher.start()
            self.addCleanup(patcher.stop)

    def change_metadata(self, **values):
        path = self.state / kvm.METADATA
        data = json.loads(path.read_text())
        data.update(values)
        path.write_text(json.dumps(data))

    def assert_no_grant(self):
        self.assertNotIn('grant', self.host.calls)
        self.assertFalse(self.state.exists())

    def test_approved_run_saves_private_acl_before_grant_and_restores_exactly(self):
        def checked_grant():
            self.assertEqual(ORIGINAL, (self.state / kvm.ORIGINAL).read_text())
            self.assertEqual(0o700, stat.S_IMODE(self.state.stat().st_mode))
            for name in (kvm.ORIGINAL, kvm.METADATA):
                self.assertEqual(0o600, stat.S_IMODE((self.state / name).stat().st_mode))
            FakeHost.grant(self.host)
        self.host.grant = checked_grant
        self.assertEqual('temporary_access', kvm.acquire(self.env, self.host)['status'])
        report = kvm.restore(self.env, self.host)
        self.assertEqual('verified', report['status'])
        self.assertFalse(report['read_write'])
        self.assertEqual(ORIGINAL, self.host.acl_text)
        self.assertEqual([('restore', ORIGINAL)], [c for c in self.host.calls if isinstance(c, tuple)])
        self.assertFalse(self.state.exists())

    def test_existing_access_never_changes_acl(self):
        self.host.accessible = True
        self.assertEqual('existing_access', kvm.acquire(self.env, self.host)['status'])
        self.assert_no_grant()
        self.assertEqual('not_needed', kvm.restore(self.env, self.host)['status'])
        self.assertFalse(any(isinstance(c, tuple) for c in self.host.calls))

    def test_each_matrix_api_is_supported(self):
        for api in ('35', '37'):
            with self.subTest(api=api):
                self.env['SMOKE_API'] = api
                kvm.acquire(self.env, self.host)
                self.assertEqual('verified', kvm.restore(self.env, self.host)['status'])

    def test_absent_false_or_nonliteral_approval_is_rejected(self):
        for value in (None, '', 'false', 'TRUE', '1'):
            with self.subTest(value=value):
                self.env['ALLOW_KVM_ACCESS'] = value
                with self.assertRaisesRegex(kvm.Blocked, 'explicit_approval_required'):
                    kvm.acquire(self.env, self.host)
                self.assert_no_grant()

    def test_reruns_require_fresh_dispatch_even_with_true_input(self):
        for value in ('2', '0', '', '01'):
            with self.subTest(value=value):
                self.env['GITHUB_RUN_ATTEMPT'] = value
                with self.assertRaisesRegex(kvm.Blocked, 'fresh_dispatch_required'):
                    kvm.acquire(self.env, self.host)
                self.assert_no_grant()

    def test_untrusted_workflow_branch_and_default_branch_rejected(self):
        for name, value in [('GITHUB_EVENT_NAME', 'push'), ('GITHUB_REF', 'refs/heads/test'),
                            ('DEFAULT_BRANCH', 'main')]:
            env = dict(self.env, **{name: value})
            with self.subTest(name=name), self.assertRaisesRegex(kvm.Blocked, 'untrusted_workflow_context'):
                kvm.acquire(env, self.host)
            self.assert_no_grant()

    def test_unexpected_uid_cannot_grant(self):
        self.host.runner_uid = 0
        with self.assertRaisesRegex(kvm.Blocked, 'unexpected_runner_uid'):
            kvm.acquire(self.env, self.host)
        self.assert_no_grant()

    def test_unknown_matrix_api_and_malformed_run_identity_rejected(self):
        for name, value in [('SMOKE_API', '36'), ('GITHUB_RUN_ID', '../1'), ('GITHUB_RUN_ID', '')]:
            with self.subTest(name=name, value=value), self.assertRaises(kvm.Blocked):
                kvm.acquire(dict(self.env, **{name: value}), self.host)
            self.assert_no_grant()

    def test_missing_utilities_fail_without_install_or_grant(self):
        self.host.tools = mock.Mock(side_effect=kvm.Blocked('missing_setfacl'))
        with self.assertRaisesRegex(kvm.Blocked, 'missing_setfacl'):
            kvm.acquire(self.env, self.host)
        self.assert_no_grant()

    def test_acl_parser_requires_exact_target_numeric_identity_and_plain_access_acl(self):
        for text in [ORIGINAL.replace('/dev/kvm', '/etc/passwd'),
                     ORIGINAL.replace('owner: 0', 'owner: root'),
                     ORIGINAL.replace('group: 993', 'group: kvm'),
                     ORIGINAL + '# file: /another\n', ORIGINAL + 'default:user::rwx\n',
                     ORIGINAL + '# flags: s--\n', ORIGINAL + 'user::rw-\n',
                     ORIGINAL.replace('other::---\n', ''), ORIGINAL + 'mask:1001:rw-\n',
                     ORIGINAL + 'user:other:rw-\n', 'x' * 4097]:
            with self.subTest(text=text), self.assertRaises(kvm.Blocked):
                kvm.parse_acl(text)

    def test_extended_original_acl_rejected_to_avoid_widening_other_masked_rights(self):
        self.host.acl_text = ORIGINAL.rstrip() + '\nuser:2345:rw-\nmask::r--\n'
        with self.assertRaisesRegex(kvm.Blocked, 'unexpected_original_acl'):
            kvm.acquire(self.env, self.host)
        self.assert_no_grant()

    def test_changed_owner_group_or_mode_rejected(self):
        for key, value in [('uid', 99), ('gid', 44), ('mode', 0o666)]:
            with self.subTest(key=key):
                old = self.host.info[key]
                self.host.info[key] = value
                with self.assertRaisesRegex(kvm.Blocked, 'unexpected_original_acl'):
                    kvm.acquire(self.env, self.host)
                self.host.info[key] = old
                self.assert_no_grant()

    def test_snapshot_failure_prevents_grant(self):
        with mock.patch.object(kvm, 'write_private', side_effect=OSError('mock disk full')):
            with self.assertRaises(OSError):
                kvm.acquire(self.env, self.host)
        self.assertNotIn('grant', self.host.calls)
        self.assertEqual('failed', kvm.restore(self.env, self.host)['status'])
        self.assertFalse(self.state.exists())

    def test_device_replacement_between_snapshot_and_grant_blocks_change(self):
        original_device = self.host.device()
        replacement = dict(original_device, ino=99)
        self.host.device = mock.Mock(side_effect=[original_device, replacement])
        with self.assertRaisesRegex(kvm.Blocked, 'kvm_changed_before_grant'):
            kvm.acquire(self.env, self.host)
        self.assertNotIn('grant', self.host.calls)

    def test_partial_grant_failure_retains_snapshot_for_always_cleanup(self):
        self.host.grant_error = True
        with self.assertRaisesRegex(kvm.Blocked, 'mock_grant_failed'):
            kvm.acquire(self.env, self.host)
        self.assertTrue(self.state.exists())
        self.assertEqual('verified', kvm.restore(self.env, self.host)['status'])
        self.assertFalse(self.state.exists())

    def test_missing_access_after_grant_fails_and_can_restore(self):
        self.host.access_error = True
        with self.assertRaisesRegex(kvm.Blocked, 'kvm_still_inaccessible'):
            kvm.acquire(self.env, self.host)
        self.assertEqual('verified', kvm.restore(self.env, self.host)['status'])

    def test_unexpected_grant_acl_fails_and_can_restore(self):
        def bad_grant():
            FakeHost.grant(self.host)
            self.host.acl_text = self.host.acl_text.rstrip() + '\nuser:2345:rw-\n'
        self.host.grant = bad_grant
        with self.assertRaisesRegex(kvm.Blocked, 'unexpected_granted_acl'):
            kvm.acquire(self.env, self.host)
        self.assertEqual('verified', kvm.restore(self.env, self.host)['status'])

    def test_restoration_command_failure_is_reported_and_snapshot_removed(self):
        kvm.acquire(self.env, self.host)
        self.host.restore_error = True
        report = kvm.restore(self.env, self.host)
        self.assertEqual('failed', report['status'])
        self.assertIn('mock_restore_failed', report['errors'])
        self.assertFalse(self.state.exists())

    def test_restoration_must_verify_exact_original_acl(self):
        kvm.acquire(self.env, self.host)
        self.host.bad_restore = True
        report = kvm.restore(self.env, self.host)
        self.assertEqual('failed', report['status'])
        self.assertIn('restoration_verification_failed', report['errors'])
        self.assertFalse(self.state.exists())

    def test_restoration_must_verify_mode_and_device_identity(self):
        kvm.acquire(self.env, self.host)
        def bad_restore(text):
            FakeHost.restore(self.host, text)
            self.host.info['mode'] = 0o640
        self.host.restore = bad_restore
        self.assertIn('restoration_verification_failed', kvm.restore(self.env, self.host)['errors'])

    def test_changed_device_is_not_restored(self):
        kvm.acquire(self.env, self.host)
        self.host.info['ino'] += 1
        report = kvm.restore(self.env, self.host)
        self.assertIn('invalid_saved_device_or_acl', report['errors'])
        self.assertFalse(any(isinstance(c, tuple) for c in self.host.calls))

    def test_mismatched_run_or_api_snapshot_is_not_restored(self):
        for changes in ({'run_id': '99'}, {'api': '35'}, {'attempt': '2'}, {'version': 2}):
            with self.subTest(changes=changes):
                self.host = FakeHost()
                kvm.acquire(self.env, self.host)
                self.change_metadata(**changes)
                self.assertIn('invalid_state_binding', kvm.restore(self.env, self.host)['errors'])
                self.assertFalse(any(isinstance(c, tuple) for c in self.host.calls))

    def test_changed_snapshot_hash_is_rejected(self):
        kvm.acquire(self.env, self.host)
        (self.state / kvm.ORIGINAL).write_text(ORIGINAL.replace('group::rw-', 'group::r--'))
        self.assertIn('changed_acl_snapshot', kvm.restore(self.env, self.host)['errors'])
        self.assertFalse(any(isinstance(c, tuple) for c in self.host.calls))

    def test_malicious_target_is_rejected_even_with_matching_hash(self):
        kvm.acquire(self.env, self.host)
        altered = ORIGINAL.replace('/dev/kvm', '/etc/passwd')
        (self.state / kvm.ORIGINAL).write_text(altered)
        self.change_metadata(acl_sha256=hashlib.sha256(altered.encode()).hexdigest())
        self.assertIn('invalid_acl_target', kvm.restore(self.env, self.host)['errors'])
        self.assertFalse(any(isinstance(c, tuple) for c in self.host.calls))

    def test_state_directory_symlink_is_rejected_without_following_target(self):
        target = Path(self.temp.name) / 'elsewhere'
        target.mkdir()
        sentinel = target / 'sentinel'
        sentinel.write_text('untouched')
        self.state.symlink_to(target, target_is_directory=True)
        with self.assertRaises(kvm.Blocked):
            kvm.acquire(self.env, self.host)
        self.assertEqual('failed', kvm.restore(self.env, self.host)['status'])
        self.assertEqual('untouched', sentinel.read_text())
        self.assertNotIn('grant', self.host.calls)

    def test_symlink_runner_temp_ancestor_is_rejected(self):
        linked = Path(self.temp.name) / 'linked'
        linked.symlink_to(self.temp.name, target_is_directory=True)
        self.env['RUNNER_TEMP'] = str(linked)
        with self.assertRaisesRegex(kvm.Blocked, 'unsafe_state_directory'):
            kvm.acquire(self.env, self.host)
        self.assert_no_grant()

    def test_state_acl_symlink_is_rejected_without_reading_target(self):
        kvm.acquire(self.env, self.host)
        original = self.state / kvm.ORIGINAL
        original.unlink()
        target = Path(self.temp.name) / 'unrelated'
        target.write_text('untouched')
        original.symlink_to(target)
        self.assertEqual('failed', kvm.restore(self.env, self.host)['status'])
        self.assertFalse(any(isinstance(c, tuple) for c in self.host.calls))
        self.assertEqual('untouched', target.read_text())

    def test_hardlinked_state_acl_is_rejected(self):
        kvm.acquire(self.env, self.host)
        os.link(self.state / kvm.ORIGINAL, Path(self.temp.name) / 'unrelated')
        self.assertIn('unsafe_state_file', kvm.restore(self.env, self.host)['errors'])
        self.assertFalse(any(isinstance(c, tuple) for c in self.host.calls))

    def test_nonprivate_existing_state_is_rejected(self):
        self.state.mkdir(mode=0o755)
        with self.assertRaisesRegex(kvm.Blocked, 'existing_state'):
            kvm.acquire(self.env, self.host)
        self.assertIn('nonprivate_state_directory', kvm.restore(self.env, self.host)['errors'])

    def test_corrupt_metadata_fails_closed(self):
        kvm.acquire(self.env, self.host)
        (self.state / kvm.METADATA).write_text('{broken')
        self.assertEqual('failed', kvm.restore(self.env, self.host)['status'])
        self.assertFalse(any(isinstance(c, tuple) for c in self.host.calls))
        self.assertFalse(self.state.exists())

    def test_cleanup_failure_cannot_hide_restoration_failure(self):
        kvm.acquire(self.env, self.host)
        self.host.restore_error = True
        with mock.patch.object(kvm, 'remove_state', side_effect=kvm.Blocked('mock_cleanup_failed')):
            report = kvm.restore(self.env, self.host)
        self.assertEqual(['mock_restore_failed', 'mock_cleanup_failed'], report['errors'])
        self.assertEqual('failed', report['status'])


class HostBoundaryTests(unittest.TestCase):
    def test_privileged_command_arguments_are_fixed_target_and_noninteractive(self):
        host = kvm.Host()
        with mock.patch.object(host, 'command', return_value=ORIGINAL) as command:
            host.acl()
            host.grant()
            host.restore(ORIGINAL)
        self.assertEqual([
            mock.call(['getfacl', '-n', '-p', '--', '/dev/kvm']),
            mock.call(['sudo', '-n', 'setfacl', '-m', 'u:1001:rw', '/dev/kvm']),
            mock.call(['sudo', '-n', 'setfacl', '--set-file=-', '/dev/kvm'], ORIGINAL),
        ], command.call_args_list)

    def test_host_command_is_bounded_and_does_not_echo_stderr(self):
        with mock.patch.object(subprocess, 'run', side_effect=subprocess.CalledProcessError(
                1, 'mock', stderr='private data')) as run:
            with self.assertRaisesRegex(kvm.Blocked, '^kvm_command_failed$'):
                kvm.Host().command(['never-executed'])
        self.assertEqual(20, run.call_args.kwargs['timeout'])
        self.assertTrue(run.call_args.kwargs['check'])
        self.assertTrue(run.call_args.kwargs['capture_output'])

    def test_each_missing_tool_fails_without_running_or_installing_anything(self):
        for missing in ('sudo', 'setfacl', 'getfacl'):
            with self.subTest(missing=missing), mock.patch.object(kvm.shutil, 'which',
                    side_effect=lambda name: None if name == missing else '/usr/bin/' + name), \
                    mock.patch.object(subprocess, 'run') as run:
                with self.assertRaisesRegex(kvm.Blocked, 'missing_' + missing):
                    kvm.Host().tools()
                run.assert_not_called()

    def test_device_boundary_rejects_symlink_regular_file_and_other_device(self):
        for mode, rdev in ((stat.S_IFLNK | 0o777, 0), (stat.S_IFREG | 0o660, 0),
                           (stat.S_IFCHR | 0o660, os.makedev(1, 3))):
            info = mock.Mock(st_mode=mode, st_rdev=rdev)
            with self.subTest(mode=mode), mock.patch.object(os, 'lstat', return_value=info):
                with self.assertRaisesRegex(kvm.Blocked, 'unexpected_kvm_device'):
                    kvm.Host().device()

    def test_missing_device_is_a_blocker(self):
        with mock.patch.object(os, 'lstat', side_effect=FileNotFoundError):
            with self.assertRaisesRegex(kvm.Blocked, 'missing_kvm'):
                kvm.Host().device()

    def test_cli_restoration_failure_is_nonzero_and_keeps_report(self):
        report = {'status': 'failed', 'errors': ['mock_restore_failed']}
        with mock.patch('sys.argv', ['kvm_access.py', 'restore']), \
                mock.patch.object(kvm, 'restore', return_value=report), \
                mock.patch.object(kvm, 'Path') as path, mock.patch('builtins.print'):
            self.assertEqual(1, kvm.main())
            path.return_value.__truediv__.assert_called_with('kvm-restoration.json')
            saved = path.return_value.__truediv__.return_value.write_text.call_args.args[0]
            self.assertEqual(report, json.loads(saved))
            self.assertNotIn(ORIGINAL, saved)
            self.assertLess(len(saved), 4096)

    def test_cli_blocker_keeps_numeric_diagnostics_without_raw_acl(self):
        with mock.patch('sys.argv', ['kvm_access.py', 'acquire']), \
                mock.patch.object(kvm, 'Host', return_value=FakeHost()), \
                mock.patch.object(kvm, 'acquire', side_effect=kvm.Blocked('explicit_approval_required')), \
                mock.patch.object(kvm, 'Path') as path, mock.patch('builtins.print'):
            self.assertEqual(1, kvm.main())
            saved = path.return_value.__truediv__.return_value.write_text.call_args.args[0]
            report = json.loads(saved)
            self.assertEqual(1001, report['runner_uid'])
            self.assertEqual(232, report['device']['minor'])
            self.assertEqual(['explicit_approval_required'], report['errors'])
            self.assertNotIn(ORIGINAL, saved)
            self.assertLess(len(saved), 4096)

    def test_cli_verified_restoration_is_zero(self):
        with mock.patch('sys.argv', ['kvm_access.py', 'restore']), \
                mock.patch.object(kvm, 'restore', return_value={'status': 'verified', 'errors': []}), \
                mock.patch.object(kvm, 'Path'):
            self.assertEqual(0, kvm.main())

    def test_effective_and_real_uid_must_match(self):
        with mock.patch.object(os, 'getuid', return_value=1001), \
                mock.patch.object(os, 'geteuid', return_value=0):
            with self.assertRaisesRegex(kvm.Blocked, 'unexpected_effective_uid'):
                kvm.Host().uid()


if __name__ == '__main__':
    unittest.main()
