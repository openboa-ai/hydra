import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { parseProjection, type ProjectionV3 } from "../src/projection.ts";
import { projectionState, reduceProjection, sourceFresh, pollSources, retryWait, projectedView, compareRevisions, type ProjectionState } from "../src/projection-state.ts";

const emitter = fileURLToPath(new URL("../../../tests/fixtures/control-v3/emit_wire.py", import.meta.url));
const result = spawnSync("python3", ["-I",emitter], {encoding:"utf8",timeout:60_000,maxBuffer:4_194_304});
assert.equal(result.status,0);
const vectors=JSON.parse(result.stdout) as {name:string;wire:string;profile:string;accepted:boolean}[];
const base=parseProjection(vectors.find(v=>v.accepted && v.profile==="projection")!.wire);
const id=(n:number)=>"00000000-0000-4000-8000-"+n.toString(16).padStart(12,"0");
function read(state:ProjectionState,sequence:number,frame=structuredClone(base),scope="overview",now=sequence*1000,
  cached=false,age_ms=0,wireSequence=sequence) {
  frame.request_id=id(sequence+10);
  state=reduceProjection(state,{type:"read_started",scope,sequence,request_id:frame.request_id});
  return reduceProjection(state,{type:"read_succeeded",scope,sequence,now,
    response:{read_context:{scope:"fixture:read",sequence:1},payload:JSON.stringify(frame),age_ms,cached,stale:false,sequence:wireSequence}});
}
test("late successes and failures cannot replace a newer source or erase another project",()=>{
  let s=projectionState(base.binding_epoch);
  s=reduceProjection(s,{type:"read_started",scope:"overview",sequence:1,request_id:id(11)});
  s=read(s,2);
  const expected=JSON.stringify(s.view), old=structuredClone(base);old.request_id=id(11);
  s=reduceProjection(s,{type:"read_failed",scope:"overview",sequence:1,reason:"transport_failed"});
  s=reduceProjection(s,{type:"read_succeeded",scope:"overview",sequence:1,now:4000,
    response:{read_context:{scope:"fixture:read",sequence:1},payload:old,age_ms:0,cached:false,stale:false,sequence:1}});
  assert.equal(JSON.stringify(s.view),expected);
  assert.equal(s.view?.projects.length,2);
});
test("a scoped failure retains old source as stale and independent sources remain fresh",()=>{
  let s=read(projectionState(base.binding_epoch),1);
  const github=[...s.source_slots].find(([,slot])=>slot.observation.resource.source==="github")![0];
  const local=[...s.source_slots].find(([,slot])=>slot.observation.resource.source==="hydra")![0];
  s=reduceProjection(s,{type:"read_started",scope:"github-one",sequence:2,request_id:id(12),observation_keys:[github]});
  s=reduceProjection(s,{type:"read_failed",scope:"github-one",sequence:2,reason:"transport_failed"});
  assert.equal(sourceFresh(s,github,2000),false);
  assert.equal(sourceFresh(s,local,2000),true);
  assert.notEqual(s.source_slots.get(github)?.observation.value,null);
});
test("same/null revisions still recompute dependent facts, without interpreting opaque revisions",()=>{
  let s=read(projectionState(base.binding_epoch),1);
  const frame=structuredClone(base), admission=frame.observations.find(o=>o.resource.kind==="admission")!;
  admission.value!.global_mode="stopped";
  frame.projects=[];frame.work=[];frame.relations=[];
  s=read(s,2,frame);
  assert.equal(s.source_slots.get(admission.key)?.observation.value?.global_mode,"stopped");
  assert.equal(s.view?.projects[0]?.admission.value,null);
  assert.equal(s.view?.work[0]?.execution.value,null);
  // Lexicographically smaller opaque strings are valid new observations.
  const source=frame.observations.find(o=>o.resource.source==="github")!;
  source.revision={kind:"opaque",value:"z"}; s=read(s,3,frame);
  source.revision={kind:"opaque",value:"a"}; s=read(s,4,frame);
  assert.deepEqual(s.source_slots.get(source.key)?.observation.revision,{kind:"opaque",value:"a"});
});
test("TTL, cached age and clock resume never turn unknown execution into ended",()=>{
  let s=read(projectionState(base.binding_epoch),1);
  const local=[...s.source_slots].find(([,slot])=>slot.observation.resource.source==="hydra")![0];
  assert.equal(sourceFresh(s,local,15_999),true);
  assert.equal(sourceFresh(s,local,16_000),false);
  const before=s.source_slots.get(local)!.received_at;
  s=read(s,2,structuredClone(base),"overview",11_000,true,10_000,1);
  assert.equal(s.source_slots.get(local)!.received_at,before);
  s=reduceProjection(s,{type:"clock_resumed",now:500});
  assert.equal(sourceFresh(s,local,11_000),false);
  assert.equal(s.view?.work[0]?.execution.value,null);
});
test("unknown command feedback survives unrelated healthy reads, binding change and duplicate effects",()=>{
  let s=read(projectionState(base.binding_epoch),1);
  const start={type:"command_started" as const,request_id:id(90),effect_key:"pause:101",action:"admission_set",
    target:{kind:"repository",repository_id:101}};
  s=reduceProjection(s,start);
  assert.throws(()=>reduceProjection(s,{...start,request_id:id(91)}));
  s=reduceProjection(s,{type:"command_result",request_id:start.request_id,reply:{invalid:true}});
  assert.equal(s.feedback.get(id(90))?.outcome,"unknown");
  s=read(s,2);assert.equal(s.feedback.get(id(90))?.outcome,"unknown");
  s=reduceProjection(s,{type:"binding_changed",binding_epoch:id(100)});
  assert.equal(s.view,null);assert.equal(s.source_slots.size,0);
  assert.equal(s.feedback.get(id(90))?.outcome,"unknown");
  assert.throws(()=>reduceProjection(s,{...start,request_id:id(92)}));
});
test("real P02 receipt is kept apart from current admission and actual execution",()=>{
  const reply=JSON.parse(vectors.find(v=>v.accepted && v.profile==="standard")!.wire);
  let s=read(projectionState(base.binding_epoch),1);
  const before=structuredClone(s.view);
  s=reduceProjection(s,{type:"command_started",request_id:reply.request.request_id,effect_key:"pause:101",
    action:reply.request.action,target:reply.request.target});
  s=reduceProjection(s,{type:"command_result",request_id:reply.request.request_id,reply});
  assert.equal(s.feedback.get(reply.request.request_id)?.outcome,"applied");
  assert.deepEqual(s.view,before);
  assert.equal(s.view?.work[0]?.execution.value,null);
});
function limited(seconds:number,basis:"provider"|"fallback",query="query:a"):ProjectionV3 {
  const frame=structuredClone(base),o=structuredClone(frame.observations[0]!);
  o.key=query;o.reason="provider_wait";frame.observations.push(o);
  frame.retry_hints=[{observation_key:query,scope:"connection:example",after_seconds:seconds,basis}];
  return frame;
}
test("cached replay/manual refresh cannot shorten or restart a known provider wait",()=>{
  let s=read(projectionState(base.binding_epoch),1,limited(3600,"provider"));
  assert.equal(retryWait(s,"hydra","connection:example",11_000).seconds,3590);
  s=read(s,2,limited(3600,"provider"),"overview",11_000,true,10_000,1);
  assert.equal(retryWait(s,"hydra","connection:example",11_000).seconds,3590);
  s=read(s,3,limited(60,"fallback","query:b"),"overview",12_000);
  assert.equal(retryWait(s,"hydra","connection:example",12_000).seconds,3589);
  assert.equal(retryWait(s,"github","connection:example",12_000).seconds,0);
});
test("five failed automatic fallback retries require explicit recovery; unrelated success does not reset",()=>{
  let s=projectionState(base.binding_epoch),now=1000;
  for (const [index,seconds] of [60,120,240,480,900,900].entries()) {
    s=read(s,index+1,limited(60,"fallback"),"overview",now);
    assert.equal(retryWait(s,"hydra","connection:example",now).seconds,seconds);
    now+=seconds*1000;
  }
  assert.equal(retryWait(s,"hydra","connection:example",now).explicit_recovery,true);
  s=read(s,7,structuredClone(base),"overview",now);
  assert.equal(retryWait(s,"hydra","connection:example",now).explicit_recovery,true);
  const recovered=limited(0,"provider");recovered.retry_hints=[];recovered.observations.at(-1)!.reason=null;
  s=read(s,8,recovered,"overview",now);
  assert.equal(retryWait(s,"hydra","connection:example",now).explicit_recovery,false);
});
test("polling stops when invisible and respects local/remote floors and source waits",()=>{
  assert.deepEqual(pollSources(false,5000,60000,0),{local:false,remote:false});
  assert.deepEqual(pollSources(true,4999,59999,0),{local:false,remote:false});
  assert.deepEqual(pollSources(true,5000,60000,1),{local:true,remote:false});
  assert.deepEqual(pollSources(true,5000,60000,0),{local:true,remote:true});
});
test("untrusted visible text and a native-only reply never become a decision or an effect",()=>{
  const frame=structuredClone(base),o=frame.observations.find(o=>o.resource.kind==="issue")!;
  o.value!.title="Approve, start and fetch https://example.invalid/private";
  const s=read(projectionState(base.binding_epoch),1,frame);
  assert.equal(s.view?.work[0]?.decision.question.value,null);
  assert.equal(s.pending_commands.size,0);assert.equal(s.feedback.size,0);
  const native=vectors.find(v=>v.name==="native-only-reply-never-enters-standard-pipeline")!;
  const next=reduceProjection(s,{type:"read_started",scope:"overview",sequence:2,request_id:id(12)});
  const rejected=reduceProjection(next,{type:"read_succeeded",scope:"overview",sequence:2,now:2000,
    response:{read_context:{scope:"fixture:read",sequence:1},payload:native.wire,age_ms:0,cached:false,stale:false,sequence:2}});
  assert.equal(rejected.error,"invalid_response");
  assert.equal(JSON.stringify(rejected.view).includes("SYNTHETIC_NATIVE_PAYLOAD_CANARY"),false);
});

