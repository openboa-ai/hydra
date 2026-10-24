"""P14 normal full observations and independently closed pending deliveries."""
import copy
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

from hydra_sdlc.github import GitHub, GitHubError
from hydra_sdlc.native_delivery import Delivery
from hydra_sdlc.operations import OperationDenied
import test_delivery_review as fixture


REPO = 'example/product'
HEAD, BASE = 'a' * 40, 'b' * 40


def delivery_reader(workflows=5):
    calls = []
    repository = {'id': 22, 'full_name': REPO, 'default_branch': 'main'}
    actor = {'id': 9, 'login': 'openboa'}
    pr = {'number': 7, 'title': 'Deliver the selected output', 'state': 'open', 'merged': False,
          'body': '<!-- hydra-pr:v1 {"repository_id":22,"issue_number":4} -->',
          'user': actor, 'changed_files': 1,
          'head': {'sha': HEAD, 'ref': 'hydra/issue-4', 'repo': repository},
          'base': {'sha': BASE, 'ref': 'main', 'repo': repository}}
    root = '/repos/' + REPO

    def transport(method, path, payload):
        calls.append((method, path))
        endpoint, _, query = path.partition('?')
        if method == 'POST' and endpoint == '/graphql':
            return {'data': {'repository': {'pullRequest': {'id': 'PR_7', 'reviewDecision': None,
                'reviewThreads': {'nodes': [], 'pageInfo': {'hasNextPage': False}}}}}}
        if method != 'GET':
            raise RuntimeError('A read attempted a provider mutation')
        if endpoint == '/user': return dict(actor)
        if endpoint == root: return copy.deepcopy(repository)
        if endpoint == root + '/pulls/7': return copy.deepcopy(pr)
        if endpoint == root + '/git/ref/heads/main': return {'object': {'sha': BASE}}
        if '/check-runs' in endpoint: return {'check_runs': []}
        if endpoint == root + '/actions/runs':
            commit = parse_qs(query)['head_sha'][0]
            offset = 0 if commit == HEAD else workflows
            return {'workflow_runs': [{'id': offset + i + 1} for i in range(workflows)]}
        if endpoint.startswith(root + '/actions/runs/'):
            if endpoint.endswith('/jobs'): return {'jobs': []}
            return {'id': int(endpoint.rsplit('/', 1)[1])}
        if endpoint == root + '/pulls/7/files': return [{'filename': 'src/main.py'}]
        if endpoint == root + '/pulls/7/commits': return [{'sha': HEAD}]
        if endpoint == root + '/rules/branches/main':
            return [{'type': 'non_fast_forward', 'ruleset_id': 8,
                     'ruleset_source': REPO, 'ruleset_source_type': 'Repository'}]
        if endpoint == root + '/rulesets/8':
            return {'id': 8, 'enforcement': 'active', 'bypass_actors': []}
        if endpoint in {root + '/pulls/7/reviews', root + '/pulls/7/comments',
                        root + '/issues/7/comments'}:
            return []
        raise RuntimeError('Unexpected synthetic source route: ' + path)

    client = GitHub(transport=transport)
    params = {'candidate': {'attempt_id': '11111111-1111-4111-8111-111111111111',
                           'head': HEAD, 'contract_revision': BASE},
              'pr_number': 7, 'integration_base': BASE}
    controller = SimpleNamespace(runner=SimpleNamespace(github=client))
    command = Delivery(controller, REPO, 4, params, 22, 0, lambda: None,
                       lambda value: None, lambda *args, **kwargs: None, Event())
    return command, calls


