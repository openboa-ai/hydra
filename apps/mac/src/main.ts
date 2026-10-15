import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { ObservationFeedback, Observations, actionDisabled, admissionSummary, appliedNotice, count, isStale, nextActionLabel, parseSnapshot, pendingLabel, title, waitReasonLabel, workRecord } from './model.ts';
import type { Action, FeedbackSource, ObservationTicket, Project, RecordRequest, Snapshot, Target } from './model.ts';
import './tokens.css';
import './style.css';

const app = document.querySelector<HTMLDivElement>('#app')!;
let snapshot: Snapshot | null = null;
let remoteSnapshot: Snapshot | null = null;
const observations = new Observations();
const feedback = new ObservationFeedback(observations);
let pending: { action: Action; target: Target } | null = null;
let localBusy = false;
let remoteBusy = false;
let quitting = false;
let quitTicket: ObservationTicket | null = null;
let notice = '';
let theme: 'system' | 'light' | 'dark' = 'system';
let runtimeDetailsOpen = false;
let focusIntent = 0;
let renderingFocus = false;

function element<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string, className?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (text !== undefined) { node.textContent = text; if (/[\u3131-\uD79D]/.test(text)) node.lang = 'ko'; }
  if (className) node.className = className;
  return node;
}
function icon(text: string): HTMLElement { const node = element('span', text, 'icon'); node.setAttribute('aria-hidden', 'true'); return node; }
function button(text: string, action: () => void, className = '', symbol?: string): HTMLButtonElement {
  const node = element('button', undefined, className); node.type = 'button';
  node.setAttribute('aria-label', text);
  if (symbol) node.append(icon(symbol)); node.append(element('span', text)); node.addEventListener('click', action); return node;
}
function badge(text: string, tone = 'neutral', symbol = '·'): HTMLElement {
  const node = element('span', undefined, `badge ${tone}`); node.append(icon(symbol), element('span', text)); return node;
}
function description(label: string, value: string): HTMLElement {
  const node = element('div', undefined, 'fact'); node.append(element('dt', label), element('dd', value)); return node;
}
function targetName(target: Target): string { return target.scope === 'all' ? 'all projects' : target.repository; }
function equalTarget(a: Target, b: Target): boolean { return a.scope === b.scope && (a.scope === 'all' || (b.scope === 'project' && a.repository === b.repository)); }
function restoreFocus(label: string | null): void {
  if (!label) return;
  Array.from(app.querySelectorAll<HTMLElement>('button[aria-label], summary[aria-label]')).find(node => node.getAttribute('aria-label') === label && !(node instanceof HTMLButtonElement && node.disabled))?.focus({ preventScroll: true });
}
function restorePendingFocus(label: string | null): void { if (document.activeElement === document.body) restoreFocus(label); }
// A later interaction owns focus even if its target is removed by another render.
function supersedePendingFocus(): void { focusIntent += 1; }
document.addEventListener('keydown', supersedePendingFocus, true);
document.addEventListener('pointerdown', supersedePendingFocus, true);
document.addEventListener('focusin', () => { if (!renderingFocus) supersedePendingFocus(); });
window.addEventListener('blur', supersedePendingFocus);

