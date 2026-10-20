import assert from "node:assert/strict";
import {spawnSync} from "node:child_process";
import {fileURLToPath} from "node:url";
import test from "node:test";
import {MAX_PROJECTION_BYTES,parseProjection,type ProjectionV3} from "../src/projection.ts";
import {projectionState,reduceProjection,type ProjectionState} from "../src/projection-state.ts";
const emitter=fileURLToPath(new URL("../../../tests/fixtures/control-v3/emit_wire.py",import.meta.url));
const result=spawnSync("python3",["-I",emitter],{encoding:"utf8",timeout:60000,maxBuffer:4194304});
assert.equal(result.status,0);
const vectors=JSON.parse(result.stdout) as {accepted:boolean;profile:string;wire:string}[];
const base=parseProjection(vectors.find(v=>v.accepted && v.profile==="projection")!.wire);
const id=(n:number)=>"00000000-0000-4000-8000-"+n.toString(16).padStart(12,"0");
function read(state:ProjectionState,n:number,frame=structuredClone(base)) {
  frame.request_id=id(n+10);
  state=reduceProjection(state,{type:"read_started",scope:"overview",sequence:n,request_id:frame.request_id});
  return reduceProjection(state,{type:"read_succeeded",scope:"overview",sequence:n,now:n*1000,
    response:{payload:JSON.stringify(frame),age_ms:0,cached:false,stale:false,sequence:n}});
}
test("a valid new runtime starts a fresh source generation and fences old pending reads",()=>{
  let s=read(projectionState(base.binding_epoch),1);
  s=reduceProjection(s,{type:"read_started",scope:"old-independent",sequence:2,request_id:id(12)});
  s=reduceProjection(s,{type:"command_started",request_id:id(90),effect_key:"pause:101",action:"admission_set",target:{kind:"repository",repository_id:101}});
  const changed=structuredClone(base);changed.runtime.code_digest="f".repeat(64);
  s=read(s,3,changed);
  assert.equal(s.view!.runtime.code_digest,"f".repeat(64));
  assert.equal(s.pending_commands.size,0);assert.equal(s.feedback.get(id(90))!.outcome,"unknown");
  const old=structuredClone(base);old.request_id=id(12);
  s=reduceProjection(s,{type:"read_succeeded",scope:"old-independent",sequence:2,now:4000,
    response:{payload:old,age_ms:0,cached:false,stale:false,sequence:2}});
  assert.equal(s.view!.runtime.code_digest,"f".repeat(64));
});
test("complete refresh prunes absent work and its source while partial refresh retains it",()=>{
  let s=read(projectionState(base.binding_epoch),1);
  const issue=s.view!.work[0]!.issue_ref;
  const key=s.view!.observations.find(o=>o.resource.kind==="issue" && o.resource.id===issue.id)!.key;
  const empty=structuredClone(base);empty.work=[];
  empty.observations=empty.observations.filter(o=>o.key!==key);
  for (const p of empty.projects) {p.work_refs=[];p.coverage={...p.coverage,state:"complete",reason:null,returned_count:0,total_count:0,next_cursor:null};}
  const partial=structuredClone(empty);
  partial.projects[0]!.coverage={...partial.projects[0]!.coverage,state:"partial",total_count:null,reason:"transport_failed"};
  s=read(s,2,partial);assert.equal(s.view!.work.length,1);
  s=read(s,3,empty);
  assert.equal(s.view!.work.length,0);assert.equal(s.source_slots.has(key),false);
});
test("display casing cannot duplicate a registered repository on a local-only poll",()=>{
  const initial=structuredClone(base);
  initial.observations.find(o=>o.resource.kind==="repository" && o.resource.id==="101")!.value!.full_name="Example/Alpha";
  let s=read(projectionState(base.binding_epoch),1,initial);
  const local=structuredClone(base);local.work=[];
  for (const o of local.observations) if (o.resource.source==="github") {
    o.value=null;o.observed_at=null;o.availability="unavailable";o.reason="not_requested";
    o.coverage={...o.coverage,state:"unavailable",returned_count:0,total_count:null,next_cursor:null,reason:"not_requested"};
  }
  local.projects[0]!.repository_ref={source:"github",kind:"repository",id:"requested:example/alpha"};
  for (const p of local.projects) p.work_refs=[];
  s=read(s,2,local);
  assert.deepEqual(s.view!.projects.map(p=>p.repository_ref.id).sort(),["101","102"]);
});
test("bounded command feedback cannot evict an otherwise valid producer prefix or its cursors",()=>{
  const frame=structuredClone(base),issue=frame.observations.find(o=>o.resource.kind==="issue")!;
  issue.value!.description_excerpt="";issue.value!.description_truncated=false;
  const bytes=()=>new TextEncoder().encode(JSON.stringify(frame)).length;
  for (let n=0;n<1024;n++) {
    frame.observations.push({key:"github:check:fixture:"+n,resource:{source:"github",kind:"check",id:"fixture:"+n},
      revision:null,observed_at:frame.assembled_at,last_attempt_at:frame.assembled_at,availability:"current",reason:null,
      coverage:{state:"complete",scope:"resource:fixture:"+n,returned_count:1,total_count:1,next_cursor:null,reason:null},
      value:{producer:null,name:"fixture",head:"a".repeat(40),status:"completed",conclusion:"success",
        url:"https://github.com/example/alpha/actions/runs/1?fixture="+"x".repeat(1800)}});
    if (bytes()>MAX_PROJECTION_BYTES) {frame.observations.pop();break;}
  }
  const padding=MAX_PROJECTION_BYTES-bytes()-128;
  assert.ok(padding>=0 && padding<=4096);issue.value!.description_excerpt="x".repeat(padding);
  parseProjection(frame);assert.ok(bytes()<=MAX_PROJECTION_BYTES);
  const reply=JSON.parse(vectors.find(v=>v.accepted && v.profile==="standard")!.wire);
  let s=read(projectionState(base.binding_epoch),1,frame);
  const count=s.view!.work.length,cursor=s.view!.page.next_cursor;
  s=reduceProjection(s,{type:"command_started",request_id:reply.request.request_id,effect_key:"e".repeat(512),action:reply.request.action,target:reply.request.target});
  s=reduceProjection(s,{type:"command_result",request_id:reply.request.request_id,reply});
  assert.equal(s.feedback.get(reply.request.request_id)!.outcome,"applied");
  assert.equal(s.view!.work.length,count,"Command feedback silently evicted valid source work");
  assert.equal(s.view!.page.next_cursor,cursor);
});
