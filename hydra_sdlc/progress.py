"""Derived operator guidance; never workflow authority or persistent state."""

from __future__ import annotations


def progress_hint(result):
    """Classify already-observed public facts without reads, writes or retries.

    Callers supply authenticated workflow results/status. A hint neither proves
    native execution nor grants permission to dispatch or repeat an effect.
    """
    unknown = {"kind": "unknown", "next_action": "reconcile", "wake_source": "none"}
    if not isinstance(result, dict):
        return unknown
    reason = result.get("reason")
    if reason is None:
        reason = result.get("wait_reason")
    if reason is not None and not isinstance(reason, str):
        return unknown
    progress = result.get("progress")
    progress = progress if isinstance(progress, dict) else {}

    def hint(kind, action, source="none"):
        return {"kind": kind, "next_action": action, "wake_source": source}

    if reason in {"host_paused", "host_stopped", "project_paused", "project_stopped"}:
        return hint("human", "await_control_change", "control_change")
    if reason in {"product_decision", "replan_required"} and result.get("resume_hint") == {
            "product_decision": "decision_resolved", "replan_required": "replan_ready"}[reason]:
        return hint("actionable", "begin")
    if reason in {"product_decision", "human_decision"}:
        return hint("human", "await_operator_decision", "operator_decision")
    if reason == "not_delegated":
        return hint("human", "await_delegation", "issue_update")
    if reason == "replan_required":
        return hint("human", "resolve_replan", "operator_decision")
    if reason in {"paused", "intake_changed", "intake_unbound", "scope_changed"}:
        return hint("human", "reconcile_intake", "issue_update")
    if reason in {"native_assignment_pending", "native_task_active", "native_owned", "confirm_previous_stopped"}:
        return hint("unknown", "reconcile_native_assignment", "native_checkpoint")
    if reason == "dependency_open":
        return hint("external", "observe_dependency", "issue_update")
    if reason == "post_merge_checks":
        return hint("external", "observe_post_merge_checks", "ci_update")
    if reason == "post_merge_failed":
        return hint("actionable", "diagnose_post_merge")
    if reason == "post_merge_evidence_unknown":
        return hint("unknown", "reconcile_post_merge_evidence", "ci_update")
    if reason in {"remote_delivery_gates", "delivery_facts_changed"}:
        # This older aggregate can include missing evidence as well as running
        # checks/reviews. It does not prove an external execution is progressing.
        return hint("unknown", "reconcile_delivery", "issue_update")
    if reason == "completion_reconciliation":
        return hint("actionable", "reconcile_completion")
    if reason is not None:
        # A generic stop request can come from a deadline or signal without any
        # change to operating controls. Reconcile its cause before choosing a wake.
        return unknown
    resource_reason = result.get("resource_wait_reason")
    if resource_reason == "resource_completion_unconfirmed":
        return hint("unknown", "reconcile_completion")
    if resource_reason == "resource_cleanup_pending":
        return hint("actionable", "reconcile_completion")
    if resource_reason is not None:
        return unknown
    if progress.get("phase") == "completed" and progress.get("next_action") == "resource_cleanup":
        # Delivery can be complete while the owned resource still needs recovery.
        return hint("actionable", "reconcile_completion")
    if result.get("action") == "completed" or (
            progress.get("phase") == "completed" and not progress.get("pending_action")):
        return hint("complete", "none")
    if result.get("action") == "continue":
        return hint("actionable", "advance")
    if result.get("action") == "native_task":
        # A freshly returned assignment is work for the caller, not evidence
        # that it has started. An unresolved status row stays unknown above.
        return hint("actionable", "perform_native_assignment")
    return unknown


def with_progress_hint(result):
    """Copy one public result and replace any stale derived guidance."""
    return {**result, "progress_hint": progress_hint(result)}
