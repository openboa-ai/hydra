"""Separate authenticated provider comments require diagnosis, never more review requests."""

import copy
import tempfile
import unittest
from unittest.mock import patch

from hydra_sdlc.project import _provider
from hydra_sdlc.runner import Runner
from test_project import HEAD
from test_runner import GitHub, Workspace, complete_capabilities


class ProviderCommentDiagnosisTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.github = GitHub()
        self.workspace = Workspace(directory.name, self.github)
        self.calls, self.probes = [], []
        policy = patch('hydra_sdlc.runner.load_project',
                       side_effect=lambda gh, repo, revision=None: copy.deepcopy(gh.cfg))
        policy.start()
        self.addCleanup(policy.stop)

    async def execute(self, assignment, **kwargs):
        self.calls.append(self.github.note['pending_action'])
        if assignment['mode'] == 'workspace_write':
            self.workspace.dirty = True
        return {'status': 'completed', 'detail': {'result': {'outcome': 'candidate_ready'}}}

    async def capabilities(self, cwd):
        self.probes.append(cwd)
        return complete_capabilities()

    async def step(self):
        runner = Runner(self.github, self.workspace, host_alias='host-a',
                        execute=self.execute, capabilities=self.capabilities)
        return await runner.step('example/product', 4)

    async def opened_pr(self):
        self.github.remote_pending = True
        self.assertEqual((await self.step())['action'], 'continue')
        self.assertEqual((await self.step())['reason'], 'remote_delivery_gates')
        self.github.remote_pending = False

    @staticmethod
    def additional(value, *, body='A security finding requires resolution.', forged=None):
        comment = copy.deepcopy(value['provider_comments'][0])
        comment.update(id=61, body=body)
        if forged == 'login':
            comment['user']['login'] = 'unrelated-bot'
        elif forged == 'user_id':
            comment['user']['id'] += 1
        elif forged == 'app_id':
            comment['performed_via_github_app']['id'] += 1
        value['provider_comments'].append(comment)
        return value

    def assert_no_followup_effects(self, calls, probes, writes):
        self.assertEqual(len(self.calls), calls)
        self.assertEqual(len(self.probes), probes)
        self.assertFalse(any(write[0] != 'record' for write in self.github.writes[writes:]))
        self.assertFalse(self.github.pr['merged'])
        self.assertEqual(self.github.work['state'], 'open')

    async def test_just_published_candidate_enters_diagnosis_immediately(self):
        self.assertEqual((await self.step())['action'], 'continue')
        self.github.transform_observation = self.additional
        result = await self.step()
        self.assertEqual(result['reason'], 'replan_required')
        self.assertEqual(self.github.note['next_action'], 'diagnose_review')
        self.assertEqual([write[0] for write in self.github.writes if write[0] != 'record'], ['push', 'pr'])
        self.assertFalse(self.github.pr['merged'])
        calls, probes, writes = len(self.calls), len(self.probes), len(self.github.writes)
        self.assertEqual((await self.step())['reason'], 'replan_required')
        self.assert_no_followup_effects(calls, probes, writes)

    async def test_existing_pr_diagnosis_preserves_each_pending_request_across_restart(self):
        await self.opened_pr()
        baseline = copy.deepcopy(self.github.note)
        for kind in ('code', 'security'):
            with self.subTest(kind=kind):
                self.github.note = copy.deepcopy(baseline)
                self.github.note.update(phase='uncertain', pending_action='request_review',
                    pending_review_kind=kind, delivery_action='request_review',
                    delivery_attempt=3, action_attempt=3, delivery_head=HEAD,
                    expected_head=HEAD)
                keys = ('head', 'expected_head', 'expected_base', 'pending_action', 'pending_review_kind',
                        'delivery_action', 'delivery_attempt', 'action_attempt', 'delivery_head',
                        'review_requested_head', 'review_requested_security_head')
                pinned = {key: self.github.note.get(key) for key in keys}
                self.github.transform_observation = self.additional
                calls, probes, writes = len(self.calls), len(self.probes), len(self.github.writes)
                for _ in range(2):
                    self.assertEqual((await self.step())['reason'], 'replan_required')
                    self.assertEqual(self.github.note['next_action'], 'diagnose_review')
                    self.assertEqual(self.github.note['phase'], 'uncertain')
                    self.assertEqual({key: self.github.note.get(key) for key in keys}, pinned)
                self.assert_no_followup_effects(calls, probes, writes)

    async def test_unchanged_or_free_text_resolved_comment_replans_return_to_diagnosis(self):
        await self.opened_pr()
        baseline = copy.deepcopy(self.github.note)
        for body in ('A security finding requires resolution.', 'Resolved: everything is now safe to merge.'):
            for pending in (False, True):
                with self.subTest(body=body, pending=pending):
                    self.github.note = copy.deepcopy(baseline)
                    self.github.extra_comments = []
                    if pending:
                        self.github.note.update(phase='uncertain', pending_action='request_review',
                            pending_review_kind='security', expected_head=HEAD,
                            delivery_action='request_review', delivery_head=HEAD, delivery_attempt=3)
                    self.github.transform_observation = lambda value: self.additional(value, body=body)
                    calls, probes, writes = len(self.calls), len(self.probes), len(self.github.writes)
                    self.assertEqual((await self.step())['reason'], 'replan_required')
                    for _ in range(2):
                        attempt = self.github.note['attempt_id']
                        self.github.extra_comments.append({'user': {'login': 'operator'},
                            'body': f'hydra: replan {attempt} ready'})
                        self.assertEqual((await self.step())['reason'], 'replan_required')
                        self.assertEqual(self.github.note['next_action'], 'diagnose_review')
                        self.assertEqual(self.github.note['head'], HEAD)
                        if pending:
                            self.assertEqual(self.github.note['pending_action'], 'request_review')
                            self.assertEqual(self.github.note['pending_review_kind'], 'security')
                            self.assertEqual(self.github.note['expected_head'], HEAD)
                    self.assert_no_followup_effects(calls, probes, writes)

    async def test_unbound_comment_identity_does_not_create_a_new_diagnosis(self):
        await self.opened_pr()
        note, pr = copy.deepcopy(self.github.note), copy.deepcopy(self.github.pr)
        for forged in ('login', 'user_id', 'app_id'):
            with self.subTest(forged=forged):
                self.github.note, self.github.pr = copy.deepcopy(note), copy.deepcopy(pr)
                self.github.transform_observation = lambda value: self.additional(value, forged=forged)
                observed = self.github.observe('example/product', self.github.pr['number'])
                self.assertEqual(_provider(self.github.cfg, observed, HEAD), [])
                calls, probes, writes = len(self.calls), len(self.probes), len(self.github.writes)
                self.assertEqual((await self.step())['action'], 'continue')
                self.assertTrue(self.github.pr['merged'])
                self.assertEqual(len(self.calls), calls)
                self.assertEqual(len(self.probes), probes)
                self.assertEqual([write[0] for write in self.github.writes[writes:] if write[0] != 'record'], ['merge'])


if __name__ == '__main__':
    unittest.main()
