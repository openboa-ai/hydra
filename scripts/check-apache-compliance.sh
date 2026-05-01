#!/usr/bin/env bash
set -euo pipefail

mode="${1:---worktree}"

if [ "$mode" != "--worktree" ] && [ "$mode" != "--staged" ]; then
  printf 'usage: %s [--worktree|--staged]\n' "$0" >&2
  exit 2
fi

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root"

failures=0

error() {
  printf 'apache-compliance: %s\n' "$*" >&2
  failures=$((failures + 1))
}

read_file() {
  local path="$1"

  if [ "$mode" = "--staged" ] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git show ":$path" 2>/dev/null
    return
  fi

  cat "$path" 2>/dev/null
}

require_file() {
  local path="$1"

  if [ "$mode" = "--staged" ] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if ! git cat-file -e ":$path" 2>/dev/null; then
      error "$path must be present in the staged commit"
    fi
    return
  fi

  if [ ! -f "$path" ]; then
    error "$path must exist"
  fi
}

require_text() {
  local path="$1"
  local needle="$2"
  local description="$3"

  if ! read_file "$path" | grep -Fq "$needle"; then
    error "$path must contain: $description"
  fi
}

require_file "LICENSE"
require_file "NOTICE"
require_file "README.md"

require_text "LICENSE" "Apache License" "Apache License title"
require_text "LICENSE" "Version 2.0" "Apache License 2.0 version"

require_text "NOTICE" "Copyright 2025 OpenAI" "upstream OpenAI copyright"
require_text "NOTICE" "This project includes code from openai/symphony." "upstream source attribution"
require_text "NOTICE" "Hydra is a modified fork of OpenAI Symphony." "Hydra fork notice"
require_text "NOTICE" "Licensed under the Apache License, Version 2.0" "Apache 2.0 notice"
require_text "NOTICE" "Modifications:" "Hydra modification notes"

require_text "README.md" "Hydra is a modified fork of OpenAI Symphony" "fork attribution"
require_text "README.md" "https://github.com/openai/symphony" "upstream Symphony link"
require_text "README.md" "Apache License 2.0" "license summary"
require_text "README.md" "NOTICE" "NOTICE reference"

if [ ! -x "hydra" ]; then
  error "hydra launcher must exist and be executable"
fi

public_paths=(
  "README.md"
  "NOTICE"
  "AGENTS.md"
  "hydra"
  "elixir/README.md"
  "elixir/WORKFLOW.md"
  "elixir/lib"
  "elixir/test"
  "elixir/Makefile"
  "elixir/.gitignore"
  ".codex"
  ".github"
  ".gitignore"
)

stale_pattern='OpenHydra|openhydra|OPENHYDRA|Ouroboros|ouroboros|OUROBOROS|\.openhydra|\.ouroboros|openboa-ai/(openhydra|ouroboros)'
if stale_hits="$(rg -n --hidden --glob '!elixir/_build/**' --glob '!elixir/deps/**' "$stale_pattern" "${public_paths[@]}" 2>/dev/null)" &&
  [ -n "$stale_hits" ]; then
  printf '%s\n' "$stale_hits" >&2
  error "stale transitional brand names must not appear in public repository surfaces"
fi


legacy_runtime_pattern='SYMPHONY_|\.symphony|symphony-orchestrator|Symphony Orchestrator|:symphony_elixir|symphony-live-view|symphony_elixir-'
if legacy_hits="$(rg -n --hidden --glob '!elixir/_build/**' --glob '!elixir/deps/**' "$legacy_runtime_pattern" hydra .gitignore elixir/Makefile elixir/.gitignore elixir/config elixir/lib elixir/test elixir/docs .codex 2>/dev/null)" &&
  [ -n "$legacy_hits" ]; then
  printf '%s
' "$legacy_hits" >&2
  error "legacy Symphony runtime environment names must not appear; use Hydra runtime names instead"
fi

if upstream_hits="$(rg -n "openai/symphony" hydra elixir/README.md elixir/WORKFLOW.md elixir/lib elixir/test 2>/dev/null)" &&
  [ -n "$upstream_hits" ]; then
  printf '%s\n' "$upstream_hits" >&2
  error "openai/symphony should only appear in attribution surfaces such as README.md and NOTICE"
fi

if official_hits="$(rg -n "official OpenAI|OpenAI official|OpenAI endorsed|endorsed by OpenAI|OpenAI product" README.md NOTICE AGENTS.md hydra elixir/README.md elixir/WORKFLOW.md elixir/lib elixir/test 2>/dev/null)" &&
  [ -n "$official_hits" ]; then
  printf '%s\n' "$official_hits" >&2
  error "Hydra must not be described as an official or endorsed OpenAI product"
fi

if [ "$failures" -ne 0 ]; then
  printf 'apache-compliance: failed with %s issue(s)\n' "$failures" >&2
  exit 1
fi

printf 'apache-compliance: ok\n'
