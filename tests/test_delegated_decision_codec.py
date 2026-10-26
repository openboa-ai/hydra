"""Independent literal and authenticated-source oracles for delegated v2 data."""
import copy
import hashlib
import importlib
import unittest

from hydra_sdlc.public_decisions import InvalidPublicDecision
from delegated_decision_fixture import (
    ATTEMPT, KEY, REPO, InstallationFixture, public_pair,
)


LITERAL_BASIS = {
    'origin_phase': 'implementation', 'head': 'a' * 40,
    'contract_revision': 'b' * 40, 'spec_revision': None,
    'intake_digest': 'c' * 64,
}
CONTEXT_BYTE_LIMIT = 16 * 1024


class DelegatedCodecBoundaryTests(unittest.TestCase):
    def setUp(self):
        try:
            self.codec = importlib.import_module('hydra_sdlc.public_delegated_decisions')
        except ModuleNotFoundError as exc:
            if exc.name != 'hydra_sdlc.public_delegated_decisions':
                raise
            self.fail('The accepted delegated v2 producer and parser must be available')

    def prepare(self, text):
        return self.codec.prepare_delegated_context(
            text, {'key': copy.deepcopy(KEY), **copy.deepcopy(LITERAL_BASIS)})

    def assert_literal_pair(self, text, normalized):
        context, receipt, _ = public_pair(LITERAL_BASIS, normalized)
        expected = context.encode('utf-8')
        prepared = self.prepare(text)
        self.assertEqual(prepared.body, expected)
        self.assertEqual(prepared.sha256, hashlib.sha256(expected).hexdigest())
        self.assertEqual(prepared.key, (123, 4, ATTEMPT, 1))
        self.assertEqual(self.codec.parse_delegated_context(context).body, expected)
        self.assertEqual(self.codec.parse_delegated_context(expected).body, expected)
        self.assertEqual(self.codec.delegated_receipt_body(prepared), receipt.encode('utf-8'))
        self.assertEqual(self.codec.parse_delegated_receipt(receipt),
                         ((123, 4, ATTEMPT, 1), hashlib.sha256(expected).hexdigest()))
        return expected

    def test_choice_and_free_text_normalize_line_endings_only(self):
        text = ' \tChoice: Keep e\u0301\u00a0\r\n자유 답변:\tstay \rKeep this\u2003\t\r\n\r\n'
        normalized = ' \tChoice: Keep e\u0301\u00a0\n자유 답변:\tstay \nKeep this\u2003\t'
        expected = self.assert_literal_pair(text, normalized)
        self.assertIn(normalized.encode('utf-8') + b'\n<!--', expected)
        self.assertEqual(self.prepare(normalized).body, expected)
        self.assertNotEqual(self.prepare(normalized.replace('e\u0301', '\u00e9')).body,
                            expected, 'Unicode normalization must not rewrite the proposal')

    def test_exact_16_kib_context_is_accepted_and_overflow_never_truncates(self):
        # Only the independent literal fixture supplies framing overhead.
        overhead = len(public_pair(LITERAL_BASIS, 'x')[0].encode('utf-8')) - 1
        text = 'x' * (CONTEXT_BYTE_LIMIT - overhead)
        expected = self.assert_literal_pair(text, text)
        self.assertEqual(len(expected), CONTEXT_BYTE_LIMIT)
        for oversized in (text + 'x', text[:-1] + '\u00e9'):
            with self.subTest(utf8_bytes=len(oversized.encode('utf-8'))):
                literal = public_pair(LITERAL_BASIS, oversized)[0].encode('utf-8')
                self.assertEqual(len(literal), CONTEXT_BYTE_LIMIT + 1)
                with self.assertRaises(InvalidPublicDecision):
                    self.prepare(oversized)
                with self.assertRaises(InvalidPublicDecision):
                    self.codec.parse_delegated_context(literal)

    def test_parsers_require_exact_canonical_context_and_receipt_framing(self):
        context, receipt, _ = public_pair(LITERAL_BASIS)
        for name, literal, parser in (
            ('context', context.encode('utf-8'), self.codec.parse_delegated_context),
            ('receipt', receipt.encode('utf-8'), self.codec.parse_delegated_receipt),
        ):
            for mutation, changed in (
                ('CRLF', literal.replace(b'\n', b'\r\n')),
                ('CR', literal.replace(b'\n', b'\r')),
                ('extra trailing LF', literal + b'\n'),
                ('missing final LF', literal[:-1]),
            ):
                with self.subTest(record=name, mutation=mutation), \
                        self.assertRaises(InvalidPublicDecision):
                    parser(changed)


