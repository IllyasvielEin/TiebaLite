#!/usr/bin/env python3
"""Write allowlisted source/toolchain metadata, never the process environment."""
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tomllib

root = Path(__file__).resolve().parents[1]
versions = tomllib.loads((root / 'gradle/libs.versions.toml').read_text())['versions']
wrapper = (root / 'gradle/wrapper/gradle-wrapper.properties').read_text()
android = (root / 'app/build.gradle.kts').read_text()
metadata = {
    'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
    'working_tree_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, text=True)),
    'repository': os.environ.get('GITHUB_REPOSITORY'),
    'run_id': os.environ.get('GITHUB_RUN_ID'),
    'run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
    'signing': 'unsigned',
    'artifact_label': 'UNSIGNED-EXPERIMENTAL-not-login-validated',
    'full_lint_status': 'not yet available at archive time; consult workflow and validation reports',
    'gradle': re.search(r'gradle-([0-9.]+)-bin\.zip', wrapper).group(1),
    'agp': versions['agp'],
    'kotlin': versions['kotlin'],
    'ksp': versions['ksp'],
    'java': subprocess.check_output(['java', '-version'], stderr=subprocess.STDOUT, text=True).strip(),
    'compile_sdk': int(re.search(r'compileSdk\s*=\s*(\d+)', android).group(1)),
    'build_tools': re.search(r'buildToolsVersion\s*=\s*"([^"]+)"', android).group(1),
}
Path(sys.argv[1]).write_text(json.dumps(metadata, indent=2) + '\n')
