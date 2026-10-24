"""P06 common-entry behavior using real progress/public codecs and GitHub adapter."""
import copy
import json
from contextlib import contextmanager
from dataclasses import replace
import unittest
from unittest.mock import patch

from hydra_sdlc.decision_coordinator import DecisionCoordinator
from hydra_sdlc.github import GitHubError
from hydra_sdlc.work_decisions import WorkDecisionObservation
from hydra_sdlc.public_decisions import receipt_body
import test_decision_apply_command as command_fixture
import test_decision_coordinator as effect_fixture
import test_public_decisions as wire


class WorkflowTransport(effect_fixture.DecisionTransport):
    def __call__(self, method, path, payload):
        if (method == 'POST' and path.endswith('/issues/4/comments')
                and '<!-- hydra-progress:v1 ' in payload['body']):
            self.effects.append(('progress', copy.deepcopy(payload)))
            self.post_behavior('progress', payload['body'])
            return self.add(max([99, *self.direct]) + 1, payload['body'])
        if (method == 'PATCH' and '/issues/comments/' in path
                and not path.endswith('/1')):
            identifier = int(path.rsplit('/', 1)[1])
            row = self.direct[identifier]
            if '<!-- hydra-progress:v1 ' not in row['body']:
                raise AssertionError('Only the actual progress original may be patched')
            self.effects.append(('progress', copy.deepcopy(payload)))
            self.patch_behavior(payload['body'])
            row = {**row, 'body': payload['body']}
            self.direct[identifier] = copy.deepcopy(row)
            self.rows = [copy.deepcopy(row) if item['id'] == identifier else item for item in self.rows]
            return copy.deepcopy(row)
        if method == 'GET' and '/git/ref/heads/' in path:
            raise GitHubError('fixture branch absent', status=404)
        if method == 'GET' and '/pulls?' in path:
            return []
        return super().__call__(method, path, payload)


class WorkSource(command_fixture.ProposalSource):
    def read_work(self, repository, number, record, *, timeout):
        if repository != wire.REPO or number != 4:
            raise RuntimeError('fixture work changed')
        snapshot = self.read_proposal(self.chosen.proposal.reference(), timeout=timeout)
        resumes = 0
        for kind, payload in self.transport.effects:
            if kind == 'resume':
                progress = json.loads(payload['body'].split('<!-- hydra-progress:v1 ', 1)[1].split(' -->', 1)[0])
                resumes += (progress.get('attempt_id') == wire.RESUME and not progress.get('native_step')
                    and progress.get('next_action') == 'decision_context_' + wire.ATTEMPT)
        return WorkDecisionObservation('selected', replace(snapshot, calls=replace(snapshot.calls,
            resume_writes=resumes, resume_state='unconfirmed' if resumes else 'not_dispatched')), True)


class NativeDecisionResumeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        with patch.object(effect_fixture, 'DecisionTransport', WorkflowTransport):
            await command_fixture.DecisionApplyCommandTests.asyncSetUp(self)
        self.transport.issue['labels'].append({'name': 'hydra:active'})
        self.workspace.existing = lambda *args: self.workspace.path
        self.source = WorkSource(self.chosen, self.transport)
        self.controller.decision_source = self.source
        self.url = 'https://github.com/example/product/issues/4'
        self.transport.add(100, self.chosen.context.body)
        self.transport.add(101, receipt_body(self.chosen.context))

    async def stop_if_assigned(self, result):
        if result.get('action') == 'native_task':
            await self.controller.checkpoint(self.url, result['attempt_id'], result['step_id'],
                result['head'], result['contract_revision'], 'stopped')

    async def test_begin_consumes_the_pinned_resume_and_returns_real_next_assignment(self):
        received = await self.controller.begin(self.url)
        self.addAsyncCleanup(self.stop_if_assigned, received)
        self.assertEqual(received['action'], 'native_task', received)
        self.assertEqual(received['attempt_id'], wire.RESUME)
        self.assertIn('Use the existing contract.', received['prompt'])
        self.assertNotIn('fixture-answer', received['prompt'])
        self.assertEqual(self.github.decision_context_attempt(wire.REPO, 4, wire.RESUME), wire.ATTEMPT)
        self.assertEqual([row[0] for row in self.transport.effects].count('resume'), 2,
            'One pinned resume PATCH and one assignment-intent PATCH; no repeated resume.')

    async def test_native_claim_cannot_fall_back_to_a_manual_legacy_resolution(self):
        self.controller.decision_source = None
        self.transport.add(102, f'hydra: decision {wire.ATTEMPT} context\nManual legacy text.')
        self.transport.rows[-1]['user'] = {'login': 'operator', 'id': 42}
        self.transport.direct[102] = copy.deepcopy(self.transport.rows[-1])
        self.transport.add(103, f'hydra: decision {wire.ATTEMPT} resolved')
        self.transport.rows[-1]['user'] = {'login': 'operator', 'id': 42}
        self.transport.direct[103] = copy.deepcopy(self.transport.rows[-1])
        original = self.github.progress(wire.REPO, 4)
        received = await self.controller.begin(self.url)
        self.addAsyncCleanup(self.stop_if_assigned, received)
        self.assertEqual(received['action'], 'waiting', received)
        self.assertEqual(self.github.progress(wire.REPO, 4), original)
        self.assertEqual(self.transport.effects, [])

    async def test_consumed_native_source_link_survives_clearing_the_resume_phase(self):
        @contextmanager
        def allowed(kind):
            yield
        coordinator = DecisionCoordinator(self.github, wire.REPO, 4,
            read_source=lambda **kw: self.source.read_proposal(self.chosen.proposal.reference(), **kw),
            effect_guard=allowed, expected_key=self.chosen.context.key,
            expected_proposal=self.chosen.proposal.source_check())
        self.assertEqual(coordinator.resume().outcome, 'applied')
        runner = self.controller.runner
        runner._bind_policy(wire.REPO, {**self.config, '_work_number': 4})
        record = self.github.progress(wire.REPO, 4)
        runner._record(wire.REPO, 4, record, resume_phase=None, phase='implementation_done',
                       next_action='verification')
        self.assertEqual(self.github.decision_context_attempt(wire.REPO, 4, wire.RESUME), wire.ATTEMPT)

    async def test_source_change_after_pinned_resume_blocks_assignment_and_preserves_it(self):
        def change(body):
            self.source.chosen = replace(self.chosen, evidence=tuple(
                replace(item, revision=('opaque', 'changed-adoption')) if item.role == 'adoption' else item
                for item in self.chosen.evidence))
        self.transport.patch_behavior = change
        received = await self.controller.begin(self.url)
        self.addAsyncCleanup(self.stop_if_assigned, received)
        self.assertEqual(received['action'], 'waiting', received)
        self.assertEqual(self.github.progress(wire.REPO, 4)['attempt_id'], wire.RESUME)
        self.assertEqual([row[0] for row in self.transport.effects], ['resume'])
