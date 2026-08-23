#!/usr/bin/env python3
"""Run the official Codex validators without assuming a user's home path."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path


PLUGIN_NAME = "openboa-ai-native-sdlc"


def validation_prefix() -> list[str]:
    if importlib.util.find_spec("yaml") is not None:
        return [sys.executable]
    uv = shutil.which("uv")
    if uv:
        return [uv, "run", "--with", "PyYAML", "python"]
    raise RuntimeError(
        "PyYAML is unavailable; install it or run this command in a Codex environment with uv"
    )


def main() -> int:
    root = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else Path.cwd()
    configured_home = os.environ.get("CODEX_HOME")
    codex_home = (
        Path(configured_home).expanduser().resolve()
        if configured_home
        else Path.home() / ".codex"
    )
    plugin_validator = (
        codex_home
        / "skills"
        / ".system"
        / "plugin-creator"
        / "scripts"
        / "validate_plugin.py"
    )
    skill_validator = (
        codex_home
        / "skills"
        / ".system"
        / "skill-creator"
        / "scripts"
        / "quick_validate.py"
    )
    plugin_root = root / "plugins" / PLUGIN_NAME
    skills_root = plugin_root / "skills"

    missing = [
        path
        for path in (plugin_validator, skill_validator, plugin_root, skills_root)
        if not path.exists()
    ]
    if missing:
        print("Codex package validation failed; missing:", file=sys.stderr)
        for path in missing:
            print(f"- {path}", file=sys.stderr)
        return 1

    skill_roots = sorted(path for path in skills_root.iterdir() if path.is_dir())
    if not skill_roots:
        print("Codex package validation failed; no skills found", file=sys.stderr)
        return 1

    try:
        prefix = validation_prefix()
    except RuntimeError as error:
        print(f"Codex package validation failed: {error}", file=sys.stderr)
        return 1

    commands = [[*prefix, str(plugin_validator), str(plugin_root)]]
    commands.extend(
        [*prefix, str(skill_validator), str(skill_root)] for skill_root in skill_roots
    )
    for command in commands:
        result = subprocess.run(command, cwd=root, check=False)
        if result.returncode != 0:
            return result.returncode

    print(f"Official Codex package validation passed: 1 plugin, {len(skill_roots)} skills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
