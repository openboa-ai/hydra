"""Actual paired producer and bound-consumer qualification, with one shared corpus."""
import asyncio
import copy
import importlib.util
import json
from pathlib import Path
import unittest

from hydra_sdlc import projection as p

EMITTER_PATH = Path(__file__).parent / 'fixtures/control-v3/emit_delegated_receipts.py'
spec = importlib.util.spec_from_file_location('delegated_receipt_vectors', EMITTER_PATH)
emitter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(emitter)


class DelegatedDecisionWireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.originals = asyncio.run(emitter.originals())
        cls.rows = emitter.vectors(cls.originals)
        cls.matrix = json.loads(emitter.MATRIX_PATH.read_text())

    def test_actual_producer_tags_only_authenticated_pair_results(self):
        for name, value in self.originals.items():
            with self.subTest(base=name):
                receipt = value['request']['receipt']
                self.assertEqual(value['request']['outcome'], 'applied', value)
                self.assertEqual(receipt.get('profile'), 'codex_delegated_v1',
                    'An actual v2 pair/root result must identify its qualified producer')
                self.assertNotIn('handoff', value)
                self.assertNotIn('reply_profile', value)
        decision = self.originals['decision']['request']
        receipt = decision['receipt']
        self.assertEqual(receipt['source_attempt'], emitter.ATTEMPT)
        self.assertNotEqual(receipt['resume_attempt'], receipt['source_attempt'])
        self.assertEqual(receipt['round'], 1)
        self.assertEqual(receipt['intent_ref'], receipt['context_ref'])
        self.assertNotEqual(receipt['context_ref'], receipt['resolved_ref'])
        self.assertEqual(receipt['context_ref'],
            {'source': 'github', 'kind': 'issue_comment', 'id': 'example/product/comments/100'})
        self.assertEqual(receipt['resolved_ref'],
            {'source': 'github', 'kind': 'issue_comment', 'id': 'example/product/comments/101'})
        for field in ('context_ref', 'resolved_ref'):
            self.assertIn(receipt[field], decision['effect_refs'])
        source = emitter.progress(self.originals['decision'])
        self.assertEqual(source['value']['attempt_id'], emitter.ATTEMPT)
        self.assertEqual(source['value']['issue_ref'],
            {'source': 'github', 'kind': 'issue', 'id': '123:4'})
        recovered = self.originals['terminal_continuation']['request']['receipt']
        self.assertEqual(recovered['boundary'], 'existing_result_reconciled')
        self.assertEqual(recovered['attempt_id'], receipt['resume_attempt'])

    def test_generated_semantic_corpus_equals_saved_cross_language_bytes(self):
        self.assertTrue(self.matrix['cases'], 'Generate the committed corpus from the final actual producer')
        self.assertEqual(self.rows, self.matrix['cases'])
        self.assertEqual(len({row['name'] for row in self.rows}), len(self.rows))

    def test_closed_receipt_shapes_follow_fixed_independent_flags(self):
        for row in self.rows:
            with self.subTest(case=row['name']):
                value = p.read_json(row['wire'].encode())
                try:
                    p.command_result(value['request'], p.observations_index(value['observations']))
                    accepted = True
                except p.ProjectionError:
                    accepted = False
                self.assertEqual(accepted, row['schema_accepted'])

    def test_standard_source_qualification_preserves_legacy_and_private_boundaries(self):
        for row in self.rows:
            with self.subTest(case=row['name']):
                try:
                    p.standard_reply(p.read_json(row['wire'].encode()))
                    reason = None
                except p.ProjectionError as exc:
                    reason = exc.reason
                    self.assertNotIn(emitter.PRIVATE_CANARY, str(exc))
                self.assertEqual(reason, row['standard_reason'])

    def test_normalization_changes_only_declared_runtime_digests_and_timestamps(self):
        for original in self.originals.values():
            expected = copy.deepcopy(original)
            for key, constant in emitter.NORMALIZED_RUNTIME.items():
                if expected['runtime'][key] is not None:
                    expected['runtime'][key] = constant
            for observation in expected['observations']:
                for key in ('observed_at', 'last_attempt_at'):
                    if observation[key] is not None:
                        observation[key] = emitter.NORMALIZED_TIMESTAMP
            self.assertEqual(emitter.normalize(original), expected)
            self.assertEqual(emitter.normalize(original)['request'], original['request'])
        self.assertLess(len(json.dumps(self.rows).encode()), 4_194_304)
        for row in self.rows:
            self.assertLess(len(row['wire'].encode()), p.MAX_BYTES)
