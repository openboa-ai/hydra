"""P14-R3: settle known partial effects before authorizing another effect."""
import copy
import unittest
from unittest.mock import patch

import test_native_publication as fixture


class PublicationPartialReconciliation(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.NativePublicationTests.asyncSetUp
    new_controller = fixture.NativePublicationTests.new_controller
    result = fixture.NativePublicationTests.result
    command = fixture.NativePublicationTests.command
    checkpoint = fixture.NativePublicationTests.checkpoint
    real_git_assignment = fixture.NativePublicationTests.real_git_assignment
    candidate = fixture.NativePublicationTests.candidate
    verification_command = fixture.NativePublicationTests.verification_command
    verification_grant = fixture.NativePublicationTests.verification_grant
    call = fixture.NativePublicationTests.call
    finish_command = fixture.NativePublicationTests.finish_command
    reviewed = fixture.NativePublicationTests.reviewed
    publication_command = fixture.NativePublicationTests.publication_command
    publication_grant = fixture.NativePublicationTests.publication_grant
    publish = fixture.NativePublicationTests.publish

    async def test_restart_settles_observed_pr_without_reconstructing_lost_review_proof(self):
        candidate = await self.reviewed()
        command = self.publication_command(candidate)
        self.gh.transform_observation = lambda value: {**value, 'provider_comments': []}
        self.gh.lose_pr = True
        unavailable = True
        pulls = self.gh.pulls
        def read_pr(*args):
            if self.gh.pr is not None and unavailable:
                raise RuntimeError('Synthetic read unavailable after actual PR creation')
            return pulls(*args)
        with patch.object(self.gh, 'pulls', side_effect=read_pr):
            first = await self.publish(command)
            self.assertEqual(first['request']['outcome'], 'unknown', first)
            self.assertEqual(self.gh.note['pending_action'], 'upsert_pr')
            unavailable = False
            self.controller = self.new_controller()
            self.controller.runner.operations = self.control
            self.assertEqual(self.controller.runner.verified_heads, set())
            restored = await self.publish(command)
        self.assertEqual(restored['request']['outcome'], 'waiting', restored)
        self.assertEqual(restored['request']['receipt']['stage'], 'pr_ready')
        self.assertIsNone(self.gh.note['pending_action'], 'A confirmed PR must not remain an unresolved write')
        self.assertEqual(self.gh.note['pr_number'], self.gh.pr['number'])
        self.assertEqual(self.gh.note['phase'], 'review_wait')
        self.assertEqual(self.controller.runner.verified_heads, set(), 'Reconciliation does not recreate candidate proof')
        self.assertEqual(len(self.pushes), 1)
        self.assertEqual(len([row for row in self.gh.writes if row[0] == 'pr']), 1)
        self.assertEqual([row for row in self.gh.writes if row[0] == 'request_review'], [])
        self.assertEqual(self.counter.read_text(), '1')

    async def test_one_lost_review_request_is_settled_before_the_other_kind_is_sent(self):
        candidate = await self.reviewed()
        command = self.publication_command(candidate)
        hidden = False
        self.gh.transform_observation = lambda value: {**value,
            'provider_comments': [] if hidden else copy.deepcopy(self.gh.extra_comments)}
        request = self.gh.request_review
        lost = False
        def requested(*args, **kwargs):
            nonlocal lost
            request(*args, **kwargs)
            kind = kwargs['kind']
            self.gh.extra_comments.append({'id': 901 if kind == 'code' else 902,
                'user': {'id': 11, 'login': 'openboa', 'type': 'User'},
                'body': f'<!-- hydra-review-request:v1 head={candidate["head"]} kind={kind} -->'})
            if kind == 'code' and not lost:
                lost = True
                raise RuntimeError('Synthetic code-request ACK loss after the actual write')
        with patch.object(self.gh, 'request_review', side_effect=requested):
            first = await self.publish(command)
            self.assertEqual(first['request']['outcome'], 'waiting', first)
            second = await self.publish(command)
            self.assertNotEqual(second['request']['outcome'], 'applied', second)
            self.assertTrue(lost)
            hidden = True
            uncertain = await self.publish(command)
            self.assertEqual(uncertain['request']['outcome'], 'unknown', uncertain)
            self.assertEqual([row[1] for row in self.gh.writes if row[0] == 'request_review'], ['code'])
            hidden = False
            recovered = await self.publish(command)
        self.assertEqual(recovered['request']['outcome'], 'applied', recovered)
        self.assertEqual(recovered['request']['receipt']['stage'], 'publication_ready')
        self.assertEqual([row[1] for row in self.gh.writes if row[0] == 'request_review'], ['code', 'security'])
        self.assertIsNone(self.gh.note['pending_action'])
        self.assertEqual(self.gh.note['phase'], 'review_wait')
        self.assertEqual(len(self.pushes), 1)
        self.assertEqual(len([row for row in self.gh.writes if row[0] == 'pr']), 1)
        self.assertEqual(self.counter.read_text(), '1')
