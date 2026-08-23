#!/usr/bin/env python3
"""Validate the public OpenBoa Hydra marketplace and plugin package."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


VERSION = "0.1.0"
PLUGIN_NAME = "openboa-ai-native-sdlc"
MARKETPLACE_NAME = "openboa-hydra"
MANAGED_START = f"<!-- openboa-ai-native-sdlc:managed:start version={VERSION} -->"
MANAGED_END = "<!-- openboa-ai-native-sdlc:managed:end -->"
EXPECTED_SKILLS = {
    "openboa-delegate-work",
    "openboa-lead-work",
    "openboa-review-work",
    "openboa-deliver-work",
    "openboa-improve-system",
    "openboa-adopt-sdlc",
}
REQUIRED_REFERENCES = {
    "doctrine.md",
    "operating-model.md",
    "workflow.md",
    "governance.md",
    "codex.md",
    "github.md",
    "evals.md",
}
REQUIRED_ASSETS = {
    "workspace-AGENTS.md",
    "repository-AGENTS.md",
    "goal-issue.md",
    "task-issue.md",
    "pull-request.md",
    "handoff.md",
}


def main() -> int:
    root = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else Path.cwd()
    errors = validate(root)
    if errors:
        print("Hydra validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Hydra validation passed: {root}")
    return 0


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    marketplace_path = root / ".agents" / "plugins" / "marketplace.json"
    plugin_root = root / "plugins" / PLUGIN_NAME
    manifest_path = plugin_root / ".codex-plugin" / "plugin.json"
    skills_root = plugin_root / "skills"
    references_root = plugin_root / "references"
    assets_root = plugin_root / "assets"

    if (root / "plugins" / "openboa-operations").exists():
        errors.append("legacy plugins/openboa-operations directory must be removed")

    marketplace = load_json(marketplace_path, "marketplace.json", errors)
    if marketplace is not None:
        if marketplace.get("name") != MARKETPLACE_NAME:
            errors.append(f"marketplace name must be {MARKETPLACE_NAME}")
        if marketplace.get("interface", {}).get("displayName") != "OpenBoa Hydra":
            errors.append("marketplace display name must be OpenBoa Hydra")
        entries = marketplace.get("plugins")
        if not isinstance(entries, list) or len(entries) != 1:
            errors.append(f"marketplace must contain exactly one {PLUGIN_NAME} entry")
        elif not isinstance(entries[0], dict):
            errors.append("marketplace plugin entry must be an object")
        else:
            entry = entries[0]
            if entry.get("name") != PLUGIN_NAME:
                errors.append(f"marketplace plugin name must be {PLUGIN_NAME}")
            if entry.get("source") != {"source": "local", "path": f"./plugins/{PLUGIN_NAME}"}:
                errors.append("marketplace plugin source is incorrect")
            policy = entry.get("policy")
            if policy != {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}:
                errors.append("marketplace plugin policy is incorrect")
            if not isinstance(entry.get("category"), str) or not entry["category"]:
                errors.append("marketplace plugin category is required")

    manifest = load_json(manifest_path, "plugin.json", errors)
    if manifest is not None:
        if manifest.get("name") != PLUGIN_NAME:
            errors.append(f"plugin name must be {PLUGIN_NAME}")
        if manifest.get("version") != VERSION:
            errors.append(f"plugin version must be {VERSION}")
        if manifest.get("license") != "Apache-2.0":
            errors.append("plugin license must be Apache-2.0")
        if manifest.get("skills") != "./skills/":
            errors.append("plugin skills path must be ./skills/")
        prompts = manifest.get("interface", {}).get("defaultPrompt")
        if not isinstance(prompts, list) or not 1 <= len(prompts) <= 3:
            errors.append("plugin defaultPrompt must contain one to three prompts")
        for forbidden in ("hooks", "mcpServers", "apps"):
            if forbidden in manifest:
                errors.append(f"plugin must not declare {forbidden} in v0.1")

    if not skills_root.is_dir():
        errors.append("plugin skills directory is missing")
    else:
        actual_skills = {path.name for path in skills_root.iterdir() if path.is_dir()}
        if actual_skills != EXPECTED_SKILLS:
            errors.append(
                "plugin skills must be exactly: " + ", ".join(sorted(EXPECTED_SKILLS))
            )
        for name in sorted(EXPECTED_SKILLS):
            skill_root = skills_root / name
            validate_skill(skill_root, name, errors)

    for name in sorted(REQUIRED_REFERENCES):
        validate_nonempty(references_root / name, f"references/{name}", errors)

    doctrine_path = references_root / "doctrine.md"
    if doctrine_path.is_file():
        doctrine = doctrine_path.read_text(encoding="utf-8")
        for required_text in (
            "organization member",
            "OpenBoa's accountable human is `SonSangjoon`",
            "Methods are replaceable",
        ):
            if required_text not in doctrine:
                errors.append(f"doctrine.md is missing `{required_text}`")
        if "**Contract:**" in doctrine:
            errors.append("doctrine.md must not version stable purpose as a workflow contract")
    for name in sorted(REQUIRED_ASSETS):
        validate_nonempty(assets_root / name, f"assets/{name}", errors)

    for name in ("goal-issue.md", "task-issue.md", "pull-request.md", "handoff.md"):
        assignment_template = assets_root / name
        if assignment_template.is_file():
            text = assignment_template.read_text(encoding="utf-8")
            for required_text in ("Work lead", "inherited"):
                if required_text not in text:
                    errors.append(f"assets/{name} is missing `{required_text}`")
            if "Accountable owner (human)" in text:
                errors.append(
                    f"assets/{name} must inherit OpenBoa accountability instead of repeating it"
                )

    forbidden_assets = {"openboa-governance.yml", "governance-exception.md"}
    for name in sorted(forbidden_assets):
        if (assets_root / name).exists():
            errors.append(f"custom governance artifact must be removed: assets/{name}")

    sync_script = plugin_root / "scripts" / "sync_agents.py"
    validate_nonempty(sync_script, "scripts/sync_agents.py", errors)
    validate_nonempty(root / "scripts" / "validate_codex.py", "scripts/validate_codex.py", errors)

    for template_name in ("workspace-AGENTS.md", "repository-AGENTS.md"):
        template = assets_root / template_name
        if template.is_file():
            validate_managed_template(template, errors)

    root_agents = root / "AGENTS.md"
    if not root_agents.is_file():
        errors.append("missing root AGENTS.md")
    else:
        validate_managed_template(root_agents, errors)
        repository_template = assets_root / "repository-AGENTS.md"
        if repository_template.is_file():
            root_block = extract_managed_block(root_agents)
            template_block = extract_managed_block(repository_template)
            if root_block is not None and template_block is not None and root_block != template_block:
                errors.append("root AGENTS.md managed block must match repository-AGENTS.md")

    readme = root / "README.md"
    if not readme.is_file():
        errors.append("missing README.md")
    else:
        readme_text = readme.read_text(encoding="utf-8")
        for required_text in ("openboa-ai/hydra", MARKETPLACE_NAME, PLUGIN_NAME):
            if required_text not in readme_text:
                errors.append(f"README.md is missing `{required_text}`")

    workflow = root / ".github" / "workflows" / "validate.yml"
    if not workflow.is_file():
        errors.append("missing .github/workflows/validate.yml")
    else:
        workflow_text = workflow.read_text(encoding="utf-8")
        for required_text in (
            "name: openboa-ai-native-sdlc",
            "name: openboa-governance",
            "needs: ai_native_sdlc",
            "Validate research evidence",
        ):
            if required_text not in workflow_text:
                errors.append(f"validate.yml is missing `{required_text}`")

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
        if "/Users/" in text:
            errors.append(f"machine-specific path remains in {path.relative_to(root)}")

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


def validate_nonempty(path: Path, label: str, errors: list[str]) -> None:
    if not path.is_file():
        errors.append(f"missing {label}")
        return
    if not path.read_text(encoding="utf-8").strip():
        errors.append(f"{label} must not be blank")


def validate_skill(skill_root: Path, expected_name: str, errors: list[str]) -> None:
    skill_md = skill_root / "SKILL.md"
    if not skill_md.is_file():
        errors.append(f"missing skill: {expected_name}/SKILL.md")
        return
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        errors.append(f"{expected_name} must start with YAML frontmatter")
        return
    end = text.find("\n---", 4)
    if end < 0:
        errors.append(f"{expected_name} frontmatter is not closed")
        return
    frontmatter = text[4:end]
    name_match = re.search(r"^name:\s*(\S+)", frontmatter, flags=re.MULTILINE)
    description = re.search(r"^description:\s*(.+)", frontmatter, flags=re.MULTILINE)
    if not name_match or name_match.group(1) != expected_name:
        errors.append(f"{expected_name} frontmatter name is incorrect")
    if not description or not description.group(1).startswith("Use when"):
        errors.append(f"{expected_name} description must start with `Use when`")
    validate_nonempty(skill_root / "agents" / "openai.yaml", f"{expected_name}/agents/openai.yaml", errors)


def validate_managed_template(path: Path, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(MANAGED_START) != 1 or text.count(MANAGED_END) != 1:
        errors.append(f"{path.name} must contain exactly one managed marker pair")
        return
    if text.index(MANAGED_START) > text.index(MANAGED_END):
        errors.append(f"{path.name} managed markers are out of order")
    if not any(
        heading in text
        for heading in ("## Repository-local instructions", "## Workspace-local instructions")
    ):
        errors.append(f"{path.name} is missing its local instructions section")
    for required_text in ("agents as team members", "accountability is inherited", "work lead"):
        if required_text not in text:
            errors.append(f"{path.name} is missing `{required_text}`")
    if "step-by-step" not in text:
        errors.append(f"{path.name} must state the step-by-step approval boundary")


def extract_managed_block(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")
    if text.count(MANAGED_START) != 1 or text.count(MANAGED_END) != 1:
        return None
    start = text.index(MANAGED_START)
    end_start = text.index(MANAGED_END)
    if start > end_start:
        return None
    return text[start : end_start + len(MANAGED_END)]


if __name__ == "__main__":
    raise SystemExit(main())
