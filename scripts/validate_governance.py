#!/usr/bin/env python3
"""Run base-controlled governance checks over a candidate tree.

The trusted workflow executes this file from the trusted source checkout and
passes the candidate checkout only as data.  This module deliberately has no
imports from, and never executes, the candidate tree.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path


CONFIG_RELATIVE = Path(".github/openboa-governance.yml")
WORKFLOW_RELATIVE = Path(".github/workflows/openboa-governance-v2.yml")
MAX_HASH_BYTES = 32 * 1024 * 1024
IGNORED_PARTS = {".git", "__pycache__", ".venv"}
REQUIRED_PROTECTED_PATHS = {
    "AGENTS.md",
    ".github/openboa-governance.yml",
    ".github/workflows/**",
    "scripts/validate_governance.py",
}
SHA_REFERENCE = re.compile(r"^[^\s#]+@[0-9a-f]{40}$")


@dataclass(frozen=True)
class AuditResult:
    errors: tuple[str, ...]
    changed_paths: tuple[str, ...]
    protected_changes: tuple[str, ...]
    trusted_source_revision: str
    candidate_revision: str

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def risk_lane(self) -> str:
        return "high" if self.protected_changes else "routine"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trusted-source", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--base-sha", default="unknown")
    parser.add_argument("--head-sha", default="unknown")
    args = parser.parse_args(argv)

    result = audit(
        trusted_source=args.trusted_source,
        candidate=args.candidate,
        base_sha=args.base_sha,
        head_sha=args.head_sha,
    )
    print(f"trusted_source_revision={result.trusted_source_revision}")
    print(f"candidate_revision={result.candidate_revision}")
    print(f"base_sha={args.base_sha}")
    print(f"head_sha={args.head_sha}")
    print(f"changed_path_count={len(result.changed_paths)}")
    print(f"risk_lane={result.risk_lane}")
    print(f"human_gate_required={'true' if result.protected_changes else 'false'}")
    for path in result.changed_paths:
        print(f"changed_path={path}")
    for path in result.protected_changes:
        print(f"protected_change={path}")
    if result.errors:
        print("governance_result=fail")
        for error in result.errors:
            print(f"error={error}")
        return 1
    print("governance_result=pass")
    return 0


def audit(
    *, trusted_source: Path, candidate: Path, base_sha: str, head_sha: str
) -> AuditResult:
    del base_sha, head_sha  # The workflow records these; file checks stay deterministic.
    errors: list[str] = []
    trusted_source = trusted_source.resolve()
    candidate = candidate.resolve()

    if not trusted_source.is_dir():
        errors.append("trusted source is not a directory")
    if not candidate.is_dir():
        errors.append("candidate is not a directory")

    protected_patterns: tuple[str, ...] = ()
    if trusted_source.is_dir():
        protected_patterns, config_errors = load_config(trusted_source / CONFIG_RELATIVE)
        errors.extend(config_errors)
        errors.extend(validate_trusted_workflow(trusted_source / WORKFLOW_RELATIVE))
        if not regular_file(trusted_source / "scripts" / "validate_governance.py"):
            errors.append("trusted source is missing scripts/validate_governance.py")

    changed_paths: tuple[str, ...] = ()
    protected_changes: tuple[str, ...] = ()
    trusted_snapshot = snapshot(trusted_source) if trusted_source.is_dir() else {}
    candidate_snapshot = snapshot(candidate) if candidate.is_dir() else {}
    if trusted_source.is_dir() and candidate.is_dir():
        changed_paths = tuple(
            sorted(
                path
                for path in set(trusted_snapshot) | set(candidate_snapshot)
                if trusted_snapshot.get(path) != candidate_snapshot.get(path)
            )
        )
        protected_changes = tuple(
            path for path in changed_paths if matches_any(path, protected_patterns)
        )
        errors.extend(validate_candidate_protected_files(candidate, protected_changes))

    return AuditResult(
        errors=tuple(errors),
        changed_paths=changed_paths,
        protected_changes=protected_changes,
        trusted_source_revision=git_revision(trusted_source),
        candidate_revision=git_revision(candidate),
    )


def load_config(path: Path) -> tuple[tuple[str, ...], list[str]]:
    if not regular_file(path):
        return (), [f"missing governance config: {CONFIG_RELATIVE.as_posix()}"]
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return (), [f"unable to read governance config: {exc}"]

    errors: list[str] = []
    version_lines = [line for line in lines if re.fullmatch(r"version:\s*1\s*", line)]
    if len(version_lines) != 1:
        errors.append("governance config must declare exactly `version: 1`")

    paths: list[str] = []
    in_paths = False
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "protected_paths:":
            if in_paths:
                errors.append("governance config must contain one protected_paths list")
            in_paths = True
            continue
        if in_paths and raw.startswith("  - "):
            value = raw[4:].strip()
            if not value or value.startswith("#"):
                errors.append("governance config contains an empty protected path")
            else:
                paths.append(value)
            continue
        if in_paths:
            errors.append(f"unsupported governance config line: {raw}")
            in_paths = False
            continue
        if raw.startswith("version:"):
            continue
        errors.append(f"unsupported governance config line: {raw}")

    if not paths:
        errors.append("governance config must contain protected_paths")
    if len(paths) != len(set(paths)):
        errors.append("governance config protected paths must be unique")
    missing = sorted(REQUIRED_PROTECTED_PATHS - set(paths))
    for path_name in missing:
        errors.append(f"governance config must protect `{path_name}`")
    return tuple(paths), errors


def validate_trusted_workflow(path: Path) -> list[str]:
    if not regular_file(path):
        return [f"missing trusted workflow: {WORKFLOW_RELATIVE.as_posix()}"]
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"unable to read trusted workflow: {exc}"]

    errors: list[str] = []
    if len(re.findall(r"(?m)^\s+name:\s*openboa-governance-v2\s*$", text)) != 1:
        errors.append("trusted workflow must contain exactly one openboa-governance-v2 job")
    if not re.search(r"(?m)^  pull_request:\s*$", text):
        errors.append("trusted workflow must trigger on pull_request")
    if not re.search(r"(?m)^  merge_group:\s*$", text):
        errors.append("trusted workflow must trigger on merge_group")
    if "pull_request_target" in text:
        errors.append("trusted workflow must not use pull_request_target")
    permissions = _top_level_mapping_children(text, "permissions")
    if permissions != [(2, "contents: read")]:
        errors.append("trusted workflow permissions must grant only contents: read")
    if re.search(r"(?mi)secrets\.", text):
        errors.append("trusted workflow must not request secret access")
    if re.search(r"(?m)^\s+continue-on-error:\s*", text):
        errors.append("trusted workflow must not continue on error")
    timeout_count = len(re.findall(r"(?m)^\s+timeout-minutes:\s*[1-9][0-9]*\s*$", text))
    if timeout_count != 1:
        errors.append("trusted workflow must declare one positive timeout-minutes value")

    action_references = re.findall(r"(?m)^\s*uses:\s*([^\s#]+)", text)
    checkout_references = [
        reference
        for reference in action_references
        if reference.startswith("actions/checkout@")
    ]
    if len(checkout_references) != 2:
        errors.append("trusted workflow must use checkout exactly twice for trusted and candidate trees")
    for reference in action_references:
        if not SHA_REFERENCE.fullmatch(reference):
            errors.append(f"trusted workflow action must use a full commit SHA: {reference}")
    if "path: trusted-source" not in text or "path: candidate" not in text:
        errors.append("trusted workflow must keep trusted and candidate checkouts separate")
    if "python3 trusted-source/scripts/validate_hydra.py candidate" not in text:
        errors.append("trusted workflow must run the trusted Hydra validator over candidate data")
    if "python3 trusted-source/scripts/validate_governance.py" not in text:
        errors.append("trusted workflow must run the trusted governance validator")
    if "repository: openboa-ai/hydra" not in text:
        errors.append("trusted workflow must pin its trusted source repository")
    if not re.search(r"(?m)^\s+ref:\s*main\s*$", text):
        errors.append("trusted workflow must check out the trusted source main branch")
    return errors


def _top_level_mapping_children(text: str, key: str) -> list[tuple[int, str]]:
    """Return the active two-space children of one top-level YAML mapping."""

    lines = text.splitlines()
    start: int | None = None
    for index, raw in enumerate(lines):
        if re.fullmatch(rf"{re.escape(key)}:\s*(?:#.*)?", raw):
            if start is not None:
                return []
            start = index
    if start is None:
        return []

    children: list[tuple[int, str]] = []
    for raw in lines[start + 1 :]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent == 0:
            break
        children.append((indent, raw.strip()))
    return children


def validate_candidate_protected_files(
    candidate: Path, protected_changes: tuple[str, ...]
) -> list[str]:
    errors: list[str] = []
    for relative in protected_changes:
        path = candidate / relative
        if path.is_symlink():
            errors.append(f"protected candidate path must not be a symlink: {relative}")
        elif path.exists() and not path.is_file():
            errors.append(f"protected candidate path must be a regular file: {relative}")
    return errors


def snapshot(root: Path) -> dict[str, tuple[object, ...]]:
    result: dict[str, tuple[object, ...]] = {}
    for current, directory_names, file_names in os.walk(
        root, topdown=True, followlinks=False
    ):
        current_path = Path(current)
        current_relative = current_path.relative_to(root)
        if set(current_relative.parts) & IGNORED_PARTS:
            directory_names[:] = []
            file_names[:] = []
            continue
        retained_directories: list[str] = []
        for name in directory_names:
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            if set(path.relative_to(root).parts) & IGNORED_PARTS:
                continue
            result[relative] = file_state(path)
            if not path.is_symlink():
                retained_directories.append(name)
        directory_names[:] = retained_directories
        for name in file_names:
            path = current_path / name
            if set(path.relative_to(root).parts) & IGNORED_PARTS:
                continue
            result[path.relative_to(root).as_posix()] = file_state(path)
    return result


def file_state(path: Path) -> tuple[object, ...]:
    try:
        info = path.lstat()
    except OSError as exc:
        return ("unreadable", type(exc).__name__)
    if stat.S_ISLNK(info.st_mode):
        try:
            return ("symlink", os.readlink(path))
        except OSError as exc:
            return ("unreadable-symlink", type(exc).__name__)
    if not stat.S_ISREG(info.st_mode):
        return ("special", info.st_mode)
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_HASH_BYTES:
                    return ("oversized", total)
                digest.update(chunk)
    except OSError as exc:
        return ("unreadable", type(exc).__name__)
    return ("file", total, digest.hexdigest())


def matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    return any(
        fnmatch.fnmatchcase(path, pattern)
        or (
            pattern.endswith("/**")
            and path.startswith(pattern[:-2])
        )
        for pattern in patterns
    )


def regular_file(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode)


def git_revision(root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
        value = completed.stdout.strip()
        if re.fullmatch(r"[0-9a-f]{40}", value):
            return value
    except (OSError, subprocess.SubprocessError):
        pass
    return "unavailable"


if __name__ == "__main__":
    raise SystemExit(main())
