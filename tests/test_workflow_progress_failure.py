"""A failed public read-back cannot retain private text after step retirement."""
import unittest
from unittest.mock import patch
import test_workflow_progress_receipts as fixture
from hydra_sdlc.control_commands import AdmissionCallContext


class FailedProofFixture(fixture.CaptureCheckpoint):
    async def capture(self):
        self.grant=AdmissionCallContext('bridge',fixture.EPOCH,self.grant.repository_ids,self.grant.operations)
        assignment=await self.result(await self.controller.begin(self.url))
        self.ws.dirty=True
        self.controller.runner.summaries[assignment['step_id']]='SYNTHETIC_PRIVATE_RETIRED_SUMMARY'
        with patch('hydra_sdlc.projection.progress_source_value',side_effect=ValueError('invalid_source')):
            self.reply=await self.checkpoint(assignment)
        self.summary_retained=assignment['step_id'] in self.controller.runner.summaries
        self.remaining_ticket=self.lock.read_bytes()


class WorkflowProgressFailureTests(unittest.TestCase):
    def test_failed_public_proof_keeps_unknown_but_retires_the_private_summary(self):
        case=FailedProofFixture('capture')
        result=unittest.TestResult()
        case.run(result)
        self.assertEqual(result.errors+result.failures,[])
        self.assertEqual(case.reply['request']['outcome'],'unknown')
        self.assertIsNone(case.reply['request']['receipt'])
        self.assertEqual(case.remaining_ticket,b'')
        self.assertFalse(case.summary_retained)
