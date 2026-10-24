"""P10 authenticated reads and changing-source oracles, with no remote writes."""
import copy
import hashlib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hydra_sdlc.github import GitHub, GitHubError
from hydra_sdlc.github_work_drafts import DraftRead, read_work_draft
import test_work_drafts as values


class Wire:
    def __init__(self):
        self.data = SimpleNamespace()
        values.DraftSelectionTests.setUp(self.data)
        self.data.issue['state'] = 'open'
        self.data.sources[(101, 10)]['state'] = 'open'
        self.calls = []
        self.counts = {}
        self.credential = b'fixture-original'
        self.user = {'id': 11, 'login': 'openboa'}
        self.repo = {'id': 101, 'full_name': 'example/alpha', 'default_branch': 'main'}
        self.on_request = lambda method, path, count: None
        self.client = GitHub(transport=self)

    def __call__(self, method, path, payload):
        self.calls.append((method, path, payload))
        if method != 'GET' or payload is not None:
            raise AssertionError('The draft source may only read')
        count = self.counts[path] = self.counts.get(path, 0) + 1
        self.on_request(method, path, count)
        self.client._credential_selected(self.credential)
        self.client._authenticated_fingerprint = self.credential
        if path == '/user':
            return copy.deepcopy(self.user)
        if path == '/repos/example/alpha':
            return copy.deepcopy(self.repo)
        if path == '/repos/example/alpha/issues/comments/77':
            return copy.deepcopy(self.data.comment)
        for (_, number), issue in self.data.sources.items():
            if path == '/repos/example/alpha/issues/' + str(number):
                return copy.deepcopy(issue)
        raise GitHubError('PRIVATE_PROVIDER_DIAGNOSTIC')

    def read(self, **changes):
        d = self.data
        return read_work_draft(self.client, changes.get('repositories', {101: 'example/alpha'}),
            changes.get('reference', d.ref), author=changes.get('author', values.ACTOR),
            target_repository_id=changes.get('target', 101),
            draft_digest=changes.get('digest', hashlib.sha256(values.canonical(d.payload).encode()).hexdigest()))


