"""Bounded Codex assignments; provider completion is not delivery.

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


def _new_client(cwd: str, mode: str = "read_only"):
    _versions()
    from openai_codex import ApprovalMode, CodexConfig, Sandbox
    from openai_codex.client import CodexClient

    client = _SdkClient(CodexClient(
        CodexConfig(cwd=cwd, client_name="hydra", client_title="Hydra"),
        approval_handler=_reject_approval,
    ))
    sandbox = Sandbox.workspace_write if mode == "workspace_write" else Sandbox.read_only
    return client, sandbox, ApprovalMode.deny_all


def _reject_approval(method: str, params: dict | None) -> dict:
    # No worker or capability read may gain authority through a server request.
    if method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
        return {"decision": "decline"}
    if method == "item/permissions/requestApproval":
        return {"permissions": {}, "scope": "turn"}
    if method in ("item/tool/requestUserInput", "tool/requestUserInput"):
        return {"answers": {}}
    if method == "mcpServer/elicitation/request":
        return {"action": "decline", "content": None}
    raise AdapterUnavailable("Unexpected server request.")


def _denied_policy(approval_mode):
    from openai_codex import ApprovalMode
    from openai_codex.generated.v2_all import AskForApproval, AskForApprovalValue

    if approval_mode != ApprovalMode.deny_all:
        raise AdapterUnavailable("Only denied escalation is supported.")
    return AskForApproval(root=AskForApprovalValue.never)


def _thread_settings(options):
    from openai_codex import Sandbox
    from openai_codex.generated.v2_all import SandboxMode

    options = dict(options)
    approval = _denied_policy(options.pop("approval_mode"))
    sandbox = options.pop("sandbox")
    if sandbox not in (Sandbox.read_only, Sandbox.workspace_write):
        raise AdapterUnavailable("Unsupported worker sandbox.")
    return {**options, "approval_policy": approval, "sandbox": SandboxMode(sandbox.value)}


class _SdkClient:
    """Async facade over public SDK methods with an explicit rejection handler.

    Blocking SDK calls stay in the supervised child. The high-level async SDK
    does not expose its approval handler and defaults to accepting requests.
    """

    def __init__(self, transport):
        self.transport = transport

    async def __aenter__(self):
        await asyncio.to_thread(self.transport.start)
        await asyncio.to_thread(self.transport.initialize)
        return self

    async def account(self, refresh_token=False):
        from openai_codex.generated.v2_all import GetAccountParams

        return await asyncio.to_thread(
            self.transport.account_read, GetAccountParams(refresh_token=refresh_token),
        )

    async def thread_start(self, **options):
        from openai_codex.generated.v2_all import ThreadStartParams

        response = await asyncio.to_thread(
            self.transport.thread_start, ThreadStartParams(**_thread_settings(options)),
        )
        return _SdkThread(self.transport, response.thread.id)

    async def thread_resume(self, thread_id, **options):
        from openai_codex.generated.v2_all import ThreadResumeParams

        response = await asyncio.to_thread(
            self.transport.thread_resume, thread_id,
            ThreadResumeParams(thread_id=thread_id, **_thread_settings(options)),
        )
        return _SdkThread(self.transport, response.thread.id)

    async def close(self):
        await asyncio.to_thread(self.transport.close)


class _SdkThread:
    def __init__(self, transport, thread_id):
        self.transport, self.id = transport, thread_id

    async def turn(self, prompt, *, approval_mode, output_schema, sandbox=None, **options):
        from openai_codex import Sandbox
        from openai_codex.generated.v2_all import (
            ReadOnlySandboxPolicy, SandboxPolicy, TextUserInput, TurnStartParams, UserInput,
        )

        policy = None
        if sandbox is not None:
            # Workspace writes inherit the restricted thread policy rather than
            # replacing its resource roots or implicit temporary-directory rules.
            if sandbox != Sandbox.read_only:
                raise AdapterUnavailable("Only a read-only turn override is supported.")
            policy = SandboxPolicy(root=ReadOnlySandboxPolicy(type="readOnly", network_access=False))
        params = TurnStartParams(
            thread_id=self.id, input=[UserInput(root=TextUserInput(type="text", text=prompt))],
            approval_policy=_denied_policy(approval_mode), sandbox_policy=policy,
            output_schema=output_schema, **options,
        )
        response = await asyncio.to_thread(self.transport.turn_start, self.id, prompt, params)
        return _SdkTurn(self.transport, self.id, response.turn.id)


class _SdkTurn:
    def __init__(self, transport, thread_id, turn_id):
        self.transport, self.thread_id, self.id = transport, thread_id, turn_id

    async def stream(self):
        # Public turn_start registers its queue before returning the turn ID.
        try:
            while True:
                event = await asyncio.to_thread(self.transport.next_turn_notification, self.id)
                yield event
                if event.method == "turn/completed":
                    break
        finally:
            self.transport.unregister_turn_notifications(self.id)

    async def interrupt(self):
        return await asyncio.to_thread(self.transport.turn_interrupt, self.thread_id, self.id)


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
    from .execution_boundary import worker_environment

    output = _unknown_capabilities()
    process = None
    try:
        _validate_cwd(cwd)
        if os.name != "posix":
            raise AdapterUnavailable("This qualification host requires POSIX process groups.")
        process = await asyncio.create_subprocess_exec(
            *_capability_command(cwd), stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
            env=worker_environment(),
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


def _owned_directory(value: str) -> Path:
    _validate_cwd(value)
    directory = Path(value).resolve(strict=True)
    if value != str(directory) or directory.stat().st_uid != os.geteuid():
        raise ValueError("Write directories must be canonical and owned by the current user.")
    if directory in (Path(directory.anchor), Path.home().resolve()):
        raise ValueError("Write directories must be scoped to the assignment.")
    return directory


def _assignment_options(assignment: dict) -> tuple[str, str, dict]:
    """Validate host-provided scope; resource authority remains with the runner."""
    _validate_cwd(assignment["cwd"])
    mode = assignment.get("mode", "read_only")
    if mode not in ("read_only", "workspace_write"):
        raise ValueError("mode must be read_only or workspace_write.")
    roots = assignment.get("writable_roots", [])
    if not isinstance(roots, list):
        raise ValueError("writable_roots must be a list of absolute directories.")
    config = {}
    if mode == "workspace_write":
        cwd = _owned_directory(assignment["cwd"])
        resources = [_owned_directory(root) for root in roots]
        if any(cwd.is_relative_to(root) for root in resources):
            raise ValueError("Resource roots cannot contain the assignment workspace.")
        config = {"sandbox_workspace_write": {
            "writable_roots": list(dict.fromkeys(str(root) for root in resources)),
            "network_access": False,
            "exclude_slash_tmp": True,
            "exclude_tmpdir_env_var": True,
        }}
    elif roots:
        raise ValueError("Read-only assignments cannot grant writable resources.")
    if "prompt" in assignment:
        prompt = assignment["prompt"]
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be nonempty text.")
    else:
        if mode != "read_only":
            raise ValueError("Workspace-write assignments require an explicit prompt.")
        task = assignment.get("task")
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task must be nonempty text.")
        prompt = (
            "Perform this bounded read-only qualification assignment. Do not change files, "
            "use external tools/connectors/browser, access credentials or authentication files, "
            "publish, push, create a PR, merge, deploy, or claim the project goal is achieved. "
            "If the assignment requires an excluded action, return needs_decision. "
            "Return the requested structured result.\n\n" + task
        )
    return mode, prompt, config


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
    """Supervise the optional SDK without owning its threads in this process."""
    from .execution_boundary import execute_worker

    return await execute_worker(
        assignment, on_identity, on_event, stop_requested, resume_thread_id,
        worker_source=str(Path(__file__).resolve()), timeout=QUALIFICATION_TIMEOUT_SECONDS,
        grace=INTERRUPT_GRACE_SECONDS, poll=POLL_SECONDS,
    )


async def _execute_in_process(
    assignment: dict,
    on_identity: Callable,
    on_event: Callable,
    stop_requested: Callable[[], bool],
    resume_thread_id: str | None = None,
    on_dispatch: Callable[[str], bool] | None = None,
) -> dict:
    """Run one bounded turn; uncertain starts always require reconciliation."""
    thread_id = None
    turn_id = None
    attempted_start = False
    attempted_turn = False
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

    async def dispatch(operation, call):
        nonlocal attempted_start, attempted_turn
        if stop_requested() or (on_dispatch is not None and not on_dispatch(operation)):
            raise _Stopped
        attempted_start = True
        attempted_turn = attempted_turn or operation == "turn/start"
        return await call()

    try:
        mode, prompt, config = _assignment_options(assignment)
        if resume_thread_id is not None and (
            not isinstance(resume_thread_id, str) or not resume_thread_id.strip()
        ):
            raise ValueError("resume_thread_id must identify an existing thread.")
        if mode == "workspace_write" and resume_thread_id is not None:
            raise ValueError("Workspace-write assignments require a fresh thread.")
        if stop_requested():
            raise _Stopped
        client, sandbox, approval_mode = _new_client(assignment["cwd"], mode)
        await bounded_call(client.__aenter__())
        account = _json(await bounded_call(client.account(refresh_token=False)))
        if (account.get("account") or {}).get("type") != "chatgpt":
            raise AdapterUnavailable("Qualification requires the existing ChatGPT account.")
        options = {"cwd": assignment["cwd"], "sandbox": sandbox, "approval_mode": approval_mode}
        if config:
            options["config"] = config
        thread = await bounded_call(dispatch(
            "thread/resume" if resume_thread_id else "thread/start",
            lambda: client.thread_resume(resume_thread_id, **options)
            if resume_thread_id else client.thread_start(service_name="hydra", **options),
        ))
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
        turn_options = {"approval_mode": approval_mode, "output_schema": RESULT_SCHEMA}
        # The workspace preset would replace the configured roots/temp restrictions.
        # Inherit that policy; a read-only override explicitly denies network access.
        if mode == "read_only":
            turn_options["sandbox"] = sandbox
        turn = await bounded_call(dispatch("turn/start", lambda: thread.turn(
            prompt, **turn_options,
        )))
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
            # The supervisor binds this callback to the current execution. Never
            # deliver foreign or malformed evidence as a current event.
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
        if thread_id is not None and not attempted_turn:
            result["status"] = "interrupted"
            detail["reason"] = "stopped_before_turn"
        else:
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
    if len(sys.argv) == 3 and sys.argv[1] == "--capability-worker":
        print(json.dumps(_capabilities_probe(sys.argv[2])))
    elif len(sys.argv) == 2 and sys.argv[1] == "--execution-worker":
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from execution_boundary import worker_main
        worker_main(_execute_in_process)
    else:
        raise SystemExit(2)
