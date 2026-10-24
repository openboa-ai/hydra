"""Closed protected-delivery command; installed authority is granted separately."""
import asyncio
import re

from . import control_commands as c
from .coordinator import HostBusy
from .operations import OperationDenied
from .verification_commands import progress_observation
from .workflow_binding import WorkflowBinding


def validate_parameters(command):
    params, expected = command['parameters'], command['expected']
    pin = params.get('candidate')
    if (set(params) != {'operation', 'candidate', 'pr_number', 'integration_base'}
            or type(pin) is not dict or set(pin) != {'attempt_id', 'head', 'contract_revision'}
            or not c._uuid(pin['attempt_id'])
            or any(type(pin[name]) is not str or re.fullmatch('[0-9a-f]{40}', pin[name]) is None
                   for name in ('head', 'contract_revision'))
            or not c._integer(params['pr_number'], 1)
            or type(params['integration_base']) is not str
            or re.fullmatch('[0-9a-f]{40}', params['integration_base']) is None
            or expected['assignment'] is not None or command['effect_key'] is not None):
        raise c.InvalidAdmissionCommand()


async def execute_delivery_command(config_path, command, *, context_provider, github, controller):
    binding = WorkflowBinding(config_path, command, context_provider, github, controller,
        'workflow_step.deliver', reason='delivery_binding_mismatch')
    observed = None

    def reply(outcome, reason, receipt=None, required_next='reconcile'):
        value = c._reply(command, binding.runtime, binding.epoch, outcome, reason,
            receipt=receipt, progress_observation=observed, required_next=required_next)
        if receipt is not None:
            value['request']['receipt'] = receipt
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

    def before_effect():
        _, control, _ = binding.validate()
        with control.guard(repository, expected_revision=command['expected']['admission_revision']):
            pass

    def observe(source):
        nonlocal observed
        observed = progress_observation(command, repository, source)

    from .native_delivery import execute
    try:
        return await execute(controller, repository, command['target']['issue_number'],
            command['parameters'], repository_id=command['target']['repository_id'],
            admission_revision=command['expected']['admission_revision'],
            before_effect=before_effect, source_observer=observe, finalize_reply=reply)
    except OperationDenied as exc:
        return reply('rejected' if exc.reason in {'stale_candidate', 'stale_delivery'} else 'waiting', exc.reason)
    except (OSError, RuntimeError, ValueError, HostBusy):
        return reply('unknown', 'delivery_unconfirmed')
