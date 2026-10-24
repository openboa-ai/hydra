import copy
import json
import unittest

from hydra_sdlc.github_producer_delivery import ProducerDeliveryRead
from hydra_sdlc.work_evidence import RequirementEvidenceRead, compare_input_evidence
from hydra_sdlc.work_records import WorkRecordError, parse_binding
from hydra_sdlc.work_relations import relation_read


SOURCE = {'repository_id': 101, 'issue_number': 11}
PRODUCER = {'repository_id': 101, 'issue_number': 10}
OTHER = {'repository_id': 202, 'issue_number': 20}
REQUIREMENT = {'repository_id': 101, 'path': 'docs/producer/spec.md',
               'revision': '1' * 40, 'selector': 'R-OUTPUT'}
SECOND_REQUIREMENT = {**REQUIREMENT, 'selector': 'R-SECOND'}
BASIS = {'repository_id': 101, 'path': 'docs/consumer/spec.md',
         'revision': '2' * 40, 'selector': 'Inputs'}
PIN = {'attempt_id': '11111111-1111-4111-8111-111111111111',
       'contract_revision': '3' * 40, 'spec_revision': '4' * 40,
       'source_digest': '7' * 64, 'head': '5' * 40, 'merge_sha': '6' * 40,
       'pr_number': 7, 'progress_comment_id': 8}
AT = '2026-10-24T00:00:00Z'


