import assert from "node:assert/strict";
import {spawnSync} from "node:child_process";
import {fileURLToPath} from "node:url";
import test from "node:test";
import {parseProjection,parseStandardReply} from "../src/projection.ts";
import {projectionState,reduceProjection} from "../src/projection-state.ts";
const emitter=fileURLToPath(new URL("../../../tests/fixtures/control-v3/emit_derived.py",import.meta.url));
const result=spawnSync("python3",["-I",emitter],{encoding:"utf8",timeout:60000,maxBuffer:4194304});
assert.equal(result.status,0,result.stderr);
const vectors=JSON.parse(result.stdout) as {name:string;profile:string;accepted:boolean;wire:string}[];
test("all derived-fact source profiles share literal admission/repository/decision oracles",()=>{
  assert.equal(vectors.length,272);const failures:string[]=[];
  for(const row of vectors){let accepted=true;try{(row.profile==="projection"?parseProjection:parseStandardReply)(row.wire);}catch{accepted=false;}
    if(accepted!==row.accepted)failures.push(row.name+":"+row.profile);}
  assert.deepEqual(failures,[]);
});
for(const kind of ["rename","reuse"])test("actual registered-address source sequence: "+kind,()=>{
  const code="from pathlib import Path\nimport sys,json\nr=Path.cwd().parents[1]\nsys.path[:0]=[str(r),str(r/'tests')]\nfrom test_projection_derived_facts import rename_frames\nprint(json.dumps(rename_frames("+JSON.stringify(kind)+")))\n";
  const result=spawnSync("python3",["-I","-c",code],{encoding:"utf8",timeout:60000,maxBuffer:4194304});
  assert.equal(result.status,0,result.stderr);const frames=JSON.parse(result.stdout).map(parseProjection);
  let state=projectionState(frames[0].binding_epoch);
  for(const [n,frame] of frames.entries()){
    frame.request_id="00000000-0000-4000-8000-"+(980+n).toString(16).padStart(12,"0");
    state=reduceProjection(state,{type:"read_started",scope:"overview",sequence:n+1,request_id:frame.request_id});
    state=reduceProjection(state,{type:"read_succeeded",scope:"overview",sequence:n+1,now:1000+n*60000,
      response:{payload:frame,age_ms:0,cached:false,stale:false,sequence:n+1,read_context:{scope:"fixture:read",sequence:1}}});
  }
  assert.ok(state.view?.projects.some(p=>p.repository_ref.id==="101"));
  assert.equal(state.view?.projects.some(p=>p.repository_ref.id==="202"),false);
  if(kind==="rename"){
    assert.equal(state.view?.observations.find(o=>o.resource.kind==="repository" && o.resource.id==="101")?.value?.full_name,"example/renamed");
    assert.equal(state.view?.work.find(w=>w.issue_ref.id==="101:7")?.admission.value,"paused");
  }else {
    assert.equal(state.view?.work.find(w=>w.issue_ref.id==="101:7")?.admission.value,"paused");
    const repository=[...state.source_slots.values()].find(s=>s.observation.resource.kind==="repository" && s.observation.resource.id==="101");
    assert.equal(repository?.stale,true);
  }
});
