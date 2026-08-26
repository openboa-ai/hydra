#!/usr/bin/env python3
"""Trusted black-box verifier for the JSONL handoff canary outcome."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Sequence


TIMEOUT_SECONDS = 10
EXPECTED_SECTIONS = ("Outcome", "Evidence", "Unknowns")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--entrypoint", type=Path, required=True)
    return parser.parse_args(argv)


def regular_entrypoint(root: Path, relative: Path) -> Path:
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("entrypoint must be a relative path inside candidate root")
    resolved_root = root.resolve(strict=True)
    target = resolved_root / relative
    metadata = os.lstat(target)
    if not stat.S_ISREG(metadata.st_mode) or target.is_symlink():
        raise ValueError("entrypoint must be a regular non-symlink file")
    return target


def run_candidate(root: Path, entrypoint: Path, source: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(entrypoint), str(source), str(output)],
        cwd=root,
        env={"PATH": "/usr/bin:/bin", "PYTHONIOENCODING": "utf-8"},
        text=True,
        capture_output=True,
        timeout=TIMEOUT_SECONDS,
        check=False,
    )


def write_jsonl(path: Path, values: list[dict[str, str]]) -> None:
    path.write_text(
        "".join(json.dumps(value, sort_keys=True) + "\n" for value in values),
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    failures: list[str] = []
    try:
        root = args.candidate_root.resolve(strict=True)
        entrypoint = regular_entrypoint(root, args.entrypoint)
        with tempfile.TemporaryDirectory(prefix="openboa-canary-blackbox-") as directory:
            temp = Path(directory)
            source = temp / "events.jsonl"
            output = temp / "handoff.md"
            write_jsonl(source, [
                {"kind": "outcome", "value": "cli-completed"},
                {"kind": "evidence", "value": "tests-passed"},
                {"kind": "unknown", "value": "deployment-status-unknown"},
            ])
            success = run_candidate(root, entrypoint, source, output)
            if success.returncode != 0 or not output.is_file():
                failures.append("success-path")
            else:
                rendered = output.read_text(encoding="utf-8")
                if any(
                    re.search(rf"(?m)^#{{1,6}}\s+{section}\s*$", rendered) is None
                    for section in EXPECTED_SECTIONS
                ):
                    failures.append("section-separation")
                if "deployment-status-unknown" not in rendered:
                    failures.append("unknown-preservation")
                original_digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()

                output.unlink()
                write_jsonl(source, [
                    {"kind": "outcome", "value": "cli-completed"},
                    {"kind": "evidence", "value": "tests-passed"},
                    {"kind": "unknown", "value": "ownership-unknown"},
                ])
                probe = run_candidate(root, entrypoint, source, output)
                if probe.returncode != 0 or not output.is_file():
                    failures.append("input-influence")
                else:
                    probe_text = output.read_text(encoding="utf-8")
                    probe_digest = hashlib.sha256(probe_text.encode("utf-8")).hexdigest()
                    if "ownership-unknown" not in probe_text or probe_digest == original_digest:
                        failures.append("input-influence")

            malformed = temp / "malformed.jsonl"
            malformed_output = temp / "malformed.md"
            malformed.write_text('{"kind":"outcome"\n', encoding="utf-8")
            rejected = run_candidate(root, entrypoint, malformed, malformed_output)
            if (
                rejected.returncode == 0
                or malformed_output.exists()
                or "traceback" in (rejected.stdout + rejected.stderr).casefold()
            ):
                failures.append("malformed-input")
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as error:
        failures.append(type(error).__name__)

    result = {
        "framework": "openboa-blackbox-v1",
        "tests_run": 3,
        "failures": len(set(failures)),
        "failed_checks": sorted(set(failures)),
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
