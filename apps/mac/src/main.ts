import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { acceptSnapshot, actionDisabled, count, displayMode, isStale, parseSnapshot, pendingLabel, title } from './model.ts';
import type { Action, Project, Snapshot, Target } from './model.ts';
import './tokens.css';
import './style.css';

const app = document.querySelector<HTMLDivElement>('#app')!;
let snapshot: Snapshot | null = null;
let remoteSnapshot: Snapshot | null = null;
let pending: { action: Action; target: Target } | null = null;
let localBusy = false;
let remoteBusy = false;
let quitting = false;
let notice = '';
let error = '';
let theme: 'system' | 'light' | 'dark' = 'system';

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
  Array.from(app.querySelectorAll<HTMLButtonElement>('button[aria-label]')).find(node => node.getAttribute('aria-label') === label && !node.disabled)?.focus({ preventScroll: true });
}
function restorePendingFocus(label: string | null): void { if (document.activeElement === document.body) restoreFocus(label); }

const messages: Record<string, string> = {
  launch_configuration_invalid: 'Launch Hydra with an installed runtime and host configuration. No operation has been enabled.',
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
function receiveFailure(value: unknown): void {
  if (value && typeof value === 'object') {
    const e = value as { code?: string; status?: unknown };
    if (e.status) { try { receive(e.status); } catch { /* Keep the last confirmed snapshot. */ } }
    error = messages[e.code ?? ''] ?? 'The operation could not be confirmed. Refresh to reconcile its state.';
  } else {
    const code = value instanceof Error ? value.message : typeof value === 'string' ? value : '';
    error = messages[code] ?? 'The operation could not be confirmed. Refresh to reconcile its state.';
  }
}
function receive(value: unknown): Snapshot {
  const next = parseSnapshot(value);
  if (acceptSnapshot(snapshot, next)) snapshot = next;
  if (next.remote.state !== 'not_requested' && (!remoteSnapshot || Date.parse(next.observed_at) >= Date.parse(remoteSnapshot.observed_at))) remoteSnapshot = next;
  return next;
}

async function refresh(remote = false, manual = false): Promise<void> {
  if (quitting || (remote ? remoteBusy : localBusy)) return;
  const focus = manual ? document.activeElement?.getAttribute('aria-label') ?? null : null;
  if (remote) remoteBusy = true; else localBusy = true;
  render();
  try { receive(await invoke('status', { refresh: remote })); if (manual && !pending) error = ''; }
  catch (value) { receiveFailure(value); }
  finally { if (remote) remoteBusy = false; else localBusy = false; render(); restorePendingFocus(focus); }
}

async function control(action: Action, target: Target): Promise<void> {
  if (actionDisabled(action, target, snapshot, !!pending || quitting)) return;
  pending = { action, target }; error = ''; notice = ''; render();
  try {
    const result = receive(await invoke('control', { action, target }));
    if (result.request?.status === 'applied') {
      notice = action === 'start' || action === 'resume'
        ? `Admission is allowed for ${targetName(target)}. Native continuation remains unavailable.`
        : `The ${action === 'pause' ? 'Pause' : 'Stop'} gate is applied to ${targetName(target)}. Execution confirmation is shown separately.`;
    } else error = result.request?.reason ? title(result.request.reason) : 'This request is held. No enabling change was confirmed.';
  } catch (value) { receiveFailure(value); }
  finally { pending = null; render(); restorePendingFocus(`${title(action)} ${targetName(target)}`); }
}

async function openRecord(repository: string, kind: 'issue' | 'pr' | 'chat'): Promise<void> {
  try { await invoke('open_record', { repository, kind }); }
  catch (value) { receiveFailure(value); render(); }
}

async function requestQuit(): Promise<void> {
  if (quitting || pending) return;
  quitting = true; error = ''; notice = 'Stopping new work and checking owned executions before quitting…'; render();
  try { await invoke('request_quit'); }
  catch (value) { receiveFailure(value); quitting = false; notice = ''; render(); restorePendingFocus('Stop and quit Hydra'); }
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
  const state = pending && equalTarget(pending.target, target) ? pendingLabel(pending.action) : displayMode(project.effective_mode);
  header.append(identity, badge(state, project.effective_mode === 'unknown' ? 'warning' : 'neutral', project.effective_mode === 'running' ? '▷' : project.effective_mode === 'paused' ? 'Ⅱ' : project.effective_mode === 'unknown' ? '?' : '□'));
  card.append(header);
  const facts = element('dl', undefined, 'facts');
  facts.append(description('Admission', project.gate_status === 'allowed' ? 'New work allowed' : project.gate_status === 'blocked' ? 'New work blocked' : 'Unconfirmed'), description('Execution', title(project.execution.state)), description('Active', count(project.execution.active_count)));
  card.append(facts);
  if (project.override_mode && project.override_mode !== 'running') card.append(element('p', `Individual ${project.override_mode === 'paused' ? 'Pause' : 'Stop'} is preserved when all projects resume.`, 'preserved'));
  if (project.execution.reason || project.gate_reason) card.append(element('p', title(project.execution.reason ?? project.gate_reason!), 'reason'));
  const remoteProject = remoteSnapshot?.projects.find(row => row.repository === project.repository);
  const workSource = project.work.length ? project : remoteProject ?? project;
  const work = element('div', undefined, 'work');
  if (workSource.work.length) {
    for (const item of workSource.work.slice(0, 3)) {
      const row = element('div', undefined, 'work-row');
      row.append(element('span', `#${item.issue}`, 'issue-id'), element('span', item.phase ? title(item.phase) : 'Phase unknown'));
      if (item.wait_reason) row.append(element('span', title(item.wait_reason), 'wait-reason'));
      work.append(row);
      if (item.next_action) work.append(element('p', `Next · ${title(item.next_action)}`, 'next-action'));
    }
    if (workSource.work.length > 3) work.append(element('p', `${workSource.work.length - 3} more work records`, 'next-action'));
    if (workSource === remoteProject) work.append(element('p', `◷ GitHub ${remoteLabel()} · ${formatTime(remoteSnapshot!.remote.observed_at)}`, 'evidence-time'));
  } else work.append(element('p', remoteSnapshot?.remote.state === 'fresh' ? 'No work records returned in this observation.' : 'Refresh GitHub to inspect work and wait reasons.', 'empty-work'));
  card.append(work);
  const bottom = element('div', undefined, 'project-bottom');
  bottom.append(controls(target));
  const links = element('div', undefined, 'record-links');
  for (const [kind, text] of [['issue', 'Issue'], ['pr', 'PR'], ['chat', 'Codex']] as const) {
    if (project.links[kind] || remoteProject?.links[kind]) {
      const link = button(`${text} ↗`, () => { void openRecord(project.repository, kind); }, 'link');
      link.setAttribute('aria-label', `Open ${text} for ${project.repository}`); links.append(link);
    }
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
  const label = quitting ? 'Stopping…' : pending?.target.scope === 'all' ? pendingLabel(pending.action) : snapshot ? `Admission ${displayMode(snapshot.global_mode).toLowerCase()}` : 'Unconfirmed';
  const hostSymbol = snapshot?.global_mode === 'running' ? '▷' : snapshot?.global_mode === 'paused' ? 'Ⅱ' : snapshot?.global_mode === 'stopped' ? '□' : '?';
  top.append(hostTitle, badge(label, !snapshot || snapshot.global_mode === 'unknown' ? 'warning' : 'neutral', hostSymbol));
  host.append(top, controls({ scope: 'all' }));
  host.append(element('p', 'Global Resume keeps every individual Pause and Stop.', 'helper'));
  const hostFacts = element('dl', undefined, 'facts host-facts');
  hostFacts.append(description('Gate', snapshot ? title(snapshot.gate_status) : 'Unconfirmed'), description('Execution', snapshot ? title(snapshot.execution.state) : 'Unknown'), description('Active', snapshot ? count(snapshot.execution.active_count) : 'Unknown'));
  host.append(hostFacts);
  if (snapshot?.execution.reason || snapshot?.gate_reason) host.append(element('p', title(snapshot.execution.reason ?? snapshot.gate_reason!), 'reason'));
  main.append(host);

  const limits = element('section', undefined, 'capability-note');
  limits.append(icon('ⓘ'), element('p', 'Native continuation is unavailable. Start and Resume allow eligible Hydra work; they do not start Codex turns or change external schedules.'));
  main.append(limits);
  const live = element('div', undefined, 'feedback'); live.setAttribute('aria-live', 'polite'); live.setAttribute('role', 'status');
  if (error) { const p = element('p', undefined, 'error'); p.append(icon('!'), element('span', error)); live.append(p); }
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
  const footerActions = element('div', undefined, 'footer-actions');
  const localRefresh = button(localBusy ? 'Reading…' : 'Refresh', () => { void refresh(false, true); }, 'quiet'); localRefresh.disabled = localBusy || quitting; localRefresh.setAttribute('aria-label', 'Refresh local status');
  const quit = button(quitting ? 'Stopping…' : 'Stop & Quit', () => { void requestQuit(); }, 'quiet'); quit.disabled = quitting || !!pending; quit.setAttribute('aria-label', 'Stop and quit Hydra'); quit.title = snapshot?.quit_reason ? title(snapshot.quit_reason) : 'Request global Stop and quit only after owned execution termination is confirmed.';
  footerActions.append(localRefresh, quit); footer.append(health, footerActions); fragment.append(footer);
  app.replaceChildren(fragment);
  restoreFocus(focused ?? null);
}

render();
void listen<{ state: 'stopping' | 'blocked'; code?: string; status?: unknown }>('hydra:quit', ({ payload }) => {
  quitting = payload.state === 'stopping';
  if (payload.status) { try { receive(payload.status); } catch { receiveFailure(new Error('invalid_response')); } }
  if (payload.state === 'blocked') { error = messages[payload.code ?? 'quit_blocked'] ?? messages.quit_blocked!; notice = ''; }
  else notice = 'Stopping new work and checking owned executions before quitting…';
  render();
}).catch(() => { error = 'The desktop connection is unavailable. Open the installed Hydra application.'; render(); });
void refresh();
setInterval(() => { if (!pending && !quitting) void refresh(); }, 5_000);
