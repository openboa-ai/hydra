"""Original-profile roots must not be adopted or blocked as delegated evidence."""
import copy
import json
import unittest

from hydra_sdlc.github import GitHub
from hydra_sdlc.public_decisions import prepare_context, receipt_body
from hydra_sdlc.public_delegated_decisions import find_delegated_public_decision
import test_public_decisions as original


class OriginalDecisionCompatibilityTests(unittest.TestCase):
    def setUp(self):
        basis = copy.deepcopy(original.BASIS)
        basis['key']['round'] = 2
        basis['supersedes'] = {'key': copy.deepcopy(original.KEY),
                               'context_sha256': original.context().sha256}
        basis['resume_attempt'] = '33333333-3333-4333-8333-333333333333'
        self.context = prepare_context('An amended original-profile decision.', basis)
        self.root = {'decision': {'key': basis['key'], 'context_sha256': self.context.sha256},
                     'resume_attempt': basis['resume_attempt']}
        self.transport = original.ReadOnlyTransport([
            original.comment(100, self.context.body),
            original.comment(101, receipt_body(self.context)),
        ])
        self.github = GitHub(transport=self.transport)

    def test_exact_original_round_two_root_returns_to_the_qualified_source_path(self):
        context, observed = find_delegated_public_decision(self.github, original.REPO, 4,
            original.ATTEMPT, expected_root=self.root)
        self.assertIsNone(context)
        self.assertEqual(observed.status, 'not_observed')

    def test_changed_original_root_is_not_a_valid_profile_fallback(self):
        wrong = copy.deepcopy(self.root)
        wrong['decision']['context_sha256'] = '0' * 64
        context, observed = find_delegated_public_decision(self.github, original.REPO, 4,
            original.ATTEMPT, expected_root=wrong)
        self.assertIsNone(context)
        self.assertIn(observed.status, {'unknown', 'conflict'})

    def test_round_two_delegated_marker_cannot_borrow_original_profile_support(self):
        basis = copy.deepcopy(original.BASIS)
        basis.update(key=self.root['decision']['key'], profile='codex_delegated_v1',
                     resume_attempt=self.root['resume_attempt'],
                     supersedes={'key': original.KEY, 'context_sha256': original.context().sha256})
        body = (f'hydra: decision {original.ATTEMPT} context\nA different profile.\n'
                '<!-- hydra-decision-intent:v2 ' + json.dumps(basis, sort_keys=True,
                    separators=(',', ':'), ensure_ascii=True) + ' -->\n')
        row = original.comment(102, body)
        self.transport.rows.append(row)
        self.transport.direct[102] = copy.deepcopy(row)
        context, observed = find_delegated_public_decision(self.github, original.REPO, 4,
            original.ATTEMPT, expected_root=self.root)
        self.assertIsNone(context)
        self.assertIn(observed.status, {'unknown', 'conflict'})
