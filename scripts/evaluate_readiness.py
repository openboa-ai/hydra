#!/usr/bin/env python3
"""Pure evaluator for an OpenBoa pull-request readiness snapshot."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
from typing import Any, Sequence


POLICY_VERSION = 1
EXPECTED_BASE = "main"
EXPECTED_REVIEWER = "chatgpt-codex-connector"
COMPATIBILITY_CHECKS = ("openboa-governance",)
TRUSTED_CHECKS = {
    "openboa-governance-v2": (
        "openboa-ai/hydra:.github/workflows/openboa-governance-v2.yml@refs/heads/main"
    ),
}
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
    for required in COMPATIBILITY_CHECKS:
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

    for required, source_binding in TRUSTED_CHECKS.items():
        matches = [item for item in checks if isinstance(item, dict) and item.get("name") == required]
        if not matches:
            reasons.append(f"missing-trusted-check:{required}")
            continue
        if not any(
            item.get("status") == "COMPLETED"
            and item.get("conclusion") == SUCCESS
            and item.get("producer") == "github-actions"
            and item.get("source_binding") == source_binding
            for item in matches
        ):
            reasons.append(f"untrusted-or-unsuccessful-check:{required}")

    reviews = snapshot.get("reviews")
    reviews = reviews if isinstance(reviews, list) else []
    exact_head_reviews = [
        item for item in reviews
        if isinstance(item, dict)
        and item.get("actor") == EXPECTED_REVIEWER
        and item.get("commit_sha") == head
    ]
    ordered_reviews: list[tuple[datetime, dict[str, Any]]] = []
    for item in exact_head_reviews:
        submitted_at = item.get("submitted_at")
        try:
            observed_at = datetime.fromisoformat(
                submitted_at.replace("Z", "+00:00")
            )
            if observed_at.tzinfo is None:
                raise ValueError
        except (AttributeError, TypeError, ValueError):
            reasons.append("invalid-review-submitted-at")
            continue
        ordered_reviews.append((observed_at, item))
    latest_review = None
    if ordered_reviews:
        latest_at = max(value[0] for value in ordered_reviews)
        latest_candidates = [item for observed_at, item in ordered_reviews if observed_at == latest_at]
        latest_states = {item.get("state") for item in latest_candidates}
        if len(latest_states) != 1:
            reasons.append("ambiguous-latest-codex-review")
        else:
            latest_review = latest_candidates[0]
    if latest_review is not None and latest_review.get("state") == "CHANGES_REQUESTED":
        reasons.append("changes-requested-by-codex")
    if latest_review is None or latest_review.get("state") not in ("COMMENTED", "APPROVED"):
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
