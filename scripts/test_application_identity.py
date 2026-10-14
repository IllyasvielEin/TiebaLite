"""Source-level application identity wiring; merged APK/device proof remains required."""
import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / 'app/src/main'
ANDROID = '{http://schemas.android.com/apk/res/android}'
APP_ID = 'io.github.illyasvielein.tiebalite'
NAMESPACE = 'com.huanchengfly.tieba.post'


class ApplicationIdentityChecks(unittest.TestCase):
    def test_version_properties_are_the_only_version_source(self):
        properties = dict(line.split('=', 1) for line in
                          (ROOT / 'application.properties').read_text().splitlines()
                          if line.strip() and not line.startswith('#'))
        self.assertEqual({'versionCode', 'versionName'}, set(properties))
        self.assertTrue(properties['versionCode'].isdigit())
        self.assertGreater(int(properties['versionCode']), 0)
        self.assertLessEqual(int(properties['versionCode']), 2100000000)
        self.assertRegex(properties['versionName'], r'^\d+\.\d+\.\d+$')
        build = (ROOT / 'app/build.gradle.kts').read_text()
        self.assertIn('val applicationVersionCode = appProperties.getProperty("versionCode").toInt()', build)
        self.assertIn('val applicationVersionName = appProperties.getProperty("versionName")', build)
        self.assertEqual(['applicationVersionCode'], re.findall(r'^\s*versionCode\s*=\s*(.+)$', build, re.M))
        self.assertEqual(['applicationVersionName'], re.findall(r'^\s*versionName\s*=\s*(.+)$', build, re.M))
        for obsolete in ('isPreRelease', 'preReleaseName', 'preReleaseVer', 'isPerVersion',
                         'versionNameSuffix', 'GITHUB_SHA', 'applicationVersionName +='):
            self.assertNotIn(obsolete, build)

    def test_self_build_flag_is_independent_of_version(self):
        build = (ROOT / 'app/build.gradle.kts').read_text()
        self.assertIn('val isCI: String? = System.getenv("CI")', build)
        self.assertIn('val isSelfBuild = isCI.isNullOrEmpty() || !isCI.equals("true", ignoreCase = true)', build)
        self.assertIn('manifestPlaceholders["is_self_build"] = "$isSelfBuild"', build)

    def test_application_id_and_namespace_are_separate(self):
        build = (ROOT / 'app/build.gradle.kts').read_text()
        self.assertIn(f'applicationId = "{APP_ID}"', build)
        self.assertIn(f'namespace = "{NAMESPACE}"', build)
        self.assertIn(f'assertEquals("{APP_ID}", appContext.getPackageName())',
                      (ROOT / 'app/src/androidTest/java/com/huanchengfly/tieba/post/ExampleInstrumentedTest.java').read_text())

    def test_shortcuts_target_this_package_and_existing_classes(self):
        intents = ET.parse(MAIN / 'res/xml/shortcut_new.xml').getroot().findall('shortcut/intent')
        self.assertEqual(4, len(intents))
        for intent in intents:
            self.assertEqual(APP_ID, intent.get(ANDROID + 'targetPackage'))
            target = intent.get(ANDROID + 'targetClass')
            if target:
                self.assertTrue(target.startswith(NAMESPACE + '.'))

    def test_label_and_vendor_client(self):
        strings = ET.parse(MAIN / 'res/values/strings.xml').getroot()
        self.assertEqual('贴吧 Lite', next(s.text for s in strings if s.get('name') == 'app_name'))
        self.assertEqual(APP_ID, json.loads((MAIN / 'assets/easygo.json').read_text())['client'])

    def test_provider_authorities_follow_application_id(self):
        providers = ET.parse(MAIN / 'AndroidManifest.xml').getroot().findall('application/provider')
        for provider in providers:
            self.assertTrue(provider.get(ANDROID + 'authorities', '').startswith('${applicationId}.'))
        image_util = (MAIN / 'java/com/huanchengfly/tieba/post/utils/ImageUtil.kt').read_text()
        self.assertIn('context.packageName + ".share.FileProvider"', image_util)

    def test_permission_buttons_do_not_require_final_resource_ids(self):
        source = (MAIN / 'java/com/huanchengfly/tieba/post/components/dialogs/PermissionDialog.java').read_text()
        click = source.split('public void onClick(View v)', 1)[1].split('public void show()', 1)[0]
        self.assertNotIn('case R.id.', click)
        allow, deny = click.split('} else if (v.getId() == R.id.permission_actions_denied) {')
        self.assertIn('if (v.getId() == R.id.permission_actions_allow)', allow)
        for block, callback, state in ((allow, 'onGranted', 'STATE_ALLOW'), (deny, 'onDenied', 'STATE_DENIED')):
            self.assertIn(f'.{callback}(checkBox.isChecked())', block)
            self.assertIn('if (checkBox.isChecked())', block)
            self.assertIn(state, block)
            self.assertIn('dismiss()', block)

    def test_source_button_links_to_this_fork(self):
        source = (MAIN / 'java/com/huanchengfly/tieba/post/ui/page/settings/about/AboutPage.kt').read_text()
        self.assertIn('https://github.com/IllyasvielEin/TiebaLite', source)


if __name__ == '__main__':
    unittest.main()
