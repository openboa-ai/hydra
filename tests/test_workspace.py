import hashlib
import errno
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from hydra_sdlc.workspace import Workspace, WorkspaceWait, _environment, _promote_directory, _run


def git(path, *args):
    return subprocess.check_output(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
         "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", *args],
        cwd=path, env=_environment(), stderr=subprocess.DEVNULL,
    ).decode().strip()


class LocalWorkspace(Workspace):
    def __init__(self, root, remote, **kwargs):
        super().__init__(root, **kwargs)
        self.remote = remote

    def _url(self, repo):
        self._repository(repo)
        return str(self.remote)

    def _auth_environment(self):
        return _environment()


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.remote = self.root / "origin.git"
        self.remote.mkdir()
        git(self.remote, "init", "--bare", "--initial-branch=main")
        self.seed = self.root / "seed"
        self.seed.mkdir()
        git(self.seed, "init", "--initial-branch=main")
        (self.seed / "README.md").write_text("Initial\n")
        git(self.seed, "add", ".")
        git(self.seed, "commit", "-m", "initial")
        self.base = git(self.seed, "rev-parse", "HEAD")
        git(self.seed, "remote", "add", "origin", str(self.remote))
        git(self.seed, "push", "origin", "main")
        self.workspace = LocalWorkspace(self.root / "work", self.remote)
        self.path = self.workspace.prepare("example/project", 1, "hydra/issue-1", None)

    def test_prepare_inspect_and_restart_use_owned_resource_identity(self):
        self.assertEqual(self.path, self.root / "work/example/project/issue-1")
        self.assertEqual(self.workspace.inspect(self.path), {
            "head": self.base, "dirty": False, "branch": "hydra/issue-1", "remote_sha": None,
        })
        restarted = LocalWorkspace(self.root / "work", self.remote)
        self.assertEqual(restarted.prepare("example/project", 1, "hydra/issue-1", None), self.path)
        self.assertFalse(list((self.root / "work").glob("**/*.json")))

    def test_interrupted_staging_before_and_after_stamping_is_preserved_on_restart(self):
        for number, after_stamp in ((2, False), (3, True)):
            with self.subTest(after_stamp=after_stamp):
                final = self.path.parent / f"issue-{number}"
                original = self.workspace._git
                staged = []
                def interrupted(path, *args, **kwargs):
                    marker = self.workspace._marker(final, "owner" if after_stamp else "repository")
                    if args[:3] == ("config", "--local", marker) and len(args) == 4:
                        staged.append(Path(path))
                        if after_stamp:
                            original(path, *args, **kwargs)
                        raise KeyboardInterrupt("allocation interrupted")
                    return original(path, *args, **kwargs)
                with patch.object(self.workspace, "_git", side_effect=interrupted):
                    with self.assertRaises(KeyboardInterrupt):
                        self.workspace.prepare("example/project", number, f"hydra/issue-{number}", None)
                self.assertFalse(final.exists())
                self.assertEqual(len(staged), 1)
                stage = staged[0]
                self.assertEqual(stage.parent, final.parent)
                self.assertNotEqual(stage, final)
                before = (stage / ".git/config").read_bytes()
                (stage / "retain").write_bytes(b"abandoned allocation")
                restarted = LocalWorkspace(self.root / "work", self.remote)
                self.assertEqual(restarted.prepare("example/project", number, f"hydra/issue-{number}", None), final)
                self.assertEqual((stage / ".git/config").read_bytes(), before)
                self.assertEqual((stage / "retain").read_bytes(), b"abandoned allocation")
                self.assertFalse((final / "retain").exists())
                self.assertEqual(restarted.inspect(final)["head"], self.base)

    def test_interruption_after_promotion_reuses_complete_owned_checkout(self):
        final = self.path.parent / "issue-2"
        def interrupted(source, destination):
            _promote_directory(source, destination)
            raise KeyboardInterrupt("promoted response lost")
        with patch("hydra_sdlc.workspace._promote_directory", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                self.workspace.prepare("example/project", 2, "hydra/issue-2", None)
        inode = final.stat().st_ino
        restarted = LocalWorkspace(self.root / "work", self.remote)
        with patch("hydra_sdlc.workspace._promote_directory", side_effect=AssertionError("unexpected reallocation")):
            self.assertEqual(restarted.prepare("example/project", 2, "hydra/issue-2", None), final)
        self.assertEqual(final.stat().st_ino, inode)
        self.assertEqual(restarted.inspect(final)["head"], self.base)

    def test_promotion_refuses_raced_foreign_empty_directory_and_symlinks(self):
        foreign = self.root / "foreign"
        foreign.mkdir()
        (foreign / "retain").write_bytes(b"foreign content")
        for number, kind in ((2, "directory"), (3, "symlink"), (4, "dangling")):
            with self.subTest(kind=kind):
                final = self.path.parent / f"issue-{number}"
                staged, identity = [], []
                def raced(source, destination):
                    staged.append(source)
                    if kind == "directory":
                        destination.mkdir()
                    else:
                        destination.symlink_to(foreign if kind == "symlink" else self.root / "absent")
                    identity.append(destination.lstat().st_ino)
                    _promote_directory(source, destination)
                with patch("hydra_sdlc.workspace._promote_directory", side_effect=raced):
                    with self.assertRaisesRegex(WorkspaceWait, "workspace_destination_exists"):
                        self.workspace.prepare("example/project", number, f"hydra/issue-{number}", None)
                self.assertEqual(final.lstat().st_ino, identity[0])
                self.assertTrue(staged[0].is_dir())
                if kind == "directory":
                    self.assertEqual(list(final.iterdir()), [])
                else:
                    self.assertTrue(final.is_symlink())
                with self.assertRaises(WorkspaceWait):
                    LocalWorkspace(self.root / "work", self.remote).prepare("example/project", number, f"hydra/issue-{number}", None)
                self.assertEqual(final.lstat().st_ino, identity[0])
                self.assertEqual((foreign / "retain").read_bytes(), b"foreign content")

    def test_exclusive_promotion_unavailable_preserves_source_without_fallback(self):
        stage, final = self.root / "stage", self.root / "destination"
        stage.mkdir()
        (stage / "retain").write_bytes(b"owned allocation")
        with patch("hydra_sdlc.workspace.sys.platform", "unsupported"):
            with self.assertRaisesRegex(WorkspaceWait, "exclusive_rename_unavailable"):
                _promote_directory(stage, final)
        with patch("hydra_sdlc.workspace.ctypes.CDLL", return_value=object()):
            with self.assertRaisesRegex(WorkspaceWait, "exclusive_rename_unavailable"):
                _promote_directory(stage, final)
        self.assertFalse(final.exists())
        self.assertEqual((stage / "retain").read_bytes(), b"owned allocation")

    def test_dirty_foreign_branch_and_alias_wait_without_changing_files(self):
        (self.path / "draft").write_text("keep")
        with self.assertRaisesRegex(WorkspaceWait, "dirty_workspace"):
            self.workspace.prepare("example/project", 1, "hydra/issue-1", None)
        self.assertEqual((self.path / "draft").read_text(), "keep")
        git(self.path, "checkout", "-b", "another-owner")
        with self.assertRaisesRegex(WorkspaceWait, "workspace_branch_changed"):
            self.workspace.inspect(self.path)
        alias = self.root / "alias"
        alias.symlink_to(self.path, target_is_directory=True)
        with self.assertRaisesRegex(WorkspaceWait, "workspace_missing_or_aliased"):
            self.workspace.inspect(alias)

    def test_existing_directory_is_never_adopted(self):
        foreign = self.root / "work/example/project/issue-2"
        git(self.root, "clone", str(self.remote), str(foreign))
        git(foreign, "checkout", "-b", "hydra/issue-2")
        with self.assertRaisesRegex(WorkspaceWait, "foreign_workspace"):
            self.workspace.prepare("example/project", 2, "hydra/issue-2", None)

    def test_explicit_dirty_recovery_preserves_staged_unstaged_and_untracked_bytes(self):
        (self.path / "README.md").write_bytes(b"staged\x00bytes\n")
        git(self.path, "add", "README.md")
        (self.path / "README.md").write_bytes(b"unstaged\x00bytes\n")
        (self.path / "draft").write_bytes(b"private\x00draft\n")
        (self.path / "link").symlink_to("draft")
        index = (self.path / ".git/index").read_bytes()
        status = git(self.path, "status", "--porcelain=v1")
        lifecycle = Mock()
        lifecycle.prepare.return_value = self.path
        self.workspace.lifecycle_provider = lifecycle
        self.assertEqual(self.workspace.prepare("example/project", 1, "hydra/issue-1", None,
                                                recover_dirty=True), self.path)
        lifecycle.prepare.assert_called_once_with("example/project", 1, "hydra/issue-1", None, self.path)
        self.assertEqual(git(self.path, "status", "--porcelain=v1"), status)
        self.assertEqual(git(self.path, "rev-parse", "HEAD"), self.base)
        self.assertEqual((self.path / ".git/index").read_bytes(), index)
        self.assertEqual((self.path / "README.md").read_bytes(), b"unstaged\x00bytes\n")
        self.assertEqual((self.path / "draft").read_bytes(), b"private\x00draft\n")
        self.assertEqual(os.readlink(self.path / "link"), "draft")

    def test_recovery_still_rejects_changed_remote_and_foreign_branch_or_identity(self):
        (self.path / "draft").write_text("keep")
        git(self.seed, "push", "origin", "main:hydra/issue-1")
        with self.assertRaisesRegex(WorkspaceWait, "remote_head_changed"):
            self.workspace.prepare("example/project", 1, "hydra/issue-1", None, recover_dirty=True)
        git(self.path, "remote", "set-url", "origin", "https://github.com/foreign/repo.git")
        with self.assertRaisesRegex(WorkspaceWait, "foreign_remote"):
            self.workspace.prepare("example/project", 1, "hydra/issue-1", self.base, recover_dirty=True)
        git(self.path, "remote", "set-url", "origin", str(self.remote))
        git(self.path, "checkout", "-b", "another-owner")
        with self.assertRaisesRegex(WorkspaceWait, "workspace_branch_changed"):
            self.workspace.prepare("example/project", 1, "hydra/issue-1", self.base, recover_dirty=True)
        git(self.path, "checkout", "hydra/issue-1")
        git(self.path, "config", "--unset", self.workspace._marker(self.path, "owner"))
        with self.assertRaisesRegex(WorkspaceWait, "foreign_workspace"):
            self.workspace.prepare("example/project", 1, "hydra/issue-1", self.base, recover_dirty=True)
        self.assertEqual((self.path / "draft").read_text(), "keep")

    def test_recovery_cannot_allocate_adopt_or_follow_alias(self):
        second = self.root / "work/example/project/issue-2"
        with self.assertRaisesRegex(WorkspaceWait, "recovery_workspace_missing"):
            self.workspace.prepare("example/project", 2, "hydra/issue-2", None, recover_dirty=True)
        self.assertFalse(second.exists())
        git(self.root, "clone", str(self.remote), str(second))
        git(second, "checkout", "-b", "hydra/issue-2")
        with self.assertRaisesRegex(WorkspaceWait, "foreign_workspace"):
            self.workspace.prepare("example/project", 2, "hydra/issue-2", None, recover_dirty=True)
        alias = self.root / "work/example/project/issue-3"
        alias.symlink_to(self.path, target_is_directory=True)
        with self.assertRaisesRegex(WorkspaceWait, "workspace_missing_or_aliased"):
            self.workspace.prepare("example/project", 3, "hydra/issue-3", None, recover_dirty=True)

    def test_existing_workspace_requires_lifecycle_validation_before_reuse(self):
        lifecycle = Mock()
        lifecycle.prepare.return_value = self.path
        self.workspace.lifecycle_provider = lifecycle
        self.assertEqual(self.workspace.prepare("example/project", 1, "hydra/issue-1", None), self.path)
        lifecycle.prepare.assert_called_once_with("example/project", 1, "hydra/issue-1", None, self.path)
        (self.path / "draft").write_text("keep")
        lifecycle.prepare.side_effect = WorkspaceWait("resources_unavailable")
        with self.assertRaisesRegex(WorkspaceWait, "resources_unavailable"):
            self.workspace.prepare("example/project", 1, "hydra/issue-1", None, recover_dirty=True)
        self.assertEqual((self.path / "draft").read_text(), "keep")
        lifecycle.prepare.side_effect = None
        lifecycle.prepare.return_value = self.path.parent
        with self.assertRaisesRegex(WorkspaceWait, "lifecycle_provider_path_mismatch"):
            self.workspace.prepare("example/project", 1, "hydra/issue-1", None, recover_dirty=True)

    def test_lifecycle_validation_cannot_change_workspace_before_reuse(self):
        def changed(*args):
            (self.path / "draft").write_text("unexpected change")
            return self.path
        lifecycle = Mock()
        lifecycle.prepare.side_effect = changed
        self.workspace.lifecycle_provider = lifecycle
        with self.assertRaisesRegex(WorkspaceWait, "workspace_changed_during_validation"):
            self.workspace.prepare("example/project", 1, "hydra/issue-1", None)

    def test_invalid_repository_branch_actor_and_commit_reject(self):
        for repo in ("../project", "example/..", "https://token@github.com/owner/repo", "x/repo.git"):
            with self.subTest(repo=repo), self.assertRaises(WorkspaceWait):
                self.workspace.prepare(repo, 2, "hydra/issue-2", None)
        for number, branch, sha in ((True, "hydra/issue-1", None), (2, "main", None), (2, "hydra/issue-2", "main")):
            with self.assertRaises(WorkspaceWait):
                self.workspace.prepare("example/project", number, branch, sha)
        with self.assertRaises(WorkspaceWait):
            Workspace(self.root, user="SonSangjoon")
        for flag in (None, 1, "true"):
            with self.assertRaisesRegex(WorkspaceWait, "invalid_recovery_flag"):
                self.workspace.prepare("example/project", 1, "hydra/issue-1", None, recover_dirty=flag)

    def test_changed_paths_include_renames_staged_and_untracked(self):
        git(self.path, "mv", "README.md", "renamed file.md")
        (self.path / "new\nfile").write_text("new\n")
        self.assertEqual(self.workspace.changed_paths(self.path, self.base),
                         ["README.md", "new\nfile", "renamed file.md"])

    def test_changed_paths_preserve_actual_non_utf8_tracked_staged_and_untracked_names(self):
        names = (b"tracked-\xff.txt", b"staged-\xfe.txt", b"untracked-\xfd.txt", b"valid-\xc3\xa9.txt")
        root = os.fsencode(self.path) + b"/"
        try:
            with open(root + names[0], "wb") as target:
                target.write(b"original tracked bytes\n")
        except OSError as exc:
            if exc.errno == errno.EILSEQ:
                self.skipTest("filesystem rejects non-UTF-8 filenames")
            raise
        baseline = self.workspace.checkpoint(self.path, "Track raw filename")
        contents = {name: b"preserved bytes " + name + b"\n" for name in names}
        for name, data in contents.items():
            with open(root + name, "wb") as target:
                target.write(data)
        git(self.path, "add", "--", os.fsdecode(names[1]))
        index = (self.path / ".git/index").read_bytes()
        paths = self.workspace.changed_paths(self.path, baseline)
        self.assertEqual({os.fsencode(path) for path in paths}, set(names))
        self.assertIn("valid-é.txt", paths)
        self.assertEqual((self.path / ".git/index").read_bytes(), index)
        self.assertEqual(git(self.path, "rev-parse", "HEAD"), baseline)
        for name, data in contents.items():
            with open(root + name, "rb") as target:
                self.assertEqual(target.read(), data)
        self.workspace.checkpoint(self.path, "Preserve owned raw paths")
        self.assertFalse(self.workspace.inspect(self.path)["dirty"])
        self.assertEqual({os.fsencode(path) for path in self.workspace.changed_paths(self.path, baseline)}, set(names))

    def test_changed_paths_report_both_sides_of_actual_non_utf8_rename(self):
        old, new = b"before-\xff.txt", b"after-\xfe.txt"
        root = os.fsencode(self.path) + b"/"
        try:
            with open(root + old, "wb") as target:
                target.write(b"preserved rename content\n")
        except OSError as exc:
            if exc.errno == errno.EILSEQ:
                self.skipTest("filesystem rejects non-UTF-8 filenames")
            raise
        baseline = self.workspace.checkpoint(self.path, "Track rename source")
        os.rename(root + old, root + new)
        self.assertEqual({os.fsencode(path) for path in self.workspace.changed_paths(self.path, baseline)}, {old, new})
        self.workspace.checkpoint(self.path, "Checkpoint raw rename")
        self.assertEqual({os.fsencode(path) for path in self.workspace.changed_paths(self.path, baseline)}, {old, new})
        with open(root + new, "rb") as target:
            self.assertEqual(target.read(), b"preserved rename content\n")

    def test_changed_paths_preserve_non_utf8_path_from_actual_git_tree(self):
        name = b"raw-\xff.txt"
        blob = git(self.path, "rev-parse", "HEAD:README.md")
        subprocess.run(["git", "update-index", "-z", "--index-info"], cwd=self.path,
                       env=_environment(), input=b"100644 " + blob.encode() + b"\t" + name + b"\0", check=True)
        tree = git(self.path, "write-tree")
        baseline = git(self.path, "commit-tree", tree, "-p", self.base, "-m", "Raw filename base")
        git(self.path, "read-tree", self.base)
        raw_tree = subprocess.check_output(["git", "ls-tree", "-rz", baseline], cwd=self.path, env=_environment())
        self.assertIn(b"\t" + name + b"\0", raw_tree)
        self.assertEqual([os.fsencode(path) for path in self.workspace.changed_paths(self.path, baseline)], [name])
        self.assertEqual(self.workspace.inspect(self.path)["head"], self.base)
        self.assertFalse(self.workspace.inspect(self.path)["dirty"])

    def test_fetch_base_prepares_exact_object_without_changing_issue_workspace(self):
        (self.seed / "new-base-file").write_text("upstream\n")
        git(self.seed, "add", ".")
        git(self.seed, "commit", "-m", "Advance main")
        upstream = git(self.seed, "rev-parse", "HEAD")
        git(self.seed, "push", "origin", "main")
        (self.path / "README.md").write_text("unfinished owned edit\n")
        before = git(self.path, "status", "--porcelain=v1")
        with patch.object(self.workspace, "_git", wraps=self.workspace._git) as calls:
            self.assertEqual(self.workspace.fetch_base(self.path, upstream), upstream)
        fetch = next(call for call in calls.call_args_list if "fetch" in call.args)
        self.assertEqual(fetch.args, (self.path, "fetch", "--no-tags", "--recurse-submodules=no", "origin", upstream))
        self.assertTrue(fetch.kwargs["remote"])
        self.assertEqual(git(self.path, "rev-parse", "FETCH_HEAD"), upstream)
        self.assertEqual(git(self.path, "rev-parse", "HEAD"), self.base)
        self.assertEqual(git(self.path, "symbolic-ref", "--short", "HEAD"), "hydra/issue-1")
        self.assertEqual(git(self.path, "status", "--porcelain=v1"), before)
        self.assertFalse((self.path / "new-base-file").exists())

    def test_fetch_base_rejects_refs_foreign_remote_and_missing_object(self):
        with self.assertRaisesRegex(WorkspaceWait, "invalid_commit"):
            self.workspace.fetch_base(self.path, "refs/heads/main")
        with self.assertRaises(WorkspaceWait):
            self.workspace.fetch_base(self.path, "f" * 40)
        git(self.path, "remote", "set-url", "origin", "https://github.com/foreign/repo.git")
        with self.assertRaisesRegex(WorkspaceWait, "foreign_remote"):
            self.workspace.fetch_base(self.path, self.base)

    def test_fetch_base_rejects_mismatched_fetch_head(self):
        real = self.workspace._git
        def mismatch(path, *args, **kwargs):
            if args == ("rev-parse", "--verify", "FETCH_HEAD^{commit}"):
                return subprocess.CompletedProcess([], 0, b"f" * 40 + b"\n")
            return real(path, *args, **kwargs)
        with patch.object(self.workspace, "_git", side_effect=mismatch):
            with self.assertRaisesRegex(WorkspaceWait, "fetched_base_mismatch"):
                self.workspace.fetch_base(self.path, self.base)

    def test_checkpoint_disables_hooks_and_is_idempotent(self):
        sentinel = self.root / "hook-ran"
        hook = self.path / ".git/hooks/pre-commit"
        hook.write_text("#!/bin/sh\ntouch " + str(sentinel) + "\n")
        hook.chmod(0o755)
        (self.path / "README.md").write_text("changed\n")
        head = self.workspace.checkpoint(self.path, "Implement issue")
        self.assertNotEqual(head, self.base)
        self.assertEqual(self.workspace.checkpoint(self.path, "No empty commit"), head)
        self.assertFalse(sentinel.exists())
        self.assertFalse(self.workspace.inspect(self.path)["dirty"])

    def test_verify_returns_digests_and_private_output_for_actual_commands(self):
        (self.path / "nested").mkdir()
        (self.path / "nested/private-output").write_text("private reviewer evidence\n")
        results = self.workspace.verify(self.path, [
            {"argv": [sys.executable, "-c", "from pathlib import Path; print(Path('private-output').read_text(), end='')"], "cwd": "nested", "timeout": 2},
            {"argv": [sys.executable, "-c", "print('failure'); raise SystemExit(3)"]},
        ])
        self.assertEqual([item["passed"] for item in results], [True, False])
        self.assertEqual(results[1]["exit_code"], 3)
        self.assertEqual(results[0]["cwd"], "nested")
        digest = hashlib.sha256(b"private reviewer evidence\n").hexdigest()
        self.assertEqual(results[0]["output_digest"], digest)
        self.assertNotIn("private reviewer evidence", str(results[0]))  # argv is policy, output is private.
        self.assertEqual(self.workspace.verification_output(digest), "private reviewer evidence\n")

    def test_verify_validates_all_commands_before_any_execution(self):
        marker = self.path / "must-not-run"
        commands = [{"argv": [sys.executable, "-c", "from pathlib import Path; Path('must-not-run').touch()"]},
                    {"argv": ["true"], "cwd": "../.."}]
        with self.assertRaises(WorkspaceWait):
            self.workspace.verify(self.path, commands)
        self.assertFalse(marker.exists())
        for commands in ([], [{"argv": "echo hello"}], [{"argv": ["true"], "timeout": float("inf")}],
                         [{"argv": ["true"], "cwd": "/"}], [{"argv": ["true"], "timeout": True}]):
            with self.assertRaises(WorkspaceWait):
                self.workspace.verify(self.path, commands)

    def test_verification_does_not_receive_publishing_tokens_and_timeout_fails(self):
        with patch.dict(os.environ, {"GH_TOKEN": "not-forwarded", "GITHUB_TOKEN": "not-forwarded"}):
            records = self.workspace.verify(self.path, [{"argv": [sys.executable, "-c",
                "import os; assert 'GH_TOKEN' not in os.environ and 'GITHUB_TOKEN' not in os.environ"]},
                {"argv": [sys.executable, "-c", "import time; time.sleep(60)"], "timeout": 1},
                {"argv": [sys.executable, "-c", "from pathlib import Path; Path('later-check').touch()"]}])
        self.assertTrue(records[0]["passed"])
        self.assertFalse(records[1]["passed"])
        self.assertEqual(len(records), 2)
        self.assertFalse((self.path / "later-check").exists())

    def test_verification_stop_kills_owned_process_group_and_skips_later_checks(self):
        marker = self.path / "processes"
        child = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready',flush=True); time.sleep(60)"
        command = (
            "import os,subprocess,sys,time\nfrom pathlib import Path\n"
            "child = subprocess.Popen([sys.executable, '-c', " + repr(child) + "], stdout=subprocess.PIPE)\n"
            "child.stdout.readline()\n"
            "Path('processes').write_text(str(os.getpid()) + ' ' + str(child.pid))\n"
            "time.sleep(60)\n"
        )
        started = time.monotonic()
        with self.assertRaisesRegex(WorkspaceWait, "verification_stopped"):
            self.workspace.verify(self.path, [
                {"argv": [sys.executable, "-c", command], "timeout": 5},
                {"argv": [sys.executable, "-c", "from pathlib import Path; Path('later-check').touch()"]},
            ], stop_requested=marker.exists)
        self.assertLess(time.monotonic() - started, 2)
        self.assertFalse((self.path / "later-check").exists())
        pids = [int(value) for value in marker.read_text().split()]
        for pid in pids:
            until = time.monotonic() + 2
            while True:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                if time.monotonic() >= until:
                    self.fail("Stopped verification left an owned process running")
                time.sleep(0.01)

    def test_verification_deadline_remains_active_after_stdout_closes(self):
        deadline = time.monotonic() + 0.4
        with self.assertRaisesRegex(WorkspaceWait, "verification_stopped"):
            self.workspace.verify(self.path, [
                {"argv": [sys.executable, "-c", "import os,time; os.close(1); os.close(2); time.sleep(60)"], "timeout": 5},
                {"argv": [sys.executable, "-c", "from pathlib import Path; Path('later-check').touch()"]},
            ], stop_requested=lambda: time.monotonic() >= deadline)
        self.assertLess(time.monotonic() - deadline, 1)
        self.assertFalse((self.path / "later-check").exists())

    def test_verification_signal_stop_is_not_a_passing_receipt(self):
        stopped = False
        def stop(_signal, _frame):
            nonlocal stopped
            stopped = True
        previous = signal.signal(signal.SIGUSR1, stop)
        try:
            with self.assertRaisesRegex(WorkspaceWait, "verification_stopped"):
                self.workspace.verify(self.path, [{"argv": [sys.executable, "-c",
                    f"import os,signal,time; os.kill({os.getpid()},signal.SIGUSR1); time.sleep(60)"], "timeout": 5}],
                    stop_requested=lambda: stopped)
        finally:
            signal.signal(signal.SIGUSR1, previous)
        self.assertTrue(stopped)

    def test_verification_stop_before_dispatch_never_runs_a_command(self):
        with self.assertRaisesRegex(WorkspaceWait, "verification_stopped"), patch(
            "hydra_sdlc.workspace.subprocess.Popen"
        ) as spawn:
            self.workspace.verify(self.path, [{"argv": ["true"]}], stop_requested=lambda: True)
        spawn.assert_not_called()

    def test_verification_cleanup_uncertainty_prevents_receipts_and_later_commands(self):
        from hydra_sdlc.execution_boundary import OwnedCommandError
        with patch("hydra_sdlc.execution_boundary.run_owned_sync",
                   side_effect=OwnedCommandError("cleanup_unknown")) as execute:
            with self.assertRaisesRegex(WorkspaceWait, "verification_cleanup_unknown") as error:
                self.workspace.verify(self.path, [{"argv": ["first"]}, {"argv": ["later"]}])
        self.assertTrue(error.exception.uncertain)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(self.workspace._outputs, {})

    def test_publish_reads_back_and_never_forces(self):
        (self.path / "README.md").write_text("changed\n")
        head = self.workspace.checkpoint(self.path, "Change")
        with patch.object(self.workspace, "_git", wraps=self.workspace._git) as calls:
            self.assertEqual(self.workspace.publish(self.path, "hydra/issue-1", None), head)
            self.assertEqual(self.workspace.publish(self.path, "hydra/issue-1", None), head)
        pushes = [call for call in calls.call_args_list if "push" in call.args]
        self.assertEqual(len(pushes), 1)
        self.assertNotIn("--force", str(pushes))
        self.assertEqual(git(self.remote, "rev-parse", "refs/heads/hydra/issue-1"), head)

    def test_publish_lost_response_is_resolved_once_without_retry(self):
        head = self.workspace.checkpoint(self.path, "No changes")
        real = self.workspace._git
        def lost(path, *args, **kwargs):
            value = real(path, *args, **kwargs)
            if args[0] == "push":
                raise WorkspaceWait("transport_lost", uncertain=True)
            return value
        with patch.object(self.workspace, "_git", side_effect=lost) as calls:
            self.assertEqual(self.workspace.publish(self.path, "hydra/issue-1", None), head)
        self.assertEqual(sum("push" in call.args for call in calls.call_args_list), 1)

    def test_publish_rejects_remote_creation_between_preflight_and_push(self):
        (self.path / "README.md").write_text("candidate\n")
        self.workspace.checkpoint(self.path, "Candidate")
        real = self.workspace._git
        def raced(path, *args, **kwargs):
            if args[0] == "push":
                git(self.seed, "push", "origin", "main:hydra/issue-1")
            return real(path, *args, **kwargs)
        with patch.object(self.workspace, "_git", side_effect=raced):
            with self.assertRaisesRegex(WorkspaceWait, "remote_head_changed"):
                self.workspace.publish(self.path, "hydra/issue-1", None)
        self.assertEqual(git(self.remote, "rev-parse", "refs/heads/hydra/issue-1"), self.base)

    def test_publish_rejects_remote_advance_even_when_still_fast_forward(self):
        self.workspace.publish(self.path, "hydra/issue-1", None)
        (self.path / "README.md").write_text("first\n")
        first = self.workspace.checkpoint(self.path, "First")
        (self.path / "README.md").write_text("second\n")
        self.workspace.checkpoint(self.path, "Second")
        real = self.workspace._git
        def raced(path, *args, **kwargs):
            if args[0] == "push":
                git(self.path, "push", "origin", first + ":refs/heads/hydra/issue-1")
            return real(path, *args, **kwargs)
        with patch.object(self.workspace, "_git", side_effect=raced):
            with self.assertRaisesRegex(WorkspaceWait, "remote_head_changed"):
                self.workspace.publish(self.path, "hydra/issue-1", self.base)
        self.assertEqual(git(self.remote, "rev-parse", "refs/heads/hydra/issue-1"), first)

    def test_command_output_is_capped_while_process_is_running(self):
        with patch("hydra_sdlc.workspace.MAX_OUTPUT_BYTES", 1000):
            with self.assertRaisesRegex(WorkspaceWait, "command_output_limit"):
                _run([sys.executable, "-c", "import os,time; os.write(1,b'x'*10000); time.sleep(60)"], self.path, 2)

    def test_publication_cannot_follow_tags_from_host_preferences(self):
        git(self.path, "config", "push.followTags", "true")
        git(self.path, "config", "push.recurseSubmodules", "on-demand")
        git(self.path, "tag", "-a", "private-tag", "-m", "Do not publish this tag")
        self.workspace.publish(self.path, "hydra/issue-1", None)
        self.assertEqual(git(self.remote, "tag", "--list"), "")

    def test_remote_change_dirty_and_foreign_pushurl_block_publication(self):
        git(self.seed, "push", "origin", "main:hydra/issue-1")
        (self.path / "README.md").write_text("candidate\n")
        self.workspace.checkpoint(self.path, "Candidate")
        with self.assertRaisesRegex(WorkspaceWait, "remote_head_changed"):
            self.workspace.publish(self.path, "hydra/issue-1", None)
        (self.path / "uncommitted").touch()
        with self.assertRaisesRegex(WorkspaceWait, "dirty_workspace"):
            self.workspace.publish(self.path, "hydra/issue-1", self.base)
        git(self.path, "remote", "set-url", "--push", "origin", "https://github.com/foreign/repo.git")
        with self.assertRaisesRegex(WorkspaceWait, "foreign_remote"):
            self.workspace.inspect(self.path)

    def test_unknown_readback_is_an_explicit_wait(self):
        with patch.object(self.workspace, "_remote_sha", side_effect=[None, WorkspaceWait("offline")]), \
             patch.object(self.workspace, "_git", wraps=self.workspace._git):
            with self.assertRaisesRegex(WorkspaceWait, "publish_unknown") as error:
                self.workspace.publish(self.path, "hydra/issue-1", None)
        self.assertTrue(error.exception.uncertain)

    def test_managed_root_requires_registered_resource_providers(self):
        (self.root / ".workspace").mkdir()
        (self.root / ".workspace/storage.json").write_text("{}")
        with self.assertRaisesRegex(WorkspaceWait, "lifecycle_provider_required"):
            self.workspace.prepare("example/project", 2, "hydra/issue-2", None)
        with self.assertRaisesRegex(WorkspaceWait, "lifecycle_provider_required"):
            self.workspace.prepare("example/project", 1, "hydra/issue-1", None)
        (self.path / "draft").write_text("keep")
        with self.assertRaisesRegex(WorkspaceWait, "lifecycle_provider_required"):
            self.workspace.prepare("example/project", 1, "hydra/issue-1", None, recover_dirty=True)
        with self.assertRaisesRegex(WorkspaceWait, "storage_provider_required"):
            self.workspace.verify(self.path, [{"argv": ["true"]}])

    def test_storage_provider_receives_owned_path_and_validated_arguments(self):
        class Storage:
            def run(inner, path, argv, cwd, timeout, *, stop_requested):
                self.assertEqual(path, self.path)
                self.assertEqual(cwd, self.path)
                self.assertEqual(timeout, 20)
                self.assertFalse(stop_requested())
                return _run(argv, cwd, timeout, stop_requested=stop_requested)
        self.workspace.storage_provider = Storage()
        self.assertTrue(self.workspace.verify(self.path, [{"argv": [sys.executable, "-c", "pass"], "timeout": 20}])[0]["passed"])

    def test_storage_stop_cannot_return_success_or_dispatch_later_command(self):
        stopped = False
        def stop_requested():
            return stopped
        class Storage:
            def run(inner, path, argv, cwd, timeout, *, stop_requested):
                nonlocal stopped
                self.assertFalse(stop_requested())
                stopped = True
                return subprocess.CompletedProcess(argv, 0, b"finished during stop")
        storage = Storage()
        self.workspace.storage_provider = storage
        with patch.object(storage, "run", wraps=storage.run) as calls:
            with self.assertRaisesRegex(WorkspaceWait, "verification_stopped"):
                self.workspace.verify(self.path, [{"argv": ["true"]}, {"argv": ["true"]}],
                                      stop_requested=stop_requested)
        self.assertEqual(calls.call_count, 1)

    def test_lifecycle_provider_can_register_independent_linked_worktrees(self):
        class Lifecycle:
            def prepare(inner, repo, number, branch, expected, path):
                self.assertEqual((repo, number, expected), ("example/project", 2, None))
                git(self.path, "worktree", "add", "-b", branch, str(path), self.base)
                return path
        self.workspace.lifecycle_provider = Lifecycle()
        second = self.workspace.prepare("example/project", 2, "hydra/issue-2", None)
        self.assertEqual(self.workspace.inspect(second)["head"], self.base)
        self.assertEqual(self.workspace.inspect(self.path)["head"], self.base)

    def test_contains_base_requires_integration_not_just_a_fetched_object(self):
        (self.seed / "upstream").write_text("base addition")
        git(self.seed, "add", "upstream")
        git(self.seed, "commit", "-m", "upstream")
        upstream = git(self.seed, "rev-parse", "HEAD")
        git(self.seed, "push", "origin", "main")
        (self.path / "candidate").write_text("owned change")
        candidate = self.workspace.checkpoint(self.path, "Candidate")
        self.workspace.fetch_base(self.path, upstream)
        self.assertTrue(self.workspace.contains_base(self.path, self.base))
        self.assertFalse(self.workspace.contains_base(self.path, upstream))
        self.assertEqual(git(self.path, "rev-parse", "HEAD"), candidate)
        git(self.path, "merge", "--no-ff", "--no-edit", upstream)
        self.assertTrue(self.workspace.contains_base(self.path, upstream))
        self.assertTrue(self.workspace.contains_base(self.path, git(self.path, "rev-parse", "HEAD")))

    def test_contains_base_rejects_refs_tags_blobs_missing_objects_and_git_errors(self):
        git(self.path, "tag", "-a", "base-tag", "-m", "tag")
        for value in ("HEAD", "refs/heads/main", git(self.path, "rev-parse", "base-tag"),
                      git(self.path, "rev-parse", "HEAD:README.md"), "f" * 40):
            with self.subTest(value=value), self.assertRaises(WorkspaceWait):
                self.workspace.contains_base(self.path, value)
        real = self.workspace._git
        def failed(path, *args, **kwargs):
            if "merge-base" in args:
                return subprocess.CompletedProcess(args, 128, b"unavailable")
            return real(path, *args, **kwargs)
        with patch.object(self.workspace, "_git", side_effect=failed):
            with self.assertRaisesRegex(WorkspaceWait, "git_operation_failed"):
                self.workspace.contains_base(self.path, self.base)

    def test_spec_candidate_inspection_does_not_stage_untracked_artifacts(self):
        spec = self.path / "spec.md"
        spec.write_bytes(b"candidate specification\n")
        index = (self.path / ".git/index").read_bytes()
        self.assertTrue(self.workspace.valid_spec(self.path, "README.md"))
        self.assertFalse(self.workspace.valid_spec(self.path, "spec.md"))
        self.assertTrue(self.workspace.valid_spec(self.path, "spec.md", require_tracked=False))
        self.assertEqual((self.path / ".git/index").read_bytes(), index)
        with self.assertRaisesRegex(WorkspaceWait, "invalid_spec"):
            self.workspace.read_spec(self.path, "spec.md")
        git(self.path, "add", "spec.md")
        self.assertTrue(self.workspace.valid_spec(self.path, "spec.md"))
        self.assertEqual(self.workspace.read_spec(self.path, "spec.md"), b"candidate specification\n")

    def test_spec_rejects_missing_empty_special_and_aliased_artifacts(self):
        (self.path / "empty.md").touch()
        (self.path / "directory").mkdir()
        os.mkfifo(self.path / "pipe.md")
        (self.path / "alias.md").symlink_to("README.md")
        (self.path / "dangling.md").symlink_to("missing.md")
        (self.path / "docs").mkdir()
        (self.path / "docs/spec.md").write_text("specification")
        (self.path / "alias-parent").symlink_to("docs", target_is_directory=True)
        for relative in ("missing.md", "empty.md", "directory", "pipe.md", "alias.md",
                         "dangling.md", "alias-parent/spec.md"):
            with self.subTest(relative=relative):
                self.assertFalse(self.workspace.valid_spec(self.path, relative, require_tracked=False))
                with self.assertRaisesRegex(WorkspaceWait, "invalid_spec"):
                    self.workspace.read_spec(self.path, relative)

    def test_spec_rejects_noncanonical_paths_and_invalid_tracking_flags(self):
        for relative in ("", "/README.md", "./README.md", "../README.md", "docs/../README.md",
                         "docs//spec.md", "README.md/", ".git/config", ".GIT/config",
                         "docs\\spec.md", "bad\0name", None):
            with self.subTest(relative=relative):
                self.assertFalse(self.workspace.valid_spec(self.path, relative, require_tracked=False))
        for flag in (None, 0, 1, "false"):
            with self.subTest(flag=flag):
                self.assertFalse(self.workspace.valid_spec(self.path, "README.md", require_tracked=flag))
        git(self.path, "config", "--unset", self.workspace._marker(self.path, "owner"))
        for operation in (lambda: self.workspace.valid_spec(self.path, "README.md"),
                          lambda: self.workspace.read_spec(self.path, "README.md"),
                          lambda: self.workspace.contains_base(self.path, self.base)):
            with self.assertRaisesRegex(WorkspaceWait, "foreign_workspace"):
                operation()

    def test_spec_rejects_symlink_index_entry_even_with_regular_worktree_file(self):
        spec = self.path / "spec.md"
        spec.symlink_to("README.md")
        git(self.path, "add", "spec.md")
        spec.unlink()
        spec.write_text("regular replacement")
        self.assertTrue(self.workspace.valid_spec(self.path, "spec.md", require_tracked=False))
        self.assertFalse(self.workspace.valid_spec(self.path, "spec.md"))

    def test_spec_rejects_unmerged_index_entries(self):
        git(self.path, "checkout", "-b", "other-spec")
        (self.path / "README.md").write_text("other specification\n")
        git(self.path, "add", "README.md")
        git(self.path, "commit", "-m", "other spec")
        git(self.path, "checkout", "hydra/issue-1")
        (self.path / "README.md").write_text("owned specification\n")
        self.workspace.checkpoint(self.path, "Owned spec")
        with self.assertRaises(subprocess.CalledProcessError):
            git(self.path, "merge", "other-spec")
        self.assertTrue(self.workspace.valid_spec(self.path, "README.md", require_tracked=False))
        self.assertFalse(self.workspace.valid_spec(self.path, "README.md"))
        with self.assertRaisesRegex(WorkspaceWait, "invalid_spec"):
            self.workspace.read_spec(self.path, "README.md")

    def test_spec_index_lookup_uses_exact_literal_paths(self):
        for relative in (":(glob)*", "spec[1].md", "spec\tline\n.md"):
            with self.subTest(relative=relative):
                (self.path / relative).write_bytes(b"literal artifact")
                self.assertFalse(self.workspace.valid_spec(self.path, relative))
                git(self.path, "--literal-pathspecs", "add", "--", relative)
                self.assertTrue(self.workspace.valid_spec(self.path, relative))
                self.assertEqual(self.workspace.read_spec(self.path, relative), b"literal artifact")

    def test_read_spec_preserves_bytes_and_bounds_size(self):
        spec = self.path / "README.md"
        for content in (b"spec\x00\xff\n", b"x" * (1024 * 1024)):
            spec.write_bytes(content)
            self.assertEqual(self.workspace.read_spec(self.path, "README.md"), content)
        spec.write_bytes(b"x" * (1024 * 1024 + 1))
        with self.assertRaisesRegex(WorkspaceWait, "invalid_spec"):
            self.workspace.read_spec(self.path, "README.md")

    def test_spec_size_limit_applies_before_tracked_or_untracked_readiness(self):
        for relative in ("README.md", "candidate.md"):
            with self.subTest(relative=relative):
                spec = self.path / relative
                spec.write_bytes(b"x" * (1024 * 1024))
                self.assertTrue(self.workspace.valid_spec(self.path, relative, require_tracked=False))
                self.assertEqual(self.workspace.valid_spec(self.path, relative), relative == "README.md")
                spec.write_bytes(b"x" * (1024 * 1024 + 1))
                self.assertFalse(self.workspace.valid_spec(self.path, relative, require_tracked=False))
                self.assertFalse(self.workspace.valid_spec(self.path, relative))
                with self.assertRaisesRegex(WorkspaceWait, "invalid_spec"):
                    self.workspace.read_spec(self.path, relative)

    def test_read_spec_refuses_raced_fifo_and_symlink_without_blocking(self):
        spec = self.path / "README.md"
        outside = self.root / "outside.md"
        outside.write_bytes(b"must not be read")
        real_open = os.open
        for kind in ("fifo", "symlink"):
            if spec.exists() or spec.is_symlink():
                spec.unlink()
            spec.write_text("valid before open")
            opened = []
            def raced(name, flags, *args, **kwargs):
                if name == "README.md":
                    self.assertTrue(flags & os.O_NONBLOCK)
                    self.assertTrue(flags & os.O_NOFOLLOW)
                    self.assertIn("dir_fd", kwargs)
                    spec.unlink()
                    if kind == "fifo":
                        os.mkfifo(spec)
                    else:
                        spec.symlink_to(outside)
                    opened.append(kind)
                return real_open(name, flags, *args, **kwargs)
            with self.subTest(kind=kind), patch("hydra_sdlc.workspace.os.open", side_effect=raced):
                with self.assertRaisesRegex(WorkspaceWait, "invalid_spec"):
                    self.workspace.read_spec(self.path, "README.md")
            self.assertEqual(opened, [kind])

    def test_read_spec_refuses_parent_symlink_created_after_validation(self):
        docs = self.path / "docs"
        docs.mkdir()
        (docs / "spec.md").write_text("owned spec")
        git(self.path, "add", "docs/spec.md")
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "spec.md").write_text("must not be read")
        real_open = os.open
        traversals = []
        def raced(name, flags, *args, **kwargs):
            if name == "docs":
                traversals.append(name)
                self.assertTrue(flags & os.O_DIRECTORY)
                self.assertTrue(flags & os.O_NOFOLLOW)
                self.assertIn("dir_fd", kwargs)
                if len(traversals) == 2:
                    docs.rename(self.path / "original-docs")
                    docs.symlink_to(outside, target_is_directory=True)
            return real_open(name, flags, *args, **kwargs)
        with patch("hydra_sdlc.workspace.os.open", side_effect=raced):
            with self.assertRaisesRegex(WorkspaceWait, "invalid_spec"):
                self.workspace.read_spec(self.path, "docs/spec.md")
        self.assertEqual(len(traversals), 2)

    def test_read_spec_bounds_growth_after_descriptor_validation(self):
        spec = self.path / "README.md"
        real_fstat = os.fstat
        checks = []
        def grown(fd):
            info = real_fstat(fd)
            checks.append(fd)
            spec.write_bytes(b"x" * (1024 * 1024 + 1))
            return info
        with patch("hydra_sdlc.workspace.os.fstat", side_effect=grown):
            with self.assertRaisesRegex(WorkspaceWait, "invalid_spec"):
                self.workspace.read_spec(self.path, "README.md")
        self.assertEqual(len(checks), 1)

    def test_additional_push_destination_is_rejected(self):
        git(self.path, "remote", "set-url", "--add", "--push", "origin", str(self.remote))
        git(self.path, "remote", "set-url", "--add", "--push", "origin", "https://github.com/foreign/repo.git")
        with self.assertRaisesRegex(WorkspaceWait, "foreign_remote"):
            self.workspace.publish(self.path, "hydra/issue-1", None)

    def test_selected_auth_is_per_process_not_saved_or_returned(self):
        workspace = Workspace(self.root / "auth")
        token = b"private-test-token\n"
        with patch("hydra_sdlc.workspace.subprocess.run", return_value=subprocess.CompletedProcess([], 0, token, b"")) as call:
            env = workspace._auth_environment()
        self.assertEqual(call.call_args.args[0], ["gh", "auth", "token", "--hostname", "github.com", "--user", "openboa"])
        self.assertEqual(env["GH_TOKEN"], token.decode().strip())
        self.assertNotEqual(os.environ.get("GH_TOKEN"), token.decode().strip())


if __name__ == "__main__":
    unittest.main()
