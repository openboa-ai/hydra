"""Private, single-worker stdio boundary; no SDK imports or durable state here."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import queue
import signal
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

MAX_FRAME_BYTES = 1024 * 1024
PROTOCOL_VERSION = 1


class ProtocolError(RuntimeError):
    pass


def _encode(frame):
    data = json.dumps(frame, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    if len(data) > MAX_FRAME_BYTES:
        raise ProtocolError("Frame too large")
    return data


def _decode(data):
    if not data or len(data) > MAX_FRAME_BYTES or not data.endswith(b"\n"):
        raise ProtocolError("Incomplete or oversized frame")
    frame = json.loads(data)
    if (not isinstance(frame, dict) or set(frame) != {"version", "kind", "seq", "data"}
            or type(frame.get("version")) is not int or frame["version"] != PROTOCOL_VERSION
            or type(frame.get("seq")) is not int or frame["seq"] < 0
            or not isinstance(frame.get("kind"), str) or not isinstance(frame.get("data"), dict)):
        raise ProtocolError("Invalid protocol frame")
    return frame


def _frame(kind, seq, data):
    return {"version": PROTOCOL_VERSION, "kind": kind, "seq": seq, "data": data}


def _worker_command(source):
    return [sys.executable, "-I", str(Path(source).resolve()), "--execution-worker"]


async def _cleanup(process):
    if process is None:
        return True
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        except OSError:
            return False
        until = loop.time() + 1.0
        while loop.time() < until:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                try:
                    await asyncio.wait_for(process.communicate(), max(0.001, until - loop.time()))
                    return True
                except TimeoutError:
                    break
            except OSError:
                return False
            await asyncio.sleep(0.02)
    return False


async def execute_worker(assignment, on_identity, on_event, stop_requested, resume_thread_id,
                         *, worker_source, timeout, grace, poll):
    """Admit one worker and keep all SDK threads inside its owned process group."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    process = None
    accepted = {"thread_id": None, "turn_id": None}
    observed = dict(accepted)
    grants = []
    terminal = None
    outcome = None
    outcome_at = None
    stopped = False
    stop_at = None
    failure = None

    def audit(method, params):
        payload = {"method": method, "params": params}
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        on_event(hashlib.sha256(raw.encode()).hexdigest(), payload)

    async def session():
        nonlocal process, terminal, outcome, outcome_at
        initial = _encode(_frame("assignment", 0, {
            "assignment": assignment, "resume_thread_id": resume_thread_id,
        }))
        process = await asyncio.create_subprocess_exec(
            *_worker_command(worker_source), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            limit=MAX_FRAME_BYTES, start_new_session=True,
        )
        audit("hydra/workerStarted", {
            "pid": process.pid, "pgid": process.pid,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        })
        process.stdin.write(initial)
        await process.stdin.drain()
        expected = 1
        while True:
            frame = _decode(await process.stdout.readline())
            if type(frame.get("seq")) is not int or frame["seq"] != expected:
                raise ProtocolError("Unexpected sequence")
            kind, data = frame.get("kind"), frame.get("data")
            if not isinstance(data, dict):
                raise ProtocolError("Invalid frame data")
            answer = {}
            if kind == "identity":
                if len(data) != 1 or next(iter(data)) not in accepted:
                    raise ProtocolError("Invalid identity fields")
                key, value = next(iter(data.items()))
                if not isinstance(value, str) or not value:
                    raise ProtocolError("Invalid identity")
                observed[key] = value
                if accepted[key] not in (None, value):
                    raise ProtocolError("Conflicting identity")
                on_identity(**data)
                accepted[key] = value
            elif kind == "event":
                if set(data) != {"event_id", "payload"} or not isinstance(data["event_id"], str) or not isinstance(data["payload"], dict):
                    raise ProtocolError("Invalid event")
                on_event(data["event_id"], data["payload"])
                payload = data["payload"]
                params = payload.get("params", {})
                if payload.get("method") == "turn/completed" and isinstance(params, dict):
                    candidate = params.get("turn", {})
                    if (isinstance(candidate, dict) and params.get("threadId") == accepted["thread_id"]
                            and candidate.get("id") == accepted["turn_id"]
                            and accepted["thread_id"] is not None and accepted["turn_id"] is not None
                            and candidate.get("status") in {"completed", "failed", "interrupted"}):
                        terminal = candidate
            elif kind == "poll":
                if data:
                    raise ProtocolError("Invalid stop poll")
                answer = {"stop": stopped or stop_requested() or loop.time() >= deadline}
            elif kind == "dispatch":
                operation = data.get("operation")
                if set(data) != {"operation"} or operation not in {"thread/start", "thread/resume", "turn/start"}:
                    raise ProtocolError("Invalid dispatch operation")
                allow = not (stopped or stop_requested() or loop.time() >= deadline)
                if allow:
                    if operation == "turn/start" and accepted["thread_id"] is None:
                        raise ProtocolError("Turn before durable thread identity")
                    audit("hydra/dispatchIntent", {"operation": operation, "sequence": expected})
                    # Even a failed/uncertain pipe write may have delivered this grant.
                    grants.append(operation)
                answer = {"allow": allow}
            elif kind == "result":
                outcome = data
                outcome_at = loop.time()
                await process.wait()
                return
            else:
                raise ProtocolError("Unexpected frame kind")
            process.stdin.write(_encode(_frame("ack", expected, answer)))
            await process.stdin.drain()
            expected += 1

    task = None
    clean = False
    try:
        if os.name != "posix":
            raise ProtocolError("POSIX host required")
        if stop_requested():
            stopped, stop_at = True, loop.time()
        else:
            task = asyncio.create_task(session())
        while task is not None:
            now = loop.time()
            if not stopped and stop_requested():
                stopped, stop_at = True, now
            cutoff = deadline + (grace if grants else 0)
            if stopped:
                cutoff = min(cutoff, stop_at + (grace if grants else 0))
            if outcome_at is not None:
                cutoff = min(cutoff, outcome_at + grace)
            if task.done():
                task.result()
                break
            if now >= cutoff:
                failure = "stop_requested" if stopped else "execution_timeout"
                break
            try:
                await asyncio.wait({task}, timeout=min(poll, cutoff - now))
            except asyncio.CancelledError:
                stopped, stop_at = True, loop.time() if stop_at is None else stop_at
    except asyncio.CancelledError:
        stopped, failure = True, "parent_cancelled"
    except Exception as exc:
        failure = type(exc).__name__
    async def finalize():
        nonlocal failure
        if task is not None and not task.done():
            task.cancel()
            # No SDK runs before the assignment is injected. Native asyncio owns
            # cancellation of an incomplete subprocess launch.
            done, _ = await asyncio.wait({task}, timeout=1.0)
            if not done:
                failure = "supervisor_cleanup_unknown"
        if task is not None and task.done() and not task.cancelled():
            task.exception()
        try:
            return await _cleanup(process)
        except Exception:
            return False

    cleanup_task = asyncio.create_task(finalize())
    while True:
        try:
            clean = await asyncio.shield(cleanup_task)
            break
        except asyncio.CancelledError:
            stopped = True

    detail = {"reason": failure or "worker_exit_without_result", "result": None,
              "items": {}, "usage": None, "terminal": terminal,
              "requested_resume_thread_id": resume_thread_id}
    result = {"status": "transport_unknown", "thread_id": observed["thread_id"],
              "turn_id": observed["turn_id"], "detail": detail}
    if not clean or failure == "supervisor_cleanup_unknown":
        detail["cleanup"] = "unknown"
        return result
    if (isinstance(outcome, dict) and isinstance(outcome.get("status"), str)
            and outcome["status"] in {"completed", "failed", "interrupted", "transport_unknown"}):
        worker_detail = outcome.get("detail")
        same_ids = all(outcome.get(key) == accepted[key] for key in accepted)
        provider_terminal = (terminal is not None and terminal.get("status") == outcome["status"])
        before_turn = (outcome["status"] == "interrupted" and "turn/start" not in grants
                       and accepted["thread_id"] is not None and accepted["turn_id"] is None
                       and isinstance(worker_detail, dict) and worker_detail.get("reason") == "stopped_before_turn")
        if isinstance(worker_detail, dict) and worker_detail.get("cleanup") != "unknown" and same_ids:
            if (provider_terminal or before_turn or (not grants and outcome["status"] in {"failed", "interrupted"})
                    or outcome["status"] == "transport_unknown"):
                worker_detail.setdefault("requested_resume_thread_id", resume_thread_id)
                return outcome
    if outcome is not None:
        detail["reason"] = "invalid_worker_result"
    if not grants:
        result["status"] = "interrupted" if stopped else "failed"
        detail["reason"] = "stopped_before_dispatch" if stopped else (failure or "before_dispatch_failure")
    return result


