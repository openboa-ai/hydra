"""One CP input/oracle set drives actual producer bytes and both native consumers."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import unittest

from hydra_sdlc import projection as p

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/control-v3'


class ControlWireContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run([sys.executable, '-I', str(FIXTURE / 'emit_wire.py')],
                                capture_output=True, timeout=60)
        if result.returncode or len(result.stdout) > 4_194_304:
            raise AssertionError('Actual bounded producer fixture did not complete')
        cls.vectors = json.loads(result.stdout)

    def test_shared_vectors_pin_contract_and_include_actual_source_cli_and_legacy(self):
        inputs = json.loads((FIXTURE / 'inputs.json').read_bytes())
        self.assertEqual(inputs['contract']['revision'], 8)
        self.assertEqual(hashlib.sha256((ROOT / inputs['contract']['path']).read_bytes()).hexdigest(),
                         inputs['contract']['sha256'])
        self.assertEqual(len({v['name'] for v in self.vectors}), len(inputs['cases']))
        self.assertTrue(any(v['name'] == 'actual-cli-source-assembly' and v['accepted'] for v in self.vectors))
        self.assertTrue(any(v['profile'] == 'legacy' and v['accepted'] for v in self.vectors))

    def test_actual_encoder_bytes_obey_independent_acceptance_and_field_oracles(self):
        for vector in self.vectors:
            with self.subTest(case=vector['name']):
                self.assertEqual(vector['producer_rejected'], not vector['accepted'])
                if not vector['accepted']:
                    with self.assertRaises(p.ProjectionError):
                        value = p.read_json(vector['wire'].encode())
                        (p.validate_frame if vector['profile'] == 'projection' else p.standard_reply)(value)
                    continue
                value = p.read_json(vector['wire'].encode())
                for expected in vector['expected']:
                    actual = value
                    for key in expected['path']:
                        actual = actual[key]
                    self.assertEqual(actual, expected['value'])
                self.assertNotIn('SYNTHETIC_UNTRUSTED_EXTRA_CANARY', vector['wire'])

    def test_source_cli_emits_visible_issue_without_creating_native_or_effect_authority(self):
        vector = next(v for v in self.vectors if v['name'] == 'actual-cli-source-assembly')
        value = p.read_json(vector['wire'].encode())
        self.assertEqual(value['schema_version'], 3)
        self.assertEqual(len(value['projects']), 2)
        self.assertEqual(len(value['work']), 1)
        work = value['work'][0]
        self.assertEqual(work['readiness']['value']['authority'], 'unknown')
        self.assertIsNone(work['next_action']['value'])
        self.assertIsNone(work['decision']['question']['value'])
        self.assertIsNone(work['execution']['value'])
        self.assertIsNone(value['request'])
