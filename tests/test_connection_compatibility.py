"""Unsupported legacy controls reject a new profile before changing modes."""
import unittest
from unittest.mock import patch

import test_project_connection as fixture
from hydra_sdlc.control import control_result


class ConnectionCompatibilityTests(unittest.TestCase):
    setUp = fixture.ConnectionBindingTests.setUp
    text = fixture.ConnectionBindingTests.text
    write = fixture.ConnectionBindingTests.write
    load = fixture.ConnectionBindingTests.load
    state = fixture.ConnectionBindingTests.state

    def check_legacy(self, action):
        cfg = self.load()
        control = self.state(cfg)
        before = control.settings_path.read_bytes()
        with patch('hydra_sdlc.control.residual_workers', return_value=[]):
            with self.assertRaises(ValueError):
                control_result(cfg, action=action, repository=fixture.ALPHA if action != 'status' else None)
        self.assertEqual(control.settings_path.read_bytes(), before)

    def test_legacy_status_does_not_misreport_the_new_profile_default(self):
        self.check_legacy('status')

    def test_legacy_mutation_rejects_before_changing_any_store(self):
        self.check_legacy('pause')
