const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const { i18nMock } = require('../../../tests/i18n-utils.cjs');
const source = fs.readFileSync(path.join(__dirname, 'insights-page.tsx'), 'utf8');
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }).outputText;
const schedule = { enabled: true, timezone: 'UTC', nextRunAt: '2026-10-13T09:00:00Z' };
const daily = { state: 'scheduled', mode: 'scheduled', runId: null };
function nodes(n) { return !n || typeof n !== 'object' ? [] : Array.isArray(n) ? n.flatMap(nodes) : [n, ...nodes(n.props?.children)]; }
function text(n) { return typeof n === 'string' || typeof n === 'number' ? String(n) : Array.isArray(n) ? n.map(text).join(' ') : n ? text(n.props?.children) : ''; }
function setup(provider = {}, locale = 'en') {
  let cursor = 0, mounted = false, cleanup, tick, refreshed = 0;
  const state = [], refs = [], calls = [];
  const data = {
    async getAnalysisSchedule(signal) { calls.push(['schedule', signal]); return schedule; },
    async getDailyAnalysisStatus(signal) { calls.push(['status', signal]); return daily; },
    startAnalysis() { assert.fail('No manual start is permitted'); }, ...provider,
  };
  const exports = {};
  const jsx = (type, props) => ({ type, props });
  vm.runInNewContext(code, { exports, Intl, AbortController, window: { setTimeout(fn, ms) { tick = { fn, ms }; return 1; }, clearTimeout() { tick = null; } }, require(name) {
    if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx };
    if (name === 'react') return {
      useState(initial) { const i = cursor++; if (!(i in state)) state[i] = initial; return [state[i], next => state[i] = typeof next === 'function' ? next(state[i]) : next]; },
      useRef(initial) { const i = cursor++; return refs[i] ??= { current: initial }; },
      useEffect(fn) { if (!mounted) cleanup = fn(); }, useCallback(fn) { return fn; },
    };
    if (name === '@/i18n/provider') return i18nMock(locale);
    if (name === '@/lib/data') return { dataProvider: data };
    if (name === '@/components/workspace-context') return { useWorkspace: () => ({ refresh() { refreshed++; } }) };
    if (name === '@/lib/team-context') return { projectHref: url => url };
    if (name === 'next/link') return { default: 'a' };
    if (name === 'next/navigation') return {};
    if (name === '@/components/icons') return {};
    if (name === './view-analytics') return {};
    throw Error('Unexpected import ' + name);
  } });
  const render = () => { cursor = 0; const tree = exports.ScheduledAnalysisStatus(); mounted = true; return tree; };
  return { render, calls, refreshes: () => refreshed, flush: () => new Promise(resolve => setImmediate(resolve)), poll: async () => { assert.ok(tick); tick.fn(); await new Promise(resolve => setImmediate(resolve)); }, dispose() { cleanup?.(); }, delay: () => tick?.ms };
}

test('Flares schedule surface has no manual action and links to existing Settings', async () => {
  const app = setup(); app.render(); await app.flush(); const tree = app.render();
  assert.match(text(tree), /Next scheduled insight/);
  assert.ok(nodes(tree).some(n => n.type === 'a' && n.props.href === '/settings'));
  assert.equal(nodes(tree).filter(n => n.type === 'button').length, 0);
  assert.deepEqual(app.calls.map(c => c[0]), ['schedule', 'status']);
  assert.doesNotMatch(source, /<AnalyzeAction\b/);
  app.dispose();
});

for (const status of ['refreshing', 'ready', 'queued', 'processing']) test('scheduled ' + status + ' shows progress with bounded automatic status checks', async () => {
  const app = setup({ async getDailyAnalysisStatus() { return { ...daily, state: status }; } });
  app.render(); await app.flush(); assert.doesNotMatch(text(app.render()), /Analyze today|Scheduled analysis is off/);
  assert.equal(app.delay(), 15000); app.dispose();
});

test('disabled schedule has an honest enable-in-settings path, including Spanish', async () => {
  for (const locale of ['en', 'es']) {
    const app = setup({ async getAnalysisSchedule() { return { ...schedule, enabled: false, nextRunAt: null }; } }, locale);
    app.render(); await app.flush(); const copy = text(app.render());
    assert.match(copy, locale === 'en' ? /Scheduled analysis is off/ : /está desactivado/);
    assert.doesNotMatch(copy, /Analyze today|Next scheduled insight/); app.dispose();
  }
});

test('outage overrides stale enabled/off state without inventing a schedule', async () => {
  let fail = false;
  const app = setup({ async getAnalysisSchedule() { if (fail) throw Error('offline'); return schedule; } });
  app.render(); await app.flush(); fail = true; await app.poll();
  assert.match(text(app.render()), /status is unavailable/);
  assert.doesNotMatch(text(app.render()), /Next scheduled insight|is off/); app.dispose();
});

test('completed runs refresh Flares once per run and never start a run', async () => {
  let id = 'done-1';
  const app = setup({ async getDailyAnalysisStatus() { return { ...daily, state: 'completed', runId: id }; } });
  app.render(); await app.flush(); assert.equal(app.refreshes(), 1);
  await app.poll(); assert.equal(app.refreshes(), 1);
  id = 'done-2'; await app.poll(); assert.equal(app.refreshes(), 2); app.dispose();
});

test('unmount aborts pending reads and ignores late completion without refresh or new poll', async () => {
  let resolve;
  const app = setup({ getDailyAnalysisStatus(signal) { app.calls.push(['pending', signal]); return new Promise(r => resolve = r); } });
  app.render(); app.dispose(); assert.ok(app.calls.every(c => c[1].aborted));
  resolve({ ...daily, state: 'completed', runId: 'late' }); await app.flush();
  assert.equal(app.refreshes(), 0); assert.equal(app.delay(), undefined);
});
