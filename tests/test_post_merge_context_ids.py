"""Malformed numeric identities never qualify origin or shared disclosure."""
import unittest

import test_post_merge_context as sources


class SourceIdentityTests(unittest.TestCase):
    read = sources.SourceContextTests.read
    context = sources.SourceContextTests.context

    def test_malformed_nested_history_id_cannot_invalidate_qualified_siblings(self):
        for identifier in (123.0, True, '123'):
            with self.subTest(identifier=identifier):
                wire = sources.Wire(2)
                for repo in wire.rows:
                    wire.rerun(repo, state='failure')
                wire.rows[sources.REPO]['history'][(50, 1)]['runs'][0]['repository'].update(
                    id=identifier, private=True, visibility='private')
                rows = self.read(wire)
                first, sibling = self.context(rows), self.context(rows, 1)
                self.assertEqual((first['state'], sibling['state']), ('failed', 'failed'))
                self.assertEqual(first['history']['failed_checks'], [])
                self.assertNotEqual(first['history']['coverage']['state'], 'complete')
                self.assertIsNone(first['history']['coverage']['total_count'])
                self.assertEqual(sibling['history']['coverage']['state'], 'complete')

    def test_malformed_pr_author_or_endpoint_ids_cannot_qualify_origin(self):
        for path, identifier in [(('user', 'id'), 101.0),
                                 (('head', 'repo', 'id'), 123.0),
                                 (('base', 'repo', 'id'), 123.0)]:
            with self.subTest(path=path):
                wire = sources.Wire(2)
                target = wire.rows[sources.REPO]['pr']
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = identifier
                rows = self.read(wire)
                first, sibling = self.context(rows), self.context(rows, 1)
                self.assertEqual(first['state'], 'unknown')
                self.assertIsNone(first['source'])
                self.assertEqual(first['current']['checks'], [])
                self.assertEqual(sibling['state'], 'failed')

    def test_malformed_current_nested_id_is_local_source_uncertainty(self):
        wire = sources.Wire(2)
        wire.rows[sources.REPO]['current']['runs'][0]['repository']['id'] = 123.0
        rows = self.read(wire)
        first, sibling = self.context(rows), self.context(rows, 1)
        self.assertEqual(first['state'], 'unknown')
        self.assertEqual(first['current']['checks'], [])
        self.assertNotEqual(first['history']['coverage']['state'], 'complete')
        self.assertIsNone(first['history']['coverage']['total_count'])
        self.assertEqual(sibling['state'], 'failed')

    def test_unqualified_fallback_repository_id_cannot_prove_empty_history(self):
        wire = sources.Wire()
        run = wire.rows[sources.REPO]['current']['runs'][0]
        run.pop('repository')
        run['repository_id'] = 123.0
        value = self.context(self.read(wire))
        self.assertEqual(value['state'], 'unknown')
        self.assertEqual(value['history']['failed_checks'], [])
        self.assertNotEqual(value['history']['coverage']['state'], 'complete')
        self.assertIsNone(value['history']['coverage']['total_count'])
