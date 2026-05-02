#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'hydra-gateway-smoke: %s\n' "$*" >&2
  exit 1
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
hydra_bin="${HYDRA_BIN:-$repo_root/hydra}"
fixture_root="$(mktemp -d)"

cleanup() {
  rm -rf "$fixture_root"
}
trap cleanup EXIT

run_hydra() {
  HYDRA_HOME="$1" "$hydra_bin" "${@:2}"
}

configure_git_user() {
  git -C "$1" config user.name "Hydra Smoke"
  git -C "$1" config user.email "hydra-smoke@example.com"
}

make_initial_repo() {
  local worktree="$1"
  local branch="$2"

  mkdir -p "$worktree"
  git -C "$worktree" init --initial-branch="$branch" >/dev/null
  configure_git_user "$worktree"
}

commit_all() {
  local worktree="$1"
  local message="$2"

  git -C "$worktree" add -A
  git -C "$worktree" commit -m "$message" >/dev/null
}

clone_bare_from_worktree() {
  local worktree="$1"
  local bare="$2"

  git clone --bare "$worktree" "$bare" >/dev/null 2>&1
}

current_branch() {
  git -C "$1" branch --show-current
}

make_empty_artifact_source() {
  local bare="$1"

  git init --bare "$bare" >/dev/null
}

make_bundled_artifact_source() {
  local worktree="$1"
  local bare="$2"
  local branch="${3:-master}"

  make_initial_repo "$worktree" "$branch"
  mkdir -p "$worktree/bundles/base" "$worktree/bundles/repo-worker" "$worktree/scripts"
  printf 'base agents\n' > "$worktree/bundles/base/AGENTS.md"
  printf 'repo worker agents\n' > "$worktree/bundles/repo-worker/AGENTS.md"
  cat > "$worktree/scripts/check-gitleaks.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  --worktree|--staged) exit 0 ;;
  *) exit 2 ;;
esac
EOF
  chmod +x "$worktree/scripts/check-gitleaks.sh"
  commit_all "$worktree" "Initial bundled artifact source"
  clone_bare_from_worktree "$worktree" "$bare"
}

make_target_repo() {
  local worktree="$1"
  local bare="$2"
  local branch="${3:-master}"

  make_initial_repo "$worktree" "$branch"
  printf '# target repo\n' > "$worktree/README.md"
  commit_all "$worktree" "Initial target repo"
  clone_bare_from_worktree "$worktree" "$bare"
}

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

assert_file_not_contains() {
  local file="$1"
  local unexpected="$2"

  if grep -F "$unexpected" "$file" >/dev/null; then
    printf 'did not expect to find %s in %s\n' "$unexpected" "$file" >&2
    printf -- '--- %s ---\n' "$file" >&2
    cat "$file" >&2
    exit 1
  fi
}

assert_fails_with() {
  local expected="$1"
  local output_file="$2"
  shift 2

  if "$@" >"$output_file" 2>&1; then
    printf 'expected command to fail: %s\n' "$*" >&2
    cat "$output_file" >&2
    exit 1
  fi

  assert_file_contains "$output_file" "$expected"
}

commit_and_push_source_changes() {
  local source_clone="$1"
  local message="$2"
  local branch

  configure_git_user "$source_clone"
  commit_all "$source_clone" "$message"
  branch="$(current_branch "$source_clone")"
  [ -n "$branch" ] || fail "source clone is not on a branch"
  git -C "$source_clone" push origin "$branch" >/dev/null
}

extract_before_run_hook() {
  local workflow="$1"
  local output="$2"

  awk '/^  before_run: \|/{flag=1; next} flag && /^  before_remove:/{exit} flag {sub(/^    /, ""); print}' "$workflow" > "$output"
  [ -s "$output" ] || fail "failed to extract before_run hook from $workflow"
}

check_legacy_commands_are_rejected() {
  local home="$fixture_root/legacy-home"

  mkdir -p "$home"
  assert_fails_with "unknown command: list" "$fixture_root/legacy-list.out" env HYDRA_HOME="$home" "$hydra_bin" list
  assert_fails_with "unknown command: openboa" "$fixture_root/legacy-project-shorthand.out" env HYDRA_HOME="$home" "$hydra_bin" openboa
}

