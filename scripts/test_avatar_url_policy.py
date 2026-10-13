"""Executable pure URL routing checks; these do not establish live CDN TLS behavior."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
JAVA = ROOT / 'app/src/main/java/com/huanchengfly/tieba/post'

class AvatarUrlTests(unittest.TestCase):
    def test_production_url_policy(self):
        self.assertIsNotNone(shutil.which('java'))
        with tempfile.TemporaryDirectory() as folder:
            sources = [JAVA / 'security/AvatarUrlPolicy.java', ROOT / 'app/src/test/java/com/huanchengfly/tieba/post/security/AvatarUrlPolicyHarness.java']
            subprocess.run(['java', '-m', 'jdk.compiler/com.sun.tools.javac.Main', '-source', '17', '-target', '17', '-Xlint:-options', '-d', folder, *map(str, sources)], check=True)
            subprocess.run(['java', '-cp', folder, 'com.huanchengfly.tieba.post.security.AvatarUrlPolicyHarness'], check=True)

    def test_fresh_and_existing_routes_use_policy_after_security_gates(self):
        utility = (JAVA / 'utils/StringUtil.kt').read_text()
        self.assertIn('AvatarUrlPolicy.small(portrait)', utility)
        self.assertIn('AvatarUrlPolicy.large(portrait)', utility)
        source = (JAVA / 'api/retrofit/interceptors/AnonymousTransportInterceptor.kt').read_text()
        mapping = source.index('if (upgradeHttp) url = AvatarUrlPolicy.normalizeLegacy')
        for guard in ('Reason.METHOD', 'Reason.CREDENTIALS', 'Reason.INSECURE_TRANSPORT'):
            self.assertLess(source.index(guard), mapping)
        self.assertLess(mapping, source.index('chain.proceed'))
        bridge = (JAVA / 'diagnostics/AvatarDiagnostics.kt').read_text()
        self.assertIn('url.host == "himg.bdimg.com"', bridge)
        self.assertIn('AvatarDiagnosticStore.classifyHost(url.host)', bridge)
        self.assertNotIn('Host.AVATAR_CDN,', bridge)

if __name__ == '__main__': unittest.main()
