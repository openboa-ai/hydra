"""Declared wire-fixture provenance must track the current accepted contract."""
import hashlib
import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = 'docs/engineering/mvp/contracts/control-plane.md'


class ControlFixtureContractTests(unittest.TestCase):
    def test_declared_control_contract_pins_match_current_source(self):
        data = (ROOT / CONTRACT).read_bytes()
        expected_digest = hashlib.sha256(data).hexdigest()
        revision = re.search(r'^Status:.*\brevision (\d+)\b', data.decode(), re.MULTILINE)
        self.assertIsNotNone(revision)
        declarations = 0
        for path in sorted((ROOT / 'tests/fixtures/control-v3').glob('*.json')):
            value = json.loads(path.read_text())
            if not isinstance(value, dict) or 'contract' not in value:
                continue
            declarations += 1
            with self.subTest(fixture=path.name):
                contract = value['contract']
                self.assertIsInstance(contract, dict)
                # Read only the fixed CP source above, never a fixture's path.
                self.assertEqual(contract['path'], CONTRACT)
                self.assertEqual(contract['sha256'], expected_digest)
                if 'revision' in contract:
                    self.assertEqual(type(contract['revision']), int)
                    self.assertEqual(contract['revision'], int(revision[1]))
        self.assertGreater(declarations, 0)
