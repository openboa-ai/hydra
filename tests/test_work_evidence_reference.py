import copy
import unittest

from hydra_sdlc.work_evidence import compare_input_evidence
from hydra_sdlc.work_inputs import InputConditions
from hydra_sdlc.work_records import WorkRecordError, parse_binding
from test_work_evidence import (BASIS, OTHER, PIN, PRODUCER, REQUIREMENT, acceptance,
                                binding, clause, compare, delivery, document,
                                relations, snapshot)


class WorkEvidenceReferenceTests(unittest.TestCase):
    def test_reference_conditions_reuse_the_selected_existing_meaning(self):
        value = binding([clause()]).value
        value['input_contract'] = {'kind': 'reference', 'ref': BASIS}
        fixed = parse_binding('<!-- hydra-work:v2 ' + document(value) + ' -->', spec_directory='docs')
        conditions = InputConditions(document({'clauses': [clause()]}))
        matched = compare_input_evidence(fixed, relations(), relations(), snapshot(), snapshot(),
                                         spec_directory='docs', conditions=conditions)
        self.assertEqual(matched.status, 'matched')
        missing = compare_input_evidence(fixed, relations(), relations(), snapshot(), snapshot(),
                                         spec_directory='docs')
        self.assertEqual((missing.status, missing.reason), ('unknown', 'accepted_meaning_unavailable'))

    def test_every_delivery_pin_field_is_bound_to_acceptance(self):
        alternatives = {'attempt_id': '22222222-2222-4222-8222-222222222222',
                        'contract_revision': 'a' * 40, 'spec_revision': 'b' * 40,
                        'source_digest': 'c' * 64, 'head': 'd' * 40, 'merge_sha': 'e' * 40,
                        'pr_number': 9, 'progress_comment_id': 10}
        for field, value in alternatives.items():
            with self.subTest(field=field):
                rows = snapshot(accepted=acceptance(pin={**PIN, field: value}))
                result = compare(first=rows, second=rows)
                self.assertEqual((result.status, result.reason), ('changed', 'acceptance_delivery_changed'))

    def test_one_waiting_producer_does_not_block_an_independent_consumer(self):
        clauses = [clause(), clause(producer=OTHER)]
        edge = relations((PRODUCER, OTHER))
        rows = {**snapshot(), **snapshot(producer=OTHER, delivered=delivery(producer=OTHER, status='pending'))}
        result = compare(clauses=clauses, first=rows, second=rows, first_relation=edge, second_relation=edge)
        self.assertEqual((result.status, result.producer_count), ('unknown', 2))
        independent = compare_input_evidence(binding([]), relations(()), relations(()), rows, rows,
                                              spec_directory='docs')
        self.assertEqual((independent.status, independent.producer_count), ('matched', 0))
        rows[(202, 20)] = (delivery(producer=OTHER), acceptance(producer=OTHER))
        result = compare(clauses=clauses, first=rows, second=copy.deepcopy(rows),
                         first_relation=edge, second_relation=edge)
        self.assertEqual((result.status, result.clause_count), ('matched', 2))

    def test_partial_relations_and_malformed_delivery_stay_distinct(self):
        partial = compare(first_relation=relations(coverage='partial'))
        self.assertEqual((partial.status, partial.reason), ('unknown', 'relations_incomplete'))
        for field, value in (('pr_number', True), ('source_digest', 'bad'), ('merge_sha', 'z' * 40)):
            with self.subTest(field=field):
                rows = snapshot(delivered=delivery(pin={**PIN, field: value}))
                with self.assertRaises(WorkRecordError): compare(first=rows, second=rows)
