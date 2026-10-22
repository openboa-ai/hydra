"""Closed publication command profile; installed authority remains separate."""
import re

from . import control_commands as c
from .coordinator import HostBusy
from .operations import OperationDenied
from .verification_commands import progress_observation
from .workflow_binding import WorkflowBinding


def validate_parameters(command):
    params, expected = command['parameters'], command['expected']
    pin = params.get('candidate')
    if (set(params) != {'operation', 'candidate', 'branch', 'expected_remote_head'}
            or type(pin) is not dict or set(pin) != {'attempt_id', 'head', 'contract_revision'}
            or not c._uuid(pin['attempt_id'])
            or any(type(pin[key]) is not str or re.fullmatch('[0-9a-f]{40}', pin[key]) is None
                   for key in ('head', 'contract_revision'))
            or type(params['branch']) is not str
            or re.fullmatch(r'hydra/issue-[1-9][0-9]*', params['branch']) is None
            or (params['expected_remote_head'] is not None
                and (type(params['expected_remote_head']) is not str
                     or re.fullmatch('[0-9a-f]{40}', params['expected_remote_head']) is None))
            or expected['assignment'] is not None or command['effect_key'] is not None):
        raise c.InvalidAdmissionCommand()


async def execute_publication_command(config_path, command, *, context_provider, github, controller):
    binding = WorkflowBinding(config_path, command, context_provider, github, controller,
        'workflow_step.publish_candidate', reason='publication_binding_mismatch')
    observed = None

    def reply(outcome, reason, receipt=None, required_next='reconcile'):
        value = c._reply(command, binding.runtime, binding.epoch, outcome, reason,
            receipt=receipt, progress_observation=observed, required_next=required_next)
        if receipt is not None:
            value['request']['receipt'] = receipt
        return value

    try:
        cfg, _, _ = binding.validate()
        repository, reason = c._repository(github, cfg['repos'], command['target']['repository_id'])
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

    from .native_publication import execute
    try:
        return await execute(controller, repository, command['target']['issue_number'],
            command['parameters'], repository_id=command['target']['repository_id'],
            admission_revision=command['expected']['admission_revision'],
            before_effect=before_effect, source_observer=observe, finalize_reply=reply)
    except OperationDenied as exc:
        return reply('rejected' if exc.reason in {'stale_candidate', 'stale_publication'} else 'waiting', exc.reason)
    except (OSError, RuntimeError, ValueError, HostBusy):
        return reply('unknown', 'publication_unconfirmed')
