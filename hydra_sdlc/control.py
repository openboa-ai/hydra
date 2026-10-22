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
from .native_admission import parse_admission_profile


_CONFIG_KEYS = {"repos", "host_alias", "workspace_root", "lock_path", "lifecycle_provider",
                "storage_provider", "knowledge_repo", "runtime_python", "project_threads",
                "native_admission_control"}
_REPOSITORY = re.compile(r"[a-z0-9][a-z0-9-]{0,38}/[a-z0-9_.-]{1,100}\Z")
_CODE = re.compile(r"[a-z0-9][a-z0-9_-]{0,119}\Z")
_PROVIDER = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*\Z", re.ASCII)
_MAX_CONFIG_BYTES = 65536
_MAX_WORK_PER_PROJECT = 128
_MAX_TOTAL_WORK = 512
_REMOTE_READ_SECONDS = 45.0
_REMOTE_READ_REQUESTS = 4096


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


def _config_parent(path):
    """Open the physical parent and retain every named directory's identity."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        root = os.fstat(fd)
        binding = [(root.st_dev, root.st_ino)]
        parts = path.parent.parts[1:]
        for index, part in enumerate(parts):
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            mode = stat.S_IMODE(info.st_mode)
            final = index == len(parts) - 1
            sticky_root = info.st_uid == 0 and bool(mode & stat.S_ISVTX) and not final
            if (info.st_uid not in {0, os.geteuid()} or (final and info.st_uid != os.geteuid())
                    or ((mode & 0o022) and not sticky_root)):
                raise ValueError("Invalid installed host settings")
            binding.append((info.st_dev, info.st_ino))
        return fd, tuple(binding)
    except BaseException:
        os.close(fd)
        raise


def _config_fingerprint(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _check_config_binding(path, binding, opened):
    current, observed = _config_parent(path)
    try:
        visible = os.stat(path.name, dir_fd=current, follow_symlinks=False)
        if observed != binding or _config_fingerprint(opened) != _config_fingerprint(visible):
            raise ValueError("Invalid installed host settings")
    finally:
        os.close(current)


def load_host_config(path):
    """Load bounded installed TOML without importing provider factories.

    Relative configured paths are anchored to the installed configuration's
    directory, never to a repository or the app's current working directory.
    """
    fd = parent = None
    try:
        path = Path(path).expanduser().absolute()
        if not path.name or ".." in path.parts or any(ord(c) < 32 for c in str(path)):
            raise ValueError("Invalid installed host settings")
        parent, binding = _config_parent(path)
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=parent)
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                or before.st_nlink != 1 or before.st_mode & 0o022 or before.st_size > _MAX_CONFIG_BYTES):
            raise ValueError("Invalid installed host settings")
        _check_config_binding(path, binding, before)
        raw = bytearray()
        while len(raw) <= _MAX_CONFIG_BYTES:
            part = os.read(fd, min(8192, _MAX_CONFIG_BYTES + 1 - len(raw)))
            if not part:
                break
            raw.extend(part)
        after = os.fstat(fd)
        if len(raw) > _MAX_CONFIG_BYTES or _config_fingerprint(before) != _config_fingerprint(after):
            raise ValueError("Invalid installed host settings")
        _check_config_binding(path, binding, after)
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
        if "native_admission_control" in cfg:
            cfg["native_admission_control"] = parse_admission_profile(cfg["native_admission_control"])
        return cfg
    except (OSError, ValueError, TypeError, RuntimeError, UnicodeError):
        raise ValueError("Invalid installed host settings") from None
    finally:
        if fd is not None:
            os.close(fd)
        if parent is not None:
            os.close(parent)


def control_from_config(cfg):
    return OperatingControl(cfg["lock_path"], cfg["repos"])


def _public_code(value):
    return value if isinstance(value, str) and _CODE.fullmatch(value) else None


def _native_scope(repo, number, record, host):
    if (record.get("host_alias") != host or record.get("execution_mode") != "native"
            or not record.get("native_step")):
        return None
    values = [repo, number, record.get("attempt_id"), record.get("head"), record.get("contract_revision")]
    if any(value is None for value in values):
        return None
    scope = hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()
    return record["native_step"], scope


def _remote_observations(cfg):
    # Import only for an explicit remote refresh. GitHub.progress authenticates
    # the service author and validates repository/Issue metadata and fields.
    from .github import GitHub
    github = GitHub(user="openboa")
    observations = {}
    retained = 0
    with github.read_budget(seconds=_REMOTE_READ_SECONDS, requests=_REMOTE_READ_REQUESTS) as total:
        for index, repo in enumerate(cfg["repos"]):
            row = {"work": [], "complete": False,
                   "native_scopes": [], "unresolved": False}
            observations[repo] = row
            remaining_repos = len(cfg["repos"]) - index
            try:
                with github.read_budget(seconds=total.remaining_seconds / remaining_repos,
                                        requests=total.remaining_requests // remaining_repos) as budget:
                    issues = github.issues(repo)
                    if not isinstance(issues, list):
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
                        # Discovery includes ordinary Issues. Only authenticated
                        # work consumes the independent display budget.
                        if len(row["work"]) >= _MAX_WORK_PER_PROJECT or retained >= _MAX_TOTAL_WORK:
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
                        scope = _native_scope(repo, number, record, cfg["host_alias"])
                        if scope is not None:
                            row["native_scopes"].append(scope)
                        if record.get("host_alias") == cfg["host_alias"]:
                            row["unresolved"] |= bool((record.get("native_step") and not record.get("native_outcome"))
                                                       or record.get("phase") == "executing")
                    if budget.remaining_seconds <= 0:
                        raise ValueError("Work observation time bound reached")
                    row["complete"] = True
            except (ValueError, RuntimeError, OSError, KeyError, TypeError):
                # Keep authenticated prefixes; later repositories retain their
                # own share. Neither partial rows nor raw errors certify idle.
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
    remote = _remote_observations(cfg) if action == "status" and refresh else {}
    # Remote reads may be slow. Date the local observation before its probes,
    # then read admission last so intervening Pause/Stop remains visible.
    observed_at = _now()
    try:
        found = residual_workers()
        workers = len(found) if isinstance(found, list) else None
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError):
        workers = None
    ownership = observe_coordinator(cfg["lock_path"])
    coverage = _coverage_observation()
    error = None
    try:
        snapshot = control.snapshot()
    except OperationDenied as exc:
        snapshot = {"revision": None, "global_mode": "unknown", "projects": {}}
        error = exc.reason
    mode = snapshot["global_mode"]
    gate_reason = error or (None if mode == "running" else "host_" + mode)
    for row in remote.values():
        row["bound_native"] = ownership.get("state") == "native" and (
            ownership.get("nonce"), ownership.get("scope_digest")) in row.pop("native_scopes")
        row["unresolved"] |= row["bound_native"]
    complete = bool(remote) and all(row["complete"] for row in remote.values())
    unresolved = any(row["unresolved"] for row in remote.values())
    execution = _execution(mode, ownership, workers, unresolved, coverage=coverage, remote_complete=complete)
    if error:
        execution = {"state": "unknown", "active_count": None, "reason": error}
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
