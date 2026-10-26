"""Explicit v2 delegated decision bytes and authenticated read-only observations.

These records describe a public proposal, not human provenance or an execution
grant. Version-1 codecs remain separate. Missing records cannot prove that no
request was dispatched or that no historical record was deleted.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import re
import uuid

from .github import GitHubError, _decision_context_marker, _number, _repo
from . import public_decisions as public

PROFILE = 'codex_delegated_v1'
_INTENT = '<!-- hydra-decision-intent:v2 '
_RECEIPT = '<!-- hydra-decision-receipt:v2 '
_CONTEXT_LINK = '<!-- hydra-decision-context:v1 '
_FAMILY = re.compile(r'<!-- hydra-decision-(intent|receipt):v([0-9]+) ')
_INPUT_FIELDS = {'key', 'origin_phase', 'head', 'contract_revision', 'spec_revision', 'intake_digest'}
_FIELDS = _INPUT_FIELDS | {'profile', 'resume_attempt', 'supersedes'}


@dataclass(frozen=True, repr=False)
class DelegatedContext:
    body: bytes
    key: tuple[int, int, str, int]

    @property
    def sha256(self):
        return hashlib.sha256(self.body).hexdigest()


def _input(basis):
    public._object(basis, _INPUT_FIELDS)
    key = public._key(basis['key'])
    if key[3] != 1 or type(basis['origin_phase']) is not str or basis['origin_phase'] not in public._PHASES:
        public._invalid()
    public._hex(basis['head'], 40)
    public._hex(basis['contract_revision'], 40)
    if basis['spec_revision'] is not None:
        public._hex(basis['spec_revision'], 40)
    public._hex(basis['intake_digest'], 64)
    return key


def _normalize(text):
    if type(text) is not str or len(text) > public.MAX_CONTEXT_BYTES:
        public._invalid()
    text = text.replace('\r\n', '\n').replace('\r', '\n').rstrip('\n')
    # Service readers scan raw comment markers, including inside Markdown.
    # Proposal text must not create another service-owned control record.
    if not text.strip() or '<!-- hydra-' in text:
        public._invalid()
    return text


def _resume(public_text, basis):
    seed = {'profile': PROFILE, 'key': basis['key'],
            'basis': {key: basis[key] for key in _INPUT_FIELDS - {'key'}},
            'public_text': public_text}
    digest = hashlib.sha256(public._json(seed).encode('utf-8')).hexdigest()
    value = str(uuid.uuid5(uuid.NAMESPACE_URL, 'hydra:codex-delegated-v1:' + digest))
    if value == basis['key']['source_attempt']:
        public._invalid()
    return value


def prepare_delegated_context(public_text, basis):
    """Construct canonical v2 bytes, without accepting or publishing a choice."""
    key = _input(basis)
    text = _normalize(public_text)
    try:
        metadata = {**basis, 'profile': PROFILE, 'resume_attempt': _resume(text, basis), 'supersedes': None}
        body = (f'hydra: decision {key[2]} context\n{text}\n'
                + _INTENT + public._json(metadata) + ' -->\n').encode('utf-8')
    except (ValueError, TypeError, UnicodeError, RecursionError):
        public._invalid()
    return parse_delegated_context(body)


def parse_delegated_context(body):
    raw, text = public._wire(body)
    lines = text.split('\n')
    if len(lines) < 4 or not lines[-2].startswith(_INTENT) or not lines[-2].endswith(' -->'):
        public._invalid()
    proposed = '\n'.join(lines[1:-2])
    if _normalize(proposed) != proposed:
        public._invalid()
    wire = lines[-2][len(_INTENT):-4]
    metadata = public._load(wire)
    public._object(metadata, _FIELDS)
    basis = {key: metadata[key] for key in _INPUT_FIELDS}
    key = _input(basis)
    if (metadata['profile'] != PROFILE or metadata['supersedes'] is not None
            or public._uuid(metadata['resume_attempt']) != _resume(proposed, basis)
            or lines[0] != f'hydra: decision {key[2]} context' or wire != public._json(metadata)):
        public._invalid()
    return DelegatedContext(raw, key)


def _checked(context):
    if type(context) is not DelegatedContext:
        public._invalid()
    checked = parse_delegated_context(context.body)
    if checked.key != context.key:
        public._invalid()
    return checked


def delegated_context_basis(context):
    checked = _checked(context)
    return public._load(checked.body.decode('utf-8').split('\n')[-2][len(_INTENT):-4])


def delegated_decision_root(context):
    checked = _checked(context)
    return {'decision': {'key': public._key_json(checked.key), 'context_sha256': checked.sha256},
            'resume_attempt': delegated_context_basis(checked)['resume_attempt']}


def delegated_receipt_body(context):
    checked = _checked(context)
    pin = {'key': public._key_json(checked.key), 'context_sha256': checked.sha256}
    return (f'hydra: decision {checked.key[2]} resolved\n' + _RECEIPT
            + public._json(pin) + ' -->\n').encode('utf-8')


def parse_delegated_receipt(body):
    _, text = public._wire(body)
    lines = text.split('\n')
    if len(lines) != 3 or not lines[1].startswith(_RECEIPT) or not lines[1].endswith(' -->'):
        public._invalid()
    wire = lines[1][len(_RECEIPT):-4]
    pin = public._load(wire)
    key, digest = public._pin(pin)
    if key[3] != 1 or lines[0] != f'hydra: decision {key[2]} resolved' or wire != public._json(pin):
        public._invalid()
    return key, digest


def _progress_context_link(body, position):
    """Recognize the existing progress annotation, never a decision claim."""
    if not body.startswith(_CONTEXT_LINK, position):
        return False
    end = body.find(' -->', position + len(_CONTEXT_LINK))
    if end < 0 or end - position - len(_CONTEXT_LINK) > public.MAX_CONTEXT_BYTES:
        return False
    try:
        return _decision_context_marker(body) is not None
    except GitHubError:
        return False


def _claim(body, key):
    """Inspect family keys without trusting the human-readable heading."""
    found = False
    position = body.find('<!-- hydra-decision-')
    while position >= 0:
        if _progress_context_link(body, position):
            # A progress link is not an intent or receipt. Continue scanning
            # every raw namespace, including ones inside the current payload.
            position = body.find('<!-- hydra-decision-', position + 1)
            continue
        found = True
        match = _FAMILY.match(body, position)
        if match is None:
            return True
        end = body.find(' -->', match.end())
        if end < 0 or end - match.end() > public.MAX_CONTEXT_BYTES:
            return True
        try:
            value = public._load(body[match.end():end])
            if type(value) is not dict or public._key(value.get('key')) == key:
                return True
        except (ValueError, TypeError, UnicodeError):
            return True
        position = body.find('<!-- hydra-decision-', position + 1)
    return not found and body.startswith(f'hydra: decision {key[2]} ')


def _owned(rows, actor, key, *, issue_url, check_deadline):
    service = public._identity(actor)
    for row in rows:
        check_deadline()
        if type(row) is not dict:
            public._invalid()
        body = row.get('body')
        try:
            identity = public._identity(row.get('user'))
        except ValueError:
            if type(body) is not str or _claim(body, key):
                public._invalid()
            continue
        if identity != service:
            continue
        if type(body) is not str:
            public._invalid()
        if not _claim(body, key):
            continue
        if body in (f'hydra: decision {key[2]} resolved', f'hydra: decision {key[2]} resolved\n'):
            continue
        if row.get('issue_url') != issue_url:
            public._invalid()
        yield row


def _observe(rows, actor, context, *, issue_url, check_deadline):
    contexts, receipts, seen = [], [], {}
    wanted_receipt = delegated_receipt_body(context)
    for row in _owned(rows, actor, context.key, issue_url=issue_url, check_deadline=check_deadline):
        identifier = public._positive(row.get('id'))
        raw, _ = public._wire(row['body'])
        if raw.startswith(f'hydra: decision {context.key[2]} context\n'.encode()):
            key, kind = parse_delegated_context(raw).key, 'context'
        else:
            key, _ = parse_delegated_receipt(raw)
            kind = 'receipt'
        if key != context.key:
            continue
        if not public._unedited(row) or identifier in seen and seen[identifier] != raw:
            return public.DecisionObservation('unknown', 'changed_service_record')
        seen[identifier] = raw
        if raw != (context.body if kind == 'context' else wanted_receipt):
            return public.DecisionObservation('conflict', 'different_service_payload')
        (contexts if kind == 'context' else receipts).append(identifier)
    status = ('pair' if contexts and receipts else 'context' if contexts else
              'receipt_without_context' if receipts else 'not_observed')
    return public.DecisionObservation(status, 'public_observation_only',
        min(contexts) if contexts else None, min(receipts) if receipts else None)


@contextmanager
def _source(client, repository, issue_number):
    """Own the caller's synchronous read scope; compose existing auth hooks."""
    original = client._credential_selected
    had_local = '_credential_selected' in client.__dict__
    original_local = client.__dict__.get('_credential_selected')
    selected = None
    changed = False

    def credential(fingerprint):
        nonlocal selected, changed
        try:
            original(fingerprint)
        finally:
            if selected is None:
                selected = fingerprint
            elif selected != fingerprint:
                changed = True
            if changed:
                raise GitHubError('Decision credential changed')

    client._credential_selected = credential
    try:
        with client.read_budget(seconds=30, requests=32):
            actor = client._identity()
            service = public._identity(actor)
            repo = client.repository(repository)
            identifier = public._positive(repo.get('id'))
            canonical = _repo(repo.get('full_name'))
            if canonical.casefold() != repository.casefold():
                public._invalid()
            issue = client.issue(canonical, issue_number)
            issue_url = f'https://api.github.com/repos/{canonical}/issues/{issue_number}'
            if (type(issue.get('number')) is not int or issue['number'] != issue_number
                    or 'url' in issue and issue['url'] != issue_url):
                public._invalid()
            rows = client.comments(canonical, issue_number)
            if type(rows) is not list:
                public._invalid()
            yield actor, identifier, canonical, issue_url, rows
            if public._identity(client._identity()) != service or changed:
                public._invalid()
            client._request_timeout(30)
    finally:
        if had_local:
            client._credential_selected = original_local
        else:
            del client._credential_selected


