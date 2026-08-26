#!/usr/bin/env python3
"""Collect read-only GitHub pull-request state for the pure readiness evaluator."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Sequence
from urllib import error, request


QUERY = """
query($owner:String!, $name:String!, $number:Int!) {
  repository(owner:$owner, name:$name) {
    pullRequest(number:$number) {
      number state isDraft mergeable baseRefName headRefOid
      reviewThreads(first:100) { nodes { isResolved } pageInfo { hasNextPage } }
      reviews(last:100) { nodes { state submittedAt author { login } commit { oid } } pageInfo { hasPreviousPage } }
      commits(last:1) { nodes { commit { statusCheckRollup { contexts(first:100) {
        nodes {
          ... on CheckRun { name status conclusion app { slug } }
          ... on StatusContext { context state }
        }
        pageInfo { hasNextPage }
      } } } } }
    }
  }
}
"""


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def graphql(token: str, variables: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps({"query": QUERY, "variables": variables}).encode("utf-8")
    req = request.Request(
        "https://api.github.com/graphql", data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "openboa-ready-shadow"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            result = json.load(response)
    except (error.URLError, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"GitHub GraphQL request failed: {exc}") from exc
    if result.get("errors"):
        raise RuntimeError(f"GitHub GraphQL returned errors: {result['errors']}")
    return result


def normalize(payload: dict[str, Any], number: int) -> dict[str, Any]:
    pr = payload["data"]["repository"]["pullRequest"]
    if pr is None:
        raise ValueError(f"pull request not found: {number}")
    threads = pr["reviewThreads"]
    reviews = pr["reviews"]
    contexts = pr["commits"]["nodes"][0]["commit"].get("statusCheckRollup")
    context_connection = contexts.get("contexts") if contexts else {"nodes": [], "pageInfo": {"hasNextPage": False}}
    if threads["pageInfo"]["hasNextPage"] or reviews["pageInfo"]["hasPreviousPage"] or context_connection["pageInfo"]["hasNextPage"]:
        raise ValueError("readiness state exceeds bounded GraphQL page")
    checks: list[dict[str, Any]] = []
    for item in context_connection["nodes"]:
        if "name" in item:
            checks.append({
                "name": item.get("name"), "status": item.get("status"),
                "conclusion": item.get("conclusion"), "producer": (item.get("app") or {}).get("slug"),
                # A GitHub App slug does not prove which workflow source produced
                # a check. A later ruleset/source readback must populate this.
                "source_binding": None,
            })
        else:
            checks.append({
                "name": item.get("context"), "status": "COMPLETED",
                "conclusion": "SUCCESS" if item.get("state") == "SUCCESS" else item.get("state"),
                "producer": "commit-status", "source_binding": None,
            })
    return {
        "policy_version": 1,
        "pull_request": number,
        "state": pr["state"],
        "is_draft": pr["isDraft"],
        "mergeable": pr["mergeable"] == "MERGEABLE",
        "base_ref": pr["baseRefName"],
        "head_sha": pr["headRefOid"],
        "unresolved_threads": sum(1 for item in threads["nodes"] if not item["isResolved"]),
        "reviews": [
            {
                "state": item["state"],
                "submitted_at": item.get("submittedAt"),
                "actor": (item.get("author") or {}).get("login"),
                "commit_sha": (item.get("commit") or {}).get("oid"),
            }
            for item in reviews["nodes"]
        ],
        "checks": checks,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is required", file=sys.stderr)
        return 2
    try:
        owner, name = args.repository.split("/", 1)
        snapshot = normalize(graphql(token, {"owner": owner, "name": name, "number": args.pr}), args.pr)
        args.output.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (ValueError, KeyError, TypeError, RuntimeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
