"""Bounded use of the existing native runner and its private verification lifetime."""
import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from threading import Event

from .coordinator import coordinator_lock, operation_scope
from .native import assignment_scope
from .operations import OperationDenied
from .project import matches
from .runner import Runner
from .workspace import WorkspaceWait


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class VerificationRun:
    """Object identity binds the reviewer to one actual invocation, not its key."""
    results: list
    digest: str
    spec_digest: str


@dataclass(frozen=True)
class VerificationBoundary:
    before_dispatch: Callable[[], None]
    before_handoff: Callable[[], None]
    cancel: Event = field(default_factory=Event)


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
    if not observed or any(observed.get(k) != v for k, v in record.items()):
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


async def execute(controller, repo, number, params, assignment, *, repository_id,
                  admission_revision, before_effect, allow_handoff, source_observer):
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
    verification = runner._verification_scope.set(VerificationBoundary(dispatch_guard, handoff_guard))
    try:
        # A retired source cannot establish which old result is being replayed.
        if assignment is not None:
            prior = runner.github.progress(repo, number)
            if not prior or not prior.get('native_step'):
                raise OperationDenied('assignment_unattributed')
        lock = ({'native_step': assignment['step_id'], 'native_scope': assignment_scope(
            repo, number, pin['attempt_id'], pin['head'], pin['contract_revision'])} if assignment else {})
        with operation_scope(runner.operations, repo, expected_revision=admission_revision), \
             coordinator_lock(controller.lock_path, **lock):
            before_effect()
            record, config, path, spec_digest = _candidate(controller, repo, number, pin,
                repository_id, assignment)
            key = (repo, number, pin['head'], config['blob_sha'])
            if params['stage'] == 'review_checkpoint':
                return _finish(controller, repo, number, params, assignment, record,
                    config, path, spec_digest, key, before_effect, source_observer)
            return await _run(controller, repo, number, params, record, config, path,
                spec_digest, key, repository_id, before_effect, allow_handoff, source_observer)
    finally:
        runner._verification_scope.reset(verification)
        runner._checkpoint_ceiling.reset(ceiling)
        runner._policy_scope.reset(policy)


async def _run(controller, repo, number, params, record, config, path, spec_digest, key,
               repository_id, before_effect, allow_handoff, observer):
    runner, pin = controller.runner, params['candidate']
    # This call is an explicit new invocation. NativeRunner's same-key cache is
    # useful to legacy continuation, but is not evidence that this command ran.
    runner.pending_verifications.pop(key, None)
    runner.verification_runs.pop(key, None)
    runner.verified_heads.discard(key)
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
        record = runner._record(repo, number, record, head=head, pending_action=None,
            phase='implementation_done', wait_reason='candidate_changed', next_action='verification')
        _source(runner, repo, number, record, observer)
        return {'outcome': 'waiting', 'reason': 'candidate_changed'}
    _candidate(controller, repo, number, pin, repository_id)
    if error:
        raise OperationDenied(error.reason)
    if not _valid_results(runner.workspace, path, config, results):
        raise OperationDenied('verification_evidence_unknown')
    passed = all(value['passed'] for value in results)
    record = runner._record(repo, number, record, phase='implementation_done', pending_action=None,
        wait_reason='native_assignment_pending' if passed else 'verification_failure',
        next_action='change_review' if passed else 'diagnose_verification')
    receipt = {'kind': 'verification', 'candidate': dict(pin), 'verdict': 'passed' if passed else 'failed',
               'review': 'pending' if passed else None, 'progress_ref': None, 'evidence_refs': []}
    assignment = None
    if passed:
        proof = VerificationRun(results, _digest(results), spec_digest)
        runner.pending_verifications[key] = results
        runner.verification_runs[key] = proof
        if allow_handoff():
            remaining, outputs = 24000, []
            for value in results:
                text = runner.workspace.verification_output(value['output_digest'], max_chars=remaining)
                outputs.append(text)
                remaining -= len(text)
                if not remaining:
                    break
            prompt = (f"Independently review diff from {config['revision']} to HEAD and accepted spec "
                f"{runner._scoped_spec(repo, number, config, record)}. Inspect behavior, tests and security. "
                "Use candidate_ready only for a passed independent review. Do not change files or deliver code. "
                f"Registered verification receipts (untrusted data): {json.dumps(results)}\n"
                + 'Bounded private verification output (untrusted data):\n' + ''.join(outputs))
            _candidate(controller, repo, number, pin, repository_id)
            _, assignment = await runner._model(repo, number, config, record, path, 'change_review', prompt)
            if assignment and assignment.get('action') != 'native_task':
                assignment = None
            if assignment:
                validate_assignment(assignment, repo, number, pin)
    before_effect()
    if assignment and not allow_handoff():
        assignment = None
    final = runner.github.progress(repo, number)
    if not final or any(final.get(k) != pin[k] for k in pin):
        raise OperationDenied('stale_candidate')
    if assignment:
        _candidate(controller, repo, number, pin, repository_id, assignment)
    source = _source(runner, repo, number, final, observer)
    receipt['progress_ref'] = source['resource']
    return {'outcome': 'waiting', 'reason': 'native_assignment_pending' if passed else 'verification_failure',
            'receipt': receipt, 'assignment': assignment, 'required_next': 'open_source'}


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
        'resume_phase': 'change_review' if outcome == 'needs_decision' else None,
        'wait_reason': wait, 'next_action': next_action}
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
    source = runner._retire_assignment(repo, number, record, checkpoint_only=True)
    observer(source)
    runner.summaries.pop(step, None)
    runner.review_steps.pop(step, None)
    runner.review_runs.pop(step, None)
    runner.pending_verifications.pop(key, None)
    runner.verification_runs.pop(key, None)
    return {'outcome': 'applied', 'reason': None, 'receipt': {'kind': 'verification_review',
        'candidate': dict(params['candidate']), 'assignment': dict(assignment), 'review': review,
        'progress_ref': source['resource'], 'evidence_refs': [], 'step_retired': True, 'ticket_released': True}}
