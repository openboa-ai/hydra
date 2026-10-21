"""Independent identity and raw-page resource bounds for native observations."""
import json
import unittest

from hydra_sdlc.github import GitHubError
from test_github_relations import Fixture, node, page


class NativeRelationIdentityTests(unittest.TestCase):
    def test_one_repository_name_cannot_identify_two_numeric_repositories(self):
        first = page(nodes=[node(2)])
        first['data']['repository']['issue']['blockedBy']['nodes'][0]['repository']['databaseId'] = 102
        second = page(nodes=[node(2, 102), node(3, 103)])
        second['data']['repository']['issue']['blockedBy']['nodes'][1]['repository']['nameWithOwner'] = 'EXAMPLE/other'
        for value in (first, second):
            with self.subTest(value=value), self.assertRaisesRegex(GitHubError, 'Invalid native relation'):
                Fixture(value).read()

    def test_exact_raw_page_bound_filters_extra_text_and_rejects_overflow(self):
        value = page()
        value['unrequested'] = 'PRIVATE_NATIVE_RELATION_CANARY'
        size = len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode())
        value['unrequested'] += 'x' * (131_072 - size)
        self.assertEqual(len(json.dumps(value, separators=(',', ':')).encode()), 131_072)
        result = Fixture(value).read()
        self.assertEqual(result['coverage'], 'complete')
        self.assertNotIn('PRIVATE_NATIVE_RELATION_CANARY', str(result))
        value['unrequested'] += 'x'
        with self.assertRaises(GitHubError):
            Fixture(value).read()

    def test_collection_counts_and_page_info_types_are_never_coerced(self):
        for path, invalid in [(('totalCount',), True), (('totalCount',), -1),
                              (('nodes',), {}), (('pageInfo', 'hasNextPage'), 0),
                              (('pageInfo', 'endCursor'), ''), (('pageInfo', 'hasNextPage'), True)]:
            value = page()
            target = value['data']['repository']['issue']['blockedBy']
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = invalid
            with self.subTest(path=path, invalid=invalid), self.assertRaises(GitHubError):
                Fixture(value).read()


if __name__ == '__main__':
    unittest.main()
