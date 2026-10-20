"""Parent-bound policy snapshots and fresh isolated execution preflights."""

import copy
from contextlib import nullcontext
from contextvars import Context
import time
import unittest
from unittest.mock import patch

from hydra_sdlc.operations import OperationDenied
from hydra_sdlc.runner import Runner
from test_runner import GitHub as FixtureGitHub


REPO = "example/product"


class DispatchPolicyCaptureTests(unittest.TestCase):
    def setUp(self):
        self.github = FixtureGitHub()
        self.github.cfg.update(version=2, work_source="legacy_issue", planning={"source": "issue"})
        self.runner = Runner(self.github, object(), host_alias="host",
                             execute=None, capabilities=None)

    def test_captured_repo_and_nested_policy_survive_empty_context_and_parent_rebinding(self):
        original = copy.deepcopy(self.github.cfg)
        bound = copy.deepcopy(original)
        self.runner._bind_policy(REPO, bound)
        prepared = self.runner._dispatch_preflight(REPO)
        bound["planning"]["source"] = "github_project"
        bound["authorized_actors"].append("not-in-original")
        self.runner._bind_policy("other/product", {"version": 2, "work_source": "github_native"})
        seen = []

        def load(reader, repo):
            self.assertIsNone(self.runner._policy_scope.get())
            self.assertIsNot(reader, self.github)
            self.assertEqual(repo, REPO)
            seen.append(reader)
            return copy.deepcopy(original)

        deadline = time.monotonic() + 10
        with patch("hydra_sdlc.runner.load_project", side_effect=load), \
             patch.object(FixtureGitHub, "read_budget", autospec=True,
                          return_value=nullcontext()) as budget:
            self.assertIsNone(Context().run(prepared.callback, deadline))
        self.assertEqual(len(seen), 1)
        self.assertEqual(budget.call_args.kwargs["deadline"], deadline)
        self.assertEqual(budget.call_args.kwargs["requests"], 4 + len(original["authorized_actors"]))
        self.assertLessEqual(budget.call_args.kwargs["seconds"], 15)

    def test_each_call_gets_fresh_reader_and_observes_later_policy_drift(self):
        original = copy.deepcopy(self.github.cfg)
        self.runner._bind_policy(REPO, original)
        prepared = self.runner._dispatch_preflight(REPO)
        readers = []

        def load(reader, repo):
            self.assertEqual(repo, REPO)
            self.assertIsNot(reader, self.github)
            readers.append(reader)
            return copy.deepcopy(reader.cfg)

        with patch("hydra_sdlc.runner.load_project", side_effect=load):
            self.assertIsNone(Context().run(prepared.callback, time.monotonic() + 10))
            self.github.cfg = {**original, "blob_sha": "d" * 40}
            with self.assertRaisesRegex(OperationDenied, "policy_changed"):
                Context().run(prepared.callback, time.monotonic() + 10)
        self.assertEqual(len(readers), 2)
        self.assertIsNot(readers[0], readers[1])

    def test_missing_or_wrong_parent_binding_denies_before_observation(self):
        for binding in (None, ("other/product", self.github.cfg)):
            with self.subTest(binding=binding):
                self.runner._policy_scope.set(binding)
                with patch("hydra_sdlc.runner.load_project",
                           side_effect=AssertionError("no observation without parent binding")):
                    with self.assertRaisesRegex(OperationDenied, "project_policy_unbound"):
                        self.runner._dispatch_preflight(REPO)

    def test_absent_reader_factory_never_falls_back_to_parent_client(self):
        self.runner._bind_policy(REPO, copy.deepcopy(self.github.cfg))
        self.runner.github = object()
        with patch("hydra_sdlc.runner.load_project",
                   side_effect=AssertionError("unsupported reader must not share parent")):
            with self.assertRaises(OperationDenied):
                self.runner._dispatch_preflight(REPO)

    def test_observation_failure_is_bounded_without_private_exception_text(self):
        self.runner._bind_policy(REPO, copy.deepcopy(self.github.cfg))
        prepared = self.runner._dispatch_preflight(REPO)
        with patch("hydra_sdlc.runner.load_project",
                   side_effect=RuntimeError("SYNTHETIC_PRIVATE_CANARY")):
            with self.assertRaises(OperationDenied) as caught:
                Context().run(prepared.callback, time.monotonic() + 10)
        self.assertEqual(caught.exception.reason, "project_contract_unavailable")
        self.assertNotIn("SYNTHETIC_PRIVATE_CANARY", str(caught.exception))

    def test_completion_only_proof_is_not_a_new_dispatch_permission(self):
        self.runner._bind_policy(REPO, {**self.github.cfg, "_completion_only": True})
        with patch("hydra_sdlc.runner.load_project",
                   side_effect=AssertionError("completion does not dispatch")):
            with self.assertRaises(OperationDenied):
                self.runner._dispatch_preflight(REPO)
