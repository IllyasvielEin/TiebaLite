"""Executable Java formatter checks plus source guards, not Kotlin/OkHttp runtime tests."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
JAVA = ROOT / 'app/src/main/java/com/huanchengfly/tieba/post'


class CookieSearchCompatibilityTests(unittest.TestCase):
    def test_production_cookie_formatter(self):
        self.assertIsNotNone(shutil.which('java'))
        with tempfile.TemporaryDirectory() as folder:
            sources = [JAVA / 'api/CookieHeaderBuilder.java',
                       ROOT / 'app/src/test/java/com/huanchengfly/tieba/post/api/CookieHeaderBuilderHarness.java']
            subprocess.run(['java', '-m', 'jdk.compiler/com.sun.tools.javac.Main',
                            '-source', '17', '-target', '17', '-Xlint:-options', '-d', folder,
                            *map(str, sources)], check=True)
            subprocess.run(['java', '-cp', folder,
                            'com.huanchengfly.tieba.post.api.CookieHeaderBuilderHarness'], check=True)

    def test_cookie_delegates_without_rewriting_or_repeating_suppliers(self):
        source = (JAVA / 'api/Utils.kt').read_text()
        body = source.split('fun getCookie(', 1)[1].split('\n}', 1)[0]
        self.assertIn('CookieHeaderBuilder.pair(name, supplier())', body)
        self.assertEqual(1, body.count('supplier()'))
        self.assertIn('.joinToString("; ")', body)
        for forbidden in ('trim(', 'encode(', 'replace(', '${it.first}:${it.second}'):
            self.assertNotIn(forbidden, body)
        self.assertIn('@Throws(IOException::class)', source)

    def test_only_search_content_is_defaulted_and_existing_coercion_is_enabled(self):
        source = (JAVA / 'api/models/SearchThreadBean.kt').read_text()
        self.assertEqual(3, source.count('val content: String = "",'))
        self.assertNotIn('val content: String?', source)
        self.assertIn('val title: String,', source)
        self.assertIn('val tid: String,', source)
        retrofit = (JAVA / 'api/retrofit/RetrofitTiebaApi.kt').read_text()
        self.assertIn('coerceInputValues = true', retrofit)
        self.assertIn('.addConverterFactory(json.asConverterFactory())', retrofit)
        self.assertIn('.addConverterFactory(gsonConverterFactory)', retrofit)


if __name__ == '__main__':
    unittest.main()
