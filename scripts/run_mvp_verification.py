#!/usr/bin/env python3
"""Strict selected unittest evidence. This is neither a sandbox nor CI authority.

Only repository test methods are selectable. Test output is deliberately discarded;
debug failures with the ordinary private test runner, never a public traceback.
"""

import sys

# Check before importing any script-directory-shadowable module. Registered entry
# points use -I; invoking this file without isolation cannot execute its imports.
if __name__ == "__main__" and not sys.flags.isolated:
    sys.stdout.write('{"reason": "isolated_python_required", "status": "FAIL"}\n')
    raise SystemExit(2)

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import functools
import hashlib
import importlib
import importlib.machinery
import importlib.util
import inspect
import json
import os
from pathlib import Path
import re
import secrets
import selectors
import signal
import stat
import struct
import subprocess
import tempfile
import threading
import time
import unittest


VERSION = 1
MANIFEST = "tests/fixtures/mvp/verification/cases.json"
SCRIPT = "scripts/run_mvp_verification.py"
POLICY = ".github/workflows/ci.yml"
ARTIFACT = Path("artifacts/mvp-verification")
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
RUN = re.compile(r"verification-[0-9a-f]{32}\Z")
CASE = re.compile(r"[A-Z][A-Z0-9-]{1,63}\Z")
SELECTOR = re.compile(r"test_[a-z0-9_]+\.[A-Za-z][A-Za-z0-9_]*\.test_[a-z0-9_]+\Z")
REASONS = {"passed", "test_failure", "test_error", "required_skipped", "expected_failure",
           "unexpected_success", "interrupted", "not_executed", "collection_invalid"}
_REASON_CODES = tuple(sorted(REASONS))
_SELECTOR_PACKET = struct.Struct('!4s10I')
EXCLUSIONS = {"unselected_v1_requirements", "live_model_evaluation", "native_operation",
              "verify_only_command", "trusted_ci_attestation"}
LIMITATIONS = sorted(EXCLUSIONS)
_TERMINATION_REQUESTED = False
_SELECTOR_SHUTDOWN_STARTED = False
_INPUT_LIMIT = 262144
# One accepted selector plus a separately bounded root/pins/framing envelope.
# The manifest limit remains unchanged; private transport is not a new input cap.
_WORKER_INPUT_LIMIT = 2 * _INPUT_LIMIT
_MAX_CASES = 64
_MAX_SELECTORS = 32
_ENVIRONMENT_EXIT = 75
# A report repeats manifest-controlled tokens at most twice. Allow 1 KiB of
# fixed outcome/count/reason formatting per method, 8 KiB per case and 4 KiB
# for the root envelope. This covers the full accepted manifest, including
# indented export, without relaxing the separate manifest/request input bound.
_REPORT_LIMIT = 2 * _INPUT_LIMIT + _MAX_CASES * (_MAX_SELECTORS * 1024 + 8192) + 4096


class Invalid(Exception):
    """No exception text is part of the public protocol."""


class EnvironmentUnavailable(OSError):
    """Known verification infrastructure is unavailable; never expose its text."""


def require(value):
    if not value:
        raise Invalid()


def sha256(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def git(root, *args):
    result = subprocess.run(["git", "--no-replace-objects", "-C", str(root), *args], capture_output=True, timeout=15)
    require(result.returncode == 0)
    return result.stdout


def regular(root, relative):
    require(isinstance(relative, str) and len(relative) <= 240)
    path = Path(relative)
    require(not path.is_absolute() and all(part not in {".", ".."} for part in path.parts))
    current = root
    for part in path.parts:
        current = current / part
        require(not current.is_symlink())
    require(current.is_file())
    return current


def decode_json(data, *, limit=_INPUT_LIMIT):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result)
            result[key] = value
        return result
    require(len(data.encode('utf-8') if isinstance(data, str) else data) <= limit)
    return json.loads(data, object_pairs_hook=unique)


def read_json(path, *, limit=_INPUT_LIMIT, dir_fd=None):
    # O_NONBLOCK makes FIFO/device rejection immediate; inspect the opened inode,
    # not a path stat followed by a potentially different blocking open.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    try:
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_size <= limit)
    except BaseException:
        os.close(descriptor)
        raise
    with os.fdopen(descriptor, "rb") as stream:
        return decode_json(stream.read(limit + 1).decode("utf-8"), limit=limit)


def section_anchors(text):
    """Resolve top-level CommonMark headings without rendering or fetching links."""
    try:
        from markdown_it import MarkdownIt
    except ImportError as error:
        raise EnvironmentUnavailable() from error
    try:
        tokens = MarkdownIt('commonmark').parse(text)
    except (ValueError, RecursionError) as error:
        raise Invalid() from error
    anchors = set()
    for index, token in enumerate(tokens):
        if token.type != 'heading_open' or token.level != 0:
            continue
        inline = tokens[index + 1]
        heading = ''.join(child.content if child.type in {'text', 'code_inline', 'image'}
            else ' ' if child.type in {'softbreak', 'hardbreak'} else ''
            for child in (inline.children or [])).strip()
        slug = re.sub(r'[^\w -]', '', heading.lower()).replace(' ', '-')
        candidate, suffix = slug, 0
        while candidate in anchors:
            suffix += 1
            candidate = slug + '-' + str(suffix)
        anchors.add(candidate)
    return anchors


