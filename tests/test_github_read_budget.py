"""Remote observation budgets constrain real transport work, not display size."""

import json
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from hydra_sdlc.github import GitHub, GitHubError


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class ReadBudgetTests(unittest.TestCase):
    def test_nested_request_limits_restore_without_replenishing_parent(self):
        calls = []
        gh = GitHub(transport=lambda *args: calls.append(args) or {})
        with gh.read_budget(seconds=10, requests=2) as total:
            with gh.read_budget(seconds=10, requests=1):
                gh.api("GET", "/first")
                with self.assertRaises(GitHubError):
                    gh.api("GET", "/child-overflow")
            self.assertEqual(total.remaining_requests, 1)
            gh.api("GET", "/last-allowed")
            with self.assertRaises(GitHubError):
                gh.api("GET", "/parent-overflow")
            other = GitHub(transport=lambda *args: {})
            other.api("GET", "/independent")
        gh.api("GET", "/outside")
        self.assertEqual([call[1] for call in calls], ["/first", "/last-allowed", "/outside"])

    def test_late_transport_response_is_rejected_and_exception_restores_scope(self):
        clock = Clock()
        def transport(*args):
            clock.now += 2
            return {"late": True}
        gh = GitHub(transport=transport)
        with patch("hydra_sdlc.github.time.monotonic", clock):
            with self.assertRaises(GitHubError):
                with gh.read_budget(seconds=1, requests=10):
                    with gh.read_budget(seconds=100, requests=10):
                        gh.api("GET", "/late")
            self.assertEqual(gh.api("GET", "/outside"), {"late": True})

    def test_expired_scope_does_not_start_transport(self):
        clock = Clock()
        calls = []
        gh = GitHub(transport=lambda *args: calls.append(args))
        with patch("hydra_sdlc.github.time.monotonic", clock):
            with gh.read_budget(seconds=1, requests=10):
                clock.now = 1
                with self.assertRaises(GitHubError):
                    gh.api("GET", "/never")
        self.assertEqual(calls, [])

    def test_pagination_consumes_one_cumulative_budget(self):
        calls = []
        gh = GitHub(transport=lambda *args: calls.append(args) or [{}] * 100)
        with gh.read_budget(seconds=10, requests=2):
            with self.assertRaises(GitHubError):
                gh.comments("example/product", 1)
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[-1][1].endswith("page=2"))

    def test_real_transport_subprocesses_use_decreasing_nested_deadlines(self):
        clock, calls = Clock(), []
        def run(argv, **kwargs):
            calls.append((argv, kwargs["timeout"]))
            clock.now += 1
            body = "fixture-token" if argv[1] == "auth" else json.dumps({"login": "openboa"})
            return subprocess.CompletedProcess(argv, 0, body, "")
        with patch("hydra_sdlc.github.time.monotonic", clock), \
                patch("hydra_sdlc.github.subprocess.run", side_effect=run):
            gh = GitHub()
            with gh.read_budget(seconds=20, requests=10):
                with gh.read_budget(seconds=10, requests=2):
                    gh.api("GET", "/repos/example/product")
        self.assertEqual([timeout for _, timeout in calls], [10, 9, 8])
        self.assertEqual([argv[1] for argv, _ in calls], ["auth", "api", "api"])

    def test_internal_identity_request_is_counted_before_dispatch(self):
        calls = []
        def run(argv, **kwargs):
            calls.append(argv)
            body = "fixture-token" if argv[1] == "auth" else '{"login":"openboa"}'
            return subprocess.CompletedProcess(argv, 0, body, "")
        with patch("hydra_sdlc.github.subprocess.run", side_effect=run):
            gh = GitHub()
            with gh.read_budget(seconds=10, requests=1):
                with self.assertRaises(GitHubError):
                    gh.api("GET", "/repos/example/product")
            self.assertEqual([argv[1] for argv in calls], ["auth"])
            calls.clear()
            with gh.read_budget(seconds=10, requests=2) as budget:
                gh.api("GET", "/repos/example/product")
                self.assertEqual(budget.remaining_requests, 0)
                with self.assertRaises(GitHubError):
                    gh.api("GET", "/never")
            self.assertEqual([argv[1] for argv in calls], ["auth", "api", "api"])

    def test_changed_credential_identity_also_consumes_the_remaining_budget(self):
        calls, token = [], ["first"]
        def run(argv, **kwargs):
            calls.append(argv)
            body = token[0] if argv[1] == "auth" else '{"login":"openboa"}'
            return subprocess.CompletedProcess(argv, 0, body, "")
        with patch("hydra_sdlc.github.subprocess.run", side_effect=run):
            gh = GitHub()
            with gh.read_budget(seconds=10, requests=3):
                gh.api("GET", "/first")
                token[0] = "second"
                with self.assertRaises(GitHubError):
                    gh.api("GET", "/not-dispatched")
        self.assertEqual([argv[1] for argv in calls], ["auth", "api", "api", "auth"])

    def test_deadline_after_auth_prevents_identity_subprocess(self):
        clock, calls = Clock(), []
        def run(argv, **kwargs):
            calls.append(kwargs["timeout"])
            clock.now = 2
            return subprocess.CompletedProcess(argv, 0, "fixture-token", "")
        with patch("hydra_sdlc.github.time.monotonic", clock), \
                patch("hydra_sdlc.github.subprocess.run", side_effect=run):
            gh = GitHub()
            with gh.read_budget(seconds=1, requests=10):
                with self.assertRaises(GitHubError):
                    gh.api("GET", "/never")
        self.assertEqual(calls, [1])

    def test_real_auth_child_is_terminated_at_remaining_deadline(self):
        real_run = subprocess.run
        timeouts = []
        def sleeping_auth(argv, **kwargs):
            self.assertEqual(argv[1], "auth")
            timeouts.append(kwargs["timeout"])
            return real_run([sys.executable, "-c", "import time; time.sleep(2)"], **kwargs)
        started = time.monotonic()
        with patch("hydra_sdlc.github.subprocess.run", side_effect=sleeping_auth):
            gh = GitHub()
            with gh.read_budget(seconds=0.05, requests=10):
                with self.assertRaises(GitHubError) as caught:
                    gh.api("GET", "/never")
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(len(timeouts), 1)
        self.assertGreater(timeouts[0], 0)
        self.assertLessEqual(timeouts[0], 0.05)
        self.assertFalse(caught.exception.uncertain)

    def test_unbudgeted_transport_keeps_auth_timeouts_and_write_uncertainty(self):
        calls = []
        def run(argv, **kwargs):
            calls.append(kwargs["timeout"])
            if argv[1] == "auth":
                return subprocess.CompletedProcess(argv, 0, "fixture-token", "")
            if argv[-1] == "user":
                return subprocess.CompletedProcess(argv, 0, '{"login":"openboa"}', "")
            return subprocess.CompletedProcess(argv, 1, "", "HTTP 503")
        with patch("hydra_sdlc.github.subprocess.run", side_effect=run):
            with self.assertRaises(GitHubError) as caught:
                GitHub().api("POST", "/repos/example/product/issues", {"title": "example"})
        self.assertEqual(calls, [15, 30, 45])
        self.assertTrue(caught.exception.uncertain)


if __name__ == "__main__":
    unittest.main()
