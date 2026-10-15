export type Mode = 'running' | 'paused' | 'stopped';
export type Action = 'start' | 'pause' | 'resume' | 'stop';
export type Target = { scope: 'all' } | { scope: 'project'; repository: string };
export type Gate = 'allowed' | 'blocked' | 'unknown';
export type ExecutionState = 'idle' | 'running' | 'pausing' | 'paused' | 'stopping' | 'stopped' | 'unknown' | 'blocked';
export interface Execution { state: ExecutionState; active_count: number | null; reason: string | null }
export interface RuntimeIdentity {
  identity_schema: 1;
  package: 'openboa-hydra-sdlc';
  version: string | null;
  code_digest: string | null;
  code_digest_scope: 'package_sources_at_startup';
  config_digest: string | null;
  control_binding_digest: string | null;
  identity_reason: string | null;
}
export interface Work { issue: number; phase: string | null; wait_reason: string | null; next_action: string | null; links: { issue: string | null; pr: string | null } }
export interface RecordRequest { repository: string; kind: 'issue' | 'pr' | 'chat'; issue: number | null; expectedPr: number | null }
export interface Project {
  repository: string;
  override_mode: Mode | null;
  effective_mode: Mode | 'unknown';
  gate_status: Gate;
  gate_reason: string | null;
  execution: Execution;
  work: Work[];
  links: { chat: string | null };
}
export interface Snapshot {
  schema_version: 2;
  runtime: RuntimeIdentity;
  observed_at: string;
  host_alias: string;
  revision: number | null;
  global_mode: Mode | 'unknown';
  gate_status: Gate;
  gate_reason: string | null;
  native_turn_control: 'unsupported';
  execution: Execution;
  coverage: { state: 'unverified' | 'confirmed'; reason: string | null };
  can_quit: boolean;
  quit_reason: string | null;
  remote: { state: 'not_requested' | 'fresh' | 'unavailable'; observed_at: string | null };
  projects: Project[];
  request: null | { action: Action; target: string; status: 'applied' | 'held' | 'unknown'; revision: number | null; reason: string | null };
}

const modes = ['running', 'paused', 'stopped'];
const gates = ['allowed', 'blocked', 'unknown'];
const executions = ['idle', 'running', 'pausing', 'paused', 'stopping', 'stopped', 'unknown', 'blocked'];
const repo = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw Error('invalid_response');
  return value as Record<string, unknown>;
}
function fields(value: Record<string, unknown>, keys: string[]): void {
  if (Object.keys(value).length !== keys.length || keys.some(key => !Object.hasOwn(value, key))) throw Error('invalid_response');
}
function oneOf(value: unknown, values: readonly string[]): void { if (typeof value !== 'string' || !values.includes(value)) throw Error('invalid_response'); }
function str(value: unknown, nullable = false): void { if (nullable && value === null) return; if (typeof value !== 'string' || value.length > 4096) throw Error('invalid_response'); }
function integer(value: unknown, nullable = false): void { if (nullable && value === null) return; if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) throw Error('invalid_response'); }
function date(value: unknown, nullable = false): void { if (nullable && value === null) return; str(value); if (!Number.isFinite(Date.parse(value as string))) throw Error('invalid_response'); }
function execution(value: unknown): void { const v = object(value); fields(v, ['state', 'active_count', 'reason']); oneOf(v.state, executions); integer(v.active_count, true); str(v.reason, true); }
function runtimeIdentity(value: unknown): void {
  const v = object(value);
  fields(v, ['identity_schema', 'package', 'version', 'code_digest', 'code_digest_scope', 'config_digest', 'control_binding_digest', 'identity_reason']);
  if (v.identity_schema !== 1 || v.package !== 'openboa-hydra-sdlc' || v.code_digest_scope !== 'package_sources_at_startup') throw Error('invalid_response');
  str(v.version, true);
  if (typeof v.version === 'string' && (!v.version.length || v.version.length > 128 || /[^\x20-\x7e]/.test(v.version))) throw Error('invalid_response');
  for (const name of ['code_digest', 'config_digest', 'control_binding_digest']) {
    if (v[name] !== null && (typeof v[name] !== 'string' || !/^[a-f0-9]{64}$/.test(v[name] as string))) throw Error('invalid_response');
  }
  if (v.identity_reason !== null && (typeof v.identity_reason !== 'string' || !/^[a-z0-9][a-z0-9_-]{0,119}$/.test(v.identity_reason))) throw Error('invalid_response');
}

