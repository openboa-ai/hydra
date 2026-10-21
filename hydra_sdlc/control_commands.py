"""Internal admission command boundary; no transport or native authority adapter.

The caller supplies installed dependencies and a current, scoped authorization
context outside the command payload. Constructing that context is not itself
authentication. No public endpoint or default authority is provided here.
"""
import copy
from dataclasses import dataclass
import json
import math
import re
import uuid
from pathlib import Path

from .control import control_from_config, load_host_config
from .operations import MAX_PROJECTS, MAX_REVISION, OperationDenied, OperationUncertain
from .runtime_identity import capture_runtime_identity


_COMMAND_KEYS = {'command_schema', 'request_id', 'binding_epoch', 'action', 'target',
                 'expected', 'effect_key', 'parameters'}
_EXPECTED_KEYS = {'runtime_key', 'admission_revision', 'source_checks', 'assignment'}
_ACTIONS = {'admission_set', 'work_create', 'workflow_step', 'native_control', 'cleanup', 'open_record'}
_IDENTITY_KEYS = ('version', 'code_digest', 'config_digest', 'control_binding_digest')
# A valid 24,000-code-point summary can use 144,000 JSON bytes when escaped.
# Leave bounded room for the exact envelope and SDK request metadata.
MAX_COMMAND_BYTES = 192 * 1024
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
    operations: frozenset[str] = frozenset({'admission_set'})


@dataclass(frozen=True)
class CheckpointStoppedEvidence:
    """Trusted adapter observation, never a model's stopped-outcome assertion.

    Producing this value requires independent execution/descendant evidence.
    This module supplies no native evidence adapter or default proof.
    """
    repository_id: int
    issue_number: int
    host_alias: str
    control_binding_digest: str
    assignment: tuple[str, str, str, str, str | None]
    state: str
    availability: str
    coverage: str
    descendants: str
    observation_id: str


class InvalidAdmissionCommand(ValueError):
    def __init__(self):
        super().__init__('invalid_command')


def bounded_command(value):
    """Reject non-JSON, recursive or excessive input before dependencies run.

    These are server limits, never request-selected effect or authority limits.
    The iterative walk bounds work before serialization or recursive parsing.
    """
    pending, count, size = [(value, 0)], 0, 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > 2048 or depth > 12:
            raise InvalidAdmissionCommand()
        kind = type(item)
        if kind is dict:
            if len(item) > 2048:
                raise InvalidAdmissionCommand()
            for key, child in item.items():
                if type(key) is not str:
                    raise InvalidAdmissionCommand()
                pending.extend(((key, depth + 1), (child, depth + 1)))
        elif kind is list:
            if len(item) > 2048:
                raise InvalidAdmissionCommand()
            pending.extend((child, depth + 1) for child in item)
        elif kind is str:
            if len(item) > MAX_COMMAND_BYTES:
                raise InvalidAdmissionCommand()
            try:
                size += len(item.encode('utf-8'))
            except UnicodeError:
                raise InvalidAdmissionCommand() from None
        elif kind is int:
            if item.bit_length() > 64:
                raise InvalidAdmissionCommand()
        elif kind is float:
            if not math.isfinite(item):
                raise InvalidAdmissionCommand()
        elif item is not None and kind is not bool:
            raise InvalidAdmissionCommand()
        if size > MAX_COMMAND_BYTES:
            raise InvalidAdmissionCommand()
    try:
        if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')) > MAX_COMMAND_BYTES:
            raise InvalidAdmissionCommand()
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise InvalidAdmissionCommand() from None
    return value


def parse_command_v1(command):
    """Validate the closed supported profiles, retaining unsupported identities."""
    bounded_command(command)
    return _parse(command, checkpoint=type(command) is dict and command.get('action') == 'workflow_step')


async def execute_command_v1(config_path, command, *, context_provider, github, controller,
                             ended_provider=None, unavailable_runtime=None):
    """Thin transport-independent dispatch to existing guarded command cores."""
    parsed = parse_command_v1(command)
    if config_path is None:
        context, reason = _context(context_provider, parsed)
        return _reply(parsed, unavailable_runtime or capture_runtime_identity(),
                      context.binding_epoch if context else None, 'rejected', reason or 'host_config_unavailable')
    if parsed['action'] == 'workflow_step':
        return await execute_checkpoint_command(config_path, command, context_provider=context_provider,
            github=github, controller=controller, ended_provider=ended_provider)
    return execute_admission_command(config_path, command, context_provider=context_provider, github=github)


