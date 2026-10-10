"""Fresh PR ownership and delegated dependency edges govern the next action."""

import copy
import tempfile
import unittest
from unittest.mock import patch

from hydra_sdlc.runner import Runner, intake_digest
from test_project import BASE, HEAD
from test_runner import GitHub, Workspace, complete_capabilities


REPO, NUMBER = 'example/product', 4


class ObservationReconciliationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.reset()
        policy = patch('hydra_sdlc.runner.load_project',
                       side_effect=lambda gh, repo, revision=None: copy.deepcopy(gh.cfg))
        policy.start()
        self.addCleanup(policy.stop)

    def reset(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.github = GitHub()
        self.workspace = Workspace(directory.name, self.github)
        self.calls = []

    async def execute(self, assignment, **kwargs):
        self.calls.append(self.github.note['pending_action'])
        if assignment['mode'] == 'workspace_write':
            self.workspace.dirty = True
        return {'status': 'completed', 'detail': {'result': {'outcome': 'candidate_ready'}}}

    async def capabilities(self, cwd):
        return complete_capabilities()

    def runner(self):
        return Runner(self.github, self.workspace, host_alias='host-a', execute=self.execute,
                      capabilities=self.capabilities)

    async def opened_pr(self):
        self.github.remote_pending = True
        self.assertEqual((await self.runner().step(REPO, NUMBER))['action'], 'continue')
        self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'remote_delivery_gates')
        self.github.remote_pending = False

    def intermediate_effect(self, route, mutation=None):
        if route == 'request_review':
            self.github.note['checkpoint'] = 'await_auto_review'
        else:
            self.github.note.update(phase='uncertain', pending_action='resolve_threads', pending_thread='THREAD')

        def observe(value):
            if mutation == 'marker':
                value['pr']['body'] = 'PR ownership marker was removed.'
            elif mutation == 'author':
                value['pr']['user']['login'] = 'other-writer'
            self.github.pr = copy.deepcopy(value['pr'])
            if route == 'request_review':
                value['provider_comments'] = []
            else:
                value['threads'] = [{'id': 'THREAD', 'isResolved': False, 'isOutdated': True,
                    'comments': {'nodes': [{'databaseId': 99,
                        'author': {'login': self.github.cfg['review_provider']['login']}}]}}]
            return value
        self.github.transform_observation = observe

    async def test_fresh_foreign_pr_blocks_review_requests_and_thread_resolution(self):
        for mutation in ('marker', 'author'):
            for route in ('request_review', 'resolve_threads'):
                with self.subTest(mutation=mutation, route=route):
                    self.reset()
                    await self.opened_pr()
                    self.intermediate_effect(route, mutation)
                    listed = []
                    original = self.github.pulls
                    def pulls(repo, branch):
                        values = original(repo, branch)
                        listed.extend(self.github.owns_pr(repo, NUMBER, pr) for pr in values)
                        return values
                    self.github.pulls = pulls
                    writes, calls = len(self.github.writes), len(self.calls)
                    result = await self.runner().step(REPO, NUMBER)
                    self.assertTrue(listed)
                    self.assertTrue(all(listed))
                    self.assertFalse(self.github.owns_pr(REPO, NUMBER, self.github.pr))
                    self.assertEqual(self.calls[calls:], [])
                    self.assertEqual([w for w in self.github.writes[writes:] if w[0] != 'record'], [])
                    self.assertEqual(result.get('reason'), 'foreign_pr')
                    self.assertEqual(self.github.note['head'], HEAD)
                    self.assertFalse(self.github.pr['merged'])
                    if route == 'resolve_threads':
                        self.assertEqual(self.github.note['pending_action'], 'resolve_threads')
                        self.assertEqual(self.github.note['pending_thread'], 'THREAD')

    async def test_same_owned_pr_still_requests_reviews_and_resolves_owned_threads(self):
        for route in ('request_review', 'resolve_threads'):
            with self.subTest(route=route):
                self.reset()
                await self.opened_pr()
                self.intermediate_effect(route)
                writes, calls = len(self.github.writes), len(self.calls)
                result = await self.runner().step(REPO, NUMBER)
                effects = [w for w in self.github.writes[writes:] if w[0] != 'record']
                if route == 'request_review':
                    self.assertEqual(result['reason'], 'remote_delivery_gates')
                    self.assertEqual(effects, [('request_review', 'code', HEAD),
                                               ('request_review', 'security', HEAD)])
                else:
                    self.assertEqual(result['action'], 'continue')
                    self.assertEqual(effects, [('resolve_thread', 'THREAD')])
                self.assertEqual(self.calls[calls:], [])

    async def dispatch_order(self, *, dependent_state='valid', recovery=False):
        def issue(number, priority, dependencies=()):
            value = copy.deepcopy(self.github.work)
            value.update(number=number, created_at=f'2026-10-10T00:00:0{number}Z')
            metadata = f'priority = {priority}\ndependencies = {list(dependencies)!r}\n'
            value['body'] = value['body'].replace('spec = ', metadata + 'spec = ')
            return value
        items = {1: issue(1, 0), 2: issue(2, 10),
                 3: issue(3, 20, [f'https://github.com/{REPO}/issues/1'])}
        if dependent_state == 'paused':
            items[3]['labels'].append({'name': self.github.cfg['labels']['paused']})
        elif dependent_state == 'malformed':
            items[3]['body'] = items[3]['body'].replace('priority = 20', 'priority = "invalid"')
        elif dependent_state == 'unauthorized':
            items[3]['user']['login'] = 'other-writer'
        elif dependent_state == 'undelegated':
            items[3]['labels'] = []
        elif dependent_state == 'decision':
            items[3]['labels'].append({'name': self.github.cfg['labels']['decision']})
        self.github.issues = lambda repo: copy.deepcopy(list(items.values()))
        self.github.issue = lambda repo, number: copy.deepcopy(items[number])
        prior = dict(attempt_id='00000000-0000-4000-8000-000000000001', host_alias='host-a',
                     contract_revision=BASE, spec_revision=None, head=HEAD, branch='hydra/issue-2',
                     pr_number=None, phase='implementation_done', pending_action=None, checkpoint=None,
                     wait_reason=None, next_action='verification', intake_digest=intake_digest(items[2]),
                     version=1, repository_id=self.github.cfg['repository_id'], issue_number=2)
        self.github.progress = lambda repo, number: copy.deepcopy(prior) if recovery and number == 2 else None
        order = []
        async def step(repo, number):
            order.append(number)
            return {'repository': repo, 'issue': number, 'action': 'continue'}
        runner = self.runner()
        runner.step = step
        await runner.cycle([REPO])
        self.assertEqual(self.github.writes, [])
        self.assertEqual(self.calls, [])
        return order

    async def test_blocked_delegated_dependency_boosts_its_ready_unblocker(self):
        self.assertEqual(await self.dispatch_order(), [1, 2])

    async def test_invalid_or_held_dependents_cannot_boost_another_issue(self):
        for state in ('paused', 'decision', 'malformed', 'unauthorized', 'undelegated'):
            with self.subTest(state=state):
                self.reset()
                self.assertEqual(await self.dispatch_order(dependent_state=state), [2, 1])

    async def test_existing_recovery_stays_ahead_of_a_new_dependency_unblocker(self):
        self.assertEqual(await self.dispatch_order(recovery=True), [2, 1])
