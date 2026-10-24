"""EX/P06 independent state oracles for source-qualified decision facts."""
import copy
from dataclasses import replace
import unittest

from hydra_sdlc.decision_protocol import (DecisionCallCoverage, DecisionEvidence,
    DecisionSelection, decision_plan)
from hydra_sdlc.native_question_source import SourceScope
from hydra_sdlc.public_decisions import (DecisionObservation, PublicContext, context_basis,
    prepare_context)
import test_public_decisions as wire


def evidence(role):
    return DecisionEvidence(role, ('codex', 'native_' + role, 'fixture-' + role), ('opaque', role + '-r1'))


def selection():
    return DecisionSelection(SourceScope('fixture', 'connection', 'task'), wire.context(),
        tuple(evidence(role) for role in ('work', 'question', 'answer', 'adoption', 'authority', 'proposal')))


def record():
    return {'repository_id': 123, 'issue_number': 4, 'version': 1,
        'attempt_id': wire.ATTEMPT, 'host_alias': 'fixture', 'branch': 'hydra/issue-4',
        'head': 'a' * 40, 'contract_revision': 'b' * 40, 'spec_revision': None,
        'intake_digest': 'c' * 64, 'phase': 'checkpoint', 'pending_action': None,
        'wait_reason': 'product_decision', 'next_action': 'operator_decision',
        'resume_phase': 'implementation'}


EMPTY = DecisionObservation('not_observed', 'public_observation_only')
CONTEXT = DecisionObservation('context', 'public_observation_only', context_id=10)
PAIR = DecisionObservation('pair', 'public_observation_only', context_id=10, receipt_id=20)
FIRST = DecisionCallCoverage(True, 0, 0, 0, 'not_dispatched')


