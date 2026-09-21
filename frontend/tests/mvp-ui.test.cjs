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
function textContent(node) {
  if (node == null || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(textContent).join(' ');
  return textContent(node.props?.children);
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
    '@/lib/voice': { async transcribeVoice() { return { id: 'voice-saved' }; } },
    './capture-position': {
      clampOrbPosition: position => position,
      hoverRectFor: () => ({ x: 0, y: 0, width: 146, height: 58, direction: 'right' }),
      placeCapturePanel: () => ({ x: 0, y: 0, width: 500, height: 204, horizontal: 'right', vertical: 'below' }),
    },
    './use-voice-capture': { useVoiceCapture: () => ({ state: 'idle', recording: null, error: '', cancel() {}, start() {}, stop() {} }) },
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
test('Capture accepts bounded text files, keeps keyboard submission, and gates conflicting voice input', () => {
  const { tree, requests, messages } = capture('A note');
  assert.equal(tree.find(n => n.props?.['aria-label'] === 'Add file').props.disabled, false);
  const voice = tree.find(n => n.props?.['aria-label'] === 'Record a voice memo');
  assert.ok(voice);
  assert.equal(voice.props.disabled, true);
  const emptyVoice = capture('').tree.find(n => n.props?.['aria-label'] === 'Record a voice memo');
  assert.equal(emptyVoice.props.disabled, false);
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
  const { sourceCatalog } = load('../src/lib/data/source-catalog.ts', {
    './types': {},
  });
  const state = [];
  let cursor = 0, effect, calls = 0;
  const providerSources = sourceCatalog.map(s => s.id === 'github' ? {
    ...s,
    name: `Provider: ${s.name}`,
    status: 'connected',
    scope: 'flare/example',
    description: 'Repository connection is active.',
    updated: 'Repository activity ingestion is not available yet.',
    repository: { id: 1, fullName: 'flare/example' },
  } : { ...s, name: `Provider: ${s.name}` });
  const { SourcesPage, GitHubControls } = load('../src/features/sources/sources-page.tsx', {
    'react/jsx-runtime': jsx, '@/components/icons': { Icon: 'icon' },
    'next/link': { default: 'a' },
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
  assert.ok(tree.some(n => n.type === 'h3' && n.props.children === 'Provider: Voice'));
  assert.ok(tree.filter(n => n.props?.className === 'eyebrow muted').every(n => n.type === 'p'));
  cleanup();
  const groups = tree.filter(n => n.props?.className === 'source-group');
  assert.equal(groups.length, 2);
  const grids = tree.filter(n => n.props?.className === 'source-grid');
  assert.equal(grids.length, 2);
  assert.equal(grids[0].props.children.length, 5);
  for (const grid of grids) assert.ok(grid.props.children.every(n => n.type === 'article'));
  assert.equal(sourceCatalog[0].scope, 'Notes, links, and text imports');
  assert.equal(sourceCatalog[0].channels.join(','), 'Notes,Links,CSV,TXT,Markdown');
  assert.equal(sourceCatalog.find(s => s.id === 'voice').status, 'ready');
  const obsidian = sourceCatalog.find(s => s.id === 'obsidian');
  const notion = sourceCatalog.find(s => s.id === 'notion');
  assert.deepEqual(
    { status: obsidian.status, primary: obsidian.channels[0], description: obsidian.description, muted: obsidian.updated },
    {
      status: 'manual-import',
      primary: 'Manual import available',
      description: 'Export Markdown from Obsidian and import it into Flare.',
      muted: 'Automatic vault sync is not available yet.',
    },
  );
  assert.deepEqual(
    { status: notion.status, primary: notion.channels[0], description: notion.description, muted: notion.updated },
    {
      status: 'manual-import',
      primary: 'Manual import available',
      description: 'Export your Notion content and import it into Flare.',
      muted: 'Automatic workspace sync is not available yet.',
    },
  );
  const articles = tree.filter(n => n.type === 'article');
  const obsidianCard = articles.find(n => textContent(n).includes('Provider: Obsidian import'));
  const notionCard = articles.find(n => textContent(n).includes('Provider: Notion'));
  const githubCard = articles.find(n => textContent(n).includes('Provider: GitHub'));
  assert.equal(nodes(obsidianCard).find(n => n.type === 'a')?.props.href, '/settings/import-guides/obsidian');
  assert.equal(nodes(notionCard).find(n => n.type === 'a')?.props.href, '/settings/import-guides/notion');
  assert.match(textContent(githubCard), /Connected/);
  assert.match(textContent(githubCard), /Repository connection is active\./);
  assert.match(textContent(githubCard), /flare\/example/);
  assert.match(textContent(githubCard), /Repository activity ingestion is not available yet\./);
  assert.doesNotMatch(textContent(githubCard), /Not available yet\./);
  const githubControls = nodes(GitHubControls({
    source: providerSources.find(s => s.id === 'github'),
    repositories: [], selectedRepository: '', loading: false, action: '', error: '',
    onSelect() {}, onConnect() {}, onSave() {}, onDisconnect() {},
  }));
  assert.match(textContent(githubControls), /flare\/example/);
  assert.match(textContent(githubControls), /Read-only connection/);
  assert.ok(sourceCatalog.filter(s => !['manual-capture', 'voice', 'obsidian', 'notion'].includes(s.id)).every(s => s.status === 'coming-soon'));
  assert.ok(nodes(grids[1]).filter(n => n.type === 'button').every(n => n.props.disabled));
});

test('Capture placement keeps the orb fixed and panels inside every viewport corner', () => {
  const positioning = load('../src/features/capture/capture-position.ts', {});
  const viewports = [
    { width: 1440, height: 900 },
    { width: 1280, height: 800 },
    { width: 900, height: 700 },
    { width: 390, height: 844 },
  ];
  for (const viewport of viewports) {
    const orbSize = 44;
    const edge = orbSize / 2 + 12;
    const corners = [
      { x: edge, y: edge, horizontal: 'right', vertical: 'below' },
      { x: viewport.width - edge, y: edge, horizontal: 'left', vertical: 'below' },
      { x: edge, y: viewport.height - edge, horizontal: 'right', vertical: 'above' },
      { x: viewport.width - edge, y: viewport.height - edge, horizontal: 'left', vertical: 'above' },
    ];
    for (const corner of corners) {
      const anchor = positioning.clampOrbPosition(corner, orbSize, viewport);
      const before = { ...anchor };
      const panel = positioning.placeCapturePanel(anchor, orbSize, { width: 500, height: 360 }, viewport);
      assert.equal(anchor.x, before.x);
      assert.equal(anchor.y, before.y);
      assert.ok(panel.x >= 16 && panel.y >= 16);
      assert.ok(panel.x + panel.width <= viewport.width - 16);
      assert.ok(panel.y + panel.height <= viewport.height - 16);
      if (viewport.width >= 900) assert.equal(panel.horizontal, corner.horizontal);
      assert.equal(panel.vertical, corner.vertical);
      const hover = positioning.hoverRectFor(anchor, orbSize, 146, viewport.width);
      assert.ok(hover.x >= 12);
      assert.ok(hover.y >= 12);
      assert.ok(hover.x + hover.width <= viewport.width - 12);
      assert.ok(hover.y + hover.height <= viewport.height - 12);
      assert.equal(anchor.x, before.x);
      assert.equal(anchor.y, before.y);
    }
    const edgeAnchors = [
      { x: viewport.width / 2, y: viewport.height / 2 },
      { x: 0, y: viewport.height / 2 },
      { x: viewport.width, y: viewport.height / 2 },
      { x: viewport.width / 2, y: 0 },
      { x: viewport.width / 2, y: viewport.height },
    ];
    for (const candidate of edgeAnchors) {
      const anchor = positioning.clampOrbPosition(candidate, orbSize, viewport);
      const panel = positioning.placeCapturePanel(anchor, orbSize, { width: 500, height: 360 }, viewport);
      assert.ok(panel.x >= 16 && panel.y >= 16);
      assert.ok(panel.x + panel.width <= viewport.width - 16);
      assert.ok(panel.y + panel.height <= viewport.height - 16);
      const hover = positioning.hoverRectFor(anchor, orbSize, 146, viewport.width);
      assert.ok(hover.x >= 12 && hover.x + hover.width <= viewport.width - 12);
      assert.ok(hover.y >= 12 && hover.y + hover.height <= viewport.height - 12);
    }
    const leftHover = positioning.hoverRectFor(
      positioning.clampOrbPosition({ x: 0, y: viewport.height / 2 }, orbSize, viewport),
      orbSize, 146, viewport.width,
    );
    const rightHover = positioning.hoverRectFor(
      positioning.clampOrbPosition({ x: viewport.width, y: viewport.height / 2 }, orbSize, viewport),
      orbSize, 146, viewport.width,
    );
    assert.equal(leftHover.direction, 'right');
    assert.equal(rightHover.direction, 'left');
  }
});
