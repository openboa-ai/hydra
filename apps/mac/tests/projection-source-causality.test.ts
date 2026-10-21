import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {spawnSync} from "node:child_process";
import test from "node:test";
import {parseProjection,parseStandardReply} from "../src/projection.ts";
import {projectionState,reduceProjection,sourceFresh} from "../src/projection-state.ts";
const load=(name:string)=>JSON.parse(readFileSync(new URL("../../../tests/fixtures/control-v3/"+name,import.meta.url),"utf8"));
const input=load("inputs.json"),commands=load("receipt-states.json").commands;
const id=(n:number)=>"00000000-0000-4000-8000-"+n.toString(16).padStart(12,"0");
for(const row of load("source-causality.json").cases)test("source causality "+row.name,()=>{
  const frame=structuredClone(input.frame);
  for(const change of row.changes){let target=frame;for(const k of change.path.slice(0,-1))target=target[k];target[change.path.at(-1)]=structuredClone(change.value);}
  const reply=structuredClone(commands.find((c:any)=>c.name==="admission").reply);reply.observations=frame.observations;
  Object.assign(reply.request,{outcome:"rejected",reason:"fixture_source_check",receipt:null,effect_refs:[],observed_refs:[],required_next:"refresh"});
  for(const [profile,value,check] of [["projection",frame,parseProjection],["standard",reply,parseStandardReply]] as const){
    if(row["accepted_"+profile])assert.doesNotThrow(()=>check(value));else assert.throws(()=>check(value));
  }
});
for(const kind of ["error","none","invalid"])test("actual progress source becomes unavailable: "+kind,()=>{
  const code="from pathlib import Path\nimport sys,json\nr=Path.cwd().parents[1]\nsys.path[:0]=[str(r),str(r/'tests')]\nfrom test_projection_source_causality import source_frames\nprint(json.dumps(source_frames("+JSON.stringify(kind)+")))\n";
  const result=spawnSync("python3",["-I","-c",code],{encoding:"utf8",timeout:60000,maxBuffer:4194304});
  assert.equal(result.status,0,result.stderr);const frames=JSON.parse(result.stdout).map(parseProjection);
  let state=projectionState(frames[0].binding_epoch);
  for(const [n,frame] of frames.entries()){
    frame.request_id=id(970+n);state=reduceProjection(state,{type:"read_started",scope:"overview",sequence:n+1,request_id:frame.request_id});
    state=reduceProjection(state,{type:"read_succeeded",scope:"overview",sequence:n+1,now:1000+n*15000,
      response:{payload:frame,age_ms:0,cached:false,stale:false,sequence:n+1,read_context:{scope:"fixture:read",sequence:1}}});
    assert.equal(sourceFresh(state,"github:101:progress:7",1000+n*15000),n===0);
  }
  const slot=state.source_slots.get("github:101:progress:7");
  assert.equal(slot?.observation.availability,"stale");
  assert.equal(slot?.stale,true);
  assert.equal(slot?.observation.value?.head,"a".repeat(40));
  assert.equal(slot?.observation.reason,kind==="none"?"progress_not_observed":"progress_unavailable");
  assert.deepEqual(state.view?.work.map(w=>w.issue_ref.id).sort(),["101:7","101:8","102:4"]);
});