class DelegatedAuthenticatedSourceTests(InstallationFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.setup_installation()
        self.write_profile(True)
        self.make_server(new_profile=True)

    def add_pair(self, *, text='Use the existing contract.', first_id=100):
        context, receipt, resume = public_pair(self.transport.basis, text)
        self.transport.add(first_id, context)
        self.transport.add(first_id + 1, receipt)
        return context, receipt, resume

    async def assert_source_holds_without_effects(self):
        progress = self.github.progress(REPO, 4)
        controls = self.control.snapshot()
        result = self.reply(await self.invoke())
        self.assertIn(result['request']['outcome'], {'waiting', 'rejected', 'unknown'}, result)
        self.assertIsNone(result['request']['receipt'], result)
        self.assertIsNone(result.get('handoff'), result)
        self.assertEqual(self.transport.effects, [], 'Invalid evidence must not be repaired by publication')
        self.assertEqual(self.github.progress(REPO, 4), progress)
        self.assertEqual(self.control.snapshot(), controls)

    async def test_exact_existing_pair_is_confirmed_without_another_publication(self):
        _, _, resume = self.add_pair()
        progress = self.github.progress(REPO, 4)
        controls = self.control.snapshot()
        result = self.reply(await self.invoke())
        self.assertEqual(result['request']['outcome'], 'applied', result)
        self.assertEqual(result['request']['receipt']['kind'], 'decision')
        self.assertEqual(result['request']['receipt']['profile'], 'codex_delegated_v1')
        self.assertEqual(result['request']['receipt']['resume_attempt'], resume)
        self.assertIn(f'/repos/{REPO}/issues/comments/100', self.transport.calls)
        self.assertIn(f'/repos/{REPO}/issues/comments/101', self.transport.calls)
        self.assertEqual(self.transport.effects, [])
        self.assertEqual(self.github.progress(REPO, 4), progress)
        self.assertEqual(self.control.snapshot(), controls)
        self.assertIsNone(result.get('handoff'))

    async def test_edited_context_does_not_become_a_confirmed_pair(self):
        self.add_pair()
        edited = {**self.transport.direct[100], 'updated_at': '2026-01-02T00:00:00Z'}
        self.transport.direct[100] = copy.deepcopy(edited)
        self.transport.rows = [copy.deepcopy(edited) if row['id'] == 100 else row
                               for row in self.transport.rows]
        await self.assert_source_holds_without_effects()

    async def test_orphan_receipt_cannot_authorize_recreating_its_missing_context(self):
        _, receipt, _ = public_pair(self.transport.basis)
        self.transport.add(101, receipt)
        await self.assert_source_holds_without_effects()

    async def test_different_canonical_context_for_same_key_holds_both_proposals(self):
        first, _, _ = self.add_pair()
        conflicting, _, _ = public_pair(self.transport.basis, 'Keep the original scope and use a different wording.')
        self.assertNotEqual(first, conflicting)
        self.transport.add(102, conflicting)
        await self.assert_source_holds_without_effects()

    async def test_conflicting_receipt_digest_cannot_confirm_the_existing_context(self):
        self.add_pair()
        _, conflicting_receipt, _ = public_pair(self.transport.basis, 'A different public interpretation.')
        self.transport.add(102, conflicting_receipt)
        await self.assert_source_holds_without_effects()
