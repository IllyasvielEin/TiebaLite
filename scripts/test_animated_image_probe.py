"""Source guards for the Sketch wrapper; not Android decoder/runtime validation.

The candidate must be selected once, before any full-image animation probe. This
keeps each factory's format, API and disallowAnimatedImage guards in control and
preserves the existing single-frame fallback. Actual image decoding and memory
use still require Android device tests with Sketch 3.3.2.
"""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'app/src/main/java/com/huanchengfly/tieba/post/App.kt'


class AnimatedImageProbeSourceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = APP.read_text()
        cls.wrapper = cls.app.split('fun wrapDecoder(', 1)[1].split(
            'addDrawableDecoder(wrapDecoder(gifAnimatedFactory))', 1)[0]
        cls.create = cls.wrapper.split('): DrawableDecoder? {', 1)[1]

    def test_factory_null_short_circuits_before_any_probe_setup(self):
        # The first executable statement must include the null return, so a
        # rejected candidate cannot touch dataSource or ImageDecoder at all.
        create = re.sub(r'//[^\n]*', '', self.create).lstrip()
        self.assertRegex(create, r'^val candidate = factory\.create\('
                         r'sketch, requestContext, fetchResult\)\s*\?: return null\b')
        guard_end = create.index('?: return null') + len('?: return null')
        self.assertLess(guard_end, create.index('fetchResult.mimeType'))
        self.assertLess(guard_end, create.index('fetchResult.dataSource'))
        self.assertLess(guard_end, create.index('ImageDecoder.createSource'))
        self.assertLess(guard_end, create.index('ImageDecoder.decodeDrawable'))

    def test_candidate_factory_is_called_exactly_once(self):
        self.assertEqual(1, self.wrapper.count('factory.create('))
        self.assertEqual(1, self.wrapper.count('val candidate ='))
        self.assertRegex(self.create, r'val candidate = factory\.create\('
                         r'sketch, requestContext, fetchResult\)')

    def test_non_animated_mime_returns_the_same_candidate_without_probe(self):
        guard = 'if (fetchResult.mimeType !in animatedMimeTypes) return candidate'
        self.assertIn(guard, self.create)
        self.assertLess(self.create.index(guard), self.create.index('fetchResult.dataSource'))
        self.assertIn('setOf("image/gif", "image/webp", "image/heif")', self.create)

    def test_animated_result_reuses_candidate_instead_of_recreating_it(self):
        result = self.create.split('if (!isActuallyAnimated)', 1)[1]
        self.assertRegex(result, r'^\s*\{\s*return null\s*\}\s*return candidate\b')
        self.assertEqual(2, self.create.count('return candidate'))

    def test_single_frame_and_probe_failures_keep_the_existing_fallback(self):
        self.assertRegex(self.create, r'if \(!isActuallyAnimated\)\s*\{\s*return null\s*\}')
        self.assertRegex(self.create, r'catch \(e: Throwable\)\s*\{\s*false\s*\}')
        self.assertIn('else -> null', self.create)
        self.assertRegex(self.create, r'animated\s*\} else \{\s*false\s*\}')

    def test_existing_probe_and_all_supported_data_sources_are_retained(self):
        self.assertEqual(1, self.create.count('ImageDecoder.decodeDrawable('))
        self.assertIn('ImageDecoder.decodeDrawable(source) { _, info, _ ->', self.create)
        self.assertIn('animated = info.isAnimated', self.create)
        for data_source in ('AssetDataSource', 'ResourceDataSource', 'ContentDataSource',
                            'ByteArrayDataSource', 'BasedFileDataSource'):
            with self.subTest(data_source=data_source):
                self.assertIn('is ' + data_source + ' -> ImageDecoder.createSource(', self.create)
        self.assertIn('is ByteArrayDataSource -> ImageDecoder.createSource(dataSource.data)',
                      self.create)

    def test_probe_size_and_animation_detection_are_not_replaced(self):
        for replacement in ('setTargetSize', 'setTargetSampleSize', 'BitmapFactory',
                            'fetchResult.header', 'requestContext.request', 'Build.VERSION'):
            with self.subTest(replacement=replacement):
                self.assertNotIn(replacement, self.create)

    def test_factory_order_and_movie_fallback_are_retained(self):
        sketch = self.app.split('override fun createSketch()', 1)[1]
        registrations = (
            'addDrawableDecoder(wrapDecoder(gifAnimatedFactory))',
            'addDrawableDecoder(wrapDecoder(webpAnimatedFactory))',
            'addDrawableDecoder(wrapDecoder(heifAnimatedFactory))',
            'addDrawableDecoder(GifMovieDrawableDecoder.Factory())',
        )
        for registration in registrations:
            self.assertEqual(1, sketch.count(registration))
        positions = [sketch.index(registration) for registration in registrations]
        self.assertEqual(sorted(positions), positions)


if __name__ == '__main__':
    unittest.main()
