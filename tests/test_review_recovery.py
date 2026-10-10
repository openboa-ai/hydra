"""Uncertain merges and terminal provider reviews retain actionable service state."""

import copy
import tempfile
import unittest
from unittest.mock import patch

from hydra_sdlc.runner import Runner
from test_project import MERGE
from test_runner import GitHub, Workspace, complete_capabilities


class ReviewRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.github = GitHub()
        self.workspace = Workspace(self.directory.name, self.github)
        self.calls = []
        self.merge_requests = []
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

    async def unknown_merge(self):
        await self.opened_pr()
        def fail_merge(repo, number, head):
            self.github.assert_intent('merge')
            self.merge_requests.append(head)
            raise RuntimeError('merge response unavailable')
        self.github.merge = fail_merge
        self.assertEqual((await self.step())['reason'], 'merge_unknown')
        self.assertEqual(self.github.note['pending_action'], 'merge')
        self.assertEqual(len(self.merge_requests), 1)

    async def held_merge(self, change):
        await self.unknown_merge()
        pinned = {key: self.github.note.get(key) for key in ('head', 'expected_head', 'expected_base')}
        calls, writes = len(self.calls), len(self.github.writes)
        self.github.transform_observation = change
        for _ in range(2):
            self.assertEqual((await self.step())['action'], 'waiting')
            self.assertEqual(self.github.note['phase'], 'uncertain')
            self.assertEqual(self.github.note['pending_action'], 'merge')
            self.assertEqual({key: self.github.note.get(key) for key in pinned}, pinned)
        self.assertEqual(len(self.calls), calls)
        self.assertEqual(len(self.merge_requests), 1)
        self.assertFalse(any(write[0] != 'record' for write in self.github.writes[writes:]))

    async def test_pending_merge_with_new_behind_state_never_integrates_or_retargets(self):
        def behind(value):
            value['pr']['mergeable_state'] = 'behind'
            value['pr']['base']['sha'] = 'e' * 40
            value['base_sha'] = 'e' * 40
            return value
        await self.held_merge(behind)

    async def test_pending_merge_with_new_finding_never_dispatches_correction(self):
        def finding(value):
            value['threads'] = [{'id': 'current-finding', 'isOutdated': False, 'isResolved': False,
                                 'comments': {'nodes': [{'databaseId': 901, 'author': {
                                     'login': self.github.cfg['review_provider']['login']}}]}}]
            value['inline_comments'] = [{'id': 901, 'body': 'Current-head finding', 'path': 'src/main.py', 'line': 1}]
            return value
        await self.held_merge(finding)

    async def test_matching_merge_readback_requires_post_checks_then_closes_without_repeat_merge(self):
        await self.unknown_merge()
        calls = len(self.calls)
        self.github.pr.update(merged=True, state='closed', merge_commit_sha=MERGE)
        original = self.github.observe_commit
        passing = False
        observed = []
        def observe_commit(repo, sha):
            observed.append(sha)
            value = original(repo, sha)
            if not passing:
                value['checks'][0]['conclusion'] = 'failure'
                value['runs'][0]['conclusion'] = 'failure'
            return value
        self.github.observe_commit = observe_commit
        self.assertEqual((await self.step())['reason'], 'post_merge_checks')
        self.assertEqual(self.github.work['state'], 'open')
        passing = True
        self.assertEqual((await self.step())['action'], 'completed')
        self.assertEqual(observed, [MERGE, MERGE])
        self.assertEqual(self.github.work['state'], 'closed')
        self.assertEqual(self.github.note['phase'], 'completed')
        self.assertEqual(len(self.calls), calls)
        self.assertEqual(len(self.merge_requests), 1)
        self.assertEqual(len([write for write in self.github.writes if write[0] == 'close']), 1)

    @staticmethod
    def review_status(value, name, status):
        comment = value['provider_comments'][0]
        lines = comment['body'].splitlines()
        for index, line in enumerate(lines):
            if line.startswith('|') and f'**{name}**' in line:
                cells = line.split('|')
                icon = '🔄' if status == 'Running' else '⏳' if status in {'Queued', 'Pending'} else '❌'
                cells[2] = f' {icon} **{status}** '
                lines[index] = '|'.join(cells)
        comment['body'] = '\n'.join(lines)
        return value

    async def terminal_reviews(self, status):
        await self.opened_pr()
        original = copy.deepcopy(self.github.note)
        for name in ('Code Review', 'Security Review'):
            with self.subTest(review=name, status=status):
                self.github.note = copy.deepcopy(original)
                self.github.transform_observation = lambda value: self.review_status(value, name, status)
                calls, writes = len(self.calls), len(self.github.writes)
                for _ in range(2):
                    self.assertEqual((await self.step())['reason'], 'replan_required')
                    self.assertEqual(self.github.note['wait_reason'], 'replan_required')
                    self.assertEqual(self.github.note['next_action'], 'diagnose_review')
                self.assertEqual(self.github.work['state'], 'open')
                self.assertFalse(self.github.pr['merged'])
                self.assertEqual(len(self.calls), calls)
                self.assertFalse(any(write[0] != 'record' for write in self.github.writes[writes:]))

    async def test_failed_review_enters_durable_diagnosis(self):
        await self.terminal_reviews('Failed')

    async def test_cancelled_review_enters_durable_diagnosis(self):
        await self.terminal_reviews('Cancelled')

    async def test_error_review_enters_durable_diagnosis(self):
        await self.terminal_reviews('Error')

    async def test_unknown_current_review_status_enters_diagnosis(self):
        await self.terminal_reviews('New terminal state')

    async def test_recognized_active_review_states_wait_without_diagnosis_or_requests(self):
        await self.opened_pr()
        original = copy.deepcopy(self.github.note)
        for status in ('Queued', 'Pending', 'Running'):
            with self.subTest(status=status):
                self.github.note = copy.deepcopy(original)
                self.github.transform_observation = lambda value: self.review_status(value, 'Code Review', status)
                calls, writes = len(self.calls), len(self.github.writes)
                for _ in range(2):
                    self.assertEqual((await self.step())['reason'], 'remote_delivery_gates')
                self.assertEqual(len(self.calls), calls)
                self.assertFalse(self.github.pr['merged'])
                self.assertFalse(any(write[0] != 'record' for write in self.github.writes[writes:]))


if __name__ == '__main__':
    unittest.main()
