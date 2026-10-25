"""Caller cancellation must drain the owned worker and prevent later effects."""
import asyncio
from threading import Event
from unittest.mock import patch
import unittest
from urllib.parse import urlsplit

import test_work_creation as fixture
from hydra_sdlc.work_creation import Registration


class CreationCancellationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.WorkCreationTests.asyncSetUp
    command = fixture.WorkCreationTests.command
    create = fixture.WorkCreationTests.create

    async def blocked_route(self, stage, *, cancellations=1, provider_error=False):
        entered, release, finished = Event(), Event(), Event()
        original = Registration.run
        loop = asyncio.get_running_loop()
        previous_handler, unhandled = loop.get_exception_handler(), []
        loop.set_exception_handler(lambda current, context: unhandled.append(
            str(context.get('exception') or context.get('message'))))

        def tracked(registration):
            try:
                return original(registration)
            finally:
                finished.set()

        def block(method, path, payload):
            route = urlsplit(path).path
            prefix = '/repos/' + fixture.REPO
            match = ((stage == 'preflight' and method == 'GET' and route == prefix + '/issues')
                or (stage == 'fence' and method == 'POST' and route == prefix + '/issues/4/comments')
                or (stage == 'issue' and method == 'POST' and route == prefix + '/issues')
                or (stage == 'binding' and method == 'POST' and route == prefix + '/issues/11/comments'))
            if match:
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('Bounded synthetic provider did not release')
                if provider_error:
                    raise RuntimeError(fixture.CANARY)

        self.wire.before_request = block
        with patch.object(Registration, 'run', tracked):
            task = asyncio.create_task(self.create())
            response, error, outcome = None, None, None
            try:
                reached = await asyncio.to_thread(entered.wait, 3)
                for _ in range(cancellations):
                    task.cancel()
                    await asyncio.sleep(.03)
                done_before_release = task.done()
                release.set()
                try:
                    response = await asyncio.wait_for(asyncio.shield(task), 5)
                    outcome = response['request']['outcome']
                except asyncio.CancelledError as exc:
                    outcome, error = 'cancelled', str(exc)
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(asyncio.shield(task), 5)
                    except asyncio.CancelledError:
                        pass
                drained = await asyncio.to_thread(finished.wait, 5)
                await asyncio.sleep(0)
                loop.set_exception_handler(previous_handler)
        return {'reached': reached, 'done_before_release': done_before_release,
            'drained': drained, 'outcome': outcome, 'error': error, 'response': response,
            'effects': [kind for kind, _ in self.wire.writes], 'unhandled': unhandled}

    async def assert_cancelled(self, stage, expected, **kwargs):
        value = await self.blocked_route(stage, **kwargs)
        self.assertTrue(value['reached'], value)
        self.assertFalse(value['done_before_release'], 'Cancellation returned before the owned worker drained')
        self.assertTrue(value['drained'], value)
        self.assertEqual(value['outcome'], 'cancelled', value)
        self.assertNotIn(fixture.CANARY, value['error'] or '')
        self.assertEqual(value['effects'], expected)
        self.assertEqual(value['unhandled'], [], 'Owned cancellation errors must be consumed, not logged')

    async def test_cancellation_during_preflight_cannot_dispatch_a_fence(self):
        await self.assert_cancelled('preflight', [])

    async def test_cancellation_during_fence_waits_for_it_and_never_dispatches_issue(self):
        await self.assert_cancelled('fence', ['fence'])

    async def test_cancellation_during_issue_preserves_it_without_dispatching_binding(self):
        await self.assert_cancelled('issue', ['fence', 'issue'])
        self.assertIn(11, self.wire.issues)

    async def test_cancellation_during_binding_drains_the_already_sent_result(self):
        await self.assert_cancelled('binding', ['fence', 'issue', 'binding'])
        self.assertIn(11, self.wire.issues)

    async def test_repeated_cancellation_cannot_abandon_the_registration_worker(self):
        await self.assert_cancelled('fence', ['fence'], cancellations=3)

    async def test_provider_error_while_draining_preserves_original_cancellation(self):
        await self.assert_cancelled('fence', [], provider_error=True)

    async def test_same_blocked_valid_route_without_cancellation_still_registers(self):
        value = await self.blocked_route('fence', cancellations=0)
        self.assertTrue(value['reached'], value)
        self.assertFalse(value['done_before_release'])
        self.assertTrue(value['drained'], value)
        self.assertEqual(value['outcome'], 'applied', value)
        self.assertEqual(value['effects'], ['fence', 'issue', 'binding'])
        self.assertEqual(value['response']['request']['receipt']['stage'], 'registered')
