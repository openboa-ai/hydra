"""Bounded use of the existing native runner and its private verification lifetime."""
import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from threading import Event

from .coordinator import (confirm_native_assignment, coordinator_lock,
                          native_assignment_matches, operation_scope)
from .native import assignment_scope
from .operations import OperationDenied
from .project import matches
from .runner import Runner
from .workspace import WorkspaceWait


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


@dataclass
class VerificationRun:
    """Object identity binds the reviewer to one actual invocation, not its key."""
    results: list
    digest: str
    spec_digest: str
    request_id: str | None = None
    request_digest: str | None = None
    verification_record: dict | None = None
    expected_record: dict | None = None
    assignment: dict | None = None
    draft: dict | None = None
    ticket: tuple[str, str] | None = None
    changed_head: str | None = None
    error_reason: str | None = None


@dataclass
class VerificationBoundary:
    before_dispatch: Callable[[], None]
    before_handoff: Callable[[], None]
    cancel: Event = field(default_factory=Event)
    run: VerificationRun | None = None


def validate_assignment(value, repo, number, candidate):
    from .control_commands import _uuid
    fields = {'repository', 'issue', 'action', 'attempt_id', 'step_id', 'phase', 'head',
              'contract_revision', 'spec_revision', 'cwd', 'mode', 'prompt'}
    if (type(value) is not dict or set(value) != fields or value['repository'] != repo
            or type(value['issue']) is not int or value['issue'] != number
            or value['action'] != 'native_task' or value['phase'] != 'change_review'
            or value['mode'] != 'read_only' or not _uuid(value['step_id'])
            or any(value[k] != candidate[k] for k in candidate)
            or value['spec_revision'] is not None and (type(value['spec_revision']) is not str
                or re.fullmatch('[0-9a-f]{40}', value['spec_revision']) is None)
            or type(value['cwd']) is not str or not Path(value['cwd']).is_absolute()
            or type(value['prompt']) is not str or not value['prompt']):
        raise OperationDenied('native_assignment_invalid')
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (UnicodeError, ValueError):
        raise OperationDenied('native_assignment_invalid') from None
    if len(encoded) > 1024 * 1024 - 65536:
        raise OperationDenied('native_assignment_too_large')


def _candidate(controller, repo, number, candidate, repository_id, assignment=None):
    runner = controller.runner
    if runner.host_hold_reason:
        raise OperationDenied(runner.host_hold_reason)
    try:
        record, config = controller._bound(repo, number, candidate['attempt_id'], candidate['head'],
            candidate['contract_revision'], assignment['step_id'] if assignment else None)
    except ValueError:
        raise OperationDenied('stale_candidate') from None
    if (record.get('repository_id') != repository_id or config.get('repository_id') != repository_id
            or config.get('_completion_only') or record.get('head') != candidate['head']):
        raise OperationDenied('stale_candidate')
    if assignment is not None:
        if record.get('native_phase') != 'change_review':
            raise OperationDenied('unsupported_phase')
        if record.get('spec_revision') != assignment['spec_revision']:
            raise OperationDenied('stale_candidate')
    elif record.get('native_step'):
        raise OperationDenied('native_assignment_pending')
    elif record.get('wait_reason') == 'product_decision' or record.get('next_action') == 'operator_decision':
        raise OperationDenied('product_decision')
    if record.get('pending_action') not in {None, 'verification'}:
        raise OperationDenied('effect_not_allowed')
    config = {**config, 'intake_digest': record['intake_digest']}
    reason = runner._latest(repo, number, config)
    if reason:
        raise OperationDenied(reason)
    boundary, remote, _ = runner._branch_boundary(repo, number, record)
    if boundary or remote not in {None, record.get('head'), record.get('expected_head')}:
        raise OperationDenied(boundary or 'remote_head_changed')
    path = runner.workspace.existing(repo, number, record['branch'])
    state = runner.workspace.inspect(path)
    if state['head'] != candidate['head'] or state['dirty']:
        raise OperationDenied('stale_candidate')
    if not runner.workspace.contains_base(path, config['revision']):
        raise OperationDenied('base_changed')
    if any(not matches(name, config['allowed_paths'])
           for name in runner.workspace.changed_paths(path, config['revision'])):
        raise OperationDenied('scope_changed')
    spec = runner._scoped_spec(repo, number, config, record)
    if (not record.get('spec_revision') or not runner.workspace.valid_spec(path, spec)
            or runner._spec_changed(repo, number, config, record, path)):
        raise OperationDenied('accepted_spec_changed')
    digest = hashlib.sha256(runner.workspace.read_spec(path, spec)).hexdigest()
    if assignment is not None and record.get('native_spec_digest') != digest:
        raise OperationDenied('accepted_spec_changed')
    return record, config, path, digest


