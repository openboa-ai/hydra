"""Read-only operational observations and explicit host admission controls.

Operating permission, workflow progress and observed execution are independent.
This module never loads workspace providers or controls native desktop turns.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tomllib
import uuid
from datetime import datetime, timezone

from .coordinator import observe_coordinator, residual_workers
from .operations import MAX_PROJECTS, MAX_REVISION, OperatingControl, OperationDenied
from .runtime_identity import capture_runtime_identity


_CONFIG_KEYS = {"repos", "host_alias", "workspace_root", "lock_path", "lifecycle_provider",
                "storage_provider", "knowledge_repo", "runtime_python", "project_threads"}
_REPOSITORY = re.compile(r"[a-z0-9][a-z0-9-]{0,38}/[a-z0-9_.-]{1,100}\Z")
_CODE = re.compile(r"[a-z0-9][a-z0-9_-]{0,119}\Z")
_PROVIDER = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*\Z", re.ASCII)
_MAX_CONFIG_BYTES = 65536
_MAX_WORK_PER_PROJECT = 128
_MAX_TOTAL_WORK = 512


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _repository(value):
    if (not isinstance(value, str) or not _REPOSITORY.fullmatch(value.lower())
            or value.split("/")[-1] in {".", ".."}):
        raise ValueError("Invalid installed repository identity")
    return value.lower()


def _path(value, base):
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise ValueError("Invalid installed host path")
    expanded = Path(value).expanduser()
    if not expanded.is_absolute():
        expanded = base / expanded
    if ".." in expanded.parts:
        raise ValueError("Invalid installed host path")
    return str(expanded.absolute())


def load_host_config(path):
    """Load bounded installed TOML without importing provider factories.

    Relative configured paths are anchored to the installed configuration's
    directory, never to a repository or the app's current working directory.
    """
    fd = None
    try:
        path = Path(path).expanduser().absolute()
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                or before.st_nlink != 1 or before.st_mode & 0o022 or before.st_size > _MAX_CONFIG_BYTES):
            raise ValueError("Invalid installed host settings")
        raw = bytearray()
        while len(raw) <= _MAX_CONFIG_BYTES:
            part = os.read(fd, min(8192, _MAX_CONFIG_BYTES + 1 - len(raw)))
            if not part:
                break
            raw.extend(part)
        after = os.fstat(fd)
        visible = path.lstat()
        fingerprint = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        if (len(raw) > _MAX_CONFIG_BYTES or fingerprint(before) != fingerprint(after)
                or fingerprint(after) != fingerprint(visible)):
            raise ValueError("Invalid installed host settings")
        cfg = tomllib.loads(raw.decode("utf-8"))
        if (set(cfg) - _CONFIG_KEYS or not isinstance(cfg.get("host_alias"), str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", cfg["host_alias"])):
            raise ValueError("Invalid installed host settings")
        repos = cfg.get("repos")
        if not isinstance(repos, list) or not 1 <= len(repos) <= MAX_PROJECTS:
            raise ValueError("Invalid installed repository allowlist")
        canonical = [_repository(repo) for repo in repos]
        if len(set(canonical)) != len(canonical):
            raise ValueError("Duplicate installed repository identity")
        cfg["repos"] = canonical
        cfg["workspace_root"] = _path(cfg.get("workspace_root"), path.parent)
        cfg["lock_path"] = _path(cfg.get("lock_path", "~/.local/share/hydra/host.lock"), path.parent)
        if "runtime_python" in cfg:
            cfg["runtime_python"] = _path(cfg["runtime_python"], path.parent)
        if "knowledge_repo" in cfg:
            cfg["knowledge_repo"] = _repository(cfg["knowledge_repo"])
        for key in ("lifecycle_provider", "storage_provider"):
            if key in cfg and (not isinstance(cfg[key], str) or not _PROVIDER.fullmatch(cfg[key])):
                raise ValueError("Invalid installed provider reference")
        threads = cfg.get("project_threads", {})
        if not isinstance(threads, dict) or len(threads) > len(canonical):
            raise ValueError("Invalid installed project threads")
        for repository, thread in threads.items():
            if (_repository(repository) != repository or repository not in canonical
                    or not isinstance(thread, str) or str(uuid.UUID(thread)) != thread):
                raise ValueError("Invalid installed project threads")
        cfg["project_threads"] = threads
        return cfg
    except (OSError, ValueError, TypeError, RuntimeError, UnicodeError) as exc:
        raise ValueError("Invalid installed host settings") from exc
    finally:
        if fd is not None:
            os.close(fd)


def control_from_config(cfg):
    return OperatingControl(cfg["lock_path"], cfg["repos"])


def _public_code(value):
    return value if isinstance(value, str) and _CODE.fullmatch(value) else None


def _native_binding(repo, number, record, ownership, host):
    if (ownership.get("state") != "native" or record.get("host_alias") != host
            or record.get("execution_mode") != "native" or not record.get("native_step")
            or record.get("native_step") != ownership.get("nonce")):
        return False
    values = [repo, number, record.get("attempt_id"), record.get("head"), record.get("contract_revision")]
    if any(value is None for value in values):
        return False
    scope = hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()
    return scope == ownership.get("scope_digest")


def _remote_observations(cfg, ownership):
    # Import only for an explicit remote refresh. GitHub.progress authenticates
    # the service author and validates repository/Issue metadata and fields.
    from .github import GitHub
    github = GitHub(user="openboa")
    observations = {}
    retained = 0
    for repo in cfg["repos"]:
        row = {"work": [], "complete": False,
               "bound_native": False, "unresolved": False}
        observations[repo] = row
        try:
            issues = github.issues(repo)
            if not isinstance(issues, list) or len(issues) > _MAX_WORK_PER_PROJECT:
                continue
            seen = set()
            for issue in issues:
                number = issue.get("number") if isinstance(issue, dict) else None
                if type(number) is not int or not 1 <= number <= MAX_REVISION or number in seen or "pull_request" in issue:
                    raise ValueError("Incomplete Issue observation")
                seen.add(number)
                record = github.progress(repo, number)
                if record is None:
                    continue
                if retained >= _MAX_TOTAL_WORK:
                    raise ValueError("Work observation bound reached")
                pr = record.get("pr_number")
                work = {"issue": number, "phase": _public_code(record.get("phase")),
                        "wait_reason": _public_code(record.get("wait_reason")),
                        "next_action": _public_code(record.get("next_action")),
                        "links": {"issue": f"https://github.com/{repo}/issues/{number}",
                                  "pr": f"https://github.com/{repo}/pull/{pr}"
                                  if type(pr) is int and 1 <= pr <= MAX_REVISION else None}}
                row["work"].append(work)
                retained += 1
                bound = _native_binding(repo, number, record, ownership, cfg["host_alias"])
                row["bound_native"] |= bound
                if record.get("host_alias") == cfg["host_alias"]:
                    row["unresolved"] |= bool(bound or (record.get("native_step") and not record.get("native_outcome"))
                                               or record.get("phase") == "executing")
            row["complete"] = True
        except (ValueError, RuntimeError, OSError, KeyError, TypeError):
            # Preserve already observed records, but never call a partial list a
            # complete inventory or expose raw transport/provider diagnostics.
            pass
    return observations


def _coverage_observation():
    # No installed schedule inventory provider is qualified in this revision.
    # This is intentionally not configurable: source tests cannot certify a
    # different installed runtime or external schedule's admission coverage.
    return {"state": "unverified", "reason": "schedule_coverage_unverified"}


def _execution(mode, ownership, workers, unresolved, *, coverage, remote_complete):
    """Classify explicit evidence. Missing evidence is never positive zero.

    The production caller supplies only real observations; tests may exercise
    the positive-zero branch without adding an installed qualification flag.
    """
    state = ownership.get("state")
    if state == "native":
        reason = "native_turn_control_unsupported"
    elif state in {"owned", "busy"}:
        reason = "owned_execution_unresolved"
    elif state not in {"free", "absent"}:
        reason = "ownership_observation_unavailable"
    elif workers is None:
        reason = "worker_observation_unavailable"
    elif workers:
        reason = "residual_workers_unresolved"
    elif unresolved:
        reason = "native_assignment_unresolved"
    elif not remote_complete:
        reason = "remote_observation_incomplete"
    elif coverage.get("state") != "confirmed":
        reason = "schedule_coverage_unverified"
    else:
        return {"state": {"running": "idle", "paused": "paused", "stopped": "stopped"}.get(mode, "unknown"),
                "active_count": 0 if mode in {"running", "paused", "stopped"} else None,
                "reason": None if mode in {"running", "paused", "stopped"} else "operation_state_unavailable"}
    pending = state in {"native", "owned", "busy"} or (state in {"free", "absent"} and (bool(workers) or unresolved))
    status = "pausing" if pending and mode == "paused" else "stopping" if pending and mode == "stopped" else "unknown"
    return {"state": status, "active_count": None, "reason": reason}


def control_result(cfg, action="status", repository=None, refresh=False):
    if not isinstance(action, str) or action not in {"status", "start", "pause", "resume", "stop"} or type(refresh) is not bool:
        raise ValueError("Invalid control request")
    if repository is not None:
        repository = _repository(repository)
    if action == "status" and repository is not None:
        raise ValueError("Status does not accept a mutation target")
    control = control_from_config(cfg)
    request = None
    if action != "status":
        request = {"action": action, "target": repository or "all", "status": "applied", "revision": None, "reason": None}
        try:
            applied = control.set_mode(action, repository)
            request["revision"] = applied["revision"]
        except OperationDenied as exc:
            request.update(status="unknown" if exc.reason in {"operation_state_unavailable", "operation_state_changed"}
                           else "held", reason=exc.reason)
    error = None
    try:
        snapshot = control.snapshot()
    except OperationDenied as exc:
        snapshot = {"revision": None, "global_mode": "unknown", "projects": {}}
        error = exc.reason
    mode = snapshot["global_mode"]
    gate_reason = error or (None if mode == "running" else "host_" + mode)
    ownership = observe_coordinator(cfg["lock_path"])
    try:
        found = residual_workers()
        workers = len(found) if isinstance(found, list) else None
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError):
        workers = None
    coverage = _coverage_observation()
    remote = _remote_observations(cfg, ownership) if action == "status" and refresh else {}
    complete = bool(remote) and all(row["complete"] for row in remote.values())
    unresolved = any(row["unresolved"] for row in remote.values())
    execution = _execution(mode, ownership, workers, unresolved, coverage=coverage, remote_complete=complete)
    if error:
        execution = {"state": "unknown", "active_count": None, "reason": error}
    observed_at = _now()
    result = {"schema_version": 2, "runtime": capture_runtime_identity(cfg, control),
              "observed_at": observed_at, "host_alias": cfg["host_alias"],
              "revision": snapshot["revision"], "global_mode": mode,
              "gate_status": "unknown" if error else "blocked" if gate_reason else "allowed",
              "gate_reason": gate_reason, "native_turn_control": "unsupported", "execution": execution,
              "coverage": coverage, "can_quit": False, "quit_reason": execution["reason"],
              "remote": {"state": "fresh" if complete else "unavailable" if remote else "not_requested",
                         "observed_at": observed_at if remote else None},
              "projects": [], "request": request}
    for repo in cfg["repos"]:
        row = remote.get(repo, {})
        override = snapshot["projects"].get(repo)
        effective = mode if mode != "running" else override or "running"
        reason = error or ("host_" + mode if mode != "running" else None if effective == "running" else "project_" + effective)
        # A host ticket can only be attributed to a repository by authenticated
        # progress plus the existing exact scope digest. Other projects retain
        # unknown ownership instead of inheriting an arbitrary active count.
        scoped_owner = ownership
        if (ownership.get("state") in {"owned", "busy"}
                or (ownership.get("state") == "native" and not row.get("bound_native"))):
            scoped_owner = {"state": "unknown"}
        scoped_workers = None if workers else workers
        project_execution = _execution(effective, scoped_owner, scoped_workers, row.get("unresolved", False),
                                       coverage=coverage, remote_complete=row.get("complete", False))
        if error:
            project_execution = {"state": "unknown", "active_count": None, "reason": error}
        thread = cfg.get("project_threads", {}).get(repo)
        result["projects"].append({"repository": repo, "override_mode": override, "effective_mode": effective,
            "gate_status": "unknown" if error else "blocked" if reason else "allowed", "gate_reason": reason,
            "execution": project_execution, "work": row.get("work", []),
            "links": {"chat": "codex://threads/" + thread if thread else None}})
    if (mode == "stopped" and not error and coverage["state"] == "confirmed"
            and execution["state"] == "stopped" and execution["active_count"] == 0):
        result["can_quit"], result["quit_reason"] = True, None
    elif result["quit_reason"] is None:
        result["quit_reason"] = "global_stop_required"
    return result
