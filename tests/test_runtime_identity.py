"""Identity is a bounded observation, not a runtime qualification or secret dump."""
import copy
import json
import os
from pathlib import Path
import tempfile
import tomllib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hydra_sdlc import __version__
from hydra_sdlc import runtime_identity as identity


class RuntimeIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "package"
        self.root.mkdir()
        (self.root / "__init__.py").write_text('__version__ = "0.2.1"\n')
        (self.root / "worker.py").write_text("VALUE = 1\n")
        self.cfg = {"repos": ["example/beta", "example/alpha"], "host_alias": "test-host",
                    "workspace_root": "/private/example/work", "lock_path": "/private/example/host.lock",
                    "lifecycle_provider": "example.provider:create", "knowledge_repo": "example/knowledge"}
        self.control = SimpleNamespace(settings_path=Path("/private/example/host.lock.operations.json"),
            control_lock_path=Path("/private/example/host.lock.operations.lock"))

    def capture(self):
        return identity._capture_code_identity(self.root, "0.2.1")

    def test_version_has_one_package_corresponding_declaration(self):
        metadata = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
        self.assertEqual(__version__, "0.2.1")
        self.assertNotIn("version", metadata["project"])
        self.assertIn("version", metadata["project"]["dynamic"])
        self.assertEqual(metadata["tool"]["setuptools"]["dynamic"]["version"]["attr"], "hydra_sdlc.__version__")
        with patch("importlib.metadata.version", side_effect=AssertionError("unrelated distribution lookup")):
            self.assertEqual(identity.capture_runtime_identity()["version"], __version__)

    def test_hash_uses_bytes_relative_names_and_nested_sources(self):
        initial = self.capture()["code_digest"]
        self.assertRegex(initial, r"^[0-9a-f]{64}$")
        (self.root / "worker.py").write_text("VALUE = 2\n")
        changed = self.capture()["code_digest"]
        self.assertNotEqual(initial, changed)
        (self.root / "worker.py").rename(self.root / "other.py")
        self.assertNotEqual(changed, self.capture()["code_digest"])
        before = self.capture()["code_digest"]
        nested = self.root / "nested"
        nested.mkdir()
        (nested / "__init__.py").write_text("VALUE = 3\n")
        self.assertNotEqual(before, self.capture()["code_digest"])

    def test_non_source_bytecode_does_not_change_identity(self):
        before = self.capture()["code_digest"]
        cache = self.root / "__pycache__"
        cache.mkdir()
        (cache / "worker.pyc").write_bytes(b"compiled")
        (self.root / "notice.txt").write_text("not package source")
        self.assertEqual(before, self.capture()["code_digest"])

    def test_startup_capture_stays_fixed_after_disk_changes_and_result_mutation(self):
        initial = self.capture()
        with patch.object(identity, "_STARTUP_IDENTITY", initial), patch.object(
                identity, "_digest_sources", side_effect=AssertionError("rehash after startup")):
            before = identity.capture_runtime_identity()
            (self.root / "worker.py").write_text("VALUE = 999\n")
            returned = identity.capture_runtime_identity()
            returned["code_digest"] = "caller changed result"
            self.assertEqual(before, identity.capture_runtime_identity())
        self.assertNotEqual(initial["code_digest"], self.capture()["code_digest"])

    def test_symlink_source_directory_and_root_are_unavailable(self):
        link = self.root / "linked.py"
        link.symlink_to(self.root / "worker.py")
        self.assertEqual(self.capture()["identity_reason"], "runtime_source_unavailable")
        link.unlink()
        outside = self.root.parent / "outside"
        outside.mkdir()
        directory = self.root / "linked"
        directory.symlink_to(outside, target_is_directory=True)
        self.assertIsNone(self.capture()["code_digest"])
        directory.unlink()
        alias = self.root.parent / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        self.assertIsNone(identity._capture_code_identity(alias, "0.2.1")["code_digest"])

    def test_nonregular_source_and_source_bounds_are_unavailable(self):
        fifo = self.root / "blocked.py"
        os.mkfifo(fifo)
        self.assertIsNone(self.capture()["code_digest"])
        fifo.unlink()
        for constant, bound in (("MAX_SOURCE_FILES", 1), ("MAX_SOURCE_FILE_BYTES", 2),
                                ("MAX_SOURCE_BYTES", 2), ("MAX_DIRECTORY_ENTRIES", 1)):
            with self.subTest(constant=constant), patch.object(identity, constant, bound):
                self.assertEqual(self.capture()["identity_reason"], "runtime_source_unavailable")
        (self.root / "nested").mkdir()
        with patch.object(identity, "MAX_SOURCE_DEPTH", 0):
            self.assertIsNone(self.capture()["code_digest"])

    def test_edit_during_read_and_edit_of_already_read_source_are_detected(self):
        original_read = os.read
        reads = 0

        def racing_read(fd, size):
            nonlocal reads
            data = original_read(fd, size)
            if data:
                reads += 1
                if reads == 2:
                    (self.root / "__init__.py").write_text('__version__ = "0.2.2"\n')
            return data

        with patch.object(identity.os, "read", side_effect=racing_read):
            self.assertIsNone(self.capture()["code_digest"])
        reads = 0

        def same_file_race(fd, size):
            data = original_read(fd, size)
            if data:
                (self.root / "__init__.py").write_text("changed during read\n")
            return data

        with patch.object(identity.os, "read", side_effect=same_file_race):
            self.assertIsNone(self.capture()["code_digest"])

    def test_configuration_order_is_semantic_but_meaningful_changes_differ(self):
        changed = dict(reversed(list(self.cfg.items())))
        changed["repos"] = list(reversed(changed["repos"]))
        a = identity.capture_runtime_identity(self.cfg, self.control)
        self.assertEqual(a["config_digest"], identity.capture_runtime_identity(changed, self.control)["config_digest"])
        changed["host_alias"] = "other-host"
        self.assertNotEqual(a["config_digest"], identity.capture_runtime_identity(changed, self.control)["config_digest"])
        other_control = copy.copy(self.control)
        other_control.control_lock_path = Path("/private/example/other.lock")
        other = identity.capture_runtime_identity(self.cfg, other_control)
        self.assertEqual(a["config_digest"], other["config_digest"])
        self.assertNotEqual(a["control_binding_digest"], other["control_binding_digest"])

    def test_invalid_or_secret_configuration_never_emits_raw_values(self):
        for changes in ({"token": "synthetic-secret-must-not-appear"}, {"repos": ["Example/alpha"]},
                        {"workspace_root": "relative/private"}, {"host_alias": False},
                        {"storage_provider": "not:a:provider"}, {"project_threads": {"example/alpha": "bad"}}):
            with self.subTest(keys=list(changes)):
                cfg = {**self.cfg, **changes}
                result = identity.capture_runtime_identity(cfg, self.control)
                self.assertIsNone(result["config_digest"])
                self.assertEqual(result["identity_reason"], "runtime_config_unavailable")
                encoded = json.dumps(result)
                self.assertNotIn("synthetic-secret", encoded)
                self.assertNotIn("/private/example", encoded)
                self.assertNotIn("example/alpha", encoded)

    def test_absence_and_invalid_binding_do_not_fabricate_an_identity(self):
        result = identity.capture_runtime_identity()
        self.assertIsNone(result["config_digest"])
        self.assertIsNone(result["control_binding_digest"])
        broken = SimpleNamespace(settings_path="relative", control_lock_path="/valid/lock")
        result = identity.capture_runtime_identity(self.cfg, broken)
        self.assertIsNone(result["control_binding_digest"])
        self.assertEqual(result["identity_reason"], "runtime_control_binding_unavailable")
        self.assertEqual(identity._capture_code_identity(self.root, None)["identity_reason"], "runtime_version_unavailable")


if __name__ == "__main__":
    unittest.main()