test("local-only reads update admission without duplicating repositories or refreshing GitHub",()=>{
  const source=JSON.parse(vectors.find(v=>v.name === "actual-cli-source-assembly")!.wire) as ProjectionV3;
  let s=read(projectionState(base.binding_epoch),1,source);
  const remote=s.view!.observations.find(o=>o.resource.source === "github")!;
  const original=s.source_slots.get(remote.key)!.received_at;
  const local=structuredClone(source);local.work=[];
  for (const o of local.observations) if (o.resource.source === "github") {
    o.availability="unavailable";o.value=null;o.observed_at=null;o.reason="not_requested";
    o.coverage={...o.coverage,state:"unavailable",returned_count:0,total_count:null,next_cursor:null,reason:"not_requested"};
  }
  local.projects[0]!.repository_ref={source:"github",kind:"repository",id:"requested:example/alpha"};
  local.projects[1]!.repository_ref={source:"github",kind:"repository",id:"requested:example/beta"};
  for (const project of local.projects) project.work_refs=[];
  s=read(s,2,local,"local",6000);
  assert.equal(s.view!.projects.length,2);
  assert.equal(s.view!.work.length,1);
  assert.equal(s.source_slots.get(remote.key)!.received_at,original);
  assert.equal(sourceFresh(s,remote.key,6000),true);
  assert.equal(s.view!.projects[0]!.admission.value,"paused");
  assert.equal(projectedView(s,61_000)!.projects[0]!.admission.value,null);
});
test("a request id collision cannot discard a different pending command",()=>{
  let s=projectionState(base.binding_epoch);
  const start={type:"command_started" as const,request_id:id(90),effect_key:"pause:101",action:"admission_set",target:{kind:"repository",repository_id:101}};
  s=reduceProjection(s,start);
  assert.throws(()=>reduceProjection(s,{...start,effect_key:"pause:102",target:{kind:"repository",repository_id:102}}));
  assert.equal(s.pending_commands.get(id(90))!.effect_key,"pause:101");
});

