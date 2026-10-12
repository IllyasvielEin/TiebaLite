#!/usr/bin/env python3
"""Exercise inline signing code using inert bytes and mock tools, never real keys."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / '.github/workflows/build.yml').read_text()
CERT = 'a' * 64


def inline(label):
    return '\n'.join(
        line[10:] for line in WORKFLOW.split("<<'" + label + "'\n", 1)[1].split('          ' + label, 1)[0].splitlines())


class SigningWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(os.environ, RUNNER_TEMP=str(self.root), ANDROID_HOME=str(self.root / 'sdk'),
            EXPECTED_ARTIFACT_ID='42', EXPECTED_CERT_SHA256=CERT,
            GITHUB_SHA='b' * 40, GITHUB_REPOSITORY='example/project', GITHUB_RUN_ID='123',
            GITHUB_RUN_ATTEMPT='2', ANDROID_KEYSTORE_BASE64=base64.b64encode(b'inert mock bytes').decode(),
            ANDROID_KEYSTORE_PASSWORD='fake-password-never-log', ANDROID_KEY_ALIAS='mock-alias',
            ANDROID_KEY_PASSWORD='fake-password-never-log')
        self.input = self.root / 'unsigned-input'
        self.input.mkdir()
        self.metadata = dict(commit=self.env['GITHUB_SHA'], repository='example/project', run_id='123',
            run_attempt='2', working_tree_dirty=False, signing='unsigned',
            artifact_label='UNSIGNED-EXPERIMENTAL-not-login-validated', build_tools='36.0.0')
        (self.input / 'release-4.0.0-beta.2+914635f(390100).apk').write_bytes(b'inert APK fixture')
        (self.input / 'README.txt').write_text('experimental')
        (self.input / 'output-metadata.json').write_text(json.dumps({'artifactType': {'type': 'APK'},
            'elements': [{'outputFile': 'release-4.0.0-beta.2+914635f(390100).apk', 'filters': []}]}))
        self.write_metadata()

    def write_metadata(self):
        (self.input / 'build-metadata.json').write_text(json.dumps(self.metadata))
        (self.input / 'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest() +
            '  ' + p.name + '\n' for p in sorted(self.input.iterdir()) if p.name != 'SHA256SUMS'))

    def validate(self):
        with patch.dict(os.environ, self.env, clear=True):
            exec(compile(inline('PY_VALIDATE'), '<workflow validation>', 'exec'), {})

    def test_valid_artifact_and_colon_certificate(self):
        self.env['EXPECTED_CERT_SHA256'] = ':'.join(['AA'] * 32)
        self.validate()
        data = json.loads((self.root / 'signing-work/source.json').read_text())
        self.assertEqual(data['certificate_sha256'], CERT)
        self.assertEqual(data['unsigned_artifact_id'], '42')

    def test_source_run_signing_and_toolchain_mismatches_fail_closed(self):
        for field, value in [('commit', 'c' * 40), ('repository', 'other/repo'), ('run_id', '1'),
                             ('run_attempt', '1'), ('working_tree_dirty', True),
                             ('signing', 'signed'), ('build_tools', '35.0.0')]:
            with self.subTest(field=field):
                old = self.metadata[field]
                self.metadata[field] = value
                self.write_metadata()
                with self.assertRaises(SystemExit):
                    self.validate()
                self.metadata[field] = old

    def test_tampered_apk_rejected(self):
        (self.input / 'release-4.0.0-beta.2+914635f(390100).apk').write_bytes(b'tampered')
        with self.assertRaises(SystemExit):
            self.validate()

    def test_unexpected_or_symlinked_files_rejected(self):
        for name in ['injected.py', 'second.apk']:
            extra = self.input / name
            extra.write_text('not executable')
            with self.assertRaises(SystemExit):
                self.validate()
            extra.unlink()
        (self.input / 'mapping.txt').symlink_to(self.input / 'README.txt')
        with self.assertRaises(SystemExit):
            self.validate()

    def test_missing_or_invalid_certificate_rejected(self):
        for cert in ['', 'ab', 'g' * 64]:
            self.env['EXPECTED_CERT_SHA256'] = cert
            with self.assertRaises(SystemExit):
                self.validate()

    def mock_signer(self):
        path = self.root / 'sdk/build-tools/36.0.0/apksigner'
        path.parent.mkdir(parents=True)
        path.write_text('''#!/usr/bin/env python3
import os, sys
from pathlib import Path
args = sys.argv[1:]
if args[0] == 'sign':
    assert args[args.index('--ks-type') + 1] == 'PKCS12'
    assert args[args.index('--ks-pass') + 1] == 'env:ANDROID_KEYSTORE_PASSWORD'
    assert args[args.index('--key-pass') + 1] == 'env:ANDROID_KEY_PASSWORD'
    key = Path(args[args.index('--ks') + 1])
    assert key.stat().st_mode & 0o777 == 0o600
    assert key.parent.stat().st_mode & 0o777 == 0o700
    assert os.environ['ANDROID_KEYSTORE_PASSWORD'] not in args
    if os.environ.get('MOCK_SIGN_FAIL'):
        print(os.environ['ANDROID_KEYSTORE_PASSWORD'], file=sys.stderr)
        sys.exit(1)
    Path(args[args.index('--out') + 1]).write_bytes(b'mock signed APK')
else:
    print('Signer #1 certificate SHA-256 digest: ' + os.environ.get('MOCK_CERT', 'a' * 64))
''')
        path.chmod(0o700)

    def sign(self):
        self.validate()
        self.mock_signer()
        body = WORKFLOW.split("          set -euo pipefail\n          umask 077\n", 1)[1]
        body = body.split('\n      - name: Remove temporary signing material', 1)[0]
        body = '\n'.join(line[10:] for line in body.splitlines())
        return subprocess.run(['bash', '-euo', 'pipefail', '-c', 'umask 077\n' + body],
                              env=self.env, capture_output=True, text=True)

    def test_mock_sign_success_only_allowlisted_public_outputs(self):
        result = self.sign()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / 'signing-private').exists())
        output = self.root / 'signed-output'
        self.assertEqual({p.name for p in output.iterdir()}, {
            'experimental-not-login-validated.apk', 'SHA256SUMS', 'signing-metadata.json'})
        raw = (output / 'signing-metadata.json').read_text()
        self.assertNotIn(self.env['ANDROID_KEYSTORE_PASSWORD'], raw)
        self.assertEqual(json.loads(raw)['full_lint_status'], 'passed')

    def test_sign_failure_cleans_key_and_suppresses_tool_errors(self):
        self.env['MOCK_SIGN_FAIL'] = '1'
        result = self.sign()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(self.env['ANDROID_KEYSTORE_PASSWORD'], result.stdout + result.stderr)
        self.assertFalse((self.root / 'signing-private').exists())

    def test_missing_secret_fails_without_key_material(self):
        self.env['ANDROID_KEY_PASSWORD'] = ''
        result = self.sign()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'signing-private').exists())
        self.assertFalse((self.root / 'signed-output').exists())

    def test_invalid_base64_cleans_private_directory(self):
        self.env['ANDROID_KEYSTORE_BASE64'] = 'invalid!?'
        result = self.sign()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'signing-private').exists())

    def test_wrong_certificate_fails_and_cleans_key(self):
        self.env['MOCK_CERT'] = 'c' * 64
        result = self.sign()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'signing-private').exists())
        self.assertFalse((self.root / 'signed-output/signing-metadata.json').exists())

    def test_isolated_job_security_invariants(self):
        job = WORKFLOW.split('\n  sign:\n', 1)[1]
        self.assertIn('default: false', WORKFLOW)
        for required in ["needs.build.result == 'success'", "github.event_name == 'workflow_dispatch'",
                         'inputs.sign_apk == true', "github.ref == 'refs/heads/4.0-dev'",
                         "github.event.repository.default_branch == '4.0-dev'", 'permissions: {}',
                         'digest-mismatch: error', "if: ${{ always() }}", 'retention-days: 3']:
            self.assertIn(required, job)
        self.assertNotIn('uses: actions/checkout', job)
        self.assertNotIn('./gradlew', job)
        self.assertNotIn('gradle/actions/', job)
        self.assertNotIn('sdkmanager', job)
        self.assertIn('actions/setup-java@b6effb05e454b25005698d916606bdc6ffcbf961', job)
        self.assertIn("java-version: '17.0.20+8'", job)
        self.assertIn('for tool in apksigner zipalign', job)
        self.assertNotIn('github-token:', job)
        self.assertNotIn('run-id:', job)
        self.assertEqual(WORKFLOW.count('${{ secrets.'), 4)
        self.assertEqual(job.count('${{ secrets.'), 4)
        self.assertRegex(job, r'actions/download-artifact@[0-9a-f]{40}')
        self.assertIn('Full Android lint (blocking quality gate)', WORKFLOW.split('\n  sign:\n')[0])


if __name__ == '__main__':
    unittest.main()
