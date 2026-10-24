"""P14 follow-up: existing PR corrections and responsive command preflight."""
import asyncio
import unittest
from threading import Event
from unittest.mock import patch

import test_native_publication as fixture
from test_project import observation
from test_workspace import git


class PublicationFollowupTests(unittest.IsolatedAsyncioTestCase):
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

    async def correction(self, *, lagging_pr=False):
        candidate = await self.reviewed()
        prior = self.base
        branch = self.gh.note['branch']
        git(self.path, 'push', 'origin', prior + ':refs/heads/' + branch)
        self.gh.branch = prior
        self.gh.note.update(expected_head=prior, published_head=prior, pr_number=7)
        pr = observation()['pr']
        pr['title'] = 'Previously reviewed candidate'
        pr['body'] = ('<!-- hydra-pr:v1 {"repository_id":'
            + str(self.gh.cfg['repository_id']) + ',"issue_number":4} -->\nRelated issue: #4')
        for side in ('head', 'base'):
            pr[side]['repo']['id'] = self.gh.cfg['repository_id']
        pr['head']['sha'], pr['base']['sha'] = prior, self.gh.cfg['revision']
        self.gh.pr = pr
        self.assertTrue(self.gh.owns_pr('example/product', 4, pr))
        actual = self.ws.publish
        def update(path, name, expected):
            result = actual(path, name, expected)
            if not lagging_pr:
                self.gh.pr['head']['sha'] = candidate['head']
            return result
        self.ws.publish = update
        return candidate, self.publication_command(candidate), prior

    async def test_reviewed_correction_updates_the_same_pr_from_the_authenticated_prior_head(self):
        candidate, command, prior = await self.correction()
        start = len(self.gh.writes)
        reply = await self.publish(command)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(reply['request']['receipt']['stage'], 'publication_ready')
        self.assertEqual(reply['request']['receipt']['candidate'], candidate)
        self.assertEqual(self.gh.pr['number'], 7)
        self.assertEqual(self.gh.pr['head']['sha'], candidate['head'])
        self.assertEqual(self.pushes, [('hydra/issue-4', prior)])
        self.assertEqual(git(self.path, 'ls-remote', 'origin', 'refs/heads/hydra/issue-4').split()[0], candidate['head'])
        self.assertTrue(all(row[0] == 'record' for row in self.gh.writes[start:]))
        self.assertEqual(self.counter.read_text(), '1')

    async def test_old_pr_head_after_push_cannot_confirm_the_new_candidate_and_restart_reuses_the_push(self):
        candidate, command, prior = await self.correction(lagging_pr=True)
        start = len(self.gh.writes)
        held = await self.publish(command)
        self.assertNotEqual(held['request']['outcome'], 'applied', held)
        self.assertEqual(self.pushes, [('hydra/issue-4', prior)])
        self.assertEqual(self.gh.branch, candidate['head'])
        self.assertEqual(self.gh.pr['head']['sha'], prior)
        receipt = held['request']['receipt']
        self.assertTrue(receipt is None or receipt['stage'] == 'branch_published', held)
        self.assertTrue(all(row[0] == 'record' for row in self.gh.writes[start:]))
        self.gh.pr['head']['sha'] = candidate['head']
        self.controller = self.new_controller()
        self.controller.runner.operations = self.control
        recovered = await self.publish(command)
        self.assertEqual(recovered['request']['outcome'], 'applied', recovered)
        self.assertEqual(recovered['request']['receipt']['stage'], 'publication_ready')
        self.assertEqual(self.pushes, [('hydra/issue-4', prior)])
        self.assertEqual(self.gh.pr['number'], 7)
        self.assertEqual(self.counter.read_text(), '1')

    async def test_repository_preflight_allows_the_event_loop_to_serve_another_callback(self):
        candidate = await self.reviewed()
        command = self.publication_command(candidate)
        loop = asyncio.get_running_loop()
        released, pinged = Event(), Event()
        responsive = []
        original = self.gh.repository
        def ping():
            pinged.set()
            released.set()
        def blocked(repo):
            loop.call_soon_threadsafe(ping)
            released.wait(3)
            responsive.append(pinged.is_set())
            return original(repo)
        with patch.object(self.gh, 'repository', side_effect=blocked):
            reply = await self.publish(command)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertTrue(responsive, 'The actual repository lookup must run')
        self.assertTrue(all(responsive), 'Repository I/O must yield to the MCP event loop')
        self.assertEqual(len(self.pushes), 1)

    async def test_confirmed_candidate_rewound_to_the_prior_head_is_held_without_another_push(self):
        candidate, command, prior = await self.correction()
        branch = self.gh.note['branch']
        git(self.path, 'push', 'origin', candidate['head'] + ':refs/heads/' + branch)
        self.gh.note['published_head'] = candidate['head']
        git(self.path, 'push', '--force', 'origin', prior + ':refs/heads/' + branch)
        start = len(self.gh.writes)
        reply = await self.publish(command)
        self.assertEqual(reply['request']['outcome'], 'rejected', reply)
        self.assertEqual(reply['request']['reason'], 'stale_publication', reply)
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual(self.pushes, [])
        self.assertEqual(git(self.path, 'ls-remote', 'origin', 'refs/heads/' + branch).split()[0], prior)
        self.assertTrue(all(row[0] == 'record' for row in self.gh.writes[start:]))
        self.assertEqual(self.counter.read_text(), '1')
