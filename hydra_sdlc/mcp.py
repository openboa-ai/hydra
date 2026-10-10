"""Optional official-SDK stdio server. Host settings contain no workflow state."""
from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import re
import tomllib


def controller_from_file(path):
    from .github import GitHub
    from .native import NativeController
    from .workspace import Workspace

    with Path(path).expanduser().open("rb") as source:
        cfg = tomllib.load(source)
    allowed = {"repos", "host_alias", "workspace_root", "lock_path", "lifecycle_provider", "storage_provider", "knowledge_repo", "runtime_python"}
    if set(cfg) - allowed or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", cfg.get("host_alias", "")):
        raise ValueError("Invalid installed host settings")
    if not isinstance(cfg.get("repos"), list) or not cfg["repos"]:
        raise ValueError("Installed repository allowlist missing")
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
    return NativeController(github, workspace, repos=cfg["repos"], host_alias=cfg["host_alias"],
        lock_path=Path(cfg.get("lock_path", "~/.local/share/hydra/host.lock")).expanduser(),
        knowledge_revision=knowledge_revision)


def create_server(controller):
    from mcp.server import MCPServer
    server = MCPServer("Hydra", log_level="WARNING")

    @server.tool()
    def hydra_status() -> dict:
        """Read registered GitHub work and waiting reasons without claiming it."""
        return {"projects": controller.status()}

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
    create_server(controller_from_file(args.config)).run(transport="stdio")


if __name__ == "__main__":
    main()
