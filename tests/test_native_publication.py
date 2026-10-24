"""P14/CP: one exact reviewed candidate can be published without delivery."""
import copy
import json
import unittest
from unittest.mock import patch

from hydra_sdlc.control_commands import (AdmissionCallContext, InvalidAdmissionCommand,
    execute_command_v1, parse_command_v1)
import test_native_verify_only_contract as verification_fixture
from test_project import observation
from test_workspace import git


class NativePublicationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = verification_fixture.VerificationContractTests.asyncSetUp
    new_controller = verification_fixture.VerificationContractTests.new_controller
    result = verification_fixture.VerificationContractTests.result
    command = verification_fixture.VerificationContractTests.command
    checkpoint = verification_fixture.VerificationContractTests.checkpoint
    real_git_assignment = verification_fixture.VerificationContractTests.real_git_assignment
    candidate = verification_fixture.VerificationContractTests.candidate
    verification_command = verification_fixture.VerificationContractTests.verification_command
    verification_grant = verification_fixture.VerificationContractTests.verification_grant
    call = verification_fixture.VerificationContractTests.call
    finish_command = verification_fixture.VerificationContractTests.finish_command

    async def reviewed(self, *, message=None):
        candidate = await self.candidate(0)
        if message is not None:
            git(self.path, 'commit', '--amend', '-m', message)
            candidate['head'] = git(self.path, 'rev-parse', 'HEAD')
            self.gh.note['head'] = candidate['head']
        command = self.verification_command(candidate)
        command['parameters']['reply_profile'] = 'native_handoff_v1'
        started = await self.call(command)
        assignment = started['handoff']['assignment']
        finished = await self.call(self.finish_command(candidate, assignment))
        self.assertEqual(finished['request']['receipt']['review'], 'accepted', finished)
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.lock.read_bytes(), b'')
        self.pushes = []
        publish = self.ws.publish
        def actual_push(path, branch, expected):
            self.pushes.append((branch, expected))
            result = publish(path, branch, expected)
            self.gh.branch = candidate['head']
            return result
        self.ws.publish = actual_push
        create = self.gh.ensure_pr
        def actual_pr(*args):
            try:
                result = create(*args)
            finally:
                if self.gh.pr is not None:
                    self.gh.pr['title'] = args[-2]
                    self.gh.pr['base']['sha'] = self.gh.cfg['revision']
            result['title'] = self.gh.pr['title']
            result['base']['sha'] = self.gh.pr['base']['sha']
            return result
        self.gh.ensure_pr = actual_pr
        self.gh._identity = lambda: {'id': 11, 'login': 'openboa'}
        return candidate

    def publication_command(self, candidate):
        command = self.verification_command(candidate)
        command['parameters'] = {'operation': 'publish_candidate',
            'candidate': dict(candidate), 'branch': self.gh.note['branch'],
            'expected_remote_head': self.gh.branch}
        return command

    def publication_grant(self):
        return AdmissionCallContext('native', None,
            frozenset({self.gh.cfg['repository_id']}),
            frozenset({'workflow_step.publish_candidate'}))

    async def publish(self, command, *, provider=None):
        with patch.object(self.controller, 'advance', side_effect=AssertionError('broad continuation')), \
             patch.object(self.controller.runner, 'step', side_effect=AssertionError('broad step')), \
             patch.object(self.controller.runner, '_correct', side_effect=AssertionError('correction')), \
             patch.object(self.ws, 'verify', side_effect=AssertionError('new verification')), \
             patch.object(self.ws, 'checkpoint', side_effect=AssertionError('new commit')), \
             patch.object(self.gh, 'merge', side_effect=AssertionError('merge')), \
             patch.object(self.gh, 'close_issue', side_effect=AssertionError('close')):
            return await execute_command_v1(self.settings, command,
                context_provider=provider or self.publication_grant,
                github=self.gh, controller=self.controller)

    def no_publication(self, writes):
        self.assertEqual(self.pushes, [])
        self.assertTrue(all(row[0] == 'record' for row in self.gh.writes[writes:]))
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_exact_reviewed_candidate_publishes_actual_git_and_owned_pr_only(self):
        candidate = await self.reviewed()
        command = self.publication_command(candidate)
        writes = len(self.gh.writes)
        reply = await self.publish(command)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        receipt = reply['request']['receipt']
        self.assertEqual(receipt['kind'], 'publication')
        self.assertEqual(receipt['candidate'], candidate)
        self.assertEqual(receipt['stage'], 'publication_ready')
        self.assertEqual(receipt['observed_remote_head'], candidate['head'])
        self.assertIsNotNone(receipt['pr_ref'])
        self.assertEqual(receipt['review_request_refs'], [])
        self.assertEqual(self.pushes, [('hydra/issue-4', None)])
        self.assertEqual(git(self.path, 'ls-remote', 'origin', 'refs/heads/hydra/issue-4').split()[0], candidate['head'])
        self.assertEqual([row[0] for row in self.gh.writes[writes:] if row[0] != 'record'], ['pr'])
        self.assertEqual(git(self.path, 'rev-parse', 'HEAD'), candidate['head'])
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.lock.read_bytes(), b'')
        self.assertNotIn('SYNTHETIC_PRIVATE', json.dumps(reply))

    async def test_confirmed_result_reuses_original_null_expectation_on_replay_and_restart(self):
        candidate = await self.reviewed()
        command = self.publication_command(candidate)
        first = await self.publish(command)
        self.assertEqual(first['request']['outcome'], 'applied', first)
        writes = len(self.gh.writes)
        again = await self.publish(command)
        self.assertEqual(again['request']['receipt'], first['request']['receipt'])
        self.controller = self.new_controller()
        self.controller.runner.operations = self.control
        restored = await self.publish(command)
        self.assertEqual(restored['request']['outcome'], 'applied', restored)
        self.assertEqual(restored['request']['receipt'], first['request']['receipt'])
        self.assertEqual(len(self.pushes), 1)
        self.assertTrue(all(row[0] == 'record' for row in self.gh.writes[writes:]))
        self.assertEqual(self.counter.read_text(), '1')

    async def test_dirty_candidate_is_held_without_committing_or_repinning(self):
        candidate = await self.reviewed()
        command = self.publication_command(candidate)
        (self.path / 'src/main.py').write_text('unreviewed = True\n')
        writes = len(self.gh.writes)
        reply = await self.publish(command)
        self.assertEqual(reply['request']['outcome'], 'waiting', reply)
        self.assertEqual(reply['request']['reason'], 'candidate_changed', reply)
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual((self.path / 'src/main.py').read_text(), 'unreviewed = True\n')
        self.no_publication(writes)

    async def test_wrong_candidate_branch_and_expected_ref_do_not_publish(self):
        candidate = await self.reviewed()
        original = self.publication_command(candidate)
        cases = []
        for field, value in [('branch', 'hydra/issue-5'), ('expected_remote_head', 'f' * 40)]:
            command = copy.deepcopy(original)
            command['parameters'][field] = value
            cases.append(command)
        for field, value in [('attempt_id', '33333333-3333-4333-8333-333333333333'),
                              ('head', 'e' * 40), ('contract_revision', 'd' * 40)]:
            command = copy.deepcopy(original)
            command['parameters']['candidate'][field] = value
            cases.append(command)
        writes = len(self.gh.writes)
        for command in cases:
            with self.subTest(parameters=command['parameters']):
                reply = await self.publish(command)
                self.assertEqual(reply['request']['outcome'], 'rejected', reply)
                self.assertIn(reply['request']['reason'], ('stale_candidate', 'stale_publication'))
                self.assertIsNone(reply['request']['receipt'])
        self.no_publication(writes)

    async def test_phase_without_actual_candidate_review_cannot_trigger_verification_or_publication(self):
        candidate = await self.reviewed()
        self.controller.runner.verified_heads.clear()
        writes = len(self.gh.writes)
        reply = await self.publish(self.publication_command(candidate))
        self.assertEqual(reply['request']['outcome'], 'waiting', reply)
        self.assertNotEqual(reply['request']['reason'], 'unsupported_operation')
        self.assertIsNone(reply['request']['receipt'])
        self.no_publication(writes)

    async def test_current_grant_is_rechecked_at_the_actual_push_boundary(self):
        candidate = await self.reviewed()
        command = self.publication_command(candidate)
        revoked = False
        def grant():
            nonlocal revoked
            if self.gh.note.get('pending_action') == 'publish':
                revoked = True
                return AdmissionCallContext('native', None,
                    frozenset({self.gh.cfg['repository_id']}), frozenset())
            return self.publication_grant()
        writes = len(self.gh.writes)
        reply = await self.publish(command, provider=grant)
        self.assertTrue(revoked, 'Revoke after the exact publication intent, before push')
        self.assertEqual(reply['request']['reason'], 'authority_denied', reply)
        self.no_publication(writes)
        restored = await self.publish(command)
        self.assertEqual(restored['request']['outcome'], 'applied', restored)
        self.assertEqual(len(self.pushes), 1)

    async def test_pause_after_push_preserves_partial_receipt_and_explicit_resume_finishes_pr(self):
        candidate = await self.reviewed()
        command = self.publication_command(candidate)
        read_ref = self.gh.ref
        paused = False
        def paused_after_push(*args):
            nonlocal paused
            result = read_ref(*args)
            if result == candidate['head'] and not paused:
                snapshot = self.control.set_mode('pause', 'example/product')
                self.assertEqual(snapshot['projects']['example/product'], 'paused')
                paused = True
            return result
        with patch.object(self.gh, 'ref', side_effect=paused_after_push):
            held = await self.publish(command)
        self.assertTrue(paused, 'Pause must actually apply after the push callback releases its effect lock')
        self.assertEqual(held['request']['outcome'], 'waiting', held)
        self.assertEqual(held['request']['receipt']['stage'], 'branch_published')
        self.assertIsNone(self.gh.pr)
        self.assertEqual(len(self.pushes), 1)
        self.control.set_mode('resume', 'example/product')
        resumed = self.publication_command(candidate)
        resumed['parameters']['expected_remote_head'] = None
        reply = await self.publish(resumed)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(len(self.pushes), 1)
        self.assertEqual(len([row for row in self.gh.writes if row[0] == 'pr']), 1)

    async def test_lost_pr_ack_and_temporarily_unavailable_readback_never_duplicate_push_or_pr(self):
        candidate = await self.reviewed()
        command = self.publication_command(candidate)
        self.gh.lose_pr = True
        pulls = self.gh.pulls
        unavailable = True
        def read_pr(*args):
            if self.gh.pr is not None and unavailable:
                raise RuntimeError('synthetic read unavailable after the PR was created')
            return pulls(*args)
        with patch.object(self.gh, 'pulls', side_effect=read_pr):
            unknown = await self.publish(command)
            self.assertEqual(unknown['request']['outcome'], 'unknown', unknown)
            unavailable = False
            recovered = await self.publish(command)
        self.assertEqual(recovered['request']['outcome'], 'applied', recovered)
        self.assertEqual(len(self.pushes), 1)
        self.assertEqual(len([row for row in self.gh.writes if row[0] == 'pr']), 1)
        self.assertEqual(self.counter.read_text(), '1')

    async def test_foreign_existing_pr_is_held_before_publication(self):
        candidate = await self.reviewed()
        self.gh.pr = observation()['pr']
        self.gh.pr['head']['sha'] = candidate['head']
        self.gh.pr['body'] = '<!-- hydra-pr:v1 {"repository_id":123,"issue_number":99} -->'
        writes = len(self.gh.writes)
        reply = await self.publish(self.publication_command(candidate))
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertNotEqual(reply['request']['reason'], 'unsupported_operation')
        self.no_publication(writes)

    async def test_candidate_commit_with_closing_intent_is_not_published(self):
        candidate = await self.reviewed(message='Fixes example/product#4')
        writes = len(self.gh.writes)
        reply = await self.publish(self.publication_command(candidate))
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertNotEqual(reply['request']['reason'], 'unsupported_operation')
        self.no_publication(writes)

    async def test_needed_review_requests_have_actual_readback_refs_without_waiting_for_approval(self):
        candidate = await self.reviewed()
        command = self.publication_command(candidate)
        self.gh.transform_observation = lambda value: {**value,
            'provider_comments': copy.deepcopy(self.gh.extra_comments)}
        request = self.gh.request_review
        def requested(*args, **kwargs):
            request(*args, **kwargs)
            kind = kwargs['kind']
            row = {'id': 901 if kind == 'code' else 902,
                'user': {'id': 11, 'login': 'openboa', 'type': 'User'},
                'body': f'<!-- hydra-review-request:v1 head={candidate["head"]} kind={kind} -->'}
            self.gh.extra_comments.append(row)
            return copy.deepcopy(row)
        with patch.object(self.gh, 'request_review', side_effect=requested):
            first = await self.publish(command)
            self.assertEqual(first['request']['outcome'], 'waiting', first)
            self.assertEqual(first['request']['receipt']['stage'], 'pr_ready')
            second = await self.publish(command)
        self.assertEqual(second['request']['outcome'], 'applied', second)
        receipt = second['request']['receipt']
        self.assertEqual(receipt['stage'], 'publication_ready')
        self.assertEqual({ref['id'] for ref in receipt['review_request_refs']},
            {'example/product/comments/901', 'example/product/comments/902'})
        self.assertEqual({row[1] for row in self.gh.writes if row[0] == 'request_review'},
            {'code', 'security'})
        self.assertEqual(len(self.pushes), 1)
        self.assertEqual(self.counter.read_text(), '1')
        self.assertNotIn('merge', [row[0] for row in self.gh.writes])

    async def test_actual_sdk_uses_the_same_closed_publication_handler(self):
        from mcp import Client
        from hydra_sdlc.mcp import create_server
        candidate = await self.reviewed()
        server = create_server(self.controller, command_config_path=self.settings,
            command_context_provider=lambda ctx: self.publication_grant())
        with patch.object(self.controller, 'advance', side_effect=AssertionError('broad continuation')), \
             patch.object(self.controller.runner, 'step', side_effect=AssertionError('broad step')):
            async with Client(server) as client:
                tools = await client.list_tools()
                self.assertEqual({tool.name for tool in tools.tools}, {'hydra_status', 'hydra_begin',
                    'hydra_checkpoint', 'hydra_verify', 'hydra_deliver', 'hydra_command_v1'})
                response = await client.call_tool('hydra_command_v1',
                    {'command': self.publication_command(candidate)})
                self.assertFalse(response.is_error, response.content)
                reply = json.loads(response.content[0].text)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(reply['request']['receipt']['stage'], 'publication_ready')
        self.assertEqual(len(self.pushes), 1)
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_publication_effect_ceiling_rejects_unrelated_provider_and_workspace_effects(self):
        from hydra_sdlc.operations import OperationDenied
        candidate = await self.reviewed()
        create = self.gh.ensure_pr
        blocked = []
        def guarded(*args):
            runner = self.controller.runner
            for effect in [lambda: runner._workspace_effect('example/product', 'checkpoint',
                               self.path, 'forbidden new commit'),
                           lambda: runner._effect('example/product',
                               lambda: self.fail('unrelated provider callback'))]:
                with self.assertRaises(OperationDenied):
                    effect()
                blocked.append(True)
            return create(*args)
        with patch.object(self.gh, 'ensure_pr', side_effect=guarded):
            reply = await self.publish(self.publication_command(candidate))
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(blocked, [True, True])
        self.assertEqual(git(self.path, 'rev-parse', 'HEAD'), candidate['head'])
        self.assertEqual(self.counter.read_text(), '1')

    async def test_foreign_source_at_the_actual_intent_writer_is_not_overwritten(self):
        candidate = await self.reviewed()
        runner, effect = self.controller.runner, self.controller.runner._effect
        changed = False
        foreign = None
        def raced(repo, callback, *args, **kwargs):
            nonlocal changed, foreign
            if kwargs.get('_checkpoint_effect') == 'progress' and not changed:
                changed = True
                foreign = {**self.gh.note, 'wait_reason': 'product_decision',
                    'next_action': 'operator_decision'}
                self.gh.note = copy.deepcopy(foreign)
            return effect(repo, callback, *args, **kwargs)
        writes = len(self.gh.writes)
        with patch.object(runner, '_effect', side_effect=raced):
            reply = await self.publish(self.publication_command(candidate))
        self.assertTrue(changed, 'Inject the source change at the actual progress-writer boundary')
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.gh.note, foreign)
        self.assertEqual(self.gh.writes[writes:], [])
        self.no_publication(writes)


