"""Control-plane wire invariants; source/reducer/native qualification is separate."""
import copy
import json
import unittest

from hydra_sdlc import projection as p


AT = '2026-10-21T00:00:00Z'
EPOCH = '00000000-0000-4000-8000-000000000001'
REQUEST = '00000000-0000-4000-8000-000000000002'
CANARY = 'SYNTHETIC_PRIVATE_NATIVE_TEXT'


def runtime():
    return {'identity_schema': 1, 'package': 'openboa-hydra-sdlc', 'version': '0.2.1',
        'code_digest': '0' * 64, 'code_digest_scope': 'package_sources_at_startup',
        'config_digest': '1' * 64, 'control_binding_digest': '2' * 64, 'identity_reason': None}


def observed(kind='admission', *, key='hydra:host:admission', value=None):
    if value is None:
        value = {'revision': 7, 'global_mode': 'paused', 'project_overrides': {'example/alpha': 'running'},
                 'gate_reason': 'host_paused'}
    return {'key': key, 'resource': {'source': 'hydra' if kind == 'admission' else 'github',
            'kind': kind, 'id': 'host' if kind == 'admission' else '101'},
        'revision': {'kind': 'monotonic', 'value': '7'} if kind == 'admission' else None,
        'observed_at': AT, 'last_attempt_at': AT, 'availability': 'current',
        'coverage': {'state': 'complete', 'scope': 'resource:host', 'returned_count': 1,
                     'total_count': 1, 'next_cursor': None, 'reason': None},
        'reason': None, 'value': value}


def minimal():
    return {'schema_version': 3, 'runtime': runtime(), 'binding_epoch': EPOCH, 'request_id': REQUEST,
        'assembled_at': AT, 'observations': [observed()], 'projects': [], 'work': [], 'relations': [],
        'page': {'state': 'partial', 'scope': 'host;overview', 'returned_count': 0,
                 'total_count': None, 'next_cursor': None, 'reason': 'not_requested'},
        'capabilities': [], 'retry_hints': [], 'request': None}


