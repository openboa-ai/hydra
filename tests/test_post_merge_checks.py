import copy
import unittest

from hydra_sdlc.project import gate_checks, post_merge_check_state, terminal_required_checks
from test_project import BASE, BLOB, HEAD, MERGE, config, observation


def push_observation():
    result = observation()
    result.pop("pr")
    result["head_sha"] = MERGE
    result["runs"][0].update(event="push", head_sha=MERGE, head_branch="main")
    for item in result["runs"][0]["jobs"] + result["checks"]:
        item["head_sha"] = MERGE
    return result


def pending(result, status="in_progress"):
    result["runs"][0].update(status=status, conclusion=None)
    result["runs"][0]["jobs"][0].update(status=status, conclusion=None)
    result["checks"][0].update(status=status, conclusion=None)


class PostMergeCheckTests(unittest.TestCase):
    def test_exact_completed_required_push_evidence_succeeds_without_mutation(self):
        cfg, result = config(), push_observation()
        before = copy.deepcopy((cfg, result))
        self.assertEqual(post_merge_check_state(cfg, result, MERGE), "success")
        self.assertEqual(gate_checks(cfg, result, MERGE, events=["push"]), [])
        self.assertEqual((cfg, result), before)

    def test_only_qualified_nonterminal_evidence_is_pending(self):
        for status in ("queued", "in_progress", "waiting", "pending", "requested"):
            with self.subTest(status=status):
                result = push_observation()
                pending(result, status)
                self.assertEqual(post_merge_check_state(config(), result, MERGE), "pending")
                self.assertTrue(gate_checks(config(), result, MERGE, events=["push"]))

    def test_missing_or_wrong_producer_identity_is_unknown_even_when_pending_or_failed(self):
        changes = [
            (["repository", "id"], 999), (["head_sha"], HEAD),
            (["runs", 0, "workflow_id"], 999), (["runs", 0, "path"], ".github/workflows/other.yml"),
            (["runs", 0, "repository", "id"], 999), (["runs", 0, "event"], "pull_request"),
            (["runs", 0, "head_sha"], HEAD), (["runs", 0, "head_branch"], "other"),
            (["runs", 0, "check_suite_id"], 999), (["runs", 0, "jobs", 0, "head_sha"], HEAD),
            (["runs", 0, "jobs", 0, "name"], "Other job"),
            (["runs", 0, "jobs", 0, "check_run_url"], "https://api.github.com/repos/other/repo/check-runs/90"),
            (["runs", 0, "jobs", 0, "run_id"], 999), (["runs", 0, "jobs", 0, "run_attempt"], 9),
            (["checks", 0, "id"], 999), (["checks", 0, "check_suite", "id"], 999),
            (["checks", 0, "app", "id"], 999), (["checks", 0, "head_sha"], HEAD),
            (["checks", 0, "name"], "Other job"), (["checks"], []), (["runs"], []),
            (["runs", 0, "jobs"], []), (["repository"], None), (["runs", 0, "repository"], None),
            (["checks", 0, "app"], None), (["checks", 0, "check_suite"], None),
        ]
        for state in ("success", "pending", "failed"):
            for path, value in changes:
                with self.subTest(state=state, path=path):
                    result = push_observation()
                    if state == "pending":
                        pending(result)
                    elif state == "failed":
                        result["runs"][0]["jobs"][0]["conclusion"] = "failure"
                        result["checks"][0]["conclusion"] = "failure"
                    target = result
                    for key in path[:-1]:
                        target = target[key]
                    target[path[-1]] = value
                    self.assertEqual(post_merge_check_state(config(), result, MERGE), "unknown")

    def test_unavailable_or_malformed_observation_is_unknown(self):
        for value in (None, {}, [], {"runs": [], "checks": []}):
            with self.subTest(observation=value):
                self.assertEqual(post_merge_check_state(config(), value, MERGE), "unknown")
        for sha in (None, "main", BASE, True):
            with self.subTest(sha=sha):
                self.assertEqual(post_merge_check_state(config(), push_observation(), sha), "unknown")
        for key, value in (("runs", None), ("checks", None), ("runs", [None]), ("checks", [None])):
            with self.subTest(key=key, value=value):
                result = push_observation()
                result[key] = value
                self.assertEqual(post_merge_check_state(config(), result, MERGE), "unknown")
        for value in (None, {}, {"required_checks": []}):
            self.assertEqual(post_merge_check_state(value, push_observation(), MERGE), "unknown")

    def test_missing_or_malformed_run_order_cannot_select_old_success(self):
        for field in ("id", "run_number", "run_attempt", "check_suite_id"):
            for value in (None, 0, -1, True, "2"):
                with self.subTest(field=field, value=value):
                    result = push_observation()
                    newer = copy.deepcopy(result["runs"][0])
                    newer.update(id=51, run_attempt=2)
                    newer[field] = value
                    result["runs"].append(newer)
                    self.assertEqual(post_merge_check_state(config(), result, MERGE), "unknown")

    def test_ambiguous_latest_run_or_required_job_is_unknown(self):
        result = push_observation()
        result["runs"].append(copy.deepcopy(result["runs"][0]))
        self.assertEqual(post_merge_check_state(config(), result, MERGE), "unknown")
        result = push_observation()
        result["runs"][0]["jobs"].append(copy.deepcopy(result["runs"][0]["jobs"][0]))
        self.assertEqual(post_merge_check_state(config(), result, MERGE), "unknown")

    def test_conflicting_duplicate_check_id_cannot_hide_behind_valid_publisher(self):
        result = push_observation()
        duplicate = copy.deepcopy(result["checks"][0])
        duplicate["app"]["id"] = 999
        result["checks"].append(duplicate)
        self.assertEqual(post_merge_check_state(config(), result, MERGE), "unknown")

    def test_terminal_required_job_or_check_failure_is_failed(self):
        for conclusion in ("failure", "timed_out", "cancelled", "startup_failure", "skipped",
                           "neutral", "action_required", "stale"):
            for source in ("job", "check", "both"):
                with self.subTest(conclusion=conclusion, source=source):
                    result = push_observation()
                    if source in {"job", "both"}:
                        result["runs"][0]["jobs"][0]["conclusion"] = conclusion
                    if source in {"check", "both"}:
                        result["checks"][0]["conclusion"] = conclusion
                    self.assertEqual(post_merge_check_state(config(), result, MERGE), "failed")

    def test_terminal_required_failure_remains_failed_while_other_jobs_run(self):
        result = push_observation()
        result["runs"][0].update(status="in_progress", conclusion=None)
        result["runs"][0]["jobs"][0]["conclusion"] = "failure"
        result["checks"][0]["conclusion"] = "failure"
        self.assertEqual(post_merge_check_state(config(), result, MERGE), "failed")

    def test_successful_required_jobs_wait_for_actual_pending_workflow(self):
        result = push_observation()
        result["runs"][0].update(status="in_progress", conclusion=None)
        self.assertEqual(post_merge_check_state(config(), result, MERGE), "pending")

    def test_optional_failure_does_not_fail_successful_required_jobs(self):
        result = push_observation()
        run = result["runs"][0]
        run["conclusion"] = "failure"
        optional = copy.deepcopy(run["jobs"][0])
        optional.update(id=91, name="Optional report", conclusion="failure",
                        check_run_url="https://api.github.com/repos/example/product/check-runs/91")
        run["jobs"].append(optional)
        check = copy.deepcopy(result["checks"][0])
        check.update(id=91, name="Optional report", conclusion="failure")
        result["checks"].append(check)
        self.assertEqual(post_merge_check_state(config(), result, MERGE), "success")
        self.assertEqual(gate_checks(config(), result, MERGE, events=["push"]), [])

    def test_newer_pending_rerun_overrides_old_failure(self):
        result = push_observation()
        old = result["runs"][0]
        old["conclusion"] = old["jobs"][0]["conclusion"] = result["checks"][0]["conclusion"] = "failure"
        newer = copy.deepcopy(old)
        newer.update(run_attempt=2, status="queued", conclusion=None)
        newer["jobs"][0].update(id=91, status="queued", conclusion=None,
                               check_run_url="https://api.github.com/repos/example/product/check-runs/91")
        check = copy.deepcopy(result["checks"][0])
        check.update(id=91, status="queued", conclusion=None)
        result["runs"].append(newer)
        result["checks"].append(check)
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                if reverse:
                    result["runs"].reverse()
                self.assertEqual(post_merge_check_state(config(), result, MERGE), "pending")

    def test_latest_unqualified_rerun_never_reuses_old_success(self):
        for missing in ("job", "check", "publisher", "reusable"):
            with self.subTest(missing=missing):
                cfg, result = config(), push_observation()
                newer = copy.deepcopy(result["runs"][0])
                newer.update(run_attempt=2)
                newer["jobs"][0].update(id=91, check_run_url="https://api.github.com/repos/example/product/check-runs/91")
                check = copy.deepcopy(result["checks"][0])
                check["id"] = 91
                result["runs"].append(newer)
                result["checks"].append(check)
                if missing == "job":
                    newer["jobs"] = []
                elif missing == "check":
                    result["checks"].pop()
                elif missing == "publisher":
                    check["app"]["id"] = 999
                else:
                    binding = cfg["required_checks"][0]
                    binding.update(reusable_workflow="example/controls/.github/workflows/check.yml", reusable_sha=BLOB)
                    result["runs"][0]["referenced_workflows"] = [
                        {"path": binding["reusable_workflow"] + "@" + BLOB, "sha": BLOB}]
                self.assertEqual(post_merge_check_state(cfg, result, MERGE), "unknown")

    def test_reusable_producer_requires_exact_pinned_identity_for_pending(self):
        cfg, result = config(), push_observation()
        pending(result)
        binding = cfg["required_checks"][0]
        binding.update(reusable_workflow="example/controls/.github/workflows/check.yml", reusable_sha=BLOB)
        self.assertEqual(post_merge_check_state(cfg, result, MERGE), "unknown")
        result["runs"][0]["referenced_workflows"] = [
            {"path": binding["reusable_workflow"] + "@" + BLOB, "sha": BLOB}]
        self.assertEqual(post_merge_check_state(cfg, result, MERGE), "pending")

    def test_unknown_or_inconsistent_status_never_becomes_pending_or_success(self):
        for path, value in [(["runs", 0, "status"], None), (["runs", 0, "status"], "mystery"),
                            (["runs", 0, "jobs", 0, "conclusion"], None),
                            (["checks", 0, "conclusion"], "unknown_result"),
                            (["checks", 0, "status"], "queued")]:
            with self.subTest(path=path, value=value):
                result = push_observation()
                target = result
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                self.assertEqual(post_merge_check_state(config(), result, MERGE), "unknown")
        result = push_observation()
        pending(result)
        result["runs"][0]["conclusion"] = "failure"
        self.assertEqual(post_merge_check_state(config(), result, MERGE), "unknown")

    def test_unknown_required_binding_prevents_polling_but_confirmed_failure_diagnoses(self):
        cfg, result = config(), push_observation()
        cfg["required_checks"].append({**cfg["required_checks"][0], "job": "Other required job"})
        pending(result)
        self.assertEqual(post_merge_check_state(cfg, result, MERGE), "unknown")
        result = push_observation()
        result["checks"][0]["conclusion"] = "failure"
        self.assertEqual(post_merge_check_state(cfg, result, MERGE), "failed")

    def test_existing_pr_terminal_missing_job_semantics_are_unchanged(self):
        cfg, result = config(), observation()
        result["runs"][0]["jobs"] = []
        self.assertEqual(terminal_required_checks(cfg, result, HEAD),
                         [{"job": "Unit tests", "conclusion": "missing_required_job"}])
        post_merge = push_observation()
        post_merge["runs"][0]["jobs"] = []
        self.assertEqual(post_merge_check_state(cfg, post_merge, MERGE), "unknown")


if __name__ == "__main__":
    unittest.main()
