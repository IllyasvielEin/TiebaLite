#!/usr/bin/env python3
"""One approved first-attempt run; only /dev/kvm may receive a temporary ACL.

Real host access is confined to Host. Tests inject a fake Host and never touch KVM.
The saved ACL stays private, is validated, and is restored through stdin to a fixed
setfacl target. This deliberately does not use setfacl's multi-target restore mode.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess

DEVICE = '/dev/kvm'
RUNNER_UID = 1001
STATE_NAME = 'offline-kvm-state'
ORIGINAL = 'original.acl'
METADATA = 'metadata.json'
BASE_ACL = (('user', '', 'rw-'), ('group', '', 'rw-'), ('other', '', '---'))
GRANTED_ACL = BASE_ACL + (('user', '1001', 'rw-'), ('mask', '', 'rw-'))


class Blocked(RuntimeError):
    """A fixed, non-sensitive diagnostic code suitable for a small CI report."""


def require(condition, code):
    if not condition:
        raise Blocked(code)


def parse_acl(text):
    """Accept a single numeric access ACL for exactly /dev/kvm, no defaults/flags."""
    require(isinstance(text, str) and len(text) <= 4096, 'invalid_acl_size')
    lines = text.strip().splitlines()
    require(len(lines) >= 6 and lines[0] == '# file: /dev/kvm', 'invalid_acl_target')
    require(re.fullmatch(r'# owner: [0-9]+', lines[1]) is not None and
            re.fullmatch(r'# group: [0-9]+', lines[2]) is not None, 'nonnumeric_acl_owner')
    entries = []
    for line in lines[3:]:
        match = re.fullmatch(r'(user|group|mask|other):([0-9]*):([r-][w-][x-])'
                            r'(?:\s+#effective:[r-][w-][x-])?', line)
        require(match is not None, 'invalid_acl_entry')
        kind, identity, permissions = match.groups()
        require(not identity or kind in ('user', 'group'), 'invalid_acl_identity')
        require((kind, identity) not in [(e[0], e[1]) for e in entries], 'duplicate_acl_entry')
        entries.append((kind, identity, permissions))
    require(all((kind, '') in [(e[0], e[1]) for e in entries]
                for kind in ('user', 'group', 'other')), 'incomplete_acl')
    return int(lines[1].split(': ')[1]), int(lines[2].split(': ')[1]), tuple(sorted(entries))


class Host:
    """The only real device/privileged operations. All commands have fixed targets."""
    def uid(self):
        require(os.getuid() == os.geteuid(), 'unexpected_effective_uid')
        return os.getuid()

    def groups(self):
        return sorted(os.getgroups())

    def device(self):
        try:
            info = os.lstat(DEVICE)
        except FileNotFoundError as exc:
            raise Blocked('missing_kvm') from exc
        require(stat.S_ISCHR(info.st_mode) and os.major(info.st_rdev) == 10 and
                os.minor(info.st_rdev) == 232, 'unexpected_kvm_device')
        require(info.st_uid == 0 and not info.st_mode & 0o7000, 'unexpected_kvm_owner_or_flags')
        return {key: int(value) for key, value in dict(
            dev=info.st_dev, ino=info.st_ino, rdev=info.st_rdev, uid=info.st_uid,
            gid=info.st_gid, mode=stat.S_IMODE(info.st_mode), major=10, minor=232).items()}

    def access(self):
        return os.access(DEVICE, os.R_OK) and os.access(DEVICE, os.W_OK)

    def tools(self):
        # No package/utility installs or interactive password prompts are permitted.
        for name in ('getfacl', 'setfacl', 'sudo'):
            require(shutil.which(name) is not None, 'missing_' + name)

    def command(self, args, text=None):
        try:
            return subprocess.run(args, input=text, text=True, check=True,
                                  capture_output=True, timeout=20).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            # Never publish raw command output, ACL snapshots or environment details.
            raise Blocked('kvm_command_failed') from exc

    def acl(self):
        return self.command(['getfacl', '-n', '-p', '--', DEVICE])

    def grant(self):
        self.command(['sudo', '-n', 'setfacl', '-m', 'u:1001:rw', DEVICE])

    def restore(self, acl):
        # Validated bytes go over stdin: privileged code never opens a user-state path.
        self.command(['sudo', '-n', 'setfacl', '--set-file=-', DEVICE], acl)


def safe_directories(path):
    """Reject symlinks in every ancestor, including RUNNER_TEMP itself."""
    require(path.is_absolute() and '..' not in path.parts, 'invalid_state_path')
    for directory in reversed((path, *path.parents)):
        info = directory.lstat()
        require(stat.S_ISDIR(info.st_mode), 'unsafe_state_directory')


def private_directory(path):
    safe_directories(path)
    info = path.lstat()
    require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
            'nonprivate_state_directory')


def write_private(path, text):
    # O_EXCL and O_NOFOLLOW also reject pre-existing files, hardlinks and symlinks.
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                           0o600), 'w', encoding='ascii') as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())


def read_private(path):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'r', encoding='ascii') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and
                stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1 and
                info.st_size <= 4096, 'unsafe_state_file')
        return stream.read(4097)


def binding(env):
    require(re.fullmatch(r'[1-9][0-9]*', env.get('GITHUB_RUN_ID', '')) is not None,
            'invalid_run_id')
    require(env.get('SMOKE_API') in ('35', '37'), 'unexpected_matrix_api')
    return {'run_id': env['GITHUB_RUN_ID'], 'api': env['SMOKE_API'], 'attempt': '1'}


def approved(env, host):
    require(env.get('ALLOW_KVM_ACCESS') == 'true', 'explicit_approval_required')
    require(env.get('GITHUB_RUN_ATTEMPT') == '1', 'fresh_dispatch_required')
    require(env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch' and
            env.get('GITHUB_REF') == 'refs/heads/4.0-dev' and
            env.get('DEFAULT_BRANCH') == '4.0-dev', 'untrusted_workflow_context')
    require(host.uid() == RUNNER_UID, 'unexpected_runner_uid')
    binding(env)


def state_path(env):
    require(bool(env.get('RUNNER_TEMP')), 'missing_runner_temp')
    parent = Path(env['RUNNER_TEMP'])
    safe_directories(parent)
    return parent / STATE_NAME


def diagnostics(host):
    return {'runner_uid': host.uid(), 'runner_groups': host.groups(),
            'device': host.device(), 'read_write': host.access()}


def acquire(env, host):
    approved(env, host)
    host.tools()
    device = host.device()
    path = state_path(env)
    require(not path.exists() and not path.is_symlink(), 'existing_state')
    if host.access():
        return {'status': 'existing_access', **diagnostics(host)}
    original = host.acl()
    owner, group, entries = parse_acl(original)
    # An extended original ACL could have masked rights broadened by setfacl.
    # Only the observed simple root:kvm 0660 baseline is eligible for a grant.
    require(owner == device['uid'] == 0 and group == device['gid'] and
            device['mode'] == 0o660 and entries == tuple(sorted(BASE_ACL)),
            'unexpected_original_acl')
    path.mkdir(mode=0o700)
    private_directory(path)
    write_private(path / ORIGINAL, original)
    metadata = {'version': 1, **binding(env), 'device': device,
                'acl_sha256': hashlib.sha256(original.encode('ascii')).hexdigest()}
    write_private(path / METADATA, json.dumps(metadata, sort_keys=True) + '\n')
    # Snapshot is durable BEFORE any permission change, including a partial failure.
    require(host.device() == device, 'kvm_changed_before_grant')
    host.grant()
    granted = host.device()
    require(all(granted[k] == v for k, v in device.items() if k != 'mode'),
            'kvm_changed_during_grant')
    require(parse_acl(host.acl()) == (owner, group, tuple(sorted(GRANTED_ACL))),
            'unexpected_granted_acl')
    require(host.access(), 'kvm_still_inaccessible')
    return {'status': 'temporary_access', **diagnostics(host)}


def remove_state(path):
    if not path.exists() and not path.is_symlink():
        return
    private_directory(path)
    require({p.name for p in path.iterdir()} <= {ORIGINAL, METADATA}, 'unexpected_state_file')
    for name in (ORIGINAL, METADATA):
        file = path / name
        if file.exists() or file.is_symlink():
            read_private(file)  # Reject symlinks/hardlinks before unlinking anything.
    for name in (ORIGINAL, METADATA):
        (path / name).unlink(missing_ok=True)
    path.rmdir()


def restore(env, host):
    """Always attempt rollback and private-state cleanup; preserve each failure code."""
    report = {'status': 'not_needed', 'errors': []}
    path = None
    try:
        path = state_path(env)
        if path.exists() or path.is_symlink():
            require(host.uid() == RUNNER_UID, 'unexpected_runner_uid')
            require(env.get('GITHUB_RUN_ATTEMPT') == '1', 'fresh_dispatch_required')
            private_directory(path)
            original = read_private(path / ORIGINAL)
            metadata = json.loads(read_private(path / METADATA))
            require(set(metadata) == {'version', 'run_id', 'api', 'attempt', 'device', 'acl_sha256'}
                    and metadata['version'] == 1 and
                    all(metadata.get(k) == v for k, v in binding(env).items()), 'invalid_state_binding')
            require(hashlib.sha256(original.encode('ascii')).hexdigest() == metadata['acl_sha256'],
                    'changed_acl_snapshot')
            owner, group, entries = parse_acl(original)
            device = host.device()
            saved = metadata['device']
            require(isinstance(saved, dict) and set(saved) == set(device) and
                    all(type(value) is int for value in saved.values()) and
                    all(device[k] == v for k, v in saved.items() if k != 'mode') and
                    saved['mode'] == 0o660 and owner == device['uid'] == 0 and
                    group == device['gid'] and entries == tuple(sorted(BASE_ACL)),
                    'invalid_saved_device_or_acl')
            host.tools()
            host.restore(original)
            require(host.device() == saved and host.acl() == original,
                    'restoration_verification_failed')
            # Compare exact numeric getfacl output AND device mode/identity.
            report.update(status='verified', device=host.device(), read_write=host.access())
    except (Blocked, OSError, ValueError, TypeError, KeyError) as exc:
        report['errors'].append(str(exc) if isinstance(exc, Blocked) else 'invalid_or_unreadable_state')
    finally:
        if path is not None:
            try:
                remove_state(path)
            except (Blocked, OSError, ValueError) as exc:
                report['errors'].append(str(exc) if isinstance(exc, Blocked) else 'state_cleanup_failed')
        if report['errors']:
            report['status'] = 'failed'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'acquire', 'restore'))
    args = parser.parse_args()
    host = Host()
    report = {}
    try:
        if args.action == 'restore':
            report = restore(os.environ, host)
        elif args.action == 'acquire':
            report = acquire(os.environ, host)
        else:
            report = {'status': 'device_checked', **diagnostics(host)}
    except (Blocked, OSError, ValueError) as exc:
        report = {'status': 'failed', 'errors': [str(exc) if isinstance(exc, Blocked)
                                                else 'kvm_check_failed']}
        try:
            report.update(diagnostics(host))
        except (Blocked, OSError, ValueError):
            pass  # Missing/invalid devices have no safe numeric device record.
    destination = Path('out/smoke-reports')
    destination.mkdir(parents=True, exist_ok=True)
    filename = 'kvm-restoration.json' if args.action == 'restore' else 'kvm-diagnostics.json'
    (destination / filename).write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    if report['status'] == 'failed':
        print('::error::KVM ' + args.action + ' failed; see ' + filename)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
