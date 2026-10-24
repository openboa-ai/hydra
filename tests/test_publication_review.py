"""P14: bind publication expectations and bound complete source observations."""
import copy
from pathlib import Path
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import patch

from hydra_sdlc.github import GitHub, GitHubError
from hydra_sdlc.native_publication import Publication
import test_native_publication as native_fixture
import test_publication_reads as read_fixture
from test_github import HEAD, BASE, REPO, IDENTITY
from test_project import observation
from test_workspace import git


def driver(client):
    value = Publication.__new__(Publication)
    value.runner = SimpleNamespace(github=client,
        workspace=SimpleNamespace(commit_messages=lambda *args: ['Related issue: #4']))
    value.repo, value.number, value.repository_id = REPO, 4, 123
    value.pin = {'head': HEAD, 'attempt_id': 'synthetic', 'contract_revision': BASE}
    value.params = {'branch': 'hydra/issue-4'}
    value.expected = {'pending_action': 'publish', 'head': HEAD}
    value.receipt, value.path = None, Path('unused-publication-fixture')
    value.source = lambda expected: {'resource': {'source': 'github', 'kind': 'issue_comment', 'id': '741'}}
    value.config = {'repository': REPO, 'revision': BASE,
        'review_provider': {'format': 'codex_summary_v1', 'user_id': 199175422,
            'login': 'chatgpt-codex-connector[bot]', 'app_id': 1144995}}
    return value


class CompletePublicationReadTests(unittest.TestCase):
    client = read_fixture.PublicationReadTests.client

    def test_complete_owned_source_and_payload_control(self):
        client, calls, _ = self.client()
        command = driver(client)
        self.assertEqual(command.read_publication()[3], {'code', 'security'})
        self.assertEqual(command.receipt['stage'], 'publication_ready')
        command.public_payloads()
        self.assertTrue(calls)
        self.assertTrue(all(method == 'GET' for method, _ in calls))

    def test_elapsed_branch_read_prevents_the_next_pr_list_request(self):
        now = 0
        def slow(path, calls):
            nonlocal now
            if '/git/ref/' in path:
                now = 16
        client, calls, _ = self.client(transform=slow)
        with patch('hydra_sdlc.github.time.monotonic', side_effect=lambda: now):
            with self.assertRaises(GitHubError):
                driver(client).read_publication()
        self.assertFalse(any('/pulls?' in path for _, path in calls))

    def test_elapsed_ownership_read_cannot_restart_the_observation_deadline(self):
        now = 0
        def slow(path, calls):
            nonlocal now
            if path == f'/repos/{REPO}':
                now = 16
        client, calls, _ = self.client(transform=slow)
        with patch('hydra_sdlc.github.time.monotonic', side_effect=lambda: now):
            with self.assertRaises(GitHubError):
                driver(client).read_publication()
        self.assertFalse(any('/commits?' in path for _, path in calls))

    def test_ref_list_ownership_and_comments_share_the_32_request_limit(self):
        def endless(path, calls):
            if '/comments?' in path:
                return [{'id': i, 'body': 'Unrelated public comment'} for i in range(100)]
        client, calls, _ = self.client(transform=endless)
        with self.assertRaises(GitHubError):
            driver(client).read_publication()
        self.assertLessEqual(len(calls), 32, 'The bound must include the prefix and ownership reads')

    def test_payload_preflight_owns_one_bounded_source_read(self):
        now = 0
        def slow(path, calls):
            nonlocal now
            if '/pulls?' in path:
                now = 16
        client, calls, _ = self.client(transform=slow)
        with patch('hydra_sdlc.github.time.monotonic', side_effect=lambda: now):
            with self.assertRaises(GitHubError):
                driver(client).public_payloads()
        self.assertFalse(any(path == f'/repos/{REPO}' for _, path in calls))

    def test_complete_observation_does_not_consume_another_callers_budget(self):
        client, _, _ = self.client()
        with client.read_budget(seconds=60, requests=1) as outer:
            try:
                observed = driver(client).read_publication()
            except GitHubError:
                self.fail('A valid complete observation must own its budget independently')
            self.assertEqual(observed[3], {'code', 'security'})
            self.assertEqual(outer.remaining_requests, 1)
        self.assertEqual(client._read_budgets, [])

    def test_receipt_source_read_is_in_the_same_observation_deadline(self):
        now = 0
        client, calls, _ = self.client()
        command = driver(client)
        command.source = MethodType(Publication.source, command)
        command.observer = lambda source: None
        command.runner._record_values = lambda record: record
        def progress(reader, repo, number):
            nonlocal now
            now = 16
            reader.api('GET', '/user')
            return {'record': command.expected,
                'resource': {'source': 'github', 'kind': 'issue_comment', 'id': '741'}}
        with patch.object(GitHub, 'progress_source', progress), \
             patch('hydra_sdlc.github.time.monotonic', side_effect=lambda: now):
            with self.assertRaises(GitHubError):
                command.read_publication()
        self.assertFalse(any('/commits?' in path for _, path in calls))


