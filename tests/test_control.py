"""Local controls never claim verified termination from missing observations."""

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from hydra_sdlc.control import (
    _execution, control_from_config, control_result, load_host_config,
)
from hydra_sdlc.operations import OperationDenied


REPOS = ["example/alpha", "example/beta"]
THREAD = "11111111-2222-4333-8444-555555555555"
ATTEMPT = "11111111-2222-4333-8444-666666666666"
STEP = "11111111-2222-4333-8444-777777777777"
HEAD, POLICY = "a" * 40, "b" * 40


class HostConfigTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.path = self.root / "host.toml"
        self.base = 'repos=["Example/alpha", "example/beta"]\nhost_alias="test"\nworkspace_root="work"\n'

    def config(self, text=None):
        self.path.write_text(self.base if text is None else text)
        self.path.chmod(0o600)
        return load_host_config(self.path)

    def test_load_expands_paths_and_canonicalizes_repositories(self):
        cfg = self.config(self.base + 'lock_path="locks/host.lock"\nruntime_python="venv/bin/python"\n'
            + 'knowledge_repo="Example/knowledge"\n[project_threads]\n"example/alpha"="' + THREAD + '"\n')
        self.assertEqual(cfg["repos"], REPOS)
        self.assertEqual(cfg["workspace_root"], str(self.root / "work"))
        self.assertEqual(cfg["lock_path"], str(self.root / "locks/host.lock"))
        self.assertEqual(cfg["runtime_python"], str(self.root / "venv/bin/python"))
        self.assertEqual(cfg["knowledge_repo"], "example/knowledge")
        self.assertEqual(cfg["project_threads"], {REPOS[0]: THREAD})
        self.assertEqual(control_from_config(cfg).repos, frozenset(REPOS))

    def test_loading_provider_names_does_not_load_factories(self):
        with patch("importlib.import_module", side_effect=AssertionError("provider loaded")):
            cfg = self.config(self.base + 'lifecycle_provider="example.lifecycle:create"\n'
                + 'storage_provider="example.storage:factory"\n')
        self.assertEqual(cfg["lifecycle_provider"], "example.lifecycle:create")

    def test_unknown_keys_cannot_qualify_desktop_or_schedule_coverage(self):
        for extra in ('qualified=true', 'schedule_coverage="confirmed"', 'model="something"',
                      'native_turn_control="supported"'):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "Invalid installed host settings"):
                self.config(self.base + extra)

    def test_invalid_repos_alias_paths_provider_and_thread_map_are_rejected(self):
        values = (
            self.base.replace('["Example/alpha", "example/beta"]', '[]'),
            self.base.replace('"example/beta"', '"example/ALPHA"'),
            self.base.replace('"Example/alpha"', '"example/.."'),
            self.base.replace('host_alias="test"', 'host_alias=true'),
            self.base.replace('host_alias="test"', 'host_alias="../other"'),
            self.base.replace('workspace_root="work"', 'workspace_root="../elsewhere"'),
            self.base.replace('workspace_root="work"', 'workspace_root=42'),
            self.base + 'storage_provider="/tmp/entry.py:run"',
            self.base + 'lifecycle_provider="module:factory();"',
            self.base + 'runtime_python=""',
            self.base + '[project_threads]\n"example/other"="' + THREAD + '"',
            self.base + '[project_threads]\n"example/alpha"="https://example.com"',
            self.base + '[project_threads]\n"Example/alpha"="' + THREAD + '"',
            self.base + 'project_threads=true',
        )
        for value in values:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "Invalid installed host settings"):
                self.config(value)

    def test_unsafe_symlink_hardlink_and_oversized_config_are_rejected(self):
        self.config()
        self.path.chmod(0o666)
        with self.assertRaises(ValueError):
            load_host_config(self.path)
        self.path.chmod(0o600)
        link = self.root / "link.toml"
        link.symlink_to(self.path)
        with self.assertRaises(ValueError):
            load_host_config(link)
        link.unlink()
        os.link(self.path, link)
        with self.assertRaises(ValueError):
            load_host_config(self.path)
        link.unlink()
        with self.assertRaises(ValueError):
            self.config("#" * 65537)

    def test_malformed_and_duplicate_toml_has_bounded_error(self):
        for text in ("not valid", self.base + 'host_alias="duplicate"', "\x00"):
            with self.assertRaises(ValueError) as raised:
                self.config(text)
            self.assertEqual(str(raised.exception), "Invalid installed host settings")
            self.assertNotIn(str(self.root), str(raised.exception))