class _WorkerChannel:
    def __init__(self):
        self.seq = 0
        self.pending = None
        self.responses = queue.Queue(maxsize=1)

    def _control_reader(self):
        try:
            buffered = b""
            while True:
                # A daemon blocked in BufferedReader.readline can prevent clean
                # Python shutdown; raw descriptor reads own no interpreter I/O lock.
                chunk = os.read(sys.stdin.fileno(), 4096)
                if not chunk:
                    raise ProtocolError("Parent disconnected")
                buffered += chunk
                if len(buffered) > MAX_FRAME_BYTES:
                    raise ProtocolError("Control frame too large")
                while b"\n" in buffered:
                    data, buffered = buffered.split(b"\n", 1)
                    frame = _decode(data + b"\n")
                    if frame["kind"] != "ack" or frame["seq"] != self.pending:
                        raise ProtocolError("Unexpected control frame")
                    self.responses.put_nowait(frame)
        except BaseException:
            # This entry point only runs in its own newly created POSIX session.
            # KILL the group together; TERM could kill us before a resistant child.
            os.killpg(os.getpid(), signal.SIGKILL)

    def start(self):
        threading.Thread(target=self._control_reader, daemon=True).start()

    def request(self, kind, data):
        self.seq += 1
        self.pending = self.seq
        sys.stdout.buffer.write(_encode(_frame(kind, self.seq, data)))
        sys.stdout.buffer.flush()
        response = self.responses.get()
        if type(response.get("seq")) is not int or response["seq"] != self.seq or not isinstance(response.get("data"), dict):
            os.killpg(os.getpid(), signal.SIGKILL)
        self.pending = None
        expected = {"poll": "stop", "dispatch": "allow"}.get(kind)
        if ((expected is None and response["data"])
                or (expected is not None and (set(response["data"]) != {expected}
                                             or type(response["data"][expected]) is not bool))):
            os.killpg(os.getpid(), signal.SIGKILL)
        return response["data"]

    def result(self, data):
        self.seq += 1
        sys.stdout.buffer.write(_encode(_frame("result", self.seq, data)))
        sys.stdout.buffer.flush()


def worker_main(execute):
    if os.name != "posix" or os.getpid() != os.getpgrp() or os.getpid() != os.getsid(0):
        raise SystemExit(2)
    initial = _decode(sys.stdin.buffer.readline(MAX_FRAME_BYTES + 1))
    if initial.get("kind") != "assignment" or initial.get("seq") != 0 or not isinstance(initial.get("data"), dict):
        raise SystemExit(2)
    channel = _WorkerChannel()
    channel.start()

    async def run():
        result = await execute(
            initial["data"]["assignment"],
            lambda **values: channel.request("identity", values),
            lambda event_id, payload: channel.request("event", {"event_id": event_id, "payload": payload}),
            lambda: channel.request("poll", {}).get("stop") is not False,
            resume_thread_id=initial["data"].get("resume_thread_id"),
            on_dispatch=lambda operation: channel.request("dispatch", {"operation": operation}).get("allow") is True,
        )
        channel.result(result)

    asyncio.run(run())