class PublicationCommentRelevanceTests(unittest.TestCase):
    client = read_fixture.PublicationReadTests.client

    def observed(self, extra):
        own = [{'id': 901 + i, 'user': dict(IDENTITY),
            'body': f'<!-- hydra-review-request:v1 head={HEAD} kind={kind} -->'}
            for i, kind in enumerate(('code', 'security'))]
        def comments(path, calls):
            if '/comments?' in path:
                return own + [extra]
        client, _, raw = self.client(transform=comments)
        raw['comments'] = 3
        return driver(client).read_publication()

    def test_unrelated_incomplete_comments_do_not_block_owned_request_evidence(self):
        cases = [
            {'id': 990, 'body': 'Ordinary discussion', 'user': None},
            {'id': 991, 'user': {'id': 44, 'login': 'former-user'}},
            {'id': 992, 'body': None, 'user': None},
            {'id': 993, 'body': 'Ordinary discussion', 'user': ['unavailable author']},
            {'id': 994, 'body': 'Ordinary discussion', 'user': {'id': 44, 'login': 'someone'},
                'performed_via_github_app': ['unavailable app']},
        ]
        for row in cases:
            with self.subTest(comment=row['id']):
                try:
                    result = self.observed(row)
                except (RuntimeError, TypeError, AttributeError):
                    self.fail('Unrelated unavailable metadata cannot erase valid owned request evidence')
                self.assertEqual(result[3], {'code', 'security'})

    def test_claimed_review_evidence_with_unavailable_author_remains_unknown(self):
        for body in [f'<!-- hydra-review-request:v1 head={HEAD} kind=code -->',
                     '<!-- codex-pull-request-review-summary -->']:
            with self.subTest(body=body):
                with self.assertRaises(RuntimeError):
                    self.observed({'id': 995, 'body': body, 'user': None})


class PublicationExpectationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = native_fixture.NativePublicationTests.asyncSetUp
    new_controller = native_fixture.NativePublicationTests.new_controller
    result = native_fixture.NativePublicationTests.result
    command = native_fixture.NativePublicationTests.command
    checkpoint = native_fixture.NativePublicationTests.checkpoint
    real_git_assignment = native_fixture.NativePublicationTests.real_git_assignment
    candidate = native_fixture.NativePublicationTests.candidate
    verification_command = native_fixture.NativePublicationTests.verification_command
    verification_grant = native_fixture.NativePublicationTests.verification_grant
    call = native_fixture.NativePublicationTests.call
    finish_command = native_fixture.NativePublicationTests.finish_command
    reviewed = native_fixture.NativePublicationTests.reviewed
    publication_command = native_fixture.NativePublicationTests.publication_command
    publication_grant = native_fixture.NativePublicationTests.publication_grant
    publish = native_fixture.NativePublicationTests.publish
    no_publication = native_fixture.NativePublicationTests.no_publication

    async def test_out_of_band_candidate_branch_cannot_replace_the_recorded_expectation(self):
        candidate = await self.reviewed()
        branch = self.gh.note['branch']
        self.assertIsNone(self.gh.note.get('expected_head'))
        self.assertIsNone(self.gh.note.get('pending_action'))
        git(self.path, 'push', 'origin', candidate['head'] + ':refs/heads/' + branch)
        self.gh.branch = candidate['head']
        existing = observation()['pr']
        existing['body'] = ('<!-- hydra-pr:v1 {"repository_id":' + str(self.gh.cfg['repository_id'])
            + ',"issue_number":4} -->\nRelated issue: #4')
        existing['title'] = 'Reviewed candidate'
        for side in ('head', 'base'):
            existing[side]['repo']['id'] = self.gh.cfg['repository_id']
        existing['head']['sha'] = candidate['head']
        existing['base']['sha'] = self.gh.cfg['revision']
        self.gh.pr = existing
        self.assertTrue(self.gh.owns_pr('example/product', 4, existing), 'The external PR must satisfy actual ownership')
        command = self.publication_command(candidate)
        self.assertEqual(command['parameters']['expected_remote_head'], candidate['head'])
        before, writes = copy.deepcopy(self.gh.note), len(self.gh.writes)
        reply = await self.publish(command)
        self.assertEqual(reply['request']['outcome'], 'rejected', reply)
        self.assertEqual(reply['request']['reason'], 'stale_publication', reply)
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual(self.gh.note, before)
        self.assertEqual(self.gh.pr, existing)
        self.no_publication(writes)