def _source(runner, repo, number, record, observer):
    if type(record) is not dict:
        raise RuntimeError('Verification record unavailable')
    source = runner.github.progress_source(repo, number)
    observed = source.get('record') if type(source) is dict else None
    if not observed or runner._record_values(observed) != runner._record_values(record):
        raise RuntimeError('Verification final record unconfirmed')
    observer(source)
    return source


def _valid_results(workspace, path, config, results):
    if type(results) is not list or not results or len(results) != len(config['verification']):
        return False
    for actual, registered in zip(results, config['verification']):
        cwd = str((path / registered.get('cwd', '.')).resolve().relative_to(path))
        if (type(actual) is not dict or set(actual) != {'argv', 'cwd', 'exit_code', 'passed', 'output_digest'}
                or actual['argv'] != registered['argv'] or actual['cwd'] != cwd
                or type(actual['exit_code']) is not int or type(actual['passed']) is not bool
                or actual['passed'] != (actual['exit_code'] == 0)
                or type(actual['output_digest']) is not str):
            return False
        output = getattr(workspace, '_outputs', {}).get(actual['output_digest'])
        if type(output) is not bytes or hashlib.sha256(output).hexdigest() != actual['output_digest']:
            return False
    return True


def _correction_debt(runner, repo, number, record, reason, *, recorded=False):
    attempts = record.get('correction_attempt') or 0
    if not recorded:
        attempts = max(attempts + (record.get('correction_reason') == reason),
            runner.failures.get((repo, number, reason), 0) + 1)
    return dict(resume_phase='correction', correction_reason=reason, correction_attempt=attempts or 1)


def _private_output(runner, results):
    remaining, outputs = 24000, []
    for value in results:
        text = runner.workspace.verification_output(value['output_digest'], max_chars=remaining)
        outputs.append(text)
        remaining -= len(text)
        if not remaining:
            break
    return ''.join(outputs)


def _remember_error(runner, repo, number, record, spec_digest, key, request_id, request_digest, reason):
    planned = runner._record_values(record, phase='implementation_done', pending_action=None,
        wait_reason='replan_required', next_action='diagnose_verification')
    proof = VerificationRun([], _digest([]), spec_digest, request_id, request_digest,
        verification_record=runner._record_values(record), expected_record=planned, error_reason=reason)
    runner.verification_runs[key] = proof
    runner._verification_scope.get().run = proof
    return proof


def _settle_error(runner, repo, number, proof, observer):
    try:
        runner._record(repo, number, proof.expected_record)
    except (OSError, RuntimeError):
        pass  # Only exact read-back can confirm the attempted settlement.
    _source(runner, repo, number, proof.expected_record, observer)
    return {'outcome': 'waiting', 'reason': proof.error_reason, 'required_next': 'open_source'}