check_empty_source_bootstrap_and_yaml_quoting() {
  local home="$fixture_root/empty-home"
  local source_bare="$fixture_root/empty-source.git"
  local source_clone
  local manifest
  local display_name

  make_empty_artifact_source "$source_bare"
  run_hydra "$home" source add "$source_bare" --name empty >/dev/null
  source_clone="$home/nest/sources/empty"

  run_hydra "$home" project add demo \
    --source empty \
    --repo https://github.com/openboa-ai/demo.git \
    --linear-project-slug demo-slug \
    --name Demo > "$fixture_root/empty-project-add.out"

  manifest="$source_clone/projects/demo/project.yml"
  assert_file_contains "$manifest" 'extends:'
  assert_file_not_contains "$manifest" '  - base'
  assert_file_not_contains "$manifest" '  - repo-worker'

  commit_and_push_source_changes "$source_clone" "Add demo project"
  run_hydra "$home" project sync demo > "$fixture_root/empty-project-sync.out"
  assert_file_contains "$fixture_root/empty-project-sync.out" 'synced: demo'

  assert_fails_with "bundle 'base' does not exist" "$fixture_root/missing-bundle.out" \
    env HYDRA_HOME="$home" "$hydra_bin" project add missing \
      --source empty \
      --repo https://github.com/openboa-ai/missing.git \
      --linear-project-slug missing-slug \
      --bundle base

  display_name="$(printf 'Injected\nworkflow: injected.WORKFLOW.md')"
  run_hydra "$home" project add yaml \
    --source empty \
    --repo https://github.com/openboa-ai/yaml.git \
    --linear-project-slug yaml-slug \
    --name "$display_name" > "$fixture_root/yaml-project-add.out"

  manifest="$source_clone/projects/yaml/project.yml"
  assert_file_contains "$manifest" 'name: "Injected\nworkflow: injected.WORKFLOW.md"'
  if [ "$(grep -c '^workflow:' "$manifest")" -ne 1 ]; then
    cat "$manifest" >&2
    fail "project manifest should contain exactly one workflow key"
  fi

  commit_and_push_source_changes "$source_clone" "Add yaml project"
  run_hydra "$home" project sync yaml > "$fixture_root/yaml-project-sync.out"
  assert_file_contains "$fixture_root/yaml-project-sync.out" 'synced: yaml'
}

check_bundled_source_publish_scope_and_hooks() {
  local home="$fixture_root/bundled-home"
  local source_worktree="$fixture_root/bundled-source-worktree"
  local source_bare="$fixture_root/bundled-source.git"
  local source_clone
  local target_worktree="$fixture_root/target-worktree"
  local target_bare="$fixture_root/target.git"
  local target_clone="$fixture_root/target-clone"
  local workflow
  local before_run="$fixture_root/before-run.sh"

  make_bundled_artifact_source "$source_worktree" "$source_bare" master
  make_target_repo "$target_worktree" "$target_bare" master

  run_hydra "$home" source add "$source_bare" --name bundled >/dev/null
  source_clone="$home/nest/sources/bundled"
  git -C "$source_clone" remote set-head origin -d >/dev/null 2>&1 || true

  run_hydra "$home" project add bundled-demo \
    --source bundled \
    --repo "$target_bare" \
    --linear-project-slug bundled-demo-slug \
    --name 'Bundled Demo' > "$fixture_root/bundled-project-add.out"

  manifest="$source_clone/projects/bundled-demo/project.yml"
  assert_file_contains "$manifest" '  - base'
  assert_file_contains "$manifest" '  - repo-worker'

  run_hydra "$home" project publish bundled-demo --source bundled --dry-run > "$fixture_root/project-publish-ok.out"
  assert_file_contains "$fixture_root/project-publish-ok.out" 'dry-run ok for projects/bundled-demo'

  printf 'outside change\n' > "$source_clone/bundles/base/outside.txt"
  assert_fails_with 'changes outside projects/bundled-demo' "$fixture_root/project-publish-outside.out" \
    env HYDRA_HOME="$home" "$hydra_bin" project publish bundled-demo --source bundled --dry-run
  rm -f "$source_clone/bundles/base/outside.txt"

  workflow="$source_clone/projects/bundled-demo/WORKFLOW.md"
  assert_file_contains "$workflow" "git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##' || true"
  assert_file_contains "$workflow" "git fetch origin \"\$default_branch\" --depth 1"
  assert_file_not_contains "$workflow" 'git fetch origin main --depth 1'
  assert_file_not_contains "$workflow" 'Fetch latest origin/main'

  extract_before_run_hook "$workflow" "$before_run"
  git clone "$target_bare" "$target_clone" >/dev/null 2>&1
  git -C "$target_clone" remote set-head origin -d >/dev/null 2>&1 || true
  (cd "$target_clone" && bash "$before_run") > "$fixture_root/before-run.out" 2>&1
  assert_file_contains "$fixture_root/before-run.out" '* branch            master'
}

main() {
  [ -x "$hydra_bin" ] || fail "Hydra binary is not executable: $hydra_bin"

  check_legacy_commands_are_rejected
  check_empty_source_bootstrap_and_yaml_quoting
  check_bundled_source_publish_scope_and_hooks

  printf 'hydra-gateway-smoke: ok\n'
}

main "$@"
