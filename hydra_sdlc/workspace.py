"""Owned issue checkouts and bounded service Git actions; no workflow journal.

The runner records publication intent before calling publish. Provider hooks are
trusted host settings, never values read from Issue text or the candidate tree.
Raw verification output remains process-local and is available to the reviewer
through verification_output, not through public result records.
"""

from __future__ import annotations

import hashlib
import ctypes
import errno
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time


class WorkspaceWait(RuntimeError):
    def __init__(self, reason: str, *, uncertain: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.uncertain = uncertain


PUBLISH_TOKENS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_SPEC_BYTES = 1024 * 1024
GIT_TIMEOUT = 60
MAX_GIT_CONFIG_BYTES = 1024 * 1024


def _git_file(path, *, optional=False, contents=True):
    """Read metadata without following aliases or blocking on special files."""
    path = Path(path)
    if path.parent != path.parent.resolve():
        raise WorkspaceWait("foreign_workspace")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        if optional:
            return None
        raise WorkspaceWait("foreign_workspace")
    except OSError as exc:
        raise WorkspaceWait("foreign_workspace") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or (contents and info.st_size > MAX_GIT_CONFIG_BYTES):
            raise WorkspaceWait("foreign_workspace")
        if not contents:
            return b""
        data = bytearray()
        while len(data) <= MAX_GIT_CONFIG_BYTES:
            chunk = os.read(descriptor, min(65536, MAX_GIT_CONFIG_BYTES + 1 - len(data)))
            if not chunk:
                return bytes(data)
            data.extend(chunk)
        raise WorkspaceWait("foreign_workspace")
    finally:
        os.close(descriptor)


def _promote_directory(source, destination):
    """Atomically publish a sibling directory without replacing any object."""
    source, destination = Path(source), Path(destination)
    if (source.parent != destination.parent or source != source.resolve()
            or destination.parent != destination.parent.resolve()):
        raise WorkspaceWait("workspace_missing_or_aliased")
    name, flags = {"darwin": ("renameatx_np", 4), "linux": ("renameat2", 1)}.get(sys.platform, (None, None))
    if name is None:
        raise WorkspaceWait("exclusive_rename_unavailable")
    try:
        rename = getattr(ctypes.CDLL(None, use_errno=True), name)
    except (AttributeError, OSError) as exc:
        raise WorkspaceWait("exclusive_rename_unavailable") from exc
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    parent = os.open(source.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        # Darwin RENAME_EXCL / Linux RENAME_NOREPLACE. No ordinary rename fallback.
        if rename(parent, os.fsencode(source.name), parent, os.fsencode(destination.name), flags):
            error = ctypes.get_errno()
            if error in {errno.EEXIST, errno.ENOTEMPTY}:
                raise WorkspaceWait("workspace_destination_exists")
            raise WorkspaceWait("exclusive_rename_unavailable")
    finally:
        os.close(parent)


def _environment():
    env = dict(os.environ)
    for key in PUBLISH_TOKENS:
        env.pop(key, None)
    # A host invocation must not redirect Git into another index/repository.
    for key in list(env):
        if key.startswith("GIT_"):
            env.pop(key)
    env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_NO_REPLACE_OBJECTS="1")
    return env


def _sha(value, *, absent=False):
    if absent and value is None:
        return value
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise WorkspaceWait("invalid_commit")
    return value


def _check_stop(stop_requested):
    if stop_requested is not None and stop_requested():
        raise WorkspaceWait("verification_stopped")


def _run(argv, cwd, timeout, env=None, *, stop_requested=None):
    """Bound command and descendants, retaining bounded private output only."""
    _check_stop(stop_requested)
    if stop_requested is not None:
        from .execution_boundary import OwnedCommandError, run_owned_sync
        try:
            return run_owned_sync(argv, cwd=cwd, env=env if env is not None else _environment(),
                                  timeout=timeout, stop_requested=stop_requested,
                                  max_output_bytes=MAX_OUTPUT_BYTES)
        except OwnedCommandError as exc:
            reason = {"stopped": "verification_stopped", "output_limit": "command_output_limit",
                      "cleanup_unknown": "verification_cleanup_unknown", "unavailable": "command_unavailable"}[exc.reason]
            raise WorkspaceWait(reason, uncertain=exc.reason == "cleanup_unknown") from exc
    try:
        process = subprocess.Popen(argv, cwd=cwd, env=env or _environment(),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as exc:
        raise WorkspaceWait("command_unavailable") from exc
    data = bytearray()
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                _check_stop(stop_requested)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(argv, timeout)
                events = selector.select(min(0.1, remaining))
                if events:
                    chunk = os.read(process.stdout.fileno(), min(65536, MAX_OUTPUT_BYTES + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > MAX_OUTPUT_BYTES:
                        raise WorkspaceWait("command_output_limit", uncertain=True)
                elif process.poll() is not None:
                    break
        if stop_requested is None:
            code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
        else:
            # A check may close stdout long before exiting; keep polling the
            # same stop predicate while waiting for that process as well.
            while process.poll() is None:
                _check_stop(stop_requested)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(argv, timeout)
                try:
                    process.wait(timeout=min(0.1, remaining))
                except subprocess.TimeoutExpired:
                    continue
            _check_stop(stop_requested)
            code = process.returncode
    except subprocess.TimeoutExpired:
        code = -signal.SIGKILL
    finally:
        # Includes children that outlive the direct parent or retain the pipe.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=2)
        process.stdout.close()
    return subprocess.CompletedProcess(argv, code, bytes(data))


class Workspace:
    """A single host's registered workspaces.

    lifecycle_provider.prepare(repo, number, branch, expected_remote_sha, path)
    must create/register exactly path, or raise when resources/ownership are not
    available. For an existing path it must validate the registered resources
    without changing checkout contents. storage_provider.wrap_command(path, argv,
    cwd) purely constructs a nonempty list of command arguments; it never executes
    commands or returns verification evidence. The runtime executes that wrapper
    at the owned worktree with its sanitized environment, original timeout, stop
    callback, output bound and owned-process cleanup. Managed
    OpenBoa roots require these providers; the standalone fallback is explicit.
    Optional issue_numbers(repo) discovers this provider owner's registered Issue
    resources. completed(repo, number, branch, head, pr_number, merge_sha, path)
    reconciles their normal release/retirement after verified product completion.
    """

    def __init__(self, root: Path, lifecycle_provider=None, storage_provider=None,
                 user="openboa"):
        root = Path(root).absolute()
        if root != root.resolve() or user != "openboa":
            raise WorkspaceWait("invalid_workspace_root_or_actor")
        self.root = root
        self.lifecycle_provider = lifecycle_provider
        self.storage_provider = storage_provider
        self.user = user
        self._outputs = {}

    def issue_numbers(self, repo):
        repo = self._repository(repo)
        discover = getattr(self.lifecycle_provider, "issue_numbers", None)
        if discover is None:
            return []
        numbers = discover(repo)
        if not isinstance(numbers, list) or any(type(n) is not int or n <= 0 for n in numbers):
            raise WorkspaceWait("resource_discovery_unavailable")
        return sorted(set(numbers))

    def completed(self, repo, number, branch, head, pr_number, merge_sha):
        complete = getattr(self.lifecycle_provider, "completed", None)
        if complete is None:
            return False
        repo = self._repository(repo)
        if (type(number) is not int or number <= 0 or branch != f"hydra/issue-{number}"
                or type(pr_number) is not int or pr_number <= 0):
            raise WorkspaceWait("invalid_issue_branch")
        _sha(head)
        _sha(merge_sha)
        path = self.root / repo / f"issue-{number}"
        if path != path.resolve():
            raise WorkspaceWait("workspace_missing_or_aliased")
        # The provider owns registry/read-back validation, including already
        # retired resources. Never recreate a missing checkout for cleanup.
        result = complete(repo, number, branch, head, pr_number, merge_sha, path)
        if not isinstance(result, dict) or result.get("retired") is not True:
            raise WorkspaceWait("resource_completion_unconfirmed")
        return True

    def _managed(self):
        return any((parent / ".workspace/storage.json").is_file()
                   for parent in (self.root, *self.root.parents))

    @staticmethod
    def _repository(repo):
        if not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise WorkspaceWait("invalid_repository")
        if any(part in (".", "..") or part.endswith(".git") for part in repo.split("/")):
            raise WorkspaceWait("invalid_repository")
        return repo

    def _url(self, repo):
        return "https://github.com/" + self._repository(repo) + ".git"

    def _auth_environment(self):
        env = _environment()
        try:
            response = subprocess.run(
                ["gh", "auth", "token", "--hostname", "github.com", "--user", self.user],
                env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise WorkspaceWait("authentication_unavailable") from exc
        token = response.stdout.decode(errors="replace").strip()
        if response.returncode or not token or "\n" in token:
            raise WorkspaceWait("authentication_unavailable")
        env["GH_TOKEN"] = token
        return env

    def _git_layout(self, path):
        path = Path(path).absolute()
        if path != path.resolve() or not path.is_dir():
            raise WorkspaceWait("workspace_missing_or_aliased")
        entry = path / ".git"
        if entry.is_dir() and not entry.is_symlink():
            gitdir = common = entry
            if (entry / "commondir").exists() or (entry / "commondir").is_symlink():
                raise WorkspaceWait("foreign_workspace")
        else:
            pointer = _git_file(entry)
            if self.lifecycle_provider is None or not pointer.startswith(b"gitdir: "):
                raise WorkspaceWait("foreign_workspace")
            gitdir = Path(os.path.abspath(path / os.fsdecode(pointer[8:].strip())))
            if gitdir != gitdir.resolve() or not gitdir.is_dir():
                raise WorkspaceWait("foreign_workspace")
            common = (gitdir / os.fsdecode(_git_file(gitdir / "commondir").strip())).resolve()
            backlink = (gitdir / os.fsdecode(_git_file(gitdir / "gitdir").strip())).resolve()
            if (gitdir.parent.name != "worktrees" or gitdir.parent.parent != common
                    or backlink != entry or common != common.resolve()):
                raise WorkspaceWait("foreign_workspace")
        for directory in (common, common / "objects", common / "refs"):
            if directory != directory.resolve() or not directory.is_dir():
                raise WorkspaceWait("foreign_workspace")
        _git_file(gitdir / "HEAD")
        for name in ("index", "FETCH_HEAD", "config.worktree"):
            _git_file(gitdir / name, optional=True, contents=False)
        if (_git_file(common / "shallow", optional=True)
                or _git_file(common / "objects/info/alternates", optional=True)):
            raise WorkspaceWait("unsupported_git_metadata")
        return gitdir, common

    def _git_config(self, common, directory):
        raw = _git_file(common / "config")
        snapshot = directory / "config-snapshot"
        snapshot.write_bytes(raw)
        result = _run(["git", "--no-replace-objects", "config", "--file", str(snapshot), "--no-includes", "--null", "--list"],
                      directory, GIT_TIMEOUT, _environment())
        if result.returncode:
            raise WorkspaceWait("invalid_git_config")
        values = {}
        try:
            for item in result.stdout.split(b"\0"):
                if item:
                    key, _, value = item.partition(b"\n")
                    values.setdefault(key.decode("utf-8"), []).append(value.decode("utf-8"))
        except UnicodeError as exc:
            raise WorkspaceWait("invalid_git_config") from exc
        if (values.get("core.repositoryformatversion", ["0"]) not in (["0"], ["1"])
                or values.get("extensions.objectformat", ["sha1"]) != ["sha1"]
                or values.get("extensions.refstorage", ["files"]) != ["files"]
                or any(key.startswith("extensions.") and key not in {
                    "extensions.objectformat", "extensions.refstorage", "extensions.worktreeconfig",
                } for key in values)):
            raise WorkspaceWait("unsupported_git_metadata")
        return raw, values, snapshot

    def _git_marker(self, common, directory, raw, values, snapshot, args):
        if (len(args) not in (3, 4) or args[:2] != ("config", "--local")):
            raise WorkspaceWait("invalid_git_config_operation")
        reading = len(args) == 4 and args[2] == "--get"
        key = args[3] if reading else args[2]
        if not re.fullmatch(r"hydra\.workspace-[0-9a-f]{64}\.(repository|issue|branch|owner)", key):
            raise WorkspaceWait("invalid_git_config_operation")
        if reading:
            found = values.get(key, [])
            return subprocess.CompletedProcess(args, 0 if len(found) == 1 else 1,
                                               (found[0] + "\n").encode() if len(found) == 1 else b"")
        if len(args) != 4:
            raise WorkspaceWait("invalid_git_config_operation")
        result = _run(["git", "--no-replace-objects", "config", "--file", str(snapshot), "--no-includes", "--replace-all", key, args[3]],
                      directory, GIT_TIMEOUT, _environment())
        if result.returncode:
            return result
        # Cooperate with Git's shared config lock and only replace the snapshot
        # we read. Other issue markers and unrelated configuration stay intact.
        lock = common / "config.lock"
        try:
            descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except OSError as exc:
            raise WorkspaceWait("git_config_changed") from exc
        locked = True
        try:
            if _git_file(common / "config") != raw:
                raise WorkspaceWait("git_config_changed")
            os.fchmod(descriptor, stat.S_IMODE((common / "config").stat().st_mode))
            with os.fdopen(descriptor, "wb") as target:
                descriptor = None
                target.write(snapshot.read_bytes())
            os.replace(lock, common / "config")
            locked = False
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if locked:
                lock.unlink(missing_ok=True)
        return result

    def _git(self, path, *args, remote=False, check=True, publish_guard=None):
        path = Path(path).absolute()
        with tempfile.TemporaryDirectory(prefix="hydra-git-") as temporary:
            directory = Path(temporary)
            env = _environment()
            options = ["-c", "core.hooksPath=/dev/null", "-c", "credential.helper=",
                       "-c", "protocol.allow=never", "-c", "protocol.https.allow=always",
                       "-c", "http.followRedirects=false", "-c", "gc.auto=0", "-c", "maintenance.auto=false",
                       "-c", "submodule.recurse=false", "-c", "fetch.recurseSubmodules=false"]
            clone = args and args[0] == "clone"
            if not clone:
                gitdir, common = self._git_layout(path)
                raw, values, snapshot = self._git_config(common, directory)
                if args[:2] == ("config", "--local"):
                    result = self._git_marker(common, directory, raw, values, snapshot, args)
                    if check and result.returncode:
                        raise WorkspaceWait("git_operation_failed")
                    return result
                # Expose data, never candidate config/includes, hooks, info or
                # legacy remote aliases. HEAD/index/FETCH_HEAD remain genuine.
                for name in ("objects", "refs", "logs"):
                    source = common / name
                    if source.exists():
                        if source != source.resolve() or not source.is_dir():
                            raise WorkspaceWait("foreign_workspace")
                        (directory / name).symlink_to(source, target_is_directory=True)
                packed = _git_file(common / "packed-refs", optional=True)
                if packed is not None:
                    (directory / "packed-refs").write_bytes(packed)
                (directory / "config").write_text("[core]\nrepositoryformatversion=0\nbare=false\nfsmonitor=false\n")
                env["GIT_COMMON_DIR"] = str(directory)
                options[:0] = ["--git-dir=" + str(gitdir), "--work-tree=" + str(path)]
                index = _run(["git", "--no-replace-objects", *options, "ls-files", "--stage", "-z"], path, GIT_TIMEOUT, env)
                if index.returncode:
                    raise WorkspaceWait("git_operation_failed")
                if any(item.startswith(b"160000 ") for item in index.stdout.split(b"\0")):
                    # Nested Git commands can discard the parent's isolated
                    # configuration. Submodule execution is not supported here.
                    raise WorkspaceWait("unsupported_git_metadata")
                if args and args[0] == "remote":
                    # Preserve identity validation without interpreting URL
                    # rewrites or invoking a transport from candidate config.
                    key = "remote.origin.pushurl" if "--push" in args else "remote.origin.url"
                    found = values.get(key, values.get("remote.origin.url", []))
                    return subprocess.CompletedProcess(args, 0, ("\n".join(found) + "\n").encode())
            if remote:
                parts = path.relative_to(self.root).parts
                repo = self._repository("/".join(parts[:2]))
                url = self._url(repo)
                args = tuple(url if value == "origin" else value for value in args)
                # The existing trusted local test transport overrides _url;
                # production's implementation always returns canonical HTTPS.
                if Path(url).is_absolute() and type(self)._url is not Workspace._url:
                    options += ["-c", "protocol.file.allow=always"]
                elif url != Workspace._url(self, repo):
                    raise WorkspaceWait("foreign_remote")
                if clone:
                    args = (*args[:1], "--template=", *args[1:])
                authenticated = self._auth_environment()
                authenticated.update(env)
                env = authenticated
                options += ["-c", "credential.helper=!gh auth git-credential"]
            if publish_guard is not None:
                branch, expected, head = publish_guard
                env.update(HYDRA_PUBLISH_REF="refs/heads/" + branch,
                           HYDRA_EXPECTED_REMOTE_SHA=expected or "0" * 40,
                           HYDRA_PUBLISH_SHA=head)
                hooks = directory / "hooks"
                hooks.mkdir()
                hook = hooks / "pre-push"
                hook.write_text("#!/bin/sh\nset -eu\ncount=0\n"
                    "while read -r local_ref local_sha remote_ref remote_sha; do\n"
                    "  test \"$remote_ref\" = \"$HYDRA_PUBLISH_REF\" || exit 1\n"
                    "  test \"$local_sha\" = \"$HYDRA_PUBLISH_SHA\" || exit 1\n"
                    "  test \"$remote_sha\" = \"$HYDRA_EXPECTED_REMOTE_SHA\" || exit 1\n"
                    "  count=$((count + 1))\ndone\ntest \"$count\" = 1\n")
                hook.chmod(0o700)
                options += ["-c", "core.hooksPath=" + str(hooks)]
            result = _run(["git", "--no-replace-objects", *options, *args], directory if clone else path, GIT_TIMEOUT, env)
        if check and result.returncode:
            raise WorkspaceWait("git_operation_failed", uncertain=remote)
        return result

    def _remote_sha(self, path, branch):
        result = self._git(path, "ls-remote", "--exit-code", "origin", "refs/heads/" + branch,
                           remote=True, check=False)
        if result.returncode == 2 and not result.stdout:
            return None
        if result.returncode:
            raise WorkspaceWait("remote_observation_unavailable", uncertain=True)
        rows = result.stdout.decode().splitlines()
        if len(rows) != 1:
            raise WorkspaceWait("ambiguous_remote_ref", uncertain=True)
        fields = rows[0].split("\t")
        if len(fields) != 2 or fields[1] != "refs/heads/" + branch:
            raise WorkspaceWait("invalid_remote_ref", uncertain=True)
        return _sha(fields[0])

    def _identity(self, path):
        path = Path(path).absolute()
        if path != path.resolve() or not path.is_dir():
            raise WorkspaceWait("workspace_missing_or_aliased")
        try:
            owner, name, issue = path.relative_to(self.root).parts
        except ValueError as exc:
            raise WorkspaceWait("foreign_workspace") from exc
        repo = self._repository(owner + "/" + name)
        if not re.fullmatch(r"issue-[1-9][0-9]*", issue):
            raise WorkspaceWait("foreign_workspace")
        branch = "hydra/" + issue
        self._checkout_identity(path, repo, issue[6:], branch, marker_path=path)
        return path, repo, branch

    def _checkout_identity(self, path, repo, number, branch, *, marker_path):
        top = self._git(path, "rev-parse", "--show-toplevel").stdout.decode().strip()
        if Path(top).resolve() != path:
            raise WorkspaceWait("foreign_workspace")
        expected = {"repository": repo, "issue": str(number), "branch": branch, "owner": self.user}
        for key, value in expected.items():
            result = self._git(path, "config", "--local", "--get", self._marker(marker_path, key), check=False)
            if result.returncode or result.stdout.decode().strip() != value:
                raise WorkspaceWait("foreign_workspace")
        origin = self._git(path, "remote", "get-url", "--all", "origin").stdout.decode().strip()
        push_origin = self._git(path, "remote", "get-url", "--push", "--all", "origin").stdout.decode().strip()
        if origin != self._url(repo) or push_origin != origin:
            raise WorkspaceWait("foreign_remote")
        current = self._git(path, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
        if current.returncode or current.stdout.decode().strip() != branch:
            raise WorkspaceWait("workspace_branch_changed")

    @staticmethod
    def _marker(path, key):
        # Linked worktrees share local Git configuration. Key by canonical path
        # so independent issues cannot overwrite each other's resource identity.
        identity = hashlib.sha256(os.fsencode(path)).hexdigest()
        return "hydra.workspace-" + identity + "." + key

    def prepare(self, repo, number, branch, expected_remote_sha, *, recover_dirty=False):
        """Prepare an owned checkout, optionally preserving a stopped worker's edits.

        The caller may enable recovery only for an authorized stopped-worker
        handover or a locally supervised stopped checkpoint. This flag supplies
        no takeover or adoption authority.
        """
        repo = self._repository(repo)
        if type(number) is not int or number <= 0 or branch != "hydra/issue-" + str(number):
            raise WorkspaceWait("invalid_issue_branch")
        if type(recover_dirty) is not bool:
            raise WorkspaceWait("invalid_recovery_flag")
        _sha(expected_remote_sha, absent=True)
        path = self.root / repo / ("issue-" + str(number))
        if path.exists() or path.is_symlink():
            observed = self.inspect(path)
            if observed["dirty"] and not recover_dirty:
                raise WorkspaceWait("dirty_workspace")
            if observed["remote_sha"] != expected_remote_sha:
                raise WorkspaceWait("remote_head_changed")
            if self._managed() and self.lifecycle_provider is None:
                raise WorkspaceWait("lifecycle_provider_required")
            if self.lifecycle_provider is not None:
                provided = self.lifecycle_provider.prepare(repo, number, branch, expected_remote_sha, path)
                if Path(provided).absolute() != path:
                    raise WorkspaceWait("lifecycle_provider_path_mismatch")
                if self.inspect(path) != observed:
                    raise WorkspaceWait("workspace_changed_during_validation")
            return path
        if recover_dirty:
            raise WorkspaceWait("recovery_workspace_missing")
        if path != path.resolve():
            raise WorkspaceWait("workspace_missing_or_aliased")
        if self._managed() and self.lifecycle_provider is None:
            raise WorkspaceWait("lifecycle_provider_required")
        path.parent.mkdir(parents=True, exist_ok=True)
        allocation = path
        if self.lifecycle_provider is not None:
            provided = self.lifecycle_provider.prepare(repo, number, branch, expected_remote_sha, path)
            if Path(provided).absolute() != path:
                raise WorkspaceWait("lifecycle_provider_path_mismatch")
        else:
            # Retain interrupted allocations. Their names grant no ownership and
            # a restart creates fresh staging rather than adopting or deleting them.
            allocation = Path(tempfile.mkdtemp(prefix="." + path.name + "-allocation-", dir=path.parent))
            self._git(path.parent, "clone", "--no-local", "--no-checkout", self._url(repo), str(allocation), remote=True)
            observed = self._remote_sha(allocation, branch)
            if observed != expected_remote_sha:
                raise WorkspaceWait("remote_head_changed")
            if expected_remote_sha is None:
                base = self._git(allocation, "symbolic-ref", "refs/remotes/origin/HEAD").stdout.decode().strip()
                self._git(allocation, "checkout", "-b", branch, base)
            else:
                self._git(allocation, "checkout", "-b", branch, expected_remote_sha)
            git_directory = allocation / ".git"
            _, common = self._git_layout(allocation)
            if (not git_directory.is_dir() or git_directory.is_symlink()
                    or common != git_directory):
                raise WorkspaceWait("foreign_workspace")
        # Stamp only the newly allocated directory. An existing arbitrary tree is
        # never adopted just because its name resembles the deterministic path.
        if allocation != allocation.resolve() or not allocation.is_dir():
            raise WorkspaceWait("workspace_missing_or_aliased")
        if self._git(allocation, "status", "--porcelain=v1", "--untracked-files=all").stdout:
            raise WorkspaceWait("dirty_workspace")
        current = self._git(allocation, "symbolic-ref", "--short", "HEAD").stdout.decode().strip()
        if current != branch:
            raise WorkspaceWait("workspace_branch_changed")
        for key, value in {"repository": repo, "issue": str(number), "branch": branch, "owner": self.user}.items():
            self._git(allocation, "config", "--local", self._marker(path, key), value)
        if allocation != path:
            self._checkout_identity(allocation, repo, number, branch, marker_path=path)
            head = _sha(self._git(allocation, "rev-parse", "--verify", "HEAD^{commit}").stdout.decode().strip())
            if expected_remote_sha is not None and head != expected_remote_sha:
                raise WorkspaceWait("remote_head_changed")
            if self._remote_sha(allocation, branch) != expected_remote_sha:
                raise WorkspaceWait("remote_head_changed")
            _promote_directory(allocation, path)
        self._identity(path)
        if self._remote_sha(path, branch) != expected_remote_sha:
            raise WorkspaceWait("remote_head_changed")
        return path

    def inspect(self, path):
        path, _, branch = self._identity(path)
        return {"head": _sha(self._git(path, "rev-parse", "HEAD").stdout.decode().strip()),
                "dirty": bool(self._git(path, "status", "--porcelain=v1", "--untracked-files=all").stdout),
                "branch": branch, "remote_sha": self._remote_sha(path, branch)}

    def contains_base(self, path, expected_base_sha):
        """Whether the owned head descends from this exact local commit."""
        path, _, _ = self._identity(path)
        _sha(expected_base_sha)
        kind = self._git(path, "--no-replace-objects", "cat-file", "-t", expected_base_sha).stdout
        if kind.strip() != b"commit":
            raise WorkspaceWait("invalid_commit")
        head = _sha(self._git(path, "rev-parse", "--verify", "HEAD^{commit}").stdout.decode().strip())
        result = self._git(path, "--no-replace-objects", "merge-base", "--is-ancestor",
                           expected_base_sha, head, check=False)
        if result.returncode not in (0, 1):
            raise WorkspaceWait("git_operation_failed")
        return result.returncode == 0

    def valid_spec(self, path, relative, *, require_tracked=True):
        """Inspect a regular nonempty artifact without opening its contents."""
        path, _, _ = self._identity(path)
        if (type(require_tracked) is not bool or not isinstance(relative, str)
                or "\0" in relative or "\\" in relative
                or any(part in ("", ".", "..") or part.casefold() == ".git"
                       for part in relative.split("/"))):
            return False
        parts = relative.split("/")
        directory = None
        try:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            directory = os.open(path, flags)
            for part in parts[:-1]:
                child = os.open(part, flags, dir_fd=directory)
                os.close(directory)
                directory = child
            info = os.stat(parts[-1], dir_fd=directory, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_SPEC_BYTES:
                return False
        except OSError:
            return False
        finally:
            if directory is not None:
                os.close(directory)
        if not require_tracked:
            return True
        entries = self._git(path, "--literal-pathspecs", "ls-files", "--stage", "-z", "--", relative).stdout.split(b"\0")
        if len(entries) != 2 or entries[-1]:
            return False
        metadata, separator, name = entries[0].partition(b"\t")
        fields = metadata.split()
        return (separator == b"\t" and name == os.fsencode(relative) and len(fields) == 3
                and fields[0] in (b"100644", b"100755") and fields[2] == b"0"
                and re.fullmatch(rb"[0-9a-f]{40}", fields[1]) is not None
                and fields[1] != b"0" * 40)

    def read_spec(self, path, relative):
        """Read at most 1 MiB from a tracked spec without following aliases."""
        if not self.valid_spec(path, relative):
            raise WorkspaceWait("invalid_spec")
        directory = source = None
        try:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            directory = os.open(Path(path).absolute(), flags)
            parts = relative.split("/")
            for part in parts[:-1]:
                child = os.open(part, flags, dir_fd=directory)
                os.close(directory)
                directory = child
            source = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            info = os.fstat(source)
            limit = MAX_SPEC_BYTES
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
                raise WorkspaceWait("invalid_spec")
            data = bytearray()
            while len(data) <= limit:
                chunk = os.read(source, min(65536, limit + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            if not data or len(data) > limit:
                raise WorkspaceWait("invalid_spec")
            return bytes(data)
        except OSError as exc:
            raise WorkspaceWait("invalid_spec") from exc
        finally:
            if source is not None:
                os.close(source)
            if directory is not None:
                os.close(directory)

    def fetch_base(self, path, expected_base_sha):
        """Prepare one observed base commit for offline integration by the worker.

        Fetch supplies no destination ref and never checks out or merges. The
        runner decides whether and when the owned issue branch should integrate
        this base; provider completion remains separate from that decision.
        """
        path, _, _ = self._identity(path)
        _sha(expected_base_sha)
        self._git(path, "fetch", "--no-tags", "--recurse-submodules=no", "origin", expected_base_sha, remote=True)
        observed = self._git(path, "rev-parse", "--verify", "FETCH_HEAD^{commit}").stdout.decode().strip()
        if observed != expected_base_sha:
            raise WorkspaceWait("fetched_base_mismatch")
        return _sha(observed)

    def verify(self, path, commands, *, stop_requested=None):
        if stop_requested is None:
            stop_requested = lambda: False
        if not callable(stop_requested):
            raise WorkspaceWait("invalid_verification_stop")
        _check_stop(stop_requested)
        path, _, _ = self._identity(path)
        if not isinstance(commands, list) or not commands or len(commands) > 64:
            raise WorkspaceWait("verification_policy_missing")
        if self._managed() and self.storage_provider is None:
            raise WorkspaceWait("storage_provider_required")
        prepared = []
        for command in commands:
            if not isinstance(command, dict) or set(command) - {"argv", "cwd", "timeout"}:
                raise WorkspaceWait("invalid_verification_command")
            argv, relative, timeout = command.get("argv"), command.get("cwd", "."), command.get("timeout", 300)
            if (not isinstance(argv, list) or not argv or
                    not all(isinstance(arg, str) and arg and "\0" not in arg for arg in argv) or
                    not isinstance(relative, str) or Path(relative).is_absolute() or
                    type(timeout) not in (int, float) or not 0 < timeout <= 3600):
                raise WorkspaceWait("invalid_verification_command")
            cwd = (path / relative).resolve()
            if not cwd.is_relative_to(path) or not cwd.is_dir():
                raise WorkspaceWait("verification_cwd_outside_workspace")
            prepared.append((list(argv), cwd, timeout))
        records = []
        for argv, cwd, timeout in prepared:
            _check_stop(stop_requested)
            try:
                execution_argv, execution_cwd = argv, cwd
                if self.storage_provider is not None:
                    wrap = getattr(self.storage_provider, "wrap_command", None)
                    if not callable(wrap):
                        raise WorkspaceWait("invalid_storage_provider_contract")
                    execution_argv = wrap(path, list(argv), cwd)
                    if (not isinstance(execution_argv, list) or not execution_argv
                            or not all(isinstance(arg, str) and arg and "\0" not in arg for arg in execution_argv)):
                        raise WorkspaceWait("invalid_storage_provider_contract")
                    execution_argv, execution_cwd = list(execution_argv), path
                _check_stop(stop_requested)
                result = _run(execution_argv, execution_cwd, timeout, env=_environment(),
                              stop_requested=stop_requested)
            except (OSError, subprocess.SubprocessError) as exc:
                raise WorkspaceWait("verification_unavailable") from exc
            _check_stop(stop_requested)
            output = result.stdout or b""
            if isinstance(output, str):
                output = output.encode()
            if not isinstance(output, bytes) or len(output) > MAX_OUTPUT_BYTES or type(result.returncode) is not int:
                raise WorkspaceWait("invalid_verification_result")
            digest = hashlib.sha256(output).hexdigest()
            self._outputs[digest] = output
            records.append({"argv": argv, "cwd": str(cwd.relative_to(path)),
                            "exit_code": result.returncode, "passed": result.returncode == 0,
                            "output_digest": digest})
            if result.returncode < 0:
                break
        return records

    def verification_output(self, digest, *, max_chars=None):
        """Private reviewer material; never include this in GitHub progress."""
        if digest not in self._outputs:
            raise WorkspaceWait("verification_output_unavailable")
        if max_chars is not None:
            if type(max_chars) is not int or max_chars < 0:
                raise ValueError("max_chars must be a nonnegative integer or None")
            return self._outputs[digest][:4 * max_chars].decode(errors="replace")[:max_chars]
        return self._outputs[digest].decode(errors="replace")

    def changed_paths(self, path, base_sha):
        path, _, _ = self._identity(path)
        _sha(base_sha)
        self._git(path, "cat-file", "-e", base_sha + "^{commit}")
        tracked = self._git(path, "diff", "--name-only", "--no-renames", "--no-ext-diff",
                            "--no-textconv", "-z", base_sha, "--").stdout
        untracked = self._git(path, "ls-files", "--others", "--exclude-standard", "-z").stdout
        return sorted(set(os.fsdecode(item) for item in (tracked + untracked).split(b"\0") if item))

    def checkpoint(self, path, message):
        path, _, _ = self._identity(path)
        if not isinstance(message, str) or not message.strip() or len(message) > 1024 or "\0" in message:
            raise WorkspaceWait("invalid_checkpoint_message")
        self._git(path, "add", "--all", "--", ".")
        changed = self._git(path, "diff", "--cached", "--quiet", check=False)
        if changed.returncode not in (0, 1):
            raise WorkspaceWait("git_operation_failed")
        if changed.returncode:
            self._git(path, "-c", "commit.gpgsign=false", "-c", "user.name=Hydra",
                      "-c", "user.email=openboa@users.noreply.github.com", "commit", "-m", message)
        return _sha(self._git(path, "rev-parse", "HEAD").stdout.decode().strip())

    def publish(self, path, branch, expected_remote_sha):
        path, _, owned_branch = self._identity(path)
        _sha(expected_remote_sha, absent=True)
        if branch != owned_branch:
            raise WorkspaceWait("foreign_publish_branch")
        if self._git(path, "status", "--porcelain=v1", "--untracked-files=all").stdout:
            raise WorkspaceWait("dirty_workspace")
        head = _sha(self._git(path, "rev-parse", "HEAD").stdout.decode().strip())
        observed = self._remote_sha(path, branch)
        if observed == head:
            return head  # Matching read-back after a previous lost response.
        if observed != expected_remote_sha:
            raise WorkspaceWait("remote_head_changed")
        if observed is not None:
            self._git(path, "fetch", "--no-tags", "origin", "refs/heads/" + branch, remote=True)
            if self._git(path, "merge-base", "--is-ancestor", observed, head, check=False).returncode:
                raise WorkspaceWait("non_fast_forward_publish")
        try:
            result = self._git(path, "push", "--no-follow-tags", "--recurse-submodules=no",
                               "origin", head + ":refs/heads/" + branch,
                               remote=True, check=False, publish_guard=(branch, expected_remote_sha, head))
        except WorkspaceWait:
            result = None
        # Every response, including transport loss, is reconciled exactly once.
        # The runner owns the pending service action and any bounded later retry.
        try:
            readback = self._remote_sha(path, branch)
        except WorkspaceWait as exc:
            raise WorkspaceWait("publish_unknown", uncertain=True) from exc
        if readback == head:
            return head
        if result is None or result.returncode == 0:
            raise WorkspaceWait("publish_unknown", uncertain=True)
        raise WorkspaceWait("publish_rejected" if readback == expected_remote_sha else "remote_head_changed")
