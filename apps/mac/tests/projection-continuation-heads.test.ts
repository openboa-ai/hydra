import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import {parseStandardReply, ProjectionError} from "../src/projection.ts";
import {projectionState, reduceProjection} from "../src/projection-state.ts";

const rows=JSON.parse(readFileSync(new URL("../../../tests/fixtures/control-v3/continuation-heads.json",import.meta.url),"utf8")).cases;
const matrix=JSON.parse(readFileSync(new URL("../../../tests/fixtures/control-v3/receipt-states.json",import.meta.url),"utf8"));
for (const row of rows) test("CP11 continuation head: "+row.name,()=>{
  assert.throws(()=>parseStandardReply(row.reply),(error:unknown)=>
    error instanceof ProjectionError && error.reason===
      (row.schema_accepted?"unsupported_receipt_source":"invalid_response"));
});
test("nullable continuation preconditions remain unchanged when an unsupported result arrives",()=>{
  const sample=structuredClone(matrix.commands.find((row:{name:string})=>row.name==="continue"));
  sample.event.parameters.progress.head=null;
  const expected=structuredClone(sample.event.parameters.progress);
  let state=reduceProjection(projectionState(sample.reply.binding_epoch),sample.event);
  sample.event.parameters.progress.head="f".repeat(40);
  assert.deepEqual(state.pending_commands.get(sample.event.request_id)?.parameters?.progress,expected);
  state=reduceProjection(state,{type:"command_result",request_id:sample.event.request_id,reply:rows[1].reply});
  assert.equal(state.feedback.get(sample.event.request_id)?.outcome,"unknown");
  assert.equal(state.feedback.get(sample.event.request_id)?.receipt,null);
});