/** Invalid or missing evidence never turns into an empty, successful snapshot. */
export function parseSnapshot(input: unknown): Snapshot {
  const v = object(input);
  if (Number.isSafeInteger(v.schema_version) && (v.schema_version as number) >= 0 && v.schema_version !== 2) throw Error('unsupported_runtime');
  fields(v, ['schema_version', 'runtime', 'observed_at', 'host_alias', 'revision', 'global_mode', 'gate_status', 'gate_reason', 'native_turn_control', 'execution', 'coverage', 'can_quit', 'quit_reason', 'remote', 'projects', 'request']);
  if (v.schema_version !== 2 || v.native_turn_control !== 'unsupported') throw Error('invalid_response');
  runtimeIdentity(v.runtime);
  date(v.observed_at); str(v.host_alias); integer(v.revision, true);
  oneOf(v.global_mode, [...modes, 'unknown']); oneOf(v.gate_status, gates); str(v.gate_reason, true);
  execution(v.execution);
  const coverage = object(v.coverage); fields(coverage, ['state', 'reason']); oneOf(coverage.state, ['unverified', 'confirmed']); str(coverage.reason, true);
  if (typeof v.can_quit !== 'boolean') throw Error('invalid_response');
  str(v.quit_reason, true);
  const remote = object(v.remote); fields(remote, ['state', 'observed_at']); oneOf(remote.state, ['not_requested', 'fresh', 'unavailable']); date(remote.observed_at, true);
  if (!Array.isArray(v.projects) || v.projects.length > 1024) throw Error('invalid_response');
  const seen = new Set<string>();
  for (const value of v.projects) {
    const p = object(value); str(p.repository);
    fields(p, ['repository', 'override_mode', 'effective_mode', 'gate_status', 'gate_reason', 'execution', 'work', 'links']);
    if (!repo.test(p.repository as string) || seen.has(p.repository as string)) throw Error('invalid_response');
    seen.add(p.repository as string);
    if (p.override_mode !== null) oneOf(p.override_mode, modes);
    oneOf(p.effective_mode, [...modes, 'unknown']); oneOf(p.gate_status, gates); str(p.gate_reason, true); execution(p.execution);
    if (!Array.isArray(p.work) || p.work.length > 1024) throw Error('invalid_response');
    const issues = new Set<number>();
    for (const value of p.work) {
      const w = object(value); fields(w, ['issue', 'phase', 'wait_reason', 'next_action', 'links']);
      integer(w.issue); if (w.issue === 0 || issues.has(w.issue as number)) throw Error('invalid_response'); issues.add(w.issue as number);
      str(w.phase, true); str(w.wait_reason, true); str(w.next_action, true);
      const links = object(w.links); fields(links, ['issue', 'pr']);
      for (const key of ['issue', 'pr']) str(links[key], true);
    }
    const links = object(p.links); fields(links, ['chat']); str(links.chat, true);
  }
  if (v.request !== null) {
    const request = object(v.request); fields(request, ['action', 'target', 'status', 'revision', 'reason']); oneOf(request.action, ['start', 'pause', 'resume', 'stop']); str(request.target); oneOf(request.status, ['applied', 'held', 'unknown']); integer(request.revision, true); str(request.reason, true);
  }
  return input as Snapshot;
}

/** A slow refresh cannot overwrite a newer gate acknowledgement. */
export function acceptSnapshot(current: Snapshot | null, incoming: Snapshot): boolean {
  if (!current || !sameRuntime(current.runtime, incoming.runtime)) return true;
  // A failed read must remain visible even if no revision can be established.
  if (incoming.revision === null) return Date.parse(incoming.observed_at) >= Date.parse(current.observed_at);
  if (current.revision !== null && incoming.revision < current.revision) return false;
  return incoming.revision !== current.revision || Date.parse(incoming.observed_at) >= Date.parse(current.observed_at);
}

/** Equality is a cache boundary, never an installation or ownership qualification. */
export function runtimeKey(runtime: RuntimeIdentity): string | null {
  if (!runtime.version || !runtime.code_digest || !runtime.config_digest || !runtime.control_binding_digest || runtime.identity_reason !== null) return null;
  return JSON.stringify([runtime.version, runtime.code_digest, runtime.config_digest, runtime.control_binding_digest]);
}
export function sameRuntime(a: RuntimeIdentity, b: RuntimeIdentity): boolean {
  const key = runtimeKey(a); return key !== null && key === runtimeKey(b);
}
export interface ObservationTicket { generation: number; sequence: number }
/** Request tickets fence responses from the runtime/configuration they started under. */
export class Observations {
  snapshot: Snapshot | null = null;
  remote: Snapshot | null = null;
  private generation = 0;
  private sequence = 0;
  private acceptedSequence = 0;
  begin(): ObservationTicket { return { generation: this.generation, sequence: ++this.sequence }; }
  current(ticket: ObservationTicket): boolean { return ticket.generation === this.generation; }
  canReportFailure(ticket: ObservationTicket): boolean {
    return this.current(ticket) && ticket.sequence >= this.acceptedSequence;
  }
  invalidate(ticket: ObservationTicket): boolean {
    if (!this.current(ticket) || ticket.sequence < this.acceptedSequence) return false;
    this.snapshot = null; this.remote = null; this.generation += 1;
    this.acceptedSequence = Math.max(this.acceptedSequence, ticket.sequence);
    return true;
  }
  accept(next: Snapshot, ticket: ObservationTicket): boolean {
    if (!this.current(ticket)) return false;
    const changed = !this.snapshot || !sameRuntime(this.snapshot.runtime, next.runtime);
    if (changed && ticket.sequence < this.acceptedSequence) return false;
    if (!acceptSnapshot(this.snapshot, next)) return false;
    if (changed) { this.remote = null; this.generation += 1; }
    this.snapshot = next;
    this.acceptedSequence = Math.max(this.acceptedSequence, ticket.sequence);
    if (next.remote.state !== 'not_requested' && (!this.remote || Date.parse(next.observed_at) >= Date.parse(this.remote.observed_at))) this.remote = next;
    return true;
  }
}

