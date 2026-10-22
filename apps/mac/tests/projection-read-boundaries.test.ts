import assert from "node:assert/strict";
import {spawnSync} from "node:child_process";
import test from "node:test";
import {parseProjection,type ProjectionV3} from "../src/projection.ts";
import {projectionState,reduceProjection} from "../src/projection-state.ts";
function vectors(){
  const result=spawnSync("python3",["-I","../../tests/fixtures/control-v3/emit_read_page_counts.py"],
    {encoding:"utf8",timeout:60000,maxBuffer:4194304});
  assert.equal(result.status,0,"Actual read producer failed: "+result.stderr);
  return JSON.parse(result.stdout) as {name:string;accepted:boolean;wire:string}[];
}
test("wire page counts describe exactly the projects in that response",()=>{
  for(const value of vectors()){
    if(value.accepted)assert.doesNotThrow(()=>parseProjection(value.wire),value.name);
    else assert.throws(()=>parseProjection(value.wire),value.name);
  }
});
function stream(){
  const frame=parseProjection(vectors()[0]!.wire);let state=projectionState(frame.binding_epoch);
  function read(payload:ProjectionV3,issued:number,received=issued,cached=false,scope="remote:overview:"){
    const f=structuredClone(payload);f.request_id="00000000-0000-4000-8000-"+issued.toString(16).padStart(12,"0");
    state=reduceProjection(state,{type:"read_started",scope,sequence:issued,request_id:f.request_id});
    state=reduceProjection(state,{type:"read_succeeded",scope,sequence:issued,now:issued*1000,
      response:{payload:f,age_ms:cached?1000:0,cached,stale:false,sequence:received,
        read_context:{scope:"fixture:read",sequence:1}}});
    assert.equal(state.error,null);return f;
  }
  return {frame,read,get state(){return state;}};
}
test("newer capability snapshots survive older cross-scope cache responses in both directions",()=>{
  for(const withdrawal of [true,false]){
    const f=stream(),available=structuredClone(f.frame),unavailable=structuredClone(f.frame);
    available.capabilities=[{source:"hydra",operation:"admission_set",state:"available",actor:"core",qualification_ref:"fixture:qualified",reason:null}];
    unavailable.capabilities=[{source:"hydra",operation:"admission_set",state:"unavailable",actor:"core",qualification_ref:null,reason:"source_unavailable"}];
    const first=withdrawal?available:unavailable,last=withdrawal?unavailable:available;
    f.read(first,10);const current=f.read(last,20);
    f.read(first,30,10,true,"remote:example/alpha:");
    assert.deepEqual(f.state.view!.capabilities,last.capabilities,"An old cache rewrote current capabilities");
    assert.equal(f.state.view!.request_id,current.request_id,"An old cache rewrote the snapshot header");
    f.read(first,40);assert.deepEqual(f.state.view!.capabilities,first.capabilities,"A fresh observation could not change capability state");
    const restarted=structuredClone(last);restarted.runtime.code_digest="f".repeat(64);
    f.read(restarted,50);assert.deepEqual(f.state.view!.capabilities,last.capabilities);
    f.read(first,60,40,true,"remote:example/alpha:");
    assert.deepEqual(f.state.view!.capabilities,last.capabilities,"An older runtime restored its capabilities");
  }
});
test("valid individual pages merge without rewriting their source page metadata",()=>{
  const f=stream(),first=structuredClone(f.frame),last=structuredClone(f.frame);
  first.projects=first.projects.slice(0,1);last.projects=last.projects.slice(1);
  first.work=first.work.filter(w=>w.issue_ref.id.startsWith(first.projects[0]!.repository_ref.id+":"));
  last.work=last.work.filter(w=>w.issue_ref.id.startsWith(last.projects[0]!.repository_ref.id+":"));
  first.page={state:"partial",scope:"registered-projects;overview",returned_count:1,total_count:null,next_cursor:"next-page",reason:"project_bound"};
  last.page={state:"complete",scope:"registered-projects;overview:from:1",returned_count:1,total_count:1,next_cursor:null,reason:null};
  f.read(first,10);f.read(last,20);
  assert.equal(f.state.view!.projects.length,2,"A valid page discarded independent project membership");
  assert.deepEqual(f.state.view!.page,last.page,"The renderer manufactured new source page counts");
});

test("whole-page memory rotation preserves newer capability and continuation snapshots",()=>{
  const f=stream();
  function bulk(start:number){
    const frame=structuredClone(f.frame),seed=structuredClone(frame.projects[0]!);
    seed.goal_refs=[];seed.work_refs=[];seed.attention_refs=[];seed.source_refs=[];
    seed.coverage={...seed.coverage,returned_count:0,total_count:seed.coverage.state==="complete"?0:null};
    seed.admission={value:null,reason:"source_unavailable",evidence:[]};
    seed.execution={value:null,reason:"source_unavailable",evidence:[]};
    frame.projects=Array.from({length:600},(_,index)=>({...structuredClone(seed),
      repository_ref:{source:"github" as const,kind:"repository",id:String(start+index)}}));
    frame.work=[];frame.relations=[];
    frame.page={state:"partial",scope:"registered-projects;overview",returned_count:600,total_count:null,next_cursor:null,reason:"source_coverage_incomplete"};
    return frame;
  }
  const current=bulk(2000),old=bulk(3000);
  current.capabilities=[{source:"hydra",operation:"admission_set",state:"unavailable",actor:"core",qualification_ref:null,reason:"source_unavailable"}];
  old.capabilities=[{source:"hydra",operation:"admission_set",state:"available",actor:"core",qualification_ref:"fixture:qualified",reason:null}];
  old.page.scope="registered-projects;overview:from:3000";old.page.next_cursor="obsolete-next";
  const latest=f.read(current,20);f.read(old,30,10,true,"remote:overview:older-window");
  assert.ok(f.state.view);assert.ok(f.state.view.projects.length<=1024);
  assert.deepEqual(f.state.view.capabilities,current.capabilities,"Memory rotation restored old capabilities");
  assert.equal(f.state.view.request_id,latest.request_id,"Memory rotation restored an old snapshot header");
  assert.deepEqual(f.state.view.page,current.page,"Memory rotation restored an obsolete continuation");
});
