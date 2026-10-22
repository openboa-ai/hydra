/** Read-side lifecycle views. Source records never authorize an operation. */
import { invoke } from '@tauri-apps/api/core';
import { pollSources, projectedView, projectionState, reduceProjection, retryWait, sourceFresh,
  type ProjectionState } from './projection-state.ts';
import type { Fact, Observation, ProjectionV3, ProjectView, ResourceRef, WorkView } from './projection.ts';

type ReadResponse = { payload: unknown; age_ms: number; cached: boolean; stale: boolean;
  sequence: number; read_context: {scope: string | null; sequence: number} };
const same = (a: ResourceRef | null, b: ResourceRef) =>
  a?.source === b.source && a.kind === b.kind && a.id === b.id;
const label = (value: string) => value.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
function node<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string, className?: string) {
  const result = document.createElement(tag);
  if (text !== undefined) { result.textContent = text; if (/[\u3131-\uD79D]/.test(text)) result.lang = 'ko'; }
  if (className) result.className = className;
  return result;
}
function button(text: string, name: string, act: () => void) {
  const result = node('button', text); result.type = 'button';
  result.setAttribute('aria-label', name); result.addEventListener('click', act); return result;
}
function fact(labelText: string, value: Fact<unknown>, display?: (v: unknown) => string) {
  const field = node('div', undefined, 'tower-fact'); field.append(node('dt', labelText));
  const text = value.value === null ? 'Unconfirmed' : display ? display(value.value) :
    typeof value.value === 'string' ? label(value.value) : 'Source observation';
  field.append(node('dd', text));
  if (value.reason) field.append(node('p', label(value.reason), 'reason'));
  return field;
}
function execution(value: unknown) {
  const state = value as {state: string; active_count: number | null};
  return state.state === 'unobserved' ? 'Unconfirmed' : `${label(state.state)} · ${
    state.active_count === null ? 'active count unconfirmed' : `${state.active_count} observed active`}`;
}

