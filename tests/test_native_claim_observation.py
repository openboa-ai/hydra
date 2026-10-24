"""Valid explicit legacy decisions survive unrelated profile and repository data."""
import copy
import unittest

from hydra_sdlc.public_decisions import context_basis, prepare_context, receipt_body
import test_continue_boundary as cleanup_fixture
import test_native_decision_resume as fixture
import test_public_decisions as wire


class NativeClaimObservationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.NativeDecisionResumeTests.asyncSetUp
    close_pending = cleanup_fixture.ContinueBoundaryTests.close_pending

    def manual(self):
        self.controller.decision_source = None
        self.transport.rows = self.transport.rows[:1]
        self.transport.direct = {1: copy.deepcopy(self.transport.rows[0])}
        for identifier, body in ((102, f'hydra: decision {wire.ATTEMPT} context\nKeep the accepted manual decision.'),
                                 (103, f'hydra: decision {wire.ATTEMPT} resolved')):
            self.transport.add(identifier, body)
            self.transport.rows[-1]['user'] = {'login': 'operator', 'id': 42}
            self.transport.direct[identifier] = copy.deepcopy(self.transport.rows[-1])

    async def test_profile_metadata_change_does_not_replace_the_service_principal(self):
        self.manual()
        original = self.transport.__call__
        def metadata(method, path, payload):
            value = original(method, path, payload)
            if path == '/user':
                value['followers'] = self.transport.identity_reads
            return value
        self.github.transport = metadata
        self.addAsyncCleanup(self.close_pending)
        result = await self.controller.begin(self.url)
        self.assertEqual(result['action'], 'native_task', result)
        self.assertIn('Keep the accepted manual decision.', result['prompt'])

    async def test_other_repository_receipt_does_not_block_an_explicit_manual_decision(self):
        self.manual()
        basis = context_basis(self.chosen.context)
        basis['key']['repository_id'] = 124
        self.transport.add(104, receipt_body(prepare_context('A different repository decision.', basis)))
        self.addAsyncCleanup(self.close_pending)
        result = await self.controller.begin(self.url)
        self.assertEqual(result['action'], 'native_task', result)
        self.assertNotEqual(result['attempt_id'], wire.RESUME)
        self.assertIn('Keep the accepted manual decision.', result['prompt'])
