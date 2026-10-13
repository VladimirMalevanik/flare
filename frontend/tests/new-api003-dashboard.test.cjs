const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const { i18nMock } = require('./i18n-utils.cjs');

const jsx = { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
const settle = () => new Promise(resolve => setImmediate(resolve));
const saved = { id: 'saved', type: 'note', title: 'Saved first draft', content: 'First draft',
  status: 'processing', createdAt: '2026-10-05T00:00:00Z' };
const insight = { id: 'flare', title: 'Real insight', statement: 'Grounded in the saved note',
  evidence: [], createdAt: '2026-10-05T00:00:00Z' };
function text(node) {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(text).join('');
  if (typeof node?.type === 'function' && node.type.name === 'ErrorState') return text(node.type(node.props));
  return node ? text(node.props?.children) : '';
}
function nodes(node) {
  if (!node || typeof node !== 'object') return [];
  if (Array.isArray(node)) return node.flatMap(nodes);
  // Render the real error presentation contract; keep nested feature hooks separate.
  if (typeof node.type === 'function' && node.type.name === 'ErrorState') return nodes(node.type(node.props));
  return [node, ...nodes(node.props?.children)];
}
function harness(overrides = {}, component = 'DashboardPage', locale = 'en') {
  const state = [], deps = [], effects = [], cleanups = [], timers = new Map();
  const creates = [], events = [];
  let cursor = 0, timerId = 0;
  const i18n = i18nMock(locale);
  const provider = {
    listItems: async () => [], listInsights: async () => [],
    createItem: async payload => ({ ...saved, content: payload.content }), trackEvent: async () => {},
    ...overrides,
  };
  const exports = {};
  const filename = path.join(__dirname, '../src/features/dashboard/dashboard-page.tsx');
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(`${code}\nexports.RecentInsights = RecentInsights;`, {
    exports, window: {
      setTimeout(fn, ms) { const id = ++timerId; timers.set(id, { fn, ms }); return id; },
      clearTimeout(id) { timers.delete(id); },
    }, require(name) {
      if (name === 'react/jsx-runtime') return jsx;
      if (name === 'react') return {
        useState(initial) { const i = cursor++; if (!(i in state)) state[i] = initial;
          return [state[i], value => state[i] = typeof value === 'function' ? value(state[i]) : value]; },
        useRef(initial) { const i = cursor++; if (!(i in state)) state[i] = { current: initial }; return state[i]; },
        useEffect(fn, values) { const i = cursor++; if (!deps[i] || values.some((value, j) => value !== deps[i][j])) {
          effects.push(fn); deps[i] = values;
        } },
      };
      if (name === 'next/link') return { default: 'a' };
      if (name === '@/i18n/provider') return i18n;
      if (name === '@/i18n/translate') return { relativeTime: () => 'Just now' };
      if (name === '@/components/icons') return { Icon: 'icon', itemIcon: { note: 'note', url: 'link' } };
      if (name === '@/components/item-type') return { ItemType: 'item-type' };
      if (name === '@/components/workspace-context') return { useWorkspace: () => ({ openCapture() {} }) };
      if (name === '@/components/ui-states') return { LoadingState: 'loading',
        ErrorState: function ErrorState({ message }) {
          return jsx.jsx('div', { role: 'alert', children: i18n.useI18n().message(message) });
        } };
      if (name === '@/lib/data') return { dataProviderMode: 'api', dataErrorMessage: (_, fallback) => fallback,
        dataProvider: { ...provider,
          createItem(payload) { creates.push(payload); return provider.createItem(payload); },
          trackEvent(event) { events.push(event); return provider.trackEvent(event); },
        } };
      throw Error(name);
    },
  });
  function render() { cursor = 0; return exports[component](); }
  function effectsNow() { for (const effect of effects.splice(0)) { const cleanup = effect(); if (cleanup) cleanups.push(cleanup); } }
  return {
    creates, events, state, render,
    textarea: () => nodes(render()).find(node => node.type === 'textarea'),
    button: label => nodes(render()).find(node => node.type === 'button' && text(node) === label),
    edit(value) { this.textarea().props.onChange({ target: { value } }); },
    async ready() { render(); effectsNow();
      for (const [id, timer] of [...timers]) if (timer.ms === 0) { timers.delete(id); timer.fn(); }
      await settle(); },
    dispose() { for (const cleanup of cleanups.splice(0)) cleanup(); },
  };
}

test('Capture guards repeated click and keyboard submissions before a rerender and shows pending state', async () => {
  let resolve;
  const app = harness({ createItem: () => new Promise(done => { resolve = done; }) });
  await app.ready(); app.edit('First draft');
  const button = app.button('Capture'), input = app.textarea();
  button.props.onClick(); button.props.onClick();
  let prevented = 0;
  for (const modifier of ['metaKey', 'ctrlKey']) input.props.onKeyDown({ [modifier]: true,
    key: 'Enter', preventDefault() { prevented++; } });
  assert.equal(app.creates.length, 1); assert.equal(prevented, 2);
  assert.equal(app.button('Saving…').props.disabled, true);
  resolve(saved); await settle();
  assert.equal(app.textarea().props.value, ''); assert.equal(app.button('Capture').props.disabled, true);
  assert.deepEqual(app.events.map(event => event.eventType), ['capture_started', 'capture_submitted']);
  assert.equal(app.events[1].targetId, 'saved'); assert.equal(app.events[1].metadata.sourceType, 'note');
  app.dispose();
});

test('a failed save preserves the draft, releases the guard and supports a real retry', async () => {
  let failed = true;
  const app = harness({ createItem: async () => { if (failed) throw Error('offline'); return saved; } });
  await app.ready(); app.edit('First draft'); app.button('Capture').props.onClick(); await settle();
  assert.equal(app.textarea().props.value, 'First draft');
  assert.equal(app.button('Capture').props.disabled, false);
  assert.match(text(app.render()), /Capture failed/);
  failed = false; app.button('Capture').props.onClick(); await settle();
  assert.equal(app.creates.length, 2); assert.equal(app.textarea().props.value, ''); app.dispose();
});

test('stalled or failed telemetry does not block saving or misreport a successful capture', async () => {
  const app = harness({ trackEvent: event => event.eventType === 'capture_started'
    ? new Promise(() => {}) : Promise.reject(Error('telemetry unavailable')) });
  await app.ready(); app.edit('First draft'); app.button('Capture').props.onClick();
  assert.equal(app.creates.length, 1); await settle();
  assert.equal(app.textarea().props.value, ''); assert.doesNotMatch(text(app.render()), /Capture failed/);
  assert.equal(app.events.length, 2); app.dispose();
});

test('saving the submitted note never clears a newer draft or a mode switch', async () => {
  for (const switchMode of [false, true]) {
    let resolve;
    const app = harness({ createItem: () => new Promise(done => { resolve = done; }) });
    await app.ready(); app.edit('First draft'); app.button('Capture').props.onClick();
    if (switchMode) app.button('Paste URL').props.onClick();
    app.edit(switchMode ? 'https://example.test/new' : 'New draft'); resolve(saved); await settle();
    assert.equal(app.textarea().props.value, switchMode ? 'https://example.test/new' : 'New draft');
    assert.equal(app.creates[0].type, 'note'); assert.equal(app.creates[0].content, 'First draft');
    assert.equal(app.button('Capture').props.disabled, false); app.dispose();
  }
});

test('a failed refresh after successful creation retains the saved item and retries only the read', async () => {
  let reads = 0;
  const app = harness({ listItems: async () => {
    reads++; if (reads === 2) throw Error('refresh failed'); return reads > 2 ? [saved] : [];
  } });
  await app.ready(); app.edit('First draft'); app.button('Capture').props.onClick(); await settle();
  assert.equal(app.creates.length, 1); assert.equal(app.textarea().props.value, '');
  assert.match(text(app.render()), /Saved first draft/);
  const alerts = nodes(app.render()).filter(node => node.props?.role === 'alert');
  assert.equal(alerts.length, 1); assert.match(text(alerts[0]), /recent items could not be loaded/);
  assert.doesNotMatch(text(alerts[0]), /Capture failed/);
  app.button('Try again').props.onClick(); await settle();
  assert.equal(reads, 3); assert.equal(app.creates.length, 1);
  assert.equal(nodes(app.render()).filter(node => node.props?.role === 'alert').length, 0); app.dispose();
});

test('a late initial list read cannot erase an item confirmed by a newer capture', async () => {
  let firstRead;
  const app = harness({ listItems: () => new Promise(done => { firstRead ??= done; }) });
  await app.ready(); app.edit('First draft'); app.button('Capture').props.onClick(); await settle();
  firstRead([]); await settle();
  assert.match(text(app.render()), /Saved first draft/); app.dispose();
});

test('Recent Flares handles rejected reads with localized recoverable errors and retries to real content', async () => {
  for (const locale of ['en', 'es']) {
    let reads = 0;
    const app = harness({ listInsights: async () => { if (++reads === 1) throw Error('offline'); return [insight]; } }, 'RecentInsights', locale);
    await app.ready();
    const alert = nodes(app.render()).find(node => node.props?.role === 'alert');
    assert.ok(alert); assert.match(text(alert), locale === 'en' ? /Recent Flares could not be loaded/ : /No se pudieron cargar los Flares recientes/);
    app.button(locale === 'en' ? 'Try again' : 'Intentar de nuevo').props.onClick(); await settle();
    assert.equal(reads, 2); assert.equal(nodes(app.render()).filter(node => node.props?.role === 'alert').length, 0);
    assert.match(text(app.render()), /Real insight/); app.dispose();
  }
});

test('Recent Flares suppresses late success and rejection after cleanup', async () => {
  for (const reject of [false, true]) {
    let finish;
    const app = harness({ listInsights: () => new Promise((resolve, fail) => { finish = reject ? fail : resolve; }) }, 'RecentInsights');
    await app.ready(); app.dispose(); const snapshot = JSON.stringify(app.state);
    finish(reject ? Error('late failure') : [insight]); await settle();
    assert.equal(JSON.stringify(app.state), snapshot);
  }
});