class DecisionProtocolTests(unittest.TestCase):
    def plan(self, *, chosen=None, calls=FIRST, progress=None, public=EMPTY, **kwargs):
        return decision_plan(selection() if chosen is None else chosen, calls,
            record() if progress is None else progress, public, **kwargs)

    def test_first_dispatch_uses_the_original_exact_context(self):
        self.assertEqual(self.plan().action, 'post_context')
        self.assertEqual(selection().context.body, wire.EXPECTED)

    def test_confirmed_context_precedes_receipt_and_pair_ends_publication(self):
        self.assertEqual(self.plan(public=CONTEXT).action, 'post_receipt')
        complete = self.plan(public=PAIR)
        self.assertEqual((complete.action, complete.resume_record), ('publish_complete', None))

    def test_resume_uses_the_preallocated_uuid_and_original_phase(self):
        progress = record()
        original = copy.deepcopy(progress)
        result = self.plan(progress=progress, public=PAIR, resume=True)
        self.assertEqual(result.action, 'record_resume')
        expected = {name: value for name, value in progress.items()
                    if name not in {'repository_id', 'issue_number', 'version'}}
        expected.update(attempt_id=wire.RESUME, phase='ready', wait_reason=None,
            next_action='decision_context_' + wire.ATTEMPT)
        self.assertEqual(result.resume_record, expected)
        self.assertEqual(progress, original)
        result.resume_record['head'] = 'f' * 40
        self.assertEqual(progress, original)

    def test_correction_and_change_review_keep_their_resume_boundary(self):
        for phase in ('correction', 'change_review'):
            with self.subTest(phase=phase):
                basis = copy.deepcopy(wire.BASIS)
                basis['origin_phase'] = phase
                chosen = replace(selection(), context=prepare_context('Use the existing contract.', basis))
                progress = {**record(), 'resume_phase': phase}
                result = self.plan(chosen=chosen, progress=progress, public=PAIR, resume=True)
                self.assertEqual(result.action, 'record_resume')
                self.assertEqual(result.resume_record['phase'], 'implementation_done')
                self.assertEqual(result.resume_record['resume_phase'], phase)

    def test_confirmed_progress_reuses_an_uncertain_patch_without_another_write(self):
        progress = {**record(), 'attempt_id': wire.RESUME, 'phase': 'implementation_done',
                    'head': 'e' * 40, 'wait_reason': None, 'resume_phase': None}
        calls = DecisionCallCoverage(False, None, None, None, 'unconfirmed')
        result = self.plan(progress=progress, calls=calls, public=PAIR, resume=True,
                           linked_source_attempt=wire.ATTEMPT)
        self.assertEqual((result.action, result.resume_record), ('reuse_resume', None))
        self.assertEqual(self.plan(progress=progress, calls=calls, public=PAIR,
            linked_source_attempt=wire.ATTEMPT).action, 'publish_complete')

    def test_old_progress_after_an_uncertain_patch_stays_unknown(self):
        calls = DecisionCallCoverage(True, 1, 1, 1, 'unconfirmed')
        result = self.plan(calls=calls, public=PAIR, resume=True)
        self.assertEqual((result.action, result.reason), ('hold', 'decision_resume_unknown'))

    def test_only_confirmed_nonapplication_allows_a_bounded_patch_retry(self):
        calls = DecisionCallCoverage(True, 1, 1, 1, 'not_applied')
        result = self.plan(calls=calls, public=PAIR, resume=True)
        self.assertEqual(result.action, 'record_resume')
        self.assertEqual(result.resume_record['attempt_id'], wire.RESUME)
        self.assertEqual(self.plan(calls=replace(calls, resume_writes=3), public=PAIR,
                                  resume=True).reason, 'decision_retry_exhausted')

    def test_missing_pair_never_rotates_the_attempt(self):
        for public in (EMPTY, CONTEXT):
            with self.subTest(status=public.status):
                result = self.plan(public=public, resume=True)
                self.assertEqual((result.action, result.resume_record), ('hold', None))

    def test_exact_append_only_retries_remain_bounded(self):
        for count in (1, 2):
            calls = replace(FIRST, context_posts=count, receipt_posts=count)
            self.assertEqual(self.plan(calls=calls).action, 'post_context')
            self.assertEqual(self.plan(calls=calls, public=CONTEXT).action, 'post_receipt')
        calls = replace(FIRST, context_posts=3, receipt_posts=3)
        self.assertEqual(self.plan(calls=calls).reason, 'decision_retry_exhausted')
        self.assertEqual(self.plan(calls=calls, public=CONTEXT).reason, 'decision_retry_exhausted')

    def test_unknown_call_coverage_is_not_a_first_dispatch(self):
        for calls in (replace(FIRST, complete=False), replace(FIRST, context_posts=None)):
            with self.subTest(calls=calls):
                self.assertEqual(self.plan(calls=calls).reason, 'decision_call_coverage_unknown')
        self.assertEqual(self.plan(calls=replace(FIRST, receipt_posts=None), public=CONTEXT).action, 'hold')
        self.assertEqual(self.plan(calls=replace(FIRST, complete=False), public=PAIR).action, 'publish_complete')

    def test_native_step_or_unsettled_effect_prevents_decision_application(self):
        for change in ({'native_step': wire.RESUME}, {'pending_action': 'merge'}):
            self.assertEqual(self.plan(progress={**record(), **change}).reason, 'decision_checkpoint_missing')

    def test_confirmed_consumed_resume_is_read_only_during_its_active_assignment(self):
        progress = {**record(), 'attempt_id': wire.RESUME, 'phase': 'executing',
                    'pending_action': 'verification', 'native_step': '33333333-3333-4333-8333-333333333333',
                    'wait_reason': None, 'resume_phase': None}
        result = self.plan(progress=progress, public=PAIR, resume=True,
                           linked_source_attempt=wire.ATTEMPT)
        self.assertEqual((result.action, result.resume_record), ('reuse_resume', None))

    def test_work_pin_changes_hold_without_reinterpreting_the_answer(self):
        for name, value in (('attempt_id', wire.RESUME), ('head', 'd' * 40),
                            ('contract_revision', 'd' * 40), ('spec_revision', 'e' * 40),
                            ('intake_digest', 'd' * 64), ('resume_phase', 'design'),
                            ('wait_reason', None)):
            with self.subTest(name=name):
                self.assertEqual(self.plan(progress={**record(), name: value}).action, 'hold')

    def test_unknown_conflicting_or_orphan_public_results_never_dispatch(self):
        for status in ('unknown', 'conflict', 'receipt_without_context'):
            with self.subTest(status=status):
                result = self.plan(public=DecisionObservation(status, 'fixture'))
                self.assertEqual((result.action, result.resume_record), ('hold', None))

    def test_missing_source_roles_and_change_detection_are_not_authority(self):
        chosen = selection()
        invalid = [replace(chosen, evidence=chosen.evidence[:-1]),
                   replace(chosen, evidence=chosen.evidence[:-1] + (chosen.evidence[0],)),
                   replace(chosen, scope=SourceScope('', 'connection', 'task'))]
        for changed in (replace(evidence('proposal'), resource=('github', 'issue', '123:4')),
                        replace(evidence('proposal'), revision=None),
                        replace(evidence('proposal'), actionable_digest='invalid'),
                        replace(evidence('proposal'), revision=('monotonic', '-1'))):
            invalid.append(replace(chosen, evidence=chosen.evidence[:-1] + (changed,)))
        for value in invalid:
            with self.subTest(value=value):
                self.assertEqual(self.plan(chosen=value).reason, 'decision_facts_unavailable')

    def test_actionable_digest_can_preserve_a_source_without_a_revision(self):
        chosen = selection()
        proposal = replace(evidence('proposal'), revision=None, actionable_digest='e' * 64)
        chosen = replace(chosen, evidence=chosen.evidence[:-1] + (proposal,))
        self.assertEqual(self.plan(chosen=chosen).action, 'post_context')
        self.assertEqual(proposal.source_check()['revision'], None)

    def test_caller_constructed_context_keys_cannot_retarget_the_work(self):
        chosen = replace(selection(), context=PublicContext(wire.EXPECTED, (999, 5, wire.RESUME, 7)))
        self.assertEqual(self.plan(chosen=chosen).action, 'post_context')
        self.assertEqual(self.plan(chosen=chosen, progress={**record(), 'repository_id': 999}).action, 'hold')
        self.assertEqual(context_basis(chosen.context), wire.BASIS)

    def test_progress_cannot_smuggle_private_fields_into_a_resume_record(self):
        result = self.plan(progress={**record(), 'private_answer': 'PRIVATE_CANARY'}, public=PAIR, resume=True)
        self.assertEqual((result.action, result.reason, result.resume_record),
                         ('hold', 'decision_facts_unavailable', None))
        self.assertNotIn('PRIVATE_CANARY', result.reason)

    def amendment(self, *, replan=False):
        basis = copy.deepcopy(wire.BASIS)
        basis['key']['round'] = 2
        basis['resume_attempt'] = '33333333-3333-4333-8333-333333333333'
        basis['supersedes'] = {'key': copy.deepcopy(wire.KEY), 'context_sha256': wire.DIGEST}
        return replace(selection(), context=prepare_context('Use the revised accepted plan.', basis),
            predecessor=wire.context(), replacement=evidence('replacement'),
            replan=evidence('replan') if replan else None)

    def test_explicit_replacement_after_context_only_has_a_normal_path(self):
        result = self.plan(chosen=self.amendment(), predecessor_public=CONTEXT,
                           predecessor_calls=replace(FIRST, context_posts=1))
        self.assertEqual(result.action, 'post_context')

    def test_resolved_unconsumed_replacement_requires_the_accepted_amendment(self):
        calls = replace(FIRST, context_posts=1, receipt_posts=1)
        self.assertEqual(self.plan(chosen=self.amendment(), predecessor_public=PAIR,
            predecessor_calls=calls).reason, 'decision_amendment_required')
        self.assertEqual(self.plan(chosen=self.amendment(replan=True), predecessor_public=PAIR,
            predecessor_calls=calls).action, 'post_context')

    def test_consumed_replacement_preserves_the_old_attempt_and_uses_the_new_uuid(self):
        chosen = self.amendment(replan=True)
        progress = {**record(), 'attempt_id': wire.RESUME}
        previous_calls = DecisionCallCoverage(True, 1, 1, 1, 'applied')
        result = self.plan(chosen=chosen, progress=progress, public=PAIR, resume=True,
            linked_source_attempt=wire.ATTEMPT, predecessor_public=PAIR, predecessor_calls=previous_calls)
        self.assertEqual(result.action, 'record_resume')
        self.assertEqual(result.resume_record['attempt_id'], '33333333-3333-4333-8333-333333333333')
        self.assertNotEqual(result.resume_record['attempt_id'], wire.ATTEMPT)
        self.assertEqual(progress['attempt_id'], wire.RESUME)

    def test_unknown_prior_resume_cannot_be_bypassed_with_a_new_round(self):
        result = self.plan(chosen=self.amendment(replan=True), predecessor_public=PAIR,
            predecessor_calls=DecisionCallCoverage(True, 1, 1, 1, 'unconfirmed'))
        self.assertEqual(result.reason, 'decision_resume_unknown')
        self.assertEqual(self.plan(chosen=self.amendment(), predecessor_public=None,
                                  predecessor_calls=FIRST).reason, 'decision_predecessor_unknown')

    def test_malformed_public_ids_counts_and_states_are_closed_inputs(self):
        for calls in (replace(FIRST, context_posts=True), replace(FIRST, receipt_posts=4),
                      replace(FIRST, resume_state='unconfirmed'),
                      replace(FIRST, resume_state='not_applied'),
                      replace(FIRST, complete='yes')):
            with self.subTest(calls=calls):
                self.assertEqual(self.plan(calls=calls).reason, 'decision_facts_unavailable')
        for public in (replace(PAIR, context_id=True), replace(PAIR, receipt_id=10),
                       replace(CONTEXT, receipt_id=20), replace(EMPTY, context_id=10)):
            with self.subTest(public=public):
                self.assertEqual(self.plan(public=public).reason, 'decision_facts_unavailable')
