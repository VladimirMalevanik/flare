const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const { i18nMock } = require('./i18n-utils.cjs');
const settle = () => new Promise(resolve => setImmediate(resolve));
const jsx = { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
function nodes(node) {
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(nodes);
  return [node, ...nodes(node.props?.children)];
}
function text(node) {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(text).join('');
  return node ? text(node.props?.children) : '';
}
function load(relative, mocks, globals = {}) {
  const filename = path.resolve(__dirname, relative), exports = {};
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(code, { exports, URLSearchParams, AbortController, Response, TextDecoder,
    ...globals, require(name) {
      if (name === 'react/jsx-runtime') return jsx;
      if (name === '@/i18n/provider') return i18nMock();
      if (Object.hasOwn(mocks, name)) return mocks[name];
      throw Error(`Unexpected import ${name}`);
    } });
  return exports;
}
function component(relative, exportName, provider = {}, workspace = {}) {
  const state = [], deps = [], effects = [], cleanups = [], timers = new Map(), listeners = new Map();
  let cursor = 0, timerId = 0;
  const react = {
    useState(initial) { const i = cursor++; if (!(i in state)) state[i] = typeof initial === 'function' ? initial() : initial;
      return [state[i], value => state[i] = typeof value === 'function' ? value(state[i]) : value]; },
    useRef(initial) { const i = cursor++; if (!(i in state)) state[i] = { current: initial }; return state[i]; },
    useCallback: fn => fn,
    useEffect(fn, values = []) { const i = cursor++; if (!deps[i] || values.some((v, j) => v !== deps[i][j])) {
      effects.push(() => { cleanups[i]?.(); cleanups[i] = fn(); }); deps[i] = values;
    } },
    useLayoutEffect() {},
  };
  const window = { innerWidth: 1280, innerHeight: 800,
    setTimeout(fn, ms) { const id = ++timerId; timers.set(id, { fn, ms }); return id; },
    clearTimeout(id) { timers.delete(id); },
    addEventListener(name, fn) { if (!listeners.has(name)) listeners.set(name, new Set()); listeners.get(name).add(fn); },
    removeEventListener(name, fn) { listeners.get(name)?.delete(fn); },
  };
  const document = { addEventListener() {}, removeEventListener() {} };
  const defaults = { revision: 0, refresh() {}, captureOpen: true, draft: 'Release note', captureOrbSize: 'medium',
    funnyMode: false, funnySounds: false, funnyRitual: { phase: 'idle' }, funnyAudioPaused: false,
    openCapture() {}, closeCapture() {}, setDraft() {}, setFunnyRitual() {}, setFunnyAudioPaused() {}, ...workspace };
  const exports = load(relative, {
    react, 'next/link': { default: 'a' },
    'next/navigation': { usePathname: () => '/vault', useSearchParams: () => new URLSearchParams(), useRouter: () => ({ replace() {} }) },
    '@/components/icons': { Icon: 'icon', itemIcon: { note: 'note' } }, '@/components/dialog': { Dialog: 'dialog' },
    '@/components/workspace-context': { useWorkspace: () => defaults },
    '@/components/auth-session': { useSession: () => ({ workspace: { role: 'owner' } }) },
    '@/lib/team-context': { projectHref: url => url },
    '@/lib/data': { dataProvider: { trackEvent: async () => {}, ...provider }, dataErrorMessage: (_, fallback) => fallback },
    '@/lib/storage/preferences': { readLocal: (_, fallback) => fallback, writeLocal() {} },
    '@/lib/voice': { transcribeVoice: async () => ({ id: 'voice' }) },
    '@/features/funny/funny-sounds': { playFunnySound() {} },
    '@/features/funny/funny-state': {},
    './capture-position': { CAPTURE_PANEL_SIZES: { medium: { width: 500, height: 204 } }, clampOrbPosition: p => p },
    './use-voice-capture': { useVoiceCapture: () => ({ state: 'idle', recording: null, cancel() {} }) },
  }, { window, document });
  const render = () => { cursor = 0; return exports[exportName](); };
  return { render, workspace: defaults,
    button(label) { const result = nodes(render()).find(n => n.type === 'button' && (text(n) === label || n.props?.['aria-label'] === label)); assert.ok(result, label); return result; },
    async effects() { for (const fn of effects.splice(0)) fn(); await settle(); },
    async debounce() { for (const [id, timer] of [...timers]) if (timer.ms === 200) { timers.delete(id); timer.fn(); } await settle(); },
    dispose() { for (const fn of cleanups) if (typeof fn === 'function') fn(); },
    listeners,
  };
}
const item = index => ({ id: `note-${index}`, title: `Note ${index}`, content: 'Saved context', type: 'note', status: 'ready',
  updatedAt: '2026-10-16T00:00:00Z', createdAt: '2026-10-16T00:00:00Z', versionNumber: 1,
  currentVersionId: `version-${index}`, extractedFacts: [], relatedItemIds: [] });

test('Capture admits one save before React has rendered the pending state', async () => {
  let resolve, calls = 0;
  const app = component('../src/features/capture/capture.tsx', 'Capture', {
    createItem() { calls++; return new Promise(done => { resolve = done; }); },
  });
  const button = nodes(app.render()).find(n => n.type === 'button' && n.props.className === 'button primary');
  button.props.onClick(); button.props.onClick();
  assert.equal(calls, 1, 'one user attempt must not create two notes');
  resolve({ id: 'saved' }); await settle(); app.dispose();
});

test('changing a Vault filter during paging releases the old loading state and ignores its late result', async () => {
  let finishOld;
  const app = component('../src/features/vault/vault-page.tsx', 'VaultPage', {
    listItems(options) {
      if (options.beforeId && options.type === 'all') return new Promise(done => { finishOld = done; });
      return Promise.resolve(Array.from({ length: 51 }, (_, i) => item(options.type === 'note' ? 100 + i : i)));
    },
  });
  app.render(); await app.effects(); await app.debounce();
  const more = nodes(app.render()).find(n => n.type === 'button' && /Load more/.test(text(n)));
  assert.ok(more); more.props.onClick();
  app.button('Notes').props.onClick(); app.render(); await app.effects(); await app.debounce();
  finishOld([item(999)]); await settle();
  const next = nodes(app.render()).find(n => n.type === 'button' && /Load more/.test(text(n)));
  assert.ok(next, 'a fresh filter can page even if a previous page was pending');
  assert.ok(!next.props.disabled);
  assert.doesNotMatch(text(app.render()), /Note 999/);
  app.dispose();
});

function apiHarness(fetch) {
  let id = 0; const timers = new Map();
  const globals = { setTimeout(fn, ms) { const key = ++id; timers.set(key, { fn, ms }); return key; }, clearTimeout(key) { timers.delete(key); } };
  const request = load('../src/lib/data/import-request.ts', {}, globals);
  const { ApiDataProvider } = load('../src/lib/data/api-provider.ts', {
    './import-request': request, '../team-context': { projectApiUrl: url => url },
  }, { ...globals, fetch });
  return { provider: new ApiDataProvider({ baseUrl: '/api', fallback: {} }), timers,
    expire() { const timer = [...timers.values()].find(t => t.ms === 15000); assert.ok(timer, 'ordinary API calls have a finite deadline'); timer.fn(); } };
}
for (const stage of ['headers', 'body']) test(`Vault reads recover from a hung response ${stage}`, async () => {
  let signal;
  const h = apiHarness(async (_, options) => { signal = options.signal;
    return stage === 'headers' ? new Promise(() => {}) : { ok: true, status: 200, json: () => new Promise(() => {}) }; });
  const pending = h.provider.listItems(); pending.catch(() => {}); await settle(); h.expire();
  await assert.rejects(pending, failure => failure.code === 'request_timeout');
  assert.equal(signal.aborted, true);
});
test('a timed-out write is uncertain and is never automatically submitted again', async () => {
  let writes = 0;
  const h = apiHarness(async () => { writes++; return new Promise(() => {}); });
  const pending = h.provider.createItem({ type: 'note', content: 'Keep my draft' }); pending.catch(() => {});
  await settle(); h.expire();
  await assert.rejects(pending, failure => failure.code === 'request_outcome_unknown');
  assert.equal(writes, 1);
});
test('a write whose success body was lost is uncertain rather than an invitation to repeat it', async () => {
  const h = apiHarness(async () => ({ ok: true, status: 201, async json() { throw new SyntaxError('broken response'); } }));
  await assert.rejects(h.provider.createItem({ type: 'note', content: 'Already persisted' }), failure => failure.code === 'request_outcome_unknown');
});
