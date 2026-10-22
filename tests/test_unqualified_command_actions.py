"""Unimplemented action profiles cannot self-report an applied result."""
from pathlib import Path
import copy,json,unittest
from hydra_sdlc import projection as p
from test_workflow_progress_receipts import frame_for

FIXTURE=Path(__file__).resolve().parent/'fixtures/control-v3'


def action_vectors():
    commands=json.loads((FIXTURE/'receipt-states.json').read_text())['commands']
    baseline=next(c['reply'] for c in commands if c['name']=='admission')
    result=[]
    targets=[('work_create',{'repository_id':101}),
        ('native_control',{'source':'codex','kind':'native_task','id':'fixture-task'}),
        ('open_record',{'source':'github','kind':'issue','id':'101:7'})]
    for action,target in targets:
        for outcome,accepted in [('applied',False),('unknown',True)]:
            reply=copy.deepcopy(baseline)
            reply['observations']=[]
            reply['request'].update(action=action,target=target,outcome=outcome,receipt=None,
                observed_refs=[],effect_refs=[],reason=None if outcome=='applied' else 'unsupported_command_source',
                required_next='none' if outcome=='applied' else 'open_source')
            for profile,value in [('standard',reply),('projection',frame_for(reply))]:
                if accepted:
                    if profile=='standard':p.standard_reply(value)
                    else:p.validate_frame(value)
                wire=p.encode(value).decode() if accepted and profile=='projection' else json.dumps(value)
                result.append({'name':action+':'+outcome,'profile':profile,'accepted':accepted,'wire':wire})
    return result


class UnqualifiedCommandActionTests(unittest.TestCase):
    def test_unpaired_actions_cannot_claim_applied_without_a_receipt(self):
        rows=action_vectors()
        self.assertEqual(len(rows),12)
        for row in rows:
            with self.subTest(case=row['name'],profile=row['profile']):
                value=p.read_json(row['wire'].encode())
                call=(lambda:p.standard_reply(value)) if row['profile']=='standard' else (lambda:p.validate_frame(value))
                if row['accepted']:call()
                else:
                    with self.assertRaises(p.ProjectionError):call()