export type FeedbackSource = 'observation' | 'operation';
/** Observation recovery must not erase an unresolved operator action. */
export class ObservationFeedback {
  error = '';
  private source: FeedbackSource = 'observation';
  private observations: Observations;
  constructor(observations: Observations) { this.observations = observations; }
  clear(): void { this.error = ''; this.source = 'observation'; }
  show(error: string, source: FeedbackSource = 'operation'): void {
    if (this.error && this.source === 'operation' && source === 'observation') return;
    this.error = error; this.source = source;
  }
  fail(error: string, ticket: ObservationTicket | undefined, source: FeedbackSource): boolean {
    if (ticket && !(source === 'observation' ? this.observations.canReportFailure(ticket) : this.observations.current(ticket))) return false;
    this.show(error, source);
    return true;
  }
  reconcileRefresh(accepted: boolean, state: { manual: boolean; pending: boolean; quitting: boolean }): void {
    if (accepted && !state.pending && !state.quitting && (state.manual || this.source === 'observation')) this.clear();
  }
}

export function workRecord(repository: string, work: Work, kind: 'issue' | 'pr'): RecordRequest | null {
  if (!repo.test(repository) || !Number.isSafeInteger(work.issue) || work.issue < 1) return null;
  if (kind === 'issue') return work.links.issue === `https://github.com/${repository}/issues/${work.issue}`
    ? { repository, kind, issue: work.issue, expectedPr: null } : null;
  const prefix = `https://github.com/${repository}/pull/`;
  const tail = work.links.pr?.startsWith(prefix) ? work.links.pr.slice(prefix.length) : '';
  if (!/^[1-9][0-9]*$/.test(tail) || !Number.isSafeInteger(Number(tail))) return null;
  return { repository, kind, issue: work.issue, expectedPr: Number(tail) };
}

export function admissionSummary(snapshot: Snapshot): string {
  const counts = { allowed: 0, blocked: 0, unknown: 0 };
  for (const project of snapshot.projects) counts[project.gate_status] += 1;
  return `${counts.allowed} allowed · ${counts.blocked} blocked · ${counts.unknown} unconfirmed`;
}
export function appliedNotice(action: Action, target: Target, snapshot: Snapshot): string {
  if (target.scope === 'all') return `${title(action)} setting applied. New work: ${admissionSummary(snapshot)}. Individual settings are preserved; execution is observed separately.`;
  const project = snapshot.projects.find(row => row.repository === target.repository);
  const admission = project?.gate_status === 'allowed' ? 'allowed' : project?.gate_status === 'blocked' ? 'blocked' : 'unconfirmed';
  return `${title(action)} setting applied to ${target.repository}. New work is ${admission}; execution is observed separately.`;
}

export function waitReasonLabel(reason: string): string {
  if (reason === 'native_task_active' || reason === 'native_assignment_pending') return 'Awaiting checkpoint; execution unconfirmed';
  return title(reason);
}
export function nextActionLabel(action: string): string {
  if (action.startsWith('decision_context_')) return 'Continue with the recorded decision context';
  return title(action);
}

export function isStale(snapshot: Snapshot | null, now = Date.now()): boolean {
  return !snapshot || now - Date.parse(snapshot.observed_at) > 15_000 || Date.parse(snapshot.observed_at) > now + 5_000;
}

export function actionDisabled(action: Action, target: Target, snapshot: Snapshot | null, pending: boolean, now = Date.now()): boolean {
  if (pending || !snapshot) return true;
  if (target.scope === 'project' && !snapshot.projects.some(p => p.repository === target.repository)) return true;
  // Blocking controls remain available through stale remote/ownership observations.
  if (action === 'pause' || action === 'stop') return false;
  if (isStale(snapshot, now) || snapshot.global_mode === 'unknown' || snapshot.gate_status === 'unknown' || snapshot.revision === null) return true;
  if (target.scope === 'project') {
    const project = snapshot.projects.find(row => row.repository === target.repository)!;
    return snapshot.global_mode !== 'running' || project.gate_status === 'unknown' || project.effective_mode === 'unknown';
  }
  return false;
}

export function pendingLabel(action: Action): string {
  return `Applying ${title(action)}…`;
}
export function displayMode(mode: Mode | 'unknown'): string {
  return ({ running: 'Allowed', paused: 'Paused', stopped: 'Stopped', unknown: 'Unknown' })[mode];
}
export function title(value: string): string { return value.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase()); }
export function count(value: number | null): string { return value === null ? 'Unknown' : String(value); }
