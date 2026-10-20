import copy
import unittest

from hydra_sdlc.github import GitHub, GitHubError
from hydra_sdlc.work_records import WorkRecordError, parse_binding
from test_work_records import AUTHOR, ATTEMPT, ISSUE, SOURCE, binding, comment, marker


REPO = 'example/alpha'
ROOT = '/repos/' + REPO
LISTING = ROOT + '/issues/11/comments?per_page=100&page=1'


class ReadSourceTests(unittest.TestCase):
    def client(self, rows=None):
        values = {('/user'): AUTHOR,
                  ROOT: {'id': 101, 'full_name': REPO, 'default_branch': 'main'},
                  ROOT + '/issues/11': ISSUE,
                  LISTING: [comment(71, marker(binding()))] if rows is None else rows}
        calls = []
        def transport(method, path, payload):
            calls.append((method, path, payload))
            self.assertEqual(method, 'GET', 'Binding inspection must have no write effects')
            value = values[path]
            if isinstance(value, Exception):
                raise value
            return copy.deepcopy(value)
        return GitHub(transport=transport), calls, values

    def read(self, github, **changes):
        args = dict(spec_directory='docs', selected_comment_id=71,
                    selected_digest=parse_binding(marker(binding()), spec_directory='docs').digest)
        args.update(changes)
        return github.work_binding_source(REPO, 11, **args)

    def test_explicit_read_binds_actual_repository_author_issue_and_selected_comment(self):
        github, calls, _ = self.client()
        result = self.read(github)
        self.assertEqual(result.comment_id, 71)
        self.assertEqual(result.binding.value, binding())
        self.assertEqual(len(calls), 4)

    def test_invalid_selection_performs_no_external_reads(self):
        for changes in [{'selected_digest': None}, {'selected_comment_id': None}, {'recover': True}, {'recover': 1}]:
            github, calls, _ = self.client()
            with self.subTest(changes=changes), self.assertRaises(WorkRecordError):
                self.read(github, **changes)
            self.assertEqual(calls, [])

    def test_repository_case_alias_uses_authenticated_canonical_source(self):
        github, calls, values = self.client()
        for path, value in list(values.items()):
            if REPO in path:
                values[path.replace(REPO, REPO.upper())] = value
        try:
            result = github.work_binding_source(REPO.upper(), 11, spec_directory='docs',
                selected_comment_id=71,
                selected_digest=parse_binding(marker(binding()), spec_directory='docs').digest)
        except WorkRecordError as exc:
            self.fail('A stable numeric repository identity was rejected for display casing: ' + exc.reason)
        self.assertEqual(result.comment_id, 71)
        self.assertIn(('GET', LISTING, None), calls)

    def test_partial_or_repeated_collection_never_becomes_a_selection(self):
        first = [comment(n, 'unrelated', user={'id': 999, 'login': 'external'}) for n in range(1, 101)]
        for tail in [GitHubError('read failed'), [first[-1]]]:
            github, calls, values = self.client(first)
            values[ROOT + '/issues/11/comments?per_page=100&page=2'] = tail
            with self.subTest(tail=type(tail).__name__), self.assertRaises((GitHubError, WorkRecordError)):
                self.read(github)
            self.assertEqual(len(calls), 5)

    def test_page_two_selection_is_read_instead_of_treating_first_page_as_complete(self):
        rows = [comment(n, 'unrelated', user={'id': 999, 'login': 'external'}) for n in range(100, 200)]
        github, calls, values = self.client(rows)
        values[ROOT + '/issues/11/comments?per_page=100&page=2'] = [comment(71, marker(binding()))]
        self.assertEqual(self.read(github).comment_id, 71)
        self.assertEqual(len(calls), 5)

    def test_collection_reads_stop_at_existing_request_budget(self):
        github, calls, _ = self.client()
        with github.read_budget(seconds=30, requests=2):
            with self.assertRaises(GitHubError):
                self.read(github)
        self.assertEqual(len(calls), 2)

    def test_numeric_repository_drift_or_wrong_issue_source_is_not_accepted(self):
        for key, value in [(ROOT, {'id': 102, 'full_name': REPO, 'default_branch': 'main'}),
                           (ROOT + '/issues/11', {**ISSUE, 'url': 'https://api.github.com/repos/example/other/issues/11'})]:
            github, _, values = self.client()
            values[key] = value
            with self.subTest(key=key), self.assertRaises(WorkRecordError) as caught:
                self.read(github)
            self.assertEqual(caught.exception.reason, 'identity_mismatch')

    def test_recovery_reads_real_validated_progress_and_does_not_accept_supplied_progress(self):
        digest = parse_binding(marker(binding()), spec_directory='docs').digest
        progress = {'version': 1, 'repository_id': 101, 'issue_number': 11,
                    'phase': 'implementation_done', 'head': '1' * 40,
                    'attempt_id': ATTEMPT, 'intake_digest': SOURCE, 'contract_revision': '2' * 40}
        anchor = {'repository_id': 101, 'issue_number': 11, 'attempt_id': ATTEMPT,
                  'binding_comment_id': 71, 'binding_digest': digest,
                  'source_digest': SOURCE, 'contract_revision': '2' * 40}
        rows = [comment(71, marker(binding())), comment(72, marker(anchor, 'hydra-attempt-binding:v1')),
                comment(73, marker(progress, 'hydra-progress:v1'))]
        github, calls, _ = self.client(rows)
        result = github.work_binding_source(REPO, 11, spec_directory='docs', recover=True)
        self.assertEqual(result.comment_id, 71)
        self.assertGreater(len(calls), 4)
        self.assertEqual(sum(path == LISTING for _, path, _ in calls), 1,
                         'Progress and attempt anchors must come from one collected view')
        with self.assertRaises(TypeError):
            github.work_binding_source(REPO, 11, spec_directory='docs', recover=True, progress=progress)


if __name__ == '__main__':
    unittest.main()