def load_manifest(root):
    value = read_json(regular(root, MANIFEST))
    require(type(value) is dict and set(value) == {"schema_version", "scope", "excluded", "cases"})
    require(type(value["schema_version"]) is int and value["schema_version"] == VERSION)
    require(value["scope"] == "selected_source_d" and value["excluded"] == LIMITATIONS)
    cases = value["cases"]
    require(type(cases) is list and 0 < len(cases) <= _MAX_CASES)
    ids, selectors = set(), set()
    for case in cases:
        require(type(case) is dict and set(case) == {"case_id", "requirements", "selectors", "fixture"})
        require(isinstance(case["case_id"], str) and CASE.fullmatch(case["case_id"]))
        require(case["case_id"] not in ids)
        ids.add(case["case_id"])
        require(type(case["requirements"]) is list and 0 < len(case["requirements"]) <= 8)
        for ref in case["requirements"]:
            require(type(ref) is dict and set(ref) == {"path", "revision", "section"})
            require(isinstance(ref["path"], str) and re.fullmatch(r"docs/[a-z0-9_/-]+\.md", ref["path"]))
            require(isinstance(ref["section"], str) and re.fullmatch(r"[a-z0-9-]{1,96}", ref["section"]))
            require(isinstance(ref["revision"], str) and DIGEST.fullmatch(ref["revision"]))
            document = regular(root, ref["path"]).read_bytes()
            require(sha256(document) == ref["revision"])
            require(ref["section"] in section_anchors(document.decode("utf-8")))
        require(type(case["selectors"]) is list and 0 < len(case["selectors"]) <= _MAX_SELECTORS)
        for selector in case["selectors"]:
            require(isinstance(selector, str) and SELECTOR.fullmatch(selector))
            require(selector not in selectors)
            selectors.add(selector)
            regular(root, "tests/" + selector.split(".")[0] + ".py")
        require(isinstance(case["fixture"], str) and re.fullmatch(
            r"tests/fixtures/mvp/verification/[a-z0-9_-]+\.json", case["fixture"]))
        fixture = read_json(regular(root, case["fixture"]))
        require(type(fixture) is dict and set(fixture) == {"case_id", "kind", "scenarios",
            "preconditions", "events", "expected", "forbidden_effects", "oracle", "scope"})
        require(fixture["case_id"] == case["case_id"] and fixture["kind"] == "D")
        scenarios = fixture["scenarios"]
        require(type(scenarios) is list and 0 < len(scenarios) <= 30)
        require(all(isinstance(item, str) and re.fullmatch(r"S(?:0[1-9]|[12][0-9]|30)", item)
                    for item in scenarios) and len(set(scenarios)) == len(scenarios))
        for field in ("preconditions", "events", "expected", "forbidden_effects"):
            require(type(fixture[field]) is list and fixture[field])
            require(all(isinstance(item, str) and item.strip() for item in fixture[field]))
        for field in ("oracle", "scope"):
            require(isinstance(fixture[field], str) and fixture[field].strip())
    return value


def binding(root, manifest, checked, base, source, *, inputs=None):
    head = git(root, "rev-parse", "HEAD").decode("ascii").strip()
    require(SHA.fullmatch(head) and (checked is None or checked == head))
    for revision in (base, source):
        require(revision is None or (isinstance(revision, str) and SHA.fullmatch(revision) and revision != "0" * 40))
    tree = {}
    for entry in git(root, "ls-tree", "-r", "-z", "HEAD").split(b"\0"):
        if not entry:
            continue
        metadata, path = entry.split(b"\t", 1)
        mode, kind, object_id = metadata.decode("ascii").split()
        require(kind == "blob" and mode in {"100644", "100755", "120000"})
        tree[path.decode("utf-8")] = (mode, object_id)
    paths, tracked = set(tree), set(tree)
    paths.update({SCRIPT, MANIFEST, POLICY})
    paths.update(importable_paths(root))
    for case in manifest["cases"]:
        paths.add(case["fixture"])
        paths.update(ref["path"] for ref in case["requirements"])
        paths.update("tests/" + selector.split(".")[0] + ".py" for selector in case["selectors"])
    require(paths <= tracked)
    git(root, "diff", "--quiet", "--no-ext-diff", "--no-textconv", "HEAD", "--")
    digest = hashlib.sha256()
    for path in sorted(paths):
        # Compare real bytes and modes to HEAD, independent of index stat hints.
        digest.update(path.encode("utf-8") + b"\0")
        target = root / path
        mode, expected_blob = tree[path]
        if target.is_symlink():
            require(mode == "120000" and not path.endswith(".py"))
            data = os.readlink(target).encode("utf-8")
        else:
            require(mode in {"100644", "100755"})
            data = regular(root, path).read_bytes()
            actual_mode = "100755" if target.stat().st_mode & 0o111 else "100644"
            require(actual_mode == mode)
        actual_blob = hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
        require(actual_blob == expected_blob)
        digest.update(mode.encode("ascii") + b"\0" + data)
        digest.update(b"\0")
    # Catch ordinary background writes to an already-scanned path. Actual test
    # imports also use a separate read-only Git snapshot, never these live files.
    git(root, "diff", "--quiet", "--no-ext-diff", "--no-textconv", "HEAD", "--")
    require(importable_paths(root) <= tracked)
    inputs = root if inputs is None else inputs
    return {"candidate_head": head, "source_head": source or head, "base_sha": base,
            "base_reason": None if base else "not_supplied", "source_revision": "sha256:" + digest.hexdigest(),
            "manifest_revision": sha256(regular(inputs, MANIFEST).read_bytes()),
            "policy_revision": sha256(regular(inputs, POLICY).read_bytes())}


def importable_paths(root):
    suffixes = tuple(importlib.machinery.all_suffixes())
    paths = {path.relative_to(root).as_posix() for path in root.iterdir()
             if (path.is_file() or path.is_symlink()) and path.name.endswith(suffixes)}
    # Preserve the registered source roots. Packaging outputs are not imports:
    # execution below uses only the Git snapshot, with no live-root sys.path.
    for name in ("hydra_sdlc", "tests", "scripts"):
        for folder, directories, files in os.walk(root / name, followlinks=False):
            # Warm PEP 3147 caches are not import inputs: the Git-only snapshot
            # contains none of these untracked files and disables cache writes.
            directories[:] = [entry for entry in directories if entry != "__pycache__"]
            for filename in files:
                if filename.endswith(suffixes):
                    paths.add((Path(folder) / filename).relative_to(root).as_posix())
    return paths


