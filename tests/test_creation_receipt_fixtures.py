"""CP12 receipt data is independent of production source qualification."""
import importlib.util
import json
from pathlib import Path
import unittest
from hydra_sdlc import projection as p


path = Path(__file__).parent / 'fixtures/control-v3/emit_creation.py'
spec = importlib.util.spec_from_file_location('creation_receipt_vectors', path)
emitter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(emitter)


class CreationReceiptFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = emitter.vectors()

    def test_actual_registered_receipt_and_replay_keep_exact_effects(self):
        by_name = {row['name']: json.loads(row['wire']) for row in self.rows}
        first, replay = (by_name[name]['request'] for name in ('registered', 'registered_replay'))
        self.assertEqual(first['receipt'], replay['receipt'])
        self.assertEqual(first['receipt']['issue_ref'], {'source': 'github', 'kind': 'issue', 'id': '123:11'})
        self.assertEqual(first['receipt']['binding_ref'], {'source': 'github', 'kind': 'issue_comment', 'id': 'example/product/comments/201'})
        self.assertEqual(first['receipt']['create_key'], '33333333-3333-4333-8333-333333333333')
        for request in (first, replay):
            for key in ('issue_ref', 'binding_ref'):
                self.assertIn(request['receipt'][key], request['effect_refs'])

    def test_actual_unknown_and_partial_results_preserve_observed_effects(self):
        values = {row['name']: json.loads(row['wire'])['request'] for row in self.rows}
        for name in ('history_unavailable', 'partial_issue'):
            self.assertEqual(values[name]['outcome'], 'unknown')
            self.assertIsNone(values[name]['receipt'])
        self.assertEqual(values['history_unavailable']['effect_refs'], [])
        self.assertIn({'source': 'github', 'kind': 'issue', 'id': '123:11'}, values['partial_issue']['effect_refs'])

    def test_shared_matrix_matches_independent_data_oracles(self):
        self.assertTrue(self.rows)
        self.assertEqual(len({row['name'] for row in self.rows}), len(self.rows))
        for row in self.rows:
            with self.subTest(case=row['name']):
                value = p.read_json(row['wire'].encode())
                try:
                    p.command_result(value['request'], p.observations_index(value['observations']))
                    accepted = True
                except p.ProjectionError:
                    accepted = False
                self.assertEqual(accepted, row['schema_accepted'])

    def test_same_vectors_retain_exact_bound_source_reasons(self):
        for row in self.rows:
            with self.subTest(case=row['name']):
                try:
                    p.standard_reply(p.read_json(row['wire'].encode()))
                    reason = None
                except p.ProjectionError as exc:
                    reason = exc.reason
                self.assertEqual(reason, row['standard_reason'])

    def test_vectors_use_closed_public_payloads_and_bounded_bytes(self):
        self.assertLess(len(json.dumps(self.rows).encode()), 4_194_304)
        for row in self.rows:
            self.assertLess(len(row['wire'].encode()), p.MAX_BYTES)
            self.assertNotIn(emitter.fixture.CANARY, row['wire'])
            self.assertNotIn('isolated-creation-credential', row['wire'])
