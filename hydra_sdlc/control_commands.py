"""Internal admission command boundary; no transport or native authority adapter.

The caller supplies installed dependencies and a current, scoped authorization
context outside the command payload. Constructing that context is not itself
authentication. No public endpoint or default authority is provided here.
"""
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import uuid

from .control import control_from_config, load_host_config
from .operations import MAX_PROJECTS, MAX_REVISION, OperationDenied, OperationUncertain
from .runtime_identity import capture_runtime_identity


_COMMAND_KEYS = {'command_schema', 'request_id', 'binding_epoch', 'action', 'target',
                 'expected', 'effect_key', 'parameters'}
_EXPECTED_KEYS = {'runtime_key', 'admission_revision', 'source_checks', 'assignment'}
_ACTIONS = {'admission_set', 'work_create', 'workflow_step', 'native_control', 'cleanup', 'open_record'}
_IDENTITY_KEYS = ('version', 'code_digest', 'config_digest', 'control_binding_digest')
_DIGEST = re.compile(r'[0-9a-f]{64}\Z')
_STORE_REASONS = frozenset({
    'stale_revision', 'precondition_required', 'invalid_command', 'host_paused', 'host_stopped',
    'operation_state_busy', 'operation_state_unsafe', 'operation_state_invalid',
    'operation_state_unavailable', 'operation_state_changed', 'operation_state_revision_exhausted',
    'operation_state_repository_invalid', 'operation_state_repository_unregistered',
    'operation_state_action_invalid', 'operation_state_path_invalid',
})


@dataclass(frozen=True)
class AdmissionCallContext:
    """A trusted adapter's current grant, never decoded from command JSON."""
    surface: str
    binding_epoch: str | None
    repository_ids: frozenset[int]


class InvalidAdmissionCommand(ValueError):
    def __init__(self):
        super().__init__('invalid_command')


def _uuid(value):
    if type(value) is not str or len(value) != 36:
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _integer(value, minimum=0):
    return type(value) is int and minimum <= value <= MAX_REVISION


def _parse(command):
    """Read safe common identities before interpreting the supported action body."""
    if (type(command) is not dict or set(command) != _COMMAND_KEYS
            or not _integer(command['command_schema'], 1)
            or not _uuid(command['request_id'])
            or (command['binding_epoch'] is not None and not _uuid(command['binding_epoch']))
            or type(command['action']) is not str or command['action'] not in _ACTIONS):
        raise InvalidAdmissionCommand()
    target, expected, parameters = command['target'], command['expected'], command['parameters']
    if type(target) is not dict:
        raise InvalidAdmissionCommand()
    admission_target = (type(target.get('kind')) is str and (target == {'kind': 'host'} or
        (set(target) == {'kind', 'repository_id'} and target['kind'] == 'repository'
         and _integer(target['repository_id'], 1))))
    repository_target = (set(target) in ({'repository_id'}, {'repository_id', 'issue_number'})
        and _integer(target['repository_id'], 1)
        and ('issue_number' not in target or _integer(target['issue_number'], 1)))
    if not admission_target and not repository_target:
        raise InvalidAdmissionCommand()
    if (type(expected) is not dict or set(expected) != _EXPECTED_KEYS or type(parameters) is not dict):
        raise InvalidAdmissionCommand()
    if command['command_schema'] != 1 or command['action'] != 'admission_set':
        # A recognizable common header can receive an exact unsupported reply.
        # Future action bodies are neither interpreted, traversed nor echoed.
        return {key: (dict(target) if key == 'target' else None if key in
                      {'expected', 'parameters', 'effect_key'} else value)
                for key, value in command.items()}
    if not admission_target:
        raise InvalidAdmissionCommand()
    key = expected['runtime_key']
    if key is not None and (type(key) is not str or not 1 <= len(key) <= 1024
                            or any(ord(c) < 32 or ord(c) >= 127 for c in key)):
        raise InvalidAdmissionCommand()
    if ((expected['admission_revision'] is not None and not _integer(expected['admission_revision']))
            or type(expected['source_checks']) is not list or expected['source_checks'] != []
            or expected['assignment'] is not None or command['effect_key'] is not None
            or type(parameters) is not dict or set(parameters) != {'mode'}
            or type(parameters['mode']) is not str or parameters['mode'] not in {'running', 'paused', 'stopped'}):
        raise InvalidAdmissionCommand()
    # Dependency callbacks must not be able to change the validated request later.
    return copy.deepcopy(command)


