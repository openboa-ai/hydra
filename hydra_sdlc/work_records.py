"""Read-only WorkBinding schemas and exact comment/attempt recovery.

These values establish structure and source identity, never independent design
acceptance, delegation, dependency satisfaction, or permission to dispatch work.
Reference input contracts remain references here; work_inputs normalizes the
explicit file read. No model, transport, persistence, or effect is used here.
"""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
import uuid


MAX_ID = 9007199254740991
_BINDING_KEYS = {'repository_id', 'issue_number', 'source_digest', 'kind', 'create_key',
                 'delegated_goal', 'outcome', 'requirements', 'spec', 'input_contract',
                 'delegation_ref'}
_ANCHOR_KEYS = {'repository_id', 'issue_number', 'attempt_id', 'binding_comment_id',
                'binding_digest', 'source_digest', 'contract_revision'}


class WorkRecordError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _require(okay, reason='invalid_schema'):
    if not okay:
        raise WorkRecordError(reason)


def _object(value, keys):
    _require(type(value) is dict and set(value) == keys)


def _integer(value):
    return type(value) is int and 1 <= value <= MAX_ID


def _hex(value, length):
    return type(value) is str and re.fullmatch('[0-9a-f]{' + str(length) + '}', value) is not None


def _text(value, limit):
    return (type(value) is str and 1 <= len(value) <= limit
            and not any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value))


def _path(value):
    return (_text(value, 512) and not value.startswith(('/', '~')) and '\\' not in value
            and all(p not in {'', '.', '..', '.git'} for p in value.split('/')))


def _uuid(value, *, version=None):
    if type(value) is not str:
        return False
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return str(parsed) == value and (version is None or parsed.version == version)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def source_digest(issue):
    """Exact legacy intake bytes: no trimming, normalization, or null fallback."""
    _require(type(issue) is dict, 'invalid_source')
    _require(all(issue.get(k) is None or type(issue.get(k)) is str for k in ('title', 'body')),
             'invalid_source')
    try:
        return _digest({'title': issue.get('title'), 'body': issue.get('body')})
    except UnicodeError as exc:
        raise WorkRecordError('invalid_source') from exc


def _issue_ref(value):
    _object(value, {'repository_id', 'issue_number'})
    _require(all(_integer(value[k]) for k in value))


def _requirement(value):
    _object(value, {'repository_id', 'path', 'revision', 'selector'})
    _require(_integer(value['repository_id']) and _path(value['path'])
             and _hex(value['revision'], 40) and _text(value['selector'], 160))


def _requirements(values, minimum=0, *, ordered=False):
    _require(type(values) is list and minimum <= len(values) <= 100)
    for value in values:
        _requirement(value)
    keys = [_canonical(value) for value in values]
    _require(len(keys) == len(set(keys)) and (not ordered or keys == sorted(keys)))


def _input_contract(value, issue):
    if value is None:
        return
    _require(type(value) is dict)
    if value.get('kind') == 'reference':
        _object(value, {'kind', 'ref'})
        _requirement(value['ref'])
        return
    _object(value, {'kind', 'clauses'})
    _require(value['kind'] == 'adopted' and type(value['clauses']) is list and len(value['clauses']) <= 50)
    for clause in value['clauses']:
        _object(clause, {'producer', 'requirements', 'required_stage', 'basis'})
        _issue_ref(clause['producer'])
        _require(clause['producer'] != issue)
        _requirements(clause['requirements'], 1, ordered=True)
        _require(type(clause['required_stage']) is str
                 and clause['required_stage'] in {'post_merge_verified', 'observed'})
        _requirement(clause['basis'])
    keys = [_canonical(clause) for clause in value['clauses']]
    _require(keys == sorted(set(keys)))


