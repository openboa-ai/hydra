import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {fileURLToPath} from "node:url";
import {spawnSync} from "node:child_process";
import test from "node:test";
import {parseProjection,parseStandardReply} from "../src/projection.ts";
import {projectionState,reduceProjection} from "../src/projection-state.ts";
const load=(name:string)=>JSON.parse(readFileSync(new URL("../../../tests/fixtures/control-v3/"+name,import.meta.url),"utf8"));
const input=load("inputs.json"),commands=load("receipt-states.json").commands;
const id=(n:number)=>"00000000-0000-4000-8000-"+n.toString(16).padStart(12,"0");

test("workflow progress targets and source proofs match the shared producer vectors",()=>{
  const script=fileURLToPath(new URL("../../../tests/fixtures/control-v3/emit_workflow_progress.py",import.meta.url));
  const output=spawnSync("python3",["-I",script],{encoding:"utf8",timeout:60000,maxBuffer:4194304});
  assert.equal(output.status,0,"Actual workflow fixture failed: "+output.stderr);
  const rows=JSON.parse(output.stdout);assert.equal(rows.length,134);
  for(const row of rows){const value=JSON.parse(row.wire),parse=row.profile==="projection"?parseProjection:parseStandardReply;
    if(row.accepted)assert.doesNotThrow(()=>parse(value),row.name);else assert.throws(()=>parse(value),row.name);}
});

function scenario(name:string){
  const command=structuredClone(commands.find((row:any)=>row.name===name));
  let state=projectionState(command.reply.binding_epoch);
  function read(reply:any|null,issued:number,received=issued,stale=false,alter?:(frame:any)=>void){
    const frame=structuredClone(input.frame);frame.runtime=structuredClone(command.reply.runtime);
    frame.binding_epoch=state.binding_epoch;frame.request_id=id(900+issued);frame.request=reply?.request??null;
    if(reply){const observations=new Map(frame.observations.map((o:any)=>[o.key,o]));
      for(const o of reply.observations)observations.set(o.key,structuredClone(o));frame.observations=[...observations.values()];}
    alter?.(frame);
    state=reduceProjection(state,{type:"read_started",scope:"overview",sequence:issued,request_id:frame.request_id});
    state=reduceProjection(state,{type:"read_succeeded",scope:"overview",sequence:issued,now:issued*1000,
      response:{payload:frame,age_ms:0,cached:received!==issued,stale,sequence:received,read_context:{scope:"fixture:read",sequence:1}}});
  }
  read(null,1);
  return {command,read,get state(){return state;},
    start(){state=reduceProjection(state,command.event);},
    result(reply:any){state=reduceProjection(state,{type:"command_result",request_id:command.event.request_id,reply});},
    binding(){state=reduceProjection(state,{type:"binding_changed",binding_epoch:id(800)});}};
}

test("matching read-backs resolve unknown feedback for every supported command kind",()=>{
  for(const row of commands){const f=scenario(row.name);f.start();f.result({});
    assert.equal(f.state.feedback.get(row.event.request_id)?.outcome,"unknown");
    f.read(f.command.reply,2);
    assert.equal(f.state.error,null,row.name);
    assert.equal(f.state.feedback.get(row.event.request_id)?.outcome,f.command.reply.request.outcome,row.name);
    if(row.event.effect_key && f.command.reply.request.outcome==="applied")
      assert.doesNotThrow(()=>reduceProjection(f.state,{...row.event,request_id:id(777)}),row.name);
  }
});

test("unrelated, stale or changed-context read-backs retain unknown effect ownership",()=>{
  for(const change of ["id","target","operation","candidate","runtime","binding","stale","older"]){
    const f=scenario("verify-run");f.start();f.result({});let reply=structuredClone(f.command.reply);
    if(change==="id")reply.request.request_id=id(123);
    if(change==="target"){reply.request.target.issue_number=99;reply.request.receipt.progress_ref.id="101:99";}
    if(change==="operation")reply=structuredClone(commands.find((r:any)=>r.name==="continue").reply);
    if(change==="candidate")reply.request.receipt.candidate.head="c".repeat(40);
    if(change==="binding")f.binding();
    if(change==="older"){f.read(null,3);f.read(reply,4,2);}
    else f.read(reply,2,2,change==="stale",change==="runtime"?(frame:any)=>{frame.runtime.code_digest="c".repeat(64);}:undefined);
    assert.equal(f.state.feedback.get(f.command.event.request_id)?.outcome,"unknown",change);
  }
  const f=scenario("checkpoint");f.start();f.result(f.command.reply);
  const old=structuredClone(f.state.feedback.get(f.command.event.request_id));
  const late=structuredClone(f.command.reply);Object.assign(late.request,{outcome:"unknown",reason:"provider_wait",receipt:null,required_next:"reconcile"});
  f.read(late,2);assert.deepEqual(f.state.feedback.get(f.command.event.request_id),old);
});

test("a later exact terminal result resolves waiting publication feedback",()=>{
  const f=scenario("publication");f.start();const waiting=structuredClone(f.command.reply);
  waiting.request.outcome="waiting";waiting.request.required_next="reconcile";
  waiting.request.receipt.stage="branch_published";waiting.request.receipt.pr_ref=null;
  f.result(waiting);assert.equal(f.state.feedback.get(f.command.event.request_id)?.outcome,"waiting");
  f.read(f.command.reply,2);assert.equal(f.state.feedback.get(f.command.event.request_id)?.outcome,"applied");
});

test("an exact read-back can settle an in-flight command before a lost primary reply",()=>{
  const f=scenario("checkpoint");f.start();f.read(f.command.reply,2);
  assert.equal(f.state.pending_commands.size,0);
  assert.equal(f.state.feedback.get(f.command.event.request_id)?.outcome,"applied");
  const settled=structuredClone(f.state.feedback.get(f.command.event.request_id));
  f.result({});assert.deepEqual(f.state.feedback.get(f.command.event.request_id),settled);
});
