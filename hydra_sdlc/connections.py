"""Ordered project connection changes through one trusted host configuration.

Invocation authority belongs to the installed launcher/operator. Request JSON
supplies data, never a path, provider, quiescence proof or workflow grant.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import copy
import json
import os
from pathlib import Path
import stat
import time
import uuid

from . import projection as p
from .control import (_config_parent, _config_fingerprint, _check_config_binding,
                      _repository, control_from_config, load_host_config)
from .github import GitHub, GitHubError
from .operations import (MAX_PROJECTS, MAX_REVISION, OperationDenied,
                         _WriteAttempt, _pairs, _invalid_constant)
from .project import load_project
from .runtime_identity import _configuration, capture_runtime_identity


MAX_INPUT_BYTES = MAX_CONFIG_BYTES = 65536
OPERATIONS = {'connect', 'update', 'disconnect', 'finalize_disconnect'}


@dataclass(frozen=True)
class ConnectionQuiescence:
    """Trusted provider observation, tied to the exact preflight scope.

    Complete means scoped writers, work, pending effects, tasks, schedules and
    resources have ended or have qualified handoff, with preservation confirmed.
    Inventory coverage alone does not qualify. This is not a public DTO
    or a proof accepted from stdin. The provider must own its source boundary.
    """
    config_digest: str
    admission_revision: int
    repository: str | None
    purpose: str
    complete: bool
    active: bool
    pending: bool


@dataclass(frozen=True)
class NativeProjectBinding:
    repository_id: int
    host_alias: str
    native_project_id: str


@dataclass
class _ConfigAttempt:
    replacement_attempted: bool = False


class _Failure(Exception):
    def __init__(self, reason, outcome='rejected'):
        self.reason, self.outcome = reason, outcome


def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def _name(value):
    p.require(type(value) is str and _repository(value) == value)
    return value


def _request(raw):
    p.require(type(raw) in {str, bytes})
    data = raw.encode('utf-8') if type(raw) is str else raw
    p.require(len(data) <= MAX_INPUT_BYTES)
    value = json.loads(data.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_invalid_constant)
    p.obj(value, 'connection_schema request_id operation repository replacement_name native_project_id expected')
    p.require(type(value['connection_schema']) is int and value['connection_schema'] == 1)
    p.uid(value['request_id']);p.one(value['operation'], OPERATIONS);_name(value['repository'])
    expected = value['expected']
    p.obj(expected, 'config_digest admission_revision repository_id')
    p.digest(expected['config_digest']);p.integer(expected['admission_revision'])
    p.nullable(expected['repository_id'], lambda v: p.integer(v, 1))
    if value['replacement_name'] is not None:
        _name(value['replacement_name'])
        p.require(value['operation'] == 'update' and value['replacement_name'] != value['repository'])
    if value['native_project_id'] is not None:
        p.require(value['operation'] in {'connect', 'update'})
        p.text(value['native_project_id'], 256)
    return value


def _digest(cfg):
    value = capture_runtime_identity(cfg)['config_digest']
    if value is None:
        raise _Failure('connection_config_invalid')
    return value


def _settings(cfg):
    rows = cfg.get('project_connections', {})
    return [{'repository': repo, 'desired': rows.get(repo, {}).get('desired'),
             'native_project_id': rows.get(repo, {}).get('native_project_id')}
            for repo in sorted(cfg['repos'])]


def _signature(path):
    parent, binding = _config_parent(path)
    fd = None
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1 or info.st_mode & 0o022 or info.st_size > MAX_CONFIG_BYTES):
            raise _Failure('connection_config_invalid')
        _check_config_binding(path, binding, info)
        return _config_fingerprint(info), binding
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent)


def _current(path, original, fingerprint, binding):
    cfg = load_host_config(path)
    observed, parents = _signature(path)
    if (observed != fingerprint or parents != binding
            or _configuration(cfg) != _configuration(original)):
        raise _Failure('connection_config_changed')
    return cfg


def _encode_config(cfg):
    """Serialize only validated, already normalized host configuration values."""
    def scalar(value):
        if type(value) is bool:
            return 'true' if value else 'false'
        if type(value) in {str, int}:
            return json.dumps(value, ensure_ascii=False)
        if type(value) is list:
            return '[' + ', '.join(scalar(item) for item in value) + ']'
        raise _Failure('connection_config_invalid')

    lines = []
    def table(value, path=()):
        for key in sorted(value):
            if type(value[key]) is not dict:
                lines.append(json.dumps(key) + ' = ' + scalar(value[key]))
        for key in sorted(value):
            if type(value[key]) is dict:
                child = path + (key,)
                lines.append('\n[' + '.'.join(json.dumps(part) for part in child) + ']')
                table(value[key], child)
    _configuration(cfg)
    table(cfg)
    raw = ('\n'.join(lines) + '\n').encode('utf-8')
    if len(raw) > MAX_CONFIG_BYTES:
        raise _Failure('connection_config_limit')
    return raw


def _replace_config(path, cfg, fingerprint, binding, attempt):
    payload = _encode_config(cfg)
    parent, actual_binding = _config_parent(path)
    fd = None
    name = '.' + path.name + '.' + uuid.uuid4().hex + '.tmp'
    try:
        if actual_binding != binding:
            raise _Failure('connection_config_changed')
        visible = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if _config_fingerprint(visible) != fingerprint:
            raise _Failure('connection_config_changed')
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=parent)
        offset = 0
        while offset < len(payload):
            written = os.write(fd, payload[offset:])
            if written <= 0:
                raise OSError('Incomplete configuration write')
            offset += written
        os.fsync(fd)
        current, current_binding = _signature(path)
        if current != fingerprint or current_binding != binding:
            raise _Failure('connection_config_changed')
        attempt.replacement_attempted = True
        os.replace(name, path.name, src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
        observed = load_host_config(path)
        _, observed_binding = _signature(path)
        if observed_binding != binding or _configuration(observed) != _configuration(cfg):
            raise _Failure('connection_config_changed', 'unknown')
        return observed
    finally:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(name, dir_fd=parent)
        except FileNotFoundError:
            pass
        finally:
            os.close(parent)


def _resource_clear(provider, cfg, repository, purpose, revision):
    if provider is None:
        raise _Failure('connection_resource_coverage_unknown', 'waiting')
    value = provider(cfg, repository, purpose, revision)
    if (type(value) is not ConnectionQuiescence or value.config_digest != _digest(cfg)
            or type(value.admission_revision) is not int or value.admission_revision != revision
            or value.repository != repository or value.purpose != purpose
            or value.complete is not True or value.active is not False or value.pending is not False):
        raise _Failure('connection_resource_coverage_unknown', 'waiting')


def _repository_source(client, cfg, request):
    name = request['replacement_name'] or request['repository']
    with client.read_budget(seconds=45, requests=4096):
        actor = client._identity()
        p.integer(actor.get('id'), 1)
        p.require(actor.get('login') == client.user)
        identity = client.repository(name)
        rid = identity.get('id');p.integer(rid, 1)
        p.require(type(identity.get('full_name')) is str and identity['full_name'].lower() == name)
        expected = request['expected']['repository_id']
        if expected is not None and expected != rid:
            raise _Failure('connection_repository_mismatch')
        for previous in cfg['repos']:
            if previous == request['repository'] and request['replacement_name'] is not None:
                # Only the explicit rename witness may follow its old address.
                # Ordinary repository reads keep their canonical-name fence.
                observed = client.api('GET', '/repos/' + previous)
                p.require(type(observed) is dict and type(observed.get('full_name')) is str
                          and observed['full_name'].lower() in {previous, name})
            else:
                observed = client.repository(previous)
            p.integer(observed.get('id'), 1)
            if previous == request['repository']:
                if observed['id'] != rid:
                    raise _Failure('connection_repository_mismatch')
            elif (observed['id'] == rid or type(observed.get('full_name')) is not str
                    or observed['full_name'].lower() != previous):
                raise _Failure('connection_repository_conflict')
        project = load_project(client, name)
        p.require(project['repository_id'] == rid and project['repository'].lower() == name)
        final = client.repository(name)
        p.require(final.get('id') == rid and type(final.get('id')) is int
                  and type(final.get('full_name')) is str and final['full_name'].lower() == name)
    now = _now()
    observed = {'key': 'github:repository-request:' + name,
        'resource': {'source': 'github', 'kind': 'repository', 'id': str(rid)},
        'revision': None, 'observed_at': now, 'last_attempt_at': now, 'availability': 'current',
        'coverage': {'state': 'complete', 'scope': 'repository-address:' + name,
                     'returned_count': 1, 'total_count': 1, 'next_cursor': None, 'reason': None},
        'reason': None, 'value': {'numeric_id': rid, 'full_name': final['full_name'],
            'url': 'https://github.com/' + final['full_name'],
            'contract_ref': {'path': '.hydra.toml', 'revision': project['revision']}}}
    p.observation(observed)
    return rid, observed


def _proposal(cfg, request):
    value = copy.deepcopy(dict(cfg))
    value['connection_schema'] = 1
    value.setdefault('project_connections', {})
    value.setdefault('project_threads', {})
    operation, repo = request['operation'], request['repository']
    target = request['replacement_name'] or repo
    if operation != 'connect' and repo not in cfg['repos']:
        raise _Failure('connection_repository_unregistered')
    if (operation == 'connect' and repo in cfg['repos']
            and cfg.get('project_connections', {}).get(repo, {}).get('desired') == 'connected'):
        raise _Failure('connection_already_registered')
    if operation in {'connect', 'update'}:
        if target != repo and target in cfg['repos']:
            raise _Failure('connection_repository_conflict')
        row = dict(value['project_connections'].get(repo, {'desired': 'connected'}))
        if operation == 'connect':
            row['desired'] = 'connected'
        row.pop('native_project_id', None)
        if request['native_project_id'] is not None:
            row['native_project_id'] = request['native_project_id']
        if target != repo:
            value['repos'].remove(repo)
            value['project_connections'].pop(repo, None)
            if repo in value['project_threads']:
                value['project_threads'][target] = value['project_threads'].pop(repo)
        if target not in value['repos']:
            value['repos'].append(target)
        value['project_connections'][target] = row
    elif operation == 'disconnect':
        value['project_connections'].setdefault(repo, {})['desired'] = 'disconnect_requested'
    else:
        if cfg.get('project_connections', {}).get(repo, {}).get('desired') != 'disconnect_requested':
            raise _Failure('connection_disconnect_required')
        value['repos'].remove(repo)
        value['project_connections'].pop(repo, None)
        value['project_threads'].pop(repo, None)
    value['repos'].sort()
    _configuration(value)
    return value


def _stop_state(control, snapshot, before, held, attempt, cfg, target, migration):
    value = copy.deepcopy(snapshot)
    if migration:
        value['version'] = 2
        value['connection_config'] = {'profile': 1, 'path': getattr(cfg, '_source_path')}
        for repo in cfg['repos']:
            value['projects'][repo] = 'stopped'
    if target is not None:
        value['projects'][target] = 'stopped'
    if value == snapshot:
        return snapshot
    if snapshot['revision'] == MAX_REVISION:
        raise _Failure('operation_state_revision_exhausted')
    if len(value['projects']) > MAX_PROJECTS:
        raise _Failure('operation_state_limit')
    value['revision'] += 1
    value['updated_at'] = _now()
    return control._write_snapshot(value, before, held, attempt)


def _read_back(reply, path, control, candidate=None):
    target = reply.pop('_target', reply['repository'])
    try:
        current = load_host_config(path)
        reply['after_config_digest'] = _digest(current)
        reply['configured'] = _settings(current)
        if candidate is not None:
            reply['config_applied'] = _configuration(current) == _configuration(candidate)
    except (ValueError, OSError, RuntimeError, _Failure):
        reply['after_config_digest'] = None
        reply['configured'] = None
        reply['config_applied'] = None
    if control is not None:
        try:
            snapshot = control.snapshot(blocking=False)
            reply['admission_revision'] = snapshot['revision']
            if candidate is not None and target is not None:
                reply['stopped_applied'] = snapshot['projects'].get(target) == 'stopped'
        except (OperationDenied, OSError):
            reply['admission_revision'] = None
            if candidate is not None:
                reply['stopped_applied'] = None
    return reply


def execute_connection(config_path, action, raw=None, *, github=None, quiescence=None, native_project=None):
    """One source action; callbacks are trusted sources, never request parameters."""
    reply = {'connection_schema': 1, 'request_id': None, 'operation': None, 'repository': None,
        'outcome': 'rejected', 'reason': None, 'runtime': capture_runtime_identity(),
        'before_config_digest': None, 'after_config_digest': None, 'admission_revision': None,
        'config_applied': False, 'stopped_applied': False, 'finalized': False,
        'configured': None, 'proposed_configured': None, 'observations': []}
    control = candidate = None
    config_attempt, admission_attempt = _ConfigAttempt(), _WriteAttempt()
    deadline = time.monotonic() + 45
    try:
        if action not in {'status', 'preview', 'apply'}:
            raise _Failure('invalid_connection_action')
        request = None if action == 'status' else _request(raw)
        if request is not None:
            reply.update({key: request[key] for key in ('request_id', 'operation', 'repository')})
        path = Path(config_path).expanduser().absolute()
        cfg = load_host_config(path)
        fingerprint, binding = _signature(path)
        control = control_from_config(cfg)
        snapshot = control.snapshot(blocking=False)
        reply.update(runtime=capture_runtime_identity(cfg, control), before_config_digest=_digest(cfg),
                     admission_revision=snapshot['revision'], configured=_settings(cfg))
        if action == 'status':
            reply['outcome'] = 'preview'
            return _read_back(reply, path, control)
        expected = request['expected']
        if expected['config_digest'] != _digest(cfg) or expected['admission_revision'] != snapshot['revision']:
            raise _Failure('connection_expected_changed')
        operation, repository = request['operation'], request['repository']
        if action == 'apply' and operation in {'connect', 'update'} and expected['repository_id'] is None:
            raise _Failure('connection_repository_id_required')
        if snapshot['version'] == 2 and snapshot['connection_config']['path'] != str(path):
            raise _Failure('connection_binding_required')
        candidate = _proposal(cfg, request)
        _encode_config(candidate)
        if operation in {'connect', 'update'}:
            rid, observed = _repository_source(github or GitHub(), cfg, request)
            reply['observations'] = [observed]
            locator = request['native_project_id']
            if locator is not None:
                value = native_project(cfg, repository, locator) if native_project is not None else None
                if (type(value) is not NativeProjectBinding or type(value.repository_id) is not int
                        or value.repository_id != rid or value.host_alias != cfg['host_alias']
                        or value.native_project_id != locator):
                    raise _Failure('connection_native_source_unavailable', 'waiting')
        if action == 'preview':
            reply.update(outcome='preview', proposed_configured=_settings(candidate))
            return _read_back(reply, path, control)
        migration = snapshot['version'] == 1 or cfg.get('connection_schema') != 1
        if migration:
            if snapshot['global_mode'] != 'stopped':
                raise _Failure('connection_migration_requires_stopped_host', 'waiting')
            _resource_clear(quiescence, cfg, None, 'migration', snapshot['revision'])
        elif (operation in {'update', 'finalize_disconnect'}
                or operation == 'connect' and (repository in cfg['repos'] or repository in snapshot['projects'])):
            if snapshot['projects'].get(repository) != 'stopped':
                raise _Failure('connection_requires_stopped_project', 'waiting')
            _resource_clear(quiescence, cfg, repository, operation, snapshot['revision'])
        destination = request['replacement_name']
        if destination is not None and destination in snapshot['projects']:
            if snapshot['projects'][destination] != 'stopped':
                raise _Failure('connection_rename_destination_not_stopped', 'waiting')
            _resource_clear(quiescence, cfg, destination, operation, snapshot['revision'])
        if time.monotonic() >= deadline:
            raise _Failure('connection_observation_expired', 'waiting')
        reply['_target'] = request['replacement_name'] or repository
        with control._locked(exclusive=True, create=True, blocking=False) as held:
            _current(path, cfg, fingerprint, binding)
            current, before = control._read(held)
            if current != snapshot:
                raise _Failure('connection_expected_changed')
            if time.monotonic() >= deadline:
                raise _Failure('connection_observation_expired', 'waiting')
            if migration or operation in {'connect', 'update'}:
                target = reply['_target'] if operation in {'connect', 'update', 'disconnect'} else None
                current = _stop_state(control, current, before, held, admission_attempt, cfg, target, migration)
            if _configuration(candidate) != _configuration(cfg):
                _replace_config(path, candidate, fingerprint, binding, config_attempt)
            if operation == 'disconnect' and not migration:
                _stop_state(control, current, before, held, admission_attempt, cfg, repository, False)
        reply.update(outcome='applied', reason=None, finalized=operation == 'finalize_disconnect')
        reply = _read_back(reply, path, control, candidate)
        if reply['config_applied'] is not True or (operation != 'finalize_disconnect' and reply['stopped_applied'] is not True):
            reply.update(outcome='unknown', reason='connection_readback_unavailable', finalized=None)
        return reply
    except _Failure as exc:
        reply.update(outcome=exc.outcome, reason=exc.reason)
    except (ValueError, TypeError, UnicodeError, RecursionError, KeyError):
        reply.update(outcome='rejected', reason='invalid_connection_request_or_source')
    except (GitHubError, RuntimeError, OSError):
        reply.update(outcome='waiting', reason='connection_source_unavailable')
    changed = config_attempt.replacement_attempted or admission_attempt.replacement_completed or admission_attempt.replacement_unknown
    if changed:
        reply.update(outcome='unknown', reason='connection_partial_effect', finalized=None)
    if control is None:
        return reply
    return _read_back(reply, Path(config_path).expanduser().absolute(), control, candidate if changed else None)
