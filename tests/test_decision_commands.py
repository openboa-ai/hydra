"""P06/CP closed decision and continuation inputs; data is not authority."""
import copy
import unittest

from hydra_sdlc.control_commands import InvalidAdmissionCommand, command_input_schema, parse_command_v1
import test_decision_protocol as domain
import test_public_decisions as wire


def decision_command():
    check = domain.selection().proposal.source_check()
    return {'command_schema': 1, 'request_id': '44444444-4444-4444-8444-444444444444',
        'binding_epoch': None, 'action': 'workflow_step',
        'target': {'repository_id': 123, 'issue_number': 4},
        'expected': {'runtime_key': 'fixture-runtime', 'admission_revision': 0,
                     'source_checks': [check], 'assignment': None},
        'effect_key': f'decision:{wire.ATTEMPT}:1',
        'parameters': {'operation': 'decision_apply', 'proposal_ref': copy.deepcopy(check['resource']),
                       'source_attempt': wire.ATTEMPT, 'round': 1}}


def continue_command(progress=True):
    command = decision_command()
    command['expected']['source_checks'] = []
    command['effect_key'] = None
    command['parameters'] = {'operation': 'continue', 'reply_profile': 'native_handoff_v1',
        'progress': {'attempt_id': wire.ATTEMPT, 'head': wire.BASIS['head'],
                     'contract_revision': wire.BASIS['contract_revision'], 'phase': 'checkpoint'} if progress else None}
    return command


class DecisionCommandInputTests(unittest.TestCase):
    def test_decision_apply_keeps_the_exact_public_key_and_source_pin(self):
        command = decision_command()
        self.assertEqual(parse_command_v1(command), command)

    def test_continue_keeps_the_exact_current_progress_pin(self):
        command = continue_command()
        self.assertEqual(parse_command_v1(command), command)

    def test_first_continue_can_explicitly_request_no_progress(self):
        command = continue_command(False)
        self.assertEqual(parse_command_v1(command), command)

    def test_source_change_detection_is_required_and_not_caller_authority(self):
        command = decision_command()
        command['expected']['source_checks'][0].update(revision=None, actionable_digest='d' * 64)
        self.assertEqual(parse_command_v1(command), command)
        changes = [lambda c: c['expected'].update(source_checks=[]),
                   lambda c: c['expected']['source_checks'].append(copy.deepcopy(c['expected']['source_checks'][0])),
                   lambda c: c['expected']['source_checks'][0].update(revision=None, actionable_digest=None),
                   lambda c: c['expected']['source_checks'][0].update(authorized=True),
                   lambda c: c['parameters'].update(authorized=True),
                   lambda c: c['parameters'].update(resume_attempt=wire.RESUME),
                   lambda c: c['parameters']['proposal_ref'].update(id='another-proposal')]
        for change in changes:
            invalid = decision_command()
            change(invalid)
            with self.subTest(change=change), self.assertRaises(InvalidAdmissionCommand):
                parse_command_v1(invalid)

    def test_continue_does_not_accept_phase_or_effect_overrides(self):
        for changes in ({'phase': 'implementation'}, {'resume_attempt': wire.RESUME},
                        {'effect_allowlist': ['merge']}, {'reply_profile': 'private'}):
            command = continue_command()
            command['parameters'].update(changes)
            with self.subTest(changes=changes), self.assertRaises(InvalidAdmissionCommand):
                parse_command_v1(command)
        for command in (continue_command(), decision_command()):
            command['expected']['assignment'] = {'attempt_id': wire.ATTEMPT}
            with self.assertRaises(InvalidAdmissionCommand):
                parse_command_v1(command)

    def test_decision_key_counts_and_progress_are_closed_and_typed(self):
        for field, invalid in (('source_attempt', 'bad'), ('round', True), ('round', 0), ('round', 1.0)):
            command = decision_command()
            command['parameters'][field] = invalid
            with self.subTest(field=field, invalid=invalid), self.assertRaises(InvalidAdmissionCommand):
                parse_command_v1(command)
        command = decision_command()
        command['effect_key'] = 'decision:another:1'
        with self.assertRaises(InvalidAdmissionCommand):
            parse_command_v1(command)
        for field, invalid in (('attempt_id', 'bad'), ('head', 'A' * 40),
                               ('contract_revision', 'b' * 39), ('phase', ''), ('extra', 'field')):
            command = continue_command()
            command['parameters']['progress'][field] = invalid
            with self.subTest(field=field), self.assertRaises(InvalidAdmissionCommand):
                parse_command_v1(command)

    def test_other_future_operations_stay_opaque(self):
        command = decision_command()
        command['parameters'] = {'operation': 'future', 'arbitrary': ['data']}
        parsed = parse_command_v1(command)
        self.assertIsNone(parsed['parameters'])
        self.assertIsNone(parsed['expected'])

    def test_wire_schema_describes_both_profiles_without_granting_them(self):
        operations = {variant['properties']['parameters']['properties'].get('operation', {}).get('const')
                      for variant in command_input_schema()['oneOf']}
        self.assertTrue({'decision_apply', 'continue'} <= operations)
