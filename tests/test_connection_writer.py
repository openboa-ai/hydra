"""P17/PC ordered store and real effect-guard oracles, using owned fixtures."""
import copy
from contextlib import contextmanager
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hydra_sdlc import cli, projection
from hydra_sdlc.connections import ConnectionQuiescence, NativeProjectBinding, execute_connection
from hydra_sdlc.control import control_from_config, load_host_config
from hydra_sdlc.operations import MAX_REVISION, OperatingControl, OperationDenied
from hydra_sdlc.runtime_identity import capture_runtime_identity
from test_project import BASE, BLOB, TOML


ALPHA, BETA, NEW = 'example/alpha', 'example/beta', 'example/new'
REQUEST = '11111111-1111-4111-8111-111111111111'
REPLY_FIELDS = set(('connection_schema request_id operation repository outcome reason runtime '
    'before_config_digest after_config_digest admission_revision config_applied stopped_applied '
    'finalized configured proposed_configured observations').split())


class ProcessLoss(BaseException):
    pass


class Source:
    user = 'openboa'

    def __init__(self):
        self.ids = {ALPHA: 123, BETA: 124, NEW: 125, 'example/renamed': 123}
        self.calls = []
        self.on_read = lambda: None
        self.fail = False
        self.budgets = []

    def record(self, kind, *args):
        self.calls.append((kind, *args))
        self.on_read()
        if self.fail:
            raise RuntimeError('PRIVATE_PROVIDER_DIAGNOSTIC')

    @contextmanager
    def read_budget(self, **limits):
        self.budgets.append(limits)
        yield

    def _identity(self):
        self.record('identity')
        return {'id': 11, 'login': 'openboa'}

    def repository(self, name):
        self.record('repository', name)
        return {'id': self.ids[name], 'full_name': name, 'default_branch': 'main'}

    def ref(self, name, branch):
        self.record('ref', name, branch)
        return BASE

    def file(self, name, path, ref):
        self.record('file', name, path, ref)
        return {'content': TOML.replace('repository_id = 123', 'repository_id = '+str(self.ids[name])),
                'sha': BLOB}

    def api(self, method, path, payload=None):
        if method != 'GET' or payload is not None:
            raise AssertionError('Connection observation must never write GitHub')
        self.record('api', path)
        return {'user': {'login': path.split('/')[-2]}, 'permission': 'write'}


class ConnectionWriterTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.path, self.lock = self.root/'host.toml', self.root/'host.lock'
        self.source = Source()
        self.write_config()
        self.write_state()

    def write_config(self, *, repos=None, profile=True, pending=False):
        repos = [ALPHA, BETA] if repos is None else repos
        text = (f'repos={json.dumps(repos)}\nhost_alias="fixture"\n'
                f'workspace_root={json.dumps(str(self.root/"work"))}\nlock_path={json.dumps(str(self.lock))}\n')
        if profile:
            text += 'connection_schema=1\n'
            for repo in repos:
                desired = 'disconnect_requested' if pending and repo == ALPHA else 'connected'
                text += f'[project_connections.{json.dumps(repo)}]\ndesired="{desired}"\n'
        self.path.write_text(text);self.path.chmod(0o600)

    def write_state(self, *, version=2, projects=None, revision=1, global_mode='running'):
        cfg = load_host_config(self.path);control = control_from_config(cfg)
        state = {'version':version,'revision':revision,'global_mode':global_mode,
                 'projects':{ALPHA:'running',BETA:'running'} if projects is None else projects,
                 'updated_at':'2026-10-24T00:00:00.000000Z'}
        if version == 2:
            state['connection_config'] = {'profile':1,'path':str(self.path)}
        control.control_lock_path.touch(mode=0o600,exist_ok=True);control.control_lock_path.chmod(0o600)
        control.settings_path.write_text(json.dumps(state));control.settings_path.chmod(0o600)
        return control

    def state(self):
        return control_from_config(load_host_config(self.path)).snapshot()

    def digest(self):
        return capture_runtime_identity(load_host_config(self.path))['config_digest']

    def request(self, operation='connect', repository=NEW, **changes):
        row = {'connection_schema':1,'request_id':REQUEST,'operation':operation,'repository':repository,
               'replacement_name':None,'native_project_id':None,
               'expected':{'config_digest':self.digest(),'admission_revision':self.state()['revision'],
                           'repository_id':self.source.ids[repository]}}
        row.update(changes)
        return row

    def closure(self, cfg, repository, purpose, revision):
        return ConnectionQuiescence(capture_runtime_identity(cfg)['config_digest'],revision,
                                    repository,purpose,True,False,False)

    def call(self, request=None, *, action='apply', quiescence=None, native_project=None, raw=None):
        result = execute_connection(self.path,action,
            (json.dumps(request) if request is not None else raw),
            github=self.source,quiescence=quiescence,native_project=native_project)
        self.assertIsInstance(result,dict,'The connection boundary must return an actual typed reply')
        self.assertEqual(set(result),REPLY_FIELDS)
        projection.runtime(result['runtime'])
        for observed in result['observations']:
            projection.observation(observed)
        self.assertNotIn(str(self.path),json.dumps(result))
        return result

    def test_status_is_read_only_and_has_no_request_correlation_or_provider_calls(self):
        before = self.path.read_bytes(),self.state()
        result = self.call(action='status')
        self.assertEqual(result['request_id'],None)
        self.assertEqual(result['operation'],None)
        self.assertEqual(result['repository'],None)
        self.assertEqual(result['configured'][0]['repository'],ALPHA)
        self.assertIsNone(result['proposed_configured'])
        self.assertEqual((self.path.read_bytes(),self.state()),before)
        self.assertEqual(self.source.calls,[])

    def test_preview_observes_policy_and_exact_proposal_without_writing(self):
        before = self.path.read_bytes(),self.state()
        request = self.request();request['expected']['repository_id']=None
        result = self.call(request,action='preview')
        self.assertEqual(result['outcome'],'preview')
        self.assertEqual(result['request_id'],REQUEST)
        self.assertEqual([r['repository'] for r in result['configured']],[ALPHA,BETA])
        self.assertEqual([r['repository'] for r in result['proposed_configured']],[ALPHA,BETA,NEW])
        self.assertFalse(result['config_applied']);self.assertFalse(result['stopped_applied'])
        self.assertEqual((self.path.read_bytes(),self.state()),before)
        self.assertTrue(any(r['value'] and r['value'].get('numeric_id')==125 for r in result['observations']))
        self.assertTrue(any(row[0]=='file' and row[2]=='.hydra.toml' for row in self.source.calls))
        self.assertTrue(self.source.budgets)

    def test_connect_persists_an_explicit_stop_before_registering_and_never_resumes(self):
        result = self.call(self.request())
        self.assertEqual(result['outcome'],'applied',result)
        self.assertTrue(result['config_applied']);self.assertTrue(result['stopped_applied'])
        cfg = load_host_config(self.path)
        self.assertIn(NEW,cfg['repos'])
        self.assertEqual(cfg['project_connections'][NEW],{'desired':'connected'})
        self.assertEqual(self.state()['projects'][NEW],'stopped')
        self.assertEqual(self.state()['projects'][ALPHA],'running')
        self.assertEqual(self.state()['global_mode'],'running')
        self.assertEqual(self.path.stat().st_mode&0o777,0o600)
        self.assertEqual(self.state()['version'],2)

    def test_invalid_closed_request_and_oversized_input_have_no_effect_or_remote_read(self):
        good=self.request();before=self.path.read_bytes(),self.state()
        cases=[{**good,'quiescence':True},{**good,'connection_schema':True},
               {**good,'replacement_name':'example/other'},{**good,'repository':'Example/alpha'},
               {**good,'native_project_id':'bad\nlocator'},
               {**good,'expected':{**good['expected'],'admission_revision':True}}]
        raws=[json.dumps(row) for row in cases]+[json.dumps(good)[:-1]+',"request_id":"'+REQUEST+'"}',
              '{"payload":"'+('x'*65537)+'"}',b'\xff']
        for raw in raws:
            with self.subTest(case=str(raw)[:40]):
                result=self.call(raw=raw)
                self.assertEqual(result['outcome'],'rejected')
                self.assertEqual((self.path.read_bytes(),self.state()),before)
        self.assertEqual(self.source.calls,[])

    def test_unknown_or_missing_numeric_identity_cannot_apply_a_connection(self):
        for rid in [None,126,True]:
            with self.subTest(rid=rid):
                request=self.request();request['expected']['repository_id']=rid
                result=self.call(request)
                self.assertEqual(result['outcome'],'rejected')
                self.assertNotIn(NEW,load_host_config(self.path)['repos'])

    def test_duplicate_numeric_repository_is_not_a_second_registration(self):
        self.source.ids[NEW]=123
        result=self.call(self.request())
        self.assertEqual(result['outcome'],'rejected')
        self.assertNotIn(NEW,load_host_config(self.path)['repos'])

    def test_lost_source_does_not_change_config_or_import_a_provider(self):
        self.source.fail=True;before=self.path.read_bytes(),self.state()
        result=self.call(self.request())
        self.assertIn(result['outcome'],{'waiting','unknown','rejected'})
        self.assertEqual((self.path.read_bytes(),self.state()),before)
        self.assertNotIn('PRIVATE_PROVIDER_DIAGNOSTIC',json.dumps(result))

    def test_config_change_during_observation_rejects_stale_expected(self):
        request=self.request();changed=[False]
        def change():
            if not changed[0]:
                changed[0]=True;self.path.write_text(self.path.read_text().replace('host_alias="fixture"','host_alias="changed"'))
        self.source.on_read=change
        result=self.call(request)
        self.assertIn(result['outcome'],{'rejected','unknown'})
        self.assertNotIn(NEW,self.state()['projects'])

    def test_admission_change_during_observation_is_not_silently_repinned(self):
        request=self.request();changed=[False];control=control_from_config(load_host_config(self.path))
        def change():
            if not changed[0]:
                changed[0]=True;control.set_mode_if_current('pause',BETA,expected_revision=1)
        self.source.on_read=change
        result=self.call(request)
        self.assertEqual(result['outcome'],'rejected')
        self.assertNotIn(NEW,load_host_config(self.path)['repos'])
        self.assertEqual(self.state()['projects'][BETA],'paused')

    def test_connect_process_loss_after_stop_preserves_unregistered_stopped_state(self):
        request=self.request()
        with patch('hydra_sdlc.connections._replace_config',side_effect=ProcessLoss()):
            with self.assertRaises(ProcessLoss):
                execute_connection(self.path,'apply',json.dumps(request),github=self.source)
        self.assertNotIn(NEW,load_host_config(self.path)['repos'])
        self.assertEqual(self.state()['projects'][NEW],'stopped')

    def test_disconnect_desired_is_durable_before_a_stop_write_and_cached_writer_is_held(self):
        old=control_from_config(load_host_config(self.path));request=self.request('disconnect',ALPHA)
        with patch.object(OperatingControl,'_write_snapshot',side_effect=ProcessLoss()):
            with self.assertRaises(ProcessLoss):
                execute_connection(self.path,'apply',json.dumps(request),github=self.source)
        self.assertEqual(load_host_config(self.path)['project_connections'][ALPHA]['desired'],'disconnect_requested')
        self.assertEqual(self.state()['projects'][ALPHA],'running')
        with self.assertRaises(OperationDenied):
            with old.guard(ALPHA):
                self.fail('An old cached writer dispatched after the disconnect intent')

    def test_disconnect_works_after_credentials_are_revoked_and_preserves_other_project(self):
        self.source.fail=True
        result=self.call(self.request('disconnect',ALPHA))
        self.assertEqual(result['outcome'],'applied',result)
        self.assertEqual(load_host_config(self.path)['project_connections'][ALPHA]['desired'],'disconnect_requested')
        self.assertEqual(self.state()['projects'][ALPHA],'stopped')
        self.assertEqual(self.state()['projects'][BETA],'running')
        self.assertEqual(self.source.calls,[])

    def test_finalize_requires_current_complete_quiescence_and_keeps_original_references(self):
        self.write_config(pending=True);self.write_state(projects={ALPHA:'stopped',BETA:'running'})
        request=self.request('finalize_disconnect',ALPHA);before=self.path.read_bytes(),self.state()
        result=self.call(request)
        self.assertEqual(result['outcome'],'waiting')
        self.assertFalse(result['finalized'])
        self.assertEqual((self.path.read_bytes(),self.state()),before)
        for name in ['complete','active','pending']:
            def unsafe(cfg,repo,purpose,revision):
                row=self.closure(cfg,repo,purpose,revision)
                return ConnectionQuiescence(**{**row.__dict__,name:name!='complete'})
            result=self.call(request,quiescence=unsafe)
            self.assertEqual(result['outcome'],'waiting')
            self.assertIn(ALPHA,load_host_config(self.path)['repos'])

    def test_finalize_removes_only_selected_config_entries_and_preserves_stopped_history(self):
        self.write_config(pending=True);self.write_state(projects={ALPHA:'stopped',BETA:'running'})
        with self.path.open('a') as out:
            out.write('[project_threads]\n"example/alpha"="'+REQUEST+'"\n')
        result=self.call(self.request('finalize_disconnect',ALPHA),quiescence=self.closure)
        self.assertEqual(result['outcome'],'applied',result)
        self.assertTrue(result['finalized'])
        cfg=load_host_config(self.path)
        self.assertEqual(cfg['repos'],[BETA]);self.assertNotIn(ALPHA,cfg['project_threads'])
        self.assertNotIn(ALPHA,cfg['project_connections'])
        self.assertEqual(self.state()['projects'][ALPHA],'stopped')
        self.assertEqual(self.state()['projects'][BETA],'running')

    def test_last_disconnect_allows_empty_registry_without_claiming_host_idle(self):
        self.write_config(repos=[ALPHA],pending=True);self.write_state(projects={ALPHA:'stopped'})
        result=self.call(self.request('finalize_disconnect',ALPHA),quiescence=self.closure)
        self.assertEqual(result['outcome'],'applied',result)
        self.assertEqual(result['configured'],[])
        self.assertEqual(load_host_config(self.path)['repos'],[])
        self.assertNotIn('can_quit',result)
        self.assertEqual(self.state()['projects'][ALPHA],'stopped')

    def test_update_requires_stopped_target_and_current_owner_closure(self):
        request=self.request('update',ALPHA)
        result=self.call(request,quiescence=self.closure)
        self.assertEqual(result['outcome'],'waiting')
        self.write_state(projects={ALPHA:'stopped',BETA:'running'})
        result=self.call(self.request('update',ALPHA))
        self.assertEqual(result['outcome'],'waiting')
        result=self.call(self.request('update',ALPHA),quiescence=self.closure)
        self.assertEqual(result['outcome'],'applied',result)

    def test_same_numeric_rename_preserves_independent_project_and_does_not_resume(self):
        self.write_state(projects={ALPHA:'stopped',BETA:'running'})
        request=self.request('update',ALPHA,replacement_name='example/renamed')
        result=self.call(request,quiescence=self.closure)
        self.assertEqual(result['outcome'],'applied',result)
        cfg=load_host_config(self.path)
        self.assertEqual(cfg['repos'],[BETA,'example/renamed'])
        self.assertEqual(self.state()['projects']['example/renamed'],'stopped')
        self.assertEqual(self.state()['projects'][BETA],'running')
        self.source.ids[NEW]=126
        invalid=self.request('update','example/renamed',replacement_name=NEW)
        result=self.call(invalid,quiescence=self.closure)
        self.assertEqual(result['outcome'],'rejected')

    def test_native_locator_is_only_saved_from_exact_host_and_repository_source(self):
        request=self.request(native_project_id='opaque-project')
        result=self.call(request)
        self.assertEqual(result['outcome'],'waiting')
        result=self.call(request,native_project=lambda *args:NativeProjectBinding(126,'fixture','opaque-project'))
        self.assertEqual(result['outcome'],'waiting')
        result=self.call(request,native_project=lambda *args:NativeProjectBinding(125,'fixture','opaque-project'))
        self.assertEqual(result['outcome'],'applied',result)
        self.assertEqual(load_host_config(self.path)['project_connections'][NEW]['native_project_id'],'opaque-project')

    def test_update_null_native_locator_explicitly_clears_without_inventing_a_task(self):
        self.write_state(projects={ALPHA:'stopped',BETA:'running'})
        text=self.path.read_text().replace('desired="connected"','desired="connected"\nnative_project_id="opaque-old"',1)
        self.path.write_text(text)
        result=self.call(self.request('update',ALPHA),quiescence=self.closure)
        self.assertEqual(result['outcome'],'applied',result)
        self.assertNotIn('native_project_id',load_host_config(self.path)['project_connections'][ALPHA])

    def test_legacy_migration_requires_stopped_host_and_confirmed_old_writer_shutdown(self):
        self.write_config(profile=False);self.write_state(version=1,global_mode='stopped')
        request=self.request()
        result=self.call(request)
        self.assertEqual(result['outcome'],'waiting')
        self.assertEqual(self.state()['version'],1)
        result=self.call(request,quiescence=self.closure)
        self.assertEqual(result['outcome'],'applied',result)
        self.assertEqual(self.state()['version'],2)
        self.assertEqual(self.state()['global_mode'],'stopped')
        self.assertTrue(all(mode=='stopped' for mode in self.state()['projects'].values()))
        self.assertEqual(load_host_config(self.path)['connection_schema'],1)

    def test_migration_crash_after_binding_does_not_allow_legacy_or_arg_only_dispatch(self):
        self.write_config(profile=False);self.write_state(version=1,global_mode='stopped')
        request=self.request()
        with patch('hydra_sdlc.connections._replace_config',side_effect=ProcessLoss()):
            with self.assertRaises(ProcessLoss):
                execute_connection(self.path,'apply',json.dumps(request),github=self.source,quiescence=self.closure)
        self.assertNotIn('connection_schema',load_host_config(self.path))
        self.assertEqual(self.state()['version'],2)
        with self.assertRaises(OperationDenied):
            with OperatingControl(self.lock,[ALPHA,BETA]).guard(ALPHA):
                self.fail('Arg-only writer escaped the migrated binding')

    def test_stale_quiescence_proof_cannot_finalize_a_current_scope(self):
        self.write_config(pending=True);self.write_state(projects={ALPHA:'stopped',BETA:'running'})
        def stale(cfg,repo,purpose,revision):
            good=self.closure(cfg,repo,purpose,revision)
            return ConnectionQuiescence(**{**good.__dict__,'config_digest':'0'*64})
        result=self.call(self.request('finalize_disconnect',ALPHA),quiescence=stale)
        self.assertEqual(result['outcome'],'waiting')
        self.assertIn(ALPHA,load_host_config(self.path)['repos'])

    def test_revision_exhaustion_never_partially_registers_a_project(self):
        self.write_state(revision=MAX_REVISION)
        result=self.call(self.request())
        self.assertEqual(result['outcome'],'rejected')
        self.assertNotIn(NEW,load_host_config(self.path)['repos'])
        self.assertNotIn(NEW,self.state()['projects'])

    def test_unsafe_config_symlink_or_hardlink_is_not_mutated_or_echoed(self):
        request=self.request();original=self.root/'original.toml';self.path.rename(original)
        self.path.symlink_to(original)
        result=self.call(request);self.assertEqual(result['outcome'],'rejected')
        self.path.unlink()
        import os
        os.link(original,self.path)
        result=self.call(request);self.assertEqual(result['outcome'],'rejected')
        self.assertEqual(self.source.calls,[])

    def test_cli_uses_fixed_config_bounded_json_and_the_same_positive_core(self):
        args=cli.parser().parse_args(['connection','apply','--config',str(self.path)])
        request=self.request()
        with patch.object(cli,'_provider',side_effect=AssertionError('Provider import')):
            result=cli.operate_connection(args,github=self.source,stdin=io.StringIO(json.dumps(request)))
        self.assertIsInstance(result,dict)
        self.assertEqual(result['outcome'],'applied',result)
        self.assertEqual(self.state()['projects'][NEW],'stopped')
        args.action='status'
        result=cli.operate_connection(args,github=self.source,stdin=io.StringIO('not read'))
        self.assertIsNone(result['request_id'])

    def test_duplicate_disconnect_does_not_rewrite_stopped_state_or_configuration(self):
        result=self.call(self.request('disconnect',ALPHA));self.assertEqual(result['outcome'],'applied')
        request=self.request('disconnect',ALPHA);before=self.path.stat().st_mtime_ns,self.state()
        result=self.call(request)
        self.assertEqual(result['outcome'],'applied')
        self.assertEqual((self.path.stat().st_mtime_ns,self.state()),before)

    def test_unregistered_finalize_is_not_assumed_success_from_external_config_removal(self):
        self.write_config(repos=[BETA]);request=self.request('finalize_disconnect',ALPHA)
        result=self.call(request,quiescence=self.closure)
        self.assertEqual(result['outcome'],'rejected')
        self.assertFalse(result['finalized'])

    def test_original_legacy_control_remains_an_independent_positive_control(self):
        self.write_config(profile=False);self.write_state(version=1,global_mode='stopped')
        control=control_from_config(load_host_config(self.path))
        self.assertEqual(control.set_mode_if_current('start',expected_revision=1)['global_mode'],'running')
