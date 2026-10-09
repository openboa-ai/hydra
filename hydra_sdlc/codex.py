"""Bounded, read-only Codex qualification; provider completion is not delivery.

The optional SDK is imported lazily. This module owns no durable state and never
retries an uncertain start. Callbacks must persist before returning.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import os
import signal
import sys
from contextlib import aclosing
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

SDK_VERSION = "0.162.0"
QUALIFICATION_TIMEOUT_SECONDS = 300.0
INTERRUPT_GRACE_SECONDS = 10.0
INTERRUPT_RETRY_DELAYS_SECONDS = (1.0, 2.0)
POLL_SECONDS = 0.2
CAPABILITIES_TIMEOUT_SECONDS = 20.0

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "outcome": {"type": "string", "enum": ["candidate_ready", "needs_decision", "failed"]},
        "summary": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "next_action": {"type": "string"},
    },
    "required": ["outcome", "summary", "evidence", "next_action"],
    "additionalProperties": False,
}


class AdapterUnavailable(RuntimeError):
    """The pinned optional runtime is unavailable or incompatible."""


class _Stopped(Exception):
    pass


def _versions() -> dict[str, str]:
    try:
        versions = {
            "sdk_version": importlib.metadata.version("openai-codex"),
            "runtime_version": importlib.metadata.version("openai-codex-cli-bin"),
        }
    except importlib.metadata.PackageNotFoundError as exc:
        raise AdapterUnavailable("Install the pinned Codex adapter extra.") from exc
    if any(value != SDK_VERSION for value in versions.values()):
        raise AdapterUnavailable("Codex SDK and runtime must both match the pinned version.")
    return versions


def _new_client(cwd: str):
    _versions()
    from openai_codex import ApprovalMode, AsyncCodex, CodexConfig, Sandbox

    client = AsyncCodex(CodexConfig(cwd=cwd, client_name="hydra", client_title="Hydra"))
    return client, Sandbox.read_only, ApprovalMode.deny_all


def _reject_approval(method: str, params: dict | None) -> dict:
    # Capability reads need no command execution, files, tools, or permissions.
    if method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
        return {"decision": "decline"}
    if method == "item/permissions/requestApproval":
        return {"permissions": {}, "scope": "turn"}
    if method in ("item/tool/requestUserInput", "tool/requestUserInput"):
        return {"answers": {}}
    if method == "mcpServer/elicitation/request":
        return {"action": "decline", "content": None}
    raise AdapterUnavailable("Unexpected server request during a capability read.")


def _new_capability_client(cwd: str):
    from openai_codex.client import CodexClient, CodexConfig
    from openai_codex.generated.v2_all import GetAccountRateLimitsResponse

    return (
        CodexClient(
            CodexConfig(cwd=cwd, client_name="hydra", client_title="Hydra"),
            approval_handler=_reject_approval,
        ),
        GetAccountRateLimitsResponse,
    )


def _json(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _json(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("Unsupported provider payload.")


def _safe_usage(data: dict) -> dict:
    """Whitelist metering data; never return account identity or arbitrary keys."""
    def snapshot(item):
        if not isinstance(item, dict):
            return None
        result = {
            key: item[key]
            for key in ("limitId", "limitName", "rateLimitReachedType", "spendControlReached")
            if key in item
        }
        for key in ("primary", "secondary"):
            window = item.get(key)
            result[key] = {
                field: window[field]
                for field in ("usedPercent", "windowDurationMins", "resetsAt")
                if field in window
            } if isinstance(window, dict) else None
        return result

    buckets = data.get("rateLimitsByLimitId")
    return {
        "ordinaryUsageAllowed": data.get("ordinaryUsageAllowed"),
        "rateLimits": snapshot(data.get("rateLimits")),
        "rateLimitsByLimitId": {
            key: snapshot(value) for key, value in buckets.items()
        } if isinstance(buckets, dict) else None,
    }


def _unknown_capabilities() -> dict:
    return {
        "available": False,
        "sdk_version": None,
        "runtime_version": None,
        "account": {"status": "unknown", "type": None},
        "models": {"status": "unknown", "ids": []},
        "usage": {"status": "unknown", "data": None},
    }


def _capabilities_probe(cwd: str) -> dict:
    """Synchronous SDK probe, called only in a supervised disposable process."""
    output = _unknown_capabilities()
    client = None
    try:
        _validate_cwd(cwd)
        output.update(_versions())
        client, usage_model = _new_capability_client(cwd)
        client.start()
        client.initialize()
        output["available"] = True
        for field, call in (
            ("account", lambda: client.account_read({"refreshToken": False})),
            ("models", client.model_list),
            ("usage", lambda: client.request(
                "account/rateLimits/read", None, response_model=usage_model,
            )),
        ):
            try:
                data = _json(call())
                if field == "account":
                    account = data.get("account") or {}
                    output[field] = {
                        "status": "known", "type": account.get("type"),
                        "authenticated": bool(account),
                        "requires_auth": data.get("requiresOpenaiAuth"),
                    }
                elif field == "models":
                    output[field] = {"status": "known", "ids": [
                        model["id"] for model in data.get("data", [])
                        if isinstance(model, dict) and isinstance(model.get("id"), str)
                    ]}
                else:
                    output[field] = {"status": "known", "data": _safe_usage(data)}
            except Exception as exc:
                output[field] = {"status": "unknown", "error_type": type(exc).__name__}
    except Exception as exc:
        output["error_type"] = type(exc).__name__
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                output["available"] = False
                output["cleanup"] = "unknown"
    return output


def _capability_command(cwd: str) -> list[str]:
    # Use this exact installed adapter, even when the operator's cwd differs.
    return [sys.executable, "-I", str(Path(__file__).resolve()), "--capability-worker", cwd]


async def _stop_capability_probe(process) -> bool:
    # This group belongs exclusively to the probe and its SDK runtime. Closing
    # the parent alone could leave a blocked app-server child behind.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        except OSError:
            return False
        deadline = asyncio.get_running_loop().time() + 1.0
        while asyncio.get_running_loop().time() < deadline:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                try:
                    await asyncio.wait_for(
                        process.communicate(), max(0.001, deadline - asyncio.get_running_loop().time()),
                    )
                    return True
                except TimeoutError:
                    break
            except OSError:
                return False
            await asyncio.sleep(0.02)
    return False


async def capabilities(cwd: str) -> dict:
    """Inspect without generation; even a blocked SDK request has a hard boundary.

    The SDK's synchronous request wait has no deadline. Running it through
    asyncio.to_thread would let its thread hold up asyncio.run shutdown after
    timeout, so the entire probe (including close) lives in a killable process.
    """
    output = _unknown_capabilities()
    process = None
    try:
        _validate_cwd(cwd)
        if os.name != "posix":
            raise AdapterUnavailable("This qualification host requires POSIX process groups.")
        process = await asyncio.create_subprocess_exec(
            *_capability_command(cwd), stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
        )
        stdout, _ = await asyncio.wait_for(
            process.communicate(), CAPABILITIES_TIMEOUT_SECONDS,
        )
        if process.returncode != 0:
            raise AdapterUnavailable("Capability probe did not complete successfully.")
        observed = json.loads(stdout)
        if not isinstance(observed, dict) or not isinstance(observed.get("available"), bool):
            raise ValueError("Capability probe returned an invalid result.")
        output.update({
            key: observed[key] for key in (*output, "error_type", "cleanup") if key in observed
        })
    except Exception as exc:
        output["error_type"] = type(exc).__name__
    finally:
        if process is not None and not await _stop_capability_probe(process):
            output["available"] = False
            output["cleanup"] = "unknown"
    return output


def _validate_cwd(cwd: str) -> None:
    if not isinstance(cwd, str) or not Path(cwd).is_absolute() or not Path(cwd).is_dir():
        raise ValueError("cwd must be an absolute existing directory.")


def _structured_result(items: dict[str, dict]) -> dict | None:
    messages = [item for item in items.values() if item.get("type") == "agentMessage"]
    messages = [item for item in messages if item.get("phase") == "final_answer"] or [
        item for item in messages if item.get("phase") is None
    ]
    if not messages:
        return None
    try:
        value = json.loads(messages[-1].get("text", ""))
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict) or set(value) != set(RESULT_SCHEMA["required"]):
        return None
    if value["outcome"] not in ("candidate_ready", "needs_decision", "failed"):
        return None
    if not all(isinstance(value[key], str) for key in ("summary", "next_action")):
        return None
    if not isinstance(value["evidence"], list) or not all(
        isinstance(item, str) for item in value["evidence"]
    ):
        return None
    return value


async def execute(
    assignment: dict,
    on_identity: Callable,
    on_event: Callable,
    stop_requested: Callable[[], bool],
    resume_thread_id: str | None = None,
) -> dict:
    """Run one qualification turn; uncertain starts always require reconciliation."""
    thread_id = None
    turn_id = None
    attempted_start = False
    client = None
    reader = None
    interrupt_task = None
    detail = {"reason": None, "result": None, "items": {}, "usage": None, "terminal": None}
    result = {"status": "failed", "detail": detail, "thread_id": None, "turn_id": None}
    loop = asyncio.get_running_loop()
    deadline = loop.time() + QUALIFICATION_TIMEOUT_SECONDS

    def persist_event(method, params):
        payload = {"method": method, "params": params}
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        event_id = hashlib.sha256(raw.encode()).hexdigest()
        on_event(event_id, payload)
        return event_id

    async def bounded_call(awaitable):
        task = asyncio.create_task(awaitable)
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError
                if stop_requested():
                    raise _Stopped
                done, _ = await asyncio.wait({task}, timeout=min(POLL_SECONDS, remaining))
                if done:
                    return task.result()
        finally:
            if not task.done():
                task.cancel()
                # Do not permit a stalled SDK call to extend the qualification indefinitely.
                task.add_done_callback(_consume_exception)

    try:
        _validate_cwd(assignment["cwd"])
        if not isinstance(assignment.get("task"), str) or not assignment["task"].strip():
            raise ValueError("task must be nonempty text.")
        if resume_thread_id is not None and (
            not isinstance(resume_thread_id, str) or not resume_thread_id.strip()
        ):
            raise ValueError("resume_thread_id must identify an existing thread.")
        if stop_requested():
            raise _Stopped
        client, sandbox, approval_mode = _new_client(assignment["cwd"])
        await bounded_call(client.__aenter__())
        account = _json(await bounded_call(client.account(refresh_token=False)))
        if (account.get("account") or {}).get("type") != "chatgpt":
            raise AdapterUnavailable("Qualification requires the existing ChatGPT account.")
        attempted_start = True
        options = {"cwd": assignment["cwd"], "sandbox": sandbox, "approval_mode": approval_mode}
        thread = await bounded_call(
            client.thread_resume(resume_thread_id, **options)
            if resume_thread_id else client.thread_start(service_name="hydra", **options)
        )
        observed_thread_id = thread.id
        if not isinstance(observed_thread_id, str) or not observed_thread_id:
            raise ValueError("Provider returned no thread identity.")
        if resume_thread_id and observed_thread_id != resume_thread_id:
            detail["reason"] = "resume_identity_mismatch"
            detail["identity_mismatch"] = {
                "requested_thread_id": resume_thread_id,
                "observed_thread_id": observed_thread_id,
            }
            raise ValueError("Provider returned a different resumed thread.")
        thread_id = observed_thread_id
        result["thread_id"] = thread_id
        on_identity(thread_id=thread_id)
        # A confirmed empty thread has not run code; stopping here is unambiguous.
        if stop_requested():
            result["status"] = "interrupted"
            detail["reason"] = "stopped_before_turn"
            return result
        prompt = (
            "Perform this bounded read-only qualification assignment. Do not change files, "
            "use external tools/connectors/browser, access credentials or authentication files, "
            "publish, push, create a PR, merge, deploy, or claim the project goal is achieved. "
            "If the assignment requires an excluded action, return needs_decision. "
            "Return the requested structured result.\n\n" + assignment["task"]
        )
        turn = await bounded_call(thread.turn(
            prompt, sandbox=sandbox, approval_mode=approval_mode, output_schema=RESULT_SCHEMA,
        ))
        turn_id = turn.id
        if not isinstance(turn_id, str) or not turn_id:
            raise ValueError("Provider returned no turn identity.")
        result["turn_id"] = turn_id
        on_identity(turn_id=turn_id)
        queue = asyncio.Queue(maxsize=1)

        async def read_stream():
            try:
                async with aclosing(turn.stream()) as stream:
                    async for event in stream:
                        await queue.put(("event", event))
                        await asyncio.sleep(0)
            except Exception as exc:
                await queue.put(("error", type(exc).__name__))
            else:
                await queue.put(("end", None))

        reader = asyncio.create_task(read_stream())
        seen = set()
        interrupt_deadline = None

        async def interrupt():
            # The pinned runtime can reject an exact-turn interrupt before its
            # newly acknowledged turn becomes active. Only that explicit rejection
            # permits retrying the same interrupt; uncertain writes never retry.
            for attempt in range(1, len(INTERRUPT_RETRY_DELAYS_SECONDS) + 2):
                if loop.time() >= interrupt_deadline:
                    return
                detail["interrupt"] = {
                    "state": "response_pending", "reason": detail["interrupt"]["reason"],
                    "attempt": attempt,
                }
                persist_event("hydra/interruptRequested", {
                    "threadId": thread_id, "turnId": turn_id, "attempt": attempt,
                    "reason": detail["interrupt"]["reason"],
                })
                retry = False
                try:
                    await turn.interrupt()
                    state = {"state": "response_acknowledged", "attempt": attempt}
                except Exception as exc:
                    state = {
                        "state": "request_failed", "attempt": attempt,
                        "error_type": type(exc).__name__,
                    }
                    code = getattr(exc, "code", None)
                    if isinstance(code, int):
                        state["rpc_code"] = code
                    if code == -32600 and getattr(exc, "message", None) == "no active turn to interrupt":
                        state["reason_code"] = "no_active_turn"
                        retry = True
                detail["interrupt"].update(state)
                persist_event("hydra/interruptResponse", {
                    "threadId": thread_id, "turnId": turn_id, **state,
                })
                if not retry or attempt > len(INTERRUPT_RETRY_DELAYS_SECONDS):
                    return
                delay = INTERRUPT_RETRY_DELAYS_SECONDS[attempt - 1]
                if loop.time() + delay >= interrupt_deadline:
                    return
                await asyncio.sleep(delay)

        while True:
            now = loop.time()
            if interrupt_deadline is None and (stop_requested() or now >= deadline):
                detail["reason"] = "stop_requested" if now < deadline else "deadline_exceeded"
                interrupt_deadline = now + INTERRUPT_GRACE_SECONDS
                detail["interrupt"] = {"state": "response_pending", "reason": detail["reason"]}
                interrupt_task = asyncio.create_task(interrupt())
            if interrupt_deadline is not None and now >= interrupt_deadline:
                detail["reason"] = "interrupt_terminal_timeout"
                raise TimeoutError
            if interrupt_task is not None and interrupt_task.done():
                # A persistence failure in the interrupt audit must not be silently discarded.
                interrupt_task.result()
            # Only queue.get() is timed out; the SDK stream subscription remains intact.
            timeout = min(POLL_SECONDS, max(0.001, (interrupt_deadline or deadline) - now))
            try:
                kind, value = await asyncio.wait_for(queue.get(), timeout)
            except TimeoutError:
                continue
            if kind != "event":
                raise ConnectionError("Provider stream ended without terminal evidence.")
            payload = {"method": value.method, "params": _json(value.payload)}
            params = payload["params"]
            if not isinstance(params, dict):
                raise ValueError("Provider event parameters must be an object.")
            if params.get("threadId", thread_id) != thread_id or params.get("turnId", turn_id) != turn_id:
                raise ValueError("Provider event identity does not match the run.")
            if value.method in ("item/completed", "thread/tokenUsage/updated"):
                if params.get("threadId") != thread_id or params.get("turnId") != turn_id:
                    raise ValueError("Provider work evidence must identify its thread and turn.")
            if value.method in ("turn/started", "turn/completed"):
                terminal = params.get("turn", {})
                if not isinstance(terminal, dict) or terminal.get("id") != turn_id or params.get("threadId") != thread_id:
                    raise ValueError("Provider terminal identity does not match the run.")
                if value.method == "turn/completed" and terminal.get("status") not in ("completed", "failed", "interrupted"):
                    raise ValueError("Provider terminal status is invalid.")
            # The store binds this callback to the current run. Never give it
            # foreign or malformed evidence to persist as a current event.
            raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            event_id = hashlib.sha256(raw.encode()).hexdigest()
            if event_id in seen:
                continue
            on_event(event_id, payload)
            seen.add(event_id)
            if value.method == "item/completed":
                item = params.get("item", {})
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    detail["items"][item["id"]] = item
            elif value.method == "thread/tokenUsage/updated":
                detail["usage"] = params.get("tokenUsage")
            elif value.method == "turn/completed":
                detail["terminal"] = terminal
                detail["result"] = _structured_result(detail["items"])
                result["status"] = terminal["status"]
                if detail["reason"] is None:
                    detail["reason"] = "provider_terminal"
                    if result["status"] == "completed" and detail["result"] is None:
                        detail["reason"] = "invalid_structured_result"
                return result
    except _Stopped:
        result["status"] = "transport_unknown" if attempted_start else "interrupted"
        detail["reason"] = "stop_during_start" if attempted_start else "stopped_before_dispatch"
    except Exception as exc:
        result["status"] = "transport_unknown" if attempted_start else "failed"
        if detail["reason"] is None:
            detail["reason"] = "uncertain_execution" if attempted_start else "before_dispatch_failure"
        detail["error_type"] = type(exc).__name__
    finally:
        cleanup_deadline = loop.time() + INTERRUPT_GRACE_SECONDS
        background = [task for task in (reader, interrupt_task) if task is not None]
        for task in background:
            if not task.done():
                task.cancel()
            task.add_done_callback(_consume_exception)
        if client is not None:
            try:
                await asyncio.wait_for(client.close(), max(0.001, cleanup_deadline - loop.time()))
            except Exception:
                detail["cleanup"] = "unknown"
        if background:
            _, pending = await asyncio.wait(background, timeout=max(0, cleanup_deadline - loop.time()))
            if pending:
                detail["cleanup"] = "unknown"
    return result


def _consume_exception(task: asyncio.Task) -> None:
    if not task.cancelled():
        task.exception()


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--capability-worker":
        raise SystemExit(2)
    print(json.dumps(_capabilities_probe(sys.argv[2])))
