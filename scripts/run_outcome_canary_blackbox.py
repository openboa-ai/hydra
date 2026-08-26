#!/usr/bin/env python3
"""Trusted black-box verifier for the JSONL handoff canary outcome."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import stat
import subprocess
import sys
import tempfile
from typing import Sequence


TIMEOUT_SECONDS = 10
MAX_CHILD_FILE_BYTES = 65_536
MAX_CHILD_MEMORY_BYTES = 536_870_912
MAX_CHILD_FDS = 64
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
    target = (resolved_root / relative).resolve(strict=True)
    try:
        target.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError("entrypoint resolves outside candidate root") from error
    metadata = os.lstat(target)
    if not stat.S_ISREG(metadata.st_mode) or target.is_symlink():
        raise ValueError("entrypoint must be a regular non-symlink file")
    return target


def run_candidate(root: Path, entrypoint: Path, source: Path, output: Path) -> subprocess.CompletedProcess[str]:
    def apply_limits() -> None:
        def hard_cap(kind: int, maximum: int) -> None:
            _, current_hard = resource.getrlimit(kind)
            bounded = maximum if current_hard == resource.RLIM_INFINITY else min(maximum, current_hard)
            resource.setrlimit(kind, (bounded, bounded))

        hard_cap(resource.RLIMIT_FSIZE, MAX_CHILD_FILE_BYTES)
        hard_cap(resource.RLIMIT_CPU, TIMEOUT_SECONDS)
        hard_cap(resource.RLIMIT_AS, MAX_CHILD_MEMORY_BYTES)
        hard_cap(resource.RLIMIT_NOFILE, MAX_CHILD_FDS)
        hard_cap(resource.RLIMIT_NPROC, 1)

    command = [sys.executable, str(entrypoint), str(source), str(output)]
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(
            command,
            cwd=root,
            env={"PATH": "/usr/bin:/bin", "PYTHONIOENCODING": "utf-8"},
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
            preexec_fn=apply_limits,
        )
        try:
            return_code = process.wait(timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            return_code = 124
        stdout.seek(0)
        stderr.seek(0)
        return subprocess.CompletedProcess(
            command,
            return_code,
            stdout.read(MAX_CHILD_FILE_BYTES + 1).decode("utf-8", errors="replace"),
            stderr.read(MAX_CHILD_FILE_BYTES + 1).decode("utf-8", errors="replace"),
        )


def write_jsonl(path: Path, values: list[dict[str, str]]) -> None:
    path.write_text(
        "".join(json.dumps(value, sort_keys=True) + "\n" for value in values),
        encoding="utf-8",
    )


def markdown_section(rendered: str, title: str) -> str | None:
    match = re.search(
        rf"(?ms)^#{{1,6}}\s+{re.escape(title)}\s*$\n(.*?)(?=^#{{1,6}}\s+|\Z)",
        rendered,
    )
    return match.group(1) if match else None


def markdown_values(section: str | None) -> set[str]:
    if section is None:
        return set()
    values: set[str] = set()
    fence: str | None = None
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if line.startswith(("```", "~~~")):
            marker = line[:3]
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            continue
        if fence is None and raw_line.startswith(("- ", "* ")):
            values.add(raw_line[2:].strip())
    return values


def read_bounded_output(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("candidate output must be a regular file")
        if metadata.st_size > MAX_CHILD_FILE_BYTES:
            raise ValueError("candidate output exceeds byte limit")
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = -1
            payload = handle.read(MAX_CHILD_FILE_BYTES + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(payload) > MAX_CHILD_FILE_BYTES:
        raise ValueError("candidate output exceeds byte limit")
    return payload.decode("utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    failures: list[str] = []
    try:
        if sys.platform != "linux" or os.geteuid() == 0 or os.environ.get("GITHUB_ACTIONS") != "true":
            raise ValueError("trusted black-box harness requires a non-root Linux GitHub Actions runner")
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
            if success.returncode != 0:
                failures.append("success-path")
            else:
                rendered = read_bounded_output(output)
                sections = {
                    section: markdown_section(rendered, section)
                    for section in EXPECTED_SECTIONS
                }
                if any(content is None for content in sections.values()):
                    failures.append("section-separation")
                if "cli-completed" not in markdown_values(sections["Outcome"]):
                    failures.append("outcome-preservation")
                if "tests-passed" not in markdown_values(sections["Evidence"]):
                    failures.append("evidence-preservation")
                if "deployment-status-unknown" not in markdown_values(sections["Unknowns"]):
                    failures.append("unknown-preservation")
                original_digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()

                output.unlink()
                write_jsonl(source, [
                    {"kind": "outcome", "value": "cli-completed"},
                    {"kind": "evidence", "value": "tests-passed"},
                    {"kind": "unknown", "value": "ownership-unknown"},
                ])
                probe = run_candidate(root, entrypoint, source, output)
                if probe.returncode != 0:
                    failures.append("input-influence")
                else:
                    probe_text = read_bounded_output(output)
                    probe_digest = hashlib.sha256(probe_text.encode("utf-8")).hexdigest()
                    probe_unknowns = markdown_values(markdown_section(probe_text, "Unknowns"))
                    if "ownership-unknown" not in probe_unknowns or probe_digest == original_digest:
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
