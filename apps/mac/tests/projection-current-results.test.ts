import assert from "node:assert/strict";
import {spawnSync} from "node:child_process";
import test from "node:test";
import {parseProjection} from "../src/projection.ts";
import {projectionState,reduceProjection} from "../src/projection-state.ts";
function fixtures(){
  const script="from pathlib import Path;import sys,json;root=Path.cwd().parents[1];sys.path[:0]=[str(root),str(root/'tests')];from test_projection_context_budgets import request_frames;print(json.dumps(request_frames()))";
  const result=spawnSync("python3",["-I","-c",script],{encoding:"utf8",timeout:60000,maxBuffer:4194304});
  assert.equal(result.status,0,"Actual producer fixture failed: "+result.stderr);return JSON.parse(result.stdout);
}
test("same-runtime frames replace embedded results without losing separate feedback history",()=>{
  const {frames,replies}=fixtures();let state=projectionState(frames[0].binding_epoch);
  const read=(index:number)=>{
    const frame=parseProjection(frames[index]);const sequence=index+1;
    state=reduceProjection(state,{type:"read_started",scope:"remote:overview:",sequence,request_id:frame.request_id});
    state=reduceProjection(state,{type:"read_succeeded",scope:"remote:overview:",sequence,now:sequence*1000,
      response:{payload:frame,age_ms:0,cached:false,stale:false,sequence,read_context:{scope:"fixture:read",sequence:1}}});
    assert.deepEqual(state.view!.request,frame.request,"The retained view exposed a different frame's result");
    assert.equal(state.view!.request_id,frame.request_id);
  };
  read(0);const reply=replies[0];
  state=reduceProjection(state,{type:"command_started",request_id:reply.request.request_id,effect_key:null,
    action:"admission_set",target:reply.request.target,parameters:{mode:"paused"}});
  state=reduceProjection(state,{type:"command_result",request_id:reply.request.request_id,reply});
  const feedback=structuredClone(state.feedback.get(reply.request.request_id));assert.equal(feedback?.outcome,"applied");
  read(1);read(2);read(3);
  assert.notEqual(state.view!.request!.request_id,reply.request.request_id);
  assert.deepEqual(state.feedback.get(reply.request.request_id),feedback,"An ordinary poll erased intentional command history");
});

test("older cached scopes cannot restore cleared or superseded embedded command results",()=>{
  const {frames,replies}=fixtures();let state=projectionState(frames[0].binding_epoch);
  function read(index:number,issued:number,received:number,cached=false,scope="remote:overview:"){
    const frame=parseProjection(frames[index]);frame.request_id="00000000-0000-4000-8000-"+issued.toString(16).padStart(12,"0");
    state=reduceProjection(state,{type:"read_started",scope,sequence:issued,request_id:frame.request_id});
    state=reduceProjection(state,{type:"read_succeeded",scope,sequence:issued,now:issued*1000,
      response:{payload:frame,age_ms:cached?1000:0,cached,stale:false,sequence:received,read_context:{scope:"fixture:read",sequence:1}}});
  }
  read(1,10,10);const reply=replies[0];
  state=reduceProjection(state,{type:"command_started",request_id:reply.request.request_id,effect_key:null,
    action:"admission_set",target:reply.request.target,parameters:{mode:"paused"}});
  state=reduceProjection(state,{type:"command_result",request_id:reply.request.request_id,reply});
  const feedback=structuredClone(state.feedback.get(reply.request.request_id));assert.equal(feedback?.outcome,"applied");
  read(2,20,20);assert.equal(state.view!.request,null);
  read(1,30,10,true,"remote:example/alpha:");assert.equal(state.view!.request,null,"A cached scope restored an older applied receipt");
  read(3,40,40);assert.deepEqual(state.view!.request,frames[3].request);
  read(2,50,20,true,"remote:example/alpha:");assert.deepEqual(state.view!.request,frames[3].request,"An older null erased a newer result");
  read(1,60,10,true,"remote:example/alpha:");assert.deepEqual(state.view!.request,frames[3].request,"An older receipt replaced a different newer result");
  read(3,70,40,true,"remote:example/alpha:");assert.deepEqual(state.view!.request,frames[3].request);
  assert.deepEqual(state.feedback.get(reply.request.request_id),feedback);
});
