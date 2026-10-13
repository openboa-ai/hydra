import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Observations, acceptSnapshot, actionDisabled, admissionSummary, appliedNotice, count, isStale, nextActionLabel, parseSnapshot, runtimeKey, sameRuntime, waitReasonLabel, workRecord } from '../src/model.ts';
import type { Snapshot, Work } from '../src/model.ts';

const now = Date.parse('2026-10-12T00:00:00Z');
function snapshot(): Snapshot {
  return {
    schema_version: 2, observed_at: new Date(now).toISOString(), host_alias: 'Test host', revision: 4,
    runtime: { identity_schema: 1, package: 'openboa-hydra-sdlc', version: '0.2.1',
      code_digest: 'a'.repeat(64), code_digest_scope: 'package_sources_at_startup',
      config_digest: 'b'.repeat(64), control_binding_digest: 'c'.repeat(64), identity_reason: null },
    global_mode: 'paused', gate_status: 'blocked', gate_reason: 'host_paused', native_turn_control: 'unsupported',
    execution: { state: 'unknown', active_count: null, reason: 'native_ownership_unconfirmed' },
    coverage: { state: 'unverified', reason: 'schedule_coverage_unverified' }, can_quit: false,
    quit_reason: 'schedule_coverage_unverified', remote: { state: 'not_requested', observed_at: null },
    projects: [{ repository: 'example/service', override_mode: 'paused', effective_mode: 'paused',
      gate_status: 'blocked', gate_reason: 'host_paused', execution: { state: 'unknown', active_count: null, reason: null },
      work: [], links: { chat: null } }], request: null,
  };
}

test('unobserved work remains unknown, including displayed count', () => {
  const value = parseSnapshot(snapshot());
  assert.equal(value.execution.active_count, null);
  assert.equal(count(value.execution.active_count), 'Unknown');
  assert.equal(value.can_quit, false);
});

test('incomplete or malformed observations are rejected, never filled with success defaults', () => {
  for (const mutate of [
    (value: any) => { delete value.execution.active_count; },
    (value: any) => { value.execution.active_count = '0'; },
    (value: any) => { value.can_quit = 'true'; },
    (value: any) => { value.native_turn_control = 'qualified'; },
    (value: any) => { value.projects.push(value.projects[0]); },
    (value: any) => { value.projects[0].links = {}; },
    (value: any) => { value.projects[0].work = [{ issue: -1, phase: null, wait_reason: null, next_action: null }]; },
    (value: any) => { value.revision = 1.5; },
    (value: any) => { value.observed_at = 'not a time'; },
  ]) { const value = snapshot(); mutate(value); assert.throws(() => parseSnapshot(value), /invalid_response/); }
});

test('slow refresh from before Pause cannot replace its confirmed newer revision', () => {
  const current = snapshot();
  const stale = snapshot(); stale.revision = 3; stale.global_mode = 'running'; stale.observed_at = new Date(now + 1000).toISOString();
  assert.equal(acceptSnapshot(current, stale), false);
  const next = snapshot(); next.revision = 5;
  assert.equal(acceptSnapshot(current, next), true);
});

test('newer unreadable gate is surfaced instead of retaining a previous allowed display', () => {
  const current = snapshot(); current.global_mode = 'running';
  const next = snapshot(); next.revision = null; next.global_mode = 'unknown'; next.observed_at = new Date(now + 1000).toISOString();
  assert.equal(acceptSnapshot(current, next), true);
});

test('a project cannot enable itself under global Pause; all Resume stays available', () => {
  const value = snapshot();
  assert.equal(actionDisabled('resume', { scope: 'project', repository: 'example/service' }, value, false, now), true);
  assert.equal(actionDisabled('resume', { scope: 'all' }, value, false, now), false);
  assert.equal(actionDisabled('stop', { scope: 'project', repository: 'example/service' }, value, false, now), false);
});

test('stale and future-dated observations cannot enable work but can block it', () => {
  for (const at of [now - 16_000, now + 6_000]) {
    const value = snapshot(); value.observed_at = new Date(at).toISOString();
    assert.equal(isStale(value, now), true);
    assert.equal(actionDisabled('start', { scope: 'all' }, value, false, now), true);
    assert.equal(actionDisabled('pause', { scope: 'all' }, value, false, now), false);
  }
});

test('unregistered targets and overlapping mutations are disabled', () => {
  assert.equal(actionDisabled('stop', { scope: 'project', repository: 'other/project' }, snapshot(), false, now), true);
  assert.equal(actionDisabled('stop', { scope: 'all' }, snapshot(), true, now), true);
});

function work(issue = 7, pr = 11): Work {
  return { issue, phase: 'reviewing', wait_reason: 'reviews_pending', next_action: 'observe_reviews',
    links: { issue: `https://github.com/example/service/issues/${issue}`, pr: `https://github.com/example/service/pull/${pr}` } };
}

