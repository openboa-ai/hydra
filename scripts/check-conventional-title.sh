#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
usage: check-conventional-title.sh (--message TEXT | --message-file PATH) [--context commit|pr-title]

Expected format:
  <type>[optional scope][!]: <description>

Allowed types:
  feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert

Examples:
  feat(cli): add profile wizard
  ci: add secret scanning gates
  fix!: remove deprecated profile field
EOF
}

first_message_line() {
  local path="$1"
  local line

  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      "" | "#"*) continue ;;
      *) printf '%s\n' "$line"; return 0 ;;
    esac
  done <"$path"

  return 0
}

context="commit"
message=""
message_file=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --context)
      if [ "$#" -lt 2 ]; then
        usage
        exit 2
      fi
      context="$2"
      shift 2
      ;;
    --message)
      if [ "$#" -lt 2 ]; then
        usage
        exit 2
      fi
      message="$2"
      shift 2
      ;;
    --message-file)
      if [ "$#" -lt 2 ]; then
        usage
        exit 2
      fi
      message_file="$2"
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done

case "$context" in
  commit | pr-title) ;;
  *)
    usage
    exit 2
    ;;
esac

if [ -n "$message" ] && [ -n "$message_file" ]; then
  usage
  exit 2
fi

if [ -n "$message_file" ]; then
  if [ ! -f "$message_file" ]; then
    printf 'conventional title: message file not found: %s\n' "$message_file" >&2
    exit 2
  fi
  message="$(first_message_line "$message_file")"
fi

message="${message%%$'\r'}"

if [ -z "$message" ]; then
  printf 'conventional title: missing %s text\n' "$context" >&2
  exit 1
fi

if [ "$context" = "commit" ]; then
  case "$message" in
    Merge\ * | fixup!\ * | squash!\ * | amend!\ *)
      exit 0
      ;;
  esac
fi

case "$message" in
  Revert\ \"*\")
    exit 0
    ;;
esac

if [ "${#message}" -gt 100 ]; then
  printf 'conventional title: %s is too long (%s > 100 chars)\n' "$context" "${#message}" >&2
  printf '  %s\n' "$message" >&2
  exit 1
fi

if [[ ! "$message" =~ ^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([A-Za-z0-9._/-]+\))?!?:\ .+ ]]; then
  printf 'conventional title: %s must use Conventional Commits format\n' "$context" >&2
  printf '  got:      %s\n' "$message" >&2
  printf '  expected: <type>[optional scope][!]: <description>\n' >&2
  printf '  types:    feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert\n' >&2
  exit 1
fi
