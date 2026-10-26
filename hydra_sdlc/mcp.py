"""Optional official-SDK stdio server. Host settings contain no workflow state."""
from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
from .runtime_identity import capture_runtime_identity


def controller_from_file(path):
    from .github import GitHub
    from .native import NativeController
    from .workspace import Workspace
    from .control import load_host_config, control_from_config

    cfg = load_host_config(path)
    def provider(key):
        value = cfg.get(key)
        if not value:
            return None
        module, factory = value.split(":", 1)
        return getattr(importlib.import_module(module), factory)()
    github = GitHub(user="openboa")
    workspace = Workspace(Path(cfg["workspace_root"]).expanduser(),
        lifecycle_provider=provider("lifecycle_provider"), storage_provider=provider("storage_provider"), user="openboa")
    def knowledge_revision():
        repo = cfg.get("knowledge_repo")
        if repo:
            return github.ref(repo, github.repository(repo)["default_branch"])
        return None
    operations = control_from_config(cfg)
    controller = NativeController(github, workspace, repos=cfg["repos"], host_alias=cfg["host_alias"],
        lock_path=Path(cfg.get("lock_path", "~/.local/share/hydra/host.lock")).expanduser(),
        knowledge_revision=knowledge_revision, operations=operations)
    controller.runtime_identity = capture_runtime_identity(cfg, operations)
    return controller


