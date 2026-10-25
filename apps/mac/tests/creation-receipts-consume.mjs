// Test-only wire path: every checked Rust vector reaches the actual TS parser.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {parseStandardReply,ProjectionError} from "../src/projection.ts";
const bytes=readFileSync(0);assert.ok(bytes.length<=4_194_304);
const rows=JSON.parse(bytes.toString("utf8"));assert.ok(rows.length>0);
let checked=0;
for(const row of rows){
  let reason=null;
  try{parseStandardReply(row.wire);}catch(error){assert.ok(error instanceof ProjectionError);reason=error.reason;}
  assert.equal(reason,row.standard_reason,row.name);
  checked++;
}
process.stdout.write(JSON.stringify({checked}));
