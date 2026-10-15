import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
const manifestPath = resolve(root, 'src/theme-map.json');
const cssPath = resolve(root, 'src/tokens.css');
const digest = 'c8df61c60f9021a8fa9b4062116cbb067f5d35770345fd2e2468bc7dcd711db3';

function css(manifest) {
  const declarations = (group) => Object.entries(group).map(([key, item]) => `  ${key}: ${item.css};`).join('\n');
  return `/* Canonical resolved theme values. See theme-map.json. */\n:root {\n${declarations(manifest.common)}\n${declarations(manifest.light)}\n}\n@media (prefers-color-scheme: dark) {\n  :root:not([data-theme="light"]) {\n${declarations(manifest.dark)}\n  }\n}\n:root[data-theme="dark"] {\n${declarations(manifest.dark)}\n}\n`;
}

const check = process.argv.includes('--check');
const sourceArg = process.argv.find((arg, index) => index > 1 && arg !== '--check');
let manifest;
if (sourceArg) {
  const bytes = readFileSync(resolve(sourceArg));
  if (createHash('sha256').update(bytes).digest('hex') !== digest) throw Error('Canonical token digest differs; review the token revision first.');
  const source = JSON.parse(bytes);
  const lookup = (path) => path.split('.').reduce((node, key) => node[key], source);
  const entry = (path, field, suffix = '') => {
    const chain = [];
    let token = lookup(path);
    chain.push({ token: path, value: token.$value });
    while (typeof token.$value === 'string' && token.$value.startsWith('{')) {
      path = token.$value.slice(1, -1);
      token = lookup(path);
      chain.push({ token: path, value: token.$value });
    }
    const value = field ? token.$value[field] : token.$value;
    return { chain, ...(field ? { field } : {}), resolved: value, css: `${value}${suffix}` };
  };
  manifest = { schema_version: 1, source: 'OpenBoa design tokens', source_sha256: digest, common: {}, light: {}, dark: {} };
  for (const mode of ['light', 'dark']) {
    for (const [key, path] of Object.entries({
      canvas: 'bg.canvas', surface: 'bg.surface', subtle: 'bg.subtle',
      text: 'text.primary', secondary: 'text.secondary', muted: 'text.muted',
      border: 'border.default', 'border-control': 'border.control',
      accent: 'action.primary', 'accent-hover': 'action.primary.hover',
      'accent-pressed': 'action.primary.pressed', 'on-accent': 'action.on-primary',
      focus: 'focus.ring', 'focus-offset': 'focus.offset',
      selection: 'selection.bg', 'selection-text': 'selection.text',
      warning: 'state.warning', danger: 'state.danger', info: 'state.info',
    })) manifest[mode][`--${key}`] = entry(`themes.${mode}.sys.${path}`);
  }
  for (const n of [0, 2, 4, 6, 8, 12, 16, 20, 24, 32, 40, 48, 64]) manifest.common[`--space-${n}`] = entry(`ref.space.${n}`);
  for (const name of ['xs', 'sm', 'md', 'xl', 'full']) manifest.common[`--radius-${name}`] = entry(`ref.radius.${name}`);
  for (const name of ['thin', 'focusRing', 'focusOffset']) manifest.common[`--border-${name}`] = entry(`ref.border.${name}`);
  for (const name of ['body', 'korean', 'mono']) manifest.common[`--font-${name}`] = entry(`ref.typography.family.${name}`);
  for (const [name, path] of Object.entries({ body: 'body.md', small: 'body.sm', caption: 'caption', heading: 'heading.md', title: 'heading.sm', label: 'label.md', overline: 'overline' })) {
    for (const field of ['size', 'lineHeight', 'tracking', 'weight', 'width']) {
      manifest.common[`--${name}-${field}`] = entry(`ref.typography.styles.${path}`, field, field === 'tracking' ? 'em' : ['size', 'lineHeight'].includes(field) ? 'px' : '');
    }
  }
  manifest.common['--control-height'] = entry('ref.size.component.medium');
  manifest.common['--control-compact'] = entry('ref.size.component.compact');
  if (check) {
    if (JSON.stringify(JSON.parse(readFileSync(manifestPath, 'utf8'))) !== JSON.stringify(manifest)) throw Error('Theme manifest differs from canonical alias resolution.');
  } else writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
} else {
  if (!check) throw Error('Provide the canonical token file explicitly.');
  manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
  if (manifest.source_sha256 !== digest) throw Error('Unexpected token revision.');
  for (const group of ['common', 'light', 'dark']) {
    for (const item of Object.values(manifest[group])) {
      for (let i = 0; i < item.chain.length - 1; i++) {
        if (item.chain[i].value !== `{${item.chain[i + 1].token}}`) throw Error('Broken token alias chain.');
      }
      const leaf = item.chain.at(-1).value;
      if (JSON.stringify(item.field ? leaf[item.field] : leaf) !== JSON.stringify(item.resolved)) throw Error('Incorrect token resolution.');
    }
  }
}
const generated = css(manifest);
if (check) {
  if (readFileSync(cssPath, 'utf8') !== generated) throw Error('CSS differs from reviewed token mapping.');
  process.stdout.write('Theme aliases, resolved values and CSS match.\n');
} else writeFileSync(cssPath, generated);
