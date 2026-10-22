"""CP8 state oracles shared by producer and both wire consumers."""
from pathlib import Path
import copy
import hashlib
import json
import unittest

from hydra_sdlc import projection as p
from hydra_sdlc.github import ACTIVE_LABEL
from test_projection_read import ReadFixture, issue

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'tests/fixtures/control-v3'
MATRIX=json.loads((FIXTURE/'receipt-states.json').read_text())

class ProjectionContractAlignmentTests(unittest.TestCase):
    def test_terminal_receipt_matrix_for_standard_and_projection_encoders(self):
        self.assertEqual(len(MATRIX['cases']),54)
        contract=MATRIX['contract']
        self.assertEqual(hashlib.sha256((ROOT/contract['path']).read_bytes()).hexdigest(),contract['sha256'])
        frame=json.loads((FIXTURE/'inputs.json').read_text())['frame']
        for case in MATRIX['cases']:
            value=p.read_json(case['wire'].encode())
            for profile in ('standard','projection'):
                with self.subTest(case=case['name'],profile=profile):
                    if profile=='standard':
                        call=lambda:p.standard_reply(copy.deepcopy(value))
                    else:
                        combined=copy.deepcopy(frame)
                        combined['request']=value['request']
                        call=lambda:p.encode(combined)
                    if case['accepted']:
                        call()
                    else:
                        with self.assertRaises(p.ProjectionError):call()

    def test_progress_failure_preserves_complete_issue_membership_and_independent_project(self):
        managed=issue(7)
        managed['labels']=[ACTIVE_LABEL]
        rows={('example/alpha','open',True):[managed],('example/alpha','open',False):[managed,issue(8)],
              ('example/beta','open',False):[issue(4)]}
        fixture=ReadFixture(rows,fail=lambda path:RuntimeError('SYNTHETIC_PROGRESS_ERROR_CANARY') if '/comments' in path else None)
        frame=fixture.read()
        self.assertEqual({w['issue_ref']['id'] for w in frame['work']},{'101:7','101:8','102:4'})
        for project in frame['projects']:
            self.assertEqual(project['coverage']['state'],'complete')
        work=next(w for w in frame['work'] if w['issue_ref']['id']=='101:7')
        self.assertIsNone(work['stage']['value'])
        self.assertEqual(work['stage']['reason'],'progress_unavailable')
        self.assertNotIn('SYNTHETIC_PROGRESS_ERROR_CANARY',json.dumps(frame))
        p.validate_frame(frame)

if __name__=='__main__':unittest.main()