async def execute(controller, repo, number, params, assignment, *, repository_id,
                  admission_revision, before_effect, allow_handoff, source_observer,
                  request_id, request_digest, finalize_reply):
    runner, pin = controller.runner, params['candidate']
    policy = runner._policy_scope.set(None)
    ceiling = runner._checkpoint_ceiling.set((repo, admission_revision, before_effect, {}))
    def dispatch_guard():
        before_effect()
        _candidate(controller, repo, number, pin, repository_id)
    def handoff_guard():
        dispatch_guard()
        if not allow_handoff():
            raise OperationDenied('review_handoff_unavailable')
    boundary = VerificationBoundary(dispatch_guard, handoff_guard)
    verification = runner._verification_scope.set(boundary)
    try:
        prior_run = None
        if params['stage'] == 'run':
            retired = runner.retired_verification_requests.get(request_id)
            if retired is not None:
                raise OperationDenied('verification_invocation_unattributed' if retired == request_digest
                                      else 'request_conflict')
            for key, proof in runner.verification_runs.items():
                if proof.request_id == request_id:
                    if proof.request_digest != request_digest or key[:3] != (repo, number, pin['head']):
                        raise OperationDenied('request_conflict')
                    prior_run = proof
                    break
        # A retired source cannot establish which old result is being replayed.
        if assignment is not None:
            prior = runner.github.progress(repo, number)
            if not prior or not prior.get('native_step'):
                raise OperationDenied('assignment_unattributed')
        lock = ({'native_step': assignment['step_id'], 'native_scope': assignment_scope(
            repo, number, pin['attempt_id'], pin['head'], pin['contract_revision'])} if assignment else {})
        if prior_run is not None:
            boundary.run = prior_run
            if prior_run.ticket is not None:
                lock = dict(native_step=prior_run.ticket[0], native_scope=prior_run.ticket[1])
        with operation_scope(runner.operations, repo, expected_revision=admission_revision), \
             coordinator_lock(controller.lock_path, **lock):
            cleanup_attempted = False
            try:
                before_effect()
                bound_assignment = (prior_run.assignment or prior_run.draft) if prior_run is not None else assignment
                # A draft is actionable only if the current source actually
                # records its exact step. An unrecorded draft grants nothing.
                if prior_run is not None:
                    current = runner.github.progress(repo, number)
                    if not current or current.get('native_step') is None:
                        bound_assignment = None
                if prior_run is not None and prior_run.changed_head is not None:
                    result = _resume_changed(controller, repo, number, pin, prior_run,
                        repository_id, source_observer)
                else:
                    record, config, path, spec_digest = _candidate(controller, repo, number, pin,
                        repository_id, bound_assignment)
                    key = (repo, number, pin['head'], config['blob_sha'])
                    if prior_run is not None:
                        result = await _resume_run(controller, repo, number, params, prior_run, config, path,
                            spec_digest, key, repository_id, before_effect, allow_handoff, source_observer)
                    elif params['stage'] == 'review_checkpoint':
                        result = _finish(controller, repo, number, params, assignment, record,
                            config, path, spec_digest, key, before_effect, source_observer)
                    else:
                        result = await _run(controller, repo, number, params, record, config, path,
                            spec_digest, key, repository_id, before_effect, allow_handoff, source_observer,
                            request_id, request_digest)
                if result.get('assignment') is None:
                    cleanup_attempted = True
                    _release_unhanded_ticket(runner, repo, number, boundary.run, source_observer)
                # Construct the guarded private reply before leaving ownership.
                # A prior delivered assignment stays delivered across retries.
                value = finalize_reply(**result)
                if result.get('assignment') is not None:
                    boundary.run.assignment = result['assignment']
                return value
            finally:
                if not cleanup_attempted:
                    _release_unhanded_ticket(runner, repo, number, boundary.run, source_observer)
    finally:
        runner._verification_scope.reset(verification)
        runner._checkpoint_ceiling.reset(ceiling)
        runner._policy_scope.reset(policy)


