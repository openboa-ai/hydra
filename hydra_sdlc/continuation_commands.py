"""P06 broad continuation inside the current delegation and native guards.

The scope below is transient caller/progress fencing, not a workflow store. Each
write is followed by original GitHub read-back; no current pin is silently adopted.
"""
import asyncio
import copy
from contextlib import contextmanager
import json
from pathlib import Path
from threading import Event

from . import control_commands as c
from . import projection as p
from .coordinator import (HostBusy, coordinator_lock, operation_scope, residual_workers,
                          native_assignment_matches)
from .operations import OperationDenied
from .verification_commands import progress_observation
from .workflow_binding import WorkflowBinding


class ContinuationScope:
    def __init__(self, binding, controller, repository, command):
        self.binding, self.controller, self.repository, self.command = binding, controller, repository, command
        self.runner = controller.runner
        self.number = command['target']['issue_number']
        self.expected, self.source, self.frame = None, None, None
        self.observed, self.read_failed = None, False
        self.confirmed_refs, self.uncertain, self.cancel = [], False, Event()

    def read(self):
        try:
            reader = self.runner.github.read_client()
            with reader.read_budget(seconds=15, requests=64):
                source = reader.progress_source(self.repository, self.number)
            observed = progress_observation(self.command, self.repository, source) if source is not None else None
        except (OSError, RuntimeError, ValueError, TypeError, KeyError):
            self.read_failed = True
            raise
        self.observed, self.read_failed = observed, False
        return source

    def initial(self):
        source = self.read()
        current = source['record'] if source is not None else None
        pin = self.command['parameters']['progress']
        if (pin is None and current is not None or pin is not None
                and (current is None or any(current.get(key) != value for key, value in pin.items()))):
            raise OperationDenied('stale_progress')
        self.expected, self.source = copy.deepcopy(current), source

    def prepare(self):
        if self.uncertain:
            raise OperationDenied('continuation_unconfirmed')
        source = self.read()
        if (source['record'] if source is not None else None) != self.expected:
            raise OperationDenied('stale_progress')
        self.source = source

    def recorded(self, record):
        expected = {**record, 'version': 1, 'repository_id': self.command['target']['repository_id'],
                    'issue_number': self.number}
        try:
            source = self.read()
            if source is None or source['record'] != expected:
                raise OperationDenied('continuation_unconfirmed')
        except (OSError, RuntimeError, ValueError):
            self.uncertain = True
            raise
        self.expected, self.source = copy.deepcopy(expected), source
        if source['resource'] not in self.confirmed_refs:
            self.confirmed_refs.append(copy.deepcopy(source['resource']))

    @contextmanager
    def guard(self, repository, *, cleanup=False, decision_frame=None, handoff=False):
        if repository.casefold() != self.repository.casefold():
            raise OperationDenied('continuation_binding_mismatch')
        if self.cancel.is_set() and not cleanup:
            raise OperationDenied('continuation_cancelled')
        self.prepare()
        if decision_frame is not None and not cleanup:
            decision_frame.check()
            self.frame = decision_frame
        _, control, caller = self.binding.validate()
        if handoff:
            self._require_handoff(caller)
        revision = (control.snapshot()['revision'] if cleanup else
                    self.command['expected']['admission_revision'])
        with control.guard(repository, cleanup=cleanup, expected_revision=revision):
            yield

    def before_handoff(self):
        _, _, caller = self.binding.validate()
        self._require_handoff(caller)

    def _require_handoff(self, caller):
        if (self.command['parameters']['reply_profile'] != 'native_handoff_v1'
                or caller.surface != 'native' or 'command_reply.native_handoff_v1' not in caller.operations):
            raise OperationDenied('continuation_handoff_unavailable')


def validate_assignment(value, repository, number, record):
    fields = {'repository', 'issue', 'action', 'attempt_id', 'step_id', 'phase', 'head',
              'contract_revision', 'spec_revision', 'cwd', 'mode', 'prompt'}
    phases = {'design', 'implementation', 'correction', 'spec_review', 'change_review'}
    if (type(value) is not dict or set(value) != fields or value['repository'] != repository
            or type(value['issue']) is not int or value['issue'] != number or value['action'] != 'native_task'
            or value['phase'] not in phases or not c._uuid(value['attempt_id']) or not c._uuid(value['step_id'])
            or value['mode'] != ('read_only' if 'review' in value['phase'] else 'workspace_write')
            or record.get('execution_mode') != 'native' or record.get('native_outcome') is not None
            or any(value[key] != record.get(key) for key in ('attempt_id', 'head', 'contract_revision', 'spec_revision'))
            or value['step_id'] != record.get('native_step') or value['phase'] != record.get('native_phase')
            or value['head'] != record.get('native_head')
            or type(value['cwd']) is not str or not Path(value['cwd']).is_absolute()
            or type(value['prompt']) is not str or not value['prompt']):
        raise OperationDenied('native_assignment_invalid')
    for key in ('head', 'contract_revision'):
        p.sha(value[key])
    if value['spec_revision'] is not None:
        p.sha(value['spec_revision'])
    try:
        size = len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8'))
    except (UnicodeError, ValueError):
        raise OperationDenied('native_assignment_invalid') from None
    if size > 1024 * 1024 - 65536:
        raise OperationDenied('native_assignment_too_large')


