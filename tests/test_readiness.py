from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EVALUATOR = load("evaluate_readiness", ROOT / "scripts/evaluate_readiness.py")
COLLECTOR = load("collect_readiness", ROOT / "scripts/collect_readiness.py")


def ready_snapshot(head: str = "a" * 40) -> dict:
    return {
        "policy_version": 1, "pull_request": 8, "state": "OPEN", "is_draft": False,
        "mergeable": True, "base_ref": "main", "head_sha": head, "unresolved_threads": 0,
        "checks": [
            {"name": "openboa-governance", "status": "COMPLETED", "conclusion": "SUCCESS", "producer": "github-actions", "source_binding": None},
            {
                "name": "openboa-governance-v2", "status": "COMPLETED", "conclusion": "SUCCESS",
                "producer": "github-actions",
                "source_binding": "openboa-ai/hydra:.github/workflows/openboa-governance-v2.yml@refs/heads/main",
            },
        ],
        "reviews": [{
            "actor": "chatgpt-codex-connector", "state": "COMMENTED",
            "commit_sha": head, "submitted_at": "2026-08-26T00:00:00Z",
        }],
    }


class ReadinessTests(unittest.TestCase):
    def test_ready_requires_all_exact_head_evidence(self) -> None:
        self.assertTrue(EVALUATOR.evaluate(ready_snapshot())["ready"])

    def test_skipped_neutral_and_missing_checks_fail_closed(self) -> None:
        for conclusion in ("SKIPPED", "NEUTRAL", None):
            with self.subTest(conclusion=conclusion):
                snapshot = ready_snapshot()
                snapshot["checks"][0]["conclusion"] = conclusion
                self.assertIn("unsuccessful-check:openboa-governance", EVALUATOR.evaluate(snapshot)["reasons"])
        snapshot = ready_snapshot()
        snapshot["checks"] = []
        self.assertIn("missing-check:openboa-governance", EVALUATOR.evaluate(snapshot)["reasons"])

    def test_new_head_invalidates_codex_review(self) -> None:
        snapshot = ready_snapshot()
        snapshot["head_sha"] = "b" * 40
        self.assertIn("missing-exact-head-codex-review", EVALUATOR.evaluate(snapshot)["reasons"])

    def test_changes_requested_review_blocks_readiness(self) -> None:
        snapshot = ready_snapshot()
        snapshot["reviews"][0]["state"] = "CHANGES_REQUESTED"
        decision = EVALUATOR.evaluate(snapshot)
        self.assertFalse(decision["ready"])
        self.assertIn("changes-requested-by-codex", decision["reasons"])
        self.assertIn("missing-exact-head-codex-review", decision["reasons"])

    def test_later_approval_supersedes_changes_requested_on_same_head(self) -> None:
        snapshot = ready_snapshot()
        snapshot["reviews"] = [
            {
                "actor": "chatgpt-codex-connector", "state": "CHANGES_REQUESTED",
                "commit_sha": snapshot["head_sha"], "submitted_at": "2026-08-26T00:00:00Z",
            },
            {
                "actor": "chatgpt-codex-connector", "state": "APPROVED",
                "commit_sha": snapshot["head_sha"], "submitted_at": "2026-08-26T00:01:00Z",
            },
        ]
        decision = EVALUATOR.evaluate(snapshot)
        self.assertTrue(decision["ready"])
        self.assertNotIn("changes-requested-by-codex", decision["reasons"])

    def test_untrusted_commit_status_cannot_impersonate_required_check(self) -> None:
        snapshot = ready_snapshot()
        snapshot["checks"][0]["producer"] = "commit-status"
        self.assertIn("unsuccessful-check:openboa-governance", EVALUATOR.evaluate(snapshot)["reasons"])

    def test_github_actions_slug_cannot_impersonate_trusted_workflow_source(self) -> None:
        snapshot = ready_snapshot()
        snapshot["checks"][1]["source_binding"] = None
        self.assertIn(
            "untrusted-or-unsuccessful-check:openboa-governance-v2",
            EVALUATOR.evaluate(snapshot)["reasons"],
        )

    def test_unresolved_draft_closed_and_unmergeable_fail(self) -> None:
        snapshot = ready_snapshot()
        snapshot.update({"unresolved_threads": 1, "is_draft": True, "state": "CLOSED", "mergeable": False})
        reasons = EVALUATOR.evaluate(snapshot)["reasons"]
        self.assertIn("unresolved-review-threads", reasons)
        self.assertIn("draft-pull-request", reasons)
        self.assertIn("pull-request-not-open", reasons)
        self.assertIn("not-mergeable", reasons)

    def test_collector_normalizes_graphql_without_trusting_candidate(self) -> None:
        head = "c" * 40
        payload = {"data":{"repository":{"pullRequest":{
            "number":8,"state":"OPEN","isDraft":False,"mergeable":"MERGEABLE","baseRefName":"main","headRefOid":head,
            "reviewThreads":{"nodes":[{"isResolved":True}],"pageInfo":{"hasNextPage":False}},
            "reviews":{"nodes":[{"state":"COMMENTED","submittedAt":"2026-08-26T00:00:00Z","author":{"login":"chatgpt-codex-connector"},"commit":{"oid":head}}],"pageInfo":{"hasPreviousPage":False}},
            "commits":{"nodes":[{"commit":{"statusCheckRollup":{"contexts":{"nodes":[{"name":"openboa-governance","status":"COMPLETED","conclusion":"SUCCESS","app":{"slug":"github-actions"}}],"pageInfo":{"hasNextPage":False}}}}}]}
        }}}}
        collected = COLLECTOR.normalize(payload, 8)
        self.assertEqual(head, collected["head_sha"])
        self.assertIsNone(collected["checks"][0]["source_binding"])
        decision = EVALUATOR.evaluate(collected)
        self.assertFalse(decision["ready"])
        self.assertIn("missing-trusted-check:openboa-governance-v2", decision["reasons"])


if __name__ == "__main__":
    unittest.main()