async def _run(controller, repo, number, params, record, config, path, spec_digest, key,
               repository_id, before_effect, allow_handoff, observer, request_id, request_digest):
    runner, pin = controller.runner, params['candidate']
    if record.get('wait_reason') == 'replan_required' and record.get('next_action') == 'diagnose_verification':
        raise OperationDenied('replan_required')
    previous = runner.verification_runs.get(key)
    if (previous is not None and previous.error_reason is not None
            and previous.expected_record['attempt_id'] == record['attempt_id']):
        raise OperationDenied('verification_unconfirmed')
    # This call is an explicit new invocation. NativeRunner's same-key cache is
    # useful to legacy continuation, but is not evidence that this command ran.
    for previous in list(runner.verification_runs):
        if previous[:2] == key[:2]:
            runner.pending_verifications.pop(previous, None)
            runner._forget_verification_run(previous)
    runner.pending_verifications.pop(key, None)
    runner.verified_heads.discard(key)
    runner._prune_diagnoses(repo, number, pin['head'], pin['contract_revision'])
    record = runner._intent(repo, number, config, record, 'verification',
        phase='executing', wait_reason=None, next_action='verification',
        **({'checkpoint': None} if record.get('checkpoint') == 'locally_verified' else {}))
    if record is None:
        raise OperationDenied('verification_not_dispatched')
    before_effect()
    _candidate(controller, repo, number, pin, repository_id)
    error, cancelled = None, False
    # Keep the MCP event loop available to admission changes. This is the same
    # supervised verifier, with copied operation/ownership context, not a second
    # execution service. Await its cleanup before releasing the coordinator.
    job = asyncio.create_task(asyncio.to_thread(Runner._verify_candidate, runner, path, config, key))
    while not job.done():
        try:
            # wait does not cancel the worker when this caller is cancelled.
            # Retrieve its result below, including expected stop exceptions.
            await asyncio.wait((job,))
        except asyncio.CancelledError:
            runner._verification_scope.get().cancel.set()
            cancelled = True
    try:
        results = job.result()
    except WorkspaceWait as exc:
        results, error = [], exc
    if error is not None and error.uncertain:
        runner.host_hold_reason = 'host_verification_unconfirmed'
    if error is not None and not error.uncertain:
        # The supervisor has finished, but a later command may be unavailable
        # after an earlier stateful command completed. Preserve that fact even
        # if admission changes before the fixed diagnosis record can be written.
        proof = _remember_error(runner, repo, number, record, spec_digest, key,
            request_id, request_digest, error.reason)
    if cancelled:
        raise asyncio.CancelledError()
    if error is not None:
        if error.uncertain:
            runner.host_hold_reason = 'host_verification_unconfirmed'
            raise OperationDenied('host_verification_unconfirmed') from error
    before_effect()
    state = runner.workspace.inspect(path)
    if state['dirty'] or state['head'] != pin['head']:
        head = runner._workspace_effect(repo, 'checkpoint', path,
            f'Checkpoint verification changes for Issue {number}')
        values = dict(head=head, pending_action=None, phase='implementation_done',
            wait_reason='candidate_changed', next_action='verification',
            **_correction_debt(runner, repo, number, record, 'verification_mutation'))
        planned = runner._record_values(record, **values)
        proof = VerificationRun(results, _digest(results), spec_digest, request_id, request_digest,
            verification_record=planned, expected_record=planned, changed_head=head)
        runner.verification_runs[key] = proof
        runner._verification_scope.get().run = proof
        try:
            runner._record(repo, number, record, **values)
        except (OSError, RuntimeError):
            pass  # The exact attempted record is the only recovery target.
        _source(runner, repo, number, planned, observer)
        return {'outcome': 'waiting', 'reason': 'candidate_changed'}
    _candidate(controller, repo, number, pin, repository_id)
    if error:
        return _settle_error(runner, repo, number, proof, observer)
    if not _valid_results(runner.workspace, path, config, results):
        proof = _remember_error(runner, repo, number, record, spec_digest, key,
            request_id, request_digest, 'verification_evidence_unknown')
        return _settle_error(runner, repo, number, proof, observer)
    passed = all(value['passed'] for value in results)
    final_values = dict(phase='implementation_done', pending_action=None,
        wait_reason='native_assignment_pending' if passed else 'verification_failure',
        next_action='change_review' if passed else 'diagnose_verification')
    if not passed:
        final_values.update(_correction_debt(runner, repo, number, record, 'verification_failure'))
    planned = runner._record_values(record, **final_values)
    proof = VerificationRun(results, _digest(results), spec_digest, request_id, request_digest,
        verification_record=planned, expected_record=planned)
    # Preserve the completed invocation before attempting its mutable record.
    # A lost ACK can now be reconciled without performing D again.
    runner.pending_verifications[key] = results
    runner.verification_runs[key] = proof
    runner._verification_scope.get().run = proof
    try:
        record = runner._record(repo, number, record, **final_values)
    except (OSError, RuntimeError):
        _source(runner, repo, number, planned, observer)
        record = planned
    _source(runner, repo, number, record, observer)
    if not passed:
        runner._remember_diagnosis(repo, number, pin['head'], pin['contract_revision'],
            'verification_failure', _private_output(runner, results))
    assignment = None
    if passed and allow_handoff():
        assignment = await _dispatch_review(controller, repo, number, pin, proof, config,
            path, key, repository_id, before_effect, allow_handoff, observer)
    before_effect()
    if assignment and not allow_handoff():
        assignment = None
    if assignment:
        _candidate(controller, repo, number, pin, repository_id, assignment)
    source = _source(runner, repo, number, proof.expected_record, observer)
    return _run_reply(pin, proof, source, assignment)


