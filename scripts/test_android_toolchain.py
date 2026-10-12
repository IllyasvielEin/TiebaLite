"""Pinned-source regressions; actual Gradle/Kotlin/Android compatibility requires CI."""
import hashlib
from pathlib import Path
import re
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'app/build.gradle.kts').read_text()
CAT = tomllib.loads((ROOT / 'gradle/libs.versions.toml').read_text())


class AndroidToolchainTests(unittest.TestCase):
    def test_reviewed_version_pins(self):
        for name, version in {'agp': '9.1.1', 'hilt': '2.59.2', 'kotlin': '2.3.21',
                              'ksp': '2.3.8', 'wire': '6.4.5'}.items():
            self.assertEqual(version, CAT['versions'][name])

    def test_complete_verified_wrapper(self):
        expected = '3b8a25775a69158b5ad2b1d17a80a88dc7b40a352a73eb27d06c612a7ce68e98'
        self.assertEqual(expected, hashlib.sha256((ROOT / 'gradle/wrapper/gradle-wrapper.jar').read_bytes()).hexdigest())
        self.assertEqual(expected, (ROOT / 'gradle/wrapper/gradle-wrapper.jar.sha256').read_text().split()[0])
        props = (ROOT / 'gradle/wrapper/gradle-wrapper.properties').read_text()
        self.assertIn('distributionUrl=https\\://services.gradle.org/distributions/gradle-9.8.1-bin.zip', props)
        self.assertIn('distributionSha256Sum=dce76f55f8e251a3a1f130eb120f30b3d271de2b76c9b0729d316b5a1b6dc01f', props)

    def test_builtin_kotlin_and_aligned_compiler_plugins(self):
        self.assertNotIn('org.jetbrains.kotlin.android', str(CAT['plugins']))
        self.assertNotIn('libs.plugins.kotlin.android', APP)
        self.assertIn('org.jetbrains.kotlin:kotlin-gradle-plugin:${libs.versions.kotlin.get()}',
                      (ROOT / 'build.gradle.kts').read_text())
        for name in ('kotlin-compose-compiler', 'kotlin-serialization', 'kotlin-parcelize'):
            self.assertEqual('kotlin', CAT['plugins'][name]['version']['ref'])
        for flag in ('android.builtInKotlin=false', 'android.newDsl=false', 'android.enableAppCompileTimeRClass=false'):
            self.assertNotIn(flag, (ROOT / 'gradle.properties').read_text())

    def test_supported_sdk_and_public_variant_api(self):
        for name, version in [('minSdk', 35), ('compileSdk', 37), ('targetSdk', 37)]:
            self.assertRegex(APP, rf'{name}\s*=\s*{version}\b')
        self.assertNotRegex(APP, r'\bmaxSdk\b')
        self.assertIn("android.nonFinalResIds=true", (ROOT / "gradle.properties").read_text())
        self.assertNotIn('applicationVariants', APP)
        self.assertNotIn('BaseVariantOutputImpl', APP)
        self.assertIn('beforeVariants(selector().all())', APP)
        self.assertIn('hostTests[HostTestBuilder.UNIT_TEST_TYPE]?.enable = true', APP)

    def test_explicit_legacy_constructor_retention(self):
        rules = (ROOT / 'app/proguard-rules.pro').read_text()
        for parent in ['android.app.Activity', 'android.app.Application', 'android.app.Service',
                       'android.content.BroadcastReceiver', 'android.content.ContentProvider',
                       'android.preference.Preference', 'com.bumptech.glide.module.AppGlideModule']:
            self.assertIn(f'-keep public class * extends {parent} {{ <init>(); }}', rules)
        self.assertIn('-keep public class * implements com.bumptech.glide.module.GlideModule { <init>(); }', rules)


if __name__ == '__main__':
    unittest.main()
