"""Derived facts and actual registered-address rename observations."""
from pathlib import Path
import copy,importlib.util,inspect,json,unittest
from unittest.mock import patch
from hydra_sdlc import projection as p
from hydra_sdlc.projection_read import read_projection
from test_projection_read import ReadFixture,issue
FOLDER=Path(__file__).resolve().parent/'fixtures/control-v3'
spec=importlib.util.spec_from_file_location('derived_vectors',FOLDER/'emit_derived.py')
vectors=importlib.util.module_from_spec(spec);spec.loader.exec_module(vectors)

def hinted(fixture,bindings,**kwargs):
    # Exercise the actual parent behavior without turning its missing new
    # read-hint argument into an import/signature setup error.
    if 'repository_bindings' in inspect.signature(read_projection).parameters:kwargs['repository_bindings']=bindings
    return fixture.read(**kwargs)

def rename_frames(kind):
    cfg={'repos':['example/alpha']}
    snapshot={'revision':7,'global_mode':'running','projects':{'example/alpha':'paused'}}
    first=ReadFixture({('example/alpha','open',False):[issue()]}).read(cfg=cfg,admission_snapshot=snapshot)
    target='example/renamed' if kind=='rename' else 'example/alpha'
    fixture=ReadFixture({(target,'open',False):[issue()]})
    original=fixture.client.transport
    def transport(method,path,payload):
        value=original(method,path,payload)
        if path=='/repos/example/alpha':value.update(id=101 if kind=='rename' else 202,full_name=target)
        return value
    fixture.client.transport=transport
    second=hinted(fixture,{'example/alpha':101},cfg=cfg,admission_snapshot=snapshot)
    return first,second

class DerivedFactTests(unittest.TestCase):
    def test_shared_fact_derivation_and_source_identity_oracles(self):
        rows=list(vectors.cases());self.assertEqual(len(rows),136)
        for row in rows:
            for profile,key in [('projection','frame'),('standard','reply')]:
                with self.subTest(case=row['name'],profile=profile):
                    check=p.encode if profile=='projection' else p.standard_reply
                    if row['accepted_'+profile]:check(row[key])
                    else:
                        with self.assertRaises(p.ProjectionError):check(row[key])

    def test_actual_rename_preserves_numeric_work_identity_and_registered_admission(self):
        first,second=rename_frames('rename')
        self.assertEqual(second['projects'][0]['repository_ref'],first['projects'][0]['repository_ref'])
        self.assertEqual(second['projects'][0]['admission']['value'],'paused')
        self.assertEqual(second['work'][0]['issue_ref']['id'],'101:7')
        repo=next(o for o in second['observations'] if o['resource']['kind']=='repository')
        self.assertEqual(repo['value']['full_name'],'example/renamed')
        self.assertEqual(second['projects'][0]['coverage']['state'],'complete')

    def test_reused_address_never_retargets_the_retained_numeric_repository(self):
        _,second=rename_frames('reuse')
        self.assertFalse(any(o['value'] is not None and o['resource']['kind']=='repository' and o['value']['numeric_id']==202 for o in second['observations']))
        self.assertEqual(second['work'],[])
        self.assertNotEqual(second['projects'][0]['coverage']['state'],'complete')

    def test_invalid_read_hints_fail_before_source_requests_and_cannot_select_a_path(self):
        for value in ([],{'example/alpha':True},{'example/alpha':0},{'example/alpha':'101'},
                      {'example/alpha':9007199254740992},{'../bad':101}):
            fixture=ReadFixture()
            with self.subTest(value=value),self.assertRaises(ValueError):hinted(fixture,value)
            self.assertEqual(fixture.calls,[])
        fixture=ReadFixture()
        value=hinted(fixture,{'example/unregistered':303},cfg={'repos':['example/alpha']})
        self.assertEqual(value['projects'][0]['repository_ref']['id'],'101')
        self.assertTrue(all('/repositories/' not in path and 'unregistered' not in path for _,path,_ in fixture.calls))


    def test_cli_passes_bounded_identity_hints_only_on_the_v3_read_profile(self):
        from contextlib import redirect_stdout,redirect_stderr
        import io
        from hydra_sdlc import cli
        frame=ReadFixture().read(refresh=False)
        args=['control','status','--config','fixture-host.toml','--projection-schema','3',
              '--binding-epoch',frame['binding_epoch'],'--request-id',frame['request_id'],
              '--repository-bindings','{"example/alpha":101}']
        with patch('hydra_sdlc.control.load_host_config',return_value={'repos':['example/alpha']}), \
             patch('hydra_sdlc.projection_read.read_projection',return_value=frame) as read, \
             redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
            try:code=cli.main(args)
            except SystemExit as error:code=error.code
        self.assertEqual(code,0,'Internal v3 identity hints never reached the source reader')
        self.assertEqual(read.call_args.kwargs['repository_bindings'],{'example/alpha':101})
        with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
            try:code=cli.main(['control','status','--repository-bindings','{"example/alpha":101}'])
            except SystemExit as error:code=error.code
        self.assertNotEqual(code,0)

if __name__=='__main__':unittest.main()
