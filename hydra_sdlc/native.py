"""Native task continuations; GitHub progress and the host ticket survive calls.

No model is invoked here. Candidate results are judgments, never delivery evidence.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path

from .coordinator import (confirm_native_assignment, coordinator_lock,
                          native_assignment_matches, register_native_assignment, residual_workers)
from .runner import Runner, intake_digest, issue_url
from .project import load_project

NATIVE_FIELDS = {"native_step", "native_phase", "native_head", "native_outcome", "native_spec_digest",
                 "native_origin_phase", "native_resume_phase", "native_correction"}


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

    def _verify_candidate(self, path, config, evidence_key):
        if evidence_key in self.pending_verifications:
            return self.pending_verifications[evidence_key]
        verification = super()._verify_candidate(path, config, evidence_key)
        state = self.workspace.inspect(path)
        if verification and all(v["passed"] for v in verification) and not state["dirty"] and state["head"] == evidence_key[2]:
            self.pending_verifications[evidence_key] = verification
        return verification

    def _record(self, repo, number, record, **values):
        if record.get("native_step") in self.consumed:
            record = {k: v for k, v in record.items() if k not in NATIVE_FIELDS}
        return super()._record(repo, number, record, **values)

    async def step(self, repo, number):
        record = self.github.progress(repo, number)
        if (record and record.get("execution_mode") == "native" and record.get("host_alias") == self.host
                and record.get("phase") == "checkpoint" and record.get("checkpoint") == "interrupted_committed"
                and self.github.ref(repo, record["branch"]) != record.get("expected_head")):
            # Local shutdown grants no authority to adopt a changed/deleted ref.
            return {"repository": repo, "issue": number, "action": "waiting", "reason": "remote_head_changed"}
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
        if step and phase == "change_review" and record.get("native_outcome") and self.review_steps.get(step) != evidence_key:
            # A restarted service has lost the run examined by this reviewer.
            # Retire its finished judgment and dispatch a new review of the fresh run.
            self.consumed.add(step)
            clean = {k: v for k, v in record.items() if k not in NATIVE_FIELDS}
            self._record(repo, number, clean, pending_action=None, wait_reason=None)
            observed = self.github.progress(repo, number)
            if observed.get("native_step") or observed.get("head") != record["head"]:
                raise RuntimeError("Stale verification review retirement is unconfirmed")
            confirm_native_assignment(step)
            self.summaries.pop(step, None)
            self.review_steps.pop(step, None)
            record, step = clean, None
        if step and step not in self.consumed:
            if record.get("native_phase") != phase:
                return None, {"action": "waiting", "reason": "native_phase_changed"}
            if not record.get("native_outcome"):
                return None, {"action": "waiting", "reason": "native_task_active", "step_id": step}
            outcome = record["native_outcome"]
            self.consumed.add(step)
            clean = {k: v for k, v in record.items() if k not in NATIVE_FIELDS}
            self._record(repo, number, clean, pending_action=None, wait_reason=None)
            result = self._candidate_result(repo, number, config, clean, path, phase,
                {"detail": {"result": {"outcome": outcome, "summary": self.summaries.pop(step, "")}}},
                correction=correction, spec_record=spec_record)
            observed = self.github.progress(repo, number)
            if (observed.get("native_step") or observed.get("attempt_id") != record["attempt_id"]
                    or observed.get("head") != record["head"]):
                raise RuntimeError("Native review retirement is unconfirmed")
            confirm_native_assignment(step)
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
        step = str(uuid.uuid4())
        recovery = {"repository": repo, "issue": number, "attempt_id": record["attempt_id"],
                    "step_id": step, "head": state["head"], "contract_revision": record["contract_revision"]}
        scope = assignment_scope(repo, number, record["attempt_id"], state["head"], record["contract_revision"])
        try:
            register_native_assignment(step, scope)
        except (RuntimeError, ValueError, OSError):
            try:
                held = native_assignment_matches(step, scope)
            except (RuntimeError, ValueError, OSError):
                held = False
            return None, {**recovery, "action": "waiting",
                          "reason": "assignment_ticket_unconfirmed" if held else "assignment_ticket_unknown"}
        try:
            record = self._intent(repo, number, config, record, None,
            execution_mode="native", native_step=step, native_phase=phase,
            native_head=state["head"], native_spec_digest=digest, native_outcome=None,
            native_origin_phase=record["phase"], native_resume_phase=origin_resume,
            native_correction=correction[0] if correction else None,
            wait_reason="native_task_active", next_action=phase, expected_head=remote,
            **({"resume_phase": record.get("resume_phase") or phase}
               if phase in {"implementation", "correction"} else {}),
            **({"correction_reason": correction[0], "correction_attempt": correction[1]} if correction else {}))
        except (RuntimeError, ValueError, OSError):
            return None, {**recovery, "action": "waiting", "reason": "assignment_record_unknown"}
        if record is None:
            return None, {**recovery, "action": "waiting", "reason": "assignment_record_unconfirmed"}
        if phase == "change_review":
            self.review_steps[step] = evidence_key
        return None, {"repository": repo, "issue": number, "action": "native_task",
            "attempt_id": record["attempt_id"], "step_id": step, "phase": phase,
            "head": state["head"], "contract_revision": record["contract_revision"],
            "spec_revision": record.get("spec_revision"), "cwd": str(path),
            "mode": "read_only" if "review" in phase else "workspace_write", "prompt": task}


class NativeController:
    def __init__(self, github, workspace, *, repos, host_alias, lock_path, knowledge_revision=lambda: None):
        if not repos or any(not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", r) for r in repos):
            raise ValueError("A host repository allowlist is required")
        self.repos = tuple({r.casefold(): r for r in repos}.values())
        self.lock_path = Path(lock_path)
        self.runner = NativeRunner(github, workspace, host_alias=host_alias, knowledge_revision=knowledge_revision)

    def _issue(self, url):
        repo, n = issue_url(url)
        if repo.casefold() not in {r.casefold() for r in self.repos}:
            raise ValueError("Issue is outside the installed repository allowlist")
        return repo, n

    def status(self):
        return self.runner.status(self.repos)

    async def begin(self, url):
        repo, n = self._issue(url)
        with coordinator_lock(self.lock_path):
            if residual_workers():
                return {"action": "waiting", "reason": "confirm_previous_stopped"}
            record = self.runner.github.progress(repo, n)
            if record and record.get("native_step"):
                if record.get("native_outcome") == "stopped":
                    self.runner.consumed.add(record["native_step"])
                    self.runner._record(repo, n, record)
                else:
                    return {"action": "waiting", "reason": "confirm_previous_stopped"}
            return await self.runner.step(repo, n)

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
        if not stopping and (not config or config["blob_sha"] != load_project(self.runner.github, repo, revision=contract_revision)["blob_sha"]
                or intake_digest(self.runner.github.issue(repo, n)) != record.get("intake_digest")):
            raise ValueError("Delegated policy or intake changed")
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

    async def checkpoint(self, url, attempt_id, step_id, head, contract_revision, outcome, summary=""):
        repo, n = self._issue(url)
        if outcome not in {"candidate_ready", "failed", "needs_decision", "stopped"} or len(summary) > 24000:
            raise ValueError("Invalid native candidate result")
        with coordinator_lock(self.lock_path, native_step=step_id,
                native_scope=assignment_scope(repo, n, attempt_id, head, contract_revision)):
            record, config = self._bound(repo, n, attempt_id, head, contract_revision, step_id,
                                         stopping=outcome == "stopped")
            if record is None:
                confirm_native_assignment(step_id)
                return {"action": "waiting", "reason": "stop_requested"}
            repo = config["repository"]
            if outcome != "stopped" and record.get("native_outcome") not in {None, outcome}:
                return {"action": "waiting", "reason": "native_result_already_recorded"}
            # A stopped checkpoint is explicit operator reconciliation, never inferred
            # from a timeout or an Issue's closed/paused state.
            reason = self.runner._latest(repo, n, {**config, "intake_digest": record["intake_digest"]})
            if reason and outcome != "stopped":
                return {"action": "waiting", "reason": reason}
            observed_remote = (self.runner.github.ref(repo, record["branch"]) if outcome == "stopped"
                               else record.get("expected_head"))
            path = self.runner.workspace.prepare(repo, n, record["branch"], observed_remote, recover_dirty=True)
            state = self.runner.workspace.inspect(path)
            phase = record["native_phase"]
            checkpointed = (record.get("native_outcome") == outcome and record.get("phase") == "checkpoint"
                            and record.get("checkpoint") == "interrupted_committed" and record.get("head") == state["head"])
            if outcome != "stopped" and ((state["head"] != head and not checkpointed) or ("review" in phase and state["dirty"])):
                return {"action": "waiting", "reason": "head_changed_during_native_task"}
            if outcome == "stopped":
                current_head = self.runner.workspace.checkpoint(path, f"Checkpoint stopped Issue {n}")
                from .workspace import WorkspaceWait
                try:
                    record, _, spec_wait = self.runner._spec_checkpoint(repo, n, config, record, path,
                        current_head, previous=record)
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
                    wait_reason=spec_wait["reason"] if spec_wait else
                        "remote_head_changed" if observed_remote != record.get("expected_head") else "stop_requested",
                    next_action="diagnose" if spec_wait else "reconcile", native_outcome="stopped")
                fresh = self.runner.github.progress(repo, n)
                if fresh.get("native_outcome") != "stopped" or fresh.get("head") != current_head:
                    raise RuntimeError("Stopped checkpoint is unconfirmed")
                confirm_native_assignment(step_id)
                self.runner.consumed.add(step_id)
                self.runner._record(repo, n, fresh)
                self.runner.summaries.pop(step_id, None)
                key = self.runner.review_steps.pop(step_id, None)
                if key is not None:
                    self.runner.pending_verifications.pop(key, None)
                return self._continuation(repo, n, record, {"action": "waiting", "reason": fresh["wait_reason"]})
            # Persist only the bounded outcome; raw summaries remain private and
            # cannot authorize delivery. Interrupted read-back keeps ownership.
            self.runner._record(repo, n, record, native_outcome=outcome)
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
                current_head = self.runner.workspace.checkpoint(path, f"Checkpoint native Issue {n}")
                fresh, _, spec_wait = self.runner._spec_checkpoint(repo, n, scoped, fresh, path,
                    current_head, previous=fresh)
                recovery = self.runner._record(repo, n, fresh, head=current_head, phase="checkpoint",
                    checkpoint="interrupted_committed", pending_action=None,
                    resume_phase=record.get("native_resume_phase") or phase, next_action="reconcile")
                observed = self.runner.github.progress(repo, n)
                if any(observed.get(k) != v for k, v in recovery.items()):
                    raise RuntimeError("Native recovery checkpoint is unconfirmed")
                self.runner.consumed.add(step_id)
                fresh = recovery
                clean = {k: v for k, v in fresh.items() if k not in NATIVE_FIELDS}
                self.runner._record(repo, n, clean)
                observed = self.runner.github.progress(repo, n)
                if observed.get("native_step") or any(observed.get(k) != v for k, v in clean.items()):
                    raise RuntimeError("Native retirement is unconfirmed")
                confirm_native_assignment(step_id)
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

    async def advance(self, url, attempt_id, head, contract_revision):
        repo, n = self._issue(url)
        with coordinator_lock(self.lock_path):
            if residual_workers():
                return {"action": "waiting", "reason": "confirm_previous_stopped"}
            record, _ = self._bound(repo, n, attempt_id, head, contract_revision)
            if record.get("native_step") and not record.get("native_outcome"):
                return {"action": "waiting", "reason": "confirm_previous_stopped"}
            return await self.runner.step(repo, n)
