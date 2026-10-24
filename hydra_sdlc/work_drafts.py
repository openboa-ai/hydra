"""Immutable work-create payloads and exact source selection.

A validated value establishes structure and source consistency only. Callers
must separately establish authenticated reads, actual delegation, accepted
scope, complete duplicate lookup and permission before any creation effect.
"""
from dataclasses import dataclass, field
import hashlib
import json
import re

from .work_records import (WorkRecordError, _canonical, _decode_marker, _hex,
    _integer, _issue_ref, _json_object, _object, _require, _text, _unchanged,
    _uuid, source_digest)


MAX_DRAFT_BYTES = 65536
MAX_BODY_BYTES = 32768
MAX_COMMENT_BYTES = 8_000_000
MAX_REF_BYTES = 16384
_DRAFT_KEYS = {'create_key', 'target_repository_id', 'outcome_key', 'goal',
               'source_ref', 'source_digest', 'title', 'body'}


@dataclass(frozen=True)
class WorkCreateDraft:
    document: str = field(repr=False)

    @property
    def value(self):
        return json.loads(self.document)

    @property
    def digest(self):
        return hashlib.sha256(self.document.encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class WorkCreateDraftRef:
    document: str = field(repr=False)

    @property
    def value(self):
        return json.loads(self.document)


@dataclass(frozen=True)
class DraftSource:
    draft: WorkCreateDraft = field(repr=False)
    reference: WorkCreateDraftRef = field(repr=False)


def _bytes(value, limit, reason):
    _require(type(value) in {str, bytes}, reason)
    try:
        data = value.encode('utf-8') if type(value) is str else value
        _require(len(data) <= limit, reason)
        return data.decode('utf-8')
    except UnicodeError as exc:
        raise WorkRecordError(reason) from exc


def _source_ref(value):
    _require(type(value) is dict)
    if value.get('kind') == 'github_issue':
        _object(value, {'kind', 'repository_id', 'issue_number'})
        _issue_ref({key: value[key] for key in ('repository_id', 'issue_number')})
    else:
        _object(value, {'kind', 'handle'})
        _require(value['kind'] == 'native_preparation' and _text(value['handle'], 512))


def _draft_value(value):
    _object(value, _DRAFT_KEYS)
    _require(_uuid(value['create_key'], version=4) and _integer(value['target_repository_id'])
             and _hex(value['outcome_key'], 64) and _hex(value['source_digest'], 64))
    if value['goal'] is not None:
        _object(value['goal'], {'repository_id', 'issue_number', 'source_digest'})
        _issue_ref({key: value['goal'][key] for key in ('repository_id', 'issue_number')})
        _require(_hex(value['goal']['source_digest'], 64))
    _source_ref(value['source_ref'])
    _require(_text(value['title'], 256))
    _require(type(value['body']) is str and bool(value['body']))
    body = _bytes(value['body'], MAX_BODY_BYTES, 'body_limit')
    creation = _decode_marker(body, 'hydra-create', 'v1', MAX_BODY_BYTES)
    _object(creation, {'create_key'})
    _require(creation['create_key'] == value['create_key'], 'creation_key_mismatch')
    start = body.index('<!-- hydra-create:')
    end = body.find(' -->', start)
    _require(not body[end + 4:].strip(), 'creation_marker_not_final')
    try:
        document = _canonical(value)
        _require(len(document.encode('utf-8')) <= MAX_DRAFT_BYTES, 'draft_limit')
    except (ValueError, UnicodeError) as exc:
        raise WorkRecordError('invalid_schema') from exc
    return WorkCreateDraft(document)


def parse_draft(raw):
    # The source representation can contain JSON escapes and whitespace. The
    # canonical payload has its own smaller limit after strict JSON decoding.
    return _draft_value(_json_object(_bytes(raw, MAX_COMMENT_BYTES, 'invalid_json')))


def validate_draft(value):
    _require(type(value) is WorkCreateDraft, 'invalid_schema')
    return parse_draft(value.document)


def parse_draft_comment(body):
    text = _bytes(body, MAX_COMMENT_BYTES, 'marker_limit')
    prefix = '<!-- hydra-create-draft:'
    start = text.find(prefix)
    _require(start >= 0, 'invalid_marker')
    expected = prefix + 'v1 '
    _require(text.startswith(expected, start), 'unsupported_version')
    tail = text[start + len(expected):]
    offset = len(tail) - len(tail.lstrip())
    try:
        _, end = json.JSONDecoder().raw_decode(tail, offset)
    except (ValueError, RecursionError) as exc:
        raise WorkRecordError('invalid_json') from exc
    suffix = tail[end:]
    whitespace = len(suffix) - len(suffix.lstrip())
    _require(suffix[whitespace:].startswith('-->'), 'invalid_marker')
    remaining = suffix[whitespace + 3:]
    _require(prefix not in remaining, 'conflict')
    # Decode strictly a second time for duplicate/nonfinite rejection. JSON
    # framing, rather than the first HTML closing token, preserves nested
    # comment text inside the fixed request body.
    return _draft_value(_json_object(tail[:end]))


def parse_draft_ref(value):
    _require(type(value) is dict)
    if value.get('kind') == 'github_comment':
        _object(value, {'kind', 'repository_id', 'issue_number', 'comment_id', 'revision'})
        _issue_ref({key: value[key] for key in ('repository_id', 'issue_number')})
        _require(_integer(value['comment_id']) and _hex(value['revision'], 64))
    else:
        _object(value, {'kind', 'handle', 'revision'})
        _require(value['kind'] == 'native_preparation'
                 and _text(value['handle'], 512) and _text(value['revision'], 512))
    return WorkCreateDraftRef(_canonical(value))


def validate_draft_ref(value):
    _require(type(value) is WorkCreateDraftRef, 'invalid_schema')
    return parse_draft_ref(_json_object(_bytes(value.document, MAX_REF_BYTES, 'invalid_schema')))


def _issue(sources, repository_id, number):
    _require(type(sources) is dict, 'source_unknown')
    row = sources.get((repository_id, number))
    _require(type(row) is dict and _integer(row.get('id')) and row.get('number') == number
             and type(row.get('number')) is int and 'pull_request' not in row, 'source_unknown')
    root = row.get('repository_url')
    _require(type(root) is str and re.fullmatch(
        r'https://api\.github\.com/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', root)
        and row.get('url') == root + '/issues/' + str(number), 'identity_mismatch')
    return row


def _draft_from_comment(comment, ref, author, root):
    _require(type(author) is dict and _integer(author.get('id')) and _text(author.get('login'), 100),
             'author_unknown')
    _require(type(comment) is dict and _integer(comment.get('id')) and comment['id'] == ref['comment_id'],
             'identity_mismatch')
    actor = comment.get('user')
    _require(type(actor) is dict and _integer(actor.get('id')) and actor['id'] == author['id']
             and actor.get('login') == author['login'], 'draft_author_mismatch')
    _require(comment.get('issue_url') == root + '/issues/' + str(ref['issue_number'])
             and comment.get('url') == root + '/issues/comments/' + str(ref['comment_id']),
             'identity_mismatch')
    _unchanged(comment)
    body = _bytes(comment.get('body'), MAX_COMMENT_BYTES, 'invalid_marker')
    _require(hashlib.sha256(body.encode('utf-8')).hexdigest() == ref['revision'], 'draft_changed')
    return parse_draft_comment(body)


def select_github_draft(comment, reference, *, author, source_issues, target_repository_id):
    """Select exact data; the caller authenticates transport and repository mapping.

    A result is neither human authority nor absence of another outcome.
    """
    selected = (validate_draft_ref(reference) if type(reference) is WorkCreateDraftRef
                else parse_draft_ref(reference))
    ref = selected.value
    _require(ref['kind'] == 'github_comment', 'unsupported_source')
    container = _issue(source_issues, ref['repository_id'], ref['issue_number'])
    parsed = _draft_from_comment(comment, ref, author, container['repository_url'])
    value = parsed.value
    _require(_integer(target_repository_id) and value['target_repository_id'] == target_repository_id,
             'target_mismatch')
    origin = value['source_ref']
    _require(origin['kind'] == 'github_issue', 'private_source_in_public_draft')
    source = _issue(source_issues, origin['repository_id'], origin['issue_number'])
    _require(source_digest(source) == value['source_digest'], 'source_changed')
    locations = {(origin['repository_id'], origin['issue_number'])}
    goal = value['goal']
    if goal is not None:
        parent = _issue(source_issues, goal['repository_id'], goal['issue_number'])
        _require(source_digest(parent) == goal['source_digest'], 'goal_changed')
        locations.add((goal['repository_id'], goal['issue_number']))
    _require((ref['repository_id'], ref['issue_number']) in locations, 'draft_container_mismatch')
    return DraftSource(parsed, selected)
