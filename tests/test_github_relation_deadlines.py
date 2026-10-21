"""Deadline oracles cover response validation and normalization, not only HTTP."""
import unittest
from unittest.mock import patch

import hydra_sdlc.github_relations as reader
from test_github_relations import Fixture, node, page


class NativeRelationDeadlineTests(unittest.TestCase):
    def test_source_validation_after_deadline_cannot_establish_known_absence(self):
        for relation in ('parent', 'children', 'blocked_by'):
            with self.subTest(relation=relation):
                clock = {'now': 100.0}
                original = reader._source
                def delayed(*args):
                    value = original(*args)
                    clock['now'] = 116.0
                    return value
                with patch('hydra_sdlc.github.time.monotonic', side_effect=lambda: clock['now']), \
                     patch.object(reader, '_source', side_effect=delayed):
                    result = Fixture(page(relation)).read(relation)
                self.assertEqual((result['coverage'], result['items'], result['digest']),
                                 ('unavailable', [], None))

    def test_late_target_validation_preserves_only_the_previous_page_prefix(self):
        clock = {'now': 100.0}
        original = reader._node
        def delayed(value):
            result = original(value)
            if value['number'] == 9:
                clock['now'] = 116.0
            return result
        fixture = Fixture(page(nodes=[node(2)], total=2, more=True, cursor='next'),
                          page(nodes=[node(9)], total=2))
        with patch('hydra_sdlc.github.time.monotonic', side_effect=lambda: clock['now']), \
             patch.object(reader, '_node', side_effect=delayed):
            result = fixture.read()
        self.assertEqual(result['coverage'], 'partial')
        self.assertEqual(result['items'], [{'repository_id': 101, 'issue_number': 2}])
        self.assertIsNone(result['digest'])
        self.assertEqual(len(fixture.calls), 2)

    def test_normalization_after_deadline_downgrades_the_completed_value(self):
        clock = {'now': 100.0}
        original = reader.relation_read
        def delayed(source, relation, coverage, items, observed_at):
            value = original(source, relation, coverage, items, observed_at)
            if coverage == 'complete':
                clock['now'] = 116.0
            return value
        with patch('hydra_sdlc.github.time.monotonic', side_effect=lambda: clock['now']), \
             patch.object(reader, 'relation_read', side_effect=delayed):
            result = Fixture(page('parent')).read('parent')
        self.assertEqual((result['coverage'], result['items'], result['digest']),
                         ('unavailable', [], None))


if __name__ == '__main__':
    unittest.main()
