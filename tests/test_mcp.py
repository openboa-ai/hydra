"""Real official-SDK initialization and subprocess stdio, without model calls."""
import asyncio
import copy
from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hydra_sdlc.mcp import create_server


class ControllerFixture:
    def status(self):
        return [{"repository": "example/product", "wait_reason": "product_decision",
                 "resume_hint": "decision_resolved"}]

    async def begin(self, url):
        if url != "https://github.com/example/product/issues/4":
            raise ValueError("Issue outside installed allowlist")
        return {"action": "waiting", "reason": "human_decision"}

    async def checkpoint(self, *args):
        return {"action": "waiting", "reason": "stop_requested"}

    async def advance(self, *args):
        return {"action": "waiting", "reason": "ci_pending"}


@unittest.skipUnless(importlib.util.find_spec("mcp"), "optional pinned MCP SDK not installed")
class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_or_invalid_context_export_keeps_legacy_server_usable(self):
        from mcp import Client
        import mcp.server.mcpserver as sdk
        context = sdk.Context
        for replacement in (None, 'missing-export'):
            with self.subTest(replacement=replacement):
                try:
                    if replacement == 'missing-export':
                        del sdk.Context
                    else:
                        sdk.Context = replacement
                    server = create_server(ControllerFixture())
                finally:
                    sdk.Context = context
                async with Client(server) as client:
                    listed = (await client.list_tools()).tools
                    self.assertEqual(len(listed), 6)
                    status = next(t for t in listed if t.name == 'hydra_status')
                    self.assertEqual(status.input_schema.get('properties', {}), {})
                    result = await client.call_tool('hydra_status', {})
                    self.assertFalse(result.is_error)
                    data = result.structured_content or json.loads(result.content[0].text)
                    self.assertEqual(data['projects'], ControllerFixture().status())
                    self.assertEqual(data['native_context']['input_required_sdk'], 'unknown')
                    self.assertIsNone(data['native_context']['protocol_version'])

    async def test_diagnostic_failure_isolated_but_controller_failure_preserved(self):
        from mcp import Client
        from mcp.server.mcpserver import Context
        from hydra_sdlc.native_context import read_probe
        controller = ControllerFixture()
        server = create_server(controller)
        async with Client(server) as client:
            def inaccessible(_):
                raise RuntimeError('SYNTHETIC_PRIVATE_CANARY')
            with patch.object(Context, 'client_capabilities', property(inaccessible)):
                result = await client.call_tool('hydra_status', {})
            self.assertFalse(result.is_error)
            data = result.structured_content or json.loads(result.content[0].text)
            self.assertEqual(data['projects'], controller.status())
            self.assertEqual(read_probe(data)['form_elicitation'], 'unknown')
            self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', str(result.content))
            if result.structured_content and result.content:
                self.assertEqual(result.structured_content, json.loads(result.content[0].text))
            with patch.object(controller, 'status', side_effect=ValueError('status unavailable')), self.assertLogs(level='ERROR'):
                failure = await client.call_tool('hydra_status', {})
            self.assertTrue(failure.is_error)

    async def test_profile_is_inspected_only_at_startup(self):
        from mcp import Client
        from hydra_sdlc.native_context import load_sdk_profile
        with patch('hydra_sdlc.native_context.load_sdk_profile', wraps=load_sdk_profile) as profile:
            server = create_server(ControllerFixture())
            async with Client(server) as client:
                for _ in range(2):
                    result = await client.call_tool('hydra_status', {})
                    self.assertFalse(result.is_error)
            profile.assert_called_once_with()

    async def test_status_exposes_request_diagnostic_without_claiming_caller(self):
        from mcp import Client
        async with Client(create_server(ControllerFixture())) as client:
            result = await client.call_tool('hydra_status', {})
            self.assertFalse(result.is_error)
            data = result.structured_content or json.loads(result.content[0].text)
            self.assertIn('native_context', data)
            self.assertEqual(data['native_context'], {
                'schema_version': 1, 'protocol_version': '2026-07-28',
                'request_channel': 'unavailable', 'form_elicitation': 'not_declared',
                'input_required_sdk': 'present', 'input_required_client': 'unverified',
                'caller_task_binding': 'unverified',
            })
            status = next(t for t in (await client.list_tools()).tools if t.name == 'hydra_status')
            self.assertEqual(status.input_schema.get('properties', {}), {})

    async def test_inprocess_schema_and_refusal(self):
        from mcp import Client
        async with Client(create_server(ControllerFixture())) as client:
            listed = await client.list_tools()
            self.assertEqual({tool.name for tool in listed.tools},
                {"hydra_status", "hydra_begin", "hydra_checkpoint", "hydra_verify", "hydra_deliver", "hydra_command_v1"})
            checkpoint = next(tool for tool in listed.tools if tool.name == "hydra_checkpoint")
            self.assertIn("step_id", checkpoint.input_schema["required"])
            with self.assertLogs(level="ERROR"):
                result = await client.call_tool("hydra_begin", {"issue_url": "https://github.com/foreign/product/issues/4"})
            self.assertTrue(result.is_error)

    async def test_server_captures_runtime_once_and_status_never_rehashes_package(self):
        from mcp import Client
        from hydra_sdlc.runtime_identity import capture_runtime_identity
        expected = capture_runtime_identity()
        with patch('hydra_sdlc.mcp.capture_runtime_identity', return_value=expected.copy()) as capture:
            server = create_server(ControllerFixture())
            capture.assert_called_once_with()
            capture.side_effect = AssertionError('runtime identity recaptured after startup')
            with patch('hydra_sdlc.runtime_identity._digest_sources', side_effect=AssertionError('package reread')) as digest:
                async with Client(server) as client:
                    for _ in range(2):
                        result = await client.call_tool('hydra_status', {})
                        self.assertFalse(result.is_error)
                        data = result.structured_content or json.loads(result.content[0].text)
                        self.assertEqual(data['runtime'], expected)
                        self.assertEqual(data['projects'], ControllerFixture().status())
                    self.assertEqual(len((await client.list_tools()).tools), 6)
                digest.assert_not_called()
            capture.assert_called_once_with()

    async def test_server_keeps_configured_startup_identity_when_controller_metadata_changes(self):
        from mcp import Client
        from hydra_sdlc.runtime_identity import capture_runtime_identity
        controller = ControllerFixture()
        controller.runtime_identity = {**capture_runtime_identity(), 'config_digest': 'a' * 64,
                                       'control_binding_digest': 'b' * 64}
        expected = controller.runtime_identity.copy()
        with patch('hydra_sdlc.mcp.capture_runtime_identity', side_effect=AssertionError('startup identity replaced')) as capture:
            server = create_server(controller)
            controller.runtime_identity['config_digest'] = 'c' * 64
            async with Client(server) as client:
                result = await client.call_tool('hydra_status', {})
                self.assertFalse(result.is_error)
                data = result.structured_content or json.loads(result.content[0].text)
                self.assertEqual(data['runtime'], expected)
            capture.assert_not_called()

    async def test_configured_mcp_cli_and_control_report_the_same_identity(self):
        from mcp import Client
        from hydra_sdlc.cli import operate, parser
        from hydra_sdlc.control import control_result, load_host_config
        from hydra_sdlc.mcp import controller_from_file
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config = root / 'host.toml'
            config.write_text('repos=["example/product"]\nhost_alias="test"\nworkspace_root="work"\n'
                              'lock_path="locks/host.lock"\n')
            config.chmod(0o600)
            with patch('hydra_sdlc.github.GitHub'), patch('hydra_sdlc.workspace.Workspace'):
                controller = controller_from_file(config)
            with patch.object(controller, 'status', return_value=ControllerFixture().status()), \
                    patch('hydra_sdlc.mcp.capture_runtime_identity', side_effect=AssertionError('identity recaptured')), \
                    patch('hydra_sdlc.runtime_identity._digest_sources', side_effect=AssertionError('package reread')), \
                    patch('hydra_sdlc.github.GitHub', side_effect=AssertionError('GitHub used')), \
                    patch('hydra_sdlc.workspace.Workspace', side_effect=AssertionError('workspace acquired')), \
                    patch('hydra_sdlc.control.observe_coordinator', return_value={'state': 'absent'}), \
                    patch('hydra_sdlc.control.residual_workers', return_value=[]):
                cli_identity = await operate(parser().parse_args(['identity', '--config', str(config)]), emit=lambda _: None)
                local = control_result(load_host_config(config))
                async with Client(create_server(controller)) as client:
                    result = await client.call_tool('hydra_status', {})
                    self.assertFalse(result.is_error)
                    data = result.structured_content or json.loads(result.content[0].text)
            self.assertEqual(data['runtime'], cli_identity)
            self.assertEqual(data['runtime'], local['runtime'])
            self.assertEqual(data['controls']['revision'], 0)
            for key in ('config_digest', 'control_binding_digest'):
                self.assertRegex(data['runtime'][key], r'\A[0-9a-f]{64}\Z')
            self.assertEqual(list(root.iterdir()), [config])
            self.assertNotIn(str(root), json.dumps(data['runtime']))

    async def test_real_stdio_initialize_list_and_read(self):
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters
        params = StdioServerParameters(command=sys.executable,
            args=[str(Path(__file__).resolve()), "--fixture"],
            cwd=str(Path(__file__).resolve().parents[1]))
        async with Client(params) as client:
            self.assertEqual(len((await client.list_tools()).tools), 6)
            result = await client.call_tool("hydra_status", {})
            self.assertFalse(result.is_error)
            data = result.structured_content or json.loads(result.content[0].text)
            self.assertEqual(data["projects"][0]["wait_reason"], "product_decision")
            self.assertEqual(data["projects"][0]["resume_hint"], "decision_resolved")
            self.assertEqual(set(data['runtime']), {'identity_schema', 'package', 'version', 'code_digest',
                'code_digest_scope', 'config_digest', 'control_binding_digest', 'identity_reason'})
            self.assertEqual(data['runtime']['identity_schema'], 1)
            self.assertEqual(data['runtime']['package'], 'openboa-hydra-sdlc')
            from hydra_sdlc.native_context import read_probe
            self.assertIsNotNone(read_probe(data))
            self.assertEqual(data['native_context']['caller_task_binding'], 'unverified')
            self.assertIsNone(data['runtime']['config_digest'])
            self.assertIsNone(data['runtime']['control_binding_digest'])
            again = await client.call_tool('hydra_status', {})
            self.assertFalse(again.is_error)
            repeated = again.structured_content or json.loads(again.content[0].text)
            self.assertEqual(repeated['runtime'], data['runtime'])


