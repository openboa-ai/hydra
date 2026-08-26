#!/usr/bin/env python3
"""Pure evaluator for an OpenBoa pull-request readiness snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Sequence


POLICY_VERSION = 1
EXPECTED_BASE = "main"
EXPECTED_REVIEWER = "chatgpt-codex-connector"
REQUIRED_CHECKS = ("openboa-governance",)
SUCCESS = "SUCCESS"


def evaluate(snapshot: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    if snapshot.get("policy_version") != POLICY_VERSION:
        reasons.append("policy-version-mismatch")
    if snapshot.get("base_ref") != EXPECTED_BASE:
        reasons.append("unexpected-base")
    head = snapshot.get("head_sha")
    if not isinstance(head, str) or re.fullmatch(r"[0-9a-f]{40}", head) is None:
        reasons.append("invalid-head")

    checks = snapshot.get("checks")
    checks = checks if isinstance(checks, list) else []
    for required in REQUIRED_CHECKS:
        matches = [item for item in checks if isinstance(item, dict) and item.get("name") == required]
        if not matches:
            reasons.append(f"missing-check:{required}")
            continue
        if not any(
            item.get("status") == "COMPLETED"
            and item.get("conclusion") == SUCCESS
            and item.get("producer") == "github-actions"
            for item in matches
        ):
            reasons.append(f"unsuccessful-check:{required}")

    reviews = snapshot.get("reviews")
    reviews = reviews if isinstance(reviews, list) else []
    qualifying = [
        item for item in reviews
        if isinstance(item, dict)
        and item.get("actor") == EXPECTED_REVIEWER
        and item.get("commit_sha") == head
        and item.get("state") not in (None, "PENDING", "DISMISSED")
    ]
    if not qualifying:
        reasons.append("missing-exact-head-codex-review")

    unresolved = snapshot.get("unresolved_threads")
    if not isinstance(unresolved, int) or isinstance(unresolved, bool) or unresolved < 0:
        reasons.append("invalid-unresolved-thread-count")
    elif unresolved:
        reasons.append("unresolved-review-threads")

    if snapshot.get("mergeable") is not True:
        reasons.append("not-mergeable")
    if snapshot.get("is_draft") is True:
        reasons.append("draft-pull-request")
    if snapshot.get("state") != "OPEN":
        reasons.append("pull-request-not-open")

    return {
        "policy_version": POLICY_VERSION,
        "pull_request": snapshot.get("pull_request"),
        "head_sha": head,
        "ready": not reasons,
        "reasons": sorted(set(reasons)),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = json.loads(args.snapshot.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"cannot read readiness snapshot: {exc}", file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print("readiness snapshot must be a JSON object", file=sys.stderr)
        return 2
    result = evaluate(payload)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