class PublicationSchemaTests(unittest.TestCase):
    def command(self):
        return {'command_schema': 1, 'request_id': '22222222-2222-4222-8222-222222222222',
            'binding_epoch': None, 'action': 'workflow_step',
            'target': {'repository_id': 123, 'issue_number': 4},
            'expected': {'runtime_key': 'opaque-runtime', 'admission_revision': 1,
                'source_checks': [], 'assignment': None}, 'effect_key': None,
            'parameters': {'operation': 'publish_candidate',
                'candidate': {'attempt_id': '33333333-3333-4333-8333-333333333333',
                    'head': 'b' * 40, 'contract_revision': 'a' * 40},
                'branch': 'hydra/issue-4', 'expected_remote_head': None}}

    def test_publication_profile_is_recognized_and_defensively_copied(self):
        command = self.command()
        result = parse_command_v1(command)
        self.assertEqual(result, command)
        command['parameters']['candidate']['head'] = 'f' * 40
        self.assertEqual(result['parameters']['candidate']['head'], 'b' * 40)

    def test_publication_profile_rejects_extra_effects_and_wrong_types(self):
        for field, value in [('branch', 4), ('expected_remote_head', True),
                             ('candidate', {}), ('command', ['sh', '-c', 'echo forbidden'])]:
            with self.subTest(field=field):
                command = self.command()
                command['parameters'][field] = value
                with self.assertRaises(InvalidAdmissionCommand):
                    parse_command_v1(command)