def _json_object(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate')
            result[key] = value
        return result
    def nonfinite(_):
        raise ValueError('nonfinite')
    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
    except (ValueError, RecursionError) as exc:
        raise WorkRecordError('invalid_json') from exc
    _require(type(value) is dict, 'invalid_schema')
    return value


def _decode_marker(body, name, version, limit):
    _require(type(body) is str and len(body) <= 8_000_000, 'invalid_marker')
    prefix = '<!-- ' + name + ':'
    _require(body.count(prefix) == 1, 'invalid_marker')
    start = body.index(prefix)
    end = body.find(' -->', start)
    _require(end >= 0, 'invalid_marker')
    raw = body[start:end + 4]
    try:
        _require(len(raw.encode('utf-8')) <= limit, 'marker_limit')
    except UnicodeError as exc:
        raise WorkRecordError('invalid_json') from exc
    expected = prefix + version + ' '
    _require(raw.startswith(expected), 'unsupported_version')
    return _json_object(raw[len(expected):-4])


@dataclass(frozen=True)
class Binding:
    """Immutable canonical content; consumers receive a fresh JSON value."""
    document: str

    @property
    def value(self):
        return json.loads(self.document)

    @property
    def digest(self):
        return hashlib.sha256(self.document.encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class BindingSource:
    binding: Binding
    comment_id: int


def parse_binding(body, *, spec_directory):
    value = _decode_marker(body, 'hydra-work', 'v2', 32768)
    return _binding_value(value, spec_directory)


def validate_binding(binding, *, spec_directory):
    """Revalidate all fields and scope; an unchecked Binding is only a value."""
    _require(type(binding) is Binding and type(binding.document) is str)
    try:
        size = len(binding.document.encode('utf-8')) + len('<!-- hydra-work:v2  -->')
    except UnicodeError as exc:
        raise WorkRecordError('invalid_schema') from exc
    _require(size <= 32768, 'marker_limit')
    return _binding_value(_json_object(binding.document), spec_directory)


def _binding_value(value, spec_directory):
    _object(value, _BINDING_KEYS)
    issue = {key: value[key] for key in ('repository_id', 'issue_number')}
    _issue_ref(issue)
    _require(_hex(value['source_digest'], 64) and type(value['kind']) is str
             and value['kind'] in {'goal', 'work'})
    _require(value['create_key'] is None or _uuid(value['create_key'], version=4))
    goal = value['delegated_goal']
    if goal is not None:
        _object(goal, {'repository_id', 'issue_number', 'source_digest'})
        _issue_ref({k: goal[k] for k in ('repository_id', 'issue_number')})
        _require(_hex(goal['source_digest'], 64)
                 and any(goal[k] != issue[k] for k in issue))
    _require(type(value['outcome']) is str and re.fullmatch('[a-z0-9][a-z0-9-]{0,63}', value['outcome']))
    _requirements(value['requirements'])
    _require(_path(spec_directory))
    spec = value['spec']
    if spec is not None:
        _object(spec, {'path', 'revision'})
        _require(_path(spec['path']) and (spec['revision'] is None or _hex(spec['revision'], 40)))
        if value['kind'] == 'work':
            _require(spec['path'].startswith(spec_directory + '/') and spec['path'].endswith('/spec.md'))
    _input_contract(value['input_contract'], issue)
    ref = value['delegation_ref']
    _require(ref is None or type(ref) is str and re.fullmatch(
        r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[1-9][0-9]*(?:#issuecomment-[1-9][0-9]*)?', ref))
    return Binding(_canonical(value))


def parse_anchor(body):
    value = _decode_marker(body, 'hydra-attempt-binding', 'v1', 2048)
    _object(value, _ANCHOR_KEYS)
    _issue_ref({k: value[k] for k in ('repository_id', 'issue_number')})
    _require(_uuid(value['attempt_id']) and _integer(value['binding_comment_id'])
             and _hex(value['binding_digest'], 64) and _hex(value['source_digest'], 64)
             and _hex(value['contract_revision'], 40))
    return value


def _owned_rows(rows, author, coverage):
    _require(coverage == 'complete', 'unknown')
    _require(type(rows) is list and len(rows) <= 10000, 'unknown')
    _require(type(author) is dict and _integer(author.get('id'))
             and _text(author.get('login'), 100), 'unknown')
    seen, own = set(), []
    for row in rows:
        _require(type(row) is dict and _integer(row.get('id')), 'unknown')
        _require(row['id'] not in seen, 'conflict')
        seen.add(row['id'])
        actor = row.get('user')
        if (type(actor) is dict and type(actor.get('id')) is int and actor['id'] == author['id']
                and actor.get('login') == author['login']):
            _require(row.get('body') is None or type(row.get('body')) is str, 'unknown')
            own.append(row)
    return own


def _unchanged(row):
    created, updated = row.get('created_at'), row.get('updated_at')
    _require(type(created) is str and created == updated and re.fullmatch(
        r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z', created), 'edited_or_unknown')
    try:
        datetime.fromisoformat(created[:-1] + '+00:00')
    except ValueError as exc:
        raise WorkRecordError('edited_or_unknown') from exc


def _comment_issue(row, issue):
    url = issue.get('url')
    _require(type(url) is str and re.fullmatch(
        r'https://api\.github\.com/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/' + str(issue['number']), url)
        and row.get('issue_url') == url,
        'identity_mismatch')


def select_binding(rows, *, repository_id, issue, author, coverage,
                   selected_comment_id, selected_digest, spec_directory):
    own = _owned_rows(rows, author, coverage)
    _require(_integer(repository_id) and type(issue) is dict and _integer(issue.get('number')),
             'identity_mismatch')
    _require(_integer(selected_comment_id) and _hex(selected_digest, 64), 'invalid_selection')
    selected = [row for row in rows if row['id'] == selected_comment_id]
    _require(bool(selected), 'unknown')
    _require(selected[0] in own, 'unbound')
    row = selected[0]
    _unchanged(row)
    _comment_issue(row, issue)
    parsed = parse_binding(row.get('body'), spec_directory=spec_directory)
    value = parsed.value
    _require(value['repository_id'] == repository_id and value['issue_number'] == issue['number'],
             'identity_mismatch')
    _require(parsed.digest == selected_digest, 'binding_changed')
    _require(value['source_digest'] == source_digest(issue), 'source_changed')
    for other in own:
        if other['id'] == row['id'] or '<!-- hydra-work:' not in (other.get('body') or ''):
            continue
        try:
            candidate = parse_binding(other['body'], spec_directory=spec_directory)
        except WorkRecordError:
            # An explicit selection never adopts another historical candidate.
            continue
        _require(candidate.digest != parsed.digest, 'conflict')
    return BindingSource(parsed, row['id'])


def recover_binding(rows, *, repository_id, issue, author, coverage, progress, spec_directory):
    """Restore a prevalidated progress attempt without choosing a newer binding.

    The caller must authenticate/validate progress with the existing v1 reader.
    Only its exact binding fields are checked here; no v1 fields are rewritten.
    """
    own = _owned_rows(rows, author, coverage)
    _require(type(progress) is dict and _uuid(progress.get('attempt_id')), 'unknown')
    anchors = []
    for row in own:
        if '<!-- hydra-attempt-binding:' not in (row.get('body') or ''):
            continue
        anchor = parse_anchor(row['body'])
        if anchor['attempt_id'] == progress['attempt_id']:
            anchors.append((row, anchor))
    _require(bool(anchors), 'unknown')
    _require(len(anchors) == 1, 'conflict')
    row, anchor = anchors[0]
    _unchanged(row)
    _require(type(issue) is dict and _integer(issue.get('number')), 'identity_mismatch')
    _comment_issue(row, issue)
    expected = {'repository_id': repository_id, 'issue_number': issue['number'],
                'source_digest': progress.get('intake_digest'), 'contract_revision': progress.get('contract_revision')}
    _require(all(anchor[k] == v for k, v in expected.items())
             and all(progress.get(k) == expected[k] for k in ('repository_id', 'issue_number')),
             'anchor_mismatch')
    return select_binding(rows, repository_id=repository_id, issue=issue, author=author,
                          coverage=coverage, spec_directory=spec_directory,
                          selected_comment_id=anchor['binding_comment_id'], selected_digest=anchor['binding_digest'])
