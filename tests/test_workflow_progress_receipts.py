"""Shared workflow target/source oracles include the actual checkpoint producer."""
from pathlib import Path
import copy,json,sys,tempfile,unittest
from unittest.mock import patch
import test_checkpoint_only as fixture
from hydra_sdlc import projection as p
from hydra_sdlc.control_commands import AdmissionCallContext

FIXTURE=Path(__file__).resolve().parent/'fixtures/control-v3'
EPOCH='00000000-0000-4000-8000-000000000001'


class CaptureCheckpoint(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Installed settings reject symlinked paths; only fixture roots are resolved.
        physical=str(Path(tempfile.gettempdir()).resolve(strict=True))
        with patch('tempfile.tempdir',physical):
            await fixture.CheckpointOnlyTests.asyncSetUp(self)
    new_controller=fixture.CheckpointOnlyTests.new_controller
    result=fixture.CheckpointOnlyTests.result
    checkpoint=fixture.CheckpointOnlyTests.checkpoint

    def command(self,assignment,outcome='candidate_ready'):
        value=fixture.CheckpointOnlyTests.command(self,assignment,outcome)
        value['binding_epoch']=EPOCH
        return value

    async def capture(self):
        self.grant=AdmissionCallContext('bridge',EPOCH,self.grant.repository_ids,self.grant.operations)
        assignment=await self.result(await self.controller.begin(self.url))
        self.ws.dirty=True
        self.reply=await self.checkpoint(assignment)


def actual_checkpoint():
    if sys.version_info < (3,14):
        raise AssertionError('Actual checkpoint fixture requires Python >=3.14; got '+sys.version.split()[0])
    case=CaptureCheckpoint('capture')
    result=unittest.TestResult()
    case.run(result)
    if result.errors or result.failures:
        details='\n'.join(message for _,message in result.errors+result.failures)
        raise AssertionError('Actual checkpoint fixture failed:\n'+details[-4000:])
    if case.reply['request']['outcome']!='applied' or case.reply['request']['receipt']['kind']!='checkpoint':
        raise AssertionError('Actual checkpoint fixture did not produce an applied checkpoint')
    return case.reply


def frame_for(reply):
    template=json.loads((FIXTURE/'inputs.json').read_text())['frame']
    template.update(runtime=copy.deepcopy(reply['runtime']),binding_epoch=reply['binding_epoch'],
        request=copy.deepcopy(reply['request']),observations=copy.deepcopy(reply['observations']),
        projects=[],work=[],relations=[],retry_hints=[])
    template['page']={'state':'complete','scope':'fixture:workflow-receipt','returned_count':0,
        'total_count':0,'next_cursor':None,'reason':None}
    return template


def materialize(row):
    commands=json.loads((FIXTURE/'receipt-states.json').read_text())['commands']
    reply=copy.deepcopy(next(c['reply'] for c in commands if c['name']==row['command']))
    receipt=reply['request']['receipt']
    mode=row['mode']
    if mode=='foreign_repository':receipt['progress_ref']={'source':'github','kind':'progress','id':'102:7'}
    elif mode=='foreign_issue':receipt['progress_ref']={'source':'github','kind':'progress','id':'101:99'}
    elif mode=='wrong_source':receipt['progress_ref']={'source':'codex','kind':'progress','id':'101:7'}
    elif mode=='wrong_kind':receipt['progress_ref']={'source':'github','kind':'issue','id':'101:7'}
    elif mode.startswith('opaque_'):
        receipt['progress_ref']={'source':'github','kind':'issue_comment','id':'example/alpha/comments/600'}
        if mode!='opaque_unbound':
            value={'issue_ref':{'source':'github','kind':'issue','id':'101:7'},
                'attempt_id':'00000000-0000-4000-8000-000000000320','phase':'implementation_done',
                'native_step':None,'head':'a'*40,'contract_revision':'b'*40,'branch':'hydra/issue-7',
                'expected_head':'a'*40,'expected_base':'c'*40,'published_head':None,'wait_reason':None,
                'next_action':'verify_only','pending_action':None,'pr_ref':None,'completion_refs':None,'cleanup_state':None}
            observation={'key':'fixture:workflow:progress','resource':{'source':'github','kind':'progress','id':'example/alpha/comments/600'},
                'revision':None,'observed_at':'2026-10-19T00:00:00Z','last_attempt_at':'2026-10-19T00:00:00Z',
                'availability':'current','coverage':{'state':'complete','scope':'resource:fixture-progress',
                    'returned_count':1,'total_count':1,'next_cursor':None,'reason':None},'reason':None,'value':value}
            if mode=='opaque_wrong_work':value['issue_ref']['id']='101:99'
            if mode=='opaque_stale':observation['availability']='stale'
            if mode=='opaque_partial':observation['coverage'].update(state='partial',total_count=None,reason='page_bound')
            reply['observations'].append(observation)
            if mode!='opaque_unselected':reply['request']['observed_refs'].append({'observation_key':observation['key'],'revision':None})
    return reply


def vectors():
    result=[]
    cases=json.loads((FIXTURE/'workflow-progress.json').read_text())['cases']
    for row in cases:
        reply=materialize(row)
        for profile,value in [('standard',reply),('projection',frame_for(reply))]:
            if row['accepted']:
                if profile=='projection':wire=p.encode(value).decode()
                else:
                    p.standard_reply(value)
                    wire=json.dumps(value)
            else:wire=json.dumps(value)
            result.append({'name':row['name'],'profile':profile,'accepted':row['accepted'],'wire':wire})
    reply=actual_checkpoint()
    for profile,value in [('standard',reply),('projection',frame_for(reply))]:
        if profile=='projection':wire=p.encode(value).decode()
        else:
            p.standard_reply(value)
            wire=json.dumps(value)
        result.append({'name':'actual-checkpoint-producer','profile':profile,'accepted':True,'wire':wire})
    return result


class WorkflowProgressReceiptTests(unittest.TestCase):
    def test_all_workflow_kinds_use_the_shared_target_and_proof_oracles(self):
        values=vectors()
        self.assertEqual(len(values),134)
        for row in values:
            with self.subTest(case=row['name'],profile=row['profile']):
                value=p.read_json(row['wire'].encode())
                call=(lambda:p.validate_frame(value)) if row['profile']=='projection' else (lambda:p.standard_reply(value))
                if row['accepted']:call()
                else:
                    with self.assertRaises(p.ProjectionError):call()

    def test_actual_checkpoint_keeps_its_comment_locator_and_proves_the_target(self):
        reply=actual_checkpoint()
        self.assertEqual(reply['request']['outcome'],'applied')
        locator=reply['request']['receipt']['progress_ref']
        self.assertEqual(locator,{'source':'github','kind':'issue_comment','id':'example/product/comments/741'})
        proofs=[o for o in reply['observations'] if o['resource']['kind']=='progress' and o['resource']['id']==locator['id']]
        self.assertEqual(len(proofs),1)
        self.assertEqual(proofs[0]['value']['issue_ref'],{'source':'github','kind':'issue','id':str(reply['request']['target']['repository_id'])+':4'})
        self.assertEqual((proofs[0]['availability'],proofs[0]['coverage']['state']),('current','complete'))
        self.assertIn({'observation_key':proofs[0]['key'],'revision':None},reply['request']['observed_refs'])
        p.standard_reply(reply)