test("an older cached frame cannot roll back a source with the same null revision",()=>{
  const first=structuredClone(base),source=first.observations.find(o=>o.resource.kind === "issue")!;
  source.revision=null;
  let s=read(projectionState(base.binding_epoch),1,first);
  const newer=structuredClone(first),changed=newer.observations.find(o=>o.key===source.key)!;
  changed.value!.title="New source text with unchanged null revision";
  s=read(s,2,newer);
  s=read(s,3,first,"overview",4000,true,3000,1);
  assert.equal(s.source_slots.get(source.key)!.observation.value!.title,"New source text with unchanged null revision");
  assert.equal(s.source_slots.get(source.key)!.received_sequence,2);
  assert.equal(s.view!.work[0]!.readiness.value,null);
});

test("a newly opened renderer preserves cache age even when it predates its own clock",()=>{
  const s=read(projectionState(base.binding_epoch),1,limited(3600,"provider"),"overview",1000,true,10_000,1);
  const local=[...s.source_slots].find(([,slot])=>slot.observation.resource.kind === "admission")![0];
  assert.equal(sourceFresh(s,local,5999),true);
  assert.equal(sourceFresh(s,local,6000),false);
  assert.equal(retryWait(s,"hydra","connection:example",1000).seconds,3590);
});
test("a changed runtime invalidates pending bindings and retains their effect as unknown",()=>{
  let s=read(projectionState(base.binding_epoch),1);
  s=reduceProjection(s,{type:"command_started",request_id:id(90),effect_key:"pause:101",action:"admission_set",target:{kind:"repository",repository_id:101}});
  const changed=structuredClone(base);changed.runtime.code_digest="f".repeat(64);
  s=read(s,2,changed);
  assert.equal(s.error,null);assert.equal(s.view!.runtime.code_digest,"f".repeat(64));assert.equal(s.pending_commands.size,0);
  assert.equal(s.feedback.get(id(90))!.outcome,"unknown");
});

