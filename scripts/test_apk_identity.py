import unittest
from verify_apk_identity import verify

BASE = """package: name='io.github.illyasvielein.tiebalite' versionCode='1'
sdkVersion:'35'
targetSdkVersion:'37'
application-label:'贴吧 Lite'
uses-permission: name='android.permission.INTERNET'
"""


class ApkIdentityTest(unittest.TestCase):
    def test_expected_manifest(self):
        verify(BASE)

    def test_changed_identity_or_sdk_or_label_rejected(self):
        for before, after in [('io.github.illyasvielein.tiebalite', 'com.huanchengfly.tieba.post'),
                              ("sdkVersion:'35'", "sdkVersion:'23'"),
                              ("targetSdkVersion:'37'", "targetSdkVersion:'36'"),
                              ('贴吧 Lite', 'Unexpected label')]:
            with self.subTest(before=before), self.assertRaises(ValueError):
                verify(BASE.replace(before, after))

    def test_removed_permissions_rejected(self):
        for permission in ['READ_MEDIA_IMAGES', 'READ_MEDIA_VISUAL_USER_SELECTED',
                           'REQUEST_INSTALL_PACKAGES', 'READ_PHONE_STATE']:
            with self.subTest(permission=permission), self.assertRaises(ValueError):
                verify(BASE + f"uses-permission: name='android.permission.{permission}'\n")

    def test_maximum_sdk_rejected(self):
        with self.assertRaises(ValueError):
            verify(BASE + "maxSdkVersion:'37'\n")

    def test_missing_evidence_rejected(self):
        with self.assertRaises(ValueError):
            verify('')


if __name__ == '__main__':
    unittest.main()
