"""Shared source/evidence oracles plus real builder failure sequences."""
from pathlib import Path
import copy,json,unittest
from unittest.mock import patch
from hydra_sdlc import projection as p
from hydra_sdlc.github import ACTIVE_LABEL
from hydra_sdlc.projection_read import read_projection
from test_projection_read import ReadFixture,issue
from test_control_projection import runtime,EPOCH,REQUEST
FIXTURE=Path(__file__).resolve().parent/'fixtures/control-v3'

def source_frames(kind):
    managed=issue();managed['labels']=[ACTIVE_LABEL]
    rows={('example/alpha','open',True):[managed],('example/alpha','open',False):[managed,issue(8)],
          ('example/beta','open',False):[issue(4)]}
    record={'record':{'attempt_id':'00000000-0000-4000-8000-000000000320','phase':'implement',
                     'head':'a'*40,'contract_revision':'b'*40},
            'resource':{'source':'github','kind':'comment','id':'fixture-progress-record'}}
    frames=[]
    for n in range(2):
        fixture=ReadFixture(rows)
        if n==0:effect={'return_value':copy.deepcopy(record)}
        elif kind=='error':effect={'side_effect':RuntimeError('PRIVATE_PROGRESS_SOURCE_CANARY')}
        elif kind=='none':effect={'return_value':None}
        else:
            invalid=copy.deepcopy(record);invalid['record']['head']='not-a-head'
            effect={'return_value':invalid}
        with patch.object(fixture.client,'progress_source',**effect):frames.append(fixture.read())
    return frames

def matrix_frames(row):
    frame=json.loads((FIXTURE/'inputs.json').read_text())['frame']
    for change in row['changes']:
        target=frame
        for key in change['path'][:-1]:target=target[key]
        target[change['path'][-1]]=copy.deepcopy(change['value'])
    commands=json.loads((FIXTURE/'receipt-states.json').read_text())['commands']
    reply=copy.deepcopy(next(c['reply'] for c in commands if c['name']=='admission'))
    reply['observations']=frame['observations']
    reply['request'].update(outcome='rejected',reason='fixture_source_check',receipt=None,effect_refs=[],observed_refs=[],required_next='refresh')
    return frame,reply

class ProjectionSourceCausalityTests(unittest.TestCase):
    def test_shared_source_evidence_matrix_in_both_profiles(self):
        rows=json.loads((FIXTURE/'source-causality.json').read_text())['cases']
        self.assertEqual(len(rows),30)
        for row in rows:
            frame,reply=matrix_frames(row)
            for profile,value in [('projection',frame),('standard',reply)]:
                with self.subTest(case=row['name'],profile=profile):
                    call=(lambda:p.encode(value)) if profile=='projection' else (lambda:p.standard_reply(value))
                    if row['accepted_'+profile]:call()
                    else:
                        with self.assertRaises(p.ProjectionError):call()

    def test_progress_failure_invalidates_stable_source_without_demoting_membership(self):
        for kind in ('error','none','invalid'):
            with self.subTest(kind=kind):
                first,second=source_frames(kind)
                key='github:101:progress:7'
                old=next(o for o in first['observations'] if o['key']==key)
                self.assertEqual(old['availability'],'current')
                observed=next((o for o in second['observations'] if o['key']==key),None)
                self.assertIsNotNone(observed,'Failed progress source omitted its stable-key failure observation')
                self.assertEqual(observed['availability'],'unavailable')
                self.assertEqual(observed['coverage']['state'],'unavailable')
                self.assertIsNone(observed['value'])
                self.assertEqual({w['issue_ref']['id'] for w in second['work']},{'101:7','101:8','102:4'})
                self.assertTrue(all(project['coverage']['state']=='complete' for project in second['projects']))
                self.assertNotIn('PRIVATE_PROGRESS_SOURCE_CANARY',json.dumps(second))

    def test_admission_resource_uses_binding_or_explicit_unavailable_request(self):
        for variant in ('known','source-unavailable','binding-unavailable','read-failed'):
            with self.subTest(variant=variant):
                identity=runtime()
                if variant=='source-unavailable':identity.update(code_digest=None,identity_reason='runtime_source_unavailable')
                if variant=='binding-unavailable':identity.update(control_binding_digest=None,identity_reason='control_binding_unavailable')
                class Control:
                    def snapshot(self):
                        if variant=='read-failed':raise OSError('fixture local read failed')
                        return {'revision':7,'global_mode':'paused','projects':{}}
                with patch('hydra_sdlc.projection_read.control_from_config',return_value=Control()), \
                     patch('hydra_sdlc.projection_read.observe_coordinator',return_value={'state':'free'}), \
                     patch('hydra_sdlc.projection_read.capture_runtime_identity',return_value=identity):
                    frame=read_projection({'repos':['example/alpha'],'host_alias':'fixture','lock_path':'unused'},
                        binding_epoch=EPOCH,request_id=REQUEST,refresh=False,github=ReadFixture().client)
                observed=next(o for o in frame['observations'] if o['resource']['kind']=='admission')
                expected=identity['control_binding_digest'] or 'requested:host-admission'
                self.assertEqual(observed['resource']['id'],expected)
                if variant in ('binding-unavailable','read-failed'):
                    self.assertEqual(observed['availability'],'unavailable')
                    self.assertIsNone(frame['projects'][0]['admission']['value'])
                else:self.assertEqual(observed['availability'],'current')
                self.assertTrue(all(ref['id']==expected for ref in frame['projects'][0]['source_refs'] if ref['kind']=='admission'))

if __name__=='__main__':unittest.main()