def document(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def clause(requirements=(REQUIREMENT,), *, producer=PRODUCER, stage='post_merge_verified'):
    return {'producer': copy.deepcopy(producer), 'requirements': sorted(copy.deepcopy(list(requirements)), key=document),
            'required_stage': stage, 'basis': copy.deepcopy(BASIS)}


def binding(clauses):
    value = {**SOURCE, 'source_digest': 'a' * 64, 'kind': 'work', 'create_key': None,
             'delegated_goal': None, 'outcome': 'consume-output', 'requirements': [BASIS],
             'spec': {'path': 'docs/consumer/spec.md', 'revision': '2' * 40},
             'input_contract': {'kind': 'adopted', 'clauses': sorted(copy.deepcopy(clauses), key=document)},
             'delegation_ref': None}
    return parse_binding('<!-- hydra-work:v2 ' + document(value) + ' -->', spec_directory='docs')


def relations(producers=(PRODUCER,), *, coverage='complete', at=AT):
    return relation_read(copy.deepcopy(SOURCE), 'blocked_by', coverage, copy.deepcopy(list(producers)), at)


def delivery(*, producer=PRODUCER, status='verified', pin=PIN, at=AT):
    reason = {'verified': 'delivery_only', 'not_delivered': 'delivery_record_missing',
              'pending': 'post_merge_checks', 'failed': 'post_merge_failed',
              'unknown': 'delivery_source_unavailable', 'changed': 'delivery_progress_changed'}[status]
    return ProducerDeliveryRead(document({'source': producer, 'status': status, 'reason': reason,
        'delivery': pin if status == 'verified' else None, 'observed_at': at}))


def acceptance(*, producer=PRODUCER, pin=PIN, accepted=(REQUIREMENT,), observed=(), coverage='complete'):
    return RequirementEvidenceRead(document({'source': producer, 'delivery': pin, 'coverage': coverage,
        'accepted': copy.deepcopy(list(accepted)), 'observed': copy.deepcopy(list(observed))}))


def snapshot(*, producer=PRODUCER, delivered=None, accepted=None):
    key = (producer['repository_id'], producer['issue_number'])
    return {key: (delivery(producer=producer) if delivered is None else delivered,
                  acceptance(producer=producer) if accepted is None else accepted)}


def compare(*, clauses=None, first=None, second=None, first_relation=None, second_relation=None):
    return compare_input_evidence(binding([clause()] if clauses is None else clauses),
        relations() if first_relation is None else first_relation,
        relations(at='2026-10-24T00:00:01Z') if second_relation is None else second_relation,
        snapshot() if first is None else first, snapshot() if second is None else second,
        spec_directory='docs')


class WorkEvidenceTests(unittest.TestCase):
    def test_independent_work_needs_no_invented_delivery(self):
        value = compare_input_evidence(binding([]), relations(()), relations(()), None, None, spec_directory='docs')
        self.assertEqual((value.status, value.reason, value.producer_count, value.clause_count),
                         ('matched', 'no_required_inputs', 0, 0))

    def test_verified_direct_output_matches_without_an_issue_close(self):
        value = compare()
        self.assertEqual((value.status, value.reason, value.producer_count, value.clause_count),
                         ('matched', 'input_evidence_only', 1, 1))

    def test_missing_delivery_cannot_be_replaced_by_acceptance(self):
        rows = snapshot(delivered=delivery(status='not_delivered'))
        self.assertEqual((compare(first=rows, second=rows).status, compare(first=rows, second=rows).reason),
                         ('unmet', 'required_output_missing'))

    def test_missing_acceptance_is_unknown(self):
        rows = {(101, 10): (delivery(), None)}
        value = compare(first=rows, second=rows)
        self.assertEqual((value.status, value.reason), ('unknown', 'acceptance_unavailable'))

    def test_another_requirement_does_not_satisfy_this_output(self):
        rows = snapshot(accepted=acceptance(accepted=(SECOND_REQUIREMENT,)))
        value = compare(first=rows, second=rows)
        self.assertEqual((value.status, value.reason, value.unmet_clauses),
                         ('unmet', 'required_requirement_missing', 1))

    def test_another_revision_does_not_satisfy_this_output(self):
        rows = snapshot(accepted=acceptance(accepted=({**REQUIREMENT, 'revision': '9' * 40},)))
        value = compare(first=rows, second=rows)
        self.assertEqual((value.status, value.reason), ('unmet', 'required_requirement_missing'))

    def test_observed_stage_requires_requirement_specific_observation(self):
        value = compare(clauses=[clause(stage='observed')])
        self.assertEqual((value.status, value.reason), ('unmet', 'required_observation_missing'))

    def test_observed_stage_matches_actual_observation_input(self):
        rows = snapshot(accepted=acceptance(observed=(REQUIREMENT,)))
        value = compare(clauses=[clause(stage='observed')], first=rows, second=rows)
        self.assertEqual((value.status, value.unmet_clauses), ('matched', 0))

    def test_every_clause_for_one_producer_is_required(self):
        clauses = [clause(), clause((SECOND_REQUIREMENT,))]
        value = compare(clauses=clauses)
        self.assertEqual((value.status, value.clause_count, value.unmet_clauses), ('unmet', 2, 1))
        rows = snapshot(accepted=acceptance(accepted=(REQUIREMENT, SECOND_REQUIREMENT)))
        self.assertEqual(compare(clauses=clauses, first=rows, second=rows).status, 'matched')

    def test_relation_changes_do_not_delete_fixed_conditions(self):
        value = compare(second_relation=relations(()))
        self.assertEqual(value.status, 'changed')
        self.assertEqual(value.reason, 'relations_unstable')

    def test_delivery_pin_changes_hold_the_current_comparison(self):
        second = snapshot(delivered=delivery(pin={**PIN, 'merge_sha': '8' * 40}),
                          accepted=acceptance(pin={**PIN, 'merge_sha': '8' * 40}))
        value = compare(second=second)
        self.assertEqual((value.status, value.reason), ('changed', 'producer_delivery_changed'))

    def test_changed_acceptance_is_not_silently_adopted(self):
        second = snapshot(accepted=acceptance(accepted=(REQUIREMENT, SECOND_REQUIREMENT)))
        value = compare(second=second)
        self.assertEqual((value.status, value.reason), ('changed', 'requirement_evidence_changed'))

    def test_acceptance_from_another_delivery_is_stale(self):
        rows = snapshot(accepted=acceptance(pin={**PIN, 'head': '9' * 40}))
        value = compare(first=rows, second=rows)
        self.assertEqual((value.status, value.reason), ('changed', 'acceptance_delivery_changed'))

    def test_partial_or_unavailable_acceptance_does_not_match(self):
        for coverage in ('partial', 'unavailable'):
            with self.subTest(coverage=coverage):
                rows = snapshot(accepted=acceptance(coverage=coverage))
                value = compare(first=rows, second=rows)
                self.assertEqual((value.status, value.reason), ('unknown', 'acceptance_incomplete'))

    def test_wrong_producer_identity_is_not_a_match(self):
        for pair in ((delivery(producer=OTHER), acceptance()), (delivery(), acceptance(producer=OTHER))):
            with self.subTest(pair=pair):
                rows = {(101, 10): pair}
                with self.assertRaises(WorkRecordError): compare(first=rows, second=rows)

    def test_missing_or_extra_evidence_scope_is_unknown(self):
        for rows in ({}, {**snapshot(), (202, 20): (delivery(producer=OTHER), acceptance(producer=OTHER))}):
            with self.subTest(keys=list(rows)):
                value = compare(first=rows, second=rows)
                self.assertEqual((value.status, value.reason), ('unknown', 'evidence_scope_unavailable'))

    def test_pending_failed_unknown_and_changed_delivery_are_distinct(self):
        expected = {'pending': ('unknown', 'producer_delivery_pending'),
                    'failed': ('unmet', 'producer_delivery_failed'),
                    'unknown': ('unknown', 'producer_delivery_unavailable'),
                    'changed': ('changed', 'producer_delivery_changed')}
        for status, result in expected.items():
            with self.subTest(status=status):
                rows = snapshot(delivered=delivery(status=status))
                value = compare(first=rows, second=rows)
                self.assertEqual((value.status, value.reason), result)

    def test_observation_times_and_set_order_do_not_create_false_drift(self):
        first = snapshot(accepted=acceptance(accepted=(REQUIREMENT, SECOND_REQUIREMENT)))
        second = snapshot(delivered=delivery(at='2026-10-24T00:00:02Z'),
                          accepted=acceptance(accepted=(SECOND_REQUIREMENT, REQUIREMENT)))
        self.assertEqual(compare(first=first, second=second).status, 'matched')

    def test_observation_requires_acceptance_for_the_same_requirement(self):
        rows = snapshot(accepted=acceptance(accepted=(), observed=(REQUIREMENT,)))
        with self.assertRaises(WorkRecordError): compare(first=rows, second=rows)

    def test_raw_model_objects_cannot_replace_internal_observations(self):
        for row in ((delivery().value, acceptance()), (delivery(), acceptance().value), (delivery(),)):
            with self.subTest(types=[type(v).__name__ for v in row]):
                with self.assertRaises(WorkRecordError): compare(first={(101, 10): row}, second={(101, 10): row})

    def test_malformed_closed_schema_and_duplicate_json_are_rejected(self):
        base = acceptance().value
        values = [document({**base, 'authority': True}),
                  document({**base, 'source': {'repository_id': True, 'issue_number': 10}}),
                  document({**base, 'delivery': {**PIN, 'head': 'bad'}}),
                  document({**base, 'accepted': [REQUIREMENT] * 2}),
                  document({**base, 'coverage': 'complete'})[:-1] + ',"coverage":"partial"}',
                  ' ' * 65537]
        for raw in values:
            with self.subTest(size=len(raw)):
                rows = snapshot(accepted=RequirementEvidenceRead(raw))
                with self.assertRaises(WorkRecordError): compare(first=rows, second=rows)

    def test_comparison_does_not_mutate_or_retain_mutable_inputs(self):
        first, second = snapshot(), snapshot()
        before = copy.deepcopy((first, second))
        value = compare(first=first, second=second)
        self.assertEqual((first, second), before)
        exposed = first[(101, 10)][1].value
        exposed['accepted'].clear()
        self.assertEqual(compare(first=first, second=second), value)
        self.assertEqual(value.status, 'matched')

    def test_cross_repository_producers_use_the_same_rules(self):
        edge = relations((OTHER,))
        rows = snapshot(producer=OTHER)
        value = compare(clauses=[clause(producer=OTHER)], first=rows, second=rows,
                        first_relation=edge, second_relation=edge)
        self.assertEqual((value.status, value.producer_count), ('matched', 1))