@contextmanager
def source_snapshot(root, head):
    """Materialize Git objects as read-only inputs, not immutable same-user files."""
    with tempfile.TemporaryDirectory(prefix="hydra-source-") as temp:
        snapshot, directories, links = Path(temp), set(), []
        directories.add(snapshot)
        try:
            for entry in git(root, "ls-tree", "-r", "-z", head).split(b"\0"):
                if not entry:
                    continue
                metadata, raw_name = entry.split(b"\t", 1)
                mode, kind, object_id = metadata.decode("ascii").split()
                name = Path(raw_name.decode("utf-8"))
                require(not name.is_absolute() and not any(part in {"..", ".git"} for part in name.parts))
                require(kind == "blob" and mode in {"100644", "100755", "120000"})
                target = snapshot / name
                for parent in reversed(target.parents):
                    if parent == snapshot or snapshot in parent.parents:
                        require(not parent.is_symlink())
                        parent.mkdir(exist_ok=True)
                        directories.add(parent)
                data = git(root, "cat-file", "blob", object_id)
                require(not target.exists() and not target.is_symlink())
                if mode == "120000":
                    target.symlink_to(data.decode("utf-8"))
                    links.append(target)
                else:
                    target.write_bytes(data)
                    target.chmod(0o555 if mode == "100755" else 0o444)
            require(all(path.resolve().is_relative_to(snapshot) for path in links))
            for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
                directory.chmod(0o555)
            yield snapshot
        finally:
            for directory in sorted(directories, key=lambda path: len(path.parts)):
                if not directory.is_symlink():
                    directory.chmod(0o700)


def _snapshot_fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _snapshot_identity(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_nlink


def _read_snapshot_file(path, identity, size, expected, link):
    require(_snapshot_identity(os.lstat(path)) == identity)
    if link:
        data = os.readlink(path).encode('utf-8')
    else:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            require(_snapshot_identity(info) == identity and info.st_size == size)
            data = stream.read(size + 1)
    require(len(data) == size and hashlib.sha256(data).digest() == expected)
    return data


def _check_snapshot_bytes(checks):
    directories, files = checks
    # Reuse known paths and expected hashes, never timestamps as content proof.
    # Names detect extra entries; inode/mode/owner binds the opened source.
    for path, identity, names in directories:
        require(_snapshot_identity(os.lstat(path)) == identity)
        require(tuple(sorted(os.listdir(path))) == names)
    for entry in files:
        _read_snapshot_file(*entry)


def verify_snapshot(root, revision, *, signatures=None, remember=False):
    """Check the actual input tree against the pinned canonical Git stream.

    Mode bits alone cannot prevent its owner from rewriting a file. Check bytes,
    executable modes, links, extra files and directory structure at import/run
    boundaries, and independently in the supervisor before publication.
    This is source-drift detection, not isolation from arbitrary same-user code.
    """
    if signatures is not None:
        _check_snapshot_bytes(signatures)
        return signatures
    require(root.is_dir() and not root.is_symlink())
    paths, folders = [], set()
    for directory, children, files in os.walk(root, followlinks=False):
        folder = Path(directory)
        require(not folder.is_symlink() and not folder.stat().st_mode & 0o222)
        folders.add(folder.relative_to(root))
        for name in children[:]:
            if (folder / name).is_symlink():
                children.remove(name)
                files.append(name)
        paths.extend((folder / name).relative_to(root) for name in files)
    expected_folders = {Path('.')}
    for path in paths:
        expected_folders.update(path.parents)
    require(folders == expected_folders)
    names = {folder: set() for folder in folders}
    for path in paths:
        names[path.parent].add(path.name)
    for folder in folders - {Path('.')}:
        names[folder.parent].add(folder.name)
    directories = tuple((str(root / folder), _snapshot_identity(os.lstat(root / folder)),
                         tuple(sorted(names[folder]))) for folder in folders)
    files = []
    digest = hashlib.sha256()
    for relative in sorted(paths, key=lambda path: path.as_posix()):
        path = root / relative
        if path.is_symlink():
            require(path.resolve().is_relative_to(root))
            mode, data = '120000', os.readlink(path).encode('utf-8')
        else:
            info = path.stat()
            require(not info.st_mode & 0o222)
            mode = '100755' if info.st_mode & 0o111 else '100644'
            data = regular(root, relative.as_posix()).read_bytes()
        files.append((str(path), _snapshot_identity(os.lstat(path)), len(data),
                      hashlib.sha256(data).digest(), mode == '120000'))
        digest.update(relative.as_posix().encode('utf-8') + b'\0')
        digest.update(mode.encode('ascii') + b'\0' + data + b'\0')
    require('sha256:' + digest.hexdigest() == revision)
    checks = directories, tuple(files)
    _check_snapshot_bytes(checks)
    return checks if remember else None


def quiet():
    """Keep imports, children and shutdown handlers private through process exit."""
    sys.stdout.flush()
    sys.stderr.flush()
    result_fd = os.dup(1)
    with open(os.devnull, "w") as sink:
        os.dup2(sink.fileno(), 1)
        os.dup2(sink.fileno(), 2)
    return result_fd


def install_termination_handler(publication=None):
    global _TERMINATION_REQUESTED, _SELECTOR_SHUTDOWN_STARTED
    _TERMINATION_REQUESTED = False
    _SELECTOR_SHUTDOWN_STARTED = False
    exit_child, getpid = os._exit, os.getpid
    handler_pid = getpid()
    def interrupted(signum, *_):
        global _TERMINATION_REQUESTED
        _TERMINATION_REQUESTED = True
        if publication is None and (_SELECTOR_SHUTDOWN_STARTED or getpid() != handler_pid):
            # Python ignores exceptions from atexit and after-fork callbacks.
            # Preserve termination even before the forked child installs its
            # own handler. This pid is a live fork relation, not native authority.
            exit_child(128 + signum)
        if publication is None or publication["result"] is None:
            raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    if publication is None:
        signal.signal(signal.SIGINT, interrupted)


class Result(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.reasons = []
        self.completed = 0
        self.subtests = 0

    def stopTest(self, test):
        self.completed += 1
        super().stopTest(test)

    def addFailure(self, test, err):
        self.reasons.append("test_failure")

    def addError(self, test, err):
        self.reasons.append("test_error")

    def addSkip(self, test, reason):
        self.reasons.append("required_skipped")

    def addExpectedFailure(self, test, err):
        self.reasons.append("expected_failure")

    def addUnexpectedSuccess(self, test):
        self.reasons.append("unexpected_success")

    def addSubTest(self, test, subtest, err):
        self.subtests += 1
        if err is not None:
            self.reasons.append("test_failure" if issubclass(err[0], test.failureException) else "test_error")


def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test


def collect(root, selector):
    module_name, class_name, method_name = selector.split(".")
    # Bind ordinary collection before selected import can patch unittest globals.
    loader = unittest.TestLoader()
    load = loader.loadTestsFromName
    case_type = unittest.TestCase
    module = importlib.import_module(module_name)
    require(Path(module.__file__).resolve() == regular(root, "tests/" + module_name + ".py"))
    cls = getattr(module, class_name, None)
    require(isinstance(cls, type) and issubclass(cls, case_type))
    require(callable(getattr(cls, method_name, None)))
    suite = load(selector)
    tests = list(flatten(suite))
    require(not loader.errors and len(tests) == 1 and type(tests[0]) is cls
            and tests[0].id() == selector and suite.countTestCases() == 1)
    return suite


def execute_selector(root, selector):
    """One selected import/run in a fresh interpreter, with no earlier test heap."""
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "tests"))
    result, collected, reasons, invoked, finished, method_reasons = Result(), 0, [], [0], [0], []
    is_instance = isinstance
    def failed(error, failure_type):
        if is_instance(error, KeyboardInterrupt):
            method_reasons.append('interrupted')
        elif is_instance(error, unittest.SkipTest):
            method_reasons.append('required_skipped')
        else:
            method_reasons.append('test_failure' if is_instance(error, failure_type) else 'test_error')
    def returned(value):
        if value is not None:
            method_reasons.append('not_executed')
        return value
    try:
        suite = collect(root, selector)
        collected = 1
        test = next(flatten(suite))
        name = selector.rsplit('.', 1)[1]
        original = getattr(test, name)
        failure_type = test.failureException
        if inspect.iscoroutinefunction(original):
            @functools.wraps(original)
            async def method(*args, **kwargs):
                invoked[0] += 1
                try:
                    return returned(await original(*args, **kwargs))
                except BaseException as error:
                    failed(error, failure_type)
                    raise
                finally:
                    finished[0] += 1
        else:
            @functools.wraps(original)
            def method(*args, **kwargs):
                invoked[0] += 1
                try:
                    return returned(original(*args, **kwargs))
                except BaseException as error:
                    failed(error, failure_type)
                    raise
                finally:
                    finished[0] += 1
        setattr(test, name, method)
        suite.run(result)
    except KeyboardInterrupt:
        reasons = ["interrupted"]
    except (SystemExit, Exception):
        reasons = ["collection_invalid"] if not collected else ["test_error"]
    reasons += result.reasons
    if 'interrupted' in method_reasons:
        reasons.append('interrupted')
    elif not reasons:
        reasons += method_reasons
    if _TERMINATION_REQUESTED:
        reasons.append("interrupted")
    if not reasons and (result.testsRun != 1 or result.completed != 1 or invoked[0] != 1 or finished[0] != 1):
        reasons = ["test_error" if invoked[0] > 1 else "not_executed"]
    return {"selector": selector, "collected": collected, "executed": result.testsRun,
            "completed": result.completed, "subtests": result.subtests,
            "reasons": sorted(set(reasons)) or ["passed"]}, invoked[0], finished[0]


