"""Pure diagnostic-state checks and wiring guards; not Android UI/runtime validation."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
JAVA = ROOT / 'app/src/main/java/com/huanchengfly/tieba/post'


class AvatarDiagnosticWiringTest(unittest.TestCase):
    def test_report_has_no_raw_request_or_exception_outputs(self):
        model = (JAVA / 'diagnostics/AvatarDiagnosticStore.java').read_text()
        bridge = (JAVA / 'diagnostics/AvatarDiagnostics.kt').read_text()
        for forbidden in ('getMessage(', 'getClass(', 'printStackTrace(', 'stackTrace', 'Throwable.toString', 'Log.', 'println('):
            self.assertNotIn(forbidden, model)
            self.assertNotIn(forbidden, bridge)
        for forbidden in ('SharedPreferences', 'dataStore', 'File(', 'newCall(', '.execute(', 'enqueue(', 'httpHeaders'):
            self.assertNotIn(forbidden, bridge)
        self.assertIn('EventListener.Factory', bridge)
        self.assertIn('url.host == "tb.himg.baidu.com"', bridge)
        self.assertIn('url.encodedPath.startsWith("/sys/portrait/item/")', bridge)
        self.assertIn('url.encodedPath.startsWith("/sys/portraith/item/")', bridge)
        self.assertIn('if (lease == null) EventListener.NONE', bridge)

    def test_avatar_state_observation_is_session_bound_and_does_not_steal_gestures(self):
        avatar = (JAVA / 'ui/widgets/compose/Avatars.kt').read_text()
        self.assertIn('LaunchedEffect(state, inputKind, host)', avatar)
        self.assertIn('snapshotFlow { sanitizedAvatarState(state) }', avatar)
        self.assertIn('AvatarDiagnostics.sessions,', avatar)
        self.assertIn('observer.close()', avatar)
        self.assertNotIn('listener(', avatar)  # Sketch 3.3.2 forbids DisplayRequest listeners in Compose.
        self.assertNotIn('collectAsState()', avatar)  # Session changes never recompose or replace requests.
        self.assertNotIn('remember(context, data,', avatar)  # Preserve the existing themed placeholder construction.
        self.assertIn('result.throwable', avatar)
        self.assertIn('DataFrom.NETWORK -> Stage.SUCCESS_NETWORK', avatar)
        self.assertIn('DataFrom.DOWNLOAD_CACHE -> Stage.SUCCESS_DOWNLOAD_CACHE', avatar)
        for forbidden in ('onClick', 'longPress', 'pointerInput', 'combinedClickable', '.message', 'toString()'):
            self.assertNotIn(forbidden, avatar)
        thread = (JAVA / 'ui/page/thread/ThreadPage.kt').read_text()
        self.assertIn('diagnosticInputKind = com.huanchengfly.tieba.post.diagnostics.AvatarDiagnosticStore.classifyInput(author.portrait)', thread)
        self.assertIn('data = StringUtil.getAvatarUrl(author.portrait)', thread)

    def test_settings_entry_and_fresh_copy_have_no_persistent_opt_in(self):
        settings = (JAVA / 'ui/page/settings/SettingsPage.kt').read_text()
        page = (JAVA / 'ui/page/settings/diagnostics/AvatarDiagnosticsPage.kt').read_text()
        self.assertIn('navigator.navigate(AvatarDiagnosticsPageDestination)', settings)
        self.assertIn('AvatarDiagnostics.snapshots.collectAsState()', page)
        self.assertIn('onCheckedChange = { AvatarDiagnostics.store.setEnabled(it) }', page)
        self.assertIn('val report = AvatarDiagnostics.store.snapshot().report()', page)
        self.assertIn('onClick = { AvatarDiagnostics.store.clear() }', page)
        for forbidden in ('rememberSaveable', 'SharedPreferences', 'dataStore', 'startActivity', 'ACTION_SEND', 'Log.', 'http'):
            self.assertNotIn(forbidden, page)

    def test_https_and_anonymous_transport_boundaries_remain(self):
        app = (JAVA / 'App.kt').read_text()
        policy = (JAVA / 'api/retrofit/interceptors/AnonymousTransportInterceptor.kt').read_text()
        self.assertIn('.cookieJar(okhttp3.CookieJar.NO_COOKIES)', app)
        self.assertIn('.followSslRedirects(false)', app)
        self.assertIn('.eventListenerFactory(com.huanchengfly.tieba.post.diagnostics.AvatarDiagnostics.networkListenerFactory)', app)
        for boundary in ('request.method != "GET" && request.method != "HEAD"', 'url.username.isNotEmpty() || url.password.isNotEmpty()',
                         'SECRET_QUERY_NAMES', 'if (!upgradeHttp || url.port != 80)', '.scheme("https").port(443)', 'sanitized.removeHeader(header)'):
            self.assertIn(boundary, policy)
        self.assertIn('android:usesCleartextTraffic="false"', (ROOT / 'app/src/main/AndroidManifest.xml').read_text())


@unittest.skipUnless(shutil.which('java'), 'JDK needed for pure avatar diagnostic tests')
class AvatarDiagnosticExecutableTest(unittest.TestCase):
    def test_pure_privacy_and_lifecycle_scenarios(self):
        with tempfile.TemporaryDirectory() as folder:
            sources = [JAVA / 'diagnostics/AvatarDiagnosticStore.java',
                       JAVA / 'diagnostics/AvatarDiagnosticObserver.java',
                       JAVA / 'security/PublicDownloadPolicyException.java',
                       ROOT / 'app/src/test/java/com/huanchengfly/tieba/post/diagnostics/AvatarDiagnosticHarness.java']
            subprocess.run([shutil.which('java'), '-m', 'jdk.compiler/com.sun.tools.javac.Main',
                            '-source', '17', '-target', '17', '-Xlint:-options',
                            '-d', folder, *map(str, sources)], check=True)
            subprocess.run([shutil.which('java'), '-cp', folder,
                            'com.huanchengfly.tieba.post.diagnostics.AvatarDiagnosticHarness'], check=True)


if __name__ == '__main__':
    unittest.main()
