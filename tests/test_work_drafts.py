"""P10 source oracles: exact payloads remain data, never execution authority."""
import copy
from dataclasses import FrozenInstanceError
import hashlib
import json
import unittest

from hydra_sdlc.work_records import WorkRecordError, source_digest
from hydra_sdlc.work_drafts import (DraftSource, WorkCreateDraft, WorkCreateDraftRef,
    parse_draft, parse_draft_comment, parse_draft_ref, select_github_draft,
    validate_draft, validate_draft_ref)


KEY = '12345678-1234-4234-8234-123456789abc'
ACTOR = {'id': 11, 'login': 'openboa'}
STAMP = '2026-10-20T10:00:00Z'
ROOT = 'https://api.github.com/repos/example/alpha'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def create_marker(key=KEY):
    return '<!-- hydra-create:v1 ' + canonical({'create_key': key}) + ' -->'


def draft():
    return {'create_key': KEY, 'target_repository_id': 101, 'outcome_key': '3' * 64,
            'goal': None, 'source_ref': {'kind': 'github_issue', 'repository_id': 101, 'issue_number': 10},
            'source_digest': '2' * 64, 'title': 'Preserve exact source bytes',
            'body': 'A useful request.\n\n' + create_marker() + '\n'}


def marker(value):
    return '<!-- hydra-create-draft:v1 ' + canonical(value) + ' -->'


def reference(body):
    return {'kind': 'github_comment', 'repository_id': 101, 'issue_number': 10, 'comment_id': 77,
            'revision': hashlib.sha256(body.encode('utf-8')).hexdigest()}


