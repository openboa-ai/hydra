"""One bounded execution cycle; external delivery is not implemented in S1."""

from __future__ import annotations

import asyncio
import fcntl
import os
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .store import StateError, StateStore


@contextmanager
def coordinator_lock(state_path: Path):
    """Do not replace/unlink the lock inode while another process may hold it."""
    path = Path(str(state_path) + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise StateError("Another coordinator owns this state; no work was started") from exc
        yield
    finally:
        os.close(fd)


async def run_once(store: StateStore, state_path: Path, execute=None):
    if execute is None:
        from .codex import execute

    with coordinator_lock(state_path):
        # Local preparation must succeed before a durable execution claim exists.
        # A missing/incompatible ps must not strand a task that never dispatched.
        try:
            process_start = subprocess.check_output(
                ["ps", "-p", str(os.getpid()), "-o", "lstart="],
                text=True, timeout=5,
            ).strip()
            if not process_start:
                raise ValueError("Empty process start observation")
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise StateError("Cannot inspect coordinator process; no work was started") from exc
        run = store.claim_next()
        if run is None:
            return {"action": "idle", "work": store.list_work()}
        run_id, generation = run["id"], run["generation"]
        identity = {
            "pid": os.getpid(),
            "process_start": process_start,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "coordinator_run_id": run_id,
        }
        store.set_identity(run_id, generation, process_identity=identity)

        def on_identity(**values):
            store.set_identity(run_id, generation, **values)

        def on_event(event_id, payload):
            store.record_event(run_id, generation, event_id, payload)

        def stop_requested():
            current = store.get_work(run["work_id"])
            return current["stop_requested"] in {"cancel", "pause"} or current["status"] in {"cancelled", "paused"}

        try:
            result = await execute(
                run["assignment"],
                on_identity=on_identity,
                on_event=on_event,
                stop_requested=stop_requested,
                resume_thread_id=run.get("resume_thread_id"),
            )
        except (Exception, asyncio.CancelledError) as exc:
            # An adapter exception cannot prove its subprocess or remote turn stopped.
            result = {"status": "transport_unknown", "detail": {"error_type": type(exc).__name__}}
        status = result.get("status") if isinstance(result, dict) else None
        if not isinstance(status, str) or status not in {"completed", "failed", "interrupted", "transport_unknown"}:
            result = {"status": "transport_unknown", "detail": {"error_type": "InvalidAdapterOutcome"}}
        store.finish_run(run_id, generation, result["status"], result)
        return {"action": "executed", "run_id": run_id, "work": store.get_work(run["work_id"])}
