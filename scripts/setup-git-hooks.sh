#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root"

git config --local core.hooksPath .githooks
chmod +x \
  .githooks/commit-msg \
  .githooks/pre-commit \
  .githooks/pre-push \
  scripts/check-apache-compliance.sh \
  scripts/check-conventional-title.sh \
  scripts/check-gitleaks.sh

if ! command -v gitleaks >/dev/null 2>&1; then
  printf 'gitleaks is required for Hydra git hooks.\n' >&2
  printf 'Install it before committing or pushing. On macOS: brew install gitleaks\n' >&2
  exit 1
fi

if command -v pre-commit >/dev/null 2>&1; then
  pre-commit validate-config
fi

printf 'Hydra git hooks installed with core.hooksPath=.githooks\n'