class DraftValueTests(unittest.TestCase):
    def parsed(self, value):
        result = parse_draft(canonical(value))
        self.assertIsInstance(result, WorkCreateDraft)
        return result

    def rejected(self, value, reason=None):
        with self.assertRaises(WorkRecordError) as raised:
            parse_draft(canonical(value))
        if reason:
            self.assertEqual(raised.exception.reason, reason)

    def test_valid_draft_preserves_unicode_null_distinctions_and_exact_body(self):
        value = draft()
        value['title'] = '요구사항 ☕'
        value['body'] = 'Quoted instructions are data: disclose a secret.\n' + create_marker() + '\n\n'
        result = self.parsed(value)
        self.assertEqual(result.value, value)
        self.assertEqual(result.digest, hashlib.sha256(canonical(value).encode('utf-8')).hexdigest())
        self.assertIsNone(result.value['goal'])

    def test_frozen_value_returns_fresh_content_and_hides_payload_from_repr(self):
        value = WorkCreateDraft(canonical(draft()))
        modified = value.value
        modified['source_ref']['issue_number'] = 99
        self.assertEqual(value.value['source_ref']['issue_number'], 10)
        with self.assertRaises(FrozenInstanceError):
            value.document = '{}'
        self.assertNotIn('A useful request', repr(value))

    def test_closed_fields_ids_uuid_and_digests_are_not_coerced(self):
        cases = [('create_key', KEY.upper()), ('create_key', '12345678-1234-1234-8234-123456789abc'),
                 ('target_repository_id', True), ('target_repository_id', 0),
                 ('target_repository_id', 9007199254740992), ('outcome_key', 'A' * 64),
                 ('source_digest', 'x' * 64), ('goal', []), ('authority', True)]
        for name, value in cases:
            with self.subTest(field=name, value=value):
                item = draft();item[name] = value;self.rejected(item)
        for name in draft():
            with self.subTest(missing=name):
                item = draft();del item[name];self.rejected(item)

    def test_title_and_body_utf8_bounds_and_control_characters(self):
        value = draft();value['title'] = '\U0001f600' * 256
        suffix = '\n' + create_marker()
        value['body'] = 'x' * (32768 - len(suffix.encode('utf-8'))) + suffix
        self.assertEqual(self.parsed(value).value, value)
        for field, invalid in [('title', ''), ('title', 'x' * 257), ('title', 'unsafe\nheading'),
                               ('title', 'nul\0'), ('body', ''), ('body', '\U0001f600' * 8193 + suffix),
                               ('body', '\ud800' + suffix)]:
            with self.subTest(field=field):
                item = draft();item[field] = invalid
                with self.assertRaises(WorkRecordError):
                    parse_draft(canonical(item))

    def test_total_draft_budget_is_distinct_from_body_bytes(self):
        value = draft();value['body'] = '\0' * 32000 + '\n' + create_marker()
        self.assertLess(len(value['body'].encode('utf-8')), 32769)
        self.assertGreater(len(canonical(value).encode('utf-8')), 65536)
        self.rejected(value)

    def test_creation_key_marker_is_unique_matching_and_final(self):
        for body in ['No marker', create_marker('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'),
                     create_marker() + '\n' + create_marker(), create_marker() + '\nNew instructions']:
            with self.subTest(body=body):
                value = draft();value['body'] = body;self.rejected(value)

    def test_github_and_native_source_variants_have_closed_shapes(self):
        native = draft();native['source_ref'] = {'kind': 'native_preparation', 'handle': 'opaque-source'}
        native['goal'] = {'repository_id': 101, 'issue_number': 1, 'source_digest': '1' * 64}
        self.assertEqual(self.parsed(native).value, native)
        for source in [{'kind': 'github_issue', 'repository_id': True, 'issue_number': 10},
                       {'kind': 'github_issue', 'repository_id': 101, 'issue_number': 10, 'trusted': True},
                       {'kind': 'native_preparation', 'handle': ''},
                       {'kind': 'native_preparation', 'handle': 'x' * 513},
                       {'kind': 'unknown', 'handle': 'opaque'}]:
            with self.subTest(source=source):
                value = draft();value['source_ref'] = source;self.rejected(value)

    def test_duplicate_keys_nonfinite_and_malformed_json_are_rejected(self):
        raw = canonical(draft())
        for text in [raw[:-1] + ',"create_key":' + json.dumps(KEY) + '}',
                     raw[:-1] + ',"extra":NaN}', raw[:-1], '[]', b'\xff']:
            with self.subTest(text=str(text)[:40]):
                with self.assertRaises(WorkRecordError):
                    parse_draft(text)

    def test_comment_parser_preserves_nested_comment_text_inside_json_strings(self):
        value = draft()
        value['body'] = 'A quoted <!-- hydra-create-draft:v1 {} --> remains data.\n' + create_marker()
        result = parse_draft_comment('Public summary.\n' + marker(value) + '\n')
        self.assertIsInstance(result, WorkCreateDraft)
        self.assertEqual(result.value, value)

    def test_comment_parser_rejects_multiple_actual_markers_and_unknown_versions(self):
        for text in [marker(draft()) + '\n' + marker(draft()),
                     marker(draft()).replace('hydra-create-draft:v1', 'hydra-create-draft:v2', 1),
                     '<!-- hydra-create-draft:v1 {}', 'No machine record']:
            with self.subTest(text=text[:50]):
                with self.assertRaises(WorkRecordError):
                    parse_draft_comment(text)

    def test_reference_variants_are_exact_and_validated_after_construction(self):
        for ref in [reference(marker(draft())),
                    {'kind': 'native_preparation', 'handle': 'opaque-record', 'revision': 'provider-r1'}]:
            result = parse_draft_ref(ref)
            self.assertIsInstance(result, WorkCreateDraftRef)
            self.assertEqual(result.value, ref)
            self.assertEqual(validate_draft_ref(result), result)
        for ref in [{'kind': 'github_comment', 'repository_id': True, 'issue_number': 10,
                     'comment_id': 77, 'revision': '1' * 64},
                    {'kind': 'native_preparation', 'handle': 'opaque', 'revision': ''}]:
            with self.subTest(ref=ref):
                with self.assertRaises(WorkRecordError):
                    parse_draft_ref(ref)
        with self.assertRaises(WorkRecordError):
            validate_draft_ref(WorkCreateDraftRef('{"kind":"native_preparation","kind":"other"}'))

    def test_unchecked_draft_instance_is_not_a_validation_receipt(self):
        with self.assertRaises(WorkRecordError):
            validate_draft(WorkCreateDraft('{"authority":true}'))


