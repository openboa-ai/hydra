#!/usr/bin/env python3
"""Validate the OpenBoa AI-Native SDLC research package."""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path


PACKAGE = Path("research/openboa-ai-native-sdlc-v0.1")
SOURCE_FILE = PACKAGE / "sources.csv"
REQUIRED_COLUMNS = {
    "source_id",
    "organization",
    "title",
    "source_type",
    "grade",
    "publication_date",
    "lifecycle_stage",
    "claim",
    "evidence",
    "observed_pattern",
    "precondition",
    "failure_mode",
    "control",
    "metric",
    "confidence",
    "applicability",
    "citation",
}
REQUIRED_FILES = {
    "README.md",
    "sources.csv",
    "evidence-synthesis.md",
    "lifecycle-matrix.md",
    "artifact-catalog.md",
    "source-verification.md",
    "risk-and-authority.md",
    "decision-traceability.md",
    "draft-model.md",
    "application-hydra.md",
    "open-questions.md",
}
REQUIRED_ORGANIZATIONS = {
    "OpenAI",
    "Anthropic",
    "NVIDIA",
    "Google/DeepMind",
    "GitHub",
    "Cursor",
    "Factory",
    "Replit",
    "Vercel",
    "Linear",
    "Sourcegraph",
}
ALLOWED_GRADES = {"A", "B", "C", "D"}


def fail(message: str) -> int:
    print(f"Research validation failed: {message}", file=sys.stderr)
    return 1


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    package = root / PACKAGE
    missing = sorted(name for name in REQUIRED_FILES if not (package / name).is_file())
    if missing:
        return fail(f"missing required artifact(s): {', '.join(missing)}")
    source_path = root / SOURCE_FILE
    if not source_path.is_file():
        return fail("source ledger is missing")
    with source_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing_columns = sorted(REQUIRED_COLUMNS - columns)
        if missing_columns:
            return fail(f"source ledger missing column(s): {', '.join(missing_columns)}")
        rows = list(reader)

    if not 30 <= len(rows) <= 40:
        return fail(f"expected 30–40 source records, found {len(rows)}")

    ids = [row["source_id"] for row in rows]
    urls = [row["citation"] for row in rows]
    duplicate_ids = sorted(source_id for source_id, count in Counter(ids).items() if count > 1)
    duplicate_urls = sorted(url for url, count in Counter(urls).items() if count > 1)
    if duplicate_ids:
        return fail(f"duplicate source_id(s): {', '.join(duplicate_ids)}")
    if duplicate_urls:
        return fail(f"duplicate citation URL(s): {', '.join(duplicate_urls)}")

    for index, row in enumerate(rows, start=2):
        empty = sorted(column for column in REQUIRED_COLUMNS if not row.get(column, "").strip())
        if empty:
            return fail(f"row {index} ({row.get('source_id', '?')}) has empty field(s): {', '.join(empty)}")
        if row["grade"] not in ALLOWED_GRADES:
            return fail(f"row {index} has invalid grade {row['grade']!r}")
        if not row["citation"].startswith(("https://", "http://")):
            return fail(f"row {index} has invalid citation URL")
    organizations = {row["organization"] for row in rows}
    missing_organizations = sorted(REQUIRED_ORGANIZATIONS - organizations)
    if missing_organizations:
        return fail(f"missing organization coverage: {', '.join(missing_organizations)}")

    grades = Counter(row["grade"] for row in rows)
    if grades["A"] < 10 or grades["B"] < 10 or grades["C"] < 2:
        return fail(f"source grade coverage is too narrow: {dict(grades)}")

    print(f"Research validation passed: {len(rows)} source records")
    print(f"Organizations: {len(organizations)}")
    print(f"Grades: {dict(sorted(grades.items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