def _request(repository, issue_number):
    _repo(repository)
    if '..' in repository or '.' in repository.split('/'):
        public._invalid()
    _number(issue_number)


def _direct(client, canonical, issue_url, rows, actor, context, observed, known_context, known_receipt):
    if observed.status in {'unknown', 'conflict'}:
        return observed
    context_refs = {value for value in (observed.context_id, known_context) if value is not None}
    receipt_refs = {value for value in (observed.receipt_id, known_receipt) if value is not None}
    if context_refs & receipt_refs:
        return public.DecisionObservation('unknown', 'pinned_reference_changed')
    for identifier in sorted(context_refs | receipt_refs):
        direct = client.api('GET', f'/repos/{canonical}/issues/comments/{identifier}')
        listed = [row for row in rows if type(row) is dict and row.get('id') == identifier]
        wanted = context.body if identifier in context_refs else delegated_receipt_body(context)
        if (type(direct) is not dict or type(direct.get('id')) is not int or direct['id'] != identifier
                or public._identity(direct.get('user')) != public._identity(actor)
                or direct.get('issue_url') != issue_url or type(direct.get('body')) is not str
                or direct['body'].encode('utf-8') != wanted or not public._unedited(direct)
                or not listed or any(row.get('body') != direct['body']
                    or public._identity(row.get('user')) != public._identity(actor)
                    or row.get('issue_url') != issue_url
                    or row.get('created_at') != direct.get('created_at')
                    or row.get('updated_at') != direct.get('updated_at') for row in listed)):
            return public.DecisionObservation('unknown', 'pinned_reference_changed')
    client._request_timeout(30)
    return observed


