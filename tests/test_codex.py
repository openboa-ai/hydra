import asyncio
import json
import tempfile
import unittest
from dataclasses import dataclass
from unittest.mock import patch

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
        self.interrupted.set()


class FakeThread:
    id = "thread-1"

    def __init__(self, turn, trace):
        self.next_turn = turn
        self.trace = trace
        self.options = None
        self.start_error = False
        self.start_silent = False

    async def turn(self, prompt, **options):
        self.trace.append("turn-start")
        self.options = options
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
            patch.object(codex, "_new_client", return_value=(self.client, "read-only", "deny-all")),
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
        return await codex.execute(
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

    async def test_wrong_resumed_identity_is_unknown_and_does_not_run(self):
        result = await self.execute(resume_thread_id="different-thread")
        self.assertEqual(result["status"], "transport_unknown")
        self.assertNotIn("turn-start", self.trace)

    async def test_stop_before_dispatch(self):
        self.stop = True
        result = await self.execute()
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(self.trace, [])

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

    async def test_interrupt_without_terminal_does_not_claim_stopped(self):
        self.turn.silent = True
        self.turn.interrupt_terminal = False
        asyncio.get_running_loop().call_later(0.015, setattr, self, "stop", True)
        result = await self.execute()
        self.assertEqual(result["status"], "transport_unknown")
        self.assertEqual(self.turn.interrupts, 1)
        self.assertIsNone(result["detail"]["terminal"])

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
            result = await codex.capabilities(directory)
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
            result = await codex.capabilities(directory)
        self.assertFalse(result["available"])
        self.assertEqual(result["error_type"], "AdapterUnavailable")
        self.assertNotIn("private diagnostic", json.dumps(result))

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
