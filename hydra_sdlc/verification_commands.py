"""Closed verify-only command boundary. No installation grants are supplied here."""
from datetime import datetime, timezone
import hashlib
import json
import re

from . import control_commands as c
from .coordinator import HostBusy
from .operations import OperationDenied
from .runtime_identity import capture_runtime_identity
from .workflow_binding import WorkflowBinding


def validate_parameters(command):
    """Called after common CommandV1 validation, before reading dependencies."""
    p, expected = command['parameters'], command['expected']
    fields = {'operation', 'stage', 'candidate', 'reply_profile'}
    stage = p.get('stage')
    if stage == 'review_checkpoint':
        fields |= {'outcome', 'summary'}
    pin = p.get('candidate')
    if (type(stage) is not str or stage not in {'run', 'review_checkpoint'} or set(p) != fields
            or type(p['reply_profile']) is not str
            or p['reply_profile'] not in {'standard_v1', 'native_handoff_v1'}
            or type(pin) is not dict or set(pin) != {'attempt_id', 'head', 'contract_revision'}
            or not c._uuid(pin['attempt_id'])
            or any(type(pin[k]) is not str or re.fullmatch('[0-9a-f]{40}', pin[k]) is None
                   for k in ('head', 'contract_revision'))):
        raise c.InvalidAdmissionCommand()
    if stage == 'run':
        if expected['assignment'] is not None or command['effect_key'] is not None:
            raise c.InvalidAdmissionCommand()
        return
    assignment = expected['assignment']
    if (type(assignment) is not dict or set(assignment) !=
            {'attempt_id', 'step_id', 'head', 'contract_revision', 'spec_revision'}
            or any(assignment[k] != pin[k] for k in pin) or not c._uuid(assignment['step_id'])
            or assignment['spec_revision'] is not None and (type(assignment['spec_revision']) is not str
                or re.fullmatch('[0-9a-f]{40}', assignment['spec_revision']) is None)
            or command['effect_key'] != f"checkpoint:{pin['attempt_id']}:{assignment['step_id']}"
            or type(p['outcome']) is not str
            or p['outcome'] not in {'candidate_ready', 'failed', 'needs_decision'}
            or type(p['summary']) is not str or len(p['summary']) > 24000
            or any(0xD800 <= ord(char) <= 0xDFFF for char in p['summary'])):
        raise c.InvalidAdmissionCommand()


def progress_observation(command, repository, source):
    """Qualify the actual GitHub read-back, never a locally invented source ref."""
    from . import projection as p
    p.require(type(source) is dict and type(source.get('record')) is dict)
    record, locator, target = source['record'], source.get('resource'), command['target']
    p.require(type(record.get('repository_id')) is int and record['repository_id'] == target['repository_id']
              and type(record.get('issue_number')) is int and record['issue_number'] == target['issue_number'])
    p.ref(locator)
    p.require(locator['source'] == 'github' and locator['kind'] == 'issue_comment'
              and re.fullmatch(re.escape(repository) + r'/comments/[1-9][0-9]*', locator['id']) is not None)
    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    key = 'command:' + command['request_id'] + ':progress-readback'
    issue = {'source': 'github', 'kind': 'issue',
             'id': str(target['repository_id']) + ':' + str(target['issue_number'])}
    observed = {'key': key, 'resource': {**locator, 'kind': 'progress'}, 'revision': None,
        'observed_at': now, 'last_attempt_at': now, 'availability': 'current',
        'coverage': {'state': 'complete', 'scope': key, 'returned_count': 1,
                     'total_count': 1, 'next_cursor': None, 'reason': None}, 'reason': None,
        'value': p.progress_source_value(record, issue, str(target['repository_id']))}
    p.observation(observed)
    return observed


async def execute_verification_command(config_path, command, *, context_provider, github, controller):
    """One real run or exact review finish; no broad continuation or retry."""
    params, expected, target = command['parameters'], command['expected'], command['target']
    operation = 'workflow_step.verify_only.' + params['stage']
    native_profile = params['reply_profile'] == 'native_handoff_v1'
    runtime, epoch = capture_runtime_identity(), None
    observed = None
    binding = WorkflowBinding(config_path, command, context_provider, github, controller,
        operation, native_profile=native_profile)

    def reply(outcome, reason, receipt=None, assignment=None, required_next='reconcile'):
        if assignment is not None:
            # The last source read can outlive the previous grant observation.
            before_effect()
            if not allow_handoff():
                raise OperationDenied('review_handoff_unavailable')
        value = c._reply(command, runtime, epoch, outcome, reason, receipt=receipt,
                         progress_observation=observed, required_next=required_next)
        # Verification is an actual effect even while its independent review
        # remains pending. Do not discard the run receipt on a waiting result.
        if receipt is not None:
            value['request']['receipt'] = receipt
        if native_profile:
            value.update(reply_profile='native_handoff_v1',
                handoff={'kind': 'native_assignment', 'assignment': assignment} if assignment else None)
        return value

    def validate():
        nonlocal runtime, epoch
        try:
            return binding.validate()
        finally:
            runtime, epoch = binding.runtime, binding.epoch

    try:
        cfg, control, _ = validate()
        repository, reason = c._repository(github, cfg['repos'], target['repository_id'])
        _, control, _ = validate()
        if reason:
            return reply('unknown' if reason == 'repository_unavailable' else 'rejected', reason)
        with control.guard(repository, expected_revision=expected['admission_revision']):
            pass
    except OperationDenied as exc:
        return reply('rejected', exc.reason)

    def before_effect():
        _, current_control, _ = validate()
        with current_control.guard(repository, expected_revision=expected['admission_revision']):
            pass

    def preservation_lease():
        # This lease is available only to the owned supervisor's positive end
        # path. Cleanup changes the mode gate, never the current caller's grants.
        _, current_control, _ = validate()
        revision = current_control.snapshot()['revision']
        def guard():
            _, current_control, _ = validate()
            controller.runner._require_policy(repository)
            with current_control.guard(repository, cleanup=True, expected_revision=revision):
                pass
        guard()
        return revision, guard

    def allow_handoff():
        _, _, current = validate()
        return (native_profile and current.surface == 'native'
            and {'workflow_step.verify_only.review_checkpoint', 'command_reply.native_handoff_v1'}
                 <= current.operations)

    def observe(source):
        nonlocal observed
        observed = progress_observation(command, repository, source)

    from .native_verification import execute
    try:
        return await execute(controller, repository, target['issue_number'], params,
            expected['assignment'], repository_id=target['repository_id'],
            admission_revision=expected['admission_revision'], before_effect=before_effect,
            preservation_lease=preservation_lease,
            allow_handoff=allow_handoff, source_observer=observe, request_id=command['request_id'],
            request_digest=hashlib.sha256(json.dumps(command, sort_keys=True,
                separators=(',', ':'), ensure_ascii=False).encode()).hexdigest(), finalize_reply=reply)
    except OperationDenied as exc:
        outcome = ('unknown' if exc.reason in {'assignment_unattributed', 'verification_invocation_unattributed'} else
                   'rejected' if exc.reason in {'stale_candidate', 'unsupported_phase', 'request_conflict'} else 'waiting')
        return reply(outcome, exc.reason)
    except (OSError, RuntimeError, ValueError, HostBusy):
        return reply('unknown', 'verification_unconfirmed')