def read_delegated_public_decision(client, repository, issue_number, context, *,
                                   known_context_id=None, known_receipt_id=None):
    """Read exact current v2 effects; absence is never non-dispatch evidence."""
    context = _checked(context)
    _request(repository, issue_number)
    if issue_number != context.key[1]:
        public._invalid()
    for identifier in (known_context_id, known_receipt_id):
        if identifier is not None:
            public._positive(identifier)
    try:
        with _source(client, repository, issue_number) as (actor, repo_id, canonical, issue_url, rows):
            if repo_id != context.key[0]:
                public._invalid()
            observed = _observe(rows, actor, context, issue_url=issue_url,
                                check_deadline=lambda: client._request_timeout(30))
            result = _direct(client, canonical, issue_url, rows, actor, context, observed,
                             known_context_id, known_receipt_id)
        return result
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, UnicodeError):
        return public.DecisionObservation('unknown', 'source_unavailable')


def find_delegated_public_decision(client, repository, issue_number, source_attempt, *, expected_root=None):
    """Discover one exact v2 intent, never the newest or a reconstructed answer.

    With no v2 claim, callers may separately inspect their original v1 profile.
    A supplied root requires the exact v2 pair and cannot fall back to that path.
    """
    _request(repository, issue_number)
    public._uuid(source_attempt)
    expected_round = 1
    if expected_root is not None:
        public._object(expected_root, {'decision', 'resume_attempt'})
        expected_key, _ = public._pin(expected_root['decision'])
        public._uuid(expected_root['resume_attempt'])
        if expected_key[1:3] != (issue_number, source_attempt):
            public._invalid()
        expected_round = expected_key[3]
    try:
        with _source(client, repository, issue_number) as (actor, repo_id, canonical, issue_url, rows):
            # Original-profile amendments may have later rounds. Only their
            # matching root can route back to the original qualified reader;
            # the separate delegated parser still accepts round one only.
            key = repo_id, issue_number, source_attempt, expected_round
            context, v1, v2, matching_v1_root = None, False, False, False
            for row in _owned(rows, actor, key, issue_url=issue_url,
                              check_deadline=lambda: client._request_timeout(30)):
                body = row['body']
                if expected_root is None and '<!-- hydra-decision-' not in body:
                    continue
                if _INTENT not in body and _RECEIPT not in body:
                    # Only strict original-profile bytes can select its reader.
                    if body.startswith(f'hydra: decision {source_attempt} context\n'):
                        previous = public.parse_context(body)
                        previous_basis = public.context_basis(previous)
                        previous_root = {
                            'decision': {'key': public._key_json(previous.key),
                                         'context_sha256': previous.sha256},
                            'resume_attempt': previous_basis['resume_attempt'],
                        }
                        matching_v1_root |= previous_root == expected_root
                    else:
                        public.parse_receipt(body)
                    v1 = True
                    continue
                v2 = True
                if not public._unedited(row):
                    public._invalid()
                if _INTENT in body:
                    candidate = parse_delegated_context(body)
                    if candidate.key != key:
                        public._invalid()
                    if context is not None and context.body != candidate.body:
                        return None, public.DecisionObservation('conflict', 'different_service_payload')
                    context = candidate
                else:
                    receipt_key, _ = parse_delegated_receipt(body)
                    if receipt_key != key:
                        public._invalid()
            if v1 and v2:
                result = None, public.DecisionObservation('conflict', 'different_decision_profile')
            elif v1 and (expected_root is None or matching_v1_root):
                result = None, public.DecisionObservation('not_observed', 'original_decision_profile')
            elif context is None:
                result = None, public.DecisionObservation(
                    'unknown' if expected_root is not None else 'receipt_without_context' if v2 else 'not_observed',
                    'decision_context_missing' if expected_root is not None or v2 else 'public_observation_only')
            elif expected_root is not None and delegated_decision_root(context) != expected_root:
                result = None, public.DecisionObservation('conflict', 'decision_root_changed')
            else:
                observed = _observe(rows, actor, context, issue_url=issue_url,
                                    check_deadline=lambda: client._request_timeout(30))
                observed = _direct(client, canonical, issue_url, rows, actor, context, observed, None, None)
                result = context, observed
        return result
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, UnicodeError):
        return None, public.DecisionObservation('unknown', 'source_unavailable')
