"""Closed native command entry for delegated public decision publication."""
import asyncio
import copy
from threading import Event

from . import projection as p


def _context(command):
    from .public_delegated_decisions import prepare_delegated_context
    params = command['parameters']
    return prepare_delegated_context(params['public_text'], {**params['basis'],
        'key': {**command['target'], 'source_attempt': params['source_attempt'], 'round': params['round']}})


def validate_parameters(command):
    from .control_commands import InvalidAdmissionCommand, _uuid
    try:
        params, expected = command['parameters'], command['expected']
        p.obj(params, 'operation source_attempt round basis public_text')
        p.require(params['operation'] == 'decision_submit' and _uuid(params['source_attempt'])
            and type(params['round']) is int and params['round'] == 1
            and expected['assignment'] is None and expected['source_checks'] == []
            and command['effect_key'] == f"decision:{params['source_attempt']}:1")
        p.obj(params['basis'], 'origin_phase head contract_revision spec_revision intake_digest')
        _context(command)
    except (ValueError, TypeError, KeyError):
        raise InvalidAdmissionCommand() from None


async def execute_decision_submit_command(config_path, command, *, context_provider, github, controller):
    from . import control_commands as c
    from .delegated_decisions import publish
    from .operations import OperationDenied
    from .verification_commands import progress_observation
    from .workflow_binding import WorkflowBinding

    binding = WorkflowBinding(config_path, command, context_provider, github, controller,
        'workflow_step.decision_submit', native_profile=True, reason='decision_binding_mismatch')
    repository = None

    def reply(outcome, reason, result=None):
        source = None if result is None else result.progress_source
        observed = None if source is None else progress_observation(command, repository, source)
        value = c._reply(command, binding.runtime, binding.epoch, outcome, reason,
            receipt=result.receipt if result is not None and outcome == 'applied' else None,
            progress_observation=observed, required_next='reconcile')
        value['request']['effect_refs'] = list(copy.deepcopy(result.effect_refs)) if result is not None else []
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
    cancel = Event()
    worker = asyncio.create_task(asyncio.to_thread(publish, controller, repository,
        command['target']['issue_number'], _context(command), command['request_id'], binding=binding, cancel=cancel))
    try:
        result = await asyncio.shield(worker)
    except asyncio.CancelledError:
        cancel.set()
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
        worker.result()
        raise
    try:
        binding.validate()
    except OperationDenied as exc:
        return reply('waiting' if result.effect_refs else 'rejected', exc.reason, result)
    return reply(result.outcome, result.reason, result)
