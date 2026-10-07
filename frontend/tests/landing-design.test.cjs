const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function fixture() {
  const state = [];
  let cursor = 0;
  const exports = {};
  const source = fs.readFileSync(path.join(__dirname, '../src/features/landing/landing-page.tsx'), 'utf8');
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const jsx = { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
  vm.runInNewContext(code, { exports, require(name) {
    if (name === 'react/jsx-runtime') return jsx;
    if (name === 'react') return { useState(initial) {
      const index = cursor++;
      if (!(index in state)) state[index] = initial;
      return [state[index], value => { state[index] = typeof value === 'function' ? value(state[index]) : value; }];
    } };
    if (name === 'next/link') return { default: 'a' };
    if (name === '@/components/brand-mark') return { BrandMark: 'brand-mark' };
    if (name === '@/components/language-selector') return { LanguageSelector: 'language-selector' };
    if (name === '@/i18n/provider') return { useI18n: () => ({ t: key => key, label: key => key }) };
    if (name === '@/components/icons') return { Icon: 'icon' };
    if (name === '@/components/landing-motion') return { LandingMotion: 'landing-motion' };
    // Any network/data dependency would turn an example into a live product action.
    throw new Error(`Unexpected landing dependency: ${name}`);
  } });
  return { render() { cursor = 0; return exports.default(); } };
}
function nodes(node) {
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(nodes);
  return [node, ...nodes(node.props?.children)];
}
function text(node) {
  if (node == null || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(text).join('');
  return text(node.props?.children);
}
function button(tree, label) {
  const result = nodes(tree).find(node => node.type === 'button' && text(node) === label);
  assert.ok(result, `Missing button: ${label}`);
  return result;
}
function panel(tree) { return nodes(tree).find(node => node.props?.role === 'tabpanel'); }

test('sample filters change the displayed insight and its evidence together', () => {
  const app = fixture();
  let tree = app.render();
  const riskTitle = text(nodes(tree).find(node => node.props?.className === 'landing-demo-insight'));
  button(tree, 'Patterns').props.onClick();
  tree = app.render();
  const pattern = nodes(tree).find(node => node.props?.className === 'landing-demo-insight');
  assert.notEqual(text(pattern), riskTitle);
  assert.ok(text(pattern).includes('Two interviews'));
  const evidence = nodes(pattern).find(node => node.props?.className === 'landing-evidence-button');
  assert.equal(evidence.props['aria-expanded'], false);
  evidence.props.onClick();
  tree = app.render();
  const quotes = nodes(tree).find(node => node.props?.id === 'landing-evidence');
  assert.ok(text(quotes).includes('Northstar'));
  assert.ok(text(quotes).includes('Acme'));
  assert.ok(!text(quotes).includes('$14k'));
  button(tree, 'Decisions').props.onClick();
  tree = app.render();
  assert.equal(nodes(tree).find(node => node.props?.className === 'landing-evidence-button').props['aria-expanded'], false);
  assert.ok(!nodes(tree).some(node => node.props?.id === 'landing-evidence'));
});

test('capture, Vault, and Analyze sample actions form a working local preview', () => {
  const app = fixture();
  let tree = app.render();
  nodes(tree).find(node => node.props?.id === 'landing-tab-capture').props.onClick();
  tree = app.render();
  assert.equal(panel(tree).props['aria-labelledby'], 'landing-tab-capture');
  button(tree, 'Save to Vault').props.onClick();
  tree = app.render();
  assert.equal(panel(tree).props['aria-labelledby'], 'landing-tab-vault');
  assert.ok(text(panel(tree)).includes('Saving context does not start an analysis.'));
  const analyze = nodes(tree).find(node => node.type === 'button' && text(node).startsWith('Analyze sample'));
  analyze.props.onClick();
  tree = app.render();
  assert.equal(panel(tree).props['aria-labelledby'], 'landing-tab-insights');
  assert.equal(button(tree, 'Decisions').props['aria-pressed'], true);
  assert.ok(text(panel(tree)).includes('Your pricing decision had a condition.'));
});

test('preview tabs support roving keyboard focus and the mobile menu returns focus on Escape', () => {
  const app = fixture();
  let tree = app.render();
  const focus = [];
  const event = key => ({ key, preventDefault() {}, currentTarget: { parentElement: { querySelector(id) { return { focus() { focus.push(id); } }; } } } });
  nodes(tree).find(node => node.props?.id === 'landing-tab-insights').props.onKeyDown(event('Home'));
  tree = app.render();
  assert.equal(panel(tree).props['aria-labelledby'], 'landing-tab-capture');
  const tabs = nodes(tree).filter(node => node.props?.role === 'tab');
  assert.equal(tabs.filter(node => node.props.tabIndex === 0).length, 1);
  nodes(tree).find(node => node.props?.id === 'landing-tab-capture').props.onKeyDown(event('ArrowRight'));
  tree = app.render();
  assert.equal(panel(tree).props['aria-labelledby'], 'landing-tab-vault');
  assert.deepEqual(focus, ['#landing-tab-capture', '#landing-tab-vault']);

  nodes(tree).find(node => node.props?.['aria-label'] === 'Toggle navigation').props.onClick();
  tree = app.render();
  assert.ok(nodes(tree).some(node => node.props?.id === 'landing-mobile-navigation'));
  assert.equal(nodes(tree).filter(node => node.type === 'language-selector').length, 1);
  nodes(tree).find(node => node.type === 'header').props.onKeyDown({ key: 'Escape', currentTarget: { querySelector() { return { focus() { focus.push('menu'); } }; } } });
  tree = app.render();
  assert.ok(!nodes(tree).some(node => node.props?.id === 'landing-mobile-navigation'));
  assert.equal(focus.at(-1), 'menu');
});

test('landing labels its sample and every rendered action has a real local handler or route', () => {
  const app = fixture();
  const tree = app.render();
  assert.ok(text(tree).includes('Sample workspace'));
  assert.ok(text(tree).includes('when you choose to analyze it'));
  assert.ok(text(tree).includes('ZIP imports are one-time copies.'));
  assert.doesNotMatch(text(tree), /HttpOnly|PostgreSQL|High confidence|Just now|148 records|01 \/|THE WORKFLOW/);
  assert.ok(text(tree).includes('Your notes go quiet.'));
  assert.ok(text(tree).includes("Flare doesn't."));
  for (const node of nodes(tree)) {
    if (node.type === 'button') assert.equal(typeof node.props.onClick, 'function');
    if (node.type === 'a') assert.ok(node.props.href?.startsWith('/') || node.props.href?.startsWith('#'));
  }
});

test('restored landing explains the outcome, evidence and memory without invented integration claims', () => {
  const tree = fixture().render();
  for (const expected of ["Less time reconstructing what happened.", "More time deciding what happens next.",
    "A workspace that shows its reasoning.", "Links every signal to evidence", "Decisions, interviews, and research in one Vault.",
    "Editable notes and sources", "Exportable workspace data"]) assert.ok(text(tree).includes(expected), expected);
  assert.equal(nodes(tree).filter(node => node.type === 'landing-motion').length, 1);
  assert.doesNotMatch(text(tree), /148|automatically synced|live sync|04 \/|05 \/|06 \//);
});
