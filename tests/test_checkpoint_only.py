"""Checkpoint-only ownership and effect-boundary oracles."""
import unittest
import copy
import json
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from hydra_sdlc import native
import test_native
from hydra_sdlc.control import load_host_config, control_from_config
from hydra_sdlc.control_commands import (AdmissionCallContext, CheckpointStoppedEvidence,
    InvalidAdmissionCommand, execute_checkpoint_command, _runtime_key)
from hydra_sdlc.runtime_identity import capture_runtime_identity
from hydra_sdlc import control_commands
from hydra_sdlc.operations import OperationDenied


class CheckpointOnlyTests(unittest.IsolatedAsyncioTestCase):
    async def test_future_body_shapes_return_unsupported_without_effects(self):
        assignment = await self.implementation()
        before, ticket = copy.deepcopy(self.gh.note), self.lock.read_bytes()
        settings = self.control.settings_path.read_bytes()
        cases = [(2, None, None), (2, ['future'], 'future'),
                 (1, None, {'operation': 'future_operation', 'future': []}),
                 (1, ['future'], {'operation': 'future_operation'})]
        for version, expected, parameters in cases:
            with self.subTest(version=version, expected=expected):
                command = self.command(assignment)
                command.update(command_schema=version, expected=expected, parameters=parameters)
                try:
                    reply = await self.checkpoint(assignment, command=command)
                except InvalidAdmissionCommand:
                    self.fail('Unsupported body must not enter the current schema validator')
                self.assertEqual(reply['request']['outcome'], 'rejected')
                self.assertEqual(reply['request']['reason'], 'unsupported_operation')
                self.assertEqual(reply['request']['target'], command['target'])
                self.assertIsNone(reply['request']['receipt'])
                self.assertEqual(self.gh.note, before)
                self.assertEqual(self.lock.read_bytes(), ticket)
                self.assertEqual(self.control.settings_path.read_bytes(), settings)
                self.assertTrue(self.ws.dirty)

    async def test_issue_edit_after_scoped_validation_cannot_finish_or_retire_design(self):
        from test_spec_reacceptance import SnapshotWorkspace
        from test_project import BASE
        self.ws = SnapshotWorkspace(Path(self.tmp.name) / 'owned', self.gh, [])
        self.ws.root = Path(self.tmp.name)
        self.ws.existing = lambda repo, number, branch: self.ws.path
        spec = self.ws.path / 'docs/engineering/task/spec.md'
        spec.unlink()
        self.ws.snapshots[BASE] = self.ws.contents()
        self.controller = self.new_controller()
        runner = self.controller.runner
        runner.operations = self.control
        assignment = await self.controller.begin(self.url)
        self.assertEqual(assignment['phase'], 'design')
        spec.write_text('Requirement-linked specification with lifecycle acceptance')
        completed_scope = False
        checkpoint = runner._spec_checkpoint
        read = self.gh.issue
        def validated_scope(*args, **kwargs):
            nonlocal completed_scope
            result = checkpoint(*args, **kwargs)
            completed_scope = True
            return result
        def changed_issue(repo, number):
            value = copy.deepcopy(read(repo, number))
            if completed_scope:
                value['title'] += ' changed after scope validation'
            return value
        with patch.object(runner, '_spec_checkpoint', side_effect=validated_scope), \
             patch.object(self.gh, 'issue', side_effect=changed_issue):
            reply = await self.checkpoint(assignment)
        self.assertTrue(completed_scope)
        self.assertEqual(reply['request']['reason'], 'intake_changed', reply)
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual(self.gh.note['native_step'], assignment['step_id'])
        self.assertIn(assignment['step_id'].encode(), self.lock.read_bytes())
        self.assertNotEqual(self.gh.note['phase'], 'design_done')
        self.assertEqual(spec.read_text(), 'Requirement-linked specification with lifecycle acceptance')
        self.assertEqual(self.ws.verification_calls, 0)

    new_controller = test_native.NativeTests.new_controller
    result = test_native.NativeTests.result

    async def asyncSetUp(self):
        await test_native.NativeTests.asyncSetUp(self)
        self.settings = Path(self.tmp.name) / 'host.toml'
        self.settings.write_text('repos = ["example/product", "example/other"]\nhost_alias = "test"\n'
            + f'workspace_root = {json.dumps(self.tmp.name)}\nlock_path = {json.dumps(str(self.lock))}\n')
        self.settings.chmod(0o600)
        cfg = load_host_config(self.settings)
        self.control = control_from_config(cfg)
        self.control.set_mode('resume')
        self.ws.root = Path(self.tmp.name)
        self.ws.existing = lambda repo, number, branch: self.ws.path
        self.gh.repository = lambda repo: {'id': self.gh.cfg['repository_id'], 'full_name': repo}
        self.gh.record_checkpoint = self.gh.record
        self.gh.progress_source = lambda repo, number: {'record': self.gh.progress(repo, number),
            'resource': {'source': 'github', 'kind': 'issue_comment', 'id': 'example/product/comments/741'}}
        self.controller.runner.operations = self.control
        self.grant = AdmissionCallContext('native', None, frozenset({self.gh.cfg['repository_id']}),
                                         frozenset({'workflow_step.checkpoint_only'}))

    def command(self, assignment, outcome='candidate_ready'):
        cfg = load_host_config(self.settings)
        keys = ('attempt_id', 'step_id', 'head', 'contract_revision', 'spec_revision')
        return {'command_schema': 1, 'request_id': '11111111-1111-4111-8111-111111111111',
            'binding_epoch': None, 'action': 'workflow_step',
            'target': {'repository_id': self.gh.cfg['repository_id'], 'issue_number': 4},
            'expected': {'runtime_key': _runtime_key(capture_runtime_identity(cfg, self.control)),
                'admission_revision': self.control.snapshot()['revision'], 'source_checks': [],
                'assignment': {key: assignment.get(key) for key in keys}},
            'effect_key': f"checkpoint:{assignment['attempt_id']}:{assignment['step_id']}",
            'parameters': {'operation': 'checkpoint_only', 'outcome': outcome, 'summary': ''}}

    async def checkpoint(self, assignment, outcome='candidate_ready', command=None, ended_provider=None):
        return await execute_checkpoint_command(self.settings, command or self.command(assignment, outcome),
            context_provider=lambda: self.grant, github=self.gh, controller=self.controller,
            ended_provider=ended_provider)

    def ended(self, assignment):
        runtime = capture_runtime_identity(load_host_config(self.settings), self.control)
        return CheckpointStoppedEvidence(self.gh.cfg['repository_id'], 4, 'test', runtime['control_binding_digest'],
            tuple(assignment.get(k) for k in ('attempt_id', 'step_id', 'head', 'contract_revision', 'spec_revision')),
            'ended', 'current', 'complete', 'ended', 'private-independent-fixture-observation')

    async def test_final_original_phase_is_read_back_before_ticket_release(self):
        assignment = await self.result(await self.controller.begin(self.url))
        self.assertEqual(assignment['phase'], 'implementation')
        self.ws.dirty = True
        observed_final = []
        progress = self.gh.progress
        confirm = native.confirm_native_assignment

        def observe(repo, number):
            record = progress(repo, number)
            if record and record.get('phase') == 'implementation_done':
                observed_final.append(record)
            return record

        def release(step):
            record = progress('example/product', 4)
            self.assertEqual(record['phase'], 'implementation_done')
            self.assertEqual(record['head'], self.ws.head)
            self.assertIsNone(record.get('pending_action'))
            self.assertTrue(observed_final, 'Final source record must be read back first')
            return confirm(step)

        with patch.object(self.gh, 'progress', side_effect=observe), patch.object(
                native, 'confirm_native_assignment', side_effect=release):
            reply = await self.checkpoint(assignment)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(reply['request']['receipt']['progress_ref']['id'], 'example/product/comments/741')
        self.assertEqual(self.ws.verification_calls, 0)
        self.assertEqual(self.lock.read_bytes(), b'')

    async def implementation(self):
        assignment = await self.result(await self.controller.begin(self.url))
        self.ws.dirty = True
        return assignment

    async def test_final_write_ack_loss_keeps_owner_and_retry_does_not_checkpoint_again(self):
        assignment = await self.implementation()
        command = self.command(assignment)
        write = self.gh.record_checkpoint
        def lose_final(repo, number, record):
            write(repo, number, record)
            if record.get('phase') == 'implementation_done':
                raise OSError('private write acknowledgement lost')
        with patch.object(self.gh, 'record_checkpoint', side_effect=lose_final):
            first = await self.checkpoint(assignment, command=command)
        self.assertEqual(first['request']['outcome'], 'unknown')
        self.assertIn(assignment['step_id'].encode(), self.lock.read_bytes())
        self.assertEqual(self.gh.note['native_step'], assignment['step_id'])
        with patch.object(self.ws, 'checkpoint', side_effect=AssertionError('must reconcile, not commit')):
            second = await self.checkpoint(assignment, command=command)
        self.assertEqual(second['request']['outcome'], 'applied', second)

    async def test_outcome_only_legacy_decision_is_completed_before_retirement(self):
        assignment = await self.implementation()
        self.ws.dirty = False
        self.gh.note.update(native_outcome='needs_decision', wait_reason='product_decision',
                            next_action='operator_decision', phase='executing')
        reply = await self.checkpoint(assignment, 'needs_decision')
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.gh.note['phase'], 'implementation_done')
        self.assertEqual(self.gh.note['wait_reason'], 'product_decision')
        self.assertEqual(self.gh.note['resume_phase'], 'implementation')

    async def test_lost_retirement_ack_and_old_request_return_unknown_without_recommit(self):
        assignment = await self.implementation()
        command = self.command(assignment)
        write = self.gh.record_checkpoint
        def lose_retirement(repo, number, record):
            write(repo, number, record)
            if 'native_step' not in record:
                raise OSError('lost retirement')
        with patch.object(self.gh, 'record_checkpoint', side_effect=lose_retirement):
            first = await self.checkpoint(assignment, command=command)
        self.assertEqual(first['request']['outcome'], 'unknown')
        self.assertNotIn('native_step', self.gh.note)
        self.assertIn(assignment['step_id'].encode(), self.lock.read_bytes())
        with patch.object(self.ws, 'checkpoint', side_effect=AssertionError('no duplicate commit')):
            again = await self.checkpoint(assignment, command=command)
        self.assertEqual(again['request']['outcome'], 'unknown')
        self.assertIsNone(again['request']['receipt'])

    async def test_revision_aba_between_progress_and_checkpoint_holds_exact_owner(self):
        assignment = await self.implementation()
        command = self.command(assignment)
        # The first checkpoint effect's authority refresh is a separate boundary.
        provider_calls = []
        def grant():
            provider_calls.append(True)
            if len(provider_calls) == 4:
                self.control.set_mode('pause', 'example/product')
                self.control.set_mode('resume', 'example/product')
            return self.grant
        with patch.object(self.ws, 'checkpoint', side_effect=AssertionError('stale revision must prevent commit')):
            reply = await execute_checkpoint_command(self.settings, command, context_provider=grant,
                github=self.gh, controller=self.controller)
        self.assertEqual(reply['request']['reason'], 'stale_revision', reply)
        self.assertTrue(self.ws.dirty)
        self.assertEqual(self.gh.note['native_step'], assignment['step_id'])
        self.assertIn(assignment['step_id'].encode(), self.lock.read_bytes())

    async def test_current_operation_grant_is_rechecked_before_each_effect(self):
        assignment = await self.implementation()
        calls = []
        def grant():
            calls.append(True)
            if len(calls) >= 4:
                return AdmissionCallContext('native', None, self.grant.repository_ids, frozenset())
            return self.grant
        with patch.object(self.ws, 'checkpoint', side_effect=AssertionError('revoked grant')):
            reply = await execute_checkpoint_command(self.settings, self.command(assignment), context_provider=grant,
                github=self.gh, controller=self.controller)
        self.assertEqual(reply['request']['reason'], 'authority_denied')
        self.assertIn(assignment['step_id'].encode(), self.lock.read_bytes())

    async def test_spec_revision_and_controller_binding_mismatch_have_no_effect(self):
        assignment = await self.implementation()
        command = self.command(assignment)
        command['expected']['assignment']['spec_revision'] = 'e' * 40
        before = copy.deepcopy(self.gh.note)
        reply = await self.checkpoint(assignment, command=command)
        self.assertEqual(reply['request']['reason'], 'stale_assignment')
        self.assertEqual(self.gh.note, before)
        self.controller.runner.host = 'other'
        reply = await self.checkpoint(assignment)
        self.assertEqual(reply['request']['reason'], 'checkpoint_binding_mismatch')
        self.assertEqual(self.gh.note, before)

    async def test_stopped_bypasses_mode_only_and_retains_edits(self):
        assignment = await self.implementation()
        self.control.set_mode('stop', 'example/product')
        reply = await self.checkpoint(assignment, 'stopped', ended_provider=lambda: self.ended(assignment))
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertFalse(self.ws.dirty)
        self.assertEqual(self.gh.note['wait_reason'], 'stop_requested')
        self.assertEqual(self.gh.note['resume_phase'], 'implementation')

    async def test_stopped_json_is_not_ended_proof_and_partial_or_wrong_proofs_do_nothing(self):
        assignment = await self.implementation()
        self.control.set_mode('stop', 'example/product')
        before, ticket = copy.deepcopy(self.gh.note), self.lock.read_bytes()
        proof = self.ended(assignment)
        for provider in (None, lambda: None, lambda: replace(proof, coverage='partial'),
                         lambda: replace(proof, descendants='unknown'),
                         lambda: replace(proof, availability='stale'),
                         lambda: replace(proof, issue_number=5),
                         lambda: replace(proof, control_binding_digest='f' * 64)):
            reply = await self.checkpoint(assignment, 'stopped', ended_provider=provider)
            self.assertEqual(reply['request']['reason'], 'termination_unconfirmed')
            self.assertIsNone(reply['request']['receipt'])
            self.assertEqual(self.gh.note, before)
            self.assertEqual(self.lock.read_bytes(), ticket)
            self.assertTrue(self.ws.dirty)

    async def test_stopped_evidence_is_refreshed_before_checkpoint(self):
        assignment = await self.implementation()
        calls = []
        def evidence():
            calls.append(True)
            return self.ended(assignment) if len(calls) < 3 else None
        with patch.object(self.ws, 'checkpoint', side_effect=AssertionError('unconfirmed writer end')):
            reply = await self.checkpoint(assignment, 'stopped', ended_provider=evidence)
        self.assertEqual(reply['request']['reason'], 'termination_unconfirmed')
        self.assertIn(assignment['step_id'].encode(), self.lock.read_bytes())

    async def test_ended_observation_cannot_keep_earlier_grant_or_config_authorized(self):
        assignment = await self.implementation()
        before = copy.deepcopy(self.gh.note)
        proof = self.ended(assignment)
        initial_grant = self.grant
        def revoke():
            self.grant = replace(self.grant, operations=frozenset())
            return proof
        reply = await self.checkpoint(assignment, 'stopped', ended_provider=revoke)
        self.assertEqual(reply['request']['reason'], 'authority_denied')
        self.assertEqual(self.gh.note, before)
        self.grant = initial_grant
        command = self.command(assignment, 'stopped')
        def change_config():
            self.settings.write_text(self.settings.read_text().replace('host_alias = "test"', 'host_alias = "other"'))
            return proof
        reply = await self.checkpoint(assignment, command=command, ended_provider=change_config)
        self.assertEqual(reply['request']['reason'], 'stale_runtime')
        self.assertEqual(self.gh.note, before)
        self.assertTrue(self.ws.dirty)

    async def test_spec_only_correction_uses_correction_origin_before_plain_design(self):
        review = await self.controller.begin(self.url)
        correction = await self.result(review, 'failed')
        self.assertEqual(correction['phase'], 'design')
        self.assertEqual(self.gh.note['native_correction'], 'spec_revision_required')
        original_resume = self.gh.note.get('native_resume_phase')
        self.ws.dirty = True
        with patch.object(self.ws, 'changed_paths', return_value=['docs/engineering/task/spec.md']), \
             patch.object(self.controller.runner, '_spec_changed', return_value=False), \
             patch.object(self.controller.runner, '_finish_design', side_effect=AssertionError('wrong original phase')):
            reply = await self.checkpoint(correction)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.gh.note['phase'], 'design_done')
        self.assertEqual(self.gh.note['correction_attempt'], 1)
        self.assertEqual(self.gh.note['checkpoint'], 'correction_1_spec_revision_required')
        self.assertEqual(self.gh.note['resume_phase'], original_resume)

    async def test_implementation_correction_completes_without_new_correction(self):
        implementation = await self.implementation()
        correction = await self.result(implementation, 'failed')
        self.ws.dirty = True
        with patch.object(self.controller.runner, '_correct', side_effect=AssertionError('next correction')):
            reply = await self.checkpoint(correction)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.gh.note['phase'], 'implementation_done')
        self.assertEqual(self.gh.note['next_action'], 'verification')
        self.assertEqual(self.gh.note['checkpoint'], 'correction_1_implementation_failure')

    async def test_effect_ceiling_rejects_verification_from_original_phase_helper(self):
        assignment = await self.implementation()
        runner = self.controller.runner
        def unsafe(*args, **kwargs):
            runner._workspace_effect('example/product', 'verify', self.ws.path, [])
        with patch.object(runner, '_complete_implementation', side_effect=unsafe):
            reply = await self.checkpoint(assignment)
        self.assertEqual(reply['request']['reason'], 'checkpoint_effect_unsupported')
        self.assertEqual(self.ws.verification_calls, 0)
        self.assertEqual(self.gh.note['native_step'], assignment['step_id'])

    async def test_stale_final_readback_never_releases_owner(self):
        assignment = await self.implementation()
        progress = self.gh.progress
        def stale(repo, number):
            record = progress(repo, number)
            if record and record.get('phase') == 'implementation_done':
                record['head'] = assignment['head']
            return record
        with patch.object(self.gh, 'progress', side_effect=stale):
            reply = await self.checkpoint(assignment)
        self.assertEqual(reply['request']['outcome'], 'unknown')
        self.assertEqual(self.gh.note['native_step'], assignment['step_id'])
        self.assertIn(assignment['step_id'].encode(), self.lock.read_bytes())

    async def real_git_assignment(self):
        import test_workspace
        root = Path(self.tmp.name) / 'real'
        root.mkdir()
        remote, seed = root / 'origin.git', root / 'seed'
        remote.mkdir(); seed.mkdir()
        git = test_workspace.git
        git(remote, 'init', '--bare', '--initial-branch=main')
        git(seed, 'init', '--initial-branch=main')
        spec = seed / 'docs/engineering/task/spec.md'
        spec.parent.mkdir(parents=True)
        spec.write_text('Requirement-linked specification with lifecycle acceptance')
        (seed / 'src').mkdir()
        (seed / 'src/main.py').write_text('original\n')
        git(seed, 'add', '.')
        git(seed, 'commit', '-m', 'fixture baseline')
        base = git(seed, 'rev-parse', 'HEAD')
        git(seed, 'remote', 'add', 'origin', str(remote))
        git(seed, 'push', 'origin', 'main')
        self.gh.cfg['revision'] = base
        self.ws = test_workspace.LocalWorkspace(root / 'work', remote)
        self.settings.write_text(self.settings.read_text().replace(json.dumps(self.tmp.name), json.dumps(str(self.ws.root))))
        self.controller = self.new_controller()
        self.controller.runner.operations = self.control
        assignment = await self.result(await self.controller.begin(self.url))
        self.assertEqual(assignment['phase'], 'implementation', assignment)
        path = self.ws.existing('example/product', 4, 'hydra/issue-4')
        return assignment, path, base

    async def test_actual_git_final_ack_loss_restarts_without_duplicate_commit_and_can_continue(self):
        from test_workspace import git
        assignment, path, base = await self.real_git_assignment()
        (path / 'src/main.py').write_text('preserved candidate change\n')
        command = self.command(assignment)
        write = self.gh.record_checkpoint
        def lose_final(repo, number, record):
            write(repo, number, record)
            if record.get('phase') == 'implementation_done':
                raise OSError('lost final ACK')
        with patch.object(self.gh, 'record_checkpoint', side_effect=lose_final):
            first = await self.checkpoint(assignment, command=command)
        self.assertEqual(first['request']['outcome'], 'unknown', first)
        committed = git(path, 'rev-parse', 'HEAD')
        self.assertNotEqual(committed, base)
        self.assertEqual(git(path, 'rev-list', '--count', f'{base}..HEAD'), '1')
        self.assertIn(assignment['step_id'].encode(), self.lock.read_bytes())
        self.controller = self.new_controller()
        self.controller.runner.operations = self.control
        with patch.object(self.ws, 'checkpoint', side_effect=AssertionError('recommit on retry')), \
             patch.object(self.controller, '_complete_checkpoint_phase', side_effect=AssertionError('repeat phase')):
            second = await self.checkpoint(assignment, command=command)
        self.assertEqual(second['request']['outcome'], 'applied', second)
        self.assertEqual(second['request']['receipt']['checkpoint_head'], committed)
        self.assertEqual(git(path, 'rev-list', '--count', f'{base}..HEAD'), '1')
        self.assertEqual((path / 'src/main.py').read_text(), 'preserved candidate change\n')
        record = self.gh.progress('example/product', 4)
        # A separate explicit advance remains possible; the old request's lack
        # of attribution does not poison the authenticated current phase.
        with patch.object(self.ws, 'verify', return_value=[{'passed': True, 'exit_code': 0,
                'argv': ['true'], 'cwd': '.', 'output_digest': 'e' * 64}]):
            next_step = await self.controller.advance(self.url, record['attempt_id'], record['head'], record['contract_revision'])
        self.assertEqual(next_step.get('phase'), 'spec_review', next_step)
        self.assertNotEqual(next_step['step_id'], assignment['step_id'])

    async def test_actual_git_commit_ack_loss_holds_until_independent_ended_proof(self):
        from test_workspace import git
        assignment, path, base = await self.real_git_assignment()
        (path / 'src/main.py').write_text('preserve uncertain checkpoint\n')
        command = self.command(assignment, 'needs_decision')
        commit = self.ws.checkpoint
        def lost_commit(*args):
            commit(*args)
            raise OSError('commit completed but ACK lost')
        with patch.object(self.ws, 'checkpoint', side_effect=lost_commit):
            first = await self.checkpoint(assignment, command=command)
        self.assertEqual(first['request']['outcome'], 'unknown')
        head = git(path, 'rev-parse', 'HEAD')
        self.assertNotEqual(head, base)
        ticket = self.lock.read_bytes()
        with patch.object(self.ws, 'checkpoint', side_effect=AssertionError('unattributed commit cannot repeat')):
            again = await self.checkpoint(assignment, command=command)
        self.assertEqual(again['request']['reason'], 'checkpoint_head_unknown')
        self.assertIsNone(again['request']['receipt'])
        self.assertEqual(self.lock.read_bytes(), ticket)
        self.assertEqual(git(path, 'rev-list', '--count', f'{base}..HEAD'), '1')
        stopped = await self.checkpoint(assignment, 'stopped', ended_provider=lambda: self.ended(assignment))
        self.assertEqual(stopped['request']['outcome'], 'applied', stopped)
        self.assertEqual(stopped['request']['receipt']['checkpoint_head'], head)
        self.assertEqual(git(path, 'rev-list', '--count', f'{base}..HEAD'), '1')
        self.assertEqual((path / 'src/main.py').read_text(), 'preserve uncertain checkpoint\n')
        self.assertEqual(self.gh.note['wait_reason'], 'product_decision')
        self.assertEqual(self.gh.note['resume_phase'], 'implementation')
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_accepted_spec_retry_budget_intermediate_ack_loss_finishes_diagnosis(self):
        assignment = await self.implementation()
        self.gh.note['correction_attempt'] = 2
        command = self.command(assignment)
        write = self.gh.record_checkpoint
        def lose_intermediate(repo, number, record):
            write(repo, number, record)
            if record.get('correction_attempt') == 3 and record.get('next_action') == 'spec_review':
                raise OSError('lost spec checkpoint before required diagnosis')
        with patch.object(self.controller.runner, '_spec_changed', return_value=True), \
             patch.object(self.gh, 'record_checkpoint', side_effect=lose_intermediate):
            first = await self.checkpoint(assignment, command=command)
        self.assertEqual(first['request']['outcome'], 'unknown')
        self.assertEqual(self.gh.note['correction_attempt'], 3)
        self.assertEqual(self.gh.note['next_action'], 'spec_review')
        with patch.object(self.controller.runner, '_spec_changed', return_value=True):
            second = await self.checkpoint(assignment, command=command)
        self.assertEqual(second['request']['outcome'], 'applied', second)
        self.assertEqual(self.gh.note['correction_attempt'], 3)
        self.assertEqual(self.gh.note['wait_reason'], 'replan_required')
        self.assertEqual(self.gh.note['next_action'], 'diagnose')
        self.assertEqual(self.gh.note['phase'], 'design_done')

    async def test_design_candidate_finishes_without_spec_review_dispatch(self):
        from test_spec_reacceptance import SnapshotWorkspace
        from test_project import BASE
        self.ws = SnapshotWorkspace(Path(self.tmp.name) / 'owned', self.gh, [])
        self.ws.root = Path(self.tmp.name)
        self.ws.existing = lambda repo, number, branch: self.ws.path
        spec = self.ws.path / 'docs/engineering/task/spec.md'
        spec.unlink()
        self.ws.snapshots[BASE] = self.ws.contents()
        self.controller = self.new_controller()
        self.controller.runner.operations = self.control
        assignment = await self.controller.begin(self.url)
        self.assertEqual(assignment['phase'], 'design')
        spec.write_text('Requirement-linked specification with lifecycle acceptance')
        reply = await self.checkpoint(assignment)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.gh.note['phase'], 'design_done')
        self.assertEqual(self.gh.note['next_action'], 'spec_review')
        self.assertIsNone(self.gh.note.get('resume_phase'))
        self.assertNotIn('native_step', self.gh.note)

    async def test_ticket_release_failure_cannot_fabricate_receipt(self):
        assignment = await self.implementation()
        with patch.object(native, 'confirm_native_assignment', side_effect=OSError('private release fault')):
            reply = await self.checkpoint(assignment)
        self.assertEqual(reply['request']['outcome'], 'unknown')
        self.assertIsNone(reply['request']['receipt'])
        self.assertNotIn('private release fault', json.dumps(reply))
        self.assertIn(assignment['step_id'].encode(), self.lock.read_bytes())
        self.assertNotIn(assignment['step_id'], self.controller.runner.consumed)

    async def test_bridge_binding_is_preserved_on_unsupported_and_successful_replies(self):
        assignment = await self.implementation()
        epoch = '22222222-2222-4222-8222-222222222222'
        self.grant = AdmissionCallContext('bridge', epoch, self.grant.repository_ids, self.grant.operations)
        command = self.command(assignment)
        command['binding_epoch'] = epoch
        unsupported = copy.deepcopy(command)
        unsupported['command_schema'] = 2
        reply = await self.checkpoint(assignment, command=unsupported)
        self.assertEqual(reply['binding_epoch'], epoch)
        self.assertEqual(reply['request']['reason'], 'unsupported_operation')
        reply = await self.checkpoint(assignment, command=command)
        self.assertEqual(reply['binding_epoch'], epoch)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)

    async def test_config_change_between_effects_cannot_continue_with_cached_controller(self):
        assignment = await self.implementation()
        command = self.command(assignment)
        write = self.gh.record_checkpoint
        def change_after_intent(repo, number, record):
            write(repo, number, record)
            if record.get('next_action') == 'checkpoint_only':
                self.settings.write_text(self.settings.read_text().replace('host_alias = "test"', 'host_alias = "other"'))
        with patch.object(self.gh, 'record_checkpoint', side_effect=change_after_intent), \
             patch.object(self.ws, 'checkpoint', side_effect=AssertionError('stale config')):
            reply = await self.checkpoint(assignment, command=command)
        self.assertEqual(reply['request']['reason'], 'stale_runtime')
        self.assertTrue(self.ws.dirty)
        self.assertIn(assignment['step_id'].encode(), self.lock.read_bytes())

    async def test_future_version_and_unknown_operation_keep_bodies_opaque(self):
        class Opaque:
            def __deepcopy__(self, memo):
                raise AssertionError('unsupported body must remain opaque')
        assignment = await self.implementation()
        before, ticket = copy.deepcopy(self.gh.note), self.lock.read_bytes()
        for version, operation in ((2, 'checkpoint_only'), (1, 'future_operation')):
            command = self.command(assignment)
            command.update(command_schema=version, expected={'future': Opaque()}, effect_key=Opaque(),
                           parameters={'operation': operation, 'future': Opaque()})
            reply = await self.checkpoint(assignment, command=command)
            self.assertEqual(reply['request']['reason'], 'unsupported_operation')
            self.assertEqual(reply['request']['request_id'], command['request_id'])
            self.assertEqual(reply['request']['target'], command['target'])
            self.assertIsNone(reply['request']['receipt'])
            self.assertEqual(self.gh.note, before)
            self.assertEqual(self.lock.read_bytes(), ticket)
            self.assertTrue(self.ws.dirty)

    async def test_config_runtime_read_revocation_is_checked_before_first_effect(self):
        assignment = await self.implementation()
        command = self.command(assignment)
        before, ticket = copy.deepcopy(self.gh.note), self.lock.read_bytes()
        capture, configured_reads = control_commands.capture_runtime_identity, []
        def revoke_during_runtime(*args):
            result = capture(*args)
            if args:
                configured_reads.append(True)
                if len(configured_reads) == 2:
                    self.grant = replace(self.grant, operations=frozenset())
            return result
        with patch.object(control_commands, 'capture_runtime_identity', side_effect=revoke_during_runtime):
            reply = await self.checkpoint(assignment, command=command)
        self.assertEqual(reply['request']['reason'], 'authority_denied')
        self.assertEqual(self.gh.note, before)
        self.assertEqual(self.lock.read_bytes(), ticket)
        self.assertTrue(self.ws.dirty)

    async def test_config_failure_discards_prior_identity_and_binding(self):
        assignment = await self.implementation()
        epoch = '22222222-2222-4222-8222-222222222222'
        self.grant = replace(self.grant, surface='bridge', binding_epoch=epoch)
        command = self.command(assignment)
        command['binding_epoch'] = epoch
        before = copy.deepcopy(self.gh.note)
        load, reads = control_commands.load_host_config, []
        def lose_binding(path):
            reads.append(True)
            if len(reads) == 2:
                self.grant = None
                raise OSError('fixture config disappeared')
            return load(path)
        with patch.object(control_commands, 'load_host_config', side_effect=lose_binding):
            reply = await self.checkpoint(assignment, command=command)
        self.assertEqual(reply['request']['reason'], 'host_config_unavailable')
        self.assertIsNone(reply['runtime']['config_digest'])
        self.assertIsNone(reply['runtime']['control_binding_digest'])
        self.assertIsNone(reply['binding_epoch'])
        self.assertEqual(self.gh.note, before)
        self.assertTrue(self.ws.dirty)

    async def test_retirement_keeps_policy_outside_guard_and_original_ticket_inside(self):
        assignment = await self.implementation()
        runner = self.controller.runner
        sequence, active = [], {'retiring': False, 'guarded': False}
        retire, require, guard = runner._retire_assignment, runner._require_policy, runner._guard
        matches, release = native.native_assignment_matches, native.confirm_native_assignment
        write, source = self.gh.record_checkpoint, self.gh.progress_source
        scope = native.assignment_scope('example/product', 4, assignment['attempt_id'],
                                        assignment['head'], assignment['contract_revision'])
        class Consumed(set):
            def add(inner, step):
                if active['retiring']:
                    self.assertTrue(active['guarded'])
                    self.assertEqual(sequence[-1], 'release')
                    sequence.append('consumed')
                super().add(step)
        runner.consumed = Consumed(runner.consumed)
        def fixed_retirement(*args, **kwargs):
            self.assertTrue(kwargs['checkpoint_only'])
            active['retiring'] = True
            try:
                return retire(*args, **kwargs)
            finally:
                active['retiring'] = False
        def policy(repo):
            if active['retiring']:
                self.assertFalse(active['guarded'])
                sequence.append('policy')
            return require(repo)
        def authority():
            if active['retiring']:
                self.assertFalse(active['guarded'])
                sequence.append('authority')
            return self.grant
        @contextmanager
        def admission(*args, **kwargs):
            with guard(*args, **kwargs):
                if active['retiring']:
                    active['guarded'] = True
                    sequence.append('guard')
                try:
                    yield
                finally:
                    active['guarded'] = False
        def exact(step, actual_scope):
            if active['retiring']:
                self.assertTrue(active['guarded'])
                self.assertEqual((step, actual_scope), (assignment['step_id'], scope))
                sequence.append('match')
            return matches(step, actual_scope)
        def record(repo, number, item):
            if active['retiring']:
                self.assertTrue(active['guarded'])
                self.assertNotIn(assignment['step_id'], runner.consumed)
                sequence.append('record')
            return write(repo, number, item)
        def readback(repo, number):
            self.assertTrue(active['guarded'])
            result = source(repo, number)
            self.assertEqual(result['record']['phase'], 'implementation_done')
            self.assertFalse(native.NATIVE_FIELDS.intersection(result['record']))
            sequence.append('readback')
            return result
        def confirm(step):
            self.assertTrue(active['guarded'])
            self.assertEqual(sequence[-1], 'readback')
            self.assertNotIn(step, runner.consumed)
            result = release(step)
            sequence.append('release')
            return result
        with patch.object(runner, '_retire_assignment', side_effect=fixed_retirement), \
             patch.object(runner, '_require_policy', side_effect=policy), \
             patch.object(runner, '_guard', side_effect=admission), \
             patch.object(native, 'native_assignment_matches', side_effect=exact), \
             patch.object(native, 'confirm_native_assignment', side_effect=confirm), \
             patch.object(self.gh, 'record_checkpoint', side_effect=record), \
             patch.object(self.gh, 'progress_source', side_effect=readback):
            reply = await execute_checkpoint_command(self.settings, self.command(assignment),
                context_provider=authority, github=self.gh, controller=self.controller)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(sequence, ['policy', 'authority', 'guard', 'match', 'record',
                                    'readback', 'release', 'consumed'])

    async def test_retirement_revocation_preserves_marker_then_current_grant_recovers(self):
        assignment = await self.implementation()
        command = self.command(assignment)
        runner, grant = self.controller.runner, self.grant
        retire = runner._retire_assignment
        def revoke_at_retirement(*args, **kwargs):
            self.grant = replace(grant, operations=frozenset())
            return retire(*args, **kwargs)
        with patch.object(runner, '_retire_assignment', side_effect=revoke_at_retirement):
            first = await self.checkpoint(assignment, command=command)
        self.assertEqual(first['request']['reason'], 'authority_denied')
        self.assertEqual(self.gh.note['native_step'], assignment['step_id'])
        self.assertTrue(self.gh.note['checkpoint'].startswith('native_complete_'))
        self.assertNotIn(assignment['step_id'], runner.consumed)
        self.assertIn(assignment['step_id'].encode(), self.lock.read_bytes())
        self.grant = grant
        with patch.object(self.ws, 'checkpoint', side_effect=AssertionError('must not recommit')):
            second = await self.checkpoint(assignment, command=command)
        self.assertEqual(second['request']['outcome'], 'applied', second)
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_changed_ticket_at_retirement_never_writes_clean_record(self):
        assignment = await self.implementation()
        runner, retiring = self.controller.runner, []
        retire, matches = runner._retire_assignment, native.native_assignment_matches
        def fixed_retirement(*args, **kwargs):
            retiring.append(True)
            return retire(*args, **kwargs)
        def changed(step, scope):
            return False if retiring else matches(step, scope)
        with patch.object(runner, '_retire_assignment', side_effect=fixed_retirement), \
             patch.object(native, 'native_assignment_matches', side_effect=changed):
            reply = await self.checkpoint(assignment)
        self.assertEqual(reply['request']['reason'], 'native_retirement_binding_mismatch')
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual(self.gh.note['native_step'], assignment['step_id'])
        self.assertNotIn(assignment['step_id'], runner.consumed)
        self.assertIn(assignment['step_id'].encode(), self.lock.read_bytes())

    async def test_checkpoint_ceiling_cannot_route_generic_retirement_or_legacy_helper(self):
        assignment = await self.implementation()
        runner = self.controller.runner
        before, ticket = copy.deepcopy(self.gh.note), self.lock.read_bytes()
        token = runner._checkpoint_ceiling.set(('example/product', self.control.snapshot()['revision'],
                                              lambda: None, {}))
        try:
            with self.assertRaisesRegex(OperationDenied, 'checkpoint_effect_unsupported'):
                runner._effect('example/product', lambda: self.fail('generic retirement callback'),
                               _checkpoint_effect='retire')
            with self.assertRaisesRegex(OperationDenied, 'checkpoint_effect_unsupported'):
                runner._retire_assignment('example/product', 4, self.gh.note)
        finally:
            runner._checkpoint_ceiling.reset(token)
        self.assertEqual(self.gh.note, before)
        self.assertEqual(self.lock.read_bytes(), ticket)
        self.assertNotIn(assignment['step_id'], runner.consumed)

    async def test_policy_observation_cannot_leave_an_earlier_grant_valid_for_effect(self):
        assignment = await self.implementation()
        command = self.command(assignment)
        before = copy.deepcopy(self.gh.note)
        original = self.controller.runner._require_policy
        def policy(repo):
            original(repo)
            # The real policy preflight completed; its external observation
            # can coincide with revocation before the bounded effect starts.
            self.grant = replace(self.grant, operations=frozenset())
        with patch.object(self.controller.runner, '_require_policy', side_effect=policy):
            reply = await self.checkpoint(assignment, command=command)
        self.assertEqual(reply['request']['reason'], 'authority_denied')
        self.assertEqual(self.gh.note, before, 'No progress effect with the earlier grant')
        self.assertTrue(self.ws.dirty)

    async def test_spec_only_correction_rejects_code_delta_even_when_spec_changed(self):
        review = await self.controller.begin(self.url)
        correction = await self.result(review, 'failed')
        self.ws.dirty = True
        with patch.object(self.ws, 'changed_paths', return_value=['docs/engineering/task/spec.md', 'src/main.py']):
            reply = await self.checkpoint(correction)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.gh.note['wait_reason'], 'implementation_before_design_acceptance')
        self.assertEqual(self.gh.note['next_action'], 'diagnose')
        self.assertEqual(self.gh.note['phase'], 'checkpoint')

    async def test_old_spec_change_reason_does_not_hide_completed_implementation_on_restart(self):
        assignment = await self.implementation()
        self.gh.note['correction_reason'] = 'accepted_spec_changed'
        command = self.command(assignment)
        write = self.gh.record_checkpoint
        def lose_final(repo, number, record):
            write(repo, number, record)
            if record.get('phase') == 'implementation_done':
                raise OSError('lost final ACK')
        with patch.object(self.gh, 'record_checkpoint', side_effect=lose_final):
            first = await self.checkpoint(assignment, command=command)
        self.assertEqual(first['request']['outcome'], 'unknown')
        self.controller = self.new_controller()
        self.controller.runner.operations = self.control
        with patch.object(self.ws, 'checkpoint', side_effect=AssertionError('repeat completed commit')):
            second = await self.checkpoint(assignment, command=command)
        self.assertEqual(second['request']['outcome'], 'applied', second)

    async def test_partial_spec_checkpoint_retry_revalidates_out_of_scope_files(self):
        assignment = await self.implementation()
        command = self.command(assignment)
        write = self.gh.record_checkpoint
        def lose_spec(repo, number, record):
            write(repo, number, record)
            if record.get('correction_reason') == 'accepted_spec_changed':
                raise OSError('lost intermediate spec ACK')
        with patch.object(self.ws, 'changed_paths', return_value=['docs/engineering/task/spec.md', 'private/secret.txt']):
            with patch.object(self.gh, 'record_checkpoint', side_effect=lose_spec):
                first = await self.checkpoint(assignment, command=command)
            self.assertEqual(first['request']['outcome'], 'unknown')
            self.assertEqual(self.gh.note['correction_attempt'], 1)
            second = await self.checkpoint(assignment, command=command)
        self.assertEqual(second['request']['outcome'], 'applied', second)
        self.assertEqual(self.gh.note['wait_reason'], 'scope_violation')
        self.assertEqual(self.gh.note['next_action'], 'diagnose')

    async def test_spec_only_decision_keeps_scope_diagnosis_debt(self):
        review = await self.controller.begin(self.url)
        correction = await self.result(review, 'failed')
        # A correction after reacceptance retains an accepted-spec anchor.
        self.gh.note['spec_revision'] = correction['head']
        correction['spec_revision'] = correction['head']
        self.ws.dirty = True
        with patch.object(self.ws, 'changed_paths', return_value=['docs/engineering/task/spec.md', 'src/main.py']):
            reply = await self.checkpoint(correction, 'needs_decision')
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.gh.note['wait_reason'], 'product_decision')
        self.assertEqual(self.gh.note['correction_reason'], 'spec_scope_unknown')
        self.assertEqual(self.gh.note['correction_attempt'], 3)
        self.assertEqual(self.gh.note['next_action'], 'operator_decision')

    async def test_intermediate_decision_spec_ack_loss_replays_scope_debt_before_retirement(self):
        review = await self.controller.begin(self.url)
        correction = await self.result(review, 'failed')
        self.gh.note['spec_revision'] = correction['head']
        self.gh.note['native_resume_phase'] = 'implementation'
        correction['spec_revision'] = correction['head']
        self.ws.dirty = True
        command = self.command(correction, 'needs_decision')
        write = self.gh.record_checkpoint
        def lose_spec(repo, number, record):
            write(repo, number, record)
            if record.get('correction_reason') == 'accepted_spec_changed':
                raise OSError('lost intermediate decision ACK')
        with patch.object(self.ws, 'changed_paths', return_value=['docs/engineering/task/spec.md', 'src/main.py']):
            with patch.object(self.gh, 'record_checkpoint', side_effect=lose_spec):
                first = await self.checkpoint(correction, command=command)
            self.assertEqual(first['request']['outcome'], 'unknown')
            self.assertEqual(self.gh.note['correction_reason'], 'accepted_spec_changed')
            self.assertIn(correction['step_id'].encode(), self.lock.read_bytes())
            second = await self.checkpoint(correction, command=command)
        self.assertEqual(second['request']['outcome'], 'applied', second)
        self.assertEqual(self.gh.note['wait_reason'], 'product_decision')
        self.assertEqual(self.gh.note['correction_reason'], 'spec_scope_unknown')
        self.assertEqual(self.gh.note['correction_attempt'], 3)
        self.assertEqual(self.gh.note['resume_phase'], 'implementation')

    async def invalid_spec_correction(self, *, empty):
        review = await self.controller.begin(self.url)
        correction = await self.result(review, 'failed')
        self.gh.note['spec_revision'] = correction['head']
        correction['spec_revision'] = correction['head']
        spec = self.ws.path / 'docs/engineering/task/spec.md'
        spec.write_text('') if empty else spec.unlink()
        self.ws.dirty = True
        with patch.object(self.ws, 'changed_paths', return_value=['docs/engineering/task/spec.md']):
            reply = await self.checkpoint(correction)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.gh.note['wait_reason'], 'replan_required')
        self.assertEqual(self.gh.note['next_action'], 'diagnose_spec_artifact')
        self.assertEqual(self.gh.note['phase'], 'checkpoint')

    async def test_empty_spec_correction_cannot_shortcut_original_artifact_validation(self):
        await self.invalid_spec_correction(empty=True)

    async def test_missing_spec_correction_cannot_shortcut_original_artifact_validation(self):
        await self.invalid_spec_correction(empty=False)

    async def test_qualified_stopped_decision_preserves_design_scope_debt(self):
        review = await self.controller.begin(self.url)
        correction = await self.result(review, 'failed')
        self.gh.note['spec_revision'] = correction['head']
        correction['spec_revision'] = correction['head']
        self.gh.note['native_outcome'] = 'needs_decision'
        self.gh.note['wait_reason'] = 'product_decision'
        self.ws.dirty = True
        with patch.object(self.ws, 'changed_paths', return_value=['docs/engineering/task/spec.md', 'src/main.py']):
            reply = await self.checkpoint(correction, 'stopped', ended_provider=lambda: self.ended(correction))
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.gh.note['phase'], 'checkpoint')
        self.assertEqual(self.gh.note['wait_reason'], 'product_decision')
        self.assertEqual(self.gh.note['correction_reason'], 'spec_scope_unknown')
        self.assertEqual(self.gh.note['correction_attempt'], 3)

    async def test_no_result_summary_or_broad_continuation_effects(self):
        assignment = await self.implementation()
        command = self.command(assignment)
        canary = 'PRIVATE-P05-CANARY-DO-NOT-PUBLISH'
        command['parameters']['summary'] = canary
        with patch.object(self.controller.runner, '_candidate_result', side_effect=AssertionError('broad callback')), \
             patch.object(self.controller.runner, '_correct', side_effect=AssertionError('new correction')), \
             patch.object(self.controller.runner, 'step', side_effect=AssertionError('next phase')):
            reply = await self.checkpoint(assignment, command=command)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertNotIn(canary, json.dumps([reply, self.gh.note, self.gh.writes]))
        before = copy.deepcopy(self.gh.note)
        again = await self.checkpoint(assignment, command=command)
        self.assertEqual(again['request']['outcome'], 'unknown')
        self.assertEqual(self.gh.note, before)

    async def test_scope_violation_preserves_checkpoint_without_completion_or_next_work(self):
        assignment = await self.implementation()
        with patch.object(self.ws, 'changed_paths', return_value=['private/secret.txt']):
            reply = await self.checkpoint(assignment)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.gh.note['phase'], 'checkpoint')
        self.assertEqual(self.gh.note['wait_reason'], 'scope_violation')
        self.assertEqual(self.ws.verification_calls, 0)

    async def test_parser_rejects_untrusted_authority_and_malformed_values(self):
        assignment = await self.implementation()
        for change in (lambda c: c['parameters'].update(effect_limit='all'),
                       lambda c: c['target'].update(issue_number=True),
                       lambda c: c['expected']['assignment'].update(step_id='A' * 36),
                       lambda c: c['parameters'].update(summary='\ud800'),
                       lambda c: c['parameters'].update(summary='x' * 24001),
                       lambda c: c.update(effect_key='checkpoint:wrong')):
            command = self.command(assignment)
            change(command)
            with self.assertRaises(InvalidAdmissionCommand):
                await self.checkpoint(assignment, command=command)
        self.assertTrue(self.ws.dirty)

    async def test_unsupported_failed_and_review_phase_do_not_fall_back(self):
        assignment = await self.implementation()
        before = copy.deepcopy(self.gh.note)
        failed = await self.checkpoint(assignment, 'failed')
        self.assertEqual(failed['request']['reason'], 'unsupported_outcome')
        self.gh.note['native_phase'] = 'change_review'
        review = await self.checkpoint(assignment)
        self.assertEqual(review['request']['reason'], 'unsupported_phase')
        self.assertEqual(review['request']['outcome'], 'rejected')
        self.assertEqual(review['request']['required_next'], 'open_source')
        self.assertIsNone(review['request']['receipt'])
        self.assertIn(assignment['step_id'].encode(), self.lock.read_bytes())
        self.assertEqual(self.gh.note['head'], before['head'])
