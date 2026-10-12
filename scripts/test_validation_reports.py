#!/usr/bin/env python3
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import tempfile
import unittest
from collect_validation_reports import collect, is_safe_within, sanitize


class ValidationReportsTest(unittest.TestCase):
    def test_partial_token_scrubbing_preserves_diagnostics(self):
        self.assertEqual(sanitize('ghp_' + 'a' * 36), '[REDACTED_GITHUB_TOKEN]')
        self.assertEqual(sanitize('"BDUSS":"' + 'a' * 40 + '"'),
                         '"BDUSS":"[REDACTED_SESSION_TOKEN]"')
        text = 'MissingPermission at MobileInfoUtil.java:20'
        self.assertEqual(sanitize(text), text)

    def test_leaf_and_ancestor_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real = root / 'real'
            real.mkdir()
            (real / 'report.txt').write_text('example')
            (root / 'link').symlink_to(real, target_is_directory=True)
            (root / 'leaf.txt').symlink_to(real / 'report.txt')
            self.assertTrue(is_safe_within(real / 'report.txt', root))
            self.assertFalse(is_safe_within(root / 'link/report.txt', root))
            self.assertFalse(is_safe_within(root / 'leaf.txt', root))
            self.assertFalse(is_safe_within(root.parent / 'outside.txt', root))

    def test_only_valid_reports_are_collected_and_stale_outputs_cleared(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reports = root / 'app/build/reports'
            reports.mkdir(parents=True)
            (reports / 'lint-results-release.txt').write_text('ghp_' + 'a' * 36)
            (reports / 'lint-results-release.html').write_bytes(b'\xff\xfe')
            (reports / 'unrelated.txt').write_text('not allowlisted')
            output = root / 'out/validation-reports'
            output.mkdir(parents=True)
            (output / 'stale.txt').write_text('old')
            self.assertEqual(collect(root), 1)
            self.assertFalse((output / 'stale.txt').exists())
            self.assertEqual((output / 'reports/lint-results-release.txt').read_text(),
                             '[REDACTED_GITHUB_TOKEN]')
            self.assertEqual(len(list(output.rglob('*.txt'))), 1)

    def test_symlink_destination_is_rejected_without_touching_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / 'retained'
            target.mkdir()
            (target / 'keep.txt').write_text('keep')
            (root / 'out').mkdir()
            (root / 'out/validation-reports').symlink_to(target, target_is_directory=True)
            with self.assertRaises(RuntimeError):
                collect(root)
            self.assertEqual((target / 'keep.txt').read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
