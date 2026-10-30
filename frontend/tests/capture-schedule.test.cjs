const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const { i18nMock } = require('./i18n-utils.cjs');

const jsx = { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }) };
const nodes = n => !n || typeof n !== 'object' ? [] : Array.isArray(n) ? n.flatMap(nodes) : [n, ...nodes(n.props?.children)];
const text = n => typeof n === 'string' ? n : Array.isArray(n) ? n.map(text).join(' ') : n && typeof n === 'object' ? text(n.props?.children) : '';
const flush = () => new Promise(resolve => setImmediate(resolve));
const schedule = { enabled: true, nextRunAt: '2026-10-30T19:00:00Z', timezone: 'America/Los_Angeles' };
const source = relative => ts.transpileModule(fs.readFileSync(path.join(__dirname, '../src', relative), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
}).outputText;

function setup({ provider = {}, locale = 'en', component = 'CaptureSchedule', project = null } = {}) {
  const slots = [], effects = [], timers = new Map(), calls = [];
  let cursor = 0, timerId = 0, writes = 0, dismissed = 0;
  const document = { activeElement: null };
  const timer = (fn, ms) => { timers.set(++timerId, { fn, ms }); return timerId; };
  const clear = id => timers.delete(id);
  const window = { location: { search: project ? `?project=${encodeURIComponent(project)}` : '' }, setTimeout: timer, clearTimeout: clear };
  const pure = file => {
    const exports = {};
    vm.runInNewContext(source(file), { exports, URLSearchParams, window, AbortController, setTimeout: timer, clearTimeout: clear });
    return exports;
  };
  const request = pure('lib/data/import-request.ts'), context = pure('lib/team-context.ts');
  const changed = (a, b) => !a || a.length !== b.length || b.some((v, i) => v !== a[i]);
  const react = {
    useState(initial) { const i = cursor++; if (!slots[i]) slots[i] = { value: initial };
      return [slots[i].value, value => { writes++; slots[i].value = typeof value === 'function' ? value(slots[i].value) : value; }]; },
    useRef(initial) { const i = cursor++; return (slots[i] ??= { current: initial }); },
    useCallback(fn, deps) { const i = cursor++; if (changed(slots[i]?.deps, deps)) slots[i] = { value: fn, deps }; return slots[i].value; },
    useEffect(fn, deps) { const i = cursor++; if (changed(slots[i]?.deps, deps)) {
      const before = slots[i]; slots[i] = { deps };
      effects.push(() => { before?.cleanup?.(); slots[i].cleanup = fn(); });
    } },
  };
  const api = {
    async getAnalysisSchedule(signal) { calls.push(signal); return schedule; },
    startAnalysis() { assert.fail('Saving must not start analysis'); },
    updateAnalysisSchedule() { assert.fail('Saving must not enable the schedule'); },
    ...provider,
  };
  const exports = {};
  vm.runInNewContext(source('features/capture/capture-schedule.tsx'), {
    exports, Intl, Date, AbortController, window, document,
    require(name) {
      if (name === 'react/jsx-runtime') return jsx;
      if (name === 'react') return react;
      if (name === '@/i18n/provider') return i18nMock(locale);
      if (name === '@/components/icons') return { Icon: 'icon' };
      if (name === 'next/link') return { default: 'a' };
      if (name === '@/lib/data') return { dataProvider: api };
      if (name === '@/lib/data/import-request') return request;
      if (name === '@/lib/team-context') return context;
      throw Error(name);
    },
  });
  const onDismiss = () => { dismissed++; };
  const props = { itemId: 'note & another', onDismiss, onNavigate: onDismiss };
  return {
    render() { cursor = 0; return exports[component](props); },
    async effects() { for (const effect of effects.splice(0)) effect(); await flush(); },
    dispose() { for (const slot of slots) slot?.cleanup?.(); },
    expire(ms) { const found = [...timers].find(([, t]) => t.ms === ms); assert.ok(found, `Timer ${ms}`); timers.delete(found[0]); found[1].fn(); },
    calls, timers, document, writes: () => writes, dismissed: () => dismissed,
  };
}

test('initial feedback does not invent an off/on state while checking the schedule', () => {
  const h = setup(); const tree = h.render();
  assert.match(text(tree), /Checking insight schedule/);
  assert.doesNotMatch(text(tree), /are off|Next scheduled insight/);
  assert.equal(nodes(tree).find(n => n.type === 'a').props.href, '/settings#daily-insight');
  h.dispose();
});

for (const locale of ['en', 'es']) test(`off schedule gives a project-bound next step (${locale})`, async () => {
  const h = setup({ locale, project: 'team-one', provider: { async getAnalysisSchedule() { return { ...schedule, enabled: false, nextRunAt: null }; } } });
  h.render(); await h.effects(); const tree = h.render();
  assert.match(text(tree), locale === 'en' ? /are off/ : /están desactivados/);
  const link = nodes(tree).find(n => n.type === 'a');
  assert.equal(link.props.href, '/settings?project=team-one#daily-insight');
  assert.match(text(link), locale === 'en' ? /Set insight time/ : /Elegir hora/);
  assert.equal(nodes(tree).filter(n => n.type === 'button').length, 0);
  link.props.onClick(); assert.equal(h.dismissed(), 1); h.dispose();
});

