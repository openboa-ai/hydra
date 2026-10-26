"""Existing progress links remain distinct from versioned decision claims."""
import copy
import unittest

from hydra_sdlc.public_delegated_decisions import find_delegated_public_decision
from delegated_decision_fixture import ATTEMPT, REPO, InstallationFixture, canonical
from test_delegated_decision_boundaries import progress_payload
from test_delegated_decision_reader_capability import literal_pair


RESUME = '22222222-2222-4222-8222-222222222222'
LINK = {'source_attempt': ATTEMPT, 'resume_attempt': RESUME}
LINK_MARKER = '<!-- hydra-decision-context:v1 ' + canonical(LINK) + ' -->'


class DelegatedProgressLinkReaderTests(InstallationFixture, unittest.TestCase):
    def setUp(self):
        self.setup_installation()
        self.write_profile(False)
        self.make_server(new_profile=True)
        record = progress_payload(self.transport.rows[0]['body'])
        record.update(attempt_id=RESUME, phase='ready', wait_reason=None,
                      next_action='decision_context_' + ATTEMPT)
        self.transport.set_progress(record)
        self.progress_body = self.transport.rows[0]['body']

    def body(self, suffix):
        row = copy.deepcopy(self.transport.direct[1])
        row['body'] = self.progress_body + '\n' + suffix
        self.transport.direct[1] = copy.deepcopy(row)
        self.transport.rows = [copy.deepcopy(row) if item['id'] == 1 else item
                               for item in self.transport.rows]

    def find(self):
        context, observed = find_delegated_public_decision(self.github, REPO, 4, ATTEMPT)
        self.assertIsNone(context)
        self.assertEqual(self.transport.effects, [])
        self.assertEqual(self.transport.route_errors, [])
        return observed

    def assert_valid_link(self):
        observed = self.github.decision_progress_source(REPO, 4)
        self.assertEqual(observed['decision_context'], LINK)
        self.assertIsNone(observed['native_root'])
        self.assertEqual(observed['record']['attempt_id'], RESUME)
        self.assertEqual(observed['resource']['id'], REPO + '/comments/1')

    def test_canonical_existing_progress_link_is_not_an_intent_or_receipt(self):
        self.body(LINK_MARKER)
        self.assert_valid_link()
        self.assertEqual(self.find().status, 'not_observed')

    def test_link_and_unreadable_namespace_in_same_comment_hold_in_both_orders(self):
        unreadable = '<!-- hydra-decision-intent:future {unreadable-key -->'
        for ordering, suffix in (
            ('link first', LINK_MARKER + '\n' + unreadable),
            ('unreadable first', unreadable + '\n' + LINK_MARKER),
        ):
            with self.subTest(ordering=ordering):
                self.body(suffix)
                self.assert_valid_link()
                self.assertIn(self.find().status, {'unknown', 'conflict'},
                              'Recognizing the progress link must not skip the rest of its body')

    def test_malformed_or_changed_version_progress_link_is_not_safe_absence(self):
        malformed = {
            'invalid JSON': '<!-- hydra-decision-context:v1 {unreadable -->',
            'missing resume': '<!-- hydra-decision-context:v1 '
                              + canonical({'source_attempt': ATTEMPT}) + ' -->',
            'noncanonical UUID': '<!-- hydra-decision-context:v1 '
                                 + canonical({**LINK, 'resume_attempt': RESUME.replace('-', '')}) + ' -->',
            'changed version': LINK_MARKER.replace('hydra-decision-context:v1 ',
                                                   'hydra-decision-context:v2 '),
        }
        for name, marker in malformed.items():
            with self.subTest(marker=name):
                self.body(marker)
                self.assertIn(self.find().status, {'unknown', 'conflict'})

    def test_existing_link_and_valid_foreign_decision_pair_do_not_claim_current_work(self):
        self.body(LINK_MARKER)
        self.assert_valid_link()
        record = self.github.progress(REPO, 4)
        foreign = {**record, 'repository_id': 124, 'attempt_id': ATTEMPT}
        context, receipt = literal_pair(foreign)
        self.transport.add(110, context)
        self.transport.add(111, receipt)
        self.assertEqual(self.find().status, 'not_observed')
