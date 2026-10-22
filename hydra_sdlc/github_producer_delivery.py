"""Bounded existing producer delivery observations, without execution authority.

The caller owns this client for the synchronous read and selects an allowed
repository. A verified delivery is only one input to P11: it does not establish
RequirementRef acceptance, operational observation or permission to dispatch.
No raw provider output, policy body, credential or persistent copy is returned.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import json

from .github import GitHubError, _repo, _sha
from .project import gate_completed_delivery, load_project, post_merge_check_state
from .work_records import WorkRecordError, _canonical, _integer, _issue_ref


MAX_OBSERVATION_BYTES = 8_000_000


@dataclass(frozen=True)
class ProducerDeliveryRead:
    document: str

    @property
    def value(self):
        return json.loads(self.document)


class _Changed(Exception):
    pass


def _require(value):
    if not value:
        raise GitHubError('Invalid producer delivery source')


def _bounded(value):
    try:
        size = len(_canonical(value).encode('utf-8'))
    except (TypeError, ValueError, RecursionError, UnicodeError):
        raise GitHubError('Invalid producer delivery source') from None
    _require(size <= MAX_OBSERVATION_BYTES)
    return value


def _comment(client, repository, source, identity):
    comment = client._progress_comment(repository, source['issue_number'])
    if comment is None:
        return None
    _bounded(comment)
    _require(type(comment) is dict and _integer(comment.get('id')))
    number, identifier = source['issue_number'], comment['id']
    root = 'https://api.github.com/repos/' + repository
    _require(comment.get('issue_url') == f'{root}/issues/{number}'
             and comment.get('url') == f'{root}/issues/comments/{identifier}')
    user = comment.get('user')
    _require(type(user) is dict and _integer(user.get('id'))
             and user['id'] == identity['id'] and user.get('login') == identity['login'])
    record = client._progress_value(repository, number, comment)
    _require(type(record) is dict and type(record.get('version')) is int and record['version'] == 1
             and type(record.get('repository_id')) is int and record['repository_id'] == source['repository_id']
             and type(record.get('issue_number')) is int and record['issue_number'] == number)
    return {'id': identifier, 'record': record}


def _policy(value):
    # The same protected blob may remain current while default-branch commits
    # advance. Compare validated semantics and current actor visibility as well.
    return _canonical({key: item for key, item in value.items() if key != 'revision'})


def _receipt(value, source):
    record = value['record']
    required = {'attempt_id', 'contract_revision', 'spec_revision', 'head', 'published_head',
                'expected_head', 'expected_base', 'checkpoint', 'intake_digest', 'pr_number', 'branch'}
    _require(required <= record.keys())
    _require(all(record.get(key) is not None for key in required))
    _require(record['branch'] == f"hydra/issue-{source['issue_number']}"
             and _integer(record['pr_number'])
             and record['head'] == record['published_head'] == record['expected_head'])
    for key in ('contract_revision', 'spec_revision', 'head', 'expected_base'):
        _sha(record[key])
    # The existing parser validates exact UUID, source digest and checkpoint
    # syntax. None is permitted for in-flight records but not a final receipt.
    return record


def read_delivery(client, repository, source):
    """Read final delivery and current exact-merge CI, never output acceptance.

    Existing source parsers and candidate/squash/CI gates remain authoritative.
    Every call reobserves; a previous verified result is not a dispatch ticket.
    Unsupported or incomplete evidence stays unknown. Issue closure is ignored.
    """
    try:
        _repo(repository)
        _issue_ref(source)
    except (GitHubError, WorkRecordError, TypeError, ValueError):
        raise GitHubError('Invalid producer delivery request') from None
    source = dict(source)

    def result(status, reason, delivery=None):
        return ProducerDeliveryRead(_canonical({'source': source, 'status': status, 'reason': reason,
            'delivery': delivery, 'observed_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}))

    previous_hook = client._credential_selected
    previous_local_hook = client.__dict__.get('_credential_selected')
    had_local_hook = '_credential_selected' in client.__dict__
    selected = None

    def credential_selected(fingerprint):
        nonlocal selected
        previous_hook(fingerprint)
        if selected is None:
            selected = fingerprint
        elif selected != fingerprint:
            raise _Changed()

    client._credential_selected = credential_selected
    try:
        with client.read_budget(seconds=45, requests=128):
            identity = client._identity()
            _require(_integer(identity.get('id')) and identity.get('login') == client.user)
            credential = client._authenticated_fingerprint
            _require(type(credential) is bytes and bool(credential))

            def read(callback, *args, **kwargs):
                value = callback(*args, **kwargs)
                client._request_timeout(45)
                if client._authenticated_fingerprint != credential:
                    raise _Changed()
                return _bounded(value)

            repository_value = read(client.repository, repository)
            _require(type(repository_value.get('id')) is int
                     and repository_value['id'] == source['repository_id']
                     and type(repository_value.get('full_name')) is str
                     and repository_value['full_name'].casefold() == repository.casefold())
            repository = repository_value['full_name']
            issue = read(client.issue, repository, source['issue_number'])
            _require(type(issue) is dict and _integer(issue.get('id')) and 'pull_request' not in issue
                     and type(issue.get('number')) is int and issue['number'] == source['issue_number']
                     and issue.get('url') == f"https://api.github.com/repos/{repository}/issues/{source['issue_number']}"
                     and issue.get('state') in {'open', 'closed'})
            original = read(_comment, client, repository, source, identity)
            if original is None:
                return result('not_delivered', 'delivery_record_missing')
            if original['record'].get('phase') != 'completed' or original['record'].get('pending_action') is not None:
                return result('not_delivered', 'delivery_not_final')
            record = _receipt(original, source)
            config = read(load_project, client, repository, revision=record['contract_revision'])
            current = read(load_project, client, repository)
            if _policy(current) != _policy(config):
                return result('changed', 'delivery_policy_changed')
            observed = read(client.observe, repository, record['pr_number'])
            _require(type(observed) is dict and type(observed.get('pr')) is dict)
            pr = observed['pr']
            observed_repository = observed.get('repository')
            _require(type(observed_repository) is dict and _integer(observed_repository.get('id'))
                     and observed_repository['id'] == source['repository_id'])
            for side in ('head', 'base'):
                endpoint = pr.get(side)
                _require(type(endpoint) is dict and type(endpoint.get('repo')) is dict
                         and _integer(endpoint['repo'].get('id'))
                         and endpoint['repo']['id'] == source['repository_id'])
            _require(type(pr.get('number')) is int and pr['number'] == record['pr_number']
                     and pr.get('url') == f"https://api.github.com/repos/{repository}/pulls/{record['pr_number']}"
                     and type(pr.get('user')) is dict and _integer(pr['user'].get('id'))
                     and read(client.owns_pr, repository, source['issue_number'], pr))
            files = observed.get('changed_files')
            _require(type(files) is list and all(type(row) is dict for row in files))
            paths = list({name for row in files for name in (row.get('filename'), row.get('previous_filename')) if name})
            blockers = gate_completed_delivery(config, observed, record['head'], paths,
                expected_base=record['expected_base'], checkpoint=record['checkpoint'])
            if blockers:
                return result('unknown', 'delivery_evidence_unverified')
            merge_sha = _sha(pr.get('merge_commit_sha'))

            def post_merge():
                value = read(client.observe_commit, repository, merge_sha)
                return post_merge_check_state(config, value, merge_sha)

            def ci_wait(state):
                status, reason = {'pending': ('pending', 'post_merge_checks'),
                    'failed': ('failed', 'post_merge_failed')}.get(state, ('unknown', 'post_merge_evidence_unknown'))
                return result(status, reason)

            state = post_merge()
            if state != 'success':
                return ci_wait(state)
            final = read(_comment, client, repository, source, identity)
            if final != original:
                return result('changed', 'delivery_progress_changed')
            fresh_policy = read(load_project, client, repository)
            if _policy(fresh_policy) != _policy(config):
                return result('changed', 'delivery_policy_changed')
            state = post_merge()
            if state != 'success':
                return ci_wait(state)
            verified = result('verified', 'delivery_only', {'attempt_id': record['attempt_id'],
                'contract_revision': record['contract_revision'], 'spec_revision': record['spec_revision'],
                'source_digest': record['intake_digest'], 'head': record['head'], 'merge_sha': merge_sha,
                'pr_number': record['pr_number'], 'progress_comment_id': original['id']})
            client._request_timeout(45)
            return verified
    except _Changed:
        return result('changed', 'delivery_credential_changed')
    except (GitHubError, WorkRecordError, OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return result('unknown', 'delivery_source_unavailable')
    finally:
        if had_local_hook:
            client._credential_selected = previous_local_hook
        else:
            del client._credential_selected
