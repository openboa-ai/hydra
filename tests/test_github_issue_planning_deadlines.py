"""Completion deadlines include normalization and inherited outer budgets."""
import unittest
from unittest.mock import patch

from hydra_sdlc import github_issue_planning as planning
from test_github_issue_planning import Fixture


class IssuePlanningDeadlineTests(unittest.TestCase):
    def late_normalization(self, body, *, outer_seconds=None):
        fixture = Fixture(body)
        clock = {'now': 100.0}
        original = planning._canonical
        normalized = []
        def slow(value):
            result = original(value)
            if type(value) is dict and value.get('coverage') == 'complete':
                normalized.append(value['priority'])
                clock['now'] = 116.0 if outer_seconds is None else 104.0
            return result
        with patch('hydra_sdlc.github.time.monotonic', side_effect=lambda: clock['now']), \
             patch.object(planning, '_canonical', side_effect=slow):
            if outer_seconds is None:
                result = fixture.read()
            else:
                with fixture.client.read_budget(seconds=outer_seconds, requests=20):
                    result = fixture.read()
        self.assertEqual(len(normalized), 1)
        self.assertEqual({key: result[key] for key in ('coverage', 'priority', 'created_at', 'source_digest', 'reason')},
                         {'coverage': 'partial', 'priority': None, 'created_at': None,
                          'source_digest': None, 'reason': 'planning_unavailable'})

    def test_normalization_after_deadline_cannot_publish_zero_or_explicit_priority(self):
        for body in (None, '```hydra\npriority=7\n```'):
            with self.subTest(body=body):
                self.late_normalization(body)

    def test_normalization_must_respect_the_shorter_outer_deadline(self):
        self.late_normalization('```hydra\npriority=7\n```', outer_seconds=3)