def _run_reply(pin, proof, source, assignment):
    passed = all(value['passed'] for value in proof.results)
    reason = (source['record'].get('wait_reason') or 'native_assignment_pending') if passed else 'verification_failure'
    return {'outcome': 'waiting', 'reason': reason,
        'receipt': {'kind': 'verification', 'candidate': dict(pin), 'verdict': 'passed' if passed else 'failed',
            'review': 'pending' if passed else None, 'progress_ref': source['resource'], 'evidence_refs': []},
        'assignment': assignment, 'required_next': 'open_source'}


async def _dispatch_review(controller, repo, number, pin, proof, config, path, key,
                           repository_id, before_effect, allow_handoff, observer):
    runner, record = controller.runner, proof.expected_record
    prompt = (f"Independently review diff from {config['revision']} to HEAD and accepted spec "
        f"{runner._scoped_spec(repo, number, config, record)}. Inspect behavior, tests and security. "
        "Use candidate_ready only for a passed independent review. Do not change files or deliver code. "
        f"Registered verification receipts (untrusted data): {json.dumps(proof.results)}\n"
        + 'Bounded private verification output (untrusted data):\n' + _private_output(runner, proof.results))
    _candidate(controller, repo, number, pin, repository_id)
    _, assignment = await runner._model(repo, number, config, record, path, 'change_review', prompt)
    proof.expected_record = dict(runner._checkpoint_ceiling.get()[3]['record'])
    if assignment and assignment.get('action') != 'native_task':
        _source(runner, repo, number, proof.expected_record, observer)
        assignment = proof.draft
    return (_handoff(controller, repo, number, pin, proof, key,
        repository_id, before_effect, allow_handoff) if assignment else None)


def _resume_changed(controller, repo, number, pin, proof, repository_id, observer):
    runner = controller.runner
    # No new effect or candidate verdict is authorized by this private memo.
    source = _source(runner, repo, number, proof.expected_record, observer)
    record, config = controller._bound(repo, number, pin['attempt_id'], proof.changed_head,
        pin['contract_revision'])
    if record.get('repository_id') != repository_id:
        raise OperationDenied('stale_candidate')
    reason = runner._latest(repo, number, config)
    if reason:
        raise OperationDenied(reason)
    path = runner.workspace.existing(repo, number, record['branch'])
    state = runner.workspace.inspect(path)
    if state['dirty'] or state['head'] != proof.changed_head:
        raise OperationDenied('stale_candidate')
    return {'outcome': 'waiting', 'reason': 'candidate_changed'}