const messages: Record<string, string> = {
  launch_configuration_invalid: 'Launch Hydra with an installed runtime and host configuration. No operation has been enabled.',
  unsupported_runtime: 'This runtime uses an unsupported control protocol. Connect a compatible Hydra runtime; no current control state is confirmed.',
  invalid_response: 'The runtime returned an invalid response. Execution state remains unconfirmed.',
  backend_unavailable: 'The installed Hydra runtime could not be reached. Refresh to reconcile its state.',
  process_failed: 'The runtime could not complete this request. Its execution state remains unconfirmed.',
  operation_timeout: 'The runtime did not answer in time. The request may have applied; its state is being reconciled.',
  output_limit: 'The runtime response exceeded the safe size limit. Refresh to reconcile its state.',
  mutation_uncertain: 'The request result is uncertain. Check the reconciled gate state before making another request.',
  quit_blocked: 'Quit is held because execution termination or control coverage is not confirmed.',
  quitting: 'Stop and Quit is already in progress.',
  invalid_target: 'The requested project is not registered in this host configuration.',
  record_unavailable: 'This record is not available. Refresh GitHub or open the original Codex chat.',
  record_invalid: 'This record link is not an allowed GitHub or Codex destination.',
  backend_response_invalid: 'The runtime returned an invalid response. Execution state remains unconfirmed.',
  backend_read_failed: 'The runtime response could not be read. Refresh to reconcile its state.',
  backend_wait_failed: 'The runtime process could not be accounted for. Its state remains unconfirmed.',
  backend_process_failed: 'The runtime could not complete this request. Its execution state remains unconfirmed.',
  backend_timeout: 'The runtime did not answer in time. Its result remains unconfirmed.',
  backend_output_too_large: 'The runtime response exceeded the safe size limit. Refresh to reconcile its state.',
  mutation_response_lost: 'The request result is uncertain. Check the reconciled gate state before making another request.',
  quit_in_progress: 'Stop and Quit is already in progress.',
  project_unregistered: 'The requested project is not registered in this host configuration.',
  record_url_rejected: 'This record link is not an allowed GitHub or Codex destination.',
  record_open_failed: 'The original record could not be opened in its native surface.',
};
function receiveFailure(value: unknown, ticket?: ObservationTicket, source: FeedbackSource = 'operation'): void {
  const failureCode = value instanceof Error ? value.message : typeof value === 'string' ? value : value && typeof value === 'object' ? (value as { code?: string }).code : null;
  if (failureCode === 'unsupported_runtime') {
    if (!observations.invalidate(ticket ?? observations.begin())) return;
    snapshot = null; remoteSnapshot = null; notice = '';
    feedback.show(messages.unsupported_runtime!, source); return;
  }
  if (!feedback.fail(messages[failureCode ?? ''] ?? 'The operation could not be confirmed. Refresh to reconcile its state.', ticket, source)) return;
  if (value && typeof value === 'object') {
    const e = value as { code?: string; status?: unknown };
    if (e.status) { try { receive(e.status, ticket ?? observations.begin()); } catch { /* Keep the last confirmed snapshot. */ } }
  }
}
function receive(value: unknown, ticket: ObservationTicket): Snapshot | null {
  const next = parseSnapshot(value);
  if (!observations.accept(next, ticket)) return null;
  snapshot = observations.snapshot;
  remoteSnapshot = observations.remote;
  return next;
}

async function refresh(remote = false, manual = false): Promise<void> {
  if (quitting || (remote ? remoteBusy : localBusy)) return;
  const label = remote ? 'Refresh GitHub' : 'Refresh local status';
  // Automatic polling can temporarily disable the focused refresh button too.
  const focus = document.activeElement?.getAttribute('aria-label') === label ? { label, intent: focusIntent } : null;
  const ticket = observations.begin();
  if (remote) remoteBusy = true; else localBusy = true;
  render();
  try {
    const accepted = receive(await invoke('status', { refresh: remote }), ticket);
    feedback.reconcileRefresh(accepted !== null, { manual, pending: !!pending, quitting });
  }
  catch (value) { receiveFailure(value, ticket, 'observation'); }
  finally {
    if (remote) remoteBusy = false; else localBusy = false;
    render();
    if (focus?.intent === focusIntent) restorePendingFocus(focus.label);
  }
}

async function control(action: Action, target: Target): Promise<void> {
  if (actionDisabled(action, target, snapshot, !!pending || quitting)) return;
  const ticket = observations.begin();
  pending = { action, target }; feedback.clear(); notice = ''; render();
  try {
    const result = receive(await invoke('control', { action, target }), ticket);
    if (!result) { feedback.show('A newer runtime observation replaced this request. Refresh to reconcile its result.'); return; }
    if (result.request?.status === 'applied') {
      notice = appliedNotice(action, target, result);
    } else feedback.show(result.request?.reason ? title(result.request.reason) : 'This request is held. No enabling change was confirmed.');
  } catch (value) { receiveFailure(value, ticket); }
  finally { pending = null; render(); restorePendingFocus(`${title(action)} ${targetName(target)}`); }
}

async function openRecord(request: RecordRequest): Promise<void> {
  const ticket = observations.begin();
  try { await invoke('open_record', { ...request }); }
  catch (value) { receiveFailure(value, ticket); render(); }
}

async function requestQuit(): Promise<void> {
  if (quitting || pending) return;
  quitTicket = observations.begin();
  quitting = true; feedback.clear(); notice = 'Stopping new work and checking owned executions before quitting…'; render();
  try { await invoke('request_quit'); }
  catch (value) { receiveFailure(value, quitTicket ?? undefined); quitting = false; quitTicket = null; notice = ''; render(); restorePendingFocus('Stop and quit Hydra'); }
}

