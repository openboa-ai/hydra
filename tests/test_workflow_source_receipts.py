"""Source identity and missing invocation proofs are independent wire oracles."""
from pathlib import Path
import copy,hashlib,json,unittest
from hydra_sdlc import projection as p

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'tests/fixtures/control-v3'


def source_vectors():
    matrix=json.loads((FIXTURE/'workflow-source-receipts.json').read_text())
    contract=matrix['contract']
    assert hashlib.sha256((ROOT/contract['path']).read_bytes()).hexdigest()==contract['sha256']
    commands=json.loads((FIXTURE/'receipt-states.json').read_text())['commands']
    result=[]
    for row in matrix['cases']:
        reply=copy.deepcopy(next(c['reply'] for c in commands if c['name']==row['command']))
        reply['request'].update(copy.deepcopy(row.get('request_patch',{})))
        if reply['request']['receipt'] is not None:
            reply['request']['receipt'].update(copy.deepcopy(row.get('receipt_patch',{})))
        if row.get('proof')=='progress':
            reply['request']['receipt']['evidence_refs']=[reply['request']['receipt']['progress_ref']]
        if row.get('proof')=='check':
            observation={'key':'fixture:unrelated:check','resource':{'source':'github','kind':'check','id':'101:44'},
                'revision':None,'observed_at':'2026-10-19T00:00:00Z','last_attempt_at':'2026-10-19T00:00:00Z',
                'availability':'current','coverage':{'state':'complete','scope':'fixture:unrelated-check',
                    'returned_count':1,'total_count':1,'next_cursor':None,'reason':None},'reason':None,
                'value':{'producer':{'source':'github','kind':'app','id':'fixture'},'name':'unrelated-check',
                         'head':reply['request']['receipt']['candidate']['head'],'status':'completed','conclusion':'success','url':None}}
            reply['observations'].append(observation)
            reply['request']['observed_refs'].append({'observation_key':observation['key'],'revision':None})
            reply['request']['receipt']['evidence_refs']=[observation['resource']]
        frame=json.loads((FIXTURE/'inputs.json').read_text())['frame']
        frame.update(runtime=copy.deepcopy(reply['runtime']),binding_epoch=reply['binding_epoch'],
            request=copy.deepcopy(reply['request']),observations=copy.deepcopy(reply['observations']),projects=[],work=[],relations=[],retry_hints=[])
        frame['page']={'state':'complete','scope':'fixture:source-receipt','returned_count':0,'total_count':0,'next_cursor':None,'reason':None}
        for profile,value in [('standard',reply),('projection',frame)]:
            if row['accepted']:
                if profile=='standard':p.standard_reply(value)
                else:p.validate_frame(value)
            wire=p.encode(value).decode() if profile=='projection' and row['accepted'] else json.dumps(value)
            result.append({'name':row['name'],'command':row['command'],'accepted':row['accepted'],'profile':profile,'wire':wire})
    return result


class WorkflowSourceReceiptTests(unittest.TestCase):
    def test_pr_identity_and_invocation_evidence_in_both_profiles(self):
        rows=source_vectors()
        self.assertEqual(len(rows),82)
        for row in rows:
            with self.subTest(case=row['name'],profile=row['profile']):
                value=p.read_json(row['wire'].encode())
                call=(lambda:p.standard_reply(value)) if row['profile']=='standard' else (lambda:p.validate_frame(value))
                if row['accepted']:call()
                else:
                    with self.assertRaises(p.ProjectionError):call()