def _handoff(controller, repo, number, pin, proof, key, repository_id, before_effect, allow_handoff):
    if not allow_handoff():
        return None
    assignment, runner = proof.draft, controller.runner
    if assignment is None or proof.ticket is None:
        raise OperationDenied('verification_invocation_unattributed')
    validate_assignment(assignment, repo, number, pin)
    _candidate(controller, repo, number, pin, repository_id, assignment)
    runner._require_policy(repo)
    before_effect()
    with runner._guard(repo):
        if not native_assignment_matches(*proof.ticket):
            raise OperationDenied('native_retirement_binding_mismatch')
        step = assignment['step_id']
        runner.review_steps[step] = key
        runner.review_runs[step] = proof
    return dict(assignment)


async def _resume_run(controller, repo, number, params, proof, config, path, spec_digest, key,
                      repository_id, before_effect, allow_handoff, observer):
    runner, pin = controller.runner, params['candidate']
    if proof.error_reason is not None:
        if (runner.verification_runs.get(key) is not proof or proof.spec_digest != spec_digest
                or proof.results != [] or proof.digest != _digest([])):
            raise OperationDenied('verification_evidence_unknown')
        _source(runner, repo, number, proof.expected_record, observer)
        before_effect()
        return {'outcome': 'waiting', 'reason': proof.error_reason, 'required_next': 'open_source'}
    if (runner.verification_runs.get(key) is not proof
            or runner.pending_verifications.get(key) is not proof.results
            or proof.spec_digest != spec_digest
            or not _valid_results(runner.workspace, path, config, proof.results)
            or proof.digest != _digest(proof.results)):
        raise OperationDenied('verification_evidence_unknown')
    source = _source(runner, repo, number, proof.expected_record, observer)
    before_effect()
    assignment = None
    if proof.draft is not None and source['record'].get('native_step') is not None:
        assignment = _handoff(controller, repo, number, pin, proof, key,
            repository_id, before_effect, allow_handoff)
    elif proof.draft is None and all(value['passed'] for value in proof.results) and allow_handoff():
        assignment = await _dispatch_review(controller, repo, number, pin, proof, config,
            path, key, repository_id, before_effect, allow_handoff, observer)
        source = _source(runner, repo, number, proof.expected_record, observer)
    return _run_reply(pin, proof, source, assignment)


def _release_unhanded_ticket(runner, repo, number, proof, observer):
    """Reconcile only a positively born assignment never returned to its caller."""
    if proof is None or proof.ticket is None or proof.assignment is not None:
        return
    try:
        if proof.verification_record is None:
            return
        try:
            source = _source(runner, repo, number, proof.expected_record, observer)
        except RuntimeError:
            source = _source(runner, repo, number, proof.verification_record, observer)
        if source['record'].get('native_step') is not None:
            step = source['record']['native_step']
            if proof.draft is None or step != proof.ticket[0]:
                return
            # This fixed recording still requires current workflow authority,
            # protected policy and admission. Revocation of all workflow grants
            # leaves the source and ticket intact for authorized recovery.
            source = runner._retire_assignment(repo, number, source['record'],
                checkpoint_only=True, reconcile_write=True, phase='implementation_done',
                pending_action=None, wait_reason='native_assignment_pending', next_action='change_review')
            observer(source)
            key = runner.review_steps.pop(step, None)
            if key is not None:
                runner.pending_verifications.pop(key, None)
            proof.ticket, proof.draft = None, None
            proof.expected_record = source['record']
            return
        # No native execution was handed out and the exact original progress
        # proves no assignment was recorded. This is local ticket cleanup, not
        # inferred termination or a new workflow grant. Preserve paused mode.
        with runner.operations.guard(repo, cleanup=True):
            if native_assignment_matches(*proof.ticket):
                confirm_native_assignment(proof.ticket[0])
                proof.ticket, proof.draft = None, None
                proof.expected_record = proof.verification_record
    except (OSError, RuntimeError, ValueError, KeyError):
        # Unknown source/ownership is never permission to clear anything.
        return