def execution_environment():
    return {"python": ".".join(map(str, sys.version_info[:3])), "execution": "local_subprocess"}


def execute(root, manifest, pins):
    # This orchestrator never imports selected modules. Each selector gets its
    # own clean process and private pipe; prior class/helper/stdlib patches cannot
    # replace later committed implementations without changing checked files.
    entries, interrupted = [], False
    signatures = verify_snapshot(root, pins['source_revision'], remember=True)
    compiled = _compile_selected(root, manifest, signatures) if _fork_available() else {}
    run_alias = "verification-" + secrets.token_hex(16)
    for case in manifest["cases"]:
        started, outcomes = now(), []
        for selector in case["selectors"]:
            verify_snapshot(root, pins['source_revision'], signatures=signatures)
            if interrupted:
                outcome = {"selector": selector, "collected": 0, "executed": 0,
                           "completed": 0, "subtests": 0, "reasons": ["not_executed"]}
            else:
                selected = isolated_worker(root, pins, selector=selector, compiled=compiled,
                                           source_files=signatures[1])
                require(type(selected) is dict and set(selected) == {"outcome", "environment"})
                require(selected["environment"] == execution_environment())
                outcome = selected["outcome"]
                interrupted = "interrupted" in outcome["reasons"]
            verify_snapshot(root, pins['source_revision'], signatures=signatures)
            outcomes.append(outcome)
        passed = all(row["reasons"] == ["passed"] for row in outcomes)
        status = "PASS" if passed else ("NOT RUN" if all(row["executed"] == 0 for row in outcomes) else "FAIL")
        entries.append({"case_id": case["case_id"], "status": status, "kind": "D",
            "candidate_head": pins["candidate_head"], "base_sha": pins["base_sha"],
            "spec_revision": case["requirements"], "policy_revision": pins["policy_revision"],
            "fixture_revision": sha256(regular(root, case["fixture"]).read_bytes()),
            "environment": execution_environment(),
            "command_or_runbook": {"runner": SCRIPT, "selectors": case["selectors"]},
            "started_at": started, "finished_at": now(), "observed": outcomes,
            "evidence_refs": [{"kind": "same_run", "case_id": case["case_id"], "run_alias": run_alias}],
            "limitations": LIMITATIONS, "remaining_owner": None if passed else "implementation_owner"})
    verify_snapshot(root, pins['source_revision'])
    return {"schema_version": VERSION, "scope": "selected_source_d", "excluded": LIMITATIONS, "run_alias": run_alias,
            "binding": pins, "results": entries}


