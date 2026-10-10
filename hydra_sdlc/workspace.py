"""Owned issue checkouts and bounded service Git actions; no workflow journal.

The runner records publication intent before calling publish. Provider hooks are
trusted host settings, never values read from Issue text or the candidate tree.
Raw verification output remains process-local and is available to the reviewer
through verification_output, not through public result records.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
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


def _environment():
    env = dict(os.environ)
    for key in PUBLISH_TOKENS:
        env.pop(key, None)
    # A host invocation must not redirect Git into another index/repository.
    for key in list(env):
        if key.startswith("GIT_"):
            env.pop(key)
    env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
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
    without changing checkout contents. storage_provider.run(path, argv, cwd,
    timeout, *, stop_requested) must poll stop/deadline at most every 100ms,
    terminate its owned process group, and raise verification_stopped on stop.
    It returns a CompletedProcess (combined private output in stdout), or raises;
    timeout kills have a negative signal return code. Managed
    OpenBoa roots require these providers; the standalone fallback is explicit.
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

    def _git(self, path, *args, remote=False, check=True, publish_guard=None):
        env = self._auth_environment() if remote else _environment()
        options = ["-c", "core.hooksPath=/dev/null", "-c", "credential.helper="]
        if remote:
            options += ["-c", "credential.helper=!gh auth git-credential"]
        if publish_guard is None:
            result = _run(["git", *options, *args], path, GIT_TIMEOUT, env)
        else:
            branch, expected, head = publish_guard
            env.update(HYDRA_PUBLISH_REF="refs/heads/" + branch,
                       HYDRA_EXPECTED_REMOTE_SHA=expected or "0" * 40,
                       HYDRA_PUBLISH_SHA=head)
            # Bind the actual server advertisement, then let normal push's
            # receive-side old-object check close the remaining race. No force.
            with tempfile.TemporaryDirectory(prefix="hydra-publish-") as directory:
                hook = Path(directory) / "pre-push"
                hook.write_text("#!/bin/sh\nset -eu\ncount=0\n"
                    "while read -r local_ref local_sha remote_ref remote_sha; do\n"
                    "  test \"$remote_ref\" = \"$HYDRA_PUBLISH_REF\" || exit 1\n"
                    "  test \"$local_sha\" = \"$HYDRA_PUBLISH_SHA\" || exit 1\n"
                    "  test \"$remote_sha\" = \"$HYDRA_EXPECTED_REMOTE_SHA\" || exit 1\n"
                    "  count=$((count + 1))\ndone\ntest \"$count\" = 1\n")
                hook.chmod(0o700)
                options += ["-c", "core.hooksPath=" + directory]
                result = _run(["git", *options, *args], path, GIT_TIMEOUT, env)
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
        top = self._git(path, "rev-parse", "--show-toplevel").stdout.decode().strip()
        if Path(top).resolve() != path:
            raise WorkspaceWait("foreign_workspace")
        expected = {"repository": repo, "issue": issue[6:], "branch": branch, "owner": self.user}
        for key, value in expected.items():
            result = self._git(path, "config", "--local", "--get", self._marker(path, key), check=False)
            if result.returncode or result.stdout.decode().strip() != value:
                raise WorkspaceWait("foreign_workspace")
        origin = self._git(path, "remote", "get-url", "--all", "origin").stdout.decode().strip()
        push_origin = self._git(path, "remote", "get-url", "--push", "--all", "origin").stdout.decode().strip()
        if origin != self._url(repo) or push_origin != origin:
            raise WorkspaceWait("foreign_remote")
        current = self._git(path, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
        if current.returncode or current.stdout.decode().strip() != branch:
            raise WorkspaceWait("workspace_branch_changed")
        return path, repo, branch

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
        if self.lifecycle_provider is not None:
            provided = self.lifecycle_provider.prepare(repo, number, branch, expected_remote_sha, path)
            if Path(provided).absolute() != path:
                raise WorkspaceWait("lifecycle_provider_path_mismatch")
        else:
            self._git(path.parent, "clone", "--no-local", "--no-checkout", self._url(repo), str(path), remote=True)
            observed = self._remote_sha(path, branch)
            if observed != expected_remote_sha:
                raise WorkspaceWait("remote_head_changed")
            if expected_remote_sha is None:
                base = self._git(path, "symbolic-ref", "refs/remotes/origin/HEAD").stdout.decode().strip()
                self._git(path, "checkout", "-b", branch, base)
            else:
                self._git(path, "checkout", "-b", branch, expected_remote_sha)
        # Stamp only the newly allocated directory. An existing arbitrary tree is
        # never adopted just because its name resembles the deterministic path.
        if path != path.resolve() or not path.is_dir():
            raise WorkspaceWait("workspace_missing_or_aliased")
        if self._git(path, "status", "--porcelain=v1", "--untracked-files=all").stdout:
            raise WorkspaceWait("dirty_workspace")
        current = self._git(path, "symbolic-ref", "--short", "HEAD").stdout.decode().strip()
        if current != branch:
            raise WorkspaceWait("workspace_branch_changed")
        for key, value in {"repository": repo, "issue": str(number), "branch": branch, "owner": self.user}.items():
            self._git(path, "config", "--local", self._marker(path, key), value)
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
                result = (self.storage_provider.run(path, argv, cwd, timeout, stop_requested=stop_requested)
                          if self.storage_provider else _run(argv, cwd, timeout, stop_requested=stop_requested))
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

    def verification_output(self, digest):
        """Private reviewer material; never include this in GitHub progress."""
        if digest not in self._outputs:
            raise WorkspaceWait("verification_output_unavailable")
        return self._outputs[digest].decode(errors="replace")

    def changed_paths(self, path, base_sha):
        path, _, _ = self._identity(path)
        _sha(base_sha)
        self._git(path, "cat-file", "-e", base_sha + "^{commit}")
        tracked = self._git(path, "diff", "--name-only", "--no-renames", "--no-ext-diff",
                            "--no-textconv", "-z", base_sha, "--").stdout
        untracked = self._git(path, "ls-files", "--others", "--exclude-standard", "-z").stdout
        return sorted(set(item.decode() for item in (tracked + untracked).split(b"\0") if item))

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
