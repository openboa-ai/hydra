"""Resource hints cannot establish delivery; cleanup needs confirmed completion."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hydra_sdlc.runner import Runner
from hydra_sdlc.workspace import Workspace as RealWorkspace, WorkspaceWait
from test_project import BASE, HEAD, MERGE
from test_runner import GitHub, Workspace, complete_capabilities


class ResourceWorkspace(Workspace):
    def __init__(self, *args):
        super().__init__(*args)
        self.retired = []
        self.fail_retire = False

    def issue_numbers(self, repo):
        return [4]

    def completed(self, repo, n, branch, head, pr, merge):
        self.retired.append((repo, n, branch, head, pr, merge, self.gh.work["state"], self.gh.note["phase"]))
        if self.fail_retire:
            raise WorkspaceWait("busy_resource")
        return True


class CompletionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.gh = GitHub()
        self.ws = ResourceWorkspace(temporary.name, self.gh)
        p = patch("hydra_sdlc.runner.load_project", side_effect=lambda *a, **kw: copy.deepcopy(self.gh.cfg))
        p.start()
        self.addCleanup(p.stop)
        async def execute(assignment, **kw):
            if assignment["mode"] == "workspace_write":
                self.ws.dirty = True
            return {"status": "completed", "detail": {"result": {"outcome": "candidate_ready"}}}
        async def capabilities(*a):
            return complete_capabilities()
        self.runner = Runner(self.gh, self.ws, host_alias="test", execute=execute, capabilities=capabilities)

    async def deliver(self):
        for _ in range(4):
            result = await self.runner.step("example/product", 4)
            if result["action"] != "continue":
                return result
        self.fail("Fixture did not reach delivery or a bounded wait")

    async def test_retire_only_after_exact_merge_main_checks_close_and_record(self):
        result = await self.deliver()
        self.assertEqual(result["resource_status"], "retired")
        self.assertEqual(self.ws.retired[-1][-2:], ("closed", "completed"))
        self.assertTrue(self.gh.pr["merged"])

    async def test_failed_delivery_gates_never_retire(self):
        self.gh.remote_pending = True
        result = await self.deliver()
        self.assertEqual(result["reason"], "remote_delivery_gates")
        self.assertEqual(self.ws.retired, [])

    async def test_cleanup_failure_preserves_delivery_and_closed_discovery_retries(self):
        self.ws.fail_retire = True
        result = await self.deliver()
        self.assertEqual(result["resource_wait_reason"], "resource_cleanup_pending")
        self.assertEqual(self.gh.note["phase"], "completed")
        self.assertEqual(self.gh.work["state"], "closed")
        counts = {effect: len([w for w in self.gh.writes if w[0] == effect])
                  for effect in ["push", "pr", "merge", "close"]}
        self.gh.issues = lambda repo: []
        issues, reason = self.runner._issues("example/product")
        self.assertIsNone(reason)
        self.assertEqual([issue["number"] for issue in issues], [4])
        self.ws.fail_retire = False
        result = await self.runner.step("example/product", 4)
        self.assertEqual(result["resource_status"], "retired")
        for effect, count in counts.items():
            self.assertEqual(len([w for w in self.gh.writes if w[0] == effect]), count)

    async def test_closed_hint_without_authored_completion_is_not_adopted(self):
        self.gh.issues = lambda repo: []
        self.gh.work["state"] = "closed"
        issues, reason = self.runner._issues("example/product")
        self.assertEqual(issues, [])
        self.assertEqual(self.ws.retired, [])


class ProviderTests(unittest.TestCase):
    def test_completed_path_is_derived_and_receipt_is_required(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            class Provider:
                def issue_numbers(self, repo):
                    return [4, 4]
                def completed(self, *args):
                    calls.append(args)
                    return {"retired": True}
            root = Path(directory).resolve()
            ws = RealWorkspace(root, lifecycle_provider=Provider())
            self.assertEqual(ws.issue_numbers("example/product"), [4])
            self.assertTrue(ws.completed("example/product", 4, "hydra/issue-4", HEAD, 7, MERGE))
            self.assertEqual(calls[-1][-1], root / "example/product/issue-4")
            self.assertFalse((root / "example/product/issue-4").exists())
            ws.lifecycle_provider.completed = lambda *a: None
            with self.assertRaisesRegex(WorkspaceWait, "resource_completion_unconfirmed"):
                ws.completed("example/product", 4, "hydra/issue-4", HEAD, 7, MERGE)
            with self.assertRaises(WorkspaceWait):
                ws.completed("example/product", 4, "other/branch", HEAD, 7, MERGE)

    def test_malformed_discovery_is_not_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            class Provider:
                def issue_numbers(self, repo):
                    return [True, -1]
            ws = RealWorkspace(Path(directory), lifecycle_provider=Provider())
            with self.assertRaises(WorkspaceWait):
                ws.issue_numbers("example/product")