test('v1 is explicitly unsupported; strict v2 rejects malformed identities and record shapes', () => {
  const legacy: any = snapshot(); legacy.schema_version = 1;
  assert.throws(() => parseSnapshot(legacy), /unsupported_runtime/);
  for (const mutate of [
    (value: any) => { delete value.runtime; },
    (value: any) => { value.runtime.identity_schema = 2; },
    (value: any) => { value.runtime.package = 'other-package'; },
    (value: any) => { value.runtime.code_digest = 'A'.repeat(64); },
    (value: any) => { value.runtime.control_binding_digest = ''; },
    (value: any) => { value.runtime.config_digest = 42; },
    (value: any) => { value.runtime.code_digest_scope = 'qualified'; },
    (value: any) => { value.runtime.identity_reason = 'raw private diagnostic'; },
    (value: any) => { value.runtime.version = '0.2.1\n'; },
    (value: any) => { value.runtime.extra = true; },
    (value: any) => { value.projects[0].links.issue = null; },
    (value: any) => { value.projects[0].work = [work(), work()]; },
    (value: any) => { value.projects[0].work = [work()]; delete value.projects[0].work[0].links.pr; },
    (value: any) => { value.unexpected = true; },
  ]) { const value = snapshot(); mutate(value); assert.throws(() => parseSnapshot(value), /invalid_response/); }
});

test('nullable identity stays unavailable and never qualifies control coverage', () => {
  const value = snapshot(); value.runtime.code_digest = null; value.runtime.identity_reason = 'source_unavailable';
  assert.equal(parseSnapshot(value).runtime.code_digest, null);
  assert.equal(runtimeKey(value.runtime), null);
  assert.equal(sameRuntime(value.runtime, value.runtime), false);
  assert.equal(value.coverage.state, 'unverified');
  assert.equal(value.can_quit, false);
});

test('matching identity retains separate remote work through local polling', () => {
  const observations = new Observations();
  const first = snapshot(); first.remote = { state: 'fresh', observed_at: first.observed_at }; first.projects[0]!.work = [work()];
  assert.equal(observations.accept(first, observations.begin()), true);
  const local = snapshot(); local.observed_at = new Date(now + 1000).toISOString();
  assert.equal(observations.accept(local, observations.begin()), true);
  assert.equal(observations.remote, first);
  assert.equal(observations.snapshot, local);
});

test('changed runtime, config, or binding clears remote cache and accepts its own lower revision', () => {
  for (const field of ['code_digest', 'config_digest', 'control_binding_digest'] as const) {
    const observations = new Observations();
    const old = snapshot(); old.remote = { state: 'fresh', observed_at: old.observed_at }; old.projects[0]!.work = [work()];
    observations.accept(old, observations.begin());
    const next = snapshot(); next.runtime[field] = 'd'.repeat(64); next.revision = 1;
    assert.equal(observations.accept(next, observations.begin()), true);
    assert.equal(observations.snapshot, next);
    assert.equal(observations.remote, null);
  }
});

test('late response cannot restore the runtime identity replaced while it was in flight', () => {
  const observations = new Observations(); observations.accept(snapshot(), observations.begin());
  const oldRequest = observations.begin();
  const newRequest = observations.begin();
  const next = snapshot(); next.runtime.config_digest = 'd'.repeat(64); next.revision = 1;
  assert.equal(observations.accept(next, newRequest), true);
  const late = snapshot(); late.revision = 99; late.observed_at = new Date(now + 20_000).toISOString(); late.remote = { state: 'fresh', observed_at: late.observed_at };
  assert.equal(observations.accept(late, oldRequest), false);
  assert.equal(observations.snapshot, next);
  assert.equal(observations.remote, null);
});

test('a request older than a newer accepted observation cannot switch its identity', () => {
  const observations = new Observations(); observations.accept(snapshot(), observations.begin());
  const oldRequest = observations.begin(); const recentRequest = observations.begin();
  const recent = snapshot(); recent.revision = 5; observations.accept(recent, recentRequest);
  const old = snapshot(); old.runtime.code_digest = 'd'.repeat(64);
  assert.equal(observations.accept(old, oldRequest), false);
  assert.equal(observations.snapshot, recent);
});

test('unknown identities do not merge cached observations, even when their null fields match', () => {
  const observations = new Observations();
  const remote = snapshot(); remote.runtime.config_digest = null; remote.remote = { state: 'fresh', observed_at: remote.observed_at };
  observations.accept(remote, observations.begin());
  const local = snapshot(); local.runtime.config_digest = null;
  assert.equal(observations.accept(local, observations.begin()), true);
  assert.equal(observations.remote, null);
});

