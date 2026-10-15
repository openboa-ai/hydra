import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';

const root = new URL('../', import.meta.url);
const mapping = JSON.parse(readFileSync(new URL('src/theme-map.json', root), 'utf8'));
const css = readFileSync(new URL('src/tokens.css', root), 'utf8');

test('theme mappings retain canonical alias chains and actual emitted values', () => {
  assert.equal(mapping.source_sha256, 'c8df61c60f9021a8fa9b4062116cbb067f5d35770345fd2e2468bc7dcd711db3');
  for (const group of ['light', 'dark', 'common']) for (const [name, value] of Object.entries(mapping[group]) as [string, any][]) {
    for (let i = 0; i < value.chain.length - 1; i++) assert.equal(value.chain[i].value, `{${value.chain[i + 1].token}}`);
    const leaf = value.chain.at(-1).value;
    assert.deepEqual(value.resolved, value.field ? leaf[value.field] : leaf);
    assert.ok(css.includes(`${name}: ${value.css};`), name);
  }
  assert.equal(mapping.light['--canvas'].resolved, '#F8F8F5');
  assert.equal(mapping.dark['--canvas'].resolved, '#111820');
  assert.equal(mapping.common['--body-weight'].resolved, 450);
  assert.equal(mapping.common['--heading-width'].resolved, 96);
});

test('used fonts are local, original assets with their required licenses', () => {
  const fonts = JSON.parse(readFileSync(new URL('public/fonts/manifest.json', root), 'utf8'));
  for (const entry of fonts.assets) {
    const bytes = readFileSync(new URL(`public/fonts/${entry.file}`, root));
    assert.equal(createHash('sha256').update(bytes).digest('hex'), entry.sha256);
    assert.ok(existsSync(new URL(`public/fonts/${entry.license}`, root)));
  }
  const styles = readFileSync(new URL('src/style.css', root), 'utf8');
  assert.ok(styles.includes("url('/fonts/MartianGrotesk-wdth-wght.ttf')"));
  assert.ok(styles.includes("url('/fonts/PretendardVariable.woff2')"));
  assert.equal(/https?:/.test(styles), false);
});
