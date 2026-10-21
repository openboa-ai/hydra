import assert from "node:assert/strict";
import {spawnSync} from "node:child_process";
import {fileURLToPath} from "node:url";
import test from "node:test";
import {MAX_PROJECTION_BYTES,parseProjection,type ProjectionV3} from "../src/projection.ts";
import {projectionState,reduceProjection,type ProjectionState} from "../src/projection-state.ts";
const emitter=fileURLToPath(new URL("../../../tests/fixtures/control-v3/emit_wire.py",import.meta.url));
const result=spawnSync("python3",["-I",emitter],{encoding:"utf8",timeout:60000,maxBuffer:4194304});
assert.equal(result.status,0);
const vectors=JSON.parse(result.stdout) as {accepted:boolean;profile:string;wire:string}[];
const base=parseProjection(vectors.find(v=>v.accepted && v.profile==="projection")!.wire);
const id=(n:number)=>"00000000-0000-4000-8000-"+n.toString(16).padStart(12,"0");
function read(state:ProjectionState,n:number,frame=structuredClone(base)) {
  frame.request_id=id(n+10);
  state=reduceProjection(state,{type:"read_started",scope:"overview",sequence:n,request_id:frame.request_id});
  return reduceProjection(state,{type:"read_succeeded",scope:"overview",sequence:n,now:n*1000,
    response:{payload:JSON.stringify(frame),age_ms:0,cached:false,stale:false,sequence:n}});
}
for (const failedRefresh of [false,true]) test(`numeric repository resolution replaces a ${failedRefresh ? "failed-refresh" : "local-only"} placeholder`,()=>{
  const code="from pathlib import Path\nimport sys,json\nroot=Path.cwd().parents[1]\nsys.path[:0]=[str(root),str(root/'tests')]\nfrom test_projection_read import ReadFixture\nfirst=ReadFixture(fail=lambda _: RuntimeError('fixture unavailable')).read() if " + (failedRefresh ? "True" : "False") + " else ReadFixture().read(refresh=False)\nprint(json.dumps([first,ReadFixture().read()]))\n";
  const r=spawnSync("python3",["-I","-c",code],{encoding:"utf8",timeout:60000,maxBuffer:4194304});
  assert.equal(r.status,0,r.stderr);
  const [initial,resolved]=(JSON.parse(r.stdout) as ProjectionV3[]).map(parseProjection);
  assert.ok(initial && resolved);
  let s=read(projectionState(initial.binding_epoch),1,initial);
  const alias=s.view!.projects.find(p=>p.repository_ref.id==="requested:example/alpha")!.repository_ref;
  s=reduceProjection(s,{type:"selection_changed",selected_ref:alias});
  s=read(s,2,resolved);
  assert.deepEqual(s.view!.projects.map(p=>p.repository_ref.id).sort(),["101","102"],
    "A successfully resolved repository remained beside its requested alias");
  assert.equal(s.selected_ref!.id,"101");
  assert.equal(s.view!.projects.find(p=>p.repository_ref.id==="101")!.admission.value,"paused");
  assert.equal(s.view!.projects.find(p=>p.repository_ref.id==="101")!.execution.value,null);
  parseProjection(s.view);
});
test("actual continuation pages keep retained work reachable within the per-project bound",()=>{
  const code="from pathlib import Path\nimport sys,json\nroot=Path.cwd().parents[1]\nsys.path[:0]=[str(root),str(root/'tests')]\nfrom test_projection_read import ReadFixture,issue\nsets=[]\nfor total in (120,150):\n rows={('example/alpha','open',False):[issue(n) for n in range(1,total+1)]}\n fail=(lambda path: RuntimeError('fixture unavailable') if '/issues?' in path and 'page=2' in path else None) if total==120 else None\n first=ReadFixture(rows,fail=fail).read(repository='example/alpha')\n second=ReadFixture(rows).read(repository='example/alpha',cursor=first['projects'][0]['coverage']['next_cursor'])\n assert second['projects'][0]['coverage']['next_cursor'] is None\n sets.append([first,second])\nprint(json.dumps(sets))\n";
  const r=spawnSync("python3",["-I","-c",code],{encoding:"utf8",timeout:60000,maxBuffer:4194304});
  assert.equal(r.status,0,r.stderr);
  const sets=(JSON.parse(r.stdout) as ProjectionV3[][]).map(frames=>frames.map(parseProjection));
  assert.deepEqual(sets.map(frames=>frames.map(f=>f.work.length)),[[100,20],[128,22]]);
  for (const [index,frames] of sets.entries()) {
  let s=read(projectionState(frames[0]!.binding_epoch),1);const seen=new Set<string>();
  for (const [n,frame] of frames.entries()) {
    s=read(s,n+2,frame);
    const project=s.view!.projects.find(p=>p.repository_ref.id==="101")!;
    const retained=s.view!.work.filter(w=>w.issue_ref.id.startsWith("101:"));
    assert.deepEqual(project.work_refs.map(r=>r.id).sort(),retained.map(w=>w.issue_ref.id).sort(),
      "Project navigation omitted retained work from an earlier continuation page");
    assert.ok(project.work_refs.length<=128,"The renderer exceeded the accepted per-project wire bound");
    for (const w of frame.work) {
      assert.ok(retained.some(r=>r.issue_ref.id===w.issue_ref.id),"A new whole work record disappeared");
      seen.add(w.issue_ref.id);
    }
    assert.ok(s.view!.projects.some(p=>p.repository_ref.id==="102"),"Project-page rotation discarded a different project");
    assert.equal(project.coverage.next_cursor,frame.projects[0]!.coverage.next_cursor);
    assert.equal(project.coverage.state,"partial","A continuation slice cannot certify whole-source coverage");
    assert.ok(retained.every(w=>w.cleanup.value===null));
    parseProjection(s.view);
  }
  assert.equal(seen.size,index===0 ? 120 : 150);
  assert.equal(s.view!.work.filter(w=>w.issue_ref.id.startsWith("101:")).length,index===0 ? 120 : 22);
  }
});
test("actual producer continuation remains traversable when merged pages exceed the renderer budget",()=>{
  const code="from pathlib import Path\nimport sys,json\nroot=Path.cwd().parents[1]\nsys.path[:0]=[str(root),str(root/'tests')]\nfrom test_projection_read import ReadFixture,issue\nrows={('example/alpha','open',False):[issue(n,'🚀'*5000) for n in range(1,151)]}\nframes=[]\ncursor=None\nfor _ in range(8):\n frame=ReadFixture(rows).read(repository='example/alpha',cursor=cursor)\n frames.append(frame)\n cursor=frame['projects'][0]['coverage']['next_cursor']\n if cursor is None: break\nassert cursor is None\nprint(json.dumps(frames,ensure_ascii=False))\n";
  const r=spawnSync("python3",["-I","-c",code],{encoding:"utf8",timeout:60000,maxBuffer:8388608});
  assert.equal(r.status,0,r.stderr);
  const frames=(JSON.parse(r.stdout) as ProjectionV3[]).map(parseProjection);
  assert.ok(frames.length>1);
  let s=projectionState(frames[0]!.binding_epoch);const seen=new Set<string>();
  for (const [n,frame] of frames.entries()) {
    s=read(s,n+1,frame);
    assert.ok(s.view,"A valid incoming continuation disappeared under aggregate pressure");
    assert.ok(new TextEncoder().encode(JSON.stringify(s.view)).length<=MAX_PROJECTION_BYTES);
    const expected=frame.projects[0]!.coverage.next_cursor;
    assert.equal(s.view.projects.find(p=>p.repository_ref.id==="101")?.coverage.next_cursor,expected,
      "The reducer lost the actual cursor for the next unread record");
    for (const w of frame.work) {
      assert.ok(s.view.work.some(current=>current.issue_ref.id===w.issue_ref.id),"A newly read whole record was omitted");
      seen.add(w.issue_ref.id);
    }
    parseProjection(s.view);
  }
  assert.equal(seen.size,150);
});
test("a regressed admission source stales only its dependent facts while current GitHub remains visible",()=>{
  const first=structuredClone(base),admission=first.observations.find(o=>o.resource.kind==="admission")!;
  const revision=(frame:ProjectionV3,n:string)=>{
    const o=frame.observations.find(o=>o.key===admission.key)!;o.revision={kind:"monotonic",value:n};
    o.value!.revision=Number(n);
    const walk=(value:unknown):void=>{
      if (Array.isArray(value)) {for(const x of value)walk(x);return;}
      if (value && typeof value==="object") {
        const v=value as Record<string,unknown>;
        if(v.observation_key===admission.key)v.revision={kind:"monotonic",value:n};
        for(const x of Object.values(v))walk(x);
      }
    };walk(frame);
  };
  revision(first,"10");let s=read(projectionState(first.binding_epoch),1,first);
  const second=structuredClone(base);revision(second,"0");
  const issue=second.observations.find(o=>o.resource.kind==="issue")!;issue.value!.title="Current independent GitHub change";
  s=read(s,2,second);
  assert.equal(s.source_slots.get(admission.key)!.stale,true);
  assert.equal(s.source_slots.get(admission.key)!.observation.revision!.value,"10");
  assert.equal(s.view!.projects[0]!.admission.value,null);
  assert.equal(s.view!.observations.find(o=>o.key===issue.key)!.value!.title,"Current independent GitHub change");
  assert.equal(s.view!.work[0]!.readiness.value!.disposition,"propose");
});
test("a valid new runtime starts a fresh source generation and fences old pending reads",()=>{
  let s=read(projectionState(base.binding_epoch),1);
  s=reduceProjection(s,{type:"read_started",scope:"old-independent",sequence:2,request_id:id(12)});
  s=reduceProjection(s,{type:"command_started",request_id:id(90),effect_key:"pause:101",action:"admission_set",target:{kind:"repository",repository_id:101}});
  const changed=structuredClone(base);changed.runtime.code_digest="f".repeat(64);
  s=read(s,3,changed);
  assert.equal(s.view!.runtime.code_digest,"f".repeat(64));
  assert.equal(s.pending_commands.size,0);assert.equal(s.feedback.get(id(90))!.outcome,"unknown");
  const old=structuredClone(base);old.request_id=id(12);
  s=reduceProjection(s,{type:"read_succeeded",scope:"old-independent",sequence:2,now:4000,
    response:{payload:old,age_ms:0,cached:false,stale:false,sequence:2}});
  assert.equal(s.view!.runtime.code_digest,"f".repeat(64));
});
test("complete refresh prunes absent work and its source while partial refresh retains it",()=>{
  let s=read(projectionState(base.binding_epoch),1);
  const issue=s.view!.work[0]!.issue_ref;
  const key=s.view!.observations.find(o=>o.resource.kind==="issue" && o.resource.id===issue.id)!.key;
  const empty=structuredClone(base);empty.work=[];
  empty.observations=empty.observations.filter(o=>o.key!==key);
  for (const p of empty.projects) {p.work_refs=[];p.coverage={...p.coverage,state:"complete",reason:null,returned_count:0,total_count:0,next_cursor:null};}
  const partial=structuredClone(empty);
  partial.projects[0]!.coverage={...partial.projects[0]!.coverage,state:"partial",total_count:null,reason:"transport_failed"};
  s=read(s,2,partial);assert.equal(s.view!.work.length,1);
  s=read(s,3,empty);
  assert.equal(s.view!.work.length,0);assert.equal(s.source_slots.has(key),false);
});
test("display casing cannot duplicate a registered repository on a local-only poll",()=>{
  const initial=structuredClone(base);
  initial.observations.find(o=>o.resource.kind==="repository" && o.resource.id==="101")!.value!.full_name="Example/Alpha";
  let s=read(projectionState(base.binding_epoch),1,initial);
  const local=structuredClone(base);local.work=[];
  for (const o of local.observations) if (o.resource.source==="github") {
    o.value=null;o.observed_at=null;o.availability="unavailable";o.reason="not_requested";
    o.coverage={...o.coverage,state:"unavailable",returned_count:0,total_count:null,next_cursor:null,reason:"not_requested"};
  }
  local.projects[0]!.repository_ref={source:"github",kind:"repository",id:"requested:example/alpha"};
  for (const p of local.projects) p.work_refs=[];
  s=read(s,2,local);
  assert.deepEqual(s.view!.projects.map(p=>p.repository_ref.id).sort(),["101","102"]);
});
test("bounded command feedback cannot evict an otherwise valid producer prefix or its cursors",()=>{
  const frame=structuredClone(base),issue=frame.observations.find(o=>o.resource.kind==="issue")!;
  issue.value!.description_excerpt="";issue.value!.description_truncated=false;
  const bytes=()=>new TextEncoder().encode(JSON.stringify(frame)).length;
  for (let n=0;n<1024;n++) {
    frame.observations.push({key:"github:check:fixture:"+n,resource:{source:"github",kind:"check",id:"fixture:"+n},
      revision:null,observed_at:frame.assembled_at,last_attempt_at:frame.assembled_at,availability:"current",reason:null,
      coverage:{state:"complete",scope:"resource:fixture:"+n,returned_count:1,total_count:1,next_cursor:null,reason:null},
      value:{producer:null,name:"fixture",head:"a".repeat(40),status:"completed",conclusion:"success",
        url:"https://github.com/example/alpha/actions/runs/1?fixture="+"x".repeat(1800)}});
    if (bytes()>MAX_PROJECTION_BYTES) {frame.observations.pop();break;}
  }
  const padding=MAX_PROJECTION_BYTES-bytes()-128;
  assert.ok(padding>=0 && padding<=4096);issue.value!.description_excerpt="x".repeat(padding);
  parseProjection(frame);assert.ok(bytes()<=MAX_PROJECTION_BYTES);
  const reply=JSON.parse(vectors.find(v=>v.accepted && v.profile==="standard")!.wire);
  let s=read(projectionState(base.binding_epoch),1,frame);
  const count=s.view!.work.length,cursor=s.view!.page.next_cursor;
  s=reduceProjection(s,{type:"command_started",request_id:reply.request.request_id,effect_key:"e".repeat(512),action:reply.request.action,target:reply.request.target});
  s=reduceProjection(s,{type:"command_result",request_id:reply.request.request_id,reply});
  assert.equal(s.feedback.get(reply.request.request_id)!.outcome,"applied");
  assert.equal(s.view!.work.length,count,"Command feedback silently evicted valid source work");
  assert.equal(s.view!.page.next_cursor,cursor);
});

