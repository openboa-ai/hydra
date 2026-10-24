"""P17 rename regressions exercise the real GitHub adapter and both scopes."""
import base64
import copy
import unittest

from hydra_sdlc.connections import ConnectionQuiescence, execute_connection
from hydra_sdlc.control import load_host_config
from hydra_sdlc.github import GitHub, GitHubError
import test_connection_writer as fixtures
from test_project import BASE, BLOB, TOML


RENAMED='example/renamed'


class RenameWire:
    def __init__(self):
        self.calls=[]
        self.old={'id':123,'full_name':RENAMED,'default_branch':'main'}
        self.client=GitHub(transport=self)

    def __call__(self,method,path,payload):
        self.calls.append((method,path,payload))
        if method!='GET' or payload is not None:
            raise AssertionError('A connection source must not write GitHub')
        if path=='/user':
            return {'id':11,'login':'openboa'}
        if path=='/repos/'+fixtures.ALPHA:
            return copy.deepcopy(self.old)
        for name,rid in [(RENAMED,123),(fixtures.BETA,124)]:
            prefix='/repos/'+name
            if path==prefix:
                return {'id':rid,'full_name':name,'default_branch':'main'}
            if path==prefix+'/git/ref/heads/main':
                return {'object':{'sha':BASE}}
            if path==prefix+'/contents/.hydra.toml?ref='+BASE:
                content=TOML.replace('repository_id = 123','repository_id = '+str(rid))
                return {'type':'file','encoding':'base64','content':base64.b64encode(content.encode()).decode(),'sha':BLOB}
            if path.startswith(prefix+'/collaborators/') and path.endswith('/permission'):
                return {'user':{'login':path.split('/')[-2]},'permission':'write'}
        raise GitHubError('Unexpected fixture read')


class ConnectionRenameTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.ConnectionWriterTests();self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.fx.write_state(projects={fixtures.ALPHA:'stopped',fixtures.BETA:'running'})

    def request(self):
        return self.fx.request('update',fixtures.ALPHA,replacement_name=RENAMED)

    def real_call(self,wire):
        import json
        result=execute_connection(self.fx.path,'apply',json.dumps(self.request()),
            github=wire.client,quiescence=self.fx.closure)
        self.assertIsInstance(result,dict)
        return result

    def test_real_github_client_accepts_only_the_explicit_same_id_rename(self):
        wire=RenameWire()
        result=self.real_call(wire)
        self.assertEqual(result['outcome'],'applied',result)
        self.assertEqual(load_host_config(self.fx.path)['repos'],[fixtures.BETA,RENAMED])
        self.assertEqual(self.fx.state()['projects'][RENAMED],'stopped')
        self.assertEqual(self.fx.state()['projects'][fixtures.BETA],'running')
        self.assertTrue(all(m=='GET' and payload is None for m,_,payload in wire.calls))
        self.assertTrue(any('/contents/.hydra.toml?' in path for _,path,_ in wire.calls))

    def test_ordinary_repository_lookup_still_rejects_the_redirected_address(self):
        with self.assertRaises(GitHubError):
            RenameWire().client.repository(fixtures.ALPHA)

    def test_redirect_to_a_different_numeric_repository_has_no_store_effect(self):
        wire=RenameWire();wire.old['id']=999
        before=self.fx.path.read_bytes(),self.fx.state()
        result=self.real_call(wire)
        self.assertNotEqual(result['outcome'],'applied')
        self.assertEqual((self.fx.path.read_bytes(),self.fx.state()),before)

    def test_unrelated_canonical_redirect_is_not_a_rename_witness(self):
        wire=RenameWire();wire.old['full_name']='example/foreign'
        before=self.fx.path.read_bytes(),self.fx.state()
        result=self.real_call(wire)
        self.assertNotEqual(result['outcome'],'applied')
        self.assertEqual((self.fx.path.read_bytes(),self.fx.state()),before)

    def test_running_retained_destination_is_not_overwritten_by_an_old_scope_proof(self):
        f=self.fx
        f.write_state(projects={fixtures.ALPHA:'stopped',fixtures.BETA:'running',RENAMED:'running'})
        before=f.path.read_bytes(),f.state()
        result=f.call(self.request(),quiescence=f.closure)
        self.assertIn(result['outcome'],{'waiting','rejected'},result)
        self.assertEqual((f.path.read_bytes(),f.state()),before)

    def test_stopped_retained_destination_with_pending_responsibility_remains_held(self):
        f=self.fx;f.write_state(projects={fixtures.ALPHA:'stopped',fixtures.BETA:'running',RENAMED:'stopped'})
        before=f.path.read_bytes(),f.state()
        def closure(cfg,repo,purpose,revision):
            value=f.closure(cfg,repo,purpose,revision)
            return ConnectionQuiescence(**{**value.__dict__,'pending':repo==RENAMED})
        result=f.call(self.request(),quiescence=closure)
        self.assertEqual(result['outcome'],'waiting',result)
        self.assertEqual((f.path.read_bytes(),f.state()),before)

    def test_both_exact_stopped_scope_proofs_allow_the_rename_without_resuming(self):
        f=self.fx;f.write_state(projects={fixtures.ALPHA:'stopped',fixtures.BETA:'running',RENAMED:'stopped'})
        seen=[]
        def closure(cfg,repo,purpose,revision):
            seen.append(repo);return f.closure(cfg,repo,purpose,revision)
        result=f.call(self.request(),quiescence=closure)
        self.assertEqual(result['outcome'],'applied',result)
        self.assertEqual(seen,[fixtures.ALPHA,RENAMED])
        self.assertEqual(f.state()['projects'][RENAMED],'stopped')
        self.assertEqual(f.state()['projects'][fixtures.BETA],'running')

    def test_old_scope_proof_cannot_be_reused_for_the_retained_destination(self):
        f=self.fx;f.write_state(projects={fixtures.ALPHA:'stopped',fixtures.BETA:'running',RENAMED:'stopped'})
        def closure(cfg,repo,purpose,revision):
            return f.closure(cfg,fixtures.ALPHA,purpose,revision)
        result=f.call(self.request(),quiescence=closure)
        self.assertEqual(result['outcome'],'waiting',result)
        self.assertIn(fixtures.ALPHA,load_host_config(f.path)['repos'])

    def test_migration_also_checks_retained_destination_responsibility(self):
        f=self.fx;f.write_config(profile=False)
        f.write_state(version=1,global_mode='stopped',
            projects={fixtures.ALPHA:'stopped',fixtures.BETA:'stopped',RENAMED:'stopped'})
        seen=[]
        def closure(cfg,repo,purpose,revision):
            seen.append(repo);return f.closure(cfg,repo,purpose,revision)
        result=f.call(self.request(),quiescence=closure)
        self.assertEqual(result['outcome'],'applied',result)
        self.assertEqual(seen,[None,RENAMED])
        self.assertEqual(f.state()['projects'][RENAMED],'stopped')
