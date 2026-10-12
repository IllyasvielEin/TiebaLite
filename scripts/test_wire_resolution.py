#!/usr/bin/env python3
import sys
sys.dont_write_bytecode = True
import unittest
from verify_wire_resolution import verify


class WireResolutionTest(unittest.TestCase):
    def test_selected_headers_and_requested_old_versions_are_distinct(self):
        report = ('com.squareup.wire:wire-runtime-jvm:6.4.5\n'
                  '   Variant jvmRuntimeElements:\n'
                  'com.squareup.wire:wire-runtime-jvm:6.4.0 -> 6.4.5\n')
        self.assertEqual(verify(report, '6.4.5'), [('wire-runtime-jvm', '6.4.5')])

    def test_unpatched_or_differently_selected_runtime_fails(self):
        for report in ('com.squareup.wire:wire-runtime-jvm:6.4.0\n',
                       'com.squareup.wire:wire-runtime-jvm:6.4.6\n',
                       'com.squareup.wire:wire-runtime:6.4.5\ncom.squareup.wire:wire-runtime-jvm:6.4.0\n'):
            with self.subTest(report=report), self.assertRaises(ValueError):
                verify(report, '6.4.5')

    def test_no_selected_evidence_or_failed_resolution_fails(self):
        for report in ('', 'com.squareup.wire:wire-runtime:6.4.0 -> 6.4.5\n',
                       '+--- com.squareup.wire:wire-runtime:6.4.5\n',
                       'com.squareup.wire:wire-runtime:6.4.5\nFAILED\n'):
            with self.subTest(report=report), self.assertRaises(ValueError):
                verify(report, '6.4.5')

    def test_unreviewed_expected_version_fails(self):
        for version in ('6.4.4', '7.0.0', '6.4.+'):
            with self.subTest(version=version), self.assertRaises(ValueError):
                verify(f'com.squareup.wire:wire-runtime:{version}\n', version)


if __name__ == '__main__':
    unittest.main()