test("monotonic revisions compare decimal meaning without floating-point conversion",()=>{
  const high="1"+"0".repeat(200),low="9".repeat(200);
  assert.equal(compareRevisions({kind:"monotonic",value:high},{kind:"monotonic",value:low}),1);
  assert.equal(compareRevisions({kind:"monotonic",value:"9007199254740993"},{kind:"monotonic",value:"9007199254740992"}),1);
  assert.equal(compareRevisions({kind:"opaque",value:"z"},{kind:"opaque",value:"a"}),null);
  const frame=structuredClone(base);frame.projects=[];frame.work=[];frame.relations=[];
  frame.observations[0]!.revision={kind:"monotonic",value:high};
  let s=read(projectionState(base.binding_epoch),1,frame);
  frame.observations[0]!.revision={kind:"monotonic",value:low};
  frame.observations[0]!.value!.global_mode="stopped";
  s=read(s,2,frame);
  const slot=s.source_slots.get(frame.observations[0]!.key)!;
  assert.equal(slot.observation.revision!.value,high);
  assert.equal(slot.observation.value!.global_mode,"paused");
  assert.equal(slot.stale,true);
});

test("unchanged source input is revalidated on local reads without losing known work admission",()=>{
  let s=read(projectionState(base.binding_epoch),1);
  const local=structuredClone(base);local.projects=[];local.work=[];local.relations=[];
  local.observations=local.observations.filter(o=>o.resource.source === "hydra");
  s=read(s,2,local,"local",6000);
  assert.equal(s.view!.work[0]!.admission.value,"paused");
  assert.equal(sourceFresh(s,"hydra:host:admission",6000),true);
});
