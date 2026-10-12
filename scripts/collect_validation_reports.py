#!/usr/bin/env python3
"""Collect only known text reports; scrub token-shaped strings without reading secrets."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / 'out/validation-reports'
PATTERNS = (
    'app/build/reports/lint-results-release.html',
    'app/build/reports/lint-results-release.xml',
    'app/build/reports/lint-results-release.txt',
    'app/build/reports/lint-results-release-fatal.html',
    'app/build/reports/lint-results-release-fatal.xml',
    'app/build/intermediates/lint_intermediate_text_report/release/**/lint-results-*.txt',
    'app/build/reports/tests/testReleaseUnitTest/**/*',
    'app/build/test-results/testReleaseUnitTest/*.xml',
)


def sanitize(text):
    text = re.sub(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b',
                  '[REDACTED_GITHUB_TOKEN]', text)
    return re.sub(r'(?i)(\bBDUSS(?:_BFESS)?\s*[=:]\s*[\"\x27]?)[A-Za-z0-9_~.%-]{20,}',
                  r'\1[REDACTED_SESSION_TOKEN]', text)


def main():
    count = 0
    for pattern in PATTERNS:
        for source in sorted(ROOT.glob(pattern)):
            if source.is_symlink() or not source.is_file():
                continue
            if source.suffix not in {'.html', '.xml', '.txt', '.css', '.js'}:
                continue
            destination = DESTINATION / source.relative_to(ROOT / 'app/build')
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(sanitize(source.read_text(encoding='utf-8')),
                                   encoding='utf-8')
            count += 1
    print(f'Collected {count} allowlisted validation report files')


if __name__ == '__main__':
    assert sanitize('ghp_' + 'a' * 36) == '[REDACTED_GITHUB_TOKEN]'
    assert sanitize('BDUSS=' + 'a' * 40) == 'BDUSS=[REDACTED_SESSION_TOKEN]'
    assert sanitize('MissingPermission: MobileInfoUtil.java:20') == 'MissingPermission: MobileInfoUtil.java:20'
    main()
