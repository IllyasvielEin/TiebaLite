"""Source/XML regression checks; not a substitute for Android/JVM/runtime tests."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

MAIN = Path(__file__).resolve().parents[2] / 'main'
JAVA = MAIN / 'java/com/huanchengfly/tieba/post'
ANDROID = '{http://schemas.android.com/apk/res/android}'
TOOLS = '{http://schemas.android.com/tools}'


class PrivacyBoundaryChecks(unittest.TestCase):
    def test_all_backup_modes_exclude_sessions(self):
        legacy = ET.parse(MAIN / 'res/xml/backup_descriptor.xml').getroot()
        modern = ET.parse(MAIN / 'res/xml/data_extraction_rules.xml').getroot()
        expected = {('database', 'tblite.db' + suffix) for suffix in ('', '-wal', '-shm', '-journal')}
        expected.add(('root', 'app_webview'))
        manifest = ET.parse(MAIN / 'AndroidManifest.xml').getroot()
        # This app currently has one applicationId for both debug/release. Fail if that changes.
        gradle = (MAIN.parents[1] / 'build.gradle.kts').read_text()
        self.assertIn('applicationId = "io.github.illyasvielein.tiebalite"', gradle)
        self.assertNotIn('applicationIdSuffix', gradle)
        for service in manifest.find('application').findall('service'):
            process = service.get(ANDROID + 'process')
            if process:
                name = 'io.github.illyasvielein.tiebalite' + process if process.startswith(':') else process
                expected.add(('root', 'app_webview_' + name))
        for mode in (legacy, modern.find('cloud-backup'), modern.find('device-transfer')):
            actual = {(node.get('domain'), node.get('path')) for node in mode.findall('exclude')}
            self.assertTrue(expected <= actual)
            self.assertFalse(any(path == '.' for _, path in actual), 'Keep unrelated user backups')

    def test_install_permission_absent_and_shortcut_preserved(self):
        root = ET.parse(MAIN / 'AndroidManifest.xml').getroot()
        permissions = [node.get(ANDROID + 'name') for node in root.findall('uses-permission')]
        self.assertNotIn('android.permission.REQUEST_INSTALL_PACKAGES', permissions)
        activities = root.find('application').findall('activity')
        sign = next(a for a in activities if a.get(ANDROID + 'name') == '.activities.OKSignActivity')
        self.assertEqual('true', sign.get(ANDROID + 'exported'))
        source = (JAVA / 'activities/OKSignActivity.java').read_text()
        self.assertEqual(1, source.count('TiebaUtil.startSign(this);'))
        positive = source.split('.setPositiveButton(', 1)[1].split('.setNegativeButton(', 1)[0]
        self.assertIn('TiebaUtil.startSign(this);', positive)
        self.assertIn('.setOnCancelListener(ignored -> finish())', source)
        self.assertIn('setFilterTouchesWhenObscured(true)', source)

    def test_event_logs_never_interpolate_payloads(self):
        source = (JAVA / 'arch/BaseViewModel.kt').read_text()
        for variable in ('it', 'event', 'intent'):
            self.assertIn('${' + variable + '.javaClass.simpleName}', source)
        self.assertNotIn('Log.i("ReplyPage", "collect: $it")', (JAVA / 'ui/page/reply/ReplyPage.kt').read_text())
        account = (JAVA / 'models/database/Account.kt').read_text()
        self.assertIn('override fun toString(): String = "Account(id=$id, credentials=[REDACTED])"', account)

    def test_web_navigation_uses_exact_host_and_scheme_helpers(self):
        web = (JAVA / 'ui/page/webview/WebViewPage.kt').read_text()
        launch = (JAVA / 'utils/utils.kt').read_text()
        self.assertIn('val isHttp = TrustedWebHosts.isWebScheme(scheme)', web)
        self.assertIn('fun isInternalHost(host: String): Boolean = TrustedWebHosts.isInternalHost(host)', web)
        self.assertIn('TrustedWebHosts.isWebScheme(scheme) && TrustedWebHosts.isInternalHost(host)', launch)
        for source in (web, launch):
            for host in ('tieba.baidu.com', 'wappass.baidu.com', 'ufosdk.baidu.com', 'm.help.baidu.com'):
                self.assertNotIn('host.contains("' + host + '")', source)

    def test_no_phone_identifier_collection_or_permission(self):
        source = (JAVA / 'utils/MobileInfoUtil.java').read_text()
        self.assertIn('return DEFAULT_IMEI;', source)
        self.assertNotIn('TelephonyManager', source)
        self.assertNotIn('getDeviceId', source)
        root = ET.parse(MAIN / 'AndroidManifest.xml').getroot()
        phone_permissions = [node for node in root
                             if node.tag in ('uses-permission', 'uses-permission-sdk-23')
                             and 'PHONE_STATE' in node.get(ANDROID + 'name', '')]
        # A library manifest can restore an omitted permission during merging.
        # Require an unconditional removal marker, not merely source absence.
        self.assertEqual(1, len(phone_permissions))
        removal = phone_permissions[0]
        self.assertEqual('uses-permission', removal.tag)
        self.assertEqual('android.permission.READ_PHONE_STATE', removal.get(ANDROID + 'name'))
        self.assertEqual('remove', removal.get(TOOLS + 'node'))
        self.assertNotIn(TOOLS + 'selector', removal.attrib)

    def test_unused_guid_settings_permission_is_removed(self):
        root = ET.parse(MAIN / 'AndroidManifest.xml').getroot()
        permissions = [node for node in root
                       if node.tag in ('uses-permission', 'uses-permission-sdk-23')
                       and node.get(ANDROID + 'name') == 'android.permission.WRITE_SETTINGS']
        self.assertEqual(1, len(permissions))
        removal = permissions[0]
        self.assertEqual('uses-permission', removal.tag)
        self.assertEqual('remove', removal.get(TOOLS + 'node'))
        self.assertNotIn(TOOLS + 'selector', removal.attrib)
        # The app uses the OAID-only overload, never the GUID-persisting fallback.
        for path in JAVA.rglob('*'):
            if path.suffix not in ('.java', '.kt'):
                continue
            with self.subTest(source=path.relative_to(JAVA)):
                source = path.read_text()
                self.assertNotRegex(source, r'\bDeviceID\s*\.\s*(register|getGUID|getClientId\w*)\s*\(')
                self.assertNotRegex(source, r'\bSettings\s*\.\s*System\s*\.\s*put\w*\s*\(')
                self.assertNotIn('ACTION_MANAGE_WRITE_SETTINGS', source)

    def test_custom_routes_remain_unverified_and_unchanged(self):
        app = ET.parse(MAIN / 'AndroidManifest.xml').getroot().find('application')
        routes = []
        for component in app:
            for intent in component.findall('intent-filter'):
                for data in intent.findall('data'):
                    if data.get(ANDROID + 'scheme') == 'com.baidu.tieba':
                        self.assertEqual('unidispatch', data.get(ANDROID + 'host'))
                        self.assertNotEqual('true', intent.get(ANDROID + 'autoVerify'))
                        self.assertIn('android.intent.action.VIEW', [n.get(ANDROID + 'name') for n in intent.findall('action')])
                        self.assertIn('android.intent.category.BROWSABLE', [n.get(ANDROID + 'name') for n in intent.findall('category')])
                        routes.append(component.get(ANDROID + 'name'))
        self.assertEqual(5, len(routes))

    def test_back_handler_delegates_without_recursive_callback(self):
        source = (JAVA / 'activities/BaseActivity.kt').read_text()
        self.assertNotIn('override fun onBackPressed()', source)
        self.assertIn('onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true)', source)
        start = source.index('if (!HandleBackUtil.handleBackPress(this@BaseActivity))')
        body = source[start:source.index('        if (isNeedFixBg)', start)]
        self.assertLess(body.index('isEnabled = false'), body.index('onBackPressedDispatcher.onBackPressed()'))
        self.assertIn('finally {', body)
        self.assertGreater(body.index('isEnabled = true'), body.index('finally {'))

    def test_theme_refresh_uses_public_apis_without_replacing_adapters(self):
        source = (JAVA / 'ui/common/theme/utils/ThemeUtils.java').read_text()
        for forbidden in ('getDeclaredField', 'getDeclaredMethod', 'setAccessible', 'setAdapter(', 'swapAdapter(', '@SuppressLint'):
            self.assertNotIn(forbidden, source)
        for expected in ('invalidateViews()', '((BaseAdapter) adapter).notifyDataSetChanged()',
                         'recyclerView.getRecycledViewPool().clear()', 'adapter.notifyDataSetChanged()',
                         'recyclerView.invalidateItemDecorations()', 'refreshView(((ViewGroup) view).getChildAt(i), extraRefreshable)'):
            self.assertIn(expected, source)

    def test_dynamic_palette_has_direct_platform_guard(self):
        source = (JAVA / 'ui/common/theme/compose/Theme.kt').read_text()
        branch = source[source.index('    val extendedColors = if ('):]
        self.assertIn('Build.VERSION.SDK_INT >= Build.VERSION_CODES.S &&', branch)
        self.assertIn('isDynamicTheme && !ThemeUtil.isTranslucentTheme(theme)', branch)
        self.assertLess(branch.index('Build.VERSION.SDK_INT'), branch.index('dynamicTonalPalette(context)'))
        self.assertIn('} else {\n        getThemeColorForTheme(theme)', branch)

    def test_emoticon_entry_points_validate_ids(self):
        source = (JAVA / 'utils/EmoticonManager.kt').read_text()
        self.assertIn('emoticonCache.ids.filter { EmoticonCachePath.isValidId(it) }', source)
        self.assertIn('emoticonCache.mapping.filterValues { EmoticonCachePath.isValidId(it) }', source)
        self.assertIn('if (!EmoticonCachePath.isValidId(realId)) return', source)
        self.assertIn('return EmoticonCachePath.resolve(getEmoticonCacheDir(), id)', source)
        self.assertNotIn('File(getEmoticonCacheDir(), "$id.png")', source)


if __name__ == '__main__':
    unittest.main()