function controls(target: Target): HTMLElement {
  const group = element('div', undefined, 'controls'); group.setAttribute('role', 'group'); group.setAttribute('aria-label', `Controls for ${targetName(target)}`);
  for (const [action, symbol] of [['start', '▷'], ['pause', 'Ⅱ'], ['resume', '↻'], ['stop', '□']] as const) {
    const node = button(title(action), () => { void control(action, target); }, action === 'resume' ? 'primary' : '', symbol);
    node.disabled = actionDisabled(action, target, snapshot, !!pending || quitting);
    node.setAttribute('aria-label', `${title(action)} ${targetName(target)}`);
    node.title = action === 'start' || action === 'resume' ? 'Allow new eligible work; does not resume external schedules or native turns.' : 'Block new work; actual execution termination must be confirmed separately.';
    group.append(node);
  }
  return group;
}

function projectCard(project: Project): HTMLElement {
  const target: Target = { scope: 'project', repository: project.repository };
  const card = element('article', undefined, 'project');
  const header = element('div', undefined, 'project-heading');
  const identity = element('div'); identity.append(element('p', project.repository.split('/')[0], 'owner'), element('h3', project.repository.split('/')[1]));
  const state = pending && equalTarget(pending.target, target) ? pendingLabel(pending.action) : `New work ${project.gate_status === 'unknown' ? 'unconfirmed' : project.gate_status}`;
  header.append(identity, badge(state, project.effective_mode === 'unknown' ? 'warning' : 'neutral', project.effective_mode === 'running' ? '▷' : project.effective_mode === 'paused' ? 'Ⅱ' : project.effective_mode === 'unknown' ? '?' : '□'));
  card.append(header);
  const facts = element('dl', undefined, 'facts');
  facts.append(description('Admission', project.gate_status === 'allowed' ? 'New work allowed' : project.gate_status === 'blocked' ? 'New work blocked' : 'Unconfirmed'), description('Execution', title(project.execution.state)), description('Active', count(project.execution.active_count)));
  card.append(facts);
  card.append(element('p', `Individual setting · ${project.override_mode === null ? 'Inherit global' : title(project.override_mode)} · Effective setting · ${title(project.effective_mode)}`, 'helper'));
  if (project.override_mode && project.override_mode !== 'running') card.append(element('p', `Individual ${project.override_mode === 'paused' ? 'Pause' : 'Stop'} is preserved when all projects resume.`, 'preserved'));
  if (project.execution.reason || project.gate_reason) card.append(element('p', title(project.execution.reason ?? project.gate_reason!), 'reason'));
  const remoteProject = remoteSnapshot?.projects.find(row => row.repository === project.repository);
  const workSource = project.work.length ? project : remoteProject ?? project;
  const work = element('div', undefined, 'work');
  if (workSource.work.length) {
    for (const item of workSource.work.slice(0, 3)) {
      const row = element('div', undefined, 'work-row');
      row.append(element('span', `#${item.issue}`, 'issue-id'), element('span', item.phase ? title(item.phase) : 'Phase unknown'));
      if (item.wait_reason) row.append(element('span', waitReasonLabel(item.wait_reason), 'wait-reason'));
      work.append(row);
      if (item.next_action) work.append(element('p', `Next · ${nextActionLabel(item.next_action)}`, 'next-action'));
      const links = element('div', undefined, 'record-links');
      for (const kind of ['issue', 'pr'] as const) {
        const request = workRecord(project.repository, item, kind);
        if (!request) continue;
        const text = kind === 'issue' ? `Issue #${item.issue}` : `PR #${request.expectedPr}`;
        const link = button(`${text} ↗`, () => { void openRecord(request); }, 'link');
        link.disabled = quitting;
        link.setAttribute('aria-label', `Open ${text} for ${project.repository} issue ${item.issue}`); links.append(link);
      }
      work.append(links);
    }
    if (workSource.work.length > 3) work.append(element('p', `${workSource.work.length - 3} more work records`, 'next-action'));
    if (workSource === remoteProject) work.append(element('p', `◷ GitHub ${remoteLabel()} · ${formatTime(remoteSnapshot!.remote.observed_at)}`, 'evidence-time'));
  } else work.append(element('p', remoteSnapshot?.remote.state === 'fresh' ? 'No work records returned in this observation.' : 'Refresh GitHub to inspect work and wait reasons.', 'empty-work'));
  card.append(work);
  const bottom = element('div', undefined, 'project-bottom');
  bottom.append(controls(target));
  const links = element('div', undefined, 'record-links');
  if (project.links.chat) {
    const link = button('Project Codex ↗', () => { void openRecord({ repository: project.repository, kind: 'chat', issue: null, expectedPr: null }); }, 'link');
    link.disabled = quitting;
    link.setAttribute('aria-label', `Open project Codex for ${project.repository}`); links.append(link);
  }
  bottom.append(links); card.append(bottom); return card;
}

