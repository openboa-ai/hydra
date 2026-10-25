"""Native task continuations; GitHub progress and the host ticket survive calls.

No model is invoked here. Candidate results are judgments, never delivery evidence.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from contextlib import nullcontext
from pathlib import Path
from contextvars import ContextVar

from .coordinator import (confirm_native_assignment, coordinator_lock,
                          native_assignment_matches, register_native_assignment, residual_workers, operation_scope)
from .runner import Runner, intake_digest, issue_url
from .project import load_project, matches, parse_intake
from .operations import OperationDenied
from .progress import with_progress_hint

NATIVE_FIELDS = {"native_step", "native_phase", "native_head", "native_outcome", "native_spec_digest",
                 "native_origin_phase", "native_resume_phase", "native_correction", "native_completion"}
_FINISHED_CHECKPOINT = 'native_complete_'


def _completed_checkpoint(record, outcome):
    """Closed final source states; an outcome-only legacy write is not completion."""
    if record.get('pending_action') is not None or record.get('native_outcome') != outcome:
        return False
    if (record.get('checkpoint') or '').startswith(_FINISHED_CHECKPOINT):
        return True
    phase, next_action, wait = record.get('phase'), record.get('next_action'), record.get('wait_reason')
    if outcome == 'stopped':
        return phase == 'checkpoint' and record.get('checkpoint') == 'interrupted_committed' and next_action in {
            'reconcile', 'operator_decision', 'diagnose'} and wait in {
            'stop_requested', 'remote_head_changed', 'product_decision', 'replan_required'}
    if outcome == 'needs_decision':
        completed = (phase == record['native_phase'] + '_done' or
                     phase == 'design_done' and record.get('correction_reason') == 'accepted_spec_changed')
        return (completed and next_action == 'operator_decision' and wait == 'product_decision'
                and record.get('resume_phase') == (record.get('native_resume_phase') or record['native_phase']))
    correction = record.get('native_correction')
    if correction:
        completed = (record['native_origin_phase'] if correction == 'integration_changed' else
                     'design_done' if record['native_phase'] == 'design' else 'implementation_done')
        resume = record.get('native_resume_phase') if correction == 'integration_changed' or record['native_phase'] == 'design' else None
        if (phase == completed and record.get('checkpoint') == f"correction_{record.get('correction_attempt')}_{correction}"
            and next_action == ('reconcile' if correction == 'integration_changed' else 'verification')
            and wait is None and record.get('resume_phase') == resume):
            return True
    elif (wait is None and record.get('resume_phase') is None and (phase, next_action) == (
            ('design_done', 'spec_review') if record['native_phase'] == 'design' else ('implementation_done', 'verification'))):
        return True
    # Accepted-spec records can precede scope/budget diagnosis. Until the full
    # completion marker is read back, reconcile that retained step below.
    return False


def assignment_scope(repo, number, attempt, head, policy):
    """Bounded admission identity, not a second workflow record."""
    return hashlib.sha256(json.dumps([repo.casefold(), number, attempt, head, policy],
                                    separators=(",", ":")).encode()).hexdigest()


class NativeRunner(Runner):
    native = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, execute=None, capabilities=None, **kwargs)
        self.consumed = set()
        self.summaries = {}
        self.pending_verifications = {}
        self.review_steps = {}
        # These links live exactly as long as the private verification/review
        # caches. A matching candidate key does not identify an invocation.
        self.verification_runs = {}
        self.review_runs = {}
        # Bounded, process-local request tombstones contain no result/transcript.
        # They prevent a known completed UI request from becoming a fresh run.
        self.retired_verification_requests = {}
        self.decision_source = None
        self._continuation_scope = ContextVar('hydra_native_continuation', default=None)
        self.technical_replan_attempts = {}
        self.technical_replan_observations = {}

    def _decision_frame(self):
        bound = self._policy_scope.get()
        return bound[2] if bound is not None and len(bound) == 3 else None

    def _work_config(self, repo, number, record):
        return {**super()._work_config(repo, number, record), '_work_number': number}

    def _bind_policy(self, repo, config):
        from .work_decisions import WorkDecisionGuard
        previous = self._decision_frame()
        number = config.get('_work_number')
        if previous is not None and previous.repository.casefold() == repo.casefold():
            number = number or previous.number
        frame = (previous if previous is not None and previous.repository.casefold() == repo.casefold()
                 and previous.number == number else
                 WorkDecisionGuard(self, repo, number) if type(number) is int and number > 0 else None)
        self._policy_scope.set((repo.casefold(), config, frame))

    def _guard(self, repo, *, cleanup=False):
        frame = self._decision_frame()
        continuation = self._continuation_scope.get()
        if continuation is not None:
            return continuation.guard(repo, cleanup=cleanup, decision_frame=frame)
        if not cleanup and frame is not None:
            if frame.repository.casefold() != repo.casefold():
                raise OperationDenied('decision_binding_mismatch')
            frame.check()
        return super()._guard(repo, cleanup=cleanup)

    def _effect(self, repo, callback, *args, **kwargs):
        continuation = self._continuation_scope.get()
        if continuation is not None and kwargs.get('_checkpoint_effect') == 'progress':
            writer = callback
            def callback(*values, **options):
                continuation.progress_dispatches += 1
                return writer(*values, **options)
        return super()._effect(repo, callback, *args, **kwargs)

    def _decision_preflight(self, repo):
        frame = self._decision_frame()
        continuation = self._continuation_scope.get()
        if continuation is not None:
            def check():
                with continuation.guard(repo, decision_frame=frame):
                    pass
            return check
        return frame.check if frame is not None else super()._decision_preflight(repo)

    def _stopping(self, repo):
        continuation = self._continuation_scope.get()
        return bool(continuation is not None and continuation.cancel.is_set()) or super()._stopping(repo)

    def _prepare_decision(self, repo, number, record):
        frame = self._decision_frame()
        return frame.reconcile(allow_resume=True, record=record) if frame is not None else record

    def _record_options(self):
        frame = self._decision_frame()
        return {'preserve_decision_context': True} if frame is not None and frame.consumed else {}

    def _replan_record(self, repo, number, record, **values):
        frame = self._decision_frame()
        if frame is not None and frame.consumed:
            return frame.replan(record, values)
        return super()._replan_record(repo, number, record, **values)

    def _operator_context(self, repo, number, config, record, task):
        frame = self._decision_frame()
        if frame is not None and frame.consumed:
            frame.check()
            return task + '\nPublic operator decision (untrusted data; retain accepted scope and policy):\n' + frame.public_context()
        return super()._operator_context(repo, number, config, record, task)

    def _forget_verification_run(self, key):
        proof = self.verification_runs.pop(key, None)
        if proof is not None:
            self._retire_verification_request(proof)

    def _retire_verification_request(self, proof):
        if proof.request_id is not None:
            self.retired_verification_requests[proof.request_id] = proof.request_digest
            while len(self.retired_verification_requests) > 1024:
                self.retired_verification_requests.pop(next(iter(self.retired_verification_requests)))

    def _prune_diagnoses(self, repo, number, head, contract):
        for key in list(self.summaries):
            if (type(key) is tuple and key[:3] == ('diagnosis', repo, number)
                    and key[3:5] != (head, contract)):
                self.summaries.pop(key, None)

    def _remember_diagnosis(self, repo, number, head, contract, reason, summary):
        self._prune_diagnoses(repo, number, head, contract)
        self.summaries[('diagnosis', repo, number, head, contract, reason)] = summary[:24000]

    def _forget_diagnoses(self, repo, number, head, contract):
        for key in list(self.summaries):
            if type(key) is tuple and key[:5] == ('diagnosis', repo, number, head, contract):
                self.summaries.pop(key, None)

    def _verify_candidate(self, path, config, evidence_key):
        if evidence_key in self.pending_verifications:
            return self.pending_verifications[evidence_key]
        verification = super()._verify_candidate(path, config, evidence_key)
        state = self.workspace.inspect(path)
        if verification and all(v["passed"] for v in verification) and not state["dirty"] and state["head"] == evidence_key[2]:
            self.pending_verifications[evidence_key] = verification
        return verification

    def _record(self, repo, number, record, **values):
        frame = self._decision_frame()
        if frame is not None and self._cleanup_scope.get() is None:
            frame.check()
        if record.get("native_step") in self.consumed:
            record = {k: v for k, v in record.items() if k not in NATIVE_FIELDS}
        result = super()._record(repo, number, record, **values)
        continuation = self._continuation_scope.get()
        if continuation is not None:
            continuation.recorded(result)
        return result

    def _retire_assignment(self, repo, number, record, *, checkpoint_only=False, reconcile_write=False, **values):
        """One fixed retirement, with remote policy observed before admission.

        This synchronous operation never grants a policy bypass to a callback
        or subsequent work. The coordinator owns the exact original assignment.
        """
        allowed = {"phase", "pending_action", "resume_phase", "wait_reason", "next_action"}
        ceiling = self._checkpoint_ceiling.get()
        if type(checkpoint_only) is not bool:
            raise OperationDenied("native_retirement_binding_mismatch")
        if (type(reconcile_write) is not bool or reconcile_write and
                (not checkpoint_only or self._verification_scope.get() is None)):
            raise OperationDenied("native_retirement_binding_mismatch")
        if checkpoint_only:
            if ceiling is None or ceiling[0] != repo:
                raise OperationDenied("checkpoint_binding_mismatch")
            allowed.add("checkpoint")
        elif ceiling is not None:
            raise OperationDenied("checkpoint_effect_unsupported")
        if set(values) - allowed:
            raise OperationDenied("native_retirement_binding_mismatch")
        step = record.get("native_step")
        if not step or record.get("execution_mode") != "native" or record.get("host_alias") != self.host:
            raise OperationDenied("native_retirement_binding_mismatch")
        scope = assignment_scope(repo, number, record["attempt_id"],
                                 record["native_head"], record["contract_revision"])
        clean = {k: v for k, v in self._record_values(record, **values).items() if k not in NATIVE_FIELDS}
        cleanup = checkpoint_only and self._cleanup_scope.get() == (repo, number, record["attempt_id"])
        writer = getattr(self.github, "record_checkpoint", None) if checkpoint_only else self.github.record
        if not callable(writer):
            raise OperationDenied("checkpoint_recording_unavailable")
        if not cleanup:
            self._require_policy(repo)
        if checkpoint_only:
            ceiling[2]()
        with self._guard(repo, cleanup=cleanup) if checkpoint_only else self._guard(repo):
            if not native_assignment_matches(step, scope):
                raise OperationDenied("native_retirement_binding_mismatch")
            if checkpoint_only:
                observer = ceiling[3].get('before_progress')
                if observer is not None:
                    observer()
            try:
                writer(repo, number, clean, **self._record_options())
                continuation = self._continuation_scope.get()
                if continuation is not None:
                    continuation.recorded(clean)
            except (OSError, RuntimeError):
                if not reconcile_write:
                    raise
                # The original write was attempted under this exact ticket.
                # Read back once; never retransmit or infer from partial state.
            source = self.github.progress_source(repo, number) if checkpoint_only else None
            observed = (source["record"] if source else None) if checkpoint_only else self.github.progress(repo, number)
            if (not observed or observed.get("native_step") or any(observed.get(k) != v for k, v in clean.items())
                    or checkpoint_only and any(k in observed for k in NATIVE_FIELDS)):
                raise RuntimeError("Native retirement is unconfirmed")
            if reconcile_write and self._record_values(observed) != clean:
                raise RuntimeError("Native retirement source changed")
            confirm_native_assignment(step)
            self.consumed.add(step)
            if record.get('native_correction') and record.get('native_outcome') == 'candidate_ready':
                self._forget_diagnoses(repo, number, record['native_head'], record['contract_revision'])
            self.review_runs.pop(step, None)
            key = self.review_steps.get(step)
            if key is not None:
                self._forget_verification_run(key)
        return source if checkpoint_only else clean

    async def step(self, repo, number):
        record = self.github.progress(repo, number)
        if (record and record.get('execution_mode') == 'native' and record.get('host_alias') == self.host
                and record.get('native_step') and record.get('native_completion') is not None):
            return with_progress_hint({'repository': repo, 'issue': number, 'action': 'waiting',
                'reason': 'verify_only_completion_required'})
        if (record and record.get('host_alias') == self.host and record.get('phase') == 'executing'
                and record.get('pending_action') == 'verification'
                and not any(key[:2] == (repo.casefold(), number) for key in self._pending_ended)):
            # A source intent without its owned end witness cannot authorize a
            # second invocation after restart. Real pending-ended cleanup is
            # still handled by Runner.step before ordinary continuation.
            return with_progress_hint({'repository': repo, 'issue': number, 'action': 'waiting',
                'reason': 'verification_unconfirmed'})
        if (record and record.get("execution_mode") == "native" and record.get("host_alias") == self.host
                and record.get("phase") == "checkpoint" and record.get("checkpoint") == "interrupted_committed"
                and self.github.ref(repo, record["branch"]) != record.get("expected_head")):
            # Local shutdown grants no authority to adopt a changed/deleted ref.
            return with_progress_hint({"repository": repo, "issue": number, "action": "waiting", "reason": "remote_head_changed"})
        return await super().step(repo, number)

    async def _model(self, repo, number, config, record, path, phase, task, *, correction=None, spec_record=None):
        reason = self._latest(repo, number, config)
        if reason:
            return None, self._wait(repo, number, record, reason)
        self.knowledge_revision()
        boundary, remote, _ = self._branch_boundary(repo, number, record)
        if boundary or remote not in {None, record.get("head"), record.get("expected_head")}:
            return None, self._wait(repo, number, record, boundary or "remote_head_changed")
        config = {**config, "_scoped_spec": self._scoped_spec(repo, number, config, record)}
        digest = (hashlib.sha256(self.workspace.read_spec(path, config["_scoped_spec"])).hexdigest()
                  if self.workspace.valid_spec(path, config["_scoped_spec"], require_tracked=False) else None)
        step = record.get("native_step")
        evidence_key = (repo, number, record["head"], config["blob_sha"])
        if (step and phase == "change_review" and record.get("native_outcome") not in {None, "needs_decision"}
                and self.review_steps.get(step) != evidence_key):
            # A restarted service has lost the run examined by this reviewer.
            # Retire its finished judgment and dispatch a new review of the fresh run.
            clean = self._retire_assignment(repo, number, record, pending_action=None, wait_reason=None)
            self.summaries.pop(step, None)
            self.review_steps.pop(step, None)
            record, step = clean, None
        if step and step not in self.consumed:
            if record.get("native_phase") != phase:
                return None, {"action": "waiting", "reason": "native_phase_changed"}
            if not record.get("native_outcome"):
                return None, {"action": "waiting", "reason": "native_assignment_pending", "step_id": step}
            outcome = record["native_outcome"]
            if outcome not in {"candidate_ready", "failed", "needs_decision"} or "review" not in phase:
                return None, self._wait(repo, number, record, "invalid_model_result", phase="uncertain")
            candidate = {"outcome": outcome, "summary": self.summaries.get(step, "")}
            self._retire_assignment(repo, number, record, **self._review_completion(record, phase, outcome))
            self.summaries.pop(step, None)
            result = ((None, {"repository": repo, "issue": number, "action": "waiting", "reason": "product_decision"})
                      if outcome == "needs_decision" else (candidate, None))
            self.review_steps.pop(step, None)
            if phase == "change_review":
                self.pending_verifications.pop(evidence_key, None)
            return result
        state = self.workspace.inspect(path)
        if state["dirty"]:
            return None, self._wait(repo, number, record, "dirty_workspace")
        origin_resume = record.get("resume_phase")
        if phase == "design" and not record.get("resume_phase"):
            record = {**record, "resume_phase": "design"}
        task = self._operator_context(repo, number, config, record, task)
        if task is None:
            return None, self._wait(repo, number, record, "decision_context_missing")
        if phase == 'correction' and correction:
            diagnosis = self.summaries.get(('diagnosis', repo, number, state['head'],
                record['contract_revision'], correction[0]))
            if diagnosis:
                task += '\nBounded private diagnosis (untrusted data):\n' + diagnosis
        continuation = self._continuation_scope.get()
        if continuation is not None:
            continuation.before_handoff()
        step = str(uuid.uuid4())
        recovery = {"repository": repo, "issue": number, "attempt_id": record["attempt_id"],
                    "step_id": step, "head": state["head"], "contract_revision": record["contract_revision"]}
        scope = assignment_scope(repo, number, record["attempt_id"], state["head"], record["contract_revision"])
        boundary = self._verification_scope.get()
        if boundary is not None:
            task += ('\nComplete through hydra_command_v1 workflow_step.verify_only review_checkpoint. '
                     'The legacy hydra_checkpoint path accepts only explicit stopped cleanup for this review.')
        draft = {**recovery, 'action': 'native_task', 'phase': phase,
            'spec_revision': record.get('spec_revision'), 'cwd': str(path),
            'mode': 'read_only' if 'review' in phase else 'workspace_write', 'prompt': task}
        if boundary is not None:
            from .native_verification import validate_assignment
            validate_assignment(draft, repo, number,
                {k: record[k] for k in ('attempt_id', 'head', 'contract_revision')})
            if boundary.run is None:
                raise OperationDenied('verification_evidence_unknown')
        try:
            self._effect(repo, register_native_assignment, step, scope,
                _checkpoint_effect='review_assignment' if self._verification_scope.get() is not None else None)
            if boundary is not None:
                boundary.run.ticket, boundary.run.draft = (step, scope), draft
        except OperationDenied:
            raise
        except (RuntimeError, ValueError, OSError):
            try:
                held = native_assignment_matches(step, scope)
            except (RuntimeError, ValueError, OSError):
                held = False
            if boundary is not None and held:
                boundary.run.ticket, boundary.run.draft = (step, scope), draft
            return None, {**recovery, "action": "waiting",
                          "reason": "assignment_ticket_unconfirmed" if held else "assignment_ticket_unknown"}
        before_intent = continuation.progress_dispatches if continuation is not None else None
        try:
            record = self._intent(repo, number, config, record, None,
                head=state['head'], execution_mode="native", native_step=step, native_phase=phase,
                native_head=state["head"], native_spec_digest=digest, native_outcome=None,
                native_origin_phase=record["phase"], native_resume_phase=origin_resume,
                native_correction=correction[0] if correction else None,
                wait_reason="native_assignment_pending", next_action=phase, expected_head=remote,
                **({"resume_phase": record.get("resume_phase") or phase}
                   if phase in {"implementation", "correction"} else {}),
                **({'native_completion': 'verify_only'} if boundary is not None else {}),
                **({"correction_reason": correction[0], "correction_attempt": correction[1]} if correction else {}))
        except (RuntimeError, ValueError, OSError):
            if continuation is not None:
                continuation.release_undispatched_ticket(step, scope, before_intent)
            return None, {**recovery, "action": "waiting", "reason": "assignment_record_unknown"}
        if record is None:
            if continuation is not None:
                continuation.release_undispatched_ticket(step, scope, before_intent)
            return None, {**recovery, "action": "waiting", "reason": "assignment_record_unconfirmed"}
        # A ticket plus intent is not yet a grant. Recheck protected policy
        # outside the admission lock, then guard the final handoff itself.
        try:
            reason = self._latest(repo, number, config)
            if reason:
                return None, {**recovery, "action": "waiting", "reason": reason}
            self._require_policy(repo)
            with self._guard(repo):
                if phase == "change_review":
                    self.review_steps[step] = evidence_key
                    if self._verification_scope.get() is not None:
                        self.review_runs[step] = self.verification_runs.get(evidence_key)
                return None, {"repository": repo, "issue": number, "action": "native_task",
                    "attempt_id": record["attempt_id"], "step_id": step, "phase": phase,
                    "head": state["head"], "contract_revision": record["contract_revision"],
                    "spec_revision": record.get("spec_revision"), "cwd": str(path),
                    "mode": "read_only" if "review" in phase else "workspace_write", "prompt": task}
        except OperationDenied as exc:
            return None, {**recovery, "action": "waiting", "reason": exc.reason}
        except (RuntimeError, ValueError, OSError):
            return None, {**recovery, "action": "waiting", "reason": "assignment_observation_unavailable"}


class NativeController:
    def __init__(self, github, workspace, *, repos, host_alias, lock_path, knowledge_revision=lambda: None,
                 operations=None, decision_source=None, creation_source=None):
        if isinstance(repos, (str, bytes)):
            raise ValueError("A host repository allowlist is required")
        try:
            repos = tuple(repos)
        except TypeError:
            raise ValueError("A host repository allowlist is required") from None
        if any(not isinstance(r, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", r) for r in repos):
            raise ValueError("A host repository allowlist is required")
        self.repos = tuple({r.casefold(): r for r in repos}.values())
        self.lock_path = Path(lock_path)
        self.runner = NativeRunner(github, workspace, host_alias=host_alias, knowledge_revision=knowledge_revision,
                                   operations=operations)
        self.decision_source = decision_source
        # Explicit installed dependencies only. Constructors and command JSON
        # cannot qualify a production history source or grant current ownership.
        self.creation_source = creation_source
        self.creation_observations = {}

    @property
    def decision_source(self):
        return self.runner.decision_source

    @decision_source.setter
    def decision_source(self, value):
        # Installed trusted code supplies a qualified adapter. No command JSON
        # or default transport can install one or certify its qualification.
        self.runner.decision_source = value

    def _issue(self, url):
        repo, n = issue_url(url)
        if repo.casefold() not in {r.casefold() for r in self.repos}:
            raise ValueError("Issue is outside the installed repository allowlist")
        return repo, n

    def status(self):
        return self.runner.status(self.repos)

    async def _entry(self, url, callback, *args, cleanup=False):
        repo, n = self._issue(url)
        policy_token = self.runner._policy_scope.set(None)
        try:
            with operation_scope(self.runner.operations, repo):
                if not cleanup:
                    reason = self.runner._operation_reason(repo)
                    if reason:
                        return with_progress_hint({"repository": repo, "issue": n, "action": "waiting", "reason": reason})
                try:
                    return with_progress_hint(await callback(url, *args))
                except OperationDenied as exc:
                    return with_progress_hint({"repository": repo, "issue": n, "action": "waiting", "reason": exc.reason})
        finally:
            self.runner._policy_scope.reset(policy_token)

    async def begin(self, url):
        return await self._entry(url, self._begin)

    async def checkpoint(self, url, attempt_id, step_id, head, contract_revision, outcome, summary=""):
        return await self._entry(url, self._checkpoint, attempt_id, step_id, head,
                                 contract_revision, outcome, summary, cleanup=outcome == "stopped")

    async def advance(self, url, attempt_id, head, contract_revision):
        return await self._entry(url, self._advance, attempt_id, head, contract_revision)

    async def _checkpoint_only(self, repo, number, assignment, outcome, *, repository_id, admission_revision, before_effect, source_observer=None):
        """Internal, already-authorized original-phase completion. No dispatch."""
        runner = self.runner
        policy = runner._policy_scope.set(None)
        ceiling = runner._checkpoint_ceiling.set((repo, admission_revision, before_effect, {}))
        try:
            with operation_scope(runner.operations, repo), coordinator_lock(self.lock_path,
                    native_step=assignment['step_id'], native_scope=assignment_scope(repo, number,
                    assignment['attempt_id'], assignment['head'], assignment['contract_revision'])):
                record, config = self._bound(repo, number, assignment['attempt_id'], assignment['head'],
                    assignment['contract_revision'], assignment['step_id'], stopping=outcome == 'stopped')
                if record is None:
                    raise OperationDenied('assignment_unattributed')
                if record.get('repository_id') != repository_id or config.get('repository_id') != repository_id:
                    raise OperationDenied('stale_assignment')
                if record.get('spec_revision') != assignment['spec_revision']:
                    raise OperationDenied('stale_assignment')
                phase = record['native_phase']
                if phase not in {'design', 'implementation', 'correction'}:
                    raise OperationDenied('unsupported_phase')
                if outcome != 'stopped' and record.get('native_outcome') not in {None, outcome}:
                    raise OperationDenied('outcome_conflict')
                reason = runner._latest(repo, number, {**config, 'intake_digest': record['intake_digest']})
                if reason and outcome != 'stopped':
                    raise OperationDenied(reason)
                path = runner.workspace.existing(repo, number, record['branch'])
                state = runner.workspace.inspect(path)
                finished = (_completed_checkpoint(record, outcome)
                    and record.get('head') == state['head'] and not state['dirty'])
                scope_recovery = False
                if (phase == 'design' and outcome != 'stopped'
                        and not (record.get('checkpoint') or '').startswith(_FINISHED_CHECKPOINT)):
                    base = assignment['head'] if record.get('native_correction') and record.get('spec_revision') else config['revision']
                    spec = runner._scoped_spec(repo, number, config, record)
                    problem = runner._design_problem(path, base, spec, require_tracked=True)
                    if problem and (outcome == 'candidate_ready' or problem[0] == 'implementation_before_design_acceptance'):
                        finished = False
                        scope_recovery = record.get('native_outcome') == outcome and record.get('head') == state['head'] and not state['dirty']
                recovering = (record.get('native_outcome') == outcome and record.get('phase') == 'checkpoint'
                    and record.get('next_action') == 'checkpoint_only' and record.get('head') == state['head'])
                recovering_spec = (record.get('native_outcome') == outcome and record.get('phase') == 'design_done'
                    and record.get('correction_reason') == 'accepted_spec_changed'
                    and record.get('correction_attempt') in {None, 1, 2, 3}
                    and record.get('next_action') in {'spec_review', 'diagnose', 'operator_decision'}
                    and record.get('head') == state['head'] and not state['dirty'])
                if outcome != 'stopped' and state['head'] != assignment['head'] and not (finished or recovering or recovering_spec or scope_recovery):
                    raise OperationDenied('checkpoint_head_unknown')
                # The trusted before_effect adapter independently proves ended
                # execution for stopped requests; the JSON outcome is no proof.
                # Cleanup relaxes mode only, never runtime/revision/ownership.
                with runner._confirmed_cleanup(repo, number, record) if outcome == 'stopped' else nullcontext():
                    if not finished:
                        record = self._complete_checkpoint_phase(repo, number, config, record, path,
                            assignment, outcome)
                    final = runner.github.progress(repo, number)
                    if not final or any(final.get(key) != value for key, value in record.items()):
                        raise RuntimeError('Checkpoint final record unconfirmed')
                    if not (final.get('checkpoint') or '').startswith(_FINISHED_CHECKPOINT):
                        marker = _FINISHED_CHECKPOINT + ('null' if final.get('checkpoint') is None
                                                        else 'value_' + final['checkpoint'])
                        if len(marker) > 120:
                            raise OperationDenied('checkpoint_marker_unavailable')
                        final = runner._record(repo, number, final, checkpoint=marker)
                        observed = runner.github.progress(repo, number)
                        if not observed or any(observed.get(key) != value for key, value in final.items()):
                            raise RuntimeError('Checkpoint completion marker unconfirmed')
                    prior_checkpoint = final['checkpoint'][len(_FINISHED_CHECKPOINT):]
                    if prior_checkpoint == 'null':
                        original_checkpoint = None
                    elif prior_checkpoint.startswith('value_'):
                        original_checkpoint = prior_checkpoint[len('value_'):]
                    else:
                        raise OperationDenied('checkpoint_marker_unavailable')
                    source = runner._retire_assignment(repo, number, final, checkpoint_only=True,
                        checkpoint=original_checkpoint)
                    observed = source['record']
                    runner.summaries.pop(assignment['step_id'], None)
                    if source_observer is not None:
                        source_observer(source)
                    return {'kind': 'checkpoint', 'assignment': dict(assignment), 'outcome': outcome,
                        'checkpoint_head': observed['head'], 'progress_ref': source['resource'],
                        'step_retired': True, 'ticket_released': True}
        finally:
            runner._checkpoint_ceiling.reset(ceiling)
            runner._policy_scope.reset(policy)

    def _complete_checkpoint_phase(self, repo, number, config, record, path, assignment, outcome):
        runner = self.runner
        phase = record['native_phase']
        decision = outcome == 'needs_decision' or (outcome == 'stopped' and
            (record.get('native_outcome') == 'needs_decision' or record.get('wait_reason') == 'product_decision'))
        # The existing progress record is the recovery anchor. No result prose is
        # persisted, and an unfinished write remains visibly checkpoint_only.
        record = runner._record(repo, number, record, native_outcome=outcome, phase='checkpoint',
            pending_action=None, next_action='checkpoint_only',
            resume_phase=record.get('native_resume_phase') or phase,
            wait_reason='product_decision' if decision else None)
        head = runner._workspace_effect(repo, 'checkpoint', path, f'Checkpoint native Issue {number}')
        from .workspace import WorkspaceWait
        design_scope_unknown = False
        try:
            scoped = {**config, '_scoped_spec': runner._scoped_spec(repo, number, config, record)}
            if phase == 'design':
                base = assignment['head'] if record.get('native_correction') and record.get('spec_revision') else config['revision']
                problem = runner._design_problem(path, base, scoped['_scoped_spec'], require_tracked=True)
                if problem:
                    if decision and problem[0] == 'implementation_before_design_acceptance':
                        design_scope_unknown = True
                    elif outcome == 'candidate_ready':
                        record = runner._record(repo, number, record, head=head)
                        runner._wait(repo, number, record, problem[0], phase='checkpoint',
                                     next_action='diagnose' if problem[0] == 'implementation_before_design_acceptance' else problem[1])
                        return dict(runner._checkpoint_ceiling.get()[3]['record'])
            record, revised, wait = runner._spec_checkpoint(repo, number, scoped, record, path, head,
                previous=record, preserve_decision=decision)
        except WorkspaceWait as exc:
            if outcome != 'stopped' or str(exc) != 'intake_changed':
                raise
            record = {**record, 'correction_reason': 'spec_scope_unknown', 'correction_attempt': 3}
            revised, wait = True, {'reason': 'replan_required'}
        if not revised or outcome == 'stopped':
            record = runner._record(repo, number, record, head=head)
        if design_scope_unknown:
            # The spec checkpoint may record accepted_spec_changed. Preserve
            # the stronger diagnosis debt after that bounded observation/write.
            record = {**record, 'correction_reason': 'spec_scope_unknown', 'correction_attempt': 3}
        if outcome == 'stopped':
            remote = runner.github.ref(repo, record['branch'])
            return runner._record(repo, number, record, phase='checkpoint', checkpoint='interrupted_committed',
                pending_action=None, wait_reason='product_decision' if decision else wait['reason'] if wait else
                'remote_head_changed' if remote != record.get('expected_head') else 'stop_requested',
                next_action='operator_decision' if decision else 'diagnose' if wait else 'reconcile')
        if decision:
            return runner._record(repo, number, record, phase=record['phase'] if revised else phase + '_done',
                pending_action=None, wait_reason='product_decision', next_action='operator_decision',
                resume_phase=record.get('native_resume_phase') or phase)
        paths = runner.workspace.changed_paths(path, config['revision'])
        if any(not matches(name, config['allowed_paths']) for name in paths):
            runner._wait(repo, number, record, 'scope_violation', phase='checkpoint', next_action='diagnose')
        elif revised:
            pass  # Accepted-spec changes retain their own review/diagnosis state.
        elif record.get('native_correction'):
            spec_only = phase == 'design'
            integrating = record['native_correction'] == 'integration_changed'
            runner._finish_correction(repo, number, scoped, record, path, {'outcome': 'candidate_ready'},
                reason=record['native_correction'], attempts=record['correction_attempt'],
                prior_head=assignment['head'], spec_base=assignment['head'] if spec_only and record.get('spec_revision')
                else config['revision'], spec_only=spec_only, integrating=integrating,
                completed_phase=record['native_origin_phase'] if integrating else 'design_done' if spec_only
                else 'implementation_done', resume_phase=record.get('native_resume_phase'),
                spec_record=record, remote_before=record.get('expected_head'))
        elif phase == 'design':
            current_issue = runner.github.issue(repo, number)
            if intake_digest(current_issue) != record['intake_digest']:
                raise OperationDenied('intake_changed')
            runner._finish_design(repo, number, scoped, record, path,
                parse_intake(current_issue, config), {'outcome': 'candidate_ready'})
        else:
            runner._complete_implementation(repo, number, record, head)
        return dict(runner._checkpoint_ceiling.get()[3]['record'])

    async def _begin(self, url):
        repo, n = self._issue(url)
        with coordinator_lock(self.lock_path):
            if residual_workers():
                return {"action": "waiting", "reason": "confirm_previous_stopped"}
            record = self.runner.github.progress(repo, n)
            held = self._prepare_begin(repo, n, record)
            if held is not None:
                return held
            return await self.runner.step(repo, n)

    def _prepare_begin(self, repo, number, record):
        """Reconcile a confirmed stop inside the caller's existing host lock."""
        if residual_workers():
            return {"action": "waiting", "reason": "confirm_previous_stopped"}
        if not record or not record.get("native_step"):
            return None
        if record.get("native_outcome") != "stopped":
            return {"action": "waiting", "reason": "confirm_previous_stopped"}
        config = self.runner._work_config(repo, number, record)
        target = config["repository"]
        if self.runner._policy_changed(target, config, record):
            return {"repository": target, "issue": number, "action": "waiting", "reason": "policy_changed"}
        self.runner._bind_policy(target, config)
        self.runner.consumed.add(record["native_step"])
        self.runner._record(repo, number, record)
        return None

    def _bound(self, repo, n, attempt_id, head, contract_revision, step_id=None, *, stopping=False):
        record = self.runner.github.progress(repo, n)
        if stopping and (not record or not record.get("native_step")):
            # The scoped ticket admits this exact stop. There was no confirmed
            # dispatch (or retirement response was lost); do not invent work or
            # adopt a workspace from caller inputs.
            return None, None
        if (not record or record.get("execution_mode") != "native" or record.get("host_alias") != self.runner.host
                or record.get("attempt_id") != attempt_id or record.get("contract_revision") != contract_revision
                or (step_id and record.get("native_step") != step_id)
                or (record.get("native_head") if step_id else record.get("head")) != head):
            raise ValueError("Stale native continuation")
        config = (load_project(self.runner.github, repo, revision=contract_revision) if stopping
                  else self.runner._work_config(repo, n, record))
        if not stopping and (not config or (step_id and config.get("_completion_only"))
                or config["blob_sha"] != load_project(self.runner.github, repo, revision=contract_revision)["blob_sha"]
                or intake_digest(self.runner.github.issue(repo, n)) != record.get("intake_digest")):
            raise ValueError("Delegated policy or intake changed")
        config = {**config, '_work_number': n}
        self.runner._bind_policy(repo, config)
        return record, config

    def _continuation(self, repo, n, prior, result):
        if result.get("action") == "native_task":
            return result
        current = self.runner.github.progress(repo, n)
        if (not current or current.get("execution_mode") != "native" or current.get("host_alias") != self.runner.host
                or any(current.get(k) != prior.get(k) for k in ("attempt_id", "contract_revision"))):
            raise RuntimeError("Native continuation identity is unconfirmed")
        return {**result, "repository": repo, "issue": n, "attempt_id": current["attempt_id"],
                "head": current["head"], "contract_revision": current["contract_revision"]}

    async def _checkpoint(self, url, attempt_id, step_id, head, contract_revision, outcome, summary=""):
        repo, n = self._issue(url)
        if outcome not in {"candidate_ready", "failed", "needs_decision", "stopped"} or len(summary) > 24000:
            raise ValueError("Invalid native candidate result")
        with coordinator_lock(self.lock_path, native_step=step_id,
                native_scope=assignment_scope(repo, n, attempt_id, head, contract_revision)):
            record, config = self._bound(repo, n, attempt_id, head, contract_revision, step_id,
                                         stopping=outcome == "stopped")
            if record is None:
                with self.runner._guard(repo, cleanup=True):
                    confirm_native_assignment(step_id)
                return {"action": "waiting", "reason": "stop_requested"}
            repo = config["repository"]
            if (outcome != 'stopped' and (record.get('native_completion') is not None
                    or step_id in self.runner.review_runs)):
                return {'action': 'waiting', 'reason': 'verify_only_completion_required'}
            if outcome != "stopped" and record.get("native_outcome") not in {None, outcome}:
                return {"action": "waiting", "reason": "native_result_already_recorded"}
            # A stopped checkpoint is explicit operator reconciliation, never inferred
            # from a timeout or an Issue's closed/paused state.
            reason = self.runner._latest(repo, n, {**config, "intake_digest": record["intake_digest"]})
            if reason and outcome != "stopped":
                return {"action": "waiting", "reason": reason}
            observed_remote = (self.runner.github.ref(repo, record["branch"]) if outcome == "stopped"
                               else record.get("expected_head"))
            if outcome == "stopped" and self.runner.operations is not None:
                # Do not invoke a lifecycle provider or allocate on the cleanup path.
                path = self.runner.workspace.existing(repo, n, record["branch"])
            elif outcome == "stopped":
                # Preserve the existing legacy workspace recovery only after
                # the exact stopped ticket and pinned record have been bound.
                path = self.runner._effect(repo, self.runner.workspace.prepare, repo, n, record["branch"],
                                           observed_remote, recover_dirty=True, cleanup=True)
            else:
                path = self.runner._workspace_effect(repo, "prepare", repo, n, record["branch"],
                                                     observed_remote, recover_dirty=True)
            state = self.runner.workspace.inspect(path)
            phase = record["native_phase"]
            checkpointed = (record.get("native_outcome") == outcome and record.get("phase") == "checkpoint"
                            and record.get("checkpoint") == "interrupted_committed" and record.get("head") == state["head"])
            if outcome != "stopped" and ((state["head"] != head and not checkpointed) or ("review" in phase and state["dirty"])):
                return {"action": "waiting", "reason": "head_changed_during_native_task"}
            if outcome == "stopped":
                needs_decision = (record.get("native_outcome") == "needs_decision"
                                  or record.get("wait_reason") == "product_decision")
                with self.runner._confirmed_cleanup(repo, n, record):
                    current_head = self.runner._workspace_effect(repo, "checkpoint", path, f"Checkpoint stopped Issue {n}")
                    from .workspace import WorkspaceWait
                    try:
                        record, _, spec_wait = self.runner._spec_checkpoint(repo, n, config, record, path,
                            current_head, previous=record, preserve_decision=needs_decision)
                    except WorkspaceWait as exc:
                        if str(exc) != "intake_changed":
                            raise
                        # Shutdown does not adopt an edited goal. Preserve the accepted
                        # anchor and edits, require diagnosis, and release only the
                        # explicitly stopped assignment after confirmed public recording.
                        record = {**record, "correction_reason": "spec_scope_unknown", "correction_attempt": 3}
                        spec_wait = {"reason": "replan_required"}
                    self.runner._record(repo, n, record,
                        head=current_head, resume_phase=record.get("resume_phase") or phase,
                        pending_action=None, phase="checkpoint", checkpoint="interrupted_committed",
                        wait_reason="product_decision" if needs_decision else spec_wait["reason"] if spec_wait else
                            "remote_head_changed" if observed_remote != record.get("expected_head") else "stop_requested",
                        next_action="operator_decision" if needs_decision else "diagnose" if spec_wait else "reconcile",
                        native_outcome="stopped")
                    fresh = self.runner.github.progress(repo, n)
                    if fresh.get("native_outcome") != "stopped" or fresh.get("head") != current_head:
                        raise RuntimeError("Stopped checkpoint is unconfirmed")
                    self.runner._effect(repo, confirm_native_assignment, step_id, cleanup=True)
                    self.runner.consumed.add(step_id)
                    self.runner._record(repo, n, fresh)
                    self.runner.summaries.pop(step_id, None)
                    self.runner.review_runs.pop(step_id, None)
                    key = self.runner.review_steps.pop(step_id, None)
                    if key is not None:
                        self.runner.pending_verifications.pop(key, None)
                        self.runner._forget_verification_run(key)
                    return self._continuation(repo, n, record, {"action": "waiting", "reason": fresh["wait_reason"]})
            # Persist only the bounded outcome; raw summaries remain private and
            # cannot authorize delivery. Interrupted read-back keeps ownership.
            decision = outcome == "needs_decision"
            self.runner._record(repo, n, record, native_outcome=outcome,
                **({"wait_reason": "product_decision", "next_action": "operator_decision"}
                   if decision and phase in {"design", "implementation", "correction"} else {}))
            fresh = self.runner.github.progress(repo, n)
            if fresh.get("native_outcome") != outcome or fresh.get("native_step") != step_id:
                raise RuntimeError("Candidate result write is unconfirmed")
            if "review" in phase:
                self.runner.summaries[step_id] = summary
            digest = record.get("native_spec_digest")
            if phase in {"implementation", "correction", "change_review"} and record.get("spec_revision") and digest:
                actual = hashlib.sha256(self.runner.workspace.read_spec(path, config["_scoped_spec"]
                    if "_scoped_spec" in config else self.runner._scoped_spec(repo, n, config, record))).hexdigest()
                if actual == digest:
                    self.runner.accepted_specs[(repo, n, digest)] = True
            if phase in {"design", "implementation", "correction"}:
                # Complete the originating callback before selecting a new phase.
                # This reuses exactly the same scope/spec/correction completion as CLI.
                from .project import parse_intake
                # Commit edits and persist a restartable originating phase before
                # retiring admission. Callback failure must never strand dirty
                # edits without an ownership/recovery identity.
                scoped = {**config, "_scoped_spec": self.runner._scoped_spec(repo, n, config, record)}
                current_head = self.runner._workspace_effect(repo, "checkpoint", path, f"Checkpoint native Issue {n}")
                fresh, _, spec_wait = self.runner._spec_checkpoint(repo, n, scoped, fresh, path,
                    current_head, previous=fresh, preserve_decision=decision)
                recovery = self.runner._record(repo, n, fresh, head=current_head, phase="checkpoint",
                    checkpoint="interrupted_committed", pending_action=None,
                    resume_phase=record.get("native_resume_phase") or phase,
                    wait_reason="product_decision" if decision else spec_wait["reason"] if spec_wait else fresh.get("wait_reason"),
                    next_action="operator_decision" if decision else "diagnose" if spec_wait else "reconcile")
                observed = self.runner.github.progress(repo, n)
                if any(observed.get(k) != v for k, v in recovery.items()):
                    raise RuntimeError("Native recovery checkpoint is unconfirmed")
                fresh = recovery
                clean = self.runner._retire_assignment(repo, n, fresh)
                if spec_wait:
                    return self._continuation(repo, n, record, spec_wait)
                if outcome == "needs_decision":
                    clean = {**clean, "resume_phase": phase}
                candidate, wait = self.runner._candidate_result(repo, n, scoped, clean, path, phase,
                    {"detail": {"result": {"outcome": outcome, "summary": summary}}})
                if wait:
                    return self._continuation(repo, n, record, wait)
                self.runner._record(repo, n, clean, pending_action=None, wait_reason=None)
                if record.get("native_correction"):
                    spec_only = phase == "design"
                    integrating = record["native_correction"] == "integration_changed"
                    result = self.runner._finish_correction(repo, n, scoped, clean, path, candidate,
                        reason=record["native_correction"], attempts=record["correction_attempt"],
                        prior_head=head, spec_base=head if spec_only and record.get("spec_revision") else config["revision"],
                        spec_only=spec_only, integrating=integrating,
                        completed_phase=record["native_origin_phase"] if integrating else "design_done" if spec_only else "implementation_done",
                        resume_phase=record.get("native_resume_phase"), spec_record=clean,
                        remote_before=record.get("expected_head"))
                elif phase == "design":
                    intake = parse_intake(self.runner.github.issue(repo, n), config)
                    result = self.runner._finish_design(repo, n, scoped, clean, path, intake, candidate)
                else:
                    result = await self.runner._finish_implementation(repo, n, scoped, clean, path, candidate)
                return self._continuation(repo, n, record, result)
            return await self.runner.step(repo, n)

    async def _advance(self, url, attempt_id, head, contract_revision):
        repo, n = self._issue(url)
        with coordinator_lock(self.lock_path):
            if residual_workers():
                return {"action": "waiting", "reason": "confirm_previous_stopped"}
            record, _ = self._bound(repo, n, attempt_id, head, contract_revision)
            if record.get("native_step") and not record.get("native_outcome"):
                return {"action": "waiting", "reason": "confirm_previous_stopped"}
            return await self.runner.step(repo, n)
