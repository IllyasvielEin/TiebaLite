#!/usr/bin/env python3
"""Install only the owner's approved SDK packages using the runner's SDK manager.

SDK terms: https://developer.android.com/studio/terms
Never runs the blanket --licenses command or changes KVM/system permissions.
"""
import argparse
from pathlib import Path
import os
import subprocess

BASE = ('platforms;android-37.0', 'build-tools;36.0.0', 'platform-tools')
IMAGES = {'emulator35': 'system-images;android-35;google_apis;x86_64',
          'emulator37': 'system-images;android-37.0;google_apis;x86_64'}


def packages(mode):
    if mode == 'build':
        return BASE
    if mode in IMAGES:
        return BASE + ('emulator', IMAGES[mode])
    raise ValueError('Unsupported SDK package scope')


def ensure(root, mode, run=subprocess.run):
    root = Path(root).resolve()
    manager = root / 'cmdline-tools/latest/bin/sdkmanager'
    if not manager.is_file() or not os.access(manager, os.X_OK):
        raise RuntimeError('Official preinstalled SDK command-line tools are required')
    selected = packages(mode)
    # This prompt input applies only to these fixed packages, under the owner's
    # explicit SDK-terms grant. It does not accept every installed SDK license.
    run([str(manager), '--sdk_root=' + str(root), '--channel=0', '--install', *selected],
        input='y\n' * 8, text=True, check=True, timeout=1200)
    required = [root / 'platforms/android-37.0/android.jar',
                root / 'build-tools/36.0.0/aapt2',
                root / 'build-tools/36.0.0/apksigner',
                root / 'build-tools/36.0.0/zipalign',
                root / 'licenses/android-sdk-license']
    if mode in IMAGES:
        required += [root / 'emulator/emulator', root / 'platform-tools/adb',
                     root.joinpath(*IMAGES[mode].split(';')) / 'package.xml']
    for path in required:
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError('Required SDK evidence missing: ' + str(path.relative_to(root)))
    print('Approved SDK package scope ready: ' + ', '.join(selected))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('build', 'emulator35', 'emulator37'))
    args = parser.parse_args()
    sdk_root = os.environ.get('ANDROID_HOME')
    if not sdk_root:
        raise SystemExit('ANDROID_HOME is required')
    ensure(sdk_root, args.mode)
