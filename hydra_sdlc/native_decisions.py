"""P06 work ownership and original-source effects. No adapter is activated."""
from .coordinator import coordinator_lock, operation_scope
from .decision_coordinator import DecisionCoordinator, DecisionEffectResult
from .operations import OperationDenied
from .project import load_project


def validate_apply_target(controller, repository, number, repository_id, *, mutation=False):
    runner = controller.runner
    reader = runner.github.read_client()
    with reader.read_budget(seconds=30, requests=128):
        source = reader.progress_source(repository, number)
        if source is None:
            raise OperationDenied('decision_checkpoint_missing')
        record = source['record']
        if (record.get('repository_id') != repository_id or record.get('issue_number') != number
                or record.get('host_alias') != runner.host or record.get('execution_mode') != 'native'
                or record.get('branch') != f'hydra/issue-{number}'):
            raise OperationDenied('decision_binding_mismatch')
        config = load_project(reader, repository)
        if config['repository_id'] != repository_id:
            raise OperationDenied('decision_binding_mismatch')
        pinned = load_project(reader, repository, revision=record['contract_revision'])
        if pinned['blob_sha'] != config['blob_sha']:
            raise OperationDenied('policy_changed')
        config = {**config, 'intake_digest': record['intake_digest']}
        if mutation:
            reason = runner._latest(repository, number, config, github=reader)
            if reason:
                raise OperationDenied(reason)
        runner._bind_policy(repository, config)
        return source


def apply_public_decision(controller, repository, number, params, *, repository_id, source_check,
                          read_source, effect_guard, prepare_effect, cancel):
    runner = controller.runner
    token = runner._policy_scope.set(None)
    try:
        if (runner._checkpoint_ceiling.get() is not None or runner._verification_scope.get() is not None
                or runner._continuation_scope.get() is not None):
            raise OperationDenied('effect_not_allowed')
        with coordinator_lock(controller.lock_path), operation_scope(runner.operations, repository):
            validate_apply_target(controller, repository, number, repository_id)
            coordinator = DecisionCoordinator(runner.github, repository, number,
                read_source=read_source, effect_guard=effect_guard,
                expected_key=(repository_id, number, params['source_attempt'], params['round']),
                expected_proposal=source_check, cancel=cancel, prepare_effect=prepare_effect)
            return coordinator.apply()
    except OperationDenied as exc:
        return DecisionEffectResult('waiting', exc.reason)
    finally:
        runner._policy_scope.reset(token)