class GitHubDraftReadTests(unittest.TestCase):
    def setUp(self):
        self.wire = Wire()

    def test_valid_exact_source_returns_private_data_without_a_write_or_authority(self):
        result = self.wire.read()
        self.assertIsInstance(result, DraftRead)
        self.assertEqual(result.status, 'available', result)
        self.assertEqual(result.source.draft.value, self.wire.data.payload)
        self.assertEqual(result.source.reference.value, self.wire.data.ref)
        self.assertTrue(all(method == 'GET' and payload is None for method, _, payload in self.wire.calls))
        self.assertGreaterEqual(self.wire.counts['/repos/example/alpha/issues/comments/77'], 2)
        self.assertGreaterEqual(self.wire.counts['/repos/example/alpha/issues/10'], 2)
        self.assertNotIn('A useful request', repr(result))
        self.assertFalse(hasattr(result, 'authority'))

    def test_fresh_calls_do_not_use_a_previous_draft_when_provider_read_fails(self):
        self.assertEqual(self.wire.read().status, 'available')
        def failure(method, path, count):
            raise GitHubError('PRIVATE_PROVIDER_DIAGNOSTIC')
        self.wire.on_request = failure
        result = self.wire.read()
        self.assertEqual(result.status, 'unavailable')
        self.assertIsNone(result.source)
        self.assertNotIn('PRIVATE_PROVIDER_DIAGNOSTIC', repr(result))

    def test_native_reference_is_explicitly_unavailable_without_private_payload_or_io(self):
        ref = {'kind': 'native_preparation', 'handle': 'PRIVATE_NATIVE_SENTINEL', 'revision': 'r1'}
        result = self.wire.read(reference=ref)
        self.assertEqual((result.status, result.reason), ('unavailable', 'native_draft_source_unavailable'))
        self.assertIsNone(result.source)
        self.assertNotIn('PRIVATE_NATIVE_SENTINEL', repr(result))
        self.assertEqual(self.wire.calls, [])

    def test_invalid_reference_registry_or_target_is_rejected_before_io(self):
        cases = [{'reference': {**self.wire.data.ref, 'comment_id': True}},
                 {'repositories': {}}, {'repositories': {True: 'example/alpha'}},
                 {'repositories': {101: 'example/alpha;echo unsafe'}},
                 {'target': 102}, {'digest': 'not-a-digest'}]
        for case in cases:
            with self.subTest(case=case):
                before = len(self.wire.calls)
                result = self.wire.read(**case)
                self.assertEqual(result.status, 'invalid')
                self.assertIsNone(result.source)
                self.assertEqual(len(self.wire.calls), before)

    def test_copied_or_edited_comment_never_becomes_an_available_draft(self):
        for changes in [{'user': {'id': 12, 'login': 'openboa'}},
                        {'updated_at': '2026-10-20T11:00:00Z'},
                        {'issue_url': values.ROOT + '/issues/11'}]:
            with self.subTest(changes=changes):
                wire = Wire();wire.data.comment.update(changes)
                result = wire.read()
                self.assertIn(result.status, {'invalid', 'changed'}, result)
                self.assertIsNone(result.source)

    def test_digest_pin_and_original_issue_changes_are_reported_without_repinning(self):
        result = self.wire.read(digest='0' * 64)
        self.assertEqual(result.status, 'changed', result)
        self.assertIsNone(result.source)
        self.wire.data.sources[(101, 10)]['body'] += '\nChanged request'
        result = self.wire.read()
        self.assertEqual(result.status, 'changed', result)
        self.assertIsNone(result.source)

    def test_changed_comment_during_final_read_discards_the_entire_source(self):
        def change(method, path, count):
            if path.endswith('/issues/comments/77') and count == 2:
                self.wire.data.comment['body'] += '\nChanged draft'
        self.wire.on_request = change
        result = self.wire.read()
        self.assertEqual(result.status, 'changed', result)
        self.assertIsNone(result.source)

    def test_changed_original_issue_during_final_read_cannot_reuse_initial_digest(self):
        def change(method, path, count):
            if path.endswith('/issues/10') and count == 2:
                self.wire.data.sources[(101, 10)]['title'] += ' Changed'
        self.wire.on_request = change
        result = self.wire.read()
        self.assertEqual(result.status, 'changed', result)
        self.assertIsNone(result.source)

    def test_changed_repository_identity_during_final_read_is_not_accepted(self):
        def change(method, path, count):
            if path == '/repos/example/alpha' and count == 2:
                self.wire.repo['id'] = 102
        self.wire.on_request = change
        result = self.wire.read()
        self.assertEqual(result.status, 'changed', result)
        self.assertIsNone(result.source)

    def test_identity_or_credential_rotation_discards_source_and_restores_client_hooks(self):
        received = []
        previous = received.append
        self.wire.client._credential_selected = previous
        def rotate(method, path, count):
            if path.endswith('/issues/comments/77'):
                self.wire.credential = b'fixture-rotated'
        self.wire.on_request = rotate
        result = self.wire.read()
        self.assertEqual(result.status, 'changed', result)
        self.assertIsNone(result.source)
        self.assertIs(self.wire.client._credential_selected, previous)
        self.wire.on_request = lambda *args: None
        self.wire.credential = b'fixture-original'
        self.assertEqual(self.wire.read().status, 'available')
        self.assertTrue(received)

    def test_parent_goal_is_read_and_fenced_independently(self):
        d = self.wire.data
        goal = {**d.issue, 'id': 10001, 'number': 1, 'url': values.ROOT + '/issues/1', 'body': 'Accepted parent scope'}
        d.sources[(101, 1)] = goal
        d.payload['goal'] = {'repository_id': 101, 'issue_number': 1,
                             'source_digest': values.source_digest(goal)}
        d.comment['body'] = values.marker(d.payload)
        d.ref = values.reference(d.comment['body'])
        self.assertEqual(self.wire.read().status, 'available')
        before = self.wire.counts.get('/repos/example/alpha/issues/1', 0)
        def change(method, path, count):
            if path.endswith('/issues/1') and count == before + 2:
                d.sources[(101, 1)]['body'] += ' Changed'
        self.wire.on_request = change
        result = self.wire.read()
        self.assertEqual(result.status, 'changed', result)
        self.assertIsNone(result.source)

    def test_nested_budget_exhaustion_and_late_response_never_return_available_source(self):
        with self.wire.client.read_budget(seconds=10, requests=2):
            result = self.wire.read()
        self.assertEqual(result.status, 'unavailable')
        self.assertIsNone(result.source)
        self.assertLessEqual(len(self.wire.calls), 2)
        self.assertEqual(self.wire.read().status, 'available')
        clock = [1000.0]
        def late(method, path, count):
            if path.endswith('/issues/comments/77'):
                clock[0] += 100.0
        self.wire.on_request = late
        with patch('hydra_sdlc.github.time.monotonic', side_effect=lambda: clock[0]):
            result = self.wire.read()
        self.assertEqual(result.status, 'unavailable')
        self.assertIsNone(result.source)

    def test_oversized_provider_data_is_bounded_without_echoing_it(self):
        self.wire.data.comment['body'] = 'PRIVATE_LARGE_SENTINEL' + 'x' * 8_000_001
        result = self.wire.read()
        self.assertIn(result.status, {'invalid', 'unavailable'})
        self.assertIsNone(result.source)
        self.assertNotIn('PRIVATE_LARGE_SENTINEL', repr(result))
