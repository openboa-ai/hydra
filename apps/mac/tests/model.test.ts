import { test } from 'node:test';
import assert from 'node:assert/strict';
import { acceptSnapshot, actionDisabled, count, isStale, parseSnapshot } from '../src/model.ts';
import type { Snapshot } from '../src/model.ts';

const now = Date.parse('2026-10-12T00:00:00Z');
function snapshot(): Snapshot {
  return {
    schema_version: 1, observed_at: new Date(now).toISOString(), host_alias: 'Test host', revision: 4,
    global_mode: 'paused', gate_status: 'blocked', gate_reason: 'host_paused', native_turn_control: 'unsupported',
    execution: { state: 'unknown', active_count: null, reason: 'native_ownership_unconfirmed' },
    coverage: { state: 'unverified', reason: 'schedule_coverage_unverified' }, can_quit: false,
    quit_reason: 'schedule_coverage_unverified', remote: { state: 'not_requested', observed_at: null },
    projects: [{ repository: 'example/service', override_mode: 'paused', effective_mode: 'paused',
      gate_status: 'blocked', gate_reason: 'host_paused', execution: { state: 'unknown', active_count: null, reason: null },
      work: [], links: { issue: null, pr: null, chat: null } }], request: null,
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
