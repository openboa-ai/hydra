"""Partial-source and disclosure transitions preserve their actual scope."""
import copy
import json
import unittest

from hydra_sdlc.github import GitHubError
import test_post_merge_context as sources

CANARY, REPO, Wire = sources.CANARY, sources.REPO, sources.Wire


class SourceContextBoundaryTests(unittest.TestCase):
    read = sources.SourceContextTests.read
    context = sources.SourceContextTests.context

    def test_other_required_source_uncertainty_keeps_a_confirmed_failure(self):
        wire = Wire()
        row = wire.rows[REPO]
        row['policy'] += '\n[[required_checks]]\nworkflow_id=41\nworkflow_path=".github/workflows/ci.yml"\n' + \
            'job="Other required"\nevents=["pull_request","push"]\napp_id=15368\n'
        broken = copy.deepcopy(row['current']['runs'][0])
        broken.update(id=51, workflow_id=41, repository=None)
        row['current']['runs'].append(broken)
        value = self.context(self.read(wire))
        self.assertEqual(value['state'], 'failed')
        self.assertEqual([ref['job_id'] for ref in value['current']['checks']], [90])
        self.assertEqual(value['current']['coverage']['state'], 'partial')
        self.assertEqual(value['current']['coverage']['total_count'], 2)
        self.assertIsNone(value['history']['coverage']['total_count'])

    def test_known_repository_becoming_inaccessible_invalidates_shared_details(self):
        wire = Wire(2)
        counts = {}
        def revoke(repo, path):
            if wire.enriching and repo == 'example/project1':
                if '/issues/4/comments' in path:
                    counts['comments'] = counts.get('comments', 0) + 1
                if path == 'repos/example/project1' and counts.get('comments', 0) >= 2:
                    raise GitHubError(CANARY, status=404)
        wire.before = revoke
        rows = self.read(wire)
        for index in range(2):
            value = self.context(rows, index)
            self.assertEqual(value['state'], 'changed')
            self.assertIsNone(value['source'])
            self.assertEqual(value['current']['checks'], [])
            self.assertNotIn(CANARY, json.dumps(value))

    def test_historical_http_denial_does_not_imply_shared_disclosure_change(self):
        wire = Wire()
        wire.rerun(state='failure')
        def deny(repo, path):
            if wire.enriching and '/attempts/' in path:
                raise GitHubError(CANARY, status=403)
        wire.before = deny
        value = self.context(self.read(wire))
        self.assertEqual(value['state'], 'failed')
        self.assertEqual(value['current']['checks'][0]['run_attempt'], 2)
        self.assertNotEqual(value['history']['coverage']['state'], 'complete')
        self.assertNotIn(CANARY, json.dumps(value))

    def test_history_reauthenticates_every_required_source_predicate(self):
        for mutate in (
            lambda x: x['runs'][0].update(event='pull_request'),
            lambda x: x['runs'][0].update(head_sha='e' * 40),
            lambda x: x['runs'][0]['repository'].update(id=999),
            lambda x: x['checks'][0]['app'].update(id=999),
            lambda x: x['runs'][0]['jobs'].append(copy.deepcopy(x['runs'][0]['jobs'][0])),
        ):
            with self.subTest(mutate=mutate):
                wire = Wire()
                wire.rerun(state='failure')
                mutate(wire.rows[REPO]['history'][(50, 1)])
                value = self.context(self.read(wire))
                self.assertEqual(value['state'], 'failed')
                self.assertEqual(value['history']['failed_checks'], [])
                self.assertNotEqual(value['history']['coverage']['state'], 'complete')
                self.assertIsNone(value['history']['coverage']['total_count'])

    def test_optional_history_near_byte_limit_never_erases_current_failure(self):
        for length in range(14500, 16000, 19):
            with self.subTest(length=length):
                wire = Wire()
                name = 'Required' + 'x' * length
                row = wire.rows[REPO]
                row['policy'] = row['policy'].replace('Unit tests', name)
                row['current']['runs'][0]['jobs'][0]['name'] = name
                row['current']['checks'][0]['name'] = name
                wire.rerun(state='failure')
                value = self.context(self.read(wire))
                self.assertEqual(value['state'], 'failed')
                self.assertIsNotNone(value['source'])
                self.assertEqual(len(value['current']['checks']), 1)
                self.assertLessEqual(len(json.dumps(value).encode()), 32768)

    def test_current_budget_exhaustion_keeps_prior_rows_and_skips_history(self):
        wire = Wire(4)
        for repo in wire.rows:
            wire.rerun(repo, state='failure')
        rows = self.read(wire)
        self.assertEqual(self.context(rows)['state'], 'failed')
        self.assertTrue(all('post_merge_context' in row for row in rows))
        enriched = [call for call in wire.calls if call[0]]
        self.assertLessEqual(len(enriched), 128)
        # Every selected sibling has a current outcome before optional history.
        self.assertFalse(any('/attempts/' in call[3] for call in enriched))
