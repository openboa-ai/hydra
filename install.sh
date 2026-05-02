#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  install.sh [--repo <git-url>] [--ref <ref>] [--install-dir <path>] [--bin-dir <path>] [--no-build]

Installs Hydra as a local CLI:
  - clones or updates the Hydra repository under ~/.local/share/hydra/hydra
  - links the `hydra` command into ~/.local/bin
  - builds the Elixir runtime when `mise` is available

Environment overrides:
  HYDRA_REPO_URL       Git repository URL. Default: https://github.com/openboa-ai/hydra.git
  HYDRA_REF            Git ref to install. Default: main
  HYDRA_INSTALL_DIR    Install checkout path. Default: ${XDG_DATA_HOME:-~/.local/share}/hydra/hydra
  HYDRA_BIN_DIR        Command symlink directory. Default: ~/.local/bin

Examples:
  curl -fsSL https://raw.githubusercontent.com/openboa-ai/hydra/main/install.sh | bash
  curl -fsSL https://raw.githubusercontent.com/openboa-ai/hydra/main/install.sh | bash -s -- --ref main
  HYDRA_INSTALL_DIR="$HOME/.hydra-cli" bash install.sh --no-build
USAGE
}

die() {
  printf 'hydra install: %s\n' "$*" >&2
  exit 1
}

info() {
  printf 'hydra install: %s\n' "$*"
}

expand_path() {
  case "$1" in
    "~") printf '%s\n' "$HOME" ;;
    \~/*) printf '%s/%s\n' "$HOME" "${1#~/}" ;;
    /*) printf '%s\n' "$1" ;;
    *) printf '%s/%s\n' "$PWD" "$1" ;;
  esac
}

repo_url="${HYDRA_REPO_URL:-https://github.com/openboa-ai/hydra.git}"
ref="${HYDRA_REF:-main}"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
install_dir="${HYDRA_INSTALL_DIR:-$data_home/hydra/hydra}"
bin_dir="${HYDRA_BIN_DIR:-$HOME/.local/bin}"
build_runtime=1

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo)
      [ "$#" -ge 2 ] || die "--repo requires a value"
      repo_url="$2"
      shift 2
      ;;
    --ref)
      [ "$#" -ge 2 ] || die "--ref requires a value"
      ref="$2"
      shift 2
      ;;
    --install-dir)
      [ "$#" -ge 2 ] || die "--install-dir requires a value"
      install_dir="$2"
      shift 2
      ;;
    --bin-dir)
      [ "$#" -ge 2 ] || die "--bin-dir requires a value"
      bin_dir="$2"
      shift 2
      ;;
    --no-build)
      build_runtime=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument '$1'. Use --help for usage."
      ;;
  esac
done

[ -n "${HOME:-}" ] || die "HOME is not set"
command -v git >/dev/null 2>&1 || die "git is required"

install_dir="$(expand_path "$install_dir")"
bin_dir="$(expand_path "$bin_dir")"

mkdir -p "$(dirname "$install_dir")" "$bin_dir"

if [ -d "$install_dir/.git" ]; then
  info "updating existing checkout at $install_dir"
  git -C "$install_dir" fetch --tags origin
  if git -C "$install_dir" rev-parse --verify --quiet "origin/$ref" >/dev/null; then
    git -C "$install_dir" checkout -B "$ref" "origin/$ref"
  else
    git -C "$install_dir" checkout "$ref"
  fi
else
  if [ -e "$install_dir" ] && [ -n "$(find "$install_dir" -mindepth 1 -maxdepth 1 2>/dev/null | head -n 1)" ]; then
    die "install dir exists and is not an empty Hydra git checkout: $install_dir"
  fi

  info "cloning $repo_url#$ref into $install_dir"
  if ! git clone --branch "$ref" --single-branch "$repo_url" "$install_dir"; then
    rm -rf "$install_dir"
    git clone "$repo_url" "$install_dir"
    git -C "$install_dir" checkout "$ref"
  fi
fi

chmod +x "$install_dir/hydra"
ln -sfn "$install_dir/hydra" "$bin_dir/hydra"
info "linked $bin_dir/hydra -> $install_dir/hydra"

if [ "$build_runtime" = "1" ]; then
  if command -v mise >/dev/null 2>&1; then
    info "building Elixir runtime with mise"
    (
      cd "$install_dir/elixir"
      mise trust
      mise install
      mise exec -- mix setup
      mise exec -- mix build
    )
  else
    info "mise not found; skipping runtime build"
    info "install mise, then run: hydra update"
  fi
else
  info "runtime build skipped"
fi

case ":$PATH:" in
  *":$bin_dir:"*) ;;
  *)
    info "add this to your shell profile:"
    printf '  export PATH="%s:$PATH"\n' "$bin_dir"
    ;;
esac

info "installed"
printf '\nNext steps:\n'
printf '  hydra setup --wizard\n'
printf '  hydra setup sandbox\n'
printf '  hydra nest add git@github.com:openboa-ai/nest.git --name openboa-ai-nest\n'
printf '  hydra nest sync openboa\n'
