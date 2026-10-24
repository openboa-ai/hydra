"""P06 dispatcher integration with fixed source facts and fixture GitHub IO."""
import asyncio
import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from hydra_sdlc.control import control_from_config, load_host_config
from hydra_sdlc.control_commands import AdmissionCallContext, _runtime_key, execute_command_v1
from hydra_sdlc.decision_coordinator import DecisionSnapshot
from hydra_sdlc.decision_protocol import DecisionCallCoverage
from hydra_sdlc.github import GitHub, GitHubError
from hydra_sdlc.native import NativeController
from hydra_sdlc.public_decisions import prepare_context
from hydra_sdlc.runtime_identity import capture_runtime_identity
from hydra_sdlc.runner import intake_digest
import test_decision_coordinator as effect_fixture
import test_decision_protocol as domain
import test_decision_commands as commands
import test_project as project_fixture
import test_runner as work_fixture
import test_public_decisions as wire


class ProposalSource:
    """Fixed interpretation fixture; this is not a qualified installed adapter."""
    def __init__(self, chosen, transport):
        self.chosen, self.transport, self.reads = chosen, transport, []
        self.on_read = lambda: None

    def read_proposal(self, reference, *, timeout):
        self.reads.append(copy.deepcopy(reference))
        self.on_read()
        if reference != self.chosen.proposal.reference() or timeout <= 0:
            raise RuntimeError('fixture source unavailable')
        counts = {kind: sum(row[0] == kind for row in self.transport.effects)
                  for kind in ('context', 'receipt', 'resume')}
        return DecisionSnapshot(self.chosen, DecisionCallCoverage(True,
            counts['context'], counts['receipt'], counts['resume'], self.transport.resume_state))


class DecisionApplyCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.settings = self.root / 'host.toml'
        self.settings.write_text('repos=["example/product"]\nhost_alias="fixture"\n'
            'workspace_root="work"\nlock_path="locks/host.lock"\n')
        self.settings.chmod(0o600)
        host = load_host_config(self.settings)
        self.control = control_from_config(host)
        self.control.set_mode('start')
        self.transport = effect_fixture.DecisionTransport()
        self.transport.issue = copy.deepcopy(work_fixture.GitHub().work)
        self.github = GitHub(transport=self.transport)
        self.config = project_fixture.config()
        self.config['revision'] = wire.BASIS['contract_revision']
        for name in ('hydra_sdlc.runner.load_project', 'hydra_sdlc.native.load_project',
                     'hydra_sdlc.native_decisions.load_project'):
            active = patch(name, side_effect=lambda *a, **k: copy.deepcopy(self.config))
            active.start()
            self.addCleanup(active.stop)
        self.workspace = work_fixture.Workspace(host['workspace_root'], self.github)
        self.workspace.root = Path(host['workspace_root'])
        self.controller = NativeController(self.github, self.workspace,
            repos=host['repos'], host_alias=host['host_alias'], lock_path=host['lock_path'], operations=self.control)
        basis = copy.deepcopy(wire.BASIS)
        basis['intake_digest'] = intake_digest(self.transport.issue)
        progress = {**domain.record(), 'execution_mode': 'native', 'intake_digest': basis['intake_digest']}
        self.transport.rows[0]['body'] = '<!-- hydra-progress:v1 ' + json.dumps(progress, sort_keys=True) + ' -->'
        self.transport.direct[1] = copy.deepcopy(self.transport.rows[0])
        self.chosen = replace(domain.selection(), context=prepare_context('Use the existing contract.', basis))
        self.source = ProposalSource(self.chosen, self.transport)
        self.controller.decision_source = self.source
        self.grant = AdmissionCallContext('native', None, frozenset({123}),
            frozenset({'workflow_step.decision_apply'}))

    def command(self):
        command = commands.decision_command()
        command['expected']['runtime_key'] = _runtime_key(capture_runtime_identity(load_host_config(self.settings), self.control))
        command['expected']['admission_revision'] = self.control.snapshot()['revision']
        return command

    async def invoke(self, command=None, context_provider=None):
        return await execute_command_v1(self.settings, self.command() if command is None else command,
            context_provider=context_provider or (lambda: self.grant), github=self.github, controller=self.controller)

    async def test_dispatcher_records_public_decision_without_resume_or_assignment(self):
        before = self.github.progress(wire.REPO, 4)
        reply = await self.invoke()
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(reply['request']['receipt']['kind'], 'decision')
        self.assertEqual(reply['request']['receipt']['resume_attempt'], wire.RESUME)
        self.assertEqual([row[0] for row in self.transport.effects], ['context', 'receipt'])
        self.assertEqual(self.github.progress(wire.REPO, 4), before)
        self.assertNotIn('handoff', reply)
        self.assertNotIn('native_context', reply)
        self.assertNotIn('fixture-task', json.dumps(reply))
        self.assertEqual(self.controller.lock_path.read_bytes(), b'')

    async def test_missing_qualified_reader_stays_unsupported_without_legacy_fallback(self):
        self.controller.decision_source = None
        reply = await self.invoke()
        self.assertEqual(reply['request']['reason'], 'unsupported_operation', reply)
        self.assertEqual(self.transport.effects, [])
        self.assertEqual(self.source.reads, [])

    async def test_stale_proposal_revision_has_no_public_effect(self):
        command = self.command()
        command['expected']['source_checks'][0]['revision']['value'] = 'obsolete'
        reply = await self.invoke(command)
        self.assertEqual(reply['request']['outcome'], 'rejected', reply)
        self.assertEqual(reply['request']['reason'], 'stale_decision', reply)
        self.assertEqual(self.transport.effects, [])

    async def test_paused_project_does_not_publish_the_first_context(self):
        self.control.set_mode('pause', wire.REPO)
        reply = await self.invoke()
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.transport.effects, [])

    async def test_pause_after_context_retains_its_original_ref_and_blocks_receipt(self):
        def pause():
            if self.transport.effects and self.control.snapshot()['projects'].get(wire.REPO) != 'paused':
                self.control.set_mode('pause', wire.REPO)
        self.source.on_read = pause
        reply = await self.invoke()
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual([row[0] for row in self.transport.effects], ['context'])
        self.assertEqual(reply['request']['effect_refs'],
                         [{'source': 'github', 'kind': 'issue_comment', 'id': wire.REPO + '/comments/100'}])
        self.assertEqual(self.github.progress(wire.REPO, 4)['attempt_id'], wire.ATTEMPT)

    async def test_existing_confirmed_pair_is_reconciled_read_only_while_paused(self):
        first = await self.invoke()
        self.assertEqual(first['request']['outcome'], 'applied', first)
        self.control.set_mode('pause', wire.REPO)
        reply = await self.invoke()
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(reply['request']['receipt'], first['request']['receipt'])
        self.assertEqual([row[0] for row in self.transport.effects], ['context', 'receipt'])

    async def test_grant_revoked_during_source_read_cannot_publish(self):
        self.source.on_read = lambda: setattr(self, 'grant', replace(self.grant, operations=frozenset()))
        reply = await self.invoke()
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.transport.effects, [])

    async def test_grant_revoked_after_context_preserves_the_observed_partial_effect(self):
        def revoke():
            if self.transport.effects:
                self.grant = replace(self.grant, operations=frozenset())
        self.source.on_read = revoke
        reply = await self.invoke()
        self.assertEqual(reply['request']['outcome'], 'waiting', reply)
        self.assertEqual(reply['request']['reason'], 'authority_denied', reply)
        self.assertEqual([row[0] for row in self.transport.effects], ['context'])
        self.assertEqual(len(reply['request']['effect_refs']), 1)
        self.assertIsNone(reply['request']['receipt'])

    async def test_source_adapter_replacement_during_read_cannot_publish(self):
        replacement = ProposalSource(self.chosen, self.transport)
        self.source.on_read = lambda: setattr(self.controller, 'decision_source', replacement)
        reply = await self.invoke()
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.transport.effects, [])

    async def test_private_provider_exception_is_not_returned_to_caller(self):
        def fail():
            raise RuntimeError('private-answer-canary-do-not-publish')
        self.source.on_read = fail
        reply = await self.invoke()
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertNotIn('private-answer-canary', json.dumps(reply))
        self.assertEqual(self.transport.effects, [])

    async def test_intake_changed_before_dispatch_cannot_publish(self):
        self.transport.issue['body'] += '\nA new product requirement.'
        reply = await self.invoke()
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.transport.effects, [])

    async def test_lost_context_ack_uses_original_readback_without_another_post(self):
        def lost(kind, body):
            if kind == 'context':
                self.transport.add(100, body)
                raise GitHubError('fixture response lost', uncertain=True)
        self.transport.post_behavior = lost
        reply = await self.invoke()
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual([row[0] for row in self.transport.effects], ['context', 'receipt'])

    async def test_changed_adoption_during_policy_refresh_prevents_the_first_post(self):
        original = self.controller.runner._latest
        def change(*args, **kwargs):
            self.source.chosen = replace(self.chosen, evidence=tuple(
                replace(item, revision=('opaque', 'changed-adoption')) if item.role == 'adoption' else item
                for item in self.chosen.evidence))
            return original(*args, **kwargs)
        with patch.object(self.controller.runner, '_latest', side_effect=change):
            reply = await self.invoke()
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.transport.effects, [], 'Changed original selection must be read after policy IO.')

    async def test_cancellation_drains_the_single_worker_and_keeps_context_readback(self):
        dispatched, release = Event(), Event()
        def block(kind, body):
            if kind == 'context':
                dispatched.set()
                if not release.wait(5):
                    raise RuntimeError('fixture release deadline')
        self.transport.post_behavior = block
        task = asyncio.create_task(self.invoke())
        try:
            self.assertTrue(await asyncio.to_thread(dispatched.wait, 5))
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done(), 'An in-flight effect worker must be drained before cancellation returns.')
        finally:
            release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual([row[0] for row in self.transport.effects], ['context'])
        self.assertEqual(len(self.transport.rows), 2)
        self.assertEqual(self.controller.lock_path.read_bytes(), b'')
