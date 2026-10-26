"""The legacy authenticated read contract preserves valid progress links."""
import copy
from types import SimpleNamespace
import unittest

from hydra_sdlc.github import _decision_context_marker
from hydra_sdlc.operations import OperationDenied
from hydra_sdlc.work_decisions import WorkDecisionGuard
from delegated_decision_fixture import ATTEMPT, REPO, canonical
from test_public_decisions import comment
from test_runner import GitHub as LegacyGitHub


RESUME = '22222222-2222-4222-8222-222222222222'
LINK = {'source_attempt': ATTEMPT, 'resume_attempt': RESUME}
LINK_MARKER = '<!-- hydra-decision-context:v1 ' + canonical(LINK) + ' -->'
UNREADABLE = '<!-- hydra-decision-intent:future {unreadable-key -->'


class LegacyFacadeProgressLinkTests(unittest.TestCase):
    def setUp(self):
        self.github = LegacyGitHub()
        self.record = {
            'version': 1, 'repository_id': 123, 'issue_number': 4,
            'attempt_id': RESUME, 'host_alias': 'fixture',
            'branch': 'hydra/issue-4', 'execution_mode': 'native',
            'head': 'a' * 40, 'contract_revision': 'b' * 40,
            'spec_revision': None, 'intake_digest': 'c' * 64,
            'phase': 'ready', 'pending_action': None, 'wait_reason': None,
            'next_action': 'decision_context_' + ATTEMPT,
            'resume_phase': 'implementation',
        }
        self.github.note = copy.deepcopy(self.record)
        self.github._identity = lambda: {'id': 11, 'login': 'openboa'}
        self.github.repository = lambda repo: {'id': 123, 'full_name': repo}

        def progress_source(repo, number):
            return {'record': self.github.progress(repo, number),
                    'resource': {'source': 'github', 'kind': 'issue_comment',
                                 'id': REPO + '/comments/741'}}

        def original_progress(repo, number):
            # Only the established composite source contract is supplied. The
            # existing grammar reads the same actual body returned by comments.
            source = progress_source(repo, number)
            row = next(row for row in self.github.extra_comments if row['id'] == 741)
            return {**source, 'decision_context': _decision_context_marker(row['body']),
                    'native_root': None}

        self.github.progress_source = progress_source
        self.github.decision_progress_source = original_progress
        self.runner = SimpleNamespace(github=self.github, host='fixture', decision_source=None)
        self.set_link_body(LINK_MARKER)
        facade = self.github.read_client()
        self.assertEqual(facade._identity(), {'id': 11, 'login': 'openboa'})
        self.assertFalse(callable(getattr(facade, '_credential_selected', None)))
        self.assertFalse(callable(getattr(facade, '_request_timeout', None)))

    def set_link_body(self, suffix):
        body = '<!-- hydra-progress:v1 ' + canonical(self.record) + ' -->\n' + suffix
        self.github.extra_comments = [comment(741, body)]

    def guard(self):
        return WorkDecisionGuard(self.runner, REPO, 4)

    def assert_unchanged(self):
        self.assertEqual(self.github.note, self.record)
        self.assertEqual(self.github.writes, [])
        self.assertIsNone(self.github.branch)
        self.assertIsNone(self.github.pr)

    def test_valid_progress_link_remains_ordinary_with_or_without_outsider_noise(self):
        for outsider in (False, True):
            with self.subTest(outsider=outsider):
                self.set_link_body(LINK_MARKER)
                if outsider:
                    self.github.extra_comments.append(comment(742, UNREADABLE,
                        user={'id': 99, 'login': 'unrelated-contributor'}))
                observed = self.github.read_client().decision_progress_source(REPO, 4)
                self.assertEqual(observed['record'], self.record)
                self.assertEqual(observed['decision_context'], LINK)
                self.assertIsNone(observed['native_root'])
                guard = self.guard()
                self.assertEqual(guard.reconcile(), self.record)
                self.assertEqual(guard.mode, 'none')
                self.assert_unchanged()

    def test_unknown_mixed_malformed_and_duplicate_links_hold_the_common_guard(self):
        cases = {
            'link then unknown': LINK_MARKER + '\n' + UNREADABLE,
            'unknown then link': UNREADABLE + '\n' + LINK_MARKER,
            'malformed link': '<!-- hydra-decision-context:v1 {unreadable -->',
            'duplicate link': LINK_MARKER + '\n' + LINK_MARKER,
        }
        for name, suffix in cases.items():
            with self.subTest(source=name):
                self.set_link_body(suffix)
                with self.assertRaises(OperationDenied):
                    self.guard().reconcile()
                self.assert_unchanged()
