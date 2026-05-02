class OpenboaHydra < Formula
  desc "Autonomous repository workflow orchestrator based on OpenAI Symphony"
  homepage "https://github.com/openboa-ai/hydra"
  url "https://github.com/openboa-ai/hydra.git", branch: "main"
  version "0.1.0"
  license "Apache-2.0"
  head "https://github.com/openboa-ai/hydra.git", branch: "main"

  depends_on "elixir"
  depends_on "gh"
  uses_from_macos "git"

  conflicts_with "hydra", because: "both install a hydra executable"
  conflicts_with "ory-hydra", because: "both install a hydra executable"

  def install
    ENV["MIX_ENV"] = "prod"
    ENV["MIX_HOME"] = buildpath/".mix"
    ENV["HEX_HOME"] = buildpath/".hex"
    ENV["REBAR_CACHE_DIR"] = buildpath/".cache/rebar3"

    cd "elixir" do
      system "mix", "local.hex", "--force"
      system "mix", "local.rebar", "--force"
      system "mix", "deps.get", "--only", "prod"
      system "mix", "compile"
      system "mix", "escript.build"
    end

    %w[
      AGENTS.md
      LICENSE
      NOTICE
      README.md
      SPEC.md
      elixir
      hydra
      plugins
      scripts
      .agents
      .codex
      .github
    ].each do |path|
      libexec.install path if File.exist?(path)
    end

    chmod 0755, libexec/"hydra"
    (libexec/".hydra-version").write(version.to_s)

    bin.write_env_script libexec/"hydra",
                         HYDRA_PACKAGE_MANAGER:  "homebrew",
                         HYDRA_HOMEBREW_FORMULA: name,
                         HYDRA_RUNTIME_RUNNER:   "system",
                         HYDRA_SKIP_BUILD:       "1",
                         HYDRA_ELIXIR_DIR:       (libexec/"elixir").to_s,
                         MIX_ENV:                "prod"
  end

  test do
    hydra_home = testpath/"hydra-home"
    ENV["HYDRA_HOME"] = hydra_home

    version_output = shell_output("#{bin}/hydra version")
    assert_match "install_manager: homebrew", version_output
    assert_match "update_command: brew upgrade openboa-hydra", version_output
    assert_match "install_root: #{libexec}", version_output
    assert_match "home: #{hydra_home}", shell_output("#{bin}/hydra setup --non-interactive")
    assert_path_exists hydra_home/"config.toml"
  end
end
