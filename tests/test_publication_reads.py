"""Publication reads do not require delivery-only API capabilities."""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hydra_sdlc.github import GitHub, GitHubError
from hydra_sdlc.native_publication import Publication
from test_github import owned_pr, HEAD, BASE, REPO, IDENTITY, REPOSITORY


class PublicationReadTests(unittest.TestCase):
    def client(self, *, transform=None):
        raw = {**owned_pr(), 'title': 'Implement Issue 4', 'commits': 1, 'comments': 2}
        comments = [{'id': 901 + i, 'user': dict(IDENTITY),
            'body': f'<!-- hydra-review-request:v1 head={HEAD} kind={kind} -->'}
            for i, kind in enumerate(('code', 'security'))]
        calls = []
        def transport(method, path, payload):
            calls.append((method, path))
            self.assertEqual(method, 'GET')
            if transform:
                changed = transform(path, calls)
                if changed is not None:
                    return changed
            values = {'/user': IDENTITY, f'/repos/{REPO}': REPOSITORY,
                f'/repos/{REPO}/pulls/7': raw,
                f'/repos/{REPO}/pulls/7/commits?per_page=100&page=1': [{'sha': HEAD}],
                f'/repos/{REPO}/issues/7/comments?per_page=100&page=1': comments,
                f'/repos/{REPO}/git/ref/heads/hydra%2Fissue-4': {'object': {'sha': HEAD}},
                f'/repos/{REPO}/pulls?state=all&head=example%3Ahydra%2Fissue-4&per_page=100&page=1': [raw]}
            if path not in values:
                raise GitHubError('Synthetic delivery-only source unavailable')
            return copy.deepcopy(values[path])
        return GitHub(transport=transport), calls, raw

    def reader(self, client):
        method = getattr(client, 'observe_publication', None)
        self.assertTrue(callable(method), 'Publication needs its own bounded source read')
        return method

    def test_complete_source_has_no_fabricated_delivery_observations(self):
        client, calls, raw = self.client()
        got = self.reader(client)(REPO, 7)
        self.assertEqual(set(got), {'pr', 'head_sha', 'commits', 'provider_comments'})
        self.assertEqual(got['pr'], raw)
        self.assertEqual(got['head_sha'], HEAD)
        self.assertEqual(len(got['provider_comments']), 2)
        self.assertEqual(len(calls), 4)

    def test_changed_anchor_or_incomplete_counts_cannot_return_partial_success(self):
        for field, value in [('head', {'sha': BASE}), ('commits', 2), ('comments', 3), ('body', 'Changed')]:
            with self.subTest(field=field):
                reads = 0
                raw = None
                def transform(path, calls):
                    nonlocal reads
                    if path == f'/repos/{REPO}/pulls/7':
                        reads += 1
                        return {**raw, field: value} if reads == 2 else None
                client, calls, raw = self.client(transform=transform)
                with self.assertRaises(GitHubError):
                    self.reader(client)(REPO, 7)

    def test_complete_pagination_uses_a_fresh_shared_request_budget(self):
        def transform(path, calls):
            if '/comments?' in path:
                return [{'id': i, 'body': 'Synthetic page'} for i in range(100)]
        client, calls, _ = self.client(transform=transform)
        with client.read_budget(seconds=60, requests=1) as outer:
            with self.assertRaises(GitHubError):
                self.reader(client)(REPO, 7)
            self.assertEqual(outer.remaining_requests, 1, 'A separate read must not consume another caller budget')
        self.assertLessEqual(len(calls), 32)
        self.assertEqual(client._read_budgets, [])

    def test_read_deadline_prevents_the_next_collection_request(self):
        now = 0
        def transform(path, calls):
            nonlocal now
            if '/commits?' in path:
                now = 16
        client, calls, _ = self.client(transform=transform)
        with patch('hydra_sdlc.github.time.monotonic', side_effect=lambda: now):
            with self.assertRaises(GitHubError):
                self.reader(client)(REPO, 7)
        self.assertFalse(any('/comments?' in path for _, path in calls))

    def test_actual_command_reader_does_not_require_ci_rules_or_review_threads(self):
        client, calls, _ = self.client()
        driver = Publication.__new__(Publication)
        driver.runner = SimpleNamespace(github=client)
        driver.repo, driver.number, driver.repository_id = REPO, 4, 123
        driver.pin = {'head': HEAD, 'attempt_id': 'synthetic', 'contract_revision': BASE}
        driver.params = {'branch': 'hydra/issue-4'}
        driver.expected = {'pending_action': 'publish', 'head': HEAD}
        driver.receipt = None
        driver.source = lambda expected: {'resource': {'source': 'github', 'kind': 'issue_comment', 'id': '741'}}
        driver.config = {'repository': REPO, 'review_provider': {'format': 'codex_summary_v1',
            'user_id': 199175422, 'login': 'chatgpt-codex-connector[bot]', 'app_id': 1144995}}
        result = None
        try:
            result = driver.read_publication()
        except GitHubError:
            pass
        self.assertIsNotNone(result, 'Valid publication must not depend on unavailable delivery sources')
        self.assertEqual(result[3], {'code', 'security'})
        self.assertEqual(driver.receipt['stage'], 'publication_ready')
        self.assertFalse(any(any(part in path for part in ('/check-runs', '/actions/', '/rules', '/reviews', '/graphql'))
                             for _, path in calls))
