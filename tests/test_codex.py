import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from hydra_sdlc import codex


@dataclass
class Event:
    method: str
    payload: dict


def event(method, **params):
    return Event(method, params)


def terminal(status="completed", thread_id="thread-1", turn_id="turn-1"):
    return event("turn/completed", threadId=thread_id, turn={"id": turn_id, "status": status})


def message(outcome="candidate_ready"):
    return event("item/completed", threadId="thread-1", turnId="turn-1", item={
        "id": "message-1", "type": "agentMessage", "phase": "final_answer", "text": json.dumps({
            "outcome": outcome, "summary": "Read-only inspection complete.",
            "evidence": ["README exists"], "next_action": "Verify candidate evidence.",
        }),
    })


class NoActiveTurn(Exception):
    def __init__(self, message="no active turn to interrupt"):
        super().__init__(message)
        self.code = -32600
        self.message = message


class FakeTurn:
    id = "turn-1"

    def __init__(self, events=None, silent=False, interrupt_terminal=True, disconnect=False):
        self.events = [message(), terminal()] if events is None else events
        self.silent = silent
        self.interrupt_terminal = interrupt_terminal
        self.disconnect = disconnect
        self.interrupted = asyncio.Event()
        self.interrupts = 0
        self.streams = 0
        self.interrupt_error = None
        self.interrupt_errors = []

    async def stream(self):
        self.streams += 1
        if self.silent:
            await self.interrupted.wait()
            if self.interrupt_terminal:
                yield terminal("interrupted")
            else:
                await asyncio.Event().wait()
            return
        for item in self.events:
            yield item
        if self.disconnect:
            raise OSError("private provider diagnostic")

    async def interrupt(self):
        self.interrupts += 1
        if self.interrupt_errors:
            error = self.interrupt_errors.pop(0)
            if error is not None:
                raise error
        if self.interrupt_error:
            raise self.interrupt_error
        self.interrupted.set()


class FakeThread:
    id = "thread-1"

    def __init__(self, turn, trace):
        self.next_turn = turn
        self.trace = trace
        self.options = None
        self.prompt = None
        self.start_error = False
        self.start_silent = False

    async def turn(self, prompt, **options):
        self.trace.append("turn-start")
        self.options = options
        self.prompt = prompt
        if self.start_error:
            raise ConnectionError("sensitive start response")
        if self.start_silent:
            await asyncio.Event().wait()
        return self.next_turn


