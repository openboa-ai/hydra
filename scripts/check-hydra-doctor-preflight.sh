#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'hydra-doctor-preflight: %s\n' "$*" >&2
  exit 1
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
hydra_bin="${HYDRA_BIN:-$repo_root/hydra}"
fixture_root="$(mktemp -d)"

cleanup() {
  rm -rf "$fixture_root"
}
trap cleanup EXIT

assert_file_contains() {
  local file="$1"
  local expected="$2"

  grep -F "$expected" "$file" >/dev/null || {
    printf 'expected to find %s in %s\n' "$expected" "$file" >&2
    printf -- '--- %s ---\n' "$file" >&2
    cat "$file" >&2
    exit 1
  }
}

write_demo_profile() {
  local home="$1"

  mkdir -p \
    "$home/projects/demo" \
    "$home/runtime/demo/codex-home/agents" \
    "$home/runtime/demo/codex-home/plugins/hydra/.codex-plugin" \
    "$home/runtime/demo/home/.agents/skills/demo"

  touch "$home/config.toml"
  printf 'Hydra demo AGENTS\n' > "$home/runtime/demo/codex-home/AGENTS.md"
  printf '[mcp_servers.docs]\ncommand = "true"\n' > "$home/runtime/demo/codex-home/config.toml"
  printf '{}\n' > "$home/runtime/demo/codex-home/hooks.json"
  printf '{"name":"hydra","version":"0.0.0"}\n' > "$home/runtime/demo/codex-home/plugins/hydra/.codex-plugin/plugin.json"
  printf '# Demo skill\n' > "$home/runtime/demo/home/.agents/skills/demo/SKILL.md"

  cat > "$home/projects/demo/WORKFLOW.md" <<'EOF'
---
project:
  name: Demo
  key: demo
  repo: https://github.com/openboa-ai/openboa.git
  workspace_root: workspaces/demo
  logs_root: logs/demo
worker:
  sbx:
    enabled: true
tracker:
  kind: linear
  api_key: $LINEAR_API_KEY
  project_slug: demo
server:
  port: 0
---
Demo workflow.
EOF
}

main() {
  local home="$fixture_root/home"

  write_demo_profile "$home"

  HYDRA_HOME="$home" HYDRA_RUNTIME_RUNNER=system "$hydra_bin" doctor demo --json > "$fixture_root/doctor.json" || true
  ruby -rjson -e '
    data = JSON.parse(File.read(ARGV.fetch(0)))
    project = data.fetch("project")
    abort "missing project_sync_detail" unless project.fetch("project_sync_detail").include?("project_sync:")
    abort "missing codex artifacts" unless project.fetch("codex_artifacts").include?("AGENTS=1")
    abort "missing ready codex runtime" unless project.fetch("codex_runtime") == "ready"
  ' "$fixture_root/doctor.json"

  assert_file_contains "$hydra_bin" 'export_project_runtime_context "$project"'

  HYDRA_HOME="$home" HYDRA_RUNTIME_RUNNER=system "$hydra_bin" status demo > "$fixture_root/status.out"
  assert_file_contains "$fixture_root/status.out" 'project_sync: unmanaged (no resolved.yml)'
  assert_file_contains "$fixture_root/status.out" 'codex_runtime: ready'
  assert_file_contains "$fixture_root/status.out" 'codex_artifacts: AGENTS=1 skills=1 agents=0 hooks=1 plugins=1 MCP=1'

  if HYDRA_HOME="$home" HYDRA_RUNTIME_RUNNER=system "$hydra_bin" run demo --no-web-dashboard --no-terminal-dashboard > "$fixture_root/run.out" 2>&1; then
    fail 'expected run preflight to fail without Hydra-managed auth and sbx secrets'
  fi

  assert_file_contains "$fixture_root/run.out" 'hydra: preflight demo'
  assert_file_contains "$fixture_root/run.out" 'project_sync: unmanaged (no resolved.yml)'
  assert_file_contains "$fixture_root/run.out" 'codex_runtime: ready'
  assert_file_contains "$fixture_root/run.out" 'codex_artifacts: AGENTS=1 skills=1 agents=0 hooks=1 plugins=1 MCP=1'
  assert_file_contains "$fixture_root/run.out" 'preflight: failed'

  printf 'hydra-doctor-preflight: ok\n'
}

main "$@"
