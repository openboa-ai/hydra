#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'usage: %s [--staged|--pre-push [remote-name remote-url]|--all]\n' "$0" >&2
}

require_gitleaks() {
  if ! command -v gitleaks >/dev/null 2>&1; then
    printf 'gitleaks: missing. Install gitleaks before committing or pushing; secret scanning is required.\n' >&2
    exit 1
  fi
}

run_gitleaks() {
  gitleaks git --redact --no-banner --log-level warn "$@"
}

rev_parse_commit() {
  git rev-parse --verify --quiet "$1^{commit}" 2>/dev/null
}

merge_base_for_refs() {
  local commit="$1"
  shift

  local ref
  local base
  for ref in "$@"; do
    if [ -z "$ref" ]; then
      continue
    fi

    if ! rev_parse_commit "$ref" >/dev/null; then
      continue
    fi

    if base="$(git merge-base "$commit" "$ref" 2>/dev/null)" && [ -n "$base" ]; then
      printf '%s\n' "$base"
      return 0
    fi
  done

  return 1
}

push_range_for_ref() {
  local remote_name="$1"
  local local_sha="$2"
  local remote_sha="$3"
  local zero_sha="0000000000000000000000000000000000000000"
  local base=""

  if [ "$remote_sha" != "$zero_sha" ]; then
    printf '%s..%s\n' "$remote_sha" "$local_sha"
    return 0
  fi

  if [ -n "$remote_name" ]; then
    base="$(
      merge_base_for_refs \
        "$local_sha" \
        "refs/remotes/${remote_name}/HEAD" \
        "refs/remotes/${remote_name}/main" \
        "refs/remotes/${remote_name}/master" \
        "refs/remotes/${remote_name}/trunk" || true
    )"
  fi

  if [ -z "$base" ]; then
    base="$(
      merge_base_for_refs \
        "$local_sha" \
        refs/remotes/origin/HEAD \
        refs/remotes/origin/main \
        refs/remotes/origin/master \
        main \
        master || true
    )"
  fi

  if [ -n "$base" ]; then
    printf '%s..%s\n' "$base" "$local_sha"
  else
    printf '%s\n' "$local_sha"
  fi
}

range_has_commits() {
  [ -n "$(git rev-list --max-count=1 "$1" 2>/dev/null)" ]
}

scan_push_range() {
  local local_ref="$1"
  local local_sha="$2"
  local remote_ref="$3"
  local remote_sha="$4"
  local remote_name="$5"
  local zero_sha="0000000000000000000000000000000000000000"
  local range

  if [ "$local_sha" = "$zero_sha" ]; then
    return 0
  fi

  range="$(push_range_for_ref "$remote_name" "$local_sha" "$remote_sha")"
  if ! range_has_commits "$range"; then
    return 0
  fi

  printf 'gitleaks: scanning pushed commits for %s -> %s (%s)\n' "$local_ref" "$remote_ref" "$range" >&2
  run_gitleaks --log-opts="$range" .
}

scan_pre_push() {
  local remote_name="${1:-}"
  local remote_url="${2:-}"
  local saw_input=0
  local local_ref
  local local_sha
  local remote_ref
  local remote_sha

  # remote_url is accepted because Git passes it to pre-push hooks.
  : "$remote_url"

  while read -r local_ref local_sha remote_ref remote_sha; do
    saw_input=1
    scan_push_range "$local_ref" "$local_sha" "$remote_ref" "$remote_sha" "$remote_name"
  done

  if [ "$saw_input" -eq 0 ]; then
    local head_sha
    local fallback_range

    head_sha="$(git rev-parse --verify HEAD)"
    fallback_range="$(push_range_for_ref "$remote_name" "$head_sha" "0000000000000000000000000000000000000000")"
    if range_has_commits "$fallback_range"; then
      printf 'gitleaks: scanning current branch commits (%s)\n' "$fallback_range" >&2
      run_gitleaks --log-opts="$fallback_range" .
    fi
  fi
}

mode="${1:---staged}"
case "$mode" in
  --staged | --pre-push | --all)
    shift || true
    ;;
  *)
    usage
    exit 2
    ;;
esac

require_gitleaks

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root"

case "$mode" in
  --staged)
    run_gitleaks --staged
    ;;
  --pre-push)
    scan_pre_push "$@"
    ;;
  --all)
    run_gitleaks --log-opts=--all .
    ;;
esac
