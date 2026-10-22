"""A verifier edit invalidates acceptance while preserving its owned bytes."""
import unittest
from unittest.mock import patch

import test_native_verify_only_preservation as fixture
from test_workspace import git


class VerificationOwnedSpecEditTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.VerificationPreservationTests.asyncSetUp
    new_controller = fixture.VerificationPreservationTests.new_controller
    result = fixture.VerificationPreservationTests.result
    command = fixture.VerificationPreservationTests.command
    checkpoint = fixture.VerificationPreservationTests.checkpoint
    real_git_assignment = fixture.VerificationPreservationTests.real_git_assignment
    candidate = fixture.VerificationPreservationTests.candidate
    verification_command = fixture.VerificationPreservationTests.verification_command
    verification_grant = fixture.VerificationPreservationTests.verification_grant
    call = fixture.VerificationPreservationTests.call

    async def test_owned_spec_edits_are_checkpointed_without_accepting_the_changed_spec(self):
        original = self.real_git_assignment
        async def configure():
            argv = self.gh.cfg['verification'][0]['argv']
            mutation = 'doc=Path("docs/engineering/task/spec.md"); doc.write_text(doc.read_text()+chr(10)+"Owned verifier edit."+chr(10)); '
            argv[2] = argv[2].replace('print(', mutation+'print(')
            return await original()
        with patch.object(self, 'real_git_assignment', side_effect=configure):
            candidate = await self.candidate(0)
        verify = self.ws.verify
        def completed(*args, **kwargs):
            results = verify(*args, **kwargs)
            self.control.set_mode('pause', 'example/product')
            return results
        with patch.object(self.ws, 'verify', side_effect=completed):
            reply = await self.call(self.verification_command(candidate))
        self.assertEqual(reply['request']['reason'], 'candidate_changed',
                         'Changed acceptance evidence must not block owned-edit preservation')
        self.assertIsNone(reply['request']['receipt'])
        self.assertNotIn('native_step', self.gh.note)
        head = git(self.path, 'rev-parse', 'HEAD')
        self.assertNotEqual(head, candidate['head'])
        self.assertEqual(self.gh.note['head'], head)
        self.assertFalse(self.ws.inspect(self.path)['dirty'])
        self.assertEqual(git(self.path, 'rev-list', '--count', candidate['head']+'..HEAD'), '1')
        self.assertIn('Owned verifier edit.', (self.path/'docs/engineering/task/spec.md').read_text())
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.control.snapshot()['projects']['example/product'], 'paused')