export function mountControlTower(root: HTMLElement): void {
  let state: ProjectionState | null = null;
  type ReadTicket = { remote: boolean; generation: number };
  let sequence = 0;
  let localBusy: ReadTicket | null = null, remoteBusy: ReadTicket | null = null;
  const pendingReads = new Set<ReadTicket>();
  let lastLocal = 0, lastRemote = 0, previousTick = Date.now();
  let notice = '', focusVersion = 0, restoringFocus = false;
  let readGeneration = 0, clockBusy = false, clockBlocked = false;
  function releaseReadGeneration() {
    readGeneration += 1; localBusy = null; remoteBusy = null;
    // Fenced IPCs remain accounted for until their actual promises settle.
  }
  const readFailures = new Map<string, string>();
  let omittedReadFailures = false;
  function clearReadFailures() { readFailures.clear(); omittedReadFailures = false; }
  function failRead(scope: string, message: string) {
    if (!readFailures.has(scope) && readFailures.size >= 16) {
      readFailures.delete(readFailures.keys().next().value!); omittedReadFailures = true;
    }
    readFailures.set(scope, message);
  }
  const supersedeFocus = () => { if (!restoringFocus) focusVersion += 1; };
  document.addEventListener('pointerdown', supersedeFocus, true);
  document.addEventListener('keydown', supersedeFocus, true);
  document.addEventListener('focusin', supersedeFocus, true);
  window.addEventListener('blur', supersedeFocus);
  function restoreFocus(name: string | null | undefined, version: number) {
    if (!name || version !== focusVersion || document.activeElement !== document.body) return;
    const next = [...root.querySelectorAll<HTMLButtonElement>('button[aria-label]')]
      .find(n => n.getAttribute('aria-label') === name && !n.disabled);
    restoringFocus = true;
    try { next?.focus({preventScroll: true}); } finally { restoringFocus = false; }
  }
  async function recoverClock(): Promise<boolean> {
    if (clockBusy) return false;
    const generation = readGeneration;
    clockBusy = true; render();
    try {
      await invoke('projection_clock_resumed');
      if (generation !== readGeneration) return false;
      clockBlocked = false; return true;
    } catch {
      if (generation === readGeneration)
        notice = 'Source refresh unavailable after clock resume. Refresh explicitly to recover.';
      return false;
    } finally {
      clockBusy = false; render();
      if (generation !== readGeneration && clockBlocked)
        void recoverClock().then(ok => { if (ok) void read(false); });
    }
  }

  function repository(ref: ResourceRef | null): string | null {
    return ref ? ref.kind === 'repository' ? ref.id : ref.kind === 'issue' ? ref.id.split(':')[0]! : null : null;
  }
  function metadata(view: ProjectionV3, ref: ResourceRef): Observation | undefined {
    return view.observations.find(o => same(o.resource, ref));
  }
  function repositoryName(view: ProjectionV3, id: string): string | null {
    const value = metadata(view, {source: 'github', kind: 'repository', id})?.value;
    return typeof value?.full_name === 'string' ? value.full_name : null;
  }
  function readAddress(view: ProjectionV3, id: string): string | null {
    // Requested aliases are validated read addresses, never numeric command targets.
    const name = repositoryName(view, id) ?? (id.startsWith('requested:') ? id.slice(10) : null);
    const normalized = name?.toLowerCase();
    return normalized && /^[a-z0-9][a-z0-9-]{0,38}\/[a-z0-9_.-]{1,100}$/.test(normalized) ? normalized : null;
  }
  function projectName(view: ProjectionV3, project: ProjectView) {
    return repositoryName(view, project.repository_ref.id) ?? readAddress(view, project.repository_ref.id) ?? `Repository ${project.repository_ref.id}`;
  }
  function select(ref: ResourceRef | null) {
    if (!state) return;
    state = reduceProjection(state, {type: 'selection_changed', selected_ref: ref}); render();
  }
  function wait(now = Date.now()) {
    return state ? retryWait(state, 'github', state.read_context.scope ?? '', now) :
      {seconds: 0, explicit_recovery: false, basis: null};
  }
  async function read(remote: boolean, manual = false, cursor: string | null = null) {
    if (clockBusy || (remote ? remoteBusy : localBusy)) return;
    if (clockBlocked && (!manual || !await recoverClock())) return;
    if (!manual && document.visibilityState === 'hidden') return;
    if (remote && !manual && (wait().seconds > 0 || wait().explicit_recovery)) return;
    if ([...pendingReads].filter(ticket => ticket.remote === remote).length >= 2) {
      notice = 'Prior source reads are still being reconciled. Retry when they settle.'; render(); return;
    }
    const ticket: ReadTicket = {remote, generation: readGeneration};
    pendingReads.add(ticket);
    if (remote) { remoteBusy = ticket; lastRemote = Date.now(); }
    else { localBusy = ticket; lastLocal = Date.now(); }
    const generation = ticket.generation;
    const focused = root.contains(document.activeElement) ? document.activeElement?.getAttribute('aria-label') : null;
    const focusIntent = focusVersion;
    const selected = state?.selected_ref ?? null;
    const id = remote ? repository(selected) : null;
    const oldEpoch = state?.binding_epoch;
    const view = state ? projectedView(state, Date.now()) : null;
    const name = id && view ? readAddress(view, id) : null;
    const scope = `${remote ? 'github' : 'local'}:${name ?? id ?? 'overview'}:${cursor ? 'page' : 'first'}`;
    const readTarget = id && view ? repositoryName(view, id) ?? name ?? 'selected project' : 'overview';
    const unavailable = `${remote ? 'GitHub' : 'Local'} ${readTarget}${cursor ? ' continuation' : ''} refresh unavailable. Prior observations are retained with uncertainty.`;
    let epoch: string | undefined, requestSequence = 0, bindingConfirmed = false;
    render();
    try {
      epoch = await invoke<string>('projection_binding');
      if (generation !== readGeneration || (state && oldEpoch !== undefined && state.binding_epoch !== oldEpoch)) return;
      const bound = projectionState(epoch);
      if (!state) state = bound;
      else if (state.binding_epoch !== epoch) {
        state = reduceProjection(state, {type: 'binding_changed', binding_epoch: epoch});
        state = reduceProjection(state, {type: 'selection_changed', selected_ref: null});
        releaseReadGeneration(); clearReadFailures();
        notice = 'Connection changed. Previous source data and selection were cleared. Refresh to inspect the current connection.';
        return;
      }
      bindingConfirmed = true;
      if (id && !name) { failRead(scope, unavailable + ' Repository identity is unconfirmed.'); return; }
      requestSequence = ++sequence;
      const requestId = crypto.randomUUID();
      const keys = cursor ? [] : [...state.source_slots].filter(([,slot]) =>
        slot.observation.resource.source === (remote ? 'github' : 'hydra') &&
        (!id || slot.observation.resource.id === id || slot.observation.resource.id.startsWith(id + ':')))
        .map(([key]) => key);
      state = reduceProjection(state, {type: 'read_started', scope, sequence: requestSequence,
        request_id: requestId, observation_keys: keys});
      const response = await invoke<ReadResponse>('projection_status', {epoch, requestId, refresh: remote,
        repository: name, cursor, explicitRecovery: manual});
      if (generation !== readGeneration || state.binding_epoch !== epoch) return;
      const previousRuntime = state.runtime_key;
      state = reduceProjection(state, {type: 'read_succeeded', scope, sequence: requestSequence,
        now: Date.now(), response});
      if (previousRuntime !== null && state.runtime_key !== previousRuntime) {
        releaseReadGeneration(); clearReadFailures();
      }
      if (state.error) failRead(scope, unavailable);
      else if (!response.cached && !response.stale) {
        readFailures.delete(scope); if (manual) notice = '';
      }
    } catch {
      // Bridge error text may contain private paths or provider output.
      if (generation !== readGeneration) return;
      if (!bindingConfirmed) {
        releaseReadGeneration();
        if (state) state = reduceProjection(state, {type: 'binding_unavailable', now: Date.now()});
        failRead(scope, unavailable);
      } else if (state && epoch === state.binding_epoch) {
        if (requestSequence > 0)
          state = reduceProjection(state, {type: 'read_failed', scope, sequence: requestSequence, reason: 'read_unavailable'});
        failRead(scope, unavailable);
      }
    } finally {
      pendingReads.delete(ticket);
      if (remote && remoteBusy === ticket) remoteBusy = null;
      if (!remote && localBusy === ticket) localBusy = null;
      render(); if (generation === readGeneration) restoreFocus(focused, focusIntent);
    }
  }
  function coverage(parent: HTMLElement, view: {coverage: ProjectView['coverage']}) {
    const c = view.coverage;
    parent.append(node('p', `${label(c.state)} coverage · ${c.returned_count} observed work references${
      c.total_count === null ? ' · total unconfirmed' : ` of ${c.total_count}`}`, 'tower-coverage'));
    if (c.reason) parent.append(node('p', label(c.reason), 'reason'));
  }
  function goals(parent: HTMLElement, view: ProjectionV3, project: ProjectView) {
    parent.append(node('h3', 'Delegated goals'));
    if (!project.goal_refs.length) parent.append(node('p', 'No goal references in this observation. Goal completion is unconfirmed.', 'helper'));
    for (const goal of project.goal_refs)
      parent.append(node('p', `${repositoryName(view, String(goal.repository_id)) ?? `Repository ${goal.repository_id}`} · Goal #${goal.issue_number} · outcome unconfirmed`, 'tower-goal'));
  }
  function facts(parent: HTMLElement, fields: HTMLElement[]) {
    const dl = node('dl', undefined, 'tower-facts'); dl.append(...fields); parent.append(dl);
  }
  function sourceStatus(parent: HTMLElement, view: ProjectionV3, refs: ResourceRef[]) {
    const section = node('details', undefined, 'tower-sources'); section.append(node('summary', 'Source evidence'));
    const observed = view.observations.filter(o => refs.some(ref => same(ref, o.resource)));
    if (!observed.length) section.append(node('p', 'Source details are unconfirmed.', 'helper'));
    for (const o of observed) {
      const current = state !== null && sourceFresh(state, o.key, Date.now());
      const row = node('p', `${label(o.resource.source)} / ${label(o.resource.kind)} · ${
        current ? label(o.availability) : 'Stale or unavailable'} · ${label(o.coverage.state)} coverage`, 'helper');
      section.append(row);
      if (o.observed_at) section.append(node('p', `Observed ${o.observed_at}`, 'evidence-time'));
      if (o.reason) section.append(node('p', label(o.reason), 'reason'));
    }
    parent.append(section);
  }
  function originalButton(parent: HTMLElement, view: ProjectionV3, ref: ResourceRef) {
    const source = metadata(view, ref), id = repository(ref), name = id ? repositoryName(view, id) : null;
    if (ref.source !== 'github' || ref.kind !== 'issue' || !source || !name) return;
    const issue = Number(ref.id.split(':')[1]);
    const open = button('Open original issue', 'Open original issue', () => {
      // The native bridge re-reads and validates this exact Issue before opening it.
      void invoke('open_record', {repository: name.toLowerCase(), kind: 'issue', issue, expectedPr: null})
        .catch(() => { notice = 'The original source could not be opened. Refresh to reconcile it.'; render(); });
    });
    const repoSource = metadata(view, {source: 'github', kind: 'repository', id: id!});
    open.disabled = !state || !sourceFresh(state, source.key, Date.now()) ||
      !repoSource || !sourceFresh(state, repoSource.key, Date.now());
    parent.append(open);
  }
  function workDetail(parent: HTMLElement, view: ProjectionV3, work: WorkView) {
    const source = metadata(view, work.issue_ref);
    const title = source?.value?.title;
    parent.append(node('h2', typeof title === 'string' ? title : 'Work source unconfirmed'));
    const original = node('section', undefined, 'tower-original'); original.append(node('h3', 'Original request'));
    const excerpt = source?.value?.description_excerpt;
    original.append(node('p', typeof excerpt === 'string' ? excerpt : 'Original text is unavailable in this observation.'));
    if (source?.value?.description_truncated) original.append(node('p', 'Excerpt truncated. Open the original for the complete request.', 'helper'));
    originalButton(original, view, work.issue_ref); parent.append(original);
    facts(parent, [fact('Readiness', work.readiness, v => label(String((v as {disposition: string}).disposition))),
      fact('Stage', work.stage), fact('Admission', work.admission), fact('Execution', work.execution, execution),
      fact('Wait', work.wait), fact('Question', work.decision.question), fact('Answer received', work.decision.answer),
      fact('Answer accepted', work.decision.acceptance), fact('Decision applied', work.decision.application),
      fact('Delivery', work.delivery), fact('Outcome', work.result), fact('Cleanup', work.cleanup),
      fact('Next action', work.next_action)]);
    if (work.readiness.value) {
      const readiness = work.readiness.value;
      parent.append(node('p', `Authority · ${label(String(readiness.authority))}. Readiness is a source interpretation, not permission to run.`, 'helper'));
      const missing = readiness.missing as {code: string; detail: string}[];
      for (const item of missing) parent.append(node('p', `${label(item.code)} · ${item.detail}`, 'helper'));
    }
    const links = node('section', undefined, 'tower-references'); links.append(node('h3', 'Design and verification'));
    if (!work.spec_refs.length && !work.requirement_refs.length)
      links.append(node('p', 'No design or requirement references in this observation.', 'helper'));
    for (const ref of [...work.spec_refs, ...work.requirement_refs])
      links.append(node('p', `${ref.path} · ${ref.selector} · revision ${ref.revision}`, 'helper'));
    links.append(node('p', `${work.evidence_refs.length} evidence references · ${work.task_refs.length} task references · ${work.resource_refs.length} resource references`, 'helper'));
    parent.append(links);
    const keys = new Set([work.issue_ref, ...work.task_refs, ...work.resource_refs].map(r => JSON.stringify(r)));
    for (const e of work.evidence_refs) {
      const o = view.observations.find(o => o.key === e.observation_key); if (o) keys.add(JSON.stringify(o.resource));
    }
    sourceStatus(parent, view, [...keys].map(k => JSON.parse(k) as ResourceRef));
  }
  function projectDetail(parent: HTMLElement, view: ProjectionV3, project: ProjectView) {
    const name = projectName(view, project);
    parent.append(node('h2', name)); coverage(parent, project); goals(parent, view, project);
    facts(parent, [fact('Admission', project.admission), fact('Execution', project.execution, execution)]);
    parent.append(node('h3', 'Observed work'));
    if (!project.work_refs.length) parent.append(node('p', 'No work references in this observation. Execution and completion remain unconfirmed.', 'helper'));
    for (const ref of project.work_refs) {
      const number = ref.id.split(':')[1]; const work = view.work.find(w => same(w.issue_ref, ref));
      const title = metadata(view, ref)?.value?.title;
      const row = node('div', undefined, 'tower-work');
      const inspect = button(`#${number}${typeof title === 'string' ? ' · ' + title : ''}`,
        `Inspect work #${number} in ${name}`, () => { select(ref); });
      inspect.disabled = !work; row.append(inspect);
      if (!work) row.append(node('p', 'Work details were not returned. Refresh this project to request them.', 'helper'));
      parent.append(row);
    }
    sourceStatus(parent, view, [project.repository_ref, ...project.source_refs]);
  }
  function render() {
    const focused = root.contains(document.activeElement) ? document.activeElement?.getAttribute('aria-label') : null;
    const interaction = focusVersion;
    const fragment = document.createDocumentFragment();
    const header = node('header', undefined, 'tower-header');
    const identity = node('div'); identity.append(node('p', 'HYDRA', 'eyebrow'), node('h1', 'Work lifecycle'));
    const refresh = button(remoteBusy ? 'Refreshing…' : 'Refresh sources', 'Refresh workflow sources', () => { void read(true, true); });
    refresh.disabled = remoteBusy !== null || clockBusy; header.append(identity, refresh); fragment.append(header);
    const messages = [notice, ...readFailures.values(), omittedReadFailures ?
      'Earlier read failures remain unconfirmed outside this bounded view. Inspect their sources to reconcile them.' : ''];
    const status = node('p', messages.filter(Boolean).join(' '), 'tower-status'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    fragment.append(status);
    const view = state ? projectedView(state, Date.now()) : null;
    if (!view) fragment.append(node('p', state ? 'Workflow sources are unconfirmed. Refresh to inspect them.' : 'Reading workflow sources…', 'empty'));
    else {
      const layout = node('div', undefined, 'tower-layout');
      const navigation = node('nav', undefined, 'tower-navigation'); navigation.setAttribute('aria-label', 'Lifecycle projects');
      navigation.append(button('Overview', 'Inspect lifecycle overview', () => { select(null); }));
      for (const project of view.projects) {
        const item = button(projectName(view, project), `Inspect ${projectName(view, project)}`, () => { select(project.repository_ref); });
        if (repository(state!.selected_ref) === project.repository_ref.id) item.setAttribute('aria-current', 'page');
        navigation.append(item);
      }
      const detail = node('div', undefined, 'tower-detail');
      const selected = state!.selected_ref;
      const work = selected?.kind === 'issue' ? view.work.find(w => same(selected, w.issue_ref)) : null;
      const project = view.projects.find(p => p.repository_ref.id === repository(selected));
      if (work) workDetail(detail, view, work);
      else if (project) projectDetail(detail, view, project);
      else {
        detail.append(node('h2', 'Projects and delegated goals'));
        detail.append(node('p', `${label(view.page.state)} observation · ${view.projects.length} observed projects. Observations do not establish goal completion.`, 'helper'));
        if (!view.projects.length) detail.append(node('p', 'No projects in this observation. Host activity and coverage remain unconfirmed.', 'empty'));
        for (const p of view.projects) {
          const card = node('section', undefined, 'tower-project'); card.append(node('h3', projectName(view, p)));
          coverage(card, p); goals(card, view, p);
          facts(card, [fact('Admission', p.admission), fact('Execution', p.execution, execution)]);
          card.append(button('Inspect project', `Inspect project details for ${projectName(view, p)}`, () => { select(p.repository_ref); }));
          detail.append(card);
        }
      }
      const cursor = project ? project.coverage.next_cursor : view.page.next_cursor;
      if (cursor) {
        const more = button('Read next source page', 'Read next source page', () => { void read(true, true, cursor); });
        more.disabled = remoteBusy !== null; detail.append(more);
      }
      const retry = wait();
      if (retry.seconds || retry.explicit_recovery) detail.append(node('p', retry.seconds ?
        `Source retry is held for ${retry.seconds} seconds.` : 'Automatic source retry is held. Refresh explicitly to recover.', 'helper'));
      layout.append(navigation, detail); fragment.append(layout);
      fragment.append(node('p', 'Read-only lifecycle view. Questions, answers and execution stay in their original systems. Additional controls require a qualified command path.', 'tower-boundary'));
    }
    root.setAttribute('aria-busy', String(localBusy !== null || remoteBusy !== null)); root.replaceChildren(fragment);
    restoreFocus(focused, interaction);
  }
  function tick() {
    const now = Date.now();
    if (now < previousTick || now - previousTick > 15_000) {
      previousTick = now; releaseReadGeneration(); clockBlocked = true;
      if (state) {
        for (const [scope, query] of [...state.queries])
          state = reduceProjection(state, {type: 'read_failed', scope, sequence: query.sequence, reason: 'clock_resumed'});
        state = reduceProjection(state, {type: 'clock_resumed', now});
      }
      notice = 'Clock resumed. Previous source freshness is unconfirmed.';
      void recoverClock().then(ok => { if (ok) void read(false); });
      return;
    }
    previousTick = now;
    const due = pollSources(document.visibilityState !== 'hidden', Math.max(0, now-lastLocal), Math.max(0, now-lastRemote), wait(now).seconds);
    if (due.local) void read(false);
    if (due.remote) void read(true);
    render();
  }
  document.addEventListener('visibilitychange', tick);
  render(); void read(true); setInterval(tick, 5_000);
}