class FakeGitHub:
    def __init__(self, records=None, unavailable=()):
        self.records = records or {}
        self.unavailable = set(unavailable)
        self.calls = []

    def issues(self, repo):
        self.calls.append(("issues", repo))
        if repo in self.unavailable:
            raise RuntimeError("private provider diagnostic /credential/path")
        return [{"number": number, "state": "open"} for number in self.records.get(repo, {})]

    def progress(self, repo, number):
        self.calls.append(("progress", repo, number))
        return copy.deepcopy(self.records[repo][number])


class ControlResultTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.cfg = {"repos": REPOS, "host_alias": "test", "workspace_root": str(self.root / "work"),
                    "lock_path": str(self.root / "host.lock"), "project_threads": {REPOS[0]: THREAD},
                    "lifecycle_provider": "nonexistent.provider:factory"}
        owner = patch("hydra_sdlc.control.observe_coordinator", return_value={"state": "free", "ticket": None})
        workers = patch("hydra_sdlc.control.residual_workers", return_value=[])
        self.ownership = owner.start()
        self.workers = workers.start()
        self.addCleanup(owner.stop)
        self.addCleanup(workers.stop)

    def test_local_status_does_not_load_providers_or_call_github(self):
        with patch("hydra_sdlc.github.GitHub", side_effect=AssertionError("GitHub used")), \
                patch("importlib.import_module", side_effect=AssertionError("provider loaded")):
            status = control_result(self.cfg)
        self.assertEqual(status["global_mode"], "stopped")
        self.assertEqual(status["remote"], {"state": "not_requested", "observed_at": None})
        self.assertEqual(status["execution"]["state"], "unknown")
        self.assertIsNone(status["execution"]["active_count"])
        self.assertEqual(status["native_turn_control"], "unsupported")
        self.assertFalse(status["can_quit"])
        self.assertIsNone(status["request"])
        self.assertFalse(Path(self.cfg["lock_path"]).exists())

    def test_schema_keys_are_stable_and_private_config_paths_are_not_returned(self):
        status = control_result(self.cfg)
        self.assertEqual(status["schema_version"], 2)
        self.assertEqual(set(status), {"schema_version", "runtime", "observed_at", "host_alias", "revision", "global_mode",
            "gate_status", "gate_reason", "native_turn_control", "execution", "coverage", "can_quit",
            "quit_reason", "remote", "projects", "request"})
        self.assertEqual(set(status["runtime"]), {"identity_schema", "package", "version", "code_digest",
            "code_digest_scope", "config_digest", "control_binding_digest", "identity_reason"})
        self.assertEqual(status["runtime"]["identity_schema"], 1)
        self.assertEqual(status["runtime"]["package"], "openboa-hydra-sdlc")
        self.assertEqual(status["runtime"]["code_digest_scope"], "package_sources_at_startup")
        for key in ("config_digest", "control_binding_digest"):
            self.assertRegex(status["runtime"][key], r"\A[0-9a-f]{64}\Z")
        self.assertEqual(set(status["projects"][0]), {"repository", "override_mode", "effective_mode", "gate_status",
            "gate_reason", "execution", "work", "links"})
        self.assertEqual(status["projects"][0]["links"], {"chat": "codex://threads/" + THREAD})
        self.assertEqual(status["projects"][1]["links"], {"chat": None})
        self.assertNotIn(str(self.root), json.dumps(status))

    def test_mode_update_is_applied_and_read_back_without_remote_refresh(self):
        with patch("hydra_sdlc.github.GitHub", side_effect=AssertionError("GitHub used")):
            result = control_result(self.cfg, "start", refresh=True)
        self.assertEqual(result["request"], {"action": "start", "target": "all", "status": "applied",
            "revision": 1, "reason": None})
        self.assertEqual(result["global_mode"], "running")
        self.assertEqual(result["gate_status"], "allowed")
        self.assertEqual(result["remote"]["state"], "not_requested")
        self.assertNotEqual(result["execution"]["state"], "running")
        self.assertFalse(result["can_quit"])

    def test_global_resume_preserves_individual_pause_and_stop(self):
        control_result(self.cfg, "start")
        control_result(self.cfg, "pause", REPOS[0])
        control_result(self.cfg, "stop", REPOS[1])
        control_result(self.cfg, "pause")
        result = control_result(self.cfg, "resume")
        self.assertEqual([p["effective_mode"] for p in result["projects"]], ["paused", "stopped"])
        self.assertEqual([p["gate_reason"] for p in result["projects"]], ["project_paused", "project_stopped"])

    def test_project_resume_under_global_stop_returns_hold(self):
        result = control_result(self.cfg, "resume", REPOS[0])
        self.assertEqual(result["request"]["status"], "held")
        self.assertEqual(result["request"]["reason"], "host_stopped")
        self.assertEqual(result["projects"][0]["effective_mode"], "stopped")
        self.assertEqual(result["revision"], 0)

    def test_unregistered_target_is_held_and_invalid_request_is_rejected(self):
        result = control_result(self.cfg, "start", "example/other")
        self.assertEqual(result["request"]["reason"], "operation_state_repository_unregistered")
        for action, repository, refresh in (("status", REPOS[0], False), ("launch", None, False),
                                             ("start", "../other", False), ("status", None, "yes"), ([], None, False)):
            with self.assertRaises(ValueError):
                control_result(self.cfg, action, repository, refresh)

    def test_corrupt_settings_are_unknown_and_cannot_be_enabled(self):
        control = control_from_config(self.cfg)
        control.set_mode("pause")
        control.settings_path.write_text("{broken}")
        result = control_result(self.cfg, "start")
        self.assertEqual(result["global_mode"], "unknown")
        self.assertEqual(result["gate_status"], "unknown")
        self.assertEqual(result["gate_reason"], "operation_state_invalid")
        self.assertIsNone(result["revision"])
        self.assertEqual(result["request"]["status"], "held")
        self.assertTrue(all(p["effective_mode"] == "unknown" for p in result["projects"]))

    def test_uncertain_mode_write_has_unknown_request_and_reconciled_observation(self):
        control = control_from_config(self.cfg)
        def uncertain(action, repository):
            control.set_mode(action, repository)
            raise OperationDenied("operation_state_unavailable")
        with patch("hydra_sdlc.control.control_from_config") as factory:
            fake = factory.return_value
            fake.set_mode.side_effect = uncertain
            fake.snapshot.side_effect = control.snapshot
            result = control_result(self.cfg, "pause")
        self.assertEqual(result["request"]["status"], "unknown")
        self.assertEqual(result["global_mode"], "paused")
        self.assertEqual(result["revision"], 1)

    def test_worker_observation_failure_and_residuals_do_not_become_zero(self):
        for workers in (subprocess.TimeoutExpired("ps", 5), ["1234", "5678"]):
            with self.subTest(workers=workers):
                self.workers.side_effect = workers if isinstance(workers, Exception) else None
                self.workers.return_value = workers if isinstance(workers, list) else None
                result = control_result(self.cfg, "stop")
                self.assertFalse(result["can_quit"])
                self.assertIsNone(result["execution"]["active_count"])
                self.assertNotIn("1234", json.dumps(result))
                self.assertNotIn("5678", json.dumps(result))
                self.assertTrue(all(project["execution"]["state"] == "unknown" for project in result["projects"]))

    def test_unmapped_owned_admission_is_never_attributed_to_every_project(self):
        self.ownership.return_value = {"state": "owned", "busy": True, "nonce": STEP}
        result = control_result(self.cfg, "stop")
        self.assertEqual(result["execution"]["state"], "stopping")
        self.assertTrue(all(project["execution"]["state"] == "unknown" for project in result["projects"]))

    def test_remote_refresh_sanitizes_work_links_and_preserves_partial_observations(self):
        github = FakeGitHub({REPOS[0]: {7: {"phase": "verification", "wait_reason": "ci_pending", "pr_number": 9,
                                          "next_action": "<script>secret</script>"}}}, unavailable=[REPOS[1]])
        with patch("hydra_sdlc.github.GitHub", return_value=github):
            status = control_result(self.cfg, refresh=True)
        self.assertEqual(status["remote"]["state"], "unavailable")
        project = status["projects"][0]
        self.assertEqual(project["work"], [{"issue": 7, "phase": "verification", "wait_reason": "ci_pending", "next_action": None,
            "links": {"issue": "https://github.com/example/alpha/issues/7", "pr": "https://github.com/example/alpha/pull/9"}}])
        self.assertEqual(project["links"], {"chat": "codex://threads/" + THREAD})
        self.assertFalse(status["can_quit"])
        self.assertNotIn("credential", json.dumps(status))
        self.assertNotIn("<script>", json.dumps(status))

    def test_remote_refresh_reports_admission_changes_during_the_last_remote_read(self):
        control = control_from_config(self.cfg)
        identity = control_result(self.cfg)["runtime"]
        for action, repository in (("pause", None), ("stop", None),
                                   ("pause", REPOS[0]), ("stop", REPOS[0])):
            for unavailable in (False, True):
                with self.subTest(action=action, repository=repository, unavailable=unavailable):
                    control.set_mode("start")
                    for repo in REPOS:
                        control.set_mode("resume", repo)
                    github = FakeGitHub({REPOS[0]: {7: {"phase": "verification", "pr_number": 9}}},
                                        unavailable=[REPOS[1]] if unavailable else [])
                    original = github.issues
                    applied = {}
                    def issues(repo):
                        if repo == REPOS[-1]:
                            applied.update(control.set_mode(action, repository))
                        return original(repo)
                    with patch.object(github, "issues", side_effect=issues), \
                            patch("hydra_sdlc.github.GitHub", return_value=github):
                        result = control_result(self.cfg, refresh=True)
                    mode = "paused" if action == "pause" else "stopped"
                    self.assertEqual(result["revision"], applied["revision"])
                    self.assertEqual(result["global_mode"], "running" if repository else mode)
                    self.assertEqual(result["gate_status"], "allowed" if repository else "blocked")
                    self.assertEqual(result["projects"][0]["effective_mode"], mode)
                    self.assertEqual(result["projects"][0]["gate_status"], "blocked")
                    self.assertEqual(result["projects"][1]["gate_status"], "allowed" if repository else "blocked")
                    self.assertEqual(result["projects"][0]["work"][0]["issue"], 7)
                    self.assertEqual(result["remote"]["state"], "unavailable" if unavailable else "fresh")
                    self.assertEqual(result["runtime"], identity)
                    self.assertEqual(result["coverage"]["state"], "unverified")
                    self.assertIsNone(result["request"])
                    self.assertIsNone(result["execution"]["active_count"])
                    self.assertFalse(result["can_quit"])

    def test_settings_corrupted_during_remote_refresh_cannot_remain_allowed(self):
        control = control_from_config(self.cfg)
        control.set_mode("start")
        github = FakeGitHub()
        original = github.issues
        def issues(repo):
            if repo == REPOS[-1]:
                control.settings_path.write_text("{broken}")
            return original(repo)
        with patch.object(github, "issues", side_effect=issues), \
                patch("hydra_sdlc.github.GitHub", return_value=github):
            result = control_result(self.cfg, refresh=True)
        self.assertEqual(result["remote"]["state"], "fresh")
        self.assertIsNone(result["revision"])
        self.assertEqual(result["global_mode"], "unknown")
        self.assertEqual(result["gate_reason"], "operation_state_invalid")
        self.assertTrue(all(project["gate_status"] == "unknown" for project in result["projects"]))
        self.assertIsNone(result["execution"]["active_count"])
        self.assertFalse(result["can_quit"])

    def test_local_probes_follow_remote_reads_and_admission_is_read_last(self):
        control = control_from_config(self.cfg)
        control.set_mode("start")
        github = FakeGitHub()
        original = github.issues
        clock = {"now": "2026-10-15T00:00:00.000000Z", "remote_done": False}
        observed = "2026-10-15T00:01:00.000000Z"
        def issues(repo):
            if repo == REPOS[-1]:
                clock.update(now=observed, remote_done=True)
            return original(repo)
        def workers():
            self.assertTrue(clock["remote_done"])
            clock["now"] = "2026-10-15T00:02:00.000000Z"
            control.set_mode("pause")
            return ["1234"]
        self.workers.side_effect = workers
        with patch.object(github, "issues", side_effect=issues), \
                patch("hydra_sdlc.github.GitHub", return_value=github), \
                patch("hydra_sdlc.control._now", side_effect=lambda: clock["now"]):
            result = control_result(self.cfg, refresh=True)
        self.assertEqual(result["observed_at"], observed)
        self.assertEqual(result["remote"]["observed_at"], observed)
        self.assertEqual(result["global_mode"], "paused")
        self.assertEqual(result["revision"], control.snapshot()["revision"])
        self.assertEqual(result["execution"]["state"], "pausing")
        self.assertEqual(result["execution"]["reason"], "residual_workers_unresolved")
        self.assertIsNone(result["execution"]["active_count"])
        self.assertFalse(result["can_quit"])
        self.assertNotIn("1234", json.dumps(result))

    def test_remote_refresh_cannot_reuse_an_earlier_successful_worker_observation(self):
        github = FakeGitHub()
        original = github.issues
        def issues(repo):
            if repo == REPOS[-1]:
                self.workers.side_effect = subprocess.TimeoutExpired("ps", 5)
            return original(repo)
        with patch.object(github, "issues", side_effect=issues), \
                patch("hydra_sdlc.github.GitHub", return_value=github):
            result = control_result(self.cfg, refresh=True)
        self.assertEqual(result["execution"]["reason"], "worker_observation_unavailable")
        self.assertIsNone(result["execution"]["active_count"])
        self.assertFalse(result["can_quit"])

    def test_remote_native_records_bind_only_to_current_ownership(self):
        first = {"host_alias": "test", "execution_mode": "native", "native_step": STEP,
                 "attempt_id": ATTEMPT, "head": HEAD, "contract_revision": POLICY,
                 "phase": "verification", "native_outcome": "completed"}
        second = {**first, "native_step": THREAD}
        def owner(repo, issue, step):
            digest = hashlib.sha256(json.dumps([repo, issue, ATTEMPT, HEAD, POLICY], separators=(",", ":")).encode()).hexdigest()
            return {"state": "native", "nonce": step, "scope_digest": digest}
        for current in (owner(REPOS[1], 8, THREAD), {"state": "free", "ticket": None},
                        {"state": "unknown", "reason": "ownership_observation_unavailable"}):
            with self.subTest(current=current["state"]):
                self.ownership.return_value = owner(REPOS[0], 7, STEP)
                github = FakeGitHub({REPOS[0]: {7: first}, REPOS[1]: {8: second}})
                original = github.progress
                def progress(repo, issue):
                    if repo == REPOS[-1]:
                        self.ownership.return_value = current
                    return original(repo, issue)
                with patch.object(github, "progress", side_effect=progress), \
                        patch("hydra_sdlc.github.GitHub", return_value=github):
                    result = control_result(self.cfg, refresh=True)
                self.assertEqual(result["projects"][0]["execution"]["state"], "unknown")
                self.assertEqual(result["projects"][1]["execution"]["state"],
                                 "stopping" if current["state"] == "native" else "unknown")
                self.assertEqual(result["execution"]["reason"], {
                    "native": "native_turn_control_unsupported", "free": "schedule_coverage_unverified",
                    "unknown": "ownership_observation_unavailable"}[current["state"]])
                self.assertIsNone(result["execution"]["active_count"])
                self.assertFalse(result["can_quit"])
                self.assertNotIn("native_scopes", json.dumps(result))

    def test_each_issue_retains_its_own_links_when_other_records_change(self):
        github = FakeGitHub({REPOS[0]: {
            7: {"phase": "verification", "pr_number": 9},
            8: {"phase": "delivery", "pr_number": 12},
            11: {"phase": "specification", "pr_number": "https://untrusted.example/private"},
        }})
        with patch("hydra_sdlc.github.GitHub", return_value=github):
            first = control_result(self.cfg, refresh=True)
            github.records[REPOS[0]].pop(7)
            github.records[REPOS[0]][8]["pr_number"] = 15
            later = control_result(self.cfg, refresh=True)
        links = {work["issue"]: work["links"] for work in first["projects"][0]["work"]}
        self.assertEqual(links, {
            7: {"issue": "https://github.com/example/alpha/issues/7", "pr": "https://github.com/example/alpha/pull/9"},
            8: {"issue": "https://github.com/example/alpha/issues/8", "pr": "https://github.com/example/alpha/pull/12"},
            11: {"issue": "https://github.com/example/alpha/issues/11", "pr": None},
        })
        later_links = {work["issue"]: work["links"] for work in later["projects"][0]["work"]}
        self.assertEqual(set(later_links), {8, 11})
        self.assertEqual(later_links[8], {"issue": "https://github.com/example/alpha/issues/8",
                                        "pr": "https://github.com/example/alpha/pull/15"})
        self.assertEqual(later_links[11], links[11])
        for result in (first, later):
            self.assertEqual(result["projects"][0]["links"], {"chat": "codex://threads/" + THREAD})
            self.assertNotIn("untrusted.example", json.dumps(result))

    def test_admission_changes_preserve_runtime_identity_and_unknown_execution(self):
        initial = control_result(self.cfg)
        for action, repository in (("start", None), ("pause", REPOS[0]), ("stop", None)):
            with self.subTest(action=action, repository=repository):
                result = control_result(self.cfg, action, repository)
                self.assertEqual(result["runtime"], initial["runtime"])
                self.assertIsNone(result["execution"]["active_count"])
                self.assertFalse(result["can_quit"])

    def test_fresh_empty_github_and_free_coordinator_do_not_certify_schedule_coverage(self):
        with patch("hydra_sdlc.github.GitHub", return_value=FakeGitHub()):
            status = control_result(self.cfg, refresh=True)
        self.assertEqual(status["remote"]["state"], "fresh")
        self.assertEqual(status["coverage"], {"state": "unverified", "reason": "schedule_coverage_unverified"})
        self.assertEqual(status["quit_reason"], "schedule_coverage_unverified")
        self.assertFalse(status["can_quit"])
        self.assertIsNone(status["execution"]["active_count"])

    def test_native_ticket_attribution_requires_exact_authenticated_scope(self):
        record = {"host_alias": "test", "execution_mode": "native", "native_step": STEP,
                  "attempt_id": ATTEMPT, "head": HEAD, "contract_revision": POLICY,
                  "phase": "executing", "native_outcome": None}
        digest = hashlib.sha256(json.dumps([REPOS[0], 7, ATTEMPT, HEAD, POLICY], separators=(",", ":")).encode()).hexdigest()
        self.ownership.return_value = {"state": "native", "nonce": STEP, "scope_digest": digest}
        for change, expected in (({}, "stopping"), ({"head": "c" * 40}, "unknown"),
                                 ({"host_alias": "other"}, "unknown"), ({"native_step": THREAD}, "unknown")):
            github = FakeGitHub({REPOS[0]: {7: {**record, **change}}})
            with self.subTest(change=change), patch("hydra_sdlc.github.GitHub", return_value=github):
                status = control_result(self.cfg, refresh=True)
            self.assertEqual(status["projects"][0]["execution"]["state"], expected)
            self.assertEqual(status["projects"][1]["execution"]["state"], "unknown")
            self.assertFalse(status["can_quit"])


