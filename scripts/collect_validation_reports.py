#!/usr/bin/env python3
"""Collect only known text reports; scrub token-shaped strings without reading secrets."""
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = (
    'app/build/reports/lint-results-release.html',
    'app/build/reports/lint-results-release.xml',
    'app/build/reports/lint-results-release.txt',
    'app/build/reports/lint-results-release-fatal.html',
    'app/build/reports/lint-results-release-fatal.xml',
    'app/build/intermediates/lint_intermediate_text_report/release/**/lint-results-*.txt',
    'app/build/reports/tests/testReleaseUnitTest/**/*',
    'app/build/test-results/testReleaseUnitTest/*.xml',
    'app/build/reports/dependencies/release-runtime.txt',
    'app/build/reports/dependencies/wire-runtime.txt',
    'app/build/reports/apk/identity-badging.txt',
)


def sanitize(text):
    text = re.sub(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b',
                  '[REDACTED_GITHUB_TOKEN]', text)
    return re.sub(r'(?i)(\bBDUSS(?:_BFESS)?[\"\x27]?\s*[=:]\s*[\"\x27]?)[A-Za-z0-9_~.%-]{20,}',
                  r'\1[REDACTED_SESSION_TOKEN]', text)


def is_safe_within(path, root):
    """Reject traversal and every symlink component, including parent directories."""
    try:
        relative = path.relative_to(root)
        current = root
        if current.is_symlink():
            return False
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return False
        return path.resolve().is_relative_to(root.resolve())
    except (ValueError, OSError, RuntimeError):
        return False


def collect(root):
    destination_root = root / 'out/validation-reports'
    if not is_safe_within(destination_root, root):
        raise RuntimeError('Unsafe validation report destination')
    if destination_root.exists():
        shutil.rmtree(destination_root)
    destination_root.mkdir(parents=True)
    count = 0
    for pattern in PATTERNS:
        for source in sorted(root.glob(pattern)):
            if not is_safe_within(source, root) or not source.is_file():
                continue
            if source.suffix not in {'.html', '.xml', '.txt', '.css', '.js'}:
                continue
            try:
                contents = source.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                continue
            destination = destination_root / source.relative_to(root / 'app/build')
            if not is_safe_within(destination, destination_root):
                raise RuntimeError('Unsafe validation report path')
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(sanitize(contents), encoding='utf-8')
            count += 1
    return count


if __name__ == '__main__':
    assert sanitize('ghp_' + 'a' * 36) == '[REDACTED_GITHUB_TOKEN]'
    assert sanitize('BDUSS=' + 'a' * 40) == 'BDUSS=[REDACTED_SESSION_TOKEN]'
    assert sanitize('MissingPermission: MobileInfoUtil.java:20') == 'MissingPermission: MobileInfoUtil.java:20'
    print(f"Collected {collect(ROOT)} allowlisted validation report files")
