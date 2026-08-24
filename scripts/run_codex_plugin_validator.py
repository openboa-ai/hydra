#!/usr/bin/env python3
"""Run the official Codex plugin and skill validators when installed locally."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


PLUGIN_NAME = "openboa-ai-native-sdlc"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path, help="Codex home containing system skills")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Hydra repository root")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.expanduser().resolve()
    codex_home = resolve_codex_home(args.codex_home)
    validators = (
        (
            codex_home / "skills" / ".system" / "plugin-creator" / "scripts" / "validate_plugin.py",
            root / "plugins" / PLUGIN_NAME,
        ),
        (
            codex_home / "skills" / ".system" / "skill-creator" / "scripts" / "quick_validate.py",
            root / "plugins" / PLUGIN_NAME / "skills" / PLUGIN_NAME,
        ),
    )
    missing = [path for path, _ in validators if not path.is_file()]
    if missing:
        print("Official Codex validator not found:")
        for path in missing:
            print(f"- {path}")
        print("Install or update Codex system skills, or pass --codex-home.")
        return 2

    for validator, target in validators:
        print(f"Running {validator.name} for {target}")
        result = subprocess.run([sys.executable, str(validator), str(target)], check=False)
        if result.returncode != 0:
            return result.returncode
    print("Official Codex plugin and skill validation passed.")
    return 0


def resolve_codex_home(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".codex").resolve()


if __name__ == "__main__":
    raise SystemExit(main())
