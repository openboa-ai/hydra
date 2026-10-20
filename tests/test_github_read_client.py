"""Isolated protected policy reads retain deadlines, identity and actor checks."""

import base64
import hashlib
import json
import subprocess
import unittest
from unittest.mock import patch

from hydra_sdlc.github import GitHub, GitHubError
from hydra_sdlc.project import ProjectError, load_project
from test_project import BASE, BLOB, TOML


REPO = "example/product"
IDENTITY = {"id": 11, "login": "openboa"}
REPOSITORY = {"id": 123, "full_name": REPO, "default_branch": "main"}
TOKEN = "SYNTHETIC_PRIVATE_CANARY"


class ReadClientTests(unittest.TestCase):
    def response(self, path, *, content=TOML, permission="write"):
        if path == "user":
            return IDENTITY
        if path == f"repos/{REPO}":
            return REPOSITORY
        if path == f"repos/{REPO}/git/ref/heads/main":
            return {"object": {"sha": BASE}}
        if path == f"repos/{REPO}/contents/.hydra.toml?ref={BASE}":
            return {
                "type": "file", "encoding": "base64", "sha": BLOB,
                "content": base64.b64encode(content.encode()).decode(),
            }
        if path.startswith(f"repos/{REPO}/collaborators/") and path.endswith("/permission"):
            return {"user": {"login": path.split("/")[-2]}, "permission": permission}
        self.fail(f"Unexpected synthetic read: {path}")

    def fake_run(self, calls, now, *, content=TOML, permission="write"):
        def run(argv, **kwargs):
            calls.append((list(argv), dict(kwargs), now[0]))
            now[0] += 0.01
            if argv[1:3] == ["auth", "token"]:
                return subprocess.CompletedProcess(argv, 0, TOKEN + "\n", "")
            self.assertEqual(argv[1], "api")
            if "--method" in argv:
                self.assertEqual(argv[argv.index("--method") + 1], "GET")
            result = self.response(argv[-1], content=content, permission=permission)
            return subprocess.CompletedProcess(argv, 0, json.dumps(result), "")
        return run

    def test_default_client_rebinds_transport_and_does_not_share_budget_or_identity(self):
        now = [100.0]
        parent = GitHub()
        parent._authenticated_fingerprint = b"parent-observation"
        with patch("hydra_sdlc.github.time.monotonic", side_effect=lambda: now[0]):
            with parent.read_budget(seconds=30, requests=9) as outer:
                reader = parent.read_client()
                self.assertIs(reader.transport.__self__, reader)
                self.assertIs(reader.transport.__func__, GitHub._gh)
                self.assertIsNone(reader._authenticated_fingerprint)
                self.assertEqual(reader._read_budgets, [])
                self.assertIsNot(reader._read_budgets, parent._read_budgets)
                with reader.read_budget(seconds=15, requests=4, deadline=105.0):
                    reader._reserve_request()
                self.assertEqual(outer.remaining_requests, 9)
                self.assertEqual(parent._authenticated_fingerprint, b"parent-observation")
                self.assertEqual(len(parent._read_budgets), 1)
        self.assertEqual(parent._read_budgets, [])

    def test_current_injected_or_replaced_transport_is_preserved_without_gh_fallback(self):
        class Transport:
            def __init__(inner, truthy):
                inner.calls = []
                inner.truthy = truthy

            def __bool__(inner):
                return inner.truthy

            def __call__(inner, method, path, payload):
                inner.calls.append((method, path, payload))
                return REPOSITORY

        for replace_after_creation in (False, True):
            with self.subTest(replace_after_creation=replace_after_creation):
                transport = Transport(truthy=not replace_after_creation)
                parent = GitHub() if replace_after_creation else GitHub(transport=transport)
                if replace_after_creation:
                    parent.transport = transport
                reader = parent.read_client()
                self.assertIs(reader.transport, transport)
                self.assertEqual(reader._read_budgets, [])
                self.assertIsNone(reader._authenticated_fingerprint)
                with patch("hydra_sdlc.github.subprocess.run",
                           side_effect=AssertionError("must not fall back to gh")):
                    self.assertEqual(reader.repository(REPO), REPOSITORY)
                self.assertEqual(transport.calls, [("GET", f"/repos/{REPO}", None)])

    def test_default_transport_authenticates_fresh_and_full_project_reads_fit_actor_budget(self):
        now, calls = [100.0], []
        parent = GitHub()
        parent._authenticated_fingerprint = hashlib.sha256(TOKEN.encode()).digest()
        with patch("hydra_sdlc.github.time.monotonic", side_effect=lambda: now[0]), \
             patch("hydra_sdlc.github.subprocess.run", side_effect=self.fake_run(calls, now)):
            with parent.read_budget(seconds=30, requests=9) as outer:
                reader = parent.read_client()
                with reader.read_budget(seconds=15, requests=4 + 2, deadline=105.0) as budget:
                    observed = load_project(reader, REPO)
                    self.assertEqual(budget.remaining_requests, 0)
                self.assertEqual(outer.remaining_requests, 9)
                self.assertEqual(parent._authenticated_fingerprint,
                                 hashlib.sha256(TOKEN.encode()).digest())
        self.assertEqual(observed["actor_permissions"], {"openboa": "write", "operator": "write"})
        api_calls = [(argv, options, started) for argv, options, started in calls if argv[1] == "api"]
        self.assertEqual(len(api_calls), 6)
        self.assertEqual(sum(argv[-1] == "user" for argv, _, _ in api_calls), 1)
        for argv, options, started in calls:
            self.assertGreater(options["timeout"], 0)
            self.assertLessEqual(options["timeout"], 105.0 - started)
            self.assertNotIn(TOKEN, argv)
        self.assertEqual(reader._read_budgets, [])

    def test_four_requests_do_not_silently_skip_actor_permissions(self):
        now, calls = [100.0], []
        reader = GitHub().read_client()
        with patch("hydra_sdlc.github.time.monotonic", side_effect=lambda: now[0]), \
             patch("hydra_sdlc.github.subprocess.run", side_effect=self.fake_run(calls, now)):
            with reader.read_budget(seconds=15, requests=4, deadline=105.0):
                with self.assertRaisesRegex(GitHubError, "read budget exhausted"):
                    load_project(reader, REPO)
        self.assertFalse(any("/collaborators/" in argv[-1] for argv, _, _ in calls))

    def test_permission_revocation_still_fails_the_full_validator(self):
        now, calls = [100.0], []
        reader = GitHub().read_client()
        with patch("hydra_sdlc.github.time.monotonic", side_effect=lambda: now[0]), \
             patch("hydra_sdlc.github.subprocess.run",
                   side_effect=self.fake_run(calls, now, permission="read")):
            with reader.read_budget(seconds=15, requests=6, deadline=105.0):
                with self.assertRaisesRegex(ProjectError, "not a repository writer"):
                    load_project(reader, REPO)
        self.assertEqual(sum("/collaborators/" in argv[-1] for argv, _, _ in calls), 1)

    def test_new_actor_cannot_expand_the_parent_pinned_request_budget(self):
        now, calls = [100.0], []
        expanded = TOML.replace('["openboa", "operator"]', '["openboa", "operator", "third"]', 1)
        reader = GitHub().read_client()
        with patch("hydra_sdlc.github.time.monotonic", side_effect=lambda: now[0]), \
             patch("hydra_sdlc.github.subprocess.run",
                   side_effect=self.fake_run(calls, now, content=expanded)):
            with reader.read_budget(seconds=15, requests=4 + 2, deadline=105.0):
                with self.assertRaisesRegex(GitHubError, "read budget exhausted"):
                    load_project(reader, REPO)
        self.assertFalse(any("/collaborators/third/" in argv[-1] for argv, _, _ in calls))

    def test_expiry_after_token_prevents_identity_and_api_reads(self):
        now, calls = [100.0], []
        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            self.assertEqual(argv[1:3], ["auth", "token"])
            self.assertEqual(kwargs["timeout"], 0.5)
            now[0] = 100.5
            return subprocess.CompletedProcess(argv, 0, TOKEN, "")
        with patch("hydra_sdlc.github.time.monotonic", side_effect=lambda: now[0]), \
             patch("hydra_sdlc.github.subprocess.run", side_effect=run):
            reader = GitHub().read_client()
            with reader.read_budget(seconds=15, requests=4, deadline=100.5):
                with self.assertRaisesRegex(GitHubError, "read budget exhausted") as caught:
                    reader.repository(REPO)
        self.assertEqual(len(calls), 1)
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertIsNone(reader._authenticated_fingerprint)

    def test_late_injected_read_result_is_not_returned_as_fresh_success(self):
        now, calls = [100.0], []
        def transport(method, path, payload):
            calls.append((method, path))
            now[0] = 101.0
            return REPOSITORY
        reader = GitHub(transport=transport).read_client()
        with patch("hydra_sdlc.github.time.monotonic", side_effect=lambda: now[0]):
            with reader.read_budget(seconds=15, requests=4, deadline=101.0):
                with self.assertRaisesRegex(GitHubError, "read budget exhausted"):
                    reader.repository(REPO)
        self.assertEqual(calls, [("GET", f"/repos/{REPO}")])

    def test_absolute_deadline_and_nested_deadline_never_extend(self):
        now = [100.0]
        reader = GitHub(transport=lambda *_: REPOSITORY).read_client()
        with patch("hydra_sdlc.github.time.monotonic", side_effect=lambda: now[0]):
            with reader.read_budget(seconds=15, requests=8, deadline=102.0) as outer:
                now[0] = 101.0
                with reader.read_budget(seconds=15, requests=4, deadline=105.0) as inner:
                    self.assertEqual((outer.deadline, inner.deadline), (102.0, 102.0))
                    self.assertEqual(reader._request_timeout(45), 1.0)
                now[0] = 102.0
                with self.assertRaisesRegex(GitHubError, "read budget exhausted"):
                    reader.repository(REPO)
            with reader.read_budget(seconds=2, requests=1, deadline=110.0) as shorter:
                self.assertEqual(shorter.deadline, 104.0)
        self.assertEqual(reader._read_budgets, [])

    def test_invalid_absolute_deadline_does_not_change_existing_budget(self):
        reader = GitHub().read_client()
        with reader.read_budget(seconds=15, requests=4) as outer:
            for deadline in (True, False, "100", float("nan"), float("inf"), -float("inf"), []):
                with self.subTest(deadline=deadline):
                    with self.assertRaisesRegex(GitHubError, "Invalid GitHub read budget"):
                        with reader.read_budget(seconds=15, requests=4, deadline=deadline):
                            self.fail("invalid deadline must not enter the scope")
                    self.assertEqual(reader._read_budgets, [outer])


if __name__ == "__main__":
    unittest.main()