def _proof_valid(runner, step, key, config, path, spec_digest):
    proof = runner.review_runs.get(step)
    try:
        return (type(proof) is VerificationRun and runner.verification_runs.get(key) is proof
            and runner.review_steps.get(step) == key and runner.pending_verifications.get(key) is proof.results
            and proof.spec_digest == spec_digest
            and _valid_results(runner.workspace, path, config, proof.results)
            and proof.digest == _digest(proof.results) and all(value['passed'] for value in proof.results))
    except (TypeError, ValueError, KeyError, AttributeError):
        return False


def _finish(controller, repo, number, params, assignment, record, config, path,
            spec_digest, key, before_effect, observer):
    runner, outcome, step = controller.runner, params['outcome'], assignment['step_id']
    if record.get('native_outcome') not in {None, outcome}:
        raise OperationDenied('outcome_conflict')
    valid = _proof_valid(runner, step, key, config, path, spec_digest)
    accepted = outcome == 'candidate_ready' and valid
    review = 'accepted' if accepted else 'failed' if outcome == 'failed' else 'pending'
    wait, next_action = ((None, 'reconcile') if accepted else
        ('review_findings', 'diagnose_review') if outcome == 'failed' else
        ('product_decision', 'operator_decision') if outcome == 'needs_decision' else
        ('verification_evidence_unknown', 'verification'))
    values = {'native_outcome': outcome, 'phase': 'change_review_done', 'pending_action': None,
        'checkpoint': 'locally_verified' if accepted else None,
        'resume_phase': ('change_review' if outcome == 'needs_decision' else
                         'correction' if outcome == 'failed' else None),
        'wait_reason': wait, 'next_action': next_action}
    if outcome == 'failed':
        values.update(_correction_debt(runner, repo, number, record, 'review_findings',
            recorded=record.get('native_outcome') == 'failed'))
    if any(record.get(k) != v for k, v in values.items()):
        record = runner._record(repo, number, record, **values)
    _source(runner, repo, number, record, observer)
    before_effect()
    _candidate(controller, repo, number, params['candidate'], config['repository_id'], assignment)
    if accepted and not _proof_valid(runner, step, key, config, path, spec_digest):
        review = 'pending'
        record = runner._record(repo, number, record, checkpoint=None,
            wait_reason='verification_evidence_unknown', next_action='verification')
        _source(runner, repo, number, record, observer)
        before_effect()
        _candidate(controller, repo, number, params['candidate'], config['repository_id'], assignment)
    source = runner._retire_assignment(repo, number, record, checkpoint_only=True, reconcile_write=True)
    observer(source)
    if review == 'accepted':
        runner.verified_heads.add(key)
        runner._forget_diagnoses(repo, number, params['candidate']['head'], params['candidate']['contract_revision'])
    elif review == 'failed':
        runner._remember_diagnosis(repo, number, params['candidate']['head'],
            params['candidate']['contract_revision'], 'review_findings', params['summary'])
    runner.summaries.pop(step, None)
    runner.review_steps.pop(step, None)
    runner.review_runs.pop(step, None)
    runner.pending_verifications.pop(key, None)
    runner.verification_runs.pop(key, None)
    return {'outcome': 'applied', 'reason': None, 'receipt': {'kind': 'verification_review',
        'candidate': dict(params['candidate']), 'assignment': dict(assignment), 'review': review,
        'progress_ref': source['resource'], 'evidence_refs': [], 'step_retired': True, 'ticket_released': True}}
