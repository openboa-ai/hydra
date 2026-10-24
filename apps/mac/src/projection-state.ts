/** Source ordering and display state. No event in this reducer sends an effect. */
import {
  MAX_PROJECTION_BYTES, ProjectionError, parseProjection, parseStandardReply, validateProjectionView,
  projectAdmissionMode,
  type CommandResult, type Fact, type Observation, type ProjectionV3, type ResourceRef, type Revision,
} from "./projection.ts";

type Slot = { latest_issued_seq: number; latest_settled_seq: number; observation: Observation;
  query_scope: string; received_at: number; stale: boolean; frame: string; received_sequence:number };
type Query = { sequence: number; request_id: string; keys: Set<string> };
type Command = { request_id: string; effect_key: string | null; action: string; target: Record<string, unknown>;
  operation?: "preserve" | "archive" | "retire" | "remove_schedule";
  parameters?: Record<string, unknown>; assignment?: Record<string, unknown> | null; repository_name?: string };
type CapturedCommand = Command & {command_binding_epoch:string;command_runtime_key:string|null};
type RetryWindow = { received_at: number; after_seconds: number; basis: "provider" | "fallback"; failures: Map<string, { count: number; frame: string }> };
type Feedback = CapturedCommand & { outcome: CommandResult["outcome"]; reason: string | null; receipt: unknown };
export interface ProjectionState {
  binding_epoch: string; source_slots: Map<string, Slot>; selected_ref: ResourceRef | null;
  pending_commands: Map<string, CapturedCommand>; feedback: Map<string, Feedback>;
  // Accumulated display records retain source page metadata; this is not a new wire frame.
  queries: Map<string, Query>; view: ProjectionV3 | null; runtime_key: string | null; runtime_sequence:number; page_sequence:number;
  read_context: {scope:string|null;sequence:number};
  retry_windows: Map<string, RetryWindow>; last_now: number; error: string | null;
}
export type ProjectionEvent =
  | { type: "read_started"; scope: string; sequence: number; request_id: string; observation_keys?: string[] }
  | { type: "read_succeeded"; scope: string; sequence: number; now: number;
      response: { payload: unknown; age_ms: number; cached: boolean; stale: boolean; sequence: number; read_context: {scope:string|null;sequence:number} } }
  | { type: "read_failed"; scope: string; sequence: number; reason: string }
  | ({ type: "command_started" } & Command)
  | { type: "command_result"; request_id: string; reply: unknown }
  | { type: "binding_changed"; binding_epoch: string }
  | { type: "clock_resumed"; now: number }
  | { type: "binding_unavailable"; now: number }
  | { type: "selection_changed"; selected_ref: ResourceRef | null };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const json = (value: unknown): string => {
  if (Array.isArray(value)) return "[" + value.map(json).join(",") + "]";
  if (value !== null && typeof value === "object") return "{" + Object.keys(value).sort().map(k =>
    JSON.stringify(k) + ":" + json((value as Record<string,unknown>)[k])).join(",") + "}";
  return JSON.stringify(value);
};
const size = (value: unknown) => new TextEncoder().encode(json(value)).length;
const key = (ref: ResourceRef) => json([ref.source, ref.kind, ref.id]);
const runtime = (view: Pick<ProjectionV3,"runtime">) => json([view.runtime.version, view.runtime.code_digest,
  view.runtime.config_digest, view.runtime.control_binding_digest]);