test("capacity pressure from a failed read retains known work and independent source scope",()=>{
  const frame=structuredClone(base);
  const bytes=()=>new TextEncoder().encode(JSON.stringify(frame)).length;
  for(let n=0;n<1024;n++) {
    frame.observations.push({key:"github:optional-check:"+n,resource:{source:"github",kind:"check",id:"optional:"+n},
      revision:null,observed_at:frame.assembled_at,last_attempt_at:frame.assembled_at,availability:"current",reason:null,
      coverage:{state:"complete",scope:"optional:"+n,returned_count:1,total_count:1,next_cursor:null,reason:null},
      value:{producer:null,name:"fixture",head:"a".repeat(40),status:"completed",conclusion:"success",
        url:"https://github.com/example/alpha/actions/runs/1?fixture="+"x".repeat(1800)}});
    if(bytes()>MAX_PROJECTION_BYTES-128) {frame.observations.pop();break;}
  }
  parseProjection(frame);
  let s=read(projectionState(frame.binding_epoch),1,frame);
  const ids=s.view!.work.map(w=>w.issue_ref.id);
  const cursor=s.view!.page.next_cursor;
  s=reduceProjection(s,{type:"read_started",scope:"overview",sequence:2,request_id:id(12)});
  s=reduceProjection(s,{type:"read_failed",scope:"overview",sequence:2,reason:"transport_failed"});
  assert.ok(s.view,"A bounded read failure erased all known work");
  assert.deepEqual(s.view.work.map(w=>w.issue_ref.id),ids);
  assert.equal(s.view.page.next_cursor,cursor);
  assert.ok(new TextEncoder().encode(JSON.stringify(s.view)).length<=MAX_PROJECTION_BYTES);
  parseProjection(s.view);
});
