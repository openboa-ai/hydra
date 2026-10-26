import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import {parseStandardReply, ProjectionError} from "../src/projection.ts";
import {projectionState, reduceProjection} from "../src/projection-state.ts";

type Row = {name:string;wire:string;schema_accepted:boolean;standard_reason:string|null};
const fixture=JSON.parse(readFileSync(new URL(
  "../../../tests/fixtures/control-v3/delegated-source-receipts.json",import.meta.url),"utf8"));
const rows=fixture.cases as Row[];
const ATTEMPT="11111111-1111-4111-8111-111111111111";
const EPOCH="99999999-9999-4999-8999-999999999999";
const PRIVATE="SYNTHETIC_PRIVATE_HANDOFF_MUST_NOT_BE_TRAVERSED";

test("delegated consumers use all independently frozen actual-wire cases",()=>{
  assert.equal(rows.length,41);
  assert.equal(rows.length,fixture.vectors.length);
  for (let i=0;i<rows.length;i++) {
    const row=rows[i]!, descriptor=fixture.vectors[i];
    for (const field of ["name","schema_accepted","standard_reason"] as const)
      assert.deepEqual(row[field],descriptor[field]);
    assert.equal(typeof row.wire,"string");
  }
});

for (const row of rows) test("delegated source boundary: "+row.name,()=>{
  if (row.standard_reason===null) assert.doesNotThrow(()=>parseStandardReply(row.wire));
  else assert.throws(()=>parseStandardReply(row.wire),(error:unknown)=>
    error instanceof ProjectionError && error.reason===row.standard_reason);
});

function actual(name:string) {
  const row=rows.find(row=>row.name===name);
  assert.ok(row,"Missing fixed actual producer case");
  // Source parser tests above use the identical saved bytes. This isolated UI
  // correlation harness gives the nullable producer envelope a UI binding epoch.
  const reply=JSON.parse(row.wire);
  reply.binding_epoch=EPOCH;
  return reply;
}

function decision(operation="decision_submit", attempt=ATTEMPT, round=1) {
  const reply=actual("decision_actual"), result=reply.request;
  const state=reduceProjection(projectionState(EPOCH),{type:"command_started",
    request_id:result.request_id,action:"workflow_step",target:result.target,
    effect_key:"decision:"+attempt+":"+round,assignment:null,
    parameters:{operation,source_attempt:attempt,round,public_text:PRIVATE,
      basis:{untrusted_private_summary:PRIVATE}}});
  return {reply,result,state};
}

test("decision_submit correlates only the exact tagged source attempt and round",()=>{
  const {reply,result,state:pending}=decision();
  const captured=pending.pending_commands.get(result.request_id)!;
  assert.deepEqual(captured.parameters,{operation:"decision_submit",source_attempt:ATTEMPT,round:1});
  assert.ok(!JSON.stringify(captured).includes(PRIVATE));
  const state=reduceProjection(pending,{type:"command_result",request_id:result.request_id,reply});
  assert.equal(state.feedback.get(result.request_id)?.outcome,"applied");
  assert.equal((state.feedback.get(result.request_id)?.receipt as Record<string,unknown>).profile,"codex_delegated_v1");
  assert.equal(state.view,null);
  assert.equal(state.source_slots.size,0,"Command feedback invented source observations");
});

test("decision submission cannot settle a different attempt, round or old apply operation",()=>{
  for (const [operation,attempt,round] of [
    ["decision_submit","33333333-3333-4333-8333-333333333333",1],
    ["decision_submit",ATTEMPT,2],
    ["decision_apply",ATTEMPT,1],
  ] as const) {
    const {reply,result,state:pending}=decision(operation,attempt,round);
    const state=reduceProjection(pending,{type:"command_result",request_id:result.request_id,reply});
    assert.equal(state.feedback.get(result.request_id)?.outcome,"unknown",operation+":"+round);
    assert.equal(state.feedback.get(result.request_id)?.receipt,null);
    assert.equal(state.view,null);
  }
});

test("continuation preserves its submitted pin while verifying changed actual post-state",()=>{
  const reply=actual("continuation_terminal_actual"), result=reply.request;
  const pin={attempt_id:ATTEMPT,head:null,contract_revision:"b".repeat(40),phase:"checkpoint"};
  const original=structuredClone(pin);
  let state=reduceProjection(projectionState(EPOCH),{type:"command_started",request_id:result.request_id,
    action:"workflow_step",target:result.target,effect_key:null,assignment:null,
    parameters:{operation:"continue",progress:pin,private_summary:PRIVATE}});
  pin.attempt_id="33333333-3333-4333-8333-333333333333";
  assert.deepEqual(state.pending_commands.get(result.request_id)?.parameters,
    {operation:"continue",progress:original});
  assert.notEqual(result.receipt.attempt_id,original.attempt_id);
  assert.notEqual(result.receipt.head,original.head);
  state=reduceProjection(state,{type:"command_result",request_id:result.request_id,reply});
  assert.equal(state.feedback.get(result.request_id)?.outcome,"applied");
  assert.deepEqual(state.feedback.get(result.request_id)?.parameters?.progress,original);
  assert.equal(state.view,null);
});

test("private handoff is rejected before property traversal or copying",()=>{
  const reply=actual("decision_actual");
  let reads=0;
  Object.defineProperty(reply,"handoff",{enumerable:true,get(){reads++;throw new Error(PRIVATE);}});
  assert.throws(()=>parseStandardReply(reply),(error:unknown)=>
    error instanceof ProjectionError && error.reason==="unsupported_reply_profile");
  assert.equal(reads,0);
});
