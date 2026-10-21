"""Only paired command sources may prove effects; preserve actual checkpoint heads."""
from pathlib import Path
import copy,hashlib,json,unittest
from hydra_sdlc import projection as p
from test_workflow_progress_receipts import actual_checkpoint,frame_for

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'tests/fixtures/control-v3'


def qualified_vectors():
    matrix=json.loads((FIXTURE/'qualified-command-sources.json').read_text())
    pin=matrix['contract']
    assert hashlib.sha256((ROOT/pin['path']).read_bytes()).hexdigest()==pin['sha256']
    commands=json.loads((FIXTURE/'receipt-states.json').read_text())['commands']
    actual=actual_checkpoint()
    result=[]
    for row in matrix['cases']:
        reply=copy.deepcopy(actual if row['command']=='actual-checkpoint' else
            next(c['reply'] for c in commands if c['name']==row['command']))
        request=reply['request'];receipt=request['receipt'];mode=row['mode']
        if row['command']=='actual-checkpoint':
            proof=next(o for o in reply['observations'] if o['resource']['kind']=='progress')
            if mode.startswith('canonical'):
                locator={'source':'github','kind':'progress','id':str(request['target']['repository_id'])+':'+str(request['target']['issue_number'])}
                receipt['progress_ref']=locator;proof['resource']=copy.deepcopy(locator)
            if mode=='missing_proof':reply['observations']=[];request['observed_refs']=[]
            if mode=='unselected':request['observed_refs']=[]
            if mode=='stale':proof['availability']='stale'
            if mode=='partial':proof['coverage'].update(state='partial',total_count=None,reason='fixture_partial')
            if mode in {'wrong_head','canonical_wrong_head'}:proof['value']['head']='f'*40
            if mode=='null_head':proof['value']['head']=None
            if mode=='wrong_attempt':proof['value']['attempt_id']='00000000-0000-4000-8000-000000000999'
            if mode=='null_attempt':proof['value']['attempt_id']=None
            if mode=='wrong_contract':proof['value']['contract_revision']='f'*40
            if mode=='null_contract':proof['value']['contract_revision']=None
            if mode=='active_step':proof['value']['native_step']=receipt['assignment']['step_id']
            if mode=='wrong_issue':proof['value']['issue_ref']['id']=str(request['target']['repository_id'])+':999'
            if mode=='duplicate_selection':request['observed_refs']+=copy.deepcopy(request['observed_refs'])
        elif mode=='unrelated_progress':
            reply['observations']=copy.deepcopy(actual['observations'])
            request['observed_refs']=copy.deepcopy(actual['request']['observed_refs'])
        elif mode=='unknown_without_receipt':
            request.update(outcome='unknown',reason='unsupported_receipt_source',receipt=None,
                observed_refs=[],effect_refs=[],required_next='open_source')
            reply['observations']=[]
        for profile,value in [('standard',reply),('projection',frame_for(reply))]:
            if row['accepted']:
                if profile=='standard':p.standard_reply(value)
                else:p.validate_frame(value)
            wire=p.encode(value).decode() if profile=='projection' and row['accepted'] else json.dumps(value)
            result.append({'name':row['name'],'accepted':row['accepted'],'profile':profile,'wire':wire})
    return result


class QualifiedCommandSourceTests(unittest.TestCase):
    def test_paired_sources_and_actual_checkpoint_readbacks_in_both_profiles(self):
        rows=qualified_vectors()
        self.assertEqual(len(rows),76)
        for row in rows:
            with self.subTest(case=row['name'],profile=row['profile']):
                value=p.read_json(row['wire'].encode())
                call=(lambda:p.standard_reply(value)) if row['profile']=='standard' else (lambda:p.validate_frame(value))
                if row['accepted']:call()
                else:
                    with self.assertRaises(p.ProjectionError):call()
