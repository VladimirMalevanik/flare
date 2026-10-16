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
function component(relative, exportName, provider = {}, workspace = {}, routing = { search: "", replaced: [] }) {
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
    'next/navigation': { usePathname: () => '/vault', useSearchParams: () => new URLSearchParams(routing.search), useRouter: () => ({ replace(url) { routing.replaced.push(url); routing.search = url.split("?")[1] ?? ""; } }) },
    '@/components/icons': { Icon: 'icon', itemIcon: { note: 'note' } }, '@/components/dialog': { Dialog: 'dialog' },
    '@/components/workspace-context': { useWorkspace: () => defaults },
    '@/components/auth-session': { useSession: () => ({ workspace: { role: 'owner' } }) },
    './auth-session': { useSession: () => null },
    '@/lib/team-context': { projectHref: url => url },
    '@/lib/data/import-request': { importRequest: fn => fn(new AbortController().signal) },
    './view-analytics': {},
    '@/lib/data': { dataProvider: { trackEvent: async () => {}, ...provider }, dataErrorMessage: (_, fallback) => fallback },
    '@/lib/storage/preferences': { readLocal: (_, fallback) => fallback, writeLocal() {} },
    '@/lib/voice': { transcribeVoice: async () => ({ id: 'voice' }) },
    '@/features/funny/funny-sounds': { playFunnySound() {}, stopFunnySounds() {} },
    '@/features/funny/funny-state': { INITIAL_FUNNY_RITUAL: { phase: 'idle', requestId: 0 } },
    './capture-position': { CAPTURE_PANEL_SIZES: { medium: { width: 500, height: 204 } }, clampOrbPosition: p => p },
    './use-voice-capture': { useVoiceCapture: () => ({ state: 'idle', recording: null, cancel() {} }) },
  }, { window, document, requestAnimationFrame: () => 1, cancelAnimationFrame() {} });
  const render = () => { cursor = 0; return exports[exportName]({ children: null }); };
  return { render, module: exports, workspace: defaults,
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

test('evidence links identify the original version and tolerate pre-upgrade evidence DTOs', () => {
  const app = component('../src/features/insights/insights-page.tsx', 'InsightsPage');
  assert.equal(app.module.evidenceSourceHref({ itemId: 'note/one', documentVersionId: 'version/one' }),
    '/vault?item=note%2Fone&version=version%2Fone');
  assert.equal(app.module.evidenceSourceHref({ itemId: 'old-note' }), '/vault?item=old-note');
});

test('original source sheet shows the exact text/date/author and exposes current version instead of mutation controls', async () => {
  let writes = 0;
  const original = { ...item(1), content:'Original release decision.', author:'Original author' };
  const app = component('../src/features/vault/vault-page.tsx', 'VaultPage', {
    listItems: async () => [{ ...item(1), content:'Current changed text' }],
    getItem() { assert.fail('An original source must not fall back to the current note'); },
    getItemVersion: async (id, versionId) => {
      assert.equal(id, original.id); assert.equal(versionId, original.currentVersionId);
      return { item:original, savedAt:'2026-10-15T12:00:00Z', isCurrent:false };
    },
    updateItem() { writes++; }, deleteItem() { writes++; },
  }, {}, { search:'item=note-1&version=version-1&project=team', replaced:[] });
  app.render(); await app.effects();
  const dialog = nodes(app.render()).find(n => n.type === 'dialog');
  assert.match(text(dialog), /Original release decision/);
  assert.match(text(dialog), /Original author/);
  assert.match(text(dialog), /Version 1/); assert.match(text(dialog), /2026/);
  assert.ok(!nodes(dialog).some(n => n.type === 'button' && /Edit|Delete|Save new version/.test(text(n))));
  const current = nodes(dialog).find(n => n.type === 'a' && text(n) === 'Open current version');
  assert.equal(current.props.href, '/vault?item=note-1');
  assert.equal(writes, 0); app.dispose();
});

test('closing an original source clears version and item while retaining project context', async () => {
  const routing = { search:'project=team&item=note-1&version=version-1&filter=note', replaced:[] };
  const app = component('../src/features/vault/vault-page.tsx', 'VaultPage', {
    listItems: async () => [], getItemVersion: async () => ({ item:item(1), savedAt:item(1).updatedAt, isCurrent:false }),
  }, {}, routing);
  app.render(); await app.effects(); app.button('Close item').props.onClick();
  assert.equal(routing.replaced[0], '/vault?project=team&filter=note');
  app.render(); await app.effects();
  assert.ok(!nodes(app.render()).some(n => n.type === 'dialog')); app.dispose();
});

test('unavailable original versions show an error and never display a substituted current note', async () => {
  const app = component('../src/features/vault/vault-page.tsx', 'VaultPage', {
    listItems: async () => [], getItemVersion: async () => null,
    getItem() { assert.fail('Never silently replace missing evidence'); },
  }, {}, {search:'item=note-1&version=missing',replaced:[]});
  app.render(); await app.effects();
  assert.match(text(app.render()), /This source is unavailable/);
  await app.debounce();
  assert.match(text(app.render()), /This source is unavailable/, 'a successful list refresh must not erase the source error');
  assert.ok(!nodes(app.render()).some(n => n.type === 'dialog')); app.dispose();
});

test('a late original-version request cannot replace a manually opened current item', async () => {
  let finish;
  const app = component('../src/features/vault/vault-page.tsx', 'VaultPage', {
    listItems: async () => [item(2)], getItemVersion: () => new Promise(done => { finish = done; }),
  }, {}, {search:'item=note-1&version=version-1',replaced:[]});
  app.render(); await app.effects(); await app.debounce();
  app.button('Note 2').props.onClick();
  finish({ item:item(1),savedAt:item(1).updatedAt,isCurrent:false }); await settle();
  const dialog = nodes(app.render()).find(n => n.type === 'dialog');
  assert.equal(dialog.props.title, 'Note 2'); assert.doesNotMatch(text(dialog), /Original source version/);
  app.dispose();
});

function adapter(fetch) {
  const request = load('../src/lib/data/import-request.ts', {}, {setTimeout,clearTimeout});
  const { ApiDataProvider } = load('../src/lib/data/api-provider.ts', {
    './import-request':request, '../team-context':{projectApiUrl:url=>url},
  }, {fetch,setTimeout,clearTimeout});
  return new ApiDataProvider({baseUrl:'/api',fallback:{}});
}
test('API version adapter validates the requested identity and date and handles404 without fallback', async () => {
  const urls=[];
  const provider=adapter(async url=>{urls.push(url);return new Response(JSON.stringify({item:item(1),savedAt:item(1).updatedAt,isCurrent:false}));});
  const result=await provider.getItemVersion('note-1','version-1');
  assert.equal(result.item.content,item(1).content); assert.equal(result.isCurrent,false);
  assert.deepEqual(urls,['/api/items/note-1/versions/version-1']);
  await assert.rejects(provider.getItemVersion('note-1','wrong-version'));
  const missing=adapter(async()=>new Response(JSON.stringify({detail:'Item not found'}),{status:404}));
  assert.equal(await missing.getItemVersion('note-1','version-1'),null);
  const invalid=adapter(async()=>new Response(JSON.stringify({item:item(1),savedAt:'not-a-date',isCurrent:false})));
  await assert.rejects(invalid.getItemVersion('note-1','version-1'));
});

test('Flare API adapter retains immutable evidence identity and rejects malformed version metadata', async () => {
  const evidence={itemId:'note-1',sourceTitle:'Source',sourceType:'note',excerpt:'Decision',sourceUrl:null,
    documentVersionId:'version-1',versionNumber:1,versionCreatedAt:'2026-10-15T12:00:00Z'};
  const flare={id:'flare-1',type:'Reminder',title:'Reminder',statement:'Decision',action:null,reason:'Evidence',createdAt:'2026-10-16T12:00:00Z',evidence:[evidence]};
  const provider=adapter(async()=>new Response(JSON.stringify([flare])));
  const result=(await provider.listInsights())[0].evidence[0];
  assert.equal(result.documentVersionId,evidence.documentVersionId); assert.equal(result.versionNumber,1);
  const malformed=adapter(async()=>new Response(JSON.stringify([{...flare,evidence:[{...evidence,versionNumber:0}]}])));
  await assert.rejects(malformed.listInsights());
});

