"""P06 deterministic integration: real GitHub adapter, fixture transport only."""
import copy
from contextlib import contextmanager
from dataclasses import replace
import json
from threading import Event
import unittest
from unittest.mock import patch

from hydra_sdlc.decision_coordinator import DecisionCoordinator, DecisionSnapshot
from hydra_sdlc.decision_protocol import DecisionCallCoverage
from hydra_sdlc.github import GitHub, GitHubError
from hydra_sdlc.operations import OperationDenied
import test_decision_protocol as domain
import test_public_decisions as wire


class DecisionTransport(wire.ReadOnlyTransport):
    def __init__(self):
        body = '<!-- hydra-progress:v1 ' + json.dumps(domain.record(), sort_keys=True) + ' -->'
        super().__init__([wire.comment(1, body)])
        self.effects = []
        self.post_behavior = lambda kind, body: None
        self.patch_behavior = lambda body: None
        self.resume_state = 'not_dispatched'

    def add(self, identifier, body):
        row = wire.comment(identifier, body)
        self.rows.append(row)
        self.direct[identifier] = copy.deepcopy(row)
        return copy.deepcopy(row)

    def __call__(self, method, path, payload):
        if method == 'POST' and path == '/repos/example/product/issues/4/comments':
            body = payload['body']
            kind = 'context' if body.startswith(f'hydra: decision {wire.ATTEMPT} context\n') else 'receipt'
            self.effects.append((kind, copy.deepcopy(payload)))
            self.post_behavior(kind, body)
            return self.add(99 + len(self.effects), body)
        if method == 'PATCH' and path == '/repos/example/product/issues/comments/1':
            self.effects.append(('resume', copy.deepcopy(payload)))
            self.resume_state = 'unconfirmed'
            self.patch_behavior(payload['body'])
            self.rows[0]['body'] = payload['body']
            self.direct[1] = copy.deepcopy(self.rows[0])
            return copy.deepcopy(self.rows[0])
        return super().__call__(method, path, payload)


class DecisionCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.transport = DecisionTransport()
        self.github = GitHub(transport=self.transport)
        self.chosen = domain.selection()
        self.source_reads = 0
        self.guard_kinds = []
        self.on_source_read = lambda: None
        self.call_transform = lambda value: value

    def snapshot(self, *, timeout):
        self.assertGreater(timeout, 0)
        self.source_reads += 1
        self.on_source_read()
        counts = {kind: sum(row[0] == kind for row in self.transport.effects)
                  for kind in ('context', 'receipt', 'resume')}
        return DecisionSnapshot(self.chosen,
            self.call_transform(DecisionCallCoverage(True, counts['context'], counts['receipt'], counts['resume'],
                                 self.transport.resume_state)))

    @contextmanager
    def guard(self, kind):
        self.guard_kinds.append(kind)
        yield

    def coordinator(self):
        return DecisionCoordinator(self.github, wire.REPO, 4, read_source=self.snapshot,
            effect_guard=self.guard, expected_key=(123, 4, wire.ATTEMPT, 1),
            expected_proposal=self.chosen.proposal.source_check())

    def pair(self):
        self.transport.add(100, wire.EXPECTED)
        self.transport.add(101, wire.RECEIPT)

    def test_publication_records_the_exact_pair_without_resuming_or_allocating(self):
        before = self.github.progress(wire.REPO, 4)
        result = self.coordinator().apply()
        self.assertEqual(result.outcome, 'applied', result.reason)
        self.assertEqual([row[0] for row in self.transport.effects], ['context', 'receipt'])
        self.assertEqual([row[1]['body'].encode() for row in self.transport.effects],
                         [wire.EXPECTED, wire.RECEIPT])
        self.assertEqual(self.guard_kinds, ['context', 'receipt'])
        self.assertEqual(self.github.progress(wire.REPO, 4), before)
        self.assertEqual(result.receipt, {'kind': 'decision', 'source_attempt': wire.ATTEMPT, 'round': 1,
            'intent_ref': {'source': 'github', 'kind': 'issue_comment', 'id': wire.REPO + '/comments/100'},
            'context_ref': {'source': 'github', 'kind': 'issue_comment', 'id': wire.REPO + '/comments/100'},
            'resolved_ref': {'source': 'github', 'kind': 'issue_comment', 'id': wire.REPO + '/comments/101'},
            'resume_attempt': wire.RESUME})
        repeated = self.coordinator().apply()
        self.assertEqual(repeated.outcome, 'applied')
        self.assertEqual(len(self.transport.effects), 2)

    def test_resume_writes_one_pinned_record_and_reconciles_it_after_restart(self):
        self.pair()
        result = self.coordinator().resume()
        self.assertEqual(result.outcome, 'applied', result.reason)
        self.assertEqual([row[0] for row in self.transport.effects], ['resume'])
        progress = self.github.progress(wire.REPO, 4)
        self.assertEqual((progress['attempt_id'], progress['phase'], progress['resume_phase']),
                         (wire.RESUME, 'ready', 'implementation'))
        self.assertEqual(self.github.decision_context_attempt(wire.REPO, 4, wire.RESUME), wire.ATTEMPT)
        self.assertEqual(result.progress_source['record'], progress)
        self.assertEqual(result.receipt['boundary'], 'progress_recorded')
        repeated = self.coordinator().resume()
        self.assertEqual(repeated.outcome, 'applied')
        self.assertEqual(repeated.receipt['boundary'], 'existing_result_reconciled')
        self.assertEqual(len(self.transport.effects), 1)

    def test_lost_context_ack_reuses_the_confirmed_context_before_receipt(self):
        def lost(kind, body):
            if kind == 'context':
                self.transport.add(100, body)
                raise GitHubError('synthetic lost context acknowledgment', uncertain=True)
        self.transport.post_behavior = lost
        result = self.coordinator().apply()
        self.assertEqual(result.outcome, 'applied', result.reason)
        self.assertEqual([row[0] for row in self.transport.effects], ['context', 'receipt'])
        self.assertEqual(result.receipt['context_ref']['id'], wire.REPO + '/comments/100')

    def test_unknown_post_is_not_retried_in_the_same_call_and_retries_exact_bytes(self):
        def unavailable(kind, body):
            raise GitHubError('synthetic unknown POST', uncertain=True)
        self.transport.post_behavior = unavailable
        first = self.coordinator().apply()
        self.assertEqual(first.outcome, 'unknown', first.reason)
        self.assertEqual(len(self.transport.effects), 1)
        self.transport.post_behavior = lambda kind, body: None
        recovered = self.coordinator().apply()
        self.assertEqual(recovered.outcome, 'applied', recovered.reason)
        self.assertEqual([row[0] for row in self.transport.effects], ['context', 'context', 'receipt'])
        self.assertEqual(self.transport.effects[0][1], self.transport.effects[1][1])

    def test_three_unknown_posts_cannot_be_reset_by_new_coordinators(self):
        self.transport.post_behavior = lambda kind, body: (_ for _ in ()).throw(
            GitHubError('synthetic unknown POST', uncertain=True))
        for _ in range(3):
            self.assertEqual(self.coordinator().apply().outcome, 'unknown')
        exhausted = self.coordinator().apply()
        self.assertEqual(exhausted.reason, 'decision_retry_exhausted')
        self.assertEqual(len(self.transport.effects), 3)

    def test_unknown_original_call_coverage_never_becomes_an_initial_post(self):
        self.call_transform = lambda value: replace(value, complete=False, context_posts=None, receipt_posts=None)
        result = self.coordinator().apply()
        self.assertEqual(result.reason, 'decision_call_coverage_unknown')
        self.assertEqual(self.transport.effects, [])

    def test_source_scope_or_adoption_changes_before_dispatch_hold(self):
        original = self.chosen
        for changed in (replace(original, scope=replace(original.scope, connection_id='different')),
                        replace(original, evidence=tuple(replace(item, revision=('opaque', 'changed'))
                            if item.role == 'adoption' else item for item in original.evidence))):
            with self.subTest(changed=changed):
                self.chosen, self.source_reads = original, 0
                def change():
                    if self.source_reads == 2:
                        self.chosen = changed
                self.on_source_read = change
                result = self.coordinator().apply()
                self.assertEqual(result.reason, 'decision_source_changed')
                self.assertEqual(self.transport.effects, [])

    def test_discovered_retry_exhaustion_at_the_final_read_prevents_a_fourth_post(self):
        def count(value):
            return replace(value, context_posts=3) if self.source_reads >= 2 else value
        self.call_transform = count
        result = self.coordinator().apply()
        self.assertEqual(result.reason, 'decision_retry_exhausted')
        self.assertEqual(self.transport.effects, [])

    def test_pause_after_context_prevents_receipt_but_preserves_the_context(self):
        @contextmanager
        def paused(kind):
            if kind != 'context':
                raise OperationDenied('project_paused')
            yield
        coordinator = self.coordinator()
        coordinator.effect_guard = paused
        result = coordinator.apply()
        self.assertEqual(result.reason, 'project_paused')
        self.assertEqual([row[0] for row in self.transport.effects], ['context'])
        self.assertTrue(any(row['body'].encode() == wire.EXPECTED for row in self.transport.rows))
        self.assertEqual(self.github.progress(wire.REPO, 4)['attempt_id'], wire.ATTEMPT)

    def test_changed_adoption_after_context_does_not_publish_a_receipt(self):
        original = self.chosen
        def change():
            if self.transport.effects:
                self.chosen = replace(original, evidence=tuple(replace(item, revision=('opaque', 'changed'))
                    if item.role == 'adoption' else item for item in original.evidence))
        self.on_source_read = change
        result = self.coordinator().apply()
        self.assertEqual(result.reason, 'decision_source_changed')
        self.assertEqual([row[0] for row in self.transport.effects], ['context'])

    def test_missing_pinned_original_is_not_recreated_from_an_empty_collection(self):
        self.pair()
        self.transport.rows = [row for row in self.transport.rows if row['id'] != 100]
        self.transport.direct[100] = GitHubError('not found', status=404)
        coordinator = self.coordinator()
        read = coordinator.read_source
        coordinator.read_source = lambda **kw: replace(read(**kw), known_context_id=100, known_receipt_id=101)
        result = coordinator.apply()
        self.assertEqual(result.reason, 'decision_evidence_unknown')
        self.assertEqual(self.transport.effects, [])

    def test_lost_patch_ack_reconciles_the_exact_progress_without_another_patch(self):
        self.pair()
        def lost(body):
            self.transport.rows[0]['body'] = body
            self.transport.direct[1] = copy.deepcopy(self.transport.rows[0])
            raise GitHubError('synthetic lost PATCH acknowledgment', uncertain=True)
        self.transport.patch_behavior = lost
        first = self.coordinator().resume()
        self.assertEqual(first.outcome, 'applied', first.reason)
        self.assertEqual(self.coordinator().resume().outcome, 'applied')
        self.assertEqual([row[0] for row in self.transport.effects], ['resume'])

    def test_unknown_patch_preserves_old_progress_until_the_original_late_write_is_observed(self):
        self.pair()
        original = self.github.progress(wire.REPO, 4)
        self.transport.patch_behavior = lambda body: (_ for _ in ()).throw(
            GitHubError('synthetic unknown PATCH', uncertain=True))
        first = self.coordinator().resume()
        self.assertEqual(first.reason, 'decision_resume_unknown')
        self.assertEqual(self.github.progress(wire.REPO, 4), original)
        self.assertEqual(self.coordinator().resume().reason, 'decision_resume_unknown')
        self.assertEqual(len(self.transport.effects), 1)
        body = self.transport.effects[0][1]['body']
        self.transport.rows[0]['body'] = body
        self.transport.direct[1] = copy.deepcopy(self.transport.rows[0])
        recovered = self.coordinator().resume()
        self.assertEqual(recovered.outcome, 'applied', recovered.reason)
        self.assertEqual(recovered.receipt['attempt_id'], wire.RESUME)
        self.assertEqual(len(self.transport.effects), 1)

    def test_terminal_nonapplication_allows_only_the_same_bounded_resume_payload(self):
        self.pair()
        self.transport.patch_behavior = lambda body: (_ for _ in ()).throw(
            GitHubError('synthetic unknown PATCH', uncertain=True))
        self.assertEqual(self.coordinator().resume().outcome, 'unknown')
        self.transport.resume_state = 'not_applied'
        self.transport.patch_behavior = lambda body: None
        self.assertEqual(self.coordinator().resume().outcome, 'applied')
        self.assertEqual([row[0] for row in self.transport.effects], ['resume', 'resume'])
        self.assertEqual(self.transport.effects[0][1], self.transport.effects[1][1])

    def test_source_failure_and_unsupported_source_do_not_echo_private_data(self):
        for read in (lambda **kw: None, lambda **kw: (_ for _ in ()).throw(RuntimeError('PRIVATE_CANARY'))):
            with self.subTest(read=read):
                coordinator = self.coordinator()
                coordinator.read_source = read
                result = coordinator.apply()
                self.assertEqual(result.reason, 'decision_source_unavailable')
                self.assertNotIn('PRIVATE_CANARY', repr(result))
                self.assertEqual(self.transport.effects, [])

    def test_cancellation_before_dispatch_and_after_context_stops_new_effects(self):
        cancel = Event()
        cancel.set()
        coordinator = self.coordinator()
        coordinator.cancel = cancel
        self.assertEqual(coordinator.apply().reason, 'decision_cancelled')
        self.assertEqual(self.transport.effects, [])
        cancel.clear()
        @contextmanager
        def guarded(kind):
            yield
            cancel.set()
        coordinator = self.coordinator()
        coordinator.cancel, coordinator.effect_guard = cancel, guarded
        self.assertEqual(coordinator.apply().reason, 'decision_cancelled')
        self.assertEqual([row[0] for row in self.transport.effects], ['context'])

    def test_expired_source_read_cannot_dispatch_after_the_deadline(self):
        clock = [0.0]
        self.on_source_read = lambda: clock.__setitem__(0, 1000.0)
        with patch('hydra_sdlc.decision_coordinator.time.monotonic', side_effect=lambda: clock[0]):
            result = self.coordinator().apply()
        self.assertEqual(result.reason, 'decision_deadline_exhausted')
        self.assertEqual(self.transport.effects, [])

    def test_original_context_is_read_back_before_a_new_source_failure(self):
        def unavailable():
            if self.transport.effects:
                raise RuntimeError('PRIVATE_CANARY')
        self.on_source_read = unavailable
        result = self.coordinator().apply()
        self.assertEqual(result.reason, 'decision_source_unavailable')
        self.assertEqual(result.effect_refs, ({'source': 'github', 'kind': 'issue_comment',
            'id': wire.REPO + '/comments/100'},))
        self.assertEqual([row[0] for row in self.transport.effects], ['context'])
        self.assertNotIn('PRIVATE_CANARY', repr(result))

    def test_paused_resume_does_not_write_or_lift_pause(self):
        self.pair()
        before = self.github.progress(wire.REPO, 4)
        @contextmanager
        def paused(kind):
            raise OperationDenied('project_paused')
            yield
        coordinator = self.coordinator()
        coordinator.effect_guard = paused
        result = coordinator.resume()
        self.assertEqual(result.reason, 'project_paused')
        self.assertEqual(self.transport.effects, [])
        self.assertEqual(self.github.progress(wire.REPO, 4), before)

    def test_regressing_original_call_coverage_is_not_reset_to_a_lower_count(self):
        self.call_transform = lambda value: replace(value, context_posts=2 if self.source_reads == 1 else 1)
        result = self.coordinator().apply()
        self.assertEqual(result.reason, 'decision_call_coverage_unknown')
        self.assertEqual(self.transport.effects, [])
