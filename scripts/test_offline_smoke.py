"""Host-only guards: these do NOT claim Android compilation or emulator success."""
import pathlib
import json
import re
import sys
import tempfile
import unittest
from unittest import mock
import verify_offline_apks
import xml.etree.ElementTree as ET
from verify_offline_apks import ANDROID_NAMESPACE, APPLICATION_ID, HOST, verify_dumps
from verify_smoke_results import EXPECTED, verify_results

ROOT = pathlib.Path(__file__).resolve().parents[1]


class OfflineSmokeGuards(unittest.TestCase):
    def dumps(self, role="target"):
        package = APPLICATION_ID + (".test" if role == "test" else "")
        result = dict(role=role, permissions=f"package: {package}\n",
                    badging=f"package: name='{package}'\nsdkVersion:'35'\ntargetSdkVersion:'37'\n",
                    manifest=f'N: android={ANDROID_NAMESPACE} (line=1)\n'
                             f'E: manifest (line=1)\n  A: package="{package}"\n'
                             f'  E: application (line=2)\n'
                             f'    A: android:name(0x01010003)="android.app.Application"\n'
                             f'    E: activity (line=3)\n'
                             f'      A: android:name(0x01010003)="{HOST}"\n'
                             f'    E: provider (line=4)\n'
                             f'      A: android:name(0x01010003)="androidx.core.content.FileProvider"\n'
                             f'      A: android:authorities(0x01010018)="{APPLICATION_ID}.smoke-fixtures"\n')
        if role == "test":
            result["manifest"] = (
                f'N: android={ANDROID_NAMESPACE} (line=1)\n'
                f'  E: manifest (line=1)\n    A: package="{package}" (Raw: "{package}")\n'
                '      E: uses-sdk (line=2)\n        A: android:minSdkVersion(0x0101020c)=35\n'
                '        A: android:targetSdkVersion(0x01010270)=37\n'
                '      E: instrumentation (line=3)\n'
                '        A: android:name(0x01010003)="androidx.test.runner.AndroidJUnitRunner"\n'
                f'        A: android:targetPackage(0x01010021)="{APPLICATION_ID}"\n'
                '      E: application (line=4)\n        A: android:debuggable(0x0101000f)=true\n'
            )
        return result

    def expanded_dumps(self, role="target"):
        # Sanitized shape of aapt2 36.0.0 output in run 38232632130, API37.
        args = self.dumps(role)
        args["badging"] = args["badging"].replace("sdkVersion:'35'", "minSdkVersion:'35'")
        args["manifest"] = args["manifest"].replace("A: android:", "A: " + ANDROID_NAMESPACE + ":")
        return args

    def test_expanded_android_namespace_from_actual_aapt2_format(self):
        for role in ("target", "test"):
            args = self.expanded_dumps(role)
            self.assertEqual(APPLICATION_ID + (".test" if role == "test" else ""),
                             verify_dumps(**args))
        # An explicitly declared alias is equivalent only when its URI is exact.
        args = self.dumps()
        args["manifest"] = args["manifest"].replace("N: android=", "N: sdk=").replace("A: android:", "A: sdk:")
        verify_dumps(**args)

    def test_impostor_attribute_namespaces_and_rebindings_fail(self):
        for namespace in ("https://schemas.android.com/apk/res/android",
                          ANDROID_NAMESPACE + ".impostor", "http://impostor.invalid/android",
                          "android", "foreign"):
            args = self.expanded_dumps()
            args["manifest"] = args["manifest"].replace("A: " + ANDROID_NAMESPACE + ":",
                                                        "A: " + namespace + ":")
            if namespace == "android":
                args["manifest"] = args["manifest"].replace("N: android=" + ANDROID_NAMESPACE,
                                                            "N: android=http://impostor.invalid")
            with self.subTest(namespace=namespace), self.assertRaises(ValueError):
                verify_dumps(**args)
        args = self.dumps()
        args["manifest"] = args["manifest"].split("\n", 1)[1]  # An unbound prefix is ambiguous.
        with self.assertRaises(ValueError):
            verify_dumps(**args)
        args = self.dumps()
        args["manifest"] = "N: sdk=http://impostor.invalid\nN: sdk=" + ANDROID_NAMESPACE + "\n" + args["manifest"]
        with self.assertRaises(ValueError):
            verify_dumps(**args)

    def test_expanded_and_prefixed_duplicate_attributes_fail(self):
        for namespace in (ANDROID_NAMESPACE, "android"):
            args = self.expanded_dumps()
            original = f'    A: {ANDROID_NAMESPACE}:name(0x01010003)="android.app.Application"'
            duplicate = f'    A: {namespace}:name(0x01010003)="android.app.Application"'
            args["manifest"] = args["manifest"].replace(original, original + "\n" + duplicate)
            with self.subTest(namespace=namespace), self.assertRaises(ValueError):
                verify_dumps(**args)

    def test_expanded_names_still_require_exact_element_identity(self):
        for identity in ("android.app.Application", HOST, "androidx.core.content.FileProvider",
                         APPLICATION_ID + ".smoke-fixtures"):
            args = self.expanded_dumps()
            args["manifest"] = args["manifest"].replace('="' + identity + '"', '="impostor"')
            args["manifest"] += f'      E: meta-data (line=6)\n        A: {ANDROID_NAMESPACE}:name="{identity}"\n'
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                verify_dumps(**args)
        args = self.expanded_dumps()
        args["manifest"] += "    E: receiver (line=6)\n"
        with self.assertRaises(ValueError):
            verify_dumps(**args)

    def test_both_apk_dumps_are_retained_before_a_validation_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            for role in ("target", "test"):
                (root / f"{role}.apk").write_bytes(b"synthetic APK bytes")
            reports = root / "reports"
            def aapt2(args, **kwargs):
                role = pathlib.Path(args[-1]).stem
                dumps = self.expanded_dumps(role)
                if role == "target":
                    dumps["manifest"] += "    E: receiver (line=6)\n"
                kind = "manifest" if args[2] == "xmltree" else args[2]
                return mock.Mock(stdout=dumps[kind])
            argv = ["verify_offline_apks.py", "--aapt2", str(root / "aapt2"),
                    "--target", str(root / "target.apk"), "--test", str(root / "test.apk"),
                    "--reports", str(reports)]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(
                    verify_offline_apks.subprocess, "run", side_effect=aapt2) as commands:
                with self.assertRaisesRegex(ValueError, "Unexpected startup/production component"):
                    verify_offline_apks.main()
            self.assertEqual(6, commands.call_count)
            for role in ("target", "test"):
                for kind in ("permissions", "badging", "manifest"):
                    self.assertTrue((reports / f"{role}-{kind}.txt").is_file())
            self.assertFalse((reports / "apk-verification.json").exists())

    def test_current_minimum_sdk_field_and_duplicate_rejection(self):
        args = self.dumps()
        args["badging"] = args["badging"].replace("sdkVersion:'35'", "minSdkVersion:'35'")
        verify_dumps(**args)
        args["badging"] += "sdkVersion:'35'\n"
        with self.assertRaises(ValueError):
            verify_dumps(**args)

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
        return "\n".join(lines + ["OK (11 tests)", "INSTRUMENTATION_CODE: -1"])

    def test_all_expected_cases_are_required(self):
        self.assertEqual(11, verify_results(self.result())["test_count"])
        for source in ("", self.result().replace("OK (11 tests)", "OK (10 tests)"),
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
        self.assertIn("(inputs.api_scope == '37' || inputs.api_scope == '35-and-37')", source)
        self.assertIn("default: '35-and-37'", source)
        matrix = source.split("        include: ", 1)[1].splitlines()[0]
        choices = re.findall(r"'(\[\{.*?\}\])'", matrix)
        self.assertEqual(2, len(choices))
        single, pair = map(json.loads, choices)
        self.assertEqual([37], [row['api'] for row in single])
        self.assertEqual([37, 35], [row['api'] for row in pair])
        self.assertEqual(single[0], pair[0])
        for row in pair:
            level = '37.0' if row['api'] == 37 else '35'
            self.assertEqual(f'system-images;android-{level};google_apis;x86_64', row['image'])
            self.assertEqual(f'android-{level}/google_apis/x86_64', row['image_dir'])
        self.assertIn('python3 scripts/test_install_termination.py', source)
        self.assertIn("'install-termination.json'", source)
        self.assertIn('runs-on: ubuntu-24.04', source)
        self.assertIn("kvm-diagnostics.json", source)
        self.assertIn("kvm-restoration.json", source)
        self.assertIn("default: 'default'", source)
        self.assertIn("(inputs.install_transport == 'no-streaming' && inputs.api_scope == '37')", source)
        self.assertIn('INSTALL_TRANSPORT: ${{ inputs.install_transport }}', source)
        self.assertIn('--transport "$INSTALL_TRANSPORT"', source)
        self.assertNotIn('--transport ${{', source)
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
        self.assertLess(source.index("verify_offline_apks.py"), source.index('install_offline_apks.py'))
        self.assertNotIn("connectedSmokeAndroidTest", source)  # No rebuild after APK verification.


if __name__ == "__main__":
    unittest.main()
