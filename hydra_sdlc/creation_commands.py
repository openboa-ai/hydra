"""Closed work_create command. Qualified current authority remains external."""
import asyncio
from contextlib import contextmanager
import copy
import re

from . import control_commands as c
from . import projection as p
from .coordinator import HostBusy
from .operations import OperationDenied
from .work_drafts import parse_draft_ref
from .work_records import WorkRecordError, _hex, _uuid
from .workflow_binding import WorkflowBinding


def validate_parameters(command):
    try:
        params, expected = command['parameters'], command['expected']
        p.obj(params, 'draft_ref draft_digest')
        reference = parse_draft_ref(params['draft_ref']).value
        p.require(_hex(params['draft_digest'], 64) and _uuid(command['effect_key'], version=4)
                  and expected['assignment'] is None)
        checks = expected['source_checks']
        p.require(type(checks) is list and len(checks) == 1)
        check = checks[0]
        p.obj(check, 'resource revision actionable_digest')
        p.ref(check['resource'])
        p.require(check['resource']['source'] == 'github' and check['resource']['kind'] == 'issue_comment'
            and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/comments/[1-9][0-9]*', check['resource']['id'])
            and check['revision'] is None and _hex(check['actionable_digest'], 64))
        if reference['kind'] == 'github_comment':
            p.require(check['actionable_digest'] == reference['revision'])
    except (WorkRecordError, ValueError, TypeError, KeyError):
        raise c.InvalidAdmissionCommand() from None


async def execute_creation_command(config_path, command, *, context_provider, github, controller):
    from .work_creation import Registration
    binding = WorkflowBinding(config_path, command, context_provider, github, controller,
        'work_create', native_profile=True, reason='creation_binding_mismatch')
    registration = None

    def reply(outcome, reason, receipt=None):
        observed = registration.observation() if registration is not None else None
        result = c._reply(command, binding.runtime, binding.epoch, outcome, reason,
            observation=observed, receipt=receipt, required_next='reconcile')
        if registration is not None:
            result['request']['effect_refs'] = copy.deepcopy(registration.effects)
        return result

    try:
        cfg, _, _ = binding.validate()
        repository, reason = await asyncio.to_thread(c._repository, github, cfg['repos'],
            command['target']['repository_id'])
        binding.validate()
        if reason:
            return reply('unknown' if reason == 'repository_unavailable' else 'rejected', reason)

        def validate_current():
            binding.validate()

        @contextmanager
        def effect_guard():
            _, control, _ = binding.validate()
            with control.guard(repository, expected_revision=command['expected']['admission_revision']):
                # Revalidate caller/runtime on this side of the barrier. Remote
                # source observations have already completed outside this lock.
                binding.validate()
                yield

        registration = Registration(github, cfg['repos'], command, controller.lock_path,
            validate_current=validate_current, effect_guard=effect_guard, controller=controller)
        receipt = await asyncio.to_thread(registration.run)
        return reply('applied', None, receipt) if receipt is not None else reply('unknown', 'creation_effect_unconfirmed')
    except OperationDenied as exc:
        rejected = {'creation_payload_conflict', 'stale_runtime', 'stale_binding', 'authority_denied',
                    'authority_unavailable', 'precondition_required', 'unsupported_operation'}
        unknown = {'creation_effect_unconfirmed', 'creation_duplicate_scope_unknown',
                   'creation_source_unavailable', 'creation_repository_unavailable',
                   'creation_authority_unknown', 'creation_credential_changed', 'creation_reference_unavailable'}
        unknown |= {'creation_history_unsupported', 'creation_history_unavailable',
                    'creation_history_unknown', 'creation_history_changed', 'creation_history_capacity',
                    'creation_execution_unavailable'}
        outcome = 'rejected' if exc.reason in rejected else 'unknown' if exc.reason in unknown else 'waiting'
        return reply(outcome, exc.reason)
    except HostBusy:
        return reply('waiting', 'host_busy')
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return reply('unknown', 'creation_effect_unconfirmed')
