"""Native relation page/identity oracles; fixtures grant no live capability."""
import copy
import hashlib
import unittest

from hydra_sdlc.github import GitHub, GitHubError

SOURCE = {'repository_id': 101, 'issue_number': 7}
FIELDS = {'parent': 'parent', 'children': 'subIssues', 'blocked_by': 'blockedBy'}


def repository(identifier=101, name='example/product', permission='ADMIN'):
    return {'databaseId': identifier, 'nameWithOwner': name,
            'isPrivate': False, 'viewerPermission': permission}


def node(number, identifier=101):
    return {'id': f'I_{identifier}_{number}', 'number': number,
            'repository': repository(identifier, 'example/product' if identifier == 101 else 'example/other')}


def page(relation='blocked_by', nodes=(), *, total=None, more=False, cursor=None, summary=None):
    issue = {'id': 'I_101_7', 'number': 7}
    if relation == 'parent':
        issue['parent'] = copy.deepcopy(nodes[0]) if nodes else None
    else:
        total = len(nodes) if total is None else total
        issue[FIELDS[relation]] = {'totalCount': total, 'nodes': copy.deepcopy(list(nodes)),
                                  'pageInfo': {'hasNextPage': more, 'endCursor': cursor}}
        if relation == 'blocked_by':
            issue['issueDependenciesSummary'] = {'totalBlockedBy': total if summary is None else summary}
        else:
            issue['subIssuesSummary'] = {'total': total if summary is None else summary}
    return {'data': {'repository': {**repository(), 'issue': issue}}}


class Fixture:
    def __init__(self, *responses, rotate=False):
        self.responses = list(copy.deepcopy(responses))
        self.calls = []
        self.rotate = rotate
        self.client = GitHub(transport=self.transport)

    def transport(self, method, path, payload):
        self.calls.append((method, path, copy.deepcopy(payload)))
        if self.rotate:
            self.client._authenticated_fingerprint = bytes([len(self.calls)]) * 32
        if not self.responses:
            raise AssertionError('Unbounded or unexpected source read')
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def read(self, relation='blocked_by', source=None):
        return self.client.native_relation_read('example/product', copy.deepcopy(SOURCE if source is None else source), relation).value


