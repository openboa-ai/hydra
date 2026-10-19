"""Run the workflow's real whitespace check against isolated Git objects."""

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ASSETS = {
    "apps/mac/public/fonts/MartianGrotesk-wdth-wght.ttf":
        "f81807163c34ff754e6d915b0b59f76cca88332b67c45cfc7453ace5751ae912",
    "apps/mac/public/fonts/PretendardVariable.woff2":
        "9599f12fd42fc0bce1cd50b47a0c022e108d7aa64dd0d1bb0ed44f3282d900b4",
    "apps/mac/src-tauri/icons/icon.png":
        "005be38b40da8a96037bc632b6f2c3ff48028d007b9e959dc9ed2a6543c3580c",
}
ZERO = "0" * 40


def whitespace_script():
    """Extract one literal run block, without interpreting candidate YAML."""
    lines = (ROOT / ".github/workflows/ci.yml").read_text().splitlines()
    starts = [i for i, line in enumerate(lines) if re.fullmatch(r" +\- name: Check whitespace", line)]
    if len(starts) != 1:
        raise AssertionError("Expected exactly one Check whitespace step")
    start = starts[0]
    step_indent = len(lines[start]) - len(lines[start].lstrip())
    run = None
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.strip() and len(line) - len(line.lstrip()) <= step_indent:
            break
        if line == " " * (step_indent + 2) + "run: |":
            run = index
            break
    if run is None:
        raise AssertionError("Whitespace check must remain an inline literal script")
    body = []
    prefix = " " * (step_indent + 4)
    for line in lines[run + 1:]:
        if not line.strip():
            body.append("")
        elif line.startswith(prefix):
            body.append(line[len(prefix):])
        else:
            break
    script = "\n".join(body) + "\n"
    if not body or "git -C candidate diff --check" not in script:
        raise AssertionError("The extracted script must include the actual whitespace diff")
    return script


class GitFixture:
    def __init__(self, directory, assets):
        self.root = Path(directory)
        self.repo = self.root / "candidate"
        self.repo.mkdir()
        self.assets = assets
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith("GIT_") and key not in {"BASH_ENV", "ENV", "CDPATH"}}
        self.env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_AUTHOR_NAME="Hygiene fixture", GIT_COMMITTER_NAME="Hygiene fixture",
                        GIT_AUTHOR_EMAIL="fixture@example.invalid", GIT_COMMITTER_EMAIL="fixture@example.invalid",
                        LC_ALL="C")
        self.git("init", "--quiet", "--object-format=sha1")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "core.filemode", "true")
        self.write("README.md", b"Whitespace fixture.\n")

    def git(self, *args, data=None, check=True):
        result = subprocess.run(["git", "-C", str(self.repo), *args], input=data,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=self.env, timeout=15)
        if check and result.returncode:
            raise AssertionError(result.stderr.decode(errors="replace")[-2000:])
        return result.stdout.decode().strip() if check else result

    def write(self, path, content):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def add_assets(self):
        for path, content in self.assets.items():
            self.write(path, content)

    def commit(self, *, index_only=False):
        if not index_only:
            self.git("add", "--all")
        self.git("commit", "--quiet", "-m", "Fixture revision")
        return self.git("rev-parse", "HEAD")

    def asset_entry(self, path, kind, commit_id):
        """Install exact index modes, independently of filesystem mode support."""
        self.git("rm", "--cached", "-r", "--ignore-unmatch", "--", path)
        data = self.assets[path]
        mode, object_type = "100644", "blob"
        if kind == "changed_bytes":
            data += b"changed"
        elif kind == "text":
            data = b"A text replacement with no whitespace error.\n"
        elif kind == "symlink":
            mode, data = "120000", b"unrelated-target"
        elif kind == "executable":
            mode = "100755"
        elif kind == "gitlink":
            mode, object_type = "160000", "commit"
        elif kind == "tree":
            mode, object_type, data = "040000", "tree", b"Child content.\n"
        elif kind != "valid":
            raise AssertionError("Unknown fixture kind")
        object_id = commit_id if kind == "gitlink" else self.git("hash-object", "-w", "--stdin", data=data)
        if kind == "tree":
            object_id = self.git("mktree", data=f"100644 blob {object_id}\tchild.txt\n".encode())
            self.git("read-tree", f"--prefix={path}/", object_id)
        else:
            self.git("update-index", "--add", "--cacheinfo", f"{mode},{object_id},{path}")
        revision = self.commit(index_only=True)
        actual = self.git("ls-tree", revision, "--", path)
        if actual != f"{mode} {object_type} {object_id}\t{path}":
            raise AssertionError("The fixture did not create the intended Git object")
        return revision

    def check(self, script, base, checked=None):
        return subprocess.run(["bash", "--noprofile", "--norc", "-c", script],
                              cwd=self.root, env={**self.env, "BASE_SHA": base,
                                                 "CHECKED_SHA": checked or self.git("rev-parse", "HEAD")},
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              errors="replace", timeout=20)


class WhitespaceWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for command in ("git", "bash", "sha256sum"):
            if shutil.which(command) is None:
                raise RuntimeError(f"Required whitespace test command is unavailable: {command}")
        cls.script = whitespace_script()
        cls.assets = {path: (ROOT / path).read_bytes() for path in ASSETS}
        for path, content in cls.assets.items():
            if hashlib.sha256(content).hexdigest() != ASSETS[path]:
                raise AssertionError(f"The real asset fixture changed: {path}")

    def fixture(self, *, assets=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        fixture = GitFixture(temporary.name, self.assets)
        if assets:
            fixture.add_assets()
        return fixture

    def assert_check(self, fixture, base, *, succeeds, checked=None):
        result = fixture.check(self.script, base, checked)
        detail = (result.stdout + result.stderr)[-3000:]
        if succeeds:
            self.assertEqual(result.returncode, 0, detail)
        else:
            self.assertNotEqual(result.returncode, 0, "Unsafe candidate passed the actual whitespace script")
        return result

    def test_extracted_script_keeps_whitespace_and_diff_safety_options(self):
        diff = next(line for line in self.script.splitlines() if line.startswith("git -C candidate diff --check"))
        for option in ("--no-renames", "--no-ext-diff", "--no-textconv"):
            self.assertIn(option, diff)
        self.assertIn("* diff whitespace=blank-at-eol,blank-at-eof,space-before-tab", self.script)

    def test_original_asset_addition_and_unchanged_assets_pass(self):
        fixture = self.fixture()
        base = fixture.commit()
        fixture.add_assets()
        head = fixture.commit()
        self.assert_check(fixture, base, succeeds=True)
        fixture.write("src/example.py", b"answer = 42\n")
        fixture.commit()
        self.assert_check(fixture, head, succeeds=True)

    def test_valid_asset_deletion_passes(self):
        fixture = self.fixture(assets=True)
        base = fixture.commit()
        for path in ASSETS:
            (fixture.repo / path).unlink()
        fixture.commit()
        self.assert_check(fixture, base, succeeds=True)

    def test_initial_zero_base_passes_without_preseeding_an_empty_tree(self):
        fixture = self.fixture(assets=True)
        # This is the first commit: no previous empty tree was created by a seed.
        fixture.commit()
        self.assert_check(fixture, ZERO, succeeds=True)

    def test_genuine_absence_is_not_a_asset_override(self):
        for included in (None, *ASSETS):
            with self.subTest(included=included):
                fixture = self.fixture()
                base = fixture.commit()
                if included:
                    fixture.write(included, self.assets[included])
                fixture.write("src/example.py", b"answer = 42\n")
                fixture.commit()
                self.assert_check(fixture, base, succeeds=True)
                attributes = (fixture.repo / ".git/info/attributes").read_text().splitlines()
                for path in ASSETS:
                    self.assertEqual(f"{path} -diff" in attributes, path == included)

    def test_candidate_attributes_cannot_hide_source_whitespace(self):
        fixture = self.fixture(assets=True)
        base = fixture.commit()
        fixture.write(".gitattributes", b"* -diff -whitespace\n")
        fixture.write("src/example.py", b"answer = 42  \n")
        fixture.commit()
        result = self.assert_check(fixture, base, succeeds=False)
        self.assertIn("src/example.py", result.stdout + result.stderr)

    def test_ofl_notice_whitespace_remains_checked(self):
        for name in ("LICENSE-MartianGrotesk-OFL.txt", "LICENSE-Pretendard-OFL.txt"):
            with self.subTest(name=name):
                fixture = self.fixture(assets=True)
                base = fixture.commit()
                path = "apps/mac/public/fonts/" + name
                fixture.write(path, (ROOT / path).read_bytes() + b"Notice whitespace fixture.  \n")
                fixture.write(".gitattributes", b"apps/mac/public/fonts/* -diff -whitespace\n")
                fixture.commit()
                result = self.assert_check(fixture, base, succeeds=False)
                self.assertIn(name, result.stdout + result.stderr)

    def test_unreviewed_asset_bytes_and_nonregular_objects_fail_at_either_endpoint(self):
        for path in ASSETS:
            for kind in ("changed_bytes", "text", "symlink", "executable", "tree", "gitlink"):
                for endpoint in ("base", "head"):
                    with self.subTest(path=path, kind=kind, endpoint=endpoint):
                        fixture = self.fixture(assets=True)
                        valid = fixture.commit()
                        invalid = fixture.asset_entry(path, kind, valid)
                        base = valid
                        if endpoint == "base":
                            base = invalid
                            fixture.asset_entry(path, "valid", valid)
                        self.assert_check(fixture, base, succeeds=False)

    def test_invalid_deleted_base_asset_is_not_treated_as_absent(self):
        fixture = self.fixture(assets=True)
        valid = fixture.commit()
        path = next(iter(ASSETS))
        base = fixture.asset_entry(path, "changed_bytes", valid)
        fixture.git("rm", "--cached", "--", path)
        fixture.commit(index_only=True)
        self.assert_check(fixture, base, succeeds=False)

    def test_missing_invalid_and_non_tree_base_queries_fail(self):
        fixture = self.fixture(assets=True)
        fixture.commit()
        blob = fixture.git("hash-object", "-w", "--stdin", data=b"Not a tree.\n")
        for base in ("", "not-a-revision", "1" * 40, blob):
            with self.subTest(base=base):
                self.assert_check(fixture, base, succeeds=False)

    def test_missing_asset_blob_read_fails_before_granting_an_override(self):
        fixture = self.fixture(assets=True)
        base = fixture.commit()
        fixture.write("src/example.py", b"answer = 42\n")
        fixture.commit()
        path = next(iter(ASSETS))
        object_id = fixture.git("rev-parse", f"HEAD:{path}")
        loose_object = fixture.repo / ".git/objects" / object_id[:2] / object_id[2:]
        self.assertTrue(loose_object.is_file())
        loose_object.unlink()
        # The tree entry is still present, but cat-file must fail closed.
        self.assertIn(object_id, fixture.git("ls-tree", "HEAD", "--", path))
        self.assert_check(fixture, base, succeeds=False)
        self.assertNotIn(f"{path} -diff", (fixture.repo / ".git/info/attributes").read_text())

    def test_renamed_mutated_destination_cannot_inherit_a_asset_exception(self):
        for path in ASSETS:
            with self.subTest(path=path):
                fixture = self.fixture(assets=True)
                base = fixture.commit()
                destination = "src/renamed-asset.txt"
                (fixture.repo / path).unlink()
                fixture.write(destination, self.assets[path] + b"\nsource whitespace  \n")
                fixture.write(".gitattributes", b"src/renamed-asset.txt -diff -whitespace\n")
                fixture.commit()
                result = self.assert_check(fixture, base, succeeds=False)
                self.assertIn(destination, result.stdout + result.stderr)

    def test_checked_head_must_match_the_actual_checkout(self):
        fixture = self.fixture(assets=True)
        base = fixture.commit()
        fixture.write("src/example.py", b"answer = 42\n")
        fixture.commit()
        self.assert_check(fixture, base, checked=base, succeeds=False)


if __name__ == "__main__":
    unittest.main()