def command_input_schema():
    """Closed schemas for the two implemented profiles; not capability grants."""
    def obj(properties):
        return {'type': 'object', 'properties': properties, 'required': list(properties),
                'additionalProperties': False}
    integer = {'type': 'integer', 'minimum': 0, 'maximum': MAX_REVISION}
    positive = {**integer, 'minimum': 1}
    uid = {'type': 'string', 'pattern': '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'}
    sha = {'type': 'string', 'pattern': '^[0-9a-f]{40}$'}
    nullable = lambda schema: {'anyOf': [schema, {'type': 'null'}]}
    assignment = obj({'attempt_id': uid, 'step_id': uid, 'head': sha,
                      'contract_revision': sha, 'spec_revision': nullable(sha)})
    common = {'command_schema': {'const': 1}, 'request_id': uid, 'binding_epoch': nullable(uid)}
    expected = {'runtime_key': nullable({'type': 'string', 'minLength': 1, 'maxLength': 1024}),
                'admission_revision': nullable(integer), 'source_checks': {'type': 'array', 'maxItems': 0}}
    admission = obj({**common, 'action': {'const': 'admission_set'},
        'target': obj({'kind': {'const': 'repository'}, 'repository_id': positive}),
        'expected': obj({**expected, 'assignment': {'type': 'null'}}), 'effect_key': {'type': 'null'},
        'parameters': obj({'mode': {'enum': ['running', 'paused']}})})
    checkpoint = obj({**common, 'action': {'const': 'workflow_step'},
        'target': obj({'repository_id': positive, 'issue_number': positive}),
        'expected': obj({**expected, 'assignment': assignment}),
        'effect_key': {'type': 'string', 'pattern': '^checkpoint:[0-9a-f-]{36}:[0-9a-f-]{36}$'},
        'parameters': obj({'operation': {'const': 'checkpoint_only'},
            'outcome': {'enum': ['candidate_ready', 'needs_decision', 'stopped']},
            'summary': {'type': 'string', 'maxLength': 24000}})})
    return {'oneOf': [admission, checkpoint]}


def _uuid(value):
    if type(value) is not str or len(value) != 36:
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _integer(value, minimum=0):
    return type(value) is int and minimum <= value <= MAX_REVISION