def create_server(controller, *, command_config_path=None, command_context_provider=None,
                  command_ended_provider=None, subscriptions=None):
    """Create the SDK server; command providers are trusted internal dependencies.

    Embedded callers have no grant by default. Standalone main supplies optional
    operation-specific protected profiles; request metadata never grants scope.
    """
    from mcp.server import MCPServer
    from mcp.server.mcpserver.tools import Tool
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp.types import CallToolResult, CallToolRequestParams, TextContent
    from pydantic import WithJsonSchema
    from typing import Annotated, Any
    from .control_commands import (AdmissionCallContext, InvalidAdmissionCommand, bounded_command, command_input_schema,
                                   execute_command_v1, parse_command_v1)
    from .native_context import load_sdk_profile, probe_context
    runtime = dict(getattr(controller, "runtime_identity", None) or capture_runtime_identity())
    profile = load_sdk_profile()

    async def command_result(command, ctx=None):
        # Both providers receive the actual SDK Context, never model-supplied
        # context/authority fields. The core re-reads the provider at each gate.
        def grant():
            if ctx is None or command_context_provider is None:
                return None
            selected = getattr(command_context_provider, 'for_command', None)
            value = (selected(ctx, command) if callable(selected)
                     else command_context_provider(ctx))
            # MCP is the native surface; a bridge grant cannot cross into it.
            return value if type(value) is AdmissionCallContext and value.surface == 'native' else None
        ended = (lambda: command_ended_provider(ctx)) if ctx is not None and command_ended_provider else None
        try:
            command = parse_command_v1(command)
            return await execute_command_v1(command_config_path, command,
                context_provider=grant, github=getattr(getattr(controller, 'runner', None), 'github', None),
                controller=controller, ended_provider=ended, unavailable_runtime=runtime)
        except InvalidAdmissionCommand:
            raise ToolError('invalid_command') from None
        except Exception:
            # The command cores preserve unknown effects in their typed replies.
            # An unexpected boundary failure must not disclose provider text.
            raise ToolError('command_unavailable') from None

    if profile.supported:
        async def hydra_command_v1(command, ctx=None) -> dict:
            """Apply one explicitly granted admission or bounded workflow command."""
            return await command_result(command, ctx)
        hydra_command_v1.__annotations__['ctx'] = profile.context_type
    else:
        async def hydra_command_v1(command) -> dict:
            """Apply a guarded command; unsupported caller context leaves writes inactive."""
            return await command_result(command)
    hydra_command_v1.__annotations__['command'] = Annotated[Any, WithJsonSchema(command_input_schema())]
    command_tool = Tool.from_function(hydra_command_v1)
    command_tool.parameters['additionalProperties'] = False
    server = MCPServer("Hydra", log_level="WARNING", tools=[command_tool], subscriptions=subscriptions)

    async def command_boundary(ctx, call_next):
        params = ctx.params
        if (ctx.method != 'tools/call' or type(params) is not dict
                or params.get('name') != 'hydra_command_v1'):
            return await call_next(ctx)
        try:
            bounded_command(params)
            if (not {'name', 'arguments'} <= set(params) or not set(params) <= {'name', 'arguments', '_meta'}
                    or type(params['arguments']) is not dict or set(params['arguments']) != {'command'}):
                raise InvalidAdmissionCommand()
            parse_command_v1(params['arguments']['command'])
            # Validate protocol fields here, before SDK errors can echo values.
            CallToolRequestParams.model_validate(params)
        except Exception:
            return CallToolResult(content=[TextContent(type='text', text='invalid_command')], is_error=True)
        try:
            return await call_next(ctx)
        except Exception:
            return CallToolResult(content=[TextContent(type='text', text='command_unavailable')], is_error=True)

    # Public SDK middleware API. Put this before SDK request-state processing,
    # while leaving every legacy tool and other protocol method unchanged.
    server.middleware.insert(0, command_boundary)

    def status_result(ctx=None):
        result = {"projects": controller.status(), "runtime": dict(runtime)}
        operations = getattr(getattr(controller, "runner", None), "operations", None)
        if operations is not None:
            from .operations import OperationDenied
            from .connection_profile import public_snapshot
            try:
                result["controls"] = public_snapshot(operations.snapshot())
            except OperationDenied as exc:
                result["controls"] = {"reason": exc.reason, "gate_status": "unknown"}
        result["native_context"] = probe_context(ctx, profile)
        return result

    if profile.supported:
        def hydra_status(ctx=None) -> dict:
            """Read registered GitHub work and waiting reasons without claiming it."""
            return status_result(ctx)
        # Real SDK type, not a postponed local annotation or model argument.
        hydra_status.__annotations__['ctx'] = profile.context_type
    else:
        def hydra_status() -> dict:
            """Read registered GitHub work and waiting reasons without claiming it."""
            return status_result()
    server.tool()(hydra_status)

    @server.tool()
    async def hydra_begin(issue_url: str) -> dict:
        """Reconcile a delegated Issue; prepare a native assignment or resume delivery."""
        return await controller.begin(issue_url)

    @server.tool()
    async def hydra_checkpoint(issue_url: str, attempt_id: str, step_id: str, head: str,
                               contract_revision: str, outcome: str, summary: str = "") -> dict:
        """Submit a native phase judgment. 'stopped' requires explicit task shutdown.

        Results are candidate_ready, failed, needs_decision or stopped. No model
        result substitutes for registered verification, PR reviews or GitHub CI.
        """
        return await controller.checkpoint(issue_url, attempt_id, step_id, head, contract_revision, outcome, summary)

    @server.tool()
    async def hydra_verify(issue_url: str, attempt_id: str, head: str, contract_revision: str) -> dict:
        """Continue registered verification and request independent review as needed."""
        return await controller.advance(issue_url, attempt_id, head, contract_revision)

    @server.tool()
    async def hydra_deliver(issue_url: str, attempt_id: str, head: str, contract_revision: str) -> dict:
        """Reconcile publication, real PR reviews/CI, exact-head merge and observation."""
        return await controller.advance(issue_url, attempt_id, head, contract_revision)

    return server


def main():
    parser = argparse.ArgumentParser(description="Hydra native Codex stdio MCP")
    parser.add_argument("--config", type=Path, default=Path.home() / ".config/hydra/host.toml")
    args = parser.parse_args()
    os.umask(0o077)
    # Protocol output belongs exclusively to the official SDK.
    from mcp.server.subscriptions import InMemorySubscriptionBus
    from .mcp_stdio import run_stdio
    from .native_admission import installation_admission_provider
    config_path = args.config.expanduser().absolute()
    subscriptions = InMemorySubscriptionBus()
    server = create_server(controller_from_file(config_path), command_config_path=config_path,
                           command_context_provider=installation_admission_provider(config_path),
                           subscriptions=subscriptions)
    run_stdio(server, subscriptions)


if __name__ == "__main__":
    main()
