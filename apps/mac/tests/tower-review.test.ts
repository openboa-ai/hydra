import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { appFixture, flush, noMutations, sourceFrame } from './tower-fixture.ts';

const result = spawnSync('python3', ['-I', '-c',
  'from pathlib import Path;import sys,json;root=Path.cwd().parents[1];sys.path[:0]=[str(root),str(root/"tests")];from test_projection_qualified_facts import membership_frames;print(json.dumps(membership_frames()))'],
  {encoding:'utf8',timeout:60_000,maxBuffer:4_194_304});
assert.equal(result.status,0,'The actual local/remote producer controls must run: '+result.stderr);
const [actualRemote, actualLocal] = JSON.parse(result.stdout);

async function pollLocal(app: Awaited<ReturnType<typeof appFixture>>) {
  app.api.deferred = (args,sequence) => args.refresh ? undefined :
    Promise.resolve(app.cached(args,actualLocal,sequence));
  app.advance(5_000);
  for (const tick of app.api.intervals) tick();
  await flush();
  assert.ok(app.calls.some(c => c.method === 'projection_status' && c.args.refresh === false),
    'The actual entry must have completed its five-second local read');
}

test('an actual local producer poll cannot demote complete remote overview coverage', async () => {
  const app = await appFixture(structuredClone(actualRemote));
  try {
    assert.match(app.lifecycle()?.textContent??'',/Complete observation/);
    await pollLocal(app);
    assert.match(app.lifecycle()?.textContent??'',/Complete observation/,
      'Local admission observations cannot replace complete remote membership');
    noMutations(app.calls);
  } finally { app.close(); }
});

test('an actual local producer poll retains the remote overview continuation', async () => {
  const frame = structuredClone(sourceFrame); frame.page.next_cursor = 'fixture-overview-continuation';
  const app = await appFixture(frame);
  try {
    const next = () => app.lifecycle()?.querySelector('[aria-label="Read next source page"]');
    assert.ok(next(),'The valid remote page must have a continuation before polling');
    await pollLocal(app);
    assert.ok(next(),'A local poll cannot erase the pending remote continuation');
    noMutations(app.calls);
  } finally { app.close(); }
});

function mixedName() {
  const frame=structuredClone(sourceFrame);
  const repository=frame.observations.find((o:{resource:{kind:string;id:string}})=>
    o.resource.kind==='repository' && o.resource.id==='101')!;
  repository.value.full_name='Example/Alpha'; repository.value.url='https://github.com/Example/Alpha';
  return frame;
}
test('case-preserving source names use the normalized repository address for refresh', async () => {
  const app=await appFixture(mixedName());
  try {
    await app.click('Inspect Example/Alpha'); await app.click('Refresh workflow sources');
    const refresh=app.calls.filter(c=>c.method==='projection_status' && c.args.repository!==null).at(-1);
    assert.ok(refresh,'A scoped refresh must reach the actual bridge boundary');
    assert.equal(refresh.args.repository,'example/alpha');
    assert.match(app.lifecycle()?.textContent??'',/Example\/Alpha/,'Keep display casing');
    noMutations(app.calls);
  } finally {app.close();}
});
test('case-preserving source names use the normalized address for original navigation', async () => {
  const app=await appFixture(mixedName());
  try {
    await app.click('Inspect Example/Alpha'); await app.click('Inspect work #7 in Example/Alpha');
    await app.click('Open original issue');
    const open=app.calls.find(c=>c.method==='open_record');assert.ok(open);
    assert.deepEqual(open.args,{repository:'example/alpha',kind:'issue',issue:7,expectedPr:null});
    noMutations(app.calls);
  } finally {app.close();}
});
test('a failed continuation preserves current source evidence from completed pages', async () => {
  const frame=structuredClone(sourceFrame);frame.page.next_cursor='fixture-overview-continuation';
  const app=await appFixture(frame);
  try {
    app.api.fail=true;await app.click('Read next source page');
    assert.match(app.lifecycle()?.textContent??'',/refresh.*unavailable/i);
    await app.click('Inspect example/alpha');await app.click('Inspect work #7 in example/alpha');
    const open=app.lifecycle()?.querySelector<HTMLButtonElement>('[aria-label="Open original issue"]');
    assert.ok(open,'The earlier page must remain inspectable');
    assert.equal(open.disabled,false,'A failed new slice cannot stale the already completed source page');
    assert.match(app.lifecycle()?.textContent??'',/Propose/,'Retain the earlier readiness evidence');
    noMutations(app.calls);
  } finally {app.close();}
});
