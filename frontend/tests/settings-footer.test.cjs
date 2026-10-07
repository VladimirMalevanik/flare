const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const { i18nMock } = require('./i18n-utils.cjs');
const jsx = { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
function load(file, mocks) {
  const exports = {};
  const source = ts.transpileModule(fs.readFileSync(path.join(__dirname, file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(source, { exports, Intl, require(name) {
    if (name === 'react/jsx-runtime') return jsx;
    if (name === '@/i18n/provider') return i18nMock();
    if (name in mocks) return mocks[name];
    throw Error(`Unexpected import ${name}`);
  } });
  return exports;
}
function nodes(node) {
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(nodes);
  return [node, ...nodes(node.props?.children)];
}
function harness() {
  const slots = [];
  let cursor = 0, pathname = '/vault';
  const state = value => {
    const index = cursor++;
    if (!(index in slots)) slots[index] = value;
    return [slots[index], next => { slots[index] = next; }];
  };
  const react = { useState: state, useEffect() {}, useRef: value => state({ current: value })[0] };
  const calls = [];
  const workspace = { profile: { name: 'Fedor', role: 'owner' }, funnyMode: false,
    setFunnyMode(value) { workspace.funnyMode = value; calls.push(value); }, setTheme() {} };
  const { AppShell } = load('../src/components/app-shell.tsx', {
    react, 'next/link': { default: 'a' }, 'next/navigation': { usePathname: () => pathname },
    './icons': { Icon: 'icon' }, './brand-mark': { BrandMark: 'brand-mark' }, './dialog': { Dialog: 'dialog' },
    './workspace-context': { WorkspaceProvider: 'provider', useWorkspace: () => workspace },
    '@/features/capture/capture': { Capture: 'capture' }, '@/features/funny/funny-effects': { FunnyEffects: 'effects' },
    '@/lib/data': { dataProvider: {} },
  });
  return { calls, workspace, path(value) { pathname = value; }, render() {
    cursor = 0;
    const shell = AppShell({ children: 'content' }).props.children;
    return shell.type(shell.props);
  } };
}
const gear = tree => nodes(tree).find(node => node.props?.className === 'button icon-button profile-settings');
const click = (tree, modifiers = {}) => gear(tree).props.onClick({ preventDefault() {}, ...modifiers });

test('profile gear opens Settings, retains its label and counts only its own ordinary activations', () => {
  const h = harness();
  let tree = h.render();
  assert.equal(gear(tree).props.href, '/settings');
  assert.equal(gear(tree).props['aria-label'], 'Settings');
  assert.equal(nodes(tree).filter(node => node.type === 'language-selector').length, 0);
  // Profile and navigation Settings links are ordinary navigation, not unlock presses.
  for (let i = 0; i < 12; i++) nodes(tree).find(node => node.props?.className === 'profile').props.onClick();
  for (const key of ['ctrlKey', 'metaKey', 'altKey', 'shiftKey']) click(tree, { [key]: true });
  for (let i = 0; i < 9; i++) {
    click(tree);
    h.path('/settings');
    tree = h.render();
    assert.deepEqual(h.calls, []);
  }
  click(tree);
  assert.deepEqual(h.calls, [true]);
  tree = h.render();
  let prevented = 0;
  click(tree, { preventDefault() { prevented++; } });
  assert.equal(prevented, 1);
  for (let i = 0; i < 8; i++) { click(tree); tree = h.render(); }
  assert.deepEqual(h.calls, [true]);
  click(tree);
  assert.deepEqual(h.calls, [true, false]);
});

test('mobile gear and profile navigation both close the drawer', () => {
  for (const target of ['gear', 'profile']) {
    const h = harness();
    let tree = h.render();
    nodes(tree).find(node => node.props?.className === 'mobile-menu icon-button').props.onClick();
    tree = h.render();
    assert.equal(nodes(tree).filter(node => node.type === 'dialog').length, 1);
    const drawer = nodes(tree).find(node => node.type === 'dialog');
    if (target === 'gear') click(drawer);
    else nodes(drawer).find(node => node.props?.className === 'profile').props.onClick();
    assert.equal(nodes(h.render()).filter(node => node.type === 'dialog').length, 0);
    assert.deepEqual(h.calls, []);
  }
});

test('Settings keeps language and theme controls with both funny preference rows removed', () => {
  const { SettingsPage } = load('../src/features/settings/settings-page.tsx', {
    react: { useState: value => [value, () => {}], useEffect() {}, useMemo: fn => fn() },
    'next/link': { default: 'a' }, '@/components/auth-session': { useSession: () => null },
    '@/lib/auth/session': {}, '@/components/icons': { Icon: 'icon' },
    '@/components/workspace-context': { useWorkspace: () => ({ profile: { name: 'Fedor', role: 'owner', timezone: 'UTC' }, theme: 'dark' }) },
    '@/lib/storage/preferences': {}, '@/components/language-selector': { LanguageSelector: 'language-selector' },
    '@/components/select': { Select: 'select' }, '@/features/telemetry/analytics-preferences': { AnalyticsPreferences: 'analytics' },
    '@/lib/data': {},
  });
  const all = nodes(SettingsPage({ supportEmail: null }));
  assert.equal(all.filter(node => node.type === 'language-selector').length, 1);
  assert.equal(all.filter(node => node.props?.className?.startsWith('theme-option ')).length, 3);
  assert.ok(all.every(node => !['Funny mode', 'Funny sounds'].includes(node.props?.title)));
});
