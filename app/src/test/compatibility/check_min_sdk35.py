"""Focused minSdk35 source regressions; Android compilation/runtime remain separate gates."""
from pathlib import Path
import operator
import re
import unittest

ROOT = Path(__file__).resolve().parents[4]
JAVA = ROOT / 'app/src/main/java/com/huanchengfly/tieba/post'
MIN_SDK = 35
# Ownership is deliberately bounded to this cleanup. Media files have separate checks.
OWNED_FILES = (
    'App.kt', 'Extensions.kt', 'MainActivityV2.kt',
    'api/interfaces/impls/MixedTiebaApiImpl.kt',
    'components/transformations/internal/RSBlur.java',
    'components/transformations/internal/SupportRSBlur.java',
    'components/transformations/internal/Utils.java',
    'fragments/BaseFragment.kt',
    'services/NotifyJobService.kt', 'services/OKSignTileService.java',
    'ui/common/theme/compose/DynamicTonalPalette.kt', 'ui/common/theme/compose/Theme.kt',
    'ui/page/MonetTestPage.kt', 'ui/page/photoview/PhotoViewActivity.kt',
    'ui/page/settings/custom/CustomSettingsPage.kt',
    'ui/page/settings/more/MoreSettingsPage.kt', 'ui/page/settings/oksign/OKSignSettingsPage.kt',
    'ui/page/settings/theme/AppThemePage.kt', 'ui/utils/ImeInsetsConnection.kt',
    'ui/widgets/compose/FullScreen.kt', 'ui/widgets/theme/TintUndoableEditText.java',
    'utils/ClipBoardUtils.kt', 'utils/FileUtil.kt', 'utils/ImageUtil.kt', 'utils/NetworkUtil.kt',
    'utils/PermissionUtils.kt', 'utils/ThemeUtil.kt', 'utils/TiebaUtil.kt', 'utils/UIDUtil.kt',
    'utils/Util.java', 'utils/utils.kt',
)
API_LEVELS = {
    'JELLY_BEAN_MR2': 18, 'LOLLIPOP': 21, 'M': 23, 'N': 24, 'N_MR1': 25,
    'O': 26, 'O_MR1': 27, 'P': 28, 'Q': 29, 'R': 30, 'S': 31, 'S_V2': 32,
    'TIRAMISU': 33, 'UPSIDE_DOWN_CAKE': 34, 'VANILLA_ICE_CREAM': 35,
}
OPERATORS = {'>=': operator.ge, '<=': operator.le, '>': operator.gt,
             '<': operator.lt, '==': operator.eq, '!=': operator.ne}
# Exact dead closure only. Other live status-bar/reflection paths remain outside this guard.
REMOVED_SOURCE_FILES = (
    'utils/KeyEventManager.kt', 'utils/StatusBarUtil.java',
    'fragments/BaseBottomSheetDialogFragment.java', 'fragments/MenuDialogFragment.java',
    'interfaces/InitMenuCallback.java',
)
REMOVED_REFERENCES = re.compile(
    rb'\b(?:KeyEventManager(?:Kt)?|bindKeyEvent|StatusBarUtil|BaseBottomSheetDialogFragment|'
    rb'MenuDialogFragment|InitMenuCallback|BottomSheetDialogStyle)\b'
)
REMOVED_HIDDEN_REFLECTION = re.compile(
    rb'android\.view\.View\.ListenerInfo|\b(?:getListenerInfo|mOnKeyListener|'
    rb'MiuiWindowManager|EXTRA_FLAG_STATUS_BAR_DARK_MODE|MEIZU_FLAG_DARK_STATUS_BAR_ICON|'
    rb'meizuFlags)\b'
)


def source(name):
    return (JAVA / name).read_text()


def redundant_comparison(operation, threshold):
    # Include both sides of the cutoff. API35 <= 35 and API36+ gates are live.
    samples = {MIN_SDK, max(MIN_SDK, threshold - 1), max(MIN_SDK, threshold),
               max(MIN_SDK, threshold + 1)}
    return len({OPERATORS[operation](sdk, threshold) for sdk in samples}) == 1