def _parse(command, *, checkpoint=False):
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
    supported = 'workflow_step' if checkpoint else 'admission_set'
    if command['command_schema'] != 1 or command['action'] != supported:
        # A recognizable common header can receive an exact unsupported reply.
        # Future action bodies are neither interpreted, traversed nor echoed.
        return {key: (dict(target) if key == 'target' else None if key in
                      {'expected', 'parameters', 'effect_key'} else value)
                for key, value in command.items()}
    if checkpoint:
        if (type(parameters) is not dict or type(parameters.get('operation')) is not str
                or not parameters['operation']):
            raise InvalidAdmissionCommand()
        if parameters['operation'] != 'checkpoint_only':
            # An unknown operation's expected/effect/body are also opaque.
            return {key: (dict(target) if key == 'target' else None if key in
                          {'expected', 'parameters', 'effect_key'} else value)
                    for key, value in command.items()}
    if type(expected) is not dict or type(parameters) is not dict:
        raise InvalidAdmissionCommand()
    supported_target = (repository_target and set(target) == {'repository_id', 'issue_number'}
                        if checkpoint else admission_target)
    if not supported_target or set(expected) != _EXPECTED_KEYS:
        raise InvalidAdmissionCommand()
    key = expected['runtime_key']
    if key is not None and (type(key) is not str or not 1 <= len(key) <= 1024
                            or any(ord(c) < 32 or ord(c) >= 127 for c in key)):
        raise InvalidAdmissionCommand()
    if ((expected['admission_revision'] is not None and not _integer(expected['admission_revision']))
            or type(expected['source_checks']) is not list or expected['source_checks'] != []):
        raise InvalidAdmissionCommand()
    if checkpoint:
        assignment = expected['assignment']
        if (type(assignment) is not dict or set(assignment) !=
                {'attempt_id', 'step_id', 'head', 'contract_revision', 'spec_revision'}
                or not _uuid(assignment['attempt_id']) or not _uuid(assignment['step_id'])
                or any(type(assignment[k]) is not str or not re.fullmatch('[0-9a-f]{40}', assignment[k])
                       for k in ('head', 'contract_revision'))
                or (assignment['spec_revision'] is not None and (type(assignment['spec_revision']) is not str
                    or not re.fullmatch('[0-9a-f]{40}', assignment['spec_revision'])))
                or command['effect_key'] != f"checkpoint:{assignment['attempt_id']}:{assignment['step_id']}"
                or set(parameters) != {'operation', 'outcome', 'summary'}
                or type(parameters['outcome']) is not str
                or parameters['outcome'] not in {'candidate_ready', 'needs_decision', 'stopped', 'failed'}
                or type(parameters['summary']) is not str or len(parameters['summary']) > 24000
                or any(0xD800 <= ord(c) <= 0xDFFF for c in parameters['summary'])):
            raise InvalidAdmissionCommand()
    elif (expected['assignment'] is not None or command['effect_key'] is not None
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
    if (type(context.operations) is not frozenset or not context.operations <=
            {'admission_set', 'workflow_step.checkpoint_only'}):
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


def _observation(command, runtime, snapshot, repository, suffix, observed_at):
    key = f"command:{command['request_id']}:admission-{suffix}"
    revision = {'kind': 'monotonic', 'value': str(snapshot['revision'])}
    mode = snapshot['global_mode']
    project_mode = snapshot['projects'].get(repository, 'running')
    reason = ('host_' + mode if mode != 'running' else
              'project_' + project_mode if project_mode != 'running' else None)
    return {
        'key': key,
        'resource': {'source': 'hydra', 'kind': 'admission', 'id': runtime['control_binding_digest']},
        'revision': revision, 'observed_at': observed_at, 'last_attempt_at': observed_at,
        'availability': 'current',
        'coverage': {'state': 'complete', 'scope': key, 'returned_count': 1,
                     'total_count': 1, 'next_cursor': None, 'reason': None},
        'reason': None,
        'value': {'revision': snapshot['revision'], 'global_mode': mode,
                  'project_overrides': dict(snapshot['projects']), 'gate_reason': reason},
    }


def _reply(command, runtime, epoch, outcome, reason, *, observation=None, required_next='refresh', receipt=None, progress_observation=None):
    observations = ([] if observation is None else [observation]) + ([] if progress_observation is None else [progress_observation])
    refs = [{'observation_key': o['key'], 'revision': copy.deepcopy(o['revision'])} for o in observations]
    applied = outcome == 'applied'
    return {
        'command_schema': 1, 'runtime': runtime, 'binding_epoch': epoch,
        'request': {
            'request_id': command['request_id'], 'action': command['action'],
            'target': dict(command['target']), 'outcome': outcome, 'reason': reason,
            'effect_refs': [dict(receipt['progress_ref'] if receipt else observation['resource'])] if applied else [],
            'observed_refs': refs,
            'receipt': (receipt or {'kind': 'admission', 'readback': refs[0]}) if applied else None,
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
    if ('admission_set' not in context.operations or command['target']['repository_id'] not in context.repository_ids):
        return _reply(command, runtime, epoch, 'rejected', 'authority_denied')
    expected = command['expected']
    if expected['runtime_key'] is None or expected['admission_revision'] is None:
        return _reply(command, runtime, epoch, 'rejected', 'precondition_required')
    key = _runtime_key(runtime)
    if key is None or key != expected['runtime_key']:
        return _reply(command, runtime, epoch, 'rejected', 'runtime_unavailable' if key is None else 'stale_runtime')
    repository, repository_reason = _repository(github, cfg['repos'], command['target']['repository_id'])
    # Remote lookup may take time. Re-read the installed binding and current grant
    # without extending the admission lock around network work.
    config_unavailable = False
    try:
        current_cfg = load_host_config(config_path)
        current_control = control_from_config(current_cfg)
        current_runtime = capture_runtime_identity(current_cfg, current_control)
    except (OSError, ValueError, OperationDenied):
        config_unavailable = True
        current_runtime = capture_runtime_identity()
    # Read authority last, including on config failure. Never return an old
    # config identity or retain a grant revoked during the config/runtime read.
    context, reason = _context(context_provider, command)
    epoch = context.binding_epoch if context else None
    if config_unavailable:
        return _reply(command, current_runtime, epoch, 'rejected', 'host_config_unavailable')
    if reason:
        return _reply(command, current_runtime, epoch, 'rejected', reason)
    if ('admission_set' not in context.operations or command['target']['repository_id'] not in context.repository_ids):
        return _reply(command, current_runtime, epoch, 'rejected', 'authority_denied')
    if repository_reason:
        return _reply(command, current_runtime, epoch,
                      'unknown' if repository_reason == 'repository_unavailable' else 'rejected', repository_reason)
    current_key = _runtime_key(current_runtime)
    if current_key is None or current_key != expected['runtime_key']:
        return _reply(command, current_runtime, epoch, 'rejected',
                      'runtime_unavailable' if current_key is None else 'stale_runtime')
    mode = command['parameters']['mode']
    try:
        readback = current_control.set_mode_if_current_observed(
            'pause' if mode == 'paused' else 'resume', repository,
            expected_revision=expected['admission_revision'], blocking=False)
    except OperationUncertain as exc:
        observation = (_observation(command, current_runtime, exc.observation, repository, 'current', exc.observation_at)
                       if exc.observation is not None and exc.observation_at is not None else None)
        return _reply(command, current_runtime, epoch, 'unknown', 'operation_state_unknown',
                      observation=observation, required_next='reconcile')
    except OperationDenied as exc:
        reason = exc.reason if exc.reason in _STORE_REASONS else 'operation_state_unavailable'
        reason = 'revision_exhausted' if reason == 'operation_state_revision_exhausted' else reason
        return _reply(command, current_runtime, epoch,
                      'waiting' if reason == 'operation_state_busy' else 'rejected', reason)
    reason = None
    snapshot = readback.snapshot
    if snapshot['revision'] == expected['admission_revision']:
        reason = ('stronger_mode_retained' if mode == 'paused'
                  and snapshot['projects'].get(repository) == 'stopped' else 'already_satisfied')
    return _reply(command, current_runtime, epoch, 'applied', reason,
                  observation=_observation(command, current_runtime, snapshot, repository, 'readback', readback.observed_at))


async def execute_checkpoint_command(config_path, command, *, context_provider, github, controller,
                                     ended_provider=None):
    """Internal checkpoint-only dispatch; no endpoint or native grant adapter."""
    command = _parse(command, checkpoint=True)
    context, reason = _context(context_provider, command)
    epoch = context.binding_epoch if context else None
    runtime = capture_runtime_identity()
    try:
        cfg = load_host_config(config_path)
        control = control_from_config(cfg)
        runtime = capture_runtime_identity(cfg, control)
    except (OSError, ValueError, OperationDenied):
        return _reply(command, runtime, epoch, 'rejected', 'host_config_unavailable')
    if reason:
        return _reply(command, runtime, epoch, 'rejected', reason)
    if command['command_schema'] != 1 or command['action'] != 'workflow_step' or command['parameters'] is None:
        return _reply(command, runtime, epoch, 'rejected', 'unsupported_operation')
    if command['parameters']['outcome'] == 'failed':
        return _reply(command, runtime, epoch, 'rejected', 'unsupported_outcome')
    if command['parameters']['outcome'] == 'stopped' and ended_provider is None:
        return _reply(command, runtime, epoch, 'rejected', 'termination_unconfirmed')
    expected = command['expected']
    if expected['runtime_key'] is None or expected['admission_revision'] is None:
        return _reply(command, runtime, epoch, 'rejected', 'precondition_required')
    target = command['target']
    if ('workflow_step.checkpoint_only' not in context.operations or target['repository_id'] not in context.repository_ids):
        return _reply(command, runtime, epoch, 'rejected', 'authority_denied')
    repository, repository_reason = _repository(github, cfg['repos'], target['repository_id'])

    def validate(*, include_evidence=True):
        nonlocal runtime, epoch
        config_unavailable = False
        try:
            current_cfg = load_host_config(config_path)
            current_control = control_from_config(current_cfg)
            runtime = capture_runtime_identity(current_cfg, current_control)
        except (OSError, ValueError, OperationDenied):
            config_unavailable = True
            runtime = capture_runtime_identity()
        # Match admission's final order: config/runtime, then current authority.
        # Even a failed config read must not retain an earlier grant or identity.
        current, reason = _context(context_provider, command)
        epoch = current.binding_epoch if current else None
        if config_unavailable:
            raise OperationDenied('host_config_unavailable')
        if reason:
            raise OperationDenied(reason)
        if ('workflow_step.checkpoint_only' not in current.operations or target['repository_id'] not in current.repository_ids):
            raise OperationDenied('authority_denied')
        key = _runtime_key(runtime)
        if key is None or key != expected['runtime_key']:
            raise OperationDenied('runtime_unavailable' if key is None else 'stale_runtime')
        runner = controller.runner
        if (runner.github is not github or runner.host != current_cfg['host_alias']
                or tuple(controller.repos) != tuple(current_cfg['repos'])
                or Path(controller.lock_path).absolute() != Path(current_cfg['lock_path'])
                or runner.operations is None
                or runner.operations.control_lock_path != current_control.control_lock_path
                or runner.operations.repos != current_control.repos
                or Path(runner.workspace.root).absolute() != Path(current_cfg['workspace_root'])):
            raise OperationDenied('checkpoint_binding_mismatch')
        if command['parameters']['outcome'] == 'stopped' and include_evidence:
            try:
                evidence = ended_provider()
            except Exception as exc:
                raise OperationDenied('termination_unconfirmed') from exc
            assignment = expected['assignment']
            exact = tuple(assignment[key] for key in ('attempt_id', 'step_id', 'head', 'contract_revision', 'spec_revision'))
            if (type(evidence) is not CheckpointStoppedEvidence
                    or type(evidence.repository_id) is not int or evidence.repository_id != target['repository_id']
                    or type(evidence.issue_number) is not int or evidence.issue_number != target['issue_number']
                    or evidence.host_alias != current_cfg['host_alias']
                    or evidence.control_binding_digest != runtime['control_binding_digest']
                    or type(evidence.assignment) is not tuple or evidence.assignment != exact
                    or evidence.state != 'ended' or evidence.availability != 'current'
                    or evidence.coverage != 'complete' or evidence.descendants != 'ended'
                    or type(evidence.observation_id) is not str or not 1 <= len(evidence.observation_id) <= 256
                    or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in evidence.observation_id)):
                raise OperationDenied('termination_unconfirmed')
            # Evidence can require a remote observation. It must not leave the
            # authority/config read from before that observation as the grant.
            validate(include_evidence=False)

    try:
        validate()
        if repository_reason:
            return _reply(command, runtime, epoch,
                          'unknown' if repository_reason == 'repository_unavailable' else 'rejected',
                          repository_reason)
        with control.guard(repository, cleanup=command['parameters']['outcome'] == 'stopped',
                           expected_revision=expected['admission_revision']):
            pass
    except OperationDenied as exc:
        return _reply(command, runtime, epoch, 'waiting' if exc.reason == 'operation_state_busy' else 'rejected', exc.reason)
    from .coordinator import HostBusy
    progress_observation = None
    def observe_progress(source):
        nonlocal progress_observation
        from datetime import datetime, timezone
        from . import projection as p
        p.require(type(source) is dict and type(source.get('record')) is dict)
        record, locator = source['record'], source.get('resource')
        p.require(type(record.get('repository_id')) is int and record['repository_id'] == target['repository_id']
                  and type(record.get('issue_number')) is int and record['issue_number'] == target['issue_number'])
        p.ref(locator)
        p.require(locator['source'] == 'github' and locator['kind'] == 'issue_comment'
                  and re.fullmatch(re.escape(repository) + r'/comments/[1-9][0-9]*', locator['id']) is not None)
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        key = 'command:' + command['request_id'] + ':progress-readback'
        issue_ref = {'source': 'github', 'kind': 'issue',
                     'id': str(target['repository_id']) + ':' + str(target['issue_number'])}
        progress_observation = {'key': key, 'resource': {**locator, 'kind': 'progress'},
            'revision': None, 'observed_at': now, 'last_attempt_at': now, 'availability': 'current',
            'coverage': {'state': 'complete', 'scope': key, 'returned_count': 1,
                         'total_count': 1, 'next_cursor': None, 'reason': None}, 'reason': None,
            'value': p.progress_source_value(record, issue_ref, str(target['repository_id']))}
        p.observation(progress_observation)

    try:
        receipt = await controller._checkpoint_only(repository, target['issue_number'], expected['assignment'],
            command['parameters']['outcome'], repository_id=target['repository_id'],
            admission_revision=expected['admission_revision'], before_effect=validate, source_observer=observe_progress)
        if progress_observation is None or receipt['progress_ref'] != {**progress_observation['resource'], 'kind': 'issue_comment'}:
            raise ValueError('Checkpoint progress readback unconfirmed')
    except OperationDenied as exc:
        if exc.reason == 'unsupported_phase':
            return _reply(command, runtime, epoch, 'rejected', exc.reason, required_next='open_source')
        return _reply(command, runtime, epoch, 'unknown' if exc.reason == 'assignment_unattributed' else 'waiting',
                      exc.reason, required_next='reconcile')
    except (OSError, RuntimeError, ValueError, HostBusy):
        return _reply(command, runtime, epoch, 'unknown', 'checkpoint_unconfirmed', required_next='reconcile')
    return _reply(command, runtime, epoch, 'applied', None, receipt=receipt, progress_observation=progress_observation)
