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
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
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
EXCLUSIONS = {"unselected_v1_requirements", "live_model_evaluation", "native_operation",
              "verify_only_command", "trusted_ci_attestation"}
LIMITATIONS = sorted(EXCLUSIONS)


class Invalid(Exception):
    """No exception text is part of the public protocol."""


def require(value):
    if not value:
        raise Invalid()


def sha256(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=15)
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


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result)
            result[key] = value
        return result
    require(path.stat().st_size <= 262144)
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


def section_anchors(text):
    """Resolve ATX/single-line Setext headings; code and raw HTML are not headings.

    Ambiguous inline markup is ignored rather than inventing a requirement anchor.
    """
    anchors, paragraph, fence, raw_html = set(), [], None, None
    for line in text.splitlines():
        stripped = line.strip()
        if fence:
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(fence[1]) + r",}[ \t]*", line):
                fence = None
            continue
        if raw_html:
            if ((raw_html == "block" and not stripped) or
                    (raw_html != "block" and raw_html in line.lower())):
                raw_html = None
            continue
        opening = re.match(r" {0,3}(`{3,}|~{3,})", line)
        if opening:
            marker = opening[1]
            fence, paragraph = (marker[0], len(marker)), []
            continue
        if line.startswith(("    ", "\t")):
            paragraph = []
            continue
        if stripped.startswith("<!--"):
            raw_html = None if "-->" in stripped else "-->"
            paragraph = []
            continue
        html = re.match(r" {0,3}<(script|pre|style|textarea)(?:\s|>)", line, re.IGNORECASE)
        if html:
            end = "</" + html[1].lower() + ">"
            raw_html, paragraph = (None if end in line.lower() else end), []
            continue
        if re.match(r" {0,3}<[A-Za-z/!?]", line):
            raw_html, paragraph = "block", []
            continue
        atx = re.fullmatch(r" {0,3}#{1,6}(?:[ \t]+(.*?))?[ \t]*", line)
        heading = atx[1] or "" if atx else None
        if atx:
            heading = re.sub(r"[ \t]+#+[ \t]*$", "", heading)
        elif re.fullmatch(r" {0,3}(?:=+|-+)[ \t]*", line) and len(paragraph) == 1:
            heading = paragraph[0]
        if heading is None:
            if stripped and not re.match(r"[#>*+\-]", stripped):
                paragraph.append(stripped)
            else:
                paragraph = []
            continue
        paragraph = []
        heading = re.sub(r"!?\[([^\[\]]*)\]\([^()]*\)", r"\1", heading)
        heading = re.sub(r"(`+)([^`]*?)\1", r"\2", heading)
        heading = re.sub(r"(\*\*?|__?|~~)(.+?)\1", r"\2", heading)
        if re.search(r"[\\<>&\[\]`*~]", heading):
            continue
        slug = re.sub(r"[^\w -]", "", heading.strip().lower()).replace(" ", "-")
        candidate, suffix = slug, 0
        while candidate in anchors:
            suffix += 1
            candidate = slug + "-" + str(suffix)
        anchors.add(candidate)
    return anchors


def load_manifest(root):
    value = read_json(regular(root, MANIFEST))
    require(type(value) is dict and set(value) == {"schema_version", "scope", "excluded", "cases"})
    require(type(value["schema_version"]) is int and value["schema_version"] == VERSION)
    require(value["scope"] == "selected_source_d" and value["excluded"] == LIMITATIONS)
    cases = value["cases"]
    require(type(cases) is list and 0 < len(cases) <= 64)
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
        require(type(case["selectors"]) is list and 0 < len(case["selectors"]) <= 32)
        for selector in case["selectors"]:
            require(isinstance(selector, str) and SELECTOR.fullmatch(selector))
            require(selector not in selectors)
            selectors.add(selector)
            regular(root, "tests/" + selector.split(".")[0] + ".py")
        require(isinstance(case["fixture"], str) and re.fullmatch(
            r"tests/fixtures/mvp/verification/[a-z0-9_-]+\.json", case["fixture"]))
        fixture = read_json(regular(root, case["fixture"]))
        require(type(fixture) is dict and fixture.get("case_id") == case["case_id"])
        require(all(key in fixture for key in ("preconditions", "events", "expected", "forbidden_effects", "oracle")))
    return value


def binding(root, manifest, checked, base, source):
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
    paths.update(path.relative_to(root).as_posix() for path in root.glob("*.py"))
    for folder in ("hydra_sdlc", "tests", "scripts"):
        paths.update(path.relative_to(root).as_posix() for path in (root / folder).rglob("*.py"))
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
    return {"candidate_head": head, "source_head": source or head, "base_sha": base,
            "base_reason": None if base else "not_supplied", "source_revision": "sha256:" + digest.hexdigest(),
            "manifest_revision": sha256(regular(root, MANIFEST).read_bytes()),
            "policy_revision": sha256(regular(root, POLICY).read_bytes())}


