#!/usr/bin/env bash
set -euo pipefail

mode="${1:---staged}"

if [ "$mode" != "--staged" ]; then
  printf 'usage: %s [--staged]\n' "$0" >&2
  exit 2
fi

if ! command -v gitleaks >/dev/null 2>&1; then
  printf 'gitleaks: missing. Install gitleaks before committing; secret scanning is required.\n' >&2
  exit 1
fi

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root"

gitleaks git --staged --redact --no-banner --log-level warn
