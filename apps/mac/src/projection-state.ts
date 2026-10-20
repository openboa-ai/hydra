/** Source ordering and display state. No event in this reducer sends an effect. */
import {
  MAX_PROJECTION_BYTES, ProjectionError, parseProjection, parseStandardReply,
  type CommandResult, type Fact, type Observation, type ProjectionV3, type ResourceRef, type Revision,
} from "./projection.ts";

type Slot = { latest_issued_seq: number; latest_settled_seq: number; observation: Observation;
  query_scope: string; received_at: number; stale: boolean; frame: string; received_sequence:number };
type Query = { sequence: number; request_id: string; keys: Set<string> };
type Command = { request_id: string; effect_key: string; action: string; target: Record<string, unknown> };
type RetryWindow = { received_at: number; after_seconds: number; basis: "provider" | "fallback"; failures: Map<string, { count: number; frame: string }> };
type Feedback = Command & { outcome: CommandResult["outcome"]; reason: string | null; receipt: unknown };
export interface ProjectionState {
  binding_epoch: string; source_slots: Map<string, Slot>; selected_ref: ResourceRef | null;
  pending_commands: Map<string, Command>; feedback: Map<string, Feedback>;
  queries: Map<string, Query>; view: ProjectionV3 | null; runtime_key: string | null;
  retry_windows: Map<string, RetryWindow>; last_now: number; error: string | null;
}
export type ProjectionEvent =
  | { type: "read_started"; scope: string; sequence: number; request_id: string; observation_keys?: string[] }
  | { type: "read_succeeded"; scope: string; sequence: number; now: number;
      response: { payload: unknown; age_ms: number; cached: boolean; stale: boolean; sequence: number } }
  | { type: "read_failed"; scope: string; sequence: number; reason: string }
  | ({ type: "command_started" } & Command)
  | { type: "command_result"; request_id: string; reply: unknown }
  | { type: "binding_changed"; binding_epoch: string }
  | { type: "clock_resumed"; now: number }
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
    feedback: new Map(), retry_windows: new Map(), queries: new Map(), view: null, runtime_key: null, last_now: 0, error: null };
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
  for (const w of view.work) {
    for (const axis of ["readiness", "stage", "admission", "execution", "wait", "delivery", "result", "cleanup", "next_action"] as const)
      w[axis] = currentFact(w[axis], state, changed, incoming.has(w), seq, receivedSequence) as never;
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
function partial(view: ProjectionV3) {
  view.page = { ...view.page, state: "partial", returned_count: view.projects.length,
    total_count: null, next_cursor: null, reason: "renderer_limit" };
  for (const p of view.projects) {
    p.work_refs = p.work_refs.filter(ref => view.work.some(w => key(w.issue_ref) === key(ref)));
    p.coverage = { ...p.coverage, state: "partial", returned_count: p.work_refs.length,
      total_count: null, next_cursor: null, reason: "renderer_limit" };
  }
}
function bound(state: ProjectionState) {
  const feedbackSize = () => size([...state.feedback.values()]);
  if (feedbackSize() > 131_072) {
    for (const [k, f] of state.feedback) state.feedback.set(k, { ...f, outcome: "unknown",
      reason: "receipt_capacity_held", receipt: null });
  }
  const view = state.view; if (!view) return;
  while (size(view) > MAX_PROJECTION_BYTES || view.work.length > 512 || view.projects.length > 1024) {
    if (view.work.length) view.work.shift();
    else if (view.projects.length) view.projects.shift();
    else {
      const victim = state.source_slots.keys().next().value;
      if (victim === undefined) { state.view = null; state.error = "renderer_limit"; return; }
      state.source_slots.delete(victim);
      refreshFacts(state, new Set([victim]), new Set(), Number.MAX_SAFE_INTEGER);
    }
    partial(view);
  }
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
      const identity = runtime(frame);
      if (state.runtime_key !== null && state.runtime_key !== identity) {
        for (const [id,c] of state.pending_commands) state.feedback.set(id,{...c,outcome:"unknown",reason:"runtime_binding_changed",receipt:null});
        state.pending_commands.clear();state.queries.clear();state.source_slots.clear();
        state.view=null;state.selected_ref=null;
      }
      state.runtime_key = identity;
      if (event.now < state.last_now) stale(state,state.source_slots.keys(),"clock_resumed");
      const origin = Math.max(state.last_now,event.now)-event.response.age_ms;
      if (!event.response.cached) {
        for (const window of state.retry_windows.values()) for (const o of frame.observations) {
          if (o.availability === "current" && o.coverage.state === "complete" &&
              o.reason !== "rate_limited" && o.reason !== "provider_wait") window.failures.delete(o.key);
        }
      }
      for (const hint of frame.retry_hints) {
        const o=frame.observations.find(o=>o.key===hint.observation_key)!;
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
      for (const p of frame.projects) {
        if (!p.repository_ref.id.startsWith("requested:")) continue;
        const address=p.repository_ref.id.slice("requested:".length);
        const observed=[...state.source_slots.values()].find(s=>s.observation.resource.kind === "repository" &&
          typeof s.observation.value?.full_name === "string" && s.observation.value.full_name.toLowerCase() === address.toLowerCase() &&
          !s.observation.resource.id.startsWith("requested:"));
        const old=state.view?.projects.find(p=>observed && key(p.repository_ref) === key(observed.observation.resource));
        if (old) Object.assign(p,structuredClone(old),{admission:p.admission});
      }
      const incoming = new Set<object>();
      if (!state.view) { state.view = structuredClone(frame); for (const x of [...state.view.projects,...state.view.work,...state.view.relations]) incoming.add(x); }
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
        state.view.work=state.view.work.filter(w=>!removed.has(key(w.issue_ref)));
        state.view.relations=state.view.relations.filter(r=>!removed.has(key(r.from)) && !removed.has(key(r.to)));
        for (const [k,slot] of state.source_slots) {
          const o=slot.observation,issue=o.value?.issue_ref as ResourceRef|undefined;
          if ((o.resource.kind==="issue" && removed.has(key(o.resource))) ||
              (o.resource.kind==="progress" && issue && removed.has(key(issue)))) {
            state.source_slots.delete(k);changed.add(k);
          }
        }
        const merge = <T extends object>(old:T[],next:T[],identify:(x:T)=>string) => {
          const values = new Map(old.map(x => [identify(x),x]));
          for (const x of next) { const clone = structuredClone(x); values.set(identify(clone),clone); incoming.add(clone); }
          return [...values.values()];
        };
        state.view.projects = merge(state.view.projects,frame.projects,x=>key(x.repository_ref));
        state.view.work = merge(state.view.work,frame.work,x=>key(x.issue_ref));
        state.view.relations = merge(state.view.relations,frame.relations,x=>json([x.from,x.kind,x.to]));
        state.view.assembled_at = frame.assembled_at; state.view.request_id = frame.request_id;
        state.view.capabilities = structuredClone(frame.capabilities); state.view.page = structuredClone(frame.page);
        state.view.retry_hints = structuredClone(frame.retry_hints);
      }
      refreshFacts(state,changed,incoming,event.sequence,event.response.sequence);
      if (state.error !== "read_policy_capacity_held") state.error = null; break;
    }
    case "clock_resumed": {
      uint(event.now); state.last_now = Math.max(state.last_now,event.now);
      stale(state,state.source_slots.keys(),"clock_resumed");
      refreshFacts(state,new Set(state.source_slots.keys()),new Set(),Number.MAX_SAFE_INTEGER); break;
    }
    case "selection_changed": state.selected_ref = event.selected_ref; break;
    case "command_started": {
      valid(uuid.test(event.request_id) && event.effect_key.length > 0 && event.effect_key.length <= 512);
      valid(!state.pending_commands.has(event.request_id) && !state.feedback.has(event.request_id));
      valid(/^[a-z][a-z0-9_]{0,63}$/.test(event.action) && size(event.target)<=4096);
      valid(![...state.pending_commands.values(),...[...state.feedback.values()].filter(f=>f.outcome === "unknown" || f.outcome === "waiting")].some(c => c.effect_key === event.effect_key));
      for (const [id,f] of state.feedback) if (state.pending_commands.size+state.feedback.size>=16 &&
          (f.outcome === "applied" || f.outcome === "rejected")) state.feedback.delete(id);
      valid(state.pending_commands.size + state.feedback.size < 16);
      state.pending_commands.set(event.request_id, { request_id:event.request_id,effect_key:event.effect_key,
        action:event.action,target:structuredClone(event.target) }); break;
    }
    case "command_result": {
      const pending = state.pending_commands.get(event.request_id); if (!pending) return previous;
      let result: CommandResult | null = null;
      try {
        const reply = parseStandardReply(event.reply);
        const r = reply.request as CommandResult;
        valid((state.runtime_key === null || runtime({runtime:reply.runtime as ProjectionV3["runtime"]}) === state.runtime_key) &&
          reply.binding_epoch === state.binding_epoch && r.request_id === pending.request_id &&
          r.action === pending.action && json(r.target) === json(pending.target));
        result = r;
      } catch { /* A bad/lost receipt cannot become a failure-to-send or an applied Fact. */ }
      state.pending_commands.delete(event.request_id);
      state.feedback.set(event.request_id, { ...pending, outcome:result?.outcome ?? "unknown",
        reason:result?.reason ?? (result ? null : "command_response_unverified"), receipt:result?.receipt ?? null });
      break;
    }
  }
  bound(state); return state;
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
  stale(display,expired,"ttl_expired");
  refreshFacts(display,new Set(expired),new Set(),Number.MAX_SAFE_INTEGER);
  return display.view;
}
