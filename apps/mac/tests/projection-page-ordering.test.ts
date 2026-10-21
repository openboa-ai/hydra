import assert from "node:assert/strict";
import {spawnSync} from "node:child_process";
import test from "node:test";
import {parseProjection} from "../src/projection.ts";
import {projectionState,reduceProjection} from "../src/projection-state.ts";

function frames(){
  const code="from pathlib import Path;import sys,json;root=Path.cwd().parents[1];sys.path[:0]=[str(root),str(root/'tests')];from test_projection_read import ReadFixture;from hydra_sdlc import projection as p;f=ReadFixture();print(json.dumps([json.loads(p.encode(f.read())),json.loads(p.encode(f.read(refresh=False)))]))";
  const result=spawnSync("python3",["-I","-c",code],{encoding:"utf8",timeout:60000,maxBuffer:4194304});
  assert.equal(result.status,0,"Actual Python frames failed: "+result.stderr);
  return JSON.parse(result.stdout).map(parseProjection);
}
function sequence(){
  const [remote,local]=frames();let state=projectionState(remote.binding_epoch);
  const first=structuredClone(remote),last=structuredClone(remote);
  first.page={state:"partial",scope:"registered-projects;overview",returned_count:2,total_count:null,next_cursor:"cursor-A",reason:"project_bound"};
  last.page={state:"complete",scope:"registered-projects;overview:from:819",returned_count:2,total_count:2,next_cursor:null,reason:null};
  function read(payload:typeof remote,issued:number,received:number,scope:string,cached=false){
    const frame=structuredClone(payload);frame.request_id="00000000-0000-4000-8000-"+issued.toString(16).padStart(12,"0");
    state=reduceProjection(state,{type:"read_started",scope,sequence:issued,request_id:frame.request_id});
    state=reduceProjection(state,{type:"read_succeeded",scope,sequence:issued,now:issued*1000,
      response:{payload:frame,age_ms:cached?1000:0,cached,stale:false,sequence:received,read_context:{scope:"fixture:read",sequence:1}}});
    assert.equal(state.error,null);
  }
  return {first,last,local,read,get state(){return state;}};
}
test("older cached overview pages cannot resurrect a consumed continuation",()=>{
  const f=sequence();f.read(f.first,10,10,"remote:overview:");
  assert.equal(f.state.view!.page.next_cursor,"cursor-A");
  f.read(f.last,20,20,"remote:overview:cursor-A");
  assert.equal(f.state.view!.page.next_cursor,null);
  const terminal=structuredClone(f.state.view!.page);
  f.read(f.first,30,10,"remote:overview:",true);
  assert.deepEqual(f.state.view!.page,terminal);
  f.read(f.last,40,20,"remote:overview:cursor-A",true);
  assert.deepEqual(f.state.view!.page,terminal);
});
test("newer local payloads cannot suppress a fresh remote page",()=>{
  const f=sequence();f.read(f.first,10,10,"remote:overview:");
  f.read(f.local,20,100,"local");
  assert.equal(f.state.view!.page.next_cursor,"cursor-A");
  f.read(f.last,30,30,"remote:overview:cursor-A");
  assert.deepEqual(f.state.view!.page,f.last.page);
});