def _runtime_key(runtime):
    if type(runtime) is not dict or runtime.get('identity_reason') is not None:
        return None
    version = runtime.get('version')
    if (type(version) is not str or not 1 <= len(version) <= 128
            or any(ord(c) < 32 or ord(c) >= 127 for c in version)
            or any(type(runtime.get(k)) is not str or not _DIGEST.fullmatch(runtime[k])
                   for k in _IDENTITY_KEYS[1:])):
        return None
    return json.dumps([runtime[k] for k in _IDENTITY_KEYS], separators=(',', ':'))


def _context(provider, command):
    try:
        context = provider()
    except Exception:
        return None, 'authority_unavailable'
    if (type(context) is not AdmissionCallContext or type(context.surface) is not str
            or context.surface not in {'bridge', 'native'}
            or (context.surface == 'bridge' and not _uuid(context.binding_epoch))
            or (context.surface == 'native' and context.binding_epoch is not None)
            or type(context.repository_ids) is not frozenset
            or len(context.repository_ids) > MAX_PROJECTS
            or any(not _integer(value, 1) for value in context.repository_ids)):
        return None, 'authority_unavailable'
    if context.binding_epoch != command['binding_epoch']:
        return context, 'stale_binding'
    return context, None


def _repository(github, names, identifier):
    failed = False
    for name in names:
        try:
            row = github.repository(name)
            if (type(row) is not dict or not _integer(row.get('id'), 1)
                    or type(row.get('full_name')) is not str or row['full_name'].lower() != name):
                failed = True
                continue
            if row['id'] == identifier:
                return name, None
        except Exception:
            failed = True
    return None, 'repository_unavailable' if failed else 'target_unregistered'


def _observation(command, runtime, snapshot, repository, suffix):
    key = f"command:{command['request_id']}:admission-{suffix}"
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
    revision = {'kind': 'monotonic', 'value': str(snapshot['revision'])}
    mode = snapshot['global_mode']
    project_mode = snapshot['projects'].get(repository, 'running')
    reason = ('host_' + mode if mode != 'running' else
              'project_' + project_mode if project_mode != 'running' else None)
    return {
        'key': key,
        'resource': {'source': 'hydra', 'kind': 'admission', 'id': runtime['control_binding_digest']},
        'revision': revision, 'observed_at': now, 'last_attempt_at': now,
        'availability': 'current',
        'coverage': {'state': 'complete', 'scope': key, 'returned_count': 1,
                     'total_count': 1, 'next_cursor': None, 'reason': None},
        'reason': None,
        'value': {'revision': snapshot['revision'], 'global_mode': mode,
                  'project_overrides': dict(snapshot['projects']), 'gate_reason': reason},
    }


def _reply(command, runtime, epoch, outcome, reason, *, observation=None, required_next='refresh'):
    observations = [] if observation is None else [observation]
    refs = [{'observation_key': o['key'], 'revision': dict(o['revision'])} for o in observations]
    applied = outcome == 'applied'
    return {
        'command_schema': 1, 'runtime': runtime, 'binding_epoch': epoch,
        'request': {
            'request_id': command['request_id'], 'action': command['action'],
            'target': dict(command['target']), 'outcome': outcome, 'reason': reason,
            'effect_refs': [dict(observation['resource'])] if applied else [],
            'observed_refs': refs,
            'receipt': {'kind': 'admission', 'readback': refs[0]} if applied else None,
            'required_next': 'none' if applied else required_next,
        },
        'observations': observations,
    }