class FakeClient:
    def __init__(self, thread, trace):
        self.thread = thread
        self.trace = trace
        self.options = None
        self.resume_id = None
        self.start_silent = False
        self.closed = False
        self.account_type = "chatgpt"

    async def __aenter__(self):
        return self

    async def account(self, refresh_token=False):
        return {"account": {"type": self.account_type, "email": "private@example.test"}}

    async def thread_start(self, **options):
        self.trace.append("thread-start")
        self.options = options
        if self.start_silent:
            await asyncio.Event().wait()
        return self.thread

    async def thread_resume(self, thread_id, **options):
        self.resume_id = thread_id
        return await self.thread_start(**options)

    async def close(self):
        self.closed = True


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.assignment = {"cwd": self.directory.name, "task": "Inspect README."}
        self.trace = []
        self.turn = FakeTurn()
        self.thread = FakeThread(self.turn, self.trace)
        self.client = FakeClient(self.thread, self.trace)
        self.identities = []
        self.events = []
        self.stop = False
        self.patches = [
            patch.object(codex, "_new_client", side_effect=lambda cwd, mode="read_only": (
                self.client, mode.replace("_", "-"), "deny-all",
            )),
            patch.object(codex, "POLL_SECONDS", 0.005),
            patch.object(codex, "INTERRUPT_GRACE_SECONDS", 0.03),
            patch.object(codex, "QUALIFICATION_TIMEOUT_SECONDS", 1.0),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def identity(self, **fields):
        self.identities.append(fields)
        self.trace.append("persist-" + next(iter(fields)))

    def save_event(self, event_id, payload):
        self.events.append((event_id, payload))
        self.trace.append("persist-event")

    async def execute(self, **kwargs):
        return await codex._execute_in_process(
            self.assignment, kwargs.pop("on_identity", self.identity),
            kwargs.pop("on_event", self.save_event), lambda: self.stop, **kwargs,
        )

    async def test_identity_is_persisted_before_turn_and_events(self):
        result = await self.execute()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["detail"]["result"]["outcome"], "candidate_ready")
        self.assertEqual(self.trace[:5], [
            "thread-start", "persist-thread_id", "turn-start", "persist-turn_id", "persist-event",
        ])
        self.assertEqual(self.client.options["sandbox"], "read-only")
        self.assertEqual(self.client.options["approval_mode"], "deny-all")
        self.assertEqual(self.thread.options["approval_mode"], "deny-all")
        self.assertEqual(self.turn.streams, 1)
        self.assertTrue(self.client.closed)

    async def test_resume_uses_explicit_identity_and_denied_escalation(self):
        result = await self.execute(resume_thread_id="thread-1")
        self.assertEqual(self.client.resume_id, "thread-1")
        self.assertEqual(result["thread_id"], "thread-1")
        self.assertEqual(self.client.options["approval_mode"], "deny-all")

    async def test_explicit_prompt_is_preserved_for_read_only_review(self):
        self.assignment["prompt"] = "Review the actual diff and report evidence."
        result = await self.execute()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.thread.prompt, self.assignment["prompt"])
        self.assertEqual(self.thread.options["sandbox"], "read-only")

    async def test_legacy_task_keeps_read_only_qualification(self):
        await self.execute()
        self.assertIn("bounded read-only qualification", self.thread.prompt)
        self.assertTrue(self.thread.prompt.endswith(self.assignment["task"]))

    async def test_workspace_write_uses_fresh_restricted_thread_and_inherits_policy(self):
        resources = Path(self.directory.name) / "resources"
        resources.mkdir()
        self.assignment.update(mode="workspace_write", prompt="Implement the accepted spec.",
                               writable_roots=[str(resources)])
        result = await self.execute()
        self.assertEqual(result["status"], "completed")
        self.assertIsNone(self.client.resume_id)
        self.assertEqual(self.client.options["sandbox"], "workspace-write")
        self.assertEqual(self.client.options["approval_mode"], "deny-all")
        self.assertEqual(self.client.options["config"], {"sandbox_workspace_write": {
            "writable_roots": [str(resources)], "network_access": False,
            "exclude_slash_tmp": True, "exclude_tmpdir_env_var": True,
        }})
        self.assertEqual(self.thread.prompt, self.assignment["prompt"])
        self.assertNotIn("sandbox", self.thread.options)
        self.assertEqual(self.thread.options["approval_mode"], "deny-all")

    async def test_workspace_write_resume_fails_before_client_creation(self):
        self.assignment.update(mode="workspace_write", prompt="Implement the accepted spec.")
        result = await self.execute(resume_thread_id="old-thread")
        self.assertEqual(result["status"], "failed")
        codex._new_client.assert_not_called()

    async def test_invalid_assignment_scope_never_constructs_client(self):
        root = Path(self.directory.name)
        file = root / "file"
        file.write_text("fixture")
        real = root / "resource"
        real.mkdir()
        alias = root / "alias"
        alias.symlink_to(real, target_is_directory=True)
        cases = [
            {"mode": "full_access"}, {"prompt": ""}, {"prompt": None},
            {"mode": "workspace_write"},
            {"mode": "workspace_write", "prompt": "edit", "writable_roots": "resource"},
            {"writable_roots": [str(real)]},
        ]
        for invalid in (None, 1, "relative", str(file), str(root / "missing"),
                        str(alias), str(root), str(root.parent), "/", str(Path.home())):
            cases.append({"mode": "workspace_write", "prompt": "edit", "writable_roots": [invalid]})
        for change in cases:
            with self.subTest(change=change):
                self.assignment = {"cwd": str(root), "task": "Inspect README.", **change}
                result = await self.execute()
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["detail"]["reason"], "before_dispatch_failure")
                codex._new_client.assert_not_called()

    async def test_workspace_and_resource_ownership_are_required(self):
        self.assignment.update(mode="workspace_write", prompt="edit")
        with patch.object(codex.os, "geteuid", return_value=os.geteuid() + 1):
            result = await self.execute()
        self.assertEqual(result["status"], "failed")
        codex._new_client.assert_not_called()

    async def test_workspace_alias_is_rejected_before_client_creation(self):
        alias = Path(self.directory.name) / "alias"
        alias.symlink_to(self.directory.name, target_is_directory=True)
        self.assignment.update(cwd=str(alias), mode="workspace_write", prompt="edit")
        result = await self.execute()
        self.assertEqual(result["status"], "failed")
        codex._new_client.assert_not_called()

    async def test_wrong_resumed_identity_is_unknown_and_does_not_run(self):
        result = await self.execute(resume_thread_id="different-thread")
        self.assertEqual(result["status"], "transport_unknown")
        self.assertEqual(result["detail"]["reason"], "resume_identity_mismatch")
        self.assertEqual(result["detail"]["identity_mismatch"], {
            "requested_thread_id": "different-thread", "observed_thread_id": "thread-1",
        })
        self.assertIsNone(result["thread_id"])
        self.assertIsNone(result["turn_id"])
        self.assertEqual(self.identities, [])
        self.assertEqual(self.events, [])
        self.assertNotIn("turn-start", self.trace)

    async def test_stop_before_dispatch(self):
        self.stop = True
        result = await self.execute()
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(self.trace, [])

    async def test_stop_after_account_before_mutation_coroutine_is_not_dispatched(self):
        async def account(refresh_token=False):
            self.stop = True
            return {"account": {"type": "chatgpt"}}
        self.client.account = account
        grants = []
        result = await self.execute(on_dispatch=lambda operation: grants.append(operation) or True)
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(result["detail"]["reason"], "stopped_before_dispatch")
        self.assertEqual(grants, [])
        self.assertNotIn("thread-start", self.trace)

    async def test_refused_dispatch_never_invokes_sdk_mutation(self):
        result = await self.execute(on_dispatch=lambda operation: False)
        self.assertEqual(result["status"], "interrupted")
        self.assertNotIn("thread-start", self.trace)

    async def test_stop_after_thread_identity_does_not_start_turn(self):
        def save(**fields):
            self.identity(**fields)
            self.stop = True
        result = await self.execute(on_identity=save)
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(result["detail"]["reason"], "stopped_before_turn")
        self.assertNotIn("turn-start", self.trace)

    async def test_stop_during_pending_start_is_unknown(self):
        self.client.start_silent = True
        asyncio.get_running_loop().call_later(0.015, setattr, self, "stop", True)
        result = await self.execute()
        self.assertEqual(result["status"], "transport_unknown")
        self.assertNotIn("turn-start", self.trace)

    async def test_cancel_silent_stream_interrupts_once_and_waits_for_terminal(self):
        self.turn.silent = True
        asyncio.get_running_loop().call_later(0.015, setattr, self, "stop", True)
        result = await self.execute()
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(self.turn.interrupts, 1)
        self.assertEqual(result["detail"]["terminal"]["status"], "interrupted")

    async def test_buffered_burst_yields_to_external_stop_with_bounded_handoff(self):
        produced = 0
        maximum_ahead = 0
        closed = False

        async def burst():
            nonlocal produced, maximum_ahead, closed
            try:
                # Finite so a regression reports failure instead of hanging the suite.
                for index in range(10_000):
                    if self.turn.interrupted.is_set():
                        break
                    produced += 1
                    consumed = sum(payload["method"] == "item/agentMessage/delta" for _, payload in self.events)
                    maximum_ahead = max(maximum_ahead, produced - consumed)
                    if produced == 3:
                        asyncio.get_running_loop().call_soon(setattr, self, "stop", True)
                    yield event("item/agentMessage/delta", threadId="thread-1", turnId="turn-1", delta=str(index))
                await self.turn.interrupted.wait()
                yield terminal("interrupted")
            finally:
                closed = True

        stream = burst()
        self.turn.stream = lambda: stream
        result = await self.execute()
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(self.turn.interrupts, 1)
        self.assertLess(produced, 20)
        self.assertLessEqual(maximum_ahead, 3)  # Consumer, handoff, producer only.
        self.assertTrue(closed)

    async def test_consumer_failure_closes_backpressured_stream(self):
        closed = False

        async def burst():
            nonlocal closed
            try:
                for index in range(10_000):
                    yield event("item/agentMessage/delta", threadId="thread-1", turnId="turn-1", delta=str(index))
            finally:
                closed = True

        def fail(event_id, payload):
            raise OSError("disk unavailable")

        # Keep the generator alive: cleanup must close it, not rely on garbage collection.
        stream = burst()
        self.turn.stream = lambda: stream
        result = await self.execute(on_event=fail)
        self.assertEqual(result["status"], "transport_unknown")
        self.assertTrue(closed)
        self.assertFalse(any(
            task.get_coro().__name__ == "read_stream" for task in asyncio.all_tasks()
        ))

    async def test_interrupt_without_terminal_does_not_claim_stopped(self):
        self.turn.silent = True
        self.turn.interrupt_terminal = False
        asyncio.get_running_loop().call_later(0.015, setattr, self, "stop", True)
        result = await self.execute()
        self.assertEqual(result["status"], "transport_unknown")
        self.assertEqual(self.turn.interrupts, 1)
        self.assertIsNone(result["detail"]["terminal"])
        self.assertEqual(result["detail"]["reason"], "interrupt_terminal_timeout")
        self.assertEqual(result["detail"]["interrupt"]["state"], "response_acknowledged")

    async def test_interrupt_failure_is_durable_without_sensitive_message(self):
        self.turn.silent = True
        self.turn.interrupt_error = ConnectionError("private response diagnostics")
        asyncio.get_running_loop().call_later(0.015, setattr, self, "stop", True)
        result = await self.execute()
        self.assertEqual(result["status"], "transport_unknown")
        self.assertEqual(result["detail"]["interrupt"], {
            "state": "request_failed", "reason": "stop_requested", "error_type": "ConnectionError",
            "attempt": 1,
        })
        self.assertEqual(self.turn.interrupts, 1)
        methods = [payload["method"] for _, payload in self.events]
        self.assertIn("hydra/interruptRequested", methods)
        self.assertIn("hydra/interruptResponse", methods)
        self.assertNotIn("private response diagnostics", json.dumps(result))

    async def test_delayed_turn_activation_retries_same_interrupt(self):
        self.turn.silent = True
        self.turn.interrupt_errors = [NoActiveTurn(), None]
        asyncio.get_running_loop().call_later(0.015, setattr, self, "stop", True)
        with patch.object(codex, "INTERRUPT_RETRY_DELAYS_SECONDS", (0.005, 0.01)):
            result = await self.execute()
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(self.turn.interrupts, 2)
        self.assertEqual(self.trace.count("turn-start"), 1)
        requests = [payload["params"] for _, payload in self.events if payload["method"] == "hydra/interruptRequested"]
        self.assertEqual([item["attempt"] for item in requests], [1, 2])
        self.assertEqual({item["turnId"] for item in requests}, {"turn-1"})

    async def test_no_active_turn_retries_are_bounded_to_two(self):
        self.turn.silent = True
        self.turn.interrupt_errors = [NoActiveTurn() for _ in range(4)]
        asyncio.get_running_loop().call_later(0.015, setattr, self, "stop", True)
        with patch.object(codex, "INTERRUPT_RETRY_DELAYS_SECONDS", (0.005, 0.01)):
            result = await self.execute()
        self.assertEqual(result["status"], "transport_unknown")
        self.assertEqual(self.turn.interrupts, 3)
        self.assertEqual(result["detail"]["interrupt"]["attempt"], 3)
        self.assertEqual(result["detail"]["interrupt"]["reason_code"], "no_active_turn")

    async def test_terminal_cancels_pending_interrupt_retry(self):
        self.turn.silent = True
        self.turn.interrupt_errors = [NoActiveTurn()]
        asyncio.get_running_loop().call_later(0.015, setattr, self, "stop", True)
        asyncio.get_running_loop().call_later(0.022, self.turn.interrupted.set)
        with patch.object(codex, "INTERRUPT_RETRY_DELAYS_SECONDS", (0.02, 0.03)):
            result = await self.execute()
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(self.turn.interrupts, 1)

    async def test_different_invalid_request_does_not_retry(self):
        self.turn.silent = True
        self.turn.interrupt_error = NoActiveTurn("different active turn")
        asyncio.get_running_loop().call_later(0.015, setattr, self, "stop", True)
        with patch.object(codex, "INTERRUPT_RETRY_DELAYS_SECONDS", (0.005, 0.01)):
            result = await self.execute()
        self.assertEqual(result["status"], "transport_unknown")
        self.assertEqual(self.turn.interrupts, 1)

    async def test_interrupt_acknowledgement_does_not_count_as_terminal(self):
        self.turn.silent = True
        self.turn.interrupt_terminal = False
        asyncio.get_running_loop().call_later(0.015, setattr, self, "stop", True)
        result = await self.execute()
        response = next(payload for _, payload in self.events if payload["method"] == "hydra/interruptResponse")
        self.assertEqual(response["params"]["state"], "response_acknowledged")
        self.assertEqual(result["status"], "transport_unknown")

    async def test_execution_deadline_interrupts_silent_stream(self):
        self.turn.silent = True
        with patch.object(codex, "QUALIFICATION_TIMEOUT_SECONDS", 0.02):
            result = await self.execute()
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(result["detail"]["reason"], "deadline_exceeded")

    async def test_deadline_in_turn_start_preserves_unknown(self):
        self.thread.start_silent = True
        with patch.object(codex, "QUALIFICATION_TIMEOUT_SECONDS", 0.02):
            result = await self.execute()
        self.assertEqual(result["status"], "transport_unknown")
        self.assertEqual(result["thread_id"], "thread-1")
        self.assertIsNone(result["turn_id"])

    async def test_disconnect_and_start_response_loss_do_not_retry(self):
        self.turn.events = [message()]
        self.turn.disconnect = True
        result = await self.execute()
        self.assertEqual(result["status"], "transport_unknown")
        self.assertNotIn("private provider diagnostic", json.dumps(result))
        self.assertEqual(self.trace.count("turn-start"), 1)

    async def test_start_response_loss_is_unknown(self):
        self.thread.start_error = True
        result = await self.execute()
        self.assertEqual(result["status"], "transport_unknown")
        self.assertEqual(result["thread_id"], "thread-1")
        self.assertNotIn("sensitive start response", json.dumps(result))

    async def test_no_terminal_event_is_unknown(self):
        self.turn.events = [message()]
        result = await self.execute()
        self.assertEqual(result["status"], "transport_unknown")

    async def test_duplicate_event_is_idempotent_and_usage_is_saved(self):
        self.turn.events = [message(), message(), event(
            "thread/tokenUsage/updated", threadId="thread-1", turnId="turn-1",
            tokenUsage={"total": {"totalTokens": 100}},
        ), terminal()]
        result = await self.execute()
        self.assertEqual(len(self.events), 3)
        self.assertEqual(len(result["detail"]["items"]), 1)
        self.assertEqual(result["detail"]["usage"]["total"]["totalTokens"], 100)

    async def test_candidate_cannot_claim_goal_completed(self):
        self.turn.events = [message("goal_achieved"), terminal()]
        result = await self.execute()
        self.assertEqual(result["status"], "completed")
        self.assertIsNone(result["detail"]["result"])
        self.assertEqual(result["detail"]["reason"], "invalid_structured_result")

    async def test_decision_result_is_not_a_provider_failure(self):
        self.turn.events = [message("needs_decision"), terminal()]
        result = await self.execute()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["detail"]["result"]["outcome"], "needs_decision")

    async def test_wrong_terminal_cannot_finish_current_run(self):
        self.turn.events = [terminal(turn_id="wrong")]
        result = await self.execute()
        self.assertEqual(result["status"], "transport_unknown")
        self.assertEqual(self.events, [])

    async def test_foreign_usage_is_not_persisted_as_current_evidence(self):
        self.turn.events = [event('thread/tokenUsage/updated', threadId='foreign-thread',
                                  turnId='turn-1', tokenUsage={'total': 10})]
        result = await self.execute()
        self.assertEqual(result['status'], 'transport_unknown')
        self.assertEqual(self.events, [])
        self.assertIsNone(result['detail']['usage'])

    async def test_missing_or_nested_foreign_identity_is_not_persisted(self):
        missing_thread = message()
        del missing_thread.payload['threadId']
        cases = [
            missing_thread,
            event('thread/tokenUsage/updated', threadId='thread-1', tokenUsage={}),
            event('turn/started', threadId='thread-1', turn={'id': 'foreign-turn'}),
            # Malformed known SDK notifications can arrive in an UnknownNotification wrapper.
            event('item/completed', params={'turnId': 'turn-1', 'item': None}),
        ]
        for invalid in cases:
            with self.subTest(method=invalid.method, payload=invalid.payload):
                self.turn.events = [invalid]
                result = await self.execute()
                self.assertEqual(result['status'], 'transport_unknown')
                self.assertEqual(self.events, [])

    async def test_persistence_failure_is_unknown(self):
        def fail(**fields):
            raise OSError("disk unavailable")
        result = await self.execute(on_identity=fail)
        self.assertEqual(result["status"], "transport_unknown")
        self.assertNotIn("turn-start", self.trace)

    async def test_event_persistence_failure_does_not_report_completion(self):
        def fail(event_id, payload):
            raise OSError("disk unavailable")
        result = await self.execute(on_event=fail)
        self.assertEqual(result["status"], "transport_unknown")
        self.assertIsNone(result["detail"]["terminal"])

    async def test_other_turn_candidate_is_not_admitted(self):
        wrong = message()
        wrong.payload["turnId"] = "another-turn"
        self.turn.events = [wrong, terminal()]
        result = await self.execute()
        self.assertEqual(result["status"], "transport_unknown")
        self.assertEqual(result["detail"]["items"], {})
        self.assertEqual(self.events, [])

    async def test_sdk_missing_is_failed_before_dispatch(self):
        with patch.object(codex, "_new_client", side_effect=codex.AdapterUnavailable):
            result = await self.execute()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.trace, [])

    async def test_other_auth_mode_cannot_spend_api_credits(self):
        self.client.account_type = "apiKey"
        result = await self.execute()
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("thread-start", self.trace)