for (const locale of ['en', 'es']) test(`next run is formatted in the actual project timezone (${locale})`, async () => {
  const h = setup({ locale }); h.render(); await h.effects(); const tree = h.render();
  const date = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short', timeZone: schedule.timezone }).format(new Date(schedule.nextRunAt));
  assert.ok(text(tree).includes(date)); assert.ok(text(tree).includes(schedule.timezone));
  assert.doesNotMatch(text(tree), /are off|Set insight time/); assert.equal(h.calls.length, 1);
  h.dispose(); assert.equal(h.timers.size, 0);
});

test('enabled schedule without a known date never manufactures a date', async () => {
  const h = setup({ provider: { async getAnalysisSchedule() { return { ...schedule, nextRunAt: null }; } } });
  h.render(); await h.effects(); assert.match(text(h.render()), /schedule is on/);
  assert.doesNotMatch(text(h.render()), /Next scheduled insight|are off/); h.dispose();
});

for (const prepared of [true, false]) test(`a recently saved note is not promised to an already prepared run (${prepared})`, async () => {
  const h = setup({ provider: { async getAnalysisSchedule() {
    return { ...schedule, nextRefreshAt: new Date(Date.now() + (prepared ? -60_000 : 60_000)).toISOString() };
  } } });
  h.render(); await h.effects(); const copy = text(h.render());
  if (prepared) assert.match(copy, /after preparation.*following scheduled run/);
  else assert.doesNotMatch(copy, /after preparation/);
  h.dispose();
});

for (const patch of [{ nextRunAt: 'bad date' }, { timezone: 'not-a-timezone' }]) test('invalid date or timezone degrades to honest unavailable status', async () => {
  const h = setup({ provider: { async getAnalysisSchedule() { return { ...schedule, ...patch }; } } });
  h.render(); await h.effects(); assert.match(text(h.render()), /content is saved.*unavailable/);
  assert.doesNotMatch(text(h.render()), /Next scheduled insight|are off/); h.dispose();
});

test('read failure preserves saved success and a recovery link', async () => {
  const h = setup({ provider: { async getAnalysisSchedule() { throw Error('offline'); } } });
  h.render(); await h.effects(); const tree = h.render();
  assert.match(text(tree), /content is saved.*unavailable/);
  assert.doesNotMatch(text(tree), /save failed|are off|Next scheduled insight/i);
  assert.ok(nodes(tree).some(n => n.type === 'a')); h.dispose();
});

test('a transport ignoring abort still times out, and late success cannot replace the fallback', async () => {
  let finish;
  const h = setup({ provider: { getAnalysisSchedule() { return new Promise(resolve => { finish = resolve; }); } } });
  h.render(); await h.effects(); h.expire(4000); await flush();
  assert.match(text(h.render()), /unavailable/);
  finish(schedule); await flush(); assert.match(text(h.render()), /unavailable/);
  assert.equal(h.timers.size, 0); h.dispose();
});

test('unmount prevents even an ignored-abort result from updating state', async () => {
  let finish, signal;
  const h = setup({ provider: { getAnalysisSchedule(value) { signal = value; return new Promise(resolve => { finish = resolve; }); } } });
  h.render(); await h.effects(); const before = h.writes(); h.dispose();
  assert.equal(signal.aborted, true); finish(schedule); await flush();
  assert.equal(h.writes(), before); assert.equal(h.timers.size, 0);
});

test('unmount before the deferred read does not issue a request', async () => {
  const h = setup(); h.render(); const pending = h.effects(); h.dispose(); await pending;
  assert.equal(h.calls.length, 0);
});

test('confirmation is dismissible, uses an encoded item link in the selected project, and releases its timer', async () => {
  const h = setup({ component: 'CaptureConfirmation', project: 'team-one' });
  let tree = h.render(); await h.effects();
  assert.equal(tree.props.role, 'status'); assert.equal(tree.props['aria-live'], 'polite');
  const link = nodes(tree).find(n => n.type === 'a');
  assert.equal(link.props.href, '/vault?item=note%20%26%20another&project=team-one');
  assert.equal(h.timers.size, 1); link.props.onClick(); assert.equal(h.dismissed(), 1);
  h.dispose(); assert.equal(h.timers.size, 0);
});

test('actionable feedback dismisses after eight seconds and unmount cancels pending expiry', async () => {
  const h = setup({ component: 'CaptureConfirmation' }); h.render(); await h.effects();
  h.expire(8000); assert.equal(h.dismissed(), 1); h.dispose();
  const another = setup({ component: 'CaptureConfirmation' }); another.render(); await another.effects();
  another.dispose(); assert.equal(another.timers.size, 0); assert.equal(another.dismissed(), 0);
});

test('keyboard focus and pointer hover independently keep actions available', async () => {
  const h = setup({ component: 'CaptureConfirmation' }); const tree = h.render(); await h.effects();
  const inside = {}, outside = {}, target = { contains: node => node === inside };
  tree.props.onMouseEnter(); assert.equal(h.timers.size, 0);
  tree.props.onFocusCapture(); h.document.activeElement = inside;
  tree.props.onMouseLeave({ currentTarget: target }); assert.equal(h.timers.size, 0);
  tree.props.onBlurCapture({ currentTarget: target, relatedTarget: outside }); assert.equal(h.timers.size, 1);
  tree.props.onMouseEnter(); assert.equal(h.timers.size, 0);
  tree.props.onBlurCapture({ currentTarget: target, relatedTarget: outside }); assert.equal(h.timers.size, 0);
  h.document.activeElement = outside; tree.props.onMouseLeave({ currentTarget: target }); assert.equal(h.timers.size, 1);
  h.dispose();
});
