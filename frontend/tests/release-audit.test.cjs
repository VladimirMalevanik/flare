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
    createContext: () => ({ Provider: 'context-provider' }),
    useCallback(fn, values = []) { const i = cursor++; if (!deps[i] || values.some((v, j) => v !== deps[i][j])) {
      state[i] = fn; deps[i] = values;
    } return state[i]; },
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
    './auth-session': { useSession: () => null },
    '@/lib/team-context': { projectHref: url => url },
    '@/lib/data': { dataProvider: { trackEvent: async () => {}, ...provider }, dataErrorMessage: (_, fallback) => fallback },
    '@/lib/storage/preferences': { readLocal: (_, fallback) => fallback, writeLocal() {} },
    '@/lib/voice': { transcribeVoice: async () => ({ id: 'voice' }) },
    '@/features/funny/funny-sounds': { playFunnySound() {}, stopFunnySounds() {} },
    '@/features/funny/funny-state': { INITIAL_FUNNY_RITUAL: { phase: 'idle', requestId: 0 } },
    './capture-position': { CAPTURE_PANEL_SIZES: { medium: { width: 500, height: 204 } }, clampOrbPosition: p => p },
    './use-voice-capture': { useVoiceCapture: () => ({ state: 'idle', recording: null, cancel() {} }) },
  }, { window, document, requestAnimationFrame: () => 1, cancelAnimationFrame() {} });
  const render = () => { cursor = 0; return exports[exportName]({ children: null }); };
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

test('typing a draft does not restart the scheduled analysis polling effect', () => {
  const app = component('../src/components/workspace-context.tsx', 'WorkspaceProvider');
  const original = app.render().props.value.refresh;
  for (let i = 0; i < 20; i++) {
    app.render().props.value.setDraft(`Draft ${i}`);
    assert.equal(app.render().props.value.refresh, original, 'the schedule effect depends on this callback');
  }
  original();
  assert.equal(app.render().props.value.revision, 1);
  app.dispose();
});

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

test('Capture guards a real unsaved draft against reload/project switching, and releases the guard after saving', async () => {
  const app = component('../src/features/capture/capture.tsx', 'Capture', { createItem: async () => ({ id: 'saved' }) });
  app.workspace.setDraft = value => { app.workspace.draft = value; };
  app.workspace.closeCapture = () => { app.workspace.captureOpen = false; };
  app.render(); await app.effects();
  let prevented = 0;
  const event = { preventDefault() { prevented++; }, returnValue: undefined };
  for (const listener of app.listeners.get('beforeunload') ?? []) listener(event);
  assert.equal(prevented, 1, 'a full project switch/reload must not silently discard typed context');
  const button = nodes(app.render()).find(n => n.type === 'button' && n.props.className === 'button primary');
  button.props.onClick(); await settle(); app.render(); await app.effects();
  assert.equal(app.workspace.draft, '');
  assert.equal(app.listeners.get('beforeunload')?.size ?? 0, 0);
  app.dispose();
});

test('an empty Capture does not add an unload warning', async () => {
  const app = component('../src/features/capture/capture.tsx', 'Capture', {}, { draft: '' });
  app.render(); await app.effects();
  assert.equal(app.listeners.get('beforeunload')?.size ?? 0, 0);
  app.dispose();
});

test('Vault edits are guarded only after text changes, not merely when the editor opens', async () => {
  const app = component('../src/features/vault/vault-page.tsx', 'VaultPage', { listItems: async () => [item(1)] });
  app.render(); await app.effects(); await app.debounce();
  app.button('Note 1').props.onClick(); app.button('Edit note').props.onClick(); app.render(); await app.effects();
  assert.equal(app.listeners.get('beforeunload')?.size ?? 0, 0);
  nodes(app.render()).find(n => n.type === 'textarea').props.onChange({ target: { value: 'New team decision' } });
  app.render(); await app.effects();
  let prevented = false;
  for (const listener of app.listeners.get('beforeunload') ?? []) listener({ preventDefault() { prevented = true; }, returnValue: undefined });
  assert.ok(prevented);
  app.button('Cancel').props.onClick(); app.render(); await app.effects();
  assert.equal(app.listeners.get('beforeunload')?.size ?? 0, 0);
  app.dispose();
});

test('Vault does not send the same version update twice before the pending render', async () => {
  let resolve, calls = 0;
  const app = component('../src/features/vault/vault-page.tsx', 'VaultPage', {
    listItems: async () => [item(1)],
    updateItem() { calls++; return new Promise(done => { resolve = done; }); },
  });
  app.render(); await app.effects(); await app.debounce();
  app.button('Note 1').props.onClick(); app.button('Edit note').props.onClick();
  nodes(app.render()).find(n => n.type === 'textarea').props.onChange({ target: { value: 'Updated release note' } });
  const form = nodes(app.render()).find(n => n.type === 'form');
  form.props.onSubmit({ preventDefault() {} }); form.props.onSubmit({ preventDefault() {} });
  assert.equal(calls, 1, 'duplicate PATCH would report a conflict after the first save already succeeded');
  resolve({ ...item(1), content: 'Updated release note', currentVersionId: 'version-2', versionNumber: 2 });
  await settle();
  assert.ok(!nodes(app.render()).some(n => n.type === 'form'));
  app.dispose();
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

test('login/register requests have a bounded wait without automatically creating another account/session', async () => {
  let id = 0, sends = 0, signal;
  const timers = new Map();
  const globals = { setTimeout(fn, ms) { const key = ++id; timers.set(key, { fn, ms }); return key; }, clearTimeout(key) { timers.delete(key); } };
  const request = load('../src/lib/data/import-request.ts', {}, globals);
  const auth = load('../src/lib/auth/session.ts', {
    './acquisition': { currentAcquisitionOptIn: () => false, resetAcquisitionConsent() {} },
    '@/lib/data/import-request': request,
  }, { ...globals, process: { env: {} }, fetch: async (_, options) => { sends++; signal = options.signal; return new Promise(() => {}); } });
  const pending = auth.authRequest('register', { email: 'test@demo.invalid', password: 'synthetic-only' }); pending.catch(() => {});
  await settle();
  const timer = [...timers.values()].find(t => t.ms === 30000);
  assert.ok(timer, 'auth forms must eventually recover from a stalled API'); timer.fn();
  await assert.rejects(pending, error => error.code === 'request_outcome_unknown');
  assert.equal(signal.aborted, true); assert.equal(sends, 1);
});
