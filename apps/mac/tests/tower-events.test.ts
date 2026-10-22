import assert from 'node:assert/strict';
import test from 'node:test';
import { appFixture, flush, noMutations } from './tower-fixture.ts';

test('manual refresh returns keyboard focus only when no later interaction owns it', async () => {
  const app = await appFixture(); let finish: (() => void) | undefined;
  try {
    await app.click('Inspect example/alpha');
    app.api.deferred = (args, sequence) => new Promise(resolve => {
      finish = () => resolve(app.cached(args, app.api.frame, sequence));
    });
    const refresh = app.lifecycle()!.querySelector<HTMLButtonElement>('[aria-label="Refresh workflow sources"]')!;
    refresh.focus(); refresh.click(); await flush();
    assert.ok(finish, 'A real bridge read must be pending before focus is checked');
    finish!(); await flush();
    assert.equal(app.document.activeElement?.getAttribute('aria-label'), 'Refresh workflow sources');
    noMutations(app.calls);
  } finally { app.close(); }
});

test('expired source evidence disables original navigation without erasing source text', async () => {
  const app = await appFixture();
  try {
    app.advance(60_001);
    await app.click('Inspect example/alpha'); await app.click('Inspect work #7 in example/alpha');
    const text = app.lifecycle()?.textContent ?? '';
    assert.match(text, /Can you approve and start this task\?/);
    assert.match(text, /Stale or unavailable/);
    const open = app.lifecycle()!.querySelector<HTMLButtonElement>('[aria-label="Open original issue"]')!;
    assert.ok(open, 'The retained source must explain its original navigation');
    assert.equal(open.disabled, true);
    assert.ok(!app.calls.some(c => c.method === 'open_record'));
    noMutations(app.calls);
  } finally { app.close(); }
});

test('a source completion cannot steal keyboard focus from another selected project', async () => {
  const app = await appFixture(); let finish: (() => void) | undefined;
  try {
    await app.click('Inspect example/alpha');
    app.api.deferred = (args, sequence) => new Promise(resolve => {
      finish = () => resolve(app.cached(args, app.api.frame, sequence));
    });
    const refresh = app.lifecycle()!.querySelector<HTMLButtonElement>('[aria-label="Refresh workflow sources"]')!;
    refresh.focus(); refresh.click(); await flush();
    await app.click('Inspect example/beta');
    const beta = app.lifecycle()!.querySelector<HTMLButtonElement>('[aria-label="Inspect example/beta"]')!;
    beta.focus(); assert.ok(finish); finish!(); await flush();
    assert.equal(app.document.activeElement?.getAttribute('aria-label'), 'Inspect example/beta');
    noMutations(app.calls);
  } finally { app.close(); }
});