class NativeRelationReadTests(unittest.TestCase):
    def test_empty_collections_and_explicit_null_parent_are_complete_observations(self):
        for relation in FIELDS:
            with self.subTest(relation=relation):
                fixture = Fixture(page(relation))
                result = fixture.read(relation)
                self.assertEqual((result['source'], result['relation'], result['coverage'], result['items']),
                                 (SOURCE, relation, 'complete', []))
                self.assertIsNotNone(result['digest'])
                self.assertEqual(len(fixture.calls), 1)

    def test_present_parent_and_sorted_cross_repository_items_keep_numeric_identity(self):
        parent = Fixture(page('parent', [node(9, 102)])).read('parent')
        self.assertEqual(parent['items'], [{'repository_id': 102, 'issue_number': 9}])
        fixture = Fixture(page(nodes=[node(9, 102), node(2)]))
        result = fixture.read()
        self.assertEqual(result['items'], [{'repository_id': 101, 'issue_number': 2},
                                          {'repository_id': 102, 'issue_number': 9}])
        literal = (b'{"items":[{"issue_number":2,"repository_id":101},{"issue_number":9,"repository_id":102}],'
                   b'"relation":"blocked_by","source":{"issue_number":7,"repository_id":101}}')
        self.assertEqual(result['digest'], hashlib.sha256(literal).hexdigest())

    def test_two_pages_follow_only_the_returned_cursor_and_terminal_page_info(self):
        for relation in ('blocked_by', 'children'):
            fixture = Fixture(page(relation, [node(2)], total=2, more=True, cursor='next-1'),
                              page(relation, [node(9, 102)], total=2))
            result = fixture.read(relation)
            self.assertEqual((result['coverage'], len(result['items'])), ('complete', 2))
            self.assertEqual([call[2]['variables']['after'] for call in fixture.calls], [None, 'next-1'])
            self.assertEqual([call[:2] for call in fixture.calls], [('POST', '/graphql')] * 2)

    def test_first_http_failure_is_unknown_and_second_failure_preserves_only_observed_prefix(self):
        for status in (403, 404, 429, None):
            with self.subTest(status=status):
                error = GitHubError('PRIVATE_NATIVE_RELATION_CANARY', status=status, uncertain=True)
                first = Fixture(error).read()
                self.assertEqual((first['coverage'], first['items'], first['digest']), ('unavailable', [], None))
                fixture = Fixture(page(nodes=[node(2)], total=2, more=True, cursor='next'), error)
                later = fixture.read()
                self.assertEqual((later['coverage'], later['items'], later['digest']),
                                 ('partial', [{'repository_id': 101, 'issue_number': 2}], None))
                self.assertNotIn('PRIVATE_NATIVE_RELATION_CANARY', str(later))
                self.assertEqual(len(fixture.calls), 2)

    def test_graphql_field_errors_never_promote_partial_data_to_empty_success(self):
        value = page(nodes=[node(2)])
        value['errors'] = [{'message': 'PRIVATE_NATIVE_RELATION_CANARY', 'path': ['repository', 'issue']}]
        result = Fixture(value).read()
        self.assertEqual((result['coverage'], result['items'], result['digest']), ('unavailable', [], None))

    def test_missing_issue_repository_or_permission_is_unavailable(self):
        for kind in ('repository-null', 'issue-null', 'permission-null'):
            value = page()
            if kind == 'repository-null':
                value['data']['repository'] = None
            elif kind == 'issue-null':
                value['data']['repository']['issue'] = None
            else:
                value['data']['repository']['viewerPermission'] = None
            with self.subTest(kind=kind):
                result = Fixture(value).read()
                self.assertEqual((result['coverage'], result['items']), ('unavailable', []))

    def test_source_repository_issue_and_node_identity_are_not_retargeted(self):
        changes = [('databaseId', 102), ('nameWithOwner', 'example/renamed'), ('isPrivate', 0),
                   ('viewerPermission', 'invented')]
        for key, invalid in changes:
            value = page()
            value['data']['repository'][key] = invalid
            with self.subTest(key=key), self.assertRaisesRegex(GitHubError, 'Invalid native relation'):
                Fixture(value).read()
        for key, invalid in [('id', None), ('number', 8), ('number', True)]:
            value = page()
            value['data']['repository']['issue'][key] = invalid
            with self.subTest(key=key, invalid=invalid), self.assertRaises(GitHubError):
                Fixture(value).read()

    def test_duplicate_nodes_within_or_across_pages_are_invalid(self):
        cases = [(page(nodes=[node(2), node(2)]),),
                 (page(nodes=[node(2)], total=2, more=True, cursor='next'), page(nodes=[node(2)], total=2))]
        for responses in cases:
            with self.subTest(pages=len(responses)), self.assertRaises(GitHubError):
                Fixture(*responses).read()

    def test_repeated_missing_and_nonadvancing_cursors_do_not_loop(self):
        for cursor in (None, '', 12):
            with self.subTest(cursor=cursor), self.assertRaises(GitHubError):
                Fixture(page(nodes=[node(2)], total=2, more=True, cursor=cursor)).read()
        fixture = Fixture(page(nodes=[node(2)], total=3, more=True, cursor='next'),
                          page(nodes=[node(3)], total=3, more=True, cursor='next'))
        with self.assertRaises(GitHubError):
            fixture.read()
        self.assertEqual(len(fixture.calls), 2)

    def test_summary_and_terminal_count_mismatches_remain_partial(self):
        for relation in ('blocked_by', 'children'):
            for value in (page(relation, [node(2)], total=2),
                          page(relation, [node(2)], total=1, summary=2)):
                with self.subTest(relation=relation):
                    result = Fixture(value).read(relation)
                    self.assertEqual((result['coverage'], result['digest']), ('partial', None))
                    self.assertEqual(result['items'], [{'repository_id': 101, 'issue_number': 2}])

    def test_total_or_source_node_changes_between_pages_do_not_form_complete_membership(self):
        changed_count = page(nodes=[node(3)], total=3)
        changed_identity = page(nodes=[node(3)], total=2)
        changed_identity['data']['repository']['issue']['id'] = 'replaced-source-node'
        for second in (changed_count, changed_identity):
            fixture = Fixture(page(nodes=[node(2)], total=2, more=True, cursor='next'), second)
            result = fixture.read()
            self.assertEqual((result['coverage'], result['digest']), ('partial', None))
            self.assertEqual(result['items'], [{'repository_id': 101, 'issue_number': 2}])

    def test_closed_inclusive_summary_is_used_instead_of_open_only_count(self):
        value = page(nodes=[node(2)], total=1)
        value['data']['repository']['issue']['issueDependenciesSummary']['blockedBy'] = 0
        result = Fixture(value).read()
        self.assertEqual((result['coverage'], len(result['items'])), ('complete', 1))

    def test_bad_target_shape_identity_and_unknown_visibility_are_not_complete(self):
        for key, invalid in [('number', False), ('number', 0), ('id', ''), ('repository', None)]:
            value = page(nodes=[node(2)])
            value['data']['repository']['issue']['blockedBy']['nodes'][0][key] = invalid
            with self.subTest(key=key), self.assertRaises(GitHubError):
                Fixture(value).read()
        value = page(nodes=[node(2)])
        value['data']['repository']['issue']['blockedBy']['nodes'][0]['repository']['viewerPermission'] = None
        result = Fixture(value).read()
        self.assertEqual(result['coverage'], 'unavailable')

    def test_each_selected_relation_uses_one_fixed_query_without_unrelated_relations(self):
        for relation, field in FIELDS.items():
            fixture = Fixture(page(relation))
            fixture.read(relation)
            self.assertEqual(len(fixture.calls), 1)
            query = fixture.calls[0][2]['query']
            self.assertTrue(query.startswith('query '))
            self.assertNotIn('mutation', query.lower())
            self.assertIn(field, query)
            for unrelated in set(FIELDS.values()) - {field}:
                self.assertNotIn(unrelated, query)

    def test_cursor_data_is_a_variable_and_cannot_change_the_fixed_query(self):
        cursor = '\"}) mutation { removeBlockedBy(input:{id:1}) } #'
        fixture = Fixture(page(nodes=[node(2)], total=2, more=True, cursor=cursor), page(nodes=[node(3)], total=2))
        self.assertEqual(fixture.read()['coverage'], 'complete')
        self.assertEqual(fixture.calls[1][2]['variables']['after'], cursor)
        self.assertEqual(fixture.calls[0][2]['query'], fixture.calls[1][2]['query'])
        self.assertNotIn(cursor, fixture.calls[1][2]['query'])

    def test_numeric_bounds_and_invalid_relation_are_rejected_before_http(self):
        for source in ({'repository_id': True, 'issue_number': 7}, {'repository_id': 101, 'issue_number': 0},
                       {'repository_id': 101, 'issue_number': 9_007_199_254_740_992}, {**SOURCE, 'extra': True}):
            fixture = Fixture()
            with self.subTest(source=source), self.assertRaises(GitHubError):
                fixture.read(source=source)
            self.assertEqual(fixture.calls, [])
        for relation in ('legacy', '', [], None):
            fixture = Fixture()
            with self.subTest(relation=relation), self.assertRaises(GitHubError):
                fixture.read(relation)
            self.assertEqual(fixture.calls, [])

    def test_255_items_are_complete_and_256_is_a_bounded_partial_prefix(self):
        for total in (255, 256):
            fixture = Fixture(page(nodes=[node(n) for n in range(10, 110)], total=total, more=True, cursor='p2'),
                              page(nodes=[node(n) for n in range(110, 210)], total=total, more=True, cursor='p3'),
                              page(nodes=[node(n) for n in range(210, 265)], total=total, more=total == 256, cursor='p4' if total == 256 else None))
            result = fixture.read()
            self.assertEqual(len(result['items']), 255)
            self.assertEqual(result['coverage'], 'complete' if total == 255 else 'partial')
            self.assertEqual([call[2]['variables']['first'] for call in fixture.calls], [100, 100, 55])
            self.assertEqual(len(fixture.calls), 3)

    def test_outer_request_and_time_budgets_bound_the_reader(self):
        fixture = Fixture(page(nodes=[node(2)], total=2, more=True, cursor='next'))
        with fixture.client.read_budget(seconds=2, requests=1):
            result = fixture.read()
        self.assertEqual((result['coverage'], len(fixture.calls)), ('partial', 1))
        fixture = Fixture()
        with fixture.client.read_budget(seconds=0, requests=5):
            result = fixture.read()
        self.assertEqual((result['coverage'], fixture.calls), ('unavailable', []))

    def test_credential_rotation_during_collection_is_partial_without_mixing_new_page(self):
        fixture = Fixture(page(nodes=[node(2)], total=2, more=True, cursor='next'), page(nodes=[node(3)], total=2), rotate=True)
        result = fixture.read()
        self.assertEqual((result['coverage'], result['digest'], len(fixture.calls)), ('partial', None, 2))
        self.assertEqual(result['items'], [{'repository_id': 101, 'issue_number': 2}])

    def test_independent_observations_do_not_reuse_cached_membership(self):
        fixture = Fixture(page(nodes=[node(2)]), page(nodes=[node(3)]))
        first, second = fixture.read(), fixture.read()
        self.assertEqual(len(fixture.calls), 2)
        self.assertNotEqual(first['digest'], second['digest'])
        self.assertEqual(first['items'], [{'repository_id': 101, 'issue_number': 2}])


if __name__ == '__main__':
    unittest.main()
