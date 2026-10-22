import assert from 'node:assert/strict';
import test from 'node:test';
import { appFixture, noMutations, sourceFrame } from './tower-fixture.ts';

test('an overview cursor cannot become another project continuation', async () => {
  const frame = structuredClone(sourceFrame);
  frame.page.next_cursor = 'fixture-overview-continuation';
  const app = await appFixture(frame);
  try {
    const next = () => app.lifecycle()?.querySelector('[aria-label="Read next source page"]');
    assert.ok(next(), 'The valid overview must expose its original continuation');
    await app.click('Inspect example/beta');
    assert.equal(next(), null, 'A project without its own continuation cannot reuse an overview cursor');
    await app.click('Inspect lifecycle overview');
    assert.ok(next(), 'Returning to the overview retains that continuation');
    noMutations(app.calls);
  } finally { app.close(); }
});