function formatTime(value: string | null): string {
  return value ? new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : 'not observed';
}

function remoteLabel(): string {
  if (!remoteSnapshot || remoteSnapshot.remote.state === 'not_requested') return 'not observed';
  if (remoteSnapshot.remote.state === 'unavailable' || !remoteSnapshot.remote.observed_at) return 'unavailable';
  const age = Date.now() - Date.parse(remoteSnapshot.remote.observed_at);
  return age > 60_000 || age < -5_000 ? 'stale' : 'observed';
}

function render(): void {
  // Stable focus identifiers preserve keyboard position through read-only polling.
  const focused = document.activeElement?.getAttribute('aria-label');
  const fragment = document.createDocumentFragment();
  const header = element('header', undefined, 'app-header');
  const identity = element('div'); identity.append(element('p', 'PROJECT OPERATIONS', 'eyebrow'), element('h1', 'Hydra'));
  const utilities = element('div', undefined, 'utilities');
  const themeButton = button(theme === 'system' ? 'System theme' : `${title(theme)} theme`, () => {
    theme = theme === 'system' ? 'light' : theme === 'light' ? 'dark' : 'system';
    if (theme === 'system') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = theme;
    render();
  }, 'quiet', '◐'); themeButton.setAttribute('aria-label', 'Change theme');
  utilities.append(themeButton); header.append(identity, utilities); fragment.append(header);

  const main = element('main');
  const host = element('section', undefined, 'host'); host.setAttribute('aria-label', 'Host controls');
  const top = element('div', undefined, 'host-top');
  const hostTitle = element('div'); hostTitle.append(element('h2', 'All projects'), element('p', snapshot?.host_alias ?? 'Connecting to installed runtime', 'host-name'));
  const label = quitting ? 'Stopping…' : pending?.target.scope === 'all' ? pendingLabel(pending.action) : snapshot ? `New work ${snapshot.gate_status === 'unknown' ? 'unconfirmed' : snapshot.gate_status}` : 'Unconfirmed';
  const hostSymbol = snapshot?.global_mode === 'running' ? '▷' : snapshot?.global_mode === 'paused' ? 'Ⅱ' : snapshot?.global_mode === 'stopped' ? '□' : '?';
  top.append(hostTitle, badge(label, !snapshot || snapshot.global_mode === 'unknown' ? 'warning' : 'neutral', hostSymbol));
  host.append(top, controls({ scope: 'all' }));
  host.append(element('p', 'Start / Resume allow new work. Pause / Stop block new work. Global Resume preserves individual settings.', 'helper'));
  if (snapshot) host.append(element('p', `Global setting · ${title(snapshot.global_mode)} · ${admissionSummary(snapshot)}`, 'helper'));
  const hostFacts = element('dl', undefined, 'facts host-facts');
  hostFacts.append(description('Gate', snapshot ? title(snapshot.gate_status) : 'Unconfirmed'), description('Execution', snapshot ? title(snapshot.execution.state) : 'Unknown'), description('Active', snapshot ? count(snapshot.execution.active_count) : 'Unknown'));
  host.append(hostFacts);
  if (snapshot?.execution.reason || snapshot?.gate_reason) host.append(element('p', title(snapshot.execution.reason ?? snapshot.gate_reason!), 'reason'));
  main.append(host);

  const limits = element('section', undefined, 'capability-note');
  limits.append(icon('ⓘ'), element('p', 'Native continuation is unavailable. Start and Resume allow eligible Hydra work; they do not start Codex turns or change external schedules.'));
  main.append(limits);
  const live = element('div', undefined, 'feedback'); live.setAttribute('aria-live', 'polite'); live.setAttribute('role', 'status');
  if (feedback.error) { const p = element('p', undefined, 'error'); p.append(icon('!'), element('span', feedback.error)); live.append(p); }
  else if (notice) live.append(element('p', notice, 'notice'));
  if (snapshot && isStale(snapshot)) { const p = element('p', undefined, 'stale'); p.append(icon('◷'), element('span', 'Local observation is stale. Refresh before enabling new work.')); live.append(p); }
  main.append(live);

  const section = element('section', undefined, 'projects'); section.setAttribute('aria-label', 'Registered projects');
  const sectionHeader = element('div', undefined, 'section-heading');
  sectionHeader.append(element('h2', snapshot ? `Projects · ${snapshot.projects.length}` : 'Projects'));
  const refreshButton = button(remoteBusy ? 'Refreshing…' : 'Refresh GitHub', () => { void refresh(true, true); }, 'link', '↻'); refreshButton.disabled = remoteBusy || quitting; refreshButton.setAttribute('aria-label', 'Refresh GitHub');
  sectionHeader.append(refreshButton); section.append(sectionHeader);
  if (snapshot?.projects.length) for (const project of snapshot.projects) section.append(projectCard(project));
  else section.append(element('p', snapshot ? 'No registered projects are available.' : 'Waiting for a validated host observation. Controls remain disabled.', 'empty'));
  main.append(section); fragment.append(main);

  const footer = element('footer');
  const health = element('div', undefined, 'health');
  health.append(element('p', `Local · ${formatTime(snapshot?.observed_at ?? null)}${snapshot?.revision !== null && snapshot ? ` · revision ${snapshot.revision}` : ''}`));
  health.append(element('p', `Coverage · ${snapshot?.coverage.state === 'confirmed' ? 'Confirmed' : 'Unverified'} · GitHub ${remoteLabel()}`));
  if (snapshot?.coverage.reason) health.append(element('p', title(snapshot.coverage.reason), 'coverage-reason'));
  if (snapshot) {
    const runtime = snapshot.runtime;
    health.append(element('p', `Runtime · ${runtime.version ?? 'version unknown'} · control schema ${snapshot.schema_version}`));
    const identity = element('details', undefined, 'runtime-identity');
    identity.open = runtimeDetailsOpen;
    identity.addEventListener('toggle', () => { if (identity.isConnected) runtimeDetailsOpen = identity.open; });
    const summary = element('summary', 'Reported runtime identity'); summary.setAttribute('aria-label', 'Reported runtime identity'); identity.append(summary);
    for (const [label, value] of [['Package', runtime.package], ['Code SHA-256 at startup', runtime.code_digest], ['Configuration SHA-256', runtime.config_digest], ['Control binding SHA-256', runtime.control_binding_digest]]) identity.append(element('p', `${label} · ${value ?? 'unavailable'}`));
    if (runtime.identity_reason) identity.append(element('p', title(runtime.identity_reason)));
    identity.append(element('p', 'Identity is observation metadata. It does not qualify this installation, schedule coverage or native control.'));
    health.append(identity);
  }
  const footerActions = element('div', undefined, 'footer-actions');
  const localRefresh = button(localBusy ? 'Reading…' : 'Refresh', () => { void refresh(false, true); }, 'quiet'); localRefresh.disabled = localBusy || quitting; localRefresh.setAttribute('aria-label', 'Refresh local status');
  const quit = button(quitting ? 'Stopping…' : 'Stop & Quit', () => { void requestQuit(); }, 'quiet'); quit.disabled = quitting || !!pending; quit.setAttribute('aria-label', 'Stop and quit Hydra'); quit.title = snapshot?.quit_reason ? title(snapshot.quit_reason) : 'Request global Stop and quit only after owned execution termination is confirmed.';
  footerActions.append(localRefresh, quit); footer.append(health, footerActions); fragment.append(footer);
  renderingFocus = true;
  try { app.replaceChildren(fragment); restoreFocus(focused ?? null); }
  finally { renderingFocus = false; }
}

render();
void listen<{ state: 'stopping' | 'blocked'; code?: string; status?: unknown }>('hydra:quit', ({ payload }) => {
  if (payload.state === 'stopping' && !quitTicket) quitTicket = observations.begin();
  quitting = payload.state === 'stopping';
  if (payload.status) { try { receive(payload.status, quitTicket ?? observations.begin()); } catch { receiveFailure(new Error('invalid_response')); } }
  if (payload.state === 'blocked') { feedback.show(messages[payload.code ?? 'quit_blocked'] ?? messages.quit_blocked!); notice = ''; }
  else notice = 'Stopping new work and checking owned executions before quitting…';
  if (payload.state === 'blocked') quitTicket = null;
  render();
}).catch(() => { feedback.show('The desktop connection is unavailable. Open the installed Hydra application.'); render(); });
void refresh();
setInterval(() => { if (!pending && !quitting) void refresh(); }, 5_000);