class _SelectorExit(BaseException):
    """Leave the clean fork through the outer bootstrap's normal Python exit."""
    def __init__(self, code):
        self.code = code


def _import_entries(root, files):
    return [[str(Path(path).relative_to(root)), list(identity), size, digest.hex(), link]
            for path, identity, size, digest, link in files
            if link or Path(path).suffix == '.py']


def _install_source_reader(root, entries):
    """Bind default repository imports to the bytes pinned by the supervisor.

    This is child-local drift detection, not a sandbox for hostile Python code.
    Runtime/dependency imports outside the snapshot keep their normal loader.
    """
    require(type(entries) is list)
    pinned = {}
    for entry in entries:
        require(type(entry) is list and len(entry) == 5)
        relative, identity, size, digest, link = entry
        require(isinstance(relative, str))
        path = Path(relative)
        require(not path.is_absolute() and path.parts and '..' not in path.parts)
        require(str(path) == relative and relative not in pinned)
        require(type(identity) is list and len(identity) == 6
                and all(type(value) is int and value >= 0 for value in identity))
        require(type(size) is int and size >= 0 and type(link) is bool)
        require(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest))
        require(link or path.suffix == '.py')
        pinned[relative] = (str(root / path), tuple(identity), size, bytes.fromhex(digest), link)

    def source_path(path):
        # Resolve only verified link text; mutable resolve() would select bytes
        # through an unchecked directory link before reaching the pinned file.
        for _ in range(64):
            relative = path.relative_to(root)
            for index in range(1, len(relative.parts) + 1):
                prefix = Path(*relative.parts[:index])
                entry = pinned.get(str(prefix))
                if entry is not None and entry[-1]:
                    target = _read_snapshot_file(*entry).decode('utf-8')
                    path = Path(os.path.abspath(root / prefix.parent / target /
                                Path(*relative.parts[index:])))
                    require(path.is_relative_to(root))
                    break
            else:
                entry = pinned.get(str(relative))
                require(entry is not None and not entry[-1])
                return entry
        raise Invalid()

    original = importlib.machinery.SourceFileLoader.get_data

    def get_data(loader, path):
        path = Path(os.path.abspath(path))
        if not path.is_relative_to(root):
            return original(loader, str(path))
        if path.suffix in {'.pyc', '.pyo'}:
            # Force SourceFileLoader to consume verified source, never cache.
            raise OSError('repository bytecode unavailable')
        if path.suffix == '.py':
            return _read_snapshot_file(*source_path(path))
        return original(loader, str(path))

    importlib.machinery.SourceFileLoader.get_data = get_data


class _CompiledLoader(importlib.machinery.SourceFileLoader):
    def __init__(self, name, path, code):
        super().__init__(name, path)
        self.code = code

    def get_code(self, fullname):
        require(fullname == self.name)
        return self.code


class _CompiledFinder:
    def __init__(self, compiled):
        self.compiled = compiled

    def find_spec(self, fullname, path=None, target=None):
        entry = self.compiled.get(fullname)
        if entry is None:
            return None
        path, code = entry
        return importlib.util.spec_from_loader(fullname, _CompiledLoader(fullname, path, code))


def _compile_selected(root, manifest, signatures):
    """Compile bounded repeated inputs once; never execute/import selected code.

    Forks inherit immutable code objects, while every module namespace and test
    fixture remains private to its fresh selector. No pyc files or selected heap
    are reused. Actual source-byte checks still run at every selector boundary.
    """
    counts = {}
    for case in manifest['cases']:
        for selector in case['selectors']:
            name = selector.split('.')[0]
            counts[name] = counts.get(name, 0) + 1
    compiled, retained = {}, 0
    pinned = {entry[0]: entry for entry in signatures[1]}
    for name in sorted(counts, key=counts.get, reverse=True):
        if counts[name] < 2:
            continue
        path = regular(root, 'tests/' + name + '.py')
        entry = pinned.get(str(path))
        require(entry is not None and not entry[-1])
        size = entry[2]
        if size > 8_000_000 - retained:
            continue
        data = _read_snapshot_file(*entry)
        try:
            code = compile(data, str(path), 'exec', dont_inherit=True, optimize=sys.flags.optimize)
        except SyntaxError:
            # Preserve the ordinary per-selector collection failure protocol.
            continue
        compiled[name] = str(path), code
        retained += size
    return compiled


def _fork_available():
    # The orchestrator has loaded no selected modules and has no worker threads.
    # Keep the fresh-exec route for platforms without this safe fork profile.
    return (sys.platform in {'darwin', 'linux'} and hasattr(os, 'fork')
            and Path('/dev/fd').is_dir() and threading.active_count() == 1)


def _emit_selector(root, selector, descriptor):
    # Capture immutable C operations before any selected import. Selected tests
    # may legitimately patch json.dumps/JSONEncoder; they never serialize their
    # own verdict. The pristine orchestrator constructs all JSON.
    global _SELECTOR_SHUTDOWN_STARTED
    pack, write, close = _SELECTOR_PACKET.pack, os.write, os.close
    codes = _REASON_CODES
    try:
        outcome, invoked, finished = execute_selector(root, selector)
        _SELECTOR_SHUTDOWN_STARTED = True
        mask = 0
        for bit, reason in enumerate(codes):
            if reason in outcome['reasons']:
                mask |= 1 << bit
        data = pack(b'HYD1', outcome['collected'], outcome['executed'], outcome['completed'],
                    outcome['subtests'], invoked, finished, mask, *sys.version_info[:3])
        while data:
            count = write(descriptor, data)
            require(count > 0)
            data = data[count:]
    finally:
        close(descriptor)