class ExecutionEvidenceTests(unittest.TestCase):
    def test_only_complete_positive_evidence_can_report_zero_owned_executions(self):
        result = _execution("stopped", {"state": "free"}, 0, False,
                            coverage={"state": "confirmed"}, remote_complete=True)
        self.assertEqual(result, {"state": "stopped", "active_count": 0, "reason": None})
        for owner, workers, unresolved, coverage, remote in (
            ({"state": "unknown"}, 0, False, "confirmed", True),
            ({"state": "free"}, None, False, "confirmed", True),
            ({"state": "free"}, 1, False, "confirmed", True),
            ({"state": "free"}, 0, True, "confirmed", True),
            ({"state": "free"}, 0, False, "unverified", True),
            ({"state": "free"}, 0, False, "confirmed", False),
            ({"state": "native"}, 0, False, "confirmed", True),
        ):
            result = _execution("stopped", owner, workers, unresolved,
                                coverage={"state": coverage}, remote_complete=remote)
            self.assertIsNone(result["active_count"])
            self.assertNotEqual(result["state"], "stopped")

    def test_native_capability_alone_does_not_invent_active_execution(self):
        for mode, expected in (("running", "idle"), ("paused", "paused"), ("stopped", "stopped")):
            result = _execution(mode, {"state": "free"}, 0, False,
                                coverage={"state": "confirmed"}, remote_complete=True)
            self.assertEqual(result["state"], expected)
            self.assertEqual(result["active_count"], 0)


if __name__ == "__main__":
    unittest.main()
