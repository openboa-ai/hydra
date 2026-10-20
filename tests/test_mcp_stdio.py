"""Raw SDK stdio behavioral gates; effects are local temporary Git/config only."""
import asyncio
from contextlib import asynccontextmanager
import copy
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
import hydra_sdlc
assert Path(hydra_sdlc.__file__).resolve().parent == ROOT/'hydra_sdlc'
from hydra_sdlc.mcp_stdio import (validate_frame, ValidatedLines, claimed_stdin,
    StdioUnavailable, INVALID_FRAME, MAX_WIRE_BYTES, MAX_DECODED_BYTES)

CANARY = 'SYNTHETIC_RAW_PRIVATE_CANARY'
FIXTURE = Path(__file__).with_name('mcp_stdio_fixture.py')
META = {'io.modelcontextprotocol/protocolVersion': '2026-07-28',
        'io.modelcontextprotocol/clientInfo': {'name':'fixture','version':'1'},
        'io.modelcontextprotocol/clientCapabilities': {'elicitation': {'form': {}}}}


def value(reply):
    result = reply['result']
    return result.get('structuredContent') or json.loads(result['content'][0]['text'])


def command(summary=''):
    attempt, step = '11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222'
    return {'command_schema':1, 'request_id':step, 'binding_epoch':None, 'action':'workflow_step',
        'target':{'repository_id':101,'issue_number':4},
        'expected':{'runtime_key':None,'admission_revision':None,'source_checks':[],
            'assignment':{'attempt_id':attempt,'step_id':step,'head':'a'*40,'contract_revision':'b'*40,'spec_revision':None}},
        'effect_key':f'checkpoint:{attempt}:{step}',
        'parameters':{'operation':'checkpoint_only','outcome':'candidate_ready','summary':summary}}


class Wire:
    def __init__(self, proc, folder, modern):
        self.proc, self.folder, self.modern = proc, folder, modern
        self.number, self.frames, self.pending = 1, [], []

    def frame(self, method, params, number):
        params = copy.deepcopy(params)
        if self.modern:
            params['_meta'] = {**params.get('_meta',{}), **META}
        return {'jsonrpc':'2.0','id':number,'method':method,'params':params}

    async def send(self, raw):
        self.proc.stdin.write(raw)
        await self.proc.stdin.drain()

    async def read(self):
        line = await asyncio.wait_for(self.proc.stdout.readline(), 8)
        if not line:
            raise AssertionError('unexpected stdio EOF')
        result = json.loads(line)
        self.frames.append(result)
        return result

    async def request(self, method, params=None, *, raw=None, eof=False):
        number = self.number
        self.number += 1
        payload = self.frame(method, params or {}, number)
        data = json.dumps(payload).encode()+b'\n' if raw is None else raw(payload)
        await self.send(data)
        if eof:
            self.proc.stdin.close()
            await self.proc.stdin.wait_closed()
        while True:
            result = await self.read()
            if result.get('id') == number:
                return result
            self.pending.append(result)

    async def tool(self, name, arguments, **kwargs):
        return await self.request('tools/call', {'name':name,'arguments':arguments}, **kwargs)

    async def notification(self, method, subscription_id):
        def matches(frame):
            return (frame.get('method') == method and
                    frame.get('params', {}).get('_meta', {}).get(
                        'io.modelcontextprotocol/subscriptionId') == subscription_id)
        for index, frame in enumerate(self.pending):
            if matches(frame):
                return self.pending.pop(index)
        while True:
            frame = await self.read()
            if matches(frame):
                return frame
            self.pending.append(frame)


