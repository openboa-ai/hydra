export type Mode = 'running' | 'paused' | 'stopped';
export type Action = 'start' | 'pause' | 'resume' | 'stop';
export type Target = { scope: 'all' } | { scope: 'project'; repository: string };
export type Gate = 'allowed' | 'blocked' | 'unknown';
export type ExecutionState = 'idle' | 'running' | 'pausing' | 'paused' | 'stopping' | 'stopped' | 'unknown' | 'blocked';
export interface Execution { state: ExecutionState; active_count: number | null; reason: string | null }
export interface Work { issue: number; phase: string | null; wait_reason: string | null; next_action: string | null }
export interface Project {
  repository: string;
  override_mode: Mode | null;
  effective_mode: Mode | 'unknown';
  gate_status: Gate;
  gate_reason: string | null;
  execution: Execution;
  work: Work[];
  links: { issue: string | null; pr: string | null; chat: string | null };
}
export interface Snapshot {
  schema_version: 1;
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
function oneOf(value: unknown, values: readonly string[]): void { if (typeof value !== 'string' || !values.includes(value)) throw Error('invalid_response'); }
function str(value: unknown, nullable = false): void { if (nullable && value === null) return; if (typeof value !== 'string' || value.length > 4096) throw Error('invalid_response'); }
function integer(value: unknown, nullable = false): void { if (nullable && value === null) return; if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) throw Error('invalid_response'); }
function date(value: unknown, nullable = false): void { if (nullable && value === null) return; str(value); if (!Number.isFinite(Date.parse(value as string))) throw Error('invalid_response'); }
function execution(value: unknown): void { const v = object(value); oneOf(v.state, executions); integer(v.active_count, true); str(v.reason, true); }

/** Invalid or missing evidence never turns into an empty, successful snapshot. */
export function parseSnapshot(input: unknown): Snapshot {
  const v = object(input);
  if (v.schema_version !== 1 || v.native_turn_control !== 'unsupported') throw Error('invalid_response');
  date(v.observed_at); str(v.host_alias); integer(v.revision, true);
  oneOf(v.global_mode, [...modes, 'unknown']); oneOf(v.gate_status, gates); str(v.gate_reason, true);
  execution(v.execution);
  const coverage = object(v.coverage); oneOf(coverage.state, ['unverified', 'confirmed']); str(coverage.reason, true);
  if (typeof v.can_quit !== 'boolean') throw Error('invalid_response');
  str(v.quit_reason, true);
  const remote = object(v.remote); oneOf(remote.state, ['not_requested', 'fresh', 'unavailable']); date(remote.observed_at, true);
  if (!Array.isArray(v.projects) || v.projects.length > 1024) throw Error('invalid_response');
  const seen = new Set<string>();
  for (const value of v.projects) {
    const p = object(value); str(p.repository);
    if (!repo.test(p.repository as string) || seen.has(p.repository as string)) throw Error('invalid_response');
    seen.add(p.repository as string);
    if (p.override_mode !== null) oneOf(p.override_mode, modes);
    oneOf(p.effective_mode, [...modes, 'unknown']); oneOf(p.gate_status, gates); str(p.gate_reason, true); execution(p.execution);
    if (!Array.isArray(p.work) || p.work.length > 1024) throw Error('invalid_response');
    for (const value of p.work) { const w = object(value); integer(w.issue); if (w.issue === 0) throw Error('invalid_response'); str(w.phase, true); str(w.wait_reason, true); str(w.next_action, true); }
    const links = object(p.links); for (const key of ['issue', 'pr', 'chat']) str(links[key], true);
  }
  if (v.request !== null) {
    const request = object(v.request); oneOf(request.action, ['start', 'pause', 'resume', 'stop']); str(request.target); oneOf(request.status, ['applied', 'held', 'unknown']); integer(request.revision, true); str(request.reason, true);
  }
  return input as Snapshot;
}

/** A slow refresh cannot overwrite a newer gate acknowledgement. */
export function acceptSnapshot(current: Snapshot | null, incoming: Snapshot): boolean {
  if (!current) return true;
  // A failed read must remain visible even if no revision can be established.
  if (incoming.revision === null) return Date.parse(incoming.observed_at) >= Date.parse(current.observed_at);
  if (current.revision !== null && incoming.revision < current.revision) return false;
  return incoming.revision !== current.revision || Date.parse(incoming.observed_at) >= Date.parse(current.observed_at);
}

export function isStale(snapshot: Snapshot | null, now = Date.now()): boolean {
  return !snapshot || now - Date.parse(snapshot.observed_at) > 15_000 || Date.parse(snapshot.observed_at) > now + 5_000;
}

export function actionDisabled(action: Action, target: Target, snapshot: Snapshot | null, pending: boolean, now = Date.now()): boolean {
  if (pending || !snapshot) return true;
  if (target.scope === 'project' && !snapshot.projects.some(p => p.repository === target.repository)) return true;
  // Blocking controls remain available through stale remote/ownership observations.
  if (action === 'pause' || action === 'stop') return false;
  if (isStale(snapshot, now) || snapshot.global_mode === 'unknown' || snapshot.revision === null) return true;
  return target.scope === 'project' && snapshot.global_mode !== 'running';
}

export function pendingLabel(action: Action): string {
  return ({ start: 'Applying Start…', pause: 'Pausing…', resume: 'Applying Resume…', stop: 'Stopping…' })[action];
}
export function displayMode(mode: Mode | 'unknown'): string {
  return ({ running: 'Allowed', paused: 'Paused', stopped: 'Stopped', unknown: 'Unknown' })[mode];
}
export function title(value: string): string { return value.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase()); }
export function count(value: number | null): string { return value === null ? 'Unknown' : String(value); }
