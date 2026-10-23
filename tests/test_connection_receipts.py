"""Version-aware project modes must survive actual admission read-back."""
import json
import unittest

import test_connection_review as fixture
from hydra_sdlc.control import control_from_config
from hydra_sdlc.control_commands import AdmissionCallContext, execute_admission_command, _runtime_key
from hydra_sdlc.runtime_identity import capture_runtime_identity


ALPHA, BETA = fixture.ALPHA, fixture.BETA


class ConnectionReceiptTests(unittest.TestCase):
    setUp = fixture.ConnectionReviewTests.setUp
    text = fixture.ConnectionReviewTests.text
    write = fixture.ConnectionReviewTests.write
    load = fixture.ConnectionReviewTests.load
    state = fixture.ConnectionReviewTests.state
    connected = fixture.ConnectionReviewTests.connected

    def receipt(self, cfg, control, mode):
        command = {'command_schema': 1, 'request_id': '33333333-3333-4333-8333-333333333333',
            'binding_epoch': None, 'action': 'admission_set',
            'target': {'kind': 'repository', 'repository_id': 124},
            'expected': {'runtime_key': _runtime_key(capture_runtime_identity(cfg, control)),
                'admission_revision': control.snapshot()['revision'], 'source_checks': [], 'assignment': None},
            'effect_key': None, 'parameters': {'mode': mode}}
        class Source:
            def repository(self, repo):
                return {'id': 123 if repo == ALPHA else 124, 'full_name': repo, 'default_branch': 'main'}
        result = execute_admission_command(self.path, command,
            context_provider=lambda: AdmissionCallContext('native', None,
                frozenset({123, 124}), frozenset({'admission_set'})), github=Source())
        self.assertEqual(result['request']['outcome'], 'applied', result)
        self.assertNotIn(str(self.path), json.dumps(result))
        return result

    def test_implicit_stopped_pause_is_unchanged_and_reports_stronger_mode(self):
        cfg = self.connected()
        control = self.state(cfg, projects={ALPHA: 'running'})
        before = control.settings_path.read_bytes()
        reply = self.receipt(cfg, control, 'paused')
        self.assertEqual(control.settings_path.read_bytes(), before)
        self.assertNotIn(BETA, control.snapshot()['projects'])
        self.assertEqual(reply['observations'][0]['value']['default_project_mode'], 'stopped')
        self.assertEqual(reply['request']['reason'], 'stronger_mode_retained')

    def test_explicit_stopped_pause_keeps_the_same_stronger_receipt(self):
        cfg = self.connected()
        control = self.state(cfg, projects={ALPHA: 'running', BETA: 'stopped'})
        before = control.settings_path.read_bytes()
        reply = self.receipt(cfg, control, 'paused')
        self.assertEqual(control.settings_path.read_bytes(), before)
        self.assertEqual(reply['request']['reason'], 'stronger_mode_retained')

    def test_legacy_implicit_running_resume_retains_legacy_receipt(self):
        cfg = self.load(self.text(profile=False))
        control = control_from_config(cfg)
        control.set_mode('start')
        before = control.settings_path.read_bytes()
        reply = self.receipt(cfg, control, 'running')
        self.assertEqual(control.settings_path.read_bytes(), before)
        self.assertNotIn('default_project_mode', reply['observations'][0]['value'])
        self.assertEqual(reply['request']['reason'], 'already_satisfied')

    def test_explicit_resume_from_the_stopped_default_records_running(self):
        cfg = self.connected()
        control = self.state(cfg, projects={ALPHA: 'running'})
        reply = self.receipt(cfg, control, 'running')
        self.assertEqual(control.snapshot()['projects'][BETA], 'running')
        self.assertEqual(control.snapshot()['revision'], 2)
        self.assertIsNone(reply['request']['reason'])
