import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {spawnSync} from "node:child_process";
import test from "node:test";
import {parseProjection,parseStandardReply} from "../src/projection.ts";
import {projectionState,reduceProjection,type ProjectionState} from "../src/projection-state.ts";
const data=JSON.parse(readFileSync(new URL("../../../tests/fixtures/control-v3/receipt-states.json",import.meta.url),"utf8"));
const frame=JSON.parse(readFileSync(new URL("../../../tests/fixtures/control-v3/inputs.json",import.meta.url),"utf8")).frame;
const id=(n:number)=>"00000000-0000-4000-8000-"+n.toString(16).padStart(12,"0");
const sample=(name:string)=>structuredClone(data.commands.find((c:{name:string})=>c.name===name));
for(const row of data.cases) test("CP8 receipt state "+row.name,()=>{
  const combined=structuredClone(frame);combined.request=JSON.parse(row.wire).request;
  if(row.accepted){parseStandardReply(row.wire);parseProjection(combined);}
  else{assert.throws(()=>parseStandardReply(row.wire));assert.throws(()=>parseProjection(combined));}
});
for(const row of data.commands) test("real typed tracking metadata "+row.name,()=>{
  const c=structuredClone(row);parseStandardReply(c.reply);
  let state=projectionState(frame.binding_epoch);
  assert.doesNotThrow(()=>{state=reduceProjection(state,c.event);});
  state=reduceProjection(state,{type:"command_result",request_id:c.event.request_id,reply:c.reply});
  assert.equal(state.feedback.get(c.event.request_id)?.outcome,"applied");
  assert.equal(state.view,null,"Command feedback invented source facts");
  assert.equal(JSON.stringify([...state.feedback.values()]).includes("PRIVATE_CORRELATION_CANARY"),false);
});
for(const changed of ["none","attempt_id","head","contract_revision","missing","null"])
test("continuation retains its ProgressPin "+changed,()=>{
  const c=sample("continue");
  if(changed==="missing")delete c.event.parameters.progress;
  else if(changed==="null")c.event.parameters.progress=null;
  else if(changed!=="none")c.reply.request.receipt[changed]=changed==="attempt_id"?id(899):"f".repeat(40);
  let state=projectionState(frame.binding_epoch);
  assert.doesNotThrow(()=>{state=reduceProjection(state,c.event);});
  if(changed!=="missing" && changed!=="null")
    assert.deepEqual(state.pending_commands.get(c.event.request_id)?.parameters?.progress,c.event.parameters.progress);
  state=reduceProjection(state,{type:"command_result",request_id:c.event.request_id,reply:c.reply});
  assert.equal(state.feedback.get(c.event.request_id)?.outcome,["none","null"].includes(changed)?"applied":"unknown");
});
test("continuation ProgressPin is a bounded snapshot",()=>{
  const c=sample("continue");let state=projectionState(frame.binding_epoch);
  assert.doesNotThrow(()=>{state=reduceProjection(state,c.event);});
  c.event.parameters.progress.head="f".repeat(40);
  state=reduceProjection(state,{type:"command_result",request_id:c.event.request_id,reply:c.reply});
  assert.equal(state.feedback.get(c.event.request_id)?.outcome,"applied");
  const large=sample("continue");large.event.parameters.progress.phase="x".repeat(5000);
  assert.throws(()=>reduceProjection(projectionState(frame.binding_epoch),large.event));
});
test("independent null-key commands do not collide; exact effect keys still do",()=>{
  const first=sample("admission"),second=sample("admission");
  second.event.request_id=id(991);second.event.target.repository_id=102;
  let state=projectionState(frame.binding_epoch);
  assert.doesNotThrow(()=>{state=reduceProjection(state,first.event);state=reduceProjection(state,second.event);});
  assert.equal(state.pending_commands.size,2);
  assert.throws(()=>reduceProjection(state,{...first.event,target:{kind:"repository",repository_id:103}}));
  const keyed=sample("checkpoint");state=reduceProjection(projectionState(frame.binding_epoch),keyed.event);
  assert.throws(()=>reduceProjection(state,{...keyed.event,request_id:id(992)}));
});
test("a failed progress read cannot retain a removed ordinary Issue",()=>{
  const code="from pathlib import Path\nimport sys,json\nroot=Path.cwd().parents[1]\nsys.path[:0]=[str(root),str(root/'tests')]\nfrom hydra_sdlc.github import ACTIVE_LABEL\nfrom test_projection_read import ReadFixture,issue\nmanaged=issue(7);managed['labels']=[ACTIVE_LABEL]\nframes=[]\nfor ordinary in ([managed,issue(8)],[managed]):\n rows={('example/alpha','open',True):[managed],('example/alpha','open',False):ordinary,('example/beta','open',False):[issue(4)]}\n frames.append(ReadFixture(rows,fail=lambda path:RuntimeError('fixture progress unavailable') if '/comments' in path else None).read())\nprint(json.dumps(frames))\n";
  const output=spawnSync("python3",["-I","-c",code],{encoding:"utf8",timeout:60000,maxBuffer:4194304});
  assert.equal(output.status,0,output.stderr);
  const frames=JSON.parse(output.stdout).map(parseProjection);
  let state=projectionState(frame.binding_epoch);
  for(let n=0;n<frames.length;n++){
    const value=frames[n];value.request_id=id(995+n);
    state=reduceProjection(state,{type:"read_started",scope:"overview",sequence:n+1,request_id:value.request_id});
    state=reduceProjection(state,{type:"read_succeeded",scope:"overview",sequence:n+1,now:1000*(n+1),
      response:{payload:value,age_ms:0,cached:false,stale:false,sequence:n+1,read_context:{scope:"fixture:read",sequence:1}}});
    if(n===0)assert.ok(state.view?.work.some(w=>w.issue_ref.id==="101:8"));
  }
  assert.deepEqual(state.view?.work.map(w=>w.issue_ref.id).sort(),["101:7","102:4"]);
  assert.equal(state.view?.projects.find(p=>p.repository_ref.id==="101")?.coverage.state,"complete");
  assert.equal(state.view?.work.find(w=>w.issue_ref.id==="101:7")?.stage.value,null);
});
