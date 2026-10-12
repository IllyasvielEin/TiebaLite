"""Source wiring regressions, not a substitute for Android/device picker tests."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[4]
JAVA = ROOT / 'app/src/main/java/com/huanchengfly/tieba/post'
ANDROID = '{http://schemas.android.com/apk/res/android}'


def source(relative):
    return (JAVA / relative).read_text()


class ImagePickerChecks(unittest.TestCase):
    def setUp(self):
        self.profile = source('ui/page/user/edit/EditProfileActivity.kt')
        self.background = source('activities/TranslucentThemeActivity.kt')
        self.adapter = source('utils/ImagePicker.kt')

    def test_active_screens_register_single_image_contracts(self):
        for screen in (self.profile, self.background):
            with self.subTest(screen=screen.split('class ', 1)[1].split(':', 1)[0]):
                self.assertIn('registerForActivityResult(ActivityResultContracts.PickVisualMedia())', screen)
                self.assertIn('PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)', screen)
                self.assertNotIn('registerPickMediasLauncher', screen)
                self.assertNotIn('shouldUsePhotoPicker', screen)

    def test_selection_does_not_request_whole_library_access(self):
        for screen in (self.profile, self.background):
            self.assertNotIn('READ_MEDIA_IMAGES', screen)
            self.assertNotIn('READ_EXTERNAL_STORAGE', screen)
            self.assertNotIn('requestPermission', screen)
            self.assertNotIn('takePersistableUriPermission', screen)
        manifest = ET.parse(ROOT / 'app/src/main/AndroidManifest.xml').getroot()
        permissions = {item.get(ANDROID + 'name') for item in manifest.findall('uses-permission')}
        self.assertNotIn('android.permission.READ_MEDIA_IMAGES', permissions)
        self.assertNotIn('android.permission.READ_MEDIA_VISUAL_USER_SELECTED', permissions)

    def test_cancelled_single_selection_does_not_start_loading_or_crop(self):
        callback = self.profile.split('registerForActivityResult(ActivityResultContracts.PickVisualMedia())', 1)[1]
        callback = callback.split('private val viewModel', 1)[0]
        self.assertLess(callback.index('if (sourceUri != null)'), callback.index('Glide.with(this)'))
        background_callback = self.background.split('registerForActivityResult(ActivityResultContracts.PickVisualMedia())', 1)[1].split('var wallpapers', 1)[0]
        self.assertLess(background_callback.index('if (uri != null)'), background_callback.index('launchUCrop(uri)'))

    def test_only_content_uris_reach_generic_loaders(self):
        profile_callback = self.profile.split('registerForActivityResult(ActivityResultContracts.PickVisualMedia())', 1)[1].split('private val viewModel', 1)[0]
        self.assertLess(profile_callback.index('if (!sourceUri.isPickerContentUri())'), profile_callback.index('Glide.with(this)'))
        self.assertLess(profile_callback.index('return@registerForActivityResult'), profile_callback.index('Glide.with(this)'))
        background_callback = self.background.split('registerForActivityResult(ActivityResultContracts.PickVisualMedia())', 1)[1].split('var wallpapers', 1)[0]
        self.assertLess(background_callback.index('if (uri.isPickerContentUri())'), background_callback.index('launchUCrop(uri)'))
        self.assertIn('PickerUriPolicy.isAllowed(scheme, authority)', self.adapter)
        self.assertIn('resultSet.filter(Uri::isPickerContentUri)', self.adapter)

    def test_crop_uses_app_files_instead_of_passing_external_uri_through(self):
        self.assertIn('.asFile()\n                    .load(sourceUri)', self.profile)
        self.assertIn('val sourceFileUri = Uri.fromFile(resource)', self.profile)
        self.assertIn('File(cacheDir, "cropped_portrait")', self.profile)
        self.assertIn('UCrop.of(sourceFileUri, destUri)', self.profile)
        self.assertIn('ImageUtil.bitmapToFile(result.bitmap, File(cacheDir, "origin_background.jpg"))', self.background)
        self.assertIn('File(filesDir, "cropped_background.jpg")', self.background)
        self.assertIn('UCrop.of(sourceFileUri, destUri)', self.background)

    def test_cancelled_or_malformed_crop_cannot_commit_output(self):
        profile_result = self.profile.split('private val uCropLauncher', 1)[1].split('private val pickImageLauncher', 1)[0]
        self.assertLess(profile_result.index('it.resultCode == Activity.RESULT_OK'), profile_result.index('UploadPortrait'))
        self.assertLess(profile_result.index('it.data?.let(UCrop::getOutput) != null'), profile_result.index('UploadPortrait'))
        background_result = self.background.split('override fun onActivityResult', 1)[1].split('private fun refreshWallpapers', 1)[0]
        self.assertIn('resultCode == Activity.RESULT_OK && requestCode == UCrop.REQUEST_CROP', background_result)
        self.assertLess(background_result.index('if (outputUri != null)'), background_result.index('mUri = outputUri'))
        self.assertNotIn('data!!', profile_result + background_result)

    def test_unreadable_uri_and_crop_errors_have_user_feedback(self):
        self.assertIn('override fun onLoadFailed(errorDrawable: Drawable?)', self.profile)
        self.assertIn('toastShort(R.string.text_load_failed)', self.profile)
        self.assertIn('result is LoadResult.Error', self.background)
        self.assertIn('toastShort(R.string.text_load_failed)', self.background)

    def test_legacy_adapter_delegates_fallback_to_androidx(self):
        # AndroidX owns capability detection and ACTION_OPEN_DOCUMENT fallback.
        self.assertIn('PickVisualMedia().createIntent(context, request)', self.adapter)
        self.assertIn('PickMultipleVisualMedia(input.maxItems).createIntent(context, request)', self.adapter)
        self.assertIn('PickVisualMedia.SingleMimeType(type.mimeType)', self.adapter)
        self.assertNotIn('MediaStore.ACTION_PICK_IMAGES', self.adapter)
        self.assertNotIn('Build.VERSION', self.adapter)

    def test_reselection_resets_only_the_launchers_own_request(self):
        self.assertIn('registerForActivityResult(PickMediasContract())', self.adapter)
        self.assertIn('private class PickMediasContract', self.adapter)
        self.assertNotIn('object PickMediasContract', self.adapter)
        self.assertIn('currentRequest = input', self.adapter)
        parse = self.adapter.split('override fun parseResult', 1)[1]
        self.assertLess(parse.index('currentRequest = null'), parse.index('if (request == null'))
        self.assertIn('resultCode != Activity.RESULT_OK || intent == null', parse)
        self.assertIn('PickMediasResult(request?.id.orEmpty(), emptyList())', parse)

    def test_document_fallback_results_are_deduplicated_and_bounded(self):
        self.assertIn('LinkedHashSet<Uri>()', self.adapter)
        self.assertIn('data?.let(resultSet::add)', self.adapter)
        self.assertIn('clip.getItemAt(i).uri?.let(resultSet::add)', self.adapter)
        self.assertIn('intent.getClipDataUris().take(request.maxItems)', self.adapter)
        self.assertIn('require(maxItems > 0)', self.adapter)

    def test_matisse_and_obsolete_preference_are_removed(self):
        for file in JAVA.rglob('*'):
            if file.suffix in ('.kt', '.java'):
                with self.subTest(file=str(file.relative_to(JAVA))):
                    content = file.read_text()
                    self.assertNotIn('com.zhihu.matisse', content)
                    self.assertNotIn('doNotUsePhotoPicker', content)
        self.assertNotIn('matisse', (ROOT / 'gradle/libs.versions.toml').read_text().lower())
        self.assertNotIn('matisse', (ROOT / 'app/build.gradle.kts').read_text().lower())
        self.assertNotIn('com.zhihu.matisse', (ROOT / 'app/proguard-rules.pro').read_text())
        image_util = source('utils/ImageUtil.kt')
        self.assertIn('var mimeType = "image/jpeg"', image_util)
        self.assertIn('mimeType = "image/gif"', image_util)

    def test_old_download_permissions_and_publication_boundary_remain(self):
        manifest = ET.parse(ROOT / 'app/src/main/AndroidManifest.xml').getroot()
        permissions = {item.get(ANDROID + 'name'): item.get(ANDROID + 'maxSdkVersion')
                       for item in manifest.findall('uses-permission')}
        self.assertEqual('28', permissions['android.permission.WRITE_EXTERNAL_STORAGE'])
        self.assertEqual('32', permissions['android.permission.READ_EXTERNAL_STORAGE'])
        self.assertIn('PermissionUtils.WRITE_EXTERNAL_STORAGE', source('utils/ImageUtil.kt'))
        self.assertIn('val enabled: Boolean = false', source('security/PublicationPolicy.kt'))
        self.assertIn('if (!PublicationPolicy.enabled)', source('ui/page/reply/ReplyPage.kt'))


if __name__ == '__main__':
    unittest.main()
