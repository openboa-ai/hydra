import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { appFixture, flush, noMutations, sourceFrame } from './tower-fixture.ts';

const emitted=spawnSync('python3',['-I','-c',
  'from pathlib import Path;import sys,json;root=Path.cwd().parents[1];sys.path[:0]=[str(root),str(root/"tests")];from test_projection_qualified_facts import membership_frames;from test_projection_read import ReadFixture,issue;remote,local,_=membership_frames();beta=ReadFixture({("example/beta","open",False):[issue(4)]}).read(repository="example/beta");print(json.dumps([remote,local,beta]))'],
  {encoding:'utf8',timeout:60_000,maxBuffer:4_194_304});
assert.equal(emitted.status,0,'Actual producer controls must run: '+emitted.stderr);
const [actualRemote,actualLocal,actualBeta]=JSON.parse(emitted.stdout);
const status=(app:Awaited<ReturnType<typeof appFixture>>)=>
  app.lifecycle()?.querySelector('[role="status"]')?.textContent??'';

test('a failed continuation remains visible after a successful actual local poll',async()=>{
  const frame=structuredClone(sourceFrame);frame.page.next_cursor='fixture-overview-continuation';
  const app=await appFixture(frame);
  try {
    app.api.fail=true;await app.click('Read next source page');
    assert.match(status(app),/refresh.*unavailable/i);
    app.api.fail=false;
    app.api.deferred=(args,sequence)=>args.refresh?undefined:
      Promise.resolve(app.cached(args,actualLocal,sequence));
    app.advance(5_000);for(const tick of app.api.intervals)tick();await flush();
    assert.ok(app.calls.some(c=>c.method==='projection_status' && c.args.refresh===false));
    assert.match(status(app),/refresh.*unavailable/i,'Local success cannot acknowledge a failed remote continuation');
    noMutations(app.calls);
  } finally {app.close();}
});

test('another project source success cannot acknowledge the failed project query',async()=>{
  const app=await appFixture(structuredClone(actualRemote));
  try {
    await app.click('Inspect example/alpha');app.api.fail=true;
    await app.click('Refresh workflow sources');assert.match(status(app),/refresh.*unavailable/i);
    app.api.fail=false;
    app.api.deferred=(args,sequence)=>args.repository==='example/beta'?
      Promise.resolve(app.cached(args,actualBeta,sequence)):undefined;
    await app.click('Inspect example/beta');await app.click('Refresh workflow sources');
    assert.match(status(app),/refresh.*unavailable/i,'Beta recovery cannot acknowledge Alpha failure');
    assert.match(status(app),/example\/alpha/,'The remaining failure identifies its actual source target');
    noMutations(app.calls);
  } finally {app.close();}
});

test('a successful first-page refresh cannot acknowledge a failed continuation query',async()=>{
  const frame=structuredClone(sourceFrame);
  frame.projects[0].coverage.next_cursor='fixture-alpha-continuation';
  const app=await appFixture(frame);
  try {
    await app.click('Inspect example/alpha');app.api.fail=true;
    await app.click('Read next source page');assert.match(status(app),/refresh.*unavailable/i);
    app.api.fail=false;await app.click('Refresh workflow sources');
    assert.match(status(app),/refresh.*unavailable/i,'A different query cannot acknowledge the failed page');
    noMutations(app.calls);
  } finally {app.close();}
});

test('a matching remote query success clears its own failure feedback',async()=>{
  const app=await appFixture();
  try {
    await app.click('Inspect example/alpha');app.api.fail=true;
    await app.click('Refresh workflow sources');assert.match(status(app),/refresh.*unavailable/i);
    app.api.fail=false;await app.click('Refresh workflow sources');
    assert.doesNotMatch(status(app),/refresh.*unavailable/i);
    assert.equal(app.calls.filter(c=>c.method==='projection_status' && c.args.repository==='example/alpha').length,2);
    noMutations(app.calls);
  } finally {app.close();}
});
