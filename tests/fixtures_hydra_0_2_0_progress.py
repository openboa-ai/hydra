"""Immutable progress-reader fixture extracted from Hydra 0.2.0 commit 0e6bdb9."""

import json
import re
import uuid


class GitHubError(RuntimeError):
    pass


def _number(value):
    if type(value) is not int or value < 1:
        raise GitHubError("Invalid issue or PR number")
    return value


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise GitHubError("Missing or invalid commit SHA")
    return value


def _marker(body, name):
    prefix = f"<!-- {name}:v1 "
    if prefix not in (body or ""):
        return None
    matches = re.findall(re.escape(prefix) + r"(.*?) -->", body, re.S)
    if len(matches) != 1 or body.count(prefix) != 1:
        raise GitHubError("Ambiguous service marker")

    def unique_keys(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError()
            value[key] = item
        return value

    try:
        value = json.loads(matches[0], object_pairs_hook=unique_keys)
    except (ValueError, TypeError) as exc:
        raise GitHubError("Malformed service marker") from exc
    if not isinstance(value, dict):
        raise GitHubError("Malformed service marker")
    return value


def _validate_record(record, *, metadata=False):
    allowed = {"attempt_id", "host_alias", "contract_revision", "spec_revision", "phase",
               "branch", "head", "published_head", "pr_number", "pending_action",
               "pending_thread", "checkpoint", "wait_reason", "next_action", "expected_head",
               "expected_base", "action_attempt", "review_requested_head", "delivery_action",
               "delivery_attempt", "delivery_head", "review_requested_security_head",
               "pending_review_kind", "intake_digest", "correction_reason", "correction_attempt",
               "resume_phase"}
    if metadata:
        allowed |= {"repository_id", "issue_number", "version"}
    allowed |= {"execution_mode", "native_step", "native_phase", "native_head", "native_outcome",
                "native_spec_digest", "native_origin_phase", "native_resume_phase",
                "native_correction"}
    if not isinstance(record, dict) or set(record) - allowed:
        raise GitHubError("Unknown progress fields")
    for key, value in record.items():
        if value is None:
            continue
        if key in {"intake_digest", "native_spec_digest"}:
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                raise GitHubError("Invalid delegated intake digest")
        elif key in {"contract_revision", "spec_revision", "head", "published_head",
                     "expected_head", "expected_base", "review_requested_head", "delivery_head",
                     "review_requested_security_head", "native_head"}:
            _sha(value)
        elif key in {"attempt_id", "native_step"}:
            try:
                if str(uuid.UUID(value)) != value:
                    raise ValueError()
            except (ValueError, AttributeError, TypeError) as exc:
                raise GitHubError("Invalid attempt UUID") from exc
        elif key == "pending_thread":
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
                raise GitHubError("Invalid pending review thread ID")
        elif key == "pending_review_kind" and value not in {"code", "security"}:
            raise GitHubError("Invalid pending review kind")
        elif key == "execution_mode" and value != "native":
            raise GitHubError("Invalid execution mode")
        elif key == "native_phase" and value not in {
                "design", "spec_review", "implementation", "correction", "change_review"}:
            raise GitHubError("Invalid native phase")
        elif key == "native_outcome" and value not in {
                "candidate_ready", "failed", "needs_decision", "stopped"}:
            raise GitHubError("Invalid native outcome")
        elif key in {"action_attempt", "delivery_attempt", "correction_attempt"}:
            if type(value) is not int or not 1 <= value <= 3:
                raise GitHubError("Service action retry bound exceeded")
        elif key in {"pr_number", "repository_id", "issue_number", "version"}:
            _number(value)
        elif key == "branch":
            if not re.fullmatch(r"hydra/issue-[1-9][0-9]*", value):
                raise GitHubError("Invalid owned branch")
        elif not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,119}", value):
            raise GitHubError("Progress requires public codes, not raw text")


def read_progress(body, repository_id, issue_number):
    value = _marker(body, "hydra-progress")
    if (value.get("repository_id") != repository_id
            or value.get("issue_number") != issue_number or value.get("version") != 1):
        raise GitHubError("Progress identity mismatch")
    _validate_record(value, metadata=True)
    return value
