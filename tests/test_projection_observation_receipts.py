"""Exact receipt proof and independent final local observations."""
from pathlib import Path
import copy
import json
import unittest
from unittest.mock import patch

from hydra_sdlc import projection as p
from hydra_sdlc.projection_read import read_projection
from test_control_projection import EPOCH, REQUEST, runtime
from test_projection_read import ReadFixture, issue

FIXTURE=Path(__file__).resolve().parent/'fixtures/control-v3'


class ProjectionObservationReceiptTests(unittest.TestCase):
    def test_cleanup_requires_readback_for_every_operation_and_outcome(self):
        matrix=json.loads((FIXTURE/'cleanup-receipts.json').read_text())
        self.assertEqual(len(matrix['cases']),32)
        frame=json.loads((FIXTURE/'inputs.json').read_text())['frame']
        for row in matrix['cases']:
            for profile in ('standard','projection'):
                with self.subTest(case=row['name'],profile=profile):
                    value=p.read_json(row['wire'].encode())
                    combined=copy.deepcopy(frame);combined['request']=value['request']
                    call=(lambda:p.standard_reply(value)) if profile=='standard' else (lambda:p.encode(combined))
                    if row['accepted']:call()
                    else:
                        with self.assertRaises(p.ProjectionError):call()

    def test_coordinator_failure_is_unavailable_without_hiding_other_sources(self):
        failures=['ownership_file_unsafe','ownership_file_changed',
                  'ownership_changed_during_observation','ownership_observation_unavailable',None,
                  'PRIVATE_COORDINATOR_REASON_CANARY']
        for reason in failures:
            with self.subTest(reason=reason):
                value=ReadFixture({('example/alpha','open',False):[issue()]}).read(
                    owner=lambda _:dict(state='unknown',reason=reason))
                observed=next(o for o in value['observations'] if o['resource']['kind']=='ownership')
                self.assertEqual(observed['availability'],'unavailable')
                self.assertEqual(observed['coverage']['state'],'unavailable')
                self.assertIsNone(observed['value'])
                expected=reason if reason in failures[:4] else 'ownership_unavailable'
                self.assertEqual(observed['reason'],expected)
                self.assertEqual(value['work'][0]['issue_ref']['id'],'101:7')
                self.assertEqual(value['projects'][0]['coverage']['state'],'complete')
                self.assertNotIn('PRIVATE_COORDINATOR_REASON_CANARY',json.dumps(value))
        for state in ('absent','free','busy','native','owned'):
            with self.subTest(healthy=state):
                value=ReadFixture().read(owner=lambda _:dict(state=state))
                observed=next(o for o in value['observations'] if o['resource']['kind']=='ownership')
                self.assertEqual(observed['availability'],'current')
                self.assertEqual(observed['coverage']['state'],'complete')
                self.assertEqual(observed['value']['state'],state)

    def _concurrent_read(self,mode,*,local_failure=False,project_only=False):
        snapshot={'revision':7,'global_mode':'running','projects':{}}
        fixture=ReadFixture({('example/alpha','open',False):[issue()]})
        original=fixture.transport
        samples=[]
        def transport(method,path,payload):
            value=original(method,path,payload)
            if path.startswith('/repos/example/beta/issues'):
                snapshot.update(revision=8)
                if project_only:snapshot['projects']={'example/alpha':mode}
                else:snapshot['global_mode']=mode
            return value
        fixture.client.transport=transport
        class Control:
            def snapshot(self):
                samples.append(len(fixture.calls))
                if local_failure and fixture.calls:raise OSError('PRIVATE_ADMISSION_READ_CANARY')
                return copy.deepcopy(snapshot)
        with patch('hydra_sdlc.projection_read.control_from_config',return_value=Control()), \
             patch('hydra_sdlc.projection_read.observe_coordinator',return_value={'state':'free'}), \
             patch('hydra_sdlc.projection_read.capture_runtime_identity',return_value=runtime()):
            value=read_projection({'repos':['example/alpha','example/beta'],'host_alias':'fixture',
                                   'lock_path':'unused-fixture-lock'},binding_epoch=EPOCH,request_id=REQUEST,
                                  refresh=True,github=fixture.client)
        return value,samples,len(fixture.calls)

    def test_local_admission_is_sampled_after_all_remote_work(self):
        for mode in ('paused','stopped'):
            for project_only in (False,True):
                with self.subTest(mode=mode,project_only=project_only):
                    frame,samples,reads=self._concurrent_read(mode,project_only=project_only)
                    self.assertEqual(samples[-1],reads)
                    admission=next(o for o in frame['observations'] if o['resource']['kind']=='admission')
                    self.assertEqual(admission['value']['revision'],8)
                    self.assertEqual(admission['revision'],{'kind':'monotonic','value':'8'})
                    gates={p['repository_ref']['id']:p['admission']['value'] for p in frame['projects']}
                    self.assertEqual(gates,{'101':mode,'102':'allowed' if project_only else mode})
                    self.assertEqual(frame['work'][0]['admission']['value'],mode)
                    self.assertTrue(all(p['coverage']['state']=='complete' for p in frame['projects']))
                    p.validate_frame(frame)

    def test_final_local_read_failure_preserves_github_and_unknown_gate(self):
        frame,samples,reads=self._concurrent_read('stopped',local_failure=True)
        self.assertEqual(samples[-1],reads)
        admission=next(o for o in frame['observations'] if o['resource']['kind']=='admission')
        self.assertEqual(admission['availability'],'unavailable')
        for project in frame['projects']:
            self.assertIsNone(project['admission']['value'])
            self.assertEqual(project['admission']['reason'],'admission_unavailable')
            self.assertEqual(project['coverage']['state'],'complete')
        self.assertIsNone(frame['work'][0]['admission']['value'])
        self.assertEqual(frame['work'][0]['issue_ref']['id'],'101:7')
        self.assertNotIn('PRIVATE_ADMISSION_READ_CANARY',json.dumps(frame))


if __name__=='__main__':unittest.main()