class InstalledSdkShapeTests(unittest.IsolatedAsyncioTestCase):
    def facade(self, mode="workspace_write"):
        try:
            import openai_codex
        except ImportError:
            self.skipTest("Optional pinned Codex SDK is not installed.")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.cwd = str(Path(directory.name).resolve())
        client, sandbox, approval = codex._new_client(self.cwd, mode)
        transport = client.transport
        transport.start = Mock()
        transport.initialize = Mock()
        transport.close = Mock()
        self.requests = []

        def request(method, params, *, response_model):
            self.requests.append((method, params))
            if method in ("thread/start", "thread/resume"):
                return SimpleNamespace(thread=SimpleNamespace(id="thread-1"))
            if method == "turn/start":
                return SimpleNamespace(turn=SimpleNamespace(id="turn-1"))
            if method == "account/read":
                return {"account": {"type": "chatgpt"}}
            return SimpleNamespace()

        transport.request = Mock(side_effect=request)
        transport.unregister_turn_notifications = Mock(wraps=transport.unregister_turn_notifications)
        return client, sandbox, approval

    async def test_facade_uses_public_transport_and_inherits_write_scope(self):
        client, sandbox, approval = self.facade()
        _, prompt, config = codex._assignment_options({
            "cwd": self.cwd, "mode": "workspace_write", "prompt": "Implement the accepted spec.",
        })
        await client.__aenter__()
        self.assertEqual(await client.account(refresh_token=False), {"account": {"type": "chatgpt"}})
        thread = await client.thread_start(cwd=self.cwd, sandbox=sandbox,
                                           approval_mode=approval, config=config, service_name="hydra")
        turn = await thread.turn(prompt, approval_mode=approval, output_schema=codex.RESULT_SCHEMA)
        client.transport.next_turn_notification = Mock(side_effect=[message(), terminal()])
        self.assertEqual(len([value async for value in turn.stream()]), 2)
        await turn.interrupt()
        await client.close()
        wire = dict(self.requests)
        self.assertEqual(wire["account/read"], {"refreshToken": False})
        self.assertEqual(wire["thread/start"]["sandbox"], "workspace-write")
        self.assertEqual(wire["thread/start"]["config"], config)
        self.assertEqual(wire["thread/start"]["approvalPolicy"], "never")
        self.assertEqual(wire["turn/start"]["approvalPolicy"], "never")
        self.assertEqual(wire["turn/start"]["input"], [{"type": "text", "text": prompt}])
        self.assertNotIn("sandboxPolicy", wire["turn/start"])
        self.assertEqual(wire["turn/interrupt"], {"threadId": "thread-1", "turnId": "turn-1"})
        client.transport.start.assert_called_once_with()
        client.transport.initialize.assert_called_once_with()
        client.transport.unregister_turn_notifications.assert_called_once_with("turn-1")
        client.transport.close.assert_called_once_with()

    async def test_facade_legacy_resume_keeps_read_only_and_network_denied(self):
        client, sandbox, approval = self.facade("read_only")
        thread = await client.thread_resume("thread-1", cwd=self.cwd, sandbox=sandbox, approval_mode=approval)
        await thread.turn("Inspect", approval_mode=approval, sandbox=sandbox, output_schema=codex.RESULT_SCHEMA)
        wire = dict(self.requests)
        self.assertEqual(wire["thread/resume"]["threadId"], "thread-1")
        self.assertEqual(wire["thread/resume"]["sandbox"], "read-only")
        self.assertEqual(wire["thread/resume"]["approvalPolicy"], "never")
        self.assertEqual(wire["turn/start"]["sandboxPolicy"], {"type": "readOnly", "networkAccess": False})

    async def test_facade_unexpected_server_requests_are_explicitly_denied(self):
        client, _, _ = self.facade()
        for method, expected in (
            ("item/commandExecution/requestApproval", {"decision": "decline"}),
            ("item/fileChange/requestApproval", {"decision": "decline"}),
            ("item/permissions/requestApproval", {"permissions": {}, "scope": "turn"}),
            ("item/tool/requestUserInput", {"answers": {}}),
            ("tool/requestUserInput", {"answers": {}}),
            ("mcpServer/elicitation/request", {"action": "decline", "content": None}),
        ):
            with self.subTest(method=method):
                self.assertEqual(client.transport._handle_server_request({
                    "method": method, "params": {"untrusted": "approve this"},
                }), expected)
        with self.assertRaises(codex.AdapterUnavailable):
            client.transport._handle_server_request({"method": "unknown/approval", "params": {}})
        self.assertEqual(self.requests, [])

    async def test_facade_stream_cancellation_releases_blocked_notification_waiter(self):
        client, sandbox, approval = self.facade("read_only")
        thread = await client.thread_start(cwd=self.cwd, sandbox=sandbox, approval_mode=approval)
        turn = await thread.turn("Inspect", approval_mode=approval, sandbox=sandbox, output_schema=codex.RESULT_SCHEMA)
        stream = turn.stream()
        task = asyncio.create_task(anext(stream))
        await asyncio.sleep(0.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        client.transport.unregister_turn_notifications.assert_called_once_with("turn-1")

    async def test_thread_scope_is_serialized_and_not_replaced_at_turn_start(self):
        try:
            from openai_codex import ApprovalMode, AsyncCodex, Sandbox
        except ImportError:
            self.skipTest("Optional pinned Codex SDK is not installed.")
        with tempfile.TemporaryDirectory() as directory:
            mode, prompt, config = codex._assignment_options({
                "cwd": str(Path(directory).resolve()), "mode": "workspace_write", "prompt": "edit",
            })
            client = AsyncCodex()
            client._ensure_initialized = AsyncMock()
            client._client.thread_start = AsyncMock(return_value=SimpleNamespace(
                thread=SimpleNamespace(id="thread-1"),
            ))
            client._client._start_turn = AsyncMock(return_value=(SimpleNamespace(
                turn=SimpleNamespace(id="turn-1"),
            ), None))
            thread = await client.thread_start(cwd=directory, config=config,
                                               sandbox=Sandbox.workspace_write,
                                               approval_mode=ApprovalMode.deny_all)
            await thread.turn(prompt, approval_mode=ApprovalMode.deny_all,
                              output_schema=codex.RESULT_SCHEMA)
        start = client._client.thread_start.call_args.args[0].model_dump(mode="json", by_alias=True)
        turn = client._client._start_turn.call_args.kwargs["params"].model_dump(
            mode="json", by_alias=True, exclude_none=True,
        )
        self.assertEqual(mode, "workspace_write")
        self.assertEqual(start["sandbox"], "workspace-write")
        self.assertEqual(start["approvalPolicy"], "never")
        self.assertEqual(start["config"], config)
        self.assertEqual(turn["approvalPolicy"], "never")
        self.assertNotIn("sandboxPolicy", turn)


class FakeCapabilityClient:
    def start(self):
        pass

    def initialize(self):
        pass

    def close(self):
        pass

    def account_read(self, params):
        assert params == {"refreshToken": False}
        return {"account": {"type": "chatgpt", "email": "private@example.test"}, "requiresOpenaiAuth": True}

    def model_list(self):
        return {"data": [{"id": "configured-model", "secret": "hidden"}]}

    def request(self, method, params, *, response_model):
        assert method == "account/rateLimits/read"
        return {
            "accountId": "private-account", "accessToken": "secret-token",
            "ordinaryUsageAllowed": None,
            "rateLimits": {"primary": {"usedPercent": 27, "email": "private@example.test"}},
            "rateLimitsByLimitId": {"codex": {"secondary": {"usedPercent": 99}}},
        }


class CapabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_capability_reads_do_not_expose_account_or_auth_data(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            codex, "_versions", return_value={"sdk_version": "0.162.0", "runtime_version": "0.162.0"}
        ), patch.object(codex, "_new_capability_client", return_value=(FakeCapabilityClient(), object)):
            result = codex._capabilities_probe(directory)
        serialized = json.dumps(result)
        for secret in ("private@example.test", "private-account", "secret-token", "hidden"):
            self.assertNotIn(secret, serialized)
        self.assertTrue(result["available"])
        self.assertEqual(result["account"]["type"], "chatgpt")
        self.assertEqual(result["models"]["ids"], ["configured-model"])
        self.assertIsNone(result["usage"]["data"]["ordinaryUsageAllowed"])

    async def test_absent_dependency_is_reported_without_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            codex, "_versions", side_effect=codex.AdapterUnavailable("private diagnostic")
        ):
            result = codex._capabilities_probe(directory)
        self.assertFalse(result["available"])
        self.assertEqual(result["error_type"], "AdapterUnavailable")
        self.assertNotIn("private diagnostic", json.dumps(result))

    async def test_completed_probe_is_collected_without_extra_output(self):
        payload = codex._unknown_capabilities()
        payload.update(available=True, private_diagnostic="must not propagate")
        with tempfile.TemporaryDirectory() as directory, patch.object(
            codex, "_capability_command", return_value=[
                sys.executable, "-I", "-c", "print(" + repr(json.dumps(payload)) + ")",
            ],
        ):
            result = await codex.capabilities(directory)
        self.assertTrue(result["available"])
        self.assertNotIn("cleanup", result)
        self.assertNotIn("must not propagate", json.dumps(result))

    async def test_probe_excludes_publishing_tokens_and_preserves_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            captured = Path(directory) / "environment.json"
            publishing = {
                name: "synthetic-" + name for name in (
                    "GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN",
                )
            }
            configuration = {
                "CODEX_HOME": str(Path(directory) / "synthetic-codex-home"),
                "HOME": str(Path(directory) / "synthetic-home"),
                "HYDRA_TEST_HARMLESS": "retained",
            }
            synthetic = {**publishing, **configuration}
            worker = (
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "keys = " + repr(list(synthetic)) + "\n"
                "Path(sys.argv[1]).write_text(json.dumps({key: os.environ.get(key) for key in keys}))\n"
                "print(json.dumps({'available': True}))\n"
            )
            with patch.dict(os.environ, synthetic, clear=True), patch.object(
                codex, "_capability_command", return_value=[
                    sys.executable, "-I", "-c", worker, str(captured),
                ],
            ):
                result = await codex.capabilities(directory)
                self.assertEqual(dict(os.environ), synthetic)
            self.assertTrue(result["available"])
            self.assertNotIn("cleanup", result)
            self.assertEqual(json.loads(captured.read_text()), {
                **{name: None for name in publishing}, **configuration,
            })

    async def test_unconfirmed_cleanup_is_unavailable(self):
        payload = codex._unknown_capabilities()
        payload["available"] = True
        with tempfile.TemporaryDirectory() as directory, patch.object(
            codex, "_capability_command", return_value=[
                sys.executable, "-I", "-c", "print(" + repr(json.dumps(payload)) + ")",
            ],
        ), patch.object(codex, "_stop_capability_probe", new=AsyncMock(return_value=False)):
            result = await codex.capabilities(directory)
        self.assertFalse(result["available"])
        self.assertEqual(result["cleanup"], "unknown")

    def test_blocked_sdk_request_does_not_hold_asyncio_run_shutdown(self):
        # A separate outer interpreter tests the actual asyncio.run shutdown:
        # cancelling a to_thread wrapper alone would still hang this process.
        adapter = str(Path(codex.__file__).resolve())
        load = (
            "import sys\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, str(Path(sys.argv[1]).resolve().parent.parent))\n"
            "from hydra_sdlc import codex\n"
        )
        worker = load + """
import json, os, signal, threading
from pathlib import Path
class BlockedClient:
    def start(self): pass
    def initialize(self): pass
    def account_read(self, params):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        Path(sys.argv[3]).write_text(str(os.getpid()))
        threading.Event().wait()
    def model_list(self): return {}
    def request(self, *args, **kwargs): return {}
    def close(self): pass
codex._versions = lambda: {'sdk_version': '0.162.0', 'runtime_version': '0.162.0'}
codex._new_capability_client = lambda cwd: (BlockedClient(), object)
print(json.dumps(codex._capabilities_probe(sys.argv[2])))
"""
        outer = load + """
import asyncio, json
codex.CAPABILITIES_TIMEOUT_SECONDS = 0.5
codex._capability_command = lambda cwd: [
    sys.executable, '-I', '-c', sys.argv[4], sys.argv[1], cwd, sys.argv[3]
]
print(json.dumps(asyncio.run(codex.capabilities(sys.argv[2]))))
"""
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / "probe.pid"
            completed = subprocess.run(
                [sys.executable, "-I", "-c", outer, adapter, directory, str(pid_file), worker],
                capture_output=True, text=True, timeout=6, check=True,
            )
            result = json.loads(completed.stdout)
            self.assertEqual(result["error_type"], "TimeoutError")
            self.assertFalse(result["available"])
            self.assertNotIn("cleanup", result)
            pid = int(pid_file.read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_worker_uses_exact_source_and_isolated_interpreter(self):
        command = codex._capability_command("/unrelated/candidate")
        self.assertEqual(command, [
            sys.executable, "-I", str(Path(codex.__file__).resolve()),
            "--capability-worker", "/unrelated/candidate",
        ])

    def test_native_capability_requests_never_approve(self):
        self.assertEqual(codex._reject_approval("item/commandExecution/requestApproval", {}), {"decision": "decline"})
        self.assertEqual(codex._reject_approval("item/fileChange/requestApproval", {}), {"decision": "decline"})
        self.assertEqual(codex._reject_approval("item/permissions/requestApproval", {})["permissions"], {})
        with self.assertRaises(codex.AdapterUnavailable):
            codex._reject_approval("unknown/request", {})

    def test_runtime_version_mismatch_is_not_silently_used(self):
        with patch.object(codex.importlib.metadata, "version", side_effect=["0.162.0", "0.144.5"]):
            with self.assertRaises(codex.AdapterUnavailable):
                codex._versions()


if __name__ == "__main__":
    unittest.main()