class ProjectionPrimitiveTests(unittest.TestCase):
    def test_applied_workflow_and_cleanup_require_receipts_in_both_wire_profiles(self):
        from hydra_sdlc.control_commands import _observation, _reply
        command = {'request_id': REQUEST, 'action': 'admission_set',
                   'target': {'kind': 'repository', 'repository_id': 101}}
        observation = _observation(command, runtime(), {'revision': 7, 'global_mode': 'paused',
            'projects': {'example/alpha': 'running'}}, 'example/alpha', 'readback', AT)
        base = _reply(command, runtime(), EPOCH, 'applied', None, observation=observation)
        targets = [('workflow_step', {'repository_id': 101, 'issue_number': 7}),
                   ('cleanup', {'kind': 'owned_resource', 'repository_id': 101, 'issue_number': 7,
                    'source_attempt': EPOCH, 'resource': {'source': 'resource_provider', 'kind': 'workspace', 'id': 'fixture'}})]
        for action, target in targets:
            for profile in ('standard', 'projection'):
                with self.subTest(action=action, profile=profile):
                    result = dict(base['request'], action=action, target=target, receipt=None,
                                  effect_refs=[], observed_refs=[], outcome='waiting')
                    value = copy.deepcopy(base) if profile == 'standard' else minimal()
                    value['request'] = result
                    consume = p.standard_reply if profile == 'standard' else p.encode
                    consume(value)
                    result['outcome'] = 'applied'
                    with self.assertRaises(p.ProjectionError):
                        consume(value)

    def test_retry_hints_keep_provider_zero_distinct_from_fallback_and_unknown(self):
        value = minimal()
        source = value['observations'][0]
        source['reason'] = 'provider_wait'
        value['retry_hints'] = [{'observation_key': source['key'], 'scope': 'connection:example',
                                'after_seconds': 0, 'basis': 'provider'}]
        decoded = p.read_json(p.encode(value))
        self.assertEqual(decoded['retry_hints'][0]['after_seconds'], 0)
        self.assertEqual(decoded['retry_hints'][0]['basis'], 'provider')
        value['retry_hints'][0].update(after_seconds=60, basis='fallback')
        self.assertEqual(p.read_json(p.encode(value))['retry_hints'][0]['basis'], 'fallback')
        value['retry_hints'] = []
        self.assertEqual(p.read_json(p.encode(value))['retry_hints'], [])

    def test_retry_hints_require_same_frame_observation_and_actual_limit_or_failure(self):
        value = minimal()
        hint = {'observation_key': value['observations'][0]['key'], 'scope': 'connection:example',
                'after_seconds': 300, 'basis': 'provider'}
        value['retry_hints'] = [hint]
        with self.assertRaises(p.ProjectionError):
            p.encode(value)
        value['observations'][0]['reason'] = 'rate_limited'
        p.encode(value)
        for changed in ({'observation_key': 'foreign'}, {'basis': 'guess'}, {'after_seconds': True},
                        {'after_seconds': -1}, {'after_seconds': 2 ** 53}, {'scope': ''}):
            with self.subTest(changed=changed), self.assertRaises(p.ProjectionError):
                bad = copy.deepcopy(value)
                bad['retry_hints'][0].update(changed)
                p.encode(bad)
        value['retry_hints'].append(copy.deepcopy(hint))
        with self.assertRaises(p.ProjectionError):
            p.encode(value)

    def test_retry_hints_are_required_only_in_v3_and_never_added_to_command_reply(self):
        value = minimal()
        del value['retry_hints']
        with self.assertRaises(p.ProjectionError):
            p.encode(value)
        from hydra_sdlc.control_commands import _observation, _reply
        command = {'request_id': REQUEST, 'action': 'admission_set',
                   'target': {'kind': 'repository', 'repository_id': 101}}
        source = _observation(command, runtime(), {'revision': 7, 'global_mode': 'paused',
            'projects': {'example/alpha': 'running'}}, 'example/alpha', 'readback', AT)
        response = _reply(command, runtime(), EPOCH, 'applied', None, observation=source)
        p.standard_reply(response)
        response['retry_hints'] = []
        with self.assertRaises(p.ProjectionError):
            p.standard_reply(response)

    def test_unavailable_values_do_not_bypass_closed_source_kinds(self):
        value = minimal()
        source = value['observations'][0]
        source.update(availability='unsupported', value=None, observed_at=None,
                      reason='source_unsupported', revision=None)
        source['coverage'].update(state='unavailable', returned_count=0, total_count=None,
                                  next_cursor=None, reason='source_unsupported')
        source['resource']['kind'] = 'native_context'
        with self.assertRaises(p.ProjectionError):
            p.encode(value)

    def test_monotonic_revisions_preserve_decimal_strings_beyond_json_integer_range(self):
        value = minimal()
        counter = '100000000000000000000000000000000000001'
        value['observations'][0]['revision']['value'] = counter
        try:
            result = p.read_json(p.encode(value))
        except p.ProjectionError:
            result = None
        self.assertIsNotNone(result, 'A string logical counter was narrowed to a JSON number')
        self.assertEqual(result['observations'][0]['revision']['value'], counter)
        for invalid in ('01', '-1', '+1', '1.0', '1e2'):
            with self.subTest(invalid=invalid), self.assertRaises(p.ProjectionError):
                p.revision({'kind': 'monotonic', 'value': invalid})

    def test_goal_refs_preserve_accepted_scope_digest_and_issue_parent_identity(self):
        goal = {'repository_id': 101, 'issue_number': 1, 'source_digest': 'c' * 64}
        p.goal_ref(goal)
        p.parent_ref(goal)
        p.parent_ref({'repository_id': 101, 'issue_number': 1})
        with self.assertRaises(p.ProjectionError):
            p.goal_ref({'repository_id': 101, 'issue_number': 1})
        for changed in (None, 'c' * 63, 'C' * 64, True):
            with self.subTest(changed=changed), self.assertRaises(p.ProjectionError):
                p.goal_ref({**goal, 'source_digest': changed})
        other = {**goal, 'source_digest': 'd' * 64}
        self.assertNotEqual(p.canonical(goal), p.canonical(other))

    def test_unread_description_retains_unknown_truncation_and_known_empty_is_distinct(self):
        value = {'number': 1, 'title': 'Useful request', 'state': 'open',
            'url': 'https://github.com/example/alpha/issues/1', 'work_kind': None,
            'parent_refs': None, 'requirement_refs': None, 'description_excerpt': None,
            'description_truncated': None}
        p.source_value('issue', value)
        self.assertIsNone(value['description_truncated'])
        empty = {**value, 'description_excerpt': '', 'description_truncated': False}
        p.source_value('issue', empty)
        self.assertNotEqual(value, empty)

    def test_actual_encoder_preserves_known_admission_and_partial_scope(self):
        value = minimal()
        decoded = p.read_json(p.encode(value))
        self.assertEqual(decoded, value)
        self.assertEqual(decoded['observations'][0]['value']['global_mode'], 'paused')
        self.assertEqual(decoded['page']['state'], 'partial')

    def test_every_nullable_key_is_required_and_unknown_fields_are_rejected(self):
        for path, key in [((), 'request'), (('runtime',), 'identity_reason'),
                          (('observations', 0), 'revision'), (('page',), 'total_count')]:
            for action in ('delete', 'extra'):
                with self.subTest(path=path, key=key, action=action):
                    value = minimal()
                    target = value
                    for part in path:
                        target = target[part]
                    if action == 'delete':
                        del target[key]
                    else:
                        target['unexpected'] = None
                    with self.assertRaises(p.ProjectionError):
                        p.encode(value)

    def test_safe_integers_never_accept_booleans_fractions_or_overflow(self):
        for number in (True, False, -1, 1.0, 2 ** 53):
            with self.subTest(number=number):
                value = minimal()
                value['observations'][0]['value']['revision'] = number
                with self.assertRaises(p.ProjectionError):
                    p.encode(value)

    def test_dates_are_real_utc_dates(self):
        for date in ('2026-02-30T00:00:00Z', '2026-10-21', '2026-10-21T00:00:00+09:00',
                     '2026-10-21T25:00:00Z', '2026-10-21T00:00:00'):
            with self.subTest(date=date):
                value = minimal()
                value['assembled_at'] = date
                with self.assertRaises(p.ProjectionError):
                    p.encode(value)
        p.timestamp('2026-10-21T00:00:00.123456789Z')

    def test_json_rejects_duplicate_keys_nonfinite_bytes_and_excess_input(self):
        for data in (b'{"a":1,"a":2}', b'{"x":{"a":1,"a":2}}', b'{"x":NaN}',
                     b'{"x":Infinity}', b'\xff', b' ' * (p.MAX_BYTES + 1)):
            with self.subTest(prefix=data[:30]):
                with self.assertRaises(p.ProjectionError):
                    p.read_json(data)

    def test_code_point_limits_preserve_astral_text_without_utf16_shortcuts(self):
        value = {'number': 1, 'title': '😀' * 512, 'state': 'open',
            'url': 'https://github.com/example/alpha/issues/1', 'work_kind': None,
            'parent_refs': None, 'requirement_refs': None, 'description_excerpt': '',
            'description_truncated': False}
        p.source_value('issue', value)
        value['title'] += '😀'
        with self.assertRaises(p.ProjectionError):
            p.source_value('issue', value)
        for text in ('\ud800', '\udfff'):
            with self.assertRaises(p.ProjectionError):
                p.text(text)

    def test_unknown_is_not_empty_zero_or_ended(self):
        data = p.unknown('execution_unqualified')
        self.assertIsNone(data['value'])
        self.assertEqual(data['evidence'], [])
        self.assertEqual(data['reason'], 'execution_unqualified')
        p.fact(data, p.execution, {})
        with self.assertRaises(p.ProjectionError):
            p.fact({'value': {'state': 'ended', 'active_count': 0}, 'evidence': [], 'reason': None},
                   p.execution, {})

    def test_fact_requires_same_frame_revision_current_and_complete_evidence(self):
        observation = observed()
        fact = p.known('paused', [observation])
        p.fact(fact, lambda v: self.assertEqual(v, 'paused'), {observation['key']: observation})
        cases = []
        for name in ('missing', 'wrong_revision', 'stale', 'partial'):
            index = {observation['key']: copy.deepcopy(observation)}
            if name == 'missing':
                index.clear()
            elif name == 'wrong_revision':
                index[observation['key']]['revision']['value'] = '8'
            elif name == 'stale':
                index[observation['key']]['availability'] = 'stale'
            else:
                index[observation['key']]['coverage'].update(state='partial', reason='source_partial')
            cases.append((name, index))
        for name, index in cases:
            with self.subTest(name=name), self.assertRaises(p.ProjectionError):
                p.fact(fact, lambda v: None, index)

    def test_null_revision_can_be_observed_without_inventing_a_digest(self):
        observation = observed('repository', key='github:101:repository', value={
            'numeric_id': 101, 'full_name': 'example/alpha', 'url': 'https://github.com/example/alpha',
            'contract_ref': None})
        p.observation(observation)
        value = p.known('observed', [observation])
        self.assertIsNone(value['evidence'][0]['revision'])
        p.fact(value, lambda v: None, {observation['key']: observation})

    def test_source_values_are_closed_and_missing_lists_stay_null(self):
        value = {'number': 1, 'url': 'https://github.com/example/alpha/pull/1', 'state': 'open',
            'head': 'a' * 40, 'base': 'b' * 40, 'merge_commit': None,
            'required_check_refs': None, 'review_refs': None}
        p.source_value('pull_request', value)
        self.assertIsNone(value['review_refs'])
        with self.assertRaises(p.ProjectionError):
            p.source_value('pull_request', {**value, 'body': CANARY})

    def test_unavailable_and_unsupported_have_no_success_value_or_time(self):
        for availability in ('unavailable', 'unsupported'):
            item = observed()
            item.update(availability=availability, value=None, observed_at=None, reason='not_requested')
            item['coverage'].update(state='unavailable', returned_count=0, total_count=None, reason='not_requested')
            p.observation(item)
            item['value'] = {'revision': 0}
            with self.assertRaises(p.ProjectionError):
                p.observation(item)

    def test_native_metadata_has_no_question_execution_or_private_payload(self):
        task = {'source': 'codex', 'kind': 'native_task', 'id': 'fixture:host:task:one'}
        item = observed('native_task_metadata', key='codex:one:metadata',
                        value={'task_ref': task, 'reported_status': 'active'})
        item['resource'].update(source='codex', id=task['id'])
        p.observation(item)
        self.assertEqual(item['value']['reported_status'], 'active')
        state = p.unknown_decision()
        p.decision(state, {item['key']: item})
        self.assertTrue(all(v['value'] is None and v['reason'] == 'decision_provenance_unverified'
                            for v in state.values()))
        for key in ('title', 'cwd', 'preview', 'body'):
            with self.subTest(key=key), self.assertRaises(p.ProjectionError):
                p.source_value('native_task_metadata', {**item['value'], key: CANARY})
        item['revision'] = {'kind': 'opaque', 'value': 'fake-updatedAt'}
        with self.assertRaises(p.ProjectionError):
            p.observation(item)

    def test_native_history_end_page_is_partial_and_duplicate_locators_fail(self):
        task = {'source': 'codex', 'kind': 'native_task', 'id': 'fixture:host:task:one'}
        turn = {'turn_ref': {'source': 'codex', 'kind': 'native_turn', 'id': task['id'] + ':turn:one'},
                'reported_status': 'completed', 'started_at': None, 'completed_at': None,
                'messages': [{'message_ref': {'source': 'codex', 'kind': 'native_message',
                    'id': task['id'] + ':turn:one:message:one'}, 'message_type': 'userMessage'}]}
        item = observed('native_history_page', key='codex:one:history', value={
            'task_ref': task, 'turns': [turn], 'page': {'order': 'newest_first', 'limit': 10, 'has_more': False}})
        item['resource'].update(source='codex', id=task['id'])
        item['coverage'].update(state='partial', total_count=None, reason='history_scope_unverified')
        p.observation(item)
        duplicate = copy.deepcopy(item)
        duplicate['value']['turns'].append(copy.deepcopy(turn))
        duplicate['coverage']['returned_count'] = 2
        with self.assertRaises(p.ProjectionError):
            p.observation(duplicate)
        item['coverage'].update(state='complete', total_count=1, reason=None)
        with self.assertRaises(p.ProjectionError):
            p.observation(item)

    def test_typed_requirement_ref_is_not_an_opaque_resource_id(self):
        value = {'repository_id': 101, 'path': 'docs/plan/spec.md', 'revision': 'a' * 40,
                 'selector': 'R1'}
        p.requirement_ref(value)
        with self.assertRaises(p.ProjectionError):
            p.requirement_ref({'source': 'github', 'kind': 'requirement', 'id': 'R1'})
        for path in ('../private', '/absolute', 'docs/.git/plan.md', 'docs//spec.md'):
            with self.subTest(path=path), self.assertRaises(p.ProjectionError):
                p.requirement_ref({**value, 'path': path})

    def test_native_reply_is_rejected_without_traversing_private_handoff(self):
        with self.assertRaises(p.ProjectionError) as caught:
            p.standard_reply({'reply_profile': 'native_handoff_v1',
                              'handoff': {'cwd': CANARY, 'prompt': CANARY}})
        self.assertEqual(caught.exception.reason, 'unsupported_reply_profile')
        self.assertNotIn(CANARY, str(caught.exception))

    def test_actual_admission_reply_producer_is_consumed_with_its_own_readback(self):
        from hydra_sdlc.control_commands import _observation, _reply
        command = {'request_id': REQUEST, 'action': 'admission_set',
                   'target': {'kind': 'repository', 'repository_id': 101}}
        source = _observation(command, runtime(), {'revision': 7, 'global_mode': 'paused',
                              'projects': {'example/alpha': 'running'}}, 'example/alpha', 'readback', AT)
        response = _reply(command, runtime(), EPOCH, 'applied', None, observation=source)
        self.assertEqual(p.standard_reply(response), response)
        foreign = copy.deepcopy(response)
        foreign['request']['receipt']['readback']['revision']['value'] = '8'
        with self.assertRaises(p.ProjectionError):
            p.standard_reply(foreign)

    def test_known_values_and_references_are_copied_from_mutable_inputs(self):
        source = observed()
        raw = {'state': 'unobserved', 'active_count': None}
        known = p.known(raw, [source])
        raw['state'] = 'ended'
        source['revision']['value'] = '8'
        self.assertEqual(known['value']['state'], 'unobserved')
        self.assertIsNone(known['value']['active_count'])
        self.assertEqual(known['evidence'][0]['revision']['value'], '7')
