"""P06 closed command data and dispatch. No source or grant is installed here."""
import asyncio
import copy
from contextlib import contextmanager
from dataclasses import replace
from threading import Event

from . import projection as p


def validate_parameters(command):
    from .control_commands import InvalidAdmissionCommand, _integer, _uuid
    params, expected = command['parameters'], command['expected']
    try:
        p.require(expected['assignment'] is None)
        if params['operation'] == 'decision_apply':
            p.obj(params, 'operation proposal_ref source_attempt round')
            p.require(_uuid(params['source_attempt']) and _integer(params['round'], 1)
                and command['effect_key'] == f"decision:{params['source_attempt']}:{params['round']}")
            p.ref(params['proposal_ref'])
            p.require(params['proposal_ref']['source'] == 'codex')
            checks = expected['source_checks']
            p.require(type(checks) is list and len(checks) == 1)
            check = checks[0]
            p.obj(check, 'resource revision actionable_digest')
            p.ref(check['resource'])
            p.require(check['resource'] == params['proposal_ref'])
            p.nullable(check['revision'], p.revision)
            p.nullable(check['actionable_digest'], p.digest)
            p.require(check['revision'] is not None or check['actionable_digest'] is not None)
        else:
            p.require(params['operation'] == 'continue')
            p.obj(params, 'operation progress reply_profile')
            p.one(params['reply_profile'], {'standard_v1', 'native_handoff_v1'})
            p.require(expected['source_checks'] == [] and command['effect_key'] is None)
            if params['progress'] is not None:
                pin = params['progress']
                p.obj(pin, 'attempt_id head contract_revision phase')
                p.require(_uuid(pin['attempt_id']))
                p.sha(pin['head'])
                p.sha(pin['contract_revision'])
                p.code(pin['phase'])
    except (ValueError, TypeError, KeyError):
        raise InvalidAdmissionCommand() from None


async def execute_decision_apply_command(config_path, command, *, context_provider, github, controller):
    from . import control_commands as c
    from .coordinator import HostBusy
    from .operations import OperationDenied
    from .verification_commands import progress_observation
    from .workflow_binding import WorkflowBinding
    from .native_decisions import apply_public_decision

    binding = WorkflowBinding(config_path, command, context_provider, github, controller,
        'workflow_step.decision_apply', reason='decision_binding_mismatch')

    def reply(outcome, reason, receipt=None, source=None, effects=(), required_next='reconcile'):
        observed = None if source is None else progress_observation(command, repository, source)
        result = c._reply(command, binding.runtime, binding.epoch, outcome, reason,
            receipt=receipt, progress_observation=observed, required_next=required_next)
        result['request']['effect_refs'] = [copy.deepcopy(ref) for ref in effects]
        return result

    repository = None
    try:
        cfg, _, _ = binding.validate()
        repository, reason = await asyncio.to_thread(c._repository, github, cfg['repos'],
            command['target']['repository_id'])
        binding.validate()
        if reason:
            return reply('unknown' if reason == 'repository_unavailable' else 'rejected', reason)
        provider = getattr(controller, 'decision_source', None)
        if provider is None or not callable(getattr(provider, 'read_proposal', None)):
            return reply('rejected', 'unsupported_operation', required_next='open_source')
    except OperationDenied as exc:
        return reply('rejected', exc.reason)

    def read_source(*, timeout):
        binding.validate()
        if controller.decision_source is not provider:
            raise RuntimeError('Decision source unavailable')
        try:
            value = provider.read_proposal(copy.deepcopy(command['parameters']['proposal_ref']), timeout=timeout)
        except Exception:
            raise RuntimeError('Decision source unavailable') from None
        binding.validate()
        if controller.decision_source is not provider:
            raise RuntimeError('Decision source unavailable')
        return value

    def prepare_effect(kind):
        if kind not in {'context', 'receipt'}:
            raise OperationDenied('effect_not_allowed')
        _, current, _ = binding.validate()
        if controller.decision_source is not provider:
            raise OperationDenied('decision_source_changed')
        # Remote policy/work reads stay outside the admission lock.
        from .native_decisions import validate_apply_target
        validate_apply_target(controller, repository, command['target']['issue_number'],
                              command['target']['repository_id'], mutation=True)

    @contextmanager
    def effect_guard(kind):
        if kind not in {'context', 'receipt'}:
            raise OperationDenied('effect_not_allowed')
        if controller.decision_source is not provider:
            raise OperationDenied('decision_source_changed')
        _, current, _ = binding.validate()
        with current.guard(repository, expected_revision=command['expected']['admission_revision']):
            yield

    cancel = Event()
    worker = asyncio.create_task(asyncio.to_thread(apply_public_decision, controller, repository,
        command['target']['issue_number'], command['parameters'],
        repository_id=command['target']['repository_id'],
        source_check=command['expected']['source_checks'][0], read_source=read_source,
        effect_guard=effect_guard, prepare_effect=prepare_effect, cancel=cancel))
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
    except (HostBusy, OSError, RuntimeError, ValueError):
        return reply('unknown', 'decision_unconfirmed')
    try:
        binding.validate()
    except OperationDenied as exc:
        result = replace(result, outcome='waiting' if result.effect_refs else 'rejected',
                         reason=exc.reason, receipt=None)
    if not result.effect_refs and result.reason in {'stale_decision', 'decision_binding_mismatch',
            'authority_denied', 'stale_runtime', 'stale_revision'}:
        result = replace(result, outcome='rejected')
    return reply(result.outcome, result.reason, result.receipt, result.progress_source,
                 result.effect_refs, required_next='refresh' if result.reason in
                 {'stale_decision', 'authority_denied', 'stale_runtime', 'stale_revision'} else 'reconcile')
