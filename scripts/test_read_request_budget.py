"""Source-only guards for selective read budgets. These do not run OkHttp/JVM timeout tests."""
from collections import Counter
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
RETROFIT = ROOT / 'app/src/main/java/com/huanchengfly/tieba/post/api/retrofit'


class ReadRequestBudgetSourceTest(unittest.TestCase):
    def test_only_individually_audited_read_methods_are_marked(self):
        expected = {
            'OfficialProtobufTiebaApi.kt': [
                ('/c/f/frs/page?cmd=301001', 'frsPageFlow'),
                ('/c/f/frs/threadlist?cmd=301002', 'threadListFlow'),
                ('/c/f/pb/page?cmd=302001&format=protobuf', 'pbPageFlow'),
                ('/c/f/pb/floor?cmd=302002&format=protobuf', 'pbFloorFlow'),
                ('/c/f/frs/generalTabList?cmd=309622&format=protobuf', 'generalTabListFlow'),
            ],
            'OfficialTiebaApi.kt': [
                ('/c/f/pb/page', 'threadContent'),
                ('/c/f/pb/page', 'threadContent'),
                ('/c/f/pb/page', 'threadContentAsync'),
                ('/c/f/pb/page', 'threadContentAsync'),
                ('/c/f/pb/floor', 'floor'),
            ],
            'MiniTiebaApi.kt': [
                ('/c/f/frs/page', 'forumPage'),
                ('/c/f/frs/page', 'forumPageAsync'),
                ('/c/f/pb/floor', 'floor'),
            ],
        }
        marked_count = 0
        for path in (RETROFIT / 'interfaces').glob('*.kt'):
            source = path.read_text()
            matches = re.findall(
                r'@BudgetedReadRequest\s+@POST\("([^"\n]+)"\)\s+'
                r'(?:@FormUrlEncoded\s+)?fun\s+(\w+)\s*\(', source)
            self.assertEqual(Counter(matches), Counter(expected.get(path.name, [])), path.name)
            self.assertEqual(source.count('@BudgetedReadRequest'), len(matches), path.name)
            marked_count += len(matches)
        self.assertEqual(13, marked_count)

    def test_factory_derives_client_before_call_creation_without_changing_other_settings(self):
        source = (RETROFIT / 'ReadOnlyRequestCallFactory.kt').read_text()
        self.assertIn('timeout: Long = 60L', source)
        self.assertIn('unit: TimeUnit = TimeUnit.SECONDS', source)
        self.assertIn('require(timeout > 0L)', source)
        self.assertRegex(source, r'client\.newBuilder\(\)\s*\.callTimeout\(timeout, unit\)\s*\.build\(\)')
        self.assertIn('request.tag(Invocation::class.java)?.method()', source)
        self.assertIn('method?.isAnnotationPresent(BudgetedReadRequest::class.java)', source)
        self.assertIn('return selectedClient.newCall(request)', source)
        self.assertEqual(1, source.count('.callTimeout('))
        for forbidden in ('request.method', 'request.url', 'request.body', 'arguments()',
                          'addInterceptor(', 'retryOnConnectionFailure(', 'followRedirects(',
                          'cookieJar(', 'dispatcher(', 'connectionPool('):
            self.assertNotIn(forbidden, source)

    def test_both_retrofit_factories_use_budget_selector_and_sofire_stays_unmarked(self):
        source = (RETROFIT / 'RetrofitTiebaApi.kt').read_text()
        self.assertEqual(2, source.count('.callFactory(ReadOnlyRequestCallFactory('))
        self.assertEqual(1, source.count('.client(OkHttpClient.Builder()'))
        sofire = source.split('val SOFIRE_API:', 1)[1].split('private inline fun', 1)[0]
        self.assertIn('.client(OkHttpClient.Builder()', sofire)
        self.assertNotIn('ReadOnlyRequestCallFactory', sofire)
        self.assertEqual(3, source.count('followRedirects(false)'))
        self.assertEqual(3, source.count('followSslRedirects(false)'))
        self.assertEqual(3, source.count('addInterceptor(CredentialTransportInterceptor('))
        self.assertNotIn('.callTimeout(', source)

    def test_annotation_is_runtime_retained_and_has_a_narrow_release_keep_rule(self):
        source = (RETROFIT / 'BudgetedReadRequest.kt').read_text()
        self.assertIn('@Target(AnnotationTarget.FUNCTION)', source)
        self.assertIn('@Retention(AnnotationRetention.RUNTIME)', source)
        rules = (ROOT / 'app/proguard-rules.pro').read_text()
        self.assertIn('-keep @interface com.huanchengfly.tieba.post.api.retrofit.BudgetedReadRequest', rules)
        self.assertIn('RuntimeVisibleAnnotations', rules)

    def test_runtime_tests_use_production_factory_real_invocations_and_socket_io(self):
        source = (ROOT / 'app/src/test/java/com/huanchengfly/tieba/post/api/retrofit/ReadOnlyRequestCallFactoryTest.kt').read_text()
        for required in ('ReadOnlyRequestCallFactory(base)', '.callFactory(factory)',
                         'request.tag(Invocation::class.java)', 'raw.clone()', 'original.clone()',
                         'ServerSocket(', 'scheduleAtFixedRate(', 'call.cancel()',
                         'service.upload(', 'dispatcher.queuedCallsCount()',
                         'CredentialTransportInterceptor(', 'server.requestCount.get()'):
            self.assertIn(required, source)
        self.assertNotIn('Thread.sleep(', source)


if __name__ == '__main__':
    unittest.main()
