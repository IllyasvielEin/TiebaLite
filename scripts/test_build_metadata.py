#!/usr/bin/env python3
"""Regression test for build metadata's deliberately narrow data boundary."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class BuildMetadataTest(unittest.TestCase):
    def test_metadata_is_unsigned_and_does_not_dump_environment(self):
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ, GITHUB_REPOSITORY='example/learning',
                   GITHUB_RUN_ID='123', GITHUB_RUN_ATTEMPT='2',
                   TEST_SECRET='must-not-appear-in-artifact')
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'metadata.json'
            subprocess.run([sys.executable, str(root / 'scripts/build_metadata.py'),
                            str(output)], env=env, check=True)
            raw = output.read_text()
            metadata = json.loads(raw)
        self.assertNotIn(env['TEST_SECRET'], raw)
        self.assertNotIn('TEST_SECRET', raw)
        self.assertEqual(metadata['signing'], 'unsigned')
        self.assertEqual(metadata['repository'], 'example/learning')
        self.assertEqual(metadata['run_id'], '123')
        self.assertEqual(metadata['run_attempt'], '2')
        self.assertRegex(metadata['commit'], r'^[0-9a-f]{40}$')
        self.assertIsInstance(metadata['working_tree_dirty'], bool)
        self.assertEqual(set(metadata), {
            'commit', 'working_tree_dirty', 'repository', 'run_id', 'run_attempt',
            'signing', 'gradle', 'agp', 'kotlin', 'ksp', 'java', 'compile_sdk',
            'build_tools',
        })


if __name__ == '__main__':
    unittest.main()
