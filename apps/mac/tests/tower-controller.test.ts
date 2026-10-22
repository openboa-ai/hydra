import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { appFixture, flush, noMutations } from './tower-fixture.ts';
const out=spawnSync('python3',['-I','-c','from pathlib import Path;import sys,json;root=Path.cwd().parents[1];sys.path[:0]=[str(root),str(root/"tests")];from test_projection_qualified_facts import membership_frames;print(json.dumps(membership_frames()))'],
 {encoding:'utf8',timeout:60_000,maxBuffer:4_194_304});
assert.equal(out.status,0,'The actual producer controls must run: '+out.stderr);
const [remote,local,alpha]=JSON.parse(out.stdout);
type App=Awaited<ReturnType<typeof appFixture>>;
const refresh=(app:App)=>app.lifecycle()!.querySelector<HTMLButtonElement>('[aria-label="Refresh workflow sources"]')!;
async function tick(app:App,ms:number){app.advance(ms);for(const callback of app.api.intervals)callback();await flush();}
async function inspectAlias(app:App){
 const project=[...app.lifecycle()!.querySelectorAll<HTMLButtonElement>('nav button')].find(b=>b.textContent?.includes('example/alpha'));
 assert.ok(project,'The actual local producer must expose the registered project');project.click();await flush();
}

test('unresolved local project aliases expose no original-Issue or mutation authority',async()=>{
 const app=await appFixture(structuredClone(local));
 try{await inspectAlias(app);assert.match(app.lifecycle()?.textContent??'',/Unconfirmed/);
  assert.equal(app.lifecycle()?.querySelector('[aria-label="Open original issue"]'),null);noMutations(app.calls);
 }finally{app.close();}
});
test('a requested project alias can recover with its encoded normalized read address',async()=>{
 const app=await appFixture(structuredClone(local));
 try{await inspectAlias(app);
  app.api.deferred=(args,n)=>args.repository==='example/alpha'?Promise.resolve(app.cached(args,alpha,n)):undefined;
  await app.click('Refresh workflow sources');
  assert.ok(app.calls.some(c=>c.method==='projection_status' && c.args.repository==='example/alpha'),
   'A requested alias must reach the fixed scoped read bridge');
  assert.match(app.lifecycle()?.textContent??'',/Can you approve and start this task\?/);noMutations(app.calls);
 }finally{app.close();}
});
test('binding preflight failure invalidates the selected original navigation immediately',async()=>{
 const app=await appFixture(structuredClone(remote));
 try{await app.click('Inspect example/alpha');await app.click('Inspect work #7 in example/alpha');
  const open=()=>app.lifecycle()!.querySelector<HTMLButtonElement>('[aria-label="Open original issue"]')!;
  assert.equal(open().disabled,false,'The current source is a valid positive control');
  app.api.beforeInvoke=method=>{if(method==='projection_binding')throw {code:'backend_unavailable',message:'PRIVATE_PROVIDER_CANARY'};};
  await app.click('Refresh workflow sources');
  assert.equal(open().disabled,true,'A failed preflight cannot leave retained evidence current');
  assert.ok(!app.lifecycle()?.textContent?.includes('PRIVATE_PROVIDER_CANARY'));noMutations(app.calls);
 }finally{app.close();}
});
test('shared binding failure also invalidates another retained project source',async()=>{
 const app=await appFixture(structuredClone(remote));
 try{await app.click('Inspect example/alpha');
  app.api.beforeInvoke=method=>{if(method==='projection_binding')throw {code:'backend_unavailable'};};
  await app.click('Refresh workflow sources');
  await app.click('Inspect example/beta');await app.click('Inspect work #4 in example/beta');
  const open=app.lifecycle()!.querySelector<HTMLButtonElement>('[aria-label="Open original issue"]')!;
  assert.ok(open);assert.equal(open.disabled,true,'An unavailable shared binding cannot authorize another original navigation');
  noMutations(app.calls);
 }finally{app.close();}
});
test('clock recovery releases the old remote display lane while retaining its pending invocation',async()=>{
 const app=await appFixture();let finish:(()=>void)|undefined;
 try{app.api.deferred=(args,n)=>!args.refresh?Promise.resolve(app.cached(args,local,n)):
   new Promise(resolve=>{finish=()=>resolve(app.cached(args,app.api.frame,n));});
  await app.click('Refresh workflow sources');assert.ok(finish);
  await tick(app,20_000);
  assert.ok(app.calls.some(c=>c.method==='projection_clock_resumed'));
  assert.equal(refresh(app).disabled,false,'The old generation cannot hold the current refresh control');
  noMutations(app.calls);
 }finally{finish?.();await flush();app.close();}
});
test('an old remote completion cannot release a newer generation pending lane',async()=>{
 const app=await appFixture();const finish:(()=>void)[]=[];
 try{app.api.deferred=(args,n)=>!args.refresh?Promise.resolve(app.cached(args,local,n)):
   new Promise(resolve=>{finish.push(()=>resolve(app.cached(args,app.api.frame,n)));});
  await app.click('Refresh workflow sources');assert.equal(finish.length,1);
  await tick(app,20_000);await app.click('Refresh workflow sources');
  assert.equal(finish.length,2,'The new generation must own a distinct pending read');
  finish[0]!();await flush();
  assert.equal(refresh(app).disabled,true,'The newer invocation still owns its lane');noMutations(app.calls);
 }finally{for(const done of finish)done();await flush();app.close();}
});
test('clock recovery can reconcile the local source before its old local invocation settles',async()=>{
 const app=await appFixture();let finish:(()=>void)|undefined;let reads=0;
 try{app.api.deferred=(args,n)=>args.refresh?undefined:++reads===1?
   new Promise(resolve=>{finish=()=>resolve(app.cached(args,local,n));}):Promise.resolve(app.cached(args,local,n));
  await tick(app,5_000);assert.ok(finish);
  await tick(app,20_000);
  assert.equal(reads,2,'A fenced local invocation cannot block the current generation reconciliation');noMutations(app.calls);
 }finally{finish?.();await flush();app.close();}
});
test('a superseded clock acknowledgement schedules recovery for the current generation',async()=>{
 const app=await appFixture();let finish:(()=>void)|undefined;let recoveries=0;
 try{app.api.beforeInvoke=method=>{
   if(method==='projection_clock_resumed')return ++recoveries===1?new Promise(resolve=>{finish=()=>resolve(null);}):Promise.resolve(null);
  };
  await tick(app,20_000);assert.ok(finish);await tick(app,20_000);
  assert.equal(recoveries,1,'Keep only one physical clock IPC pending');
  finish!();await flush();
  assert.equal(recoveries,2,'The old acknowledgement cannot confirm the newer resume boundary');noMutations(app.calls);
 }finally{finish?.();await flush();app.close();}
});

test('cached or stale replies cannot acknowledge a failed remote refresh',async()=>{
 const app=await appFixture();
 try{await app.click('Inspect example/alpha');app.api.fail=true;
  await app.click('Refresh workflow sources');
  const status=()=>app.lifecycle()?.querySelector('[role="status"]')?.textContent??'';
  assert.match(status(),/refresh.*unavailable/i);app.api.fail=false;
  for(const stale of [true,false]){
   app.api.deferred=(args,n)=>Promise.resolve({...app.cached(args,app.api.frame,n),cached:true,stale});
   await app.click('Refresh workflow sources');
   assert.match(status(),/refresh.*unavailable/i,'A held cached reply cannot confirm provider recovery');
  }
  noMutations(app.calls);
 }finally{app.close();}
});