def execute_admission_command(config_path, command, *, context_provider, github):
    """Apply one repository admission request, with no continuation or retry."""
    command = _parse(command)
    context, reason = _context(context_provider, command)
    epoch = context.binding_epoch if context else None
    try:
        cfg = load_host_config(config_path)
        control = control_from_config(cfg)
    except (OSError, ValueError, OperationDenied):
        return _reply(command, capture_runtime_identity(), epoch, 'rejected', 'host_config_unavailable')
    runtime = capture_runtime_identity(cfg, control)
    if reason:
        return _reply(command, runtime, epoch, 'rejected', reason)
    if (command['command_schema'] != 1 or command['action'] != 'admission_set'
            or command['target']['kind'] != 'repository' or command['parameters']['mode'] == 'stopped'):
        return _reply(command, runtime, epoch, 'rejected', 'unsupported_operation', required_next='open_source')
    if command['target']['repository_id'] not in context.repository_ids:
        return _reply(command, runtime, epoch, 'rejected', 'authority_denied')
    expected = command['expected']
    if expected['runtime_key'] is None or expected['admission_revision'] is None:
        return _reply(command, runtime, epoch, 'rejected', 'precondition_required')
    key = _runtime_key(runtime)
    if key is None or key != expected['runtime_key']:
        return _reply(command, runtime, epoch, 'rejected', 'runtime_unavailable' if key is None else 'stale_runtime')
    repository, reason = _repository(github, cfg['repos'], command['target']['repository_id'])
    if reason:
        return _reply(command, runtime, epoch,
                      'unknown' if reason == 'repository_unavailable' else 'rejected', reason)
    # Remote lookup may take time. Re-read the installed binding and current grant
    # without extending the admission lock around network work.
    context, reason = _context(context_provider, command)
    epoch = context.binding_epoch if context else None
    if reason:
        return _reply(command, runtime, epoch, 'rejected', reason)
    if command['target']['repository_id'] not in context.repository_ids:
        return _reply(command, runtime, epoch, 'rejected', 'authority_denied')
    try:
        current_cfg = load_host_config(config_path)
        current_control = control_from_config(current_cfg)
    except (OSError, ValueError, OperationDenied):
        return _reply(command, runtime, epoch, 'rejected', 'host_config_unavailable')
    current_runtime = capture_runtime_identity(current_cfg, current_control)
    current_key = _runtime_key(current_runtime)
    if current_key is None or current_key != expected['runtime_key']:
        return _reply(command, current_runtime, epoch, 'rejected',
                      'runtime_unavailable' if current_key is None else 'stale_runtime')
    mode = command['parameters']['mode']
    try:
        snapshot = current_control.set_mode_if_current(
            'pause' if mode == 'paused' else 'resume', repository,
            expected_revision=expected['admission_revision'], blocking=False)
    except OperationUncertain as exc:
        observation = (_observation(command, current_runtime, exc.observation, repository, 'current')
                       if exc.observation is not None else None)
        return _reply(command, current_runtime, epoch, 'unknown', 'operation_state_unknown',
                      observation=observation, required_next='reconcile')
    except OperationDenied as exc:
        reason = exc.reason if exc.reason in _STORE_REASONS else 'operation_state_unavailable'
        reason = 'revision_exhausted' if reason == 'operation_state_revision_exhausted' else reason
        return _reply(command, current_runtime, epoch,
                      'waiting' if reason == 'operation_state_busy' else 'rejected', reason)
    reason = None
    if snapshot['revision'] == expected['admission_revision']:
        reason = ('stronger_mode_retained' if mode == 'paused'
                  and snapshot['projects'].get(repository) == 'stopped' else 'already_satisfied')
    return _reply(command, current_runtime, epoch, 'applied', reason,
                  observation=_observation(command, current_runtime, snapshot, repository, 'readback'))
