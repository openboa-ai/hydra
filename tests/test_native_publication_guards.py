"""P14-R1/R3/R6: unresolved work and inconsistent publication sources hold."""
import asyncio
import copy
import json
from threading import Event
import unittest
from unittest.mock import patch

from hydra_sdlc.control_commands import AdmissionCallContext
import test_native_publication as fixture


class PublicationRecoveryGuards(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.NativePublicationTests.asyncSetUp
    new_controller = fixture.NativePublicationTests.new_controller
    result = fixture.NativePublicationTests.result
    command = fixture.NativePublicationTests.command
    checkpoint = fixture.NativePublicationTests.checkpoint
    real_git_assignment = fixture.NativePublicationTests.real_git_assignment
    candidate = fixture.NativePublicationTests.candidate
    verification_command = fixture.NativePublicationTests.verification_command
    verification_grant = fixture.NativePublicationTests.verification_grant
    call = fixture.NativePublicationTests.call
    finish_command = fixture.NativePublicationTests.finish_command
    reviewed = fixture.NativePublicationTests.reviewed
    publication_command = fixture.NativePublicationTests.publication_command
    publication_grant = fixture.NativePublicationTests.publication_grant
    publish = fixture.NativePublicationTests.publish
    no_publication = fixture.NativePublicationTests.no_publication

    async def test_unfinished_correction_cannot_reuse_an_earlier_review_marker(self):
        candidate = await self.reviewed()
        self.gh.note.update(phase='implementation_done', resume_phase='correction',
            correction_reason='review_findings', correction_attempt=1)
        writes = len(self.gh.writes)
        reply = await self.publish(self.publication_command(candidate))
        self.assertEqual(reply['request']['outcome'], 'waiting', reply)
        self.assertIsNone(reply['request']['receipt'])
        self.no_publication(writes)

    async def proposed_closure(self, index):
        candidate = await self.reviewed()
        runner, effect = self.controller.runner, self.controller.runner._effect
        injected = False
        def proposed(repo, callback, *args, **kwargs):
            nonlocal injected
            if kwargs.get('_checkpoint_effect') == 'pr':
                injected = True
                args = list(args)
                args[index] = 'Closes: example/product#4'
            return effect(repo, callback, *args, **kwargs)
        with patch.object(runner, '_effect', side_effect=proposed):
            reply = await self.publish(self.publication_command(candidate))
        self.assertTrue(injected, 'Inject the proposed public text at its actual writer')
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual([row for row in self.gh.writes if row[0] == 'pr'], [])
        self.assertEqual(len(self.pushes), 1)
        self.assertEqual(self.counter.read_text(), '1')

    async def test_closing_intent_in_proposed_pr_title_never_reaches_the_writer(self):
        await self.proposed_closure(-2)

    async def test_closing_intent_in_proposed_pr_body_never_reaches_the_writer(self):
        await self.proposed_closure(-1)

    async def test_conflicting_legacy_producer_head_is_unknown_without_another_request(self):
        candidate = await self.reviewed()
        def inconsistent(value):
            row = value['provider_comments'][0]
            row['body'] = row['body'].replace('"headSha": "' + candidate['head'] + '"',
                '"headSha": "' + 'e' * 40 + '"')
            return value
        self.gh.transform_observation = inconsistent
        reply = await self.publish(self.publication_command(candidate))
        self.assertEqual(reply['request']['outcome'], 'unknown', reply)
        self.assertNotEqual(reply['request']['receipt']['stage'], 'publication_ready')
        self.assertEqual([row for row in self.gh.writes if row[0] == 'request_review'], [])

    async def test_malformed_producer_is_typed_unknown_and_recovers_without_duplicate_publication(self):
        candidate = await self.reviewed()
        command = self.publication_command(candidate)
        broken = True
        def partial(value):
            if broken:
                value['provider_comments'][0]['user'] = ['unavailable author observation']
            return value
        self.gh.transform_observation = partial
        try:
            first = await self.publish(command)
        except (AttributeError, KeyError, TypeError) as exc:
            self.fail('A malformed provider source must return typed unknown, not ' + type(exc).__name__)
        self.assertEqual(first['request']['outcome'], 'unknown', first)
        broken = False
        recovered = await self.publish(command)
        self.assertEqual(recovered['request']['outcome'], 'applied', recovered)
        self.assertEqual(len(self.pushes), 1)
        self.assertEqual(len([row for row in self.gh.writes if row[0] == 'pr']), 1)
        self.assertEqual(self.counter.read_text(), '1')

    async def test_actual_sdk_pause_remains_responsive_during_a_provider_read(self):
        from mcp import Client
        from hydra_sdlc.mcp import create_server
        candidate = await self.reviewed()
        command = self.publication_command(candidate)
        pause = copy.deepcopy(command)
        pause.update(action='admission_set', target={'kind': 'repository',
            'repository_id': self.gh.cfg['repository_id']}, parameters={'mode': 'paused'})
        entered, release = Event(), Event()
        observe = self.gh.observe
        def waiting(*args):
            entered.set()
            if not release.wait(8):
                raise RuntimeError('The bounded test read was not released')
            return observe(*args)
        grant = AdmissionCallContext('native', None, frozenset({self.gh.cfg['repository_id']}),
            frozenset({'workflow_step.publish_candidate', 'admission_set'}))
        server = create_server(self.controller, command_config_path=self.settings,
            command_context_provider=lambda ctx: grant)
        with patch.object(self.gh, 'observe', side_effect=waiting):
            async with Client(server) as client:
                running = asyncio.create_task(client.call_tool('hydra_command_v1', {'command': command}))
                try:
                    self.assertTrue(await asyncio.wait_for(asyncio.to_thread(entered.wait, 6), 7))
                    response = await asyncio.wait_for(client.call_tool('hydra_command_v1', {'command': pause}), 3)
                    self.assertFalse(response.is_error, response.content)
                    self.assertEqual(json.loads(response.content[0].text)['request']['outcome'], 'applied')
                finally:
                    release.set()
                response = await asyncio.wait_for(running, 10)
                self.assertFalse(response.is_error, response.content)
                reply = json.loads(response.content[0].text)
        self.assertIn(reply['request']['outcome'], {'waiting', 'unknown'}, reply)
        self.assertEqual(self.control.snapshot()['projects']['example/product'], 'paused')
        self.assertEqual(len(self.pushes), 1)
        self.assertEqual(self.counter.read_text(), '1')
