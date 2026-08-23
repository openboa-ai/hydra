#!/usr/bin/env python3
"""Install or update one managed OpenBoa block without changing local guidance."""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path


VERSION = "0.1.0"
NEW_START = f"<!-- openboa-ai-native-sdlc:managed:start version={VERSION} -->"
NEW_END = "<!-- openboa-ai-native-sdlc:managed:end -->"
LEGACY_START = "<!-- openboa-operations:managed:start contract=0.1.0 -->"
LEGACY_END = "<!-- openboa-operations:managed:end -->"
ANY_MARKER = re.compile(r"<!--\s*openboa-(?:operations|ai-native-sdlc):managed:(?:start|end)[^>]*-->")
LOCAL_HEADING = re.compile(
    r"^## (?:Repository|Workspace)-local instructions[ \t]*\r?$",
    flags=re.MULTILINE,
)


class SyncError(ValueError):
    pass


def read_text_exact(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return handle.read()


def managed_block(template: str) -> str:
    if template.count(NEW_START) != 1 or template.count(NEW_END) != 1:
        raise SyncError("template managed marker pair is missing or duplicated")
    start = template.index(NEW_START)
    end_start = template.index(NEW_END)
    if start > end_start:
        raise SyncError("template managed marker pair is out of order")
    end = end_start + len(NEW_END)
    heading_index = local_heading_index(template)
    if start >= heading_index or end > heading_index:
        raise SyncError("template managed block overlaps local instructions")
    return template[start:end]


def local_heading_index(source: str) -> int:
    headings = list(LOCAL_HEADING.finditer(source))
    if not headings:
        raise SyncError("local instructions heading is missing")
    if len(headings) > 1:
        raise SyncError("local instructions heading is duplicated")
    return headings[0].start()


def replace_managed_block(source: str, replacement: str) -> tuple[str, str]:
    new_counts = (source.count(NEW_START), source.count(NEW_END))
    legacy_counts = (source.count(LEGACY_START), source.count(LEGACY_END))
    recognized = sum(new_counts) + sum(legacy_counts)
    all_markers = ANY_MARKER.findall(source)

    if len(all_markers) != recognized:
        raise SyncError("unknown managed marker version or format")
    if any(count > 1 for count in (*new_counts, *legacy_counts)):
        raise SyncError("managed marker pair is duplicated")
    if new_counts not in {(0, 0), (1, 1)} or legacy_counts not in {(0, 0), (1, 1)}:
        raise SyncError("managed marker pair is malformed")
    if new_counts == (1, 1) and legacy_counts == (1, 1):
        raise SyncError("legacy and current managed marker pairs both exist")

    heading_index = local_heading_index(source)

    if new_counts == (1, 1):
        start_marker, end_marker, action = NEW_START, NEW_END, "updated"
    elif legacy_counts == (1, 1):
        start_marker, end_marker, action = LEGACY_START, LEGACY_END, "migrated"
    else:
        prefix = source[:heading_index].rstrip()
        local = source[heading_index:]
        separator = "\n\n" if prefix else ""
        return f"{prefix}{separator}{replacement}\n\n{local}", "installed"

    start = source.index(start_marker)
    end_start = source.index(end_marker)
    if start > end_start:
        raise SyncError("managed marker pair is out of order")
    end = end_start + len(end_marker)
    if start >= heading_index or end > heading_index:
        raise SyncError("managed block overlaps local instructions")
    return source[:start] + replacement + source[end:], action


def atomic_write(path: Path, text: str) -> None:
    mode = path.stat().st_mode
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        handle.write(text)
        temp_path = Path(handle.name)
    try:
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: sync_agents.py TARGET_AGENTS_MD TEMPLATE_AGENTS_MD", file=sys.stderr)
        return 2

    target = Path(sys.argv[1]).expanduser().resolve()
    template = Path(sys.argv[2]).expanduser().resolve()
    if not target.is_file() or not template.is_file():
        print("target and template must be existing files", file=sys.stderr)
        return 2

    try:
        source = read_text_exact(target)
        replacement = managed_block(read_text_exact(template))
        result, action = replace_managed_block(source, replacement)
    except (OSError, UnicodeError, SyncError) as error:
        print(f"AGENTS.md sync refused: {error}", file=sys.stderr)
        return 1

    if result == source:
        print(f"AGENTS.md already current: {target}")
        return 0
    try:
        atomic_write(target, result)
    except OSError as error:
        print(f"AGENTS.md sync failed while writing: {error}", file=sys.stderr)
        return 1
    print(f"AGENTS.md {action}: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
