"""An ownership probe cannot hide an intervening local Pause or Stop."""
import unittest
from test_projection_read import ReadFixture


class FinalAdmissionObservationTests(unittest.TestCase):
    def test_gate_is_observed_after_the_ownership_probe(self):
        for mode in ('paused', 'stopped'):
            with self.subTest(mode=mode):
                snapshot = {'revision': 7, 'global_mode': 'running', 'projects': {}}
                def ownership(_):
                    snapshot.update(revision=8, global_mode=mode)
                    return {'state': 'free'}
                fixture = ReadFixture()
                frame = fixture.read(refresh=False, owner=ownership, admission_snapshot=snapshot)
                observation = next(o for o in frame['observations'] if o['resource']['kind'] == 'admission')
                self.assertEqual(observation['value'], {'revision': 8, 'global_mode': mode,
                    'project_overrides': {}, 'gate_reason': 'host_' + mode})
                self.assertEqual(observation['revision'], {'kind': 'monotonic', 'value': '8'})
                self.assertTrue(all(project['admission']['value'] == mode for project in frame['projects']))
                self.assertEqual(fixture.calls, [])