async def execute_continue_command(config_path, command, *, context_provider, github, controller):
    native = command['parameters']['reply_profile'] == 'native_handoff_v1'
    binding = WorkflowBinding(config_path, command, context_provider, github, controller,
        'workflow_step.continue', native_profile=native, reason='continuation_binding_mismatch')
    repository, scope = None, None

    def reply(outcome, reason, *, receipt=None, assignment=None):
        try:
            p.code(reason)
        except ValueError:
            outcome, reason, receipt, assignment = 'unknown', 'continuation_unconfirmed', None, None
        observed = scope.observed if scope is not None and not scope.read_failed else None
        value = c._reply(command, binding.runtime, binding.epoch, outcome, reason, receipt=receipt,
                         progress_observation=observed, required_next='open_source' if reason in
                         {'unsupported_reply_profile', 'continuation_handoff_unavailable'} else 'reconcile')
        value['request']['effect_refs'] = copy.deepcopy(scope.confirmed_refs) if scope else []
        if native:
            value.update(reply_profile='native_handoff_v1',
                         handoff={'kind': 'native_assignment', 'assignment': assignment} if assignment else None)
        try:
            if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')) > 1024 * 1024:
                raise OperationDenied('native_assignment_too_large')
        except (UnicodeError, ValueError):
            raise OperationDenied('native_assignment_invalid') from None
        return value

    try:
        cfg, _, _ = binding.validate()
        repository, reason = await asyncio.to_thread(c._repository, github, cfg['repos'],
            command['target']['repository_id'])
        _, control, _ = binding.validate()
        if reason:
            return reply('unknown' if reason == 'repository_unavailable' else 'rejected', reason)
        with control.guard(repository, expected_revision=command['expected']['admission_revision']):
            pass
    except OperationDenied as exc:
        return reply('rejected', exc.reason)
    scope = ContinuationScope(binding, controller, repository, command)

    def core():
        runner = controller.runner
        if (runner._continuation_scope.get() is not None or runner._checkpoint_ceiling.get() is not None
                or runner._verification_scope.get() is not None):
            return reply('rejected', 'continuation_scope_conflict')
        token = runner._continuation_scope.set(scope)
        policy = runner._policy_scope.set(None)
        try:
            scope.initial()
            before = copy.deepcopy(scope.expected)
            with operation_scope(runner.operations, repository,
                    expected_revision=command['expected']['admission_revision']), coordinator_lock(controller.lock_path):
                scope.prepare()
                if residual_workers() or scope.expected and scope.expected.get('native_step'):
                    return reply('waiting', 'confirm_previous_stopped')
                result = asyncio.run(runner.step(repository, scope.number))
                scope.prepare()
                assignment = ({key: value for key, value in result.items() if key != 'progress_hint'}
                              if result.get('action') == 'native_task' else None)
                if assignment is not None:
                    scope.before_handoff()
                    record, _ = controller._bound(repository, scope.number, assignment['attempt_id'],
                        assignment['head'], assignment['contract_revision'], assignment['step_id'])
                    validate_assignment(assignment, repository, scope.number, record)
                    from .native import assignment_scope
                    if not native_assignment_matches(assignment['step_id'], assignment_scope(repository,
                            scope.number, assignment['attempt_id'], assignment['head'], assignment['contract_revision'])):
                        raise OperationDenied('native_assignment_invalid')
                # Re-read current grant/admission and source before the private
                # response leaves the same host ownership scope.
                with scope.guard(repository, decision_frame=scope.frame, handoff=assignment is not None):
                    if scope.source is None:
                        return reply('waiting', result.get('reason') or 'continuation_waiting')
                    changed = scope.expected != before
                    applied = assignment is not None or changed or result.get('action') == 'completed'
                    receipt = None
                    if applied:
                        record = scope.source['record']
                        receipt = {'kind': 'continuation', 'progress_ref': copy.deepcopy(scope.source['resource']),
                            'attempt_id': record['attempt_id'], 'head': record['head'],
                            'contract_revision': record['contract_revision'],
                            'boundary': 'assignment_returned' if assignment is not None else
                                'progress_recorded' if changed else 'existing_result_reconciled'}
                    return reply('applied' if applied else 'waiting',
                        result.get('reason') or ('continuation_confirmed' if applied else 'continuation_waiting'),
                        receipt=receipt, assignment=assignment)
        except OperationDenied as exc:
            return reply('unknown' if exc.reason == 'continuation_unconfirmed' else
                         'rejected' if exc.reason in {'stale_progress', 'stale_runtime', 'stale_revision',
                             'authority_denied', 'stale_binding'} else 'waiting', exc.reason)
        except HostBusy:
            return reply('waiting', 'confirm_previous_stopped')
        except (OSError, RuntimeError, ValueError, TypeError, KeyError):
            return reply('unknown', 'continuation_unconfirmed')
        finally:
            runner._policy_scope.reset(policy)
            runner._continuation_scope.reset(token)

    worker = asyncio.create_task(asyncio.to_thread(core))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        scope.cancel.set()
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
        worker.result()
        raise
