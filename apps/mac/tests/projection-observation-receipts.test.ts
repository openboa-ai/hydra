import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import {parseProjection,parseStandardReply} from "../src/projection.ts";
import {projectionState,reduceProjection,type ProjectionState} from "../src/projection-state.ts";
const load=(name:string)=>JSON.parse(readFileSync(new URL("../../../tests/fixtures/control-v3/"+name,import.meta.url),"utf8"));
const frame=load("inputs.json").frame;
const rows=load("receipt-states.json").commands;
const sample=(name:string)=>structuredClone(rows.find((c:{name:string})=>c.name===name));
const modes=["running","paused","stopped"];
function seeded(){
  let state=projectionState(frame.binding_epoch);
  state=reduceProjection(state,{type:"read_started",scope:"overview",sequence:1,request_id:frame.request_id});
  return reduceProjection(state,{type:"read_succeeded",scope:"overview",sequence:1,now:1000,
    response:{payload:frame,age_ms:0,cached:false,stale:false,sequence:1,read_context:{scope:"fixture:read",sequence:1}}});
}
function applied(c:any,state:ProjectionState=seeded(),supported=true){
  if(supported)parseStandardReply(c.reply);else assert.throws(()=>parseStandardReply(c.reply));
  const before=JSON.stringify(state.view);
  state=reduceProjection(state,c.event);
  state=reduceProjection(state,{type:"command_result",request_id:c.event.request_id,reply:c.reply});
  assert.equal(JSON.stringify(state.view),before,"A command receipt replaced current source facts");
  return state.feedback.get(c.event.request_id);
}
for(const desired of modes)for(const actual of modes)test(`host admission ${desired}/${actual}`,()=>{
  const c=sample("admission");c.event.target={kind:"host"};c.reply.request.target=c.event.target;
  c.event.parameters={mode:desired};c.reply.observations[0].value.global_mode=actual;
  assert.equal(applied(c)?.outcome,desired===actual || desired==="paused" && actual==="stopped"?"applied":"unknown");
});
for(const desired of modes)for(const actual of modes)for(const host of modes)
test(`stored project admission ${desired}/${actual}/host:${host}`,()=>{
  const c=sample("admission");c.event.parameters={mode:desired};
  c.reply.observations[0].value.global_mode=host;
  c.reply.observations[0].value.project_overrides={"example/alpha":actual,"example/beta":"stopped"};
  const same=desired===actual || desired==="paused" && actual==="stopped";
  assert.equal(applied(c)?.outcome,same && (desired!=="running" || host==="running")?"applied":"unknown");
});
for(const desired of modes)test("missing project override "+desired,()=>{
  const c=sample("admission");c.event.parameters={mode:desired};
  c.reply.observations[0].value.global_mode="running";c.reply.observations[0].value.project_overrides={};
  assert.equal(applied(c)?.outcome,desired==="running"?"applied":"unknown");
});
test("admission retains only a bounded immutable requested mode",()=>{
  const c=sample("admission");c.event.target={kind:"host"};c.reply.request.target=c.event.target;
  c.event.parameters={mode:"paused",summary:"PRIVATE_MODE_TRACKING_CANARY"};
  let state=reduceProjection(seeded(),c.event);
  assert.deepEqual(state.pending_commands.get(c.event.request_id)?.parameters,{mode:"paused"});
  c.event.parameters.mode="stopped";
  state=reduceProjection(state,{type:"command_result",request_id:c.event.request_id,reply:c.reply});
  assert.equal(state.feedback.get(c.event.request_id)?.outcome,"applied");
  assert.equal(JSON.stringify([...state.feedback.values()]).includes("PRIVATE_MODE_TRACKING_CANARY"),false);
});
for(const missing of ["mode","repository","ambiguous"])
test("incomplete admission correlation stays unknown: "+missing,()=>{
  const c=sample("admission");c.event.parameters=missing==="mode"?{}:{mode:"running"};
  c.reply.observations[0].value.global_mode="running";
  const state=seeded();
  if(missing==="repository")state.source_slots.clear();
  if(missing==="ambiguous"){
    const slot=structuredClone(state.source_slots.get("github:101:repository")!);
    slot.observation.key="github:101:other";slot.observation.value!.full_name="example/other";
    state.source_slots.set(slot.observation.key,slot);
  }
  assert.equal(applied(c,state)?.outcome,"unknown");
});
for(const ref of [
  {source:"github",kind:"pull_request",id:"101:9"},
  {source:"github",kind:"pull_request",id:"101:10"},
  {source:"github",kind:"pull_request",id:"102:9"},
  {source:"codex",kind:"pull_request",id:"101:9"},
  {source:"github",kind:"issue",id:"101:9"},
  {source:"github",kind:"pull_request",id:"fixture-pr"},
])test("delivery exact PR "+JSON.stringify(ref),()=>{
  const c=sample("delivery");c.reply.request.receipt.pr_ref=ref;
  assert.equal(applied(c,seeded(),false)?.outcome,"unknown","Unqualified delivery cannot prove a merge");
});
test("delivery snapshots the requested PR and cannot infer a missing number",()=>{
  const c=sample("delivery");c.reply.request.receipt.pr_ref={source:"github",kind:"pull_request",id:"101:9"};
  let state=reduceProjection(seeded(),c.event);c.event.parameters.pr_number=10;
  state=reduceProjection(state,{type:"command_result",request_id:c.event.request_id,reply:c.reply});
  assert.equal(state.pending_commands.size,0);
  assert.equal(state.feedback.get(c.event.request_id)?.outcome,"unknown","Unqualified delivery remains unknown");
  delete c.event.parameters.pr_number;assert.equal(applied(c,seeded(),false)?.outcome,"unknown");
});
for(const row of load("cleanup-receipts.json").cases)test("cleanup proof "+row.name,()=>{
  const combined=structuredClone(frame);combined.request=JSON.parse(row.wire).request;
  if(row.accepted){parseStandardReply(row.wire);parseProjection(combined);}
  else{assert.throws(()=>parseStandardReply(row.wire));assert.throws(()=>parseProjection(combined));}
});
