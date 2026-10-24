import unittest

from hydra_sdlc.work_records import WorkRecordError
from test_work_evidence import REQUIREMENT, acceptance, clause, compare, snapshot


class ManyRequirementEvidenceTests(unittest.TestCase):
    def test_valid_clauses_can_require_more_than_fifty_outputs_from_one_producer(self):
        requirements = [{**REQUIREMENT, 'selector': 'R-' + str(index).zfill(3)} for index in range(60)]
        clauses = [clause(requirements[:30]), clause(requirements[30:])]
        rows = snapshot(accepted=acceptance(accepted=requirements))
        try:
            value = compare(clauses=clauses, first=rows, second=rows)
        except WorkRecordError as error:
            self.fail('Valid per-clause conditions were rejected by an unrelated binding limit: ' + error.reason)
        self.assertEqual((value.status, value.producer_count, value.clause_count), ('matched', 1, 2))

    def test_limits_apply_to_each_clause_not_to_aggregate_evidence(self):
        requirements = [{**REQUIREMENT, 'selector': 'R-' + str(index).zfill(3)} for index in range(120)]
        clauses = [clause(requirements[offset:offset + 40]) for offset in (0, 40, 80)]
        rows = snapshot(accepted=acceptance(accepted=requirements))
        try:
            value = compare(clauses=clauses, first=rows, second=rows)
        except WorkRecordError as error:
            self.fail('Valid aggregate evidence was rejected by a per-record reference limit: ' + error.reason)
        self.assertEqual((value.status, value.producer_count, value.clause_count), ('matched', 1, 3))

    def test_large_observed_evidence_requires_every_selected_reference(self):
        requirements = [{**REQUIREMENT, 'selector': 'R-' + str(index).zfill(3)} for index in range(120)]
        clauses = [clause(requirements[offset:offset + 40], stage='observed') for offset in (0, 40, 80)]
        rows = snapshot(accepted=acceptance(accepted=requirements, observed=requirements))
        value = compare(clauses=clauses, first=rows, second=rows)
        self.assertEqual((value.status, value.clause_count), ('matched', 3))
        missing = snapshot(accepted=acceptance(accepted=requirements, observed=requirements[:-1]))
        value = compare(clauses=clauses, first=missing, second=missing)
        self.assertEqual((value.status, value.reason, value.unmet_clauses),
                         ('unmet', 'required_observation_missing', 1))

    def test_aggregate_evidence_keeps_reference_validation(self):
        for accepted, observed in (([REQUIREMENT] * 2, []), ([REQUIREMENT], [REQUIREMENT] * 2),
                                   ({}, []), ([REQUIREMENT], {}),
                                   ([{**REQUIREMENT, 'revision': 'bad'}], [])):
            with self.subTest(accepted=accepted, observed=observed):
                rows = snapshot(accepted=acceptance())
                raw = rows[(101, 10)][1].value
                raw.update(accepted=accepted, observed=observed)
                from hydra_sdlc.work_evidence import RequirementEvidenceRead
                from test_work_evidence import document
                rows[(101, 10)] = (rows[(101, 10)][0], RequirementEvidenceRead(document(raw)))
                with self.assertRaises(WorkRecordError):
                    compare(first=rows, second=rows)
