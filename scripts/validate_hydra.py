#!/usr/bin/env python3
"""Validate the public OpenBoa Hydra marketplace and AI-Native SDLC package."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import stat
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


CONTRACT_VERSION = "0.2.0"
PLUGIN_NAME = "openboa-ai-native-sdlc"
MARKETPLACE_NAME = "openboa-hydra"
MANAGED_START = f"<!-- {PLUGIN_NAME}:managed:start contract={CONTRACT_VERSION} -->"
MANAGED_END = f"<!-- {PLUGIN_NAME}:managed:end -->"
LEGACY_ACTIVE_IDENTITIES = ("openboa-operations", "openboa operations")
DOCTOR_SHA256 = "5f3f54d22a485f0b7b193124d9812b4db9f671b6afff7f35064db63d8a0e468a"

ROOT_ROUTERS = (
    "DOCTRINE.md",
    "OPERATING-MODEL.md",
    "AI-NATIVE-SDLC.md",
    "GOVERNANCE.md",
)
REQUIRED_REFERENCES = (
    "doctrine.md",
    "operating-model.md",
    "lifecycle.md",
    "work-graphs.md",
    "authority-and-approvals.md",
    "continuity-and-recovery.md",
    "codex-and-github.md",
    "evaluation-and-learning.md",
    "research-basis.md",
    "non-goals.md",
    "capability-map.md",
)
REQUIRED_PLAYBOOKS = (
    "adopt-and-route.md",
    "shape-and-plan.md",
    "execute-and-handoff.md",
    "review-and-ship.md",
    "observe-and-improve.md",
    "automate-and-monitor.md",
)
REQUIRED_TEMPLATES = (
    "issue.md",
    "pull-request.md",
    "handoff.md",
    "exception.md",
    "observation-review.md",
)
REQUIRED_ADAPTERS = (
    "codex.md",
    "github.md",
    "scheduled-tasks.md",
    "headless-and-ci.md",
)
REQUIRED_AUTOMATIONS = (
    "pr-convergence.md",
    "outcome-health.md",
    "release-observation.md",
    "dependency-security.md",
    "docs-drift.md",
    "incident-follow-up.md",
)
REQUIRED_RESEARCH_COLUMNS = (
    "source_id",
    "organization",
    "date",
    "source_type",
    "lifecycle_stage",
    "claim",
    "evidence_status",
    "observed_pattern",
    "precondition",
    "failure_mode",
    "control",
    "metric",
    "confidence",
    "applicability",
    "citation",
)
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
LOCAL_HEADING_RE = re.compile(
    r"(?m)^## (?:Repository|Workspace)-local instructions[ \t]*$"
)
FENCE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})([^\n]*)$")
YAML_BLOCK_SCALAR_RE = re.compile(
    r":\s*[|>](?:[1-9][+-]?|[+-][1-9]?)?\s*(?:#.*)?$"
)
YAML_PERMISSIONS_KEY = r'''(?:permissions|"permissions"|'permissions')'''
YAML_USES_KEY = r'''(?:uses|"uses"|'uses')'''
YAML_IF_KEY = r'''(?:if|"if"|'if')'''
YAML_CONTINUE_KEY = r'''(?:continue-on-error|"continue-on-error"|'continue-on-error')'''


def main() -> int:
    root = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
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
    plugin_root = root / "plugins" / PLUGIN_NAME
    skill_root = plugin_root / "skills" / PLUGIN_NAME
    references_root = skill_root / "references"
    assets_root = skill_root / "assets"

    validate_plugin_symlinks(plugin_root, errors)

    for path in (
        root / "README.md",
        root / "SECURITY.md",
        root / "AGENTS.md",
        *(root / name for name in ROOT_ROUTERS),
        skill_root / "SKILL.md",
        skill_root / "agents" / "openai.yaml",
        assets_root / "managed-AGENTS.md",
        skill_root / "scripts" / "sync_agents.py",
        skill_root / "scripts" / "doctor.py",
        plugin_root / "hooks" / "hooks.json",
        root / "scripts" / "evaluate_readiness.py",
        root / "scripts" / "collect_readiness.py",
        root / ".github" / "workflows" / "openboa-ready-shadow.yml",
        root / ".github" / "openboa-governance.yml",
        root / ".github" / "workflows" / "openboa-governance-v2.yml",
        root / "scripts" / "validate_governance.py",
        root / "evals" / "README.md",
        root / "research" / "openboa-ai-native-sdlc-v0.1" / "README.md",
        root / "research" / "openboa-ai-native-sdlc-v0.1" / "evidence-to-design.md",
    ):
        if not is_regular_file(path):
            errors.append(f"missing required file: {display(root, path)}")

    for path in (
        skill_root / "scripts" / "run_headless.py",
        assets_root / "launchd",
        assets_root / "cron",
    ):
        if path.exists():
            errors.append(f"unsupported generic local execution surface: {display(root, path)}")

    automation_root = assets_root / "automations"
    automation_readme = automation_root / "README.md"
    automation_contract = read_bounded_text(
        automation_readme, root, errors, "automation template", 131072
    )
    if automation_contract is not None:
        for required in (
            "read-only monitor prompts",
            "must not edit a checkout or write to GitHub",
            "Route every required mutation to an interactive Codex task",
        ):
            if required not in automation_contract:
                errors.append(f"automation templates are missing v0.2 read-only contract: {required}")
    if not is_safe_directory(automation_root):
        errors.append(f"unsafe or missing automation directory: {display(root, automation_root)}")
        automation_paths = []
    else:
        automation_paths = []
        try:
            for index, path in enumerate(automation_root.iterdir()):
                if index >= 100:
                    errors.append("automation templates exceed the bounded 100-entry limit")
                    break
                automation_paths.append(path)
        except OSError as exc:
            errors.append(f"unable to list automation templates: {exc}")
            automation_paths = []
    for path in sorted(automation_paths):
        if path == automation_readme:
            continue
        if path.name not in REQUIRED_AUTOMATIONS:
            errors.append(f"undeclared automation entry: {display(root, path)}")
        if is_safe_directory(path):
            errors.append(
                f"automation directory must be flat; nested directory found: {display(root, path)}"
            )
            continue
        if path.suffix != ".md":
            errors.append(f"unexpected automation entry: {display(root, path)}")
            continue
        text = read_bounded_text(path, root, errors, "automation template", 131072)
        if text is None:
            continue
        for forbidden in (
            "fix routine findings inside the approved branch",
            "open or update one durable private or public work item",
            "prepare a coherent documentation update and run",
        ):
            if forbidden in text:
                errors.append(f"scheduled automation retains an unattended write: {display(root, path)}")

    if (root / "plugins" / "openboa-operations").exists():
        errors.append("legacy plugin directory must be removed")

    marketplace = load_json(root / ".agents" / "plugins" / "marketplace.json", errors)
    if marketplace is not None:
        validate_marketplace(marketplace, errors)

    manifest = load_json(plugin_root / ".codex-plugin" / "plugin.json", errors)
    if manifest is not None:
        validate_manifest(manifest, errors)

    validate_active_identity(plugin_root, marketplace, manifest, errors)

    validate_skill(skill_root, errors)

    for name in REQUIRED_REFERENCES:
        if not is_regular_file(references_root / name):
            errors.append(f"missing reference: references/{name}")
    for name in REQUIRED_PLAYBOOKS:
        if not is_regular_file(references_root / "playbooks" / name):
            errors.append(f"missing playbook: references/playbooks/{name}")
    for name in REQUIRED_ADAPTERS:
        if not is_regular_file(references_root / "adapters" / name):
            errors.append(f"missing adapter: references/adapters/{name}")
    for name in REQUIRED_TEMPLATES:
        if not is_regular_file(assets_root / "templates" / name):
            errors.append(f"missing template: assets/templates/{name}")
    for name in REQUIRED_AUTOMATIONS:
        if not is_regular_file(assets_root / "automations" / name):
            errors.append(f"missing automation template: assets/automations/{name}")

    validate_hooks(plugin_root / "hooks" / "hooks.json", errors)
    validate_file_sha256(
        skill_root / "scripts" / "doctor.py",
        root,
        errors,
        "automatic doctor",
        DOCTOR_SHA256,
        131072,
    )

    for path in (root / "AGENTS.md", assets_root / "managed-AGENTS.md"):
        if is_regular_file(path):
            validate_managed_agents(path, errors)

    validate_workflow(root / ".github" / "workflows" / "validate.yml", errors)
    validate_governance_config(root / ".github" / "openboa-governance.yml", errors)
    validate_research(root, errors)
    validate_scenarios(root, errors)
    validate_markdown(root, errors)
    validate_public_content(root, errors)
    return errors


def is_regular_file(path: Path) -> bool:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except OSError:
            return False
        if stat.S_ISLNK(info.st_mode):
            return False
    try:
        info = absolute.lstat()
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode)


def is_safe_directory(path: Path) -> bool:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except OSError:
            return False
        if stat.S_ISLNK(info.st_mode):
            return False
    return stat.S_ISDIR(info.st_mode)


def read_bounded_text(
    path: Path,
    root: Path,
    errors: list[str],
    label: str,
    maximum_bytes: int,
) -> str | None:
    shown = display(root, path)
    if not is_regular_file(path):
        errors.append(f"unsafe or missing {label}: {shown}")
        return None
    try:
        if path.lstat().st_size > maximum_bytes:
            errors.append(f"{label} exceeds {maximum_bytes} bytes: {shown}")
            return None
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        errors.append(f"{label} is not UTF-8: {shown}")
    except OSError as exc:
        errors.append(f"unable to read {label} {shown}: {exc}")
    return None


def validate_file_sha256(
    path: Path,
    root: Path,
    errors: list[str],
    label: str,
    expected: str,
    maximum_bytes: int,
) -> None:
    shown = display(root, path)
    if not is_regular_file(path):
        errors.append(f"unsafe or missing {label}: {shown}")
        return
    try:
        if path.lstat().st_size > maximum_bytes:
            errors.append(f"{label} exceeds {maximum_bytes} bytes: {shown}")
            return
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        errors.append(f"unable to read {label} {shown}: {exc}")
        return
    if observed != expected:
        errors.append(f"{label} does not match the trusted 0.2.0 artifact: {shown}")


def markdown_fenced_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    opened_at: int | None = None
    fence_char = ""
    fence_length = 0
    offset = 0
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\n")
        match = FENCE_RE.match(content)
        if match:
            token = match.group(2)
            suffix = match.group(3)
            if opened_at is None:
                opened_at = offset
                fence_char = token[0]
                fence_length = len(token)
            elif (
                token[0] == fence_char
                and len(token) >= fence_length
                and not suffix.strip(" \t")
            ):
                ranges.append((opened_at, offset + len(line)))
                opened_at = None
                fence_char = ""
                fence_length = 0
        offset += len(line)
    if opened_at is not None:
        ranges.append((opened_at, len(text)))
    return ranges


def inside_html_comment(text: str, position: int) -> bool:
    cursor = 0
    inside = False
    while cursor < position:
        if inside:
            closing = text.find("-->", cursor, position)
            if closing < 0:
                return True
            inside = False
            cursor = closing + 3
        else:
            opening = text.find("<!--", cursor, position)
            if opening < 0:
                return False
            inside = True
            cursor = opening + 4
    return inside


def markdown_inactive_reason(
    text: str, position: int, fenced: list[tuple[int, int]]
) -> str | None:
    if any(start <= position < end for start, end in fenced):
        return "fenced code"
    if inside_html_comment(text, position):
        return "an enclosing HTML comment"
    return None


def yaml_active_lines(text: str) -> list[tuple[int, int, str]]:
    """Return non-comment YAML lines, excluding literal/folded block content."""

    active: list[tuple[int, int, str]] = []
    block_parent_indent: int | None = None
    for line_number, raw in enumerate(text.splitlines(), start=1):
        expanded = raw.expandtabs(8)
        stripped = expanded.lstrip(" ")
        indent = len(expanded) - len(stripped)
        if block_parent_indent is not None:
            if not stripped or stripped.startswith("#"):
                continue
            if indent > block_parent_indent:
                continue
            block_parent_indent = None
        if not stripped or stripped.startswith("#"):
            continue
        active.append((line_number, indent, stripped))
        if YAML_BLOCK_SCALAR_RE.search(stripped):
            block_parent_indent = indent
    return active


def validate_plugin_symlinks(plugin_root: Path, errors: list[str]) -> None:
    """Reject links in the distributed tree instead of validating referents."""

    try:
        root_info = plugin_root.lstat()
    except OSError:
        return
    if stat.S_ISLNK(root_info.st_mode):
        errors.append("plugin root must not be a symlink")
        return
    if not stat.S_ISDIR(root_info.st_mode):
        return
    for path in plugin_root.rglob("*"):
        try:
            info = path.lstat()
        except OSError as exc:
            errors.append(f"unable to inspect plugin path {path.name}: {exc}")
            continue
        if stat.S_ISLNK(info.st_mode):
            errors.append(
                f"plugin package must not contain symlinks: "
                f"{path.relative_to(plugin_root).as_posix()}"
            )


def contains_legacy_identity(value: object) -> bool:
    text = json.dumps(value, ensure_ascii=False).casefold()
    return any(identity in text for identity in LEGACY_ACTIVE_IDENTITIES)


def validate_active_identity(
    plugin_root: Path,
    marketplace: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
    errors: list[str],
) -> None:
    for label, payload in (("marketplace", marketplace), ("plugin manifest", manifest)):
        if payload is not None and contains_legacy_identity(payload):
            errors.append(f"{label} contains the legacy OpenBoa Operations identity")

    skill_root = plugin_root / "skills" / PLUGIN_NAME
    for label, path in (
        ("SKILL.md", skill_root / "SKILL.md"),
        ("openai.yaml", skill_root / "agents" / "openai.yaml"),
    ):
        if not is_regular_file(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"unable to read active identity surface {label}: {exc}")
            continue
        if contains_legacy_identity(text):
            errors.append(f"{label} contains the legacy OpenBoa Operations identity")


def validate_marketplace(payload: dict[str, Any], errors: list[str]) -> None:
    if payload.get("name") != MARKETPLACE_NAME:
        errors.append(f"marketplace name must be {MARKETPLACE_NAME}")
    entries = payload.get("plugins")
    if not isinstance(entries, list):
        errors.append("marketplace plugins must be an array")
        return
    matches = [item for item in entries if isinstance(item, dict) and item.get("name") == PLUGIN_NAME]
    if len(matches) != 1:
        errors.append(f"marketplace must contain exactly one {PLUGIN_NAME} entry")
        return
    entry = matches[0]
    if entry.get("source") != {"source": "local", "path": f"./plugins/{PLUGIN_NAME}"}:
        errors.append("marketplace plugin source must point to the local plugin directory")
    if entry.get("policy") != {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}:
        errors.append("marketplace policy must declare AVAILABLE and ON_INSTALL")
    if not isinstance(entry.get("category"), str) or not entry["category"].strip():
        errors.append("marketplace plugin category must be non-empty")
    legacy = [item for item in entries if isinstance(item, dict) and item.get("name") == "openboa-operations"]
    if legacy:
        errors.append("marketplace must not publish the legacy plugin identity")


def validate_manifest(payload: dict[str, Any], errors: list[str]) -> None:
    required = {
        "name": PLUGIN_NAME,
        "version": CONTRACT_VERSION,
        "license": "Apache-2.0",
        "skills": "./skills/",
    }
    for key, expected in required.items():
        if payload.get(key) != expected:
            errors.append(f"plugin manifest {key} must be {expected}")
    for key in ("description", "author", "interface"):
        if key not in payload:
            errors.append(f"plugin manifest is missing {key}")
    for forbidden in ("hooks", "mcpServers", "apps"):
        if forbidden in payload:
            errors.append(f"plugin manifest must not declare {forbidden}; use supported default discovery")
    interface = payload.get("interface")
    if isinstance(interface, dict):
        for key in ("displayName", "shortDescription", "longDescription", "developerName", "category", "capabilities", "defaultPrompt"):
            if key not in interface:
                errors.append(f"plugin interface is missing {key}")


def validate_skill(skill_root: Path, errors: list[str]) -> None:
    path = skill_root / "SKILL.md"
    if not is_regular_file(path):
        return
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"unable to read SKILL.md: {exc}")
        return
    if not text.startswith("---\n"):
        errors.append("SKILL.md must start with YAML frontmatter")
        return
    end = text.find("\n---", 4)
    if end < 0:
        errors.append("SKILL.md frontmatter is not closed")
        return
    frontmatter = text[4:end]
    name = re.search(r"^name:\s*(\S+)", frontmatter, flags=re.MULTILINE)
    description = re.search(r"^description:\s*(\S.+)$", frontmatter, flags=re.MULTILINE)
    if name is None or name.group(1) != PLUGIN_NAME:
        errors.append(f"skill frontmatter name must be {PLUGIN_NAME}")
    if description is None:
        errors.append("skill frontmatter needs a non-empty description")
    openai = skill_root / "agents" / "openai.yaml"
    if not is_regular_file(openai):
        return
    try:
        openai_text = openai.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"unable to read openai.yaml: {exc}")
        return
    if "$openboa-ai-native-sdlc" not in openai_text:
        errors.append("openai.yaml default_prompt must name $openboa-ai-native-sdlc")


def validate_hooks(path: Path, errors: list[str]) -> None:
    payload = load_json(path, errors)
    if payload is None:
        return
    hooks = payload.get("hooks")
    if not isinstance(hooks, dict) or set(hooks) != {"SessionStart", "PostCompact"}:
        errors.append("plugin hooks must contain only SessionStart and PostCompact")
        return
    command = (
        '/usr/bin/env -i PATH=/usr/bin:/bin:/usr/local/bin python3 -I '
        '"${PLUGIN_ROOT}/skills/openboa-ai-native-sdlc/scripts/doctor.py" --hook'
    )
    expected = {
        "SessionStart": {
            "matcher": "startup|resume|compact",
            "handler": {
                "type": "command",
                "command": command,
                "timeout": 5,
                "statusMessage": "Checking OpenBoa work context",
                "additionalContextLimit": 2000,
            },
        },
        "PostCompact": {
            "matcher": "manual|auto",
            "handler": {
                "type": "command",
                "command": command,
                "timeout": 5,
                "statusMessage": "Rechecking OpenBoa work context",
            },
        },
    }
    for event, contract in expected.items():
        groups = hooks.get(event)
        if not isinstance(groups, list) or len(groups) != 1 or not isinstance(groups[0], dict):
            errors.append(f"plugin hook {event} must contain one matcher group")
            continue
        group = groups[0]
        if set(group) != {"matcher", "hooks"}:
            errors.append(f"plugin hook {event} matcher group has unsupported fields")
        if group.get("matcher") != contract["matcher"]:
            errors.append(f"plugin hook {event} matcher must be {contract['matcher']}")
        handlers = group.get("hooks")
        if not isinstance(handlers, list) or len(handlers) != 1 or not isinstance(handlers[0], dict):
            errors.append(f"plugin hook {event} must contain one handler")
            continue
        handler = handlers[0]
        if handler != contract["handler"]:
            errors.append(
                f"plugin hook {event} handler must exactly match the read-only doctor contract"
            )


def validate_managed_agents(path: Path, errors: list[str]) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"unable to read managed AGENTS.md {path.name}: {exc}")
        return
    start_matches = list(
        re.finditer(rf"(?m)^{re.escape(MANAGED_START)}[ \t]*$", text)
    )
    end_matches = list(
        re.finditer(rf"(?m)^{re.escape(MANAGED_END)}[ \t]*$", text)
    )
    if (
        text.count(MANAGED_START) != 1
        or text.count(MANAGED_END) != 1
        or len(start_matches) != 1
        or len(end_matches) != 1
    ):
        errors.append(f"{path.name} must contain exactly one current managed marker pair")
        return
    fenced = markdown_fenced_ranges(text)
    inactive = False
    for label, match in (
        ("managed start marker", start_matches[0]),
        ("managed end marker", end_matches[0]),
    ):
        reason = markdown_inactive_reason(text, match.start(), fenced)
        if reason:
            inactive = True
            errors.append(f"{path.name} {label} appears inside {reason}")
    if inactive:
        return
    if start_matches[0].start() >= end_matches[0].start():
        errors.append(f"{path.name} managed markers are out of order")
    headings = list(LOCAL_HEADING_RE.finditer(text))
    active_headings: list[re.Match[str]] = []
    for heading in headings:
        reason = markdown_inactive_reason(text, heading.start(), fenced)
        if reason:
            errors.append(
                f"{path.name} local instructions heading appears inside {reason}"
            )
        else:
            active_headings.append(heading)
    if not active_headings:
        errors.append(f"{path.name} must contain a repository or workspace local instructions heading")
    elif len(active_headings) > 1:
        errors.append(f"{path.name} must contain exactly one active local instructions heading")
    elif end_matches[0].start() >= active_headings[0].start():
        errors.append(f"{path.name} managed block must end before local instructions")


def validate_workflow(path: Path, errors: list[str]) -> None:
    if not is_regular_file(path):
        errors.append("missing .github/workflows/validate.yml")
        return
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"unable to read validation workflow: {exc}")
        return
    active_lines = yaml_active_lines(text)
    permission_lines = [
        (line_number, indent, content)
        for line_number, indent, content in active_lines
        if re.search(rf"(?:^|[{{,]\s*){YAML_PERMISSIONS_KEY}\s*:", content)
    ]
    if len(permission_lines) != 1:
        errors.append("validation workflow must contain exactly one top-level permissions block")
    else:
        line_number, indent, content = permission_lines[0]
        if indent != 0 or not re.fullmatch(r"permissions\s*:\s*(?:#.*)?", content):
            errors.append("validation workflow permissions must be a top-level mapping")
        else:
            children: list[tuple[int, int, str]] = []
            for child_number, child_indent, child_content in active_lines:
                if child_number <= line_number:
                    continue
                if child_indent <= indent:
                    break
                children.append((child_number, child_indent, child_content))
            if [(child_indent, child_content) for _, child_indent, child_content in children] != [
                (2, "contents: read")
            ]:
                errors.append(
                    "validation workflow permissions must grant only `contents: read`"
                )

    jobs_indices = [
        index
        for index, (_, indent, content) in enumerate(active_lines)
        if indent == 0 and re.fullmatch(r"jobs\s*:\s*(?:#.*)?", content)
    ]
    governance_block: list[tuple[int, int, str]] = []
    if len(jobs_indices) != 1:
        errors.append("validation workflow must contain exactly one top-level jobs mapping")
    else:
        jobs_start = jobs_indices[0]
        jobs_end = len(active_lines)
        for index in range(jobs_start + 1, len(active_lines)):
            if active_lines[index][1] == 0:
                jobs_end = index
                break
        job_starts = [
            index
            for index in range(jobs_start + 1, jobs_end)
            if active_lines[index][1] == 2
            and re.fullmatch(
                r"[A-Za-z0-9_-]+\s*:\s*(?:#.*)?", active_lines[index][2]
            )
        ]
        governance_jobs: list[list[tuple[int, int, str]]] = []
        for position, job_start in enumerate(job_starts):
            job_end = job_starts[position + 1] if position + 1 < len(job_starts) else jobs_end
            block = active_lines[job_start:job_end]
            names = [
                content
                for _, indent, content in block
                if indent == 4
                and re.fullmatch(
                    r"name\s*:\s*openboa-governance\s*(?:#.*)?", content
                )
            ]
            if len(names) == 1:
                governance_jobs.append(block)
        if len(governance_jobs) != 1:
            errors.append(
                "validation workflow must contain exactly one active `openboa-governance` job"
            )
        else:
            governance_block = governance_jobs[0]

    if governance_block:
        if any(
            indent == 4
            and re.match(rf"^{YAML_IF_KEY}\s*:", content)
            for _, indent, content in governance_block
        ):
            errors.append("openboa-governance job must not be conditional")
        if any(
            indent == 4
            and re.match(rf"^{YAML_CONTINUE_KEY}\s*:", content)
            for _, indent, content in governance_block
        ):
            errors.append(
                "openboa-governance job must not continue on error"
            )
        timeouts = [
            int(match.group(1))
            for _, indent, content in governance_block
            if indent == 4
            and (
                match := re.fullmatch(
                    r"timeout-minutes\s*:\s*([0-9]+)\s*(?:#.*)?", content
                )
            )
        ]
        if len(timeouts) != 1 or timeouts[0] <= 0:
            errors.append(
                "openboa-governance job must declare one positive timeout-minutes value"
            )
        step_parents = [
            index
            for index, (_, indent, content) in enumerate(governance_block)
            if indent == 4 and re.fullmatch(r"steps\s*:\s*(?:#.*)?", content)
        ]
        if len(step_parents) != 1:
            errors.append("openboa-governance job must contain exactly one steps list")
        required_commands = (
            "python3 scripts/validate_hydra.py .",
            "python3 -m unittest discover -s tests -v",
        )
        if len(step_parents) == 1:
            steps_start = step_parents[0]
            step_starts = [
                index
                for index in range(steps_start + 1, len(governance_block))
                if governance_block[index][1] == 6
                and governance_block[index][2].startswith("-")
            ]
            step_blocks: list[list[tuple[int, int, str]]] = []
            for position, step_start in enumerate(step_starts):
                step_end = (
                    step_starts[position + 1]
                    if position + 1 < len(step_starts)
                    else len(governance_block)
                )
                step_blocks.append(governance_block[step_start:step_end])
            for command in required_commands:
                matching_steps = [
                    block
                    for block in step_blocks
                    if any(
                        indent == 8
                        and re.fullmatch(
                            rf"run\s*:\s*{re.escape(command)}\s*(?:#.*)?",
                            content,
                        )
                        for _, indent, content in block
                    )
                ]
                if len(matching_steps) != 1:
                    errors.append(
                        f"openboa-governance job is missing one active command `{command}`"
                    )
                    continue
                required_step = matching_steps[0]
                if any(
                    indent == 8
                    and re.match(rf"^{YAML_IF_KEY}\s*:", content)
                    for _, indent, content in required_step
                ):
                    errors.append(
                        f"required command step must not be conditional: `{command}`"
                    )
                if any(
                    indent == 8
                    and re.match(rf"^{YAML_CONTINUE_KEY}\s*:", content)
                    for _, indent, content in required_step
                ):
                    errors.append(
                        f"required command step must not continue on error: `{command}`"
                    )

    for _, _, content in active_lines:
        if not re.search(rf"(?:^|[-{{,]\s*){YAML_USES_KEY}\s*:", content):
            continue
        match = re.fullmatch(
            rf"(?:-\s*)?{YAML_USES_KEY}\s*:\s*([^\s#]+)\s*(?:#.*)?",
            content,
        )
        if match is None:
            errors.append(f"unable to validate active GitHub Action reference: {content}")
            continue
        reference = match.group(1)
        ref = reference.rsplit("@", 1)[-1]
        if re.fullmatch(r"[0-9a-f]{40}", ref) is None:
            errors.append(
                f"GitHub Action must be pinned to a full commit SHA: {reference}"
            )
    if any("pull_request_target" in content for _, _, content in active_lines):
        errors.append("validation workflow must not use pull_request_target")


def validate_governance_config(path: Path, errors: list[str]) -> None:
    if not is_regular_file(path):
        errors.append("missing .github/openboa-governance.yml")
        return
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"unable to read governance config: {exc}")
        return
    if len(re.findall(r"(?m)^version:\s*1\s*$", text)) != 1:
        errors.append("governance config must declare exactly `version: 1`")
    if len(re.findall(r"(?m)^protected_paths:\s*$", text)) != 1:
        errors.append("governance config must contain exactly one protected_paths list")
    for protected in (
        "AGENTS.md",
        ".github/openboa-governance.yml",
        ".github/workflows/**",
        "scripts/validate_governance.py",
    ):
        if not re.search(rf"(?m)^  - {re.escape(protected)}\s*$", text):
            errors.append(f"governance config must protect `{protected}`")


def validate_research(root: Path, errors: list[str]) -> None:
    path = root / "research" / "openboa-ai-native-sdlc-v0.1" / "source-register.csv"
    if not is_regular_file(path):
        errors.append("missing research source-register.csv")
        return
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            columns = tuple(reader.fieldnames or ())
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        errors.append(f"unable to parse research source register: {exc}")
        return
    if columns != REQUIRED_RESEARCH_COLUMNS:
        errors.append("research source register columns do not match the public evidence format")
    if not 30 <= len(rows) <= 50:
        errors.append(f"research source register must contain 30-50 sources, found {len(rows)}")
    source_ids = [row.get("source_id", "") for row in rows]
    if len(set(source_ids)) != len(source_ids) or any(not value for value in source_ids):
        errors.append("research source_id values must be non-empty and unique")
    organizations = {row.get("organization", "").strip() for row in rows if row.get("organization", "").strip()}
    if len(organizations) < 10:
        errors.append("research source register must cover at least 10 organizations")
    for index, row in enumerate(rows, start=2):
        citation = row.get("citation", "")
        if urlsplit(citation).scheme != "https":
            errors.append(f"research row {index} citation must be an https URL")
        if any(not row.get(column, "").strip() for column in REQUIRED_RESEARCH_COLUMNS):
            errors.append(f"research row {index} has an empty required field")


def validate_scenarios(root: Path, errors: list[str]) -> None:
    paths = sorted((root / "evals" / "scenarios").glob("*.md"))
    if len(paths) != 21:
        errors.append(f"expected 21 behavioral scenarios, found {len(paths)}")
    identifiers: list[str] = []
    for path in paths:
        if not is_regular_file(path):
            errors.append(f"scenario {path.name} must be a regular file")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"unable to read scenario {path.name}: {exc}")
            continue
        match = re.search(r"^ID:\s*`?([^`\n]+)`?", text, flags=re.MULTILINE)
        if match is None:
            errors.append(f"scenario {path.name} is missing ID")
        else:
            identifiers.append(match.group(1))
        if not re.search(r"^Status:\s*`?unmeasured`?", text, flags=re.MULTILINE):
            errors.append(f"scenario {path.name} must start unmeasured")
        for heading in ("## Given", "## Expected behavior", "## Evidence"):
            if heading not in text:
                errors.append(f"scenario {path.name} is missing {heading}")
    if len(identifiers) != len(set(identifiers)):
        errors.append("behavioral scenario IDs must be unique")


def validate_markdown(root: Path, errors: list[str]) -> None:
    ignored_parts = {".git", "__pycache__", ".venv"}
    for path in root.rglob("*.md"):
        if ignored_parts.intersection(path.parts):
            continue
        if path.is_symlink():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"unable to read {display(root, path)}: {exc}")
            continue
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().strip("<>").split("#", 1)[0]
            if not target or target.startswith(("https://", "http://", "mailto:")):
                continue
            resolved = (path.parent / unquote(target)).resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                errors.append(f"link escapes repository in {display(root, path)}: {raw_target}")
                continue
            if not resolved.exists():
                errors.append(f"broken link in {display(root, path)}: {raw_target}")


def validate_public_content(root: Path, errors: list[str]) -> None:
    ignored_parts = {".git", "__pycache__", ".venv"}
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_file() or ignored_parts.intersection(path.parts):
            continue
        if path.suffix not in {".md", ".py", ".json", ".yaml", ".yml", ".csv"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            errors.append(f"public text file is not UTF-8: {display(root, path)}")
            continue
        except OSError as exc:
            errors.append(f"unable to read public text file {display(root, path)}: {exc}")
            continue
        if "[TODO" + ":" in text:
            errors.append(f"unfinished placeholder in {display(root, path)}")
        if "/Users/" + "sangjoon" in text:
            errors.append(f"machine-specific path in {display(root, path)}")


def load_json(path: Path, errors: list[str]) -> dict[str, Any] | None:
    if not is_regular_file(path):
        errors.append(f"missing JSON file: {path.name}")
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"invalid JSON in {path.name}: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append(f"{path.name} must contain a JSON object")
        return None
    return payload


def display(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
