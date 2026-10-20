"""Protected v2 reads, legacy execution, and source changes at effect boundaries."""
import copy
import fcntl
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hydra_sdlc.coordinator import HostBusy, coordinator_lock
from hydra_sdlc.native import NativeController
from hydra_sdlc.operations import OperatingControl, OperationDenied
from hydra_sdlc.project import ProjectError, load_project, parse_intake
from hydra_sdlc.runner import Runner
from test_project import BASE, MERGE, TOML, observation
from test_runner import GitHub, Workspace, complete_capabilities


REPO = 'example/product'
URL = f'https://github.com/{REPO}/issues/4'
CURRENT = 'e' * 40
LEGACY = TOML.replace('version = 1', 'version = 2\nwork_source = "legacy_issue"')
NATIVE = TOML.replace('version = 1', 'version = 2\nwork_source = "github_native"')


class SourceGitHub(GitHub):
    def __init__(self, content=LEGACY):
        super().__init__()
        self.contracts = {BASE: content}
        self.current = BASE
        self.reads = []
        self.cfg = load_project(self, REPO)

    def api(self, method, path):
        return {'user': {'login': path.split('/')[-2]}, 'permission': 'write'}

    def repository(self, repo):
        return {'id': 123, 'full_name': repo, 'default_branch': 'main'}

    def ref(self, repo, branch):
        return self.current if branch == 'main' else self.branch

    def file(self, repo, path, revision):
        self.reads.append((path, revision))
        if path != '.hydra.toml':
            raise AssertionError('Unexpected protected file read')
        content = self.contracts[revision]
        return {'content': content, 'sha': hashlib.sha1(content.encode()).hexdigest()}

    def change_source(self, content=NATIVE):
        self.contracts[CURRENT] = content
        self.current = CURRENT


class EffectWorkspace(Workspace):
    def __init__(self, *args):
        super().__init__(*args)
        self.effects = []

    def prepare(self, *args, **kwargs):
        self.effects.append('prepare')
        return super().prepare(*args, **kwargs)

    def fetch_base(self, *args):
        self.effects.append('fetch')
        return super().fetch_base(*args)

    def checkpoint(self, *args):
        self.effects.append('checkpoint')
        return super().checkpoint(*args)

    def verify(self, *args, **kwargs):
        self.effects.append('verify')
        return super().verify(*args, **kwargs)


class WorkSourceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.github = SourceGitHub()
        self.workspace = EffectWorkspace(self.root, self.github)
        self.calls = []
        self.on_execute = lambda: None
        self.outcome = 'candidate_ready'
        self.control = None
        self.lock = self.root / 'host.lock'
        workers = patch('hydra_sdlc.native.residual_workers', return_value=[])
        workers.start()
        self.addCleanup(workers.stop)

    async def capabilities(self, cwd):
        self.calls.append('capabilities')
        return complete_capabilities()

    async def execute(self, assignment, **kwargs):
        self.calls.append(self.github.note['pending_action'])
        if assignment['mode'] == 'workspace_write':
            self.workspace.dirty = True
        self.on_execute()
        return {'status': 'completed', 'detail': {'result': {'outcome': self.outcome}}}

    def runner(self):
        return Runner(self.github, self.workspace, host_alias='fixture', execute=self.execute,
                      capabilities=self.capabilities, operations=self.control)

    def controller(self):
        return NativeController(self.github, self.workspace, repos=[REPO], host_alias='fixture',
                                lock_path=self.lock, operations=self.control)

    async def result(self, controller, assignment, outcome='candidate_ready'):
        return await controller.checkpoint(URL, assignment['attempt_id'], assignment['step_id'],
            assignment['head'], assignment['contract_revision'], outcome)

    def test_native_source_is_readable_but_not_legacy_intake(self):
        self.github.change_source()
        config = load_project(self.github, REPO)
        self.assertEqual(config['work_source'], 'github_native')
        self.assertEqual(config['planning'], {'source': 'issue'})
        with self.assertRaisesRegex(ProjectError, 'work_source_unsupported'):
            parse_intake(self.github.work, config)

    async def test_v2_legacy_executes_cli_and_native_modes(self):
        runner = self.runner()
        self.assertEqual((await runner.step(REPO, 4))['action'], 'continue')
        self.assertIsNone(runner._policy_scope.get())
        self.assertIn('implementation', self.calls)
        self.assertNotIn('execution_mode', self.github.note)
        self.github = SourceGitHub()
        self.workspace = EffectWorkspace(self.root / 'native', self.github)
        controller = self.controller()
        assignment = await controller.begin(URL)
        self.assertEqual(assignment['action'], 'native_task')
        self.assertEqual(self.github.note['execution_mode'], 'native')
        self.assertEqual(load_project(self.github, REPO)['work_source'], 'legacy_issue')
        self.assertEqual((await self.result(controller, assignment, 'stopped'))['reason'], 'stop_requested')
        self.assertIsNone(controller.runner._policy_scope.get())

    async def test_native_source_never_dispatches_legacy_work(self):
        self.github.change_source()
        runner = self.runner()
        result = await runner.step(REPO, 4)
        self.assertEqual(self.calls, [], 'Unsupported work source dispatched a legacy executor')
        self.assertEqual(result['reason'], 'work_source_unsupported')
        self.assertEqual(runner.status([REPO])[0]['wait_reason'], 'work_source_unsupported')
        self.assertEqual(await runner.cycle([REPO]), [])
        self.assertEqual((await self.controller().begin(URL))['reason'], 'work_source_unsupported')
        self.assertEqual(self.github.writes, [])
        self.assertEqual(self.workspace.effects, [])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_unknown_publish_and_foreign_owner_survive_source_change(self):
        await self.runner().step(REPO, 4)
        self.github.note.update(phase='publishing', pending_action='publish', host_alias='other-host',
                                wait_reason='publish_unknown')
        before = copy.deepcopy(self.github.note)
        self.github.change_source()
        writes, effects, calls = len(self.github.writes), len(self.workspace.effects), len(self.calls)
        result = await self.runner().step(REPO, 4)
        self.assertIn(result['reason'], {'policy_changed', 'work_source_unsupported'})
        self.assertEqual(self.github.note, before)
        self.assertEqual(len(self.github.writes), writes)
        self.assertEqual(len(self.workspace.effects), effects)
        self.assertEqual(len(self.calls), calls)

    async def test_candidate_config_cannot_select_source(self):
        (self.root / '.hydra.toml').write_text(NATIVE)
        self.assertEqual((await self.runner().step(REPO, 4))['action'], 'continue')
        self.assertIn('implementation', self.calls)
        self.assertTrue(self.github.reads)
        self.assertTrue(all(path == '.hydra.toml' and revision == BASE for path, revision in self.github.reads))

    async def test_model_return_source_change_is_hold_before_new_work(self):
        self.on_execute = self.github.change_source
        result = await self.runner().step(REPO, 4)
        self.assertIn(result['reason'], {'policy_changed', 'work_source_unsupported'})
        self.assertEqual(self.calls.count('spec_review'), 1)
        self.assertNotIn('implementation', self.calls)
        self.assertNotIn('verify', self.workspace.effects)
        self.assertFalse(any(write[0] in {'push', 'pr', 'merge'} for write in self.github.writes))
        self.assertEqual(self.github.note['contract_revision'], BASE)

    async def test_source_change_after_cli_intent_blocks_model_dispatch(self):
        def after_intent(record):
            if record.get('phase') == 'executing':
                self.github.change_source()
        self.github.on_record = after_intent
        result = await self.runner().step(REPO, 4)
        self.assertEqual(self.calls, ['capabilities'])
        self.assertEqual(result['reason'], 'policy_changed')
        self.assertEqual(self.github.note['pending_action'], 'spec_review')
        self.assertEqual(self.github.note['contract_revision'], BASE)
        self.assertFalse(any(write[0] in {'push', 'pr', 'merge'} for write in self.github.writes))

    async def test_source_change_during_final_issue_read_blocks_cli_dispatch(self):
        issue = self.github.issue
        changed = False
        def after_policy_read(*args):
            nonlocal changed
            result = issue(*args)
            if not changed and self.github.note and self.github.note.get('phase') == 'executing':
                changed = True
                self.github.change_source()
            return result
        self.github.issue = after_policy_read
        result = await self.runner().step(REPO, 4)
        self.assertTrue(changed)
        self.assertEqual(self.calls, ['capabilities'])
        self.assertEqual(result['reason'], 'policy_changed')
        self.assertEqual(self.github.note['pending_action'], 'spec_review')
        self.assertEqual(self.github.note['contract_revision'], BASE)

    async def test_actual_verifier_policy_hold_checkpoints_first_command_edits(self):
        from test_workspace import LocalWorkspace, git
        remote, seed = self.root / 'origin.git', self.root / 'seed'
        remote.mkdir(); seed.mkdir()
        git(remote, 'init', '--bare', '--initial-branch=main')
        git(seed, 'init', '--initial-branch=main')
        spec = seed / 'docs/engineering/task/spec.md'
        spec.parent.mkdir(parents=True)
        spec.write_text('Accepted requirement and regression evidence.')
        (seed / 'src').mkdir()
        (seed / 'src/base.py').write_text('base = True\n')
        git(seed, 'add', '.'); git(seed, 'commit', '-m', 'accepted fixture')
        base = git(seed, 'rev-parse', 'HEAD')
        git(seed, 'remote', 'add', 'origin', str(remote)); git(seed, 'push', 'origin', 'main')
        commands = ["from pathlib import Path; Path('src/retained.py').write_text('retained = True\\n')",
                    "from pathlib import Path; Path('must-not-run').touch()"]
        verification = ''.join('[[verification]]\nargv=' + json.dumps([sys.executable, '-c', command])
                               + '\ncwd="."\ntimeout=20\n' for command in commands)
        old_verification = LEGACY[LEGACY.index('[[verification]]'):LEGACY.index('[[required_checks]]')]
        self.github = SourceGitHub(LEGACY.replace(old_verification, verification))
        self.github.contracts[base] = self.github.contracts.pop(BASE)
        self.github.current = base
        self.github.cfg = load_project(self.github, REPO)
        self.workspace = LocalWorkspace(self.root / 'work', remote)
        owned = self.root / 'work/example/product/issue-4'
        read_ref = self.github.ref
        def source_after_edit(repo, branch):
            if branch == 'main' and (owned / 'src/retained.py').exists():
                self.github.change_source()
            return read_ref(repo, branch)
        self.github.ref = source_after_edit
        async def candidate(assignment, **kwargs):
            self.calls.append(self.github.note['pending_action'])
            if assignment['mode'] == 'workspace_write':
                (owned / 'src/implementation.py').write_text('implemented = True\n')
            return {'status': 'completed', 'detail': {'result': {'outcome': 'candidate_ready'}}}
        runner = self.runner()
        runner.execute = candidate
        self.assertEqual((await runner.step(REPO, 4))['action'], 'continue')
        self.assertEqual((await runner.step(REPO, 4))['reason'], 'policy_changed')
        self.assertEqual(git(owned, 'status', '--porcelain'), '')
        self.assertEqual(git(owned, 'show', 'HEAD:src/retained.py'), 'retained = True')
        self.assertEqual(self.github.note['head'], git(owned, 'rev-parse', 'HEAD'))
        self.assertIsNone(self.github.note['pending_action'])
        self.assertEqual(self.github.note['contract_revision'], base)
        self.assertFalse((owned / 'must-not-run').exists())
        self.assertNotIn('change_review', self.calls)
        self.assertFalse(any(write[0] in {'push', 'pr', 'merge'} for write in self.github.writes))

    async def test_actual_verifier_predispatch_timeout_holds_without_failed_evidence_or_correction(self):
        import time
        from types import SimpleNamespace
        from hydra_sdlc import execution_boundary as boundary
        from test_workspace import LocalWorkspace, git
        remote, seed = self.root / 'origin.git', self.root / 'seed'
        remote.mkdir(); seed.mkdir()
        git(remote, 'init', '--bare', '--initial-branch=main')
        git(seed, 'init', '--initial-branch=main')
        spec = seed / 'docs/engineering/task/spec.md'
        spec.parent.mkdir(parents=True)
        spec.write_text('Accepted requirement and regression evidence.')
        (seed / 'src').mkdir()
        (seed / 'src/base.py').write_text('base = True\n')
        git(seed, 'add', '.'); git(seed, 'commit', '-m', 'accepted fixture')
        base = git(seed, 'rev-parse', 'HEAD')
        git(seed, 'remote', 'add', 'origin', str(remote)); git(seed, 'push', 'origin', 'main')
        verification = '[[verification]]\nargv=' + json.dumps([sys.executable, '-c',
            "from pathlib import Path; Path('must-not-run').touch()"])
        verification += '\ncwd="."\ntimeout=1\n'
        old = LEGACY[LEGACY.index('[[verification]]'):LEGACY.index('[[required_checks]]')]
        self.github = SourceGitHub(LEGACY.replace(old, verification))
        self.github.contracts[base] = self.github.contracts.pop(BASE)
        self.github.current = base
        self.github.cfg = load_project(self.github, REPO)
        self.workspace = LocalWorkspace(self.root / 'work', remote)
        owned = self.root / 'work/example/product/issue-4'
        async def candidate(assignment, **kwargs):
            self.calls.append(self.github.note['pending_action'])
            if assignment['mode'] == 'workspace_write':
                (owned / 'src/implementation.py').write_text('implemented = True\n')
            return {'status': 'completed', 'detail': {'result': {'outcome': 'candidate_ready'}}}
        runner = self.runner()
        runner.execute = candidate
        self.assertEqual((await runner.step(REPO, 4))['action'], 'continue')
        verify = self.workspace.verify
        def delayed_preflight(*args, **kwargs):
            original = kwargs['before_command']
            clock = [time.monotonic()]
            def preflight():
                original()
                clock[0] += 2
            with patch.object(boundary, 'time', SimpleNamespace(monotonic=lambda: clock[0])):
                return verify(*args, **{**kwargs, 'before_command': preflight})
        self.workspace.verify = delayed_preflight
        result = await runner.step(REPO, 4)
        self.assertEqual(result['reason'], 'replan_required')
        self.assertEqual(self.github.note['next_action'], 'diagnose_verification')
        self.assertIsNone(self.github.note['pending_action'])
        self.assertEqual(self.github.note['head'], git(owned, 'rev-parse', 'HEAD'))
        self.assertEqual(self.github.note['contract_revision'], base)
        self.assertFalse(runner.verified_heads)
        self.assertFalse((owned / 'must-not-run').exists())
        self.assertNotIn('correction', self.calls)
        self.assertNotIn('change_review', self.calls)
        self.assertFalse(any(write[0] in {'push', 'pr', 'merge'} for write in self.github.writes))
        from hydra_sdlc.workspace import WorkspaceWait
        with self.assertRaisesRegex(WorkspaceWait, 'verification_output_unavailable'):
            self.workspace.verification_output(hashlib.sha256(b'').hexdigest())

    async def test_actual_initial_worker_policy_denial_clears_intent_without_false_stopped_recovery(self):
        from hydra_sdlc import execution_boundary as boundary
        from test_execution_boundary import WORKER
        worker, marker = self.root / 'worker.py', self.root / 'observations.jsonl'
        worker.write_text(WORKER)
        events, deny_once, mode = [], [True], ['denied_exit']
        async def execute(assignment, **kwargs):
            def preflight():
                if deny_once[0]:
                    deny_once[0] = False
                    self.github.change_source()
                kwargs['before_dispatch']()
            return await boundary.execute_worker(assignment, kwargs['on_identity'],
                lambda _, payload: events.append(payload), kwargs['stop_requested'],
                kwargs.get('resume_thread_id'), worker_source=str(worker), timeout=3, grace=.1, poll=.005,
                before_dispatch=preflight)
        runner = self.runner()
        runner.execute = execute
        def command(_):
            return [sys.executable, '-I', str(worker), str(Path(boundary.__file__).resolve()), mode[0], str(marker)]
        with patch.object(boundary, '_worker_command', side_effect=command):
            result = await runner.step(REPO, 4)
            self.assertEqual(result['reason'], 'policy_changed')
            self.assertIsNone(self.github.note['pending_action'])
            self.assertEqual(self.github.note['contract_revision'], BASE)
            self.assertFalse(any(e['method'] == 'hydra/dispatchIntent' for e in events))
            self.assertFalse(any(write[0] in {'push', 'pr', 'merge'} for write in self.github.writes))
            self.assertIsNone(runner.host_hold_reason)
            self.github.current = BASE
            mode[0] = 'normal'
            resumed = await runner.step(REPO, 4)
        self.assertNotIn(resumed.get('reason'), {'confirm_previous_stopped', 'execution_failed', 'execution_unknown'})
        self.assertTrue(any(e['method'] == 'hydra/dispatchIntent' for e in events))
        for row in marker.read_text().splitlines():
            value = json.loads(row)
            if 'pid' in value:
                with self.assertRaises(ProcessLookupError):
                    __import__('os').kill(value['pid'], 0)

    async def test_actual_worker_source_hold_reconciles_clean_thread_without_publication(self):
        from hydra_sdlc import execution_boundary as boundary
        from test_execution_boundary import WORKER
        worker, marker = self.root / 'worker.py', self.root / 'observations.jsonl'
        worker.write_text(WORKER)
        events = []
        async def execute(assignment, **kwargs):
            def identity(**values):
                if values.get('thread_id'):
                    self.github.change_source()
            return await boundary.execute_worker(assignment, identity, lambda _, p: events.append(p),
                kwargs['stop_requested'], None, worker_source=str(worker), timeout=3, grace=.1, poll=.005,
                before_dispatch=kwargs['before_dispatch'])
        runner = self.runner()
        runner.execute = execute
        command = [sys.executable, '-I', str(worker), str(Path(boundary.__file__).resolve()), 'normal', str(marker)]
        with patch.object(boundary, '_worker_command', return_value=command):
            result = await runner.step(REPO, 4)
        self.assertEqual(result['reason'], 'policy_changed')
        self.assertEqual([e['params']['operation'] for e in events if e['method'] == 'hydra/dispatchIntent'], ['thread/start'])
        self.assertIsNone(self.github.note['pending_action'])
        self.assertEqual(self.github.note['contract_revision'], BASE)
        self.assertFalse(any(write[0] in {'push', 'pr', 'merge'} for write in self.github.writes))
        self.assertIsNone(runner.host_hold_reason)

    async def test_model_return_source_change_preserves_unanswered_decision(self):
        self.outcome = 'needs_decision'
        self.on_execute = self.github.change_source
        result = await self.runner().step(REPO, 4)
        self.assertIn(result['reason'], {'policy_changed', 'work_source_unsupported'})
        self.assertEqual(self.github.note['wait_reason'], 'product_decision')
        self.assertEqual(self.github.note['next_action'], 'operator_decision')
        self.assertNotIn('implementation', self.calls)

    async def test_source_change_after_prepare_blocks_next_workspace_effect(self):
        prepare = self.workspace.prepare
        def changed(*args, **kwargs):
            result = prepare(*args, **kwargs)
            self.github.change_source()
            return result
        self.workspace.prepare = changed
        self.assertEqual((await self.runner().step(REPO, 4))['reason'], 'policy_changed')
        self.assertEqual(self.workspace.effects, ['prepare'])
        self.assertEqual(self.calls, [])

    def test_missing_or_other_repository_effect_binding_denies_without_callback(self):
        runner, calls = self.runner(), []
        for binding in (None, ('another/repository', self.github.cfg)):
            runner._policy_scope.set(binding)
            with self.assertRaises(OperationDenied) as error:
                runner._effect(REPO, calls.append, 'effect')
            self.assertEqual(error.exception.reason, 'project_policy_unbound')
        self.assertEqual(calls, [])

    async def test_protected_policy_reads_are_outside_admission_locks(self):
        self.control = OperatingControl(self.lock, [REPO])
        self.control.set_mode('start')
        read, checked = self.github.file, []
        def assert_unlocked(*args):
            with self.control.control_lock_path.open('rb') as fd:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                checked.append(True)
            return read(*args)
        self.github.file = assert_unlocked
        assignment = await self.controller().begin(URL)
        self.assertEqual(assignment['action'], 'native_task')
        self.assertGreater(len(checked), 2)

    async def test_source_change_between_ticket_and_intent_retains_exact_ticket(self):
        import hydra_sdlc.native as native
        original = native.register_native_assignment
        def registered(*args):
            result = original(*args)
            self.github.change_source()
            return result
        controller = self.controller()
        with patch('hydra_sdlc.native.register_native_assignment', side_effect=registered):
            result = await controller.begin(URL)
        self.assertEqual(result['action'], 'waiting')
        self.assertEqual(result['reason'], 'assignment_record_unconfirmed')
        self.assertIn(result['step_id'].encode(), self.lock.read_bytes())
        with self.assertRaises(HostBusy):
            with coordinator_lock(self.lock):
                self.fail('Partial assignment was discarded')
        self.assertEqual((await self.result(controller, result, 'stopped'))['reason'], 'stop_requested')
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_source_or_pause_after_intent_cannot_return_native_grant(self):
        for change in ('source', 'pause'):
            with self.subTest(change=change):
                self.github = SourceGitHub()
                self.workspace = EffectWorkspace(self.root / change, self.github)
                self.control = OperatingControl(self.lock, [REPO])
                self.control.set_mode('start')
                controller = self.controller()
                intent = controller.runner._intent
                def after_intent(*args, **kwargs):
                    result = intent(*args, **kwargs)
                    if result is not None and result.get('native_step'):
                        self.github.change_source() if change == 'source' else self.control.set_mode('pause')
                    return result
                with patch.object(controller.runner, '_intent', side_effect=after_intent):
                    result = await controller.begin(URL)
                self.assertEqual(result['action'], 'waiting')
                self.assertEqual(result['reason'], 'policy_changed' if change == 'source' else 'host_paused')
                self.assertIn(result['step_id'].encode(), self.lock.read_bytes())
                self.assertEqual(self.github.note['native_step'], result['step_id'])
                # Explicit stop keeps the pre-existing exact cleanup path.
                self.workspace.existing = lambda *args: self.workspace.path
                self.github.record_checkpoint = self.github.record
                stopped = await self.result(controller, result, 'stopped')
                self.assertEqual(stopped['reason'], 'stop_requested')
                self.assertEqual(self.lock.read_bytes(), b'')

    async def test_native_source_change_preserves_ticket_until_exact_stop(self):
        controller = self.controller()
        assignment = await controller.begin(URL)
        before = copy.deepcopy(self.github.note)
        ticket = self.lock.read_bytes()
        self.github.change_source()
        writes, effects = len(self.github.writes), len(self.workspace.effects)
        with self.assertRaises(ValueError):
            await self.result(controller, assignment)
        self.assertEqual(self.github.note, before)
        self.assertEqual(self.lock.read_bytes(), ticket)
        self.assertEqual(len(self.github.writes), writes)
        self.assertEqual(len(self.workspace.effects), effects)
        with self.assertRaises(HostBusy):
            with coordinator_lock(self.lock):
                self.fail('Unconfirmed native owner was released')
        stopped = await self.result(controller, assignment, 'stopped')
        self.assertEqual(stopped['reason'], 'stop_requested')
        self.assertEqual(self.github.note['contract_revision'], BASE)
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_pause_at_final_native_grant_keeps_recovery_identity(self):
        self.control = OperatingControl(self.lock, [REPO])
        self.control.set_mode('start')
        controller = self.controller()
        require_policy = controller.runner._require_policy
        def pause_after_final_policy(repo):
            require_policy(repo)
            if self.github.note and self.github.note.get('native_step'):
                self.control.set_mode('pause')
        with patch.object(controller.runner, '_require_policy', side_effect=pause_after_final_policy):
            result = await controller.begin(URL)
        self.assertEqual(result['reason'], 'host_paused')
        self.assertEqual(result.get('step_id'), self.github.note['native_step'])
        self.assertEqual(result.get('attempt_id'), self.github.note['attempt_id'])
        self.assertIn(result['step_id'].encode(), self.lock.read_bytes())
        self.workspace.existing = lambda *args: self.workspace.path
        self.github.record_checkpoint = self.github.record
        self.assertEqual((await self.result(controller, result, 'stopped'))['reason'], 'stop_requested')
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_final_native_observation_error_keeps_exact_recovery(self):
        for error in (RuntimeError, OSError, ValueError):
            with self.subTest(error=error.__name__):
                self.github = SourceGitHub()
                self.workspace = EffectWorkspace(self.root / error.__name__, self.github)
                self.lock = self.root / (error.__name__ + '.lock')
                controller = self.controller()
                intent, issue = controller.runner._intent, self.github.issue
                failed = False
                def after_intent(*args, **kwargs):
                    result = intent(*args, **kwargs)
                    if result is not None and result.get('native_step'):
                        def unavailable(*args):
                            nonlocal failed
                            if not failed:
                                failed = True
                                raise error('private-observation-canary')
                            return issue(*args)
                        self.github.issue = unavailable
                    return result
                with patch.object(controller.runner, '_intent', side_effect=after_intent):
                    result = await controller.begin(URL)
                self.assertTrue(failed)
                self.assertEqual(result['action'], 'waiting')
                self.assertEqual(result['reason'], 'assignment_observation_unavailable')
                self.assertEqual(result['step_id'], self.github.note['native_step'])
                self.assertEqual(result['attempt_id'], self.github.note['attempt_id'])
                self.assertIn(result['step_id'].encode(), self.lock.read_bytes())
                self.assertNotIn('private-observation-canary', str(result))
                self.assertEqual((await self.result(controller, result, 'stopped'))['reason'], 'stop_requested')
                self.assertEqual(self.lock.read_bytes(), b'')

    async def test_merged_completion_exception_cannot_adopt_active_native_result(self):
        controller = self.controller()
        assignment = await controller.begin(URL)
        assignment = await self.result(controller, assignment)
        self.assertEqual(assignment['phase'], 'implementation')
        self.github.pr = observation()['pr']
        self.github.pr.update(number=7, state='closed', merged=True, merge_commit_sha=MERGE,
            body='<!-- hydra-pr:v1 {"repository_id":123,"issue_number":4} -->')
        self.github.pr['head']['sha'] = self.github.note['head']
        self.github.change_source()
        self.assertTrue(controller.runner._work_config(REPO, 4, self.github.note)['_completion_only'])
        before, ticket = copy.deepcopy(self.github.note), self.lock.read_bytes()
        writes, effects = len(self.github.writes), len(self.workspace.effects)
        with self.assertRaisesRegex(ValueError, 'Delegated policy'):
            await self.result(controller, assignment)
        self.assertEqual(self.github.note, before)
        self.assertEqual(self.lock.read_bytes(), ticket)
        self.assertEqual(len(self.github.writes), writes)
        self.assertEqual(len(self.workspace.effects), effects)
        self.assertEqual((await self.result(controller, assignment, 'stopped'))['reason'], 'stop_requested')


if __name__ == '__main__':
    unittest.main()