def _selector_result(data, selector):
    require(len(data) == _SELECTOR_PACKET.size)
    magic, collected, executed, completed, subtests, invoked, finished, mask, major, minor, micro = _SELECTOR_PACKET.unpack(data)
    require(magic == b'HYD1' and mask and not mask >> len(_REASON_CODES))
    require(0 <= completed <= executed <= collected <= 1 and subtests <= 100000)
    require(invoked <= 100000 and finished <= invoked)
    reasons = [reason for bit, reason in enumerate(_REASON_CODES) if mask & (1 << bit)]
    if reasons == ['passed']:
        require(collected == executed == completed == invoked == finished == 1)
    else:
        require('passed' not in reasons)
    return {'outcome': {'selector': selector, 'collected': collected, 'executed': executed,
            'completed': completed, 'subtests': subtests, 'reasons': reasons},
            'environment': {'python': '.'.join(map(str, (major, minor, micro))), 'execution': 'local_subprocess'}}


def _fork_selector_main(root, selector, write_fd, compiled, source_files):
    try:
        os.dup2(write_fd, 1)
        with open(os.devnull, 'rb') as empty:
            os.dup2(empty.fileno(), 0)
        # Never inherit the orchestration report descriptor or other private
        # channels. Only stdin/null and the new stdout pipe survive setup.
        for descriptor in [int(name) for name in os.listdir('/dev/fd') if name.isdecimal()]:
            if descriptor > 2:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        result_fd = quiet()
        install_termination_handler()
        sys.dont_write_bytecode = True
        _install_source_reader(root, _import_entries(root, source_files))
        if compiled:
            sys.meta_path.insert(0, _CompiledFinder(compiled))
        _emit_selector(root, selector, result_fd)
        return 0
    except KeyboardInterrupt:
        return 128 + signal.SIGINT
    except (OSError, subprocess.TimeoutExpired):
        return _ENVIRONMENT_EXIT
    except BaseException:
        return 2


class _ForkedSelector:
    """Small owned-process adapter for the same bounded capture/cleanup below."""
    def __init__(self, root, selector, compiled, source_files):
        read_fd, write_fd = os.pipe()
        try:
            self.pid = os.fork()
        except BaseException:
            os.close(read_fd)
            os.close(write_fd)
            raise
        if self.pid == 0:
            # Returning through _worker_main lets normal interpreter shutdown
            # run selected atexit handlers; stdout/stderr remain private.
            raise _SelectorExit(_fork_selector_main(root, selector, write_fd, compiled, source_files))
        os.close(write_fd)
        self.stdout = os.fdopen(read_fd, 'rb')
        self.returncode = None

    def wait(self, timeout):
        deadline = time.monotonic() + timeout
        while self.returncode is None:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.returncode = os.waitstatus_to_exitcode(status)
                break
            if time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired('verification-selector', timeout)
            time.sleep(.005)
        return self.returncode

    def terminate(self):
        if self.returncode is None:
            os.kill(self.pid, signal.SIGTERM)

    def kill(self):
        if self.returncode is None:
            os.kill(self.pid, signal.SIGKILL)


def _worker_main():
    """Private child entry: stdout here is a supervisor pipe, never public stdout."""
    try:
        result_fd = quiet()
        install_termination_handler()
        sys.dont_write_bytecode = True
    except KeyboardInterrupt:
        return 128 + signal.SIGINT
    except OSError:
        return _ENVIRONMENT_EXIT
    selector = None
    try:
        request = decode_json(sys.stdin.buffer.read(_WORKER_INPUT_LIMIT + 1), limit=_WORKER_INPUT_LIMIT)
        require(type(request) is dict and set(request) == {"root", "pins", "selector", "source_files"})
        root = Path(request["root"]).resolve()
        require(Path(__file__).resolve() == regular(root, SCRIPT))
        selector = request["selector"]
        if selector is None:
            require(request['source_files'] is None)
            manifest = load_manifest(root)
            report = execute(root, manifest, request["pins"])
        else:
            require(isinstance(selector, str) and SELECTOR.fullmatch(selector))
            _install_source_reader(root, request['source_files'])
            _emit_selector(root, selector, result_fd)
            return 0
    except _SelectorExit as ended:
        return ended.code
    except KeyboardInterrupt:
        if selector is not None:
            # _emit_selector closes its packet channel on every exit. Return a
            # cancellation status instead of writing JSON through that closed fd.
            return 128 + signal.SIGINT
        report = {"worker_interrupted": True}
    except (OSError, subprocess.TimeoutExpired):
        return _ENVIRONMENT_EXIT
    except BaseException:
        os.close(result_fd)
        return 2
    with os.fdopen(result_fd, "wb") as stream:
        stream.write(json.dumps(report, ensure_ascii=True, sort_keys=True).encode("ascii"))
    return 0


def isolated_worker(root, pins, *, selector=None, compiled=None, source_files=None):
    """Bounded private transport; selected imports never inherit public handles.

    This is output/process separation, not a sandbox for same-user code. Only the
    supervisor validates, exports, and writes the public result. Its original
    stdout descriptor is closed in the fresh child along with other inherited fds.
    """
    if selector is not None and _fork_available():
        require(source_files is not None)
        return _capture_worker(_ForkedSelector(root, selector, compiled or {}, source_files),
                               group=False, selector=selector)
    bootstrap = "import runpy,sys; raise SystemExit(runpy.run_path(sys.argv[1])['_worker_main']())"
    envelope = json.dumps({'root': str(root), 'pins': pins, 'selector': None}, ensure_ascii=True).encode('ascii')
    require(len(envelope) <= _INPUT_LIMIT)
    request = json.dumps({"root": str(root), "pins": pins, "selector": selector,
        "source_files": _import_entries(root, source_files) if source_files is not None else None},
        ensure_ascii=True).encode("ascii")
    require(len(request) <= _WORKER_INPUT_LIMIT)
    with tempfile.TemporaryFile() as channel:
        channel.write(request)
        channel.seek(0)
        child = subprocess.Popen([sys.executable, "-I", "-c", bootstrap, str(root / SCRIPT)],
            stdin=channel, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            close_fds=True, start_new_session=selector is None)
        return _capture_worker(child, group=selector is None, selector=selector)


