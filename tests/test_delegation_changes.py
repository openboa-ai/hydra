"""WR 7.1 private normalization. Parsing never establishes source authority."""
import copy
import hashlib
import json
import unittest

from hydra_sdlc.work_records import WorkRecordError, parse_delegation_change


CANARY = 'PRIVATE_INSTRUCTION_NOT_FOR_EXPORT'


def instruction(change=None, target='work'):
    return {
        'source_ref': {'kind': 'native_instruction', 'handle': CANARY, 'revision': 'opaque:r1'},
        'target': {'kind': target, 'repository_id': 101, 'issue_number': 7},
        'change': change if change is not None else {'kind': 'cancel'},
    }


def requirement(n=0):
    return {'repository_id': 101, 'path': 'docs/spec.md', 'revision': 'a' * 40,
            'selector': 'purpose-' + str(n)}


class DelegationChangeParsingTests(unittest.TestCase):
    def test_requirement_paths_and_selectors_reject_c1_controls(self):
        for field in ('path', 'selector'):
            for control in ('\x80', '\x85'):
                with self.subTest(field=field, control=repr(control)):
                    ref = requirement()
                    ref[field] = 'docs/' + control + 'spec.md'
                    self.rejected(instruction({'kind': 'amend', 'requirements': [ref]}))

    def test_maximum_escaped_astral_input_keeps_the_same_normalized_value(self):
        value = instruction({'kind': 'amend', 'requirements': [requirement(n) for n in range(50)]})
        value['source_ref'].update(handle='🚀' * 2048, revision='🚀' * 512)
        for n, ref in enumerate(value['change']['requirements']):
            ref.update(path='🚀' * 512, selector='🚀' * 157 + f'{n:03}')
        plain = json.dumps(value, ensure_ascii=False)
        escaped = json.dumps(value)
        self.assertLess(len(plain.encode()), 262144)
        self.assertGreater(len(escaped.encode()), 262144)
        self.assertLessEqual(len(escaped.encode()), 524288)
        parsed = parse_delegation_change(plain)
        try:
            encoded = parse_delegation_change(escaped)
        except WorkRecordError:
            self.fail('Equivalent accepted strings were rejected solely because JSON escaped them')
        self.assertEqual(encoded.value, value)
        self.assertEqual(encoded.digest, parsed.digest)

    def parse(self, value):
        return parse_delegation_change(json.dumps(value, ensure_ascii=False))

    def rejected(self, value):
        with self.assertRaises(WorkRecordError) as caught:
            self.parse(value)
        self.assertNotIn(CANARY, str(caught.exception))
        self.assertRegex(caught.exception.reason, r'^[a-z][a-z0-9_]+$')

    def test_each_change_and_target_preserves_exact_private_meaning(self):
        changes = [{'kind': 'cancel'}, {'kind': 'amend', 'requirements': None},
                   {'kind': 'amend', 'requirements': [requirement()]},
                   {'kind': 'withdraw', 'actions': ['execute_work']},
                   {'kind': 'withdraw', 'actions': ['prepare', 'create_work', 'execute_work']}]
        for target in ('work', 'goal'):
            for change in changes:
                with self.subTest(target=target, change=change):
                    value = instruction(change, target)
                    parsed = self.parse(value)
                    self.assertEqual(parsed.value, value)
                    self.assertEqual(parse_delegation_change(json.dumps(value).encode()).value, value)
                    self.assertEqual(value['source_ref']['handle'], CANARY)

    def test_closed_objects_numeric_identity_and_opaque_source_fields(self):
        for path, changes in [
            ((), [dict(instruction(), human=True), {}, [], None]),
            (('source_ref',), [{}, dict(instruction()['source_ref'], human=True),
                {'kind': 'user_summary', 'handle': CANARY, 'revision': 'r1'},
                {'kind': 'native_instruction', 'handle': '', 'revision': 'r1'},
                {'kind': 'native_instruction', 'handle': CANARY, 'revision': None}]),
            (('target',), [{}, dict(instruction()['target'], title='same title'),
                {'kind': 'task', 'repository_id': 101, 'issue_number': 7},
                {'kind': 'work', 'repository_id': True, 'issue_number': 7},
                {'kind': 'work', 'repository_id': 101, 'issue_number': 0},
                {'kind': 'work', 'repository_id': 101, 'issue_number': 2**53},
                {'kind': 'work', 'repository_id': '101', 'issue_number': 7}]),
            (('change',), [{}, [], None, {'kind': True}, {'kind': ['cancel']}]),
        ]:
            for changed in changes:
                with self.subTest(path=path, changed=changed):
                    value = instruction()
                    if path:
                        value[path[0]] = changed
                    else:
                        value = changed
                    self.rejected(value)

    def test_union_fields_actions_and_accepted_requirement_references(self):
        malformed = [
            {'kind': 'stop'}, {'kind': 'resume'}, {'kind': 'cancel', 'actions': []},
            {'kind': 'cancel', 'requirements': None}, {'kind': 'amend'},
            {'kind': 'amend', 'requirements': []},
            {'kind': 'amend', 'requirements': [requirement(), requirement()]},
            {'kind': 'amend', 'requirements': [dict(requirement(), accepted=True)]},
            {'kind': 'amend', 'requirements': [dict(requirement(), revision='main')]},
            {'kind': 'amend', 'requirements': [dict(requirement(), path='../spec.md')]},
            {'kind': 'amend', 'requirements': [dict(requirement(), selector='')]},
            {'kind': 'amend', 'requirements': [dict(requirement(), repository_id=False)]},
            {'kind': 'amend', 'requirements': None, 'actions': ['prepare']},
            {'kind': 'withdraw'}, {'kind': 'withdraw', 'actions': None},
            {'kind': 'withdraw', 'actions': []}, {'kind': 'withdraw', 'actions': 'execute_work'},
            {'kind': 'withdraw', 'actions': ['execute_work', 'execute_work']},
            {'kind': 'withdraw', 'actions': ['deploy']},
            {'kind': 'withdraw', 'actions': [[]]},
            {'kind': 'withdraw', 'actions': ['prepare'], 'requirements': None},
        ]
        for change in malformed:
            with self.subTest(change=change):
                self.rejected(instruction(change))

    def test_accepted_limits_are_inclusive_and_do_not_truncate(self):
        value = instruction({'kind': 'amend', 'requirements': [requirement(n) for n in range(50)]})
        value['source_ref'].update(handle='문' * 2048, revision='판' * 512)
        value['target'].update(repository_id=2**53 - 1, issue_number=2**53 - 1)
        for ref in value['change']['requirements']:
            ref.update(path='文' * 512, selector='節' * 157 + ref['selector'][-2:])
        # Make every otherwise maximum-size reference unique without shortening its path.
        for n, ref in enumerate(value['change']['requirements']):
            ref['selector'] = '節' * 157 + f'{n:03}'
        self.assertEqual(self.parse(value).value, value)
        for field, limit in [('handle', 2048), ('revision', 512)]:
            bad = instruction()
            bad['source_ref'][field] = 'x' * (limit + 1)
            with self.subTest(field=field):
                self.rejected(bad)
        self.rejected(instruction({'kind': 'amend', 'requirements': [requirement(n) for n in range(51)]}))

    def test_opaque_control_characters_and_surrogates_are_rejected(self):
        for field in ('handle', 'revision'):
            for control in ('\x00', '\t', '\n', '\x7f', '\x85', '\x9f', '\ud800'):
                with self.subTest(field=field, control=repr(control)):
                    value = instruction()
                    value['source_ref'][field] = CANARY + control
                    # ASCII JSON keeps an invalid Unicode escape in the raw input.
                    with self.assertRaises(WorkRecordError):
                        parse_delegation_change(json.dumps(value))

    def test_raw_duplicate_malformed_deep_and_oversized_json_never_normalizes(self):
        raw = json.dumps(instruction())
        malformed = [raw[:-1] + ',"change":{"kind":"cancel"}}',
            raw.replace('"revision": "opaque:r1"', '"revision":"r1","revision":"r2"'),
            '{"x":NaN}', '{"x":Infinity}', '{', b'\xff', '\ufeff' + raw,
            '[' * 1200 + '0' + ']' * 1200, ' ' * 524288 + raw,
            {'source_ref': CANARY}, None]
        for value in malformed:
            with self.subTest(kind=type(value).__name__, length=len(value) if value is not None else 0):
                with self.assertRaises(WorkRecordError) as caught:
                    parse_delegation_change(value)
                self.assertNotIn(CANARY, str(caught.exception))

    def test_digest_binds_whole_canonical_object_without_array_reordering(self):
        value = instruction({'kind': 'withdraw', 'actions': ['prepare', 'execute_work']})
        parsed = self.parse(value)
        canonical = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        self.assertEqual(parsed.document, canonical)
        self.assertEqual(parsed.digest, hashlib.sha256(canonical.encode()).hexdigest())
        self.assertEqual(parse_delegation_change(json.dumps(value, indent=4)).digest, parsed.digest)
        for mutation in ('revision', 'target', 'actions'):
            changed = copy.deepcopy(value)
            if mutation == 'revision':
                changed['source_ref']['revision'] = 'opaque:r2'
            elif mutation == 'target':
                changed['target']['issue_number'] = 8
            else:
                changed['change']['actions'].reverse()
            self.assertNotEqual(self.parse(changed).digest, parsed.digest)
        copy_value = parsed.value
        copy_value['source_ref']['revision'] = 'changed outside parsed input'
        self.assertEqual(parsed.value, value)
