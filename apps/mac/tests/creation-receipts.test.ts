import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {spawnSync} from "node:child_process";
import test from "node:test";
import {parseStandardReply, ProjectionError} from "../src/projection.ts";
import {projectionState, reduceProjection} from "../src/projection-state.ts";

const emitted=spawnSync("python3",["-I",new URL("../../../tests/fixtures/control-v3/emit_creation.py",import.meta.url).pathname],
  {encoding:"utf8",maxBuffer:4_194_304});
assert.equal(emitted.status,0,"The actual Registration emitter failed");
const rows=JSON.parse(emitted.stdout) as {name:string;wire:string;standard_reason:string|null}[];
assert.ok(rows.length>0 && rows.length<=256);
function reason(wire:unknown) {
  try {parseStandardReply(wire);return null;}
  catch(error) {assert.ok(error instanceof ProjectionError);return error.reason;}
}
for(const row of rows)test("creation receipt boundary: "+row.name,()=>{
  assert.equal(reason(row.wire),row.standard_reason);
});
test("unqualified registration cannot become applied feedback or replace source facts",()=>{
  const frame=JSON.parse(readFileSync(new URL("../../../tests/fixtures/control-v3/inputs.json",import.meta.url),"utf8")).frame;
  const reply=JSON.parse(rows.find(row=>row.name==="registered")!.wire);
  // Align transport identity only; no source or authority evidence is added.
  reply.binding_epoch=frame.binding_epoch;reply.runtime=structuredClone(frame.runtime);
  assert.equal(reason(reply),"unsupported_command_source");
  let state=projectionState(frame.binding_epoch);
  state=reduceProjection(state,{type:"read_started",scope:"overview",sequence:1,request_id:frame.request_id});
  state=reduceProjection(state,{type:"read_succeeded",scope:"overview",sequence:1,now:1000,
    response:{payload:frame,age_ms:0,cached:false,stale:false,sequence:1,read_context:{scope:"fixture:read",sequence:1}}});
  assert.ok(state.view && state.source_slots.size>0);
  const facts=JSON.stringify(state.view),slots=JSON.stringify([...state.source_slots]);
  const request=reply.request;
  state=reduceProjection(state,{type:"command_started",request_id:request.request_id,
    effect_key:"33333333-3333-4333-8333-333333333333",action:"work_create",target:request.target});
  assert.ok(state.pending_commands.has(request.request_id));
  state=reduceProjection(state,{type:"command_result",request_id:request.request_id,reply});
  assert.equal(state.feedback.get(request.request_id)?.outcome,"unknown");
  assert.equal(state.feedback.get(request.request_id)?.receipt,null);
  assert.equal(state.pending_commands.size,0);
  assert.equal(JSON.stringify(state.view),facts);
  assert.equal(JSON.stringify([...state.source_slots]),slots);
});
