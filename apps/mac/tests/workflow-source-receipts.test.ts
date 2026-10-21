import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {fileURLToPath} from "node:url";
import {spawnSync} from "node:child_process";
import test from "node:test";
import {parseProjection,parseStandardReply} from "../src/projection.ts";
import {projectionState,reduceProjection} from "../src/projection-state.ts";
const script=fileURLToPath(new URL("../../../tests/fixtures/control-v3/emit_workflow_source_receipts.py",import.meta.url));
const output=spawnSync("python3",["-I",script],{encoding:"utf8",timeout:60000,maxBuffer:4194304});
assert.equal(output.status,0,output.stderr);
const rows=JSON.parse(output.stdout);
const commands=JSON.parse(readFileSync(new URL("../../../tests/fixtures/control-v3/receipt-states.json",import.meta.url),"utf8")).commands;

test("workflow source receipt decoders share exact PR and invocation evidence oracles",()=>{
  assert.equal(rows.length,82);
  for(const row of rows){const parse=row.profile==="standard"?parseStandardReply:parseProjection;
    if(row.accepted)assert.doesNotThrow(()=>parse(row.wire),row.name);else assert.throws(()=>parse(row.wire),row.name);}
});

test("unproven invocation and foreign PR replies cannot become applied command feedback",()=>{
  for(const row of rows.filter((r:any)=>r.profile==="standard")){
    const command=structuredClone(commands.find((c:any)=>c.name===row.command));
    if(row.name.endsWith(":maximum"))command.event.parameters.pr_number=9007199254740991;
    let state=reduceProjection(projectionState(command.reply.binding_epoch),command.event);
    const reply=JSON.parse(row.wire);
    state=reduceProjection(state,{type:"command_result",request_id:command.event.request_id,reply});
    assert.equal(state.feedback.get(command.event.request_id)?.outcome,row.accepted?reply.request.outcome:"unknown",row.name);
    if(!row.accepted)assert.equal(state.feedback.get(command.event.request_id)?.receipt,null,row.name);
    assert.equal(state.view,null,"Receipt manufactured current facts");
  }
});
