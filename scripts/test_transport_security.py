"""Offline security regression checks; never send an account or HTTP request."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
JAVA = ROOT / 'app/src/main/java/com/huanchengfly/tieba/post'


class TransportWiringTest(unittest.TestCase):
    def test_credential_apis_require_https_and_disable_redirects(self):
        text = (JAVA / 'api/retrofit/RetrofitTiebaApi.kt').read_text()
        self.assertNotIn('http://c.tieba.baidu.com', text)
        self.assertEqual(text.count('"https://tiebac.baidu.com/"'), 7)
        for method in ('createJsonApi', 'createProtobufApi'):
            builder = text.split('private inline fun <reified T : Any> ' + method, 1)[1]
            self.assertLess(builder.index('addInterceptor(CredentialTransportInterceptor(baseUrl))'),
                            builder.index('interceptors.forEach'))
            self.assertIn('followRedirects(false)', builder)
            self.assertIn('followSslRedirects(false)', builder)
        self.assertNotIn('hostnameVerifier(', text)
        self.assertNotIn('sslSocketFactory(', text)

    def test_images_and_general_requests_have_no_cookie_jar(self):
        for path in ('App.kt', 'api/LiteApi.kt', 'components/glide/OkHttpLibraryGlideModule.java'):
            text = (JAVA / path).read_text()
            self.assertIn('AnonymousTransportInterceptor', text, path)
            self.assertIn('CookieJar.NO_COOKIES', text, path)
            self.assertIn('followSslRedirects(false)', text, path)
        manifest = (ROOT / 'app/src/main/AndroidManifest.xml').read_text()
        self.assertIn('android:usesCleartextTraffic="false"', manifest)
        self.assertNotIn('android:usesCleartextTraffic="true"', manifest)

    def test_native_publication_guard_runs_before_network(self):
        text = (JAVA / 'api/retrofit/interceptors/CredentialTransportInterceptor.kt').read_text()
        self.assertLess(text.index('!PublicationPolicy.enabled'), text.index('chain.proceed(request)'))
        self.assertIn('CredentialTransportPolicy.isPublicationPath(path)', text)
        self.assertIn('response.close()', text)
        self.assertIn('throw IOException("Redirects are disabled', text)


@unittest.skipUnless(shutil.which('java'), 'JDK needed for offline pure Java policy tests')
class CredentialPolicyExecutableTest(unittest.TestCase):
    def test_policy_without_android_or_network(self):
        harness = r'''
import com.huanchengfly.tieba.post.security.CredentialTransportPolicy;
public class TransportPolicyHarness {
 public static void main(String[] args) {
  for(String host : new String[]{"tieba.baidu.com","tiebac.baidu.com","wapp.baidu.com"}) {
   assert CredentialTransportPolicy.permitsWebCookie("https",host,443,null);
   assert !CredentialTransportPolicy.permitsWebCookie("http",host,80,null);
   assert !CredentialTransportPolicy.permitsWebCookie("https",host,444,null);
   assert !CredentialTransportPolicy.permitsWebCookie("https",host,443,"user");
  }
  for(String host : new String[]{null,"baidu.com","evil.baidu.com","tieba.baidu.com.","tieba.baidu.com.evil.example","static.tieba.baidu.com"})
   assert !CredentialTransportPolicy.permitsWebCookie("https",host,443,null);
  for(String path : new String[]{"/c/c/post/add","/c/c/thread/add","/c/s/uploadPicture","/mo/q/cooluploadpic","/mo/q/apubpost","/C/C/POST/ADD/"})
   assert CredentialTransportPolicy.isPublicationPath(path);
  for(String path : new String[]{"/c/f/pb/page","/c/c/post/addstore","/c/c/post/addPollPost","/c/c/img/portrait","/c/c/user/follow","/c/c/forum/sign","/c/s/login"})
   assert !CredentialTransportPolicy.isPublicationPath(path);
  String cookie=CredentialTransportPolicy.bdussCookie("synthetic_test-=~123");
  assert cookie.contains("; Secure") && cookie.contains("; HttpOnly") && !cookie.contains("Domain=") && !cookie.contains("Max-Age=");
  for(String invalid : new String[]{"","token; Domain=.baidu.com","token\r\nCookie: other","token value","a,b","a\\b","a\"b"}) {
   try { CredentialTransportPolicy.bdussCookie(invalid); throw new AssertionError("invalid value accepted"); } catch (IllegalArgumentException expected) {}
  }
 }
}
'''
        with tempfile.TemporaryDirectory() as folder:
            source = pathlib.Path(folder) / 'TransportPolicyHarness.java'
            source.write_text(harness)
            compiler = [shutil.which('java'), '-m', 'jdk.compiler/com.sun.tools.javac.Main']
            subprocess.run(compiler + ['-d', folder, str(JAVA / 'security/CredentialTransportPolicy.java'), str(source)], check=True)
            subprocess.run([shutil.which('java'), '-ea', '-cp', folder, 'TransportPolicyHarness'], check=True)


if __name__ == '__main__':
    unittest.main()
