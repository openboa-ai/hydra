import assert from "node:assert/strict";
import {fileURLToPath} from "node:url";
import {spawnSync} from "node:child_process";
import test from "node:test";
import {parseProjection,parseStandardReply} from "../src/projection.ts";
test("unpaired actions cannot self-assert an applied outcome",()=>{
  const script=fileURLToPath(new URL("../../../tests/fixtures/control-v3/emit_unqualified_command_actions.py",import.meta.url));
  const output=spawnSync("python3",["-I",script],{encoding:"utf8",timeout:60000,maxBuffer:4194304});
  assert.equal(output.status,0,output.stderr);const rows=JSON.parse(output.stdout);assert.equal(rows.length,12);
  for(const row of rows){const parse=row.profile==="standard"?parseStandardReply:parseProjection;
    if(row.accepted)assert.doesNotThrow(()=>parse(row.wire),row.name);else assert.throws(()=>parse(row.wire),row.name);}
});
