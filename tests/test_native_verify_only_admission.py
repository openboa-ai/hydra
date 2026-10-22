"""A running registered verifier must not prevent remote admission or cancellation."""
import asyncio
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from hydra_sdlc.mcp import create_server
import test_native_verify_only_contract as fixture


class VerificationAdmissionTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.VerificationContractTests.asyncSetUp
    new_controller = fixture.VerificationContractTests.new_controller
    result = fixture.VerificationContractTests.result
    command = fixture.VerificationContractTests.command
    checkpoint = fixture.VerificationContractTests.checkpoint
    real_git_assignment = fixture.VerificationContractTests.real_git_assignment
    candidate = fixture.VerificationContractTests.candidate
    verification_command = fixture.VerificationContractTests.verification_command
    verification_grant = fixture.VerificationContractTests.verification_grant
    call = fixture.VerificationContractTests.call

    async def slow_candidate(self):
        original = self.real_git_assignment
        async def configure():
            argv = self.gh.cfg['verification'][0]['argv']
            argv[2] = argv[2].replace('sys.exit(int(sys.argv[2]))',
                'import os,time; Path(str(p)+".pid").write_text(str(os.getpid())); '
                'time.sleep(3); Path(str(p)+".finished").write_text("done"); sys.exit(int(sys.argv[2]))')
            return await original()
        with patch.object(self, 'real_git_assignment', side_effect=configure):
            return await self.candidate(0)

    async def started(self, task):
        for _ in range(400):
            if self.counter.exists() or task.done():
                break
            await asyncio.sleep(.05)
        self.assertTrue(self.counter.exists(), 'Actual registered child must have started')
        return not Path(str(self.counter) + '.finished').exists()

    async def test_actual_sdk_can_pause_while_registered_verification_is_running(self):
        from mcp import Client
        candidate = await self.slow_candidate()
        grant = self.verification_grant('admission_set', 'workflow_step.verify_only.run',
            'workflow_step.verify_only.review_checkpoint', 'command_reply.native_handoff_v1')
        server = create_server(self.controller, command_config_path=self.settings,
            command_context_provider=lambda ctx: grant)
        async with Client(server) as client:
            task = asyncio.create_task(client.call_tool('hydra_command_v1',
                {'command': self.verification_command(candidate)}))
            try:
                responsive = await self.started(task)
                if responsive:
                    pause = self.verification_command(candidate)
                    pause.update(action='admission_set', target={'kind': 'repository',
                        'repository_id': self.gh.cfg['repository_id']}, parameters={'mode': 'paused'})
                    response = await client.call_tool('hydra_command_v1', {'command': pause})
                    self.assertFalse(response.is_error, response.content)
                    reply = json.loads(response.content[0].text)
                    self.assertEqual(reply['request']['outcome'], 'applied', reply)
                    response = await task
                    self.assertFalse(response.is_error, response.content)
                    reply = json.loads(response.content[0].text)
                    self.assertIsNone(reply['request']['receipt'])
                    self.assertIn(reply['request']['outcome'], ('waiting', 'unknown'))
                    self.assertFalse(Path(str(self.counter) + '.finished').exists())
            finally:
                if not task.done(): task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(responsive,
            'Command processing must remain responsive while the verifier is running')
        self.assertEqual(self.control.snapshot()['projects']['example/product'], 'paused')
        self.assertEqual(self.lock.read_bytes(), b'')
        self.assertNotIn('native_step', self.gh.note)

    async def test_cancelled_call_waits_for_owned_child_cleanup_before_releasing_coordinator(self):
        candidate = await self.slow_candidate()
        task = asyncio.create_task(self.call(self.verification_command(candidate)))
        try:
            self.assertTrue(await self.started(task),
                'Command processing must remain responsive while the verifier is running')
            pid = int(Path(str(self.counter) + '.pid').read_text())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
            with self.assertRaises(ProcessLookupError): os.kill(pid, 0)
            self.assertFalse(Path(str(self.counter) + '.finished').exists())
            self.assertEqual(self.lock.read_bytes(), b'')
            self.assertNotIn('native_step', self.gh.note)
        finally:
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)