def _capture_worker(child, *, group, selector=None):
    try:
        data, deadline = bytearray(), time.monotonic() + 600
        with selectors.DefaultSelector() as poller:
            poller.register(child.stdout, selectors.EVENT_READ)
            while True:
                if time.monotonic() >= deadline:
                    raise EnvironmentUnavailable()
                if not poller.select(.1):
                    continue
                chunk = os.read(child.stdout.fileno(), 65536)
                if not chunk:
                    break
                data.extend(chunk)
                require(len(data) <= (_SELECTOR_PACKET.size if selector is not None else _REPORT_LIMIT))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise EnvironmentUnavailable()
        returncode = child.wait(timeout=remaining)
        if returncode in {-signal.SIGTERM, -signal.SIGINT, 128 + signal.SIGTERM, 128 + signal.SIGINT}:
            raise KeyboardInterrupt()
        if returncode == _ENVIRONMENT_EXIT:
            raise EnvironmentUnavailable()
        if selector is not None:
            # A selected implementation can crash before returning its packet,
            # or during private shutdown after a complete packet. Preserve only
            # available counters and record failure; never certify that PASS.
            invalid_packet = False
            try:
                selected = _selector_result(data, selector)
            except (Invalid, ValueError, struct.error):
                invalid_packet = True
                selected = {'outcome': {'selector': selector, 'collected': 0, 'executed': 0,
                    'completed': 0, 'subtests': 0, 'reasons': []}, 'environment': execution_environment()}
            if invalid_packet or returncode != 0:
                outcome = selected['outcome']
                outcome['reasons'] = sorted((set(outcome['reasons']) - {'passed'}) | {'test_error'})
            return selected
        require(returncode == 0)
        report = decode_json(data, limit=_REPORT_LIMIT)
        if report == {"worker_interrupted": True}:
            raise KeyboardInterrupt()
        return report
    finally:
        try:
            os.killpg(child.pid, signal.SIGTERM) if group else child.terminate()
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(child.pid, signal.SIGKILL) if group else child.kill()
        except ProcessLookupError:
            pass
        child.wait(timeout=2)
        child.stdout.close()


def isolated_execute(root, manifest, pins):
    # Validate in the supervisor, independently of every selected import/run.
    report = isolated_worker(root, pins)
    validate(report, root, manifest, pins)
    require(all(row["environment"] == execution_environment() for row in report["results"]))
    return report


