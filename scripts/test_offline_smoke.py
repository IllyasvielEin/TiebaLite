"""Host-only guards: these do NOT claim Android compilation or emulator success."""
import pathlib
import re
import unittest
import xml.etree.ElementTree as ET
from verify_offline_apks import APPLICATION_ID, HOST, verify_dumps
from verify_smoke_results import EXPECTED, verify_results

ROOT = pathlib.Path(__file__).resolve().parents[1]


class OfflineSmokeGuards(unittest.TestCase):
    def dumps(self, role="target"):
        package = APPLICATION_ID + (".test" if role == "test" else "")
        return dict(role=role, permissions=f"package: {package}\n",
                    badging=f"package: name='{package}'\nsdkVersion:'35'\ntargetSdkVersion:'37'\n",
                    manifest=f'E: manifest (line=1)\n  A: package="{package}"\n'
                             f'  E: application (line=2)\n'
                             f'    A: android:name(0x01010003)="android.app.Application"\n'
                             f'    E: activity (line=3)\n'
                             f'      A: android:name(0x01010003)="{HOST}"\n'
                             f'    E: provider (line=4)\n'
                             f'      A: android:name(0x01010003)="androidx.core.content.FileProvider"\n'
                             f'      A: android:authorities(0x01010018)="{APPLICATION_ID}.smoke-fixtures"\n')

    def test_both_packaged_permissions_must_be_absent(self):
        for role in ("target", "test"):
            args = self.dumps(role)
            verify_dumps(**args)
            for key in ("permissions", "manifest"):
                modified = args.copy()
                modified[key] += "android.permission.INTERNET"
                with self.assertRaises(ValueError):
                    verify_dumps(**modified)

    def test_wrong_identity_or_background_component_fails(self):
        args = self.dumps()
        args["manifest"] += "    E: service (line=5)\n"
        with self.assertRaises(ValueError):
            verify_dumps(**args)
        args = self.dumps()
        args["badging"] = "package: name='wrong'"
        with self.assertRaises(ValueError):
            verify_dumps(**args)

    def test_manifest_identity_strings_in_other_elements_do_not_pass(self):
        for identity in ("android.app.Application", HOST, "androidx.core.content.FileProvider",
                         APPLICATION_ID + ".smoke-fixtures"):
            args = self.dumps()
            args["manifest"] = args["manifest"].replace('="' + identity + '"', '="impostor"')
            args["manifest"] += f'      E: meta-data (line=6)\n        A: android:name="{identity}"\n'
            with self.assertRaises(ValueError):
                verify_dumps(**args)
        for malformed in ("", "E: manifest\n E: manifest\n", "A: package=broken\n",
                          self.dumps()["manifest"].replace('="android.app.Application"', '=@0x123')):
            args = self.dumps()
            args["manifest"] = malformed
            with self.assertRaises(ValueError):
                verify_dumps(**args)

    def test_manifest_boundaries_are_smoke_only(self):
        namespace = "{http://schemas.android.com/tools}"
        android = "{http://schemas.android.com/apk/res/android}"
        for source in ("smoke", "androidTestSmoke"):
            root = ET.parse(ROOT / f"app/src/{source}/AndroidManifest.xml").getroot()
            for tag in ("uses-permission", "uses-permission-sdk-23"):
                self.assertTrue(any(p.get(android + "name") == "android.permission.INTERNET" and
                                    p.get(namespace + "node") == "remove" for p in root.findall(tag)))
        self.assertIn('android.permission.INTERNET',
                      (ROOT / "app/src/main/AndroidManifest.xml").read_text())

    def result(self):
        lines = []
        for cls, count in EXPECTED.items():
            for index in range(count):
                lines.extend([f"INSTRUMENTATION_STATUS: class=com.test.{cls}",
                              f"INSTRUMENTATION_STATUS: test=case{index}",
                              "INSTRUMENTATION_STATUS_CODE: 0"])
        return "\n".join(lines + ["OK (10 tests)", "INSTRUMENTATION_CODE: -1"])

    def test_all_expected_cases_are_required(self):
        self.assertEqual(10, verify_results(self.result())["test_count"])
        for source in ("", self.result().replace("OK (10 tests)", "OK (9 tests)"),
                       self.result().replace("STATUS_CODE: 0", "STATUS_CODE: -3", 1),
                       self.result().replace("CODE: -1", "CODE: 0")):
            with self.assertRaises(ValueError):
                verify_results(source)

    def test_runner_paths_are_evaluated_in_steps_not_job_env(self):
        source = (ROOT / ".github/workflows/emulator.yml").read_text()
        self.assertNotIn("runner.temp", source.split("    steps:", 1)[0])
        for name in ("ANDROID_USER_HOME", "ANDROID_EMULATOR_HOME", "ANDROID_AVD_HOME"):
            self.assertIn("printf '" + name + "=%s/", source)
        self.assertIn('>> "$GITHUB_ENV"', source)
        self.assertIn('rm -rf -- "$RUNNER_TEMP/offline-avd"', source)

    def test_workflow_security_and_order(self):
        source = (ROOT / ".github/workflows/emulator.yml").read_text()
        self.assertIn("workflow_dispatch:", source)
        self.assertIn("refs/heads/4.0-dev", source)
        self.assertIn("max-parallel: 1", source)
        self.assertEqual(['37', '35'], re.findall(r'^          - api: (\d+)$', source, re.M))
        self.assertIn('runs-on: ubuntu-24.04', source)
        self.assertIn("kvm-diagnostics.json", source)
        self.assertIn("kvm-restoration.json", source)
        self.assertIn("default: false", source)
        self.assertIn("type: boolean", source)
        self.assertIn("inputs.allow_kvm_access == true", source)
        self.assertIn("github.run_attempt == 1", source)
        self.assertIn("python3 scripts/test_kvm_access.py", source)
        self.assertLess(source.index("verify_offline_apks.py"), source.index("kvm_access.py acquire"))
        self.assertLess(source.index("kvm_access.py acquire"), source.index("-accel-check"))
        self.assertLess(source.index("-accel-check"), source.index("create avd"))
        self.assertLess(source.index("kill -KILL"), source.index("kvm_access.py restore"))
        self.assertLess(source.index("kvm_access.py restore"), source.index('rm -rf --'))
        restore_step = source.split("- name: Restore and verify", 1)[1].split("- name:", 1)[0]
        cleanup_step = source.split("- name: Remove disposable state", 1)[1].split("- name:", 1)[0]
        for step in (restore_step, cleanup_step):
            self.assertIn("always()", step)
            self.assertNotIn("continue-on-error", step)
        self.assertNotIn("kvm_access.py restore ||", source)
        self.assertIn("retention-days: 3", source)
        self.assertNotIn("secrets.", source)
        self.assertNotIn("chmod", source)
        self.assertNotIn("sudo", source)
        self.assertNotIn("pull_request", source)
        self.assertLess(source.index("verify_offline_apks.py"), source.index('install -t'))
        self.assertNotIn("connectedSmokeAndroidTest", source)  # No rebuild after APK verification.


if __name__ == "__main__":
    unittest.main()
