"""Admission settings are durable controls, never evidence a worker stopped."""

import asyncio
import json
import os
import select
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

from hydra_sdlc.operations import (
    MAX_REVISION, MAX_SETTINGS_BYTES, OperatingControl, OperationDenied,
)


REPOS = ("example/alpha", "example/beta")
DRIVER = """
import os
import sys
from hydra_sdlc.operations import OperatingControl, OperationDenied
control = OperatingControl(sys.argv[1], ('example/alpha', 'example/beta'))
action = sys.argv[2]
if action == 'effect':
    with control.guard('example/alpha'):
        print('admitted', flush=True)
        sys.stdin.readline()
        print('effect-finished', flush=True)
elif action == 'pause':
    print('requesting', flush=True)
    snapshot = control.set_mode('pause')
    print('applied:' + str(snapshot['revision']), flush=True)
elif action == 'project':
    print('requesting', flush=True)
    sys.stdin.readline()
    print(control.set_mode('pause', sys.argv[3])['revision'], flush=True)
elif action == 'reason':
    print(control.reason('example/alpha'), flush=True)
elif action == 'held-update':
    from unittest.mock import patch
    replace = os.replace
    def pending_replace(*args, **kwargs):
        replace(*args, **kwargs)
        print('locked', flush=True)
        sys.stdin.readline()
    with patch('hydra_sdlc.operations.os.replace', side_effect=pending_replace):
        control.set_mode('pause', 'example/beta')
"""


class OperatingControlTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        # On macOS the conventional temp prefix can itself be a symlink. The
        # fixture is an explicit physical path, just like trusted host settings.
        self.root = Path(temporary.name).resolve()
        self.lock = self.root / "host.lock"
        self.control = OperatingControl(self.lock, REPOS)

    def denied(self, reason, callback):
        with self.assertRaises(OperationDenied) as raised:
            callback()
        self.assertEqual(raised.exception.reason, reason)
        self.assertEqual(str(raised.exception), reason)

    def write_value(self, value):
        self.control.settings_path.write_text(json.dumps(value), encoding="utf-8")
        self.control.settings_path.chmod(0o600)

    def process(self, *args):
        child = subprocess.Popen(
            [sys.executable, "-c", DRIVER, str(self.lock), *args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        def cleanup():
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)
        self.addCleanup(cleanup)
        return child

    def line(self, child):
        self.assertTrue(select.select([child.stdout], [], [], 5)[0], "child did not respond")
        return child.stdout.readline().strip()

    def test_missing_snapshot_is_read_only_and_stopped(self):
        control = OperatingControl(self.root / "absent" / "host.lock", REPOS)
        self.assertEqual(control.snapshot(), {
            "version": 1, "revision": 0, "global_mode": "stopped", "projects": {}, "updated_at": None,
        })
        self.assertEqual(control.reason(REPOS[0]), "host_stopped")
        self.assertFalse((self.root / "absent").exists())
        self.assertFalse(self.lock.exists())

    def test_default_guard_denies_and_uses_separate_lock(self):
        self.denied("host_stopped", lambda: self.control.guard(REPOS[0]).__enter__())
        self.assertFalse(self.lock.exists())
        self.assertTrue(self.control.control_lock_path.exists())
        self.assertFalse(self.control.settings_path.exists())

    def test_start_and_resume_preserve_project_overrides(self):
        self.control.set_mode("start")
        self.control.set_mode("pause", REPOS[0])
        self.control.set_mode("stop", REPOS[1])
        for action in ("pause", "resume", "stop", "start"):
            self.control.set_mode(action)
        snapshot = self.control.snapshot()
        self.assertEqual(snapshot["revision"], 7)
        self.assertEqual(snapshot["projects"], {REPOS[0]: "paused", REPOS[1]: "stopped"})
        self.assertEqual(self.control.reason(REPOS[0]), "project_paused")
        self.assertEqual(self.control.reason(REPOS[1]), "project_stopped")
        self.assertIsNone(self.control.reason())

    def test_project_start_requires_global_permission_without_writing(self):
        for initial in ("pause", "stop"):
            self.control.set_mode(initial)
            self.control.set_mode("stop", REPOS[0])
            previous = self.control.settings_path.read_bytes()
            for action in ("start", "resume"):
                self.denied("host_" + ("paused" if initial == "pause" else "stopped"),
                            lambda: self.control.set_mode(action, REPOS[0]))
                self.assertEqual(self.control.settings_path.read_bytes(), previous)

    def test_project_pause_only_blocks_its_repository(self):
        self.control.set_mode("start")
        self.control.set_mode("pause", REPOS[0])
        self.assertEqual(self.control.reason(REPOS[0]), "project_paused")
        with self.control.guard(REPOS[1]) as snapshot:
            self.assertEqual(snapshot["global_mode"], "running")
        self.control.set_mode("resume", REPOS[0])
        self.assertIsNone(self.control.reason(REPOS[0]))

    def test_new_project_inherits_global_and_removed_override_is_preserved(self):
        self.control.set_mode("start")
        self.control.set_mode("pause", REPOS[0])
        other = OperatingControl(self.lock, (REPOS[1], "example/new"))
        self.assertIsNone(other.reason("example/new"))
        self.assertEqual(other.reason(REPOS[0]), "operation_state_repository_unregistered")
        other.set_mode("pause", "example/new")
        self.assertEqual(self.control.snapshot()["projects"][REPOS[0]], "paused")

    def test_repository_validation_and_empty_allowlist_are_fail_closed(self):
        control = OperatingControl(self.lock)
        for repository in (REPOS[0], "EXAMPLE/ALPHA"):
            self.assertEqual(control.reason(repository), "operation_state_repository_unregistered")
            self.denied("operation_state_repository_unregistered",
                        lambda: control.set_mode("pause", repository))
        for repository in ("../alpha", "example/..", "example/alpha/extra", "a b/c", 2):
            self.denied("operation_state_repository_invalid", lambda: self.control.set_mode("pause", repository))
        self.denied("operation_state_repository_invalid", lambda: OperatingControl(self.lock, None))
        self.denied("operation_state_repository_invalid", lambda: OperatingControl(self.lock, REPOS[0]))
        control.set_mode("start")
        self.assertIsNone(self.control.reason("EXAMPLE/ALPHA"))

    def test_invalid_action_does_not_create_controls(self):
        for action in (None, "running", "START", [], True):
            self.denied("operation_state_action_invalid", lambda: self.control.set_mode(action))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_modes_survive_new_process_and_snapshot_has_only_operating_settings(self):
        self.control.set_mode("start")
        self.control.set_mode("pause", REPOS[0])
        process = self.process("reason")
        output, error = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0, error)
        self.assertEqual(output.strip(), "project_paused")
        self.assertEqual(set(self.control.snapshot()), {
            "version", "revision", "global_mode", "projects", "updated_at",
        })
        self.assertEqual(self.control.settings_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.control.control_lock_path.stat().st_mode & 0o777, 0o600)

    def test_corruption_is_not_repaired_by_start_pause_or_cleanup(self):
        self.control.set_mode("start")
        invalid = (
            b"{}", b"null", b"[1]", b"\xff", b"{" * 1500,
            b'{"version":1,"version":1}', b'{"version":NaN}',
        )
        for raw in invalid:
            with self.subTest(raw=raw[:20]):
                self.control.settings_path.write_bytes(raw)
                self.assertEqual(self.control.reason(REPOS[0]), "operation_state_invalid")
                for action in ("start", "pause", "stop"):
                    self.denied("operation_state_invalid", lambda: self.control.set_mode(action))
                self.denied("operation_state_invalid",
                            lambda: self.control.guard(REPOS[0], cleanup=True).__enter__())
                self.assertEqual(self.control.settings_path.read_bytes(), raw)

    def test_strict_snapshot_fields_and_timestamp(self):
        valid = self.control.set_mode("start")
        changes = ({"version": True}, {"version": 2}, {"revision": False}, {"revision": -1},
                   {"revision": MAX_REVISION + 1}, {"global_mode": "ready"},
                   {"projects": []}, {"projects": {"EXAMPLE/ALPHA": "paused"}},
                   {"projects": {"example/..": "paused"}}, {"projects": {REPOS[0]: False}},
                   {"updated_at": "2026-99-99T00:00:00.000000Z"}, {"updated_at": None},
                   {"revision": 0, "updated_at": None}, {"history": []})
        for change in changes:
            with self.subTest(change=change):
                self.write_value({**valid, **change})
                self.denied("operation_state_invalid", self.control.snapshot)

    def test_nested_duplicate_project_keys_and_oversized_input_are_rejected(self):
        self.control.set_mode("start")
        raw = self.control.settings_path.read_text().replace('"projects":{}',
            '"projects":{"example/alpha":"paused","example/alpha":"running"}')
        self.control.settings_path.write_text(raw)
        self.assertEqual(self.control.reason(), "operation_state_invalid")
        self.control.settings_path.write_bytes(b" " * (MAX_SETTINGS_BYTES + 1))
        self.assertEqual(self.control.reason(), "operation_state_invalid")

    def test_revision_exhaustion_preserves_last_state(self):
        value = self.control.set_mode("start")
        self.write_value({**value, "revision": MAX_REVISION})
        before = self.control.settings_path.read_bytes()
        self.denied("operation_state_revision_exhausted", lambda: self.control.set_mode("pause"))
        self.assertEqual(before, self.control.settings_path.read_bytes())

    def test_cleanup_only_bypasses_valid_modes_and_does_not_change_settings(self):
        self.control.set_mode("pause")
        before = self.control.settings_path.read_bytes()
        with self.control.guard(REPOS[0], cleanup=True):
            self.assertEqual(self.control.reason(REPOS[0]), "host_paused")
        self.assertEqual(before, self.control.settings_path.read_bytes())
        self.denied("operation_state_repository_unregistered",
                    lambda: self.control.guard("example/stranger", cleanup=True).__enter__())
        self.denied("operation_state_cleanup_invalid",
                    lambda: self.control.guard(REPOS[0], cleanup="true").__enter__())

    def test_nested_guards_and_reads_share_lock_but_cannot_upgrade(self):
        self.control.set_mode("start")
        other = OperatingControl(self.lock, REPOS)
        with self.control.guard(REPOS[0]):
            with other.guard(REPOS[1]):
                self.assertIsNone(other.reason(REPOS[0]))
                self.denied("operation_state_busy", lambda: other.set_mode("pause"))
        self.assertEqual(self.control.set_mode("pause")["global_mode"], "paused")

    def test_effect_failure_preserves_original_error_and_releases_lock(self):
        self.control.set_mode("start")
        failure = OSError("effect itself failed")
        with self.assertRaises(OSError) as raised:
            with self.control.guard(REPOS[0]):
                raise failure
        self.assertIs(raised.exception, failure)
        self.assertEqual(self.control.set_mode("pause")["global_mode"], "paused")

    def test_settings_symlink_hardlink_permissions_and_fifo_are_rejected(self):
        self.control.set_mode("start")
        settings = self.control.settings_path
        settings.chmod(0o644)
        self.assertEqual(self.control.reason(), "operation_state_unsafe")
        settings.chmod(0o600)
        alias = self.root / "alias"
        os.link(settings, alias)
        self.assertEqual(self.control.reason(), "operation_state_unsafe")
        settings.unlink()
        settings.symlink_to(alias)
        self.assertEqual(self.control.reason(), "operation_state_unsafe")
        settings.unlink()
        os.mkfifo(settings, 0o600)
        self.assertEqual(self.control.reason(), "operation_state_unsafe")

    def test_unsafe_or_symlink_parent_cannot_create_controls(self):
        unsafe = self.root / "unsafe"
        unsafe.mkdir(mode=0o777)
        unsafe.chmod(0o777)
        control = OperatingControl(unsafe / "host.lock", REPOS)
        self.denied("operation_state_unsafe", lambda: control.set_mode("start"))
        self.assertEqual(list(unsafe.iterdir()), [])
        target = self.root / "target"
        target.mkdir(mode=0o700)
        link = self.root / "symlink"
        link.symlink_to(target, target_is_directory=True)
        control = OperatingControl(link / "host.lock", REPOS)
        self.denied("operation_state_unsafe", lambda: control.set_mode("start"))
        self.assertEqual(list(target.iterdir()), [])

    def test_nonempty_lock_and_missing_lock_with_settings_are_unsafe(self):
        self.control.set_mode("start")
        self.control.control_lock_path.write_bytes(b"not a control lock")
        self.assertEqual(self.control.reason(), "operation_state_unsafe")
        self.control.control_lock_path.unlink()
        self.assertEqual(self.control.reason(), "operation_state_unsafe")
        self.denied("operation_state_unsafe", lambda: self.control.set_mode("start"))
        self.denied("operation_state_unsafe",
                    lambda: self.control.guard(REPOS[0], cleanup=True).__enter__())
        self.assertFalse(self.control.control_lock_path.exists())

    def test_lock_replacement_during_guard_retains_uncertainty(self):
        self.control.set_mode("start")
        replacement = self.root / "replacement"
        replacement.touch(mode=0o600)
        with self.assertRaises(OperationDenied) as raised:
            with self.control.guard(REPOS[0]):
                os.replace(replacement, self.control.control_lock_path)
        self.assertEqual(raised.exception.reason, "operation_state_unsafe")

    def test_settings_replaced_during_read_are_rejected(self):
        self.control.set_mode("start")
        replacement = self.root / "replacement"
        replacement.write_bytes(self.control.settings_path.read_bytes())
        replacement.chmod(0o600)
        read = os.read
        replaced = False
        def replacing_read(fd, length):
            nonlocal replaced
            data = read(fd, length)
            if not replaced:
                os.replace(replacement, self.control.settings_path)
                replaced = True
            return data
        with patch("hydra_sdlc.operations.os.read", side_effect=replacing_read):
            self.denied("operation_state_unsafe", self.control.snapshot)

    def test_failed_precommit_fsync_keeps_existing_state_and_removes_temporary(self):
        self.control.set_mode("start")
        previous = self.control.settings_path.read_bytes()
        with patch("hydra_sdlc.operations.os.fsync", side_effect=OSError("fixture")):
            self.denied("operation_state_unavailable", lambda: self.control.set_mode("pause"))
        self.assertEqual(self.control.settings_path.read_bytes(), previous)
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_lost_postreplace_sync_response_is_reconciled_from_snapshot(self):
        first = self.control.set_mode("start")
        real_sync = os.fsync
        calls = 0
        def uncertain_sync(fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("fixture response unavailable")
            return real_sync(fd)
        with patch("hydra_sdlc.operations.os.fsync", side_effect=uncertain_sync):
            self.denied("operation_state_unavailable", lambda: self.control.set_mode("pause"))
        observed = self.control.snapshot()
        self.assertEqual(observed["revision"], first["revision"] + 1)
        self.assertEqual(observed["global_mode"], "paused")

    def test_pause_acknowledges_only_after_admitted_subprocess_effect_finishes(self):
        self.control.set_mode("start")
        effect = self.process("effect")
        self.assertEqual(self.line(effect), "admitted")
        pause = self.process("pause")
        self.assertEqual(self.line(pause), "requesting")
        self.assertFalse(select.select([pause.stdout], [], [], 0.1)[0])
        self.assertIsNone(pause.poll())
        effect.stdin.write("finish\n")
        effect.stdin.flush()
        self.assertEqual(self.line(effect), "effect-finished")
        self.assertEqual(self.line(pause), "applied:2")
        self.denied("host_paused", lambda: self.control.guard(REPOS[0]).__enter__())
        self.assertEqual(effect.wait(timeout=5), 0)
        self.assertEqual(pause.wait(timeout=5), 0)

    def test_concurrent_process_updates_do_not_lose_project_override(self):
        self.control.set_mode("start")
        children = [self.process("project", repo) for repo in REPOS]
        for child in children:
            self.assertEqual(self.line(child), "requesting")
        for child in children:
            child.stdin.write("go\n")
            child.stdin.flush()
        revisions = {int(self.line(child)) for child in children}
        self.assertEqual(revisions, {2, 3})
        self.assertEqual(self.control.snapshot()["projects"], dict.fromkeys(REPOS, "paused"))
        for child in children:
            self.assertEqual(child.wait(timeout=5), 0)


class AsyncOperatingControlTests(unittest.IsolatedAsyncioTestCase):
    def running_control(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        control = OperatingControl(Path(temporary.name).resolve() / "host.lock", REPOS)
        control.set_mode("start")
        return control

    @asynccontextmanager
    async def pending_update(self, control, action, repository=None):
        # Hold a real exclusive writer after atomic replacement and before its
        # read-back/acknowledgment. The event loop must remain free to supervise.
        published, release = threading.Event(), threading.Event()
        replace = os.replace

        def pending_replace(*args, **kwargs):
            replace(*args, **kwargs)
            published.set()
            if not release.wait(5):
                raise RuntimeError("fixture writer was not released")

        with patch("hydra_sdlc.operations.os.replace", side_effect=pending_replace):
            writer = asyncio.create_task(asyncio.to_thread(control.set_mode, action, repository))
            try:
                self.assertTrue(await asyncio.to_thread(published.wait, 5), "writer did not acquire its lock")
                yield
            finally:
                release.set()
                await asyncio.wait_for(writer, timeout=5)

    def assert_contention_holds_admission_without_interrupting(self, control, runner):
        self.assertEqual(control.reason(REPOS[0]), "operation_state_busy")
        self.assertEqual(control.reason(), "operation_state_busy")
        self.assertIsNone(control.interruption_reason(REPOS[0]))
        self.assertIsNone(control.interruption_reason())
        self.assertFalse(runner._stopping(REPOS[0]))
        with self.assertRaises(OperationDenied) as raised:
            control.snapshot()
        self.assertEqual(raised.exception.reason, "operation_state_busy")
        with self.assertRaises(OperationDenied) as raised:
            with control.guard(REPOS[0]):
                self.fail("A new effect was admitted during a pending control update")
        self.assertEqual(raised.exception.reason, "operation_state_busy")

    async def test_external_control_writer_does_not_cancel_another_project(self):
        from hydra_sdlc.runner import Runner

        control = self.running_control()
        runner = Runner(None, None, host_alias="fixture", execute=None,
                        capabilities=None, operations=control)
        lock = control.settings_path.with_name("host.lock")
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-c", DRIVER, str(lock), "held-update",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            self.assertEqual(await asyncio.wait_for(process.stdout.readline(), 5), b"locked\n")
            self.assert_contention_holds_admission_without_interrupting(control, runner)
        finally:
            if process.returncode is None:
                try:
                    process.stdin.write(b"release\n")
                    await process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
            try:
                _, error = await asyncio.wait_for(process.communicate(), 5)
            except asyncio.TimeoutError:
                process.kill()
                await process.communicate()
                raise
        self.assertEqual(process.returncode, 0, error.decode())
        self.assertFalse(runner._stopping(REPOS[0]))
        self.assertIsNone(control.interruption_reason())
        self.assertEqual(control.interruption_reason(REPOS[1]), "project_paused")

    async def test_unrelated_and_enabling_updates_do_not_interrupt_admitted_work(self):
        from hydra_sdlc.runner import Runner

        for action, repository in (("pause", REPOS[1]), ("stop", REPOS[1]),
                                   ("start", None), ("resume", None)):
            with self.subTest(action=action, repository=repository):
                control = self.running_control()
                runner = Runner(None, None, host_alias="fixture", execute=None,
                                capabilities=None, operations=control)
                async with self.pending_update(control, action, repository):
                    self.assert_contention_holds_admission_without_interrupting(control, runner)
                self.assertIsNone(control.interruption_reason(REPOS[0]))
                self.assertIsNone(control.interruption_reason())
                self.assertFalse(runner._stopping(REPOS[0]))
                with control.guard(REPOS[0]):
                    pass
                if repository is not None:
                    self.assertEqual(control.interruption_reason(repository),
                                     "project_" + {"pause": "paused", "stop": "stopped"}[action])

    async def test_target_pause_and_stop_interrupt_after_pending_writer_finishes(self):
        from hydra_sdlc.runner import Runner

        for action in ("pause", "stop"):
            for repository in (None, REPOS[0]):
                with self.subTest(action=action, repository=repository):
                    control = self.running_control()
                    runner = Runner(None, None, host_alias="fixture", execute=None,
                                    capabilities=None, operations=control)
                    async with self.pending_update(control, action, repository):
                        self.assert_contention_holds_admission_without_interrupting(control, runner)
                    reason = ("host_" if repository is None else "project_") + {
                        "pause": "paused", "stop": "stopped",
                    }[action]
                    self.assertEqual(control.interruption_reason(REPOS[0]), reason)
                    self.assertTrue(runner._stopping(REPOS[0]))
                    with self.assertRaises(OperationDenied) as raised:
                        with control.guard(REPOS[0]):
                            self.fail("A completed Pause/Stop admitted a new effect")
                    self.assertEqual(raised.exception.reason, reason)
                    if repository is not None:
                        self.assertIsNone(control.interruption_reason())
                        self.assertFalse(runner._stopping(REPOS[1]))

    async def test_invalid_or_unsafe_state_still_interrupts_admitted_work(self):
        from hydra_sdlc.runner import Runner

        control = self.running_control()
        runner = Runner(None, None, host_alias="fixture", execute=None,
                        capabilities=None, operations=control)
        original = control.settings_path.read_bytes()
        control.settings_path.write_bytes(b"{}")
        self.assertEqual(control.interruption_reason(REPOS[0]), "operation_state_invalid")
        self.assertTrue(runner._stopping(REPOS[0]))
        control.settings_path.write_bytes(original)
        control.settings_path.chmod(0o644)
        self.assertEqual(control.interruption_reason(REPOS[0]), "operation_state_unsafe")
        self.assertTrue(runner._stopping(REPOS[0]))
        control.settings_path.chmod(0o600)
        with patch.object(control, "snapshot", side_effect=OperationDenied("operation_state_unavailable")):
            self.assertEqual(control.interruption_reason(REPOS[0]), "operation_state_unavailable")
            self.assertTrue(runner._stopping(REPOS[0]))
        self.assertEqual(control.interruption_reason("example/unregistered"),
                         "operation_state_repository_unregistered")

    async def test_external_stop_still_interrupts_during_control_contention(self):
        from hydra_sdlc.runner import Runner

        control = self.running_control()
        runner = Runner(None, None, host_alias="fixture", execute=None, capabilities=None,
                        operations=control, stop_requested=lambda: True)
        async with self.pending_update(control, "resume"):
            self.assertTrue(runner._stopping(REPOS[0]))

    async def test_inherited_context_cannot_upgrade_or_reuse_other_tasks_lock(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        control = OperatingControl(Path(temporary.name).resolve() / "host.lock", REPOS)
        control.set_mode("start")
        async def update():
            with self.assertRaises(OperationDenied) as raised:
                control.set_mode("pause")
            self.assertEqual(raised.exception.reason, "operation_state_busy")
        with control.guard(REPOS[0]):
            await asyncio.wait_for(asyncio.create_task(update()), timeout=2)
        self.assertEqual(control.set_mode("pause")["global_mode"], "paused")

    async def test_task_inherited_context_after_outer_exit_reopens_current_store(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        control = OperatingControl(Path(temporary.name).resolve() / "host.lock", REPOS)
        control.set_mode("start")
        begin = asyncio.Event()
        async def read_later():
            await begin.wait()
            self.assertEqual(control.reason(REPOS[0]), "host_paused")
        with control.guard(REPOS[0]):
            task = asyncio.create_task(read_later())
        control.set_mode("pause")
        begin.set()
        await asyncio.wait_for(task, timeout=2)


if __name__ == "__main__":
    unittest.main()