const unknown = (reason: string): Fact<never> => ({ value: null, evidence: [], reason });
function valid(condition: unknown): asserts condition { if (!condition) throw new ProjectionError(); }
function admissionReceipt(pending:Command,result:CommandResult,observations:Observation[],binding:unknown) {
  const desired=pending.parameters?.mode;
  valid(typeof desired==="string" && ["running","paused","stopped"].includes(desired));
  const receipt=result.receipt as {kind:string;readback:{observation_key:string}};
  valid(receipt.kind==="admission");
  const observation=observations.find(o=>o.key===receipt.readback.observation_key);
  valid(typeof binding==="string" && observation?.value && observation.resource.source==="hydra" &&
    observation.resource.kind==="admission" && observation.resource.id===binding);
  const value=observation.value;
  let actual=value.global_mode;
  if (pending.target.kind==="repository") {
    valid(pending.repository_name!==undefined);
    actual=projectAdmissionMode(value,pending.repository_name);
    if (desired==="running") valid(value.global_mode==="running");
  } else valid(pending.target.kind==="host");
  valid(actual===desired || desired==="paused" && actual==="stopped");
}
function workflowReceipt(pending:Command,result:CommandResult) {
  const p=pending.parameters,r=result.receipt as Record<string,unknown>;
  valid(p && typeof p.operation==="string");
  const kinds:Record<string,string>={checkpoint_only:"checkpoint",decision_apply:"decision",
    continue:"continuation",publish_candidate:"publication",deliver:"delivery"};
  const kind=p.operation==="verify_only" ? (p.stage==="run"?"verification":
    p.stage==="review_checkpoint"?"verification_review":undefined) :
    Object.hasOwn(kinds,p.operation)?kinds[p.operation]:undefined;
  valid(kind!==undefined && r.kind===kind);
  if (kind==="checkpoint" || kind==="verification_review")
    valid(pending.assignment!=null && json(r.assignment)===json(pending.assignment));
  else valid(pending.assignment===null);
  if (kind==="checkpoint") valid(r.outcome===p.outcome);
  if (kind==="verification_review" && result.outcome==="applied") {
    const outcomes:Record<string,string>={candidate_ready:"accepted",failed:"failed",needs_decision:"pending"};
    valid(typeof p.outcome==="string" && Object.hasOwn(outcomes,p.outcome) && r.review===outcomes[p.outcome]);
  }
  if (Object.hasOwn(r,"candidate")) valid(json(r.candidate)===json(p.candidate));
  if (kind==="decision") valid(r.source_attempt===p.source_attempt && r.round===p.round);
  if (kind==="continuation") {
    valid(Object.hasOwn(p,"progress"));
    const progress=p.progress;
    if (progress!==null) {
      valid(progress && typeof progress==="object" && !Array.isArray(progress));
    }
    // The pin is the submitted precondition. The parser binds the receipt to
    // actual post-state progress; successful continuation may change its head
    // or attempt. Keep the captured input intact.
  }
  if (kind==="publication") valid(r.branch===p.branch);
  if (kind==="delivery") {
    valid(r.integration_base===p.integration_base);
    valid(typeof p.pr_number==="number" && Number.isSafeInteger(p.pr_number) && p.pr_number>0);
    const ref=r.pr_ref as ResourceRef;
    valid(ref.source==="github" && ref.kind==="pull_request" &&
      ref.id===String(pending.target.repository_id)+":"+String(p.pr_number));
  }
}
function correlateResult(state:ProjectionState,pending:CapturedCommand,reply:Record<string,unknown>):CommandResult {
  const r=reply.request as CommandResult;
  const identity=runtime({runtime:reply.runtime as ProjectionV3["runtime"]});
  valid(reply.binding_epoch===state.binding_epoch && reply.binding_epoch===pending.command_binding_epoch &&
    (state.runtime_key===null || identity===state.runtime_key) &&
    (pending.command_runtime_key===null || identity===pending.command_runtime_key) &&
    r.request_id===pending.request_id && r.action===pending.action && json(r.target)===json(pending.target));
  if(pending.action==="cleanup" && r.receipt!==null){
    const receipt=r.receipt as Record<string,unknown>;
    valid(json(receipt.resource)===json(pending.target.resource) && receipt.operation===pending.operation);
  }
  if(pending.action==="workflow_step" && r.receipt!==null)workflowReceipt(pending,r);
  if(pending.action==="admission_set" && r.receipt!==null)
    admissionReceipt(pending,r,reply.observations as Observation[],(reply.runtime as ProjectionV3["runtime"]).control_binding_digest);
  return r;
}
function uint(n: number) { valid(Number.isSafeInteger(n) && n >= 0); }
export function compareRevisions(left:Revision|null,right:Revision|null):number|null {
  if (!left || !right || left.kind !== right.kind) return null;
  if (left.value === right.value) return 0;
  if (left.kind !== "monotonic") return null;
  if (left.value.length !== right.value.length) return left.value.length < right.value.length ? -1 : 1;
  return left.value < right.value ? -1 : 1;
}
export function projectionState(binding_epoch: string): ProjectionState {
  valid(uuid.test(binding_epoch));
  return { binding_epoch, source_slots: new Map(), selected_ref: null, pending_commands: new Map(),
    feedback: new Map(), read_context:{scope:null,sequence:0}, retry_windows: new Map(), queries: new Map(), view: null, runtime_key: null, runtime_sequence:0, page_sequence:0, last_now: 0, error: null };
}
function stale(state: ProjectionState, keys: Iterable<string>, reason: string) {
  for (const k of keys) {
    const slot = state.source_slots.get(k); if (!slot) continue;
    state.source_slots.set(k, { ...slot, stale: true, observation: slot.observation.value === null ? slot.observation :
      { ...slot.observation, availability: "stale", reason } });
  }
}
function currentFact(f: Fact<unknown>, state: ProjectionState, changed: Set<string>, incoming: boolean, seq: number, receivedSequence = Number.MAX_SAFE_INTEGER): Fact<unknown> {
  if (f.value === null) return f;
  if (!incoming && f.evidence.some(e => changed.has(e.observation_key))) return unknown("source_changed");
  for (const e of f.evidence) {
    const slot = state.source_slots.get(e.observation_key), o = slot?.observation;
    if (!slot || slot.stale || slot.latest_settled_seq > seq || (incoming && slot.received_sequence>receivedSequence) || o?.availability !== "current" ||
        o.coverage.state !== "complete" || json(e.revision) !== json(o.revision)) return unknown("source_unavailable");
  }
  return f;
}
function refreshFacts(state: ProjectionState, changed: Set<string>, incoming: Set<object>, seq: number, receivedSequence=Number.MAX_SAFE_INTEGER) {
  const view = state.view; if (!view) return;
  for (const p of view.projects) {
    for (const axis of ["admission", "execution"] as const)
      p[axis] = currentFact(p[axis], state, changed, incoming.has(p), seq, receivedSequence) as never;
  }
  const admissions=new Map<string,Fact<string>|null>();
  for (const p of view.projects) for (const ref of p.work_refs) {
    const k=key(ref);
    admissions.set(k,admissions.has(k) ? null : p.admission);
  }
  for (const w of view.work) {
    for (const axis of ["readiness", "stage", "admission", "execution", "wait", "delivery", "result", "cleanup", "next_action"] as const)
      w[axis] = currentFact(w[axis], state, changed, incoming.has(w), seq, receivedSequence) as never;
    // Local polls carry project gates without work rows. A uniquely matched,
    // freshly validated project gate also applies to its retained work display.
    const admission=admissions.get(key(w.issue_ref));
    if (!incoming.has(w) && admission && admission.value!==null) w.admission=structuredClone(admission);
    for (const axis of ["question", "answer", "acceptance", "application"] as const)
      w.decision[axis] = currentFact(w.decision[axis], state, changed, incoming.has(w), seq, receivedSequence);
    // A lost question cannot leave a dependent answer/application looking current.
    if (w.decision.question.value === null) {
      for (const axis of ["answer", "acceptance", "application"] as const)
        w.decision[axis] = unknown("question_unavailable");
    }
  }
  view.relations = view.relations.filter(r => currentFact({ value: true, evidence: r.evidence, reason: null },
    state, changed, incoming.has(r), seq, receivedSequence).value === true);
  view.observations = [...state.source_slots.values()].map(slot => slot.observation);
}
type ReadWindow = { frame: ProjectionV3; sequence: number; received_sequence: number };
function removeWork(state:ProjectionState,removed:Set<string>,changed:Set<string>) {
  const view=state.view!;
  view.work=view.work.filter(w=>!removed.has(key(w.issue_ref)));
  view.relations=view.relations.filter(r=>!removed.has(key(r.from)) && !removed.has(key(r.to)));
  for (const [k,slot] of state.source_slots) {
    const o=slot.observation,issue=o.value?.issue_ref as ResourceRef|undefined;
    if ((o.resource.kind==="issue" && removed.has(key(o.resource))) ||
        (o.resource.kind==="progress" && issue && removed.has(key(issue)))) {
      state.source_slots.delete(k);changed.add(k);
    }
  }
}
function pruneUnusedSources(state: ProjectionState) {
  const view = state.view!;
  const evidence = new Set(view.retry_hints.map(h => h.observation_key)), resources = new Set<string>();
  const walk = (value: unknown): void => {
    if (Array.isArray(value)) { for (const v of value) walk(v); return; }
    if (!value || typeof value !== "object") return;
    const v = value as Record<string, unknown>;
    if (typeof v.observation_key === "string") evidence.add(v.observation_key);
    if (typeof v.source === "string" && typeof v.kind === "string" && typeof v.id === "string") resources.add(json([v.source,v.kind,v.id]));
    for (const child of Object.values(v)) walk(child);
  };
  walk(view.projects); walk(view.work); walk(view.relations); walk(view.capabilities);
  for (const [k,slot] of state.source_slots) {
    const o = slot.observation;
    if (!evidence.has(k) && o.resource.source !== "hydra" &&
        (!resources.has(key(o.resource)) || k.startsWith("github:query:"))) state.source_slots.delete(k);
  }
  refreshFacts(state,new Set(),new Set(),Number.MAX_SAFE_INTEGER);
}
function replaceablePage(frame:ProjectionV3):boolean {
  const prefixes=new Set(["record_limit","page_limit","response_limit","continuation_slice"]);
  return (frame.projects.length>0 || frame.page.state==="complete") && frame.projects.every(p=>
    p.coverage.state==="complete" || (p.coverage.state==="partial" && prefixes.has(p.coverage.reason ?? "") &&
      frame.observations.some(o=>key(o.resource)===key(p.repository_ref) && o.resource.source==="github" &&
        o.availability==="current" && o.coverage.state==="complete")));
}
function bound(state: ProjectionState, window?: ReadWindow) {
  const feedbackSize = () => size([...state.feedback.values()]);
  if (feedbackSize() > 131_072) {
    for (const [k, f] of state.feedback) state.feedback.set(k, { ...f, outcome: "unknown",
      reason: "receipt_capacity_held", receipt: null });
  }
  const fits = (view: ProjectionV3) => size(view) <= MAX_PROJECTION_BYTES &&
    view.work.length <= 512 && view.projects.length <= 1024 && view.projects.every(p=>p.work_refs.length<=128);
  if (!state.view || fits(state.view)) return;
  pruneUnusedSources(state);
  if (fits(state.view)) return;
  // Failure metadata can grow a previously full page. Evict stale cached values
  // before any known work identity; this never marks a source current or ended.
  const hints = new Set(state.view.retry_hints.map(h => h.observation_key));
  const rotate=window!==undefined && replaceablePage(window.frame);
  const staleValues = [...state.source_slots].filter(([k,s]) => s.observation.value !== null && !hints.has(k) &&
    (s.stale || (!rotate && s.observation.resource.source!=="hydra")))
    .sort(([,a],[,b]) => Number(b.stale)-Number(a.stale) || size(b.observation.value)-size(a.observation.value));
  for (const [k,s] of staleValues) {
    const o = s.observation;
    state.source_slots.set(k,{...s,stale:true,observation:{...o,value:null,availability:"unavailable",observed_at:null,
      reason:"renderer_limit",coverage:{...o.coverage,state:"unavailable",returned_count:0,total_count:null,next_cursor:null,reason:"renderer_limit"}}});
    refreshFacts(state,new Set([k]),new Set(),Number.MAX_SAFE_INTEGER);
    if (fits(state.view)) return;
  }
  if (window && rotate) {
    // Pages are individually bounded. Rotate to the complete incoming page
    // when their union no longer fits; never manufacture an intra-page cursor
    // or silently discard part of the page behind its real next-record cursor.
    const keys = new Set(window.frame.observations.map(o => o.key));
    const current = state.view;
    state.source_slots = new Map([...state.source_slots].filter(([k]) => keys.has(k)));
    state.view = structuredClone(window.frame);
    if (window.received_sequence < state.runtime_sequence) {
      state.view.assembled_at=current.assembled_at; state.view.request_id=current.request_id;
      state.view.capabilities=current.capabilities; state.view.request=current.request;
      state.view.retry_hints=current.retry_hints.filter(h=>keys.has(h.observation_key));
    }
    if (window.received_sequence < state.page_sequence) state.view.page=current.page;
    const incoming = new Set<object>([...state.view.projects, ...state.view.work, ...state.view.relations]);
    refreshFacts(state, new Set(), incoming, window.sequence, window.received_sequence);
    try {
      if (fits(state.view)) { validateProjectionView(state.view); return; }
    } catch { /* A retained source fence cannot create a malformed display. */ }
  }
  // Memory pressure is an explicit read-model failure, never task completion,
  // resource retirement or a claim that a command did not take effect.
  state.view = null; state.source_slots.clear(); state.error = "renderer_limit";
}
function failed(state: ProjectionState, scope: string, sequence: number, reason: string) {
  const query = state.queries.get(scope);
  if (!query || query.sequence !== sequence) return;
  const affected = [...query.keys].filter(k => state.source_slots.get(k)?.latest_issued_seq === sequence);
  stale(state, affected, reason);
  state.queries.delete(scope);
  refreshFacts(state, new Set(affected), new Set(), sequence);
  state.error = reason;
}
export function reduceProjection(previous: ProjectionState, event: ProjectionEvent): ProjectionState {
  // Each stored payload is bounded; no source frame or conversation history is accumulated.
  const state = { ...previous, source_slots: new Map(previous.source_slots), queries: new Map(previous.queries),
    pending_commands: new Map(previous.pending_commands), feedback: new Map(previous.feedback),
    view: previous.view ? structuredClone(previous.view) : null, retry_windows: new Map([...previous.retry_windows].map(([k,v]) => [k,{ ...v, failures:new Map(v.failures) }])) };
  let window: ReadWindow | undefined;
  switch (event.type) {
    case "binding_changed": {
      valid(uuid.test(event.binding_epoch) && event.binding_epoch !== state.binding_epoch);
      const next = projectionState(event.binding_epoch); next.selected_ref = state.selected_ref;
      next.feedback = new Map(state.feedback);
      for (const [id, c] of state.pending_commands) next.feedback.set(id, { ...c, outcome: "unknown", reason: "binding_changed", receipt: null });
      return next;
    }
    case "read_started": {
      uint(event.sequence); valid(event.sequence > 0 && uuid.test(event.request_id));
      valid(event.scope.length > 0 && [...event.scope].length <= 512 && !/[\x00-\x1f\x7f]/.test(event.scope));
      const old = state.queries.get(event.scope);
      valid(!old || old.sequence < event.sequence);
      valid(old || state.queries.size < 16);
      const keys = new Set(event.observation_keys ?? [...state.source_slots].filter(([,s]) => s.query_scope === event.scope).map(([k]) => k));
      valid(keys.size <= 4096);
      state.queries.set(event.scope, { sequence: event.sequence, request_id: event.request_id, keys });
      for (const k of keys) { const s = state.source_slots.get(k); if (s) state.source_slots.set(k, { ...s, latest_issued_seq: Math.max(s.latest_issued_seq,event.sequence) }); }
      break;
    }
    case "read_failed": failed(state,event.scope,event.sequence,event.reason); break;
    case "read_succeeded": {
      const query = state.queries.get(event.scope); if (!query || query.sequence !== event.sequence) return previous;
      uint(event.now); uint(event.response.age_ms); uint(event.response.sequence);
      valid(typeof event.response.cached === "boolean" && typeof event.response.stale === "boolean");
      let frame: ProjectionV3;
      try { frame = parseProjection(event.response.payload); }
      catch { failed(state,event.scope,event.sequence,"invalid_response"); break; }
      if (frame.binding_epoch !== state.binding_epoch || (!event.response.cached && frame.request_id !== query.request_id)) {
        failed(state,event.scope,event.sequence,"read_binding_mismatch"); break;
      }
      const context=event.response.read_context;
      if (context) {
        uint(context.sequence);
        valid(Object.keys(context).sort().join(",")==="scope,sequence" &&
          (context.scope===null || (typeof context.scope==="string" && [...context.scope].length>0 && [...context.scope].length<=256 && !/[\x00-\x1f\x7f]/.test(context.scope))));
        if (context.sequence<state.read_context.sequence) {state.queries.delete(event.scope);break;}
        valid(context.sequence!==state.read_context.sequence || context.scope===state.read_context.scope);
        if (context.sequence>state.read_context.sequence) {
          const affected=[...state.source_slots].filter(([,slot])=>slot.observation.resource.source==="github").map(([key])=>key);
          stale(state,affected,"credential_context_changed");
          refreshFacts(state,new Set(affected),new Set(),Number.MAX_SAFE_INTEGER);
          state.read_context={...context};
        }
      } else {
        failed(state,event.scope,event.sequence,"read_context_unavailable");break;
      }
      const identity = runtime(frame);
      const windowFrame = structuredClone(frame);
      if (state.runtime_key !== null && state.runtime_key !== identity) {
        if (state.runtime_sequence>=event.response.sequence) {
          state.queries.delete(event.scope);break;
        }
        for (const [id,c] of state.pending_commands) state.feedback.set(id,{...c,outcome:"unknown",reason:"runtime_binding_changed",receipt:null});
        state.pending_commands.clear();state.queries.clear();state.source_slots.clear();
        state.view=null;state.page_sequence=0;state.selected_ref=null;
      }
      state.runtime_key = identity;
      state.runtime_sequence=Math.max(state.runtime_sequence,event.response.sequence);
      if (event.now < state.last_now) stale(state,state.source_slots.keys(),"clock_resumed");
      const origin = Math.max(state.last_now,event.now)-event.response.age_ms;
      if (!event.response.cached) {
        for (const [identity,window] of state.retry_windows) for (const o of frame.observations) {
          const [source,scope]=JSON.parse(identity) as [string,string];
          if (source===o.resource.source && (source!=="github" || context?.scope===scope) &&
              o.availability === "current" && o.coverage.state === "complete" &&
              o.reason !== "rate_limited" && o.reason !== "provider_wait") window.failures.delete(o.key);
        }
      }
      for (const hint of frame.retry_hints) {
        const o=frame.observations.find(o=>o.key===hint.observation_key)!;
        if (context && o.resource.source==="github" && hint.scope!==context.scope) continue;
        const k=json([o.resource.source,hint.scope]);
        if (!state.retry_windows.has(k) && state.retry_windows.size>=256) {state.error="read_policy_capacity_held";continue;}
        const window=state.retry_windows.get(k) ?? {received_at:origin,after_seconds:0,basis:hint.basis,failures:new Map()};
        let seconds=hint.after_seconds;
        if (hint.basis === "fallback" && !event.response.cached) {
          const prior=window.failures.get(o.key), marker=frame.binding_epoch+":"+event.response.sequence;
          if (!prior && window.failures.size>=512) {state.error="read_policy_capacity_held";continue;}
          const count=prior?.frame===marker ? prior.count : (prior?.count ?? 0)+1;
          window.failures.set(o.key,{count,frame:marker}); seconds=Math.max(seconds,[60,120,240,480,900][Math.min(count-1,4)]!);
        }
        const now=Math.max(state.last_now,event.now);
        const remaining=(w:RetryWindow) => Math.max(0,w.after_seconds-Math.max(0,now-w.received_at)/1000);
        const candidate={...window,received_at:origin,after_seconds:seconds,basis:hint.basis};
        if (remaining(candidate)>remaining(window)) {window.received_at=origin;window.after_seconds=seconds;window.basis=hint.basis;}
        state.retry_windows.set(k,window);
      }
      const now = Math.max(state.last_now,event.now); state.last_now = now;
      const changed = new Set<string>(), marker = frame.binding_epoch + ":" + event.response.sequence;
      // Resolve display aliases before comparing project causality. Failed reads
      // keep both source references, so their newer attempt cannot be replaced
      // by an older complete cached page. Local admission remains independent.
      for (const p of frame.projects) if (p.repository_ref.id.startsWith("requested:")) {
        const address=p.repository_ref.id.slice("requested:".length).toLowerCase();
        const observed=[...state.source_slots.values()].find(s=>s.observation.resource.kind==="repository" &&
          typeof s.observation.value?.full_name==="string" && s.observation.value.full_name.toLowerCase()===address &&
          !s.observation.resource.id.startsWith("requested:"));
        const old=state.view?.projects.find(old=>observed && key(old.repository_ref)===key(observed.observation.resource));
        if (old) {
          const coverage=p.coverage,sourceRefs=p.source_refs;
          Object.assign(p,structuredClone(old),{admission:p.admission});
          if (coverage.reason!=="not_requested") {
            p.coverage=coverage;
            p.source_refs=[...new Map([...p.source_refs,...sourceRefs].map(ref=>[key(ref),ref])).values()];
          }
        }
      }
      const olderProjects=new Set<string>(),olderRefs=new Set<string>(),olderIndexes=new Set<number>();
      frame.projects.forEach((p,index)=>{
        const prior=state.view?.projects.find(old=>key(old.repository_ref)===key(p.repository_ref));
        const refs=[...p.source_refs,...(prior?.source_refs ?? [])].filter(ref=>ref.source==="github");
        const matches=(ref:ResourceRef)=>refs.some(r=>key(r)===key(ref)) ||
          (ref.source==="github" && ref.id.startsWith(p.repository_ref.id+":"));
        if ([...state.source_slots.values()].some(s=>matches(s.observation.resource) && s.received_sequence>event.response.sequence)) {
          olderProjects.add(p.repository_ref.id);olderIndexes.add(index);
          for (const ref of refs) olderRefs.add(key(ref));
        }
      });
      if (olderProjects.size) {
        const older=(ref:ResourceRef)=>ref.source==="github" && (olderRefs.has(key(ref)) ||
          [...olderProjects].some(id=>ref.id.startsWith(id+":")));
        for (const o of frame.observations) if (older(o.resource)) {
          const current=state.source_slots.get(o.key)?.observation;
          // Keep the newer source bytes, but retain the existing conservative
          // fact hold when an unversioned source has conflicting cached content.
          if (current && current.revision===null && o.revision===null && json(current.value)!==json(o.value))
            changed.add(o.key);
        }
        for (const value of [frame,windowFrame]) {
          value.projects=value.projects.filter((_,index)=>!olderIndexes.has(index));
          value.work=value.work.filter(w=>!older(w.issue_ref));
          value.relations=value.relations.filter(r=>!older(r.from) && !older(r.to));
          value.observations=value.observations.filter(o=>!older(o.resource));
          value.retry_hints=value.retry_hints.filter(h=>value.observations.some(o=>o.key===h.observation_key));
          value.page={...value.page,state:"partial",returned_count:value.projects.length,total_count:null,reason:"source_changed"};
        }
      }
      for (const observation of frame.observations) {
        const old = state.source_slots.get(observation.key);
        if (old && (old.latest_issued_seq > event.sequence || old.latest_settled_seq > event.sequence || old.received_sequence > event.response.sequence)) continue;
        const order=old ? compareRevisions(observation.revision,old.observation.revision) : null;
        if (old && order !== null && order < 0) {
          changed.add(observation.key);
          state.source_slots.set(observation.key,{...old,latest_issued_seq:event.sequence,latest_settled_seq:event.sequence});
          stale(state,[observation.key],"source_revision_regressed");continue;
        }
        // A local-only poll did not attempt GitHub. Preserve its original age and value.
        if (old && observation.resource.source !== "hydra" && observation.reason === "not_requested") continue;
        if (event.response.cached && old?.frame === marker) continue; // no freshness renewal
        const semantic=(o:Observation)=>json([o.resource,o.revision,o.availability,o.coverage,o.reason,o.value]);
        if (!old || semantic(old.observation)!==semantic(observation)) changed.add(observation.key);
        const failedRead = observation.availability !== "current";
        const retained = failedRead && old?.observation.value !== null && old?.observation.value !== undefined ?
          { ...old.observation, availability: "stale" as const, last_attempt_at: observation.last_attempt_at,
            reason: observation.reason ?? "source_unavailable" } : observation;
        const received = now-event.response.age_ms;
        const ttl = observation.resource.source === "hydra" ? 15_000 : 60_000;
        state.source_slots.set(observation.key, { latest_issued_seq: event.sequence, latest_settled_seq: event.sequence,
          query_scope: event.scope, observation: retained, received_at: received,
          stale: failedRead || event.response.stale || event.response.age_ms >= ttl, frame: marker,received_sequence:event.response.sequence });
      }
      state.queries.delete(event.scope);
      // Local admission can update the already observed repository's display context.
      // This does not refresh repository identity, coverage, progress or authority.
      const resolvedAliases=new Map<string,ResourceRef>();
      for (const p of frame.projects) {
        const observed=[...state.source_slots.values()].find(s=>key(s.observation.resource)===key(p.repository_ref) &&
          s.observation.resource.kind==="repository" && typeof s.observation.value?.full_name==="string");
        if (observed) resolvedAliases.set("requested:"+(observed.observation.value!.full_name as string).toLowerCase(),p.repository_ref);
      }
      if (state.view) state.view.projects=state.view.projects.filter(p=>!resolvedAliases.has(p.repository_ref.id.toLowerCase()));
      if (state.selected_ref?.kind==="repository") {
        const resolved=resolvedAliases.get(state.selected_ref.id.toLowerCase());
        if (resolved) state.selected_ref=structuredClone(resolved);
      }
      const currentRequest = event.response.sequence < state.runtime_sequence ? state.view?.request ?? null : structuredClone(frame.request);
      const incoming = new Set<object>();
      const localRead=event.scope==="local" || event.scope.startsWith("local:");
      if (!state.view) { state.view = structuredClone(frame); state.page_sequence=localRead?0:event.response.sequence; for (const x of [...state.view.projects,...state.view.work,...state.view.relations]) incoming.add(x); }
      else {
        // Absence is meaningful only for a complete refresh of the same set.
        // Removing a display record does not complete or retire its native work.
        const removed=new Set<string>();
        for (const p of frame.projects) {
          const old=state.view.projects.find(old=>key(old.repository_ref)===key(p.repository_ref));
          if (!old || p.coverage.state!=="complete" || p.coverage.scope!==old.coverage.scope) continue;
          const present=new Set(p.work_refs.map(key));
          for (const w of state.view.work) if (w.issue_ref.source==="github" &&
              w.issue_ref.id.startsWith(p.repository_ref.id+":") && !present.has(key(w.issue_ref))) removed.add(key(w.issue_ref));
        }
        removeWork(state,removed,changed);
        const merge = <T extends object>(old:T[],next:T[],identify:(x:T)=>string) => {
          const values = new Map(old.map(x => [identify(x),x]));
          for (const x of next) { const clone = structuredClone(x); values.set(identify(clone),clone); incoming.add(clone); }
          return [...values.values()];
        };
        const priorProjects=new Map(state.view.projects.map(p=>[key(p.repository_ref),p]));
        state.view.projects = merge(state.view.projects,frame.projects,x=>key(x.repository_ref));
        state.view.work = merge(state.view.work,frame.work,x=>key(x.issue_ref));
        const retainedWork=new Set(state.view.work.map(w=>key(w.issue_ref)));
        const evicted=new Set<string>();
        for (const p of state.view.projects) {
          const refs=[...(priorProjects.get(key(p.repository_ref))?.work_refs ?? []),...p.work_refs];
          const combined=[...new Map(refs.filter(ref=>retainedWork.has(key(ref))).map(ref=>[key(ref),ref])).values()];
          if (combined.length<=128) p.work_refs=combined;
          else {
            // Rotate only this project's whole page at its wire bound. Other
            // projects, the provider cursor and command feedback remain intact.
            const incomingRefs=new Set(p.work_refs.map(key));
            for (const ref of combined) if (!incomingRefs.has(key(ref))) evicted.add(key(ref));
          }
        }
        removeWork(state,evicted,changed);
        state.view.relations = merge(state.view.relations,frame.relations,x=>json([x.from,x.kind,x.to]));
        if (event.response.sequence >= state.runtime_sequence) {
          state.view.assembled_at = frame.assembled_at; state.view.request_id = frame.request_id;
          state.view.capabilities = structuredClone(frame.capabilities);
          state.view.retry_hints = structuredClone(frame.retry_hints);
        }
        const domain=(scope:string)=>scope.startsWith("registered-projects;")?scope.replace(/:from:[0-9]+$/,""):scope;
        if(!localRead && event.response.sequence>=state.page_sequence &&
            (domain(frame.page.scope)===domain(state.view.page.scope) ||
             domain(frame.page.scope)==="registered-projects;overview")) {
          state.view.page=structuredClone(frame.page);state.page_sequence=event.response.sequence;
        }
      }
      state.view.request = currentRequest;
      if(currentRequest && frame.request && event.response.sequence===state.runtime_sequence && !event.response.stale){
        const saved=state.pending_commands.get(currentRequest.request_id) ?? state.feedback.get(currentRequest.request_id);
        if(saved && (!("outcome" in saved) || saved.outcome==="unknown" || saved.outcome==="waiting")){
          try{
            const result=correlateResult(state,saved,{runtime:frame.runtime,binding_epoch:frame.binding_epoch,
              request:currentRequest,observations:frame.observations});
            state.pending_commands.delete(result.request_id);
            state.feedback.set(result.request_id,{...saved,outcome:result.outcome,reason:result.reason,receipt:result.receipt});
          }catch{/* Unrelated or unverified read-backs preserve the original effect hold. */}
        }
      }
      refreshFacts(state,changed,incoming,event.sequence,event.response.sequence);
      window = {frame:windowFrame,sequence:event.sequence,received_sequence:event.response.sequence};
      if (state.error !== "read_policy_capacity_held") state.error = null; break;
    }
    case "binding_unavailable": {
      uint(event.now); state.last_now = Math.max(state.last_now,event.now);
      state.queries.clear();
      stale(state,state.source_slots.keys(),"binding_unavailable");
      refreshFacts(state,new Set(state.source_slots.keys()),new Set(),Number.MAX_SAFE_INTEGER);
      state.error = "binding_unavailable"; break;
    }
    case "clock_resumed": {
      uint(event.now); state.last_now = Math.max(state.last_now,event.now);
      stale(state,state.source_slots.keys(),"clock_resumed");
      refreshFacts(state,new Set(state.source_slots.keys()),new Set(),Number.MAX_SAFE_INTEGER); break;
    }
    case "selection_changed": state.selected_ref = event.selected_ref; break;
    case "command_started": {
      valid(uuid.test(event.request_id) && (event.effect_key === null ||
        (typeof event.effect_key === "string" && event.effect_key.length > 0 && event.effect_key.length <= 512)));
      valid(!state.pending_commands.has(event.request_id) && !state.feedback.has(event.request_id));
      valid(/^[a-z][a-z0-9_]{0,63}$/.test(event.action) && size(event.target)<=4096);
      valid(event.effect_key === null || ![...state.pending_commands.values(),...[...state.feedback.values()].filter(f=>f.outcome === "unknown" || f.outcome === "waiting")].some(c => c.effect_key === event.effect_key));
      for (const [id,f] of state.feedback) if (state.pending_commands.size+state.feedback.size>=16 &&
          (f.outcome === "applied" || f.outcome === "rejected")) state.feedback.delete(id);
      valid(state.pending_commands.size + state.feedback.size < 16);
      if (event.action==="cleanup") valid(["preserve","archive","retire","remove_schedule"].includes(event.operation ?? ""));
      else valid(event.operation===undefined);
      let workflow:Pick<Command,"parameters"|"assignment"|"repository_name">={};
      if (event.action==="admission_set") {
        const input=event.parameters;
        valid(input===undefined || (input!==null && typeof input==="object" && !Array.isArray(input)));
        const parameters=input && Object.hasOwn(input,"mode")?{mode:input.mode}:{};
        valid(!Object.hasOwn(parameters,"mode") || typeof parameters.mode==="string" &&
          ["running","paused","stopped"].includes(parameters.mode));
        valid(size(parameters)<=4096);
        const names=new Set([...state.source_slots.values()].filter(({observation:o,stale})=>
          !stale && o.availability==="current" && o.coverage.state==="complete" &&
          o.resource.source==="github" && o.resource.kind==="repository" &&
          o.resource.id===String(event.target.repository_id) && o.value?.numeric_id===event.target.repository_id &&
          typeof o.value?.full_name==="string").map(({observation:o})=>(o.value!.full_name as string).toLowerCase()));
        workflow={parameters:structuredClone(parameters),...(names.size===1?{repository_name:[...names][0]!}:{})};
      }
      if (event.action==="workflow_step") {
        const input=event.parameters;
        valid(input===undefined || (input!==null && typeof input==="object" && !Array.isArray(input)));
        const parameters=input===undefined?undefined:Object.fromEntries(
          ["operation","stage","outcome","candidate","progress","source_attempt","round","branch","integration_base","pr_number"]
            .filter(k=>Object.hasOwn(input,k)).map(k=>[k,input[k]]));
        if (parameters?.progress!==undefined && parameters.progress!==null) {
          const pin=parameters.progress;
          valid(typeof pin==="object" && !Array.isArray(pin));
          parameters.progress=Object.fromEntries(["attempt_id","head","contract_revision","phase"]
            .filter(k=>Object.hasOwn(pin,k)).map(k=>[k,(pin as Record<string,unknown>)[k]]));
        }
        // Keep only bounded correlation pins; private summaries never enter state.
        valid(size({parameters,assignment:event.assignment,effect_key:event.effect_key,target:event.target})<=4096);
        workflow={parameters:structuredClone(parameters),assignment:structuredClone(event.assignment)};
      }
      state.pending_commands.set(event.request_id, { command_binding_epoch:state.binding_epoch,command_runtime_key:state.runtime_key,request_id:event.request_id,effect_key:event.effect_key,
        action:event.action,target:structuredClone(event.target),...workflow,...(event.action==="cleanup"?{operation:event.operation}:{}) }); break;
    }
    case "command_result": {
      const pending = state.pending_commands.get(event.request_id); if (!pending) return previous;
      let result: CommandResult | null = null;
      try {
        result=correlateResult(state,pending,parseStandardReply(event.reply));
      } catch { /* A bad/lost receipt cannot become a failure-to-send or an applied Fact. */ }
      state.pending_commands.delete(event.request_id);
      state.feedback.set(event.request_id, { ...pending, outcome:result?.outcome ?? "unknown",
        reason:result?.reason ?? (result ? null : "command_response_unverified"), receipt:result?.receipt ?? null });
      break;
    }
  }
  bound(state,window); return state;
}
export function sourceFresh(state: ProjectionState, observation_key: string, now: number): boolean {
  uint(now); const slot = state.source_slots.get(observation_key); if (!slot) return false;
  const age = Math.max(state.last_now,now)-slot.received_at;
  return !slot.stale && slot.observation.availability === "current" &&
    age < (slot.observation.resource.source === "hydra" ? 15_000 : 60_000);
}
export function pollSources(visible: boolean, elapsedLocal: number, elapsedRemote: number, providerWait: number) {
  [elapsedLocal,elapsedRemote,providerWait].forEach(uint);
  return { local: visible && elapsedLocal >= 5_000, remote: visible && elapsedRemote >= 60_000 && providerWait === 0 };
}

export function retryWait(state:ProjectionState,source:string,scope:string,now:number) {
  uint(now);const window=state.retry_windows.get(json([source,scope]));
  if (!window) return {seconds:0,explicit_recovery:false,basis:null};
  const seconds=Math.ceil(Math.max(0,window.after_seconds-Math.max(0,Math.max(state.last_now,now)-window.received_at)/1000));
  return {seconds,explicit_recovery:[...window.failures.values()].some(f=>f.count>5),basis:window.basis};
}

export function projectedView(state:ProjectionState,now:number):ProjectionV3|null {
  uint(now);if (!state.view) return null;
  const display={...state,source_slots:new Map(state.source_slots),view:structuredClone(state.view)};
  const expired=[...state.source_slots.keys()].filter(k=>!sourceFresh(state,k,now));
  const timedOut = expired.filter(k => {
    const slot = state.source_slots.get(k)!;
    return !slot.stale && slot.observation.availability === "current";
  });
  stale(display,timedOut,"ttl_expired");
  refreshFacts(display,new Set(expired),new Set(),Number.MAX_SAFE_INTEGER);
  return display.view;
}
