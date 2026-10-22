"""P17: stored running cannot become effective permission under a bad binding."""
import json
import unittest
from unittest.mock import patch

import test_project_connection as fixture
from hydra_sdlc.projection_read import read_projection


class ConnectionProjectionBindingTests(unittest.TestCase):
    setUp = fixture.ConnectionBindingTests.setUp
    text = fixture.ConnectionBindingTests.text
    write = fixture.ConnectionBindingTests.write
    load = fixture.ConnectionBindingTests.load
    state = fixture.ConnectionBindingTests.state

    def read_admission(self, cfg):
        with patch('hydra_sdlc.projection_read.observe_coordinator', return_value={'state': 'free'}):
            value = read_projection(cfg, binding_epoch='11111111-1111-4111-8111-111111111111',
                request_id='22222222-2222-4222-8222-222222222222', refresh=False)
        self.assertNotIn(str(self.path), json.dumps(value))
        return next(row for row in value['observations'] if row['resource']['kind'] == 'admission')

    def test_other_binding_is_unavailable_in_the_actual_read_producer(self):
        cfg = self.load()
        self.state(cfg)
        self.assertEqual(self.read_admission(cfg)['availability'], 'current')
        other = self.root / 'other.toml'
        other.write_text(self.path.read_text())
        other.chmod(0o600)
        self.state(cfg, path=other)
        observed = self.read_admission(cfg)
        self.assertEqual(observed['availability'], 'unavailable')
        self.assertIsNone(observed['value'])

    def test_missing_config_cannot_expose_running_permission_from_an_old_snapshot(self):
        cfg = self.load()
        self.state(cfg)
        self.assertEqual(self.read_admission(cfg)['availability'], 'current')
        self.path.unlink()
        observed = self.read_admission(cfg)
        self.assertEqual(observed['availability'], 'unavailable')
        self.assertIsNone(observed['value'])
