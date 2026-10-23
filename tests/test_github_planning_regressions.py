"""Provider corruption and response processing stay inside the read boundary."""
import unittest
from unittest.mock import patch

from hydra_sdlc import github_planning
from test_github_planning import Fixture, membership, value, values


class PlanningBoundaryTests(unittest.TestCase):
    def test_unhashable_provider_type_returns_unknown_without_exposing_content(self):
        for malformed in ([], {'private': 'SYNTHETIC_PRIVATE_TYPE_CANARY'}):
            with self.subTest(type=type(malformed).__name__):
                raw = values()
                raw['data']['item']['fieldValues']['nodes'][0]['__typename'] = malformed
                fixture = Fixture(fields=[raw])
                try:
                    result = fixture.read()
                except (TypeError, ValueError) as error:
                    self.fail('Malformed provider type escaped the unavailable-result boundary: '
                              + type(error).__name__)
                self.assertNotEqual(result['coverage'], 'complete')
                self.assertIsNone(result['priority'])
                self.assertEqual(result['reason'], 'planning_unavailable')
                self.assertNotIn('SYNTHETIC_PRIVATE_TYPE_CANARY', str(result))

    def test_deadline_includes_success_result_construction(self):
        clock = [0.0]
        original = github_planning.result

        def construct(*args, **kwargs):
            result = original(*args, **kwargs)
            if result.value['coverage'] == 'complete':
                clock[0] = 16.0
            return result

        fixture = Fixture()
        with patch('hydra_sdlc.github.time.monotonic', side_effect=lambda: clock[0]), \
                patch.object(github_planning, 'result', side_effect=construct):
            result = fixture.read()
        self.assertNotEqual(result['coverage'], 'complete')
        self.assertIsNone(result['priority'])
        self.assertEqual(len(fixture.calls), 2)

    def test_valid_source_still_returns_the_mapped_priority(self):
        result = Fixture().read()
        self.assertEqual((result['coverage'], result['priority'], result['reason']),
                         ('complete', 42, None))

    def test_deleted_unused_mapping_option_invalidates_existing_selected_value(self):
        members, fields = membership(), values()
        for raw in (members, fields):
            raw['data']['priorityField']['options'] = [{'id': 'option-critical'}]
        result = Fixture(members=[members], fields=[fields]).read()
        self.assertNotEqual(result['coverage'], 'complete')
        self.assertIsNone(result['priority'])
        self.assertEqual(result['reason'], 'planning_unavailable')

    def test_deleted_configured_option_cannot_make_explicit_null_known_zero(self):
        members, fields = membership(), values([value(None)])
        for raw in (members, fields):
            raw['data']['priorityField']['options'] = [{'id': 'option-critical'}]
        result = Fixture(members=[members], fields=[fields]).read()
        self.assertNotEqual(result['coverage'], 'complete')
        self.assertIsNone(result['priority'])

    def test_replaced_unused_option_cannot_make_unset_field_known_zero(self):
        members, fields = membership(), values([])
        for raw in (members, fields):
            raw['data']['priorityField']['options'] = [
                {'id': 'option-critical'}, {'id': 'replacement-low'}]
        result = Fixture(members=[members], fields=[fields]).read()
        self.assertNotEqual(result['coverage'], 'complete')
        self.assertIsNone(result['priority'])


if __name__ == '__main__':
    unittest.main()