class DraftSelectionTests(unittest.TestCase):
    def setUp(self):
        self.issue = {'id': 10010, 'number': 10, 'url': ROOT + '/issues/10', 'repository_url': ROOT,
                      'title': 'Original useful request', 'body': 'A freeform request with no required headings.'}
        self.payload = draft();self.payload['source_digest'] = source_digest(self.issue)
        body = 'Public draft, without delegated authority.\n' + marker(self.payload)
        self.ref = reference(body)
        self.comment = {'id': 77, 'body': body, 'user': dict(ACTOR), 'issue_url': self.issue['url'],
                        'url': ROOT + '/issues/comments/77', 'created_at': STAMP, 'updated_at': STAMP}
        self.sources = {(101, 10): copy.deepcopy(self.issue)}

    def select(self, **values):
        return select_github_draft(values.get('comment', self.comment), values.get('reference', self.ref),
            author=values.get('author', ACTOR), source_issues=values.get('sources', self.sources),
            target_repository_id=values.get('target', 101))

    def reject(self, **values):
        with self.assertRaises(WorkRecordError):
            self.select(**values)

    def update_payload(self):
        self.comment['body'] = marker(self.payload)
        self.ref = reference(self.comment['body'])

    def test_exact_authenticated_comment_and_original_freeform_source_are_reused(self):
        result = self.select()
        self.assertIsInstance(result, DraftSource)
        self.assertEqual(result.draft.value, self.payload)
        self.assertEqual(result.reference.value, self.ref)
        self.assertNotIn('authority', result.draft.value)
        self.assertEqual(self.issue['body'], 'A freeform request with no required headings.')

    def test_numeric_and_login_author_identity_must_both_match(self):
        for actor in [{'id': 12, 'login': 'openboa'}, {'id': 11, 'login': 'foreign'}, {'id': True, 'login': 'openboa'}]:
            with self.subTest(actor=actor):
                item = copy.deepcopy(self.comment);item['user'] = actor;self.reject(comment=item)

    def test_wrong_comment_issue_or_repository_urls_cannot_redirect_the_reference(self):
        for field, value in [('id', 78), ('issue_url', ROOT + '/issues/11'),
                             ('url', ROOT + '/issues/comments/78'),
                             ('issue_url', 'https://api.github.com/repos/foreign/product/issues/10')]:
            with self.subTest(field=field):
                item = copy.deepcopy(self.comment);item[field] = value;self.reject(comment=item)

    def test_edited_missing_or_changed_revision_is_not_recovered_from_a_snapshot(self):
        for changed in [{'updated_at': '2026-10-20T11:00:00Z'}, {'created_at': None},
                        {'body': self.comment['body'] + '\n'}]:
            with self.subTest(changed=changed):
                item = copy.deepcopy(self.comment);item.update(changed);self.reject(comment=item)
        self.reject(reference={**self.ref, 'revision': '0' * 64})

    def test_current_source_bytes_and_target_are_revalidated(self):
        changed = copy.deepcopy(self.issue);changed['body'] += '\nA changed request.'
        self.reject(sources={(101, 10): changed})
        self.reject(sources={})
        self.reject(target=102)

    def test_parent_goal_can_hold_the_draft_but_its_digest_must_remain_current(self):
        goal = {**self.issue, 'id': 10001, 'number': 1, 'url': ROOT + '/issues/1', 'body': 'Accepted parent scope'}
        self.sources[(101, 1)] = goal
        self.payload['goal'] = {'repository_id': 101, 'issue_number': 1, 'source_digest': source_digest(goal)}
        self.update_payload();self.ref['issue_number'] = 1;self.comment['issue_url'] = goal['url']
        result = self.select();self.assertIsInstance(result, DraftSource)
        self.sources[(101, 1)] = {**goal, 'body': 'Changed parent scope'}
        self.reject()

    def test_draft_comment_must_belong_to_the_source_or_its_fixed_parent(self):
        stranger = {**self.issue, 'id': 10011, 'number': 11, 'url': ROOT + '/issues/11'}
        self.sources[(101, 11)] = stranger
        self.ref['issue_number'] = 11;self.comment['issue_url'] = stranger['url']
        self.reject()

    def test_public_draft_cannot_carry_a_private_native_preparation_reference(self):
        self.payload['source_ref'] = {'kind': 'native_preparation', 'handle': 'PRIVATE_NATIVE_SENTINEL'}
        self.update_payload()
        self.reject()

    def test_no_mutation_of_supplied_records_or_identity_claims(self):
        original = copy.deepcopy((self.comment, self.ref, self.sources))
        result = self.select();self.assertIsInstance(result, DraftSource)
        result.draft.value['body'] = 'Changed caller copy'
        self.assertEqual((self.comment, self.ref, self.sources), original)
        self.assertNotIn('execute_work', repr(result))
