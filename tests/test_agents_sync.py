from __future__ import annotations

import contextlib
import importlib.util
import io
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "plugins"
    / "openboa-ai-native-sdlc"
    / "skills"
    / "openboa-ai-native-sdlc"
    / "scripts"
    / "sync_agents.py"
)
SPEC = importlib.util.spec_from_file_location("openboa_sync_agents", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
sync_agents = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync_agents
SPEC.loader.exec_module(sync_agents)


CURRENT_START = (
    "<!-- openboa-ai-native-sdlc:managed:start contract={version} -->"
)
CURRENT_END = "<!-- openboa-ai-native-sdlc:managed:end -->"
LEGACY_START = "<!-- openboa-operations:managed:start contract={version} -->"
LEGACY_END = "<!-- openboa-operations:managed:end -->"
LOCAL_HEADING = "## Repository-local instructions"


def managed_block(
    *, namespace: str = "current", version: str = "0.1.0", body: str = "- Keep the goal bounded."
) -> str:
    if namespace == "current":
        start = CURRENT_START.format(version=version)
        end = CURRENT_END
    else:
        start = LEGACY_START.format(version=version)
        end = LEGACY_END
    return f"{start}\n## Immediate execution contract\n\n{body}\n{end}"


class SyncAgentsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        # macOS exposes the temporary directory through /var -> /private/var.
        # Use the canonical path because the synchronizer deliberately refuses
        # any user-supplied path containing a symlinked ancestor.
        self.root = Path(self.temporary.name).resolve()
        self.template = self.root / "managed-AGENTS.md"
        self.template_block = managed_block()
        self.template.write_text(self.template_block + "\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_target(
        self,
        data: bytes,
        *,
        directory: Path | None = None,
        mode: int = 0o640,
    ) -> Path:
        parent = directory or self.root
        parent.mkdir(parents=True, exist_ok=True)
        target = parent / "AGENTS.md"
        target.write_bytes(data)
        os.chmod(target, mode)
        return target

    def state(self, target: Path) -> tuple[bytes, int, int, int]:
        info = os.lstat(target)
        return (
            target.read_bytes(),
            stat.S_IMODE(info.st_mode),
            info.st_ino,
            info.st_mtime_ns,
        )

    def assert_refused_without_write(self, target: Path, message: str) -> None:
        before = self.state(target)
        with self.assertRaisesRegex(sync_agents.SyncRefused, message):
            sync_agents.synchronize(
                target, write=True, template_path=self.template
            )
        self.assertEqual(self.state(target), before)

    def test_default_cli_mode_reports_drift_without_writing(self) -> None:
        original = (
            b"# Product\n\n"
            b"## Repository-local instructions\n\n"
            b"- This exact text belongs to the repository.\n"
        )
        target = self.make_target(original)
        before = self.state(target)
        stdout = io.StringIO()
        stderr = io.StringIO()

        with mock.patch.object(sync_agents, "DEFAULT_TEMPLATE", self.template):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = sync_agents.main([str(target)])

        self.assertEqual(exit_code, sync_agents.EXIT_DRIFT)
        self.assertIn("DRIFT: install required", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(self.state(target), before)

    def test_write_installs_atomically_and_preserves_local_bytes_and_mode(self) -> None:
        local = (
            b"## Repository-local instructions\n\n"
            b"- Preserve non-ASCII: \xec\x97\xb4\xeb\xa6\xb0.  \n"
        )
        target = self.make_target(b"# Product\n\n" + local, mode=0o751)

        result = sync_agents.synchronize(
            target, write=True, template_path=self.template
        )

        updated = target.read_bytes()
        self.assertTrue(result.changed)
        self.assertTrue(result.wrote)
        self.assertEqual(result.action, "install")
        self.assertIn(CURRENT_START.format(version="0.1.0").encode(), updated)
        self.assertEqual(updated[updated.index(local) :], local)
        self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o751)
        recoveries = list(target.parent.glob(".AGENTS.md.sync-*"))
        self.assertEqual(1, len(recoveries))
        self.assertEqual(result.recovery, recoveries[0])
        self.assertEqual(recoveries[0].read_bytes(), b"# Product\n\n" + local)

    def test_prepared_ownership_is_rechecked_after_content_write(self) -> None:
        target = self.make_target(
            f"# Product\n\n{LOCAL_HEADING}\n- Original.\n".encode()
        )
        before = self.state(target)
        original_read = sync_agents._read_snapshot_fd
        calls = 0

        def change_prepared_group(fd: int) -> sync_agents.Snapshot:
            nonlocal calls
            calls += 1
            snapshot = original_read(fd)
            if calls == 2:
                return sync_agents.dataclasses.replace(
                    snapshot, gid=snapshot.gid + 1
                )
            return snapshot

        with mock.patch.object(
            sync_agents, "_read_snapshot_fd", side_effect=change_prepared_group
        ):
            with self.assertRaisesRegex(
                sync_agents.SyncRefused, "preserve target ownership and group"
            ):
                sync_agents.synchronize(
                    target, write=True, template_path=self.template
                )

        self.assertEqual(self.state(target), before)
        self.assertEqual(list(target.parent.glob(".AGENTS.md.sync-*")), [])

    def test_cli_write_then_check_returns_success(self) -> None:
        target = self.make_target(
            f"# Product\n\n{LOCAL_HEADING}\n\n- Local.\n".encode()
        )
        with mock.patch.object(sync_agents, "DEFAULT_TEMPLATE", self.template):
            with contextlib.redirect_stdout(io.StringIO()):
                write_exit = sync_agents.main([str(target), "--write"])
            with contextlib.redirect_stdout(io.StringIO()):
                check_exit = sync_agents.main([str(target)])

        self.assertEqual(write_exit, sync_agents.EXIT_OK)
        self.assertEqual(check_exit, sync_agents.EXIT_OK)
        self.assertIn(b"openboa-ai-native-sdlc:managed:start", target.read_bytes())

    def test_directory_target_is_resolved_to_agents_file(self) -> None:
        target = self.make_target(
            f"# Product\n\n{LOCAL_HEADING}\n\n- Local.\n".encode()
        )

        result = sync_agents.synchronize(
            target.parent, write=True, template_path=self.template
        )

        self.assertEqual(result.target, target)
        self.assertTrue(result.wrote)

    def test_recognized_legacy_block_migrates_with_crlf_and_no_trailing_newline(self) -> None:
        legacy = managed_block(namespace="legacy").replace("\n", "\r\n").encode()
        local = (
            "## Workspace-local instructions\r\n\r\n"
            "- Keep  two spaces and unicode: caf\u00e9"
        ).encode()
        original = b"# Workspace\r\n\r\n" + legacy + b"\r\n\r\n" + local
        target = self.make_target(original, mode=0o744)

        result = sync_agents.synchronize(
            target, write=True, template_path=self.template
        )

        updated = target.read_bytes()
        self.assertEqual(result.action, "migrate")
        self.assertTrue(result.wrote)
        self.assertNotIn(b"openboa-operations:managed:", updated)
        self.assertIn(b"openboa-ai-native-sdlc:managed:", updated)
        self.assertEqual(updated[updated.index(local) :], local)
        self.assertFalse(updated.endswith(b"\n"))
        self.assertNotIn(b"\n", updated.replace(b"\r\n", b""))
        self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o744)

    def test_second_write_is_idempotent_and_does_not_replace_file(self) -> None:
        target = self.make_target(
            f"# Product\n\n{LOCAL_HEADING}\n\n- Local.\n".encode()
        )
        first = sync_agents.synchronize(
            target, write=True, template_path=self.template
        )
        after_first = self.state(target)

        second = sync_agents.synchronize(
            target, write=True, template_path=self.template
        )

        self.assertTrue(first.wrote)
        self.assertIsNotNone(first.recovery)
        self.assertFalse(second.changed)
        self.assertFalse(second.wrote)
        self.assertIsNone(second.recovery)
        self.assertEqual(self.state(target), after_first)

    def test_current_block_is_updated_without_touching_local_section(self) -> None:
        old_current = managed_block(body="- Outdated method.").encode()
        local = (
            b"## Repository-local instructions\n\n"
            b"- Local line one.\n\n- Local line two.\n"
        )
        target = self.make_target(
            b"# Product\n\n" + old_current + b"\n\n" + local
        )

        result = sync_agents.synchronize(
            target, write=True, template_path=self.template
        )

        updated = target.read_bytes()
        self.assertEqual(result.action, "update")
        self.assertNotIn(b"Outdated method", updated)
        self.assertEqual(updated[updated.index(local) :], local)

    def test_all_marker_and_heading_failures_leave_target_unchanged(self) -> None:
        current = managed_block()
        legacy = managed_block(namespace="legacy")
        cases = {
            "duplicate": (
                f"# Product\n\n{current}\n\n{current}\n\n{LOCAL_HEADING}\n- Local.\n",
                "duplicate",
            ),
            "malformed": (
                f"# Product\n\n{CURRENT_START.format(version='0.1.0')}\n"
                f"- Missing end.\n\n{LOCAL_HEADING}\n- Local.\n",
                "incomplete",
            ),
            "mixed": (
                f"# Product\n\n{current}\n\n{legacy}\n\n{LOCAL_HEADING}\n- Local.\n",
                "mixed current and legacy",
            ),
            "higher-current-major": (
                f"# Product\n\n{managed_block(version='1.0.0')}\n\n"
                f"{LOCAL_HEADING}\n- Local.\n",
                "newer current contract version",
            ),
            "higher-current-minor": (
                f"# Product\n\n{managed_block(version='0.2.0')}\n\n"
                f"{LOCAL_HEADING}\n- Local.\n",
                "newer current contract version",
            ),
            "higher-current-patch": (
                f"# Product\n\n{managed_block(version='0.1.1')}\n\n"
                f"{LOCAL_HEADING}\n- Local.\n",
                "newer current contract version",
            ),
            "higher-legacy-major": (
                f"# Product\n\n{managed_block(namespace='legacy', version='1.0.0')}\n\n"
                f"{LOCAL_HEADING}\n- Local.\n",
                "unsupported legacy contract version",
            ),
            "higher-legacy-minor": (
                f"# Product\n\n{managed_block(namespace='legacy', version='0.2.0')}\n\n"
                f"{LOCAL_HEADING}\n- Local.\n",
                "unsupported legacy contract version",
            ),
            "missing-local-heading": (
                f"# Product\n\n{current}\n",
                "missing repository/workspace local",
            ),
            "heading-inside-block": (
                f"# Product\n\n{CURRENT_START.format(version='0.1.0')}\n"
                f"{LOCAL_HEADING}\n- Local.\n{CURRENT_END}\n",
                "overlaps or follows local",
            ),
            "block-after-local": (
                f"# Product\n\n{LOCAL_HEADING}\n- Local.\n\n{current}\n",
                "overlaps or follows local",
            ),
            "multiple-local-headings": (
                f"# Product\n\n{current}\n\n{LOCAL_HEADING}\n- One.\n\n"
                "## Workspace-local instructions\n- Two.\n",
                "multiple or overlapping local",
            ),
            "mixed-line-endings": (
                f"# Product\r\n\r\n{LOCAL_HEADING}\n- Local.\n",
                "mixes LF and CRLF",
            ),
        }

        for name, (content, message) in cases.items():
            with self.subTest(name=name):
                case_dir = self.root / name
                target = self.make_target(content.encode(), directory=case_dir)
                self.assert_refused_without_write(target, message)

    def test_oversized_contract_component_is_a_controlled_refusal(self) -> None:
        digits = "9" * 5000
        target = self.make_target(
            (
                "# Product\n\n"
                f"<!-- openboa-ai-native-sdlc:managed:start contract={digits}.0.0 -->\n"
                "- Candidate.\n"
                f"{CURRENT_END}\n\n{LOCAL_HEADING}\n- Local.\n"
            ).encode()
        )

        self.assert_refused_without_write(target, "malformed.*managed marker")

    def test_fenced_or_commented_headings_and_markers_are_refused(self) -> None:
        current = managed_block()
        cases = {
            "fenced-heading": (
                "# Product\n\n```markdown\n"
                f"{LOCAL_HEADING}\n- Example only.\n```\n",
                "heading appears inside fenced code",
            ),
            "commented-heading": (
                "# Product\n\n<!--\n"
                f"{LOCAL_HEADING}\n- Example only.\n-->\n",
                "heading appears inside an enclosing HTML comment",
            ),
            "fenced-markers": (
                f"# Product\n\n```markdown\n{current}\n```\n\n"
                f"{LOCAL_HEADING}\n- Local.\n",
                "managed marker appears inside fenced code",
            ),
            "commented-markers": (
                f"# Product\n\n<!--\n{current}\n-->\n\n"
                f"{LOCAL_HEADING}\n- Local.\n",
                "managed marker appears inside an enclosing HTML comment",
            ),
            "inner-opening-fence-is-not-a-close": (
                "# Product\n\n```markdown\n```python\n"
                f"{LOCAL_HEADING}\n- Example only.\n```\n",
                "heading appears inside fenced code",
            ),
        }

        for name, (content, message) in cases.items():
            with self.subTest(name=name):
                target = self.make_target(
                    content.encode(), directory=self.root / name
                )
                self.assert_refused_without_write(target, message)

    def test_explicit_symlink_is_refused_without_touching_referent(self) -> None:
        referent_dir = self.root / "referent"
        referent = self.make_target(
            f"# Real\n\n{LOCAL_HEADING}\n- Keep.\n".encode(),
            directory=referent_dir,
        )
        link_dir = self.root / "link"
        link_dir.mkdir()
        link = link_dir / "AGENTS.md"
        link.symlink_to(referent)
        before = referent.read_bytes()

        with self.assertRaisesRegex(sync_agents.SyncRefused, "symlink"):
            sync_agents.synchronize(link, write=True, template_path=self.template)

        self.assertTrue(link.is_symlink())
        self.assertEqual(referent.read_bytes(), before)

    def test_directory_target_refuses_agents_symlink_resolving_outside(self) -> None:
        outside_dir = self.root / "outside"
        outside = self.make_target(
            f"# Outside\n\n{LOCAL_HEADING}\n- Keep.\n".encode(),
            directory=outside_dir,
        )
        target_dir = self.root / "target"
        target_dir.mkdir()
        (target_dir / "AGENTS.md").symlink_to(outside)
        before = outside.read_bytes()

        with self.assertRaisesRegex(sync_agents.SyncRefused, "outside target directory"):
            sync_agents.synchronize(
                target_dir, write=True, template_path=self.template
            )

        self.assertEqual(outside.read_bytes(), before)

    def test_symlinked_ancestor_is_refused_for_an_explicit_file(self) -> None:
        outside_dir = self.root / "ancestor-outside"
        nested_dir = outside_dir / "nested"
        outside = self.make_target(
            f"# Outside\n\n{LOCAL_HEADING}\n- Keep.\n".encode(),
            directory=nested_dir,
        )
        link = self.root / "ancestor-link"
        link.symlink_to(outside_dir, target_is_directory=True)
        before = self.state(outside)

        with self.assertRaisesRegex(sync_agents.SyncRefused, "symlinked ancestor"):
            sync_agents.synchronize(
                link / "nested" / "AGENTS.md",
                write=True,
                template_path=self.template,
            )

        self.assertEqual(self.state(outside), before)

    def test_parent_swap_after_resolution_cannot_redirect_the_write(self) -> None:
        selected_dir = self.root / "selected"
        selected = self.make_target(
            f"# Selected\n\n{LOCAL_HEADING}\n- Keep selected.\n".encode(),
            directory=selected_dir,
        )
        outside_dir = self.root / "swap-outside"
        outside = self.make_target(
            f"# Outside\n\n{LOCAL_HEADING}\n- Keep outside.\n".encode(),
            directory=outside_dir,
        )
        selected_before = self.state(selected)
        outside_before = self.state(outside)
        original_resolve = sync_agents.resolve_target

        def resolve_then_swap(value: object) -> object:
            resolved = original_resolve(value)
            moved = self.root / "selected-moved"
            selected_dir.rename(moved)
            selected_dir.symlink_to(outside_dir, target_is_directory=True)
            return resolved

        with mock.patch.object(sync_agents, "resolve_target", side_effect=resolve_then_swap):
            with self.assertRaisesRegex(sync_agents.SyncRefused, "bind target directory"):
                sync_agents.synchronize(
                    selected_dir, write=True, template_path=self.template
                )

        moved_selected = self.root / "selected-moved" / "AGENTS.md"
        self.assertEqual(self.state(moved_selected), selected_before)
        self.assertEqual(self.state(outside), outside_before)

    def test_parent_swap_after_directory_binding_cannot_redirect_the_write(self) -> None:
        selected_dir = self.root / "bound-selected"
        selected = self.make_target(
            f"# Selected\n\n{LOCAL_HEADING}\n- Keep selected.\n".encode(),
            directory=selected_dir,
        )
        selected_before = self.state(selected)
        replacement_data = (
            f"# Replacement\n\n{LOCAL_HEADING}\n- Keep replacement.\n".encode()
        )
        original_open = sync_agents._open_target_at

        def swap_then_open(parent_fd: int, *, write: bool) -> int:
            moved = self.root / "bound-selected-moved"
            selected_dir.rename(moved)
            replacement = self.make_target(
                replacement_data, directory=selected_dir
            )
            self.assertEqual(replacement.read_bytes(), replacement_data)
            return original_open(parent_fd, write=write)

        with mock.patch.object(sync_agents, "_open_target_at", side_effect=swap_then_open):
            with self.assertRaisesRegex(sync_agents.SyncRefused, "directory path changed"):
                sync_agents.synchronize(
                    selected_dir, write=True, template_path=self.template
                )

        moved_selected = self.root / "bound-selected-moved" / "AGENTS.md"
        replacement = selected_dir / "AGENTS.md"
        self.assertEqual(self.state(moved_selected), selected_before)
        self.assertEqual(replacement.read_bytes(), replacement_data)

    def test_change_at_exchange_boundary_is_restored_without_overwrite(self) -> None:
        target = self.make_target(
            f"# Product\n\n{LOCAL_HEADING}\n- Original.\n".encode()
        )
        original_exchange = sync_agents._atomic_exchange
        calls = 0

        def edit_then_exchange(parent_fd: int, left: str, right: str) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                target.write_text(
                    f"# Product\n\n{LOCAL_HEADING}\n- Concurrent edit.\n",
                    encoding="utf-8",
                )
            original_exchange(parent_fd, left, right)

        with mock.patch.object(sync_agents, "_atomic_exchange", side_effect=edit_then_exchange):
            with self.assertRaisesRegex(sync_agents.SyncRefused, "exchange boundary"):
                sync_agents.synchronize(
                    target, write=True, template_path=self.template
                )

        self.assertIn(b"Concurrent edit", target.read_bytes())
        self.assertNotIn(b"openboa-ai-native-sdlc:managed:start", target.read_bytes())
        recoveries = list(target.parent.glob(".AGENTS.md.sync-*"))
        self.assertEqual(1, len(recoveries))
        self.assertIn(
            b"openboa-ai-native-sdlc:managed:start", recoveries[0].read_bytes()
        )

    def test_change_after_exchange_keeps_visible_edit_and_original_recovery(self) -> None:
        target = self.make_target(
            f"# Product\n\n{LOCAL_HEADING}\n- Original.\n".encode()
        )
        original_exchange = sync_agents._atomic_exchange
        calls = 0

        def exchange_then_replace(parent_fd: int, left: str, right: str) -> None:
            nonlocal calls
            calls += 1
            original_exchange(parent_fd, left, right)
            if calls == 1:
                replacement = target.parent / "concurrent-replacement"
                replacement.write_text("# Concurrent replacement\n", encoding="utf-8")
                os.replace(replacement, target)

        with mock.patch.object(sync_agents, "_atomic_exchange", side_effect=exchange_then_replace):
            with self.assertRaisesRegex(
                sync_agents.SyncRefused, "pre-exchange file retained as"
            ):
                sync_agents.synchronize(
                    target, write=True, template_path=self.template
                )

        self.assertEqual(target.read_text(encoding="utf-8"), "# Concurrent replacement\n")
        recoveries = list(target.parent.glob(".AGENTS.md.sync-*"))
        self.assertEqual(1, len(recoveries))
        self.assertIn("- Original.", recoveries[0].read_text(encoding="utf-8"))

    def test_in_place_change_after_exchange_is_visible_and_original_is_recoverable(self) -> None:
        target = self.make_target(
            f"# Product\n\n{LOCAL_HEADING}\n- Original.\n".encode()
        )
        original_exchange = sync_agents._atomic_exchange
        calls = 0

        def exchange_then_edit(parent_fd: int, left: str, right: str) -> None:
            nonlocal calls
            calls += 1
            original_exchange(parent_fd, left, right)
            if calls == 1:
                target.write_text("# Concurrent in-place edit\n", encoding="utf-8")

        with mock.patch.object(sync_agents, "_atomic_exchange", side_effect=exchange_then_edit):
            with self.assertRaisesRegex(
                sync_agents.SyncRefused, "pre-exchange file retained as"
            ):
                sync_agents.synchronize(
                    target, write=True, template_path=self.template
                )

        self.assertEqual(target.read_text(encoding="utf-8"), "# Concurrent in-place edit\n")
        recoveries = list(target.parent.glob(".AGENTS.md.sync-*"))
        self.assertEqual(1, len(recoveries))
        self.assertIn("- Original.", recoveries[0].read_text(encoding="utf-8"))

    def test_metadata_change_after_exchange_is_refused_with_original_recovery(self) -> None:
        target = self.make_target(
            f"# Product\n\n{LOCAL_HEADING}\n- Original.\n".encode()
        )
        original_exchange = sync_agents._atomic_exchange
        calls = 0

        def exchange_then_chmod(parent_fd: int, left: str, right: str) -> None:
            nonlocal calls
            calls += 1
            original_exchange(parent_fd, left, right)
            if calls == 1:
                os.chmod(target, 0o777)

        with mock.patch.object(sync_agents, "_atomic_exchange", side_effect=exchange_then_chmod):
            with self.assertRaisesRegex(
                sync_agents.SyncRefused, "pre-exchange file retained as"
            ):
                sync_agents.synchronize(
                    target, write=True, template_path=self.template
                )

        self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o777)
        recoveries = list(target.parent.glob(".AGENTS.md.sync-*"))
        self.assertEqual(1, len(recoveries))
        self.assertIn("- Original.", recoveries[0].read_text(encoding="utf-8"))

    def test_post_exchange_durability_failure_rolls_back_the_original(self) -> None:
        target = self.make_target(
            f"# Product\n\n{LOCAL_HEADING}\n- Original.\n".encode()
        )
        before = self.state(target)
        original_fsync = sync_agents._fsync_directory
        calls = 0

        def fail_second_fsync(parent_fd: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise sync_agents.SyncRefused("injected directory fsync failure")
            original_fsync(parent_fd)

        with mock.patch.object(
            sync_agents, "_fsync_directory", side_effect=fail_second_fsync
        ):
            with self.assertRaisesRegex(
                sync_agents.SyncRefused, "injected directory fsync failure"
            ):
                sync_agents.synchronize(
                    target, write=True, template_path=self.template
                )

        self.assertEqual(self.state(target), before)
        recoveries = list(target.parent.glob(".AGENTS.md.sync-*"))
        self.assertEqual(1, len(recoveries))
        self.assertIn(
            b"openboa-ai-native-sdlc:managed:start", recoveries[0].read_bytes()
        )

    def test_late_fd_edit_after_rollback_survives_in_recovery(self) -> None:
        target = self.make_target(
            f"# Product\n\n{LOCAL_HEADING}\n- Original.\n".encode()
        )
        original_exchange = sync_agents._atomic_exchange
        original_read = sync_agents._read_snapshot_fd
        original_fsync = sync_agents._fsync_directory
        exchange_calls = 0
        fsync_calls = 0
        rolled_back = False
        injected = False
        editor_fd = -1

        def exchange_with_open_editor(parent_fd: int, left: str, right: str) -> None:
            nonlocal exchange_calls, editor_fd, rolled_back
            exchange_calls += 1
            original_exchange(parent_fd, left, right)
            if exchange_calls == 1:
                editor_fd = os.open(target, os.O_WRONLY)
            elif exchange_calls == 2:
                rolled_back = True

        def fail_post_exchange_fsync(parent_fd: int) -> None:
            nonlocal fsync_calls
            fsync_calls += 1
            if fsync_calls == 2:
                raise sync_agents.SyncRefused("injected post-exchange failure")
            original_fsync(parent_fd)

        def edit_after_snapshot(fd: int) -> sync_agents.Snapshot:
            nonlocal injected
            snapshot = original_read(fd)
            if rolled_back and not injected and snapshot.data.startswith(b"# Product"):
                injected = True
                os.lseek(editor_fd, 0, os.SEEK_SET)
                os.write(editor_fd, b"# Late fd edit\n")
                os.ftruncate(editor_fd, len(b"# Late fd edit\n"))
                os.fsync(editor_fd)
            return snapshot

        try:
            with mock.patch.object(
                sync_agents, "_atomic_exchange", side_effect=exchange_with_open_editor
            ), mock.patch.object(
                sync_agents, "_fsync_directory", side_effect=fail_post_exchange_fsync
            ), mock.patch.object(
                sync_agents, "_read_snapshot_fd", side_effect=edit_after_snapshot
            ):
                with self.assertRaisesRegex(
                    sync_agents.SyncRefused, "recovery retained as"
                ):
                    sync_agents.synchronize(
                        target, write=True, template_path=self.template
                    )
        finally:
            if editor_fd >= 0:
                os.close(editor_fd)

        self.assertIn("- Original.", target.read_text(encoding="utf-8"))
        recoveries = list(target.parent.glob(".AGENTS.md.sync-*"))
        self.assertEqual(1, len(recoveries))
        self.assertEqual(recoveries[0].read_text(encoding="utf-8"), "# Late fd edit\n")

    def test_late_fd_edit_after_success_survives_in_recovery(self) -> None:
        target = self.make_target(
            f"# Product\n\n{LOCAL_HEADING}\n- Original.\n".encode()
        )
        editor_fd = os.open(target, os.O_WRONLY)
        original_assert = sync_agents._assert_parent_binding
        calls = 0

        def edit_at_final_binding(
            resolved: sync_agents.ResolvedTarget, parent_fd: int
        ) -> None:
            nonlocal calls
            calls += 1
            original_assert(resolved, parent_fd)
            if calls == 5:
                os.lseek(editor_fd, 0, os.SEEK_SET)
                os.write(editor_fd, b"# Late pre-exchange inode edit\n")
                os.ftruncate(editor_fd, len(b"# Late pre-exchange inode edit\n"))
                os.fsync(editor_fd)

        try:
            with mock.patch.object(
                sync_agents, "_assert_parent_binding", side_effect=edit_at_final_binding
            ):
                result = sync_agents.synchronize(
                    target, write=True, template_path=self.template
                )
        finally:
            os.close(editor_fd)

        self.assertTrue(result.wrote)
        self.assertIn(
            b"openboa-ai-native-sdlc:managed:start", target.read_bytes()
        )
        assert result.recovery is not None
        self.assertEqual(
            result.recovery.read_text(encoding="utf-8"),
            "# Late pre-exchange inode edit\n",
        )

    def test_success_has_no_fallible_backup_cleanup_after_commit(self) -> None:
        target = self.make_target(
            f"# Product\n\n{LOCAL_HEADING}\n- Original.\n".encode()
        )
        original_fsync = sync_agents._fsync_directory
        calls = 0

        def fail_third_fsync(parent_fd: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 3:
                raise sync_agents.SyncRefused("injected cleanup fsync failure")
            original_fsync(parent_fd)

        with mock.patch.object(
            sync_agents, "_fsync_directory", side_effect=fail_third_fsync
        ):
            result = sync_agents.synchronize(
                target, write=True, template_path=self.template
            )

        self.assertTrue(result.wrote)
        self.assertEqual(calls, 2)
        self.assertIn(b"openboa-ai-native-sdlc:managed:start", target.read_bytes())
        recoveries = list(target.parent.glob(".AGENTS.md.sync-*"))
        self.assertEqual(1, len(recoveries))
        self.assertEqual(result.recovery, recoveries[0])

    def test_unsupported_atomic_exchange_refuses_without_a_partial_write(self) -> None:
        target = self.make_target(
            f"# Product\n\n{LOCAL_HEADING}\n- Original.\n".encode()
        )
        before = self.state(target)

        with mock.patch.object(
            sync_agents,
            "_atomic_exchange",
            side_effect=sync_agents.SyncRefused(
                "host does not support atomic file exchange"
            ),
        ):
            with self.assertRaisesRegex(
                sync_agents.SyncRefused, "does not support atomic file exchange"
            ):
                sync_agents.synchronize(
                    target, write=True, template_path=self.template
                )

        self.assertEqual(self.state(target), before)
        self.assertEqual(list(target.parent.glob(".AGENTS.md.sync-*")), [])

    def test_existing_recovery_file_stops_a_new_write(self) -> None:
        target = self.make_target(
            f"# Product\n\n{LOCAL_HEADING}\n- Original.\n".encode()
        )
        recovery = target.parent / ".AGENTS.md.sync-review-required"
        recovery.write_text("original recovery", encoding="utf-8")
        before = self.state(target)

        with self.assertRaisesRegex(sync_agents.SyncRefused, "recovery file exists"):
            sync_agents.synchronize(
                target, write=True, template_path=self.template
            )

        self.assertEqual(self.state(target), before)
        self.assertTrue(recovery.exists())

    @unittest.skipIf(sync_agents.fcntl is None, "flock support is required")
    def test_existing_exclusive_lock_stops_a_competing_write(self) -> None:
        target = self.make_target(
            f"# Product\n\n{LOCAL_HEADING}\n- Original.\n".encode()
        )
        before = self.state(target)
        fd = os.open(target, os.O_RDONLY)
        try:
            sync_agents.fcntl.flock(
                fd, sync_agents.fcntl.LOCK_EX | sync_agents.fcntl.LOCK_NB
            )
            with self.assertRaisesRegex(sync_agents.SyncRefused, "locked"):
                sync_agents.synchronize(
                    target, write=True, template_path=self.template
                )
        finally:
            os.close(fd)

        self.assertEqual(self.state(target), before)

    def test_hard_linked_target_is_refused_without_breaking_links(self) -> None:
        target = self.make_target(
            f"# Product\n\n{LOCAL_HEADING}\n- Original.\n".encode()
        )
        alias = target.parent / "AGENTS.alias.md"
        os.link(target, alias)
        original = target.read_bytes()

        with self.assertRaisesRegex(sync_agents.SyncRefused, "multiple hard links"):
            sync_agents.synchronize(
                target, write=True, template_path=self.template
            )

        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(alias.read_bytes(), original)
        self.assertEqual(os.stat(target).st_ino, os.stat(alias).st_ino)

    def test_extended_attribute_is_refused_and_preserved(self) -> None:
        target = self.make_target(
            f"# Product\n\n{LOCAL_HEADING}\n- Original.\n".encode()
        )
        attribute = "user.openboa.sync-test"
        if hasattr(os, "setxattr"):
            try:
                os.setxattr(target, attribute, b"keep")
            except OSError as exc:
                self.skipTest(f"filesystem cannot create a test xattr: {exc}")
            read_attribute = lambda: os.getxattr(target, attribute)
        elif sys.platform == "darwin":
            attribute = "com.openboa.sync-test"
            try:
                subprocess.run(
                    ["xattr", "-w", attribute, "keep", str(target)], check=True
                )
            except (OSError, subprocess.CalledProcessError) as exc:
                self.skipTest(f"filesystem cannot create a test xattr: {exc}")
            read_attribute = lambda: subprocess.run(
                ["xattr", "-p", attribute, str(target)],
                check=True,
                capture_output=True,
            ).stdout.rstrip(b"\n")
        else:
            self.skipTest("host cannot create a test extended attribute")
        before = self.state(target)

        with self.assertRaisesRegex(sync_agents.SyncRefused, "extended attribute"):
            sync_agents.synchronize(
                target, write=True, template_path=self.template
            )

        self.assertEqual(self.state(target), before)
        self.assertEqual(read_attribute(), b"keep")

    @unittest.skipUnless(sys.platform == "darwin", "macOS ACL test")
    def test_extended_acl_is_refused_and_preserved(self) -> None:
        target = self.make_target(
            f"# Product\n\n{LOCAL_HEADING}\n- Original.\n".encode()
        )
        subprocess.run(
            ["chmod", "+a", "everyone deny write", str(target)], check=True
        )
        before_acl = subprocess.run(
            ["ls", "-le", str(target)], check=True, capture_output=True, text=True
        ).stdout

        with self.assertRaises(sync_agents.SyncRefused):
            sync_agents.synchronize(
                target, write=True, template_path=self.template
            )

        after_acl = subprocess.run(
            ["ls", "-le", str(target)], check=True, capture_output=True, text=True
        ).stdout
        self.assertEqual(after_acl, before_acl)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO support is required")
    def test_non_regular_file_is_refused_without_opening_it(self) -> None:
        fifo_dir = self.root / "fifo"
        fifo_dir.mkdir()
        fifo = fifo_dir / "AGENTS.md"
        os.mkfifo(fifo)

        with self.assertRaisesRegex(sync_agents.SyncRefused, "not a regular file"):
            sync_agents.synchronize(fifo, write=True, template_path=self.template)

        self.assertTrue(stat.S_ISFIFO(os.lstat(fifo).st_mode))

    def test_agents_override_precedence_refuses_write(self) -> None:
        directory = self.root / "override"
        target = self.make_target(
            f"# Product\n\n{LOCAL_HEADING}\n- Local.\n".encode(),
            directory=directory,
        )
        (directory / "AGENTS.override.md").write_text("# Override\n", encoding="utf-8")
        before = self.state(target)

        with self.assertRaisesRegex(sync_agents.SyncRefused, "takes precedence"):
            sync_agents.synchronize(
                directory, write=True, template_path=self.template
            )

        self.assertEqual(self.state(target), before)

    def test_invalid_template_fails_without_writing_target(self) -> None:
        target = self.make_target(
            f"# Product\n\n{LOCAL_HEADING}\n- Local.\n".encode()
        )
        invalid_template = self.root / "invalid-template.md"
        invalid_template.write_text("# No managed block\n", encoding="utf-8")
        before = self.state(target)

        with self.assertRaisesRegex(sync_agents.TemplateError, "no current managed block"):
            sync_agents.synchronize(
                target, write=True, template_path=invalid_template
            )

        self.assertEqual(self.state(target), before)

    def test_cli_exit_codes_distinguish_refusal_and_template_error(self) -> None:
        missing_local = self.make_target(b"# Product\n")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(sync_agents, "DEFAULT_TEMPLATE", self.template):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                refused = sync_agents.main([str(missing_local), "--write"])
        self.assertEqual(refused, sync_agents.EXIT_REFUSED)
        self.assertIn("REFUSED:", stderr.getvalue())

        valid = self.make_target(
            f"# Product\n\n{LOCAL_HEADING}\n- Local.\n".encode(),
            directory=self.root / "missing-asset",
        )
        with mock.patch.object(
            sync_agents, "DEFAULT_TEMPLATE", self.root / "does-not-exist.md"
        ):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                io.StringIO()
            ):
                template_error = sync_agents.main([str(valid)])
        self.assertEqual(template_error, sync_agents.EXIT_ERROR)


if __name__ == "__main__":
    unittest.main()