class MinSdk35Checks(unittest.TestCase):
    def test_runtime_floor_matches_the_cleanup(self):
        gradle = (ROOT / 'app/build.gradle.kts').read_text()
        self.assertRegex(gradle, r'minSdk\s*=\s*35\b')
        self.assertRegex(gradle, r'targetSdk\s*=\s*37\b')

    def test_guard_check_allows_real_minimum_and_future_boundaries(self):
        for operation, threshold in [('<=', 35), ('==', 35), ('!=', 35),
                                     ('>=', 36), ('<', 36), ('>=', 37)]:
            self.assertFalse(redundant_comparison(operation, threshold))
        for operation, threshold in [('>=', 35), ('<', 35), ('<=', 34), ('>', 34), ('>=', 23)]:
            self.assertTrue(redundant_comparison(operation, threshold))

    def test_cleaned_files_do_not_reintroduce_redundant_sdk_checks_or_annotations(self):
        compare = re.compile(r'Build\.VERSION\.SDK_INT\s*(>=|<=|==|!=|>|<)\s*'
                             r'(?:Build\.VERSION_CODES\.(\w+)|(\d+))')
        annotation = re.compile(r'@(?:TargetApi|RequiresApi)\(\s*(?:api\s*=\s*)?'
                                r'(?:Build\.VERSION_CODES\.(\w+)|(\d+))')
        for file in OWNED_FILES:
            content = source(file)
            with self.subTest(file=file):
                self.assertNotRegex(content, r'@Suppress(?:Lint|Warnings)?\([^\n]*ObsoleteSdkInt')
                for match in compare.finditer(content):
                    operation, named, numeric = match.groups()
                    level = int(numeric) if numeric else API_LEVELS.get(named)
                    if level is not None:
                        self.assertFalse(redundant_comparison(operation, level), match.group())
                for match in annotation.finditer(content):
                    named, numeric = match.groups()
                    level = int(numeric) if numeric else API_LEVELS.get(named)
                    if level is not None:
                        self.assertGreater(level, MIN_SDK, match.group())

    def test_dynamic_colors_preserve_user_choice_and_custom_fallbacks(self):
        theme = source('ui/common/theme/compose/Theme.kt')
        self.assertIn('if (isDynamicTheme && !ThemeUtil.isTranslucentTheme(theme))', theme)
        self.assertIn('getDynamicColor(theme, dynamicTonalPalette(context))', theme)
        self.assertIn('} else {\n        getThemeColorForTheme(theme)', theme)
        app = source('App.kt')
        self.assertEqual(3, app.count('if (ThemeUtil.isDynamicTheme(theme))'))
        self.assertIn('ThemeUtil.THEME_CUSTOM == theme', app)
        self.assertIn('checkDynamic && isUsingDynamicTheme()', source('utils/ThemeUtil.kt'))
        custom = source('ui/page/settings/custom/CustomSettingsPage.kt')
        self.assertIn('enabled = isCurrentSupportThemedIcon', custom)
        self.assertIn('AppIconUtil.setIcon(isThemed = it)', custom)
        self.assertIn('ThemeUtil.setUseDynamicTheme(true)', source('ui/page/settings/theme/AppThemePage.kt'))

    def test_webview_process_isolation_and_native_decoder_remain(self):
        app = source('App.kt')
        self.assertIn('if (applicationContext.packageName != processName)', app)
        self.assertIn('WebView.setDataDirectorySuffix(processName!!)', app)
        self.assertLess(app.index('setWebViewPath(this)'), app.index('AccountUtil.init(this)'))
        self.assertIn('is ByteArrayDataSource -> ImageDecoder.createSource(dataSource.data)', app)

    def test_pending_intent_mutability_stays_explicit(self):
        helpers = source('Extensions.kt')
        self.assertIn('fun pendingIntentFlagMutable(): Int = PendingIntent.FLAG_MUTABLE', helpers)
        self.assertIn('fun pendingIntentFlagImmutable(): Int = PendingIntent.FLAG_IMMUTABLE', helpers)

    def test_notification_permission_still_requires_login_and_grant_flow(self):
        main = source('MainActivityV2.kt').split('private fun requestNotificationPermission()', 1)[1]
        main = main.split('private fun initAutoSign()', 1)[0]
        self.assertIn('if (AccountUtil.isLoggedIn())', main)
        self.assertIn('requestPermission {', main)
        self.assertIn('permissions = listOf(PermissionUtils.POST_NOTIFICATIONS)', main)
        service = source('services/NotifyJobService.kt')
        for expected in ('NotificationChannel(', 'NotificationChannelGroup(',
                         'createNotificationChannelGroup(channelGroup)',
                         'createChannel(CHANNEL_REPLY, CHANNEL_REPLY_NAME)',
                         'createChannel(CHANNEL_AT, CHANNEL_AT_NAME)'):
            self.assertIn(expected, service)

    def test_permission_labels_keep_background_distinctions_and_denial_callbacks(self):
        permissions = source('utils/PermissionUtils.kt')
        for expected in ('!permissions.contains(Manifest.permission.ACCESS_FINE_LOCATION)',
                         '!permissions.contains(Manifest.permission.ACCESS_COARSE_LOCATION)',
                         '!permissions.contains(Manifest.permission.BODY_SENSORS)',
                         'common_permission_location_background', 'common_permission_location)',
                         'common_permission_body_sensors_background', 'common_permission_body_sensors)',
                         'common_permission_activity_recognition_api30', 'common_permission_call_logs',
                         'if (deniedList.isEmpty())', 'onDenied?.invoke()',
                         '.interceptor(ShowPermissionTipInterceptor(permissions, description))'):
            self.assertIn(expected, permissions)

    def test_modern_image_and_file_downloads_keep_io_failure_handling(self):
        image = source('utils/ImageUtil.kt')
        for expected in ('if (forShare)', 'downloadForShare(context, url, taskCallback)',
                         'downloadAboveQ(context, url)', 'MediaStore.Images.Media.RELATIVE_PATH',
                         'MediaStore.Images.Media.MIME_TYPE', 'cr.openFileDescriptor(uri, "w")',
                         'cr.delete(uri, null, null)', 'FileProvider.getUriForFile(',
                         'context.packageName + ".share.FileProvider"'):
            self.assertIn(expected, image)
        self.assertNotIn('downloadBelowQ', image)
        self.assertNotIn('askPermission(', image)
        files = source('utils/FileUtil.kt')
        self.assertIn('downloadBySystemWithPermission(context, fileType, url, fileName)', files)
        self.assertIn('downloadManager.enqueue(request)', files)
        self.assertNotIn('askPermission(', files)
        photo = source('ui/page/photoview/PhotoViewActivity.kt')
        self.assertIn('putExtra(Intent.EXTRA_STREAM, uri)', photo)
        self.assertIn('addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)', photo)
        self.assertIn('runCatching {\n                                            startActivity(chooser)', photo)

    def test_clipboard_sensitivity_and_public_timestamp_remain(self):
        helper = source('utils/TiebaUtil.kt')
        self.assertIn('putBoolean(ClipDescription.EXTRA_IS_SENSITIVE, isSensitive)', helper)
        self.assertIn('ClipData.newPlainText("Tieba Lite", text).setIsSensitive(isSensitive)', helper)
        self.assertIn('cm.setPrimaryClip(clipData)', helper)
        copy = helper.split('fun copyText(', 1)[1].split('fun initAutoSign(', 1)[0]
        self.assertNotIn('context.toastShort(toast)', copy)
        timestamps = source('utils/ClipBoardUtils.kt')
        self.assertIn('return clipDescription.timestamp', timestamps)
        self.assertNotIn('getDeclaredField', timestamps)

    def test_ime_connection_retains_platform_animation_and_disposal(self):
        ime = source('ui/utils/ImeInsetsConnection.kt')
        self.assertIn('nestedScroll(nestedScrollConnection)', ime)
        self.assertIn('remember(view, sideCalculator, density)', ime)
        self.assertIn('DisposableEffect(connection)', ime)
        self.assertIn('connection.dispose()', ime)
        self.assertIn('android.view.WindowInsets.Type.ime()', ime)
        self.assertNotIn('DoNothingNestedScrollConnection', ime)

    def test_fragment_context_attachment_remains_single_owned_path(self):
        kotlin = source('fragments/BaseFragment.kt')
        self.assertIn('override fun onAttach(context: Context)', kotlin)
        self.assertIn('super.onAttach(context)\n        onAttachToContext(context)', kotlin)
        self.assertNotIn('onAttach(activity: Activity)', kotlin)

    def test_removed_dead_closure_has_no_production_files_or_references(self):
        for file in REMOVED_SOURCE_FILES:
            with self.subTest(removed=file):
                self.assertFalse((JAVA / file).exists())
        # Include shipping source sets, manifests, resources and all asset bytes, but not
        # tests/reports that legitimately describe the deleted names or historical findings.
        production_files = {ROOT / 'app/proguard-rules.pro'}
        for source_set in (ROOT / 'app/src').iterdir():
            if not source_set.is_dir() or source_set.name.startswith(('test', 'androidTest')):
                continue
            for file in source_set.rglob('*'):
                if file.is_file() and (file.suffix in ('.kt', '.java', '.xml', '.pro') or
                                       'assets' in file.relative_to(source_set).parts):
                    production_files.add(file)
        for file in sorted(production_files):
            with self.subTest(file=str(file.relative_to(ROOT))):
                content = file.read_bytes()
                self.assertNotRegex(content, REMOVED_REFERENCES)
                self.assertNotRegex(content, REMOVED_HIDDEN_REFLECTION)
        # This pre-existing unused layout is intentionally not part of the deletion.
        self.assertTrue((ROOT / 'app/src/main/res/layout/fragment_menu_dialog.xml').is_file())

    def test_platform_cleanup_and_error_fallbacks_are_retained(self):
        for file in ('RSBlur.java', 'SupportRSBlur.java'):
            rs = source('components/transformations/internal/' + file)
            for expected in ('finally {', 'if (rs != null)', 'RenderScript.releaseAllContexts();',
                             'input.destroy();', 'output.destroy();', 'blur.destroy();'):
                self.assertIn(expected, rs)
        util = source('utils/Util.java')
        status_bar = util.split('public static void setStatusBarTransparent(', 1)[1].split('public static int alphaColor', 1)[0]
        self.assertIn('try {', status_bar)
        self.assertIn('catch (Exception ignored)', status_bar)
        network = source('utils/NetworkUtil.kt').split('object NetworkUtil', 1)[0]
        self.assertIn('activeNetwork ?: return false', network)
        self.assertIn('getNetworkCapabilities(network) ?: return false', network)
        self.assertIn('NetworkCapabilities.NET_CAPABILITY_VALIDATED', network)

    def test_battery_optimization_and_default_settings_fallbacks_remain(self):
        battery = source('utils/utils.kt')
        self.assertIn('if (!powerManager.isIgnoringBatteryOptimizations(packageName))', battery)
        self.assertIn('Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS', battery)
        settings = source('ui/page/settings/more/MoreSettingsPage.kt').split('private fun openDefaultLinkSettings', 1)[1]
        self.assertLess(settings.index('Settings.ACTION_APP_OPEN_BY_DEFAULT_SETTINGS'),
                        settings.index('Settings.ACTION_APPLICATION_DETAILS_SETTINGS'))
        self.assertIn('for (action in actions)', settings)
        self.assertIn('catch (_: ActivityNotFoundException)', settings)
        self.assertIn('return false', settings)

    def test_publication_is_blocked_before_the_remaining_modern_upload_branch(self):
        api = source('api/interfaces/impls/MixedTiebaApiImpl.kt')
        upload = api.split('override fun webUploadPic(', 1)[1].split('override fun webAddThread', 1)[0]
        self.assertLess(upload.index('PublicationPolicy.requireEnabled()'), upload.index('openAssetFileDescriptor('))
        self.assertIn(')?.use { afd ->', upload)
        self.assertIn('catch (e: IOException)', upload)
        self.assertIn('val enabled: Boolean = false', source('security/PublicationPolicy.kt'))


if __name__ == '__main__':
    unittest.main()
