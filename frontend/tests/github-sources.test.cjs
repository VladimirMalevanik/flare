const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const ts = require('typescript');

const jsx = { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
function nodes(node) {
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(nodes);
  const rendered = typeof node.type === 'function' ? node.type(node.props) : null;
  return [node, ...nodes(rendered), ...nodes(node.props?.children)];
}
function source(status, extra = {}) {
  return { id: 'github', name: 'GitHub', scope: 'One repository', description: 'GitHub source',
    channels: [], status, updated: 'Now', ...extra };
}
function harness(initialSource, available = []) {
  const state = [];
  const calls = [];
  let cursor = 0, effect;
  const provider = {
    async listSources() { return [initialSource]; },
    async listGitHubRepositories() { calls.push('repositories'); return available; },
    async startGitHubConnection() { calls.push('connect'); return 'https://github.com/apps/flare/installations/new?state=safe'; },
    async selectGitHubRepository(id) { calls.push(['select', id]); return {}; },
    async disconnectGitHub() { calls.push('disconnect'); },
  };
  const filename = path.join(__dirname, '../src/features/sources/sources-page.tsx');
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  const sandbox = { exports, window: { location: { assign(url) { calls.push(['redirect', url]); } } }, require(name) {
    if (name === 'react/jsx-runtime') return jsx;
    if (name === 'next/link') return { default: 'a' };
    if (name === 'react') return {
      useState(initial) { const index = cursor++; if (!(index in state)) state[index] = initial;
        return [state[index], value => { state[index] = typeof value === 'function' ? value(state[index]) : value; }]; },
      useEffect(fn) { effect = fn; },
    };
    if (name === '@/lib/data') return { dataProvider: provider, dataErrorMessage: (error, fallback) => error?.message || fallback };
    if (name === '@/components/icons') return { Icon: 'icon' };
    if (name === '@/components/workspace-context') return { useWorkspace: () => ({ openCapture() {} }) };
    throw Error(`Unexpected import ${name}`);
  } };
  vm.runInNewContext(code, sandbox);
  function render() { cursor = 0; return nodes(exports.SourcesPage()); }
  return { render, runEffect: async () => { effect(); await new Promise(resolve => setImmediate(resolve)); }, calls };
}

test('GitHub disconnected state starts the real authorization flow', async () => {
  const app = harness(source('disconnected'));
  app.render(); await app.runEffect();
  const tree = app.render();
  assert.ok(tree.some(node => Array.isArray(node.props?.children) && node.props.children.includes('Not connected')));
  tree.find(node => node.type === 'button' && node.props.children === 'Connect GitHub').props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(app.calls, ['connect', ['redirect', 'https://github.com/apps/flare/installations/new?state=safe']]);
});

test('GitHub pending state loads repositories and saves one selection', async () => {
  const repository = { id: 101, owner: 'acme', name: 'flare', fullName: 'acme/flare', private: true,
    htmlUrl: 'https://github.com/acme/flare' };
  const app = harness(source('syncing'), [repository]);
  app.render(); await app.runEffect();
  let tree = app.render();
  assert.deepEqual(app.calls, ['repositories']);
  tree.find(node => node.type === 'select').props.onChange({ target: { value: '101' } });
  tree = app.render();
  tree.find(node => node.type === 'button' && node.props.children === 'Save repository').props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(app.calls.slice(1), [['select', 101]]);
});

test('GitHub connected and error states are truthful and disconnect is real', async () => {
  const repository = { id: 101, owner: 'acme', name: 'flare', fullName: 'acme/flare', private: true,
    htmlUrl: 'https://github.com/acme/flare' };
  const connected = harness(source('connected', { repository }));
  connected.render(); await connected.runEffect();
  const tree = connected.render();
  assert.ok(tree.some(node => node.props?.children === 'acme/flare'));
  tree.find(node => node.type === 'button' && node.props.children === 'Disconnect').props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(connected.calls, ['disconnect']);

  const failed = harness(source('error', { error: 'GitHub integration is not configured' }));
  failed.render(); await failed.runEffect();
  const failureTree = failed.render();
  assert.ok(failureTree.some(node => node.props?.role === 'alert'));
  assert.ok(failureTree.some(node => node.type === 'button' && node.props.children === 'Retry connection'));
});
