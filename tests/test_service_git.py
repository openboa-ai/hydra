"""Real service Git configuration isolation with local, synthetic fixtures."""

from pathlib import Path
import shlex
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hydra_sdlc.workspace import WorkspaceWait, _environment
from test_workspace import LocalWorkspace, git


class SyntheticWorkspace(LocalWorkspace):
    def _auth_environment(self):
        env = _environment()
        env["GH_TOKEN"] = "synthetic-service-git-test-token"
        return env


def quoted(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def observed_git(path, *args):
    # Read the actual repository after poisoning its config, without invoking
    # the fsmonitor command through an index-aware observation.
    return git(path, "-c", "core.fsmonitor=false", *args)


class ServiceGitIsolationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()

    def checkout(self, layout):
        root = self.root / layout
        root.mkdir()
        remote, seed = root / "origin.git", root / "seed"
        remote.mkdir()
        seed.mkdir()
        git(remote, "init", "--bare", "--initial-branch=main")
        git(seed, "init", "--initial-branch=main")
        (seed / "README.md").write_text("Initial\n")
        (seed / ".gitattributes").write_text("*.txt filter=trap\n")
        git(seed, "add", ".")
        git(seed, "commit", "-m", "initial")
        base = git(seed, "rev-parse", "HEAD")
        git(seed, "remote", "add", "origin", str(remote))
        git(seed, "push", "origin", "main")
        shared = None
        lifecycle = None
        if layout == "linked":
            shared = root / "shared"
            git(root, "clone", str(remote), str(shared))

            class Lifecycle:
                def prepare(inner, repo, number, branch, expected, path):
                    if not path.exists():
                        git(shared, "worktree", "add", "-b", branch, str(path), base)
                    return path

            lifecycle = Lifecycle()
        workspace = SyntheticWorkspace(root / "work", remote, lifecycle_provider=lifecycle)
        path = workspace.prepare("example/project", 1, "hydra/issue-1", None)
        gitdir = (path / ".git" if layout == "standalone" else
                  Path((path / ".git").read_text().strip().removeprefix("gitdir: ")))
        common = path / ".git" if shared is None else shared / ".git"
        return SimpleNamespace(root=root, remote=remote, seed=seed, base=base,
                               shared=shared, workspace=workspace, path=path,
                               gitdir=gitdir, common=common, traps=[])

    def trap(self, fixture, name, tail="exit 0"):
        marker = fixture.root / (name + ".executed")
        script = fixture.root / (name + ".sh")
        script.write_text("#!/bin/sh\nprintf entered > " + shlex.quote(str(marker)) + "\n" + tail + "\n")
        script.chmod(0o700)
        fixture.traps.append(marker)
        return shlex.quote(str(script))

    def install(self, fixture, location, settings):
        config = fixture.common / "config"
        if location == "common":
            with config.open("a") as output:
                output.write(settings)
            return {config: config.read_bytes()}
        if location == "include":
            included = fixture.root / "included.config"
            included.write_text(settings)
            with config.open("a") as output:
                output.write("\n[include]\n\tpath = " + quoted(included) + "\n")
            return {config: config.read_bytes(), included: included.read_bytes()}
        worktree_config = fixture.gitdir / "config.worktree"
        worktree_config.write_text(settings)
        with config.open("a") as output:
            output.write("\n[extensions]\n\tworktreeConfig = true\n")
        return {config: config.read_bytes(), worktree_config: worktree_config.read_bytes()}

    def assert_preserved(self, fixture, snapshots):
        for marker in fixture.traps:
            self.assertFalse(marker.exists(), f"candidate command executed: {marker.name}")
        for path, content in snapshots.items():
            self.assertEqual(path.read_bytes(), content, f"shared configuration changed: {path.name}")

    def exercise(self, fixture):
        workspace, path = fixture.workspace, fixture.path
        self.assertEqual(workspace.inspect(path), {
            "head": fixture.base, "dirty": False, "branch": "hydra/issue-1", "remote_sha": None,
        })
        candidate = path / "candidate.txt"
        content = b"Exact candidate bytes\n"
        candidate.write_bytes(content)
        self.assertEqual(workspace.changed_paths(path, fixture.base), ["candidate.txt"])
        head = workspace.checkpoint(path, "Candidate checkpoint")
        self.assertNotEqual(head, fixture.base)
        # These are direct observations of the genuine ref, index and object
        # store, independent of the service's private configuration view.
        self.assertEqual(observed_git(path, "rev-parse", "HEAD"), head)
        self.assertEqual(observed_git(path, "rev-parse", "refs/heads/hydra/issue-1"), head)
        self.assertEqual(observed_git(path, "show", "HEAD:candidate.txt"), content.decode().strip())
        indexed = observed_git(path, "ls-files", "--stage", "--", "candidate.txt")
        blob = observed_git(path, "rev-parse", "HEAD:candidate.txt")
        self.assertEqual(indexed, f"100644 {blob} 0\tcandidate.txt")
        self.assertEqual(observed_git(path, "diff", "--cached", "--quiet"), "")
        candidate.unlink()
        workspace._git(path, "checkout", "--", "candidate.txt")
        self.assertEqual(candidate.read_bytes(), content)
        self.assertEqual(workspace.checkpoint(path, "No extra checkpoint"), head)

        (fixture.seed / "upstream.md").write_text("Upstream\n")
        git(fixture.seed, "add", "upstream.md")
        git(fixture.seed, "commit", "-m", "upstream")
        upstream = git(fixture.seed, "rev-parse", "HEAD")
        git(fixture.seed, "push", "origin", "main")
        self.assertEqual(workspace.fetch_base(path, upstream), upstream)
        self.assertEqual(observed_git(path, "rev-parse", "FETCH_HEAD"), upstream)
        self.assertEqual(observed_git(path, "rev-parse", "HEAD"), head)
        self.assertEqual(workspace.publish(path, "hydra/issue-1", None), head)
        self.assertEqual(git(fixture.remote, "rev-parse", "refs/heads/hydra/issue-1"), head)
        self.assertEqual(workspace.prepare("example/project", 1, "hydra/issue-1", head), path)
        self.assertFalse(workspace.inspect(path)["dirty"])
        if fixture.shared is not None:
            self.assertEqual(observed_git(fixture.shared, "rev-parse", "HEAD"), fixture.base)
            self.assertEqual(observed_git(fixture.shared, "ls-files", "--", "candidate.txt"), "")

    def check_commands(self, location, *, transport=False):
        for layout in ("standalone", "linked"):
            with self.subTest(layout=layout, location=location, transport=transport):
                fixture = self.checkout(layout)
                if transport:
                    upload = self.trap(fixture, "upload-pack", 'exec git-upload-pack "$@"')
                    receive = self.trap(fixture, "receive-pack", 'exec git-receive-pack "$@"')
                    settings = ("\n[remote \"origin\"]\n\tuploadpack = " + quoted(upload)
                                + "\n\treceivepack = " + quoted(receive) + "\n")
                else:
                    monitor = self.trap(fixture, "fsmonitor")
                    clean = self.trap(fixture, "clean", "cat")
                    smudge = self.trap(fixture, "smudge", "cat")
                    settings = ("\n[core]\n\tfsmonitor = " + quoted(monitor)
                                + "\n[filter \"trap\"]\n\tclean = " + quoted(clean)
                                + "\n\tsmudge = " + quoted(smudge) + "\n\trequired = true\n")
                snapshots = self.install(fixture, location, settings)
                try:
                    self.exercise(fixture)
                finally:
                    self.assert_preserved(fixture, snapshots)

    def test_common_config_fsmonitor_and_filters_never_execute(self):
        self.check_commands("common")

    def test_included_config_fsmonitor_and_filters_never_execute(self):
        self.check_commands("include")

    def test_worktree_config_fsmonitor_and_filters_never_execute(self):
        self.check_commands("worktree")

    def test_common_config_transport_commands_never_execute(self):
        self.check_commands("common", transport=True)

    def test_included_config_transport_commands_never_execute(self):
        self.check_commands("include", transport=True)

    def test_worktree_config_transport_commands_never_execute(self):
        self.check_commands("worktree", transport=True)

    def test_remote_url_rewrite_cannot_redirect_service_transport(self):
        for layout in ("standalone", "linked"):
            with self.subTest(layout=layout):
                fixture = self.checkout(layout)
                command = self.trap(fixture, "redirected-transport")
                settings = ("\n[url " + quoted("ext::" + command) + "]\n\tinsteadOf = "
                            + quoted(fixture.remote) + "\n[protocol \"ext\"]\n\tallow = always\n")
                snapshots = self.install(fixture, "common", settings)
                try:
                    self.exercise(fixture)
                finally:
                    self.assert_preserved(fixture, snapshots)

    def test_initialized_submodule_commands_are_held_before_execution(self):
        for layout in ("standalone", "linked"):
            with self.subTest(layout=layout):
                fixture = self.checkout(layout)
                git(fixture.path, "-c", "protocol.file.allow=always", "submodule", "add",
                    str(fixture.seed), "nested")
                git(fixture.path, "commit", "-m", "Initialized local submodule")
                head = git(fixture.path, "rev-parse", "HEAD")
                self.assertTrue(git(fixture.path, "ls-files", "--stage", "--", "nested").startswith("160000 "))
                nested = fixture.path / "nested"
                nested_gitdir = Path(git(nested, "rev-parse", "--absolute-git-dir"))
                self.assertTrue((nested / "README.md").is_file())
                monitor = self.trap(fixture, "nested-fsmonitor")
                credential = self.trap(
                    fixture, "nested-credential",
                    "printf 'username=synthetic\\npassword=synthetic-test-only\\n'",
                )
                nested_config = nested_gitdir / "config"
                with nested_config.open("a") as output:
                    output.write("\n[core]\n\tfsmonitor = " + quoted(monitor)
                                 + "\n[credential]\n\thelper = " + quoted("!" + credential) + "\n")
                snapshots = self.install(fixture, "common", (
                    "\n[submodule]\n\trecurse = true\n[fetch]\n\trecurseSubmodules = true\n"
                    "[push]\n\trecurseSubmodules = on-demand\n[status]\n\tsubmoduleSummary = true\n"
                ))
                snapshots[nested_config] = nested_config.read_bytes()
                snapshots[fixture.gitdir / "index"] = (fixture.gitdir / "index").read_bytes()
                snapshots[nested_gitdir / "index"] = (nested_gitdir / "index").read_bytes()
                operations = (
                    lambda: fixture.workspace.inspect(fixture.path),
                    lambda: fixture.workspace.checkpoint(fixture.path, "Must not checkpoint"),
                    lambda: fixture.workspace.publish(fixture.path, "hydra/issue-1", None),
                )
                try:
                    for operation in operations:
                        with self.assertRaisesRegex(WorkspaceWait, "^unsupported_git_metadata$"):
                            operation()
                    self.assertEqual(observed_git(fixture.path, "rev-parse", "HEAD"), head)
                    self.assertEqual(git(fixture.remote, "for-each-ref", "--format=%(refname)",
                                         "refs/heads/hydra/issue-1"), "")
                finally:
                    self.assert_preserved(fixture, snapshots)

    def test_config_mutation_after_identity_cannot_redirect_remote_read(self):
        for layout in ("standalone", "linked"):
            with self.subTest(layout=layout):
                fixture = self.checkout(layout)
                branch = "hydra/issue-1"
                git(fixture.remote, "update-ref", "refs/heads/" + branch, fixture.base)
                (fixture.seed / "foreign.md").write_text("Foreign destination\n")
                git(fixture.seed, "add", "foreign.md")
                git(fixture.seed, "commit", "-m", "foreign head")
                foreign_head = git(fixture.seed, "rev-parse", "HEAD")
                foreign = fixture.root / "foreign.git"
                git(fixture.root, "clone", "--bare", str(fixture.seed), str(foreign))
                git(foreign, "update-ref", "refs/heads/" + branch, foreign_head)
                self.assertNotEqual(foreign_head, fixture.base)
                self.assertEqual(fixture.workspace._identity(fixture.path),
                                 (fixture.path, "example/project", branch))

                upload = self.trap(fixture, "raced-upload-pack", 'exec git-upload-pack "$@"')
                redirect = self.trap(fixture, "raced-redirect")
                config = fixture.common / "config"
                before = config.read_bytes()
                self.assertEqual(before.count(str(fixture.remote).encode()), 1)
                poisoned = []
                original_auth = fixture.workspace._auth_environment

                def mutate_before_authenticated_command():
                    changed = before.replace(str(fixture.remote).encode(), str(foreign).encode())
                    changed += ("\n[remote \"origin\"]\n\tuploadpack = " + quoted(upload)
                                + "\n[url " + quoted("ext::" + redirect) + "]\n\tinsteadOf = "
                                + quoted(fixture.remote) + "\n[protocol \"ext\"]\n\tallow = always\n").encode()
                    config.write_bytes(changed)
                    poisoned.append(config.read_bytes())
                    return original_auth()

                with patch.object(fixture.workspace, "_auth_environment",
                                  side_effect=mutate_before_authenticated_command) as authenticate:
                    observed = fixture.workspace._remote_sha(fixture.path, branch)
                authenticate.assert_called_once_with()
                self.assertEqual(observed, fixture.base)
                self.assert_preserved(fixture, {config: poisoned[0]})


if __name__ == "__main__":
    unittest.main()