@asynccontextmanager
async def connection(kind='basic', modern=False, baseline=None):
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        errors = open(folder/'stderr','wb')
        env = {**os.environ, 'PYTHONDONTWRITEBYTECODE':'1'}
        if baseline is not None:
            env['HYDRA_RAW_BASELINE'] = '1' if baseline else '0'
        proc = await asyncio.create_subprocess_exec(sys.executable,'-B',str(FIXTURE),kind,str(folder),
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=errors,
            env=env,start_new_session=True, limit=2*MAX_WIRE_BYTES)
        wire = Wire(proc,folder,modern)
        try:
            for _ in range(400):
                if (folder/'ready').exists():
                    break
                if proc.returncode is not None:
                    raise AssertionError('fixture setup failed: '+(folder/'stderr').read_text()[-1500:])
                await asyncio.sleep(.02)
            else:
                raise AssertionError('fixture setup timed out')
            if not modern:
                wire.initial = await wire.request('initialize', {'protocolVersion':'2025-11-25',
                    'clientInfo':{'name':'fixture','version':'1'}, 'capabilities':{'elicitation':{'form':{}}}})
                await wire.send(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
            else:
                wire.initial = await wire.request('server/discover')
            yield wire
        finally:
            try:
                if not proc.stdin.is_closing():
                    proc.stdin.close()
                    await proc.stdin.wait_closed()
                await asyncio.wait_for(proc.wait(), 4)
            except (BrokenPipeError, ConnectionResetError, asyncio.TimeoutError):
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()
            errors.close()
            if proc.returncode != 0:
                raise AssertionError('fixture exit '+str(proc.returncode)+': '+(folder/'stderr').read_text()[-2500:])
            # Inspect every final frame after the process has actually ended.
            # This is not a timing-based "nothing arrived yet" assertion.
            remainder = await asyncio.wait_for(proc.stdout.read(), 1)
            wire.frames.extend(json.loads(line) for line in remainder.splitlines() if line)
            wire.final = json.loads((folder/'final.json').read_text())
            wire.stderr = (folder/'stderr').read_text()
            assert wire.final['fds_restored']
            assert CANARY not in wire.stderr
            assert CANARY not in json.dumps(wire.frames)


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional pinned MCP SDK not installed')
class RawStdioTests(unittest.IsolatedAsyncioTestCase):
    async def test_raw_duplicate_keys_never_reach_provider(self):
        async with connection('checkpoint') as wire:
            item = json.loads((wire.folder/'command.json').read_text())
            item['parameters']['summary'] = CANARY
            base = json.dumps(wire.frame('tools/call',{'name':'hydra_command_v1','arguments':{'command':item}},88))
            variants = [base.replace('"command": {','"command": null, "command": {',1),
                base.replace('"action": "workflow_step"','"action": "wrong", "action": "workflow_step"'),
                base.replace('"target": {','"target": null, "target": {',1),
                base.replace('"assignment": {','"assignment": null, "assignment": {',1),
                base.replace('"step_id": ','"step_id": "wrong", "step_id": ',1)]
            for raw in variants:
                await wire.send(raw.encode()+b'\n')
            following = await wire.request('tools/list')
            self.assertEqual(len(following['result']['tools']),6)
            events = json.loads((wire.folder/'events.json').read_text()) if (wire.folder/'events.json').exists() else []
            observed = sum(e['name']=='provider' for e in events)
        # This is the intended behavioral RED on the original real stdio entry.
        self.assertEqual((observed,wire.final['commit_count']), (0,0),
            'raw duplicates reached trusted provider or real temporary Git effect')

    async def test_six_tool_schema_discovery_cursor_error_and_context_parity(self):
        for modern in (False,True):
            outputs = []
            for baseline in (True,False):
                async with connection(modern=modern,baseline=baseline) as wire:
                    rows = [wire.initial]
                    for method in ('tools/list','prompts/list','resources/list','resources/templates/list'):
                        for params in ({},{'cursor':'ignored'},{'cursor':12}):
                            rows.append(await wire.request(method,params))
                    rows.append(await wire.request('prompts/get',{'name':'missing'}))
                    rows.append(await wire.request('resources/read',{'uri':'example://missing'}))
                    rows.append(await wire.tool('hydra_status',{}))
                    rows.append(await wire.tool('hydra_begin',{'issue_url':'example'}))
                    rows.append(await wire.tool('hydra_checkpoint',{'issue_url':'x','attempt_id':'a','step_id':'s',
                        'head':'h','contract_revision':'c','outcome':'candidate_ready'}))
                    for name in ('hydra_verify','hydra_deliver'):
                        rows.append(await wire.tool(name,{'issue_url':'x','attempt_id':'a','head':'h','contract_revision':'c'}))
                    rows.append(await wire.tool('hydra_command_v1',{'command':command()}))
                    rows.append(await wire.tool('hydra_command_v1',{'command':CANARY}))
                    self.assertEqual(value(rows[-2])['request']['reason'],'authority_unavailable')
                    status = value(rows[15])
                    self.assertEqual(status['native_context']['protocol_version'], '2026-07-28' if modern else '2025-11-25')
                    self.assertEqual(status['native_context']['caller_task_binding'],'unverified')
                self.assertEqual(wire.final['provider_count'],1)
                outputs.append(rows)
            self.assertEqual(*outputs)

    async def test_malformed_raw_sanitized_before_sdk_formatter(self):
        async with connection() as wire:
            valid = json.dumps(wire.frame('tools/call',{'name':'hydra_command_v1','arguments':{'command':command(CANARY)}},88))
            bad = [valid.replace('"method": ','"method": "bad", "method": ',1).encode(),
                b'{"private":"'+CANARY.encode()+b'",}',
                b'{"private":"'+CANARY.encode()+b'\xff"}',
                b'{"private":"'+CANARY.encode()+b'","value":NaN}',
                b'{"private":"'+CANARY.encode()+b'","value":1e999}',
                b'{"private":"'+CANARY.encode()+b'","nested":'+b'['*80+b'0'+b']'*80+b'}',
                b'{"private":"'+CANARY.encode()+b'a'*MAX_WIRE_BYTES+b'"}',
                json.dumps({'jsonrpc':'2.0','id':CANARY,'method':False,'params':{}}).encode(),
                json.dumps({'jsonrpc':'invalid','id':CANARY,'method':'tools/list','params':{}}).encode(),
                json.dumps({'jsonrpc':'2.0','id':CANARY+'x'*(16*1024),'method':'tools/list','params':{}}).encode(),
                json.dumps([CANARY]).encode(),
                valid.replace('"summary": ', '"summary": "\\ud800", "unused": ',1).encode()]
            for raw in bad:
                await wire.send(raw+b'\n')
            response = await wire.request('tools/list')
            self.assertEqual(len(response['result']['tools']),6)
        self.assertEqual(wire.final['provider_count'],0)

    async def test_valid_unicode_and_worst_escape_reach_real_git_receipt(self):
        for character, worst in (('😀',False),('\x00',False),('a',True)):
            async with connection('checkpoint') as wire:
                item = json.loads((wire.folder/'command.json').read_text())
                item['parameters']['summary'] = character*24000
                def encode(payload):
                    from hydra_sdlc.control_commands import MAX_COMMAND_BYTES
                    metadata_length = MAX_COMMAND_BYTES-4096-24000 if worst else 4096
                    payload['params']['_meta'] = {'fixture_note':'x'*metadata_length}
                    text = json.dumps(payload,ensure_ascii=True)
                    if worst:
                        quoted,escaped,out = False,False,[]
                        for c in text:
                            if quoted and not escaped and c not in ('"','\\'):
                                out.append('\\u%04x'%ord(c))
                            else:
                                out.append(c)
                            if escaped: escaped=False
                            elif c=='\\' and quoted: escaped=True
                            elif c=='"': quoted=not quoted
                        text=''.join(out)
                    return text.encode()+b'\n'
                reply = value(await wire.tool('hydra_command_v1',{'command':item},raw=encode))
                self.assertEqual(reply['request']['outcome'],'applied',reply)
                receipt = reply['request']['receipt']
            self.assertEqual(wire.final['commit_count'],1)
            self.assertEqual(wire.final['head'],receipt['checkpoint_head'])
            self.assertEqual(wire.final['phase'],'implementation_done')
            self.assertTrue(wire.final['ticket_empty'])
            self.assertGreater(wire.final['provider_count'],0)

    async def test_fragmented_crlf_multiple_frames_and_eof_disconnect_parity(self):
        observations=[]
        for baseline in (True,False):
            async with connection(baseline=baseline) as wire:
                frames=[json.dumps(wire.frame('tools/list',{},n)).encode()+b'\r\n' for n in (88,89,90)]
                for offset in range(0,len(frames[0]),7):
                    await wire.send(frames[0][offset:offset+7])
                await wire.send(frames[1]+frames[2])
                replies=[await wire.read() for _ in range(3)]
                self.assertEqual({r['id'] for r in replies},{88,89,90})
                self.assertTrue(all(len(r['result']['tools'])==6 for r in replies))
                # EOF is SDK disconnect, not a promise that the last RPC completes.
                frame=wire.frame('tools/call',{'name':'hydra_begin','arguments':{'issue_url':'eof'}},91)
                await wire.send(json.dumps(frame).encode())
                wire.proc.stdin.close()
                await wire.proc.stdin.wait_closed()
                last=[]
                while True:
                    line=await asyncio.wait_for(wire.proc.stdout.readline(),4)
                    if not line: break
                    last.append(json.loads(line))
            self.assertIn(wire.final['begin_calls'],(0,1))
            self.assertEqual(wire.final['provider_count'],0)
            observations.append({'baseline':baseline,'callback':wire.final['begin_calls'],
                'receipt':False,'reply_count':len(last),'clean_exit':True})
        print('EOF disconnect observations: '+json.dumps(observations))

    async def test_raw_admission_command_reaches_real_cas_receipt(self):
        async with connection('admission',modern=True) as wire:
            item=json.loads((wire.folder/'command.json').read_text())
            reply=value(await wire.tool('hydra_command_v1',{'command':item}))
            self.assertEqual(reply['request']['outcome'],'applied',reply)
            self.assertEqual(reply['request']['receipt']['kind'],'admission')
        self.assertEqual(wire.final['control']['projects']['example/alpha'],'paused')
        self.assertEqual(wire.final['control']['revision'],item['expected']['admission_revision']+1)
        self.assertIn('paused',wire.final['settings_bytes'])

    async def test_active_async_cancel_preserves_next_call_and_command_reentry_rejection(self):
        for modern in (False,True):
            async with connection(modern=modern) as wire:
                await wire.send((json.dumps(wire.frame('tools/call',{'name':'hydra_begin','arguments':{'issue_url':'sleep'}},88))+'\n').encode())
                await wire.tool('hydra_begin', {'issue_url':'wait_started'})
                await wire.send(b'{"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":88}}\n')
                await wire.tool('hydra_begin', {'issue_url':'wait_cancelled'})
                await wire.request('tools/list')
                events=json.loads((wire.folder/'events.json').read_text())
                self.assertTrue(any(e['name']=='async_cancelled' for e in events))
                for key,value_ in (('requestState','opaque'),('inputResponses',{})):
                    reply=await wire.request('tools/call',{'name':'hydra_command_v1','arguments':{'command':command()},key:value_})
                    self.assertEqual(reply['result']['content'][0]['text'],'invalid_command')
            self.assertFalse([frame for frame in wire.frames if frame.get('id') == 88 and
                              ('result' in frame or 'error' in frame)],
                             'cancelled request 88 produced a result or error')

    async def test_modern_request_state_roundtrip_and_subscription_filter_cancel(self):
        for baseline in (True,False):
            async with connection('sdk',modern=True,baseline=baseline) as wire:
                first=await wire.tool('conversation',{'value':'roundtrip'})
                state=first['result']['requestState']
                self.assertNotIn('fixture-private-state',state)
                reply=await wire.request('tools/call',{'name':'conversation','arguments':{'value':'roundtrip'},
                    'requestState':state,'inputResponses':{'choice':{'action':'accept','content':{'answer':'yes'}}}})
                self.assertEqual(reply['result']['content'][0]['text'],'answer-applied')
                invalid=await wire.request('tools/call',{'name':'conversation','arguments':{'value':'changed'},
                    'requestState':state,'inputResponses':{'choice':{'action':'accept','content':{'answer':'yes'}}}})
                self.assertEqual(invalid['error']['code'],-32602)
                await wire.send((json.dumps(wire.frame('subscriptions/listen',{'notifications':{'toolsListChanged':True}},88))+'\n').encode())
                ack=await wire.read()
                self.assertEqual(ack['method'],'notifications/subscriptions/acknowledged')
                self.assertEqual(ack['params']['_meta']['io.modelcontextprotocol/subscriptionId'],88)
                await wire.tool('conversation',{'value':'notify'})
                await wire.notification('notifications/tools/list_changed',88)
                notifications=[f for f in wire.frames if f.get('method','').startswith('notifications/')]
                self.assertEqual([f['method'] for f in notifications],
                    ['notifications/subscriptions/acknowledged','notifications/tools/list_changed'])
                await wire.send(b'{"jsonrpc":"2.0","method":"notifications/cancelled","params":{"requestId":88}}\n')
                removed=await wire.tool('conversation',{'value':'wait_unsubscribed'})
                self.assertEqual(removed['result']['content'][0]['text'],'unsubscribed')
                events=json.loads((wire.folder/'events.json').read_text())
                self.assertEqual([e['active'] for e in events if e['name']=='bus_unsubscribed'],[0])
                delivered=sum(e['name']=='bus_listener' for e in events)
                count=len([f for f in wire.frames if f.get('method')=='notifications/tools/list_changed'])
                await wire.tool('conversation',{'value':'notify'})
                events=json.loads((wire.folder/'events.json').read_text())
                self.assertEqual(sum(e['name']=='bus_listener' for e in events),delivered)
                self.assertEqual([e['active'] for e in events if e['name']=='bus_published'][-2:],[0,0])
            self.assertEqual(sum(f.get('method')=='notifications/tools/list_changed' for f in wire.frames),count)
            self.assertFalse([frame for frame in wire.frames if frame.get('id') == 88 and
                              ('result' in frame or 'error' in frame)],
                             'cancelled subscription 88 produced a result or error')


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional pinned MCP SDK not installed')
class ReaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_final_non_newline_frame_reaches_official_sdk_parser(self):
        import anyio
        import io
        from mcp.server.stdio import stdio_server
        read,write=os.pipe()
        os.set_blocking(read,False)
        raw=b'{"jsonrpc":"2.0","method":"tools/list","id":17,"params":{}}'
        os.write(write,raw)
        os.close(write)
        try:
            async with stdio_server(stdin=ValidatedLines(read),stdout=anyio.wrap_file(io.StringIO())) as (incoming,outgoing):
                message=await incoming.receive()
                self.assertEqual(message.message.id,17)
                self.assertEqual(message.message.method,'tools/list')
                with self.assertRaises(anyio.EndOfStream): await incoming.receive()
                await incoming.aclose()
                await outgoing.aclose()
        finally:
            os.close(read)

    async def test_bounded_discard_eof_and_idle_cancellation(self):
        import anyio
        read,write=os.pipe()
        os.set_blocking(read,False)
        lines=ValidatedLines(read)
        iterator=lines.__aiter__()
        try:
            waiting=asyncio.create_task(anext(iterator))
            await asyncio.sleep(.01)
            waiting.cancel()
            with self.assertRaises(asyncio.CancelledError): await waiting
            await iterator.aclose()
            lines=ValidatedLines(read)
            async def produce():
                await anyio.to_thread.run_sync(os.write,write,b'x'*(MAX_WIRE_BYTES+100)+b'\n{"jsonrpc":"2.0","method":"ping","id":1}')
                os.close(write)
            producer=asyncio.create_task(produce())
            got=[line async for line in lines]
            await producer
            self.assertEqual(got[0],INVALID_FRAME)
            self.assertNotEqual(got[1],INVALID_FRAME)
            self.assertLessEqual(lines.buffered_peak,MAX_WIRE_BYTES)
        finally:
            os.close(read)

    async def test_read_failure_is_fixed_fatal_error(self):
        async def ready(fd): return None
        with patch('anyio.wait_readable',ready),patch('hydra_sdlc.mcp_stdio.os.read',side_effect=OSError(CANARY)):
            with self.assertRaisesRegex(StdioUnavailable,'^stdio_unavailable$'):
                await anext(ValidatedLines(99).__aiter__())


class ClaimTests(unittest.TestCase):
    def test_claim_failures_never_yield_unprotected_stdin(self):
        import hydra_sdlc.mcp_stdio as module
        for stage in ('acquire','divert','restore'):
            calls,closed=[],[]
            def dup(source,target):
                calls.append((source,target))
                if (stage=='divert' and source==11) or (stage=='restore' and source==10):
                    raise OSError(CANARY)
            def fcntl_(fd,op,arg=None):
                if op==fcntl.F_DUPFD_CLOEXEC:
                    self.assertEqual(arg,3)
                    if stage=='acquire': raise OSError(CANARY)
                    return 10
                return 0
            with patch.object(module,'_owner',__import__('threading').Lock()), \
                 patch.object(sys.stdin,'fileno',return_value=0), \
                 patch('hydra_sdlc.mcp_stdio.os.fstat',return_value=type('Stat',(),{'st_mode':stat.S_IFIFO})()), \
                 patch('hydra_sdlc.mcp_stdio._identity',return_value=(1,2,3)), \
                 patch('hydra_sdlc.mcp_stdio.os.open',return_value=11), \
                 patch('hydra_sdlc.mcp_stdio.os.close',side_effect=closed.append), \
                 patch('hydra_sdlc.mcp_stdio.os.dup2',side_effect=dup), \
                 patch('fcntl.fcntl',side_effect=fcntl_):
                with self.assertRaisesRegex(StdioUnavailable,'^stdio_unavailable$'):
                    with claimed_stdin():
                        self.assertEqual(stage,'restore')
                if stage=='restore': self.assertNotIn(10,closed)
                elif stage=='divert': self.assertIn((10,0),calls)


if __name__=='__main__':
    unittest.main()


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional pinned MCP SDK not installed')
class StdioExitTests(unittest.TestCase):
    def test_sdk_grouped_stdio_failures_exit_safely_and_restore_descriptors(self):
        import subprocess
        script = '''import os, sys
sys.path.insert(0, ROOT)
from contextlib import contextmanager
from unittest.mock import patch
from mcp.server import MCPServer
from mcp.server.subscriptions import InMemorySubscriptionBus
import hydra_sdlc.mcp_stdio as module
assert str(module.__file__).startswith(ROOT + os.sep)
def identities():
    return [(os.fstat(fd).st_dev, os.fstat(fd).st_ino) for fd in (0, 1)]
before = identities()
original_claim = module.claimed_stdin
original_identity = module._identity
@contextmanager
def failed_read():
    with original_claim() as lines:
        original_read = os.read
        def read(fd, count):
            if fd == lines.fd:
                raise OSError('SYNTHETIC_RAW_PRIVATE_CANARY')
            return original_read(fd, count)
        with patch.object(module.os, 'read', side_effect=read):
            yield lines
def changed_identity(fd):
    value = original_identity(fd)
    if fd == 1 and value == original_identity(2):
        return (-1, -1, value[2])
    return value
fault = (patch.object(module, 'claimed_stdin', failed_read) if FAULT == 'read'
         else patch.object(module, '_identity', side_effect=changed_identity))
try:
    with fault:
        module.run_stdio(MCPServer('stdio-failure-fixture'), InMemorySubscriptionBus())
finally:
    assert identities() == before, 'standard descriptors were not restored'
    assert not module._owner.locked(), 'restored stdin claim was retained'
'''
        for fault in ('read', 'stdout_identity'):
            with self.subTest(fault=fault):
                code = script.replace('ROOT', repr(str(ROOT))).replace('FAULT', repr(fault))
                result = subprocess.run([sys.executable, '-I', '-c', code], input=b'',
                    capture_output=True, timeout=15,
                    env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
                self.assertEqual(result.returncode, 2, result.stderr.decode(errors='replace')[-2200:])
                self.assertEqual(result.stdout, b'')
                self.assertEqual(result.stderr, b'stdio_unavailable\n')

    def test_only_stdio_failures_are_relabelled_in_nested_groups(self):
        import io
        from contextlib import redirect_stderr
        from hydra_sdlc.mcp_stdio import run_stdio
        failures = [StdioUnavailable(), ExceptionGroup('outer', [
            StdioUnavailable(), ExceptionGroup('inner', [StdioUnavailable()])])]
        for error in failures:
            with self.subTest(kind=type(error).__name__):
                output = io.StringIO()
                with patch('anyio.run', side_effect=error), redirect_stderr(output):
                    with self.assertRaises(SystemExit) as result:
                        run_stdio(None, None)
                self.assertEqual(result.exception.code, 2)
                self.assertEqual(output.getvalue(), 'stdio_unavailable\n')
        failures = [RuntimeError('unrelated'), ExceptionGroup('outer', [
            ExceptionGroup('inner', [RuntimeError('unrelated')])]),
            ExceptionGroup('mixed', [StdioUnavailable(), RuntimeError('unrelated')])]
        for error in failures:
            with self.subTest(kind=str(error)):
                with patch('anyio.run', side_effect=error):
                    with self.assertRaises(type(error)) as result:
                        run_stdio(None, None)
                self.assertIs(result.exception, error)
