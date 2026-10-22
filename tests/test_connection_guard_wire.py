"""A current mode snapshot cannot erase a project's connection guard."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

from hydra_sdlc import projection as p


class ConnectionGuardWireTests(unittest.TestCase):
    def test_actual_guard_producer_and_strict_decoder_preserve_independent_outcomes(self):
        script = Path(__file__).parent / 'fixtures/control-v3/emit_connection_guards.py'
        result = subprocess.run([sys.executable, '-I', str(script)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = json.loads(result.stdout)
        self.assertEqual(len(rows), 6)
        self.assertEqual(len({row['name'] for row in rows}), 6)
        for row in rows:
            with self.subTest(case=row['name']):
                if row['accepted']:
                    p.encode(p.read_json(row['wire'].encode()))
                else:
                    with self.assertRaises(p.ProjectionError):
                        p.encode(p.read_json(row['wire'].encode()))