test('unsupported runtime invalidation removes cached work and fences already pending reads', () => {
  const observations = new Observations(); observations.accept(snapshot(), observations.begin());
  const pending = observations.begin(); observations.invalidate(observations.begin());
  assert.equal(observations.snapshot, null);
  assert.equal(observations.remote, null);
  assert.equal(observations.accept(snapshot(), pending), false);
});

test('an old incompatible-runtime failure cannot erase a newer successful v2 observation', () => {
  const observations = new Observations(); observations.accept(snapshot(), observations.begin());
  const oldRequest = observations.begin(); const recentRequest = observations.begin();
  const recent = snapshot(); recent.revision = 5;
  assert.equal(observations.accept(recent, recentRequest), true);
  assert.equal(observations.invalidate(oldRequest), false);
  assert.equal(observations.snapshot, recent);
  assert.equal(observations.invalidate(observations.begin()), true);
  assert.equal(observations.snapshot, null);
});

test('decision context provenance is not presented as an executable next action', () => {
  const marker = 'decision_context_11111111-2222-4333-8444-555555555555';
  assert.equal(nextActionLabel(marker), 'Continue with the recorded decision context');
  assert.doesNotMatch(nextActionLabel(marker), /await|waiting/i);
  assert.doesNotMatch(nextActionLabel(marker), /decision_context|11111111/);
  assert.equal(nextActionLabel('diagnose_post_merge_failure'), 'Diagnose post merge failure');
});

test('legacy and current native wait reasons do not assert observed execution', () => {
  for (const reason of ['native_task_active', 'native_assignment_pending']) {
    assert.equal(waitReasonLabel(reason), 'Awaiting checkpoint; execution unconfirmed');
    assert.doesNotMatch(waitReasonLabel(reason), /active|running|stopped/i);
  }
  assert.equal(waitReasonLabel('reviews_pending'), 'Reviews pending');
});

test('unknown admission disables enabling without disabling blocking or conflating execution coverage', () => {
  for (const mutate of [
    (value: Snapshot) => { value.gate_status = 'unknown'; },
    (value: Snapshot) => { value.projects[0]!.gate_status = 'unknown'; },
    (value: Snapshot) => { value.projects[0]!.effective_mode = 'unknown'; },
  ]) {
    const value = snapshot(); value.global_mode = 'running'; value.gate_status = 'allowed'; mutate(value);
    const target = { scope: 'project' as const, repository: 'example/service' };
    assert.equal(actionDisabled('start', target, value, false, now), true);
    assert.equal(actionDisabled('resume', target, value, false, now), true);
    assert.equal(actionDisabled('pause', target, value, false, now), false);
    assert.equal(actionDisabled('stop', target, value, false, now), false);
  }
  const value = snapshot(); value.global_mode = 'running'; value.gate_status = 'unknown';
  assert.equal(actionDisabled('resume', { scope: 'all' }, value, false, now), true);
  value.gate_status = 'allowed';
  assert.equal(value.execution.state, 'unknown'); assert.equal(value.coverage.state, 'unverified');
  assert.equal(actionDisabled('resume', { scope: 'project', repository: 'example/service' }, value, false, now), false);
});

test('global Resume reports actual allowed/blocked project counts and preserved overrides', () => {
  const value = snapshot(); value.global_mode = 'running'; value.gate_status = 'allowed';
  const paused = value.projects[0]!;
  value.projects.push({ ...paused, repository: 'example/other', override_mode: null, effective_mode: 'running', gate_status: 'allowed', gate_reason: null });
  assert.equal(admissionSummary(value), '1 allowed · 1 blocked · 0 unconfirmed');
  const notice = appliedNotice('resume', { scope: 'all' }, value);
  assert.match(notice, /1 allowed · 1 blocked/);
  assert.match(notice, /Individual settings are preserved/);
  assert.doesNotMatch(notice, /allowed for all projects/);
  assert.match(appliedNotice('resume', { scope: 'project', repository: 'example/service' }, value), /New work is blocked/);
});

test('each work record sends its own Issue and pins the observed PR number', () => {
  const first = work(7, 11); const second = work(8, 12);
  assert.deepEqual(workRecord('example/service', first, 'issue'), { repository: 'example/service', kind: 'issue', issue: 7, expectedPr: null });
  assert.deepEqual(workRecord('example/service', first, 'pr'), { repository: 'example/service', kind: 'pr', issue: 7, expectedPr: 11 });
  assert.deepEqual(workRecord('example/service', second, 'pr'), { repository: 'example/service', kind: 'pr', issue: 8, expectedPr: 12 });
  assert.equal(workRecord('example/other', first, 'pr'), null);
  first.links.issue = 'https://github.com/example/service/issues/8';
  assert.equal(workRecord('example/service', first, 'issue'), null);
  for (const tail of ['11?redirect=1', '11/extra', '0', '01', '9007199254740992']) {
    first.links.pr = `https://github.com/example/service/pull/${tail}`;
    assert.equal(workRecord('example/service', first, 'pr'), null);
  }
});
