import assert from "node:assert/strict";
import {spawnSync} from "node:child_process";
import {readFileSync} from "node:fs";
import test from "node:test";
import {parseProjection,parseStandardReply} from "../src/projection.ts";
import {projectionState,reduceProjection} from "../src/projection-state.ts";
const base=JSON.parse(readFileSync(new URL("../../../tests/fixtures/control-v3/inputs.json",import.meta.url),"utf8")).frame;
const id=(n:number)=>"00000000-0000-4000-8000-"+n.toString(16).padStart(12,"0");
function python(args:string[]){const out=spawnSync("python3",["-I",...args],{encoding:"utf8",timeout:60000,maxBuffer:33554432});
  assert.equal(out.status,0,"Actual bounded fixture failed: "+out.stderr);return JSON.parse(out.stdout);}
const vectors=()=>python([new URL("../../../tests/fixtures/control-v3/emit_qualified.py",import.meta.url).pathname]);
function read(state:ReturnType<typeof projectionState>,frame:unknown,scope:string,n:number){
  const value=parseProjection(frame);value.request_id=id(n);
  state=reduceProjection(state,{type:"read_started",scope,sequence:n,request_id:value.request_id});
  return reduceProjection(state,{type:"read_succeeded",scope,sequence:n,now:n*1000,
    response:{payload:value,age_ms:0,cached:false,stale:false,sequence:n,read_context:{scope:"fixture:read",sequence:1}}});
}
test("qualified fact matrix uses Python positive encoders and literal claim oracles",()=>{
  const rows=vectors();assert.equal(rows.length,862);
  for(const row of rows){const call=()=>row.profile==="projection"?parseProjection(row.wire):parseStandardReply(row.wire);
    if(row.accepted)assert.doesNotThrow(call,row.name+" "+row.profile);
    else assert.throws(call,undefined,row.name+" "+row.profile);}
});
test("admission feedback cannot use a foreign active-store readback",()=>{
  for(const row of vectors().filter((r:{family:string;profile:string})=>r.family==="receipt" && r.profile==="standard")){
    const reply=JSON.parse(row.wire);let state=read(projectionState(base.binding_epoch),structuredClone(base),"remote:overview:",1);
    state=reduceProjection(state,{type:"command_started",request_id:reply.request.request_id,effect_key:null,
      action:"admission_set",target:reply.request.target,parameters:{mode:"paused"}});
    state=reduceProjection(state,{type:"command_result",request_id:reply.request.request_id,reply});
    assert.equal(state.feedback.get(reply.request.request_id)?.outcome,row.accepted?"applied":"unknown",row.name);
  }
});
function frames(){return python(["-c","from pathlib import Path;import sys,json;root=Path.cwd().parents[1];sys.path[:0]=[str(root),str(root/'tests')];from test_projection_qualified_facts import membership_frames;print(json.dumps(membership_frames()))"]);}
test("actual local admission polls preserve remote overview coverage and source age",()=>{
  const [remote,local]=frames();let state=read(projectionState(base.binding_epoch),remote,"remote:overview:",1);
  const before=structuredClone(state.view!.page);const issue=[...state.source_slots.values()].find(s=>s.observation.resource.kind==="issue")!;
  const repository=[...state.source_slots.values()].find(s=>s.observation.resource.kind==="repository" && s.observation.resource.id==="101")!;
  const repositoryReceived=repository.received_at;
  const received=issue.received_at;state=read(state,local,"local:overview:",2);
  assert.deepEqual(state.view!.page,before,"A local admission read replaced remote membership");
  assert.deepEqual(state.view!.work.map(w=>w.issue_ref.id).sort(),["101:7","102:4"]);
  assert.equal(state.view!.work.find(w=>w.issue_ref.id==="101:7")!.admission.value,"paused");
  assert.equal(state.source_slots.get(issue.observation.key)!.received_at,received,"A local read renewed the remote source");
  const retained=state.source_slots.get(repository.observation.key)!;
  assert.equal(retained.observation.resource.id,"101");assert.equal(retained.observation.availability,"current");
  assert.equal(retained.stale,false);assert.equal(retained.received_at,repositoryReceived);
});
test("a scoped remote read cannot replace retained host overview coverage",()=>{
  const [remote,,detail]=frames();let state=read(projectionState(base.binding_epoch),remote,"remote:overview:",1);
  const before=structuredClone(state.view!.page);state=read(state,detail,"remote:example/alpha:",2);
  assert.deepEqual(state.view!.page,before,"Repository membership replaced the host overview");
  let partial=read(projectionState(base.binding_epoch),detail,"remote:example/alpha:",1);
  partial=read(partial,remote,"remote:overview:",2);assert.deepEqual(partial.view!.page,remote.page);
});
