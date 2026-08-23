#!/usr/bin/env python3
"""Validate the public OpenBoa Hydra marketplace and plugin contract."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


CONTRACT_VERSION = "0.1.0"
PLUGIN_NAME = "openboa-operations"
MARKETPLACE_NAME = "openboa-hydra"
MANAGED_START = f"<!-- openboa-operations:managed:start contract={CONTRACT_VERSION} -->"
MANAGED_END = "<!-- openboa-operations:managed:end -->"

REQUIRED_REFERENCES = (
    "doctrine.md",
    "operating-model.md",
    "workflow.md",
    "governance.md",
    "github.md",
)
REQUIRED_ASSETS = (
    "workspace-AGENTS.md",
    "repository-AGENTS.md",
    "goal-issue.md",
    "pull-request.md",
    "handoff.md",
    "governance-exception.md",
    "openboa-governance.yml",
)


def main() -> int:
    root = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else Path.cwd()
    errors = validate(root)
    if errors:
        print("Hydra contract validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Hydra contract validation passed: {root}")
    return 0


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    marketplace_path = root / ".agents" / "plugins" / "marketplace.json"
    plugin_root = root / "plugins" / PLUGIN_NAME
    manifest_path = plugin_root / ".codex-plugin" / "plugin.json"
    skill_root = plugin_root / "skills" / PLUGIN_NAME

    marketplace = load_json(marketplace_path, "marketplace.json", errors)
    if marketplace is not None:
        if marketplace.get("name") != MARKETPLACE_NAME:
            errors.append(f"marketplace name must be {MARKETPLACE_NAME}")
        entries = marketplace.get("plugins")
        if not isinstance(entries, list):
            errors.append("marketplace plugins must be an array")
        else:
            matching = [entry for entry in entries if isinstance(entry, dict) and entry.get("name") == PLUGIN_NAME]
            if len(matching) != 1:
                errors.append(f"marketplace must contain exactly one {PLUGIN_NAME} entry")
            elif matching[0].get("source", {}).get("path") != f"./plugins/{PLUGIN_NAME}":
                errors.append("marketplace plugin source path is incorrect")

    manifest = load_json(manifest_path, "plugin.json", errors)
    if manifest is not None:
        if manifest.get("name") != PLUGIN_NAME:
            errors.append(f"plugin name must be {PLUGIN_NAME}")
        if manifest.get("version") != CONTRACT_VERSION:
            errors.append(f"plugin version must be {CONTRACT_VERSION}")
        if manifest.get("license") != "Apache-2.0":
            errors.append("plugin license must be Apache-2.0")
        if manifest.get("skills") != "./skills/":
            errors.append("plugin skills path must be ./skills/")
        for forbidden in ("hooks", "mcpServers", "apps"):
            if forbidden in manifest:
                errors.append(f"plugin must not declare {forbidden} in v1")

    skill_md = skill_root / "SKILL.md"
    if not skill_md.is_file():
        errors.append("skill is missing SKILL.md")
    else:
        validate_skill_frontmatter(skill_md, errors)

    references_root = skill_root / "references"
    for name in REQUIRED_REFERENCES:
        if not (references_root / name).is_file():
            errors.append(f"missing skill reference: references/{name}")

    assets_root = skill_root / "assets"
    for name in REQUIRED_ASSETS:
        asset = assets_root / name
        if not asset.is_file():
            errors.append(f"missing skill asset: assets/{name}")

    for template_name in ("workspace-AGENTS.md", "repository-AGENTS.md"):
        template = assets_root / template_name
        if template.is_file():
            validate_managed_template(template, errors)

    governance = assets_root / "openboa-governance.yml"
    if governance.is_file():
        governance_text = governance.read_text(encoding="utf-8")
        for required_line in (
            "schema: 1",
            f'contract: "{CONTRACT_VERSION}"',
            "profile: public-standard",
            "control_plane: codex-github-connector",
            "scope_key: workspace/repository/goal",
            "account_is_not_authority: true",
            "cli_fallback: human-gated",
        ):
            if required_line not in governance_text:
                errors.append(f"governance profile is missing `{required_line}`")

    readme = root / "README.md"
    if not readme.is_file():
        errors.append("missing README.md")
    else:
        readme_text = readme.read_text(encoding="utf-8")
        for required_text in (
            "openboa-ai/hydra",
            "openboa-hydra",
            "openboa-operations",
        ):
            if required_text not in readme_text:
                errors.append(f"README.md is missing `{required_text}`")

    root_agents = root / "AGENTS.md"
    if not root_agents.is_file():
        errors.append("missing root AGENTS.md")
    else:
        validate_managed_template(root_agents, errors)

    for path in root.rglob("*.md"):
        if ".git" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            errors.append(f"unable to read {path.relative_to(root)}")
            continue
        if "[TODO:" in text:
            errors.append(f"placeholder remains in {path.relative_to(root)}")

    return errors


def load_json(path: Path, label: str, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file():
        errors.append(f"missing {label}")
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        errors.append(f"{label} must be valid JSON")
        return None
    if not isinstance(payload, dict):
        errors.append(f"{label} must contain an object")
        return None
    return payload


def validate_skill_frontmatter(path: Path, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        errors.append("skill SKILL.md must start with YAML frontmatter")
        return
    end = text.find("\n---", 4)
    if end < 0:
        errors.append("skill SKILL.md frontmatter is not closed")
        return
    frontmatter = text[4:end]
    for key in ("name", "description"):
        if not re.search(rf"^{re.escape(key)}:\s*\S+", frontmatter, flags=re.MULTILINE):
            errors.append(f"skill frontmatter is missing {key}")
    name_match = re.search(r"^name:\s*(\S+)", frontmatter, flags=re.MULTILINE)
    if name_match and name_match.group(1) != PLUGIN_NAME:
        errors.append(f"skill frontmatter name must be {PLUGIN_NAME}")


def validate_managed_template(path: Path, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    start_count = text.count(MANAGED_START)
    end_count = text.count(MANAGED_END)
    if start_count != 1 or end_count != 1:
        errors.append(f"{path.name} must contain exactly one managed marker pair")
        return
    if text.index(MANAGED_START) > text.index(MANAGED_END):
        errors.append(f"{path.name} managed markers are out of order")
    if "## Repository-local instructions" not in text and "## Workspace-local instructions" not in text:
        errors.append(f"{path.name} is missing its local instructions section")


if __name__ == "__main__":
    raise SystemExit(main())
