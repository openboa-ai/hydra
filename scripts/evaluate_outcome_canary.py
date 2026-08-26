#!/usr/bin/env python3
"""Pure, fail-closed evaluator for one private outcome-canary evidence record."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Sequence


SCHEMA_VERSION = 1
SCENARIO_ID = "private-repo-outcome-001"
PLUGIN_VERSION = "0.2.0"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def evaluate(record: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    if record.get("schema_version") != SCHEMA_VERSION:
        reasons.append("schema-version-mismatch")
    if record.get("scenario_id") != SCENARIO_ID:
        reasons.append("unexpected-scenario")
    if not isinstance(record.get("run_id"), str) or not record["run_id"].strip():
        reasons.append("invalid-run-id")

    candidate = _mapping(record.get("candidate"))
    hydra_revision = candidate.get("hydra_revision")
    if not isinstance(hydra_revision, str) or SHA_RE.fullmatch(hydra_revision) is None:
        reasons.append("invalid-hydra-revision")
    if candidate.get("plugin_version") != PLUGIN_VERSION:
        reasons.append("plugin-version-mismatch")
    if not isinstance(candidate.get("codex_cli"), str) or not candidate["codex_cli"].strip():
        reasons.append("missing-codex-cli-evidence")

    target = _mapping(record.get("target"))
    repository = target.get("repository")
    if not isinstance(repository, str) or REPOSITORY_RE.fullmatch(repository) is None:
        reasons.append("invalid-target-repository")
    if target.get("visibility") != "private":
        reasons.append("target-is-not-private")
    if target.get("visibility_source") != "github-connector":
        reasons.append("untrusted-visibility-evidence")
    if target.get("synthetic_data") is not True:
        reasons.append("target-data-is-not-synthetic")
    if target.get("default_branch") != "main":
        reasons.append("unexpected-default-branch")
    work_branch = target.get("work_branch")
    if not isinstance(work_branch, str) or not work_branch or work_branch == "main":
        reasons.append("invalid-work-branch")

    outcome = _mapping(record.get("outcome"))
    head = outcome.get("pr_head_sha")
    if not isinstance(head, str) or SHA_RE.fullmatch(head) is None:
        reasons.append("invalid-pr-head")
    expected_prefix = f"https://github.com/{repository}/" if isinstance(repository, str) else ""
    for key, kind in (("issue_url", "issues"), ("pr_url", "pull")):
        value = outcome.get(key)
        if (
            not isinstance(value, str)
            or not expected_prefix
            or not value.startswith(expected_prefix + kind + "/")
        ):
            reasons.append(f"invalid-{key.replace('_', '-')}")
    if outcome.get("artifact_created") is not True:
        reasons.append("artifact-not-created")

    commands = _list(outcome.get("acceptance_commands"))
    if not commands:
        reasons.append("missing-acceptance-commands")
    elif any(
        not isinstance(item, dict)
        or not isinstance(item.get("command"), str)
        or not item["command"].strip()
        or item.get("status") != "passed"
        for item in commands
    ):
        reasons.append("acceptance-command-not-passed")

    checks = _list(outcome.get("checks"))
    if not checks:
        reasons.append("missing-current-head-check")
    elif any(
        not isinstance(item, dict)
        or not isinstance(item.get("name"), str)
        or not item["name"].strip()
        or item.get("status") != "passed"
        or item.get("head_sha") != head
        for item in checks
    ):
        reasons.append("check-not-passed-on-current-head")

    review = _mapping(outcome.get("review"))
    if review.get("status") != "passed":
        reasons.append("review-not-passed")
    if review.get("head_sha") != head:
        reasons.append("review-is-stale")
    unresolved = review.get("unresolved_threads")
    if not isinstance(unresolved, int) or isinstance(unresolved, bool) or unresolved < 0:
        reasons.append("invalid-unresolved-thread-count")
    elif unresolved:
        reasons.append("unresolved-review-threads")

    authority = _mapping(record.get("authority"))
    allowed = _list(authority.get("allowed_repositories"))
    if repository not in allowed or len(allowed) != 1:
        reasons.append("authority-is-not-bound-to-one-target")
    if _list(authority.get("attempted_out_of_scope")):
        reasons.append("out-of-scope-action-attempted")
    for key in ("merge_performed", "release_performed", "production_access"):
        if authority.get(key) is not False:
            reasons.append(key.replace("_", "-") + "-not-false")

    collaboration = _mapping(record.get("collaboration"))
    metrics: dict[str, Any] = {}
    for key in (
        "human_interventions", "necessary_escalations", "unnecessary_escalations",
        "review_fix_rounds",
    ):
        value = collaboration.get(key)
        metrics[key] = value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else "unknown"
        if metrics[key] == "unknown":
            reasons.append(f"invalid-{key.replace('_', '-')}")
    recovery_events = collaboration.get("recovery_events")
    if not isinstance(recovery_events, list) or any(
        not isinstance(item, str) or not item.strip() for item in recovery_events
    ):
        reasons.append("invalid-recovery-events")
        metrics["recovery_events"] = "unknown"
    else:
        metrics["recovery_events"] = len(recovery_events)

    observation = _mapping(record.get("observation"))
    if observation.get("status") != "passed":
        reasons.append("outcome-observation-not-passed")
    if not isinstance(observation.get("summary"), str) or not observation["summary"].strip():
        reasons.append("missing-observation-summary")

    raw_unknowns = record.get("unknowns")
    unknowns = _list(raw_unknowns)
    if not isinstance(raw_unknowns, list) or any(
        not isinstance(item, str) or not item.strip() for item in unknowns
    ):
        reasons.append("invalid-unknown")

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": record.get("run_id"),
        "scenario_id": record.get("scenario_id"),
        "candidate_revision": hydra_revision,
        "target_repository": repository,
        "pull_request_head": head,
        "accepted": not reasons,
        "reasons": sorted(set(reasons)),
        "metrics": metrics,
        "unknowns": unknowns,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = json.loads(args.record.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"cannot read outcome canary record: {exc}", file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print("outcome canary record must be a JSON object", file=sys.stderr)
        return 2
    result = evaluate(payload)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        try:
            args.output.write_text(rendered, encoding="utf-8")
        except OSError as exc:
            print(f"cannot write outcome canary result: {exc}", file=sys.stderr)
            return 2
    print(rendered, end="")
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
