"""P14 r4 / CP: exact protected delivery, recovery and forbidden-effect oracles."""
import copy
from contextlib import ExitStack
import unittest
from unittest.mock import patch

from hydra_sdlc.control_commands import (
    AdmissionCallContext, InvalidAdmissionCommand, execute_command_v1)
import test_native_publication as publication_fixture
from test_project import MERGE


class NativeDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await publication_fixture.NativePublicationTests.asyncSetUp(self)
        self._delivery_main = None
        self._delivery_parent = None
        original_ref, original_observe, original_merge = self.gh.ref, self.gh.observe, self.gh.merge

        def ref(repo, branch):
            if branch == self.gh.cfg['default_branch']:
                return self._delivery_main or self.gh.cfg['revision']
            return original_ref(repo, branch)

        def merge(repo, pr, head, **kwargs):
            self._delivery_parent = ref(repo, self.gh.cfg['default_branch'])
            try:
                return original_merge(repo, pr, head, **kwargs)
            finally:
                if self.gh.pr.get('merged'):
                    self._delivery_main = self.gh.pr['merge_commit_sha']

        def observe(repo, pr):
            value = original_observe(repo, pr)
            value['base_sha'] = self.gh.ref(repo, self.gh.cfg['default_branch'])
            for run in value['runs']:
                for association in run.get('pull_requests', []):
                    association['base']['sha'] = self.base
            from test_workspace import git
            paths = git(self.path, 'diff', '--name-only', self.base, 'HEAD').splitlines()
            value['changed_files'] = [{'filename': name, 'status': 'modified'} for name in paths]
            value['pr']['changed_files'] = len(paths)
            if value['pr'].get('merged'):
                value['merge_commit']['parents'] = [{'sha': self._delivery_parent}]
            return value

        self.gh.ref, self.gh.observe, self.gh.merge = ref, observe, merge

        def project(github, repo, *, revision=None):
            value = copy.deepcopy(github.cfg)
            value['revision'] = revision if revision is not None else github.ref(repo, value['default_branch'])
            return value

        for name in ('hydra_sdlc.runner.load_project', 'hydra_sdlc.native.load_project'):
            self.enterContext(patch(name, side_effect=project))
    new_controller = publication_fixture.NativePublicationTests.new_controller
    result = publication_fixture.NativePublicationTests.result
    command = publication_fixture.NativePublicationTests.command
    checkpoint = publication_fixture.NativePublicationTests.checkpoint
    real_git_assignment = publication_fixture.NativePublicationTests.real_git_assignment
    candidate = publication_fixture.NativePublicationTests.candidate
    verification_command = publication_fixture.NativePublicationTests.verification_command
    verification_grant = publication_fixture.NativePublicationTests.verification_grant
    call = publication_fixture.NativePublicationTests.call
    finish_command = publication_fixture.NativePublicationTests.finish_command
    reviewed = publication_fixture.NativePublicationTests.reviewed
    publication_command = publication_fixture.NativePublicationTests.publication_command
    publication_grant = publication_fixture.NativePublicationTests.publication_grant
    publish = publication_fixture.NativePublicationTests.publish

    async def published(self):
        candidate = await self.reviewed()
        reply = await self.publish(self.publication_command(candidate))
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(reply['request']['receipt']['stage'], 'publication_ready')
        self.assertEqual(self.counter.read_text(), '1')
        return candidate

    def delivery_command(self, candidate):
        command = self.verification_command(candidate)
        command['parameters'] = {
            'operation': 'deliver', 'candidate': dict(candidate),
            'pr_number': self.gh.pr['number'],
            'integration_base': self.gh.pr['base']['sha']}
        return command

    def delivery_grant(self):
        return AdmissionCallContext('native', None,
            frozenset({self.gh.cfg['repository_id']}),
            frozenset({'workflow_step.deliver'}))

    async def deliver(self, command):
        with ExitStack() as stack:
            for target, name in [
                (self.controller, 'advance'), (self.controller.runner, 'step'),
                (self.controller.runner, '_correct'), (self.ws, 'verify'),
                (self.ws, 'checkpoint'), (self.ws, 'publish'),
                (self.gh, 'ensure_pr'), (self.gh, 'request_review')]:
                stack.enter_context(patch.object(target, name,
                    side_effect=AssertionError('Forbidden delivery effect: ' + name)))
            try:
                return await execute_command_v1(self.settings, command,
                    context_provider=self.delivery_grant,
                    github=self.gh, controller=self.controller)
            except InvalidAdmissionCommand as exc:
                self.fail('The accepted narrow deliver profile is unavailable: ' + str(exc))

    def effects(self, start):
        return [row for row in self.gh.writes[start:] if row[0] != 'record']

    def unchanged_candidate(self, candidate):
        from test_workspace import git
        self.assertEqual(git(self.path, 'rev-parse', 'HEAD'), candidate['head'])
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(len(self.pushes), 1)
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_published_candidate_control_stops_before_merge(self):
        candidate = await self.published()
        self.assertFalse(self.gh.pr['merged'])
        self.assertEqual(self.gh.work['state'], 'open')
        self.assertNotIn('merge', [row[0] for row in self.gh.writes])
        self.unchanged_candidate(candidate)

    async def test_exact_delivery_closes_only_after_verified_squash_and_replays_without_writes(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        writes = len(self.gh.writes)
        reply = await self.deliver(command)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        receipt = reply['request']['receipt']
        self.assertEqual(receipt['kind'], 'delivery')
        self.assertEqual(receipt['candidate'], candidate)
        self.assertEqual(receipt['integration_base'], command['parameters']['integration_base'])
        self.assertEqual(receipt['merge_commit'], MERGE)
        self.assertEqual(receipt['post_merge'], 'success')
        self.assertIs(receipt['issue_closed'], True)
        self.assertEqual(self.effects(writes), [('merge', candidate['head']), ('close', 4)])
        self.assertEqual(self.gh.work['state'], 'closed')
        replay_start = len(self.gh.writes)
        replay = await self.deliver(command)
        self.assertEqual(replay['request']['receipt'], receipt)
        self.assertEqual(self.effects(replay_start), [])
        self.unchanged_candidate(candidate)

    async def test_changed_base_is_rejected_without_repinned_merge(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        self.gh.pr['base']['sha'] = 'e' * 40
        before = copy.deepcopy(self.gh.note)
        writes = len(self.gh.writes)
        reply = await self.deliver(command)
        self.assertEqual(reply['request']['outcome'], 'rejected', reply)
        self.assertEqual(reply['request']['reason'], 'stale_delivery', reply)
        self.assertIsNone(reply['request']['receipt'])
        self.assertFalse(self.gh.pr['merged'])
        self.assertEqual(self.effects(writes), [])
        self.assertEqual(self.gh.note.get('expected_base'), before.get('expected_base'))
        self.unchanged_candidate(candidate)

    async def test_current_ci_pending_holds_without_new_review_or_merge(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        transform = self.gh.transform_observation
        def pending(value):
            value = transform(value)
            value['runs'][0]['status'] = 'in_progress'
            value['runs'][0]['conclusion'] = None
            return value
        self.gh.transform_observation = pending
        writes = len(self.gh.writes)
        reply = await self.deliver(command)
        self.assertIn(reply['request']['outcome'], {'waiting', 'unknown'}, reply)
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual(self.effects(writes), [])
        self.assertFalse(self.gh.pr['merged'])
        self.unchanged_candidate(candidate)

    async def test_current_code_review_pending_holds_without_retransmission_or_merge(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        transform = self.gh.transform_observation
        def pending(value):
            value = transform(value)
            comment = value['provider_comments'][0]
            comment['body'] = comment['body'].replace('✅ **Completed**', '🔄 **Running**', 1)
            return value
        self.gh.transform_observation = pending
        writes = len(self.gh.writes)
        reply = await self.deliver(command)
        self.assertIn(reply['request']['outcome'], {'waiting', 'unknown'}, reply)
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual(self.effects(writes), [])
        self.assertFalse(self.gh.pr['merged'])
        self.unchanged_candidate(candidate)

    async def test_post_merge_pending_is_observed_without_another_merge_until_success(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        observe = self.gh.observe_commit
        pending = True
        revisions = []
        def post(repo, sha):
            revisions.append(sha)
            value = observe(repo, sha)
            if pending:
                run = value['runs'][0]
                run.update(status='in_progress', conclusion=None)
                run['jobs'][0].update(status='in_progress', conclusion=None)
                value['checks'][0].update(status='in_progress', conclusion=None)
            return value
        self.gh.observe_commit = post
        writes = len(self.gh.writes)
        first = await self.deliver(command)
        self.assertEqual(first['request']['outcome'], 'waiting', first)
        self.assertEqual(first['request']['receipt']['post_merge'], 'pending')
        self.assertEqual(first['request']['receipt']['merge_commit'], MERGE)
        self.assertEqual(self.effects(writes), [('merge', candidate['head'])])
        self.assertEqual(self.gh.work['state'], 'open')
        pending = False
        second = await self.deliver(command)
        self.assertEqual(second['request']['outcome'], 'applied', second)
        self.assertEqual(second['request']['receipt']['post_merge'], 'success')
        self.assertEqual(self.effects(writes), [('merge', candidate['head']), ('close', 4)])
        self.assertTrue(revisions)
        self.assertEqual(set(revisions), {MERGE})
        self.unchanged_candidate(candidate)

    async def test_failed_post_merge_is_retained_without_close_or_automatic_repair(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        observe = self.gh.observe_commit
        def failed(repo, sha):
            value = observe(repo, sha)
            value['runs'][0].update(status='completed', conclusion='failure')
            value['runs'][0]['jobs'][0].update(status='completed', conclusion='failure')
            value['checks'][0].update(status='completed', conclusion='failure')
            return value
        self.gh.observe_commit = failed
        writes = len(self.gh.writes)
        reply = await self.deliver(command)
        self.assertEqual(reply['request']['outcome'], 'waiting', reply)
        self.assertEqual(reply['request']['receipt']['post_merge'], 'failed')
        self.assertEqual(reply['request']['receipt']['merge_commit'], MERGE)
        self.assertEqual(self.gh.work['state'], 'open')
        self.assertEqual(self.effects(writes), [('merge', candidate['head'])])
        self.unchanged_candidate(candidate)

    async def test_lost_merge_response_reuses_original_base_after_restart_and_main_advance(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        self.gh.lose_merge = True
        observe = self.gh.observe
        hidden = True
        def read(repo, pr):
            if hidden and self.gh.pr['merged']:
                raise RuntimeError('Synthetic unavailable merge read-back')
            return observe(repo, pr)
        self.gh.observe = read
        writes = len(self.gh.writes)
        first = await self.deliver(command)
        self.assertIn(first['request']['outcome'], {'waiting', 'unknown'}, first)
        self.assertEqual(self.effects(writes), [('merge', candidate['head'])])
        self.assertEqual(self.gh.note['expected_base'], command['parameters']['integration_base'])
        self.assertEqual(self.gh.work['state'], 'open')
        hidden = False
        self.controller = self.new_controller()
        self.controller.runner.operations = self.control
        # The main ref may advance, while the immutable squash's parent remains
        # the original integration base exposed by the real provider fixture.
        original_ref = self.gh.ref
        self.gh.ref = lambda repo, branch: 'e' * 40 if branch == 'main' else original_ref(repo, branch)
        restored = await self.deliver(command)
        self.assertEqual(restored['request']['outcome'], 'applied', restored)
        self.assertEqual(restored['request']['receipt']['merge_commit'], MERGE)
        self.assertEqual(restored['request']['receipt']['integration_base'],
                         command['parameters']['integration_base'])
        self.assertEqual(self.effects(writes), [('merge', candidate['head']), ('close', 4)])
        self.unchanged_candidate(candidate)

    async def test_pause_at_final_observation_prevents_new_merge(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        observe = self.gh.observe
        paused = False
        def read(repo, pr):
            nonlocal paused
            value = observe(repo, pr)
            if not paused:
                paused = True
                self.control.set_mode('pause', 'example/product')
            return value
        self.gh.observe = read
        writes = len(self.gh.writes)
        reply = await self.deliver(command)
        self.assertTrue(paused)
        self.assertIn(reply['request']['outcome'], {'waiting', 'rejected'}, reply)
        self.assertIsNone(reply['request']['receipt'])
        self.assertFalse(self.gh.pr['merged'])
        self.assertEqual(self.effects(writes), [])
        self.unchanged_candidate(candidate)

    async def test_closing_intent_in_existing_pr_cannot_skip_post_merge_responsibility(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        self.gh.pr['title'] = 'Fixes: #4'
        writes = len(self.gh.writes)
        reply = await self.deliver(command)
        self.assertIn(reply['request']['outcome'], {'waiting', 'rejected'}, reply)
        self.assertIsNone(reply['request']['receipt'])
        self.assertFalse(self.gh.pr['merged'])
        self.assertEqual(self.gh.work['state'], 'open')
        self.assertEqual(self.effects(writes), [])
        self.unchanged_candidate(candidate)

    async def test_fixture_sources_provide_a_valid_direct_delivery_candidate(self):
        candidate = await self.published()
        from hydra_sdlc.project import gate_delivery
        from hydra_sdlc.runner import Runner
        value = self.gh.observe('example/product', self.gh.pr['number'])
        cfg = self.controller.runner._work_config('example/product', 4, self.gh.note)
        self.assertEqual(value['base_sha'], self.base)
        self.assertEqual(value['pr']['base']['sha'], self.base)
        self.assertEqual(gate_delivery(cfg, value, candidate['head'], Runner._paths(value)), [])
        self.assertFalse(value['pr']['merged'])
        self.unchanged_candidate(candidate)

    async def test_unknown_post_merge_reconciles_without_new_merge_after_source_recovers(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        original = self.gh.observe_commit
        revisions = []
        def unavailable(repo, sha):
            revisions.append(sha)
            raise RuntimeError('Synthetic unavailable actual-merge checks')
        self.gh.observe_commit = unavailable
        start = len(self.gh.writes)
        first = await self.deliver(command)
        self.assertEqual(first['request']['outcome'], 'waiting', first)
        self.assertEqual(first['request']['receipt']['post_merge'], 'unknown')
        self.assertEqual(first['request']['receipt']['merge_commit'], MERGE)
        self.assertEqual(self.gh.work['state'], 'open')
        self.assertEqual(self.effects(start), [('merge', candidate['head'])])
        self.assertEqual(set(revisions), {MERGE})
        self.gh.observe_commit = original
        again = await self.deliver(command)
        self.assertEqual(again['request']['outcome'], 'applied', again)
        self.assertEqual(again['request']['receipt']['post_merge'], 'success')
        self.assertEqual(self.effects(start), [('merge', candidate['head']), ('close', 4)])
        self.unchanged_candidate(candidate)

    async def test_unconfirmed_merge_does_not_retransmit_on_restart_and_reuses_late_result(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        actual = self.gh.merge
        attempts = []
        def uncertain(*args, **kwargs):
            attempts.append((args, kwargs))
            if len(attempts) > 1:
                raise AssertionError('Unknown merge must not be retransmitted')
            raise RuntimeError('Synthetic merge dispatch with unavailable outcome')
        self.gh.merge = uncertain
        first = await self.deliver(command)
        self.assertIn(first['request']['outcome'], {'waiting', 'unknown'}, first)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(self.gh.note['pending_action'], 'merge')
        self.assertEqual(self.gh.note['expected_base'], command['parameters']['integration_base'])
        self.controller = self.new_controller()
        self.controller.runner.operations = self.control
        again = await self.deliver(command)
        self.assertIn(again['request']['outcome'], {'waiting', 'unknown'}, again)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(self.gh.work['state'], 'open')
        args, kwargs = attempts[0]
        actual(*args, **kwargs)
        recovered = await self.deliver(command)
        self.assertEqual(recovered['request']['outcome'], 'applied', recovered)
        self.assertEqual(recovered['request']['receipt']['merge_commit'], MERGE)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(self.gh.work['state'], 'closed')
        self.unchanged_candidate(candidate)

    async def test_pause_after_merge_intent_resumes_the_known_unsent_effect_without_replanning(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        intent = self.controller.runner._intent
        paused = False
        def apply_pause(*args, **kwargs):
            nonlocal paused
            value = intent(*args, **kwargs)
            if len(args) > 4 and args[4] == 'merge' and value is not None and not paused:
                paused = True
                self.control.set_mode('pause', 'example/product')
            return value
        start = len(self.gh.writes)
        with patch.object(self.controller.runner, '_intent', side_effect=apply_pause):
            held = await self.deliver(command)
        self.assertTrue(paused, 'Apply Pause after the real merge intent and before its writer')
        self.assertIn(held['request']['outcome'], {'waiting', 'rejected'}, held)
        self.assertFalse(self.gh.pr['merged'])
        self.assertEqual(self.effects(start), [])
        self.control.set_mode('resume', 'example/product')
        resumed = await self.deliver(self.delivery_command(candidate))
        self.assertEqual(resumed['request']['outcome'], 'applied', resumed)
        self.assertEqual(self.effects(start), [('merge', candidate['head']), ('close', 4)])
        self.unchanged_candidate(candidate)
