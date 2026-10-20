import copy
import importlib.util
import json
import unittest

from hydra_sdlc.runner import intake_digest


REF = {'repository_id': 101, 'path': 'docs/design/spec.md',
       'revision': '1' * 40, 'selector': 'R-EMPTY-1'}
ISSUE = {'number': 11, 'title': '빈 입력', 'body': ' 줄\n',
         'url': 'https://api.github.com/repos/example/alpha/issues/11'}
SOURCE = 'e48e7230725e3c4e496be9af4c3c3dc4ce2e17c1fcf678973461f7af8ee47528'
AUTHOR = {'id': 21, 'login': 'openboa'}
ATTEMPT = '11111111-1111-4111-8111-111111111111'


def binding(**changes):
    value = {'repository_id': 101, 'issue_number': 11, 'source_digest': SOURCE,
             'kind': 'work', 'create_key': None, 'delegated_goal': None,
             'outcome': 'empty-input', 'requirements': [copy.deepcopy(REF)],
             'spec': {'path': 'docs/design/spec.md', 'revision': '1' * 40},
             'input_contract': {'kind': 'adopted', 'clauses': []},
             'delegation_ref': None}
    value.update(changes)
    return value


def marker(value, name='hydra-work:v2'):
    return '<!-- ' + name + ' ' + json.dumps(value, ensure_ascii=False) + ' -->'


def comment(identifier, body, **changes):
    value = {'id': identifier, 'user': copy.deepcopy(AUTHOR), 'body': body,
             'created_at': '2026-01-01T00:00:00Z', 'updated_at': '2026-01-01T00:00:00Z',
             'issue_url': 'https://api.github.com/repos/example/alpha/issues/11'}
    value.update(changes)
    return value


class WorkRecordTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('hydra_sdlc.work_records'),
                             'The reviewed v2 binding read boundary is not implemented')
        from hydra_sdlc import work_records
        self.wr = work_records

    def parse(self, value=None):
        return self.wr.parse_binding(marker(binding() if value is None else value),
                                     spec_directory='docs')

    def select(self, rows, **changes):
        args = dict(repository_id=101, issue=ISSUE, author=AUTHOR,
                    coverage='complete', selected_comment_id=71,
                    selected_digest=self.parse().digest, spec_directory='docs')
        args.update(changes)
        return self.wr.select_binding(rows, **args)

    def assert_reason(self, reason, call):
        with self.assertRaises(self.wr.WorkRecordError) as caught:
            call()
        self.assertEqual(caught.exception.reason, reason)
        self.assertEqual(str(caught.exception), reason)

    def test_public_read_boundary_preserves_valid_binding_and_original_issue(self):
        original = copy.deepcopy(ISSUE)
        parsed = self.parse()
        self.assertEqual(parsed.value, binding())
        self.assertEqual(parsed.digest, '296c78bd4da775b43193c7f23fab627ab12b19f43c070294e6687770996c27a2')
        result = self.select([comment(71, marker(binding()))])
        self.assertEqual(result.binding.value, binding())
        self.assertEqual(result.comment_id, 71)
        self.assertEqual(ISSUE, original)
        self.assertFalse(hasattr(result, 'authority'))

    def test_source_digest_has_fixed_legacy_null_space_unicode_vectors(self):
        vectors = [({}, '9df181cb210a7582a3fac2b1f134f5519bd823a9ad89ff80ad4d4c2a3053af55'),
                   ({'title': '', 'body': None}, '00211f56359be94870ccf1aead41cdbbae7d758d7a4a452ebfe72631f179d518'),
                   ({'title': '', 'body': ''}, 'b534f10aad8c935f3ee750d6051594fcb1e2ea42adb3c5cacf85e47ea1841e8d'),
                   (ISSUE, SOURCE)]
        for value, expected in vectors:
            with self.subTest(value=value):
                self.assertEqual(self.wr.source_digest(value), expected)
                self.assertEqual(intake_digest(value), expected)
        self.assertNotEqual(self.wr.source_digest(ISSUE),
                            self.wr.source_digest({**ISSUE, 'body': '줄\n'}))

    def test_binding_is_immutable_and_top_requirement_order_is_preserved(self):
        a = self.parse()
        changed = a.value
        changed['requirements'][0]['path'] = 'other'
        self.assertEqual(a.value, binding())
        second = {**REF, 'selector': 'R-EMPTY-2'}
        b = self.parse(binding(requirements=[REF, second]))
        c = self.parse(binding(requirements=[second, REF]))
        self.assertNotEqual(b.digest, c.digest)
        self.assertNotEqual(a.digest, SOURCE)

    def test_anchor_closed_schema_version_and_bytes_do_not_mutate_progress(self):
        value = {'repository_id': 101, 'issue_number': 11, 'attempt_id': ATTEMPT,
                 'binding_comment_id': 71, 'binding_digest': self.parse().digest,
                 'source_digest': SOURCE, 'contract_revision': '2' * 40}
        raw = marker(value, 'hydra-attempt-binding:v1')
        self.assertEqual(self.wr.parse_anchor(raw), value)
        for field, changed in [('binding_comment_id', True), ('attempt_id', ATTEMPT.upper()),
                               ('contract_revision', '2' * 39), ('extra', 0)]:
            if field == 'attempt_id':
                changed = 'ABCDEFAB-CDEF-4ABC-8DEF-ABCDEFABCDEF'
            self.assert_reason('invalid_schema', lambda: self.wr.parse_anchor(
                marker({**value, field: changed}, 'hydra-attempt-binding:v1')))
        self.assert_reason('unsupported_version', lambda: self.wr.parse_anchor(
            marker(value, 'hydra-attempt-binding:v2')))
        excessive = raw.replace(' -->', ' ' * 2048 + ' -->')
        self.assert_reason('marker_limit', lambda: self.wr.parse_anchor(excessive))

    def test_unknown_version_keys_and_duplicate_json_keys_are_not_reinterpreted(self):
        self.assert_reason('unsupported_version', lambda: self.wr.parse_binding(
            marker(binding(), 'hydra-work:v1'), spec_directory='docs'))
        for value in [binding(priority=1), binding(spec={'path': 'docs/design/spec.md', 'revision': '1' * 40, 'extra': 0}),
                      binding(requirements=[{**REF, 'extra': 0}]),
                      binding(input_contract={'kind': 'adopted', 'clauses': [], 'extra': 0})]:
            self.assert_reason('invalid_schema', lambda: self.parse(value))
        text = marker(binding()).replace('"repository_id": 101', '"repository_id":101,"repository_id":101', 1)
        self.assert_reason('invalid_json', lambda: self.wr.parse_binding(text, spec_directory='docs'))

    def test_ids_sha_uuid_paths_and_limits_are_strict(self):
        for field, value in [('repository_id', True), ('issue_number', 0),
                             ('repository_id', 9007199254740992), ('source_digest', 'A' * 64),
                             ('create_key', '11111111-1111-1111-8111-111111111111'),
                             ('outcome', 'Has space'), ('requirements', [REF] * 101)]:
            with self.subTest(field=field, value=value):
                self.assert_reason('invalid_schema', lambda: self.parse(binding(**{field: value})))
        for path in ['../spec.md', '/tmp/spec.md', 'docs//spec.md', 'docs/.git/spec.md',
                     'docs/./spec.md', 'docs/a\\b/spec.md', 'docs/x\x7f/spec.md', '~user/spec.md']:
            self.assert_reason('invalid_schema', lambda: self.parse(binding(requirements=[{**REF, 'path': path}])))
        self.assert_reason('invalid_schema', lambda: self.parse(binding(spec={'path': 'elsewhere/spec.md', 'revision': '1' * 40})))
        self.assert_reason('invalid_schema', lambda: self.parse(binding(requirements=[REF, REF])))

    def test_marker_byte_boundary_and_ambiguous_markers(self):
        raw = marker(binding())
        exact = raw.replace(' -->', ' ' * (32768 - len(raw.encode())) + ' -->')
        self.assertEqual(len(exact.encode()), 32768)
        self.assertEqual(self.wr.parse_binding(exact, spec_directory='docs').value, binding())
        self.assert_reason('marker_limit', lambda: self.wr.parse_binding(exact.replace(' -->', '  -->', 1), spec_directory='docs'))
        self.assert_reason('invalid_marker', lambda: self.wr.parse_binding(raw + raw, spec_directory='docs'))
        self.assert_reason('invalid_json', lambda: self.wr.parse_binding(raw.replace('"kind": "work"', '"kind": NaN'), spec_directory='docs'))

    def test_delegated_goal_is_fixed_and_self_delegation_is_invalid(self):
        goal = {'repository_id': 101, 'issue_number': 10, 'source_digest': 'b' * 64}
        self.assertEqual(self.parse(binding(delegated_goal=goal)).value['delegated_goal'], goal)
        self.assert_reason('invalid_schema', lambda: self.parse(binding(delegated_goal={**goal, 'issue_number': 11})))
        self.assert_reason('invalid_schema', lambda: self.parse(binding(delegated_goal={**goal, 'parent': 4})))

    def test_goals_and_preparation_preserve_missing_execution_inputs(self):
        for value in [binding(kind='goal'), binding(spec=None, input_contract=None, requirements=[]),
                      binding(spec={'path': 'docs/design/spec.md', 'revision': None}, input_contract=None)]:
            self.assertEqual(self.parse(value).value, value)
        self.assertEqual(self.parse().value['input_contract']['clauses'], [])
        self.assertIsNone(self.parse(binding(input_contract=None)).value['input_contract'])

    def test_adopted_input_clauses_require_canonical_order_and_no_self_producer(self):
        clause = {'producer': {'repository_id': 101, 'issue_number': 12},
                  'requirements': [REF], 'required_stage': 'post_merge_verified', 'basis': REF}
        value = binding(input_contract={'kind': 'adopted', 'clauses': [clause]})
        self.assertEqual(self.parse(value).value, value)
        for clauses in [[clause, clause], [{**clause, 'producer': {'repository_id': 101, 'issue_number': 11}}],
                        [{**clause, 'required_stage': 'closed'}], [{**clause, 'requirements': []}]]:
            self.assert_reason('invalid_schema', lambda: self.parse(binding(input_contract={'kind': 'adopted', 'clauses': clauses})))
        later = {**clause, 'required_stage': 'observed'}
        # Canonical JSON sorts observed before post_merge_verified for these otherwise equal clauses.
        self.parse(binding(input_contract={'kind': 'adopted', 'clauses': [later, clause]}))
        self.assert_reason('invalid_schema', lambda: self.parse(binding(input_contract={'kind': 'adopted', 'clauses': [clause, later]})))

    def test_reference_is_kept_as_exact_reference_without_inventing_a_payload(self):
        value = binding(input_contract={'kind': 'reference', 'ref': REF})
        self.assertEqual(self.parse(value).value['input_contract'], value['input_contract'])
        self.assert_reason('invalid_schema', lambda: self.parse(binding(input_contract={'kind': 'reference', 'ref': REF, 'clauses': []})))

    def test_foreign_copied_marker_never_replaces_explicit_owned_selection(self):
        for actor in [{'id': 22, 'login': 'openboa'}, {'id': 21, 'login': 'external'}]:
            self.assert_reason('unbound', lambda: self.select([comment(71, marker(binding()), user=actor)]))
        rows = [comment(70, marker(binding()), user={'id': 33, 'login': 'external'}),
                comment(71, marker(binding()))]
        self.assertEqual(self.select(rows).comment_id, 71)

    def test_historical_binding_requires_exact_id_digest_not_latest(self):
        old = self.parse()
        newer = binding(outcome='different-result')
        result = self.select([comment(71, marker(binding())), comment(72, marker(newer))])
        self.assertEqual(result.binding.digest, old.digest)
        self.assert_reason('binding_changed', lambda: self.select([comment(71, marker(newer))]))
        self.assert_reason('unknown', lambda: self.select([comment(72, marker(newer))]))
        self.assert_reason('conflict', lambda: self.select([comment(71, marker(binding())), comment(72, marker(binding()))]))

    def test_edited_deleted_partial_and_source_drift_do_not_change_selection(self):
        own = comment(71, marker(binding()))
        for changes in [{'updated_at': '2026-01-01T00:00:01Z'}, {'created_at': None},
                        {'updated_at': 'not-a-time'}]:
            self.assert_reason('edited_or_unknown', lambda: self.select([{**own, **changes}]))
        for coverage in ['partial', 'unavailable', None]:
            self.assert_reason('unknown', lambda: self.select([own], coverage=coverage))
        self.assert_reason('source_changed', lambda: self.select([own], issue={**ISSUE, 'body': 'changed'}))
        self.assert_reason('identity_mismatch', lambda: self.select([own], repository_id=102))
        self.assert_reason('identity_mismatch', lambda: self.select([{**own, 'issue_url': 'https://api.github.com/repos/example/alpha/issues/12'}]))

    def test_restart_uses_attempt_anchor_and_exact_binding_without_cache(self):
        parsed = self.parse()
        anchor = {'repository_id': 101, 'issue_number': 11, 'attempt_id': ATTEMPT,
                  'binding_comment_id': 71, 'binding_digest': parsed.digest,
                  'source_digest': SOURCE, 'contract_revision': '2' * 40}
        progress = {'repository_id': 101, 'issue_number': 11, 'attempt_id': ATTEMPT,
                    'intake_digest': SOURCE, 'contract_revision': '2' * 40}
        rows = [comment(71, marker(binding())), comment(72, marker(binding(outcome='newer'))),
                comment(73, marker(anchor, 'hydra-attempt-binding:v1'))]
        args = dict(repository_id=101, issue=ISSUE, author=AUTHOR, progress=progress,
                    coverage='complete', spec_directory='docs')
        first = self.wr.recover_binding(copy.deepcopy(rows), **args)
        second = self.wr.recover_binding(copy.deepcopy(rows), **copy.deepcopy(args))
        self.assertEqual(first, second)
        self.assertEqual(first.comment_id, 71)
        self.assert_reason('conflict', lambda: self.wr.recover_binding(rows + [comment(74, marker(anchor, 'hydra-attempt-binding:v1'))], **args))
        self.assert_reason('unknown', lambda: self.wr.recover_binding(rows[:2], **args))
        edited = [*rows[:2], {**rows[2], 'updated_at': '2026-01-02T00:00:00Z'}]
        self.assert_reason('edited_or_unknown', lambda: self.wr.recover_binding(edited, **args))
        self.assert_reason('anchor_mismatch', lambda: self.wr.recover_binding(rows, **{**args, 'progress': {**progress, 'contract_revision': '3' * 40}}))


if __name__ == '__main__':
    unittest.main()
