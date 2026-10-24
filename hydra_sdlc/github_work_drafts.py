"""Bounded, fresh GitHub draft observations, without creation authority.

The caller owns this client and supplies its approved read-repository mapping
and selected publisher identity. A source result is transient input data. It
does not prove human delegation, duplicate absence, disclosure permission or
readiness to dispatch; those must be checked independently before any effect.
"""
from dataclasses import dataclass, field
import json

from .github import GitHubError, _repo
from .work_drafts import (DraftSource, WorkCreateDraftRef, _draft_from_comment,
    parse_draft_ref, select_github_draft, validate_draft_ref)
from .work_records import (WorkRecordError, _canonical, _hex, _integer, _require, _text)


MAX_OBSERVATION_BYTES = 8_000_000


@dataclass(frozen=True)
class DraftRead:
    status: str
    reason: str
    source: DraftSource | None = field(default=None, repr=False)


class _Changed(Exception):
    pass


def _bounded(value):
    try:
        document = _canonical(value)
        if len(document.encode('utf-8')) > MAX_OBSERVATION_BYTES:
            raise GitHubError('Draft observation exceeds bound')
        return json.loads(document)
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        raise GitHubError('Invalid draft observation') from exc


def _repository_signature(value):
    return {key: value.get(key) for key in ('id', 'full_name', 'private', 'visibility')}


def _issue_signature(value):
    return {key: value.get(key) for key in
            ('id', 'number', 'url', 'repository_url', 'title', 'body', 'state')}


def read_work_draft(client, repositories, reference, *, author, target_repository_id, draft_digest):
    try:
        _require(type(repositories) is dict and bool(repositories))
        _require(all(_integer(key) and type(value) is str for key, value in repositories.items()))
        names = {key: _repo(value) for key, value in repositories.items()}
        _require(_integer(target_repository_id) and target_repository_id in names and _hex(draft_digest, 64))
        _require(type(author) is dict and _integer(author.get('id')) and _text(author.get('login'), 100))
        publisher = {'id': author['id'], 'login': author['login']}
        selected = (validate_draft_ref(reference) if type(reference) is WorkCreateDraftRef
                    else parse_draft_ref(reference))
        ref = selected.value
        if ref['kind'] == 'native_preparation':
            return DraftRead('unavailable', 'native_draft_source_unavailable')
        _require(ref['repository_id'] in names)
    except (WorkRecordError, GitHubError, ValueError, TypeError, UnicodeError):
        return DraftRead('invalid', 'invalid_draft_source_request')

    previous_hook = client._credential_selected
    had_local = '_credential_selected' in client.__dict__
    previous_local = client.__dict__.get('_credential_selected')
    fingerprint = None

    def credential_selected(value):
        nonlocal fingerprint
        previous_hook(value)
        if type(value) is not bytes or not value:
            raise GitHubError('Unknown draft credential')
        if fingerprint is None:
            fingerprint = value
        elif value != fingerprint:
            raise _Changed()

    client._credential_selected = credential_selected
    try:
        with client.read_budget(seconds=45, requests=32):
            def read(callback, *args):
                value = callback(*args)
                client._request_timeout(45)
                if fingerprint is not None and client._authenticated_fingerprint != fingerprint:
                    raise _Changed()
                return _bounded(value)

            identity = read(client._identity)
            if (not _integer(identity.get('id')) or identity.get('login') != client.user
                    or fingerprint is None):
                raise GitHubError('Unknown draft reader identity')
            repos, issues = {}, {}

            def repository(identifier, *, fresh=False):
                _require(identifier in names, 'source_scope_unknown')
                if identifier not in repos or fresh:
                    value = read(client.repository, names[identifier])
                    if (type(value.get('id')) is not int or value['id'] != identifier
                            or type(value.get('full_name')) is not str
                            or value['full_name'].casefold() != names[identifier].casefold()):
                        raise _Changed()
                    if fresh and _repository_signature(value) != _repository_signature(repos[identifier]):
                        raise _Changed()
                    if not fresh:
                        repos[identifier] = value
                    return value
                return repos[identifier]

            def issue(identifier, number, *, fresh=False):
                name = repository(identifier)['full_name']
                value = read(client.issue, name, number)
                root = 'https://api.github.com/repos/' + name
                _require(type(value) is dict and _integer(value.get('id'))
                         and type(value.get('number')) is int and value['number'] == number
                         and value.get('url') == root + '/issues/' + str(number)
                         and value.get('repository_url') == root and 'pull_request' not in value,
                         'identity_mismatch')
                key = (identifier, number)
                if fresh:
                    if _issue_signature(value) != _issue_signature(issues[key]):
                        raise _Changed()
                else:
                    issues[key] = value
                return value

            repository(target_repository_id)
            container = repository(ref['repository_id'])
            root = 'https://api.github.com/repos/' + container['full_name']

            def comment():
                return read(client.api, 'GET', '/repos/' + container['full_name']
                            + '/issues/comments/' + str(ref['comment_id']))

            initial = comment()
            parsed = _draft_from_comment(initial, ref, publisher, root)
            _require(parsed.digest == draft_digest, 'draft_digest_mismatch')
            value = parsed.value
            _require(value['target_repository_id'] == target_repository_id, 'target_mismatch')
            origin = value['source_ref']
            _require(origin['kind'] == 'github_issue', 'private_source_in_public_draft')
            locations = {(origin['repository_id'], origin['issue_number'])}
            goal = value['goal']
            if goal is not None:
                locations.add((goal['repository_id'], goal['issue_number']))
            _require((ref['repository_id'], ref['issue_number']) in locations, 'draft_container_mismatch')
            for identifier, number in sorted(locations):
                issue(identifier, number)
            original = select_github_draft(initial, selected, author=publisher,
                source_issues=issues, target_repository_id=target_repository_id)
            for identifier in sorted(repos):
                repository(identifier, fresh=True)
            for identifier, number in sorted(issues):
                issue(identifier, number, fresh=True)
            final = select_github_draft(comment(), selected, author=publisher,
                source_issues=issues, target_repository_id=target_repository_id)
            if final != original:
                raise _Changed()
            client._request_timeout(45)
            if client._authenticated_fingerprint != fingerprint:
                raise _Changed()
            return DraftRead('available', 'draft_source_only', final)
    except _Changed:
        return DraftRead('changed', 'draft_source_changed')
    except WorkRecordError as exc:
        changed = {'draft_changed', 'source_changed', 'goal_changed', 'edited_or_unknown', 'draft_digest_mismatch'}
        return DraftRead('changed' if exc.reason in changed else 'invalid', exc.reason)
    except (GitHubError, OSError, ValueError, TypeError, KeyError, RecursionError):
        return DraftRead('unavailable', 'draft_source_unavailable')
    finally:
        if had_local:
            client._credential_selected = previous_local
        else:
            del client._credential_selected
