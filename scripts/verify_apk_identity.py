#!/usr/bin/env python3
"""Check actual compiled APK manifest evidence emitted by official aapt2 dump badging."""
from pathlib import Path
import re
import sys


def verify(text):
    required = {
        r"(?m)^package: name='([^']+)'": 'io.github.illyasvielein.tiebalite',
        r"(?m)^sdkVersion:'([^']+)'": '35',
        r"(?m)^targetSdkVersion:'([^']+)'": '37',
        r"(?m)^application-label:'([^']+)'": '贴吧 Lite',
    }
    for pattern, expected in required.items():
        found = re.findall(pattern, text)
        if found != [expected]:
            raise ValueError('APK identity/SDK/label does not match the approved edition')
    if re.search(r'(?mi)^maxSdkVersion:', text):
        raise ValueError('APK unexpectedly declares a maximum supported SDK')
    forbidden = {'android.permission.READ_MEDIA_IMAGES', 'android.permission.READ_MEDIA_VISUAL_USER_SELECTED',
                 'android.permission.REQUEST_INSTALL_PACKAGES', 'android.permission.READ_PHONE_STATE'}
    permissions = set(re.findall(r"(?m)^uses-permission[^:]*: name='([^']+)'", text))
    if permissions & forbidden:
        raise ValueError('APK contains a removed sensitive permission')


if __name__ == '__main__':
    verify(Path(sys.argv[1]).read_text())
    print('Compiled APK identity, SDK range and removed-permission checks passed')
