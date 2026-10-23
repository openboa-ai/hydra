/** CP-D17/P16: compatibility can inspect source without acquiring command authority. */
import assert from 'node:assert/strict';
import test from 'node:test';
import {appFixture,flush,noMutations} from './tower-fixture.ts';

async function compatibility() {
  const app=await appFixture();
  const execution={state:'unknown',active_count:null,reason:'native_ownership_unconfirmed'};
  const snapshot={schema_version:2,observed_at:app.api.frame.assembled_at,host_alias:'Fixture host',revision:5,
    runtime:{identity_schema:1,package:'openboa-hydra-sdlc',version:'0.2.1',code_digest:'a'.repeat(64),
      code_digest_scope:'package_sources_at_startup',config_digest:'b'.repeat(64),control_binding_digest:'c'.repeat(64),identity_reason:null},
    global_mode:'paused',gate_status:'blocked',gate_reason:'host_paused',native_turn_control:'unsupported',execution,
    coverage:{state:'unverified',reason:'schedule_coverage_unverified'},can_quit:false,
    quit_reason:'schedule_coverage_unverified',remote:{state:'not_requested',observed_at:null},request:null,
    projects:[{repository:'example/alpha',override_mode:'paused',effective_mode:'paused',gate_status:'blocked',
      gate_reason:'host_paused',execution,links:{chat:null},work:[{issue:7,phase:'waiting',wait_reason:null,next_action:null,
        links:{issue:'https://github.com/example/alpha/issues/7',pr:null}}]}]};
  app.api.beforeInvoke=(method)=>method==='status'?structuredClone(snapshot):undefined;
  app.document.querySelector<HTMLDetailsElement>('#host-controls')!.open=true;
  app.document.querySelector<HTMLButtonElement>('[aria-label="Refresh local status"]')!.click();
  await flush();
  return app;
}
const quit=(app:Awaited<ReturnType<typeof compatibility>>)=>[...app.document.querySelectorAll<HTMLButtonElement>('#app footer button')]
  .find(button=>/quit/i.test(button.getAttribute('aria-label')??''));

test('valid v2 compatibility status remains inspectable and refreshable',async()=>{
  const app=await compatibility();
  try {
    assert.equal(app.document.querySelector('#app h1')?.textContent,'Hydra');
    assert.match(app.document.querySelector('#app')?.textContent??'',/alpha/);
    const refresh=app.document.querySelector<HTMLButtonElement>('[aria-label="Refresh local status"]')!;
    assert.equal(refresh.disabled,false);
    const before=app.calls.filter(c=>c.method==='status').length;
    refresh.click();await flush();
    assert.ok(app.calls.filter(c=>c.method==='status').length>before);
    noMutations(app.calls);
  } finally {app.close();}
});
test('v2 host and project controls stay read-only despite a valid runtime observation',async()=>{
  const app=await compatibility();
  try {
    const controls=[...app.document.querySelectorAll<HTMLButtonElement>('#app .controls button')];
    assert.equal(controls.length,8);
    assert.ok(controls.every(button=>button.disabled),'Every legacy host/project command must be unavailable');
    assert.match(app.document.querySelector('#app')?.textContent??'',/read.only compatibility/i);
    noMutations(app.calls);
  } finally {app.close();}
});
test('forcing a compatibility button handler cannot dispatch a legacy write',async()=>{
  const app=await compatibility();
  try {
    const stop=app.document.querySelector<HTMLButtonElement>('[aria-label="Stop all projects"]')!;
    assert.ok(stop);stop.disabled=false;stop.click();await flush();
    noMutations(app.calls);
  } finally {app.close();}
});
test('compatibility Quit is unavailable without qualified shutdown support',async()=>{
  const app=await compatibility();
  try {assert.ok(quit(app));assert.equal(quit(app)!.disabled,true);noMutations(app.calls);}
  finally {app.close();}
});
test('forcing compatibility Quit cannot request an implicit global Stop',async()=>{
  const app=await compatibility();
  try {
    const button=quit(app);assert.ok(button);button.disabled=false;button.click();await flush();
    noMutations(app.calls);
  } finally {app.close();}
});
test('compatibility original navigation retains its existing guarded read target',async()=>{
  const app=await compatibility();
  try {
    const original=app.document.querySelector<HTMLButtonElement>('[aria-label="Open Issue #7 for example/alpha issue 7"]');
    assert.ok(original);assert.equal(original.disabled,false);original.click();await flush();
    const call=app.calls.find(c=>c.method==='open_record');assert.ok(call);
    assert.deepEqual(call.args,{repository:'example/alpha',kind:'issue',issue:7,expectedPr:null});
    noMutations(app.calls);
  } finally {app.close();}
});