def validate(report, root, manifest, pins):
    """Strict same-revision consumer; this does not authenticate a CI producer."""
    require(type(report) is dict and set(report) == {"schema_version", "scope", "excluded", "run_alias", "binding", "results"})
    require(isinstance(report["run_alias"], str) and RUN.fullmatch(report["run_alias"]))
    require(type(report["schema_version"]) is int and report["schema_version"] == VERSION)
    require(report["scope"] == "selected_source_d" and report["excluded"] == LIMITATIONS and report["binding"] == pins)
    require(type(report["results"]) is list and len(report["results"]) == len(manifest["cases"]))
    for case, row in zip(manifest["cases"], report["results"]):
        require(type(row) is dict and set(row) == {"case_id", "status", "kind", "candidate_head", "base_sha",
            "spec_revision", "policy_revision", "fixture_revision", "environment", "command_or_runbook",
            "started_at", "finished_at", "observed", "evidence_refs", "limitations", "remaining_owner"})
        require(row["case_id"] == case["case_id"] and row["kind"] == "D")
        require(row["candidate_head"] == pins["candidate_head"] and row["base_sha"] == pins["base_sha"])
        require(row["spec_revision"] == case["requirements"] and row["policy_revision"] == pins["policy_revision"])
        require(row["fixture_revision"] == sha256(regular(root, case["fixture"]).read_bytes()))
        env = row["environment"]
        require(type(env) is dict and set(env) == {"python", "execution"} and env["execution"] == "local_subprocess")
        require(isinstance(env["python"], str) and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", env["python"]))
        require(row["command_or_runbook"] == {"runner": SCRIPT, "selectors": case["selectors"]})
        require(row["evidence_refs"] == [{"kind": "same_run", "case_id": case["case_id"], "run_alias": report["run_alias"]}])
        require(row["limitations"] == LIMITATIONS)
        times = []
        for key in ("started_at", "finished_at"):
            require(isinstance(row[key], str) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", row[key]))
            times.append(datetime.fromisoformat(row[key]))
        require(times[1] >= times[0])
        require(type(row["observed"]) is list and len(row["observed"]) == len(case["selectors"]))
        for selector, outcome in zip(case["selectors"], row["observed"]):
            require(type(outcome) is dict and set(outcome) == {"selector", "collected", "executed", "completed", "subtests", "reasons"})
            require(outcome["selector"] == selector)
            require(all(type(outcome[k]) is int and 0 <= outcome[k] <= 100000 for k in ("collected", "executed", "completed", "subtests")))
            require(0 <= outcome["completed"] <= outcome["executed"] <= outcome["collected"] <= 1)
            require(type(outcome["reasons"]) is list and 0 < len(outcome["reasons"]) <= len(REASONS))
            require(all(isinstance(reason, str) and reason in REASONS for reason in outcome["reasons"]))
            if outcome["reasons"] == ["passed"]:
                require(outcome["collected"] == outcome["executed"] == outcome["completed"] == 1)
            else:
                require("passed" not in outcome["reasons"])
        passed = all(item["reasons"] == ["passed"] for item in row["observed"])
        expected = "PASS" if passed else ("NOT RUN" if all(item["executed"] == 0 for item in row["observed"]) else "FAIL")
        require(row["status"] == expected and row["remaining_owner"] == (None if passed else "implementation_owner"))
    return all(row["status"] == "PASS" for row in report["results"])


def artifact_path(root, relative, *, create=False):
    path = Path(relative)
    require(not path.is_absolute() and path.parent == ARTIFACT)
    require(re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,80}\.json", path.name))
    current = root
    for part in ARTIFACT.parts:
        current = current / part
        require(not current.is_symlink())
        if create:
            current.mkdir(exist_ok=True)
        require(current.is_dir())
    target = root / path
    require(not target.is_symlink())
    return target


def open_artifact_directory(root):
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in ARTIFACT.parts:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def read_report(root, relative):
    target = artifact_path(root, relative)
    descriptor = open_artifact_directory(root)
    try:
        return read_json(target.name, limit=_REPORT_LIMIT, dir_fd=descriptor)
    except FileNotFoundError as error:
        raise Invalid() from error
    finally:
        os.close(descriptor)


def export(root, relative, report, *, publication=None, outcome=None):
    target = artifact_path(root, relative, create=True)
    # Each execution gets a new artifact. Never replace earlier evidence, even on failure.
    require(not target.exists())
    data = (json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("ascii")
    require(len(data) <= _REPORT_LIMIT)
    descriptor = open_artifact_directory(root)
    temp = ".pending-" + secrets.token_hex(8)
    created, linked, identity = False, False, None
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
        created = True
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            info = os.fstat(stream.fileno())
            identity = info.st_dev, info.st_ino
        # dir_fd pins the validated parent; no-replace link preserves concurrent/old evidence.
        os.link(temp, target.name, src_dir_fd=descriptor, dst_dir_fd=descriptor, follow_symlinks=False)
        linked = True
        os.fsync(descriptor)
        os.unlink(temp, dir_fd=descriptor)
        created = False
        os.fsync(descriptor)
        visible = artifact_path(root, relative)
        info = visible.stat(follow_symlinks=False)
        require((info.st_dev, info.st_ino) == identity)
        if publication is not None:
            # This single trusted assignment is the publication commit point.
            # Earlier interruption rolls back; later interruption cannot relabel
            # finalized evidence while snapshot/descriptor cleanup unwinds.
            publication["result"] = outcome
    except BaseException:
        if linked and (publication is None or publication["result"] is None):
            try:
                info = os.stat(target.name, dir_fd=descriptor, follow_symlinks=False)
                if (info.st_dev, info.st_ino) == identity:
                    os.unlink(target.name, dir_fd=descriptor)
            except FileNotFoundError:
                pass
        raise
    finally:
        try:
            if created:
                try:
                    os.unlink(temp, dir_fd=descriptor)
                except OSError:
                    pass
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Invalid()


def main():
    try:
        result_fd = quiet()
    except OSError:
        try:
            os.write(1, b'{"reason":"environment_unavailable","status":"BLOCKED"}\n')
        except OSError:
            pass
        return 2
    publication = {"result": None}
    reason, code = "invalid_input", 2
    try:
        install_termination_handler(publication)
        sys.dont_write_bytecode = True
        parser = Parser(description=__doc__)
        parser.add_argument("--manifest", default=MANIFEST, choices=[MANIFEST])
        parser.add_argument("--output")
        parser.add_argument("--validate-report")
        parser.add_argument("--checked-sha")
        parser.add_argument("--base-sha")
        parser.add_argument("--source-head")
        args = parser.parse_args()
        require(bool(args.output) != bool(args.validate_report))
        root = Path.cwd().resolve()
        require(git(root, "rev-parse", "--show-toplevel").decode().strip() == str(root))
        head = git(root, "rev-parse", "HEAD").decode("ascii").strip()
        require(SHA.fullmatch(head) and (args.checked_sha is None or args.checked_sha == head))
        with source_snapshot(root, head) as snapshot:
            # Parse every definition from pinned Git inputs before selecting or
            # executing methods; live manifest replacement cannot select work.
            manifest = load_manifest(snapshot)
            pins = binding(root, manifest, args.checked_sha, args.base_sha, args.source_head, inputs=snapshot)
            require(pins["candidate_head"] == head)
            verify_snapshot(snapshot, pins['source_revision'])
            if args.validate_report:
                passed = validate(read_report(root, args.validate_report), snapshot, manifest, pins)
            else:
                artifact_path(root, args.output, create=True)
                report = isolated_execute(snapshot, manifest, pins)
                require(binding(root, manifest, args.checked_sha, args.base_sha, args.source_head, inputs=snapshot) == pins)
                verify_snapshot(snapshot, pins['source_revision'])
                passed = validate(report, snapshot, manifest, pins)
                reason = "export_failed"
                outcome = ("passed", 0) if passed else ("required_evidence_incomplete", 1)
                export(root, args.output, report, publication=publication, outcome=outcome)
        reason, code = ("passed", 0) if passed else ("required_evidence_incomplete", 1)
    except KeyboardInterrupt:
        reason, code = "interrupted", 2
    except SystemExit:
        reason, code = "invalid_input", 2
    except (OSError, subprocess.TimeoutExpired):
        if reason == "invalid_input":
            reason, code = "environment_unavailable", 2
    except Exception:
        pass
    if publication["result"] is not None:
        reason, code = publication["result"]
    elif _TERMINATION_REQUESTED:
        reason, code = "interrupted", 2
    status = "PASS" if code == 0 else ("BLOCKED" if reason == "environment_unavailable" else "FAIL")
    os.write(result_fd, (json.dumps({"status": status, "reason": reason}, sort_keys=True) + "\n").encode("ascii"))
    os.close(result_fd)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
