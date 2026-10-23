"""P17 source facts preserve the v2 stopped default without exposing its path."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

from hydra_sdlc import projection as p


class ConnectionProjectionTests(unittest.TestCase):
    def test_actual_producer_defaults_match_independent_wire_oracles(self):
        script = Path(__file__).parent / 'fixtures/control-v3/emit_connection_defaults.py'
        result = subprocess.run([sys.executable, '-I', str(script)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = json.loads(result.stdout)
        self.assertEqual(len(rows), 9)
        self.assertEqual(len({row['name'] for row in rows}), 9)
        for row in rows:
            with self.subTest(case=row['name']):
                accepted = True
                try:
                    p.encode(p.read_json(row['wire'].encode()))
                except p.ProjectionError:
                    accepted = False
                self.assertEqual(accepted, row['accepted'])