def quiet():
    """Keep imports, children and shutdown handlers private through process exit."""
    sys.stdout.flush()
    sys.stderr.flush()
    result_fd = os.dup(1)
    with open(os.devnull, "w") as sink:
        os.dup2(sink.fileno(), 1)
        os.dup2(sink.fileno(), 2)
    return result_fd


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
    module = importlib.import_module(module_name)
    require(Path(module.__file__).resolve() == regular(root, "tests/" + module_name + ".py"))
    cls = getattr(module, class_name, None)
    require(isinstance(cls, type) and issubclass(cls, unittest.TestCase))
    require(callable(getattr(cls, method_name, None)))
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromName(selector)
    tests = list(flatten(suite))
    require(not loader.errors and len(tests) == 1 and tests[0].id() == selector and suite.countTestCases() == 1)
    return suite


def execute(root, manifest, pins):
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "tests"))
    entries, interrupted = [], False
    run_alias = "verification-" + secrets.token_hex(16)
    for case in manifest["cases"]:
        started, outcomes = now(), []
        for selector in case["selectors"]:
            result, collected, reasons = Result(), 0, []
            if interrupted:
                reasons = ["not_executed"]
            else:
                try:
                    suite = collect(root, selector)
                    collected = 1
                    suite.run(result)
                except (KeyboardInterrupt, SystemExit):
                    interrupted = True
                    reasons = ["interrupted"]
                except Exception:
                    reasons = ["collection_invalid"] if not collected else ["test_error"]
                reasons += result.reasons
                if not reasons and (result.testsRun != 1 or result.completed != 1):
                    reasons = ["not_executed"]
            outcomes.append({"selector": selector, "collected": collected, "executed": result.testsRun,
                             "completed": result.completed, "subtests": result.subtests,
                             "reasons": sorted(set(reasons)) or ["passed"]})
        passed = all(row["reasons"] == ["passed"] for row in outcomes)
        status = "PASS" if passed else ("NOT RUN" if all(row["executed"] == 0 for row in outcomes) else "FAIL")
        entries.append({"case_id": case["case_id"], "status": status, "kind": "D",
            "candidate_head": pins["candidate_head"], "base_sha": pins["base_sha"],
            "spec_revision": case["requirements"], "policy_revision": pins["policy_revision"],
            "fixture_revision": sha256(regular(root, case["fixture"]).read_bytes()),
            "environment": {"python": ".".join(map(str, sys.version_info[:3])), "execution": "local_subprocess"},
            "command_or_runbook": {"runner": SCRIPT, "selectors": case["selectors"]},
            "started_at": started, "finished_at": now(), "observed": outcomes,
            "evidence_refs": [{"kind": "same_run", "case_id": case["case_id"], "run_alias": run_alias}],
            "limitations": LIMITATIONS, "remaining_owner": None if passed else "implementation_owner"})
    return {"schema_version": VERSION, "scope": "selected_source_d", "excluded": LIMITATIONS, "run_alias": run_alias,
            "binding": pins, "results": entries}


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
        for key in ("started_at", "finished_at"):
            require(isinstance(row[key], str) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", row[key]))
        require(row["finished_at"] >= row["started_at"])
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


def export(root, relative, report):
    target = artifact_path(root, relative, create=True)
    # Each execution gets a new artifact. Never replace earlier evidence, even on failure.
    require(not target.exists())
    data = (json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("ascii")
    require(len(data) <= 262144)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temp = ".pending-" + secrets.token_hex(8)
    created = False
    try:
        for part in ARTIFACT.parts:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
        created = True
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # dir_fd pins the validated parent; no-replace link preserves concurrent/old evidence.
        os.link(temp, target.name, src_dir_fd=descriptor, dst_dir_fd=descriptor, follow_symlinks=False)
        os.fsync(descriptor)
    finally:
        try:
            if created:
                os.unlink(temp, dir_fd=descriptor)
        finally:
            os.close(descriptor)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Invalid()


def main():
    result_fd = quiet()
    reason, code = "invalid_input", 2
    try:
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
        manifest = load_manifest(root)
        pins = binding(root, manifest, args.checked_sha, args.base_sha, args.source_head)
        if args.validate_report:
            passed = validate(read_json(artifact_path(root, args.validate_report)), root, manifest, pins)
        else:
            # Fail malformed output paths before tests; filesystem failures after execution never rerun tests.
            artifact_path(root, args.output, create=True)
            signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
            report = execute(root, manifest, pins)
            require(binding(root, load_manifest(root), args.checked_sha, args.base_sha, args.source_head) == pins)
            passed = validate(report, root, manifest, pins)
            reason = "export_failed"
            export(root, args.output, report)
        reason, code = ("passed", 0) if passed else ("required_evidence_incomplete", 1)
    except (KeyboardInterrupt, SystemExit):
        reason, code = "interrupted", 2
    except Exception:
        pass
    os.write(result_fd, (json.dumps({"status": "PASS" if code == 0 else "FAIL", "reason": reason}, sort_keys=True) + "\n").encode("ascii"))
    os.close(result_fd)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