@unittest.skipUnless(importlib.util.find_spec("mcp"), "optional pinned MCP SDK not installed")
class OperatingGateProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_native_controller_observes_pause_and_preserves_exact_stopped_cleanup(self):
        from mcp import Client
        from hydra_sdlc.native import NativeController
        from hydra_sdlc.operations import OperatingControl
        from test_operation_integration import CheckpointGitHub, OwnedWorkspace

        repo = "example/product"
        url = f"https://github.com/{repo}/issues/4"
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory).resolve()
            lock = root / "host.lock"
            controls = OperatingControl(lock, [repo])
            controls.set_mode("start")
            github = CheckpointGitHub()
            workspace = OwnedWorkspace(root, github)
            controller = NativeController(github, workspace, repos=[repo], host_alias="test",
                                          lock_path=lock, operations=controls)
            for name in ("hydra_sdlc.runner.load_project", "hydra_sdlc.native.load_project"):
                stack.enter_context(patch(name, side_effect=lambda gh, repo, **kw: copy.deepcopy(gh.cfg)))
            stack.enter_context(patch("hydra_sdlc.native.residual_workers", return_value=[]))
            model = stack.enter_context(patch("hydra_sdlc.codex.execute"))
            capabilities = stack.enter_context(patch("hydra_sdlc.codex.capabilities"))

            async with Client(create_server(controller)) as client:
                async def call(name, arguments):
                    result = await asyncio.wait_for(client.call_tool(name, arguments), timeout=10)
                    self.assertFalse(result.is_error, result.content)
                    return result.structured_content or json.loads(result.content[0].text)

                review = await call("hydra_begin", {"issue_url": url})
                self.assertEqual(review["action"], "native_task")
                review_identity = {key: review[key] for key in
                                   ("attempt_id", "step_id", "head", "contract_revision")}
                assignment = await call("hydra_checkpoint", {
                    "issue_url": url, **review_identity, "outcome": "candidate_ready"})
                self.assertEqual(assignment["mode"], "workspace_write")
                identity = {key: assignment[key] for key in
                            ("attempt_id", "step_id", "head", "contract_revision")}
                advance = {key: identity[key] for key in ("attempt_id", "head", "contract_revision")}
                running = await call("hydra_status", {})
                self.assertEqual(running["controls"]["global_mode"], "running")
                # No task is executed by this fixture. Its owned edit stands for
                # work whose shutdown the exact stopped checkpoint confirms.
                workspace.dirty = True
                ticket, progress = lock.read_bytes(), copy.deepcopy(github.note)
                writes, prepared = list(github.writes), list(workspace.prepared_recovery)
                OperatingControl(lock, [repo]).set_mode("pause")
                paused = controls.snapshot()

                calls = [("hydra_begin", {"issue_url": url})]
                calls.extend(("hydra_checkpoint", {"issue_url": url, **identity, "outcome": outcome})
                             for outcome in ("candidate_ready", "failed", "needs_decision"))
                calls.extend((name, {"issue_url": url, **advance})
                             for name in ("hydra_verify", "hydra_deliver"))
                with ExitStack() as blocked:
                    effects = [blocked.enter_context(patch.object(workspace, method)) for method in
                               ("prepare", "existing", "checkpoint", "fetch_base", "verify", "publish")]
                    effects.extend(blocked.enter_context(patch.object(github, method)) for method in
                                   ("progress", "record", "record_checkpoint"))
                    effects.append(blocked.enter_context(patch("hydra_sdlc.native.coordinator_lock")))
                    for name, arguments in calls:
                        with self.subTest(tool=name, outcome=arguments.get("outcome")):
                            result = await call(name, arguments)
                            self.assertEqual(result["action"], "waiting")
                            self.assertEqual(result["reason"], "host_paused")
                    for effect in effects:
                        effect.assert_not_called()
                self.assertEqual(github.note, progress)
                self.assertEqual(github.writes, writes)
                self.assertEqual(workspace.prepared_recovery, prepared)
                self.assertTrue(workspace.dirty)
                self.assertEqual(lock.read_bytes(), ticket)

                status = await call("hydra_status", {})
                self.assertEqual(status["controls"], paused)
                self.assertGreater(paused["revision"], running["controls"]["revision"])
                self.assertEqual(status["projects"][0]["wait_reason"], "host_paused")
                self.assertEqual(status["projects"][0]["progress"]["native_step"], identity["step_id"])
                with self.assertLogs(level="ERROR"):
                    stale = await asyncio.wait_for(client.call_tool("hydra_checkpoint", {
                        "issue_url": url, **identity, "head": "e" * 40, "outcome": "stopped"}), timeout=10)
                self.assertTrue(stale.is_error)
                self.assertEqual(lock.read_bytes(), ticket)
                self.assertEqual(github.note, progress)
                self.assertEqual(github.writes, writes)
                self.assertTrue(workspace.dirty)

                stopped = await call("hydra_checkpoint", {"issue_url": url, **identity, "outcome": "stopped"})
                self.assertEqual(stopped["reason"], "stop_requested")
                self.assertEqual(lock.read_bytes(), b"")
                self.assertFalse(workspace.dirty)
                self.assertEqual(workspace.existing_calls, 1)
                self.assertEqual(workspace.prepared_recovery, prepared)
                self.assertTrue(github.cleanup_records)
                self.assertTrue(all(write[0] == "record" for write in github.writes[len(writes):]))
                self.assertIsNone(github.branch)
                self.assertIsNone(github.pr)
                self.assertEqual(controls.snapshot(), paused)
                self.assertEqual((await call("hydra_begin", {"issue_url": url}))["reason"], "host_paused")
                model.assert_not_called()
                capabilities.assert_not_called()


if __name__ == "__main__":
    if sys.argv[1:] == ["--fixture"]:
        create_server(ControllerFixture()).run(transport="stdio")
    else:
        unittest.main()
