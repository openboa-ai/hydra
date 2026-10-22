/** P16 independent UI outcomes on the actual app entry; no native app is opened. */
import assert from 'node:assert/strict';
import test from 'node:test';
import { appFixture, flush, noMutations, sourceFrame } from './tower-fixture.ts';

test('the existing host entry renders in the real DOM without a mutation',async()=>{
  const app=await appFixture();
  try { assert.equal(app.document.querySelector('#app h1')?.textContent,'Hydra');noMutations(app.calls); }
  finally { app.close(); }
});

test('the actual app reads the v3 bridge and shows the observed project and goal overview',async()=>{
  const app=await appFixture();
  try {
    assert.ok(app.calls.some(call=>call.method==='projection_status'),
      'The current app must consume the delivered v3 read path, not only legacy status');
    const text=app.lifecycle()?.textContent??'';
    for(const expected of ['Work lifecycle','Delegated goals','example/alpha','example/beta','Partial'])
      assert.ok(text.includes(expected),`The actual overview must show ${expected}`);
    noMutations(app.calls);
  } finally { app.close(); }
});

test('project and work navigation separates original request, decision, delivery and cleanup',async()=>{
  const app=await appFixture();
  try {
    await app.click('Inspect example/alpha');
    await app.click('Inspect work #7 in example/alpha');
    const text=app.lifecycle()?.textContent??'';
    for(const expected of ['Can you approve and start this task?','Original request','Readiness',
      'Question','Answer received','Answer accepted','Decision applied','Delivery','Outcome','Cleanup','Next action'])
      assert.ok(text.includes(expected),`Work detail must distinguish ${expected}`);
    noMutations(app.calls);
  } finally { app.close(); }
});

test('reported native activity and partial empty work cannot manufacture ended or zero active state',async()=>{
  const app=await appFixture();
  try {
    await app.click('Inspect example/beta');
    const text=app.lifecycle()?.textContent??'';
    assert.match(text,/Unconfirmed/);
    assert.match(text,/Partial/);
    assert.doesNotMatch(text,/0 active|execution ended|all work complete/i);
    assert.ok(!app.calls.some(call=>call.method==='control'));
  } finally { app.close(); }
});

test('original source markup remains visible inert text and cannot introduce DOM or network actions',async()=>{
  const frame=structuredClone(sourceFrame);
  const issue=frame.observations.find((o:{resource:{kind:string}})=>o.resource.kind==='issue')!;
  issue.value.description_excerpt='<img data-canary="original" src="https://invalid.example/secret" onerror="window.canary=1">';
  issue.value.description_truncated=false;
  const app=await appFixture(frame);
  try {
    await app.click('Inspect example/alpha');await app.click('Inspect work #7 in example/alpha');
    assert.ok(app.lifecycle()?.textContent?.includes('<img data-canary="original"'));
    assert.equal(app.document.querySelector('img[data-canary="original"]'),null);
    assert.equal((app.window as unknown as {canary?:unknown}).canary,undefined);
    noMutations(app.calls);
  } finally { app.close(); }
});

test('a failed scoped refresh preserves the project display, independent records and uncertainty',async()=>{
  const app=await appFixture();
  try {
    await app.click('Inspect example/alpha');app.api.fail=true;
    await app.click('Refresh workflow sources');
    assert.match(app.lifecycle()?.textContent??'',/refresh.*(failed|unavailable)/i);
    assert.ok(app.lifecycle()?.textContent?.includes('example/alpha'));
    assert.ok(app.lifecycle()?.textContent?.includes('example/beta'));
    assert.ok(!app.lifecycle()?.textContent?.includes('PRIVATE_PROVIDER_CANARY'));
    assert.doesNotMatch(app.lifecycle()?.textContent??'',/all work complete|0 active/i);
    noMutations(app.calls);
  } finally { app.close(); }
});

test('a late read for another project cannot redirect the current project selection',async()=>{
  const app=await appFixture();
  let finish:((value:unknown)=>void)|undefined;
  try {
    await app.click('Inspect example/alpha');
    app.api.deferred=(args,sequence)=>new Promise(resolve=>{finish=()=>resolve(app.cached(args,sourceFrame,sequence));});
    await app.click('Refresh workflow sources');
    await app.click('Inspect example/beta');
    assert.ok(finish,'The read must actually be pending in the bridge fixture');finish!(null);await flush();
    const selected=app.lifecycle()?.querySelector('[aria-current="page"]');
    assert.ok(selected?.textContent?.includes('example/beta'),'Source completion cannot change the selected target');
    noMutations(app.calls);
  } finally { app.close(); }
});

test('binding replacement clears the old lifecycle selection and source view before new reads',async()=>{
  const app=await appFixture();
  try {
    await app.click('Inspect example/alpha');await app.click('Inspect work #7 in example/alpha');
    app.api.binding='00000000-0000-4000-8000-000000000099';
    await app.click('Refresh workflow sources');
    const text=app.lifecycle()?.textContent??'';
    assert.match(text,/connection changed/i);
    assert.ok(!text.includes('Can you approve and start this task?'));
    assert.equal(app.lifecycle()?.querySelector('[aria-current="page"]'),null);
    noMutations(app.calls);
  } finally { app.close(); }
});
