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
  const state = [], refs = [], calls = [], deadlines = new Map();
  let deadlineId = 0;
  const request = {};
  const requestCode = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../../lib/data/import-request.ts'), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  vm.runInNewContext(requestCode, { exports: request, AbortController, setTimeout(fn, ms) { deadlines.set(++deadlineId, {fn, ms}); return deadlineId; }, clearTimeout(id) { deadlines.delete(id); } });
  const data = {
    async getAnalysisSchedule(signal) { calls.push(['schedule', signal]); return schedule; },
    async getDailyAnalysisStatus(signal) { calls.push(['status', signal]); return daily; },
    async getAnalysisRun(id, signal) { calls.push(['run', signal]); return { id, status: 'completed', stage: 'completed', selectedChunkCount: 1, flareIds: ['flare-one'], error: null }; },
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
    if (name === '@/lib/data/import-request') return request;
    if (name === '@/lib/data') return { dataProvider: data };
    if (name === '@/components/workspace-context') return { useWorkspace: () => ({ refresh() { refreshed++; } }) };
    if (name === '@/lib/team-context') return { projectHref: url => url };
    if (name === 'next/link') return { default: 'a' };
    if (name === 'next/navigation') return {};
    if (name === '@/components/icons') return { Icon: 'icon' };
    if (name === './view-analytics') return {};
    throw Error('Unexpected import ' + name);
  } });
  const render = () => { cursor = 0; const tree = exports.ScheduledAnalysisStatus(); mounted = true; return tree; };
  return { render, calls, refreshes: () => refreshed, flush: () => new Promise(resolve => setImmediate(resolve)), poll: async () => { assert.ok(tick); tick.fn(); await new Promise(resolve => setImmediate(resolve)); }, dispose() { cleanup?.(); }, delay: () => tick?.ms, expireResultRead() { assert.equal(deadlines.size,1); const deadline=[...deadlines.values()][0]; assert.equal(deadline.ms,15000); deadline.fn(); }, deadlines: () => deadlines.size };
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


const completed = { ...daily, state: 'completed', runId: 'finished-run' };
const emptyRun = { id: 'finished-run', status: 'completed', stage: 'completed', selectedChunkCount: 2, flareIds: [], error: null };
for (const locale of ['en', 'es']) test(`${locale}: confirmed completed-empty run has a visible, nonblocking result notice and never calls Analyze`, async () => {
  const app = setup({ async getDailyAnalysisStatus() { return completed; }, async getAnalysisRun() { return emptyRun; }, listInsights() { assert.fail('Overall feed count cannot classify a run'); } }, locale);
  app.render(); await app.flush(); const tree = app.render();
  const notice = nodes(tree).find(n => n.props?.className === 'card analysis-result-notice');
  assert.ok(notice); assert.equal(notice.props.role, 'status'); assert.equal(notice.props['aria-live'], 'polite');
  assert.match(text(notice), locale === 'en' ? /No new Flares found.*Analysis completed.*saved in Vault/ : /No se encontraron nuevos Flares.*Análisis completado.*guardadas en Vault/);
  assert.doesNotMatch(text(notice), /useless|no useful information|error|failed/i);
  assert.equal(app.refreshes(), 1); assert.equal(app.delay(), 60000); assert.equal(app.deadlines(),0); app.dispose();
});

for (const count of [1,2]) test(`completed run with ${count} new Flares shows its actual result count without a zero-result notice`, async () => {
  const app = setup({ async getDailyAnalysisStatus() { return completed; }, async getAnalysisRun() { return {...emptyRun,flareIds:['one','two'].slice(0,count)}; } });
  app.render(); await app.flush(); const tree=app.render();assert.match(text(tree),new RegExp(`Latest analysis completed: ${count} new Flare${count===1?'':'s'}`));
  assert.ok(!nodes(tree).some(n=>n.props?.className==='card analysis-result-notice'));app.dispose();
});

for(const state of ['scheduled','refreshing','processing','failed','consumed']) test(`${state} is never presented as a completed empty result`, async()=>{
 const app=setup({async getDailyAnalysisStatus(){return {...daily,state,reason:state==='failed'?'no_eligible_context':null};},getAnalysisRun(){assert.fail('Only a completed run can be read as a result');}});
 app.render();await app.flush();const tree=app.render();assert.ok(!nodes(tree).some(n=>n.props?.className==='card analysis-result-notice'));
 if(state==='failed')assert.match(text(tree),/No ready context was available/);app.dispose();
});

for(const run of [null,{...emptyRun,id:'other-run'},{...emptyRun,status:'processing',stage:'flare_generation'}]) test('unavailable or mismatched completed receipt is not guessed as zero Flares',async()=>{
 const app=setup({async getDailyAnalysisStatus(){return completed;},async getAnalysisRun(){if(!run)throw Error('offline');return run;}});
 app.render();await app.flush();const tree=app.render();assert.match(text(tree),/result is unavailable/);assert.ok(!nodes(tree).some(n=>n.props?.className==='card analysis-result-notice'));app.dispose();
});

test('a previous empty notice clears when the next cycle is processing or status becomes unavailable',async()=>{
 let state='completed',offline=false;
 const app=setup({async getDailyAnalysisStatus(){if(offline)throw Error('offline');return {...completed,state};},async getAnalysisRun(){return emptyRun;}});
 app.render();await app.flush();assert.match(text(app.render()),/No new Flares found/);
 state='processing';await app.poll();assert.doesNotMatch(text(app.render()),/No new Flares found/);assert.match(text(app.render()),/Analysis is running/);
 state='completed';await app.poll();assert.match(text(app.render()),/No new Flares found/);offline=true;await app.poll();assert.doesNotMatch(text(app.render()),/No new Flares found/);assert.match(text(app.render()),/status is unavailable/);app.dispose();
});

test('completed result lookup is bounded even when transport ignores abort, and late zero result is ignored',async()=>{
 let finish;const app=setup({async getDailyAnalysisStatus(){return completed;},getAnalysisRun(_id,signal){app.calls.push(['run',signal]);return new Promise(resolve=>finish=resolve);}});
 app.render();await app.flush();app.expireResultRead();await app.flush();assert.match(text(app.render()),/result is unavailable/);assert.ok(app.calls.find(c=>c[0]==='run')[1].aborted);
 finish(emptyRun);await app.flush();assert.doesNotMatch(text(app.render()),/No new Flares found/);app.dispose();
});

test('unmount during result lookup aborts the request and prevents late notice, refresh or poll',async()=>{
 let finish;const app=setup({async getDailyAnalysisStatus(){return completed;},getAnalysisRun(_id,signal){app.calls.push(['run',signal]);return new Promise(resolve=>finish=resolve);}});
 app.render();await app.flush();app.dispose();assert.equal(app.deadlines(),0);assert.ok(app.calls.every(c=>c[1].aborted));
 finish(emptyRun);await app.flush();assert.doesNotMatch(text(app.render()),/No new Flares found/);assert.equal(app.refreshes(),0);assert.equal(app.delay(),undefined);
});
