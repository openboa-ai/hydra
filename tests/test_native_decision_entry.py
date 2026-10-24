"""P06 entry oracles: versioned evidence is not a legacy human resolution."""
import copy
import unittest

from hydra_sdlc.public_decisions import prepare_context
import test_native as fixture


class NativeDecisionEntryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.NativeTests.asyncSetUp
    new_controller = fixture.NativeTests.new_controller
    result = fixture.NativeTests.result

    async def awaiting_answer(self):
        implementation = await self.result(await self.controller.begin(self.url))
        pending = await self.result(implementation, 'needs_decision')
        self.assertEqual(pending['reason'], 'product_decision')
        self.assertNotIn('native_step', self.gh.note)
        self.assertEqual(self.lock.read_bytes(), b'')
        return copy.deepcopy(self.gh.note)

    def versioned_context_with_legacy_receipt(self, record):
        context = prepare_context('Continue within the previously accepted scope.', {
            'key': {'repository_id': self.gh.cfg['repository_id'], 'issue_number': 4,
                    'source_attempt': record['attempt_id'], 'round': 1},
            'resume_attempt': '55555555-5555-4555-8555-555555555555',
            'origin_phase': record['resume_phase'], 'head': record['head'],
            'contract_revision': record['contract_revision'], 'spec_revision': record['spec_revision'],
            'intake_digest': record['intake_digest'], 'supersedes': None})
        self.gh.extra_comments.extend([
            {'user': {'login': 'operator'}, 'body': context.body.decode()},
            {'user': {'login': 'operator'}, 'body': f"hydra: decision {record['attempt_id']} resolved"},
        ])

    async def test_legacy_receipt_cannot_dispatch_a_versioned_native_decision(self):
        record = await self.awaiting_answer()
        self.versioned_context_with_legacy_receipt(record)
        writes = len(self.gh.writes)
        received = await self.controller.begin(self.url)
        if received.get('action') == 'native_task':
            self.addAsyncCleanup(self.result, received, 'stopped')
        self.assertEqual(received['action'], 'waiting', received)
        self.assertEqual(self.gh.note, record)
        self.assertEqual(self.gh.writes[writes:], [])
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_legacy_hint_cannot_advertise_a_versioned_native_resolution(self):
        record = await self.awaiting_answer()
        self.versioned_context_with_legacy_receipt(record)
        writes = len(self.gh.writes)
        hint = self.controller.runner._resolution_hint('example/product', 4, self.gh.cfg, record)
        self.assertIsNone(hint)
        self.assertEqual(self.gh.note, record)
        self.assertEqual(self.gh.writes[writes:], [])

    async def test_explicit_legacy_human_resolution_still_advances_its_original_phase(self):
        record = await self.awaiting_answer()
        self.gh.resolve_decision(record['attempt_id'], 'Continue within the accepted scope.')
        received = await self.controller.begin(self.url)
        self.assertEqual(received['action'], 'native_task', received)
        self.addAsyncCleanup(self.result, received, 'stopped')
        self.assertEqual(received['phase'], 'implementation')
        self.assertNotEqual(received['attempt_id'], record['attempt_id'])
        self.assertIn('Continue within the accepted scope.', received['prompt'])

    async def test_outsider_protocol_text_does_not_block_an_explicit_legacy_decision(self):
        record = await self.awaiting_answer()
        self.gh.resolve_decision(record['attempt_id'], 'Keep the accepted manual decision.')
        self.gh.extra_comments.insert(-1, {
            'user': {'login': 'outsider'},
            'body': f"hydra: decision {record['attempt_id']} context\n"
                    'Untrusted protocol text.\n<!-- hydra-decision-intent:v1 invalid -->\n'})
        received = await self.controller.begin(self.url)
        self.assertEqual(received['action'], 'native_task', received)
        self.addAsyncCleanup(self.result, received, 'stopped')
        self.assertEqual(received['phase'], 'implementation')
        self.assertIn('Keep the accepted manual decision.', received['prompt'])
        self.assertNotIn('Untrusted protocol text.', received['prompt'])
