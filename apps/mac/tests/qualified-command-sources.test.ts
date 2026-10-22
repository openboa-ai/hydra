import assert from "node:assert/strict";
import {fileURLToPath} from "node:url";
import {spawnSync} from "node:child_process";
import test from "node:test";
import {parseProjection,parseStandardReply} from "../src/projection.ts";
import {projectionState,reduceProjection} from "../src/projection-state.ts";
const script=fileURLToPath(new URL("../../../tests/fixtures/control-v3/emit_qualified_command_sources.py",import.meta.url));
const output=spawnSync("python3",["-I",script],{encoding:"utf8",timeout:60000,maxBuffer:4194304});
assert.equal(output.status,0,output.stderr);
const rows=JSON.parse(output.stdout);

test("qualified command source profiles agree with actual checkpoint wire oracles",()=>{
  assert.equal(rows.length,76);
  for(const row of rows){const parse=row.profile==="standard"?parseStandardReply:parseProjection;
    if(row.accepted)assert.doesNotThrow(()=>parse(row.wire),row.name);else assert.throws(()=>parse(row.wire),row.name);}
});

test("a mismatched checkpoint read-back cannot settle an exact command as applied",()=>{
  for(const row of rows.filter((r:any)=>r.profile==="standard" && r.name.startsWith("checkpoint:"))){
    const reply=JSON.parse(row.wire),r=reply.request;
    let state=reduceProjection(projectionState(reply.binding_epoch),{type:"command_started",request_id:r.request_id,
      effect_key:"checkpoint:"+r.receipt.assignment.attempt_id+":"+r.receipt.assignment.step_id,
      action:"workflow_step",target:r.target,assignment:r.receipt.assignment,
      parameters:{operation:"checkpoint_only",outcome:r.receipt.outcome}});
    state=reduceProjection(state,{type:"command_result",request_id:r.request_id,reply});
    assert.equal(state.feedback.get(r.request_id)?.outcome,row.accepted?"applied":"unknown",row.name);
    if(!row.accepted)assert.equal(state.feedback.get(r.request_id)?.receipt,null,row.name);
    assert.equal(state.view,null,"Command feedback invented source facts");
  }
});