class DeliveryObservationReviewTests(unittest.TestCase):
    def test_full_observation_and_ownership_with_five_runs_per_commit(self):
        command, calls = delivery_reader()
        try:
            value = command.read_pr()
        except GitHubError as error:
            self.fail('A complete five-run observation could not reach ownership: ' + str(error))
        self.assertEqual((value['head_sha'], value['base_sha'], len(value['runs'])), (HEAD, BASE, 10))
        self.assertGreater(len(calls), 32)
        self.assertLessEqual(len(calls), 128)
        self.assertEqual(sum(path == '/user' for _, path in calls), 1)

    def test_full_observation_keeps_a_hard_request_limit(self):
        command, calls = delivery_reader(workflows=80)
        with self.assertRaisesRegex(GitHubError, 'read budget exhausted'):
            command.read_pr()
        self.assertEqual(len(calls), 128)

    def test_progress_reads_keep_their_smaller_allowance(self):
        command, calls = delivery_reader()
        with self.assertRaisesRegex(GitHubError, 'read budget exhausted'):
            with command.read_scope() as reader:
                for _ in range(33):
                    reader.api('GET', '/user')
        self.assertEqual(len(calls), 32)

    def test_full_observation_keeps_a_hard_time_limit(self):
        command, calls = delivery_reader()
        transport, clock = command.runner.github.transport, [100.0]
        def delayed(method, path, payload):
            value = transport(method, path, payload)
            if len(calls) == 20:
                clock[0] += 46.0
            return value
        command.runner.github.transport = delayed
        with patch('hydra_sdlc.github.time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(GitHubError, 'read budget exhausted'):
                command.read_pr()
        self.assertEqual(len(calls), 20)

    def test_larger_observation_still_rejects_a_foreign_pr(self):
        command, calls = delivery_reader()
        transport = command.runner.github.transport
        def foreign(method, path, payload):
            value = transport(method, path, payload)
            if path == '/repos/' + REPO + '/pulls/7':
                value['user'] = {'id': 10, 'login': 'outsider'}
            return value
        command.runner.github.transport = foreign
        with self.assertRaisesRegex(OperationDenied, 'stale_delivery'):
            command.read_pr()
        self.assertGreater(len(calls), 32)
        self.assertEqual(sum(path == '/user' for _, path in calls), 1)


class ExternalClosureReviewTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.DeliveryReviewTests.asyncSetUp
    new_controller = fixture.DeliveryReviewTests.new_controller
    result = fixture.DeliveryReviewTests.result
    command = fixture.DeliveryReviewTests.command
    checkpoint = fixture.DeliveryReviewTests.checkpoint
    real_git_assignment = fixture.DeliveryReviewTests.real_git_assignment
    candidate = fixture.DeliveryReviewTests.candidate
    verification_command = fixture.DeliveryReviewTests.verification_command
    verification_grant = fixture.DeliveryReviewTests.verification_grant
    call = fixture.DeliveryReviewTests.call
    finish_command = fixture.DeliveryReviewTests.finish_command
    reviewed = fixture.DeliveryReviewTests.reviewed
    publication_command = fixture.DeliveryReviewTests.publication_command
    publication_grant = fixture.DeliveryReviewTests.publication_grant
    publish = fixture.DeliveryReviewTests.publish
    published = fixture.DeliveryReviewTests.published
    delivery_command = fixture.DeliveryReviewTests.delivery_command
    delivery_grant = fixture.DeliveryReviewTests.delivery_grant
    deliver = fixture.DeliveryReviewTests.deliver
    effects = fixture.DeliveryReviewTests.effects
    unchanged_candidate = fixture.DeliveryReviewTests.unchanged_candidate

    async def test_external_close_after_pause_reconciles_without_another_close(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        original = self.controller.runner._intent
        paused = False
        def intent(*args, **kwargs):
            nonlocal paused
            value = original(*args, **kwargs)
            if args[4] == 'close_issue' and value is not None and not paused:
                self.control.set_mode('pause', REPO)
                paused = True
            return value
        start = len(self.gh.writes)
        with patch.object(self.controller.runner, '_intent', side_effect=intent):
            waiting = await self.deliver(command)
        self.assertTrue(paused)
        self.assertIn(waiting['request']['outcome'], {'waiting', 'unknown'})
        self.assertEqual(self.gh.note['pending_action'], 'close_issue')
        self.assertEqual(self.effects(start), [('merge', candidate['head'])])
        self.gh.work['state'] = 'closed'
        self.control.set_mode('resume', REPO)
        command['expected']['admission_revision'] = self.control.snapshot()['revision']
        recovered = await self.deliver(command)
        self.assertEqual(recovered['request']['outcome'], 'applied', recovered)
        self.assertTrue(recovered['request']['receipt']['issue_closed'])
        self.assertEqual((self.gh.note['phase'], self.gh.note['pending_action']), ('completed', None))
        self.assertEqual(self.effects(start), [('merge', candidate['head'])])
        replay = await self.deliver(command)
        self.assertEqual(replay['request']['outcome'], 'applied', replay)
        self.assertEqual(self.effects(start), [('merge', candidate['head'])])
        self.unchanged_candidate(candidate)

    async def test_external_close_during_intent_recheck_avoids_another_close(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        original = self.controller.runner._intent
        def intent(*args, **kwargs):
            value = original(*args, **kwargs)
            if args[4] == 'close_issue' and value is not None:
                self.gh.work['state'] = 'closed'
            return value
        start = len(self.gh.writes)
        with patch.object(self.controller.runner, '_intent', side_effect=intent):
            completed = await self.deliver(command)
        self.assertEqual(completed['request']['outcome'], 'applied', completed)
        self.assertTrue(completed['request']['receipt']['issue_closed'])
        self.assertEqual((self.gh.note['phase'], self.gh.note['pending_action']), ('completed', None))
        self.assertEqual(self.effects(start), [('merge', candidate['head'])])
        self.unchanged_candidate(candidate)
