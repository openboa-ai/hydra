"""Private-effect stdio fixture; never loads an installed host or grant."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import hydra_sdlc
assert Path(hydra_sdlc.__file__).resolve().parent == ROOT/'hydra_sdlc'


async def main(kind, folder):
    import anyio
    from hydra_sdlc.mcp import create_server
    from mcp.server import MCPServer
    from mcp.server.mcpserver import Context
    from mcp.server.subscriptions import InMemorySubscriptionBus
    from mcp.types import InputRequiredResult, ElicitRequest, ElicitRequestFormParams
    folder = Path(folder)
    events, provider_count, case, path, base = [], 0, None, None, None
    events_lock = threading.Lock()
    def event(name, **data):
        with events_lock:
            events.append({'name': name, **data})
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                        dir=folder, prefix='.events-', delete=False) as stream:
                    temporary = Path(stream.name)
                    json.dump(events, stream)
                os.replace(temporary, folder/'events.json')
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

    class RecordingBus(InMemorySubscriptionBus):
        """Observe the public bus seam, without reading SDK internals."""
        def __init__(self):
            super().__init__()
            self.active_tokens = set()
            self.next_token = 0
            self.unsubscribed = anyio.Event()

        def subscribe(self, listener):
            self.next_token += 1
            token = self.next_token
            def observed(item):
                event('bus_listener', token=token, event_type=type(item).__name__)
                listener(item)
            unsubscribe = super().subscribe(observed)
            self.active_tokens.add(token)
            event('bus_subscribed', token=token)
            def remove():
                unsubscribe()
                if token in self.active_tokens:
                    self.active_tokens.remove(token)
                    event('bus_unsubscribed', token=token, active=len(self.active_tokens))
                    self.unsubscribed.set()
            return remove

        async def publish(self, item):
            await super().publish(item)
            event('bus_published', event_type=type(item).__name__,
                  active=len(self.active_tokens))

    bus = RecordingBus() if kind == 'sdk' else InMemorySubscriptionBus()
    async_started, async_cancelled = anyio.Event(), anyio.Event()

    class Controller:
        runtime_identity = {'version': '0.2.1', 'code_digest': 'a'*64,
                            'config_digest': None, 'control_binding_digest': None}
        def status(self):
            if os.read(0, 1) != b'':
                raise AssertionError('stdin must be diverted')
            os.write(1, b'FIXTURE_STDOUT_DIVERTED\n')
            event('status')
            return [{'repository': 'example/product'}]
        async def begin(self, url):
            event('begin')
            if url == 'sleep':
                event('async_started')
                async_started.set()
                try:
                    await anyio.sleep_forever()
                finally:
                    event('async_cancelled')
                    async_cancelled.set()
            elif url == 'wait_started':
                with anyio.fail_after(5):
                    await async_started.wait()
            elif url == 'wait_cancelled':
                with anyio.fail_after(5):
                    await async_cancelled.wait()
            return {'action': 'waiting', 'reason': 'human_decision'}
        async def checkpoint(self, *args):
            return {'action': 'waiting', 'reason': 'stop_requested'}
        async def advance(self, *args):
            return {'action': 'waiting', 'reason': 'ci_pending'}

    def grant(ctx):
        nonlocal provider_count
        assert isinstance(ctx, Context)
        assert ctx.request_context.method == 'tools/call'
        provider_count += 1
        event('provider', protocol=ctx.protocol_version, request_id=ctx.request_id)
        return case.grant if case else None

    if kind == 'checkpoint':
        import test_checkpoint_only
        case = test_checkpoint_only.CheckpointOnlyTests()
        await case.asyncSetUp()
        assignment, path, base = await case.real_git_assignment()
        (path/'src/main.py').write_text('retained raw stdio checkpoint\n')
        (folder/'command.json').write_text(json.dumps(case.command(assignment)))
        kwargs = {'command_config_path': case.settings, 'command_context_provider': grant}
        controller = case.controller
    elif kind == 'admission':
        import test_control_commands
        from hydra_sdlc.control_commands import AdmissionCallContext
        case = test_control_commands.AdmissionCommandTests()
        case.setUp()
        case.grant = AdmissionCallContext('native', None, frozenset({101,202}))
        item = case.command()
        item['binding_epoch'] = None
        (folder/'command.json').write_text(json.dumps(item))
        kwargs = {'command_config_path': case.config_path, 'command_context_provider': grant}
        controller = SimpleNamespace(runner=SimpleNamespace(github=case.github), status=lambda:[])
    else:
        kwargs = {'command_context_provider': grant}
        controller = Controller()
    baseline = os.environ.get('HYDRA_RAW_BASELINE') == '1'
    if not baseline:
        kwargs['subscriptions'] = bus
    high = create_server(controller, **kwargs)
    if kind == 'sdk':
        high = MCPServer('fixture-only', log_level='WARNING', subscriptions=bus)
        async def conversation(value: str, ctx: Context) -> str | InputRequiredResult:
            if value == 'notify':
                # The requested tools event follows the excluded prompt event,
                # so observing it on the FIFO listen stream is a filter barrier.
                await ctx.notify_prompts_changed()
                await ctx.notify_tools_changed()
                return 'published'
            if value == 'wait_unsubscribed':
                with anyio.fail_after(5):
                    await bus.unsubscribed.wait()
                assert not bus.active_tokens
                event('unsubscribe_observed')
                return 'unsubscribed'
            if ctx.input_responses is None:
                return InputRequiredResult(request_state='fixture-private-state', input_requests={
                    'choice': ElicitRequest(params=ElicitRequestFormParams(message='Fixture question',
                        requested_schema={'type': 'object', 'properties': {'answer': {'type': 'string'}},
                                          'required': ['answer']}))})
            assert ctx.request_state == 'fixture-private-state'
            assert ctx.input_responses['choice'].action == 'accept'
            assert ctx.input_responses['choice'].content == {'answer': 'yes'}
            event('input_applied')
            return 'answer-applied'
        high.tool()(conversation)
    (folder/'ready').write_text('ready')
    before = [os.fstat(n) for n in (0,1)]
    try:
        if baseline:
            await high.run_stdio_async()
        else:
            from hydra_sdlc.mcp_stdio import serve_stdio
            await serve_stdio(high, bus)
    finally:
        after = [os.fstat(n) for n in (0,1)]
        final = {'provider_count': provider_count, 'begin_calls':sum(e['name']=='begin' for e in events),
                 'fds_restored': all(
            (a.st_dev,a.st_ino)==(b.st_dev,b.st_ino) for a,b in zip(before,after))}
        if path is not None:
            from test_workspace import git
            final.update(phase=case.gh.note['phase'], ticket_empty=case.lock.read_bytes()==b'',
                head=git(path,'rev-parse','HEAD'), commit_count=int(git(path,'rev-list','--count',f'{base}..HEAD')),
                preserved_text=(path/'src/main.py').read_text(),
                verification_calls=getattr(case.ws,'verification_calls',0))
        elif case:
            final.update(control=case.control.snapshot(), settings_bytes=case.payload().decode())
        if case:
            case.doCleanups()
        (folder/'final.json').write_text(json.dumps(final))


if __name__ == '__main__':
    import anyio
    anyio.run(main, *sys.argv[1:])
