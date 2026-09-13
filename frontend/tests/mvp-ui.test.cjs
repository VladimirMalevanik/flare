const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const ts = require('typescript');

function load(relative, mocks) {
  const filename = path.join(__dirname, relative);
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  vm.runInNewContext(code, { exports, require: (name) => {
    if (name in mocks) return mocks[name];
    throw Error(`Unexpected import ${name}`);
  } });
  return exports;
}
const jsx = { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
function nodes(node) {
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(nodes);
  return [node, ...nodes(node.props?.children)];
}
function capture(draft) {
  const requests = [], messages = [];
  const mocks = {
    'react/jsx-runtime': jsx,
    react: { useState: (initial) => [initial, (value) => messages.push(value)], useRef: () => ({ current: null }), useEffect: () => {}, useCallback: (fn) => fn },
    'next/link': { default: 'a' },
    '@/components/icons': { Icon: 'icon' },
    '@/components/workspace-context': { useWorkspace: () => ({ captureOpen: true, draft, captureOrbSize: 'medium', openCapture() {}, closeCapture() {}, setDraft() {}, refresh() {} }) },
    '@/lib/data': { dataProvider: { async createItem(input) { requests.push(input); return { id: 'saved' }; }, async importTextFile() { return { item: { id: 'imported' } }; }, async trackEvent() {} }, dataErrorMessage: () => 'error' },
    '@/lib/storage/preferences': {},
    './use-voice-capture': { useVoiceCapture: () => ({ state: 'idle', cancel() {}, start() {}, stop() {} }) },
  };
  return { tree: nodes(load('../src/features/capture/capture.tsx', mocks).Capture()), requests, messages };
}
for (const draft of ['A project note', 'https://example.com/context']) {
  test(`Capture submits text as a Note: ${draft}`, async () => {
    const { tree, requests } = capture(draft);
    const button = tree.find(n => n.props?.className === 'button primary');
    assert.equal(button.props.disabled, false);
    button.props.onClick();
    await Promise.resolve();
    assert.equal(requests.length, 1);
    assert.equal(requests[0].type, 'note');
    assert.equal(requests[0].content, draft);
    assert.equal(requests[0].sourceUrl, undefined);
  });
}
test('Capture accepts bounded text files and keeps microphone and keyboard submission', () => {
  const { tree, requests, messages } = capture('A note');
  assert.equal(tree.find(n => n.props?.['aria-label'] === 'Add file').props.disabled, false);
  assert.ok(tree.find(n => n.props?.['aria-label'] === 'Start recording'));
  assert.equal(tree.filter(n => n.type === 'input' && n.props.type === 'file').length, 1);
  let prevented = 0;
  const file = { name: 'context.csv', size: 25, type: 'text/csv' };
  tree.find(n => n.type === 'textarea').props.onPaste({ clipboardData: { files: [file] }, preventDefault() { prevented++; } });
  tree.find(n => n.props?.className === 'capture-dropzone').props.onDrop({ dataTransfer: { files: [file] }, preventDefault() { prevented++; } });
  assert.equal(prevented, 2);
  assert.equal(requests.length, 0);
  assert.equal(messages.filter(x => x === file).length, 2);
  for (const modifier of ['metaKey', 'ctrlKey']) {
    tree.find(n => n.type === 'textarea').props.onKeyDown({ [modifier]: true, key: 'Enter', preventDefault() {} });
  }
  assert.equal(requests.length, 2);
  assert.equal(capture('   ').tree.find(n => n.props?.className === 'button primary').props.disabled, true);
});
test('Capture preserves a UTF-8 BOM so file size and uploaded bytes agree', () => {
  const source = fs.readFileSync(path.join(__dirname, '../src/features/capture/capture.tsx'), 'utf8');
  assert.match(source, /new TextDecoder\("utf-8",\s*\{\s*fatal: true,\s*ignoreBOM: true,?\s*\}\)/s);
  const bomText = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(
    new Uint8Array([0xef, 0xbb, 0xbf, 0x61]),
  );
  assert.equal(bomText, '\ufeffa');
  assert.equal(Buffer.byteLength(bomText, 'utf8'), 4);
});
test('Sources loads through provider with headings outside grids and margin-safe labels', async () => {
  const { seedSources } = load('../src/mocks/sources.ts', {});
  const state = [];
  let cursor = 0, effect, calls = 0;
  const providerSources = seedSources.map(s => ({ ...s, name: `Provider: ${s.name}` }));
  const { SourcesPage } = load('../src/features/sources/sources-page.tsx', {
     'react/jsx-runtime': jsx, '@/components/icons': { Icon: 'icon' },
    react: {
      useState(initial) { const index = cursor++; if (!(index in state)) state[index] = initial; return [state[index], value => { state[index] = value; }]; },
      useEffect(fn) { effect = fn; },
    },
    '@/lib/data': { dataProvider: { async listSources() { calls++; return providerSources; } } },
    '@/components/workspace-context': { useWorkspace: () => ({ openCapture() {} }) },
  });
  assert.ok(nodes(SourcesPage()).some(n => n.props?.role === 'status'));
  const cleanup = effect();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 1);
  cursor = 0;
  const tree = nodes(SourcesPage());
  assert.ok(tree.some(n => n.type === 'h3' && n.props.children === 'Provider: Manual capture'));
  assert.ok(tree.filter(n => n.props?.className === 'eyebrow muted').every(n => n.type === 'p'));
  cleanup();
  const groups = tree.filter(n => n.props?.className === 'source-group');
  assert.equal(groups.length, 2);
  const grids = tree.filter(n => n.props?.className === 'source-grid');
  assert.equal(grids.length, 2);
  assert.equal(grids[0].props.children.length, 1);
  for (const grid of grids) assert.ok(grid.props.children.every(n => n.type === 'article'));
  assert.equal(seedSources[0].scope, 'Notes, links, and text imports');
  assert.equal(seedSources[0].channels.join(','), 'Notes,Links,CSV,TXT,Markdown');
  assert.ok(seedSources.slice(1).every(s => s.status === 'coming-soon'));
  assert.ok(nodes(grids[1]).filter(n => n.type === 'button').every(n => n.props.disabled));
});
