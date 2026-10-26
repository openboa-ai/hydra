"""Proposal data must not become another service-owned workflow record."""
import unittest

from hydra_sdlc.public_decisions import InvalidPublicDecision
from hydra_sdlc.public_delegated_decisions import (
    parse_delegated_context, prepare_delegated_context,
)
from delegated_decision_fixture import KEY, InstallationFixture, public_pair


MARKERS = (
    '<!-- hydra-progress:v1 {} -->',
    '<!-- hydra-work:v2 {} -->',
    '<!-- hydra-attempt-binding:v1 {} -->',
    '```text\n<!-- hydra-progress:v1 {} -->\n```',
    '\\<!-- hydra-progress:v1 {} -->',
)
BASIS = {'origin_phase': 'implementation', 'head': 'a' * 40,
         'contract_revision': 'b' * 40, 'spec_revision': None, 'intake_digest': 'c' * 64}


class DelegatedControlMarkerTests(unittest.TestCase):
    def test_reserved_markers_are_rejected_by_preparation_and_original_readback(self):
        for marker in MARKERS:
            text = 'Preserve the useful requirement.\n' + marker
            with self.subTest(marker=marker, boundary='prepare'):
                with self.assertRaises(InvalidPublicDecision):
                    prepare_delegated_context(text, {**BASIS, 'key': KEY})
            with self.subTest(marker=marker, boundary='readback'):
                body, _, _ = public_pair(BASIS, text)
                with self.assertRaises(InvalidPublicDecision):
                    parse_delegated_context(body)

    def test_escaped_examples_and_unrelated_comments_remain_valid_data(self):
        text = ('Use /settings. Example: &lt;!-- hydra-progress:v1 {} --&gt;.\n'
                '<!-- ordinary public note -->')
        context = prepare_delegated_context(text, {**BASIS, 'key': KEY})
        self.assertIn(text, context.body.decode())
        self.assertEqual(parse_delegated_context(context.body), context)


class DelegatedControlMarkerEntryTests(InstallationFixture, unittest.IsolatedAsyncioTestCase):
    async def test_sdk_rejects_reserved_records_before_any_service_publication(self):
        for marker in MARKERS:
            with self.subTest(marker=marker):
                self.setup_installation()
                self.write_profile(True)
                self.make_server(new_profile=True)
                result = await self.invoke(self.command(text='A useful route fix.\n' + marker))
                self.assertTrue(result.is_error, 'Reserved workflow records must remain input data')
                self.assertEqual(self.transport.effects, [])
