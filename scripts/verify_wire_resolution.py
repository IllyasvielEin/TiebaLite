#!/usr/bin/env python3
"""Verify selected Gradle Wire runtime headers, not just requested coordinates."""
from pathlib import Path
import re
import sys
import tomllib


def verify(report, expected):
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)', expected)
    if not match or not (6, 4, 5) <= tuple(map(int, match.groups())) < (7, 0, 0):
        raise ValueError('Expected a reviewed patched Wire 6.x version')
    if 'FAILED' in report:
        raise ValueError('Dependency resolution contains failures')
    # dependencyInsight lists selected components without tree prefixes. Requested
    # versions with " -> " are deliberately excluded from this strict expression.
    selected = re.findall(
        r'^com\.squareup\.wire:(wire-runtime(?:-jvm)?):(\d+\.\d+\.\d+)'
        r'(?:[ \t]+\([^\n]*\))?[ \t]*$', report, re.MULTILINE)
    if not selected or any(version != expected for _, version in selected):
        raise ValueError('Selected Wire runtime does not match the patched catalog pin')
    return sorted(set(selected))


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    expected = tomllib.loads((root / 'gradle/libs.versions.toml').read_text())['versions']['wire']
    selected = verify(Path(sys.argv[1]).read_text(), expected)
    print('Verified selected Wire runtime: ' + ', '.join(f'{name}:{version}' for name, version in selected))
