import subprocess
import tempfile
from pathlib import Path
import unittest
from ensure_android_sdk import ensure, packages


class AndroidSdkSetupTests(unittest.TestCase):
    def test_fixed_package_scopes(self):
        self.assertEqual(('platforms;android-37.0', 'build-tools;36.0.0', 'platform-tools'), packages('build'))
        self.assertIn('system-images;android-37.0;google_apis;x86_64', packages('emulator37'))
        self.assertIn('system-images;android-35;google_apis;x86_64', packages('emulator35'))
        with self.assertRaises(ValueError):
            packages('arbitrary;package')

    def test_missing_manager_fails_before_install(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(RuntimeError):
                ensure(root, 'build', lambda *a, **k: self.fail('must not execute'))

    def test_only_selected_packages_and_no_blanket_terms_or_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manager = root / 'cmdline-tools/latest/bin/sdkmanager'
            manager.parent.mkdir(parents=True)
            manager.write_text('fixture, never executed')
            manager.chmod(0o700)
            for name in ['platforms/android-37.0/android.jar', 'build-tools/36.0.0/aapt2',
                         'build-tools/36.0.0/apksigner', 'build-tools/36.0.0/zipalign', 'licenses/android-sdk-license']:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture')
            calls = []
            ensure(root, 'build', lambda *a, **k: calls.append((a, k)))
            self.assertEqual(1, len(calls))
            argv = calls[0][0][0]
            self.assertEqual(list(packages('build')), argv[4:])
            self.assertNotIn('--licenses', argv)
            self.assertEqual(True, calls[0][1]['check'])
            self.assertEqual(1200, calls[0][1]['timeout'])

    def test_install_failure_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            manager = Path(folder) / 'cmdline-tools/latest/bin/sdkmanager'
            manager.parent.mkdir(parents=True)
            manager.write_text('fixture')
            manager.chmod(0o700)
            def fail(*a, **k):
                raise subprocess.CalledProcessError(1, a[0])
            with self.assertRaises(subprocess.CalledProcessError):
                ensure(folder, 'build', fail)


if __name__ == '__main__':
    unittest.main()
